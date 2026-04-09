from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
import json
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import get_settings
from app.db.models import DispatchTask, User, WorkOrder, WorkOrderAuditLog, WorkerProfile

ACTIVE_DISPATCH_STATUSES = {"assigned", "accepted", "arrived", "processing", "waiting_support"}
PENDING_CLOSE_STATUSES = {"completed", "false_alarm", "escalated"}
CLOSED_WORK_ORDER_STATUSES = {"closed"}
ACTIVE_WORK_ORDER_STATUSES = {"pending_dispatch", "dispatched", *PENDING_CLOSE_STATUSES}
AUTO_DISPATCH_MODES = ("auto", "auto_fallback")
AUTO_DISPATCH_AUDIT_ACTIONS = (
    "auto_dispatch_rollout_skipped",
    "auto_dispatch_attempt_skipped",
    "auto_dispatch_hall_fallback",
)


def _count_value(rows: dict[str, int], *keys: str) -> int:
    return sum(int(rows.get(key, 0) or 0) for key in keys)


def _ratio(numerator: int, denominator: int) -> float:
    if denominator <= 0:
        return 0.0
    return round(numerator / denominator, 4)


def _minutes_between(start: datetime | None, end: datetime | None) -> float | None:
    if start is None or end is None:
        return None
    try:
        minutes = (end - start).total_seconds() / 60
    except TypeError:
        return None
    if minutes < 0:
        return None
    return minutes


def _average(values: list[float]) -> float | None:
    if not values:
        return None
    return round(sum(values) / len(values), 2)


