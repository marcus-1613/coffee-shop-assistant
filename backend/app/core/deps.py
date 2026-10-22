"""
认证依赖（get_current_user）

这是「资源隔离」的闸门：任何需要登录的接口，只要声明
`current_user: User = Depends(get_current_user)`，FastAPI 就会：
1. 从请求头 Authorization 里取出 token
2. 校验签名、解析出用户 ID
3. 从数据库查出这个用户
4. 注入给接口使用

如果 token 缺失/无效/过期，直接返回 401（未认证）。

为什么这个设计是「资源隔离」的关键？
  因为「谁是当前用户」不是前端自己说的（那可以被伪造），
  而是服务端从签名 token 里验出来的。前端只能传 token，
  不能传「我是用户A」——身份由服务端裁决。
"""
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from app.core.security import decode_access_token
from app.models.database import get_db
from app.models.user import User

# OAuth2 密码流：从请求头 Authorization: Bearer <token> 里取 token
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login", auto_error=False)


def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
) -> User:
    """解析 token，返回当前登录用户。失败抛 401。"""
    credentials_error = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="未认证或凭证无效",
        headers={"WWW-Authenticate": "Bearer"},
    )

    # 1. 校验并解析 token
    payload = decode_access_token(token)
    if payload is None:
        raise credentials_error

    # 2. 从 payload 里取出用户 ID
    user_id = payload.get("sub")
    if user_id is None:
        raise credentials_error

    # 3. 查数据库确认这个用户真实存在
    user = db.query(User).filter(User.id == int(user_id)).first()
    if user is None:
        raise credentials_error

    return user


def get_current_user_optional(
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
):
    """可选登录：登录了返回 User，没登录（无 token 或无效）返回 None。

    用于「可选登录」的接口（如聊天）——不强制登录，
    但登录后能获得用户身份，从而持久化消息、查历史。
    """
    if token is None:
        return None
    payload = decode_access_token(token)
    if payload is None:
        return None
    user_id = payload.get("sub")
    if user_id is None:
        return None
    return db.query(User).filter(User.id == int(user_id)).first()

