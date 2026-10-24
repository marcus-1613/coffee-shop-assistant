"""
认证路由：注册 / 登录

这是「企业级升级 · P0 · 用户认证」的接口层。

- POST /auth/register  注册新用户
- POST /auth/login     登录，返回 JWT 令牌
- GET  /auth/me        查看当前登录用户（需带 token，验证认证生效）

登录接口用的是 OAuth2 的「密码流」——表单提交 username/password，
返回 access_token。前端拿到 token 后，后续请求都带在 Authorization 头里。
"""
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session

from app.core.security import hash_password, verify_password, create_access_token
from app.core.deps import get_current_user
from app.models.database import get_db
from app.models.user import User

router = APIRouter(prefix="/auth", tags=["认证"])


class RegisterRequest(BaseModel):
    """JSON registration payload with basic account validation."""

    username: str = Field(min_length=3, max_length=50)
    password: str = Field(min_length=8)

    @field_validator("username")
    @classmethod
    def normalize_username(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("用户名不能为空")
        if any(ch.isspace() for ch in value):
            raise ValueError("用户名不能包含空白字符")
        return value

    @field_validator("password")
    @classmethod
    def validate_password_length(cls, value: str) -> str:
        if len(value.encode("utf-8")) > 72:
            raise ValueError("密码不能超过 72 字节")
        return value


@router.post("/register", status_code=status.HTTP_201_CREATED)
def register(
    payload: RegisterRequest,
    db: Session = Depends(get_db),
):
    """注册新用户。用户名唯一，密码会被哈希后入库。"""
    # 检查用户名是否已存在
    if db.query(User).filter(User.username == payload.username).first():
        raise HTTPException(status_code=400, detail="用户名已被占用")

    # 密码哈希后入库（绝不存明文）
    user = User(
        username=payload.username,
        hashed_password=hash_password(payload.password),
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    return {"id": user.id, "username": user.username, "message": "注册成功"}


@router.post("/login")
def login(
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db),
):
    """登录：校验密码，签发 JWT 令牌。"""
    # 1. 查用户
    user = db.query(User).filter(User.username == form_data.username).first()
    # 2. 校验密码（注意：用户不存在也返回同样的错误，防止「用户名枚举」攻击）
    if not user or not verify_password(form_data.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="用户名或密码错误",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # 3. 签发 token
    token = create_access_token(user.id, user.username)
    return {"access_token": token, "token_type": "bearer", "username": user.username}


@router.get("/me")
def read_me(current_user: User = Depends(get_current_user)):
    """查看当前登录用户（验证认证链路是否生效）。"""
    return {"id": current_user.id, "username": current_user.username}
