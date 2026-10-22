"""
数据库连接管理

核心概念：
- engine（引擎）：负责与数据库建立连接，是 SQLAlchemy 的"总入口"
- SessionLocal（会话工厂）：每次操作数据库时，从它获取一个"会话"
- get_db：FastAPI 依赖，自动管理会话的打开和关闭

当前使用 SQLite（零配置，开箱即用）。
未来切换 PostgreSQL 时，只需修改这里的连接串（这正是 ADR-003 的设计）。
"""
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# 数据库连接串（SQLite 文件存在 backend 目录下）
# 注意：check_same_thread=False 是为了配合 FastAPI 的多线程/异步特性
DATABASE_URL = "sqlite:///./smart_assistant.db"

# 创建引擎
engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False},  # SQLite 特有配置
    echo=False,  # 设为 True 可打印所有 SQL 语句（调试用）
)

# 创建会话工厂
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db():
    """FastAPI 依赖：每次请求获取一个独立的数据库会话，用完自动关闭"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
