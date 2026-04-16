from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.services import operator_ai_service, work_order_analysis_service
from app.services.operator_ai_service import handle_operator_ai_chat
from app.services.work_order_analysis_service import (
    build_work_order_facts_response,
    extract_work_order_analysis_scope,
)


def test_extract_work_order_analysis_scope_detects_comparison_and_building() -> None:
    scope = extract_work_order_analysis_scope(
        question="对比本周和上周公共楼工单处理效率",
        scope=None,
        previous_scope=None,
        intent=None,
        today=date(2026, 4, 14),
    )

    assert scope["intent"] == "comparison_analysis"
    assert scope["building_id"] == "public services"
    assert scope["comparison_previous"]["label"] == "上周"
    assert scope["date_from"] == date(2026, 4, 13)


@pytest.mark.asyncio
async def test_build_work_order_facts_response_returns_worker_chart(monkeypatch: pytest.MonkeyPatch) -> None:
    now = datetime(2026, 4, 14, 9, 0, tzinfo=timezone.utc)
    dispatch_rows = [
        {
            "dispatch_id": "dispatch-1",
            "work_order_id": "wo-1",
            "attempt_no": 1,
            "dispatch_mode": "manual",
            "dispatch_status": "completed",
            "team_id": "team-1",
            "worker_id": "ops-1",
            "transfer_from_dispatch_id": None,
            "support_team_id": None,
            "assigned_at": now - timedelta(days=3, hours=3),
            "accepted_at": now - timedelta(days=3, hours=2, minutes=50),
            "arrived_at": now - timedelta(days=3, hours=2, minutes=20),
            "processing_started_at": now - timedelta(days=3, hours=2),
            "completed_at": now - timedelta(days=3, hours=1),
            "closed_at": now - timedelta(days=3, hours=1),
            "finish_deadline_at": now - timedelta(days=3, minutes=30),
            "timeout_level": "normal",
            "latest_note": "已处理",
            "ticket_id": "WO-001",
            "building_id": "Fox_public_Henry",
            "issue_description": "公共楼空调不制冷",
            "priority": "high",
            "work_order_status": "completed",
            "work_order_created_at": now - timedelta(days=3, hours=4),
            "worker_name": "张工",
            "team_name": "暖通班",
        },
        {
            "dispatch_id": "dispatch-2",
            "work_order_id": "wo-2",
            "attempt_no": 1,
            "dispatch_mode": "manual",
            "dispatch_status": "completed",
            "team_id": "team-2",
            "worker_id": "ops-2",
            "transfer_from_dispatch_id": None,
            "support_team_id": None,
            "assigned_at": now - timedelta(days=2, hours=5),
            "accepted_at": now - timedelta(days=2, hours=4, minutes=55),
            "arrived_at": now - timedelta(days=2, hours=4, minutes=30),
            "processing_started_at": now - timedelta(days=2, hours=4),
            "completed_at": now - timedelta(days=2, hours=2),
            "closed_at": now - timedelta(days=2, hours=2),
            "finish_deadline_at": now - timedelta(days=2, hours=3),
            "timeout_level": "overdue",
            "latest_note": "处理较慢",
            "ticket_id": "WO-002",
            "building_id": "Fox_public_Henry",
            "issue_description": "公共楼漏水",
            "priority": "medium",
            "work_order_status": "completed",
            "work_order_created_at": now - timedelta(days=2, hours=6),
            "worker_name": "李工",
            "team_name": "给排水班",
        },
    ]
    work_order_rows = [
        {
            "work_order_id": "wo-1",
            "ticket_id": "WO-001",
            "building_id": "Fox_public_Henry",
            "issue_description": "公共楼空调不制冷",
            "priority": "high",
            "status": "completed",
            "created_at": now - timedelta(days=3, hours=4),
            "closed_at": now - timedelta(days=3, hours=1),
        },
        {
            "work_order_id": "wo-2",
            "ticket_id": "WO-002",
            "building_id": "Fox_public_Henry",
            "issue_description": "公共楼漏水",
            "priority": "medium",
            "status": "completed",
            "created_at": now - timedelta(days=2, hours=6),
            "closed_at": now - timedelta(days=2, hours=2),
        },
    ]

    monkeypatch.setattr(work_order_analysis_service, "_load_dispatch_rows", AsyncMock(return_value=dispatch_rows))
    monkeypatch.setattr(work_order_analysis_service, "_load_work_order_rows", AsyncMock(return_value=work_order_rows))
    monkeypatch.setattr(work_order_analysis_service, "_load_hall_rows", AsyncMock(return_value=[]))
    monkeypatch.setattr(work_order_analysis_service, "_load_experience_rows", AsyncMock(return_value=[]))

    payload = await build_work_order_facts_response(
        SimpleNamespace(),
        question="这个月谁处理得最多",
        scope={
            "date_from": date(2026, 4, 1),
            "date_to": date(2026, 4, 30),
            "building_id": "Public",
        },
        include_chart=True,
    )

    assert payload["intent"] == "worker_performance"
    assert payload["chart"]["type"] == "bar"
    assert payload["metrics"]["rows"][0]["worker_name"] == "张工"
    assert payload["facts"]["scope"]["building_id"] == "public services"


