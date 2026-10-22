"""
消息持久化测试

这是「企业级升级 · P0 · 消息持久化」的测试。

核心验证点：
1. 登录用户的消息：create 落库（question 存、answer 空）→ complete 更新 answer
2. 匿名用户（user_id=None）：不落库（create 返回 None，complete 不做任何事）
3. 两段式写入：即使只 create 没 complete，question 也已在库里（partial 保留）

用独立的临时 SQLite（内存库），不污染真实数据库。
"""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models.base import Base
from app.models.user import User, Conversation
from app.services.message_repository import MessageRepository


@pytest.fixture
def db():
    """每个测试用独立的内存数据库，测完即弃"""
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    # 造一个测试用户
    user = User(username="testuser", hashed_password="hash")
    session.add(user)
    session.commit()
    yield session
    session.close()


class TestMessagePersistence:
    """消息持久化测试"""

    def test_create_stores_question_with_empty_answer(self, db):
        """登录用户：create 后 question 已落库，answer 为空"""
        repo = MessageRepository(db)
        conv_id = repo.create("美国疫情趋势", user_id=1)

        assert conv_id is not None
        record = db.query(Conversation).filter(Conversation.id == conv_id).first()
        assert record.question == "美国疫情趋势"
        assert record.answer is None  # 还没 complete，answer 为空

    def test_complete_updates_answer(self, db):
        """complete 后 answer 被更新"""
        repo = MessageRepository(db)
        conv_id = repo.create("美国疫情趋势", user_id=1)
        repo.complete(conv_id, "这是分析报告")

        record = db.query(Conversation).filter(Conversation.id == conv_id).first()
        assert record.answer == "这是分析报告"

    def test_anonymous_does_not_persist(self, db):
        """匿名用户（user_id=None）：不落库"""
        repo = MessageRepository(db)
        conv_id = repo.create("匿名问题", user_id=None)

        assert conv_id is None  # 返回 None，表示没落库
        # 库里应该没有这条匿名记录
        count = db.query(Conversation).count()
        assert count == 0  # 只有 create 前造的测试用户，没有 conversation

    def test_complete_with_none_id_is_noop(self, db):
        """匿名用户 complete（conv_id=None）：不做任何事，不报错"""
        repo = MessageRepository(db)
        repo.complete(None, "随便什么答案")  # 不应抛异常
        assert db.query(Conversation).count() == 0

    def test_partial_preserved_on_no_complete(self, db):
        """两段式写入：只 create 不 complete，question 仍在（partial 保留）"""
        repo = MessageRepository(db)
        conv_id = repo.create("断连前的提问", user_id=1)
        # 模拟断连：没有调用 complete

        record = db.query(Conversation).filter(Conversation.id == conv_id).first()
        assert record is not None
        assert record.question == "断连前的提问"  # question 保住了
        assert record.answer is None  # answer 为空，但记录本身没丢
