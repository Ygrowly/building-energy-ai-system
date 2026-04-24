from __future__ import annotations

import argparse
import asyncio
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import selectinload

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.db.models import (  # noqa: E402
    DispatchEvent,
    DispatchHallEntry,
    DispatchTask,
    User,
    WorkOrder,
    WorkOrderAuditLog,
    WorkerProfile,
    WorkerProfileSkill,
)
from app.db.session import AsyncSessionLocal, engine  # noqa: E402
from app.services.dispatch_service import (  # noqa: E402
    complete_dispatch_task,
    get_current_dispatch_task,
    reassign_dispatch_task,
)
from app.services.work_order_service import (  # noqa: E402
    apply_ai_review,
    assign_work_order,
    create_work_order,
    record_worker_dispatch_action,
    transition_status,
)

MOCK_TICKET_PREFIX = "WO-MOCK-"
DEFAULT_MANAGER_USERNAME = "test1"


@dataclass(frozen=True)
class MockFlowSeed:
    suffix: str
    building_id: str
    issue_description: str
    suggested_action: str
    priority: str
    primary_worker: str
    start_at: datetime
    flow_type: str
    device_id: str | None = None
    reassign_to: str | None = None


SEEDS: tuple[MockFlowSeed, ...] = (
    MockFlowSeed(
        suffix="20260422-A17",
        building_id="Fox_public_Henry",
        device_id="AC-PUBLIC-01",
        issue_description="公共楼空调供回水温差异常，三层东侧体感偏热。",
        suggested_action="先核对供回水温度和阀门开度，再检查末端风机盘管运行状态。",
        priority="high",
        primary_worker="ops_hvac_01",
        start_at=datetime(2026, 4, 21, 1, 0, tzinfo=timezone.utc),
        flow_type="fixed_closed",
    ),
    MockFlowSeed(
        suffix="20260422-C43",
        building_id="Fox_office_Alice",
        device_id="WATER-OFFICE-02",
        issue_description="办公楼二层茶水间排水缓慢，地面积水，需现场协同排查。",
        suggested_action="先封控积水区域，检查地漏和排水立管，再确认是否需要协同疏通。",
        priority="medium",
        primary_worker="ops_plumbing_01",
        start_at=datetime(2026, 4, 21, 3, 30, tzinfo=timezone.utc),
        flow_type="support_closed",
    ),
    MockFlowSeed(
        suffix="20260422-H08",
        building_id="Fox_office_Alice",
        device_id="CTRL-OFFICE-03",
        issue_description="办公楼 BMS 新风联动策略异常，先派综合值守到场，后改派自控。",
        suggested_action="先确认现场模式切换与传感器读数，再由自控班复核联动逻辑。",
        priority="high",
        primary_worker="ops_general_02",
        reassign_to="ops_controls_01",
        start_at=datetime(2026, 4, 21, 6, 0, tzinfo=timezone.utc),
        flow_type="reassign_escalated_closed",
    ),
    MockFlowSeed(
        suffix="20260422-X31",
        building_id="Fox_education_Louie",
        device_id="SENSOR-EDU-04",
        issue_description="教学楼走廊温湿度传感器短时跳点，现场复测需确认是否误报。",
        suggested_action="先复测现场读数并核对传感器安装环境，如现场正常则按误报关闭。",
        priority="low",
        primary_worker="ops_controls_01",
        start_at=datetime(2026, 4, 22, 0, 30, tzinfo=timezone.utc),
        flow_type="false_alarm_closed",
    ),
)


def _ticket_id(seed: MockFlowSeed) -> str:
    return f"{MOCK_TICKET_PREFIX}{seed.suffix}"


def _ensure_allowed_workers() -> None:
    banned = {"ops_electrical_01"}
    used = {seed.primary_worker for seed in SEEDS}
    used.update(seed.reassign_to for seed in SEEDS if seed.reassign_to)
    conflict = banned & {item for item in used if item}
    if conflict:
        raise RuntimeError(f"mock seeds include banned workers: {sorted(conflict)}")


