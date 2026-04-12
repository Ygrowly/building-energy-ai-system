from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, WebSocket
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import get_current_user
from app.db.models import User
from app.db.session import AsyncSessionLocal, get_db_session
from app.services.notification_realtime_service import (
    build_ws_message,
    consume_realtime_ticket,
    issue_realtime_ticket,
    stream_user_events,
)
from app.services.notification_service import (
    get_notification_summary,
    list_notifications,
    mark_all_notifications_read,
    mark_notification_recipients_read,
    serialize_notification_recipient,
)

router = APIRouter(prefix="/notifications", tags=["notification"])


def _require_role(user: User, *roles: str) -> None:
    if user.role not in roles:
        raise HTTPException(status_code=403, detail="权限不足")


class MarkReadRequest(BaseModel):
    recipient_ids: list[str] = Field(default_factory=list)


class MarkAllReadRequest(BaseModel):
    category: str | None = Field(default=None)


@router.get("", summary="获取通知列表")
async def list_notifications_endpoint(
    category: str | None = Query(default="workorder"),
    status: str = Query(default="all", pattern="^(all|unread)$"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    db: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    _require_role(user, "ops", "manager", "admin")
    items, total = await list_notifications(
        db,
        user_id=user.id,
        category=category,
        status=status,
        page=page,
        page_size=page_size,
    )
    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "notifications": [serialize_notification_recipient(item) for item in items],
    }


@router.get("/summary", summary="获取通知未读摘要")
async def get_notifications_summary_endpoint(
    db: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    _require_role(user, "ops", "manager", "admin")
    return await get_notification_summary(db, user_id=user.id)


@router.post("/mark-read", summary="按通知收件箱 ID 标记已读")
async def mark_notifications_read_endpoint(
    req: MarkReadRequest,
    db: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    _require_role(user, "ops", "manager", "admin")
    items = await mark_notification_recipients_read(
        db,
        user_id=user.id,
        recipient_ids=req.recipient_ids,
    )
    await db.commit()
    return {
        "updated": len(items),
        "recipient_ids": [item.id for item in items],
    }


@router.post("/mark-all-read", summary="按分类全部标记已读")
async def mark_all_notifications_read_endpoint(
    req: MarkAllReadRequest,
    db: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    _require_role(user, "ops", "manager", "admin")
    items = await mark_all_notifications_read(
        db,
        user_id=user.id,
        category=req.category,
    )
    await db.commit()
    return {
        "updated": len(items),
    }


@router.post("/realtime-ticket", summary="获取通知实时通道票据")
async def create_notifications_realtime_ticket_endpoint(
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    _require_role(user, "ops", "manager", "admin")
    return await issue_realtime_ticket(user.id)


@router.websocket("/ws")
async def notifications_ws_endpoint(
    websocket: WebSocket,
    ticket: str,
    page_size: int = 20,
) -> None:
    user_id = await consume_realtime_ticket(ticket)
    if not user_id:
        await websocket.close(code=1008, reason="invalid ticket")
        return

    await websocket.accept()
    async with AsyncSessionLocal() as db:
        summary = await get_notification_summary(db, user_id=user_id)
        items, _ = await list_notifications(
            db,
            user_id=user_id,
            category="workorder",
            status="all",
            page=1,
            page_size=page_size,
        )
        serialized = [serialize_notification_recipient(item) for item in items]

    await websocket.send_text(build_ws_message("notification.summary", summary))
    for item in serialized:
        await websocket.send_text(
            build_ws_message(
                "notification.created",
                {
                    **item,
                    "bootstrap": True,
                },
            )
        )
    await stream_user_events(user_id, websocket)
