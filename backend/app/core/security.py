"""
安全工具集合：
  1. API Key 校验（旧机制，保留兼容）
  2. 密码哈希 / 校验（passlib bcrypt）
  3. JWT 生成 / 解码（PyJWT）
  4. FastAPI 依赖：get_current_user
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING

import jwt
from fastapi import Depends, HTTPException, Security, status
from fastapi.security import APIKeyHeader, OAuth2PasswordBearer
from passlib.context import CryptContext
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from app.core.config import get_settings
from app.db.session import get_db_session

if TYPE_CHECKING:
    from app.db.models import User

# ---------------------------------------------------------------------------
# 旧 API Key 校验（X-API-Key 请求头）
# ---------------------------------------------------------------------------

_api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


async def verify_api_key(
    api_key: str | None = Security(_api_key_header),
) -> str | None:
    """
    FastAPI 依赖注入：校验请求头中的 X-API-Key。
    跳过条件（任一满足即放行）：DEBUG=True 或未配置 API_KEY。
    """
    settings = get_settings()
    if settings.DEBUG or not settings.API_KEY:
        return api_key
    if not api_key or api_key != settings.API_KEY:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="无效的 API Key，请在请求头中携带 X-API-Key",
        )
    return api_key


# ---------------------------------------------------------------------------
# 密码哈希（bcrypt）
# ---------------------------------------------------------------------------

_pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(plain_password: str) -> str:
    """将明文密码哈希为 bcrypt 字符串。"""
    return _pwd_context.hash(plain_password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """校验明文密码是否与哈希值匹配。"""
    return _pwd_context.verify(plain_password, hashed_password)


# ---------------------------------------------------------------------------
# JWT 工具
# ---------------------------------------------------------------------------

_oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login", auto_error=False)


def create_access_token(user_id: str) -> tuple[str, int]:
    """
    生成 access token（3 小时过期）。
    返回 (token_str, expires_in_seconds)。
    """
    settings = get_settings()
    expire_seconds = settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60
    expire = datetime.now(timezone.utc) + timedelta(seconds=expire_seconds)
    payload = {
        "sub": user_id,
        "exp": expire,
        "iat": datetime.now(timezone.utc),
        "type": "access",
    }
    token = jwt.encode(
        payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM
    )
    return token, expire_seconds


def create_refresh_token(user_id: str) -> tuple[str, str, datetime]:
    """
    生成 refresh token（7 天过期）。
    返回 (token_str, jti, expires_at)，jti 用于数据库存储与吊销。
    """
    settings = get_settings()
    jti = str(uuid.uuid4())
    expires_at = datetime.now(timezone.utc) + timedelta(
        days=settings.REFRESH_TOKEN_EXPIRE_DAYS
    )
    payload = {
        "sub": user_id,
        "jti": jti,
        "exp": expires_at,
        "iat": datetime.now(timezone.utc),
        "type": "refresh",
    }
    token = jwt.encode(
        payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM
    )
    return token, jti, expires_at


def _decode_token(token: str) -> dict:
    """解码并验证 JWT，失败时抛出 401 HTTPException。"""
    settings = get_settings()
    try:
        return jwt.decode(
            token,
            settings.JWT_SECRET_KEY,
            algorithms=[settings.JWT_ALGORITHM],
        )
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token 已过期，请重新登录",
            headers={"WWW-Authenticate": "Bearer"},
        )
    except jwt.InvalidTokenError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="无效的 Token",
            headers={"WWW-Authenticate": "Bearer"},
        )


def decode_access_token(token: str) -> str:
    """解码 access token，返回 user_id（sub 字段）。"""
    payload = _decode_token(token)
    if payload.get("type") != "access":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token 类型错误",
        )
    user_id: str | None = payload.get("sub")
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token 缺少用户信息",
        )
    return user_id


def decode_refresh_token(token: str) -> tuple[str, str]:
    """
    解码 refresh token，返回 (user_id, jti)。
    """
    payload = _decode_token(token)
    if payload.get("type") != "refresh":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token 类型错误，需要 refresh token",
        )
    user_id: str | None = payload.get("sub")
    jti: str | None = payload.get("jti")
    if not user_id or not jti:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token 格式无效",
        )
    return user_id, jti


# ---------------------------------------------------------------------------
# FastAPI 依赖：获取当前登录用户
# ---------------------------------------------------------------------------

async def get_current_user(
    token: str | None = Depends(_oauth2_scheme),
    db: AsyncSession = Depends(get_db_session),
) -> "User":
    """
    从 Bearer token 中解析并返回当前用户 ORM 对象。
    复用路由层注入的同一个 DB Session，避免每次请求多建一条连接。
    """
    from app.db.models import User as UserModel

    if token is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="未提供认证 Token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user_id = decode_access_token(token)

    result = await db.execute(
        select(UserModel).where(UserModel.id == user_id)
    )
    user = result.scalar_one_or_none()

    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="用户不存在",
        )
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="账户已被禁用",
        )
    return user


async def get_current_active_user(
    current_user: "User" = Depends(get_current_user),
) -> "User":
    """便捷依赖：同 get_current_user，语义更明确。"""
    return current_user
