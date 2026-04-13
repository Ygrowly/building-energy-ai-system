"""
Auto-dispatch evaluation and guarded execution service.

Evaluation calls are read-only. Execution calls stay behind explicit feature
flags and only write through existing dispatch / dispatch-hall services.
"""
from __future__ import annotations

from collections import Counter
import json
from types import SimpleNamespace
from typing import Any

from sqlalchemy import inspect, select
from sqlalchemy.exc import NoInspectionAvailable
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.models import User, WorkOrder, WorkerProfile, WorkerProfileSkill
from app.services.audit_log_service import write_work_order_audit_log
from app.services.dispatch_service import derive_dispatch_timeout_level, reassign_dispatch_task
from app.services.dispatch_hall_service import create_or_reopen_takeover_hall_entry
from app.services.work_order_service import (
    DISPATCHABLE_WORK_ORDER_STATUSES,
    assign_work_order,
    build_batch_dispatch_selection_reason,
    derive_dispatch_requirement,
    list_dispatch_candidates,
)


AUTO_DISPATCH_SKIP_LABELS: dict[str, str] = {
    "status_invalid": "当前工单状态不允许自动派工",
    "approval_not_ready": "审批维度尚未通过",
    "dispatch_not_pending": "派工维度不是待派工",
    "current_dispatch_exists": "工单已有当前派工任务",
    "no_candidates": "当前没有可用候选人",
    "top_candidate_disabled": "第一候选人未开启派工",
    "top_candidate_not_on_duty": "第一候选人当前不在值班状态",
    "top_score_below_threshold": "第一候选人推荐分不足",
    "score_gap_below_threshold": "第一候选人优势不够明显",
    "top_candidate_over_capacity": "第一候选人当前负载已达上限",
    "no_fallback_candidate_available": "没有满足低置信兜底条件的候选人",
    "fallback_score_below_threshold": "候选人未达到低置信兜底最低分",
    "fallback_candidate_disabled": "候选人未开启派工",
    "fallback_candidate_not_available_shift": "候选人当前班次不适合兜底派工",
    "fallback_candidate_over_capacity": "候选人当前负载已达上限",
    "rollout_building_not_allowed": "当前楼宇不在自动派工灰度范围内",
    "rollout_priority_not_allowed": "当前优先级不在自动派工灰度范围内",
    "rollout_skill_not_allowed": "当前工单技能类型不在自动派工灰度范围内",
    "reassign_rollout_building_not_allowed": "当前楼宇不在自动重派灰度范围内",
    "reassign_rollout_priority_not_allowed": "当前优先级不在自动重派灰度范围内",
    "reassign_rollout_skill_not_allowed": "当前工单技能类型不在自动重派灰度范围内",
    "assignee_unavailable": "自动派工候选人已不可用",
    "no_current_dispatch": "当前工单没有有效派工任务",
    "dispatch_stage_not_reassignable": "当前派工阶段不适合自动重派",
    "dispatch_not_overdue": "当前派工尚未超时",
    "max_reassign_attempts_reached": "已达到自动重派尝试上限",
}

_AUTO_REASSIGNABLE_DISPATCH_STATUSES = {
    "assigned",
    "accepted",
    "arrived",
    "processing",
}
_FALLBACK_ON_DUTY_STATUSES = {"on_duty"}
_FALLBACK_STANDBY_STATUSES = {"on_duty", "standby"}


def _summarize_candidate(candidate: dict[str, Any] | None) -> dict[str, Any] | None:
    if not candidate:
        return None
    return {
        "user_id": candidate.get("user_id"),
        "username": candidate.get("username"),
        "phone": candidate.get("phone"),
        "team_id": candidate.get("team_id"),
        "team_name": candidate.get("team_name"),
        "shift_status": candidate.get("shift_status"),
        "dispatch_enabled": candidate.get("dispatch_enabled"),
        "score": candidate.get("score"),
        "current_active_orders": candidate.get("current_active_orders"),
        "max_active_orders": candidate.get("max_active_orders"),
        "load_ratio": candidate.get("load_ratio"),
        "matched_skill_names": candidate.get("matched_skill_names") or [],
        "badges": candidate.get("badges") or [],
        "recommend_reason": candidate.get("recommend_reason"),
    }


