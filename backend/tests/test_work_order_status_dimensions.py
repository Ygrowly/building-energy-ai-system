from __future__ import annotations

from types import SimpleNamespace

from app.services.work_order_status_dimensions import (
    derive_approval_status,
    derive_dispatch_summary_status,
    derive_work_result,
    serialize_work_order_status_dimensions,
    sync_work_order_status_dimensions,
)


def _work_order(**overrides):
    data = {
        "status": "pending_review",
        "ai_decision": None,
        "admin_action": None,
        "worker_result": None,
        "approval_status": None,
        "dispatch_summary_status": None,
        "work_result": None,
    }
    data.update(overrides)
    return SimpleNamespace(**data)


def test_derive_dimensions_for_pending_review() -> None:
    work_order = _work_order()

    assert derive_approval_status(work_order) == "pending_review"
    assert derive_dispatch_summary_status(work_order) is None
    assert derive_work_result(work_order) is None


def test_derive_dimensions_for_rejected_work_order() -> None:
    work_order = _work_order(status="auto_rejected", ai_decision="reject")

    assert derive_approval_status(work_order) == "rejected"
    assert derive_dispatch_summary_status(work_order) is None


def test_derive_dimensions_from_current_dispatch_task() -> None:
    work_order = _work_order(status="dispatched", ai_decision="approve")
    dispatch_task = SimpleNamespace(dispatch_status="waiting_support", worker_result="needs_parts")

    sync_work_order_status_dimensions(work_order, dispatch_task=dispatch_task)

    assert work_order.approval_status == "approved"
    assert work_order.dispatch_summary_status == "waiting_support"
    assert work_order.work_result == "needs_parts"


def test_derive_dimensions_for_finished_legacy_status() -> None:
    work_order = _work_order(status="false_alarm", ai_decision="approve")

    assert serialize_work_order_status_dimensions(work_order) == {
        "approval_status": "approved",
        "dispatch_summary_status": "completed",
        "work_result": "false_alarm",
    }
