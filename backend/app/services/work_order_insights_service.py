from __future__ import annotations

from collections import Counter
from datetime import date, datetime, time, timedelta, timezone
import asyncio
import json
import logging
import re
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import get_settings
from app.db.models import (
    DispatchOperationRun,
    DispatchHallApplication,
    DispatchHallEntry,
    DispatchTask,
    User,
    WorkOrder,
    WorkOrderAuditLog,
    WorkerProfile,
    WorkerTeam,
)
from app.services.dispatch_operation_run_service import (
    DISPATCH_RUN_TRIGGER_SOURCES,
    DISPATCH_SLA_SCAN_OPERATION,
)

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
AUTO_DISPATCH_OPERATION_MODES = ("auto", "auto_fallback", "hall_fallback", "rollout_hall_fallback")
AUTO_DISPATCH_REVIEW_AUDIT_ACTIONS = (
    "auto_dispatch_reviewed",
    "auto_dispatch_needs_reassign",
)
AUTO_REASSIGN_SHADOW_AUDIT_ACTION = "auto_reassign_shadow_evaluated"
AUTO_REASSIGN_SHADOW_TRIGGER_REASONS = (
    "assigned_overdue",
    "accepted_overdue",
    "assignee_unavailable",
)
AUTO_DISPATCH_RUN_HEALTH_SOURCES = DISPATCH_RUN_TRIGGER_SOURCES
_LLM_TIMEOUT = 18
_JSON_BLOCK_RE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)
logger = logging.getLogger(__name__)


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


def _safe_json_list(raw: str | None) -> list[Any]:
    if not raw:
        return []
    try:
        data = json.loads(raw)
    except (TypeError, ValueError):
        return []
    return data if isinstance(data, list) else []


def _normalize_filter(value: str | None) -> str | None:
    normalized = (value or "").strip()
    return normalized if normalized and normalized != "all" else None


def _date_window(date_from: date | None, date_to: date | None) -> tuple[datetime, datetime]:
    now = datetime.now(timezone.utc)
    end = datetime.combine(date_to + timedelta(days=1), time.min, tzinfo=timezone.utc) if date_to else now
    start = datetime.combine(date_from, time.min, tzinfo=timezone.utc) if date_from else end - timedelta(days=7)
    if start >= end:
        start = end - timedelta(days=1)
    return start, end


def _required_skills_from_payload(*payloads: dict[str, Any]) -> list[str]:
    for payload in payloads:
        raw = payload.get("required_skills")
        if isinstance(raw, list):
            skills = [str(item).strip() for item in raw if str(item).strip()]
            if skills:
                return skills
    return []


def _dispatch_required_skills(task: DispatchTask, work_order: WorkOrder) -> list[str]:
    return _required_skills_from_payload(
        _safe_json_object(getattr(task, "dispatch_profile_snapshot_json", None)),
        _safe_json_object(getattr(work_order, "dispatch_profile_json", None)),
    )


def _hall_required_skills(entry: DispatchHallEntry, detail: dict[str, Any]) -> list[str]:
    target_skills = [str(item).strip() for item in _safe_json_list(entry.target_skill_tags_json) if str(item).strip()]
    if target_skills:
        return target_skills
    rollout_gate = detail.get("rollout_gate") if isinstance(detail.get("rollout_gate"), dict) else {}
    requirement = rollout_gate.get("requirement") if isinstance(rollout_gate.get("requirement"), dict) else {}
    return _required_skills_from_payload(requirement)


def _operation_required_skills(work_order: WorkOrder, task: DispatchTask | None) -> list[str]:
    payloads: list[dict[str, Any]] = []
    if task is not None:
        payloads.append(_safe_json_object(getattr(task, "dispatch_profile_snapshot_json", None)))
    payloads.append(_safe_json_object(getattr(work_order, "dispatch_profile_json", None)))
    return _required_skills_from_payload(*payloads)


def _matches_skill(required_skills: list[str], required_skill: str | None) -> bool:
    return required_skill is None or required_skill in set(required_skills)


def _detail_required_skills(detail: dict[str, Any]) -> list[str]:
    return _required_skills_from_payload(
        detail,
        detail.get("requirement") if isinstance(detail.get("requirement"), dict) else {},
    )


def _detail_blocker_reasons(detail: dict[str, Any]) -> list[str]:
    blockers = detail.get("blockers")
    if not isinstance(blockers, list):
        return []
    rows: list[str] = []
    for blocker in blockers:
        if isinstance(blocker, dict) and blocker.get("reason"):
            rows.append(str(blocker["reason"]))
    return rows


def _detail_rollout_blocker_reasons(detail: dict[str, Any]) -> list[str]:
    rollout_gate = detail.get("rollout_gate")
    if not isinstance(rollout_gate, dict):
        return []
    blockers = rollout_gate.get("blockers")
    if not isinstance(blockers, list):
        return []
    rows: list[str] = []
    for blocker in blockers:
        if isinstance(blocker, dict) and blocker.get("reason"):
            rows.append(str(blocker["reason"]))
    return rows


def _safe_json_int_object(raw: str | None) -> dict[str, int]:
    payload = _safe_json_object(raw)
    values: dict[str, int] = {}
    for key, value in payload.items():
        try:
            values[str(key)] = int(value or 0)
        except (TypeError, ValueError):
            continue
    return values


def _avg_int(values: list[int]) -> int | None:
    if not values:
        return None
    return int(round(sum(values) / len(values)))


def _counter_rows(counter: Counter[str], *, limit: int = 10) -> list[dict[str, Any]]:
    return [
        {"key": key, "label": key, "count": int(count)}
        for key, count in counter.most_common(limit)
    ]


def _top_counter_label(rows: list[dict[str, Any]], fallback: str = "暂无") -> str:
    if not rows:
        return fallback
    first = rows[0]
    return f"{first.get('label') or first.get('key')}（{first.get('count', 0)}）"


def _increment_dimension(counter: Counter[str], value: str | None, fallback: str) -> None:
    counter[str(value or fallback)] += 1


def _plain_text_items(value: Any, *, limit: int = 5) -> list[str]:
    if not isinstance(value, list):
        return []
    items: list[str] = []
    for item in value[:limit]:
        text = str(item).strip()
        if text:
            items.append(text[:160])
    return items


def _plain_evidence_items(value: Any, *, limit: int = 6) -> list[dict[str, str]]:
    if not isinstance(value, list):
        return []
    rows: list[dict[str, str]] = []
    for item in value[:limit]:
        if not isinstance(item, dict):
            continue
        label = str(item.get("label") or "").strip()
        item_value = str(item.get("value") or "").strip()
        if label and item_value:
            rows.append({"label": label[:80], "value": item_value[:160]})
    return rows


def _normalize_llm_explanation(payload: dict[str, Any]) -> dict[str, Any] | None:
    summary = str(payload.get("summary") or "").strip()
    if not summary:
        return None
    return {
        "summary": summary[:500],
        "findings": _plain_text_items(payload.get("findings")),
        "risks": _plain_text_items(payload.get("risks")),
        "recommendations": _plain_text_items(payload.get("recommendations")),
        "evidence": _plain_evidence_items(payload.get("evidence")),
    }


def _parse_json_object(raw: str) -> dict[str, Any] | None:
    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else None
    except json.JSONDecodeError:
        pass
    match = _JSON_BLOCK_RE.search(raw)
    if match:
        try:
            data = json.loads(match.group(1))
            return data if isinstance(data, dict) else None
        except json.JSONDecodeError:
            return None
    return None


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
            "create_hall_on_rollout_skip": settings.AUTO_DISPATCH_CREATE_HALL_ON_ROLLOUT_SKIP,
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


