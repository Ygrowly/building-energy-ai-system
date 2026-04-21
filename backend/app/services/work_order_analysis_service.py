from __future__ import annotations

import re
from collections import Counter
from datetime import date, datetime, time, timedelta, timezone
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.person_name import format_person_display_name, replace_person_names_in_text
from app.core.time_context import get_today
from app.db.models import (
    DispatchHallEntry,
    DispatchTask,
    MaintenanceExperience,
    MaintenanceExperienceUsageLog,
    User,
    WorkOrder,
    WorkerTeam,
)
from app.services.work_order_insights_service import CLOSED_WORK_ORDER_STATUSES, PENDING_CLOSE_STATUSES

ANALYSIS_INTENTS = {
    "worker_performance",
    "team_performance",
    "building_hotspot",
    "overdue_analysis",
    "open_work_order_analysis",
    "support_takeover_analysis",
    "reassign_analysis",
    "experience_usage_analysis",
    "daily_report",
    "weekly_report",
    "monthly_report",
    "comparison_analysis",
}

ANALYSIS_GROUP_BYS = {"worker", "team", "building", "day", "status", "experience", "period"}

_BUILDING_LABELS = {
    "education": "教学楼",
    "office": "办公楼",
    "public services": "公共楼",
}
_BUILDING_ALIASES = {
    "education": "education",
    "教学楼": "education",
    "fox_education_louie": "education",
    "office": "office",
    "办公楼": "office",
    "fox_office_alice": "office",
    "public": "public services",
    "public services": "public services",
    "公共楼": "public services",
    "公共服务楼": "public services",
    "fox_public_henry": "public services",
}
_STATUS_ALIASES = {
    "已完成": "completed",
    "完成": "completed",
    "completed": "completed",
    "待协同": "waiting_support",
    "协同": "waiting_support",
    "waiting_support": "waiting_support",
    "超时": "overdue",
    "overdue": "overdue",
    "待关闭": "pending_close",
    "已关闭": "closed",
    "closed": "closed",
    "执行中": "dispatched",
    "已派工": "dispatched",
    "派工中": "dispatched",
    "dispatched": "dispatched",
    "处理中": "processing",
    "processing": "processing",
    "待派工": "pending_dispatch",
    "pending_dispatch": "pending_dispatch",
}
_STATUS_LABELS = {
    "pending_dispatch": "待派工",
    "dispatched": "已派工",
    "processing": "处理中",
    "waiting_support": "待协同",
    "pending_close": "待关闭",
    "completed": "已完成",
    "closed": "已关闭",
    "overdue": "超时",
}
_OPEN_WORK_ORDER_KEYWORDS = (
    "未完成",
    "未关闭",
    "未闭环",
    "开放工单",
    "在途工单",
    "待处理工单",
    "待关闭工单",
)
_STATUS_QUERY_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("pending_close", ("待关闭", "待闭环")),
    ("waiting_support", ("待协同", "协同中", "需协同", "支援中")),
    ("processing", ("处理中", "维修中", "处置中")),
    ("dispatched", ("已派工", "派工中", "已分派")),
    ("pending_dispatch", ("待派工", "未派工")),
    ("completed", ("已完成", "已完工")),
    ("closed", ("已关闭", "已闭环")),
    ("overdue", ("超时", "sla")),
)
_ISSUE_CATEGORY_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("暖通空调", ("空调", "暖通", "冷机", "风机", "温度", "hvac", "chiller")),
    ("电气照明", ("电", "照明", "配电", "跳闸", "elect", "power")),
    ("给排水", ("漏水", "排水", "阀门", "管路", "plumb", "water")),
    ("自控传感", ("控制", "传感", "联动", "bms", "sensor", "controller")),
)


