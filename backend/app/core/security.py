"""
安全模块：密码哈希 + JWT 令牌

这是「企业级升级 · P0 · 用户认证」的核心。

两大职责：
1. 密码哈希（hash / verify）—— 用 bcrypt 把密码变成不可逆的哈希
2. JWT 令牌（create / decode）—— 登录后签发、之后校验的令牌

关键认知：
- 密码「哈希」和「加密」是两回事：
  加密可逆（能解密回原文），哈希不可逆（只能比对，不能还原）。
  密码必须用哈希，这样数据库泄露了，攻击者也拿不回原文。
- JWT 是「无状态」的：服务端不存 token，靠签名校验真伪。
  签名用的 SECRET_KEY 必须保密（放在 .env，不进 git）。
"""
import os
from datetime import datetime, timedelta, timezone
from typing import Optional

import bcrypt
from dotenv import load_dotenv
from jose import JWTError, jwt

# 从 .env 文件加载配置；生产环境应通过密钥管理服务注入。
load_dotenv()

SECRET_KEY = os.getenv("SECRET_KEY")
_INSECURE_SECRETS = {
    "",
    "dev-secret-key-change-in-production",
    "please-generate-a-random-secret-key",
    "replace-with-a-random-secret-key",
}
if not SECRET_KEY or SECRET_KEY in _INSECURE_SECRETS:
    raise RuntimeError(
        "SECRET_KEY 未配置或仍为示例值。请在 backend/.env 中生成随机密钥。"
    )
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24  # token 有效期：24 小时


def hash_password(password: str) -> str:
    """把明文密码哈希化（不可逆）。

    直接用 bcrypt 库（而非已停止维护的 passlib）。
    bcrypt 有 72 字节长度限制，这里做截断防护。
    """
    return bcrypt.hashpw(password.encode("utf-8")[:72], bcrypt.gensalt()).decode("utf-8")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """校验明文密码是否匹配哈希值"""
    try:
        return bcrypt.checkpw(
            plain_password.encode("utf-8")[:72],
            hashed_password.encode("utf-8"),
        )
    except ValueError:
        return False


def create_access_token(user_id: int, username: str) -> str:
    """签发一个 JWT 令牌，里面装「用户ID + 用户名 + 过期时间」"""
    expire = datetime.now(timezone.utc) + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    payload = {
        "sub": str(user_id),   # subject：令牌的主体（这里存用户ID）
        "username": username,
        "exp": expire,         # 过期时间
    }
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def decode_access_token(token: str) -> Optional[dict]:
    """校验并解析 JWT 令牌。

    成功返回 payload（含 sub=用户ID），失败/过期/伪造返回 None。
    这是「无状态认证」的关键：不查数据库，只验签名。
    """
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return payload
    except JWTError:
        return None