def _blocker(reason: str, **extra: Any) -> dict[str, Any]:
    return {
        "reason": reason,
        "label": AUTO_DISPATCH_SKIP_LABELS.get(reason, reason),
        **extra,
    }


def _candidate_capacity_left(candidate: dict[str, Any] | None) -> int | None:
    if not candidate:
        return None
    max_active = int(candidate.get("max_active_orders") or 4)
    current_active = int(candidate.get("current_active_orders") or 0)
    return max_active - current_active


def _normalize_rollout_values(values: list[str] | tuple[str, ...] | set[str] | None) -> set[str]:
    return {
        str(item).strip()
        for item in (values or [])
        if str(item).strip()
    }


def _load_dispatch_requirement_snapshot(work_order: WorkOrder) -> dict[str, Any]:
    raw = getattr(work_order, "dispatch_profile_json", None)
    if raw:
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, dict):
                parsed.setdefault("required_skills", [])
                return parsed
        except (TypeError, ValueError):
            pass
    try:
        state = inspect(work_order)
    except NoInspectionAvailable:
        state = None
    if state is not None and "anomaly_links" in getattr(state, "unloaded", set()):
        return derive_dispatch_requirement(
            SimpleNamespace(
                building_id=getattr(work_order, "building_id", None),
                priority=getattr(work_order, "priority", None),
                issue_description=getattr(work_order, "issue_description", None),
                suggested_action=getattr(work_order, "suggested_action", None),
                anomaly_links=[],
            )
        )
    return derive_dispatch_requirement(work_order)


def _build_selection_reason(
    *,
    prefix: str,
    chosen_candidate: dict[str, Any],
    requirement: dict[str, Any],
    score_gap: int | None,
    high_confidence_blockers: list[dict[str, Any]] | None = None,
) -> str:
    reason = build_batch_dispatch_selection_reason(
        chosen_candidate=chosen_candidate,
        requirement=requirement,
        score_gap=score_gap,
    ).replace("批量派工推荐：", prefix, 1)
    if high_confidence_blockers:
        blocker_labels = "、".join(item["label"] for item in high_confidence_blockers[:3])
        reason = f"{reason}；未走高置信派工原因：{blocker_labels}"
    return reason


def build_auto_dispatch_rollout_gate(
    work_order: WorkOrder,
    *,
    allowed_buildings: list[str] | tuple[str, ...] | set[str] | None = None,
    allowed_priorities: list[str] | tuple[str, ...] | set[str] | None = None,
    allowed_required_skills: list[str] | tuple[str, ...] | set[str] | None = None,
) -> dict[str, Any]:
    return _build_rollout_gate(
        work_order,
        allowed_buildings=allowed_buildings,
        allowed_priorities=allowed_priorities,
        allowed_required_skills=allowed_required_skills,
        blocker_reason_prefix="rollout",
    )


def build_auto_reassign_rollout_gate(
    work_order: WorkOrder,
    *,
    allowed_buildings: list[str] | tuple[str, ...] | set[str] | None = None,
    allowed_priorities: list[str] | tuple[str, ...] | set[str] | None = None,
    allowed_required_skills: list[str] | tuple[str, ...] | set[str] | None = None,
) -> dict[str, Any]:
    return _build_rollout_gate(
        work_order,
        allowed_buildings=allowed_buildings,
        allowed_priorities=allowed_priorities,
        allowed_required_skills=allowed_required_skills,
        blocker_reason_prefix="reassign_rollout",
    )


