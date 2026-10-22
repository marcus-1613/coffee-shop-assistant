"""
模型基类

所有数据模型都继承这个 Base。
SQLAlchemy 通过 Base 来"登记"所有表，创建数据库时据此建表。
"""
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """所有 ORM 模型的基类"""
    pass
