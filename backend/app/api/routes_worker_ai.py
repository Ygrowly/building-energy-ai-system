from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import get_current_user
from app.db.models import User
from app.db.session import get_db_session
from app.services.ai_media_service import (
    analyze_worker_image,
    build_tts_response,
    get_tts_cache_path,
    transcribe_worker_audio,
)
from app.services.maintenance_guidance_service import (
    get_or_create_worker_step_plan,
    handle_worker_guidance_chat,
    update_worker_step_status,
)
from app.services.worker_ai_service import handle_worker_ai_chat

router = APIRouter(prefix="/worker-ai", tags=["维小修"])


class WorkerAiChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=1000)
    session_id: str | None = Field(default=None, max_length=128)
    ticket_id: str | None = Field(default=None, max_length=128)
    dispatch_id: str | None = Field(default=None, max_length=128)
    hall_entry_id: str | None = Field(default=None, max_length=128)
    client_context: dict[str, Any] | None = None


class WorkerAiStepUpdateRequest(BaseModel):
    plan_id: str = Field(..., min_length=1, max_length=128)
    status: str = Field(..., pattern="^(pending|completed|skipped|needs_support|uncertain)$")
    note: str | None = Field(default=None, max_length=1000)
    client_version: int | None = Field(default=None, ge=0)


class WorkerAiGuidanceChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=1000)
    session_id: str | None = Field(default=None, max_length=128)
    ticket_id: str = Field(..., min_length=1, max_length=128)
    dispatch_id: str | None = Field(default=None, max_length=128)
    plan_id: str | None = Field(default=None, max_length=128)
    step_id: str | None = Field(default=None, max_length=64)
    client_context: dict[str, Any] | None = None


class WorkerAiTtsRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=1000)
    voice: str | None = Field(default=None, max_length=64)


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


@router.post("/guidance/chat", summary="维小修维修指导对话")
async def worker_ai_guidance_chat(
    req: WorkerAiGuidanceChatRequest,
    db: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
):
    return await handle_worker_guidance_chat(
        db,
        message=req.message,
        session_id=req.session_id,
        ticket_id=req.ticket_id,
        dispatch_id=req.dispatch_id,
        plan_id=req.plan_id,
        step_id=req.step_id,
        client_context=req.client_context,
        user=user,
    )


@router.get("/work-orders/{ticket_id}/steps", summary="获取或生成维小修维修步骤卡片")
async def worker_ai_steps(
    ticket_id: str,
    auto_generate: bool = Query(default=True),
    dispatch_id: str | None = Query(default=None),
    db: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
):
    return await get_or_create_worker_step_plan(
        db,
        ticket_id=ticket_id,
        dispatch_id=dispatch_id,
        auto_generate=auto_generate,
        user=user,
    )


@router.post("/work-orders/{ticket_id}/steps/{step_id}/update", summary="更新维小修步骤状态")
async def worker_ai_step_update(
    ticket_id: str,
    step_id: str,
    req: WorkerAiStepUpdateRequest,
    db: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
):
    return await update_worker_step_status(
        db,
        ticket_id=ticket_id,
        step_id=step_id,
        plan_id=req.plan_id,
        status=req.status,
        note=req.note,
        client_version=req.client_version,
        user=user,
    )


@router.post("/media/analyze-image", summary="维小修现场图片分析")
async def worker_ai_analyze_image(
    ticket_id: str = Form(...),
    dispatch_id: str | None = Form(default=None),
    step_id: str | None = Form(default=None),
    prompt: str | None = Form(default=None),
    image: UploadFile = File(...),
    db: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
):
    return await analyze_worker_image(
        db,
        ticket_id=ticket_id,
        dispatch_id=dispatch_id,
        step_id=step_id,
        prompt=prompt,
        file=image,
        user=user,
    )


@router.post("/media/transcribe", summary="维小修语音转文字")
async def worker_ai_transcribe_audio(
    ticket_id: str = Form(...),
    dispatch_id: str | None = Form(default=None),
    step_id: str | None = Form(default=None),
    audio: UploadFile = File(...),
    db: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
):
    return await transcribe_worker_audio(
        db,
        ticket_id=ticket_id,
        dispatch_id=dispatch_id,
        step_id=step_id,
        file=audio,
        user=user,
    )


@router.post("/tts", summary="维小修回复播报")
async def worker_ai_tts(
    req: WorkerAiTtsRequest,
    user: User = Depends(get_current_user),
):
    return await build_tts_response(text=req.text, voice=req.voice)


@router.get("/tts/cache/{filename}", summary="获取维小修 TTS 缓存音频")
async def worker_ai_tts_cache(
    filename: str,
    user: User = Depends(get_current_user),
):
    cache_key = filename.removesuffix(".mp3")
    path = get_tts_cache_path(cache_key)
    if not path.exists():
        raise HTTPException(status_code=404, detail="音频缓存不存在")
    return FileResponse(path, media_type="audio/mpeg", filename=path.name)
