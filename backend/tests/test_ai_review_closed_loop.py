from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.api import routes_workorder
from app.services import ai_review_service, auto_work_order_service


class _FakeScalarResult:
    def __init__(self, *, scalar=None, rows=None):
        self._scalar = scalar
        self._rows = rows or []

    def scalar_one_or_none(self):
        return self._scalar

    def fetchall(self):
        return list(self._rows)


class _AsyncSessionContext:
    def __init__(self, db):
        self._db = db

    async def __aenter__(self):
        return self._db

    async def __aexit__(self, exc_type, exc, tb):
        return False


def _work_order(**overrides):
    now = datetime.now(timezone.utc)
    data = {
        "id": "wo-1",
        "ticket_id": "WO-001",
        "status": "pending_review",
        "ai_decision": None,
        "ai_reviewed_at": None,
        "building_id": "Fox_public_Henry",
        "priority": "high",
        "issue_description": "空调异常",
        "suggested_action": "安排暖通班排查",
        "dispatch_profile_json": None,
        "created_at": now,
    }
    data.update(overrides)
    return SimpleNamespace(**data)


@pytest.mark.asyncio
async def test_execute_auto_dispatch_after_ai_approval_commits_when_action_taken(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    work_order = _work_order(status="pending_dispatch", ai_decision="approve")
    db = SimpleNamespace(
        get=AsyncMock(return_value=work_order),
        commit=AsyncMock(),
        rollback=AsyncMock(),
    )
    mock_execute = AsyncMock(return_value={"action_taken": True, "executed": True, "reason": "auto_dispatch_executed"})
    monkeypatch.setattr(ai_review_service, "execute_auto_dispatch", mock_execute)

    result = await ai_review_service.execute_auto_dispatch_after_ai_approval(
        db,
        work_order_id=work_order.id,
        trigger_source="test_case",
    )

    assert result["action_taken"] is True
    db.commit.assert_awaited_once()
    db.rollback.assert_not_awaited()
    assert mock_execute.await_args.kwargs["work_order"] is work_order


@pytest.mark.asyncio
async def test_execute_auto_dispatch_after_ai_approval_rolls_back_when_no_action(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    work_order = _work_order(status="pending_dispatch", ai_decision="approve")
    db = SimpleNamespace(
        get=AsyncMock(return_value=work_order),
        commit=AsyncMock(),
        rollback=AsyncMock(),
    )
    monkeypatch.setattr(
        ai_review_service,
        "execute_auto_dispatch",
        AsyncMock(return_value={"action_taken": False, "executed": False, "reason": "auto_dispatch_execution_disabled"}),
    )
    mock_audit = AsyncMock()
    monkeypatch.setattr(ai_review_service, "write_work_order_audit_log", mock_audit)

    result = await ai_review_service.execute_auto_dispatch_after_ai_approval(
        db,
        work_order_id=work_order.id,
        trigger_source="test_case",
    )

    assert result["action_taken"] is False
    assert result["observation_recorded"] is True
    db.commit.assert_awaited_once()
    db.rollback.assert_awaited_once()
    mock_audit.assert_awaited_once()


@pytest.mark.asyncio
async def test_execute_auto_dispatch_after_ai_approval_records_rollout_skip(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    work_order = _work_order(
        status="pending_dispatch",
        ai_decision="approve",
        priority="medium",
        dispatch_profile_json='{"required_skills":["hvac"]}',
    )
    db = SimpleNamespace(
        get=AsyncMock(return_value=work_order),
        commit=AsyncMock(),
        rollback=AsyncMock(),
    )
    monkeypatch.setattr(ai_review_service.settings, "AUTO_DISPATCH_ALLOWED_BUILDINGS", ["Fox_public_Henry"])
    monkeypatch.setattr(ai_review_service.settings, "AUTO_DISPATCH_ALLOWED_PRIORITIES", ["high"])
    monkeypatch.setattr(ai_review_service.settings, "AUTO_DISPATCH_ALLOWED_REQUIRED_SKILLS", [])
    monkeypatch.setattr(ai_review_service.settings, "AUTO_DISPATCH_CREATE_HALL_ON_ROLLOUT_SKIP", False)
    mock_audit = AsyncMock()
    monkeypatch.setattr(ai_review_service, "write_work_order_audit_log", mock_audit)
    mock_execute = AsyncMock()
    monkeypatch.setattr(ai_review_service, "execute_auto_dispatch", mock_execute)

    result = await ai_review_service.execute_auto_dispatch_after_ai_approval(
        db,
        work_order_id=work_order.id,
        trigger_source="test_case",
    )

    assert result["reason"] == "auto_dispatch_rollout_filtered"
    assert result["observation_recorded"] is True
    db.commit.assert_awaited_once()
    db.rollback.assert_not_awaited()
    mock_audit.assert_awaited_once()
    mock_execute.assert_not_awaited()
    assert {item["reason"] for item in result["rollout_gate"]["blockers"]} == {
        "rollout_priority_not_allowed",
    }


@pytest.mark.asyncio
async def test_execute_auto_dispatch_after_ai_approval_creates_hall_on_rollout_skip(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    work_order = _work_order(
        status="pending_dispatch",
        ai_decision="approve",
        priority="medium",
        dispatch_profile_json='{"required_skills":["hvac"]}',
    )
    db = SimpleNamespace(
        get=AsyncMock(return_value=work_order),
        commit=AsyncMock(),
        rollback=AsyncMock(),
    )
    monkeypatch.setattr(ai_review_service.settings, "ENABLE_AUTO_DISPATCH_EXECUTION", True)
    monkeypatch.setattr(ai_review_service.settings, "ENABLE_AUTO_DISPATCH_HALL_FALLBACK", True)
    monkeypatch.setattr(ai_review_service.settings, "AUTO_DISPATCH_CREATE_HALL_ON_ROLLOUT_SKIP", True)
    monkeypatch.setattr(ai_review_service.settings, "AUTO_DISPATCH_ALLOWED_BUILDINGS", ["Fox_public_Henry"])
    monkeypatch.setattr(ai_review_service.settings, "AUTO_DISPATCH_ALLOWED_PRIORITIES", ["high"])
    monkeypatch.setattr(ai_review_service.settings, "AUTO_DISPATCH_ALLOWED_REQUIRED_SKILLS", [])
    mock_audit = AsyncMock()
    mock_hall = AsyncMock(return_value=SimpleNamespace(id="hall-1"))
    mock_execute = AsyncMock()
    monkeypatch.setattr(ai_review_service, "write_work_order_audit_log", mock_audit)
    monkeypatch.setattr(ai_review_service, "create_or_reopen_takeover_hall_entry", mock_hall)
    monkeypatch.setattr(ai_review_service, "execute_auto_dispatch", mock_execute)

    result = await ai_review_service.execute_auto_dispatch_after_ai_approval(
        db,
        work_order_id=work_order.id,
        trigger_source="test_case",
    )

    assert result["action_taken"] is True
    assert result["executed"] is False
    assert result["reason"] == "auto_dispatch_rollout_hall_fallback_created"
    assert result["hall_entry_id"] == "hall-1"
    db.commit.assert_awaited_once()
    db.rollback.assert_not_awaited()
    assert mock_audit.await_count == 2
    mock_hall.assert_awaited_once()
    mock_execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_execute_auto_dispatch_after_ai_approval_does_not_create_hall_for_non_dispatchable_rollout_skip(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    work_order = _work_order(
        status="dispatched",
        approval_status="approved",
        dispatch_summary_status="assigned",
        current_dispatch_id="dispatch-1",
        priority="medium",
        dispatch_profile_json='{"required_skills":["hvac"]}',
    )
    db = SimpleNamespace(
        get=AsyncMock(return_value=work_order),
        commit=AsyncMock(),
        rollback=AsyncMock(),
    )
    monkeypatch.setattr(ai_review_service.settings, "ENABLE_AUTO_DISPATCH_EXECUTION", True)
    monkeypatch.setattr(ai_review_service.settings, "ENABLE_AUTO_DISPATCH_HALL_FALLBACK", True)
    monkeypatch.setattr(ai_review_service.settings, "AUTO_DISPATCH_CREATE_HALL_ON_ROLLOUT_SKIP", True)
    monkeypatch.setattr(ai_review_service.settings, "AUTO_DISPATCH_ALLOWED_BUILDINGS", ["Fox_public_Henry"])
    monkeypatch.setattr(ai_review_service.settings, "AUTO_DISPATCH_ALLOWED_PRIORITIES", ["high"])
    monkeypatch.setattr(ai_review_service.settings, "AUTO_DISPATCH_ALLOWED_REQUIRED_SKILLS", [])
    mock_audit = AsyncMock()
    mock_hall = AsyncMock(return_value=SimpleNamespace(id="hall-1"))
    mock_execute = AsyncMock()
    monkeypatch.setattr(ai_review_service, "write_work_order_audit_log", mock_audit)
    monkeypatch.setattr(ai_review_service, "create_or_reopen_takeover_hall_entry", mock_hall)
    monkeypatch.setattr(ai_review_service, "execute_auto_dispatch", mock_execute)

    result = await ai_review_service.execute_auto_dispatch_after_ai_approval(
        db,
        work_order_id=work_order.id,
        trigger_source="test_case",
    )

    assert result["action_taken"] is False
    assert result["reason"] == "auto_dispatch_rollout_filtered"
    db.commit.assert_awaited_once()
    db.rollback.assert_not_awaited()
    mock_audit.assert_awaited_once()
    mock_hall.assert_not_awaited()
    mock_execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_trigger_ai_review_runs_auto_dispatch_after_approved_review(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reviewed_work_order = _work_order(status="pending_dispatch", ai_decision="approve")
    db = SimpleNamespace(commit=AsyncMock())
    monkeypatch.setattr(routes_workorder, "AsyncSessionLocal", lambda: _AsyncSessionContext(db))
    monkeypatch.setattr(routes_workorder, "_invalidate_related_cache", AsyncMock())
    monkeypatch.setattr(ai_review_service, "review_work_order", AsyncMock(return_value=reviewed_work_order))
    mock_auto_dispatch = AsyncMock(return_value={"action_taken": True, "executed": True})
    monkeypatch.setattr(ai_review_service, "execute_auto_dispatch_after_ai_approval", mock_auto_dispatch)

    await routes_workorder._trigger_ai_review(reviewed_work_order.id)

    db.commit.assert_awaited_once()
    mock_auto_dispatch.assert_awaited_once_with(
        db,
        work_order_id=reviewed_work_order.id,
        trigger_source="background_ai_review",
    )


@pytest.mark.asyncio
async def test_trigger_ai_review_for_pending_only_auto_dispatches_approved_reviews(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    approved = _work_order(id="wo-1", ticket_id="WO-001", status="pending_dispatch", ai_decision="approve")
    rejected = _work_order(id="wo-2", ticket_id="WO-002", status="auto_rejected", ai_decision="reject")
    db = SimpleNamespace(
        execute=AsyncMock(
            return_value=_FakeScalarResult(rows=[("wo-1",), ("wo-2",)])
        ),
        commit=AsyncMock(),
        rollback=AsyncMock(),
    )
    monkeypatch.setattr(
        ai_review_service,
        "review_work_order",
        AsyncMock(side_effect=[approved, rejected]),
    )
    mock_auto_dispatch = AsyncMock(return_value={"action_taken": False, "executed": False})
    monkeypatch.setattr(ai_review_service, "execute_auto_dispatch_after_ai_approval", mock_auto_dispatch)

    reviewed = await auto_work_order_service.trigger_ai_review_for_pending(db)

    assert reviewed == 2
    assert db.commit.await_count == 2
    db.rollback.assert_not_awaited()
    mock_auto_dispatch.assert_awaited_once_with(
        db,
        work_order_id=approved.id,
        trigger_source="batch_pending_ai_review",
    )