def _build_rollout_gate(
    work_order: WorkOrder,
    *,
    allowed_buildings: list[str] | tuple[str, ...] | set[str] | None = None,
    allowed_priorities: list[str] | tuple[str, ...] | set[str] | None = None,
    allowed_required_skills: list[str] | tuple[str, ...] | set[str] | None = None,
    blocker_reason_prefix: str,
) -> dict[str, Any]:
    requirement = _load_dispatch_requirement_snapshot(work_order)
    blockers: list[dict[str, Any]] = []

    normalized_buildings = _normalize_rollout_values(allowed_buildings)
    normalized_priorities = _normalize_rollout_values(allowed_priorities)
    normalized_skills = _normalize_rollout_values(allowed_required_skills)

    building_id = getattr(work_order, "building_id", None)
    priority = getattr(work_order, "priority", None)
    required_skills = {
        str(item).strip()
        for item in (requirement.get("required_skills") or [])
        if str(item).strip()
    }

    if normalized_buildings and building_id not in normalized_buildings:
        blockers.append(
            _blocker(
                f"{blocker_reason_prefix}_building_not_allowed",
                current_building=building_id,
                allowed_buildings=sorted(normalized_buildings),
            )
        )
    if normalized_priorities and priority not in normalized_priorities:
        blockers.append(
            _blocker(
                f"{blocker_reason_prefix}_priority_not_allowed",
                current_priority=priority,
                allowed_priorities=sorted(normalized_priorities),
            )
        )
    if normalized_skills and not required_skills.intersection(normalized_skills):
        blockers.append(
            _blocker(
                f"{blocker_reason_prefix}_skill_not_allowed",
                required_skills=sorted(required_skills),
                allowed_required_skills=sorted(normalized_skills),
            )
        )

    return {
        "allowed": not blockers,
        "filters": {
            "allowed_buildings": sorted(normalized_buildings),
            "allowed_priorities": sorted(normalized_priorities),
            "allowed_required_skills": sorted(normalized_skills),
        },
        "requirement": requirement,
        "blockers": blockers,
    }


async def _ensure_work_order_loaded(
    db: AsyncSession,
    work_order: WorkOrder,
) -> WorkOrder:
    try:
        state = inspect(work_order)
    except NoInspectionAvailable:
        return work_order

    if "anomaly_links" not in state.unloaded:
        return work_order

    result = await db.execute(
        select(WorkOrder)
        .options(selectinload(WorkOrder.anomaly_links))
        .where(WorkOrder.id == work_order.id)
    )
    return result.scalar_one_or_none() or work_order


async def _load_auto_dispatch_assignee(
    db: AsyncSession,
    user_id: str,
) -> User | None:
    result = await db.execute(
        select(User)
        .options(
            selectinload(User.worker_profile).selectinload(WorkerProfile.team),
            selectinload(User.worker_profile)
            .selectinload(WorkerProfile.skill_links)
            .selectinload(WorkerProfileSkill.skill),
        )
        .where(User.id == user_id)
    )
    return result.scalar_one_or_none()


def _pick_auto_dispatch_candidate(
    *,
    candidates: list[dict[str, Any]],
    min_score: int,
    min_gap: int,
    require_on_duty: bool,
) -> tuple[dict[str, Any] | None, list[dict[str, Any]], dict[str, Any] | None, dict[str, Any] | None, int | None]:
    if not candidates:
        return None, [_blocker("no_candidates")], None, None, None

    top_candidate = candidates[0]
    second_candidate = candidates[1] if len(candidates) > 1 else None
    top_score = int(top_candidate.get("score") or 0)
    second_score = int(second_candidate.get("score") or 0) if second_candidate else None
    score_gap = top_score - second_score if second_score is not None else None
    blockers: list[dict[str, Any]] = []

    if not bool(top_candidate.get("dispatch_enabled", True)):
        blockers.append(_blocker("top_candidate_disabled"))
    if require_on_duty and top_candidate.get("shift_status") != "on_duty":
        blockers.append(
            _blocker(
                "top_candidate_not_on_duty",
                shift_status=top_candidate.get("shift_status"),
            )
        )
    if top_score < min_score:
        blockers.append(
            _blocker(
                "top_score_below_threshold",
                top_score=top_score,
                min_score=min_score,
            )
        )
    if score_gap is not None and score_gap < min_gap:
        blockers.append(
            _blocker(
                "score_gap_below_threshold",
                score_gap=score_gap,
                min_gap=min_gap,
            )
        )

    capacity_left = _candidate_capacity_left(top_candidate)
    if capacity_left is not None and capacity_left <= 0:
        blockers.append(
            _blocker(
                "top_candidate_over_capacity",
                capacity_left=capacity_left,
            )
        )

    return (top_candidate if not blockers else None), blockers, top_candidate, second_candidate, score_gap


