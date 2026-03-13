"""
认证相关 Pydantic 模型（请求体 / 响应体）。
"""
from __future__ import annotations

import re
from datetime import datetime

from pydantic import BaseModel, Field, field_validator


# ---------------------------------------------------------------------------
# 请求体
# ---------------------------------------------------------------------------

class RegisterRequest(BaseModel):
    username: str = Field(..., min_length=3, max_length=50, pattern=r"^\w+$")
    password: str = Field(..., min_length=8, max_length=128)

    @field_validator("username")
    @classmethod
    def username_lowercase(cls, v: str) -> str:
        return v.lower()

    @field_validator("password")
    @classmethod
    def password_strength(cls, v: str) -> str:
        """
        密码复杂度要求（生产最低标准）：
          - 至少 8 位（Field min_length 已保证）
          - 至少包含一个字母
          - 至少包含一个数字
        """
        if not re.search(r"[A-Za-z]", v):
            raise ValueError("密码必须包含至少一个字母")
        if not re.search(r"\d", v):
            raise ValueError("密码必须包含至少一个数字")
        return v


class LoginRequest(BaseModel):
    username: str = Field(..., min_length=1, max_length=50)
    password: str = Field(..., min_length=1, max_length=128)

    @field_validator("username")
    @classmethod
    def username_lowercase(cls, v: str) -> str:
        return v.lower()


class RefreshRequest(BaseModel):
    # 限制最大长度，防止攻击者发送超大字符串触发 CPU 密集的 JWT 解析（DoS）
    refresh_token: str = Field(..., min_length=1, max_length=2048)


# ---------------------------------------------------------------------------
# 响应体
# ---------------------------------------------------------------------------

class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int = Field(description="access token 有效秒数")


class UserResponse(BaseModel):
    id: str
    username: str
    is_active: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class RegisterResponse(BaseModel):
    user: UserResponse
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int
