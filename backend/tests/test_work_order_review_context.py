from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from app.api import routes_workorder
from app.services.work_order_review_context_service import build_review_risk_flags


def _dispatch_task(
    *,
    dispatch_id: str,
    status: str = "assigned",
    timeout_level: str = "normal",
    reminder_count: int = 0,
    transfer_from_dispatch_id: str | None = None,
):
    return SimpleNamespace(
        id=dispatch_id,
        dispatch_status=status,
        timeout_level=timeout_level,
        reminder_count=reminder_count,
        transfer_from_dispatch_id=transfer_from_dispatch_id,
    )


def test_build_review_risk_flags_marks_overdue_reassign_and_audit_gap() -> None:
    work_order = SimpleNamespace(status="dispatched")
    current_dispatch = _dispatch_task(dispatch_id="dispatch-2", timeout_level="overdue")
    old_dispatch = _dispatch_task(
        dispatch_id="dispatch-1",
        status="rejected",
        reminder_count=2,
        transfer_from_dispatch_id="dispatch-0",
    )
    hall_entry = SimpleNamespace(status="open")

    flags = build_review_risk_flags(
        work_order=work_order,
        current_dispatch=current_dispatch,
        dispatch_tasks=[old_dispatch, current_dispatch],
        hall_entries=[hall_entry],
        audit_logs=[],
    )

    codes = {item["code"] for item in flags}
    assert "current_dispatch_overdue" in codes
    assert "has_rejected_dispatch" in codes
    assert "has_reassign_history" in codes
    assert "has_nudge_history" in codes
    assert "open_hall_entry" in codes
    assert "missing_audit_logs" in codes


@pytest.mark.asyncio
async def test_review_context_endpoint_allows_manager(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = {
        "ticket_id": "WO-001",
        "current_dispatch": {"assigned_to": "ops-1"},
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    monkeypatch.setattr(
        routes_workorder,
        "build_work_order_review_context",
        AsyncMock(return_value=payload),
    )

    response = await routes_workorder.get_work_order_review_context_endpoint(
        ticket_id="WO-001",
        db=SimpleNamespace(),
        user=SimpleNamespace(id="manager-1", role="manager"),
    )

    assert response == payload


@pytest.mark.asyncio
async def test_review_context_endpoint_allows_assigned_ops(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = {
        "ticket_id": "WO-001",
        "current_dispatch": {"assigned_to": "ops-1"},
    }
    monkeypatch.setattr(
        routes_workorder,
        "build_work_order_review_context",
        AsyncMock(return_value=payload),
    )

    response = await routes_workorder.get_work_order_review_context_endpoint(
        ticket_id="WO-001",
        db=SimpleNamespace(),
        user=SimpleNamespace(id="ops-1", role="ops"),
    )

    assert response["ticket_id"] == "WO-001"


@pytest.mark.asyncio
async def test_review_context_endpoint_rejects_unassigned_ops(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        routes_workorder,
        "build_work_order_review_context",
        AsyncMock(return_value={"ticket_id": "WO-001", "current_dispatch": {"assigned_to": "ops-2"}}),
    )

    with pytest.raises(HTTPException) as exc_info:
        await routes_workorder.get_work_order_review_context_endpoint(
            ticket_id="WO-001",
            db=SimpleNamespace(),
            user=SimpleNamespace(id="ops-1", role="ops"),
        )

    assert exc_info.value.status_code == 403


@pytest.mark.asyncio
async def test_review_context_endpoint_returns_404(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        routes_workorder,
        "build_work_order_review_context",
        AsyncMock(return_value=None),
    )

    with pytest.raises(HTTPException) as exc_info:
        await routes_workorder.get_work_order_review_context_endpoint(
            ticket_id="missing",
            db=SimpleNamespace(),
            user=SimpleNamespace(id="manager-1", role="manager"),
        )

    assert exc_info.value.status_code == 404
