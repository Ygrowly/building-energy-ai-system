from __future__ import annotations

import asyncio
import json
from typing import Any

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
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
    include_chart: bool = True


def _sse_event(payload: dict[str, Any]) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False, default=str)}\n\n"


def _chunk_text(text: str, max_chars: int = 22) -> list[str]:
    normalized = str(text or "")
    if not normalized:
        return []
    chunks: list[str] = []
    buffer = ""
    for char in normalized:
        buffer += char
        if len(buffer) >= max_chars or char in {"，", "。", "！", "？", "；", "\n"}:
            chunks.append(buffer)
            buffer = ""
    if buffer:
        chunks.append(buffer)
    return chunks


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
        include_chart=req.include_chart,
        user=user,
    )


@router.post("/chat/stream", response_class=StreamingResponse, summary="运小维只读工单问询（流式）")
async def operator_ai_chat_stream(
    req: OperatorAiChatRequest,
    db: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
):
    async def _stream():
        yield _sse_event({
            "type": "thinking",
            "agent": "operator_ai",
            "message": "正在整理运营分析...",
            "hop_count": 1,
        })
        await asyncio.sleep(0)
        try:
            response = await handle_operator_ai_chat(
                db,
                message=req.message,
                session_id=req.session_id,
                ticket_id=req.ticket_id,
                scope=req.scope,
                include_evidence=req.include_evidence,
                include_chart=req.include_chart,
                user=user,
            )
            answer = str(response.get("answer") or "").strip()
            chunks = _chunk_text(answer)
            if chunks:
                for index, chunk in enumerate(chunks):
                    yield _sse_event({
                        "type": "text",
                        "content": chunk,
                        "is_final": index == len(chunks) - 1,
                    })
                    if index != len(chunks) - 1:
                        await asyncio.sleep(0.012)
            else:
                yield _sse_event({"type": "text", "content": "", "is_final": True})
            yield _sse_event({"type": "result", "payload": response})
            yield _sse_event({
                "type": "done",
                "session_id": str(response.get("session_id") or req.session_id or ""),
                "hop_count": 1,
            })
        except Exception as exc:
            message = getattr(exc, "detail", None) or str(exc) or "请求失败，请重试"
            yield _sse_event({
                "type": "error",
                "message": str(message),
                "recoverable": True,
            })

    return StreamingResponse(_stream(), media_type="text/event-stream")