@pytest.mark.asyncio
async def test_build_work_order_facts_response_returns_open_work_order_analysis(monkeypatch: pytest.MonkeyPatch) -> None:
    now = datetime(2026, 4, 14, 9, 0, tzinfo=timezone.utc)
    dispatch_rows = [
        {
            "dispatch_id": "dispatch-open-1",
            "work_order_id": "wo-open-1",
            "attempt_no": 1,
            "dispatch_mode": "manual",
            "dispatch_status": "processing",
            "team_id": "team-1",
            "worker_id": "ops-1",
            "transfer_from_dispatch_id": None,
            "support_team_id": None,
            "assigned_at": now - timedelta(days=1, hours=3),
            "accepted_at": now - timedelta(days=1, hours=2, minutes=50),
            "arrived_at": now - timedelta(days=1, hours=2, minutes=20),
            "processing_started_at": now - timedelta(days=1, hours=2),
            "completed_at": None,
            "closed_at": None,
            "finish_deadline_at": now - timedelta(hours=2),
            "timeout_level": "overdue",
            "latest_note": "处理中",
            "ticket_id": "WO-OPEN-001",
            "building_id": "Fox_public_Henry",
            "issue_description": "公共楼空调温度异常",
            "priority": "high",
            "work_order_status": "processing",
            "work_order_created_at": now - timedelta(days=1, hours=4),
            "worker_name": "张工",
            "team_name": "暖通班",
        },
        {
            "dispatch_id": "dispatch-open-2",
            "work_order_id": "wo-open-2",
            "attempt_no": 1,
            "dispatch_mode": "manual",
            "dispatch_status": "waiting_support",
            "team_id": "team-2",
            "worker_id": "ops-2",
            "transfer_from_dispatch_id": None,
            "support_team_id": None,
            "assigned_at": now - timedelta(days=2, hours=2),
            "accepted_at": now - timedelta(days=2, hours=1, minutes=40),
            "arrived_at": None,
            "processing_started_at": None,
            "completed_at": None,
            "closed_at": None,
            "finish_deadline_at": now + timedelta(hours=5),
            "timeout_level": "normal",
            "latest_note": "等待协同",
            "ticket_id": "WO-OPEN-002",
            "building_id": "Fox_public_Henry",
            "issue_description": "公共楼漏水",
            "priority": "medium",
            "work_order_status": "waiting_support",
            "work_order_created_at": now - timedelta(days=2, hours=4),
            "worker_name": "李工",
            "team_name": "给排水班",
        },
    ]
    work_order_rows = [
        {
            "work_order_id": "wo-open-1",
            "ticket_id": "WO-OPEN-001",
            "building_id": "Fox_public_Henry",
            "issue_description": "公共楼空调温度异常",
            "priority": "high",
            "status": "processing",
            "created_at": now - timedelta(days=1, hours=4),
            "closed_at": None,
        },
        {
            "work_order_id": "wo-open-2",
            "ticket_id": "WO-OPEN-002",
            "building_id": "Fox_public_Henry",
            "issue_description": "公共楼漏水",
            "priority": "medium",
            "status": "waiting_support",
            "created_at": now - timedelta(days=2, hours=4),
            "closed_at": None,
        },
    ]

    monkeypatch.setattr(work_order_analysis_service, "_load_dispatch_rows", AsyncMock(return_value=dispatch_rows))
    monkeypatch.setattr(work_order_analysis_service, "_load_work_order_rows", AsyncMock(return_value=work_order_rows))
    monkeypatch.setattr(work_order_analysis_service, "_load_hall_rows", AsyncMock(return_value=[]))
    monkeypatch.setattr(work_order_analysis_service, "_load_experience_rows", AsyncMock(return_value=[]))

    payload = await build_work_order_facts_response(
        SimpleNamespace(),
        question="未完成工单情况",
        scope={
            "date_from": date(2026, 4, 1),
            "date_to": date(2026, 4, 30),
        },
        include_chart=True,
    )

    assert payload["intent"] == "open_work_order_analysis"
    assert payload["chart"]["type"] == "bar"
    assert payload["metrics"]["summary"]["open_total"] == 2
    assert payload["metrics"]["summary"]["processing_count"] == 1
    assert payload["metrics"]["summary"]["waiting_support_count"] == 1


