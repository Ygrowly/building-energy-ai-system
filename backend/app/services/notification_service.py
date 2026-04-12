from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from collections.abc import Iterable
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import event, func as sa_func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session as SyncSession
from sqlalchemy.orm import joinedload, selectinload

from app.db.models import (
    DispatchEvent,
    DispatchHallEntry,
    DispatchTask,
    NotificationRecord,
    NotificationRecipient,
    User,
    WorkOrder,
    WorkOrderAuditLog,
    WorkerProfile,
    WorkerProfileSkill,
)
from app.db.session import AsyncSessionLocal
from app.services.notification_realtime_service import publish_user_event

logger = logging.getLogger(__name__)

_PENDING_KEY = "notification_after_commit"
_WORKORDER_CATEGORY = "workorder"
_MANAGER_ROLES = {"manager", "admin"}
_DISPATCH_EVENT_TYPES = {
    "assigned",
    "auto_assigned",
    "accepted",
    "arrived",
    "started",
    "support_requested",
    "support_resolved",
    "rejected",
    "cancelled",
    "transferred",
    "reminded",
    "timeout_warning",
    "timeout_overdue",
    "support_assigned",
    "support_worker_accepted",
    "support_worker_rejected",
}
_AUDIT_ACTIONS = {
    "worker_feedback",
    "close",
    "admin_override",
}


def _dt_to_iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _json_dumps(payload: dict[str, Any] | None) -> str | None:
    if not payload:
        return None
    return json.dumps(payload, ensure_ascii=False, default=str)


