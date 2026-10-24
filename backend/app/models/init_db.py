"""
数据库初始化脚本

作用：建表 + 灌入咖啡店经营演示数据。
运行方式（在 backend 目录下）：
    .venv/Scripts/python.exe -m app.models.init_db

这是「阶段三 · 咖啡店经营助手」的产物：本地经营数据库初始化。
（早期版本是「医院演示数据」初始化，现已迁移到咖啡店场景。）
"""
# 导入所有模型（确保它们被 Base 登记）
from app.models.base import Base
from app.models.cafe import Member, Product, Order, OrderItem
from app.models.user import User, Conversation
from app.models.database import engine


def create_tables():
    """根据模型定义创建所有数据库表"""
    Base.metadata.create_all(bind=engine)
    print("[OK] 数据表已创建")


if __name__ == "__main__":
    create_tables()
    # 复用 seed_cafe 灌入咖啡店经营数据（幂等，已有数据则跳过）
    from app.models.seed_cafe import seed_cafe
    seed_cafe()
    print("[OK] 数据库初始化完成")
