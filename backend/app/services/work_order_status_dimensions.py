"""
Work order status dimension helpers.

The legacy ``work_orders.status`` field is still the compatibility surface, but
new code can read the three narrower dimensions maintained here.
"""
from __future__ import annotations

from typing import Any


_PENDING_DISPATCH_STATUSES = {
    "pending_dispatch",
    "auto_approved",
    "admin_override_approved",
}
_REJECTED_STATUSES = {
    "auto_rejected",
    "admin_override_rejected",
}
_DISPATCH_STATUS_PASSTHROUGH = {
    "assigned",
    "accepted",
    "arrived",
    "processing",
    "waiting_support",
    "completed",
    "cancelled",
    "escalated",
}


def derive_approval_status(work_order: Any) -> str:
    """Return the approval dimension for a work order."""
    status = getattr(work_order, "status", None)
    if status == "pending_review":
        return "pending_review"
    if status in _REJECTED_STATUSES:
        return "rejected"

    admin_action = getattr(work_order, "admin_action", None)
    ai_decision = getattr(work_order, "ai_decision", None)
    if status == "closed" and admin_action == "override_reject":
        return "rejected"
    if (
        ai_decision == "reject"
        and status in {"auto_rejected", "closed"}
        and admin_action != "override_approve"
    ):
        return "rejected"
    return "approved"


def derive_work_result(
    work_order: Any,
    *,
    dispatch_task: Any | None = None,
) -> str | None:
    """Return the result dimension without mutating the work order."""
    raw_result = getattr(work_order, "worker_result", None) or getattr(
        dispatch_task,
        "worker_result",
        None,
    )
    if raw_result:
        return raw_result

    status = getattr(work_order, "status", None)
    if status == "completed":
        return "fixed"
    if status == "false_alarm":
        return "false_alarm"
    if status == "escalated":
        return "escalated"
    return None


def derive_dispatch_summary_status(
    work_order: Any,
    *,
    dispatch_task: Any | None = None,
) -> str | None:
    """Return the dispatch summary dimension for list/detail reads."""
    status = getattr(work_order, "status", None)
    approval_status = derive_approval_status(work_order)

    if approval_status in {"pending_review", "rejected"}:
        return None
    if status in _PENDING_DISPATCH_STATUSES:
        return "pending_dispatch"

    dispatch_status = getattr(dispatch_task, "dispatch_status", None)
    if dispatch_status in _DISPATCH_STATUS_PASSTHROUGH:
        return dispatch_status
    if dispatch_status in {"rejected", "transferred"}:
        return "pending_dispatch"

    if status == "dispatched":
        return "assigned" if getattr(work_order, "current_dispatch_id", None) else "pending_dispatch"
    if status in {"completed", "false_alarm", "closed"}:
        return "completed"
    if status == "escalated":
        return "escalated"
    return None


def sync_work_order_status_dimensions(
    work_order: Any,
    *,
    dispatch_task: Any | None = None,
) -> None:
    """Populate the persisted status dimension columns on a work order."""
    work_order.approval_status = derive_approval_status(work_order)
    work_order.dispatch_summary_status = derive_dispatch_summary_status(
        work_order,
        dispatch_task=dispatch_task,
    )
    work_order.work_result = derive_work_result(
        work_order,
        dispatch_task=dispatch_task,
    )


def serialize_work_order_status_dimensions(
    work_order: Any,
    *,
    dispatch_task: Any | None = None,
) -> dict[str, str | None]:
    """Serialize dimensions, falling back to derived values if persisted data is absent."""
    return {
        "approval_status": getattr(work_order, "approval_status", None)
        or derive_approval_status(work_order),
        "dispatch_summary_status": getattr(work_order, "dispatch_summary_status", None)
        or derive_dispatch_summary_status(work_order, dispatch_task=dispatch_task),
        "work_result": getattr(work_order, "work_result", None)
        or derive_work_result(work_order, dispatch_task=dispatch_task),
    }
