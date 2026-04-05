"""
工单服务层：CRUD、状态流转、审计日志、去重。

所有数据库操作通过注入的 AsyncSession 完成，路由层负责 commit/rollback。
"""
from __future__ import annotations

import json
import logging
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select, func as sa_func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.models import (
    AnomalyIncident,
    DispatchTask,
    User,
    WorkOrder,
    WorkOrderAnomalyLink,
    WorkOrderAuditLog,
    WorkerProfile,
    WorkerProfileSkill,
)
from app.services.dispatch_service import (
    create_dispatch_task,
    derive_dispatch_ui_meta_from_task,
    get_current_dispatch_task,
    serialize_dispatch_task,
    update_dispatch_task_action,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 状态合法转移矩阵
# ---------------------------------------------------------------------------
VALID_TRANSITIONS: dict[str, set[str]] = {
    "pending_review": {"pending_dispatch", "auto_rejected"},
    "pending_dispatch": {"dispatched", "closed"},
    "auto_rejected": {"pending_dispatch", "closed"},
    "dispatched": {"pending_dispatch", "completed", "false_alarm", "escalated"},
    "completed": {"closed"},
    "false_alarm": {"closed"},
    "escalated": {"closed"},
    # 历史状态兼容
    "auto_approved": {"pending_dispatch", "dispatched", "closed"},
    "admin_override_approved": {"pending_dispatch", "dispatched"},
    "admin_override_rejected": {"closed"},
    # closed 是终态，不可转移
}

_DISPATCH_STAGE_SLA_MINUTES: dict[str, dict[str, int]] = {
    "high": {"accept": 5, "arrive": 20, "finish": 90},
    "medium": {"accept": 10, "arrive": 30, "finish": 180},
    "low": {"accept": 15, "arrive": 60, "finish": 360},
}

_DISPATCH_SKILL_RULES: tuple[tuple[str, tuple[str, ...], str], ...] = (
    ("hvac", ("hvac", "暖通", "空调", "冷机", "供水", "回水", "风机", "温度"), "暖通班"),
    ("electrical", ("electric", "电气", "配电", "照明", "电力", "跳闸"), "电气班"),
    ("plumbing", ("water", "漏水", "给排水", "阀门", "管路"), "给排水班"),
    ("controls", ("bms", "control", "控制", "传感", "自控", "联动"), "自控班"),
)

def _generate_ticket_id(timestamp: datetime | None = None) -> str:
    """生成无状态且多实例安全的工单号。"""
    ts = timestamp or datetime.now(timezone.utc)
    date_str = ts.strftime("%Y%m%d")
    time_str = ts.strftime("%H%M%S")
    random_suffix = secrets.token_hex(3).upper()
    return f"WO-{date_str}-{time_str}-{random_suffix}"


def _parse_json_list(raw: str | None) -> list[str]:
    if not raw:
        return []
    try:
        data = json.loads(raw)
    except (TypeError, ValueError):
        return []
    if not isinstance(data, list):
        return []
    return [str(item) for item in data if item not in (None, "")]


def _json_dumps(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False, default=str)


def _safe_load_json(raw: str | None) -> Any:
    if not raw:
        return None
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        return None


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


def _get_dispatch_sla_config(priority: str | None) -> dict[str, int]:
    return _DISPATCH_STAGE_SLA_MINUTES.get(priority or "", _DISPATCH_STAGE_SLA_MINUTES["medium"])


def _resolve_dispatch_deadline(
    work_order: WorkOrder,
) -> tuple[str | None, datetime | None]:
    if work_order.status != "dispatched":
        return None, None

    sla = _get_dispatch_sla_config(work_order.priority)
    dispatch_at = work_order.assigned_at or work_order.updated_at or work_order.created_at
    if not dispatch_at:
        return None, None

    if not work_order.accepted_at:
        return "accept", dispatch_at + timedelta(minutes=sla["accept"])
    if not work_order.arrived_at:
        return "arrive", work_order.accepted_at + timedelta(minutes=sla["arrive"])

    finish_anchor = (
        work_order.processing_started_at
        or work_order.arrived_at
        or work_order.accepted_at
        or dispatch_at
    )
    return "finish", finish_anchor + timedelta(minutes=sla["finish"])


def derive_dispatch_requirement(work_order: WorkOrder) -> dict[str, Any]:
    text_parts = [
        work_order.issue_description or "",
        work_order.suggested_action or "",
    ]
    for link in getattr(work_order, "anomaly_links", []) or []:
        text_parts.extend([
            getattr(link, "rule_triggered", "") or "",
            getattr(link, "hvac_root_cause", "") or "",
        ])
    haystack = " ".join(text_parts).lower()

    required_skills: list[str] = []
    preferred_team = "综合运维班"
    for skill_code, keywords, team_name in _DISPATCH_SKILL_RULES:
        if any(keyword.lower() in haystack for keyword in keywords):
            required_skills.append(skill_code)
            preferred_team = team_name

    if not required_skills:
        required_skills.append("inspection")

    summary_bits = [f"{work_order.building_id} 现场工单"]
    if required_skills:
        summary_bits.append(f"优先技能：{' / '.join(required_skills)}")
    if work_order.priority == "high":
        summary_bits.append("高优先级，优先派值班且可处理紧急任务人员")

    return {
        "building_id": work_order.building_id,
        "priority": work_order.priority,
        "required_skills": required_skills,
        "preferred_team_name": preferred_team,
        "summary": "；".join(summary_bits),
    }


def _skill_match_score(
    profile: WorkerProfile | None,
    required_skills: list[str],
) -> tuple[int, list[str]]:
    if profile is None:
        return 0, []

    matched: list[str] = []
    for link in getattr(profile, "skill_links", []) or []:
        skill = getattr(link, "skill", None)
        if skill is None:
            continue
        skill_code = getattr(skill, "code", "") or ""
        if skill_code in required_skills:
            matched.append(getattr(skill, "name", skill_code))

    if not matched and "inspection" in required_skills:
        return 12, ["基础巡检"]
    if not matched:
        return 0, []
    return min(38, 20 + len(matched) * 9), matched


def _team_match_score(profile: WorkerProfile | None, preferred_team_name: str) -> int:
    if profile is None or getattr(profile, "team", None) is None:
        return 0
    team_name = getattr(profile.team, "name", "") or ""
    if preferred_team_name and preferred_team_name in team_name:
        return 10
    if preferred_team_name == "综合运维班":
        return 6
    return 0


def _building_match_score(profile: WorkerProfile | None, building_id: str) -> tuple[int, bool, list[str]]:
    if profile is None:
        return 0, False, []
    service_buildings = _parse_json_list(getattr(profile, "service_buildings_json", None))
    if not service_buildings:
        return 8, False, []
    if building_id in service_buildings:
        return 18, True, service_buildings
    return 0, False, service_buildings


def _load_score(current_active_orders: int, max_active_orders: int) -> tuple[int, float]:
    if max_active_orders <= 0:
        max_active_orders = 4
    load_ratio = current_active_orders / max_active_orders
    if load_ratio >= 1:
        return 0, load_ratio
    return max(0, int((1 - load_ratio) * 22)), load_ratio


def _shift_score(profile: WorkerProfile | None) -> tuple[int, str]:
    shift_status = getattr(profile, "shift_status", None) or "on_duty"
    if shift_status == "on_duty":
        return 18, shift_status
    if shift_status == "standby":
        return 10, shift_status
    return 2, shift_status


def _candidate_team_name(worker: User) -> str | None:
    profile = getattr(worker, "worker_profile", None)
    team = getattr(profile, "team", None) if profile else None
    return getattr(team, "name", None) if team else None


def _build_dispatch_candidate(
    *,
    worker: User,
    work_order: WorkOrder,
    requirement: dict[str, Any],
    current_active_orders: int,
) -> dict[str, Any]:
    profile = getattr(worker, "worker_profile", None)
    max_active_orders = int(getattr(profile, "max_active_orders", 4) or 4)
    shift_bonus, shift_status = _shift_score(profile)
    skill_score, matched_skills = _skill_match_score(profile, requirement["required_skills"])
    building_score, building_match, service_buildings = _building_match_score(profile, work_order.building_id)
    team_score = _team_match_score(profile, requirement["preferred_team_name"])
    load_score, load_ratio = _load_score(current_active_orders, max_active_orders)
    emergency_bonus = 6 if work_order.priority == "high" and bool(getattr(profile, "accepts_emergency", False)) else 0
    enabled_bonus = 8 if bool(getattr(profile, "dispatch_enabled", True)) else -40

    score = max(0, 12 + shift_bonus + skill_score + building_score + team_score + load_score + emergency_bonus + enabled_bonus)
    team_name = _candidate_team_name(worker) or "综合运维班"
    skill_names = [
        getattr(link.skill, "name", "")
        for link in getattr(profile, "skill_links", []) or []
        if getattr(link, "skill", None) is not None
    ]

    badges = [team_name, f"在手{current_active_orders}/{max_active_orders}单"]
    if shift_status == "on_duty":
        badges.append("值班中")
    elif shift_status == "standby":
        badges.append("待命")
    else:
        badges.append("离岗")
    if matched_skills:
        badges.append("技能匹配")
    if building_match:
        badges.append("负责该楼栋")
    if work_order.priority == "high" and bool(getattr(profile, "accepts_emergency", False)):
        badges.append("可处理紧急任务")

    reason_parts = []
    if matched_skills:
        reason_parts.append(f"技能贴合：{' / '.join(matched_skills[:3])}")
    else:
        reason_parts.append("可做基础巡检排查")
    if building_match:
        reason_parts.append("负责该楼栋")
    elif service_buildings:
        reason_parts.append("可跨楼栋支援")
    if shift_status == "on_duty":
        reason_parts.append("当前值班中")
    elif shift_status == "standby":
        reason_parts.append("当前待命")
    if load_ratio < 1:
        reason_parts.append(f"当前负载较{'低' if load_ratio <= 0.5 else '稳'}")
    else:
        reason_parts.append("当前负载偏高")

    return {
        "user_id": worker.id,
        "username": worker.username,
        "phone": worker.phone,
        "team_name": team_name,
        "job_title": getattr(profile, "job_title", None),
        "shift_status": shift_status,
        "dispatch_enabled": bool(getattr(profile, "dispatch_enabled", True)),
        "max_active_orders": max_active_orders,
        "current_active_orders": current_active_orders,
        "load_ratio": round(load_ratio, 2),
        "service_buildings": service_buildings,
        "skill_names": [name for name in skill_names if name],
        "matched_skill_names": matched_skills,
        "score": score,
        "badges": badges,
        "recommend_reason": "，".join(reason_parts),
    }


def derive_dispatch_ui_meta(
    work_order: WorkOrder,
    *,
    assigned_user: User | None = None,
) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    assigned_to_name = assigned_user.username if assigned_user else None
    assigned_phone = assigned_user.phone if assigned_user else None
    assigned_team_name = _candidate_team_name(assigned_user) if assigned_user else None
    dispatch_at = work_order.assigned_at

    stage, sla_due_at = _resolve_dispatch_deadline(work_order)
    sla_minutes_left = None
    sla_status = None
    if sla_due_at:
        sla_minutes_left = int((sla_due_at - now).total_seconds() // 60)
        if sla_minutes_left < 0:
            sla_status = "overdue"
        elif sla_minutes_left <= 30:
            sla_status = "warning"
        else:
            sla_status = "normal"

    execution_status = work_order.status
    latest_progress_note = work_order.ai_reason or ""
    latest_progress_at = (
        work_order.worker_feedback_at
        or work_order.processing_started_at
        or work_order.arrived_at
        or work_order.accepted_at
        or dispatch_at
        or work_order.updated_at
    )

    if work_order.status == "pending_dispatch":
        execution_status = "pending_dispatch"
        latest_progress_note = "AI审批已通过，等待调度人员派工"
    elif work_order.status == "dispatched":
        if work_order.worker_result == "needs_parts":
            execution_status = "waiting_support"
            latest_progress_note = work_order.worker_notes or "等待配件或协同支持"
        elif work_order.processing_started_at:
            execution_status = "processing"
            latest_progress_note = work_order.worker_notes or "维修人员正在处理现场问题"
        elif work_order.arrived_at:
            execution_status = "arrived"
            latest_progress_note = "维修人员已到场，正在排查故障"
        elif work_order.accepted_at:
            execution_status = "accepted"
            latest_progress_note = "维修人员已接单，正在前往现场"
        else:
            execution_status = "pending_accept"
            latest_progress_note = (
                f"已派给 {assigned_to_name}，等待接单"
                if assigned_to_name else
                "已完成派工，等待维修人员接单"
            )
        if sla_status == "overdue":
            execution_status = "overdue"

    return {
        "assigned_to_name": assigned_to_name,
        "assigned_phone": assigned_phone,
        "assigned_team_name": assigned_team_name,
        "dispatch_at": dispatch_at.isoformat() if dispatch_at else None,
        "accepted_at": work_order.accepted_at.isoformat() if work_order.accepted_at else None,
        "arrived_at": work_order.arrived_at.isoformat() if work_order.arrived_at else None,
        "processing_started_at": (
            work_order.processing_started_at.isoformat()
            if work_order.processing_started_at else None
        ),
        "latest_progress_at": latest_progress_at.isoformat() if latest_progress_at else None,
        "latest_progress_note": latest_progress_note,
        "execution_status": execution_status,
        "dispatch_stage": stage,
        "sla_due_at": sla_due_at.isoformat() if sla_due_at else None,
        "sla_status": sla_status,
        "sla_minutes_left": sla_minutes_left,
    }


def _map_work_order_status_to_incident_status(status: str) -> tuple[str, bool]:
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
    if work_order.status == "pending_dispatch":
        incident.dispatch_blocked_reason = work_order.dispatch_blocked_reason
        incident.latest_dispatch_note = "AI审批已通过，等待调度人员派工"
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
    if new_status == "pending_dispatch":
        work_order.pending_dispatch_at = work_order.pending_dispatch_at or work_order.updated_at
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
        new_status = "pending_dispatch"
        action = "ai_fallback_approve" if fallback else "ai_approve"
        work_order.pending_dispatch_at = now
        work_order.dispatch_profile_json = _json_dumps(derive_dispatch_requirement(work_order))
        work_order.dispatch_blocked_reason = None
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


async def list_dispatch_candidates(
    db: AsyncSession,
    *,
    work_order: WorkOrder,
) -> dict[str, Any]:
    user_result = await db.execute(
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
    workers = list(user_result.scalars().all())
    if not workers:
        return {
            "requirement": derive_dispatch_requirement(work_order),
            "candidates": [],
        }

    worker_ids = [worker.id for worker in workers]
    load_result = await db.execute(
        select(WorkOrder.assigned_to, sa_func.count(WorkOrder.id))
        .where(
            WorkOrder.assigned_to.in_(worker_ids),
            WorkOrder.status == "dispatched",
        )
        .group_by(WorkOrder.assigned_to)
    )
    active_counts = {row[0]: int(row[1]) for row in load_result.all()}
    requirement = derive_dispatch_requirement(work_order)

    ranked: list[dict[str, Any]] = []
    for worker in workers:
        current_active_orders = active_counts.get(worker.id, 0)
        ranked.append(
            _build_dispatch_candidate(
                worker=worker,
                work_order=work_order,
                requirement=requirement,
                current_active_orders=current_active_orders,
            )
        )

    ranked.sort(
        key=lambda item: (
            -item["score"],
            item["current_active_orders"],
            item["shift_status"] != "on_duty",
            item["username"],
        )
    )
    return {
        "requirement": requirement,
        "candidates": ranked,
    }


async def assign_work_order(
    db: AsyncSession,
    *,
    work_order: WorkOrder,
    assigned_user: User,
    actor_type: str,
    actor_id: str | None = None,
    notes: str | None = None,
    dispatch_mode: str = "manual",
    candidate_snapshot: dict[str, Any] | None = None,
) -> WorkOrder:
    if work_order.status not in {"pending_dispatch", "auto_approved", "admin_override_approved"}:
        raise ValueError(f"当前状态 {work_order.status} 不支持派工")

    now = datetime.now(timezone.utc)
    work_order.pending_dispatch_at = work_order.pending_dispatch_at or now
    work_order.dispatch_blocked_reason = None
    work_order.updated_at = now

    if notes:
        work_order.worker_notes = notes

    await create_dispatch_task(
        db,
        work_order=work_order,
        assigned_user=assigned_user,
        assigned_by=actor_id,
        actor_type=actor_type,
        dispatch_mode=dispatch_mode,
        selection_reason=notes,
        candidate_snapshot=candidate_snapshot,
        dispatch_profile_snapshot=derive_dispatch_requirement(work_order),
    )

    if work_order.status != "dispatched":
        await transition_status(
            db,
            work_order=work_order,
            new_status="dispatched",
            action="dispatch",
            actor_type=actor_type,
            actor_id=actor_id,
            detail={
                "assigned_to": assigned_user.id,
                "assigned_to_name": assigned_user.username,
                "assigned_team_name": _candidate_team_name(assigned_user),
                "dispatch_mode": dispatch_mode,
                "notes": notes,
            },
        )
    return work_order


async def record_worker_dispatch_action(
    db: AsyncSession,
    *,
    work_order: WorkOrder,
    action: str,
    actor_id: str,
    notes: str | None = None,
    support_team_id: str | None = None,
) -> WorkOrder:
    if work_order.status != "dispatched":
        raise ValueError(f"当前状态 {work_order.status} 不支持执行动作")

    dispatch_task = await get_current_dispatch_task(db, work_order=work_order)
    if dispatch_task is None:
        raise ValueError("当前工单缺少有效派工任务，无法执行动作")

    await update_dispatch_task_action(
        db,
        work_order=work_order,
        dispatch_task=dispatch_task,
        action=action,
        actor_type="worker",
        actor_id=actor_id,
        notes=notes,
        support_team_id=support_team_id,
    )

    if notes:
        work_order.worker_notes = notes
    work_order.updated_at = datetime.now(timezone.utc)
    await sync_incident_from_work_order(db, work_order=work_order)
    await _write_audit_log(
        db,
        work_order_id=work_order.id,
        action=f"worker_{action}",
        old_status=work_order.status,
        new_status=work_order.status,
        actor_type="worker",
        actor_id=actor_id,
        detail={
            "action": action,
            "notes": notes,
            "dispatch_id": dispatch_task.id,
        },
    )
    return work_order


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
def serialize_work_order(
    wo: WorkOrder,
    *,
    include_links: bool = True,
    assigned_user: User | None = None,
    current_dispatch: DispatchTask | None = None,
    dispatch_events: list[Any] | None = None,
) -> dict[str, Any]:
    """将 ORM 对象转为 dict，供 JSON 响应。"""
    dispatch_meta = (
        derive_dispatch_ui_meta_from_task(current_dispatch, assigned_user=assigned_user)
        if current_dispatch is not None else
        derive_dispatch_ui_meta(wo, assigned_user=assigned_user)
    )
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
        "assigned_at": wo.assigned_at.isoformat() if wo.assigned_at else None,
        "accepted_at": wo.accepted_at.isoformat() if wo.accepted_at else None,
        "arrived_at": wo.arrived_at.isoformat() if wo.arrived_at else None,
        "processing_started_at": (
            wo.processing_started_at.isoformat() if wo.processing_started_at else None
        ),
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
        "pending_dispatch_at": wo.pending_dispatch_at.isoformat() if wo.pending_dispatch_at else None,
        "dispatch_profile": _safe_load_json(wo.dispatch_profile_json),
        "dispatch_blocked_reason": wo.dispatch_blocked_reason,
        **dispatch_meta,
    }
    data["current_dispatch"] = (
        serialize_dispatch_task(
            current_dispatch,
            assigned_user=assigned_user,
            events=dispatch_events,
        )
        if current_dispatch is not None else None
    )

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
