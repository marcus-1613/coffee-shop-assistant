"""
会话历史路由（资源隔离的核心演示）

这是「企业级升级 · P0 · 资源隔离」的关键接口。

它示范了企业级安全里最重要的一条原则：
  「永远不要相信前端传来的资源 ID，要在后端校验归属。」

- GET  /history           列出「当前登录用户」的所有会话（自动过滤，只查自己的）
- GET  /history/{id}      查某条会话详情（强制校验 owner == 当前用户，否则 403）

面试官最爱问的「越权漏洞」场景，就是靠这个接口兜底的：
  用户 B 手动输入 GET /history/123（123 是用户 A 的会话），
  后端不会返回 A 的数据，而是 403 拒绝——因为 owner 校验在服务端，不信任前端。
"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.deps import get_current_user
from app.models.database import get_db
from app.models.user import Conversation, User

router = APIRouter(prefix="/history", tags=["会话历史"])


@router.get("")
def list_history(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """列出当前用户的全部会话历史。

    关键：查询条件硬性带上 user_id == current_user.id，
    所以前端根本不可能拿到别人的数据——后端自动过滤。
    """
    records = (
        db.query(Conversation)
        .filter(Conversation.user_id == current_user.id)
        .order_by(Conversation.created_at.desc())
        .all()
    )
    return {
        "username": current_user.username,
        "count": len(records),
        "items": [
            {
                "id": r.id,
                "question": r.question,
                "answer": r.answer,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in records
        ],
    }


@router.get("/{conversation_id}")
def get_history_detail(
    conversation_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """查询某条会话详情。

    关键（资源隔离的命门）：先查这条会话，再校验它的 owner。
    如果 owner 不是当前用户，返回 403，而不是返回数据。
    这一步绝不能省——省了就是「越权漏洞（IDOR）」。
    """
    record = db.query(Conversation).filter(Conversation.id == conversation_id).first()

    if record is None:
        raise HTTPException(status_code=404, detail="会话不存在")

    # 资源隔离的核心：owner 校验
    if record.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="无权访问该会话")

    return {
        "id": record.id,
        "question": record.question,
        "answer": record.answer,
        "created_at": record.created_at.isoformat() if record.created_at else None,
    }
