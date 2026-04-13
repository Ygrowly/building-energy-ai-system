from __future__ import annotations

import base64
import hashlib
import json
import logging
import re
import uuid
from pathlib import Path
from typing import Any

from fastapi import HTTPException, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.db.models import AiMediaAsset, User, WorkOrder
from app.services.ai_model_provider import get_model_provider, parse_json_object
from app.services.maintenance_guidance_service import record_step_media_event
from app.services.worker_ai_service import _assert_worker_permission, _resolve_work_order

logger = logging.getLogger(__name__)

MEDIA_ROOT = Path("uploads/worker_ai_media")
MAX_IMAGE_BYTES = 5 * 1024 * 1024
MAX_AUDIO_BYTES = 10 * 1024 * 1024
FILLER_TRANSCRIPTS = {"嗯", "嗯。", "呃", "呃。", "啊", "啊。", "唔", "唔。"}

IMAGE_TYPES = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
}

AUDIO_TYPES = {
    "audio/aac": ".aac",
    "audio/amr": ".amr",
    "audio/flac": ".flac",
    "audio/m4a": ".m4a",
    "audio/mp4": ".m4a",
    "audio/mpeg": ".mp3",
    "audio/mp3": ".mp3",
    "audio/ogg": ".ogg",
    "audio/opus": ".opus",
    "audio/wav": ".wav",
    "audio/webm": ".webm",
    "audio/x-m4a": ".m4a",
}


def _safe_filename(name: str | None, *, fallback_ext: str) -> str:
    stem = Path(name or "upload").stem
    stem = re.sub(r"[^A-Za-z0-9_.-]+", "_", stem).strip("._")[:48] or "upload"
    return f"{stem}_{uuid.uuid4().hex[:12]}{fallback_ext}"


def _data_uri(content: bytes, mime_type: str) -> str:
    encoded = base64.b64encode(content).decode("ascii")
    return f"data:{mime_type};base64,{encoded}"


async def _read_and_validate_upload(
    file: UploadFile,
    *,
    allowed_types: dict[str, str],
    max_bytes: int,
    media_label: str,
) -> tuple[bytes, str, str]:
    mime_type = (file.content_type or "").split(";")[0].strip().lower()
    if mime_type not in allowed_types:
        raise HTTPException(status_code=400, detail=f"不支持的{media_label}格式：{mime_type or 'unknown'}")
    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail=f"{media_label}文件为空")
    if len(content) > max_bytes:
        raise HTTPException(status_code=413, detail=f"{media_label}文件过大，请压缩后再上传")
    return content, mime_type, allowed_types[mime_type]


async def _save_media_file(
    *,
    content: bytes,
    work_order: WorkOrder,
    user: User,
    original_name: str | None,
    ext: str,
    media_type: str,
) -> str:
    target_dir = MEDIA_ROOT / work_order.id / media_type
    target_dir.mkdir(parents=True, exist_ok=True)
    filename = _safe_filename(original_name, fallback_ext=ext)
    path = target_dir / filename
    path.write_bytes(content)
    return path.as_posix()


def _fallback_image_analysis() -> dict[str, Any]:
    return {
        "summary": "图片已保存，但当前视觉模型不可用或未返回结构化结果。请结合现场读数继续描述，我会基于文字信息辅助判断。",
        "observations": [],
        "uncertainties": ["未能完成自动图片理解"],
        "suggested_next_message": "请补充图片中的关键读数、设备状态或报警信息。",
    }


def normalize_transcript(text: str) -> str:
    transcript = " ".join((text or "").split()).strip()
    if transcript in FILLER_TRANSCRIPTS:
        return ""
    return transcript