@pytest.mark.asyncio
async def test_handle_operator_ai_chat_reuses_previous_analysis_scope(monkeypatch: pytest.MonkeyPatch) -> None:
    previous_scope = {
        "intent": "worker_performance",
        "building_id": "public services",
        "date_from": "2026-04-01",
        "date_to": "2026-04-30",
        "date_label": "本月（2026-04-01 至 2026-04-30）",
    }
    db = SimpleNamespace(
        get=AsyncMock(return_value=SimpleNamespace(session_state_json=json.dumps({"analysis_scope": previous_scope}))),
        commit=AsyncMock(),
    )
    monkeypatch.setattr(operator_ai_service, "_ensure_session", AsyncMock())
    monkeypatch.setattr(operator_ai_service, "_append_message", AsyncMock())
    mock_build = AsyncMock(
        return_value={
            "intent": "team_performance",
            "answer": "已按班组拆分。",
            "facts": {"scope": {"building_id": "public services", "group_by": "team"}},
            "metrics": {"rows": []},
            "chart": {"type": "bar"},
            "evidence_refs": ["dispatch_tasks"],
            "suggested_followups": ["查看超时工单"],
        }
    )
    monkeypatch.setattr(operator_ai_service, "build_work_order_facts_response", mock_build)

    response = await handle_operator_ai_chat(
        db,
        message="那按班组拆开",
        session_id="opai-phase4",
        ticket_id=None,
        scope=None,
        include_evidence=True,
        include_chart=True,
        user=SimpleNamespace(id="manager-1", role="manager"),
    )

    assert response["answer_type"] == "team_performance"
    assert response["chart"]["type"] == "bar"
    assert mock_build.await_args.kwargs["scope"]["building_id"] == "public services"
    assert mock_build.await_args.kwargs["scope"]["group_by"] == "team"


@pytest.mark.asyncio
async def test_handle_operator_ai_chat_returns_greeting_for_small_talk(monkeypatch: pytest.MonkeyPatch) -> None:
    db = SimpleNamespace(
        get=AsyncMock(return_value=None),
        commit=AsyncMock(),
    )
    monkeypatch.setattr(operator_ai_service, "_ensure_session", AsyncMock())
    monkeypatch.setattr(operator_ai_service, "_append_message", AsyncMock())
    mock_build = AsyncMock()
    monkeypatch.setattr(operator_ai_service, "build_work_order_facts_response", mock_build)

    response = await handle_operator_ai_chat(
        db,
        message="你好",
        session_id="opai-greeting",
        ticket_id=None,
        scope=None,
        include_evidence=True,
        include_chart=True,
        user=SimpleNamespace(id="manager-1", role="manager"),
    )

    assert response["answer_type"] == "greeting"
    assert response["chart"] is None
    assert "只做只读问询和运营分析" in response["answer"]
    assert "未完成工单情况" in response["suggested_followups"]
    mock_build.assert_not_awaited()