async def _load_users(db) -> dict[str, User]:
    result = await db.execute(
        select(User)
        .options(
            selectinload(User.worker_profile).selectinload(WorkerProfile.team),
            selectinload(User.worker_profile)
            .selectinload(WorkerProfile.skill_links)
            .selectinload(WorkerProfileSkill.skill),
        )
        .where(User.username.in_(
            [DEFAULT_MANAGER_USERNAME, *(seed.primary_worker for seed in SEEDS), *(seed.reassign_to for seed in SEEDS if seed.reassign_to)]
        ))
    )
    return {item.username: item for item in result.scalars().all()}


async def _resolve_manager(db, users_by_username: dict[str, User], manager_username: str) -> User:
    manager = users_by_username.get(manager_username)
    if manager and manager.role in {"admin", "manager"}:
        return manager

    result = await db.execute(
        select(User)
        .where(User.role.in_(["admin", "manager"]), User.is_active == True)  # noqa: E712
        .order_by(User.role.asc(), User.username.asc())
        .limit(1)
    )
    manager = result.scalar_one_or_none()
    if manager is None:
        raise RuntimeError("no active admin/manager user found")
    return manager


async def _cleanup_existing(db) -> list[str]:
    result = await db.execute(
        select(WorkOrder)
        .where(WorkOrder.ticket_id.like(f"{MOCK_TICKET_PREFIX}%"))
        .order_by(WorkOrder.ticket_id.asc())
    )
    work_orders = list(result.scalars().all())
    deleted = [item.ticket_id for item in work_orders]
    for item in work_orders:
        await db.delete(item)
    await db.flush()
    return deleted


def _nth_match(rows: list[Any], attr: str, expected: str, index: int = 0) -> Any | None:
    matches = [item for item in rows if getattr(item, attr) == expected]
    return matches[index] if index < len(matches) else None


async def _load_dispatch_events(db, dispatch_ids: list[str]) -> list[DispatchEvent]:
    if not dispatch_ids:
        return []
    result = await db.execute(
        select(DispatchEvent)
        .where(DispatchEvent.dispatch_task_id.in_(dispatch_ids))
        .order_by(DispatchEvent.created_at.asc(), DispatchEvent.id.asc())
    )
    return list(result.scalars().all())


async def _load_audit_logs(db, work_order_id: str) -> list[WorkOrderAuditLog]:
    result = await db.execute(
        select(WorkOrderAuditLog)
        .where(WorkOrderAuditLog.work_order_id == work_order_id)
        .order_by(WorkOrderAuditLog.created_at.asc(), WorkOrderAuditLog.id.asc())
    )
    return list(result.scalars().all())


async def _load_hall_entries(db, work_order_id: str) -> list[DispatchHallEntry]:
    result = await db.execute(
        select(DispatchHallEntry)
        .where(DispatchHallEntry.work_order_id == work_order_id)
        .order_by(DispatchHallEntry.created_at.asc(), DispatchHallEntry.id.asc())
    )
    return list(result.scalars().all())


def _set_dispatch_deadlines(dispatch_task: DispatchTask) -> None:
    assigned_at = dispatch_task.assigned_at
    if assigned_at is None:
        return
    priority = getattr(getattr(dispatch_task, "work_order", None), "priority", None) or "medium"
    sla_map = {
        "high": {"accept": 5, "arrive": 20, "start": 30, "finish": 90},
        "medium": {"accept": 10, "arrive": 30, "start": 45, "finish": 180},
        "low": {"accept": 15, "arrive": 60, "start": 90, "finish": 360},
    }
    sla = sla_map.get(priority, sla_map["medium"])
    dispatch_task.accept_deadline_at = assigned_at + timedelta(minutes=sla["accept"])
    dispatch_task.arrive_deadline_at = assigned_at + timedelta(minutes=sla["accept"] + sla["arrive"])
    dispatch_task.start_deadline_at = assigned_at + timedelta(minutes=sla["accept"] + sla["arrive"] + sla["start"])
    dispatch_task.finish_deadline_at = assigned_at + timedelta(minutes=sla["finish"])


