from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import get_current_user
from app.db.models import User
from app.db.session import get_db_session
from app.services.operator_ai_service import handle_operator_ai_chat

router = APIRouter(prefix="/operator-ai", tags=["运小维"])


class OperatorAiChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=1000)
    session_id: str | None = Field(default=None, max_length=128)
    ticket_id: str | None = Field(default=None, max_length=128)
    scope: dict[str, Any] | None = None
    include_evidence: bool = True


@router.post("/chat", summary="运小维只读工单问询")
async def operator_ai_chat(
    req: OperatorAiChatRequest,
    db: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
):
    return await handle_operator_ai_chat(
        db,
        message=req.message,
        session_id=req.session_id,
        ticket_id=req.ticket_id,
        scope=req.scope,
        include_evidence=req.include_evidence,
        user=user,
    )
