"""
用户模型 + 会话模型（认证 & 资源隔离）

这是「企业级升级 · P0 · 用户认证与资源隔离」的产物。

核心概念（为什么有两个表）：
- User（用户表）：存「谁」——账号、密码哈希。密码绝对不能存明文。
- Conversation（会话表）：存「谁的数据」——每条会话绑定 user_id，
  这是「资源隔离」的关键：查询时必须校验 owner == 当前用户。

为什么密码要哈希而不是明文？
  如果数据库泄露，攻击者拿到的是「哈希值」而不是原始密码，
  无法直接登录。这是安全的第一道防线（业界铁律）。
"""
from datetime import datetime, timezone

from sqlalchemy import Column, Integer, String, DateTime, ForeignKey
from sqlalchemy.orm import relationship

from app.models.base import Base


def _now():
    """返回带时区的 UTC 当前时间（避免 datetime.utcnow 弃用警告）"""
    return datetime.now(timezone.utc)


class User(Base):
    """用户表 —— 存账号和密码哈希"""

    __tablename__ = "users"

    id = Column(Integer, primary_key=True, autoincrement=True)
    username = Column(String(50), nullable=False, unique=True, index=True)  # 用户名，唯一
    hashed_password = Column(String(255), nullable=False)                    # 密码哈希（绝不存明文）
    created_at = Column(DateTime, default=_now, nullable=False)              # 注册时间

    # 关系：一个用户有多条会话记录
    conversations = relationship("Conversation", back_populates="user", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<User(id={self.id}, username={self.username})>"


class Conversation(Base):
    """会话表 —— 每条记录绑定一个用户（资源隔离的关键）"""

    __tablename__ = "conversations"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)  # 归属用户（外键，可空：匿名会话无 user）
    session_id = Column(String(64), nullable=True, index=True)  # 匿名会话标识（未登录用户的多轮记忆按此隔离）
    question = Column(String(500), nullable=False)   # 用户问题
    answer = Column(String(5000), nullable=True)     # AI 回答（可能为空）
    created_at = Column(DateTime, default=_now, nullable=False)

    # 关系：一条会话属于一个用户
    user = relationship("User", back_populates="conversations")

    def __repr__(self):
        return f"<Conversation(id={self.id}, user_id={self.user_id})>"