def _json_loads(payload: str | None) -> dict[str, Any]:
    if not payload:
        return {}
    try:
        data = json.loads(payload)
    except (TypeError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _session_info(db: AsyncSession) -> dict[str, Any]:
    session = getattr(db, "sync_session", db)
    return session.info


def _queue_after_commit(
    db: AsyncSession,
    *,
    created_recipient_ids: Iterable[str] = (),
    read_recipient_ids: Iterable[str] = (),
    summary_user_ids: Iterable[str] = (),
) -> None:
    info = _session_info(db)
    pending = info.setdefault(
        _PENDING_KEY,
        {
            "created_recipient_ids": set(),
            "read_recipient_ids": set(),
            "summary_user_ids": set(),
        },
    )
    pending["created_recipient_ids"].update(str(item) for item in created_recipient_ids if item)
    pending["read_recipient_ids"].update(str(item) for item in read_recipient_ids if item)
    pending["summary_user_ids"].update(str(item) for item in summary_user_ids if item)


async def _load_active_role_users(db: AsyncSession, roles: set[str]) -> list[User]:
    result = await db.execute(
        select(User)
        .where(User.role.in_(list(roles)), User.is_active == True)  # noqa: E712
        .order_by(User.username.asc())
    )
    return list(result.scalars().all())


async def _load_work_order(db: AsyncSession, work_order_id: str) -> WorkOrder | None:
    if not work_order_id:
        return None
    result = await db.execute(
        select(WorkOrder).where(WorkOrder.id == work_order_id)
    )
    return result.scalar_one_or_none()


async def _load_dispatch_task(db: AsyncSession, dispatch_task_id: str) -> DispatchTask | None:
    if not dispatch_task_id:
        return None
    return await db.get(DispatchTask, dispatch_task_id)


async def _load_visible_hall_users(db: AsyncSession, hall_entry: DispatchHallEntry) -> list[User]:
    from app.services.dispatch_hall_service import _hall_entry_visible_to_user

    result = await db.execute(
        select(User)
        .options(
            selectinload(User.worker_profile).selectinload(WorkerProfile.team),
            selectinload(User.worker_profile)
            .selectinload(WorkerProfile.skill_links)
            .selectinload(WorkerProfileSkill.skill),
        )
        .where(User.role == "ops", User.is_active == True)  # noqa: E712
        .order_by(User.username.asc())
    )
    candidates = list(result.scalars().all())
    return [user for user in candidates if _hall_entry_visible_to_user(hall_entry, user)]


def _unique_users(users: Iterable[User]) -> list[User]:
    result: list[User] = []
    seen: set[str] = set()
    for user in users:
        user_id = str(getattr(user, "id", "") or "").strip()
        if not user_id or user_id in seen:
            continue
        seen.add(user_id)
        result.append(user)
    return result


async def _load_existing_hall_recipients(
    db: AsyncSession,
    *,
    hall_entry_id: str,
) -> list[User]:
    result = await db.execute(
        select(User)
        .join(NotificationRecipient, NotificationRecipient.user_id == User.id)
        .join(NotificationRecord, NotificationRecord.id == NotificationRecipient.notification_id)
        .where(
            NotificationRecord.aggregate_type == "dispatch_hall_entry",
            NotificationRecord.aggregate_id == hall_entry_id,
            User.is_active == True,  # noqa: E712
        )
        .order_by(User.username.asc())
    )
    return _unique_users(result.scalars().all())


async def _ensure_notification_record(
    db: AsyncSession,
    *,
    category: str,
    event_type: str,
    source_type: str,
    source_id: str,
    aggregate_type: str,
    aggregate_id: str,
    title: str,
    body: str,
    severity: str,
    payload: dict[str, Any] | None,
) -> NotificationRecord:
    existing_result = await db.execute(
        select(NotificationRecord).where(
            NotificationRecord.source_type == source_type,
            NotificationRecord.source_id == source_id,
        )
    )
    existing = existing_result.scalar_one_or_none()
    if existing is not None:
        return existing

    record = NotificationRecord(
        category=category,
        event_type=event_type,
        source_type=source_type,
        source_id=source_id,
        aggregate_type=aggregate_type,
        aggregate_id=aggregate_id,
        title=title,
        body=body,
        severity=severity,
        payload_json=_json_dumps(payload),
    )
    db.add(record)
    await db.flush()
    return record


async def _ensure_recipients(
    db: AsyncSession,
    *,
    record: NotificationRecord,
    recipients: Iterable[User],
    actor_id: str | None = None,
) -> list[NotificationRecipient]:
    users = _unique_users(
        user
        for user in recipients
        if getattr(user, "role", None) in {"ops", "manager", "admin"}
    )
    if actor_id:
        users = [user for user in users if user.id != actor_id]
    if not users:
        return []

    user_ids = [user.id for user in users]
    existing_result = await db.execute(
        select(NotificationRecipient).where(
            NotificationRecipient.source_type == record.source_type,
            NotificationRecipient.source_id == record.source_id,
            NotificationRecipient.user_id.in_(user_ids),
        )
    )
    existing_user_ids = {item.user_id for item in existing_result.scalars().all()}

    created: list[NotificationRecipient] = []
    for user in users:
        if user.id in existing_user_ids:
            continue
        recipient = NotificationRecipient(
            notification_id=record.id,
            user_id=user.id,
            recipient_role=user.role,
            source_type=record.source_type,
            source_id=record.source_id,
        )
        db.add(recipient)
        created.append(recipient)

    if not created:
        return []

    await db.flush()
    _queue_after_commit(
        db,
        created_recipient_ids=[recipient.id for recipient in created],
        summary_user_ids=[recipient.user_id for recipient in created],
    )
    return created


def _dispatch_event_payload(event: DispatchEvent) -> dict[str, Any]:
    return _json_loads(getattr(event, "payload_json", None))


def _build_dispatch_payload(
    *,
    work_order: WorkOrder | None,
    dispatch_task: DispatchTask | None,
    extra_payload: dict[str, Any],
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "ticket_id": getattr(work_order, "ticket_id", None),
        "work_order_id": getattr(work_order, "id", None),
        "incident_id": getattr(work_order, "incident_id", None) or getattr(dispatch_task, "incident_id", None),
        "dispatch_id": getattr(dispatch_task, "id", None),
        "building_id": getattr(work_order, "building_id", None),
        "cta_type": "open_workorder",
        "cta_params": {
            "ticket_id": getattr(work_order, "ticket_id", None),
            "incident_id": getattr(work_order, "incident_id", None) or getattr(dispatch_task, "incident_id", None),
            "dispatch_id": getattr(dispatch_task, "id", None),
        },
    }
    payload.update(extra_payload)
    return payload


def _dispatch_event_content(
    *,
    event_type: str,
    work_order: WorkOrder | None,
    dispatch_task: DispatchTask | None,
    event_payload: dict[str, Any],
) -> tuple[str, str, str, dict[str, Any]]:
    ticket_id = getattr(work_order, "ticket_id", None) or "工单"
    assignee_name = (
        event_payload.get("assigned_to_name")
        or event_payload.get("assignee_name")
        or event_payload.get("support_assignee_name")
        or getattr(dispatch_task, "assigned_to_name", None)
        or "责任人"
    )
    note = (
        event_payload.get("notes")
        or event_payload.get("reason")
        or event_payload.get("support_reason")
        or event_payload.get("message")
        or event_payload.get("selection_reason")
        or getattr(dispatch_task, "latest_note", None)
    )
    severity = "info"

    if event_type in {"assigned", "auto_assigned"}:
        title = f"{ticket_id} 已派单"
        body = f"工单已派发给 {assignee_name}。"
    elif event_type == "accepted":
        title = f"{ticket_id} 已接单"
        body = f"{assignee_name} 已确认接单。"
    elif event_type == "arrived":
        title = f"{ticket_id} 已到场"
        body = f"{assignee_name} 已到达现场。"
    elif event_type == "started":
        title = f"{ticket_id} 开始处理"
        body = f"{assignee_name} 已开始处理工单。"
    elif event_type == "support_requested":
        title = f"{ticket_id} 发起协同"
        body = note or "当前工单发起了协同支援请求。"
        severity = "warning"
    elif event_type == "support_resolved":
        title = f"{ticket_id} 协同完成"
        body = note or "协同事项已处理完成，工单恢复现场处理。"
        severity = "success"
    elif event_type == "rejected":
        title = f"{ticket_id} 已拒单"
        body = note or f"{assignee_name} 拒绝了当前派工。"
        severity = "danger"
    elif event_type == "cancelled":
        title = f"{ticket_id} 派工已取消"
        body = note or "当前派工已取消，等待重新安排。"
        severity = "warning"
    elif event_type == "transferred":
        title = f"{ticket_id} 已转派"
        body = note or "工单已重新指派给新的责任人。"
        severity = "warning"
    elif event_type == "reminded":
        title = f"{ticket_id} 已催办"
        body = note or "工单已发起催办，请尽快处理。"
        severity = "warning"
    elif event_type in {"timeout_warning", "timeout_overdue"}:
        title = f"{ticket_id} 已超时"
        body = note or "工单处理节点已超时，请立即跟进。"
        severity = "danger"
    elif event_type == "support_assigned":
        title = f"{ticket_id} 协同已指派"
        body = f"协同任务已指派给 {event_payload.get('assigned_to_name') or assignee_name}。"
        severity = "warning"
    elif event_type == "support_worker_accepted":
        title = f"{ticket_id} 协同已确认"
        body = note or "协同维修人员已确认任务。"
    elif event_type == "support_worker_rejected":
        title = f"{ticket_id} 协同被拒绝"
        body = note or "协同维修人员拒绝了当前任务。"
        severity = "warning"
    else:
        title = f"{ticket_id} 状态更新"
        body = note or "工单状态发生变化。"

    payload = _build_dispatch_payload(
        work_order=work_order,
        dispatch_task=dispatch_task,
        extra_payload=event_payload,
    )
    return title, body, severity, payload


def _audit_content(
    *,
    audit_log: WorkOrderAuditLog,
    work_order: WorkOrder | None,
) -> tuple[str, str, str, dict[str, Any]] | None:
    if audit_log.action not in _AUDIT_ACTIONS:
        return None

    detail = _json_loads(getattr(audit_log, "detail_json", None))
    ticket_id = getattr(work_order, "ticket_id", None) or "工单"
    payload = {
        "ticket_id": getattr(work_order, "ticket_id", None),
        "work_order_id": getattr(work_order, "id", None),
        "incident_id": getattr(work_order, "incident_id", None),
        "building_id": getattr(work_order, "building_id", None),
        "cta_type": "open_workorder",
        "cta_params": {
            "ticket_id": getattr(work_order, "ticket_id", None),
            "incident_id": getattr(work_order, "incident_id", None),
        },
        **detail,
    }

    if audit_log.action == "worker_feedback":
        result = detail.get("result")
        if result == "fixed":
            return f"{ticket_id} 已完工", "维修人员已提交完工反馈，等待复核关闭。", "success", payload
        if result == "false_alarm":
            return f"{ticket_id} 标记为误报", "维修人员已提交误报反馈，等待复核关闭。", "success", payload
        if result == "escalated":
            return f"{ticket_id} 已升级", "维修人员已提交升级反馈，等待管理端继续跟进。", "warning", payload
        return f"{ticket_id} 反馈更新", detail.get("notes") or "维修反馈已更新。", "info", payload

    if audit_log.action == "close":
        return f"{ticket_id} 已关闭", detail.get("notes") or "工单已完成关闭。", "success", payload

    if audit_log.action == "admin_override":
        return f"{ticket_id} 管理员已处理", detail.get("notes") or "管理员已对工单执行覆盖处理。", "warning", payload

    return None


async def _dispatch_event_recipients(
    db: AsyncSession,
    *,
    event: DispatchEvent,
    dispatch_task: DispatchTask,
    event_payload: dict[str, Any],
) -> list[User]:
    manager_users = await _load_active_role_users(db, _MANAGER_ROLES)
    recipients: list[User] = list(manager_users)

    if event.event_type in {"assigned", "auto_assigned"}:
        if dispatch_task.assigned_to:
            assigned_user = await db.get(User, dispatch_task.assigned_to)
            if assigned_user is not None and assigned_user.is_active:
                recipients.append(assigned_user)
        return _unique_users(recipients)

    if event.event_type in {
        "accepted",
        "arrived",
        "started",
        "support_requested",
        "support_resolved",
        "rejected",
        "cancelled",
        "transferred",
        "reminded",
        "timeout_warning",
        "timeout_overdue",
    }:
        if dispatch_task.assigned_to:
            assigned_user = await db.get(User, dispatch_task.assigned_to)
            if assigned_user is not None and assigned_user.is_active:
                recipients.append(assigned_user)
        return _unique_users(recipients)

    if event.event_type == "support_assigned":
        original_user = await db.get(User, dispatch_task.assigned_to) if dispatch_task.assigned_to else None
        support_user_id = str(event_payload.get("assigned_to") or "").strip()
        support_user = await db.get(User, support_user_id) if support_user_id else None
        if original_user is not None and original_user.is_active:
            recipients.append(original_user)
        if support_user is not None and support_user.is_active:
            recipients.append(support_user)
        return _unique_users(recipients)

    if event.event_type in {"support_worker_accepted", "support_worker_rejected"}:
        original_user = await db.get(User, dispatch_task.assigned_to) if dispatch_task.assigned_to else None
        support_user = await db.get(User, event.actor_id) if event.actor_id else None
        if original_user is not None and original_user.is_active:
            recipients.append(original_user)
        if support_user is not None and support_user.is_active:
            recipients.append(support_user)
        return _unique_users(recipients)

    return _unique_users(recipients)


async def _audit_recipients(
    db: AsyncSession,
    *,
    work_order: WorkOrder | None,
) -> list[User]:
    recipients = await _load_active_role_users(db, _MANAGER_ROLES)
    assigned_to = getattr(work_order, "assigned_to", None)
    if assigned_to:
        assigned_user = await db.get(User, assigned_to)
        if assigned_user is not None and assigned_user.is_active:
            recipients.append(assigned_user)
    return _unique_users(recipients)


async def create_notifications_for_dispatch_event(
    db: AsyncSession,
    *,
    event: DispatchEvent,
    dispatch_task: DispatchTask | None = None,
) -> list[NotificationRecipient]:
    if event.event_type not in _DISPATCH_EVENT_TYPES:
        return []

    task = dispatch_task or await _load_dispatch_task(db, event.dispatch_task_id)
    if task is None:
        return []
    work_order = await _load_work_order(db, task.work_order_id)
    event_payload = _dispatch_event_payload(event)
    title, body, severity, payload = _dispatch_event_content(
        event_type=event.event_type,
        work_order=work_order,
        dispatch_task=task,
        event_payload=event_payload,
    )
    record = await _ensure_notification_record(
        db,
        category=_WORKORDER_CATEGORY,
        event_type=event.event_type,
        source_type="dispatch_event",
        source_id=event.id,
        aggregate_type="work_order",
        aggregate_id=task.work_order_id,
        title=title,
        body=body,
        severity=severity,
        payload=payload,
    )
    recipients = await _dispatch_event_recipients(
        db,
        event=event,
        dispatch_task=task,
        event_payload=event_payload,
    )
    return await _ensure_recipients(
        db,
        record=record,
        recipients=recipients,
        actor_id=event.actor_id,
    )


async def create_notifications_for_audit_log(
    db: AsyncSession,
    *,
    audit_log: WorkOrderAuditLog,
) -> list[NotificationRecipient]:
    work_order = await _load_work_order(db, audit_log.work_order_id)
    content = _audit_content(audit_log=audit_log, work_order=work_order)
    if content is None:
        return []

    title, body, severity, payload = content
    record = await _ensure_notification_record(
        db,
        category=_WORKORDER_CATEGORY,
        event_type=audit_log.action,
        source_type="work_order_audit",
        source_id=audit_log.id,
        aggregate_type="work_order",
        aggregate_id=audit_log.work_order_id,
        title=title,
        body=body,
        severity=severity,
        payload=payload,
    )
    recipients = await _audit_recipients(db, work_order=work_order)
    return await _ensure_recipients(
        db,
        record=record,
        recipients=recipients,
        actor_id=audit_log.actor_id,
    )


async def create_notifications_for_dispatch_hall_open(
    db: AsyncSession,
    *,
    hall_entry: DispatchHallEntry,
    work_order: WorkOrder,
    actor_id: str | None = None,
) -> list[NotificationRecipient]:
    if hall_entry.status != "open":
        return []

    manager_users = await _load_active_role_users(db, _MANAGER_ROLES)
    visible_ops = await _load_visible_hall_users(db, hall_entry)
    recipients = _unique_users([*visible_ops, *manager_users])

    payload = {
        "ticket_id": work_order.ticket_id,
        "work_order_id": work_order.id,
        "incident_id": work_order.incident_id,
        "building_id": work_order.building_id,
        "hall_entry_id": hall_entry.id,
        "entry_type": hall_entry.entry_type,
        "cta_type": "open_hall_entry",
        "cta_params": {
            "hall_entry_id": hall_entry.id,
            "ticket_id": work_order.ticket_id,
            "incident_id": work_order.incident_id,
        },
    }

    if hall_entry.entry_type == "takeover_candidate":
        event_type = "dispatch_hall_takeover_open"
        title = f"{work_order.ticket_id} 进入接管大厅"
        body = hall_entry.reason or "当前工单已进入接管大厅，等待新的责任人接管。"
        severity = "danger"
    else:
        event_type = "dispatch_hall_support_open"
        title = f"{work_order.ticket_id} 发起协同大厅"
        body = hall_entry.support_reason or hall_entry.reason or "当前工单发起了协同支援请求。"
        severity = "warning"

    source_ts = _dt_to_iso(hall_entry.updated_at or hall_entry.created_at) or hall_entry.id
    record = await _ensure_notification_record(
        db,
        category=_WORKORDER_CATEGORY,
        event_type=event_type,
        source_type="dispatch_hall_open",
        source_id=f"{hall_entry.id}:{source_ts}",
        aggregate_type="dispatch_hall_entry",
        aggregate_id=hall_entry.id,
        title=title,
        body=body,
        severity=severity,
        payload=payload,
    )
    return await _ensure_recipients(
        db,
        record=record,
        recipients=recipients,
        actor_id=actor_id or hall_entry.created_by,
    )


async def create_notifications_for_dispatch_hall_closed(
    db: AsyncSession,
    *,
    hall_entry: DispatchHallEntry,
    work_order: WorkOrder | None = None,
    actor_id: str | None = None,
) -> list[NotificationRecipient]:
    recipients = await _load_existing_hall_recipients(db, hall_entry_id=hall_entry.id)
    if not recipients:
        return []

    resolved_work_order = work_order or await _load_work_order(db, hall_entry.work_order_id)
    ticket_id = getattr(resolved_work_order, "ticket_id", None) or "工单"
    payload = {
        "ticket_id": getattr(resolved_work_order, "ticket_id", None),
        "work_order_id": getattr(resolved_work_order, "id", None),
        "incident_id": getattr(resolved_work_order, "incident_id", None),
        "building_id": getattr(resolved_work_order, "building_id", None),
        "hall_entry_id": hall_entry.id,
        "entry_type": hall_entry.entry_type,
        "cta_type": "open_workorder",
        "cta_params": {
            "ticket_id": getattr(resolved_work_order, "ticket_id", None),
            "incident_id": getattr(resolved_work_order, "incident_id", None),
            "hall_entry_id": hall_entry.id,
        },
    }
    source_ts = _dt_to_iso(hall_entry.updated_at or hall_entry.closed_at) or hall_entry.id
    record = await _ensure_notification_record(
        db,
        category=_WORKORDER_CATEGORY,
        event_type="dispatch_hall_closed",
        source_type="dispatch_hall_close",
        source_id=f"{hall_entry.id}:{source_ts}",
        aggregate_type="dispatch_hall_entry",
        aggregate_id=hall_entry.id,
        title=f"{ticket_id} 大厅任务已关闭",
        body="共享大厅任务已关闭，请查看工单最新状态。",
        severity="info",
        payload=payload,
    )
    return await _ensure_recipients(
        db,
        record=record,
        recipients=recipients,
        actor_id=actor_id,
    )


async def list_notifications(
    db: AsyncSession,
    *,
    user_id: str,
    category: str | None = None,
    status: str = "all",
    page: int = 1,
    page_size: int = 20,
) -> tuple[list[NotificationRecipient], int]:
    query = (
        select(NotificationRecipient)
        .join(NotificationRecord, NotificationRecord.id == NotificationRecipient.notification_id)
        .options(joinedload(NotificationRecipient.notification))
        .where(NotificationRecipient.user_id == user_id)
    )
    count_query = (
        select(sa_func.count(NotificationRecipient.id))
        .select_from(NotificationRecipient)
        .join(NotificationRecord, NotificationRecord.id == NotificationRecipient.notification_id)
        .where(NotificationRecipient.user_id == user_id)
    )
    if category:
        query = query.where(NotificationRecord.category == category)
        count_query = count_query.where(NotificationRecord.category == category)
    if status == "unread":
        query = query.where(NotificationRecipient.is_read == False)  # noqa: E712
        count_query = count_query.where(NotificationRecipient.is_read == False)  # noqa: E712

    total = int((await db.execute(count_query)).scalar() or 0)
    offset = max(page - 1, 0) * page_size
    query = query.order_by(
        NotificationRecipient.is_read.asc(),
        NotificationRecord.created_at.desc(),
        NotificationRecipient.created_at.desc(),
    ).offset(offset).limit(page_size)
    result = await db.execute(query)
    return list(result.scalars().all()), total


async def get_notification_summary(
    db: AsyncSession,
    *,
    user_id: str,
) -> dict[str, Any]:
    category_result = await db.execute(
        select(NotificationRecord.category, sa_func.count(NotificationRecipient.id))
        .join(NotificationRecipient, NotificationRecipient.notification_id == NotificationRecord.id)
        .where(
            NotificationRecipient.user_id == user_id,
            NotificationRecipient.is_read == False,  # noqa: E712
        )
        .group_by(NotificationRecord.category)
    )
    categories = {str(category): int(count) for category, count in category_result.all()}

    event_result = await db.execute(
        select(NotificationRecord.event_type, sa_func.count(NotificationRecipient.id))
        .join(NotificationRecipient, NotificationRecipient.notification_id == NotificationRecord.id)
        .where(
            NotificationRecipient.user_id == user_id,
            NotificationRecipient.is_read == False,  # noqa: E712
        )
        .group_by(NotificationRecord.event_type)
    )
    event_types = {str(event_type): int(count) for event_type, count in event_result.all()}
    return {
        "total_unread": int(sum(categories.values())),
        "categories": categories,
        "event_types": event_types,
    }


def serialize_notification_recipient(recipient: NotificationRecipient) -> dict[str, Any]:
    record = recipient.notification
    payload = _json_loads(getattr(record, "payload_json", None))
    return {
        "recipient_id": recipient.id,
        "notification_id": record.id,
        "category": record.category,
        "event_type": record.event_type,
        "title": record.title,
        "body": record.body,
        "severity": record.severity,
        "aggregate_type": record.aggregate_type,
        "aggregate_id": record.aggregate_id,
        "related_ticket_id": payload.get("ticket_id"),
        "related_dispatch_id": payload.get("dispatch_id"),
        "cta_type": payload.get("cta_type"),
        "cta_params": payload.get("cta_params") or {},
        "created_at": _dt_to_iso(record.created_at),
        "read_at": _dt_to_iso(recipient.read_at),
        "payload": payload,
    }


async def mark_notification_recipients_read(
    db: AsyncSession,
    *,
    user_id: str,
    recipient_ids: list[str],
) -> list[NotificationRecipient]:
    if not recipient_ids:
        return []
    result = await db.execute(
        select(NotificationRecipient)
        .options(joinedload(NotificationRecipient.notification))
        .where(
            NotificationRecipient.user_id == user_id,
            NotificationRecipient.id.in_(recipient_ids),
        )
    )
    items = list(result.scalars().all())
    if not items:
        return []

    now = datetime.now(timezone.utc)
    changed: list[NotificationRecipient] = []
    for item in items:
        if item.is_read:
            continue
        item.is_read = True
        item.read_at = now
        changed.append(item)
    if not changed:
        return []

    await db.flush()
    _queue_after_commit(
        db,
        read_recipient_ids=[item.id for item in changed],
        summary_user_ids=[user_id],
    )
    return changed


async def mark_all_notifications_read(
    db: AsyncSession,
    *,
    user_id: str,
    category: str | None = None,
) -> list[NotificationRecipient]:
    query = (
        select(NotificationRecipient)
        .join(NotificationRecord, NotificationRecord.id == NotificationRecipient.notification_id)
        .options(joinedload(NotificationRecipient.notification))
        .where(
            NotificationRecipient.user_id == user_id,
            NotificationRecipient.is_read == False,  # noqa: E712
        )
    )
    if category:
        query = query.where(NotificationRecord.category == category)

    result = await db.execute(query)
    items = list(result.scalars().all())
    if not items:
        return []

    now = datetime.now(timezone.utc)
    for item in items:
        item.is_read = True
        item.read_at = now

    await db.flush()
    _queue_after_commit(
        db,
        read_recipient_ids=[item.id for item in items],
        summary_user_ids=[user_id],
    )
    return items


async def _load_recipient_payloads(
    db: AsyncSession,
    recipient_ids: Iterable[str],
) -> list[NotificationRecipient]:
    ids = [str(item) for item in recipient_ids if item]
    if not ids:
        return []
    result = await db.execute(
        select(NotificationRecipient)
        .options(joinedload(NotificationRecipient.notification))
        .where(NotificationRecipient.id.in_(ids))
    )
    return list(result.scalars().all())


async def _publish_after_commit(payload: dict[str, Any]) -> None:
    created_ids = list(payload.get("created_recipient_ids", set()))
    read_ids = list(payload.get("read_recipient_ids", set()))
    summary_user_ids = {str(item) for item in payload.get("summary_user_ids", set()) if item}
    if not created_ids and not read_ids and not summary_user_ids:
        return

    async with AsyncSessionLocal() as db:
        now = datetime.now(timezone.utc)
        created_recipients = await _load_recipient_payloads(db, created_ids)
        read_recipients = await _load_recipient_payloads(db, read_ids)
        touched_users = set(summary_user_ids)

        for recipient in created_recipients:
            touched_users.add(recipient.user_id)

        pushed_created_recipients: list[NotificationRecipient] = []
        for recipient in created_recipients:
            try:
                await publish_user_event(
                    recipient.user_id,
                    "notification.created",
                    serialize_notification_recipient(recipient),
                )
            except Exception:
                logger.exception("publish notification.created failed: recipient_id=%s", recipient.id)
            else:
                recipient.last_pushed_at = now
                pushed_created_recipients.append(recipient)

        if pushed_created_recipients:
            await db.commit()

        for recipient in read_recipients:
            touched_users.add(recipient.user_id)
            try:
                await publish_user_event(
                    recipient.user_id,
                    "notification.read",
                    {
                        "recipient_id": recipient.id,
                        "notification_id": recipient.notification_id,
                        "read_at": _dt_to_iso(recipient.read_at),
                    },
                )
            except Exception:
                logger.exception("publish notification.read failed: recipient_id=%s", recipient.id)

        for user_id in touched_users:
            summary = await get_notification_summary(db, user_id=user_id)
            try:
                await publish_user_event(user_id, "notification.summary", summary)
            except Exception:
                logger.exception("publish notification.summary failed: user_id=%s", user_id)


@event.listens_for(SyncSession, "after_commit")
def _after_commit(session: SyncSession) -> None:
    payload = session.info.pop(_PENDING_KEY, None)
    if not payload:
        return
    with contextlib.suppress(RuntimeError):
        asyncio.get_running_loop().create_task(_publish_after_commit(payload))


@event.listens_for(SyncSession, "after_rollback")
def _after_rollback(session: SyncSession) -> None:
    session.info.pop(_PENDING_KEY, None)