def _fallback_candidate_blockers(
    candidate: dict[str, Any],
    *,
    fallback_min_score: int,
    allow_standby: bool,
) -> list[str]:
    reasons: list[str] = []
    if not bool(candidate.get("dispatch_enabled", True)):
        reasons.append("fallback_candidate_disabled")

    allowed_shift_statuses = _FALLBACK_STANDBY_STATUSES if allow_standby else _FALLBACK_ON_DUTY_STATUSES
    if candidate.get("shift_status") not in allowed_shift_statuses:
        reasons.append("fallback_candidate_not_available_shift")

    if int(candidate.get("score") or 0) < fallback_min_score:
        reasons.append("fallback_score_below_threshold")

    capacity_left = _candidate_capacity_left(candidate)
    if capacity_left is not None and capacity_left <= 0:
        reasons.append("fallback_candidate_over_capacity")
    return reasons


def _pick_low_confidence_fallback_candidate(
    *,
    candidates: list[dict[str, Any]],
    fallback_min_score: int,
    allow_standby: bool,
) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    if not candidates:
        return None, [_blocker("no_candidates")]

    rejection_counter: Counter[str] = Counter()
    for candidate in candidates:
        reasons = _fallback_candidate_blockers(
            candidate,
            fallback_min_score=fallback_min_score,
            allow_standby=allow_standby,
        )
        if not reasons:
            return candidate, []
        rejection_counter.update(reasons)

    return None, [
        _blocker(
            "no_fallback_candidate_available",
            reason_counts=dict(rejection_counter),
            fallback_min_score=fallback_min_score,
            allow_standby=allow_standby,
            top_candidate=_summarize_candidate(candidates[0]),
        )
    ]


async def build_auto_dispatch_evaluation(
    db: AsyncSession,
    *,
    work_order: WorkOrder,
    min_score: int = 110,
    min_gap: int = 10,
    require_on_duty: bool = True,
    fallback_min_score: int = 80,
    fallback_allow_standby: bool = True,
) -> dict[str, Any]:
    """
    Build a read-only auto-dispatch decision payload for one work order.

    The returned payload is safe to expose to UI or a future executor because it
    includes explicit blockers and the exact rules used for the dry-run.
    """
    work_order = await _ensure_work_order_loaded(db, work_order)
    rules = {
        "min_score": min_score,
        "min_gap": min_gap,
        "require_on_duty": require_on_duty,
        "fallback_min_score": fallback_min_score,
        "fallback_allow_standby": fallback_allow_standby,
        "dispatch_mode": "auto",
    }
    base_blockers: list[dict[str, Any]] = []
    approval_status = getattr(work_order, "approval_status", None)
    dispatch_summary_status = getattr(work_order, "dispatch_summary_status", None)

    if work_order.status not in set(DISPATCHABLE_WORK_ORDER_STATUSES):
        base_blockers.append(
            _blocker(
                "status_invalid",
                current_status=work_order.status,
            )
        )
    if approval_status not in (None, "approved"):
        base_blockers.append(
            _blocker(
                "approval_not_ready",
                approval_status=approval_status,
            )
        )
    if dispatch_summary_status not in (None, "pending_dispatch"):
        base_blockers.append(
            _blocker(
                "dispatch_not_pending",
                dispatch_summary_status=dispatch_summary_status,
            )
        )
    if getattr(work_order, "current_dispatch_id", None):
        base_blockers.append(
            _blocker(
                "current_dispatch_exists",
                current_dispatch_id=getattr(work_order, "current_dispatch_id", None),
            )
        )

    candidate_payload = await list_dispatch_candidates(db, work_order=work_order)
    candidates = candidate_payload["candidates"]
    chosen_candidate, candidate_blockers, top_candidate, second_candidate, score_gap = _pick_auto_dispatch_candidate(
        candidates=candidates,
        min_score=min_score,
        min_gap=min_gap,
        require_on_duty=require_on_duty,
    )
    fallback_candidate, fallback_blockers = _pick_low_confidence_fallback_candidate(
        candidates=candidates,
        fallback_min_score=fallback_min_score,
        allow_standby=fallback_allow_standby,
    )

    selection_reason = None
    apply_payload = None
    strategy = "manual_review"
    confidence = None
    blockers = list(base_blockers)
    hall_fallback = None

    if not base_blockers and chosen_candidate is not None and not candidate_blockers:
        strategy = "high_confidence_dispatch"
        confidence = "high"
        selection_reason = _build_selection_reason(
            prefix="高置信自动派工：",
            chosen_candidate=chosen_candidate,
            requirement=candidate_payload["requirement"],
            score_gap=score_gap,
        )
        apply_payload = {
            "ticket_id": work_order.ticket_id,
            "assigned_to": chosen_candidate["user_id"],
            "dispatch_mode": "auto",
            "selection_reason": selection_reason,
        }
    elif not base_blockers and fallback_candidate is not None and not fallback_blockers:
        strategy = "low_confidence_fallback_dispatch"
        confidence = "low"
        selection_reason = _build_selection_reason(
            prefix="低置信兜底派工：",
            chosen_candidate=fallback_candidate,
            requirement=candidate_payload["requirement"],
            score_gap=score_gap,
            high_confidence_blockers=candidate_blockers,
        )
        apply_payload = {
            "ticket_id": work_order.ticket_id,
            "assigned_to": fallback_candidate["user_id"],
            "dispatch_mode": "auto_fallback",
            "selection_reason": selection_reason,
        }
    elif not base_blockers:
        strategy = "hall_fallback"
        blockers = list(fallback_blockers or candidate_blockers)
        hall_reason_bits = [
            "自动派工未能指定具体维修员，进入共享工单大厅待接管",
        ]
        if blockers:
            hall_reason_bits.append("阻塞原因：" + "、".join(item["label"] for item in blockers[:3]))
        hall_fallback = {
            "entry_type": "takeover_candidate",
            "reason": "；".join(hall_reason_bits),
            "sla_stage": "pending_dispatch",
            "overdue_level": "fallback",
        }

    return {
        "readonly": True,
        "eligible": apply_payload is not None,
        "decision": "ready" if apply_payload is not None else strategy,
        "strategy": strategy,
        "confidence": confidence,
        "ticket_id": work_order.ticket_id,
        "work_order_id": work_order.id,
        "status": work_order.status,
        "approval_status": approval_status,
        "dispatch_summary_status": dispatch_summary_status,
        "current_dispatch_id": getattr(work_order, "current_dispatch_id", None),
        "rules": rules,
        "requirement": candidate_payload["requirement"],
        "candidate_count": len(candidates),
        "top_candidate": _summarize_candidate(top_candidate),
        "second_candidate": _summarize_candidate(second_candidate),
        "fallback_candidate": _summarize_candidate(fallback_candidate),
        "score_gap": score_gap,
        "blockers": blockers,
        "base_blockers": base_blockers,
        "high_confidence_blockers": candidate_blockers,
        "fallback_blockers": fallback_blockers,
        "selection_reason": selection_reason,
        "apply_payload": apply_payload,
        "hall_fallback": hall_fallback,
    }


