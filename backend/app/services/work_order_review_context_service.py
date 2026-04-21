"""
工单审查上下文服务。

该服务不直接调用 LLM，而是把工单、审计总账、派工事件流和工单大厅记录
整理成适合后续 AI 工单审查入口消费的结构化上下文。
"""
from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.person_name import sanitize_person_display_payload
from app.db.models import (
    DispatchHallEntry,
    DispatchTask,
    User,
    WorkOrder,
    WorkOrderAuditLog,
    WorkerProfile,
)
from app.services.dispatch_event_service import load_dispatch_events_by_task_ids
from app.services.dispatch_hall_service import (
    serialize_dispatch_hall_application,
    serialize_dispatch_hall_entry,
)
from app.services.dispatch_service import (
    get_current_dispatch_task,
    list_dispatch_tasks_for_work_order,
    serialize_dispatch_task,
)
from app.services.work_order_service import serialize_work_order


def _dt_to_iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _safe_load_json(raw: str | None) -> Any:
    if not raw:
        return None
    try:
        return sanitize_person_display_payload(json.loads(raw))
    except (TypeError, ValueError):
        return None


def serialize_review_audit_log(log_item: WorkOrderAuditLog) -> dict[str, Any]:
    return {
        "id": log_item.id,
        "action": log_item.action,
        "old_status": log_item.old_status,
        "new_status": log_item.new_status,
        "actor_type": log_item.actor_type,
        "actor_id": log_item.actor_id,
        "detail": _safe_load_json(log_item.detail_json),
        "created_at": _dt_to_iso(log_item.created_at),
    }


def serialize_anomaly_link_for_review(work_order: WorkOrder) -> list[dict[str, Any]]:
    return [
        {
            "id": item.id,
            "anomaly_event_id": item.anomaly_event_id,
            "rule_triggered": item.rule_triggered,
            "hvac_root_cause": item.hvac_root_cause,
            "actual_value": item.actual_value,
            "expected_value": item.expected_value,
            "deviation_pct": item.deviation_pct,
            "data_timestamp": _dt_to_iso(item.data_timestamp),
        }
        for item in getattr(work_order, "anomaly_links", []) or []
    ]


def build_review_risk_flags(
    *,
    work_order: WorkOrder,
    current_dispatch: DispatchTask | None,
    dispatch_tasks: list[DispatchTask],
    hall_entries: list[DispatchHallEntry],
    audit_logs: list[WorkOrderAuditLog],
) -> list[dict[str, str]]:
    flags: list[dict[str, str]] = []

    if work_order.status in {"dispatched", "completed"} and current_dispatch is None:
        flags.append(
            {
                "code": "missing_current_dispatch",
                "severity": "high",
                "message": "工单处于执行/完成阶段，但缺少 current_dispatch。",
            }
        )

    if current_dispatch and current_dispatch.timeout_level == "overdue":
        flags.append(
            {
                "code": "current_dispatch_overdue",
                "severity": "high",
                "message": "当前派工已超时，需要关注处理进度或接管策略。",
            }
        )

    if any(item.timeout_level == "overdue" for item in dispatch_tasks):
        flags.append(
            {
                "code": "has_overdue_history",
                "severity": "medium",
                "message": "历史派工中出现过超时记录。",
            }
        )

    if any(item.dispatch_status == "rejected" for item in dispatch_tasks):
        flags.append(
            {
                "code": "has_rejected_dispatch",
                "severity": "medium",
                "message": "历史派工中出现过拒单，需要关注拒单原因。",
            }
        )

    if any(item.transfer_from_dispatch_id for item in dispatch_tasks):
        flags.append(
            {
                "code": "has_reassign_history",
                "severity": "medium",
                "message": "该工单发生过改派或接管。",
            }
        )

    reminder_count = sum(int(item.reminder_count or 0) for item in dispatch_tasks)
    if reminder_count > 0:
        flags.append(
            {
                "code": "has_nudge_history",
                "severity": "low",
                "message": f"该工单累计催办 {reminder_count} 次。",
            }
        )

    open_hall_entries = [item for item in hall_entries if item.status in {"open", "assigned"}]
    if open_hall_entries:
        flags.append(
            {
                "code": "open_hall_entry",
                "severity": "medium",
                "message": "该工单仍有关联的工单大厅事项未关闭。",
            }
        )

    if not audit_logs:
        flags.append(
            {
                "code": "missing_audit_logs",
                "severity": "medium",
                "message": "该工单缺少审计日志，历史责任链可能不完整。",
            }
        )

    return flags