async def _rebase_fixed_closed(db, work_order: WorkOrder, dispatch_task: DispatchTask, manager: User, worker: User) -> None:
    created_at = work_order.created_at
    assert created_at is not None
    ai_at = created_at + timedelta(minutes=5)
    dispatch_at = created_at + timedelta(minutes=20)
    accept_at = created_at + timedelta(minutes=34)
    arrive_at = created_at + timedelta(minutes=56)
    start_at = created_at + timedelta(minutes=68)
    feedback_at = created_at + timedelta(minutes=128)
    close_at = created_at + timedelta(minutes=160)

    work_order.ai_reviewed_at = ai_at
    work_order.pending_dispatch_at = ai_at
    work_order.assigned_at = dispatch_at
    work_order.accepted_at = accept_at
    work_order.arrived_at = arrive_at
    work_order.processing_started_at = start_at
    work_order.worker_feedback_at = feedback_at
    work_order.admin_reviewed_by = manager.id
    work_order.admin_reviewed_at = close_at
    work_order.closed_at = close_at
    work_order.updated_at = close_at

    dispatch_task.assigned_at = dispatch_at
    dispatch_task.accepted_at = accept_at
    dispatch_task.arrived_at = arrive_at
    dispatch_task.processing_started_at = start_at
    dispatch_task.completed_at = feedback_at
    dispatch_task.closed_at = feedback_at
    dispatch_task.updated_at = feedback_at
    dispatch_task.latest_note = "已更换阀门执行器并恢复供冷。"
    _set_dispatch_deadlines(dispatch_task)

    audit_logs = await _load_audit_logs(db, work_order.id)
    event_rows = await _load_dispatch_events(db, [dispatch_task.id])

    schedule_audit = {
        ("create", 0): created_at,
        ("ai_approve", 0): ai_at,
        ("dispatch", 0): dispatch_at,
        ("worker_accept", 0): accept_at,
        ("worker_arrive", 0): arrive_at,
        ("worker_start", 0): start_at,
        ("worker_feedback", 0): feedback_at,
        ("close", 0): close_at,
    }
    schedule_event = {
        ("assigned", 0): dispatch_at,
        ("accepted", 0): accept_at,
        ("arrived", 0): arrive_at,
        ("started", 0): start_at,
        ("completed", 0): feedback_at,
    }

    for (action, index), when in schedule_audit.items():
        row = _nth_match(audit_logs, "action", action, index)
        if row:
            row.created_at = when
    for (event_type, index), when in schedule_event.items():
        row = _nth_match(event_rows, "event_type", event_type, index)
        if row:
            row.created_at = when


async def _rebase_support_closed(
    db,
    work_order: WorkOrder,
    dispatch_task: DispatchTask,
    manager: User,
) -> None:
    created_at = work_order.created_at
    assert created_at is not None
    ai_at = created_at + timedelta(minutes=4)
    dispatch_at = created_at + timedelta(minutes=18)
    accept_at = created_at + timedelta(minutes=32)
    arrive_at = created_at + timedelta(minutes=58)
    start_at = created_at + timedelta(minutes=72)
    support_at = created_at + timedelta(minutes=95)
    support_resolved_at = created_at + timedelta(minutes=128)
    feedback_at = created_at + timedelta(minutes=166)
    close_at = created_at + timedelta(minutes=190)

    work_order.ai_reviewed_at = ai_at
    work_order.pending_dispatch_at = ai_at
    work_order.assigned_at = dispatch_at
    work_order.accepted_at = accept_at
    work_order.arrived_at = arrive_at
    work_order.processing_started_at = start_at
    work_order.worker_feedback_at = feedback_at
    work_order.admin_reviewed_by = manager.id
    work_order.admin_reviewed_at = close_at
    work_order.closed_at = close_at
    work_order.updated_at = close_at

    dispatch_task.assigned_at = dispatch_at
    dispatch_task.accepted_at = accept_at
    dispatch_task.arrived_at = arrive_at
    dispatch_task.processing_started_at = start_at
    dispatch_task.completed_at = feedback_at
    dispatch_task.closed_at = feedback_at
    dispatch_task.updated_at = feedback_at
    dispatch_task.latest_note = "协同疏通后恢复排水，现场已清理。"
    _set_dispatch_deadlines(dispatch_task)

    audit_logs = await _load_audit_logs(db, work_order.id)
    event_rows = await _load_dispatch_events(db, [dispatch_task.id])
    hall_entries = await _load_hall_entries(db, work_order.id)

    schedule_audit = {
        ("create", 0): created_at,
        ("ai_approve", 0): ai_at,
        ("dispatch", 0): dispatch_at,
        ("worker_accept", 0): accept_at,
        ("worker_arrive", 0): arrive_at,
        ("worker_start", 0): start_at,
        ("worker_request_support", 0): support_at,
        ("worker_support_resolved", 0): support_resolved_at,
        ("worker_feedback", 0): feedback_at,
        ("close", 0): close_at,
    }
    schedule_event = {
        ("assigned", 0): dispatch_at,
        ("accepted", 0): accept_at,
        ("arrived", 0): arrive_at,
        ("started", 0): start_at,
        ("support_requested", 0): support_at,
        ("support_resolved", 0): support_resolved_at,
        ("completed", 0): feedback_at,
    }

    for (action, index), when in schedule_audit.items():
        row = _nth_match(audit_logs, "action", action, index)
        if row:
            row.created_at = when
    for (event_type, index), when in schedule_event.items():
        row = _nth_match(event_rows, "event_type", event_type, index)
        if row:
            row.created_at = when
    if hall_entries:
        hall_entry = hall_entries[0]
        hall_entry.created_at = support_at
        hall_entry.updated_at = support_resolved_at
        hall_entry.closed_at = support_resolved_at


