"""Report the weather/sales structure in the synthetic demo database.

This is a data-quality check for the demo, not a demand forecast model.
Run from the backend directory:

    python -m scripts.analyze_demo_signal
"""
from collections import defaultdict

from sqlalchemy import func

from app.models.cafe import Order, OrderItem, Product
from app.models.database import SessionLocal


HOT_PRODUCTS = {"热拿铁", "热可可", "卡布奇诺"}
COLD_PRODUCTS = {"冰美式", "冰拿铁", "茉莉绿茶"}


def main() -> None:
    db = SessionLocal()
    try:
        order_counts = dict(
            db.query(Order.weather, func.count(Order.id))
            .group_by(Order.weather)
            .all()
        )
        sales = (
            db.query(Order.weather, Product.name, func.sum(OrderItem.quantity))
            .join(Order, OrderItem.order_id == Order.id)
            .join(Product, OrderItem.product_id == Product.id)
            .group_by(Order.weather, Product.name)
            .all()
        )
    finally:
        db.close()

    grouped = defaultdict(lambda: {"hot": 0, "cold": 0, "other": 0})
    for weather, product_name, quantity in sales:
        if product_name in HOT_PRODUCTS:
            grouped[weather]["hot"] += quantity
        elif product_name in COLD_PRODUCTS:
            grouped[weather]["cold"] += quantity
        else:
            grouped[weather]["other"] += quantity

    print("weather  orders  hot_units  cold_units  hot_share")
    for weather in ("晴", "阴", "雨"):
        values = grouped[weather]
        hot_cold = values["hot"] + values["cold"]
        hot_share = values["hot"] / hot_cold if hot_cold else 0
        print(
            f"{weather:<8} {order_counts.get(weather, 0):>6} "
            f"{values['hot']:>10} {values['cold']:>11} "
            f"{hot_share:>9.1%}"
        )


if __name__ == "__main__":
    main()