async def _analyze_image_with_model(
    *,
    content: bytes,
    mime_type: str,
    prompt: str | None,
    work_order: WorkOrder,
    step_id: str | None,
) -> dict[str, Any]:
    provider = get_model_provider()
    if provider is None:
        return _fallback_image_analysis()
    settings = get_settings()
    user_prompt = {
        "task": "分析维修现场图片，辅助现场维修人员判断下一步。",
        "ticket_id": work_order.ticket_id,
        "building_id": work_order.building_id,
        "device_id": work_order.device_id,
        "issue_description": work_order.issue_description,
        "suggested_action": work_order.suggested_action,
        "step_id": step_id,
        "worker_prompt": prompt,
        "output_schema": {
            "summary": "string",
            "observations": ["string"],
            "uncertainties": ["string"],
            "suggested_next_message": "string",
        },
        "rules": [
            "只根据图片中能看见的内容和工单上下文给建议。",
            "如果无法确认，不要编造读数。",
            "不要要求维修人员绕过安全规范。",
        ],
    }
    try:
        raw = await provider.chat(
            [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image_url",
                            "image_url": {"url": _data_uri(content, mime_type)},
                        },
                        {
                            "type": "text",
                            "text": json.dumps(user_prompt, ensure_ascii=False, default=str),
                        },
                    ],
                }
            ],
            model=settings.AI_VISION_MODEL,
            response_schema={"type": "object"},
            temperature=0.1,
        )
    except Exception as exc:
        logger.info("维小修图片理解降级: %s", exc)
        return _fallback_image_analysis()

    parsed = parse_json_object(raw)
    if not isinstance(parsed, dict):
        return {
            **_fallback_image_analysis(),
            "summary": raw[:800] if raw else _fallback_image_analysis()["summary"],
        }
    return {
        "summary": str(parsed.get("summary") or "").strip()[:800] or _fallback_image_analysis()["summary"],
        "observations": [str(item).strip()[:240] for item in (parsed.get("observations") or []) if str(item).strip()][:8],
        "uncertainties": [str(item).strip()[:240] for item in (parsed.get("uncertainties") or []) if str(item).strip()][:6],
        "suggested_next_message": str(parsed.get("suggested_next_message") or "").strip()[:500],
    }


async def analyze_worker_image(
    db: AsyncSession,
    *,
    ticket_id: str,
    dispatch_id: str | None,
    step_id: str | None,
    prompt: str | None,
    file: UploadFile,
    user: User,
) -> dict[str, Any]:
    work_order, dispatch_task, hall_entry = await _resolve_work_order(
        db,
        ticket_id=ticket_id,
        dispatch_id=dispatch_id,
        hall_entry_id=None,
    )
    if work_order is None:
        raise HTTPException(status_code=404, detail="工单不存在")
    _assert_worker_permission(user, work_order, dispatch_task, hall_entry)

    content, mime_type, ext = await _read_and_validate_upload(
        file,
        allowed_types=IMAGE_TYPES,
        max_bytes=MAX_IMAGE_BYTES,
        media_label="图片",
    )
    storage_url = await _save_media_file(
        content=content,
        work_order=work_order,
        user=user,
        original_name=file.filename,
        ext=ext,
        media_type="image",
    )
    analysis = await _analyze_image_with_model(
        content=content,
        mime_type=mime_type,
        prompt=prompt,
        work_order=work_order,
        step_id=step_id,
    )
    settings = get_settings()
    asset = AiMediaAsset(
        id=str(uuid.uuid4()),
        owner_user_id=user.id,
        work_order_id=work_order.id,
        dispatch_id=getattr(dispatch_task, "id", dispatch_id),
        step_id=step_id,
        media_type="image",
        original_name=file.filename,
        mime_type=mime_type,
        file_size=len(content),
        storage_url=storage_url,
        analysis_json=json.dumps(analysis, ensure_ascii=False, default=str),
        model_provider=settings.AI_PROVIDER,
        model_name=settings.AI_VISION_MODEL,
    )
    db.add(asset)
    await db.flush()
    await record_step_media_event(
        db,
        work_order=work_order,
        step_id=step_id,
        user=user,
        asset_id=asset.id,
        event_type="attach_image",
        payload={"analysis": analysis},
    )
    await db.commit()
    return {
        "asset_id": asset.id,
        "media_type": "image",
        "analysis": analysis,
        "suggested_next_message": analysis.get("suggested_next_message") or "图片已保存，请继续描述现场情况。",
    }