def _dt(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _safe_json_object(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except (TypeError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _top_watchlist(metrics: dict[str, Any]) -> list[dict[str, Any]]:
    summary = metrics["summary"]
    dispatch = metrics["dispatch"]
    worker_loads = metrics["worker_loads"]
    watchlist: list[dict[str, Any]] = []

    if dispatch["overdue"] > 0:
        watchlist.append(
            {
                "level": "high",
                "code": "dispatch_overdue",
                "message": f"当前有 {dispatch['overdue']} 个派工任务已超时，建议优先催办或改派。",
            }
        )
    if dispatch["waiting_support"] > 0:
        watchlist.append(
            {
                "level": "medium",
                "code": "waiting_support",
                "message": f"当前有 {dispatch['waiting_support']} 个派工任务等待协同支援。",
            }
        )
    if summary["pending_dispatch"] > 0:
        watchlist.append(
            {
                "level": "medium",
                "code": "pending_dispatch_queue",
                "message": f"当前有 {summary['pending_dispatch']} 张工单仍在待派工队列。",
            }
        )
    if worker_loads["over_capacity"] > 0:
        watchlist.append(
            {
                "level": "medium",
                "code": "worker_over_capacity",
                "message": f"当前有 {worker_loads['over_capacity']} 名维修人员负载达到或超过上限。",
            }
        )
    if not watchlist:
        watchlist.append(
            {
                "level": "normal",
                "code": "healthy",
                "message": "当前没有发现待协同、超时或人员超载风险。",
            }
        )
    return watchlist


async def _count_work_orders_by_status(db: AsyncSession) -> dict[str, int]:
    result = await db.execute(
        select(WorkOrder.status, func.count(WorkOrder.id)).group_by(WorkOrder.status)
    )
    return {str(status or "unknown"): int(count or 0) for status, count in result.all()}


async def _count_dispatches_by_status(db: AsyncSession) -> dict[str, int]:
    result = await db.execute(
        select(DispatchTask.dispatch_status, func.count(DispatchTask.id))
        .group_by(DispatchTask.dispatch_status)
    )
    return {str(status or "unknown"): int(count or 0) for status, count in result.all()}


async def _count_current_dispatches_by_timeout(db: AsyncSession) -> dict[str, int]:
    result = await db.execute(
        select(DispatchTask.timeout_level, func.count(DispatchTask.id))
        .where(DispatchTask.is_current.is_(True))
        .group_by(DispatchTask.timeout_level)
    )
    return {str(status or "normal"): int(count or 0) for status, count in result.all()}


async def _load_duration_metrics(db: AsyncSession) -> dict[str, Any]:
    result = await db.execute(
        select(
            DispatchTask.assigned_at,
            DispatchTask.accepted_at,
            DispatchTask.arrived_at,
            DispatchTask.processing_started_at,
            DispatchTask.completed_at,
        )
        .order_by(DispatchTask.assigned_at.desc())
        .limit(5000)
    )
    accept_minutes: list[float] = []
    arrive_minutes: list[float] = []
    start_minutes: list[float] = []
    complete_minutes: list[float] = []
    sample_size = 0

    for assigned_at, accepted_at, arrived_at, processing_started_at, completed_at in result.all():
        sample_size += 1
        accept_delta = _minutes_between(assigned_at, accepted_at)
        arrive_delta = _minutes_between(accepted_at or assigned_at, arrived_at)
        start_delta = _minutes_between(arrived_at or accepted_at or assigned_at, processing_started_at)
        complete_delta = _minutes_between(assigned_at, completed_at)
        if accept_delta is not None:
            accept_minutes.append(accept_delta)
        if arrive_delta is not None:
            arrive_minutes.append(arrive_delta)
        if start_delta is not None:
            start_minutes.append(start_delta)
        if complete_delta is not None:
            complete_minutes.append(complete_delta)

    return {
        "sample_size": sample_size,
        "avg_accept_minutes": _average(accept_minutes),
        "avg_arrive_minutes": _average(arrive_minutes),
        "avg_start_minutes": _average(start_minutes),
        "avg_complete_minutes": _average(complete_minutes),
    }


async def _load_worker_loads(db: AsyncSession) -> dict[str, Any]:
    result = await db.execute(
        select(DispatchTask.assigned_to, func.count(DispatchTask.id))
        .where(
            DispatchTask.is_current.is_(True),
            DispatchTask.assigned_to.is_not(None),
            DispatchTask.dispatch_status.in_(ACTIVE_DISPATCH_STATUSES),
        )
        .group_by(DispatchTask.assigned_to)
    )
    active_counts = {str(user_id): int(count or 0) for user_id, count in result.all() if user_id}
    if not active_counts:
        return {
            "active_assignees": 0,
            "over_capacity": 0,
            "top_active": [],
        }

    users_result = await db.execute(
        select(User)
        .options(selectinload(User.worker_profile).selectinload(WorkerProfile.team))
        .where(User.id.in_(list(active_counts.keys())))
    )
    users_by_id = {item.id: item for item in users_result.scalars().all()}

    rows: list[dict[str, Any]] = []
    over_capacity = 0
    for user_id, active_orders in active_counts.items():
        user = users_by_id.get(user_id)
        profile = getattr(user, "worker_profile", None) if user else None
        max_active = int(getattr(profile, "max_active_orders", 4) or 4)
        is_over_capacity = active_orders >= max_active
        if is_over_capacity:
            over_capacity += 1
        rows.append(
            {
                "user_id": user_id,
                "username": getattr(user, "username", None) or user_id,
                "team_name": getattr(getattr(profile, "team", None), "name", None),
                "active_orders": active_orders,
                "max_active_orders": max_active,
                "capacity_ratio": _ratio(active_orders, max_active),
                "over_capacity": is_over_capacity,
            }
        )

    rows.sort(key=lambda item: (-item["active_orders"], -item["capacity_ratio"], item["username"]))
    return {
        "active_assignees": len(active_counts),
        "over_capacity": over_capacity,
        "top_active": rows[:10],
    }


async def _load_building_hotspots(db: AsyncSession) -> list[dict[str, Any]]:
    total_count = func.count(WorkOrder.id)
    result = await db.execute(
        select(WorkOrder.building_id, total_count)
        .where(WorkOrder.status.in_(ACTIVE_WORK_ORDER_STATUSES))
        .group_by(WorkOrder.building_id)
        .order_by(total_count.desc(), WorkOrder.building_id.asc())
        .limit(10)
    )
    return [
        {
            "building_id": str(building_id),
            "active_work_orders": int(count or 0),
        }
        for building_id, count in result.all()
    ]


async def _load_auto_dispatch_metrics(db: AsyncSession) -> dict[str, Any]:
    settings = get_settings()
    dispatch_mode_result = await db.execute(
        select(DispatchTask.dispatch_mode, func.count(DispatchTask.id))
        .where(DispatchTask.dispatch_mode.in_(AUTO_DISPATCH_MODES))
        .group_by(DispatchTask.dispatch_mode)
    )
    dispatch_mode_counts = {
        str(mode or "unknown"): int(count or 0)
        for mode, count in dispatch_mode_result.all()
    }
    current_mode_result = await db.execute(
        select(DispatchTask.dispatch_mode, func.count(DispatchTask.id))
        .where(
            DispatchTask.dispatch_mode.in_(AUTO_DISPATCH_MODES),
            DispatchTask.is_current.is_(True),
        )
        .group_by(DispatchTask.dispatch_mode)
    )
    current_mode_counts = {
        str(mode or "unknown"): int(count or 0)
        for mode, count in current_mode_result.all()
    }
    audit_action_result = await db.execute(
        select(WorkOrderAuditLog.action, func.count(WorkOrderAuditLog.id))
        .where(WorkOrderAuditLog.action.in_(AUTO_DISPATCH_AUDIT_ACTIONS))
        .group_by(WorkOrderAuditLog.action)
    )
    audit_action_counts = {
        str(action or "unknown"): int(count or 0)
        for action, count in audit_action_result.all()
    }
    recent_audit_result = await db.execute(
        select(
            WorkOrderAuditLog.action,
            WorkOrderAuditLog.detail_json,
            WorkOrderAuditLog.created_at,
        )
        .where(WorkOrderAuditLog.action.in_(AUTO_DISPATCH_AUDIT_ACTIONS))
        .order_by(WorkOrderAuditLog.created_at.desc())
        .limit(1000)
    )
    reason_counts: Counter[str] = Counter()
    strategy_counts: Counter[str] = Counter()
    rollout_blocker_counts: Counter[str] = Counter()
    recent_observations: list[dict[str, Any]] = []
    audit_sample_size = 0
    for action, detail_json, created_at in recent_audit_result.all():
        audit_sample_size += 1
        detail = _safe_json_object(detail_json)
        reason = detail.get("reason")
        if reason:
            reason_counts[str(reason)] += 1
        strategy = detail.get("strategy")
        if strategy:
            strategy_counts[str(strategy)] += 1

        rollout_gate = detail.get("rollout_gate") if isinstance(detail.get("rollout_gate"), dict) else {}
        for blocker in rollout_gate.get("blockers") or []:
            if isinstance(blocker, dict) and blocker.get("reason"):
                rollout_blocker_counts[str(blocker["reason"])] += 1

        if len(recent_observations) < 10:
            recent_observations.append(
                {
                    "action": str(action or "unknown"),
                    "created_at": _dt(created_at),
                    "reason": reason,
                    "strategy": strategy,
                    "message": detail.get("message"),
                }
            )

    total_auto_tasks = _count_value(dispatch_mode_counts, *AUTO_DISPATCH_MODES)
    current_auto_tasks = _count_value(current_mode_counts, *AUTO_DISPATCH_MODES)
    return {
        "enabled": settings.ENABLE_AUTO_DISPATCH_EXECUTION,
        "allow_low_confidence": (
            settings.ENABLE_AUTO_DISPATCH_FALLBACK_EXECUTION
            and settings.AUTO_DISPATCH_ALLOW_LOW_CONFIDENCE_IN_GREY
        ),
        "allow_hall_fallback": (
            settings.ENABLE_AUTO_DISPATCH_HALL_FALLBACK
            and settings.AUTO_DISPATCH_ALLOW_HALL_FALLBACK_IN_GREY
        ),
        "rules": {
            "min_score": settings.AUTO_DISPATCH_MIN_SCORE,
            "min_gap": settings.AUTO_DISPATCH_MIN_GAP,
            "require_on_duty": settings.AUTO_DISPATCH_REQUIRE_ON_DUTY,
            "fallback_min_score": settings.AUTO_DISPATCH_FALLBACK_MIN_SCORE,
            "fallback_allow_standby": settings.AUTO_DISPATCH_FALLBACK_ALLOW_STANDBY,
        },
        "rollout": {
            "allowed_buildings": settings.AUTO_DISPATCH_ALLOWED_BUILDINGS,
            "allowed_priorities": settings.AUTO_DISPATCH_ALLOWED_PRIORITIES,
            "allowed_required_skills": settings.AUTO_DISPATCH_ALLOWED_REQUIRED_SKILLS,
        },
        "tasks": {
            "total_auto": total_auto_tasks,
            "current_auto": current_auto_tasks,
            "by_mode": dispatch_mode_counts,
            "current_by_mode": current_mode_counts,
        },
        "observations": {
            "rollout_skipped": int(audit_action_counts.get("auto_dispatch_rollout_skipped", 0) or 0),
            "attempt_skipped": int(audit_action_counts.get("auto_dispatch_attempt_skipped", 0) or 0),
            "hall_fallback_created": int(audit_action_counts.get("auto_dispatch_hall_fallback", 0) or 0),
            "by_action": audit_action_counts,
            "recent_sample_size": audit_sample_size,
            "recent_reason_counts": dict(reason_counts),
            "recent_strategy_counts": dict(strategy_counts),
            "recent_rollout_blocker_counts": dict(rollout_blocker_counts),
            "recent": recent_observations,
        },
    }


async def build_work_order_insight_metrics(db: AsyncSession) -> dict[str, Any]:
    work_order_status_counts = await _count_work_orders_by_status(db)
    dispatch_status_counts = await _count_dispatches_by_status(db)
    timeout_counts = await _count_current_dispatches_by_timeout(db)
    duration_metrics = await _load_duration_metrics(db)
    worker_loads = await _load_worker_loads(db)
    building_hotspots = await _load_building_hotspots(db)
    auto_dispatch_metrics = await _load_auto_dispatch_metrics(db)

    work_orders_total = sum(work_order_status_counts.values())
    pending_close = _count_value(work_order_status_counts, *PENDING_CLOSE_STATUSES)
    current_dispatch_total = sum(timeout_counts.values())
    active_dispatch_total = _count_value(dispatch_status_counts, *ACTIVE_DISPATCH_STATUSES)
    overdue = int(timeout_counts.get("overdue", 0) or 0)
    waiting_support = int(dispatch_status_counts.get("waiting_support", 0) or 0)

    metrics = {
        "generated_at": _dt(datetime.now(timezone.utc)),
        "readonly": True,
        "summary": {
            "work_orders_total": work_orders_total,
            "pending_review": int(work_order_status_counts.get("pending_review", 0) or 0),
            "pending_dispatch": int(work_order_status_counts.get("pending_dispatch", 0) or 0),
            "auto_rejected": int(work_order_status_counts.get("auto_rejected", 0) or 0),
            "dispatched": int(work_order_status_counts.get("dispatched", 0) or 0),
            "pending_close": pending_close,
            "closed": _count_value(work_order_status_counts, *CLOSED_WORK_ORDER_STATUSES),
            "by_status": work_order_status_counts,
        },
        "dispatch": {
            "current_total": current_dispatch_total,
            "active_total": active_dispatch_total,
            "waiting_support": waiting_support,
            "warning": int(timeout_counts.get("warning", 0) or 0),
            "overdue": overdue,
            "overdue_rate": _ratio(overdue, max(current_dispatch_total, active_dispatch_total)),
            "reassigned_attempts": max(sum(dispatch_status_counts.values()) - current_dispatch_total, 0),
            "completed_attempts": int(dispatch_status_counts.get("completed", 0) or 0),
            "rejected_attempts": int(dispatch_status_counts.get("rejected", 0) or 0),
            "cancelled_attempts": int(dispatch_status_counts.get("cancelled", 0) or 0),
            "by_status": dispatch_status_counts,
            "current_by_timeout": timeout_counts,
        },
        "durations": duration_metrics,
        "worker_loads": worker_loads,
        "building_hotspots": building_hotspots,
        "auto_dispatch": auto_dispatch_metrics,
    }
    metrics["watchlist"] = _top_watchlist(metrics)
    return metrics


def infer_work_order_insight_intent(question: str) -> str:
    normalized = (question or "").strip().lower()
    if any(token in normalized for token in ("自动派工", "灰度", "自动调度", "auto dispatch", "auto-dispatch")):
        return "auto_dispatch"
    if any(token in normalized for token in ("超时", "sla", "风险", "预警", "告警")):
        return "risk"
    if any(token in normalized for token in ("人员", "维修员", "负载", "忙", "超载", "班组")):
        return "worker_load"
    if any(token in normalized for token in ("待派", "派工", "改派", "协同")):
        return "dispatch"
    if any(token in normalized for token in ("完成", "关闭", "闭环", "待关闭")):
        return "closure"
    return "summary"


def build_work_order_insight_query_response(
    *,
    question: str,
    metrics: dict[str, Any],
) -> dict[str, Any]:
    intent = infer_work_order_insight_intent(question)
    summary = metrics["summary"]
    dispatch = metrics["dispatch"]
    worker_loads = metrics["worker_loads"]
    auto_dispatch = metrics.get("auto_dispatch") or {}

    if intent == "risk":
        answer = (
            f"当前超时派工 {dispatch['overdue']} 个，临期 {dispatch['warning']} 个，"
            f"待协同 {dispatch['waiting_support']} 个。"
        )
    elif intent == "auto_dispatch":
        tasks = auto_dispatch.get("tasks") or {}
        observations = auto_dispatch.get("observations") or {}
        rules = auto_dispatch.get("rules") or {}
        answer = (
            f"自动派工执行开关当前为 {'开启' if auto_dispatch.get('enabled') else '关闭'}；"
            f"高置信阈值为 {rules.get('min_score')} 分、分差 {rules.get('min_gap')}。"
            f"已产生自动派工任务 {tasks.get('total_auto', 0)} 个，"
            f"当前有效自动派工 {tasks.get('current_auto', 0)} 个；"
            f"灰度拦截 {observations.get('rollout_skipped', 0)} 次，"
            f"自动尝试跳过 {observations.get('attempt_skipped', 0)} 次。"
        )
    elif intent == "worker_load":
        busiest = worker_loads["top_active"][0] if worker_loads["top_active"] else None
        busiest_text = (
            f"当前负载最高的是 {busiest['username']}，在手 {busiest['active_orders']} 单。"
            if busiest else
            "当前没有维修人员挂载活跃派工。"
        )
        answer = (
            f"当前有 {worker_loads['active_assignees']} 名维修人员承担活跃派工，"
            f"{worker_loads['over_capacity']} 人达到或超过负载上限。{busiest_text}"
        )
    elif intent == "dispatch":
        answer = (
            f"待派工 {summary['pending_dispatch']} 张，执行中 {summary['dispatched']} 张，"
            f"待协同 {dispatch['waiting_support']} 个，历史改派/转派尝试 {dispatch['reassigned_attempts']} 次。"
        )
    elif intent == "closure":
        answer = (
            f"待关闭 {summary['pending_close']} 张，已关闭 {summary['closed']} 张，"
            f"已完成派工尝试 {dispatch['completed_attempts']} 次。"
        )
    else:
        answer = (
            f"当前工单总数 {summary['work_orders_total']} 张："
            f"待审 {summary['pending_review']}、待派 {summary['pending_dispatch']}、"
            f"执行中 {summary['dispatched']}、待关闭 {summary['pending_close']}、已关闭 {summary['closed']}。"
        )

    return {
        "question": question,
        "intent": intent,
        "readonly": True,
        "answer": answer,
        "watchlist": metrics.get("watchlist", []),
        "metrics": metrics,
    }