async def _rebase_reassign_escalated_closed(
    db,
    work_order: WorkOrder,
    first_dispatch: DispatchTask,
    second_dispatch: DispatchTask,
    manager: User,
) -> None:
    created_at = work_order.created_at
    assert created_at is not None
    ai_at = created_at + timedelta(minutes=6)
    first_dispatch_at = created_at + timedelta(minutes=20)
    reassign_at = created_at + timedelta(minutes=42)
    second_dispatch_at = reassign_at + timedelta(minutes=1)
    accept_at = created_at + timedelta(minutes=56)
    arrive_at = created_at + timedelta(minutes=84)
    start_at = created_at + timedelta(minutes=96)
    feedback_at = created_at + timedelta(minutes=148)
    close_at = created_at + timedelta(minutes=180)

    work_order.ai_reviewed_at = ai_at
    work_order.pending_dispatch_at = ai_at
    work_order.assigned_at = second_dispatch_at
    work_order.accepted_at = accept_at
    work_order.arrived_at = arrive_at
    work_order.processing_started_at = start_at
    work_order.worker_feedback_at = feedback_at
    work_order.admin_reviewed_by = manager.id
    work_order.admin_reviewed_at = close_at
    work_order.closed_at = close_at
    work_order.updated_at = close_at

    first_dispatch.assigned_at = first_dispatch_at
    first_dispatch.closed_at = reassign_at
    first_dispatch.updated_at = reassign_at
    first_dispatch.latest_note = "综合值守到场前确认需改派自控班。"
    _set_dispatch_deadlines(first_dispatch)

    second_dispatch.assigned_at = second_dispatch_at
    second_dispatch.accepted_at = accept_at
    second_dispatch.arrived_at = arrive_at
    second_dispatch.processing_started_at = start_at
    second_dispatch.completed_at = feedback_at
    second_dispatch.closed_at = feedback_at
    second_dispatch.updated_at = feedback_at
    second_dispatch.latest_note = "已确认需外部厂商配合调参，转升级处理。"
    _set_dispatch_deadlines(second_dispatch)

    audit_logs = await _load_audit_logs(db, work_order.id)
    event_rows = await _load_dispatch_events(db, [first_dispatch.id, second_dispatch.id])

    schedule_audit = {
        ("create", 0): created_at,
        ("ai_approve", 0): ai_at,
        ("dispatch", 0): first_dispatch_at,
        ("worker_accept", 0): accept_at,
        ("worker_arrive", 0): arrive_at,
        ("worker_start", 0): start_at,
        ("worker_feedback", 0): feedback_at,
        ("close", 0): close_at,
    }
    schedule_event = {
        ("assigned", 0): first_dispatch_at,
        ("transferred", 0): reassign_at,
        ("assigned", 1): second_dispatch_at,
        ("accepted", 0): accept_at,
        ("arrived", 0): arrive_at,
        ("started", 0): start_at,
        ("escalated", 0): feedback_at,
    }

    for (action, index), when in schedule_audit.items():
        row = _nth_match(audit_logs, "action", action, index)
        if row:
            row.created_at = when
    for (event_type, index), when in schedule_event.items():
        row = _nth_match(event_rows, "event_type", event_type, index)
        if row:
            row.created_at = when


