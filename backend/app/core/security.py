"""
简单 API Key 验证（防攻击）。

使用方式：在需要保护的路由上添加 Depends(verify_api_key)。
开发环境（DEBUG=True）或未配置 API_KEY 时自动跳过验证。
"""
from __future__ import annotations

from fastapi import Depends, HTTPException, Security
from fastapi.security import APIKeyHeader

from app.core.config import get_settings

_api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


async def verify_api_key(
    api_key: str | None = Security(_api_key_header),
) -> str | None:
    """
    FastAPI 依赖注入：校验请求头中的 X-API-Key。

    跳过条件（任一满足即放行）：
    - DEBUG=True（开发环境）
    - 未配置 API_KEY（空字符串）
    """
    settings = get_settings()
    if settings.DEBUG or not settings.API_KEY:
        return api_key

    if not api_key or api_key != settings.API_KEY:
        raise HTTPException(
            status_code=401,
            detail="无效的 API Key，请在请求头中携带 X-API-Key",
        )
    return api_key