def build_ai_context_summary(
    *,
    work_order_data: dict[str, Any],
    current_dispatch_data: dict[str, Any] | None,
    dispatch_tasks: list[dict[str, Any]],
    audit_logs: list[dict[str, Any]],
    hall_entries: list[dict[str, Any]],
    risk_flags: list[dict[str, str]],
) -> str:
    lines = [
        f"工单 {work_order_data.get('ticket_id')} 当前状态为 {work_order_data.get('status')}，优先级为 {work_order_data.get('priority')}。",
        f"问题描述：{work_order_data.get('issue_description') or '未记录'}",
    ]
    if current_dispatch_data:
        lines.append(
            "当前派工："
            f"第 {current_dispatch_data.get('attempt_no')} 次，"
            f"状态 {current_dispatch_data.get('dispatch_status')}，"
            f"责任人 {current_dispatch_data.get('assigned_to_name') or current_dispatch_data.get('assigned_to') or '未记录'}。"
        )
    else:
        lines.append("当前没有有效派工任务。")

    lines.append(f"历史派工次数：{len(dispatch_tasks)}。")
    lines.append(f"审计日志条数：{len(audit_logs)}。")
    if hall_entries:
        open_count = sum(1 for item in hall_entries if item.get("status") in {"open", "assigned"})
        lines.append(f"工单大厅关联事项：{len(hall_entries)} 条，其中未关闭 {open_count} 条。")
    if risk_flags:
        lines.append("风险提示：" + "；".join(item["message"] for item in risk_flags))
    else:
        lines.append("风险提示：当前未识别到明显异常风险。")
    return "\n".join(lines)


async def _load_users_by_ids(db: AsyncSession, user_ids: list[str | None]) -> dict[str, User]:
    unique_user_ids = [user_id for user_id in dict.fromkeys(user_ids) if user_id]
    if not unique_user_ids:
        return {}
    result = await db.execute(
        select(User)
        .options(selectinload(User.worker_profile).selectinload(WorkerProfile.team))
        .where(User.id.in_(unique_user_ids))
    )
    return {user.id: user for user in result.scalars().all()}