async def _rebase_false_alarm_closed(
    db,
    work_order: WorkOrder,
    dispatch_task: DispatchTask,
    manager: User,
) -> None:
    created_at = work_order.created_at
    assert created_at is not None
    ai_at = created_at + timedelta(minutes=3)
    dispatch_at = created_at + timedelta(minutes=12)
    accept_at = created_at + timedelta(minutes=26)
    arrive_at = created_at + timedelta(minutes=42)
    feedback_at = created_at + timedelta(minutes=61)
    close_at = created_at + timedelta(minutes=78)

    work_order.ai_reviewed_at = ai_at
    work_order.pending_dispatch_at = ai_at
    work_order.assigned_at = dispatch_at
    work_order.accepted_at = accept_at
    work_order.arrived_at = arrive_at
    work_order.processing_started_at = None
    work_order.worker_feedback_at = feedback_at
    work_order.admin_reviewed_by = manager.id
    work_order.admin_reviewed_at = close_at
    work_order.closed_at = close_at
    work_order.updated_at = close_at

    dispatch_task.assigned_at = dispatch_at
    dispatch_task.accepted_at = accept_at
    dispatch_task.arrived_at = arrive_at
    dispatch_task.processing_started_at = arrive_at
    dispatch_task.completed_at = feedback_at
    dispatch_task.closed_at = feedback_at
    dispatch_task.updated_at = feedback_at
    dispatch_task.latest_note = "现场复测正常，判定为瞬时误报。"
    _set_dispatch_deadlines(dispatch_task)

    audit_logs = await _load_audit_logs(db, work_order.id)
    event_rows = await _load_dispatch_events(db, [dispatch_task.id])

    schedule_audit = {
        ("create", 0): created_at,
        ("ai_approve", 0): ai_at,
        ("dispatch", 0): dispatch_at,
        ("worker_accept", 0): accept_at,
        ("worker_arrive", 0): arrive_at,
        ("worker_feedback", 0): feedback_at,
        ("close", 0): close_at,
    }
    schedule_event = {
        ("assigned", 0): dispatch_at,
        ("accepted", 0): accept_at,
        ("arrived", 0): arrive_at,
        ("completed", 0): feedback_at,
    }

    for (action, index), when in schedule_audit.items():
        row = _nth_match(audit_logs, "action", action, index)
        if row:
            row.created_at = when
    for (event_type, index), when in schedule_event.items():
        row = _nth_match(event_rows, "event_type", event_type, index)
        if row:
            row.created_at = when


