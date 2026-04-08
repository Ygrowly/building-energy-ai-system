from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, TYPE_CHECKING

from sqlalchemy import func as sa_func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    AnomalyIncident,
    DispatchTask,
    User,
    WorkOrder,
)
from app.services.dispatch_event_service import (
    record_dispatch_event,
    serialize_dispatch_event,
)
from app.services.dispatch_hall_service import (
    close_open_hall_entries_for_dispatch,
    create_or_reopen_support_hall_entry,
    create_or_reopen_takeover_hall_entry,
)

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from app.db.models import DispatchEvent

_DISPATCH_STAGE_SLA_MINUTES: dict[str, dict[str, int]] = {
    "high": {"accept": 5, "arrive": 20, "start": 30, "finish": 90},
    "medium": {"accept": 10, "arrive": 30, "start": 45, "finish": 180},
    "low": {"accept": 15, "arrive": 60, "start": 90, "finish": 360},
}

_ACTIVE_SLA_DISPATCH_STATUSES = {
    "assigned",
    "accepted",
    "arrived",
    "processing",
    "waiting_support",
}


def _dt_to_iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _json_dumps(payload: dict[str, Any] | None) -> str | None:
    if not payload:
        return None
    return json.dumps(payload, ensure_ascii=False, default=str)


def _json_loads(payload: str | None) -> dict[str, Any] | None:
    if not payload:
        return None
    try:
        data = json.loads(payload)
    except (TypeError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _get_dispatch_sla(priority: str | None) -> dict[str, int]:
    return _DISPATCH_STAGE_SLA_MINUTES.get(priority or "", _DISPATCH_STAGE_SLA_MINUTES["medium"])


def _dispatch_stage_label(dispatch_status: str) -> str:
    mapping = {
        "assigned": "接单",
        "accepted": "到场",
        "arrived": "开始处理",
        "processing": "处理完成",
        "waiting_support": "协同完成",
    }
    return mapping.get(dispatch_status, "处理")


def _dispatch_timeout_note(
    dispatch_task: DispatchTask,
    *,
    timeout_level: str,
    due_at: datetime | None,
    now: datetime,
) -> str:
    stage_label = _dispatch_stage_label(dispatch_task.dispatch_status)
    if due_at is None:
        return f"{stage_label}阶段 SLA 状态已更新"

    minutes_left = int((due_at - now).total_seconds() // 60)
    if timeout_level == "warning":
        return f"{stage_label}阶段即将超时，剩余 {max(minutes_left, 0)} 分钟，系统已提醒责任人尽快处理"
    if timeout_level == "overdue":
        return f"{stage_label}阶段已超时 {abs(minutes_left)} 分钟，系统已自动提醒责任人并建议管理员评估接管"
    return f"{stage_label}阶段已恢复正常"


def _team_from_user(user: User | None) -> tuple[str | None, str | None]:
    profile = getattr(user, "worker_profile", None) if user else None
    team = getattr(profile, "team", None) if profile else None
    return (
        getattr(team, "id", None) if team else None,
        getattr(team, "name", None) if team else None,
    )


def _sync_work_order_dispatch_projection(
    work_order: WorkOrder,
    dispatch_task: DispatchTask | None,
) -> None:
    if dispatch_task is None:
        work_order.current_dispatch_id = None
        work_order.assigned_to = None
        work_order.assigned_at = None
        work_order.accepted_at = None
        work_order.arrived_at = None
        work_order.processing_started_at = None
        return

    work_order.current_dispatch_id = dispatch_task.id
    work_order.assigned_to = dispatch_task.assigned_to
    work_order.assigned_at = dispatch_task.assigned_at
    work_order.accepted_at = dispatch_task.accepted_at
    work_order.arrived_at = dispatch_task.arrived_at
    work_order.processing_started_at = dispatch_task.processing_started_at
    work_order.updated_at = datetime.now(timezone.utc)


async def _sync_incident_dispatch_projection(
    db: AsyncSession,
    *,
    work_order: WorkOrder,
    dispatch_task: DispatchTask | None,
    blocked_reason: str | None = None,
) -> None:
    if not work_order.incident_id:
        return

    incident = await db.get(AnomalyIncident, work_order.incident_id)
    if incident is None:
        return

    incident.current_work_order_id = work_order.id
    incident.workflow_status = work_order.status
    incident.priority = work_order.priority
    incident.updated_at = datetime.now(timezone.utc)

    if dispatch_task is None:
        incident.current_dispatch_id = None
        incident.current_dispatch_status = None
        incident.current_assigned_to = None
        incident.current_assigned_team_id = None
        incident.current_accept_deadline_at = None
        incident.current_arrive_deadline_at = None
        incident.current_finish_deadline_at = None
        incident.dispatch_overdue_flag = False
        incident.dispatch_blocked_reason = blocked_reason
        incident.latest_dispatch_note = blocked_reason
        return

    incident.current_dispatch_id = dispatch_task.id
    incident.current_dispatch_status = dispatch_task.dispatch_status
    incident.current_assigned_to = dispatch_task.assigned_to
    incident.current_assigned_team_id = dispatch_task.assigned_team_id
    incident.current_accept_deadline_at = dispatch_task.accept_deadline_at
    incident.current_arrive_deadline_at = dispatch_task.arrive_deadline_at
    incident.current_finish_deadline_at = dispatch_task.finish_deadline_at
    incident.last_dispatch_at = dispatch_task.assigned_at
    incident.dispatch_blocked_reason = blocked_reason
    incident.latest_dispatch_note = dispatch_task.latest_note or blocked_reason
    incident.dispatch_overdue_flag = derive_dispatch_timeout_level(dispatch_task)[0] != "normal"


def derive_dispatch_timeout_level(dispatch_task: DispatchTask) -> tuple[str, datetime | None]:
    now = datetime.now(timezone.utc)
    deadline = None
    if dispatch_task.dispatch_status == "assigned":
        deadline = dispatch_task.accept_deadline_at
    elif dispatch_task.dispatch_status == "accepted":
        deadline = dispatch_task.arrive_deadline_at
    elif dispatch_task.dispatch_status in {"arrived", "processing", "waiting_support"}:
        deadline = dispatch_task.finish_deadline_at

    if deadline is None:
        return "normal", None

    minutes_left = int((deadline - now).total_seconds() // 60)
    if minutes_left < 0:
        return "overdue", deadline
    if minutes_left <= 30:
        return "warning", deadline
    return "normal", deadline


async def get_dispatch_task_by_id(
    db: AsyncSession,
    dispatch_task_id: str,
) -> DispatchTask | None:
    return await db.get(DispatchTask, dispatch_task_id)


async def get_current_dispatch_task(
    db: AsyncSession,
    *,
    work_order: WorkOrder,
) -> DispatchTask | None:
    if getattr(work_order, "current_dispatch_id", None):
        dispatch_task = await db.get(DispatchTask, work_order.current_dispatch_id)
        if dispatch_task is not None:
            return dispatch_task

    result = await db.execute(
        select(DispatchTask)
        .where(
            DispatchTask.work_order_id == work_order.id,
            DispatchTask.is_current == True,  # noqa: E712
        )
        .order_by(DispatchTask.attempt_no.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def load_current_dispatches_by_work_order_ids(
    db: AsyncSession,
    *,
    work_order_ids: list[str],
) -> dict[str, DispatchTask]:
    if not work_order_ids:
        return {}
    result = await db.execute(
        select(DispatchTask)
        .where(
            DispatchTask.work_order_id.in_(work_order_ids),
            DispatchTask.is_current == True,  # noqa: E712
        )
        .order_by(DispatchTask.work_order_id.asc(), DispatchTask.attempt_no.desc())
    )
    grouped: dict[str, DispatchTask] = {}
    for item in result.scalars().all():
        grouped.setdefault(item.work_order_id, item)
    return grouped


async def list_dispatch_tasks(
    db: AsyncSession,
    *,
    assigned_to: str | None = None,
    work_order_id: str | None = None,
    incident_id: str | None = None,
    status_filter: list[str] | None = None,
    current_only: bool | None = None,
    page: int = 1,
    page_size: int = 20,
) -> tuple[list[DispatchTask], int]:
    query = select(DispatchTask)
    count_query = select(sa_func.count(DispatchTask.id))

    if assigned_to:
        query = query.where(DispatchTask.assigned_to == assigned_to)
        count_query = count_query.where(DispatchTask.assigned_to == assigned_to)
    if work_order_id:
        query = query.where(DispatchTask.work_order_id == work_order_id)
        count_query = count_query.where(DispatchTask.work_order_id == work_order_id)
    if incident_id:
        query = query.where(DispatchTask.incident_id == incident_id)
        count_query = count_query.where(DispatchTask.incident_id == incident_id)
    if status_filter:
        query = query.where(DispatchTask.dispatch_status.in_(status_filter))
        count_query = count_query.where(DispatchTask.dispatch_status.in_(status_filter))
    if current_only is not None:
        query = query.where(DispatchTask.is_current == current_only)  # noqa: E712
        count_query = count_query.where(DispatchTask.is_current == current_only)  # noqa: E712

    total = (await db.execute(count_query)).scalar() or 0
    offset = (page - 1) * page_size
    query = (
        query.order_by(DispatchTask.assigned_at.desc(), DispatchTask.attempt_no.desc())
        .offset(offset)
        .limit(page_size)
    )
    items = list((await db.execute(query)).scalars().all())
    return items, total


async def list_dispatch_tasks_for_work_order(
    db: AsyncSession,
    *,
    work_order_id: str,
) -> list[DispatchTask]:
    result = await db.execute(
        select(DispatchTask)
        .where(DispatchTask.work_order_id == work_order_id)
        .order_by(DispatchTask.attempt_no.asc(), DispatchTask.assigned_at.asc())
    )
    return list(result.scalars().all())


async def scan_dispatch_sla_states(
    db: AsyncSession,
    *,
    now: datetime | None = None,
) -> dict[str, int]:
    current_time = now or datetime.now(timezone.utc)
    result = await db.execute(
        select(DispatchTask)
        .where(
            DispatchTask.is_current == True,  # noqa: E712
            DispatchTask.dispatch_status.in_(_ACTIVE_SLA_DISPATCH_STATUSES),
        )
        .order_by(DispatchTask.assigned_at.asc())
    )
    dispatch_tasks = list(result.scalars().all())
    if not dispatch_tasks:
        return {
            "scanned": 0,
            "updated": 0,
            "warning_events": 0,
            "overdue_events": 0,
        }

    work_order_ids = [item.work_order_id for item in dispatch_tasks if item.work_order_id]
    work_order_result = await db.execute(
        select(WorkOrder).where(WorkOrder.id.in_(work_order_ids))
    )
    work_orders_by_id = {item.id: item for item in work_order_result.scalars().all()}

    updated = 0
    warning_events = 0
    overdue_events = 0
    for dispatch_task in dispatch_tasks:
        previous_timeout = dispatch_task.timeout_level or "normal"
        next_timeout, due_at = derive_dispatch_timeout_level(dispatch_task)
        if next_timeout == previous_timeout:
            continue

        dispatch_task.timeout_level = next_timeout
        dispatch_task.updated_at = current_time
        work_order = work_orders_by_id.get(dispatch_task.work_order_id)

        if next_timeout in {"warning", "overdue"}:
            message = _dispatch_timeout_note(
                dispatch_task,
                timeout_level=next_timeout,
                due_at=due_at,
                now=current_time,
            )
            dispatch_task.latest_note = message
            dispatch_task.reminder_count = int(dispatch_task.reminder_count or 0) + 1
            dispatch_task.last_reminded_at = current_time
            await record_dispatch_event(
                db,
                dispatch_task=dispatch_task,
                event_type="timeout_warning" if next_timeout == "warning" else "timeout_overdue",
                actor_type="scheduler",
                payload={
                    "timeout_level": next_timeout,
                    "previous_timeout_level": previous_timeout,
                    "deadline_at": _dt_to_iso(due_at),
                    "message": message,
                    "stage": dispatch_task.dispatch_status,
                },
            )
            if next_timeout == "warning":
                warning_events += 1
            else:
                overdue_events += 1
                if work_order is not None:
                    await create_or_reopen_takeover_hall_entry(
                        db,
                        work_order=work_order,
                        source_dispatch_id=dispatch_task.id,
                        source_assignee_id=dispatch_task.assigned_to,
                        created_by=None,
                        reason=message,
                        sla_stage=dispatch_task.dispatch_status,
                        overdue_level=next_timeout,
                    )
        elif previous_timeout == "overdue":
            await close_open_hall_entries_for_dispatch(
                db,
                source_dispatch_id=dispatch_task.id,
                entry_types=["takeover_candidate"],
                handle_note="派工时限已恢复，无需继续接管",
            )

        if work_order is not None:
            _sync_work_order_dispatch_projection(work_order, dispatch_task)
            await _sync_incident_dispatch_projection(
                db,
                work_order=work_order,
                dispatch_task=dispatch_task,
                blocked_reason=getattr(work_order, "dispatch_blocked_reason", None),
            )

        updated += 1

    return {
        "scanned": len(dispatch_tasks),
        "updated": updated,
        "warning_events": warning_events,
        "overdue_events": overdue_events,
    }


async def _next_attempt_no(
    db: AsyncSession,
    *,
    work_order_id: str,
) -> int:
    result = await db.execute(
        select(sa_func.max(DispatchTask.attempt_no)).where(DispatchTask.work_order_id == work_order_id)
    )
    current = result.scalar_one_or_none()
    return int(current or 0) + 1


async def create_dispatch_task(
    db: AsyncSession,
    *,
    work_order: WorkOrder,
    assigned_user: User,
    assigned_by: str | None,
    actor_type: str,
    dispatch_mode: str = "manual",
    selection_reason: str | None = None,
    candidate_snapshot: dict[str, Any] | None = None,
    dispatch_profile_snapshot: dict[str, Any] | None = None,
    transfer_from_dispatch_id: str | None = None,
) -> DispatchTask:
    now = datetime.now(timezone.utc)
    team_id, _ = _team_from_user(assigned_user)
    attempt_no = await _next_attempt_no(db, work_order_id=work_order.id)
    sla = _get_dispatch_sla(work_order.priority)

    current_dispatch = await get_current_dispatch_task(db, work_order=work_order)
    if current_dispatch is not None:
        current_dispatch.is_current = False
        current_dispatch.dispatch_status = "transferred"
        current_dispatch.closed_at = now
        current_dispatch.updated_at = now
        await record_dispatch_event(
            db,
            dispatch_task=current_dispatch,
            event_type="transferred",
            actor_type=actor_type,
            actor_id=assigned_by,
            payload={"reason": selection_reason, "next_attempt_no": attempt_no},
        )

    dispatch_task = DispatchTask(
        work_order_id=work_order.id,
        incident_id=work_order.incident_id,
        attempt_no=attempt_no,
        is_current=True,
        dispatch_mode=dispatch_mode,
        dispatch_status="assigned",
        assigned_team_id=team_id,
        assigned_to=assigned_user.id,
        assigned_by=assigned_by,
        selection_reason=selection_reason,
        candidate_snapshot_json=_json_dumps(candidate_snapshot),
        dispatch_profile_snapshot_json=_json_dumps(dispatch_profile_snapshot),
        transfer_from_dispatch_id=transfer_from_dispatch_id,
        assigned_at=now,
        accept_deadline_at=now + timedelta(minutes=sla["accept"]),
        arrive_deadline_at=now + timedelta(minutes=sla["accept"] + sla["arrive"]),
        start_deadline_at=now + timedelta(minutes=sla["accept"] + sla["arrive"] + sla["start"]),
        finish_deadline_at=now + timedelta(minutes=sla["finish"]),
        timeout_level="normal",
        latest_note=selection_reason,
    )
    db.add(dispatch_task)
    await db.flush()

    _sync_work_order_dispatch_projection(work_order, dispatch_task)
    await _sync_incident_dispatch_projection(
        db,
        work_order=work_order,
        dispatch_task=dispatch_task,
    )
    await record_dispatch_event(
        db,
        dispatch_task=dispatch_task,
        event_type="assigned" if dispatch_mode != "auto" else "auto_assigned",
        actor_type=actor_type,
        actor_id=assigned_by,
        payload={
            "assigned_to": assigned_user.id,
            "assigned_to_name": assigned_user.username,
            "assigned_team_id": team_id,
            "selection_reason": selection_reason,
            "dispatch_mode": dispatch_mode,
        },
    )
    logger.info("dispatch_task created: work_order=%s dispatch=%s", work_order.ticket_id, dispatch_task.id)
    return dispatch_task


def _mark_dispatch_projection_status(dispatch_task: DispatchTask) -> None:
    timeout_level, _ = derive_dispatch_timeout_level(dispatch_task)
    dispatch_task.timeout_level = timeout_level


async def update_dispatch_task_action(
    db: AsyncSession,
    *,
    work_order: WorkOrder,
    dispatch_task: DispatchTask,
    action: str,
    actor_type: str,
    actor_id: str | None = None,
    notes: str | None = None,
    support_team_id: str | None = None,
) -> DispatchTask:
    now = datetime.now(timezone.utc)
    payload: dict[str, Any] = {"action": action, "notes": notes}
    blocked_reason: str | None = None

    if action == "accept":
        if dispatch_task.dispatch_status not in {"assigned"}:
            raise ValueError("当前派工任务不支持接单")
        dispatch_task.accepted_at = dispatch_task.accepted_at or now
        dispatch_task.dispatch_status = "accepted"
    elif action == "arrive":
        if dispatch_task.dispatch_status not in {"accepted"}:
            raise ValueError("请先接单后再标记到场")
        dispatch_task.arrived_at = dispatch_task.arrived_at or now
        dispatch_task.dispatch_status = "arrived"
    elif action == "start":
        if dispatch_task.dispatch_status not in {"accepted", "arrived"}:
            raise ValueError("请先接单后再开始处理")
        dispatch_task.accepted_at = dispatch_task.accepted_at or now
        dispatch_task.arrived_at = dispatch_task.arrived_at or now
        dispatch_task.processing_started_at = dispatch_task.processing_started_at or now
        dispatch_task.dispatch_status = "processing"
    elif action == "request_support":
        if dispatch_task.dispatch_status not in {"arrived", "processing", "waiting_support"}:
            raise ValueError("当前状态不支持申请协同")
        dispatch_task.processing_started_at = dispatch_task.processing_started_at or now
        dispatch_task.dispatch_status = "waiting_support"
        dispatch_task.support_reason = notes
        dispatch_task.support_team_id = support_team_id
        payload["support_team_id"] = support_team_id
        payload["support_reason"] = dispatch_task.support_reason
        blocked_reason = notes or "等待配件或协同支持"
        work_order.dispatch_blocked_reason = blocked_reason
    elif action == "support_resolved":
        if dispatch_task.dispatch_status != "waiting_support":
            raise ValueError("当前派工任务不处于待协同状态")
        payload["previous_support_reason"] = dispatch_task.support_reason
        payload["support_team_id"] = dispatch_task.support_team_id
        dispatch_task.processing_started_at = dispatch_task.processing_started_at or now
        dispatch_task.dispatch_status = "processing"
        if dispatch_task.worker_result == "needs_parts":
            dispatch_task.worker_result = None
        dispatch_task.support_reason = None
        dispatch_task.support_team_id = None
        work_order.dispatch_blocked_reason = None
        if work_order.worker_result == "needs_parts":
            work_order.worker_result = None
            work_order.worker_feedback_at = None
    else:
        raise ValueError(f"未知执行动作: {action}")

    if action == "support_resolved":
        dispatch_task.latest_note = notes or "协同事项已解决，恢复现场处理"
    else:
        dispatch_task.latest_note = notes or dispatch_task.latest_note
    dispatch_task.updated_at = now
    _mark_dispatch_projection_status(dispatch_task)
    _sync_work_order_dispatch_projection(work_order, dispatch_task)
    await _sync_incident_dispatch_projection(
        db,
        work_order=work_order,
        dispatch_task=dispatch_task,
        blocked_reason=blocked_reason,
    )
    event_type_map = {
        "accept": "accepted",
        "arrive": "arrived",
        "start": "started",
        "request_support": "support_requested",
        "support_resolved": "support_resolved",
    }
    await record_dispatch_event(
        db,
        dispatch_task=dispatch_task,
        event_type=event_type_map[action],
        actor_type=actor_type,
        actor_id=actor_id,
        payload=payload,
    )
    if action == "request_support":
        await create_or_reopen_support_hall_entry(
            db,
            work_order=work_order,
            source_dispatch_id=dispatch_task.id,
            source_assignee_id=dispatch_task.assigned_to,
            created_by=actor_id,
            target_team_ids=[support_team_id] if support_team_id else None,
            reason=blocked_reason,
            support_reason=dispatch_task.support_reason,
        )
    elif action == "support_resolved":
        await close_open_hall_entries_for_dispatch(
            db,
            source_dispatch_id=dispatch_task.id,
            entry_types=["support_request"],
            actor_id=actor_id,
            handle_note="协同事项已解决，共享协同入口关闭",
        )
    return dispatch_task


async def nudge_dispatch_task(
    db: AsyncSession,
    *,
    work_order: WorkOrder,
    dispatch_task: DispatchTask,
    actor_type: str,
    actor_id: str | None = None,
    message: str | None = None,
) -> DispatchTask:
    now = datetime.now(timezone.utc)
    if dispatch_task.dispatch_status in {"completed", "cancelled", "transferred", "rejected", "escalated"}:
        raise ValueError("当前派工任务已结束，无法催办")

    dispatch_task.reminder_count = int(dispatch_task.reminder_count or 0) + 1
    dispatch_task.last_reminded_at = now
    dispatch_task.updated_at = now
    dispatch_task.latest_note = message or dispatch_task.latest_note or "调度已催办，请尽快处理"
    _mark_dispatch_projection_status(dispatch_task)
    _sync_work_order_dispatch_projection(work_order, dispatch_task)
    await _sync_incident_dispatch_projection(
        db,
        work_order=work_order,
        dispatch_task=dispatch_task,
        blocked_reason=getattr(work_order, "dispatch_blocked_reason", None),
    )
    await record_dispatch_event(
        db,
        dispatch_task=dispatch_task,
        event_type="reminded",
        actor_type=actor_type,
        actor_id=actor_id,
        payload={
            "message": message,
            "reminder_count": dispatch_task.reminder_count,
            "dispatch_status": dispatch_task.dispatch_status,
        },
    )
    return dispatch_task


async def cancel_dispatch_task(
    db: AsyncSession,
    *,
    work_order: WorkOrder,
    dispatch_task: DispatchTask,
    actor_type: str,
    actor_id: str | None = None,
    reason: str | None = None,
) -> DispatchTask:
    now = datetime.now(timezone.utc)
    if dispatch_task.dispatch_status not in {"assigned", "accepted"}:
        raise ValueError("当前状态不支持取消派工")

    dispatch_task.dispatch_status = "cancelled"
    dispatch_task.cancel_reason = reason
    dispatch_task.latest_note = reason or "当前派工已取消"
    dispatch_task.is_current = False
    dispatch_task.closed_at = now
    dispatch_task.updated_at = now
    _mark_dispatch_projection_status(dispatch_task)
    _sync_work_order_dispatch_projection(work_order, None)
    await _sync_incident_dispatch_projection(
        db,
        work_order=work_order,
        dispatch_task=None,
        blocked_reason=reason or "当前派工已取消，等待重新派工",
    )
    await record_dispatch_event(
        db,
        dispatch_task=dispatch_task,
        event_type="cancelled",
        actor_type=actor_type,
        actor_id=actor_id,
        payload={"reason": reason},
    )
    await close_open_hall_entries_for_dispatch(
        db,
        source_dispatch_id=dispatch_task.id,
        actor_id=actor_id,
        handle_note=reason or "当前派工已取消，共享工单同步关闭",
    )
    return dispatch_task


async def reject_dispatch_task(
    db: AsyncSession,
    *,
    work_order: WorkOrder,
    dispatch_task: DispatchTask,
    actor_type: str,
    actor_id: str | None = None,
    reason: str | None = None,
) -> DispatchTask:
    now = datetime.now(timezone.utc)
    if dispatch_task.dispatch_status in {"completed", "cancelled", "transferred"}:
        raise ValueError("当前派工任务已结束，无法拒单")

    dispatch_task.dispatch_status = "rejected"
    dispatch_task.reject_reason = reason
    dispatch_task.latest_note = reason
    dispatch_task.is_current = False
    dispatch_task.closed_at = now
    dispatch_task.updated_at = now
    _mark_dispatch_projection_status(dispatch_task)
    _sync_work_order_dispatch_projection(work_order, None)
    await _sync_incident_dispatch_projection(
        db,
        work_order=work_order,
        dispatch_task=None,
        blocked_reason=reason or "维修人员已拒单，等待重新派工",
    )
    await record_dispatch_event(
        db,
        dispatch_task=dispatch_task,
        event_type="rejected",
        actor_type=actor_type,
        actor_id=actor_id,
        payload={"reason": reason},
    )
    await close_open_hall_entries_for_dispatch(
        db,
        source_dispatch_id=dispatch_task.id,
        actor_id=actor_id,
        handle_note=reason or "当前派工已拒单，共享工单同步关闭",
    )
    return dispatch_task


async def complete_dispatch_task(
    db: AsyncSession,
    *,
    work_order: WorkOrder,
    dispatch_task: DispatchTask,
    actor_type: str,
    actor_id: str | None = None,
    result: str,
    notes: str | None = None,
) -> DispatchTask:
    now = datetime.now(timezone.utc)
    dispatch_task.processing_started_at = dispatch_task.processing_started_at or now
    dispatch_task.worker_result = result
    dispatch_task.latest_note = notes or dispatch_task.latest_note
    dispatch_task.updated_at = now

    if result == "needs_parts":
        dispatch_task.dispatch_status = "waiting_support"
        dispatch_task.support_reason = notes
        await _sync_incident_dispatch_projection(
            db,
            work_order=work_order,
            dispatch_task=dispatch_task,
            blocked_reason=notes or "等待配件或协同支持",
        )
        event_type = "support_requested"
        await create_or_reopen_support_hall_entry(
            db,
            work_order=work_order,
            source_dispatch_id=dispatch_task.id,
            source_assignee_id=dispatch_task.assigned_to,
            created_by=actor_id,
            reason=notes or "等待配件或协同支持",
            support_reason=notes,
        )
    else:
        dispatch_task.dispatch_status = "completed" if result != "escalated" else "escalated"
        dispatch_task.completed_at = now
        dispatch_task.closed_at = now
        _sync_work_order_dispatch_projection(work_order, dispatch_task)
        await _sync_incident_dispatch_projection(
            db,
            work_order=work_order,
            dispatch_task=dispatch_task,
        )
        event_type = "completed" if result != "escalated" else "escalated"
        await close_open_hall_entries_for_dispatch(
            db,
            source_dispatch_id=dispatch_task.id,
            actor_id=actor_id,
            handle_note="本次派工已完成，共享工单同步关闭",
        )

    _mark_dispatch_projection_status(dispatch_task)
    await record_dispatch_event(
        db,
        dispatch_task=dispatch_task,
        event_type=event_type,
        actor_type=actor_type,
        actor_id=actor_id,
        payload={"result": result, "notes": notes},
    )
    return dispatch_task


async def reassign_dispatch_task(
    db: AsyncSession,
    *,
    work_order: WorkOrder,
    dispatch_task: DispatchTask,
    assigned_user: User,
    actor_type: str,
    actor_id: str | None = None,
    reason: str | None = None,
    dispatch_mode: str = "reassigned",
    close_related_hall_entries: bool = True,
) -> DispatchTask:
    now = datetime.now(timezone.utc)
    if dispatch_task.dispatch_status in {"completed", "cancelled"}:
        raise ValueError("当前派工任务已结束，无法改派")

    dispatch_task.dispatch_status = "transferred"
    dispatch_task.is_current = False
    dispatch_task.closed_at = now
    dispatch_task.latest_note = reason or dispatch_task.latest_note
    dispatch_task.updated_at = now
    await record_dispatch_event(
        db,
        dispatch_task=dispatch_task,
        event_type="transferred",
        actor_type=actor_type,
        actor_id=actor_id,
        payload={
            "reason": reason,
            "new_assigned_to": assigned_user.id,
            "new_assigned_to_name": assigned_user.username,
        },
    )
    if close_related_hall_entries:
        await close_open_hall_entries_for_dispatch(
            db,
            source_dispatch_id=dispatch_task.id,
            actor_id=actor_id,
            handle_note=reason or "当前派工已改派，共享工单同步关闭",
        )

    new_dispatch = await create_dispatch_task(
        db,
        work_order=work_order,
        assigned_user=assigned_user,
        assigned_by=actor_id,
        actor_type=actor_type,
        dispatch_mode=dispatch_mode,
        selection_reason=reason,
        transfer_from_dispatch_id=dispatch_task.id,
    )
    return new_dispatch


def derive_dispatch_ui_meta_from_task(
    dispatch_task: DispatchTask | None,
    *,
    assigned_user: User | None = None,
) -> dict[str, Any]:
    if dispatch_task is None:
        return {
            "dispatch_id": None,
            "assigned_to_name": None,
            "assigned_phone": None,
            "assigned_team_name": None,
            "dispatch_status": None,
            "dispatch_mode": None,
            "dispatch_attempt_no": None,
            "dispatch_at": None,
            "accepted_at": None,
            "arrived_at": None,
            "processing_started_at": None,
            "latest_progress_at": None,
            "latest_progress_note": None,
            "execution_status": None,
            "sla_due_at": None,
            "sla_status": None,
            "sla_minutes_left": None,
        }

    now = datetime.now(timezone.utc)
    _, team_name = _team_from_user(assigned_user)
    assigned_to_name = assigned_user.username if assigned_user else None
    assigned_phone = assigned_user.phone if assigned_user else None
    execution_status = dispatch_task.dispatch_status
    if execution_status == "assigned":
        execution_status = "pending_accept"

    timeout_level, due_at = derive_dispatch_timeout_level(dispatch_task)
    sla_minutes_left = None
    if due_at:
        sla_minutes_left = int((due_at - now).total_seconds() // 60)
    if timeout_level == "overdue" and execution_status in {"pending_accept", "accepted", "arrived", "processing"}:
        execution_status = "overdue"

    latest_progress_at = (
        dispatch_task.completed_at
        or dispatch_task.processing_started_at
        or dispatch_task.arrived_at
        or dispatch_task.accepted_at
        or dispatch_task.assigned_at
    )
    latest_progress_note = dispatch_task.latest_note
    if not latest_progress_note:
        mapping = {
            "assigned": "已完成派工，等待维修人员接单",
            "accepted": "维修人员已接单，正在前往现场",
            "arrived": "维修人员已到场，等待开始处理",
            "processing": "维修人员正在处理现场问题",
            "waiting_support": "维修人员已申请协同或配件支持",
            "rejected": dispatch_task.reject_reason or "维修人员已拒单",
            "transferred": "该次派工已转派",
            "completed": "本次派工执行已完成",
            "escalated": "该次派工已升级处理",
            "cancelled": "该次派工已取消",
        }
        latest_progress_note = mapping.get(dispatch_task.dispatch_status, "")

    return {
        "dispatch_id": dispatch_task.id,
        "assigned_to_name": assigned_to_name,
        "assigned_phone": assigned_phone,
        "assigned_team_name": team_name,
        "dispatch_status": dispatch_task.dispatch_status,
        "dispatch_mode": dispatch_task.dispatch_mode,
        "dispatch_attempt_no": dispatch_task.attempt_no,
        "dispatch_at": _dt_to_iso(dispatch_task.assigned_at),
        "accepted_at": _dt_to_iso(dispatch_task.accepted_at),
        "arrived_at": _dt_to_iso(dispatch_task.arrived_at),
        "processing_started_at": _dt_to_iso(dispatch_task.processing_started_at),
        "latest_progress_at": _dt_to_iso(latest_progress_at),
        "latest_progress_note": latest_progress_note,
        "execution_status": execution_status,
        "sla_due_at": _dt_to_iso(due_at),
        "sla_status": timeout_level if due_at else None,
        "sla_minutes_left": sla_minutes_left,
    }


def serialize_dispatch_task(
    dispatch_task: DispatchTask,
    *,
    assigned_user: User | None = None,
    events: list[DispatchEvent] | None = None,
) -> dict[str, Any]:
    _, team_name = _team_from_user(assigned_user)
    data = {
        "id": dispatch_task.id,
        "work_order_id": dispatch_task.work_order_id,
        "incident_id": dispatch_task.incident_id,
        "attempt_no": dispatch_task.attempt_no,
        "is_current": dispatch_task.is_current,
        "dispatch_mode": dispatch_task.dispatch_mode,
        "dispatch_status": dispatch_task.dispatch_status,
        "assigned_team_id": dispatch_task.assigned_team_id,
        "assigned_team_name": team_name,
        "assigned_to": dispatch_task.assigned_to,
        "assigned_to_name": assigned_user.username if assigned_user else None,
        "assigned_phone": assigned_user.phone if assigned_user else None,
        "assigned_by": dispatch_task.assigned_by,
        "selection_reason": dispatch_task.selection_reason,
        "candidate_snapshot": _json_loads(dispatch_task.candidate_snapshot_json),
        "dispatch_profile_snapshot": _json_loads(dispatch_task.dispatch_profile_snapshot_json),
        "worker_result": dispatch_task.worker_result,
        "reject_reason": dispatch_task.reject_reason,
        "cancel_reason": dispatch_task.cancel_reason,
        "support_reason": dispatch_task.support_reason,
        "support_team_id": dispatch_task.support_team_id,
        "transfer_from_dispatch_id": dispatch_task.transfer_from_dispatch_id,
        "assigned_at": _dt_to_iso(dispatch_task.assigned_at),
        "accept_deadline_at": _dt_to_iso(dispatch_task.accept_deadline_at),
        "accepted_at": _dt_to_iso(dispatch_task.accepted_at),
        "arrive_deadline_at": _dt_to_iso(dispatch_task.arrive_deadline_at),
        "arrived_at": _dt_to_iso(dispatch_task.arrived_at),
        "start_deadline_at": _dt_to_iso(dispatch_task.start_deadline_at),
        "processing_started_at": _dt_to_iso(dispatch_task.processing_started_at),
        "finish_deadline_at": _dt_to_iso(dispatch_task.finish_deadline_at),
        "completed_at": _dt_to_iso(dispatch_task.completed_at),
        "closed_at": _dt_to_iso(dispatch_task.closed_at),
        "reminder_count": dispatch_task.reminder_count,
        "last_reminded_at": _dt_to_iso(dispatch_task.last_reminded_at),
        "timeout_level": dispatch_task.timeout_level,
        "latest_note": dispatch_task.latest_note,
        "created_at": _dt_to_iso(dispatch_task.created_at),
        "updated_at": _dt_to_iso(dispatch_task.updated_at),
        **derive_dispatch_ui_meta_from_task(dispatch_task, assigned_user=assigned_user),
    }
    data["events"] = [serialize_dispatch_event(item) for item in (events or [])]
    return data
