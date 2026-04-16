from types import SimpleNamespace
from unittest.mock import AsyncMock
from pathlib import Path

import pytest

from app.core.config import get_settings
from app.services import ai_media_service
from app.services.ai_media_service import build_tts_response, normalize_transcript
from app.services.maintenance_guidance_service import (
    _fallback_guidance_reply,
    _fallback_step_plan,
    _is_guidance_ready,
    _normalize_step_plan,
)


def _work_order(**overrides):
    values = {
        "ticket_id": "WO-20260403-005",
        "building_id": "公共楼",
        "device_id": "PUMP-01",
        "issue_description": "供水温度偏离",
        "suggested_action": "检查传感器与水泵运行",
        "priority": "high",
        "status": "dispatched",
        "processing_started_at": None,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_worker_ai_phase2_fallback_plan_has_stable_steps():
    plan = _fallback_step_plan(work_order=_work_order(), rag_refs=[])

    assert plan["guide_version"] == 1
    assert len(plan["steps"]) >= 5
    assert plan["steps"][0]["id"] == "step_1"
    assert all(step["status"] == "pending" for step in plan["steps"])


def test_worker_ai_phase2_hvac_fallback_plan_is_domain_specific():
    plan = _fallback_step_plan(
        work_order=_work_order(
            issue_description="暖通能耗异常偏高，根因分析：冷水机组效能衰退",
            suggested_action="检查冷水机组 COP，清洗冷凝器/蒸发器，检查制冷剂充注量",
        ),
        rag_refs=[],
    )

    titles = [step["title"] for step in plan["steps"]]
    assert "复核冷水机组 COP 和负荷匹配" in titles
    assert "检查冷凝器、蒸发器和水侧换热" in titles
    assert "检查制冷剂与压缩机运行迹象" in titles


def test_worker_ai_phase2_normalize_drops_invalid_model_steps():
    raw = {
        "summary": "排查供水温度",
        "steps": [
            {"id": "bad", "title": "", "instruction": ""},
            {"id": "custom_1", "title": "核对读数", "instruction": "查看现场温度表", "status": "done"},
        ],
    }

    normalized = _normalize_step_plan(raw, work_order=_work_order(), rag_refs=[])

    assert normalized["summary"] == "排查供水温度"
    assert normalized["steps"][0]["id"] == "custom_1"
    assert normalized["steps"][0]["status"] == "pending"


def test_worker_ai_phase2_guidance_ready_accepts_dispatch_processing_start_time():
    work_order = _work_order(processing_started_at=None)
    dispatch_task = SimpleNamespace(dispatch_status="accepted", processing_started_at="2026-04-09T04:47:00Z")

    assert _is_guidance_ready(work_order, dispatch_task) is True


@pytest.mark.asyncio
async def test_worker_ai_phase2_tts_response_uses_client_native_fallback(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("AI_TTS_MODE", "client_native")
    get_settings.cache_clear()
    try:
        response = await build_tts_response(text="下一步请检查供水阀门开度。")
    finally:
        get_settings.cache_clear()

    assert response["playback_mode"] == "client_native"
    assert response["audio_url"] is None
    assert "下一步" in response["text"]


@pytest.mark.asyncio
async def test_worker_ai_phase2_tts_response_returns_server_audio(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("AI_TTS_MODE", "dashscope_cosyvoice")
    monkeypatch.setenv("AI_API_KEY", "test-key")
    monkeypatch.setenv("AI_TTS_MODEL", "cosyvoice-v2")
    monkeypatch.setenv("AI_TTS_VOICE", "longxiaochun_v2")
    cache_root = Path("backend/tests/.tmp/tts")
    cache_root.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(ai_media_service, "TTS_CACHE_ROOT", cache_root)
    monkeypatch.setattr(
        ai_media_service,
        "_synthesize_dashscope_tts",
        AsyncMock(return_value=b"fake-audio"),
    )
    get_settings.cache_clear()
    try:
        response = await build_tts_response(text="请按步骤继续检查供水传感器。")
    finally:
        get_settings.cache_clear()

    assert response["playback_mode"] == "server_audio"
    assert response["audio_url"] == f"/api/worker-ai/tts/cache/{response['cache_key']}.mp3"
    assert (cache_root / f"{response['cache_key']}.mp3").read_bytes() == b"fake-audio"


def test_worker_ai_phase2_transcript_filters_fillers():
    assert normalize_transcript("嗯。") == ""
    assert normalize_transcript(" 我 已 到 场 ") == "我 已 到 场"


def test_worker_ai_phase2_guidance_fallback_handles_leak_observation():
    reply = _fallback_guidance_reply(
        message="压缩机一直往外流",
        work_order=_work_order(
            issue_description="暖通能耗异常偏高，根因分析：冷水机组效能衰退",
            suggested_action="检查冷水机组 COP，清洗冷凝器/蒸发器，检查制冷剂充注量",
        ),
        current_step={"id": "step_2", "title": "核对 BMS 与机组面板关键读数"},
    )

    assert reply["suggested_step_status"] == "uncertain"
    assert "外流" in reply["answer"]
    assert "接单" not in reply["answer"]
    assert "到场" not in reply["answer"]
