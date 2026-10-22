"""
消息持久化服务（Repository）

这是「企业级升级 · P0 · 消息持久化」的核心。

职责：把「用户提问 + AI 回答」持久化到数据库，让后端成为
「聊天记录的唯一可信写入方」（参考文档要求）。

核心设计：两段式写入（对应"断连保存 partial"）：
1. create()：进入时先存「用户提问」，answer 暂空
   —— 即使请求刚进来就断连，提问也已落库，有据可查
2. complete()：AI 回答生成后，把 answer 更新回那条记录
   —— 如果中途失败，至少 question 还在（partial）

「可选登录」语义：
- 传入 user_id → 消息绑定到该用户（能查历史）
- 传入 None → 匿名消息，不绑定用户（不落库，或落到匿名区）
  当前实现：匿名消息不持久化（因为没有归属，落库无意义），
  只有登录用户的消息才落库。这是务实的选择。
"""
from typing import Optional

from sqlalchemy.orm import Session

from app.models.user import Conversation


class MessageRepository:
    """消息持久化仓库"""

    def __init__(self, db: Session):
        self.db = db

    def create(
        self, question: str, user_id: Optional[int], session_id: Optional[str] = None
    ) -> Optional[int]:
        """进入时调用：存「用户提问」。

        返回会话 id（供后续 complete 更新用）。
        - 有 user_id（登录）：绑定到用户
        - 无 user_id 但有 session_id（匿名）：按会话落库，保证多轮记忆不断
        - 两者都无：不落库，返回 None
        """
        if user_id is None and not session_id:
            return None

        record = Conversation(
            user_id=user_id,
            session_id=session_id if user_id is None else None,
            question=question,
            answer=None,
        )
        self.db.add(record)
        self.db.commit()
        self.db.refresh(record)
        return record.id

    def complete(self, conversation_id: Optional[int], answer: str) -> None:
        """回答生成后调用：把 answer 更新回那条记录。

        如果 conversation_id 为 None（匿名且无会话），什么都不做。
        """
        if conversation_id is None:
            return

        record = (
            self.db.query(Conversation)
            .filter(Conversation.id == conversation_id)
            .first()
        )
        if record is not None:
            record.answer = answer
            self.db.commit()

    def get_recent_history(
        self,
        user_id: Optional[int],
        limit: int = 5,
        session_id: Optional[str] = None,
    ) -> list[dict]:
        """多轮记忆：捞取该用户（或匿名会话）最近 N 轮对话（滑动窗口）。

        返回按时间正序排列的对话列表，每项：
            {"question": str, "answer": str}

        关键设计（对应「多轮记忆」原理）：
        - 登录用户按 user_id 隔离；匿名用户按 session_id 隔离（各自只看自己的历史）
        - 滑动窗口：只取最近 limit 轮，避免上下文超长/噪声
        - 只取「有回答」的完整轮次（answer 非空），跳过刚插入、还没回答的记录
        """
        query = self.db.query(Conversation).filter(Conversation.answer.isnot(None))

        if user_id is not None:
            query = query.filter(Conversation.user_id == user_id)
        elif session_id:
            query = query.filter(Conversation.session_id == session_id)
        else:
            return []

        records = (
            query.order_by(Conversation.created_at.desc())
            .limit(limit)
            .all()
        )

        # 数据库按时间倒序取的，转成正序（最早的在前）
        records = list(reversed(records))
        return [
            {"question": r.question, "answer": r.answer}
            for r in records
        ]