async def build_work_order_review_context(
    db: AsyncSession,
    *,
    ticket_id: str,
) -> dict[str, Any] | None:
    work_order_result = await db.execute(
        select(WorkOrder)
        .options(selectinload(WorkOrder.anomaly_links))
        .where(WorkOrder.ticket_id == ticket_id)
    )
    work_order = work_order_result.scalar_one_or_none()
    if work_order is None:
        return None

    current_dispatch = await get_current_dispatch_task(db, work_order=work_order)
    dispatch_tasks = await list_dispatch_tasks_for_work_order(db, work_order_id=work_order.id)
    dispatch_events_map = await load_dispatch_events_by_task_ids(
        db,
        dispatch_task_ids=[item.id for item in dispatch_tasks],
    )

    audit_result = await db.execute(
        select(WorkOrderAuditLog)
        .where(WorkOrderAuditLog.work_order_id == work_order.id)
        .order_by(WorkOrderAuditLog.created_at.asc())
    )
    audit_logs = list(audit_result.scalars().all())

    hall_result = await db.execute(
        select(DispatchHallEntry)
        .options(selectinload(DispatchHallEntry.applications))
        .where(DispatchHallEntry.work_order_id == work_order.id)
        .order_by(DispatchHallEntry.created_at.asc())
    )
    hall_entries = list(hall_result.scalars().all())

    user_ids: list[str | None] = [
        getattr(current_dispatch, "assigned_to", None),
        getattr(current_dispatch, "assigned_by", None),
        work_order.assigned_to,
        work_order.created_by,
        work_order.admin_reviewed_by,
    ]
    for dispatch_task in dispatch_tasks:
        user_ids.extend([dispatch_task.assigned_to, dispatch_task.assigned_by])
    for log_item in audit_logs:
        user_ids.append(log_item.actor_id)
    for entry in hall_entries:
        user_ids.extend([entry.assigned_to, entry.assigned_by, entry.created_by])
        for application in entry.applications or []:
            user_ids.extend([application.applicant_user_id, application.handled_by])

    users_by_id = await _load_users_by_ids(db, user_ids)

    serialized_dispatch_tasks = [
        serialize_dispatch_task(
            item,
            assigned_user=users_by_id.get(item.assigned_to or ""),
            events=dispatch_events_map.get(item.id, []),
        )
        for item in dispatch_tasks
    ]
    current_dispatch_data = (
        serialize_dispatch_task(
            current_dispatch,
            assigned_user=users_by_id.get(current_dispatch.assigned_to or ""),
            events=dispatch_events_map.get(current_dispatch.id, []),
        )
        if current_dispatch
        else None
    )
    work_order_data = serialize_work_order(
        work_order,
        assigned_user=users_by_id.get(
            getattr(current_dispatch, "assigned_to", None) or work_order.assigned_to or ""
        ),
        current_dispatch=current_dispatch,
        dispatch_events=dispatch_events_map.get(current_dispatch.id, []) if current_dispatch else [],
    )
    serialized_audit_logs = [serialize_review_audit_log(item) for item in audit_logs]

    dispatch_tasks_by_id = {item.id: item for item in dispatch_tasks}
    serialized_hall_entries = []
    for entry in hall_entries:
        source_dispatch = dispatch_tasks_by_id.get(entry.source_dispatch_id or "")
        application_payloads = [
            serialize_dispatch_hall_application(
                application,
                applicant_user=users_by_id.get(application.applicant_user_id),
                handled_user=users_by_id.get(application.handled_by or ""),
            )
            for application in entry.applications or []
        ]
        serialized_hall_entries.append(
            serialize_dispatch_hall_entry(
                entry,
                assigned_user=users_by_id.get(entry.assigned_to or ""),
                assigned_by_user=users_by_id.get(entry.assigned_by or ""),
                created_by_user=users_by_id.get(entry.created_by or ""),
                work_order_summary={
                    "id": work_order.id,
                    "ticket_id": work_order.ticket_id,
                    "building_id": work_order.building_id,
                    "device_id": work_order.device_id,
                    "priority": work_order.priority,
                    "status": work_order.status,
                },
                source_dispatch_summary=(
                    serialize_dispatch_task(
                        source_dispatch,
                        assigned_user=users_by_id.get(source_dispatch.assigned_to or ""),
                        events=dispatch_events_map.get(source_dispatch.id, []),
                    )
                    if source_dispatch
                    else None
                ),
                applications=application_payloads,
            )
        )

    risk_flags = build_review_risk_flags(
        work_order=work_order,
        current_dispatch=current_dispatch,
        dispatch_tasks=dispatch_tasks,
        hall_entries=hall_entries,
        audit_logs=audit_logs,
    )

    return {
        "ticket_id": ticket_id,
        "context_type": "work_order_ai_review_context",
        "work_order": work_order_data,
        "current_dispatch": current_dispatch_data,
        "dispatch_tasks": serialized_dispatch_tasks,
        "dispatch_events": [
            event
            for dispatch_task in serialized_dispatch_tasks
            for event in (dispatch_task.get("events") or [])
        ],
        "audit_logs": serialized_audit_logs,
        "hall_entries": serialized_hall_entries,
        "anomaly_evidence": serialize_anomaly_link_for_review(work_order),
        "risk_flags": risk_flags,
        "ai_context_summary": build_ai_context_summary(
            work_order_data=work_order_data,
            current_dispatch_data=current_dispatch_data,
            dispatch_tasks=serialized_dispatch_tasks,
            audit_logs=serialized_audit_logs,
            hall_entries=serialized_hall_entries,
            risk_flags=risk_flags,
        ),
    }
