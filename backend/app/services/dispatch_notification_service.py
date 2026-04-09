"""
派工通知语义服务。

这里集中处理 SLA 临期/超时、人工催办等派工提醒的文案和事件 payload。
真正的事件落库仍由 dispatch_event_service 负责，业务状态流转仍由 dispatch_service 编排。
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from app.db.models import DispatchTask


@dataclass(frozen=True)
class DispatchNotification:
    message: str
    event_type: str
    payload: dict[str, Any]


def _dt_to_iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def dispatch_stage_label(dispatch_status: str) -> str:
    mapping = {
        "assigned": "接单",
        "accepted": "到场",
        "arrived": "开始处理",
        "processing": "处理完成",
        "waiting_support": "协同完成",
    }
    return mapping.get(dispatch_status, "处理")


def build_dispatch_timeout_note(
    dispatch_task: DispatchTask,
    *,
    timeout_level: str,
    due_at: datetime | None,
    now: datetime,
) -> str:
    stage_label = dispatch_stage_label(dispatch_task.dispatch_status)
    if due_at is None:
        return f"{stage_label}阶段 SLA 状态已更新"

    minutes_left = int((due_at - now).total_seconds() // 60)
    if timeout_level == "warning":
        return f"{stage_label}阶段即将超时，剩余 {max(minutes_left, 0)} 分钟，系统已提醒责任人尽快处理"
    if timeout_level == "overdue":
        return f"{stage_label}阶段已超时 {abs(minutes_left)} 分钟，系统已自动提醒责任人并建议管理员评估接管"
    return f"{stage_label}阶段已恢复正常"


def build_timeout_notification(
    dispatch_task: DispatchTask,
    *,
    timeout_level: str,
    previous_timeout_level: str,
    due_at: datetime | None,
    now: datetime,
) -> DispatchNotification:
    message = build_dispatch_timeout_note(
        dispatch_task,
        timeout_level=timeout_level,
        due_at=due_at,
        now=now,
    )
    return DispatchNotification(
        message=message,
        event_type="timeout_warning" if timeout_level == "warning" else "timeout_overdue",
        payload={
            "timeout_level": timeout_level,
            "previous_timeout_level": previous_timeout_level,
            "deadline_at": _dt_to_iso(due_at),
            "message": message,
            "stage": dispatch_task.dispatch_status,
        },
    )


def mark_dispatch_reminded(
    dispatch_task: DispatchTask,
    *,
    reminded_at: datetime,
    message: str,
) -> None:
    dispatch_task.latest_note = message
    dispatch_task.reminder_count = int(dispatch_task.reminder_count or 0) + 1
    dispatch_task.last_reminded_at = reminded_at


def resolve_nudge_message(
    dispatch_task: DispatchTask,
    *,
    requested_message: str | None,
) -> str:
    return requested_message or dispatch_task.latest_note or "调度已催办，请尽快处理"


def build_nudge_notification(
    dispatch_task: DispatchTask,
    *,
    requested_message: str | None,
) -> DispatchNotification:
    effective_message = resolve_nudge_message(
        dispatch_task,
        requested_message=requested_message,
    )
    return DispatchNotification(
        message=effective_message,
        event_type="reminded",
        payload={
            "message": requested_message,
            "effective_message": effective_message,
            "reminder_count": dispatch_task.reminder_count,
            "dispatch_status": dispatch_task.dispatch_status,
        },
    )