async def _seed_one(db, seed: MockFlowSeed, manager: User, users_by_username: dict[str, User]) -> dict[str, Any]:
    worker = users_by_username.get(seed.primary_worker)
    if worker is None:
        raise RuntimeError(f"worker not found: {seed.primary_worker}")

    ticket_id = _ticket_id(seed)
    work_order = await create_work_order(
        db,
        ticket_id=ticket_id,
        building_id=seed.building_id,
        device_id=seed.device_id,
        issue_description=seed.issue_description,
        suggested_action=seed.suggested_action,
        priority=seed.priority,
        created_by=manager.id,
        source="manual",
    )
    work_order.created_at = seed.start_at
    work_order.updated_at = seed.start_at

    await apply_ai_review(
        db,
        work_order=work_order,
        decision="approve",
        reason="mock: operator ai timeline seed approved",
    )

    await assign_work_order(
        db,
        work_order=work_order,
        assigned_user=worker,
        actor_type="admin",
        actor_id=manager.id,
        notes="mock dispatch for operator ai timeline",
        dispatch_mode="manual",
        candidate_snapshot={"username": worker.username, "user_id": worker.id},
    )
    first_dispatch = await get_current_dispatch_task(db, work_order=work_order)
    if first_dispatch is None:
        raise RuntimeError(f"failed to create dispatch task for {ticket_id}")

    if seed.flow_type == "fixed_closed":
        await record_worker_dispatch_action(db, work_order=work_order, action="accept", actor_id=worker.id, notes="mock accepted")
        await record_worker_dispatch_action(db, work_order=work_order, action="arrive", actor_id=worker.id, notes="mock arrived")
        await record_worker_dispatch_action(db, work_order=work_order, action="start", actor_id=worker.id, notes="mock started")
        work_order.worker_result = "fixed"
        work_order.worker_notes = "已更换阀门执行器并恢复供冷。"
        work_order.worker_feedback_at = seed.start_at + timedelta(minutes=128)
        await complete_dispatch_task(
            db,
            work_order=work_order,
            dispatch_task=first_dispatch,
            actor_type="worker",
            actor_id=worker.id,
            result="fixed",
            notes=work_order.worker_notes,
        )
        await transition_status(
            db,
            work_order=work_order,
            new_status="completed",
            action="worker_feedback",
            actor_type="worker",
            actor_id=worker.id,
            detail={"result": "fixed", "notes": work_order.worker_notes},
        )
        work_order.admin_action = "confirm"
        work_order.admin_notes = "mock close after completed"
        work_order.admin_reviewed_by = manager.id
        await transition_status(
            db,
            work_order=work_order,
            new_status="closed",
            action="close",
            actor_type="admin",
            actor_id=manager.id,
            detail={"admin_action": "confirm", "notes": work_order.admin_notes},
        )
        await _rebase_fixed_closed(db, work_order, first_dispatch, manager, worker)
        return {
            "ticket_id": ticket_id,
            "path": "审批通过 -> 派工 -> 接单 -> 到场 -> 开始处理 -> 维修完成 -> 管理员关闭",
            "assigned_workers": [seed.primary_worker],
        }

    if seed.flow_type == "support_closed":
        support_user = users_by_username.get("ops_controls_01")
        support_team_id = getattr(getattr(support_user, "worker_profile", None), "team_id", None) if support_user else None
        await record_worker_dispatch_action(db, work_order=work_order, action="accept", actor_id=worker.id, notes="mock accepted")
        await record_worker_dispatch_action(db, work_order=work_order, action="arrive", actor_id=worker.id, notes="mock arrived")
        await record_worker_dispatch_action(db, work_order=work_order, action="start", actor_id=worker.id, notes="mock started")
        await record_worker_dispatch_action(
            db,
            work_order=work_order,
            action="request_support",
            actor_id=worker.id,
            notes="mock request support for drain pipe",
            support_team_id=support_team_id,
        )
        await record_worker_dispatch_action(
            db,
            work_order=work_order,
            action="support_resolved",
            actor_id=worker.id,
            notes="mock support resolved",
        )
        work_order.worker_result = "fixed"
        work_order.worker_notes = "协同疏通后恢复排水，现场已清理。"
        work_order.worker_feedback_at = seed.start_at + timedelta(minutes=166)
        await complete_dispatch_task(
            db,
            work_order=work_order,
            dispatch_task=first_dispatch,
            actor_type="worker",
            actor_id=worker.id,
            result="fixed",
            notes=work_order.worker_notes,
        )
        await transition_status(
            db,
            work_order=work_order,
            new_status="completed",
            action="worker_feedback",
            actor_type="worker",
            actor_id=worker.id,
            detail={"result": "fixed", "notes": work_order.worker_notes},
        )
        work_order.admin_action = "confirm"
        work_order.admin_notes = "mock close after support flow"
        work_order.admin_reviewed_by = manager.id
        await transition_status(
            db,
            work_order=work_order,
            new_status="closed",
            action="close",
            actor_type="admin",
            actor_id=manager.id,
            detail={"admin_action": "confirm", "notes": work_order.admin_notes},
        )
        await _rebase_support_closed(db, work_order, first_dispatch, manager)
        return {
            "ticket_id": ticket_id,
            "path": "审批通过 -> 派工 -> 接单 -> 到场 -> 开始处理 -> 申请协同 -> 协同完成 -> 维修完成 -> 管理员关闭",
            "assigned_workers": [seed.primary_worker],
        }

    if seed.flow_type == "reassign_escalated_closed":
        reassign_user = users_by_username.get(seed.reassign_to or "")
        if reassign_user is None:
            raise RuntimeError(f"reassign target not found: {seed.reassign_to}")
        second_dispatch = await reassign_dispatch_task(
            db,
            work_order=work_order,
            dispatch_task=first_dispatch,
            assigned_user=reassign_user,
            actor_type="admin",
            actor_id=manager.id,
            reason="mock: reassigned to controls team",
            dispatch_mode="reassigned",
            candidate_snapshot={"username": reassign_user.username, "user_id": reassign_user.id},
        )
        await record_worker_dispatch_action(db, work_order=work_order, action="accept", actor_id=reassign_user.id, notes="mock accepted")
        await record_worker_dispatch_action(db, work_order=work_order, action="arrive", actor_id=reassign_user.id, notes="mock arrived")
        await record_worker_dispatch_action(db, work_order=work_order, action="start", actor_id=reassign_user.id, notes="mock started")
        work_order.worker_result = "escalated"
        work_order.worker_notes = "已确认需外部厂商配合调参，转升级处理。"
        work_order.worker_feedback_at = seed.start_at + timedelta(minutes=148)
        await complete_dispatch_task(
            db,
            work_order=work_order,
            dispatch_task=second_dispatch,
            actor_type="worker",
            actor_id=reassign_user.id,
            result="escalated",
            notes=work_order.worker_notes,
        )
        await transition_status(
            db,
            work_order=work_order,
            new_status="escalated",
            action="worker_feedback",
            actor_type="worker",
            actor_id=reassign_user.id,
            detail={"result": "escalated", "notes": work_order.worker_notes},
        )
        work_order.admin_action = "close_escalated"
        work_order.admin_notes = "mock close escalated order"
        work_order.admin_reviewed_by = manager.id
        await transition_status(
            db,
            work_order=work_order,
            new_status="closed",
            action="close",
            actor_type="admin",
            actor_id=manager.id,
            detail={"admin_action": "close_escalated", "notes": work_order.admin_notes},
        )
        await _rebase_reassign_escalated_closed(db, work_order, first_dispatch, second_dispatch, manager)
        return {
            "ticket_id": ticket_id,
            "path": "审批通过 -> 首次派工 -> 改派 -> 接单 -> 到场 -> 开始处理 -> 升级处理 -> 管理员关闭",
            "assigned_workers": [seed.primary_worker, seed.reassign_to],
        }

    if seed.flow_type == "false_alarm_closed":
        await record_worker_dispatch_action(db, work_order=work_order, action="accept", actor_id=worker.id, notes="mock accepted")
        await record_worker_dispatch_action(db, work_order=work_order, action="arrive", actor_id=worker.id, notes="mock arrived")
        work_order.worker_result = "false_alarm"
        work_order.worker_notes = "现场复测正常，判定为瞬时误报。"
        work_order.worker_feedback_at = seed.start_at + timedelta(minutes=61)
        await complete_dispatch_task(
            db,
            work_order=work_order,
            dispatch_task=first_dispatch,
            actor_type="worker",
            actor_id=worker.id,
            result="false_alarm",
            notes=work_order.worker_notes,
        )
        await transition_status(
            db,
            work_order=work_order,
            new_status="false_alarm",
            action="worker_feedback",
            actor_type="worker",
            actor_id=worker.id,
            detail={"result": "false_alarm", "notes": work_order.worker_notes},
        )
        work_order.admin_action = "confirm"
        work_order.admin_notes = "mock close false alarm"
        work_order.admin_reviewed_by = manager.id
        await transition_status(
            db,
            work_order=work_order,
            new_status="closed",
            action="close",
            actor_type="admin",
            actor_id=manager.id,
            detail={"admin_action": "confirm", "notes": work_order.admin_notes},
        )
        await _rebase_false_alarm_closed(db, work_order, first_dispatch, manager)
        return {
            "ticket_id": ticket_id,
            "path": "审批通过 -> 派工 -> 接单 -> 到场 -> 现场判定误报 -> 管理员关闭",
            "assigned_workers": [seed.primary_worker],
        }

    raise RuntimeError(f"unsupported flow type: {seed.flow_type}")


