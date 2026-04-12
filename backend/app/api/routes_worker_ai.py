from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import get_current_user
from app.db.models import User
from app.db.session import get_db_session
from app.services.worker_ai_service import handle_worker_ai_chat

router = APIRouter(prefix="/worker-ai", tags=["维小修"])


class WorkerAiChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=1000)
    session_id: str | None = Field(default=None, max_length=128)
    ticket_id: str | None = Field(default=None, max_length=128)
    dispatch_id: str | None = Field(default=None, max_length=128)
    hall_entry_id: str | None = Field(default=None, max_length=128)
    client_context: dict[str, Any] | None = None


@router.post("/chat", summary="维小修对话式工单执行")
async def worker_ai_chat(
    req: WorkerAiChatRequest,
    db: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
):
    return await handle_worker_ai_chat(
        db,
        message=req.message,
        session_id=req.session_id,
        ticket_id=req.ticket_id,
        dispatch_id=req.dispatch_id,
        hall_entry_id=req.hall_entry_id,
        client_context=req.client_context,
        user=user,
    )
