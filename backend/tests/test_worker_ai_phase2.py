import json
from types import SimpleNamespace
from unittest.mock import AsyncMock
from pathlib import Path

import pytest

from app.core.config import get_settings
from app.services import ai_media_service, maintenance_guidance_service
from app.services.ai_media_service import build_tts_response, normalize_transcript
from app.services.maintenance_experience_service import resolve_experience_source_contributor_name
from app.services.maintenance_guidance_service import (
    _build_experience_reference_reply,
    _build_workflow_profile,
    _build_ddc_help_reply,
    _extract_plan_experience_recommendations,
    _fallback_guidance_reply,
    _fallback_step_plan,
    _generate_guidance_reply_with_model,
    _is_guidance_ready,
    _looks_like_ddc_help_request,
    _normalize_step_plan,
    _sanitize_guidance_reply,
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
    assert len(plan["steps"]) >= 4
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


def test_worker_ai_phase2_classifies_workflow_profiles_by_anomaly_type():
    night_profile = _build_workflow_profile(
        _work_order(
            issue_description="夜间能耗异常，怀疑三层照明未关",
            suggested_action="确认是否有人使用并检查照明状态",
        )
    )
    sensor_profile = _build_workflow_profile(
        _work_order(
            issue_description="供水温度读数异常，怀疑传感器漂移",
            suggested_action="核对就地温度表和温度传感器接线",
        )
    )
    schedule_profile = _build_workflow_profile(
        _work_order(
            issue_description="系统显示 Unoccupied，但现场仍在正常使用",
            suggested_action="核实运行模式与现场实际占用是否一致",
        )
    )

    assert night_profile["profile_key"] == "night_energy"
    assert sensor_profile["profile_key"] == "sensor_display"
    assert schedule_profile["profile_key"] == "schedule_mode"


def test_worker_ai_phase2_night_energy_fallback_plan_focuses_on_onsite_usage_and_loads():
    plan = _fallback_step_plan(
        work_order=_work_order(
            building_id="教学楼 A",
            device_id="照明回路",
            issue_description="夜间异常用电偏高，怀疑教室照明未关闭",
            suggested_action="确认现场是否有人使用并检查照明状态",
        ),
        rag_refs=[],
    )

    titles = [step["title"] for step in plan["steps"]]
    instructions = " ".join(step["instruction"] for step in plan["steps"])

    assert "确认现场是否仍在实际使用" in titles
    assert "确认哪些负载仍处于开启状态" in titles
    assert "排程表" not in plan["steps"][0]["instruction"]
    assert "确认是否有人在用" in plan["steps"][0]["instruction"]
    assert "照明" in instructions


def test_worker_ai_phase2_sensor_display_fallback_plan_focuses_on_reading_comparison():
    plan = _fallback_step_plan(
        work_order=_work_order(
            issue_description="冷冻水供水温度偏差，怀疑 CHW Supply Temp Sensor 读数漂移",
            suggested_action="核对现场温度表与系统点位显示，检查传感器安装和接线",
        ),
        rag_refs=[],
    )

    titles = [step["title"] for step in plan["steps"]]
    instructions = " ".join(step["instruction"] for step in plan["steps"])

    assert "用独立参考读数复核偏差" in titles
    assert "判断读数是否由真实工况造成" in titles
    assert "按读数关系决定维修或协同" in titles
    assert "传感器/显示/计量偏差" in plan["summary"]
    assert "供回水温差" in instructions
    assert "点位映射" in instructions


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


def test_worker_ai_phase2_sanitize_guidance_reply_hides_internal_fields():
    reply = _sanitize_guidance_reply(
        {
            "answer": "师傅，系统里只确认step_1完成，step_2标了completed但还没传回读数。",
            "suggested_next_message": "先别急，pending 的信息还没补齐。",
            "suggested_followups": [
                "step_1 还差什么？",
                "completed 的是哪一步？",
            ],
        }
    )

    assert "step_1" not in reply["answer"]
    assert "completed" not in reply["answer"]
    assert "系统里只确认" not in reply["answer"]
    assert "pending" not in (reply["suggested_next_message"] or "")
    assert all("step_" not in item for item in reply["suggested_followups"])


def test_worker_ai_phase2_detects_ddc_help_request_and_returns_non_login_reply():
    assert _looks_like_ddc_help_request("我不会查DDC，怎么办") is True
    assert _looks_like_ddc_help_request("查不到点位，还能怎么继续") is True

    reply = _build_ddc_help_reply({"title": "核验 DDC 点位映射与温度信号链路"})

    assert "登录" in reply["answer"]
    assert "点位" in reply["answer"]
    assert "就地面板" in reply["answer"]
    assert "Occupied" not in reply["answer"]
    assert "Holiday" not in reply["answer"]
    assert "BA 中控室" not in reply["answer"]


def test_worker_ai_phase2_extracts_plan_experience_recommendations():
    plan = SimpleNamespace(
        generated_from_json='{"experience_recommendations":[{"experience_id":"exp-1","organized_text":"先核对现场读数。"}]}'
    )

    recommendations = _extract_plan_experience_recommendations(plan)

    assert recommendations == [{"experience_id": "exp-1", "organized_text": "先核对现场读数。"}]


def test_worker_ai_phase2_experience_reference_reply_uses_retrieved_items():
    reply = _build_experience_reference_reply(
        [
            {
                "experience_id": "exp-1",
                "source_work_order_id": "WO-20260403-005",
                "source_contributor_name": "王工",
                "organized_text": "类似能耗突增先核对现场是否有人使用，再确认未关闭负载。",
                "confidence": 0.86,
                "helpful_count": 2,
                "safety_notes": ["不要在未确认现场用电边界前直接断电。"],
                "conflict_flags": [{"message": "未说明电气隔离许可。"}],
            }
        ]
    )

    assert "召回到 1 条经验" in reply["answer"]
    assert "类似能耗突增" in reply["answer"]
    assert "王工的经验" in reply["answer"]
    assert "WO-20260403-005" in reply["answer"]
    assert "匹配 0.86" in reply["answer"]
    assert "采纳前要留意" in reply["answer"]
    assert "引用前" not in reply["answer"]


def test_worker_ai_phase2_experience_reference_reply_handles_empty_results():
    reply = _build_experience_reference_reply([])

    assert "没有召回到" in reply["answer"]
    assert "编造" not in reply["answer"]


def test_worker_ai_phase2_experience_source_contributor_demo_override():
    assert resolve_experience_source_contributor_name({"source_work_order_id": "WO-20260403-001"}) == "刘工"
    assert resolve_experience_source_contributor_name({"source_work_order_id": "WO-20260403-002"}) == "王工"
    assert (
        resolve_experience_source_contributor_name(
            {"source_work_order_id": "WO-20260403-001", "source_contributor_name": "王工"}
        )
        == "刘工"
    )


def test_worker_ai_phase2_experience_reference_reply_corrects_stale_contributor():
    reply = _build_experience_reference_reply(
        [
            {
                "experience_id": "exp-1",
                "source_work_order_id": "WO-20260403-002",
                "source_contributor_name": "刘工",
                "organized_text": "公共楼供回水温差大时先查阀门开度。",
                "confidence": 0.43,
            },
            {
                "experience_id": "exp-2",
                "source_work_order_id": "WO-20260403-001",
                "source_contributor_name": "王工",
                "organized_text": "公共楼空调跑通系统能耗异常时先核对水泵频率。",
                "confidence": 0.35,
            },
        ]
    )

    assert "1. 王工的经验" in reply["answer"]
    assert "2. 刘工的经验" in reply["answer"]
    assert "真实的现场图片" in reply["answer"]


@pytest.mark.asyncio
async def test_worker_ai_phase2_guidance_model_prompt_includes_experience_recommendations(monkeypatch: pytest.MonkeyPatch):
    captured: dict[str, object] = {}

    class FakeProvider:
        async def chat(self, messages, **kwargs):
            captured["user_prompt"] = json.loads(messages[1]["content"])
            return '{"answer":"参考经验先核对现场读数。"}'

    monkeypatch.setattr(maintenance_guidance_service, "get_model_provider", lambda: FakeProvider())
    plan = SimpleNamespace(
        id="plan-1",
        summary="先核对现场。",
        root_cause_candidates_json="[]",
        safety_notes_json="[]",
    )
    recommendations = [
        {
            "experience_id": "exp-1",
            "organized_text": "先核对现场读数。",
            "confidence": 0.86,
        }
    ]

    await _generate_guidance_reply_with_model(
        message="有没有经验可以参考的",
        context={"work_order": {"ticket_id": "WO-1"}},
        plan=plan,
        steps=[{"id": "step_1", "title": "核对现场", "instruction": "先看现场"}],
        current_step={"id": "step_1", "title": "核对现场", "instruction": "先看现场"},
        recent_events=[],
        experience_recommendations=recommendations,
    )

    assert captured["user_prompt"]["experience_recommendations"] == recommendations