async def execute_auto_dispatch(
    db: AsyncSession,
    *,
    work_order: WorkOrder,
    actor_id: str | None = None,
    enabled: bool = False,
    min_score: int = 110,
    min_gap: int = 10,
    require_on_duty: bool = True,
    allow_low_confidence_fallback: bool = False,
    fallback_min_score: int = 80,
    fallback_allow_standby: bool = True,
    create_hall_fallback: bool = False,
) -> dict[str, Any]:
    """
    Execute auto dispatch only when explicitly enabled and dry-run is eligible.

    This function does not commit. Callers own commit/rollback and cache
    invalidation so it can be composed safely in API or scheduler contexts.
    """
    evaluation = await build_auto_dispatch_evaluation(
        db,
        work_order=work_order,
        min_score=min_score,
        min_gap=min_gap,
        require_on_duty=require_on_duty,
        fallback_min_score=fallback_min_score,
        fallback_allow_standby=fallback_allow_standby,
    )
    if not enabled:
        return {
            "executed": False,
            "action_taken": False,
            "reason": "auto_dispatch_execution_disabled",
            "message": "自动派工执行开关未开启，本次只返回评估结果",
            "evaluation": evaluation,
        }
    if evaluation["strategy"] == "low_confidence_fallback_dispatch" and not allow_low_confidence_fallback:
        return {
            "executed": False,
            "action_taken": False,
            "reason": "low_confidence_fallback_disabled",
            "message": "低置信兜底派工开关未开启，本次只返回评估结果",
            "evaluation": evaluation,
        }
    if evaluation["strategy"] == "hall_fallback" and evaluation.get("hall_fallback"):
        if not create_hall_fallback:
            return {
                "executed": False,
                "action_taken": False,
                "reason": "auto_dispatch_hall_fallback_disabled",
                "message": "自动派工大厅兜底开关未开启，本次只返回评估结果",
                "evaluation": evaluation,
            }

        hall_plan = evaluation["hall_fallback"]
        hall_entry = await create_or_reopen_takeover_hall_entry(
            db,
            work_order=work_order,
            source_dispatch_id=None,
            source_assignee_id=None,
            created_by=actor_id,
            reason=hall_plan["reason"],
            sla_stage=hall_plan["sla_stage"],
            overdue_level=hall_plan["overdue_level"],
        )
        await write_work_order_audit_log(
            db,
            work_order_id=work_order.id,
            action="auto_dispatch_hall_fallback",
            old_status=work_order.status,
            new_status=work_order.status,
            actor_type="system",
            actor_id=actor_id,
            detail={
                "hall_entry_id": hall_entry.id,
                "reason": hall_plan["reason"],
                "strategy": evaluation["strategy"],
                "blockers": evaluation["blockers"],
            },
        )
        return {
            "executed": False,
            "action_taken": True,
            "reason": "auto_dispatch_hall_fallback_created",
            "message": "自动派工无法指定具体责任人，已进入工单大厅待接管",
            "ticket_id": work_order.ticket_id,
            "hall_entry_id": hall_entry.id,
            "status": work_order.status,
            "evaluation": evaluation,
        }
    if not evaluation["eligible"] or not evaluation["apply_payload"]:
        return {
            "executed": False,
            "action_taken": False,
            "reason": "auto_dispatch_not_eligible",
            "message": "当前工单不满足自动派工条件",
            "evaluation": evaluation,
        }

    assigned_to = evaluation["apply_payload"]["assigned_to"]
    assigned_user = await _load_auto_dispatch_assignee(db, assigned_to)
    if not assigned_user or assigned_user.role != "ops" or not assigned_user.is_active:
        evaluation["blockers"].append(_blocker("assignee_unavailable"))
        evaluation["eligible"] = False
        evaluation["decision"] = "manual_review"
        evaluation["apply_payload"] = None
        return {
            "executed": False,
            "action_taken": False,
            "reason": "assignee_unavailable",
            "message": "自动派工候选人已不可用",
            "evaluation": evaluation,
        }

    await assign_work_order(
        db,
        work_order=work_order,
        assigned_user=assigned_user,
        actor_type="system",
        actor_id=actor_id,
        dispatch_mode=evaluation["apply_payload"]["dispatch_mode"],
        candidate_snapshot={
            "auto_dispatch": True,
            "strategy": evaluation["strategy"],
            "confidence": evaluation["confidence"],
            "rules": evaluation["rules"],
            "top_candidate": evaluation["top_candidate"],
            "second_candidate": evaluation["second_candidate"],
            "fallback_candidate": evaluation["fallback_candidate"],
            "score_gap": evaluation["score_gap"],
            "triggered_by": actor_id,
        },
        notes=evaluation["selection_reason"],
    )

    return {
        "executed": True,
        "action_taken": True,
        "reason": "auto_dispatch_executed",
        "message": f"工单已自动派给 {assigned_user.username}",
        "ticket_id": work_order.ticket_id,
        "dispatch_id": work_order.current_dispatch_id,
        "assigned_to": assigned_user.id,
        "assigned_to_name": assigned_user.username,
        "status": work_order.status,
        "evaluation": evaluation,
    }


