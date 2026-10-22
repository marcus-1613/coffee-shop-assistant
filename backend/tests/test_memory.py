"""
多轮记忆测试

验证 MessageRepository.get_recent_history 的三个核心设计：
1. 滑动窗口：只取最近 limit 轮
2. 按用户隔离：用户 A 捞不到用户 B 的历史
3. 跳过无回答的记录（answer is None 的「partial」不参与记忆）
"""
import pytest

from app.services.message_repository import MessageRepository
from app.models.database import SessionLocal
from app.models.user import User, Conversation
from app.core.security import hash_password


@pytest.fixture
def db():
    """每个测试用独立的数据库会话，测完清空自己插入的数据（teardown）。

    关键：测试必须「自清理」，否则数据残留会污染后续测试
    （例如 users.username 唯一约束冲突，导致全量测试挂掉）。
    """
    session = SessionLocal()
    yield session
    # teardown：删除本测试插入的 conversations 和 users（用内存前缀标记的测试用户）
    session.query(Conversation).filter(
        Conversation.user_id.in_(
            session.query(User.id).filter(User.username.like("mem_%"))
        )
    ).delete(synchronize_session=False)
    session.query(User).filter(User.username.like("mem_%")).delete(
        synchronize_session=False
    )
    session.commit()
    session.close()


def _create_user(db, username):
    user = User(username=username, hashed_password=hash_password("pw"))
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _add_conversation(db, user_id, question, answer):
    rec = Conversation(user_id=user_id, question=question, answer=answer)
    db.add(rec)
    db.commit()
    db.refresh(rec)
    return rec


def test_returns_recent_turns_in_chronological_order(db):
    """多轮历史应按时间正序返回（最早的在前）。"""
    user = _create_user(db, "mem_user_1")
    _add_conversation(db, user.id, "第一问", "第一答")
    _add_conversation(db, user.id, "第二问", "第二答")
    _add_conversation(db, user.id, "第三问", "第三答")

    repo = MessageRepository(db)
    history = repo.get_recent_history(user.id, limit=5)

    questions = [h["question"] for h in history]
    assert questions == ["第一问", "第二问", "第三问"]


def test_sliding_window_keeps_only_recent(db):
    """滑动窗口：历史超过 limit 时，只保留最近 limit 轮。"""
    user = _create_user(db, "mem_user_2")
    for i in range(10):
        _add_conversation(db, user.id, f"问题{i}", f"答案{i}")

    repo = MessageRepository(db)
    history = repo.get_recent_history(user.id, limit=3)

    # 只保留最近 3 轮（问题7、8、9）
    questions = [h["question"] for h in history]
    assert questions == ["问题7", "问题8", "问题9"]


def test_history_is_isolated_by_user(db):
    """按用户隔离：用户 A 捞不到用户 B 的历史。"""
    alice = _create_user(db, "mem_alice")
    bob = _create_user(db, "mem_bob")
    _add_conversation(db, alice.id, "alice的问题", "alice的答案")
    _add_conversation(db, bob.id, "bob的问题", "bob的答案")

    repo = MessageRepository(db)
    alice_history = repo.get_recent_history(alice.id, limit=5)
    bob_history = repo.get_recent_history(bob.id, limit=5)

    alice_questions = [h["question"] for h in alice_history]
    bob_questions = [h["question"] for h in bob_history]

    assert alice_questions == ["alice的问题"]
    assert bob_questions == ["bob的问题"]


def test_skips_unanswered_partial_records(db):
    """跳过 answer 为 None 的「partial」记录（刚插入还没回答的）。"""
    user = _create_user(db, "mem_user_4")
    _add_conversation(db, user.id, "已完成的", "有回答")
    # 模拟一条「刚进入、还没生成回答」的 partial 记录
    partial = Conversation(user_id=user.id, question="没答完的", answer=None)
    db.add(partial)
    db.commit()

    repo = MessageRepository(db)
    history = repo.get_recent_history(user.id, limit=5)

    questions = [h["question"] for h in history]
    assert questions == ["已完成的"]  # 不含「没答完的」


def test_anonymous_returns_empty(db):
    """匿名用户（user_id=None）返回空历史。"""
    repo = MessageRepository(db)
    history = repo.get_recent_history(None, limit=5)
    assert history == []
