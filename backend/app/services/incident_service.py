"""
incident_service
================

负责将小时级 anomaly_event 聚合为 incident，并维护 incident 与工单的同步关系。
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select, func as sa_func
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    AnomalyEvent,
    AnomalyIncident,
    DispatchTask,
    IncidentEventLink,
    IncidentPredictionLink,
    PredictedAnomalyEvent,
    User,
    WorkOrder,
    WorkOrderAuditLog,
    WorkOrderAnomalyLink,
)
from app.services.dispatch_service import derive_dispatch_ui_meta_from_task
from app.services.work_order_service import (
    _write_audit_log,
    append_anomaly_evidence_to_work_order,
    create_work_order,
    sync_incident_from_work_order,
)

logger = logging.getLogger(__name__)

_INCIDENT_COUNTER: dict[str, int] = {}

_BUILDING_DISPLAY = {
    "Fox_office_Alice": "Alice 办公楼",
    "Fox_education_Louie": "Louie 教学楼",
    "Fox_public_Henry": "Henry 公共服务楼",
}

_RULE_DESC = {
    "water_leak": "水耗异常偏高",
    "flag_water": "水耗异常偏高",
    "electricity_overload": "电耗异常偏高",
    "flag_electricity": "电耗异常偏高",
    "hvac_overconsumption": "暖通能耗异常偏高",
    "flag_hvac_energy": "暖通能耗异常偏高",
    "supply_temp_deviation": "供水温度偏离",
    "flag_supply_deviation": "供水温度偏离",
    "return_temp_deviation": "回水温度偏离",
    "flag_return_deviation": "回水温度偏离",
}

_RULE_ACTION = {
    "water_leak": "检查水管、阀门和传感器，排查漏水点",
    "flag_water": "检查水管、阀门和传感器，排查漏水点",
    "electricity_overload": "检查配电设备、照明和用电设备运行状态",
    "flag_electricity": "检查配电设备、照明和用电设备运行状态",
    "hvac_overconsumption": "检查空调机组运行参数、冷水机组效能",
    "flag_hvac_energy": "检查空调机组运行参数、冷水机组效能",
    "supply_temp_deviation": "检查冷水机组出水温度和供水管路",
    "flag_supply_deviation": "检查冷水机组出水温度和供水管路",
    "return_temp_deviation": "检查回水管路和末端设备负荷",
    "flag_return_deviation": "检查回水管路和末端设备负荷",
}

_HVAC_CAUSE_DESC = {
    "A_low_efficiency": "冷水机组效能衰退",
    "B_small_deltaT": "供回水小温差（水力失调）",
    "C_unexpected_on": "非营业时段空调异常运行",
}

_METRIC_DESC = {
    "electricity_kwh": "电耗",
    "water_m3": "水耗",
    "hac_energy": "暖通能耗",
}

_PRIORITY_SLA_MINUTES = {
    "high": 30,
    "medium": 60,
    "low": 120,
}

_MERGEABLE_WORKFLOW_STATUSES = {
    "pending_review",
    "pending_dispatch",
    "auto_approved",
    "dispatched",
    "admin_override_approved",
}


def _generate_incident_id(timestamp: datetime | None = None) -> str:
    ts = timestamp or datetime.now(timezone.utc)
    date_str = ts.strftime("%Y%m%d")
    _INCIDENT_COUNTER[date_str] = _INCIDENT_COUNTER.get(date_str, 0) + 1
    return f"INC-{date_str}-{_INCIDENT_COUNTER[date_str]:03d}"


def _priority_rank(priority: str) -> int:
    return {"low": 1, "medium": 2, "high": 3}.get(priority, 0)


def assign_alert_priority(event: AnomalyEvent) -> str:
    rule = event.rule_triggered or ""
    dev = abs(event.deviation_pct or 0)

    if rule in ("water_leak", "flag_water"):
        return "high"
    if event.hvac_root_cause in ("A_low_efficiency", "B_small_deltaT", "C_unexpected_on"):
        return "high"
    if dev > 50:
        return "high"
    if dev > 30:
        return "medium"
    return "low"


def build_merge_key_for_event(event: AnomalyEvent) -> str:
    parts = [
        "auto_detect",
        event.building_id or "",
        event.meter_device_id or "",
        event.rule_triggered or "",
        event.hvac_root_cause or "",
    ]
    return "|".join(parts)


def get_continuity_window_hours(event: AnomalyEvent) -> int:
    if (
        event.rule_triggered in ("hvac_overconsumption", "flag_hvac_energy")
        and event.hvac_root_cause in _HVAC_CAUSE_DESC
    ):
        return 24
    return 6


def get_prediction_continuity_window_hours(pred: PredictedAnomalyEvent) -> int:
    return 12 if pred.risk_level == "high" else 6


def build_alert_evidence(event: AnomalyEvent) -> dict[str, Any]:
    return {
        "anomaly_event_id": str(event.id),
        "rule_triggered": event.rule_triggered,
        "hvac_root_cause": event.hvac_root_cause,
        "actual_value": event.actual_value,
        "expected_value": event.expected_value,
        "deviation_pct": event.deviation_pct,
        "data_timestamp": event.data_timestamp,
    }


def build_suggested_action(event: AnomalyEvent) -> str:
    action = _RULE_ACTION.get(event.rule_triggered, "请现场排查异常原因")
    if event.hvac_root_cause == "A_low_efficiency":
        return "检查冷水机组 COP，清洗冷凝器/蒸发器，检查制冷剂充注量"
    if event.hvac_root_cause == "B_small_deltaT":
        return "检查压差旁通阀开度，排查末端堵塞或水泵扬程不足"
    if event.hvac_root_cause == "C_unexpected_on":
        return "检查 BMS 排程设置，确认是否有未登记的加班或活动"
    return action


def assign_prediction_priority(pred: PredictedAnomalyEvent) -> str:
    risk = pred.risk_level or "normal"
    if risk == "high":
        return "medium"
    return "low"


def build_merge_key_for_prediction(pred: PredictedAnomalyEvent) -> str:
    parts = [
        "prediction",
        pred.building_id or "",
        pred.metric_name or "",
    ]
    return "|".join(parts)


def build_prediction_summary(
    *,
    building_id: str,
    metric_name: str,
    first_seen_at: datetime,
    last_seen_at: datetime,
    anomaly_count: int,
    peak_deviation_pct: float | None,
    latest_actual_value: float | None,
    latest_expected_value: float | None,
) -> str:
    building_name = _BUILDING_DISPLAY.get(building_id, building_id)
    metric_desc = _METRIC_DESC.get(metric_name, metric_name)
    first_str = first_seen_at.strftime("%Y-%m-%d %H:%M")
    last_str = last_seen_at.strftime("%Y-%m-%d %H:%M")
    time_span = first_str if first_str == last_str else f"{first_str}~{last_str}"
    parts = [f"[预警][{building_name}] 预测 {time_span} {metric_desc}连续高风险 {anomaly_count} 次"]
    if peak_deviation_pct is not None:
        parts.append(f"，峰值预计偏离 {peak_deviation_pct:+.1f}%")
    if latest_actual_value is not None and latest_expected_value is not None:
        parts.append(f"，最新预测={latest_actual_value:.1f}，基线={latest_expected_value:.1f}")
    return "".join(parts)


def build_prediction_suggested_action(pred: PredictedAnomalyEvent) -> str:
    metric_desc = _METRIC_DESC.get(pred.metric_name, pred.metric_name)
    return f"建议提前检查{metric_desc}相关设备运行状态，预防异常发生"


def _dt_to_iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _derive_dispatch_ui_meta(
    work_order: WorkOrder,
    *,
    current_dispatch: DispatchTask | None = None,
    assigned_user: User | None = None,
    audit_logs: list[WorkOrderAuditLog] | None = None,
) -> dict[str, Any]:
    if current_dispatch is not None:
        return derive_dispatch_ui_meta_from_task(current_dispatch, assigned_user=assigned_user)

    assigned_to_name = assigned_user.username if assigned_user else None
    assigned_phone = assigned_user.phone if assigned_user else None
    profile = getattr(assigned_user, "worker_profile", None) if assigned_user else None
    team = getattr(profile, "team", None) if profile else None
    assigned_team_name = getattr(team, "name", None) if team else None
    dispatch_at = getattr(work_order, "assigned_at", None)
    now = datetime.now(timezone.utc)

    sla_due_at = None
    sla_minutes_left = None
    sla_status = None
    execution_status = getattr(work_order, "status", "")
    priority = getattr(work_order, "priority", "medium")
    accepted_at = getattr(work_order, "accepted_at", None)
    arrived_at = getattr(work_order, "arrived_at", None)
    processing_started_at = getattr(work_order, "processing_started_at", None)
    worker_result = getattr(work_order, "worker_result", None)
    worker_notes = getattr(work_order, "worker_notes", None)
    worker_feedback_at = getattr(work_order, "worker_feedback_at", None)
    updated_at = getattr(work_order, "updated_at", None)
    ai_reason = getattr(work_order, "ai_reason", None)

    if execution_status == "dispatched" and dispatch_at:
        accept_minutes = 5 if priority == "high" else 10 if priority == "medium" else 15
        arrive_minutes = 20 if priority == "high" else 30 if priority == "medium" else 60
        finish_minutes = 90 if priority == "high" else 180 if priority == "medium" else 360

        if not accepted_at:
            sla_due_at = dispatch_at + timedelta(minutes=accept_minutes)
        elif not arrived_at:
            sla_due_at = accepted_at + timedelta(minutes=arrive_minutes)
        else:
            finish_anchor = (
                processing_started_at
                or arrived_at
                or accepted_at
                or dispatch_at
            )
            sla_due_at = finish_anchor + timedelta(minutes=finish_minutes)

        sla_minutes_left = int((sla_due_at - now).total_seconds() // 60)
        if sla_minutes_left < 0:
            sla_status = "overdue"
        elif sla_minutes_left <= 30:
            sla_status = "warning"
        else:
            sla_status = "normal"

    if execution_status == "pending_dispatch":
        execution_status = "pending_dispatch"
    elif execution_status == "dispatched":
        if worker_result == "needs_parts":
            execution_status = "waiting_support"
        elif processing_started_at:
            execution_status = "processing"
        elif arrived_at:
            execution_status = "arrived"
        elif accepted_at:
            execution_status = "accepted"
        else:
            execution_status = "pending_accept"
        if sla_status == "overdue":
            execution_status = "overdue"

    latest_progress_note = ai_reason or ""
    if getattr(work_order, "status", "") == "pending_dispatch":
        latest_progress_note = "AI审批已通过，等待调度人员派工"
    elif worker_result == "needs_parts":
        latest_progress_note = worker_notes or "等待配件或协同支持"
    elif worker_notes:
        latest_progress_note = worker_notes
    elif processing_started_at:
        latest_progress_note = "维修人员已开始处理现场问题"
    elif arrived_at:
        latest_progress_note = "维修人员已到场排查"
    elif accepted_at:
        latest_progress_note = "维修人员已接单，正在前往现场"
    elif getattr(work_order, "status", "") == "dispatched" and assigned_to_name:
        latest_progress_note = f"已派给 {assigned_to_name}，等待接单"
    elif getattr(work_order, "status", "") == "dispatched":
        latest_progress_note = "已完成派工，等待接单处理"

    latest_progress_at = (
        worker_feedback_at
        or processing_started_at
        or arrived_at
        or accepted_at
        or dispatch_at
        or updated_at
    )

    return {
        "assigned_to_name": assigned_to_name,
        "assigned_phone": assigned_phone,
        "assigned_team_name": assigned_team_name,
        "dispatch_at": _dt_to_iso(dispatch_at),
        "accepted_at": _dt_to_iso(accepted_at),
        "arrived_at": _dt_to_iso(arrived_at),
        "processing_started_at": _dt_to_iso(processing_started_at),
        "latest_progress_at": _dt_to_iso(latest_progress_at),
        "latest_progress_note": latest_progress_note,
        "execution_status": execution_status,
        "sla_due_at": _dt_to_iso(sla_due_at),
        "sla_status": sla_status,
        "sla_minutes_left": sla_minutes_left,
    }


def build_incident_summary(
    *,
    building_id: str,
    rule_triggered: str,
    hvac_root_cause: str | None,
    first_seen_at: datetime,
    last_seen_at: datetime,
    anomaly_count: int,
    peak_deviation_pct: float | None,
    latest_actual_value: float | None,
    latest_expected_value: float | None,
) -> str:
    building_name = _BUILDING_DISPLAY.get(building_id, building_id)
    rule_desc = _RULE_DESC.get(rule_triggered, rule_triggered)
    first_str = first_seen_at.strftime("%Y-%m-%d %H:%M")
    last_str = last_seen_at.strftime("%Y-%m-%d %H:%M")
    time_span = first_str if first_str == last_str else f"{first_str}~{last_str}"

    parts = [f"[{building_name}] {time_span} 连续 {anomaly_count} 次检测到{rule_desc}"]
    if peak_deviation_pct is not None:
        parts.append(f"，峰值偏离 {peak_deviation_pct:+.1f}%")
    if latest_actual_value is not None and latest_expected_value is not None:
        parts.append(f"，最新实际={latest_actual_value:.1f}，最新预期={latest_expected_value:.1f}")
    if hvac_root_cause and hvac_root_cause in _HVAC_CAUSE_DESC:
        parts.append(f"，根因分析：{_HVAC_CAUSE_DESC[hvac_root_cause]}")
    return "".join(parts)


async def check_duplicate_incident_event(
    db: AsyncSession,
    anomaly_event_id: str,
) -> bool:
    result = await db.execute(
        select(IncidentEventLink.id).where(
            IncidentEventLink.anomaly_event_id == anomaly_event_id
        ).limit(1)
    )
    return result.scalar_one_or_none() is not None


async def find_mergeable_incident(
    db: AsyncSession,
    *,
    event: AnomalyEvent,
) -> AnomalyIncident | None:
    merge_key = build_merge_key_for_event(event)
    stmt = (
        select(AnomalyIncident)
        .where(
            AnomalyIncident.source == "auto_detect",
            AnomalyIncident.merge_key == merge_key,
            AnomalyIncident.is_active == True,  # noqa: E712
            AnomalyIncident.workflow_status.in_(_MERGEABLE_WORKFLOW_STATUSES),
            AnomalyIncident.continuity_expires_at >= event.data_timestamp,
        )
        .order_by(AnomalyIncident.last_seen_at.desc())
        .limit(1)
        .with_for_update()
    )
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def _get_work_order(
    db: AsyncSession, work_order_id: str | None
) -> WorkOrder | None:
    if not work_order_id:
        return None
    return await db.get(WorkOrder, work_order_id)


async def _find_existing_work_order_for_event(
    db: AsyncSession,
    *,
    anomaly_event_id: str,
) -> WorkOrder | None:
    stmt = (
        select(WorkOrder)
        .join(WorkOrderAnomalyLink, WorkOrderAnomalyLink.work_order_id == WorkOrder.id)
        .where(WorkOrderAnomalyLink.anomaly_event_id == anomaly_event_id)
        .order_by(WorkOrder.created_at.asc())
        .limit(1)
    )
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def _append_incident_event_link(
    db: AsyncSession,
    *,
    incident: AnomalyIncident,
    event: AnomalyEvent,
) -> None:
    current_count = incident.anomaly_count or 0
    db.add(
        IncidentEventLink(
            incident_id=incident.id,
            anomaly_event_id=str(event.id),
            sequence_no=current_count + 1,
            data_timestamp=event.data_timestamp,
            actual_value=event.actual_value,
            expected_value=event.expected_value,
            deviation_pct=event.deviation_pct,
            rule_triggered=event.rule_triggered,
            hvac_root_cause=event.hvac_root_cause,
        )
    )


async def _append_incident_prediction_link(
    db: AsyncSession,
    *,
    incident: AnomalyIncident,
    pred: PredictedAnomalyEvent,
) -> None:
    current_count = incident.anomaly_count or 0
    db.add(
        IncidentPredictionLink(
            incident_id=incident.id,
            predicted_anomaly_event_id=str(pred.id),
            sequence_no=current_count + 1,
            forecast_for_timestamp=pred.forecast_for_timestamp,
            metric_name=pred.metric_name,
            predicted_value=pred.predicted_value,
            expected_value=pred.expected_value,
            deviation_pct=pred.deviation_pct,
            risk_level=pred.risk_level,
        )
    )


def _refresh_incident_from_event(
    incident: AnomalyIncident,
    *,
    event: AnomalyEvent,
) -> None:
    now = datetime.now(timezone.utc)
    priority = assign_alert_priority(event)
    incident.anomaly_count = (incident.anomaly_count or 0) + 1
    incident.last_seen_at = event.data_timestamp
    incident.continuity_expires_at = event.data_timestamp + timedelta(
        hours=get_continuity_window_hours(event)
    )
    incident.peak_deviation_pct = max(
        abs(incident.peak_deviation_pct or 0),
        abs(event.deviation_pct or 0),
    )
    incident.latest_actual_value = event.actual_value
    incident.latest_expected_value = event.expected_value
    if _priority_rank(priority) > _priority_rank(incident.priority):
        incident.priority = priority
    incident.summary_text = build_incident_summary(
        building_id=incident.building_id,
        rule_triggered=incident.rule_triggered,
        hvac_root_cause=incident.hvac_root_cause,
        first_seen_at=incident.first_seen_at,
        last_seen_at=incident.last_seen_at,
        anomaly_count=incident.anomaly_count,
        peak_deviation_pct=incident.peak_deviation_pct,
        latest_actual_value=incident.latest_actual_value,
        latest_expected_value=incident.latest_expected_value,
    )
    incident.updated_at = now


def _refresh_incident_from_prediction(
    incident: AnomalyIncident,
    *,
    pred: PredictedAnomalyEvent,
) -> None:
    now = datetime.now(timezone.utc)
    priority = assign_prediction_priority(pred)
    incident.anomaly_count = (incident.anomaly_count or 0) + 1
    incident.last_seen_at = pred.forecast_for_timestamp
    incident.continuity_expires_at = pred.forecast_for_timestamp + timedelta(
        hours=get_prediction_continuity_window_hours(pred)
    )
    incident.peak_deviation_pct = max(
        abs(incident.peak_deviation_pct or 0),
        abs(pred.deviation_pct or 0),
    )
    incident.latest_actual_value = pred.predicted_value
    incident.latest_expected_value = pred.expected_value
    if _priority_rank(priority) > _priority_rank(incident.priority):
        incident.priority = priority
    incident.summary_text = build_prediction_summary(
        building_id=incident.building_id,
        metric_name=incident.rule_triggered,
        first_seen_at=incident.first_seen_at,
        last_seen_at=incident.last_seen_at,
        anomaly_count=incident.anomaly_count,
        peak_deviation_pct=incident.peak_deviation_pct,
        latest_actual_value=incident.latest_actual_value,
        latest_expected_value=incident.latest_expected_value,
    )
    incident.updated_at = now


async def create_or_merge_alert_incident(
    db: AsyncSession,
    *,
    event: AnomalyEvent,
) -> tuple[AnomalyIncident | None, WorkOrder | None, bool]:
    """
    对 anomaly_event 执行 incident 合并逻辑。

    返回 (incident, current_work_order, created_new_incident)。
    若该事件已被处理过，返回 (None, None, False)。
    """
    event_id = str(event.id)
    if await check_duplicate_incident_event(db, event_id):
        return None, None, False

    evidence = build_alert_evidence(event)
    incident = await find_mergeable_incident(db, event=event)
    if incident:
        await _append_incident_event_link(db, incident=incident, event=event)
        _refresh_incident_from_event(incident, event=event)
        current_work_order = await _get_work_order(db, incident.current_work_order_id)
        if current_work_order:
            await append_anomaly_evidence_to_work_order(
                db,
                work_order=current_work_order,
                evidence=evidence,
            )
            current_work_order.issue_description = incident.summary_text
            current_work_order.priority = incident.priority
            current_work_order.updated_at = datetime.now(timezone.utc)
            await sync_incident_from_work_order(db, work_order=current_work_order)
            await _write_audit_log(
                db,
                work_order_id=current_work_order.id,
                action="merge_evidence",
                old_status=current_work_order.status,
                new_status=current_work_order.status,
                actor_type="system",
                detail={
                    "incident_id": incident.incident_id,
                    "anomaly_event_id": event_id,
                    "anomaly_count": incident.anomaly_count,
                },
            )
        return incident, current_work_order, False

    existing_work_order = await _find_existing_work_order_for_event(
        db,
        anomaly_event_id=event_id,
    )

    priority = assign_alert_priority(event)
    incident = AnomalyIncident(
        incident_id=_generate_incident_id(event.data_timestamp),
        source="auto_detect",
        building_id=event.building_id,
        device_id=event.meter_device_id,
        rule_triggered=event.rule_triggered,
        hvac_root_cause=event.hvac_root_cause,
        merge_key=build_merge_key_for_event(event),
        incident_status="open",
        workflow_status="pending_review",
        priority=priority,
        first_seen_at=event.data_timestamp,
        last_seen_at=event.data_timestamp,
        continuity_expires_at=event.data_timestamp + timedelta(
            hours=get_continuity_window_hours(event)
        ),
        anomaly_count=1,
        peak_deviation_pct=abs(event.deviation_pct or 0),
        latest_actual_value=event.actual_value,
        latest_expected_value=event.expected_value,
        summary_text=build_incident_summary(
            building_id=event.building_id,
            rule_triggered=event.rule_triggered,
            hvac_root_cause=event.hvac_root_cause,
            first_seen_at=event.data_timestamp,
            last_seen_at=event.data_timestamp,
            anomaly_count=1,
            peak_deviation_pct=abs(event.deviation_pct or 0),
            latest_actual_value=event.actual_value,
            latest_expected_value=event.expected_value,
        ),
        is_active=True,
    )
    db.add(incident)
    await db.flush()

    db.add(
        IncidentEventLink(
            incident_id=incident.id,
            anomaly_event_id=event_id,
            sequence_no=1,
            data_timestamp=event.data_timestamp,
            actual_value=event.actual_value,
            expected_value=event.expected_value,
            deviation_pct=event.deviation_pct,
            rule_triggered=event.rule_triggered,
            hvac_root_cause=event.hvac_root_cause,
        )
    )

    if existing_work_order:
        work_order = existing_work_order
        work_order.incident_id = incident.id
        work_order.issue_description = incident.summary_text
        if _priority_rank(priority) > _priority_rank(work_order.priority):
            work_order.priority = priority
        work_order.updated_at = datetime.now(timezone.utc)
    else:
        work_order = await create_work_order(
            db,
            building_id=event.building_id,
            device_id=event.meter_device_id,
            issue_description=incident.summary_text,
            suggested_action=build_suggested_action(event),
            priority=priority,
            source="auto_detect",
            incident_id=incident.id,
            anomaly_evidence=[evidence],
        )
    incident.current_work_order_id = work_order.id
    incident.workflow_status = work_order.status
    await sync_incident_from_work_order(db, work_order=work_order)
    logger.info(
        "incident 已创建: incident_id=%s work_order=%s building=%s",
        incident.incident_id,
        work_order.ticket_id,
        incident.building_id,
    )
    return incident, work_order, True


async def list_incidents(
    db: AsyncSession,
    *,
    workflow_status_filter: list[str] | None = None,
    building_id: str | None = None,
    assigned_to: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> tuple[list[AnomalyIncident], int]:
    query = select(AnomalyIncident)
    count_query = select(sa_func.count(AnomalyIncident.id))

    if assigned_to:
        query = query.join(WorkOrder, WorkOrder.id == AnomalyIncident.current_work_order_id)
        count_query = count_query.join(WorkOrder, WorkOrder.id == AnomalyIncident.current_work_order_id)
        query = query.where(WorkOrder.assigned_to == assigned_to)
        count_query = count_query.where(WorkOrder.assigned_to == assigned_to)

    if workflow_status_filter:
        query = query.where(AnomalyIncident.workflow_status.in_(workflow_status_filter))
        count_query = count_query.where(AnomalyIncident.workflow_status.in_(workflow_status_filter))
    if building_id:
        query = query.where(AnomalyIncident.building_id == building_id)
        count_query = count_query.where(AnomalyIncident.building_id == building_id)

    total = (await db.execute(count_query)).scalar() or 0
    offset = (page - 1) * page_size
    query = query.order_by(
        AnomalyIncident.last_seen_at.desc(),
        AnomalyIncident.created_at.desc(),
    ).offset(offset).limit(page_size)
    items = list((await db.execute(query)).scalars().all())
    return items, total


async def get_incident_by_identifier(
    db: AsyncSession,
    identifier: str,
) -> AnomalyIncident | None:
    result = await db.execute(
        select(AnomalyIncident).where(
            (AnomalyIncident.id == identifier) | (AnomalyIncident.incident_id == identifier)
        ).limit(1)
    )
    return result.scalar_one_or_none()


async def list_incident_work_orders(
    db: AsyncSession,
    *,
    incident_id: str,
) -> list[WorkOrder]:
    result = await db.execute(
        select(WorkOrder)
        .where(WorkOrder.incident_id == incident_id)
        .order_by(WorkOrder.created_at.asc())
    )
    return list(result.scalars().all())


async def list_incident_event_links(
    db: AsyncSession,
    *,
    incident_id: str,
) -> list[IncidentEventLink]:
    result = await db.execute(
        select(IncidentEventLink)
        .where(IncidentEventLink.incident_id == incident_id)
        .order_by(IncidentEventLink.data_timestamp.asc())
    )
    return list(result.scalars().all())


async def list_incident_prediction_links(
    db: AsyncSession,
    *,
    incident_id: str,
) -> list[IncidentPredictionLink]:
    result = await db.execute(
        select(IncidentPredictionLink)
        .where(IncidentPredictionLink.incident_id == incident_id)
        .order_by(IncidentPredictionLink.forecast_for_timestamp.asc())
    )
    return list(result.scalars().all())


def serialize_incident(
    incident: AnomalyIncident,
    *,
    current_work_order: WorkOrder | None = None,
    current_dispatch: DispatchTask | None = None,
    assigned_user: User | None = None,
    audit_logs: list[WorkOrderAuditLog] | None = None,
) -> dict[str, Any]:
    current_work_order_data: dict[str, Any] | None = None
    if current_work_order:
        current_work_order_data = {
            "id": current_work_order.id,
            "ticket_id": current_work_order.ticket_id,
            "status": current_work_order.status,
            "priority": current_work_order.priority,
            "ai_decision": getattr(current_work_order, "ai_decision", None),
            "ai_reason": getattr(current_work_order, "ai_reason", None),
            "ai_fallback": getattr(current_work_order, "ai_fallback", False),
            "worker_result": getattr(current_work_order, "worker_result", None),
            "worker_notes": getattr(current_work_order, "worker_notes", None),
            "assigned_to": getattr(current_work_order, "assigned_to", None),
            "suggested_action": getattr(current_work_order, "suggested_action", None),
            "created_at": current_work_order.created_at.isoformat() if getattr(current_work_order, "created_at", None) else None,
            "updated_at": current_work_order.updated_at.isoformat() if getattr(current_work_order, "updated_at", None) else None,
            **_derive_dispatch_ui_meta(
                current_work_order,
                current_dispatch=current_dispatch,
                assigned_user=assigned_user,
                audit_logs=audit_logs,
            ),
        }

    current_dispatch_meta = (
        _derive_dispatch_ui_meta(
            current_work_order,
            current_dispatch=current_dispatch,
            assigned_user=assigned_user,
        )
        if current_dispatch and current_work_order
        else (
            derive_dispatch_ui_meta_from_task(current_dispatch, assigned_user=assigned_user)
            if current_dispatch
            else None
        )
    )

    return {
        "id": incident.id,
        "incident_id": incident.incident_id,
        "source": incident.source,
        "building_id": incident.building_id,
        "device_id": incident.device_id,
        "rule_triggered": incident.rule_triggered,
        "hvac_root_cause": incident.hvac_root_cause,
        "incident_status": incident.incident_status,
        "workflow_status": incident.workflow_status,
        "priority": incident.priority,
        "summary_text": incident.summary_text,
        "first_seen_at": incident.first_seen_at.isoformat() if incident.first_seen_at else None,
        "last_seen_at": incident.last_seen_at.isoformat() if incident.last_seen_at else None,
        "continuity_expires_at": (
            incident.continuity_expires_at.isoformat() if incident.continuity_expires_at else None
        ),
        "anomaly_count": incident.anomaly_count,
        "peak_deviation_pct": incident.peak_deviation_pct,
        "latest_actual_value": incident.latest_actual_value,
        "latest_expected_value": incident.latest_expected_value,
        "is_active": incident.is_active,
        "resolved_at": incident.resolved_at.isoformat() if incident.resolved_at else None,
        "created_at": incident.created_at.isoformat() if incident.created_at else None,
        "updated_at": incident.updated_at.isoformat() if incident.updated_at else None,
        "current_work_order": current_work_order_data,
        "current_dispatch": (
            {
                "id": current_dispatch.id,
                "dispatch_status": current_dispatch.dispatch_status,
                "attempt_no": current_dispatch.attempt_no,
                **(current_dispatch_meta or {}),
            }
            if current_dispatch else None
        ),
    }


def serialize_incident_detail(
    incident: AnomalyIncident,
    *,
    current_work_order: WorkOrder | None = None,
    current_dispatch: DispatchTask | None = None,
    work_orders: list[WorkOrder] | None = None,
    current_dispatches_by_work_order_id: dict[str, DispatchTask] | None = None,
    event_links: list[IncidentEventLink] | None = None,
    prediction_links: list[IncidentPredictionLink] | None = None,
    assigned_users_by_id: dict[str, User] | None = None,
    audit_logs_by_work_order_id: dict[str, list[WorkOrderAuditLog]] | None = None,
) -> dict[str, Any]:
    data = serialize_incident(
        incident,
        current_work_order=current_work_order,
        current_dispatch=current_dispatch,
        assigned_user=(
            assigned_users_by_id or {}
        ).get(current_work_order.assigned_to or "") if current_work_order else None,
        audit_logs=(audit_logs_by_work_order_id or {}).get(current_work_order.id, []) if current_work_order else None,
    )
    data["work_orders"] = [
        {
            "id": wo.id,
            "ticket_id": wo.ticket_id,
            "status": wo.status,
            "priority": wo.priority,
            "created_at": wo.created_at.isoformat() if wo.created_at else None,
            "updated_at": wo.updated_at.isoformat() if wo.updated_at else None,
            "worker_result": getattr(wo, "worker_result", None),
            "worker_notes": getattr(wo, "worker_notes", None),
            "ai_decision": getattr(wo, "ai_decision", None),
            "ai_reason": getattr(wo, "ai_reason", None),
            "assigned_to": getattr(wo, "assigned_to", None),
            "suggested_action": getattr(wo, "suggested_action", None),
            **_derive_dispatch_ui_meta(
                wo,
                current_dispatch=(current_dispatches_by_work_order_id or {}).get(wo.id),
                assigned_user=(assigned_users_by_id or {}).get(getattr(wo, "assigned_to", "") or ""),
                audit_logs=(audit_logs_by_work_order_id or {}).get(wo.id, []),
            ),
        }
        for wo in (work_orders or [])
    ]
    data["event_links"] = [
        {
            "id": link.id,
            "data_timestamp": link.data_timestamp.isoformat() if link.data_timestamp else None,
            "actual_value": link.actual_value,
            "expected_value": link.expected_value,
            "deviation_pct": link.deviation_pct,
            "rule_triggered": link.rule_triggered,
            "hvac_root_cause": link.hvac_root_cause,
            "type": "event",
        }
        for link in (event_links or [])
    ]
    data["prediction_links"] = [
        {
            "id": link.id,
            "forecast_for_timestamp": link.forecast_for_timestamp.isoformat() if link.forecast_for_timestamp else None,
            "predicted_value": link.predicted_value,
            "expected_value": link.expected_value,
            "deviation_pct": link.deviation_pct,
            "metric_name": link.metric_name,
            "risk_level": link.risk_level,
            "type": "prediction",
        }
        for link in (prediction_links or [])
    ]
    return data


async def create_or_merge_prediction_incident(
    db: AsyncSession,
    *,
    pred: PredictedAnomalyEvent,
) -> tuple[AnomalyIncident | None, WorkOrder | None, bool]:
    pred_id = str(pred.id)
    existing_link = await db.execute(
        select(IncidentPredictionLink.id).where(
            IncidentPredictionLink.predicted_anomaly_event_id == pred_id
        ).limit(1)
    )
    if existing_link.scalar_one_or_none():
        return None, None, False

    merge_key = build_merge_key_for_prediction(pred)
    stmt = (
        select(AnomalyIncident)
        .where(
            AnomalyIncident.source == "prediction",
            AnomalyIncident.merge_key == merge_key,
            AnomalyIncident.is_active == True,  # noqa: E712
            AnomalyIncident.workflow_status.in_(_MERGEABLE_WORKFLOW_STATUSES),
            AnomalyIncident.continuity_expires_at >= pred.forecast_for_timestamp,
        )
        .order_by(AnomalyIncident.last_seen_at.desc())
        .limit(1)
        .with_for_update()
    )
    incident = (await db.execute(stmt)).scalar_one_or_none()
    if incident:
        await _append_incident_prediction_link(db, incident=incident, pred=pred)
        _refresh_incident_from_prediction(incident, pred=pred)
        current_work_order = await _get_work_order(db, incident.current_work_order_id)
        if current_work_order:
            current_work_order.issue_description = incident.summary_text
            current_work_order.priority = incident.priority
            current_work_order.updated_at = datetime.now(timezone.utc)
            await sync_incident_from_work_order(db, work_order=current_work_order)
            await _write_audit_log(
                db,
                work_order_id=current_work_order.id,
                action="merge_prediction_evidence",
                old_status=current_work_order.status,
                new_status=current_work_order.status,
                actor_type="system",
                detail={
                    "incident_id": incident.incident_id,
                    "predicted_anomaly_event_id": pred_id,
                    "anomaly_count": incident.anomaly_count,
                },
            )
        return incident, current_work_order, False

    priority = assign_prediction_priority(pred)
    incident = AnomalyIncident(
        incident_id=_generate_incident_id(pred.forecast_for_timestamp),
        source="prediction",
        building_id=pred.building_id,
        device_id=None,
        rule_triggered=pred.metric_name,
        hvac_root_cause=None,
        merge_key=merge_key,
        incident_status="open",
        workflow_status="pending_review",
        priority=priority,
        first_seen_at=pred.forecast_for_timestamp,
        last_seen_at=pred.forecast_for_timestamp,
        continuity_expires_at=pred.forecast_for_timestamp + timedelta(
            hours=get_prediction_continuity_window_hours(pred)
        ),
        anomaly_count=1,
        peak_deviation_pct=abs(pred.deviation_pct or 0),
        latest_actual_value=pred.predicted_value,
        latest_expected_value=pred.expected_value,
        summary_text=build_prediction_summary(
            building_id=pred.building_id,
            metric_name=pred.metric_name,
            first_seen_at=pred.forecast_for_timestamp,
            last_seen_at=pred.forecast_for_timestamp,
            anomaly_count=1,
            peak_deviation_pct=abs(pred.deviation_pct or 0),
            latest_actual_value=pred.predicted_value,
            latest_expected_value=pred.expected_value,
        ),
        is_active=True,
    )
    db.add(incident)
    await db.flush()

    await _append_incident_prediction_link(db, incident=incident, pred=pred)
    work_order = await create_work_order(
        db,
        building_id=pred.building_id,
        issue_description=incident.summary_text,
        suggested_action=build_prediction_suggested_action(pred),
        priority=priority,
        source="prediction",
        incident_id=incident.id,
        anomaly_evidence=None,
    )
    incident.current_work_order_id = work_order.id
    incident.workflow_status = work_order.status
    await sync_incident_from_work_order(db, work_order=work_order)
    return incident, work_order, True
