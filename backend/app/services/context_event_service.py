"""
特殊事件服务层：CRUD + 按时间/空间查询生效事件。

context_events 存储装修、加班、极端天气等业务语境，
供 AI 审批引擎判断异常是否可被特殊事件合理解释。
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from sqlalchemy import select, update, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import ContextEvent

logger = logging.getLogger(__name__)

# 事件类型白名单
COMPANY_EVENT_TYPES = {"renovation", "team_building", "overtime", "special_event", "maintenance_window"}
WEATHER_EVENT_TYPES = {"extreme_heat", "extreme_cold", "typhoon", "heavy_rain", "snow_ice"}
ALL_EVENT_TYPES = COMPANY_EVENT_TYPES | WEATHER_EVENT_TYPES

CATEGORY_MAP = {
    **{t: "company" for t in COMPANY_EVENT_TYPES},
    **{t: "weather" for t in WEATHER_EVENT_TYPES},
}


# ---------------------------------------------------------------------------
# 创建事件
# ---------------------------------------------------------------------------
async def create_context_event(
    db: AsyncSession,
    *,
    event_type: str,
    building_id: str | None = None,
    start_time: datetime,
    end_time: datetime,
    grace_period_minutes: int = 0,
    description: str | None = None,
    created_by: str | None = None,
) -> ContextEvent:
    if event_type not in ALL_EVENT_TYPES:
        raise ValueError(f"未知事件类型: {event_type}，允许: {ALL_EVENT_TYPES}")
    if end_time <= start_time:
        raise ValueError("end_time 必须大于 start_time")
    if not (0 <= grace_period_minutes <= 480):
        raise ValueError("grace_period_minutes 必须在 0-480 之间")

    category = CATEGORY_MAP[event_type]
    event = ContextEvent(
        event_type=event_type,
        category=category,
        building_id=building_id,
        start_time=start_time,
        end_time=end_time,
        grace_period_minutes=grace_period_minutes,
        description=description,
        created_by=created_by,
    )
    db.add(event)
    await db.flush()
    logger.info("特殊事件已创建: id=%s type=%s building=%s", event.id, event_type, building_id)
    return event


# ---------------------------------------------------------------------------
# 查询生效事件（供 AI 审批使用）
# ---------------------------------------------------------------------------
async def query_active_events(
    db: AsyncSession,
    *,
    building_id: str,
    anomaly_timestamp: datetime,
) -> list[ContextEvent]:
    """
    查询在 anomaly_timestamp 时刻对指定楼栋生效的特殊事件。
    匹配规则：
      - 空间: event.building_id = building_id 或 event.building_id IS NULL（全局）
      - 时间: anomaly_timestamp ∈ [start_time, end_time + grace_period_minutes]
      - 状态: is_active = True
    结果按同楼优先、时间倒序排列。
    """
    # 使用 text() 做 interval 运算（PostgreSQL 语法）
    stmt = (
        select(ContextEvent)
        .where(
            ContextEvent.is_active == True,  # noqa: E712
            (ContextEvent.building_id == building_id) | (ContextEvent.building_id.is_(None)),
            ContextEvent.start_time <= anomaly_timestamp,
        )
        .order_by(
            # 同楼优先
            (ContextEvent.building_id == building_id).desc(),
            ContextEvent.start_time.desc(),
        )
    )

    result = await db.execute(stmt)
    events = list(result.scalars().all())

    # Python 层过滤 grace_period（避免复杂 SQL interval 计算的兼容性问题）
    matched = []
    for ev in events:
        from datetime import timedelta
        effective_end = ev.end_time + timedelta(minutes=ev.grace_period_minutes)
        if anomaly_timestamp <= effective_end:
            matched.append(ev)

    return matched


# ---------------------------------------------------------------------------
# 列出事件
# ---------------------------------------------------------------------------
async def list_context_events(
    db: AsyncSession,
    *,
    building_id: str | None = None,
    category: str | None = None,
    is_active: bool = True,
    active_at: datetime | None = None,
) -> list[ContextEvent]:
    """列出特殊事件，支持多维度过滤。"""
    query = select(ContextEvent)

    if is_active is not None:
        query = query.where(ContextEvent.is_active == is_active)

    if building_id:
        query = query.where(
            (ContextEvent.building_id == building_id) | (ContextEvent.building_id.is_(None))
        )

    if category:
        query = query.where(ContextEvent.category == category)

    if active_at:
        query = query.where(
            ContextEvent.start_time <= active_at,
            ContextEvent.end_time >= active_at,
        )

    query = query.order_by(ContextEvent.start_time.desc())
    result = await db.execute(query)
    return list(result.scalars().all())


# ---------------------------------------------------------------------------
# 更新事件
# ---------------------------------------------------------------------------
async def update_context_event(
    db: AsyncSession,
    event_id: str,
    **kwargs: Any,
) -> ContextEvent | None:
    event = await db.get(ContextEvent, event_id)
    if not event:
        return None

    for key, value in kwargs.items():
        if hasattr(event, key) and value is not None:
            setattr(event, key, value)

    await db.flush()
    return event


# ---------------------------------------------------------------------------
# 软删除事件
# ---------------------------------------------------------------------------
async def deactivate_context_event(
    db: AsyncSession, event_id: str
) -> bool:
    event = await db.get(ContextEvent, event_id)
    if not event:
        return False
    event.is_active = False
    await db.flush()
    logger.info("特殊事件已停用: id=%s", event_id)
    return True


# ---------------------------------------------------------------------------
# 序列化
# ---------------------------------------------------------------------------
def serialize_context_event(ev: ContextEvent) -> dict[str, Any]:
    return {
        "id": ev.id,
        "event_type": ev.event_type,
        "category": ev.category,
        "building_id": ev.building_id,
        "start_time": ev.start_time.isoformat() if ev.start_time else None,
        "end_time": ev.end_time.isoformat() if ev.end_time else None,
        "grace_period_minutes": ev.grace_period_minutes,
        "description": ev.description,
        "is_active": ev.is_active,
        "created_by": ev.created_by,
        "created_at": ev.created_at.isoformat() if ev.created_at else None,
    }
