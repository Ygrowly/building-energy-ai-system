"""
工单服务层：CRUD、状态流转、审计日志、去重。

所有数据库操作通过注入的 AsyncSession 完成，路由层负责 commit/rollback。
"""
from __future__ import annotations

import json
import logging
import secrets
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select, update, func as sa_func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.models import (
    AnomalyIncident,
    WorkOrder,
    WorkOrderAnomalyLink,
    WorkOrderAuditLog,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 状态合法转移矩阵
# ---------------------------------------------------------------------------
VALID_TRANSITIONS: dict[str, set[str]] = {
    "pending_review": {"auto_approved", "auto_rejected"},
    "auto_approved": {"dispatched", "admin_override_rejected"},
    "auto_rejected": {"admin_override_approved", "closed"},
    "dispatched": {"completed", "false_alarm", "escalated"},
    "completed": {"closed"},
    "false_alarm": {"closed"},
    "escalated": {"closed"},
    "admin_override_approved": {"dispatched"},
    "admin_override_rejected": {"closed"},
    # closed 是终态，不可转移
}

def _generate_ticket_id(timestamp: datetime | None = None) -> str:
    """生成无状态且多实例安全的工单号。"""
    ts = timestamp or datetime.now(timezone.utc)
    date_str = ts.strftime("%Y%m%d")
    time_str = ts.strftime("%H%M%S")
    random_suffix = secrets.token_hex(3).upper()
    return f"WO-{date_str}-{time_str}-{random_suffix}"


# ---------------------------------------------------------------------------
# 状态转移校验
# ---------------------------------------------------------------------------
def validate_transition(current: str, target: str) -> bool:
    allowed = VALID_TRANSITIONS.get(current, set())
    return target in allowed


# ---------------------------------------------------------------------------
# 审计日志写入
# ---------------------------------------------------------------------------
async def _write_audit_log(
    db: AsyncSession,
    *,
    work_order_id: str,
    action: str,
    old_status: str | None,
    new_status: str,
    actor_type: str,
    actor_id: str | None = None,
    detail: dict[str, Any] | None = None,
) -> None:
    log_entry = WorkOrderAuditLog(
        work_order_id=work_order_id,
        action=action,
        old_status=old_status,
        new_status=new_status,
        actor_type=actor_type,
        actor_id=actor_id,
        detail_json=json.dumps(detail, ensure_ascii=False, default=str) if detail else None,
    )
    db.add(log_entry)


# ---------------------------------------------------------------------------
# 工单创建
# ---------------------------------------------------------------------------
async def create_work_order(
    db: AsyncSession,
    *,
    ticket_id: str | None = None,
    building_id: str,
    device_id: str | None = None,
    issue_description: str,
    suggested_action: str,
    priority: str = "medium",
    source: str = "manual",
    session_id: str | None = None,
    created_by: str | None = None,
    incident_id: str | None = None,
    anomaly_evidence: list[dict[str, Any]] | None = None,
) -> WorkOrder:
    """
    创建工单（pending_review）并写入审计日志。
    source: "auto_detect" | "prediction" | "manual"
    anomaly_evidence: 来自 anomaly_events 的证据列表，每项需含
        anomaly_event_id, rule_triggered, data_timestamp 等字段。
    """
    resolved_ticket_id = ticket_id or _generate_ticket_id()

    wo = WorkOrder(
        ticket_id=resolved_ticket_id,
        building_id=building_id,
        device_id=device_id,
        issue_description=issue_description,
        suggested_action=suggested_action,
        priority=priority,
        source=source,
        status="pending_review",
        session_id=session_id,
        created_by=created_by,
        incident_id=incident_id,
    )
    db.add(wo)
    await db.flush()  # 获取 wo.id

    # 写入异常关联（快照）
    if anomaly_evidence:
        for ev in anomaly_evidence:
            link = WorkOrderAnomalyLink(
                work_order_id=wo.id,
                anomaly_event_id=ev.get("anomaly_event_id", ev.get("id", "")),
                rule_triggered=ev.get("rule_triggered", "unknown"),
                hvac_root_cause=ev.get("hvac_root_cause"),
                actual_value=ev.get("actual_value"),
                expected_value=ev.get("expected_value"),
                deviation_pct=ev.get("deviation_pct"),
                data_timestamp=ev.get("data_timestamp", datetime.now(timezone.utc)),
            )
            db.add(link)

    await _write_audit_log(
        db,
        work_order_id=wo.id,
        action="create",
        old_status=None,
        new_status="pending_review",
        actor_type="system",
        actor_id=created_by,
    )

    logger.info("工单已创建: ticket_id=%s building=%s", resolved_ticket_id, building_id)
    return wo


async def append_anomaly_evidence_to_work_order(
    db: AsyncSession,
    *,
    work_order: WorkOrder,
    evidence: dict[str, Any],
) -> None:
    """
    为已有工单追加异常证据快照。若同一 anomaly_event 已存在，则跳过。
    """
    anomaly_event_id = evidence.get("anomaly_event_id", evidence.get("id", ""))
    existing = await db.execute(
        select(WorkOrderAnomalyLink.id).where(
            WorkOrderAnomalyLink.work_order_id == work_order.id,
            WorkOrderAnomalyLink.anomaly_event_id == anomaly_event_id,
        )
    )
    if existing.scalar_one_or_none():
        return

    db.add(
        WorkOrderAnomalyLink(
            work_order_id=work_order.id,
            anomaly_event_id=anomaly_event_id,
            rule_triggered=evidence.get("rule_triggered", "unknown"),
            hvac_root_cause=evidence.get("hvac_root_cause"),
            actual_value=evidence.get("actual_value"),
            expected_value=evidence.get("expected_value"),
            deviation_pct=evidence.get("deviation_pct"),
            data_timestamp=evidence.get("data_timestamp", datetime.now(timezone.utc)),
        )
    )


def _map_work_order_status_to_incident_status(status: str) -> tuple[str, bool]:
    """
    返回 (incident_status, is_active)。
    is_active 表示 incident 是否仍可被视为活跃问题对象。
    """
    mapping: dict[str, tuple[str, bool]] = {
        "pending_review": ("open", True),
        "auto_approved": ("open", True),
        "auto_rejected": ("watching", True),
        "dispatched": ("dispatched", True),
        "completed": ("resolved", False),
        "false_alarm": ("false_positive", False),
        "escalated": ("in_progress", False),
        "admin_override_approved": ("dispatched", True),
        "admin_override_rejected": ("closed", False),
        "closed": ("closed", False),
    }
    return mapping.get(status, ("open", True))


async def sync_incident_from_work_order(
    db: AsyncSession,
    *,
    work_order: WorkOrder,
) -> None:
    """
    将当前工单状态同步到 incident 的展示状态。
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
    incident.incident_status, incident.is_active = _map_work_order_status_to_incident_status(
        work_order.status
    )
    incident.updated_at = now
    if not incident.is_active and incident.resolved_at is None:
        incident.resolved_at = now


# ---------------------------------------------------------------------------
# 状态转移（通用）
# ---------------------------------------------------------------------------
async def transition_status(
    db: AsyncSession,
    *,
    work_order: WorkOrder,
    new_status: str,
    action: str,
    actor_type: str,
    actor_id: str | None = None,
    detail: dict[str, Any] | None = None,
) -> WorkOrder:
    """
    执行状态转移，写审计日志，更新 updated_at。
    如果转到 closed 则同时设置 closed_at。
    """
    old_status = work_order.status
    if not validate_transition(old_status, new_status):
        raise ValueError(
            f"非法状态转移: {old_status} → {new_status}，"
            f"允许的目标: {VALID_TRANSITIONS.get(old_status, set())}"
        )

    work_order.status = new_status
    work_order.updated_at = datetime.now(timezone.utc)
    if new_status == "closed":
        work_order.closed_at = datetime.now(timezone.utc)

    await sync_incident_from_work_order(db, work_order=work_order)

    await _write_audit_log(
        db,
        work_order_id=work_order.id,
        action=action,
        old_status=old_status,
        new_status=new_status,
        actor_type=actor_type,
        actor_id=actor_id,
        detail=detail,
    )

    logger.info(
        "工单状态变更: ticket=%s %s → %s (action=%s)",
        work_order.ticket_id, old_status, new_status, action,
    )
    return work_order


# ---------------------------------------------------------------------------
# AI 审批结果写入
# ---------------------------------------------------------------------------
async def apply_ai_review(
    db: AsyncSession,
    *,
    work_order: WorkOrder,
    decision: str,
    reason: str,
    matched_event_ids: list[str] | None = None,
    fallback: bool = False,
) -> WorkOrder:
    """
    写入 AI 审批结果并执行状态转移。
    decision: "approve" | "reject"
    fallback: True 表示 LLM 调用失败降级批准
    """
    now = datetime.now(timezone.utc)
    work_order.ai_decision = decision
    work_order.ai_reason = reason
    work_order.ai_matched_event_ids = (
        json.dumps(matched_event_ids, ensure_ascii=False) if matched_event_ids else None
    )
    work_order.ai_reviewed_at = now
    work_order.ai_fallback = fallback

    if decision == "approve":
        new_status = "auto_approved"
        action = "ai_fallback_approve" if fallback else "ai_approve"
    else:
        new_status = "auto_rejected"
        action = "ai_reject"

    await transition_status(
        db,
        work_order=work_order,
        new_status=new_status,
        action=action,
        actor_type="ai",
        detail={
            "reason": reason,
            "matched_event_ids": matched_event_ids,
            "fallback": fallback,
        },
    )

    # auto_approved → dispatched 自动流转
    if new_status == "auto_approved":
        await transition_status(
            db,
            work_order=work_order,
            new_status="dispatched",
            action="dispatch",
            actor_type="system",
        )

    return work_order


# ---------------------------------------------------------------------------
# 查询工具
# ---------------------------------------------------------------------------
async def get_work_order_by_ticket_id(
    db: AsyncSession, ticket_id: str
) -> WorkOrder | None:
    result = await db.execute(
        select(WorkOrder)
        .options(selectinload(WorkOrder.anomaly_links))
        .where(WorkOrder.ticket_id == ticket_id)
    )
    return result.scalar_one_or_none()


async def get_work_order_by_id(
    db: AsyncSession, work_order_id: str
) -> WorkOrder | None:
    result = await db.execute(
        select(WorkOrder)
        .options(selectinload(WorkOrder.anomaly_links))
        .where(WorkOrder.id == work_order_id)
    )
    return result.scalar_one_or_none()


async def list_work_orders(
    db: AsyncSession,
    *,
    status_filter: list[str] | None = None,
    building_id: str | None = None,
    priority: str | None = None,
    ai_fallback: bool | None = None,
    assigned_to: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> tuple[list[WorkOrder], int]:
    """分页查询工单，返回 (items, total_count)。"""
    query = select(WorkOrder).options(selectinload(WorkOrder.anomaly_links))
    count_query = select(sa_func.count(WorkOrder.id))

    if status_filter:
        query = query.where(WorkOrder.status.in_(status_filter))
        count_query = count_query.where(WorkOrder.status.in_(status_filter))
    if building_id:
        query = query.where(WorkOrder.building_id == building_id)
        count_query = count_query.where(WorkOrder.building_id == building_id)
    if priority:
        query = query.where(WorkOrder.priority == priority)
        count_query = count_query.where(WorkOrder.priority == priority)
    if ai_fallback is not None:
        query = query.where(WorkOrder.ai_fallback == ai_fallback)
        count_query = count_query.where(WorkOrder.ai_fallback == ai_fallback)
    if assigned_to:
        query = query.where(WorkOrder.assigned_to == assigned_to)
        count_query = count_query.where(WorkOrder.assigned_to == assigned_to)

    # total
    total_result = await db.execute(count_query)
    total = total_result.scalar() or 0

    # items
    query = query.order_by(WorkOrder.created_at.desc())
    offset = (page - 1) * page_size
    query = query.offset(offset).limit(page_size)
    result = await db.execute(query)
    items = list(result.scalars().all())

    return items, total


async def check_duplicate_anomaly(
    db: AsyncSession, anomaly_event_id: str
) -> bool:
    """检查某条异常事件是否已关联到未关闭的工单。"""
    from sqlalchemy import text as _text
    result = await db.execute(
        _text("""
            SELECT wal.id FROM work_order_anomaly_links wal
            JOIN work_orders wo ON wo.id = wal.work_order_id
            WHERE wal.anomaly_event_id = CAST(:eid AS uuid)
            AND wo.status != 'closed'
            LIMIT 1
        """),
        {"eid": anomaly_event_id},
    )
    return result.scalar_one_or_none() is not None


# ---------------------------------------------------------------------------
# 工单序列化（供 API 返回）
# ---------------------------------------------------------------------------
def serialize_work_order(wo: WorkOrder, include_links: bool = True) -> dict[str, Any]:
    """将 ORM 对象转为 dict，供 JSON 响应。"""
    data: dict[str, Any] = {
        "id": wo.id,
        "ticket_id": wo.ticket_id,
        "building_id": wo.building_id,
        "device_id": wo.device_id,
        "issue_description": wo.issue_description,
        "suggested_action": wo.suggested_action,
        "priority": wo.priority,
        "status": wo.status,
        "ai_decision": wo.ai_decision,
        "ai_reason": wo.ai_reason,
        "ai_fallback": wo.ai_fallback,
        "ai_reviewed_at": wo.ai_reviewed_at.isoformat() if wo.ai_reviewed_at else None,
        "worker_result": wo.worker_result,
        "worker_notes": wo.worker_notes,
        "worker_feedback_at": (
            wo.worker_feedback_at.isoformat() if wo.worker_feedback_at else None
        ),
        "assigned_to": wo.assigned_to,
        "admin_action": wo.admin_action,
        "admin_notes": wo.admin_notes,
        "admin_reviewed_by": wo.admin_reviewed_by,
        "admin_reviewed_at": (
            wo.admin_reviewed_at.isoformat() if wo.admin_reviewed_at else None
        ),
        "created_at": wo.created_at.isoformat() if wo.created_at else None,
        "updated_at": wo.updated_at.isoformat() if wo.updated_at else None,
        "closed_at": wo.closed_at.isoformat() if wo.closed_at else None,
        "source": wo.source,
        "session_id": wo.session_id,
        "incident_id": wo.incident_id,
    }

    if include_links and wo.anomaly_links:
        data["anomaly_links"] = [
            {
                "anomaly_event_id": link.anomaly_event_id,
                "rule_triggered": link.rule_triggered,
                "hvac_root_cause": link.hvac_root_cause,
                "actual_value": link.actual_value,
                "expected_value": link.expected_value,
                "deviation_pct": link.deviation_pct,
                "data_timestamp": (
                    link.data_timestamp.isoformat() if link.data_timestamp else None
                ),
            }
            for link in wo.anomaly_links
        ]
    else:
        data["anomaly_links"] = []

    return data
