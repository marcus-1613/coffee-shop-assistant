"""
咖啡店经营数据模型（ORM 层）

这是「咖啡店经营助手」的本地知识库：用 SQLAlchemy 定义咖啡店的
经营数据表，供 Text2SQL 工具查询。

四张表：
- members（会员）
- products（饮品）
- orders（订单）
- order_items（订单明细）

设计要点：
- products.cost（成本）字段让助手能算「毛利」（price - cost），
  这是体现「经营分析」价值的关键字段。
- orders.order_time 精确到时分，才能做「时段分析」（早高峰/午高峰）。
- orders.weather（天气）字段记录下单当天的天气，这是「天气 × 销量」
  关联分析（备货预测）的命脉。
"""
from sqlalchemy import Column, Integer, String, Float, DateTime, ForeignKey
from sqlalchemy.orm import relationship

from app.models.base import Base


class Member(Base):
    """会员表"""

    __tablename__ = "cafe_members"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(50), nullable=False)           # 会员姓名
    phone = Column(String(20), nullable=True)           # 手机号
    join_date = Column(DateTime, nullable=False)        # 入会时间

    orders = relationship("Order", back_populates="member")

    def __repr__(self):
        return f"<Member(id={self.id}, name={self.name})>"


class Product(Base):
    """饮品表"""

    __tablename__ = "cafe_products"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(50), nullable=False)           # 饮品名
    category = Column(String(20), nullable=False)       # 类别（咖啡/茶饮/甜品）
    price = Column(Float, nullable=False)               # 售价（元）
    cost = Column(Float, nullable=False)                # 成本（元）

    items = relationship("OrderItem", back_populates="product")

    def __repr__(self):
        return f"<Product(id={self.id}, name={self.name})>"


class Order(Base):
    """订单表"""

    __tablename__ = "cafe_orders"

    id = Column(Integer, primary_key=True, autoincrement=True)
    member_id = Column(Integer, ForeignKey("cafe_members.id"), nullable=True)  # 可为空（非会员）
    order_time = Column(DateTime, nullable=False)       # 下单时间（精确到时分）
    total_amount = Column(Float, nullable=False)        # 订单总金额
    weather = Column(String(10), nullable=True)         # 当天天气（晴/雨/阴）

    member = relationship("Member", back_populates="orders")
    items = relationship("OrderItem", back_populates="order")

    def __repr__(self):
        return f"<Order(id={self.id}, time={self.order_time})>"


class OrderItem(Base):
    """订单明细表"""

    __tablename__ = "cafe_order_items"

    id = Column(Integer, primary_key=True, autoincrement=True)
    order_id = Column(Integer, ForeignKey("cafe_orders.id"), nullable=False)
    product_id = Column(Integer, ForeignKey("cafe_products.id"), nullable=False)
    quantity = Column(Integer, nullable=False)          # 购买数量（杯）
    price = Column(Float, nullable=False)               # 单价（下单时的价格）

    order = relationship("Order", back_populates="items")
    product = relationship("Product", back_populates="items")

    def __repr__(self):
        return f"<OrderItem(id={self.id}, qty={self.quantity})>"
