"""
咖啡店经营数据灌入脚本

作用：给本地 SQLite 灌入咖啡店的示例经营数据（4 张表）。
运行方式（在 backend 目录下）：
    .venv/Scripts/python.exe -m app.models.seed_cafe

数据设计（让 Text2SQL 能跑出有分析价值的结果）：
- 饮品：咖啡/茶饮/甜品三类，含 price 和 cost（能算毛利）
- 会员：8 位，含正常 + 异常数据（空手机号）
- 订单：约 40 条，覆盖「过去 30 天」、带 weather（晴/雨/阴）、
        含不同时段（早/午/晚高峰）
- 明细：每个订单 1-3 个商品，带数量和单价

关键：订单的 weather 字段是「天气 × 销量」关联分析（备货预测）的基础。
这里先内置一份「天气快照」（做法 A 的过渡：第 2 步会用真实天气 API 回填）。
"""
import random
from datetime import datetime, timedelta

from app.models.base import Base
from app.models.cafe import Member, Product, Order, OrderItem
from app.models.database import engine, SessionLocal


def _weather_product_weight(product: Product, weather: str) -> float:
    """模型演示用的可解释天气偏好权重。

    这不是因果推断，只是让示例数据具备可观察的业务结构，
    避免天气与销量完全随机后仍对外宣称“天气洞察”。
    """
    hot = {"热拿铁", "热可可", "卡布奇诺"}
    cold = {"冰美式", "冰拿铁", "茉莉绿茶"}

    if weather == "雨":
        if product.name in hot:
            return 5.0
        if product.name in cold:
            return 0.4
    elif weather == "晴":
        if product.name in cold:
            return 5.0
        if product.name in hot:
            return 0.8
    return 1.5


def seed_cafe(reference_time: datetime | None = None):
    # 建表（确保咖啡店表存在）
    Base.metadata.create_all(bind=engine)

    db = SessionLocal()
    try:
        # 幂等：已有数据则跳过
        if db.query(Product).first():
            print("[INFO] 咖啡店数据已存在，跳过灌入")
            return

        # ---- 1. 饮品 ----
        products = [
            Product(name="冰美式", category="咖啡", price=22.0, cost=6.0),
            Product(name="热拿铁", category="咖啡", price=28.0, cost=9.0),
            Product(name="卡布奇诺", category="咖啡", price=26.0, cost=8.0),
            Product(name="冰拿铁", category="咖啡", price=28.0, cost=9.0),
            Product(name="茉莉绿茶", category="茶饮", price=18.0, cost=5.0),
            Product(name="乌龙茶", category="茶饮", price=20.0, cost=6.0),
            Product(name="热可可", category="甜品", price=24.0, cost=10.0),
            Product(name="提拉米苏", category="甜品", price=32.0, cost=14.0),
        ]
        db.add_all(products)
        db.flush()  # 让饮品先拿到 id

        # ---- 2. 会员 ----
        members = [
            Member(name="陈晓", phone="13800000001", join_date=datetime(2026, 1, 15, 10, 0)),
            Member(name="林悦", phone="13800000002", join_date=datetime(2026, 2, 20, 14, 30)),
            Member(name="王强", phone="13800000003", join_date=datetime(2026, 3, 5, 9, 0)),
            Member(name="赵敏", phone="13800000004", join_date=datetime(2026, 3, 18, 16, 0)),
            Member(name="孙磊", phone="13800000005", join_date=datetime(2026, 4, 2, 11, 0)),
            Member(name="周婷", phone="13800000006", join_date=datetime(2026, 5, 11, 8, 30)),
            Member(name="吴昊", phone="13800000007", join_date=datetime(2026, 6, 1, 13, 0)),
            # 异常数据：空手机号（用于体现「数据清洗」意识）
            Member(name="郑雪", phone=None, join_date=datetime(2026, 7, 9, 17, 30)),
        ]
        db.add_all(members)
        db.flush()

        # ---- 3. 订单 + 明细 ----
        # 生成「过去 30 天」的订单，天气按日期规律分布（晴/雨/阴交替）
        # 固定种子保证数量可复现；参考时间默认取当前时间，
        # 避免演示数据随着日历推移逐渐变成“几个月前”。
        rng = random.Random(42)

        today = (reference_time or datetime.now()).replace(
            hour=12,
            minute=0,
            second=0,
            microsecond=0,
        )
        product_list = products
        order_count = 0

        for day_offset in range(30, 0, -1):
            day = today - timedelta(days=day_offset)
            # 每天 1-3 单
            n_orders = rng.randint(1, 3)
            for _ in range(n_orders):
                order_count += 1
                hour = rng.choice([8, 9, 10, 12, 13, 14, 16, 17, 18, 19])
                minute = rng.choice([0, 15, 30, 45])
                order_time = day.replace(hour=hour, minute=minute)

                # 天气：模拟真实分布（约 50% 晴、30% 阴、20% 雨）
                weather = rng.choices(["晴", "阴", "雨"], weights=[50, 30, 20])[0]

                # 会员：70% 概率是会员
                member = rng.choice(members) if rng.random() < 0.7 else None

                # 订单里的商品（1-3 种），按天气调整偏好权重。
                # 雨天的热饮和晴天的冰饮更容易被选中，使演示数据
                # 真正具有可供 Text2SQL 分析的结构。
                n_items = min(rng.randint(1, 3), len(product_list))
                available = list(product_list)
                chosen = []
                for _ in range(n_items):
                    weights = [
                        _weather_product_weight(product, weather)
                        for product in available
                    ]
                    product = rng.choices(available, weights=weights, k=1)[0]
                    chosen.append(product)
                    available.remove(product)

                total = 0.0
                order = Order(
                    member_id=member.id if member else None,
                    order_time=order_time,
                    total_amount=0.0,  # 先占位，下面累加
                    weather=weather,
                )
                db.add(order)
                db.flush()

                for p in chosen:
                    qty = rng.randint(1, 3)
                    item = OrderItem(
                        order_id=order.id,
                        product_id=p.id,
                        quantity=qty,
                        price=p.price,
                    )
                    db.add(item)
                    total += p.price * qty

                order.total_amount = round(total, 2)

        db.commit()
        print(f"[OK] 咖啡店数据已灌入：{len(products)} 款饮品，{len(members)} 位会员，{order_count} 笔订单")

        # 统计天气分布，帮助理解「天气 × 销量」规律
        from sqlalchemy import func
        weather_dist = (
            db.query(Order.weather, func.count(Order.id))
            .group_by(Order.weather)
            .all()
        )
        print("   天气分布:", {w: c for w, c in weather_dist})

    finally:
        db.close()


if __name__ == "__main__":
    seed_cafe()
    print("[OK] 咖啡店数据初始化完成")