async def build_auto_reassign_evaluation(
    db: AsyncSession,
    *,
    work_order: WorkOrder,
    current_dispatch: Any | None,
    min_score: int = 115,
    min_gap: int = 10,
    require_on_duty: bool = True,
    require_overdue: bool = True,
    max_attempt_no: int = 3,
    dispatch_workers: list[User] | None = None,
    dispatch_active_counts: dict[str, int] | None = None,
) -> dict[str, Any]:
    """
    Build a read-only auto-reassign decision payload.

    The function intentionally stops at advice. Automatic execution should be
    introduced only after the advice payload is proven stable in operations.
    """
    work_order = await _ensure_work_order_loaded(db, work_order)
    rules = {
        "min_score": min_score,
        "min_gap": min_gap,
        "require_on_duty": require_on_duty,
        "require_overdue": require_overdue,
        "max_attempt_no": max_attempt_no,
        "dispatch_mode": "reassigned",
    }
    blockers: list[dict[str, Any]] = []
    timeout_level = None
    due_at = None
    current_assignee = getattr(current_dispatch, "assigned_to", None)

    if work_order.status != "dispatched":
        blockers.append(_blocker("status_invalid", current_status=work_order.status))

    if current_dispatch is None:
        blockers.append(_blocker("no_current_dispatch"))
    else:
        dispatch_status = getattr(current_dispatch, "dispatch_status", None)
        if dispatch_status not in _AUTO_REASSIGNABLE_DISPATCH_STATUSES:
            blockers.append(
                _blocker(
                    "dispatch_stage_not_reassignable",
                    dispatch_status=dispatch_status,
                )
            )

        timeout_level, due_at = derive_dispatch_timeout_level(current_dispatch)
        if require_overdue and timeout_level != "overdue":
            blockers.append(
                _blocker(
                    "dispatch_not_overdue",
                    timeout_level=timeout_level,
                    due_at=due_at.isoformat() if due_at else None,
                )
            )

        attempt_no = int(getattr(current_dispatch, "attempt_no", 1) or 1)
        if attempt_no >= max_attempt_no:
            blockers.append(
                _blocker(
                    "max_reassign_attempts_reached",
                    attempt_no=attempt_no,
                    max_attempt_no=max_attempt_no,
                )
            )

    candidate_payload = await list_dispatch_candidates(
        db,
        work_order=work_order,
        workers=dispatch_workers,
        active_counts=dispatch_active_counts,
    )
    candidates = [
        candidate
        for candidate in candidate_payload["candidates"]
        if candidate.get("user_id") != current_assignee
    ]
    chosen_candidate, candidate_blockers, top_candidate, second_candidate, score_gap = _pick_auto_dispatch_candidate(
        candidates=candidates,
        min_score=min_score,
        min_gap=min_gap,
        require_on_duty=require_on_duty,
    )
    blockers.extend(candidate_blockers)

    selection_reason = None
    apply_payload = None
    if chosen_candidate is not None and not blockers:
        selection_reason = build_batch_dispatch_selection_reason(
            chosen_candidate=chosen_candidate,
            requirement=candidate_payload["requirement"],
            score_gap=score_gap,
        ).replace("批量派工推荐：", "自动重派评估：", 1)
        apply_payload = {
            "ticket_id": work_order.ticket_id,
            "from_dispatch_id": getattr(current_dispatch, "id", None),
            "assigned_to": chosen_candidate["user_id"],
            "dispatch_mode": "reassigned",
            "reason": selection_reason,
        }

    return {
        "readonly": True,
        "eligible": chosen_candidate is not None and not blockers,
        "decision": "ready" if chosen_candidate is not None and not blockers else "manual_review",
        "ticket_id": work_order.ticket_id,
        "work_order_id": work_order.id,
        "status": work_order.status,
        "current_dispatch_id": getattr(current_dispatch, "id", None),
        "current_assigned_to": current_assignee,
        "current_dispatch_status": getattr(current_dispatch, "dispatch_status", None),
        "timeout_level": timeout_level,
        "due_at": due_at.isoformat() if due_at else None,
        "rules": rules,
        "requirement": candidate_payload["requirement"],
        "candidate_count": len(candidates),
        "top_candidate": _summarize_candidate(top_candidate),
        "second_candidate": _summarize_candidate(second_candidate),
        "score_gap": score_gap,
        "blockers": blockers,
        "selection_reason": selection_reason,
        "apply_payload": apply_payload,
    }


