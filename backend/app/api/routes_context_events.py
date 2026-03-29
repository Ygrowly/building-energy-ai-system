"""
特殊事件管理 API。

端点：
  POST   /api/context-events              — 创建特殊事件
  GET    /api/context-events              — 列表 / 过滤
  PUT    /api/context-events/{event_id}   — 更新事件
  DELETE /api/context-events/{event_id}   — 软删除（停用）
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.cache import delete_cache_by_prefix
from app.core.security import get_current_user
from app.db.models import User
from app.db.session import get_db_session
from app.services.context_event_service import (
    ALL_EVENT_TYPES,
    create_context_event,
    deactivate_context_event,
    list_context_events,
    serialize_context_event,
    update_context_event,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/context-events", tags=["特殊事件"])


def _require_admin(user: User) -> None:
    if user.role not in ("admin", "manager"):
        raise HTTPException(status_code=403, detail="权限不足，需要管理员角色")


# ---------------------------------------------------------------------------
# 请求模型
# ---------------------------------------------------------------------------
class CreateEventRequest(BaseModel):
    event_type: str
    building_id: str | None = None
    start_time: datetime
    end_time: datetime
    grace_period_minutes: int = Field(default=0, ge=0, le=480)
    description: str | None = None


class UpdateEventRequest(BaseModel):
    event_type: str | None = None
    building_id: str | None = None
    start_time: datetime | None = None
    end_time: datetime | None = None
    grace_period_minutes: int | None = Field(default=None, ge=0, le=480)
    description: str | None = None


# ---------------------------------------------------------------------------
# POST /api/context-events — 创建
# ---------------------------------------------------------------------------
@router.post("", summary="创建特殊事件")
async def create_event(
    req: CreateEventRequest,
    db: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
):
    _require_admin(user)

    if req.event_type not in ALL_EVENT_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"未知事件类型: {req.event_type}，允许: {sorted(ALL_EVENT_TYPES)}",
        )

    try:
        event = await create_context_event(
            db,
            event_type=req.event_type,
            building_id=req.building_id,
            start_time=req.start_time,
            end_time=req.end_time,
            grace_period_minutes=req.grace_period_minutes,
            description=req.description,
            created_by=user.id,
        )
        await db.commit()
        await delete_cache_by_prefix("context_events:")
        return serialize_context_event(event)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ---------------------------------------------------------------------------
# GET /api/context-events — 列表
# ---------------------------------------------------------------------------
@router.get("", summary="列出特殊事件")
async def list_events(
    building_id: str | None = Query(None),
    category: str | None = Query(None, pattern=r"^(company|weather)$"),
    is_active: bool = Query(True),
    active_at: datetime | None = Query(None, description="指定时间点，返回该时刻生效的事件"),
    db: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
):
    _require_admin(user)

    events = await list_context_events(
        db,
        building_id=building_id,
        category=category,
        is_active=is_active,
        active_at=active_at,
    )
    return {
        "total": len(events),
        "events": [serialize_context_event(ev) for ev in events],
    }


# ---------------------------------------------------------------------------
# PUT /api/context-events/{event_id} — 更新
# ---------------------------------------------------------------------------
@router.put("/{event_id}", summary="更新特殊事件")
async def update_event(
    event_id: str,
    req: UpdateEventRequest,
    db: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
):
    _require_admin(user)

    updates = req.model_dump(exclude_none=True)
    if not updates:
        raise HTTPException(status_code=400, detail="没有需要更新的字段")

    if "event_type" in updates and updates["event_type"] not in ALL_EVENT_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"未知事件类型: {updates['event_type']}",
        )

    event = await update_context_event(db, event_id, **updates)
    if not event:
        raise HTTPException(status_code=404, detail="事件不存在")

    await db.commit()
    await delete_cache_by_prefix("context_events:")
    return serialize_context_event(event)


# ---------------------------------------------------------------------------
# DELETE /api/context-events/{event_id} — 软删除
# ---------------------------------------------------------------------------
@router.delete("/{event_id}", summary="停用特殊事件")
async def delete_event(
    event_id: str,
    db: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
):
    _require_admin(user)

    ok = await deactivate_context_event(db, event_id)
    if not ok:
        raise HTTPException(status_code=404, detail="事件不存在")

    await db.commit()
    await delete_cache_by_prefix("context_events:")
    return {"message": "事件已停用", "event_id": event_id}