def _query_examples(ticket_ids: list[str]) -> list[str]:
    return [
        f"查一下 {ticket_ids[0]} 的完整流程",
        f"{ticket_ids[1]} 为什么需要协同",
        f"{ticket_ids[2]} 为什么改派，后来是谁接的",
        f"{ticket_ids[3]} 为什么被判定为误报",
        f"最近这几张 mock 工单 {', '.join(ticket_ids)} 的处理结果分别是什么",
    ]


def _is_retryable_seed_error(exc: Exception) -> bool:
    if isinstance(exc, asyncio.TimeoutError):
        return True
    text = f"{type(exc).__name__}: {exc}".lower()
    return any(
        token in text
        for token in (
            "timeout",
            "connection reset",
            "connection refused",
            "cannot connect",
            "closed the connection unexpectedly",
            "ssl",
            "handshake",
            "cancellederror",
        )
    )


async def _seed_mock_work_orders_once(*, manager_username: str, cleanup_existing: bool) -> dict[str, Any]:
    _ensure_allowed_workers()
    async with AsyncSessionLocal() as db:
        users_by_username = await _load_users(db)
        manager = await _resolve_manager(db, users_by_username, manager_username)

        missing = [
            username
            for username in {
                *(seed.primary_worker for seed in SEEDS),
                *(seed.reassign_to for seed in SEEDS if seed.reassign_to),
            }
            if username not in users_by_username
        ]
        if missing:
            raise RuntimeError(f"missing required workers: {sorted(missing)}")

        deleted: list[str] = []
        if cleanup_existing:
            deleted = await _cleanup_existing(db)

        created: list[dict[str, Any]] = []
        for seed in SEEDS:
            created.append(await _seed_one(db, seed, manager, users_by_username))

        await db.commit()

    ticket_ids = [item["ticket_id"] for item in created]
    return {
        "manager_username": manager.username,
        "deleted_existing": deleted,
        "created": created,
        "query_examples": _query_examples(ticket_ids),
        "notes": [
            "all mock orders avoid ops_electrical_01",
            "monthly summary will still include historical work_orders in the same date range",
            "for operator ai validation, prefer asking by ticket id or with a narrow date range",
        ],
    }


