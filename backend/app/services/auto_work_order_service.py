"""
自动工单生成服务：异常事件 / 预测预警 → 工单 → AI 审批。

设计原则：
  1. 所有被检测系统确认的异常都生成工单（检测阈值即为第一道过滤）
  2. AI 审批引擎是唯一的智能过滤层（第二道过滤）
  3. 去重：同一 anomaly_event 不重复建工单
  4. 优先级：按异常类型 + 偏离程度自动分配
  5. 预测预警工单优先级整体低于告警工单
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AnomalyEvent, PredictedAnomalyEvent
from app.services.incident_service import (
    create_or_merge_alert_incident,
    create_or_merge_prediction_incident,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 楼宇显示名映射（与 anomaly_detection_service 一致）
# ---------------------------------------------------------------------------
_BUILDING_DISPLAY = {
    "Fox_office_Alice": "Alice 办公楼",
    "Fox_education_Louie": "Louie 教学楼",
    "Fox_public_Henry": "Henry 公共服务楼",
}

# ---------------------------------------------------------------------------
# 异常规则 → 中文描述
# ---------------------------------------------------------------------------
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

# ---------------------------------------------------------------------------
# 预测指标 → 中文描述
# ---------------------------------------------------------------------------
_METRIC_DESC = {
    "electricity_kwh": "电耗",
    "water_m3": "水耗",
    "hac_energy": "暖通能耗",
}


# ---------------------------------------------------------------------------
# 优先级分配
# ---------------------------------------------------------------------------
def _assign_alert_priority(event: AnomalyEvent) -> str:
    """告警工单优先级：基于异常类型和偏离程度。"""
    rule = event.rule_triggered or ""
    dev = abs(event.deviation_pct or 0)

    # 漏水始终高优先级
    if rule in ("water_leak", "flag_water"):
        return "high"

    # 有明确 HVAC 根因
    if event.hvac_root_cause in ("A_low_efficiency", "B_small_deltaT", "C_unexpected_on"):
        return "high"

    # 按偏离程度
    if dev > 50:
        return "high"
    elif dev > 30:
        return "medium"
    else:
        return "low"


def _assign_prediction_priority(pred: PredictedAnomalyEvent) -> str:
    """预警工单优先级：整体低于告警一档。"""
    risk = pred.risk_level or "normal"
    if risk == "high":
        return "medium"  # 预测高风险 = 中优先级
    elif risk == "medium":
        return "low"
    else:
        return "low"


# ---------------------------------------------------------------------------
# 异常事件 → 工单描述生成
# ---------------------------------------------------------------------------
def _build_alert_description(event: AnomalyEvent) -> tuple[str, str]:
    """返回 (issue_description, suggested_action)。"""
    building_name = _BUILDING_DISPLAY.get(event.building_id, event.building_id)
    rule_desc = _RULE_DESC.get(event.rule_triggered, event.rule_triggered)
    ts_str = event.data_timestamp.strftime("%Y-%m-%d %H:%M") if event.data_timestamp else "未知时间"

    dev_info = ""
    if event.deviation_pct is not None:
        dev_info = f"，偏离 {event.deviation_pct:+.1f}%"
    if event.actual_value is not None and event.expected_value is not None:
        dev_info += f"（实际={event.actual_value:.1f}，预期={event.expected_value:.1f}）"

    cause_info = ""
    if event.hvac_root_cause and event.hvac_root_cause in _HVAC_CAUSE_DESC:
        cause_info = f"，根因分析：{_HVAC_CAUSE_DESC[event.hvac_root_cause]}"

    issue = f"[{building_name}] {ts_str} 检测到{rule_desc}{dev_info}{cause_info}"
    action = _RULE_ACTION.get(event.rule_triggered, "请现场排查异常原因")

    if event.hvac_root_cause == "A_low_efficiency":
        action = "检查冷水机组 COP，清洗冷凝器/蒸发器，检查制冷剂充注量"
    elif event.hvac_root_cause == "B_small_deltaT":
        action = "检查压差旁通阀开度，排查末端堵塞或水泵扬程不足"
    elif event.hvac_root_cause == "C_unexpected_on":
        action = "检查 BMS 排程设置，确认是否有未登记的加班或活动"

    return issue, action


def _build_prediction_description(pred: PredictedAnomalyEvent) -> tuple[str, str]:
    """返回 (issue_description, suggested_action)。"""
    building_name = _BUILDING_DISPLAY.get(pred.building_id, pred.building_id)
    metric_desc = _METRIC_DESC.get(pred.metric_name, pred.metric_name)
    ts_str = pred.forecast_for_timestamp.strftime("%Y-%m-%d %H:%M") if pred.forecast_for_timestamp else "未知时间"

    dev_info = ""
    if pred.deviation_pct is not None:
        dev_info = f"，预计偏离 {pred.deviation_pct:+.1f}%"

    issue = f"[预警][{building_name}] 预测 {ts_str} {metric_desc}将异常偏高{dev_info}"
    action = f"建议提前检查{metric_desc}相关设备运行状态，预防异常发生"

    return issue, action


# ---------------------------------------------------------------------------
# 核心：异常事件批量转工单
# ---------------------------------------------------------------------------
async def auto_create_alert_orders(
    db: AsyncSession,
    building_id: str,
) -> dict[str, int]:
    """
    对指定楼宇的所有 anomaly_events 自动创建工单。
    去重：已进入 incident 时间线的异常事件不重复处理。
    连续异常优先合并到同一个 incident，再决定是否复用当前工单。
    返回 {"created": N, "merged": M, "skipped_dup": M}。
    """
    # 查询该楼所有异常事件
    result = await db.execute(
        select(AnomalyEvent)
        .where(AnomalyEvent.building_id == building_id)
        .order_by(AnomalyEvent.data_timestamp.asc())
    )
    events = list(result.scalars().all())

    if not events:
        return {"created": 0, "merged": 0, "skipped_dup": 0}

    created = 0
    merged = 0
    skipped = 0

    for event in events:
        incident, wo, created_new = await create_or_merge_alert_incident(db, event=event)
        if incident is None:
            skipped += 1
            continue
        if created_new:
            created += 1
        else:
            merged += 1

    if created > 0 or merged > 0:
        await db.commit()
        logger.info(
            "自动建 incident/工单（告警）: building=%s created=%d merged=%d skipped=%d",
            building_id, created, merged, skipped,
        )

    return {"created": created, "merged": merged, "skipped_dup": skipped}


# ---------------------------------------------------------------------------
# 核心：预测预警批量转工单
# ---------------------------------------------------------------------------
async def auto_create_prediction_orders(
    db: AsyncSession,
    building_id: str,
) -> dict[str, int]:
    """
    对指定楼宇的 predicted_anomaly_events（risk_level != 'normal'）自动创建 incident/工单。
    """
    result = await db.execute(
        select(PredictedAnomalyEvent)
        .where(
            PredictedAnomalyEvent.building_id == building_id,
            PredictedAnomalyEvent.risk_level != "normal",
        )
        .order_by(PredictedAnomalyEvent.forecast_for_timestamp.asc())
    )
    predictions = list(result.scalars().all())

    if not predictions:
        return {"created": 0, "merged": 0, "skipped_dup": 0}

    created = 0
    merged = 0
    skipped = 0

    for pred in predictions:
        incident, wo, created_new = await create_or_merge_prediction_incident(db, pred=pred)
        if incident is None:
            skipped += 1
            continue
        if created_new:
            created += 1
        else:
            merged += 1

    if created > 0 or merged > 0:
        await db.commit()
        logger.info(
            "自动建 incident/工单（预警）: building=%s created=%d merged=%d skipped=%d",
            building_id, created, merged, skipped,
        )

    return {"created": created, "merged": merged, "skipped_dup": skipped}


# ---------------------------------------------------------------------------
# 批量触发 AI 审批（对所有 pending_review 工单）
# ---------------------------------------------------------------------------
async def trigger_ai_review_for_pending(db: AsyncSession) -> int:
    """对所有 pending_review 工单触发 AI 审批，返回处理数量。"""
    from app.db.models import WorkOrder
    from app.services.ai_review_service import review_work_order

    result = await db.execute(
        select(WorkOrder.id)
        .where(
            WorkOrder.status == "pending_review",
            WorkOrder.ai_reviewed_at.is_(None),
        )
    )
    pending_ids = [r[0] for r in result.fetchall()]

    if not pending_ids:
        return 0

    reviewed = 0
    for wo_id in pending_ids:
        try:
            await review_work_order(db, wo_id)
            await db.commit()
            reviewed += 1
        except Exception:
            await db.rollback()
            logger.exception("AI 审批失败: wo_id=%s", wo_id)

    logger.info("AI 审批批量处理: pending=%d reviewed=%d", len(pending_ids), reviewed)
    return reviewed