def _dt(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _coerce_date(value: Any) -> date | None:
    if value in (None, ""):
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    try:
        return date.fromisoformat(str(value))
    except ValueError:
        return None


def _coerce_datetime(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _minutes_between(start: datetime | None, end: datetime | None) -> float | None:
    left = _coerce_datetime(start)
    right = _coerce_datetime(end)
    if left is None or right is None:
        return None
    minutes = (right - left).total_seconds() / 60
    if minutes < 0:
        return None
    return round(minutes, 2)


def _average(values: list[float]) -> float | None:
    if not values:
        return None
    return round(sum(values) / len(values), 2)


def _ratio(numerator: int, denominator: int) -> float:
    if denominator <= 0:
        return 0.0
    return round(numerator / denominator, 4)


def _within_window(value: datetime | None, start_at: datetime, end_at: datetime) -> bool:
    target = _coerce_datetime(value)
    if target is None:
        return False
    return start_at <= target < end_at


def _normalize_building(value: str | None) -> str | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    normalized = raw.replace("_", " ").replace("-", " ").strip().lower()
    normalized = " ".join(normalized.split())
    return _BUILDING_ALIASES.get(normalized) or _BUILDING_ALIASES.get(normalized.replace(" ", "_")) or raw


def _building_label(value: str | None) -> str:
    normalized = _normalize_building(value)
    if normalized in _BUILDING_LABELS:
        return _BUILDING_LABELS[normalized]
    return str(value or "全部楼宇")


def _status_label(value: str | None) -> str:
    normalized = str(value or "").strip().lower()
    return _STATUS_LABELS.get(normalized, value or "未知状态")


def _normalized_statuses(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        rows = [segment.strip() for segment in re.split(r"[,，/、\s]+", value) if segment.strip()]
    elif isinstance(value, list):
        rows = [str(item).strip() for item in value if str(item).strip()]
    else:
        rows = [str(value).strip()]
    normalized = [_STATUS_ALIASES.get(item, item) for item in rows]
    return list(dict.fromkeys(normalized))


def _extract_statuses_from_question(question: str | None) -> list[str]:
    normalized = str(question or "").strip().lower()
    if not normalized:
        return []
    matches: list[str] = []
    for status, keywords in _STATUS_QUERY_RULES:
        if any(keyword in normalized for keyword in keywords):
            matches.append(status)
    if any(token in normalized for token in _OPEN_WORK_ORDER_KEYWORDS):
        matches = [item for item in matches if item not in {"completed", "closed"}]
    return list(dict.fromkeys(matches))


def _infer_issue_category(text: str | None) -> str:
    normalized = str(text or "").strip().lower()
    if not normalized:
        return "其他问题"
    for label, keywords in _ISSUE_CATEGORY_RULES:
        if any(keyword in normalized for keyword in keywords):
            return label
    return "其他问题"


def infer_work_order_analysis_intent(question: str, fallback: str | None = None) -> str:
    normalized = (question or "").strip().lower()
    if not normalized:
        return fallback or "monthly_report"
    if any(token in normalized for token in _OPEN_WORK_ORDER_KEYWORDS):
        return "open_work_order_analysis"
    if any(token in normalized for token in ("月报", "本月总结", "运营总结", "月度")):
        return "monthly_report"
    if any(token in normalized for token in ("周报", "本周总结")):
        return "weekly_report"
    if any(token in normalized for token in ("日报", "今日总结", "今天总结")):
        return "daily_report"
    if any(token in normalized for token in ("对比", "比较", "环比", "同比")):
        return "comparison_analysis"
    if any(token in normalized for token in ("经验", "引用", "推荐", "被引用最多", "使用最多")):
        return "experience_usage_analysis"
    if any(token in normalized for token in ("接管", "接手", "协同", "支援")):
        return "support_takeover_analysis"
    if any(token in normalized for token in ("改派", "重派", "转派")):
        return "reassign_analysis"
    if any(token in normalized for token in ("超时", "sla", "预警", "风险")):
        return "overdue_analysis"
    if any(token in normalized for token in ("班组", "团队")):
        return "team_performance"
    if any(token in normalized for token in ("楼", "建筑", "热点", "问题最多")):
        return "building_hotspot"
    if any(token in normalized for token in ("人员", "维修员", "维修人员", "师傅", "谁处理得最多")):
        return "worker_performance"
    return fallback or "monthly_report"


def _infer_group_by(question: str, intent: str, current: str | None = None) -> str:
    if current in ANALYSIS_GROUP_BYS:
        return current
    normalized = question or ""
    if "按班组" in normalized or "班组拆" in normalized:
        return "team"
    if any(token in normalized for token in ("按人", "按维修人员", "按人员")):
        return "worker"
    if any(token in normalized for token in ("按楼", "按楼宇", "按建筑")):
        return "building"
    if any(token in normalized for token in ("每天", "每日", "趋势")):
        return "day"
    defaults = {
        "worker_performance": "worker",
        "team_performance": "team",
        "building_hotspot": "building",
        "overdue_analysis": "building",
        "open_work_order_analysis": "status",
        "support_takeover_analysis": "team",
        "reassign_analysis": "team",
        "experience_usage_analysis": "experience",
        "comparison_analysis": "period",
        "daily_report": "day",
        "weekly_report": "day",
        "monthly_report": "day",
    }
    return defaults.get(intent, "worker")


def _infer_metrics(question: str, intent: str, raw_metrics: Any = None) -> list[str]:
    if raw_metrics:
        if isinstance(raw_metrics, str):
            metrics = [item.strip() for item in re.split(r"[,，/、\s]+", raw_metrics) if item.strip()]
        else:
            metrics = [str(item).strip() for item in raw_metrics if str(item).strip()]
        if metrics:
            return list(dict.fromkeys(metrics))
    normalized = question or ""
    if intent == "open_work_order_analysis":
        metrics: list[str] = []
        if any(token in normalized.lower() for token in ("超时", "sla")):
            metrics.append("overdue_count")
        if any(token in normalized for token in ("待协同", "协同", "支援")):
            metrics.append("waiting_support_count")
        if any(token in normalized for token in ("待关闭", "待闭环")):
            metrics.append("pending_close_count")
        return list(dict.fromkeys(metrics or ["open_count", "overdue_count"]))
    metrics: list[str] = []
    if any(token in normalized for token in ("接单", "派工量")):
        metrics.append("assigned_count")
    if ("完成" in normalized and "未完成" not in normalized) or "闭环" in normalized:
        metrics.append("completed_count")
    if any(token in normalized for token in ("超时", "sla")):
        metrics.append("overdue_count")
    if "到场" in normalized:
        metrics.append("avg_arrive_minutes")
    defaults = {
        "worker_performance": ["assigned_count", "completed_count", "avg_arrive_minutes", "overdue_count"],
        "team_performance": ["assigned_count", "completed_count", "overdue_count"],
        "building_hotspot": ["work_order_count", "completed_count", "overdue_count"],
        "overdue_analysis": ["overdue_count"],
        "open_work_order_analysis": ["open_count", "overdue_count"],
        "support_takeover_analysis": ["waiting_support_count", "takeover_count"],
        "reassign_analysis": ["reassign_count"],
        "experience_usage_analysis": ["usage_count", "helpful_count"],
        "daily_report": ["created_count", "completed_count", "overdue_count", "avg_arrive_minutes"],
        "weekly_report": ["created_count", "completed_count", "overdue_count", "avg_arrive_minutes"],
        "monthly_report": ["created_count", "completed_count", "overdue_count", "avg_arrive_minutes"],
        "comparison_analysis": ["created_count", "completed_count", "overdue_count", "avg_arrive_minutes"],
    }
    return list(dict.fromkeys(metrics or defaults.get(intent, ["created_count", "completed_count", "overdue_count"])))


def resolve_work_order_analysis_range(
    *,
    question: str,
    date_from: date | None = None,
    date_to: date | None = None,
    intent: str,
    today: date | None = None,
) -> dict[str, Any]:
    anchor = today or get_today()
    normalized = question or ""
    explicit_dates = [
        _coerce_date(item)
        for item in re.findall(r"(20\d{2}-\d{2}-\d{2})", normalized)
    ]
    explicit_dates = [item for item in explicit_dates if item is not None]

    start = _coerce_date(date_from)
    end = _coerce_date(date_to)
    if start is None and explicit_dates:
        start = explicit_dates[0]
    if end is None and len(explicit_dates) >= 2:
        end = explicit_dates[1]

    label = ""
    previous_range: dict[str, Any] | None = None
    if start and end:
        pass
    elif "今天" in normalized or "今日" in normalized:
        start = end = anchor
        label = "今天"
    elif "昨天" in normalized:
        start = end = anchor - timedelta(days=1)
        label = "昨天"
    elif "本周" in normalized and "上周" in normalized:
        current_start = anchor - timedelta(days=anchor.weekday())
        start = current_start
        end = anchor
        previous_end = current_start - timedelta(days=1)
        previous_start = previous_end - timedelta(days=6)
        previous_range = {"date_from": previous_start, "date_to": previous_end, "label": "上周"}
        label = "本周"
    elif "上周" in normalized:
        current_start = anchor - timedelta(days=anchor.weekday())
        end = current_start - timedelta(days=1)
        start = end - timedelta(days=6)
        label = "上周"
    elif "本周" in normalized:
        start = anchor - timedelta(days=anchor.weekday())
        end = anchor
        label = "本周"
    elif "本月" in normalized and "上月" in normalized:
        current_month_start = anchor.replace(day=1)
        start = current_month_start
        end = anchor
        previous_end = current_month_start - timedelta(days=1)
        previous_start = previous_end.replace(day=1)
        previous_range = {"date_from": previous_start, "date_to": previous_end, "label": "上月"}
        label = "本月"
    elif "上月" in normalized:
        current_month_start = anchor.replace(day=1)
        end = current_month_start - timedelta(days=1)
        start = end.replace(day=1)
        label = "上月"
    elif "本月" in normalized:
        start = anchor.replace(day=1)
        end = anchor
        label = "本月"
    else:
        days_match = re.search(r"(?:最近|近)(\d{1,3})天", normalized)
        if days_match:
            days = max(int(days_match.group(1) or 7), 1)
            start = anchor - timedelta(days=days - 1)
            end = anchor
            label = f"近{days}天"

    if start is None or end is None:
        if intent == "daily_report":
            start = end = anchor
            label = "今天"
        elif intent == "weekly_report":
            start = anchor - timedelta(days=anchor.weekday())
            end = anchor
            label = "本周"
        elif intent == "monthly_report":
            start = anchor.replace(day=1)
            end = anchor
            label = "本月"
        else:
            start = anchor - timedelta(days=6)
            end = anchor
            label = "近7天"

    if start > end:
        start, end = end, start

    if previous_range is None and ("对比" in normalized or "比较" in normalized or intent == "comparison_analysis"):
        span_days = max((end - start).days + 1, 1)
        previous_end = start - timedelta(days=1)
        previous_start = previous_end - timedelta(days=span_days - 1)
        previous_range = {"date_from": previous_start, "date_to": previous_end, "label": "上一周期"}

    return {
        "date_from": start,
        "date_to": end,
        "date_label": f"{label}（{start.isoformat()} 至 {end.isoformat()}）",
        "comparison_previous": previous_range,
    }


def extract_work_order_analysis_scope(
    *,
    question: str,
    scope: dict[str, Any] | None = None,
    previous_scope: dict[str, Any] | None = None,
    intent: str | None = None,
    today: date | None = None,
) -> dict[str, Any]:
    base = dict(previous_scope or {})
    if scope:
        for key, value in scope.items():
            if value not in (None, "", [], {}):
                base[key] = value
    normalized = question or ""
    if any(token in normalized for token in ("全部楼宇", "全局", "总体")):
        for key in ("building_id", "worker_id", "worker_name", "team_id", "team_name"):
            base.pop(key, None)
    for token in ("Education", "Office", "Public services", "Public", "教学楼", "办公楼", "公共楼", "公共服务楼", "Fox_education_Louie", "Fox_office_Alice", "Fox_public_Henry"):
        if token.lower() in normalized.lower():
            base["building_id"] = _normalize_building(token)
            break
    if base.get("building_id"):
        base["building_id"] = _normalize_building(str(base["building_id"]))
    statuses = _normalized_statuses(base.get("status"))
    if not statuses:
        statuses = _extract_statuses_from_question(normalized)
    if statuses:
        base["status"] = list(dict.fromkeys(statuses))
    resolved_intent = infer_work_order_analysis_intent(question, fallback=intent or str(base.get("intent") or "monthly_report"))
    base["intent"] = resolved_intent
    base["group_by"] = _infer_group_by(question, resolved_intent, current=str(base.get("group_by") or ""))
    base["metrics"] = _infer_metrics(question, resolved_intent, base.get("metrics"))
    base.update(
        resolve_work_order_analysis_range(
            question=question,
            date_from=_coerce_date(base.get("date_from")),
            date_to=_coerce_date(base.get("date_to")),
            intent=resolved_intent,
            today=today,
        )
    )
    return base


def _scope_summary(scope: dict[str, Any]) -> str:
    parts: list[str] = [str(scope.get("date_label") or "当前时间范围")]
    if scope.get("building_id"):
        parts.append(_building_label(str(scope["building_id"])))
    if scope.get("team_name"):
        parts.append(str(scope["team_name"]))
    elif scope.get("team_id"):
        parts.append(f"班组 {scope['team_id']}")
    if scope.get("worker_name"):
        parts.append(str(scope["worker_name"]))
    elif scope.get("worker_id"):
        parts.append(f"人员 {scope['worker_id']}")
    return "，".join(parts)


async def _load_dispatch_rows(
    db: AsyncSession,
    *,
    start_at: datetime,
    end_at: datetime,
) -> list[dict[str, Any]]:
    result = await db.execute(
        select(
            DispatchTask.id,
            DispatchTask.work_order_id,
            DispatchTask.attempt_no,
            DispatchTask.dispatch_mode,
            DispatchTask.dispatch_status,
            DispatchTask.assigned_team_id,
            DispatchTask.assigned_to,
            DispatchTask.transfer_from_dispatch_id,
            DispatchTask.support_team_id,
            DispatchTask.assigned_at,
            DispatchTask.accepted_at,
            DispatchTask.arrived_at,
            DispatchTask.processing_started_at,
            DispatchTask.completed_at,
            DispatchTask.closed_at,
            DispatchTask.finish_deadline_at,
            DispatchTask.timeout_level,
            DispatchTask.latest_note,
            WorkOrder.ticket_id,
            WorkOrder.building_id,
            WorkOrder.issue_description,
            WorkOrder.priority,
            WorkOrder.status,
            WorkOrder.created_at,
            User.username,
            WorkerTeam.name,
        )
        .join(WorkOrder, DispatchTask.work_order_id == WorkOrder.id)
        .outerjoin(User, DispatchTask.assigned_to == User.id)
        .outerjoin(WorkerTeam, DispatchTask.assigned_team_id == WorkerTeam.id)
        .where(
            DispatchTask.assigned_at < end_at,
            or_(
                DispatchTask.assigned_at >= start_at,
                DispatchTask.accepted_at >= start_at,
                DispatchTask.arrived_at >= start_at,
                DispatchTask.processing_started_at >= start_at,
                DispatchTask.completed_at >= start_at,
                DispatchTask.closed_at >= start_at,
            ),
        )
    )
    rows: list[dict[str, Any]] = []
    for record in result.all():
        rows.append(
            {
                "dispatch_id": record[0],
                "work_order_id": record[1],
                "attempt_no": int(record[2] or 0),
                "dispatch_mode": record[3],
                "dispatch_status": record[4],
                "team_id": record[5],
                "worker_id": record[6],
                "transfer_from_dispatch_id": record[7],
                "support_team_id": record[8],
                "assigned_at": record[9],
                "accepted_at": record[10],
                "arrived_at": record[11],
                "processing_started_at": record[12],
                "completed_at": record[13],
                "closed_at": record[14],
                "finish_deadline_at": record[15],
                "timeout_level": record[16],
                "latest_note": replace_person_names_in_text(record[17]),
                "ticket_id": record[18],
                "building_id": record[19],
                "issue_description": record[20],
                "priority": record[21],
                "work_order_status": record[22],
                "work_order_created_at": record[23],
                "worker_name": record[24] or record[6] or "未分配",
                "team_name": record[25] or "未分组",
            }
        )
    return rows


async def _load_work_order_rows(
    db: AsyncSession,
    *,
    start_at: datetime,
    end_at: datetime,
) -> list[dict[str, Any]]:
    result = await db.execute(
        select(
            WorkOrder.id,
            WorkOrder.ticket_id,
            WorkOrder.building_id,
            WorkOrder.issue_description,
            WorkOrder.priority,
            WorkOrder.status,
            WorkOrder.created_at,
            WorkOrder.closed_at,
        )
        .where(
            WorkOrder.created_at < end_at,
            or_(WorkOrder.created_at >= start_at, WorkOrder.closed_at >= start_at),
        )
    )
    return [
        {
            "work_order_id": work_order_id,
            "ticket_id": ticket_id,
            "building_id": building_id,
            "issue_description": issue_description,
            "priority": priority,
            "status": status,
            "created_at": created_at,
            "closed_at": closed_at,
        }
        for work_order_id, ticket_id, building_id, issue_description, priority, status, created_at, closed_at in result.all()
    ]


async def _load_hall_rows(
    db: AsyncSession,
    *,
    start_at: datetime,
    end_at: datetime,
) -> list[dict[str, Any]]:
    result = await db.execute(
        select(
            DispatchHallEntry.id,
            DispatchHallEntry.work_order_id,
            DispatchHallEntry.entry_type,
            DispatchHallEntry.status,
            DispatchHallEntry.reason,
            DispatchHallEntry.support_reason,
            DispatchHallEntry.sla_stage,
            DispatchHallEntry.overdue_level,
            DispatchHallEntry.assigned_to,
            DispatchHallEntry.assigned_team_id,
            DispatchHallEntry.created_at,
            WorkOrder.ticket_id,
            WorkOrder.building_id,
            User.username,
            WorkerTeam.name,
        )
        .join(WorkOrder, DispatchHallEntry.work_order_id == WorkOrder.id)
        .outerjoin(User, DispatchHallEntry.assigned_to == User.id)
        .outerjoin(WorkerTeam, DispatchHallEntry.assigned_team_id == WorkerTeam.id)
        .where(
            DispatchHallEntry.created_at >= start_at,
            DispatchHallEntry.created_at < end_at,
        )
    )
    return [
        {
            "hall_entry_id": hall_entry_id,
            "work_order_id": work_order_id,
            "entry_type": entry_type,
            "status": status,
            "reason": reason,
            "support_reason": support_reason,
            "sla_stage": sla_stage,
            "overdue_level": overdue_level,
            "worker_id": worker_id,
            "team_id": team_id,
            "created_at": created_at,
            "ticket_id": ticket_id,
            "building_id": building_id,
            "worker_name": worker_name or worker_id or "未分配",
            "team_name": team_name or "未分组",
        }
        for hall_entry_id, work_order_id, entry_type, status, reason, support_reason, sla_stage, overdue_level, worker_id, team_id, created_at, ticket_id, building_id, worker_name, team_name in result.all()
    ]


async def _load_experience_rows(
    db: AsyncSession,
    *,
    start_at: datetime,
    end_at: datetime,
) -> list[dict[str, Any]]:
    result = await db.execute(
        select(
            MaintenanceExperienceUsageLog.id,
            MaintenanceExperienceUsageLog.experience_id,
            MaintenanceExperienceUsageLog.work_order_id,
            MaintenanceExperienceUsageLog.usage_type,
            MaintenanceExperienceUsageLog.created_at,
            MaintenanceExperience.source_work_order_id,
            MaintenanceExperience.building_id,
            MaintenanceExperience.organized_text,
            MaintenanceExperience.source_text,
            MaintenanceExperience.usage_count,
            MaintenanceExperience.helpful_count,
            MaintenanceExperience.is_active,
        )
        .join(MaintenanceExperience, MaintenanceExperienceUsageLog.experience_id == MaintenanceExperience.id)
        .where(
            MaintenanceExperienceUsageLog.created_at >= start_at,
            MaintenanceExperienceUsageLog.created_at < end_at,
        )
    )
    return [
        {
            "usage_log_id": usage_log_id,
            "experience_id": experience_id,
            "work_order_id": work_order_id,
            "usage_type": usage_type,
            "used_at": used_at,
            "source_work_order_id": source_work_order_id,
            "building_id": building_id,
            "experience_text": organized_text or source_text or "经验记录",
            "usage_count": int(usage_count or 0),
            "helpful_count": int(helpful_count or 0),
            "is_active": bool(is_active),
        }
        for usage_log_id, experience_id, work_order_id, usage_type, used_at, source_work_order_id, building_id, organized_text, source_text, usage_count, helpful_count, is_active in result.all()
    ]


def _dispatch_matches_scope(row: dict[str, Any], scope: dict[str, Any]) -> bool:
    building_filter = _normalize_building(scope.get("building_id"))
    if building_filter and _normalize_building(row.get("building_id")) != building_filter:
        return False
    team_id = scope.get("team_id")
    if team_id and str(row.get("team_id") or "") != str(team_id):
        return False
    worker_id = scope.get("worker_id")
    if worker_id and str(row.get("worker_id") or "") != str(worker_id):
        return False
    statuses = set(_normalized_statuses(scope.get("status")))
    if statuses:
        row_statuses = {
            str(row.get("work_order_status") or ""),
            str(row.get("dispatch_status") or ""),
            str(row.get("timeout_level") or ""),
        }
        if not row_statuses.intersection(statuses):
            return False
    return True


def _work_order_matches_scope(row: dict[str, Any], scope: dict[str, Any], allowed_work_order_ids: set[str] | None = None) -> bool:
    if allowed_work_order_ids is not None and str(row.get("work_order_id")) not in allowed_work_order_ids:
        return False
    building_filter = _normalize_building(scope.get("building_id"))
    if building_filter and _normalize_building(row.get("building_id")) != building_filter:
        return False
    statuses = set(_normalized_statuses(scope.get("status")))
    if statuses and str(row.get("status") or "") not in statuses:
        return False
    return True


def _experience_matches_scope(row: dict[str, Any], scope: dict[str, Any]) -> bool:
    building_filter = _normalize_building(scope.get("building_id"))
    if building_filter and _normalize_building(row.get("building_id")) != building_filter:
        return False
    return True


def _is_dispatch_overdue(row: dict[str, Any], end_at: datetime) -> bool:
    if str(row.get("timeout_level") or "") == "overdue":
        return True
    deadline = _coerce_datetime(row.get("finish_deadline_at"))
    if deadline is None:
        return False
    completed_at = _coerce_datetime(row.get("completed_at")) or end_at
    return completed_at > deadline


def _claims(*items: tuple[str, list[str]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for claim, refs in items:
        text = claim.strip()
        if text:
            rows.append({"claim": text, "evidence_refs": refs})
    return rows


def _empty_response(question: str, intent: str, scope: dict[str, Any]) -> dict[str, Any]:
    return {
        "question": question,
        "intent": intent,
        "readonly": True,
        "answer": f"我没有查到 {_scope_summary(scope)} 的相关记录，因此无法给出可靠结论。",
        "facts": {"scope": scope, "claims": [], "rows": [], "empty_reason": "no_data"},
        "metrics": {"summary": {}, "rows": []},
        "chart": None,
        "evidence_refs": [],
        "suggested_followups": ["缩小时间范围后重试", "切换楼宇或班组后重试"],
    }


def _open_work_order_payload(
    question: str,
    scope: dict[str, Any],
    work_order_rows: list[dict[str, Any]],
    dispatch_rows: list[dict[str, Any]],
    end_at: datetime,
) -> dict[str, Any]:
    requested_statuses = set(_normalized_statuses(scope.get("status")))
    latest_dispatch_by_work_order: dict[str, dict[str, Any]] = {}
    for row in dispatch_rows:
        work_order_id = str(row.get("work_order_id") or "")
        previous = latest_dispatch_by_work_order.get(work_order_id)
        current_sort = (
            _coerce_datetime(row.get("assigned_at")) or datetime.min.replace(tzinfo=timezone.utc),
            int(row.get("attempt_no") or 0),
        )
        if previous is None:
            latest_dispatch_by_work_order[work_order_id] = row
            continue
        previous_sort = (
            _coerce_datetime(previous.get("assigned_at")) or datetime.min.replace(tzinfo=timezone.utc),
            int(previous.get("attempt_no") or 0),
        )
        if current_sort >= previous_sort:
            latest_dispatch_by_work_order[work_order_id] = row

    active_rows: list[dict[str, Any]] = []
    for row in work_order_rows:
        status = str(row.get("status") or "").strip().lower()
        if status in CLOSED_WORK_ORDER_STATUSES:
            continue
        if requested_statuses and status not in requested_statuses:
            continue
        dispatch = latest_dispatch_by_work_order.get(str(row.get("work_order_id") or ""))
        active_rows.append(
            {
                "work_order_id": row.get("work_order_id"),
                "ticket_id": row.get("ticket_id"),
                "status": status,
                "status_label": _status_label(status),
                "building_name": _building_label(row.get("building_id")),
                "team_name": (dispatch or {}).get("team_name") or "未分组",
                "worker_name": (dispatch or {}).get("worker_name") or "未分配",
                "overdue": _is_dispatch_overdue(dispatch, end_at) if dispatch else False,
            }
        )

    if not active_rows:
        return _empty_response(question, "open_work_order_analysis", scope)

    group_by = str(scope.get("group_by") or "status")
    grouped: dict[str, dict[str, Any]] = {}
    for row in active_rows:
        if group_by == "team":
            key = row["team_name"] or "未分组"
            label = row["team_name"] or "未分组"
        elif group_by == "building":
            key = row["building_name"] or "未知楼宇"
            label = row["building_name"] or "未知楼宇"
        elif group_by == "worker":
            key = row["worker_name"] or "未分配"
            label = row["worker_name"] or "未分配"
        else:
            key = row["status"] or "unknown"
            label = row["status_label"]
        target = grouped.setdefault(
            key,
            {
                "key": key,
                "label": label,
                "work_order_count": 0,
                "overdue_count": 0,
            },
        )
        target["work_order_count"] += 1
        if row["overdue"]:
            target["overdue_count"] += 1

    rows = sorted(grouped.values(), key=lambda item: (-int(item["work_order_count"]), item["label"]))
    top = rows[0]
    status_counter = Counter(str(row["status"]) for row in active_rows)
    open_total = len(active_rows)
    overdue_total = sum(1 for row in active_rows if row["overdue"])
    pending_dispatch_count = int(status_counter.get("pending_dispatch", 0) + status_counter.get("dispatched", 0))
    processing_count = int(status_counter.get("processing", 0))
    waiting_support_count = int(status_counter.get("waiting_support", 0))
    pending_close_count = int(status_counter.get("pending_close", 0))
    target_label = "未完成工单"
    if requested_statuses:
        if len(requested_statuses) == 1:
            target_label = _status_label(next(iter(requested_statuses)))
        else:
            target_label = "指定状态工单"

    if group_by == "status":
        answer = (
            f"{scope['date_label']}内{target_label}共 {open_total} 单，"
            f"其中待派工/已派工 {pending_dispatch_count} 单，处理中 {processing_count} 单，"
            f"待协同 {waiting_support_count} 单，待关闭 {pending_close_count} 单，超时 {overdue_total} 单。"
        )
    else:
        group_label = {
            "team": "班组",
            "building": "楼宇",
            "worker": "人员",
        }.get(group_by, "维度")
        answer = (
            f"{scope['date_label']}内{target_label}共 {open_total} 单，按{group_label}看 "
            f"{top['label']} 最多，共 {top['work_order_count']} 单，其中超时 {top['overdue_count']} 单。"
        )

    return {
        "question": question,
        "intent": "open_work_order_analysis",
        "readonly": True,
        "answer": answer,
        "facts": {
            "scope": scope,
            "claims": _claims(
                (f"{scope['date_label']}内{target_label}共 {open_total} 单。", ["metrics.summary.open_total"]),
                (f"当前最多的是 {top['label']}，共 {top['work_order_count']} 单。", ["metrics.rows[0].work_order_count"]),
            ),
            "rows": active_rows[:12],
        },
        "metrics": {
            "summary": {
                "open_total": open_total,
                "overdue_total": overdue_total,
                "pending_dispatch_count": pending_dispatch_count,
                "processing_count": processing_count,
                "waiting_support_count": waiting_support_count,
                "pending_close_count": pending_close_count,
            },
            "rows": rows,
        },
        "chart": {
            "type": "bar",
            "title": f"{scope['date_label']}{target_label}分布",
            "source": "work_order_insights.open_work_order_analysis",
            "x": [item["label"] for item in rows[:6]],
            "series": [
                {"name": "工单数", "data": [item["work_order_count"] for item in rows[:6]]},
                {"name": "超时数", "data": [item["overdue_count"] for item in rows[:6]]},
            ],
        },
        "evidence_refs": ["work_orders", "dispatch_tasks"],
        "suggested_followups": ["查看未完成工单明细", "按班组拆分未完成工单", "只看待关闭工单"],
    }


def _worker_performance_payload(
    question: str,
    scope: dict[str, Any],
    dispatch_rows: list[dict[str, Any]],
    start_at: datetime,
    end_at: datetime,
) -> dict[str, Any]:
    grouped: dict[str, dict[str, Any]] = {}
    for row in dispatch_rows:
        key = str(row.get("worker_id") or row.get("worker_name") or "unassigned")
        target = grouped.setdefault(
            key,
            {
                "worker_id": row.get("worker_id"),
                "worker_name": row.get("worker_name") or "未分配",
                "team_name": row.get("team_name") or "未分组",
                "assigned_count": 0,
                "completed_count": 0,
                "overdue_count": 0,
                "waiting_support_count": 0,
                "accept_minutes": [],
                "arrive_minutes": [],
                "complete_minutes": [],
            },
        )
        if _within_window(row.get("assigned_at"), start_at, end_at):
            target["assigned_count"] += 1
        if _within_window(row.get("completed_at"), start_at, end_at):
            target["completed_count"] += 1
        if _is_dispatch_overdue(row, end_at):
            target["overdue_count"] += 1
        if str(row.get("dispatch_status") or "") == "waiting_support":
            target["waiting_support_count"] += 1
        accept_minutes = _minutes_between(row.get("assigned_at"), row.get("accepted_at"))
        if accept_minutes is not None:
            target["accept_minutes"].append(accept_minutes)
        arrive_minutes = _minutes_between(row.get("accepted_at") or row.get("assigned_at"), row.get("arrived_at"))
        if arrive_minutes is not None:
            target["arrive_minutes"].append(arrive_minutes)
        complete_minutes = _minutes_between(row.get("assigned_at"), row.get("completed_at"))
        if complete_minutes is not None:
            target["complete_minutes"].append(complete_minutes)

    rows = [
        {
            "worker_id": value["worker_id"],
            "worker_name": value["worker_name"],
            "team_name": value["team_name"],
            "assigned_count": value["assigned_count"],
            "completed_count": value["completed_count"],
            "overdue_count": value["overdue_count"],
            "waiting_support_count": value["waiting_support_count"],
            "avg_accept_minutes": _average(value["accept_minutes"]),
            "avg_arrive_minutes": _average(value["arrive_minutes"]),
            "avg_complete_minutes": _average(value["complete_minutes"]),
        }
        for value in grouped.values()
    ]
    rows = sorted(rows, key=lambda item: (-int(item["completed_count"]), int(item["overdue_count"]), item["worker_name"]))
    if not rows:
        return _empty_response(question, "worker_performance", scope)
    leader = rows[0]
    return {
        "question": question,
        "intent": "worker_performance",
        "readonly": True,
        "answer": f"{scope['date_label']}内，{leader['worker_name']} 完成 {leader['completed_count']} 单，超时 {leader['overdue_count']} 单；整体共统计 {len(rows)} 名维修人员。",
        "facts": {
            "scope": scope,
            "claims": _claims(
                (f"{leader['worker_name']} 完成 {leader['completed_count']} 单，是当前范围内完成量最高的维修人员。", ["metrics.rows[0].completed_count"]),
                (f"{leader['worker_name']} 平均到场 {leader['avg_arrive_minutes'] or '--'} 分钟。", ["metrics.rows[0].avg_arrive_minutes"]),
            ),
            "rows": rows[:10],
        },
        "metrics": {
            "summary": {
                "workers": len(rows),
                "assigned_total": sum(int(item["assigned_count"]) for item in rows),
                "completed_total": sum(int(item["completed_count"]) for item in rows),
                "overdue_total": sum(int(item["overdue_count"]) for item in rows),
            },
            "rows": rows,
        },
        "chart": {
            "type": "bar",
            "title": f"{scope['date_label']}维修人员完成量排名",
            "source": "work_order_insights.worker_performance",
            "x": [item["worker_name"] for item in rows[:6]],
            "series": [
                {"name": "完成数", "data": [item["completed_count"] for item in rows[:6]]},
                {"name": "超时数", "data": [item["overdue_count"] for item in rows[:6]]},
            ],
        },
        "evidence_refs": ["dispatch_tasks", "work_orders"],
        "suggested_followups": ["按班组拆分本期处理效率", "查看本期超时工单明细", "对比上一周期的人员完成量"],
    }


def _team_performance_payload(
    question: str,
    scope: dict[str, Any],
    dispatch_rows: list[dict[str, Any]],
    start_at: datetime,
    end_at: datetime,
) -> dict[str, Any]:
    grouped: dict[str, dict[str, Any]] = {}
    for row in dispatch_rows:
        key = str(row.get("team_id") or row.get("team_name") or "unassigned")
        target = grouped.setdefault(
            key,
            {
                "team_id": row.get("team_id"),
                "team_name": row.get("team_name") or "未分组",
                "assigned_count": 0,
                "completed_count": 0,
                "overdue_count": 0,
                "workers": set(),
            },
        )
        if _within_window(row.get("assigned_at"), start_at, end_at):
            target["assigned_count"] += 1
        if _within_window(row.get("completed_at"), start_at, end_at):
            target["completed_count"] += 1
        if _is_dispatch_overdue(row, end_at):
            target["overdue_count"] += 1
        if row.get("worker_id"):
            target["workers"].add(str(row["worker_id"]))

    rows = [
        {
            "team_id": value["team_id"],
            "team_name": value["team_name"],
            "assigned_count": value["assigned_count"],
            "completed_count": value["completed_count"],
            "overdue_count": value["overdue_count"],
            "worker_count": len(value["workers"]),
            "overdue_rate": _ratio(value["overdue_count"], max(value["assigned_count"], 1)),
        }
        for value in grouped.values()
    ]
    rows = sorted(rows, key=lambda item: (-int(item["completed_count"]), -float(item["overdue_rate"]), item["team_name"]))
    if not rows:
        return _empty_response(question, "team_performance", scope)
    leader = rows[0]
    return {
        "question": question,
        "intent": "team_performance",
        "readonly": True,
        "answer": f"{scope['date_label']}内，{leader['team_name']} 完成 {leader['completed_count']} 单，超时 {leader['overdue_count']} 单，是当前范围内完成量最高的班组。",
        "facts": {
            "scope": scope,
            "claims": _claims(
                (f"{leader['team_name']} 完成 {leader['completed_count']} 单。", ["metrics.rows[0].completed_count"]),
                (f"{leader['team_name']} 的超时率为 {round(float(leader['overdue_rate']) * 100, 1)}%。", ["metrics.rows[0].overdue_rate"]),
            ),
            "rows": rows[:10],
        },
        "metrics": {
            "summary": {
                "teams": len(rows),
                "assigned_total": sum(int(item["assigned_count"]) for item in rows),
                "completed_total": sum(int(item["completed_count"]) for item in rows),
                "overdue_total": sum(int(item["overdue_count"]) for item in rows),
            },
            "rows": rows,
        },
        "chart": {
            "type": "bar",
            "title": f"{scope['date_label']}班组处理量对比",
            "source": "work_order_insights.team_performance",
            "x": [item["team_name"] for item in rows[:6]],
            "series": [
                {"name": "完成数", "data": [item["completed_count"] for item in rows[:6]]},
                {"name": "超时数", "data": [item["overdue_count"] for item in rows[:6]]},
            ],
        },
        "evidence_refs": ["dispatch_tasks", "worker_teams"],
        "suggested_followups": ["查看超时率最高的班组明细", "按维修人员拆开班组完成量", "对比本周和上周班组效率"],
    }


def _building_hotspot_payload(
    question: str,
    scope: dict[str, Any],
    work_order_rows: list[dict[str, Any]],
    dispatch_rows: list[dict[str, Any]],
    start_at: datetime,
    end_at: datetime,
) -> dict[str, Any]:
    overdue_ids = {str(item["work_order_id"]) for item in dispatch_rows if _is_dispatch_overdue(item, end_at)}
    if scope.get("building_id"):
        grouped: dict[str, dict[str, Any]] = {}
        for row in work_order_rows:
            category = _infer_issue_category(row.get("issue_description"))
            target = grouped.setdefault(category, {"category": category, "work_order_count": 0, "overdue_count": 0})
            if _within_window(row.get("created_at"), start_at, end_at):
                target["work_order_count"] += 1
            if str(row.get("work_order_id")) in overdue_ids:
                target["overdue_count"] += 1
        rows = sorted(grouped.values(), key=lambda item: (-int(item["work_order_count"]), item["category"]))
        if not rows:
            return _empty_response(question, "building_hotspot", scope)
        top = rows[0]
        return {
            "question": question,
            "intent": "building_hotspot",
            "readonly": True,
            "answer": f"{scope['date_label']}内，{_building_label(scope.get('building_id'))} 最常见的问题类型是{top['category']}，共 {top['work_order_count']} 单。",
            "facts": {
                "scope": scope,
                "claims": _claims((f"{top['category']} 在当前楼宇内出现 {top['work_order_count']} 次。", ["metrics.rows[0].work_order_count"])),
                "rows": rows[:10],
            },
            "metrics": {"summary": {"categories": len(rows)}, "rows": rows},
            "chart": {
                "type": "bar",
                "title": f"{_building_label(scope.get('building_id'))}{scope['date_label']}问题热点",
                "source": "work_order_insights.building_hotspot",
                "x": [item["category"] for item in rows[:6]],
                "series": [{"name": "工单数", "data": [item["work_order_count"] for item in rows[:6]]}],
            },
            "evidence_refs": ["work_orders", "dispatch_tasks"],
            "suggested_followups": ["查看该楼宇超时工单明细", "按班组拆分该楼宇处理量", "对比上周同楼宇热点变化"],
        }

    grouped: dict[str, dict[str, Any]] = {}
    for row in work_order_rows:
        building_id = _normalize_building(row.get("building_id")) or str(row.get("building_id") or "未知楼宇")
        target = grouped.setdefault(
            building_id,
            {
                "building_id": building_id,
                "building_name": _building_label(building_id),
                "work_order_count": 0,
                "completed_count": 0,
                "overdue_count": 0,
                "issues": Counter(),
            },
        )
        if _within_window(row.get("created_at"), start_at, end_at):
            target["work_order_count"] += 1
        if str(row.get("status") or "") in PENDING_CLOSE_STATUSES.union(CLOSED_WORK_ORDER_STATUSES):
            target["completed_count"] += 1
        if str(row.get("work_order_id")) in overdue_ids:
            target["overdue_count"] += 1
        target["issues"][_infer_issue_category(row.get("issue_description"))] += 1

    rows = []
    for value in grouped.values():
        hotspot = value["issues"].most_common(1)[0][0] if value["issues"] else "其他问题"
        rows.append(
            {
                "building_id": value["building_id"],
                "building_name": value["building_name"],
                "work_order_count": value["work_order_count"],
                "completed_count": value["completed_count"],
                "overdue_count": value["overdue_count"],
                "top_issue_category": hotspot,
            }
        )
    rows = sorted(rows, key=lambda item: (-int(item["work_order_count"]), item["building_name"]))
    if not rows:
        return _empty_response(question, "building_hotspot", scope)
    top = rows[0]
    return {
        "question": question,
        "intent": "building_hotspot",
        "readonly": True,
        "answer": f"{scope['date_label']}内，{top['building_name']} 工单最多，共 {top['work_order_count']} 单；其中最常见的问题类型是{top['top_issue_category']}。",
        "facts": {
            "scope": scope,
            "claims": _claims((f"{top['building_name']} 工单 {top['work_order_count']} 单，为当前范围内最多。", ["metrics.rows[0].work_order_count"])),
            "rows": rows[:10],
        },
        "metrics": {"summary": {"buildings": len(rows)}, "rows": rows},
        "chart": {
            "type": "bar",
            "title": f"{scope['date_label']}楼宇热点分布",
            "source": "work_order_insights.building_hotspot",
            "x": [item["building_name"] for item in rows[:6]],
            "series": [{"name": "工单数", "data": [item["work_order_count"] for item in rows[:6]]}],
        },
        "evidence_refs": ["work_orders", "dispatch_tasks"],
        "suggested_followups": ["查看热点楼宇的超时工单", "按问题类型拆开热点楼宇", "对比上周热点变化"],
    }


def _overdue_payload(question: str, scope: dict[str, Any], dispatch_rows: list[dict[str, Any]], end_at: datetime) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    building_counter: Counter[str] = Counter()
    for row in dispatch_rows:
        if not _is_dispatch_overdue(row, end_at):
            continue
        deadline = _coerce_datetime(row.get("finish_deadline_at"))
        completed_at = _coerce_datetime(row.get("completed_at")) or end_at
        overdue_minutes = int(max((completed_at - deadline).total_seconds() // 60, 0)) if deadline else None
        building_name = _building_label(row.get("building_id"))
        building_counter[building_name] += 1
        rows.append(
            {
                "ticket_id": row.get("ticket_id"),
                "building_name": building_name,
                "worker_name": row.get("worker_name"),
                "team_name": row.get("team_name"),
                "dispatch_status": row.get("dispatch_status"),
                "overdue_minutes": overdue_minutes,
                "latest_note": row.get("latest_note"),
            }
        )
    rows = sorted(rows, key=lambda item: (-(item["overdue_minutes"] or 0), item["ticket_id"] or ""))
    if not rows:
        return _empty_response(question, "overdue_analysis", scope)
    top_building, top_count = building_counter.most_common(1)[0]
    return {
        "question": question,
        "intent": "overdue_analysis",
        "readonly": True,
        "answer": f"{scope['date_label']}内共识别 {len(rows)} 条超时派工，其中 {top_building} 最多，共 {top_count} 条。",
        "facts": {
            "scope": scope,
            "claims": _claims((f"{top_building} 的超时派工最多，共 {top_count} 条。", ["metrics.summary.overdue_total"])),
            "rows": rows[:12],
        },
        "metrics": {"summary": {"overdue_total": len(rows)}, "rows": rows},
        "chart": {
            "type": "bar",
            "title": f"{scope['date_label']}超时工单分布",
            "source": "work_order_insights.overdue_analysis",
            "x": [name for name, _ in building_counter.most_common(6)],
            "series": [{"name": "超时数", "data": [count for _, count in building_counter.most_common(6)]}],
        },
        "evidence_refs": ["dispatch_tasks"],
        "suggested_followups": ["查看超时工单明细", "按班组拆分超时情况", "对比上一周期超时率"],
    }


def _support_takeover_payload(question: str, scope: dict[str, Any], dispatch_rows: list[dict[str, Any]], hall_rows: list[dict[str, Any]]) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    team_counter: Counter[str] = Counter()
    for row in dispatch_rows:
        if str(row.get("dispatch_status") or "") != "waiting_support":
            continue
        team_name = row.get("team_name") or "未分组"
        team_counter[team_name] += 1
        rows.append(
            {
                "ticket_id": row.get("ticket_id"),
                "source": "dispatch_waiting_support",
                "team_name": team_name,
                "worker_name": row.get("worker_name"),
                "building_name": _building_label(row.get("building_id")),
                "reason": row.get("latest_note"),
            }
        )
    for row in hall_rows:
        if str(row.get("entry_type") or "") not in {"support_request", "takeover_request", "overdue_takeover"}:
            continue
        team_name = row.get("team_name") or "未分组"
        team_counter[team_name] += 1
        rows.append(
            {
                "ticket_id": row.get("ticket_id"),
                "source": str(row.get("entry_type") or "hall"),
                "team_name": team_name,
                "worker_name": row.get("worker_name"),
                "building_name": _building_label(row.get("building_id")),
                "reason": row.get("support_reason") or row.get("reason"),
            }
        )
    rows = sorted(rows, key=lambda item: (item["team_name"], item["ticket_id"] or ""))
    if not rows:
        return _empty_response(question, "support_takeover_analysis", scope)
    top_team, top_count = team_counter.most_common(1)[0]
    return {
        "question": question,
        "intent": "support_takeover_analysis",
        "readonly": True,
        "answer": f"{scope['date_label']}内共识别 {len(rows)} 条协同/接管事项，其中 {top_team} 相关事项最多，共 {top_count} 条。",
        "facts": {
            "scope": scope,
            "claims": _claims((f"{top_team} 相关协同/接管事项 {top_count} 条。", ["metrics.summary.takeover_total"])),
            "rows": rows[:12],
        },
        "metrics": {"summary": {"takeover_total": len(rows)}, "rows": rows},
        "chart": {
            "type": "bar",
            "title": f"{scope['date_label']}协同与接管分布",
            "source": "work_order_insights.support_takeover_analysis",
            "x": [name for name, _ in team_counter.most_common(6)],
            "series": [{"name": "事项数", "data": [count for _, count in team_counter.most_common(6)]}],
        },
        "evidence_refs": ["dispatch_tasks", "dispatch_hall_entries"],
        "suggested_followups": ["查看待协同工单明细", "按楼宇拆分协同量", "查看接管后是否按时完成"],
    }


def _reassign_payload(question: str, scope: dict[str, Any], dispatch_rows: list[dict[str, Any]]) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    team_counter: Counter[str] = Counter()
    for row in dispatch_rows:
        if not row.get("transfer_from_dispatch_id") and int(row.get("attempt_no") or 0) <= 1:
            continue
        team_name = row.get("team_name") or "未分组"
        team_counter[team_name] += 1
        rows.append(
            {
                "ticket_id": row.get("ticket_id"),
                "attempt_no": row.get("attempt_no"),
                "team_name": team_name,
                "worker_name": row.get("worker_name"),
                "building_name": _building_label(row.get("building_id")),
                "dispatch_status": row.get("dispatch_status"),
            }
        )
    rows = sorted(rows, key=lambda item: (-int(item["attempt_no"] or 0), item["ticket_id"] or ""))
    if not rows:
        return _empty_response(question, "reassign_analysis", scope)
    top_team, top_count = team_counter.most_common(1)[0]
    return {
        "question": question,
        "intent": "reassign_analysis",
        "readonly": True,
        "answer": f"{scope['date_label']}内共发生 {len(rows)} 次改派/重派，其中 {top_team} 相关改派最多，共 {top_count} 次。",
        "facts": {
            "scope": scope,
            "claims": _claims((f"{top_team} 相关改派 {top_count} 次。", ["metrics.summary.reassign_total"])),
            "rows": rows[:12],
        },
        "metrics": {"summary": {"reassign_total": len(rows)}, "rows": rows},
        "chart": {
            "type": "bar",
            "title": f"{scope['date_label']}改派分布",
            "source": "work_order_insights.reassign_analysis",
            "x": [name for name, _ in team_counter.most_common(6)],
            "series": [{"name": "改派次数", "data": [count for _, count in team_counter.most_common(6)]}],
        },
        "evidence_refs": ["dispatch_tasks"],
        "suggested_followups": ["查看改派原因明细", "按班组拆分改派量", "查看改派后是否完成"],
    }


def _experience_usage_payload(question: str, scope: dict[str, Any], experience_rows: list[dict[str, Any]]) -> dict[str, Any]:
    grouped: dict[str, dict[str, Any]] = {}
    for row in experience_rows:
        key = str(row.get("experience_id"))
        target = grouped.setdefault(
            key,
            {
                "experience_id": row.get("experience_id"),
                "experience_text": row.get("experience_text"),
                "source_work_order_id": row.get("source_work_order_id"),
                "usage_count": 0,
                "helpful_count": int(row.get("helpful_count") or 0),
                "latest_used_at": None,
                "is_active": bool(row.get("is_active")),
            },
        )
        target["usage_count"] += 1
        used_at = row.get("used_at")
        if target["latest_used_at"] is None or (used_at and used_at > target["latest_used_at"]):
            target["latest_used_at"] = used_at
    rows = [
        {
            "experience_id": value["experience_id"],
            "experience_text": value["experience_text"],
            "source_work_order_id": value["source_work_order_id"],
            "usage_count": value["usage_count"],
            "helpful_count": value["helpful_count"],
            "latest_used_at": _dt(value["latest_used_at"]),
            "is_active": value["is_active"],
        }
        for value in grouped.values()
    ]
    rows = sorted(rows, key=lambda item: (-int(item["usage_count"]), -int(item["helpful_count"]), item["experience_text"]))
    if not rows:
        return _empty_response(question, "experience_usage_analysis", scope)
    top = rows[0]
    return {
        "question": question,
        "intent": "experience_usage_analysis",
        "readonly": True,
        "answer": f"{scope['date_label']}内，复用最多的经验记录被使用 {top['usage_count']} 次，来源工单为 {top['source_work_order_id'] or '未记录'}。",
        "facts": {
            "scope": scope,
            "claims": _claims((f"来源工单 {top['source_work_order_id'] or top['experience_id']} 的经验被复用 {top['usage_count']} 次。", ["metrics.rows[0].usage_count"])),
            "rows": rows[:10],
        },
        "metrics": {
            "summary": {
                "experience_total": len(rows),
                "usage_total": sum(int(item["usage_count"]) for item in rows),
            },
            "rows": rows,
        },
        "chart": {
            "type": "bar",
            "title": f"{scope['date_label']}经验复用排行",
            "source": "work_order_insights.experience_usage_analysis",
            "x": [str(item["source_work_order_id"] or item["experience_id"]) for item in rows[:6]],
            "series": [{"name": "复用次数", "data": [item["usage_count"] for item in rows[:6]]}],
        },
        "evidence_refs": ["maintenance_experiences", "maintenance_experience_usage_logs"],
        "suggested_followups": ["查看最近被复用的经验", "查看哪些工单用了经验推荐", "查看低帮助率经验"],
    }


def _report_payload(
    question: str,
    scope: dict[str, Any],
    intent: str,
    work_order_rows: list[dict[str, Any]],
    dispatch_rows: list[dict[str, Any]],
    start_at: datetime,
    end_at: datetime,
) -> dict[str, Any]:
    created_count = sum(1 for row in work_order_rows if _within_window(row.get("created_at"), start_at, end_at))
    closed_count = sum(1 for row in work_order_rows if _within_window(row.get("closed_at"), start_at, end_at))
    completed_count = sum(1 for row in dispatch_rows if _within_window(row.get("completed_at"), start_at, end_at))
    overdue_count = sum(1 for row in dispatch_rows if _is_dispatch_overdue(row, end_at))
    arrive_minutes = [
        minutes
        for row in dispatch_rows
        if (minutes := _minutes_between(row.get("accepted_at") or row.get("assigned_at"), row.get("arrived_at"))) is not None
    ]
    building_counter: Counter[str] = Counter(_building_label(row.get("building_id")) for row in work_order_rows)
    worker_counter: Counter[str] = Counter(str(row.get("worker_name") or "未分配") for row in dispatch_rows if row.get("worker_name"))
    category_counter: Counter[str] = Counter(_infer_issue_category(row.get("issue_description")) for row in work_order_rows)
    trend_counter: Counter[str] = Counter()
    for row in work_order_rows:
        created_at = _coerce_datetime(row.get("created_at"))
        if created_at and start_at <= created_at < end_at:
            trend_counter[created_at.date().isoformat()] += 1
    trend_days = sorted(trend_counter.keys())
    top_building = building_counter.most_common(1)[0][0] if building_counter else "暂无"
    top_worker = worker_counter.most_common(1)[0][0] if worker_counter else "暂无"
    top_category = category_counter.most_common(1)[0][0] if category_counter else "暂无"
    return {
        "question": question,
        "intent": intent,
        "readonly": True,
        "answer": f"{scope['date_label']}运营摘要：新增工单 {created_count} 单，完成 {completed_count} 单，关闭 {closed_count} 单，超时 {overdue_count} 单，平均到场 {_average(arrive_minutes) or '--'} 分钟；热点楼宇 {top_building}，处理量最高的维修人员 {top_worker}。",
        "facts": {
            "scope": scope,
            "claims": _claims(
                (f"{scope['date_label']}内新增工单 {created_count} 单，完成 {completed_count} 单，超时 {overdue_count} 单。", ["metrics.summary.created_count", "metrics.summary.completed_count", "metrics.summary.overdue_count"]),
                (f"热点楼宇为 {top_building}，高频问题类型为 {top_category}。", ["metrics.summary.top_building", "metrics.summary.top_category"]),
            ),
            "report": {
                "top_building": top_building,
                "top_worker": top_worker,
                "top_category": top_category,
            },
        },
        "metrics": {
            "summary": {
                "created_count": created_count,
                "completed_count": completed_count,
                "closed_count": closed_count,
                "overdue_count": overdue_count,
                "avg_arrive_minutes": _average(arrive_minutes),
                "top_building": top_building,
                "top_worker": top_worker,
                "top_category": top_category,
            },
            "rows": [{"date": day, "created_count": trend_counter[day]} for day in trend_days],
        },
        "chart": {
            "type": "line",
            "title": f"{scope['date_label']}每日工单趋势",
            "source": "work_order_insights.report",
            "x": trend_days,
            "series": [{"name": "新增工单", "data": [trend_counter[day] for day in trend_days]}],
        },
        "evidence_refs": ["work_orders", "dispatch_tasks"],
        "suggested_followups": ["查看本期超时工单明细", "按班组拆分本期效率", "对比上一周期运营表现"],
    }


def _comparison_payload(
    question: str,
    scope: dict[str, Any],
    current_work_orders: list[dict[str, Any]],
    current_dispatch_rows: list[dict[str, Any]],
    previous_work_orders: list[dict[str, Any]],
    previous_dispatch_rows: list[dict[str, Any]],
    end_at: datetime,
    previous_end_at: datetime,
) -> dict[str, Any]:
    current_created = len(current_work_orders)
    previous_created = len(previous_work_orders)
    current_completed = sum(1 for row in current_dispatch_rows if row.get("completed_at"))
    previous_completed = sum(1 for row in previous_dispatch_rows if row.get("completed_at"))
    current_overdue = sum(1 for row in current_dispatch_rows if _is_dispatch_overdue(row, end_at))
    previous_overdue = sum(1 for row in previous_dispatch_rows if _is_dispatch_overdue(row, previous_end_at))
    current_arrive = _average([
        minutes
        for row in current_dispatch_rows
        if (minutes := _minutes_between(row.get("accepted_at") or row.get("assigned_at"), row.get("arrived_at"))) is not None
    ])
    previous_arrive = _average([
        minutes
        for row in previous_dispatch_rows
        if (minutes := _minutes_between(row.get("accepted_at") or row.get("assigned_at"), row.get("arrived_at"))) is not None
    ])
    previous_label = str(scope.get("comparison_previous", {}).get("label") or "上一周期")
    return {
        "question": question,
        "intent": "comparison_analysis",
        "readonly": True,
        "answer": f"{scope['date_label']}相较{previous_label}，新增工单 {current_created} 单（变化 {current_created - previous_created:+d} 单），完成 {current_completed} 单；平均到场 {current_arrive or '--'} 分钟，上一周期为 {previous_arrive or '--'} 分钟。",
        "facts": {
            "scope": scope,
            "claims": _claims(
                (f"当前周期新增工单 {current_created} 单，上一周期 {previous_created} 单。", ["chart.series[0]"]),
                (f"当前周期平均到场 {current_arrive or '--'} 分钟，上一周期 {previous_arrive or '--'} 分钟。", ["chart.series[1]"]),
            ),
        },
        "metrics": {
            "summary": {
                "current_created_count": current_created,
                "previous_created_count": previous_created,
                "current_completed_count": current_completed,
                "previous_completed_count": previous_completed,
                "current_overdue_count": current_overdue,
                "previous_overdue_count": previous_overdue,
                "current_avg_arrive_minutes": current_arrive,
                "previous_avg_arrive_minutes": previous_arrive,
            },
            "rows": [
                {"period": previous_label, "created_count": previous_created, "completed_count": previous_completed, "overdue_count": previous_overdue, "avg_arrive_minutes": previous_arrive},
                {"period": str(scope.get("date_label") or "当前周期"), "created_count": current_created, "completed_count": current_completed, "overdue_count": current_overdue, "avg_arrive_minutes": current_arrive},
            ],
        },
        "chart": {
            "type": "bar",
            "title": "两周期处理效率对比",
            "source": "work_order_insights.comparison_analysis",
            "x": [previous_label, "当前周期"],
            "series": [
                {"name": "新增工单", "data": [previous_created, current_created]},
                {"name": "平均到场分钟", "data": [previous_arrive or 0, current_arrive or 0]},
                {"name": "超时数", "data": [previous_overdue, current_overdue]},
            ],
        },
        "evidence_refs": ["work_orders", "dispatch_tasks"],
        "suggested_followups": ["查看当前周期超时工单", "按班组拆分两周期差异", "切换楼宇后重做对比"],
    }


def _maybe_drop_chart(payload: dict[str, Any], include_chart: bool) -> dict[str, Any]:
    if not include_chart:
        payload["chart"] = None
    return payload


async def build_work_order_facts_response(
    db: AsyncSession,
    *,
    question: str,
    intent: str | None = None,
    scope: dict[str, Any] | None = None,
    include_chart: bool = True,
) -> dict[str, Any]:
    resolved_scope = extract_work_order_analysis_scope(question=question, scope=scope, previous_scope=None, intent=intent)
    resolved_intent = str(resolved_scope.get("intent") or intent or "monthly_report")
    date_from = _coerce_date(resolved_scope.get("date_from")) or get_today()
    date_to = _coerce_date(resolved_scope.get("date_to")) or date_from
    start_at = datetime.combine(date_from, time.min, tzinfo=timezone.utc)
    end_at = datetime.combine(date_to + timedelta(days=1), time.min, tzinfo=timezone.utc)

    dispatch_rows = [item for item in await _load_dispatch_rows(db, start_at=start_at, end_at=end_at) if _dispatch_matches_scope(item, resolved_scope)]
    work_order_ids = {str(item["work_order_id"]) for item in dispatch_rows}
    work_order_rows = [
        item
        for item in await _load_work_order_rows(db, start_at=start_at, end_at=end_at)
        if _work_order_matches_scope(item, resolved_scope, allowed_work_order_ids=work_order_ids if (resolved_scope.get("worker_id") or resolved_scope.get("team_id")) else None)
    ]
    hall_rows = [item for item in await _load_hall_rows(db, start_at=start_at, end_at=end_at) if _dispatch_matches_scope(item, resolved_scope)]
    experience_rows = [item for item in await _load_experience_rows(db, start_at=start_at, end_at=end_at) if _experience_matches_scope(item, resolved_scope)]

    if resolved_intent == "worker_performance":
        payload = _worker_performance_payload(question, resolved_scope, dispatch_rows, start_at, end_at)
    elif resolved_intent == "team_performance" or str(resolved_scope.get("group_by")) == "team":
        payload = _team_performance_payload(question, resolved_scope, dispatch_rows, start_at, end_at)
    elif resolved_intent == "building_hotspot":
        payload = _building_hotspot_payload(question, resolved_scope, work_order_rows, dispatch_rows, start_at, end_at)
    elif resolved_intent == "overdue_analysis":
        payload = _overdue_payload(question, resolved_scope, dispatch_rows, end_at)
    elif resolved_intent == "open_work_order_analysis":
        payload = _open_work_order_payload(question, resolved_scope, work_order_rows, dispatch_rows, end_at)
    elif resolved_intent == "support_takeover_analysis":
        payload = _support_takeover_payload(question, resolved_scope, dispatch_rows, hall_rows)
    elif resolved_intent == "reassign_analysis":
        payload = _reassign_payload(question, resolved_scope, dispatch_rows)
    elif resolved_intent == "experience_usage_analysis":
        payload = _experience_usage_payload(question, resolved_scope, experience_rows)
    elif resolved_intent in {"daily_report", "weekly_report", "monthly_report"}:
        payload = _report_payload(question, resolved_scope, resolved_intent, work_order_rows, dispatch_rows, start_at, end_at)
    else:
        previous_scope = dict(resolved_scope)
        previous_range = previous_scope.get("comparison_previous") or {}
        previous_from = _coerce_date(previous_range.get("date_from")) or (date_from - timedelta(days=7))
        previous_to = _coerce_date(previous_range.get("date_to")) or (date_from - timedelta(days=1))
        previous_start_at = datetime.combine(previous_from, time.min, tzinfo=timezone.utc)
        previous_end_at = datetime.combine(previous_to + timedelta(days=1), time.min, tzinfo=timezone.utc)
        previous_scope["date_from"] = previous_from
        previous_scope["date_to"] = previous_to
        previous_dispatch_rows = [item for item in await _load_dispatch_rows(db, start_at=previous_start_at, end_at=previous_end_at) if _dispatch_matches_scope(item, previous_scope)]
        previous_work_order_ids = {str(item["work_order_id"]) for item in previous_dispatch_rows}
        previous_work_order_rows = [
            item
            for item in await _load_work_order_rows(db, start_at=previous_start_at, end_at=previous_end_at)
            if _work_order_matches_scope(item, previous_scope, allowed_work_order_ids=previous_work_order_ids if (previous_scope.get("worker_id") or previous_scope.get("team_id")) else None)
        ]
        payload = _comparison_payload(question, resolved_scope, work_order_rows, dispatch_rows, previous_work_order_rows, previous_dispatch_rows, end_at, previous_end_at)

    payload["generated_at"] = _dt(datetime.now(timezone.utc))
    payload["facts"]["scope"] = {
        **payload["facts"].get("scope", {}),
        "date_from": date_from.isoformat(),
        "date_to": date_to.isoformat(),
    }
    return _maybe_drop_chart(payload, include_chart)


async def build_work_order_report_response(
    db: AsyncSession,
    *,
    report_type: str,
    question: str | None = None,
    scope: dict[str, Any] | None = None,
    include_chart: bool = True,
) -> dict[str, Any]:
    normalized_type = (report_type or "").strip().lower()
    intent = {
        "daily": "daily_report",
        "daily_report": "daily_report",
        "weekly": "weekly_report",
        "weekly_report": "weekly_report",
        "monthly": "monthly_report",
        "monthly_report": "monthly_report",
    }.get(normalized_type, "monthly_report")
    resolved_question = question or {
        "daily_report": "生成今日日报",
        "weekly_report": "生成本周周报",
        "monthly_report": "生成本月月报",
    }[intent]
    payload = await build_work_order_facts_response(
        db,
        question=resolved_question,
        intent=intent,
        scope=scope,
        include_chart=include_chart,
    )
    payload["report_type"] = intent
    payload["report"] = {
        "title": {
            "daily_report": "运维日报",
            "weekly_report": "运维周报",
            "monthly_report": "运维月报",
        }[intent],
        "summary": payload.get("answer"),
        "claims": payload.get("facts", {}).get("claims", []),
    }
    return payload