async def seed_mock_work_orders(
    *,
    manager_username: str,
    cleanup_existing: bool,
    db_attempts: int,
    db_timeout_seconds: float,
) -> dict[str, Any]:
    last_error: Exception | None = None
    attempts = max(1, db_attempts)
    timeout_seconds = max(30.0, float(db_timeout_seconds))

    for attempt in range(1, attempts + 1):
        try:
            return await asyncio.wait_for(
                _seed_mock_work_orders_once(
                    manager_username=manager_username,
                    cleanup_existing=cleanup_existing,
                ),
                timeout=timeout_seconds,
            )
        except Exception as exc:
            last_error = exc
            await engine.dispose()
            if not _is_retryable_seed_error(exc):
                raise
            if attempt >= attempts:
                break
            print(
                f"[seed_operator_ai_mock_workorders] attempt {attempt}/{attempts} failed: "
                f"{type(exc).__name__}: {exc}. retrying...",
                file=sys.stderr,
            )
            await asyncio.sleep(attempt)

    assert last_error is not None
    raise RuntimeError(
        "mock 工单写入失败。数据库操作超时。"
        f" 已重试 {attempts} 次，每次超时 {timeout_seconds:.0f}s。"
        " 建议先确认数据库连接稳定，再重跑脚本。"
    ) from last_error


def _print_result(result: dict[str, Any]) -> None:
    print("== Mock Work Orders Seeded ==")
    print(f"manager: {result['manager_username']}")
    if result["deleted_existing"]:
        print("deleted_existing:")
        for ticket_id in result["deleted_existing"]:
            print(f"  - {ticket_id}")
    print("created:")
    for item in result["created"]:
        workers = ", ".join(item["assigned_workers"])
        print(f"  - {item['ticket_id']}: {item['path']} | workers={workers}")
    print("query_examples:")
    for query in result["query_examples"]:
        print(f"  - {query}")
    print("notes:")
    for note in result["notes"]:
        print(f"  - {note}")


async def main_async() -> int:
    parser = argparse.ArgumentParser(description="Seed operator-ai mock work orders with full lifecycle timelines.")
    parser.add_argument("--manager-username", default=DEFAULT_MANAGER_USERNAME)
    parser.add_argument("--no-cleanup-existing", action="store_true")
    parser.add_argument("--db-attempts", type=int, default=3)
    parser.add_argument("--db-timeout-seconds", type=float, default=180.0)
    args = parser.parse_args()

    result = await seed_mock_work_orders(
        manager_username=args.manager_username,
        cleanup_existing=not args.no_cleanup_existing,
        db_attempts=args.db_attempts,
        db_timeout_seconds=args.db_timeout_seconds,
    )
    _print_result(result)
    return 0


def main() -> int:
    return asyncio.run(main_async())


if __name__ == "__main__":
    raise SystemExit(main())
