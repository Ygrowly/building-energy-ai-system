"""
数据库有效时间范围查询（带内存缓存）。

供 Agent Prompt 动态注入 + 前端日期选择器使用。
查询 energy_data 表的 MIN/MAX(timestamp)，缓存 10 分钟。

注意：当前日期和默认查询范围的计算统一由 app.core.time_context 负责，
本模块仅查询数据库中的 min/max 并配合 time_context 计算 default_start/end。
"""
import logging
import time
from datetime import date

from sqlalchemy import text

from app.db.session import AsyncSessionLocal

logger = logging.getLogger(__name__)

_CACHE_TTL_SECONDS = 600  # 10 分钟

_cached_range: dict | None = None
_cached_at: float = 0.0


async def get_data_range() -> dict:
    """
    返回 {"min_date": ..., "max_date": ..., "default_start": ..., "default_end": ...}
    min/max 来自数据库，default_start/end 由统一时间工具计算，缓存 10 分钟。
    """
    global _cached_range, _cached_at

    if _cached_range and (time.time() - _cached_at) < _CACHE_TTL_SECONDS:
        return _cached_range

    try:
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                text('SELECT MIN("timestamp")::date, MAX("timestamp")::date FROM energy_data')
            )
            row = result.first()

        if row and row[0] and row[1]:
            min_d: date = row[0]
            max_d: date = row[1]
            from app.core.time_context import resolve_query_range
            default_start, default_end = resolve_query_range(
                data_min=str(min_d), data_max=str(max_d),
            )
            _cached_range = {
                "min_date": str(min_d),
                "max_date": str(max_d),
                "default_start": default_start,
                "default_end": default_end,
            }
        else:
            _cached_range = _fallback()

        _cached_at = time.time()
        logger.info("data_range 已刷新: %s", _cached_range)
        return _cached_range

    except Exception as exc:
        logger.warning("查询 data_range 失败，使用默认值: %s", exc)
        if _cached_range:
            return _cached_range
        return _fallback()


def _fallback() -> dict:
    from app.core.time_context import get_today
    today = get_today()
    return {
        "min_date": "2026-01-01",
        "max_date": str(today),
        "default_start": "2026-01-01",
        "default_end": str(today),
    }
