"""
Incident 读模型同步服务。

这里集中维护 anomaly_incidents 上供列表/详情快速读取的投影字段，避免派工、
审批、关闭等流程在多个服务里手写 current_dispatch/current_work_order 同步逻辑。
调用方仍负责 commit/rollback。
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AnomalyIncident, DispatchTask, WorkOrder


def map_work_order_status_to_incident_status(status: str) -> tuple[str, bool]:
    """
    返回 (incident_status, is_active)。
    is_active 表示 incident 是否仍可被视为活跃问题对象。
    """
    mapping: dict[str, tuple[str, bool]] = {
        "pending_review": ("open", True),
        "pending_dispatch": ("open", True),
        "auto_rejected": ("watching", True),
        "dispatched": ("dispatched", True),
        "completed": ("resolved", False),
        "false_alarm": ("false_positive", False),
        "escalated": ("in_progress", False),
        # 历史状态兼容
        "auto_approved": ("open", True),
        "admin_override_approved": ("open", True),
        "admin_override_rejected": ("closed", False),
        "closed": ("closed", False),
    }
    return mapping.get(status, ("open", True))


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


async def sync_incident_from_work_order(
    db: AsyncSession,
    *,
    work_order: WorkOrder,
) -> None:
    """
    将当前工单状态同步到 incident 的基础读模型。
    """
    if not work_order.incident_id:
        return

    incident = await db.get(AnomalyIncident, work_order.incident_id)
    if not incident:
        return
    if incident.current_work_order_id and incident.current_work_order_id != work_order.id:
        return

    now = datetime.now(timezone.utc)
    incident.workflow_status = work_order.status
    incident.priority = work_order.priority
    incident.current_work_order_id = work_order.id
    if work_order.status == "pending_dispatch":
        incident.dispatch_blocked_reason = work_order.dispatch_blocked_reason
        incident.latest_dispatch_note = "AI审批已通过，等待调度人员派工"
    incident.incident_status, incident.is_active = map_work_order_status_to_incident_status(
        work_order.status
    )
    incident.updated_at = now
    if not incident.is_active and incident.resolved_at is None:
        incident.resolved_at = now


async def sync_incident_dispatch_projection(
    db: AsyncSession,
    *,
    work_order: WorkOrder,
    dispatch_task: DispatchTask | None,
    blocked_reason: str | None = None,
) -> None:
    """
    将当前派工任务同步到 incident 的 current_dispatch 读模型。
    """
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
