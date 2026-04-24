from __future__ import annotations

import json
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.services import operator_ai_service
from app.services.maintenance_experience_service import looks_like_experience_query
from app.services.maintenance_guidance_service import serialize_step_plan
from app.services.operator_ai_service import handle_operator_ai_chat


def test_serialize_step_plan_includes_experience_recommendations():
    plan = SimpleNamespace(
        id="plan-1",
        dispatch_id="dispatch-1",
        status="active",
        version=2,
        summary="先核对现场温度表。",
        root_cause_candidates_json="[]",
        steps_json="[]",
        safety_notes_json="[]",
        generated_from_json=json.dumps(
            {
                "experience_recommendations": [
                    {
                        "experience_id": "exp-1",
                        "source_work_order_id": "WO-20260403-005",
                        "organized_text": "先核对现场温度表。",
                        "confidence": 0.86,
                    }
                ]
            },
            ensure_ascii=False,
        ),
        model_provider="local_fallback",
        model_name="local_template",
        updated_at=datetime.now(timezone.utc),
    )

    serialized = serialize_step_plan(plan)

    assert serialized["experience_recommendations"][0]["experience_id"] == "exp-1"
    assert serialized["experience_recommendations"][0]["confidence"] == 0.86


def test_serialize_step_plan_enriches_legacy_experience_source_contributor():
    plan = SimpleNamespace(
        id="plan-1",
        dispatch_id="dispatch-1",
        status="active",
        version=2,
        summary="先核对现场温度表。",
        root_cause_candidates_json="[]",
        steps_json="[]",
        safety_notes_json="[]",
        generated_from_json=json.dumps(
            {
                "experience_recommendations": [
                    {
                        "experience_id": "exp-1",
                        "source_work_order_id": "WO-20260403-001",
                        "organized_text": "先核对现场温度表。",
                        "confidence": 0.86,
                    }
                ]
            },
            ensure_ascii=False,
        ),
        model_provider="local_fallback",
        model_name="local_template",
        updated_at=datetime.now(timezone.utc),
    )

    serialized = serialize_step_plan(plan)

    assert serialized["experience_recommendations"][0]["source_contributor_name"] == "刘工"


def test_looks_like_experience_query_matches_history_questions():
    assert looks_like_experience_query("最近有哪些供水温度偏离的经验？") is True
    assert looks_like_experience_query("这张工单当前是谁在处理？") is False


@pytest.mark.asyncio
async def test_operator_ai_experience_query_returns_experience_summary(monkeypatch: pytest.MonkeyPatch):
    db = SimpleNamespace(commit=AsyncMock(), execute=AsyncMock())
    user = SimpleNamespace(id="admin-1", role="admin")

    monkeypatch.setattr(operator_ai_service, "_ensure_session", AsyncMock())
    monkeypatch.setattr(operator_ai_service, "_append_message", AsyncMock())
    mock_answer = AsyncMock(
        return_value={
            "answer": "最近的相关经验如下：\n1. 王工的经验：先核对现场温度表（来源 WO-20260403-005，匹配 0.86，复用 3，有用 2，启用）",
            "facts": {"items": [{"id": "exp-1"}]},
            "evidence_refs": ["maintenance_experiences"],
            "suggested_followups": ["查看某条经验的来源工单"],
        }
    )
    monkeypatch.setattr(operator_ai_service, "build_operator_experience_answer", mock_answer)

    response = await handle_operator_ai_chat(
        db,
        message="最近有哪些供水温度偏离的经验？",
        session_id="opai_test",
        ticket_id=None,
        scope=None,
        include_evidence=True,
        user=user,
    )

    assert response["answer_type"] == "maintenance_experience_summary"
    assert response["readonly"] is True
    assert response["facts"]["items"][0]["id"] == "exp-1"