async def execute_auto_reassign(
    db: AsyncSession,
    *,
    work_order: WorkOrder,
    current_dispatch: Any | None,
    evaluation: dict[str, Any] | None = None,
    actor_id: str | None = None,
    trigger_reason: str | None = None,
    trigger_label: str | None = None,
    enabled: bool = False,
    min_score: int = 115,
    min_gap: int = 10,
    require_on_duty: bool = True,
    require_overdue: bool = True,
    max_attempt_no: int = 3,
    dispatch_workers: list[User] | None = None,
    dispatch_active_counts: dict[str, int] | None = None,
) -> dict[str, Any]:
    """
    Execute auto reassign only when explicitly enabled and dry-run is eligible.

    This function does not commit. Callers own commit/rollback and cache
    invalidation so API routes and future schedulers can compose it safely.
    """
    evaluation = evaluation or await build_auto_reassign_evaluation(
        db,
        work_order=work_order,
        current_dispatch=current_dispatch,
        min_score=min_score,
        min_gap=min_gap,
        require_on_duty=require_on_duty,
        require_overdue=require_overdue,
        max_attempt_no=max_attempt_no,
        dispatch_workers=dispatch_workers,
        dispatch_active_counts=dispatch_active_counts,
    )
    if not enabled:
        return {
            "executed": False,
            "action_taken": False,
            "reason": "auto_reassign_execution_disabled",
            "message": "自动重派执行开关未开启，本次只返回评估结果",
            "evaluation": evaluation,
        }
    if not evaluation["eligible"] or not evaluation["apply_payload"]:
        return {
            "executed": False,
            "action_taken": False,
            "reason": "auto_reassign_not_eligible",
            "message": "当前工单不满足自动重派条件",
            "evaluation": evaluation,
        }
    if current_dispatch is None:
        return {
            "executed": False,
            "action_taken": False,
            "reason": "no_current_dispatch",
            "message": "当前工单没有有效派工任务",
            "evaluation": evaluation,
        }

    assigned_to = evaluation["apply_payload"]["assigned_to"]
    assigned_user = await _load_auto_dispatch_assignee(db, assigned_to)
    if not assigned_user or assigned_user.role != "ops" or not assigned_user.is_active:
        evaluation["blockers"].append(_blocker("assignee_unavailable"))
        evaluation["eligible"] = False
        evaluation["decision"] = "manual_review"
        evaluation["apply_payload"] = None
        return {
            "executed": False,
            "action_taken": False,
            "reason": "assignee_unavailable",
            "message": "自动重派候选人已不可用",
            "evaluation": evaluation,
        }

    candidate_snapshot = {
        "auto_reassign": True,
        "rules": evaluation["rules"],
        "top_candidate": evaluation["top_candidate"],
        "second_candidate": evaluation["second_candidate"],
        "score_gap": evaluation["score_gap"],
        "from_dispatch_id": evaluation["current_dispatch_id"],
        "current_assigned_to": evaluation["current_assigned_to"],
        "timeout_level": evaluation["timeout_level"],
        "triggered_by": actor_id,
        "trigger_reason": trigger_reason,
        "trigger_label": trigger_label,
    }
    new_dispatch = await reassign_dispatch_task(
        db,
        work_order=work_order,
        dispatch_task=current_dispatch,
        assigned_user=assigned_user,
        actor_type="system",
        actor_id=actor_id,
        reason=evaluation["selection_reason"],
        dispatch_mode=evaluation["apply_payload"]["dispatch_mode"],
        candidate_snapshot=candidate_snapshot,
    )
    await write_work_order_audit_log(
        db,
        work_order_id=work_order.id,
        action="auto_reassign_executed",
        old_status=work_order.status,
        new_status=work_order.status,
        actor_type="system",
        actor_id=actor_id,
        detail={
            "from_dispatch_id": evaluation["current_dispatch_id"],
            "to_dispatch_id": new_dispatch.id,
            "assigned_to": assigned_user.id,
            "assigned_to_name": assigned_user.username,
            "selection_reason": evaluation["selection_reason"],
            "rules": evaluation["rules"],
            "score_gap": evaluation["score_gap"],
            "trigger_reason": trigger_reason,
            "trigger_label": trigger_label,
        },
    )

    return {
        "executed": True,
        "action_taken": True,
        "reason": "auto_reassign_executed",
        "message": f"工单已自动改派给 {assigned_user.username}",
        "ticket_id": work_order.ticket_id,
        "from_dispatch_id": evaluation["current_dispatch_id"],
        "dispatch_id": new_dispatch.id,
        "assigned_to": assigned_user.id,
        "assigned_to_name": assigned_user.username,
        "status": work_order.status,
        "trigger_reason": trigger_reason,
        "trigger_label": trigger_label,
        "evaluation": evaluation,
    }
