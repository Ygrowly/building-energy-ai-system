"""
派工事件流服务。

dispatch_events 是派工执行层的事件轨迹；这里集中处理事件写入、批量加载
和序列化，调用方仍负责 commit/rollback。
"""
from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import DispatchEvent, DispatchTask


def _dt_to_iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _json_dumps(payload: dict[str, Any] | None) -> str | None:
    if not payload:
        return None
    return json.dumps(payload, ensure_ascii=False, default=str)


def _json_loads(payload: str | None) -> dict[str, Any] | None:
    if not payload:
        return None
    try:
        data = json.loads(payload)
    except (TypeError, ValueError):
        return None
    return data if isinstance(data, dict) else None


async def record_dispatch_event(
    db: AsyncSession,
    *,
    dispatch_task: DispatchTask,
    event_type: str,
    actor_type: str,
    actor_id: str | None = None,
    payload: dict[str, Any] | None = None,
) -> DispatchEvent:
    event = DispatchEvent(
        dispatch_task_id=dispatch_task.id,
        work_order_id=dispatch_task.work_order_id,
        incident_id=dispatch_task.incident_id,
        event_type=event_type,
        actor_type=actor_type,
        actor_id=actor_id,
        payload_json=_json_dumps(payload),
    )
    db.add(event)
    return event


async def list_dispatch_events(
    db: AsyncSession,
    *,
    dispatch_task_id: str,
) -> list[DispatchEvent]:
    result = await db.execute(
        select(DispatchEvent)
        .where(DispatchEvent.dispatch_task_id == dispatch_task_id)
        .order_by(DispatchEvent.created_at.asc())
    )
    return list(result.scalars().all())


async def load_dispatch_events_by_task_ids(
    db: AsyncSession,
    *,
    dispatch_task_ids: list[str],
) -> dict[str, list[DispatchEvent]]:
    if not dispatch_task_ids:
        return {}
    result = await db.execute(
        select(DispatchEvent)
        .where(DispatchEvent.dispatch_task_id.in_(dispatch_task_ids))
        .order_by(DispatchEvent.created_at.asc())
    )
    grouped: dict[str, list[DispatchEvent]] = {}
    for item in result.scalars().all():
        grouped.setdefault(item.dispatch_task_id, []).append(item)
    return grouped


def serialize_dispatch_event(event: DispatchEvent) -> dict[str, Any]:
    return {
        "id": event.id,
        "dispatch_task_id": event.dispatch_task_id,
        "work_order_id": event.work_order_id,
        "incident_id": event.incident_id,
        "event_type": event.event_type,
        "actor_type": event.actor_type,
        "actor_id": event.actor_id,
        "payload": _json_loads(event.payload_json),
        "created_at": _dt_to_iso(event.created_at),
    }
