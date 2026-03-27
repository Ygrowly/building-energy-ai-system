"""
数据库有效时间范围查询（带内存缓存）。

供 Agent Prompt 动态注入 + 前端日期选择器使用。
查询 energy_data 表的 MIN/MAX(timestamp)，缓存 10 分钟。
"""
import logging
import time
from datetime import date, timedelta

from sqlalchemy import text

from app.db.session import AsyncSessionLocal

logger = logging.getLogger(__name__)

_CACHE_TTL_SECONDS = 600  # 10 分钟

_cached_range: dict | None = None
_cached_at: float = 0.0


async def get_data_range() -> dict:
    """
    返回 {"min_date": ..., "max_date": ..., "default_start": ..., "default_end": ...}
    default_start/end 默认为最近 30 天（而非数据集起始），缓存 10 分钟。
    查询失败时返回安全默认值。
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
            # 默认展示最近 30 天，而不是从数据集最开始
            default_start = max(min_d, max_d - timedelta(days=29))
            _cached_range = {
                "min_date": str(min_d),
                "max_date": str(max_d),
                "default_start": str(default_start),
                "default_end": str(max_d),
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
    return {
        "min_date": "2026-01-01",
        "max_date": "2026-03-31",
        "default_start": "2026-01-01",
        "default_end": "2026-01-31",
    }