async def _transcribe_audio_with_model(*, content: bytes, mime_type: str) -> tuple[str, dict[str, Any]]:
    provider = get_model_provider()
    if provider is None:
        return "", {"fallback": True, "reason": "model_provider_not_configured"}
    settings = get_settings()
    try:
        raw = await provider.chat(
            [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "input_audio",
                            "input_audio": {"data": _data_uri(content, mime_type)},
                        }
                    ],
                }
            ],
            model=settings.AI_ASR_MODEL,
            extra_body={"asr_options": {"language": "zh", "enable_itn": True}},
            temperature=0,
        )
    except Exception as exc:
        logger.info("维小修语音转文字降级: %s", exc)
        return "", {"fallback": True, "reason": str(exc)}
    transcript = normalize_transcript(raw)
    return transcript, {"raw": raw[:1000], "fallback": False}


async def transcribe_worker_audio(
    db: AsyncSession,
    *,
    ticket_id: str,
    dispatch_id: str | None,
    step_id: str | None,
    file: UploadFile,
    user: User,
) -> dict[str, Any]:
    work_order, dispatch_task, hall_entry = await _resolve_work_order(
        db,
        ticket_id=ticket_id,
        dispatch_id=dispatch_id,
        hall_entry_id=None,
    )
    if work_order is None:
        raise HTTPException(status_code=404, detail="工单不存在")
    _assert_worker_permission(user, work_order, dispatch_task, hall_entry)

    content, mime_type, ext = await _read_and_validate_upload(
        file,
        allowed_types=AUDIO_TYPES,
        max_bytes=MAX_AUDIO_BYTES,
        media_label="音频",
    )
    storage_url = await _save_media_file(
        content=content,
        work_order=work_order,
        user=user,
        original_name=file.filename,
        ext=ext,
        media_type="audio",
    )
    transcript, meta = await _transcribe_audio_with_model(content=content, mime_type=mime_type)
    settings = get_settings()
    asset = AiMediaAsset(
        id=str(uuid.uuid4()),
        owner_user_id=user.id,
        work_order_id=work_order.id,
        dispatch_id=getattr(dispatch_task, "id", dispatch_id),
        step_id=step_id,
        media_type="audio",
        original_name=file.filename,
        mime_type=mime_type,
        file_size=len(content),
        storage_url=storage_url,
        transcript=transcript or None,
        analysis_json=json.dumps(meta, ensure_ascii=False, default=str),
        model_provider=settings.AI_PROVIDER,
        model_name=settings.AI_ASR_MODEL,
    )
    db.add(asset)
    await db.flush()
    await record_step_media_event(
        db,
        work_order=work_order,
        step_id=step_id,
        user=user,
        asset_id=asset.id,
        event_type="attach_audio",
        payload={"transcript": transcript},
    )
    await db.commit()
    return {
        "asset_id": asset.id,
        "media_type": "audio",
        "transcript": transcript,
        "confidence": 0.0 if not transcript else None,
        "fallback": bool(meta.get("fallback")),
    }


def build_tts_response(*, text: str, voice: str | None = None) -> dict[str, Any]:
    cleaned = " ".join((text or "").split())
    if not cleaned:
        raise HTTPException(status_code=400, detail="播报文本不能为空")
    cleaned = cleaned[:500]
    settings = get_settings()
    digest = hashlib.sha256(f"{settings.AI_TTS_MODEL}:{voice or settings.AI_TTS_VOICE}:{cleaned}".encode("utf-8")).hexdigest()[:24]
    if settings.AI_TTS_MODE != "dashscope_cosyvoice":
        return {
            "audio_url": None,
            "cache_hit": False,
            "playback_mode": "client_native",
            "text": cleaned,
            "voice": voice or settings.AI_TTS_VOICE,
            "cache_key": digest,
        }
    return {
        "audio_url": None,
        "cache_hit": False,
        "playback_mode": "client_native",
        "text": cleaned,
        "voice": voice or settings.AI_TTS_VOICE,
        "cache_key": digest,
        "warning": "服务端 CosyVoice WebSocket TTS 尚未启用，当前回退到客户端本机播报。",
    }