async def build_auto_dispatch_operation_insights(
    db: AsyncSession,
    *,
    date_from: date | None = None,
    date_to: date | None = None,
    building_id: str | None = None,
    priority: str | None = None,
    required_skill: str | None = None,
    dispatch_mode: str | None = None,
    team_id: str | None = None,
    assignee_id: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> dict[str, Any]:
    start_at, end_at = _date_window(date_from, date_to)
    building_filter = _normalize_filter(building_id)
    priority_filter = _normalize_filter(priority)
    skill_filter = _normalize_filter(required_skill)
    mode_filter = _normalize_filter(dispatch_mode)
    team_filter = _normalize_filter(team_id)
    assignee_filter = _normalize_filter(assignee_id)
    page = max(int(page or 1), 1)
    page_size = min(max(int(page_size or 20), 1), 100)

    mode_counts: Counter[str] = Counter()
    building_counts: Counter[str] = Counter()
    priority_counts: Counter[str] = Counter()
    skill_counts: Counter[str] = Counter()
    team_counts: Counter[str] = Counter()
    assignee_counts: Counter[str] = Counter()
    hall_status_counts: Counter[str] = Counter()
    hall_strategy_counts: Counter[str] = Counter()
    records: list[dict[str, Any]] = []

    should_load_tasks = mode_filter in (None, "auto", "auto_fallback")
    if should_load_tasks:
        task_query = (
            select(DispatchTask, WorkOrder, User.username, WorkerTeam.name)
            .join(WorkOrder, WorkOrder.id == DispatchTask.work_order_id)
            .outerjoin(User, User.id == DispatchTask.assigned_to)
            .outerjoin(WorkerProfile, WorkerProfile.user_id == DispatchTask.assigned_to)
            .outerjoin(WorkerTeam, WorkerTeam.id == WorkerProfile.team_id)
            .where(
                DispatchTask.dispatch_mode.in_(AUTO_DISPATCH_MODES),
                DispatchTask.created_at >= start_at,
                DispatchTask.created_at < end_at,
            )
        )
        if mode_filter:
            task_query = task_query.where(DispatchTask.dispatch_mode == mode_filter)
        if building_filter:
            task_query = task_query.where(WorkOrder.building_id == building_filter)
        if priority_filter:
            task_query = task_query.where(WorkOrder.priority == priority_filter)
        if team_filter:
            task_query = task_query.where(DispatchTask.assigned_team_id == team_filter)
        if assignee_filter:
            task_query = task_query.where(DispatchTask.assigned_to == assignee_filter)

        task_result = await db.execute(task_query.order_by(DispatchTask.created_at.desc()).limit(5000))
        for task, work_order, username, team_name in task_result.all():
            skills = _dispatch_required_skills(task, work_order)
            if not _matches_skill(skills, skill_filter):
                continue
            snapshot = _safe_json_object(task.candidate_snapshot_json)
            mode = str(task.dispatch_mode or "unknown")
            candidate = (
                snapshot.get("fallback_candidate")
                if mode == "auto_fallback"
                else snapshot.get("top_candidate")
            )
            candidate = candidate if isinstance(candidate, dict) else {}
            mode_counts[mode] += 1
            _increment_dimension(building_counts, work_order.building_id, "未标记楼宇")
            _increment_dimension(priority_counts, work_order.priority, "未标记优先级")
            for skill in skills or ["未识别技能"]:
                skill_counts[skill] += 1
            _increment_dimension(team_counts, team_name or task.assigned_team_id, "未分组")
            _increment_dimension(assignee_counts, username or task.assigned_to, "未指定")
            records.append(
                {
                    "type": "dispatch_task",
                    "mode": mode,
                    "strategy": snapshot.get("strategy") or (
                        "low_confidence_fallback_dispatch" if mode == "auto_fallback" else "high_confidence_dispatch"
                    ),
                    "confidence": snapshot.get("confidence"),
                    "ticket_id": work_order.ticket_id,
                    "work_order_id": work_order.id,
                    "dispatch_id": task.id,
                    "hall_entry_id": None,
                    "building_id": work_order.building_id,
                    "priority": work_order.priority,
                    "required_skills": skills,
                    "created_at": _dt(task.created_at),
                    "status": task.dispatch_status,
                    "assignee_id": task.assigned_to,
                    "assignee_name": username,
                    "team_id": task.assigned_team_id,
                    "team_name": team_name,
                    "score": candidate.get("score"),
                    "score_gap": snapshot.get("score_gap"),
                    "reason": task.selection_reason,
                }
            )

    should_load_hall = mode_filter in (None, "hall_fallback", "rollout_hall_fallback")
    hall_details_by_id: dict[str, dict[str, Any]] = {}
    if should_load_hall:
        hall_audit_query = (
            select(WorkOrderAuditLog.detail_json)
            .where(
                WorkOrderAuditLog.action == "auto_dispatch_hall_fallback",
                WorkOrderAuditLog.created_at >= start_at,
                WorkOrderAuditLog.created_at < end_at,
            )
            .order_by(WorkOrderAuditLog.created_at.desc())
            .limit(5000)
        )
        hall_audit_result = await db.execute(hall_audit_query)
        for (detail_json,) in hall_audit_result.all():
            detail = _safe_json_object(detail_json)
            hall_entry_id = str(detail.get("hall_entry_id") or "")
            if hall_entry_id and hall_entry_id not in hall_details_by_id:
                hall_details_by_id[hall_entry_id] = detail

    if hall_details_by_id:
        hall_query = (
            select(DispatchHallEntry, WorkOrder)
            .join(WorkOrder, WorkOrder.id == DispatchHallEntry.work_order_id)
            .where(DispatchHallEntry.id.in_(list(hall_details_by_id.keys())))
        )
        if building_filter:
            hall_query = hall_query.where(WorkOrder.building_id == building_filter)
        if priority_filter:
            hall_query = hall_query.where(WorkOrder.priority == priority_filter)

        hall_result = await db.execute(hall_query.order_by(DispatchHallEntry.created_at.desc()))
        hall_rows = hall_result.all()
        hall_entry_ids: list[str] = []
        for entry, work_order in hall_rows:
            detail = hall_details_by_id.get(entry.id, {})
            strategy = str(detail.get("strategy") or "hall_fallback")
            mode = "rollout_hall_fallback" if strategy == "rollout_hall_fallback" else "hall_fallback"
            if mode_filter and mode != mode_filter:
                continue
            target_team_ids = [str(item) for item in _safe_json_list(entry.target_team_ids_json)]
            target_user_ids = [str(item) for item in _safe_json_list(entry.target_user_ids_json)]
            if team_filter and team_filter not in {entry.assigned_team_id, *target_team_ids}:
                continue
            if assignee_filter and assignee_filter not in {entry.assigned_to, *target_user_ids}:
                continue
            skills = _hall_required_skills(entry, detail)
            if not _matches_skill(skills, skill_filter):
                continue
            hall_entry_ids.append(entry.id)
            mode_counts[mode] += 1
            hall_strategy_counts[str(strategy)] += 1
            hall_status_counts[str(entry.status or "unknown")] += 1
            _increment_dimension(building_counts, work_order.building_id, "未标记楼宇")
            _increment_dimension(priority_counts, work_order.priority, "未标记优先级")
            for skill in skills or ["未识别技能"]:
                skill_counts[skill] += 1
            _increment_dimension(team_counts, entry.assigned_team_id, "大厅待接管")
            _increment_dimension(assignee_counts, entry.assigned_to, "大厅待接管")
            records.append(
                {
                    "type": "hall_entry",
                    "mode": mode,
                    "strategy": strategy,
                    "confidence": None,
                    "ticket_id": work_order.ticket_id,
                    "work_order_id": work_order.id,
                    "dispatch_id": entry.source_dispatch_id,
                    "hall_entry_id": entry.id,
                    "building_id": work_order.building_id,
                    "priority": work_order.priority,
                    "required_skills": skills,
                    "created_at": _dt(entry.created_at),
                    "status": entry.status,
                    "assignee_id": entry.assigned_to,
                    "assignee_name": None,
                    "team_id": entry.assigned_team_id,
                    "team_name": None,
                    "score": None,
                    "score_gap": None,
                    "reason": detail.get("message") or detail.get("reason") or entry.reason,
                    "visibility_scope": entry.visibility_scope,
                    "target_skill_tags": skills,
                    "target_user_count": len(target_user_ids),
                }
            )

        application_counts: dict[str, dict[str, int]] = {}
        if hall_entry_ids:
            application_result = await db.execute(
                select(
                    DispatchHallApplication.hall_entry_id,
                    DispatchHallApplication.status,
                    func.count(DispatchHallApplication.id),
                )
                .where(DispatchHallApplication.hall_entry_id.in_(hall_entry_ids))
                .group_by(DispatchHallApplication.hall_entry_id, DispatchHallApplication.status)
            )
            for entry_id, status, count in application_result.all():
                bucket = application_counts.setdefault(
                    str(entry_id),
                    {"total": 0, "pending": 0, "approved": 0, "rejected": 0, "withdrawn": 0},
                )
                bucket[str(status or "unknown")] = int(count or 0)
                bucket["total"] += int(count or 0)
        for record in records:
            hall_entry_id = record.get("hall_entry_id")
            if hall_entry_id:
                record["application_stats"] = application_counts.get(
                    str(hall_entry_id),
                    {"total": 0, "pending": 0, "approved": 0, "rejected": 0, "withdrawn": 0},
                )

    review_counts: Counter[str] = Counter()
    if mode_filter not in ("hall_fallback", "rollout_hall_fallback"):
        review_query = (
            select(WorkOrderAuditLog.action, WorkOrder, DispatchTask)
            .join(WorkOrder, WorkOrder.id == WorkOrderAuditLog.work_order_id)
            .outerjoin(DispatchTask, DispatchTask.id == WorkOrder.current_dispatch_id)
            .where(
                WorkOrderAuditLog.action.in_(AUTO_DISPATCH_REVIEW_AUDIT_ACTIONS),
                WorkOrderAuditLog.created_at >= start_at,
                WorkOrderAuditLog.created_at < end_at,
            )
        )
        if building_filter:
            review_query = review_query.where(WorkOrder.building_id == building_filter)
        if priority_filter:
            review_query = review_query.where(WorkOrder.priority == priority_filter)
        if mode_filter in ("auto", "auto_fallback"):
            review_query = review_query.where(DispatchTask.dispatch_mode == mode_filter)
        if team_filter:
            review_query = review_query.where(DispatchTask.assigned_team_id == team_filter)
        if assignee_filter:
            review_query = review_query.where(DispatchTask.assigned_to == assignee_filter)
        review_result = await db.execute(review_query.limit(5000))
        for action, work_order, task in review_result.all():
            skills = (
                _dispatch_required_skills(task, work_order)
                if task
                else _required_skills_from_payload(_safe_json_object(work_order.dispatch_profile_json))
            )
            if _matches_skill(skills, skill_filter):
                review_counts[str(action or "unknown")] += 1

    records.sort(key=lambda item: item.get("created_at") or "", reverse=True)
    total_records = len(records)
    offset = (page - 1) * page_size
    page_records = records[offset: offset + page_size]
    direct_dispatch_total = _count_value(mode_counts, "auto", "auto_fallback")
    hall_total = _count_value(mode_counts, "hall_fallback", "rollout_hall_fallback")
    reviewed = int(review_counts.get("auto_dispatch_reviewed", 0) or 0)
    needs_reassign = int(review_counts.get("auto_dispatch_needs_reassign", 0) or 0)

    return {
        "generated_at": _dt(datetime.now(timezone.utc)),
        "readonly": True,
        "window": {
            "date_from": date_from.isoformat() if date_from else None,
            "date_to": date_to.isoformat() if date_to else None,
            "start_at": _dt(start_at),
            "end_at": _dt(end_at),
        },
        "filters": {
            "building_id": building_filter,
            "priority": priority_filter,
            "required_skill": skill_filter,
            "dispatch_mode": mode_filter,
            "team_id": team_filter,
            "assignee_id": assignee_filter,
        },
        "summary": {
            "total_events": total_records,
            "direct_dispatch_total": direct_dispatch_total,
            "high_confidence_auto": int(mode_counts.get("auto", 0) or 0),
            "low_confidence_auto_fallback": int(mode_counts.get("auto_fallback", 0) or 0),
            "hall_fallback_total": hall_total,
            "rollout_hall_fallback": int(mode_counts.get("rollout_hall_fallback", 0) or 0),
            "in_rollout_hall_fallback": int(mode_counts.get("hall_fallback", 0) or 0),
            "open_hall_fallback": int(hall_status_counts.get("open", 0) or 0),
            "reviewed": reviewed,
            "needs_reassign": needs_reassign,
            "needs_reassign_rate": _ratio(needs_reassign, max(reviewed + needs_reassign, direct_dispatch_total)),
        },
        "breakdowns": {
            "by_mode": _counter_rows(mode_counts),
            "by_building": _counter_rows(building_counts),
            "by_priority": _counter_rows(priority_counts),
            "by_skill": _counter_rows(skill_counts),
            "by_team": _counter_rows(team_counts),
            "by_assignee": _counter_rows(assignee_counts),
            "hall_by_status": _counter_rows(hall_status_counts),
            "hall_by_strategy": _counter_rows(hall_strategy_counts),
            "review_by_status": _counter_rows(review_counts),
        },
        "records": page_records,
        "pagination": {
            "page": page,
            "page_size": page_size,
            "total": total_records,
        },
    }


async def build_work_order_operation_insights(
    db: AsyncSession,
    *,
    date_from: date | None = None,
    date_to: date | None = None,
    building_id: str | None = None,
    priority: str | None = None,
    required_skill: str | None = None,
    status: str | None = None,
    dispatch_status: str | None = None,
    timeout_level: str | None = None,
    team_id: str | None = None,
    assignee_id: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> dict[str, Any]:
    start_at, end_at = _date_window(date_from, date_to)
    building_filter = _normalize_filter(building_id)
    priority_filter = _normalize_filter(priority)
    skill_filter = _normalize_filter(required_skill)
    status_filter = _normalize_filter(status)
    dispatch_status_filter = _normalize_filter(dispatch_status)
    timeout_filter = _normalize_filter(timeout_level)
    team_filter = _normalize_filter(team_id)
    assignee_filter = _normalize_filter(assignee_id)
    page = max(int(page or 1), 1)
    page_size = min(max(int(page_size or 20), 1), 100)

    query = (
        select(WorkOrder, DispatchTask, User.username, WorkerTeam.name)
        .outerjoin(DispatchTask, DispatchTask.id == WorkOrder.current_dispatch_id)
        .outerjoin(User, User.id == DispatchTask.assigned_to)
        .outerjoin(WorkerTeam, WorkerTeam.id == DispatchTask.assigned_team_id)
        .where(
            WorkOrder.created_at >= start_at,
            WorkOrder.created_at < end_at,
        )
    )
    if building_filter:
        query = query.where(WorkOrder.building_id == building_filter)
    if priority_filter:
        query = query.where(WorkOrder.priority == priority_filter)
    if status_filter:
        query = query.where(WorkOrder.status == status_filter)
    if dispatch_status_filter:
        query = query.where(DispatchTask.dispatch_status == dispatch_status_filter)
    if timeout_filter:
        query = query.where(DispatchTask.timeout_level == timeout_filter)
    if team_filter:
        query = query.where(DispatchTask.assigned_team_id == team_filter)
    if assignee_filter:
        query = query.where(DispatchTask.assigned_to == assignee_filter)

    result = await db.execute(query.order_by(WorkOrder.created_at.desc()).limit(5000))

    status_counts: Counter[str] = Counter()
    approval_counts: Counter[str] = Counter()
    dispatch_summary_counts: Counter[str] = Counter()
    work_result_counts: Counter[str] = Counter()
    dispatch_status_counts: Counter[str] = Counter()
    timeout_counts: Counter[str] = Counter()
    priority_counts: Counter[str] = Counter()
    building_counts: Counter[str] = Counter()
    skill_counts: Counter[str] = Counter()
    team_counts: Counter[str] = Counter()
    assignee_counts: Counter[str] = Counter()
    day_counts: Counter[str] = Counter()
    team_stats: dict[str, dict[str, Any]] = {}
    assignee_stats: dict[str, dict[str, Any]] = {}
    building_stats: dict[str, dict[str, Any]] = {}
    accept_minutes: list[float] = []
    arrive_minutes: list[float] = []
    complete_minutes: list[float] = []
    records: list[dict[str, Any]] = []

    for work_order, task, username, team_name in result.all():
        skills = _operation_required_skills(work_order, task)
        if not _matches_skill(skills, skill_filter):
            continue

        work_order_status = str(work_order.status or "unknown")
        dispatch_status_value = str(getattr(task, "dispatch_status", None) or "not_dispatched")
        timeout_value = str(getattr(task, "timeout_level", None) or "none")
        team_key = str(getattr(task, "assigned_team_id", None) or "unassigned")
        team_label = str(team_name or getattr(task, "assigned_team_id", None) or "未分组")
        assignee_key = str(getattr(task, "assigned_to", None) or "unassigned")
        assignee_label = str(username or getattr(task, "assigned_to", None) or "未指定")
        building_key = str(work_order.building_id or "unknown")
        created_day = work_order.created_at.date().isoformat() if work_order.created_at else "unknown"
        is_active_work_order = work_order_status in ACTIVE_WORK_ORDER_STATUSES
        is_completed = work_order_status in {"completed", "closed"}
        is_closed = work_order_status in CLOSED_WORK_ORDER_STATUSES
        is_pending_close = work_order_status in PENDING_CLOSE_STATUSES
        is_overdue = timeout_value == "overdue"

        status_counts[work_order_status] += 1
        _increment_dimension(approval_counts, work_order.approval_status, "未标记审批")
        _increment_dimension(dispatch_summary_counts, work_order.dispatch_summary_status, "未标记派工")
        _increment_dimension(work_result_counts, work_order.work_result, "未标记结果")
        dispatch_status_counts[dispatch_status_value] += 1
        timeout_counts[timeout_value] += 1
        _increment_dimension(priority_counts, work_order.priority, "未标记优先级")
        _increment_dimension(building_counts, work_order.building_id, "未标记楼宇")
        for skill in skills or ["未识别技能"]:
            skill_counts[skill] += 1
        team_counts[team_label] += 1
        assignee_counts[assignee_label] += 1
        day_counts[created_day] += 1

        team_row = team_stats.setdefault(
            team_key,
            {
                "team_id": None if team_key == "unassigned" else team_key,
                "team_name": team_label,
                "total_work_orders": 0,
                "active_work_orders": 0,
                "completed_work_orders": 0,
                "closed_work_orders": 0,
                "overdue_dispatches": 0,
            },
        )
        team_row["total_work_orders"] += 1
        team_row["active_work_orders"] += 1 if is_active_work_order else 0
        team_row["completed_work_orders"] += 1 if is_completed else 0
        team_row["closed_work_orders"] += 1 if is_closed else 0
        team_row["overdue_dispatches"] += 1 if is_overdue else 0

        assignee_row = assignee_stats.setdefault(
            assignee_key,
            {
                "assignee_id": None if assignee_key == "unassigned" else assignee_key,
                "assignee_name": assignee_label,
                "total_work_orders": 0,
                "active_work_orders": 0,
                "completed_work_orders": 0,
                "overdue_dispatches": 0,
            },
        )
        assignee_row["total_work_orders"] += 1
        assignee_row["active_work_orders"] += 1 if is_active_work_order else 0
        assignee_row["completed_work_orders"] += 1 if is_completed else 0
        assignee_row["overdue_dispatches"] += 1 if is_overdue else 0

        building_row = building_stats.setdefault(
            building_key,
            {
                "building_id": building_key,
                "total_work_orders": 0,
                "active_work_orders": 0,
                "pending_dispatch": 0,
                "overdue_dispatches": 0,
                "closed_work_orders": 0,
            },
        )
        building_row["total_work_orders"] += 1
        building_row["active_work_orders"] += 1 if is_active_work_order else 0
        building_row["pending_dispatch"] += 1 if work_order_status == "pending_dispatch" else 0
        building_row["overdue_dispatches"] += 1 if is_overdue else 0
        building_row["closed_work_orders"] += 1 if is_closed else 0

        if task is not None:
            accept_delta = _minutes_between(task.assigned_at, task.accepted_at)
            arrive_delta = _minutes_between(task.accepted_at or task.assigned_at, task.arrived_at)
            complete_delta = _minutes_between(task.assigned_at, task.completed_at)
            if accept_delta is not None:
                accept_minutes.append(accept_delta)
            if arrive_delta is not None:
                arrive_minutes.append(arrive_delta)
            if complete_delta is not None:
                complete_minutes.append(complete_delta)

        records.append(
            {
                "ticket_id": work_order.ticket_id,
                "work_order_id": work_order.id,
                "building_id": work_order.building_id,
                "priority": work_order.priority,
                "required_skills": skills,
                "status": work_order_status,
                "approval_status": work_order.approval_status,
                "dispatch_summary_status": work_order.dispatch_summary_status,
                "work_result": work_order.work_result,
                "issue_description": work_order.issue_description,
                "created_at": _dt(work_order.created_at),
                "updated_at": _dt(work_order.updated_at),
                "closed_at": _dt(work_order.closed_at),
                "current_dispatch_id": getattr(task, "id", None),
                "current_dispatch_status": dispatch_status_value,
                "timeout_level": timeout_value,
                "assignee_id": getattr(task, "assigned_to", None),
                "assignee_name": username,
                "team_id": getattr(task, "assigned_team_id", None),
                "team_name": team_name,
                "is_active_work_order": is_active_work_order,
                "is_pending_close": is_pending_close,
                "is_overdue": is_overdue,
            }
        )

    total_records = len(records)
    offset = (page - 1) * page_size
    page_records = records[offset: offset + page_size]
    active_total = _count_value(status_counts, *ACTIVE_WORK_ORDER_STATUSES)
    pending_close_total = _count_value(status_counts, *PENDING_CLOSE_STATUSES)
    closed_total = _count_value(status_counts, *CLOSED_WORK_ORDER_STATUSES)
    completed_total = _count_value(status_counts, "completed", "closed")
    overdue_total = int(timeout_counts.get("overdue", 0) or 0)
    warning_total = int(timeout_counts.get("warning", 0) or 0)
    waiting_support_total = int(dispatch_status_counts.get("waiting_support", 0) or 0)

    watchlist: list[dict[str, Any]] = []
    if overdue_total:
        watchlist.append({"level": "high", "code": "overdue", "message": f"当前筛选内有 {overdue_total} 个当前派工已超时。"})
    if int(status_counts.get("pending_dispatch", 0) or 0):
        watchlist.append({"level": "medium", "code": "pending_dispatch", "message": f"当前筛选内有 {int(status_counts.get('pending_dispatch', 0) or 0)} 张工单待派工。"})
    if waiting_support_total:
        watchlist.append({"level": "medium", "code": "waiting_support", "message": f"当前筛选内有 {waiting_support_total} 个派工等待协同。"})
    if not watchlist:
        watchlist.append({"level": "normal", "code": "normal", "message": "当前筛选内没有明显超时、待派工或待协同堆积。"})

    return {
        "generated_at": _dt(datetime.now(timezone.utc)),
        "readonly": True,
        "window": {
            "date_from": date_from.isoformat() if date_from else None,
            "date_to": date_to.isoformat() if date_to else None,
            "start_at": _dt(start_at),
            "end_at": _dt(end_at),
            "basis": "work_order.created_at",
        },
        "filters": {
            "building_id": building_filter,
            "priority": priority_filter,
            "required_skill": skill_filter,
            "status": status_filter,
            "dispatch_status": dispatch_status_filter,
            "timeout_level": timeout_filter,
            "team_id": team_filter,
            "assignee_id": assignee_filter,
        },
        "summary": {
            "total_work_orders": total_records,
            "active_work_orders": active_total,
            "pending_review": int(status_counts.get("pending_review", 0) or 0),
            "pending_dispatch": int(status_counts.get("pending_dispatch", 0) or 0),
            "dispatched": int(status_counts.get("dispatched", 0) or 0),
            "pending_close": pending_close_total,
            "closed": closed_total,
            "completed_or_closed": completed_total,
            "completion_rate": _ratio(completed_total, total_records),
            "close_rate": _ratio(closed_total, total_records),
            "warning_dispatches": warning_total,
            "overdue_dispatches": overdue_total,
            "waiting_support_dispatches": waiting_support_total,
            "avg_accept_minutes": _average(accept_minutes),
            "avg_arrive_minutes": _average(arrive_minutes),
            "avg_complete_minutes": _average(complete_minutes),
        },
        "breakdowns": {
            "by_status": _counter_rows(status_counts),
            "by_approval_status": _counter_rows(approval_counts),
            "by_dispatch_summary_status": _counter_rows(dispatch_summary_counts),
            "by_work_result": _counter_rows(work_result_counts),
            "by_dispatch_status": _counter_rows(dispatch_status_counts),
            "by_timeout": _counter_rows(timeout_counts),
            "by_priority": _counter_rows(priority_counts),
            "by_building": _counter_rows(building_counts),
            "by_skill": _counter_rows(skill_counts),
            "by_team": _counter_rows(team_counts),
            "by_assignee": _counter_rows(assignee_counts),
            "by_day": _counter_rows(day_counts, limit=14),
        },
        "team_efficiency": sorted(
            team_stats.values(),
            key=lambda item: (-int(item["active_work_orders"]), -int(item["overdue_dispatches"]), item["team_name"]),
        )[:10],
        "worker_loads": sorted(
            assignee_stats.values(),
            key=lambda item: (-int(item["active_work_orders"]), -int(item["overdue_dispatches"]), item["assignee_name"]),
        )[:10],
        "building_hotspots": sorted(
            building_stats.values(),
            key=lambda item: (-int(item["active_work_orders"]), -int(item["overdue_dispatches"]), item["building_id"]),
        )[:10],
        "watchlist": watchlist,
        "records": page_records,
        "pagination": {
            "page": page,
            "page_size": page_size,
            "total": total_records,
        },
    }


async def build_auto_reassign_shadow_insights(
    db: AsyncSession,
    *,
    date_from: date | None = None,
    date_to: date | None = None,
    building_id: str | None = None,
    priority: str | None = None,
    required_skill: str | None = None,
    trigger_reason: str | None = None,
    eligible: bool | None = None,
    current_dispatch_status: str | None = None,
    team_id: str | None = None,
    assignee_id: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> dict[str, Any]:
    settings = get_settings()
    start_at, end_at = _date_window(date_from, date_to)
    building_filter = _normalize_filter(building_id)
    priority_filter = _normalize_filter(priority)
    skill_filter = _normalize_filter(required_skill)
    trigger_filter = _normalize_filter(trigger_reason)
    status_filter = _normalize_filter(current_dispatch_status)
    team_filter = _normalize_filter(team_id)
    assignee_filter = _normalize_filter(assignee_id)
    page = max(int(page or 1), 1)
    page_size = min(max(int(page_size or 20), 1), 100)

    trigger_counts: Counter[str] = Counter()
    building_counts: Counter[str] = Counter()
    priority_counts: Counter[str] = Counter()
    skill_counts: Counter[str] = Counter()
    status_counts: Counter[str] = Counter()
    team_counts: Counter[str] = Counter()
    assignee_counts: Counter[str] = Counter()
    decision_counts: Counter[str] = Counter()
    blocker_counts: Counter[str] = Counter()
    rollout_status_counts: Counter[str] = Counter()
    rollout_blocker_counts: Counter[str] = Counter()
    records: list[dict[str, Any]] = []
    unique_work_order_ids: set[str] = set()
    unique_dispatch_ids: set[str] = set()
    eligible_total = 0
    would_execute_total = 0
    would_hall_fallback_total = 0
    in_rollout_total = 0
    out_of_rollout_total = 0
    would_execute_in_rollout_total = 0

    query = (
        select(WorkOrderAuditLog, WorkOrder)
        .join(WorkOrder, WorkOrder.id == WorkOrderAuditLog.work_order_id)
        .where(
            WorkOrderAuditLog.action == AUTO_REASSIGN_SHADOW_AUDIT_ACTION,
            WorkOrderAuditLog.created_at >= start_at,
            WorkOrderAuditLog.created_at < end_at,
        )
    )
    if building_filter:
        query = query.where(WorkOrder.building_id == building_filter)
    if priority_filter:
        query = query.where(WorkOrder.priority == priority_filter)

    result = await db.execute(query.order_by(WorkOrderAuditLog.created_at.desc()).limit(5000))
    for audit_log, work_order in result.all():
        detail = _safe_json_object(audit_log.detail_json)
        skills = _detail_required_skills(detail)
        blockers = _detail_blocker_reasons(detail)
        rollout_blockers = _detail_rollout_blocker_reasons(detail)
        detail_trigger = str(detail.get("trigger_reason") or "unknown")
        detail_status = str(detail.get("current_dispatch_status") or "unknown")
        detail_team_id = str(detail.get("current_assignee_team_id") or "") or None
        detail_assignee_id = str(detail.get("current_assigned_to") or "") or None
        detail_eligible = detail.get("eligible")
        within_live_rollout = detail.get("within_live_rollout")
        if trigger_filter and detail_trigger != trigger_filter:
            continue
        if status_filter and detail_status != status_filter:
            continue
        if team_filter and detail_team_id != team_filter:
            continue
        if assignee_filter and detail_assignee_id != assignee_filter:
            continue
        if skill_filter and not _matches_skill(skills, skill_filter):
            continue
        if eligible is not None:
            if not isinstance(detail_eligible, bool) or detail_eligible is not eligible:
                continue

        unique_work_order_ids.add(work_order.id)
        dispatch_id = str(detail.get("current_dispatch_id") or "") or None
        if dispatch_id:
            unique_dispatch_ids.add(dispatch_id)

        would_execute = bool(detail.get("would_execute"))
        would_hall_fallback = bool(detail.get("would_hall_fallback"))
        if detail_eligible is True:
            eligible_total += 1
        if would_execute:
            would_execute_total += 1
        if would_hall_fallback:
            would_hall_fallback_total += 1
        if within_live_rollout is True:
            in_rollout_total += 1
        elif within_live_rollout is False:
            out_of_rollout_total += 1
        if detail.get("would_execute_in_rollout"):
            would_execute_in_rollout_total += 1

        trigger_counts[detail_trigger] += 1
        _increment_dimension(building_counts, work_order.building_id, "未标记楼宇")
        _increment_dimension(priority_counts, work_order.priority, "未标记优先级")
        _increment_dimension(status_counts, detail_status, "未标记阶段")
        _increment_dimension(
            team_counts,
            detail.get("current_assignee_team_name") or detail_team_id,
            "未分组",
        )
        _increment_dimension(
            assignee_counts,
            detail.get("current_assignee_name") or detail_assignee_id,
            "未指定",
        )
        _increment_dimension(decision_counts, detail.get("decision"), "未判定")
        _increment_dimension(
            rollout_status_counts,
            "in_rollout" if within_live_rollout is True else ("out_of_rollout" if within_live_rollout is False else None),
            "未标记",
        )
        for skill in skills or ["未识别技能"]:
            skill_counts[skill] += 1
        for blocker in blockers:
            blocker_counts[blocker] += 1
        for blocker in rollout_blockers:
            rollout_blocker_counts[blocker] += 1

        records.append(
            {
                "ticket_id": work_order.ticket_id,
                "work_order_id": work_order.id,
                "building_id": work_order.building_id,
                "priority": work_order.priority,
                "created_at": _dt(audit_log.created_at),
                "trigger_reason": detail_trigger,
                "trigger_label": detail.get("trigger_label"),
                "assignee_unavailable_reason": detail.get("assignee_unavailable_reason"),
                "current_dispatch_id": dispatch_id,
                "current_dispatch_status": detail_status,
                "current_timeout_level": detail.get("current_timeout_level"),
                "due_at": detail.get("due_at"),
                "assignee_id": detail_assignee_id,
                "assignee_name": detail.get("current_assignee_name"),
                "team_id": detail_team_id,
                "team_name": detail.get("current_assignee_team_name"),
                "required_skills": skills,
                "eligible": bool(detail_eligible),
                "decision": detail.get("decision"),
                "candidate_count": detail.get("candidate_count"),
                "top_candidate": detail.get("top_candidate"),
                "second_candidate": detail.get("second_candidate"),
                "score_gap": detail.get("score_gap"),
                "blocker_reasons": blockers,
                "rollout_blocker_reasons": rollout_blockers,
                "selection_reason": detail.get("selection_reason"),
                "within_live_rollout": within_live_rollout,
                "would_execute": would_execute,
                "would_execute_in_rollout": bool(detail.get("would_execute_in_rollout")),
                "would_hall_fallback": would_hall_fallback,
            }
        )

    records.sort(key=lambda item: item.get("created_at") or "", reverse=True)
    total_records = len(records)
    offset = (page - 1) * page_size
    page_records = records[offset: offset + page_size]

    return {
        "generated_at": _dt(datetime.now(timezone.utc)),
        "readonly": True,
        "settings": {
            "phase1_trigger_enabled": settings.ENABLE_AUTO_REASSIGN_PHASE1_TRIGGER,
            "shadow_enabled": (
                settings.ENABLE_AUTO_REASSIGN_PHASE1_TRIGGER
                and settings.ENABLE_AUTO_REASSIGN_SHADOW_MODE
            ),
            "execution_enabled": (
                settings.ENABLE_AUTO_REASSIGN_PHASE1_TRIGGER
                and settings.ENABLE_AUTO_REASSIGN_EXECUTION
            ),
            "rollout": {
                "allowed_buildings": settings.AUTO_REASSIGN_ALLOWED_BUILDINGS,
                "allowed_priorities": settings.AUTO_REASSIGN_ALLOWED_PRIORITIES,
                "allowed_required_skills": settings.AUTO_REASSIGN_ALLOWED_REQUIRED_SKILLS,
            },
            "rules": {
                "min_score": settings.AUTO_REASSIGN_MIN_SCORE,
                "min_gap": settings.AUTO_REASSIGN_MIN_GAP,
                "require_on_duty": settings.AUTO_REASSIGN_REQUIRE_ON_DUTY,
                "require_overdue": settings.AUTO_REASSIGN_REQUIRE_OVERDUE,
                "max_attempt_no": settings.AUTO_REASSIGN_MAX_ATTEMPT_NO,
            },
            "trigger_scope": {
                "assigned_overdue": settings.AUTO_REASSIGN_TRIGGER_ASSIGNED_OVERDUE,
                "accepted_overdue": settings.AUTO_REASSIGN_TRIGGER_ACCEPTED_OVERDUE,
                "accepted_min_previous_reminders": settings.AUTO_REASSIGN_ACCEPTED_MIN_PREVIOUS_REMINDERS,
                "assignee_unavailable": settings.AUTO_REASSIGN_TRIGGER_ASSIGNEE_UNAVAILABLE,
            },
        },
        "window": {
            "date_from": date_from.isoformat() if date_from else None,
            "date_to": date_to.isoformat() if date_to else None,
            "start_at": _dt(start_at),
            "end_at": _dt(end_at),
        },
        "filters": {
            "building_id": building_filter,
            "priority": priority_filter,
            "required_skill": skill_filter,
            "trigger_reason": trigger_filter,
            "eligible": eligible,
            "current_dispatch_status": status_filter,
            "team_id": team_filter,
            "assignee_id": assignee_filter,
        },
        "summary": {
            "total_evaluations": total_records,
            "unique_work_orders": len(unique_work_order_ids),
            "unique_dispatches": len(unique_dispatch_ids),
            "eligible_total": eligible_total,
            "blocked_total": max(total_records - eligible_total, 0),
            "would_execute_total": would_execute_total,
            "would_hall_fallback_total": would_hall_fallback_total,
            "in_rollout_total": in_rollout_total,
            "out_of_rollout_total": out_of_rollout_total,
            "would_execute_in_rollout_total": would_execute_in_rollout_total,
            "eligible_rate": _ratio(eligible_total, total_records),
            "would_execute_rate": _ratio(would_execute_total, total_records),
        },
        "breakdowns": {
            "by_trigger": _counter_rows(trigger_counts),
            "by_building": _counter_rows(building_counts),
            "by_priority": _counter_rows(priority_counts),
            "by_skill": _counter_rows(skill_counts),
            "by_status": _counter_rows(status_counts),
            "by_team": _counter_rows(team_counts),
            "by_assignee": _counter_rows(assignee_counts),
            "by_decision": _counter_rows(decision_counts),
            "by_blocker": _counter_rows(blocker_counts),
            "by_rollout_status": _counter_rows(rollout_status_counts),
            "by_rollout_blocker": _counter_rows(rollout_blocker_counts),
        },
        "records": page_records,
        "pagination": {
            "page": page,
            "page_size": page_size,
            "total": total_records,
        },
    }


async def build_auto_dispatch_run_health_insights(
    db: AsyncSession,
    *,
    date_from: date | None = None,
    date_to: date | None = None,
    trigger_source: str | None = None,
    slow_threshold_ms: int = 8000,
    recent_limit: int = 12,
    slow_limit: int = 10,
) -> dict[str, Any]:
    start_at, end_at = _date_window(date_from, date_to)
    source_filter = _normalize_filter(trigger_source)
    slow_threshold = max(int(slow_threshold_ms or 8000), 1000)
    recent_limit = min(max(int(recent_limit or 12), 1), 50)
    slow_limit = min(max(int(slow_limit or 10), 1), 50)

    query = (
        select(DispatchOperationRun)
        .where(
            DispatchOperationRun.operation_type == DISPATCH_SLA_SCAN_OPERATION,
            DispatchOperationRun.started_at >= start_at,
            DispatchOperationRun.started_at < end_at,
        )
        .order_by(DispatchOperationRun.started_at.desc())
        .limit(5000)
    )
    if source_filter:
        query = query.where(DispatchOperationRun.trigger_source == source_filter)

    result = await db.execute(query)
    runs = list(result.scalars().all())

    source_counts: Counter[str] = Counter()
    status_counts: Counter[str] = Counter()
    timing_totals: Counter[str] = Counter()
    daily_rows: dict[str, dict[str, Any]] = {}
    recent_runs: list[dict[str, Any]] = []
    slow_runs: list[dict[str, Any]] = []

    success_runs = 0
    failed_runs = 0
    slow_runs_count = 0
    duration_values: list[int] = []
    success_duration_values: list[int] = []
    success_records: list[dict[str, Any]] = []

    for run in runs:
        source_counts[str(run.trigger_source or "unknown")] += 1
        status_counts[str(run.run_status or "unknown")] += 1
        is_success = str(run.run_status or "") == "success"
        is_slow = int(run.duration_ms or 0) >= slow_threshold
        timings = _safe_json_int_object(run.timings_json)

        if is_success:
            success_runs += 1
            success_duration_values.append(int(run.duration_ms or 0))
        else:
            failed_runs += 1
        if is_slow:
            slow_runs_count += 1

        duration_values.append(int(run.duration_ms or 0))
        for key, value in timings.items():
            if key == "total":
                continue
            timing_totals[key] += int(value or 0)

        started_at_value = getattr(run, "started_at", None)
        day_key = started_at_value.astimezone(timezone.utc).date().isoformat() if started_at_value else "unknown"
        day_row = daily_rows.setdefault(
            day_key,
            {
                "day": day_key,
                "run_count": 0,
                "success_count": 0,
                "failed_count": 0,
                "duration_values": [],
                "slow_run_count": 0,
                "scanned_values": [],
                "trigger_values": [],
                "overdue_values": [],
            },
        )
        day_row["run_count"] += 1
        day_row["duration_values"].append(int(run.duration_ms or 0))
        day_row["scanned_values"].append(int(run.scanned_count or 0))
        day_row["trigger_values"].append(int(run.auto_reassign_triggers or 0))
        day_row["overdue_values"].append(int(run.overdue_events or 0))
        if is_success:
            day_row["success_count"] += 1
        else:
            day_row["failed_count"] += 1
        if is_slow:
            day_row["slow_run_count"] += 1

        record = {
            "id": run.id,
            "trigger_source": run.trigger_source,
            "run_status": run.run_status,
            "started_at": _dt(run.started_at),
            "finished_at": _dt(run.finished_at),
            "duration_ms": int(run.duration_ms or 0),
            "scanned_count": int(run.scanned_count or 0),
            "updated_count": int(run.updated_count or 0),
            "warning_events": int(run.warning_events or 0),
            "overdue_events": int(run.overdue_events or 0),
            "auto_reassign_triggers": int(run.auto_reassign_triggers or 0),
            "auto_reassign_executed": int(run.auto_reassign_executed or 0),
            "auto_reassign_hall_fallbacks": int(run.auto_reassign_hall_fallbacks or 0),
            "auto_reassign_shadow_evaluated": int(run.auto_reassign_shadow_evaluated or 0),
            "auto_reassign_shadow_would_execute": int(run.auto_reassign_shadow_would_execute or 0),
            "auto_reassign_shadow_would_hall_fallbacks": int(run.auto_reassign_shadow_would_hall_fallbacks or 0),
            "timings_ms": timings,
            "error_message": run.error_message,
            "is_slow": is_slow,
        }
        if len(recent_runs) < recent_limit:
            recent_runs.append(record)
        if is_slow:
            slow_runs.append(record)
        if is_success:
            success_records.append(record)

    slow_runs.sort(key=lambda item: (-(item.get("duration_ms") or 0), item.get("started_at") or ""))
    timing_total_ms = sum(timing_totals.values())
    timing_share_rows = []
    for key, total_ms in timing_totals.most_common():
        timing_share_rows.append(
            {
                "key": key,
                "label": key,
                "total_ms": int(total_ms),
                "avg_ms": int(round(total_ms / max(success_runs, 1))),
                "share": round((total_ms / timing_total_ms), 4) if timing_total_ms else 0.0,
            }
        )

    daily_trend = []
    for item in sorted(daily_rows.values(), key=lambda row: row["day"]):
        daily_trend.append(
            {
                "day": item["day"],
                "run_count": item["run_count"],
                "success_count": item["success_count"],
                "failed_count": item["failed_count"],
                "slow_run_count": item["slow_run_count"],
                "avg_duration_ms": _avg_int(item["duration_values"]),
                "avg_scanned_count": _avg_int(item["scanned_values"]),
                "avg_auto_reassign_triggers": _avg_int(item["trigger_values"]),
                "avg_overdue_events": _avg_int(item["overdue_values"]),
            }
        )

    slow_success = [item for item in success_records if item["is_slow"]]
    normal_success = [item for item in success_records if not item["is_slow"]]
    slow_avg_triggers = _avg_int([int(item["auto_reassign_triggers"] or 0) for item in slow_success])
    normal_avg_triggers = _avg_int([int(item["auto_reassign_triggers"] or 0) for item in normal_success])
    slow_avg_scanned = _avg_int([int(item["scanned_count"] or 0) for item in slow_success])
    normal_avg_scanned = _avg_int([int(item["scanned_count"] or 0) for item in normal_success])
    slow_avg_overdue = _avg_int([int(item["overdue_events"] or 0) for item in slow_success])
    normal_avg_overdue = _avg_int([int(item["overdue_events"] or 0) for item in normal_success])

    return {
        "generated_at": _dt(datetime.now(timezone.utc)),
        "readonly": True,
        "window": {
            "date_from": date_from.isoformat() if date_from else None,
            "date_to": date_to.isoformat() if date_to else None,
            "start_at": _dt(start_at),
            "end_at": _dt(end_at),
        },
        "filters": {
            "trigger_source": source_filter,
            "slow_threshold_ms": slow_threshold,
            "recent_limit": recent_limit,
            "slow_limit": slow_limit,
        },
        "summary": {
            "total_runs": len(runs),
            "success_runs": success_runs,
            "failed_runs": failed_runs,
            "slow_runs": slow_runs_count,
            "slow_run_rate": _ratio(slow_runs_count, len(runs)),
            "avg_duration_ms": _avg_int(duration_values),
            "avg_success_duration_ms": _avg_int(success_duration_values),
            "max_duration_ms": max(duration_values) if duration_values else 0,
            "slow_threshold_ms": slow_threshold,
        },
        "breakdowns": {
            "by_source": _counter_rows(source_counts),
            "by_status": _counter_rows(status_counts),
        },
        "timing_shares": timing_share_rows,
        "recent_runs": recent_runs,
        "daily_trend": daily_trend,
        "slow_runs": slow_runs[:slow_limit],
        "slow_trigger_correlation": {
            "slow_run_count": len(slow_success),
            "normal_run_count": len(normal_success),
            "slow_avg_auto_reassign_triggers": slow_avg_triggers,
            "normal_avg_auto_reassign_triggers": normal_avg_triggers,
            "slow_avg_scanned_count": slow_avg_scanned,
            "normal_avg_scanned_count": normal_avg_scanned,
            "slow_avg_overdue_events": slow_avg_overdue,
            "normal_avg_overdue_events": normal_avg_overdue,
            "slow_runs_have_higher_trigger_load": (
                slow_avg_triggers is not None
                and normal_avg_triggers is not None
                and slow_avg_triggers > normal_avg_triggers
            ),
            "slow_runs_have_higher_scan_load": (
                slow_avg_scanned is not None
                and normal_avg_scanned is not None
                and slow_avg_scanned > normal_avg_scanned
            ),
        },
    }


def _build_auto_dispatch_operation_fallback_explanation(
    insights: dict[str, Any],
    *,
    question: str | None = None,
) -> dict[str, Any]:
    summary = insights.get("summary") or {}
    breakdowns = insights.get("breakdowns") or {}
    filters = insights.get("filters") or {}
    total = int(summary.get("total_events") or 0)
    direct_total = int(summary.get("direct_dispatch_total") or 0)
    hall_total = int(summary.get("hall_fallback_total") or 0)
    open_hall = int(summary.get("open_hall_fallback") or 0)
    needs_reassign = int(summary.get("needs_reassign") or 0)
    findings = [
        f"当前筛选范围内共有 {total} 条自动派工相关闭环记录。",
        f"直接自动派工 {direct_total} 条，其中高置信 {int(summary.get('high_confidence_auto') or 0)} 条、低置信兜底 {int(summary.get('low_confidence_auto_fallback') or 0)} 条。",
        f"大厅兜底 {hall_total} 条，其中灰度外进大厅 {int(summary.get('rollout_hall_fallback') or 0)} 条，仍打开 {open_hall} 条。",
    ]
    top_skill = _top_counter_label(breakdowns.get("by_skill") or [])
    top_building = _top_counter_label(breakdowns.get("by_building") or [])
    if total:
        findings.append(f"主要集中在 {top_building}，技能分布最高的是 {top_skill}。")

    risks: list[str] = []
    if open_hall:
        risks.append(f"仍有 {open_hall} 条大厅兜底打开，需要关注是否有人接管。")
    if needs_reassign:
        risks.append(f"复核中已有 {needs_reassign} 条被标记需改派，需要回看候选人分数、负载和技能匹配。")
    if hall_total > direct_total and total:
        risks.append("大厅兜底多于直接派工，说明当前筛选范围里自动指定具体人员的确定性不足。")
    if not risks:
        risks.append("当前筛选范围未出现明显改派或大厅堆积信号。")

    recommendations = [
        "先处理打开状态的大厅兜底记录，确认是否有人接管或需要管理员手动派工。",
        "继续保留低置信阈值 95 且不允许待命人员，等复核稳定后再考虑扩技能或扩楼宇。",
    ]
    if int(summary.get("rollout_hall_fallback") or 0):
        recommendations.append("灰度外进大厅已有命中，扩容前先按技能维度复盘这些工单是否适合直接自动派人。")

    return {
        "summary": (
            f"自动派工闭环已覆盖当前筛选范围，直接派工 {direct_total} 条，"
            f"大厅兜底 {hall_total} 条，仍打开 {open_hall} 条。"
        ),
        "findings": findings,
        "risks": risks,
        "recommendations": recommendations,
        "evidence": [
            {"label": "筛选条件", "value": json.dumps(filters, ensure_ascii=False)},
            {"label": "模式分布", "value": json.dumps(breakdowns.get("by_mode") or [], ensure_ascii=False)},
            {"label": "复核统计", "value": json.dumps(breakdowns.get("review_by_status") or [], ensure_ascii=False)},
        ],
    }


def _build_auto_dispatch_operation_llm_prompt(
    insights: dict[str, Any],
    *,
    question: str | None = None,
) -> str:
    compact_payload = {
        "question": question or "请解释自动派工与大厅兜底运营情况",
        "window": insights.get("window"),
        "filters": insights.get("filters"),
        "summary": insights.get("summary"),
        "breakdowns": insights.get("breakdowns"),
        "recent_records": (insights.get("records") or [])[:8],
    }
    return (
        "你是楼宇维修派工运营分析员。请只基于给定 JSON 做中文运营解读，"
        "不要编造不存在的工单、人员或原因。关注自动派工、低置信兜底、工单大厅兜底、复核和风险。\n"
        "返回严格 JSON，不要 markdown，格式如下：\n"
        "{\"summary\":\"一句话结论\",\"findings\":[\"事实1\"],\"risks\":[\"风险1\"],"
        "\"recommendations\":[\"建议1\"],\"evidence\":[{\"label\":\"证据名\",\"value\":\"证据值\"}]}\n\n"
        f"数据：{json.dumps(compact_payload, ensure_ascii=False, default=str)}"
    )


async def _call_auto_dispatch_operation_llm(prompt: str) -> dict[str, Any] | None:
    settings = get_settings()
    if not (settings.LLM_API_KEY or "").strip():
        return None
    try:
        from langchain_core.messages import HumanMessage, SystemMessage
        from langchain_openai import ChatOpenAI

        llm = ChatOpenAI(
            model=settings.LLM_MODEL_SYNTHESIS or settings.LLM_MODEL,
            api_key=settings.LLM_API_KEY,
            base_url=settings.LLM_BASE_URL,
            temperature=0.0,
            max_tokens=900,
            timeout=_LLM_TIMEOUT,
        )
        response = await asyncio.wait_for(
            llm.ainvoke(
                [
                    SystemMessage(content="你只做只读运营解释，不提出会修改系统状态的自动操作。"),
                    HumanMessage(content=prompt),
                ]
            ),
            timeout=_LLM_TIMEOUT + 5,
        )
        parsed = _parse_json_object(str(response.content or ""))
        if parsed:
            return _normalize_llm_explanation(parsed)
    except Exception as exc:
        logger.warning("自动派工运营洞察 LLM 解释失败，使用确定性兜底: %s", exc)
    return None


async def explain_auto_dispatch_operation_insights(
    db: AsyncSession,
    *,
    question: str | None = None,
    use_llm: bool = True,
    date_from: date | None = None,
    date_to: date | None = None,
    building_id: str | None = None,
    priority: str | None = None,
    required_skill: str | None = None,
    dispatch_mode: str | None = None,
    team_id: str | None = None,
    assignee_id: str | None = None,
) -> dict[str, Any]:
    insights = await build_auto_dispatch_operation_insights(
        db,
        date_from=date_from,
        date_to=date_to,
        building_id=building_id,
        priority=priority,
        required_skill=required_skill,
        dispatch_mode=dispatch_mode,
        team_id=team_id,
        assignee_id=assignee_id,
        page=1,
        page_size=20,
    )
    explanation = None
    source = "deterministic"
    if use_llm:
        explanation = await _call_auto_dispatch_operation_llm(
            _build_auto_dispatch_operation_llm_prompt(insights, question=question)
        )
        if explanation:
            source = "llm"
    if explanation is None:
        explanation = _build_auto_dispatch_operation_fallback_explanation(
            insights,
            question=question,
        )

    return {
        "readonly": True,
        "generated_at": _dt(datetime.now(timezone.utc)),
        "source": source,
        "question": question,
        "explanation": explanation,
        "insights": insights,
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
            f"低置信兜底为 {'开启' if auto_dispatch.get('allow_low_confidence') else '关闭'}，"
            f"大厅兜底为 {'开启' if auto_dispatch.get('allow_hall_fallback') else '关闭'}。"
            f"已产生自动派工任务 {tasks.get('total_auto', 0)} 个，"
            f"当前有效自动派工 {tasks.get('current_auto', 0)} 个；"
            f"灰度拦截 {observations.get('rollout_skipped', 0)} 次，"
            f"大厅兜底 {observations.get('hall_fallback_created', 0)} 次，"
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
