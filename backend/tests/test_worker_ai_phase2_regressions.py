from __future__ import annotations

import json
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.services import operator_ai_service, worker_ai_service
from app.services.operator_ai_service import handle_operator_ai_chat
from app.services.worker_ai_service import (
    _PENDING_ACTIONS,
    _is_worker_ai_action_history_message,
    _validate_worker_action_availability,
    handle_worker_ai_chat,
)


class _ScalarResult:
    def __init__(self, *, scalar=None, items=None):
        self._scalar = scalar
        self._items = items or []

    def scalar_one_or_none(self):
        return self._scalar

    def scalars(self):
        return SimpleNamespace(all=lambda: self._items)


def test_worker_ai_validation_blocks_duplicate_arrive_after_processing():
    message = _validate_worker_action_availability(
        action="arrive",
        work_order=SimpleNamespace(id="wo-1", ticket_id="WO-001"),
        dispatch_task=SimpleNamespace(id="dispatch-1", dispatch_status="processing"),
        hall_entry=None,
    )

    assert message is not None
    assert "无需重复确认到场" in message


def test_worker_ai_history_filters_action_flow_messages_but_keeps_guidance():
    action_message = SimpleNamespace(
        role="assistant",
        content="当前工单已开始处理，无需重复开始。",
        content_type="text",
    )
    tool_result = SimpleNamespace(
        role="assistant",
        content="已完成“开始处理”。",
        content_type="tool_result",
    )
    guidance_message = SimpleNamespace(
        role="assistant",
        content="先看控制屏读数，再拍一张面板照片。",
        content_type="guidance_reply",
    )

    assert _is_worker_ai_action_history_message(action_message) is True
    assert _is_worker_ai_action_history_message(tool_result) is True
    assert _is_worker_ai_action_history_message(guidance_message) is False


@pytest.mark.asyncio
async def test_worker_ai_confirm_invalid_pending_action_returns_chat_not_500(
    monkeypatch: pytest.MonkeyPatch,
):
    session_id = "wx_test_session"
    user = SimpleNamespace(id="worker-1", role="ops")
    work_order = SimpleNamespace(id="wo-1", ticket_id="WO-001")
    dispatch_task = SimpleNamespace(
        id="dispatch-1",
        assigned_to="worker-1",
        dispatch_status="processing",
    )
    db = SimpleNamespace(commit=AsyncMock())

    monkeypatch.setattr(
        worker_ai_service,
        "_resolve_work_order",
        AsyncMock(return_value=(work_order, dispatch_task, None)),
    )
    monkeypatch.setattr(worker_ai_service, "_ensure_session", AsyncMock())
    monkeypatch.setattr(worker_ai_service, "_append_message", AsyncMock())
    monkeypatch.setattr(worker_ai_service, "_record_action_audit", AsyncMock())

    _PENDING_ACTIONS[session_id] = {
        "action": "arrive",
        "action_label": "确认到场",
        "ticket_id": work_order.ticket_id,
        "work_order_id": work_order.id,
        "dispatch_id": dispatch_task.id,
        "hall_entry_id": None,
        "stage": "awaiting_confirmation",
    }

    try:
        response = await handle_worker_ai_chat(
            db,
            message="确认",
            session_id=session_id,
            ticket_id=work_order.ticket_id,
            dispatch_id=dispatch_task.id,
            hall_entry_id=None,
            client_context=None,
            user=user,
        )
    finally:
        _PENDING_ACTIONS.pop(session_id, None)

    assert response["message_type"] == "chat"
    assert response["executed"] is False
    assert "无需重复确认到场" not in response["answer"]
    assert "现场排查" in response["answer"]


@pytest.mark.asyncio
async def test_operator_ai_guidance_query_reads_worker_guidance_records(
    monkeypatch: pytest.MonkeyPatch,
):
    now = datetime.now(timezone.utc)
    plan = SimpleNamespace(
        id="plan-1",
        status="active",
        version=2,
        summary="请先核验传感器和控制器读数。",
        steps_json=json.dumps(
            [
                {"id": "step_1", "title": "核对传感器", "status": "completed"},
                {"id": "step_2", "title": "检查控制器", "status": "pending", "note": "BMS读数波动"},
            ],
            ensure_ascii=False,
        ),
        updated_at=now,
    )
    event = SimpleNamespace(
        step_id="step_2",
        event_type="note",
        note="BMS读数波动",
        created_at=now,
    )
    image = SimpleNamespace(media_type="image", created_at=now)
    audio = SimpleNamespace(media_type="audio", created_at=now)
    db = SimpleNamespace(
        execute=AsyncMock(
            side_effect=[
                _ScalarResult(scalar=plan),
                _ScalarResult(items=[event]),
                _ScalarResult(items=[image, audio]),
            ]
        ),
        commit=AsyncMock(),
    )
    user = SimpleNamespace(id="admin-1", role="admin")

    monkeypatch.setattr(operator_ai_service, "_ensure_session", AsyncMock())
    monkeypatch.setattr(operator_ai_service, "_append_message", AsyncMock())
    monkeypatch.setattr(
        operator_ai_service,
        "build_work_order_review_context",
        AsyncMock(
            return_value={
                "work_order": {"id": "wo-1", "ticket_id": "WO-001"},
                "current_dispatch": {"dispatch_status": "processing"},
            }
        ),
    )

    response = await handle_operator_ai_chat(
        db,
        message="WO-001 这张工单的维修指导做到哪一步了？",
        session_id="opai_test",
        ticket_id="WO-001",
        scope=None,
        include_evidence=True,
        user=user,
    )

    assert response["answer_type"] == "worker_guidance_record"
    assert response["readonly"] is True
    assert response["facts"]["plan"]["current_step"]["title"] == "检查控制器"
    assert response["facts"]["media_summary"] == {"image_count": 1, "audio_count": 1}
    assert "worker_ai_step_events" in response["evidence_refs"]
