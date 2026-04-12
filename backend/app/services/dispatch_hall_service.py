from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func as sa_func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import DispatchHallApplication, DispatchHallEntry, User, WorkOrder

_OPEN_ENTRY_STATUSES = {"open", "assigned"}
logger = logging.getLogger(__name__)


def _dt_to_iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _normalize_str_list(values: list[str] | None) -> list[str]:
    normalized: list[str] = []
    for item in values or []:
        text = str(item or "").strip()
        if text and text not in normalized:
            normalized.append(text)
    return normalized


def _json_dumps_list(values: list[str] | None) -> str | None:
    items = _normalize_str_list(values)
    if not items:
        return None
    return json.dumps(items, ensure_ascii=False)


def _json_loads_list(payload: str | None) -> list[str]:
    if not payload:
        return []
    try:
        data = json.loads(payload)
    except (TypeError, ValueError):
        return []
    if not isinstance(data, list):
        return []
    return _normalize_str_list([str(item) for item in data])


def _derive_visibility_scope(
    *,
    target_team_ids: list[str] | None = None,
    target_skill_tags: list[str] | None = None,
    target_user_ids: list[str] | None = None,
) -> str:
    has_teams = bool(_normalize_str_list(target_team_ids))
    has_skills = bool(_normalize_str_list(target_skill_tags))
    has_users = bool(_normalize_str_list(target_user_ids))

    if has_teams and has_skills and has_users:
        return "team_skill_or_recommended"
    if has_teams and has_users:
        return "team_or_recommended"
    if has_skills and has_users:
        return "skill_or_recommended"
    if has_teams and has_skills:
        return "team_or_skill"
    if has_users:
        return "recommended_users"
    if has_skills:
        return "skill_pool"
    if has_teams:
        return "team_only"
    return "all_ops"


def _user_team_id(user: User | None) -> str | None:
    profile = getattr(user, "worker_profile", None) if user else None
    team = getattr(profile, "team", None) if profile else None
    return getattr(profile, "team_id", None) or getattr(team, "id", None)


def _user_skill_codes(user: User | None) -> set[str]:
    profile = getattr(user, "worker_profile", None) if user else None
    links = getattr(profile, "skill_links", None) or []
    codes: set[str] = set()
    for link in links:
        skill = getattr(link, "skill", None)
        code = getattr(skill, "code", None)
        if code:
            codes.add(str(code))
    return codes


def _hall_entry_visible_to_user(entry: DispatchHallEntry, viewer: User | None) -> bool:
    if viewer is None or getattr(viewer, "role", None) != "ops":
        return True

    if entry.status in {"assigned", "accepted"}:
        return entry.assigned_to == viewer.id
    if entry.status != "open":
        return False
    if entry.entry_type == "support_request" and entry.created_by and entry.created_by == viewer.id:
        return False

    team_ids = set(_json_loads_list(entry.target_team_ids_json))
    skill_tags = set(_json_loads_list(entry.target_skill_tags_json))
    target_user_ids = set(_json_loads_list(entry.target_user_ids_json))
    team_match = False
    skill_match = False
    recommended_match = viewer.id in target_user_ids

    team_id = _user_team_id(viewer)
    if team_id and team_id in team_ids:
        team_match = True

    skill_match = bool(skill_tags & _user_skill_codes(viewer))

    scope = entry.visibility_scope or "all_ops"
    if scope == "all_ops":
        return True
    if scope == "recommended_users":
        return recommended_match
    if scope == "team_only":
        return team_match
    if scope == "skill_pool":
        return skill_match
    if scope == "team_or_skill":
        return team_match or skill_match
    if scope == "team_or_recommended":
        return team_match or recommended_match
    if scope == "skill_or_recommended":
        return skill_match or recommended_match
    if scope == "team_skill_or_recommended":
        return team_match or skill_match or recommended_match

    return team_match or skill_match or recommended_match


def can_view_dispatch_hall_entry(entry: DispatchHallEntry, viewer: User | None) -> bool:
    return _hall_entry_visible_to_user(entry, viewer)


async def _load_hall_recommendation_context(
    db: AsyncSession,
    *,
    work_order: WorkOrder,
) -> dict[str, Any]:
    from app.services import work_order_service

    requirement = work_order_service.derive_dispatch_requirement(work_order)
    try:
        payload = await work_order_service.list_dispatch_candidates(
            db,
            work_order=work_order,
        )
    except Exception:
        return {
            "requirement": requirement,
            "candidates": [],
        }
    return {
        "requirement": payload.get("requirement") or requirement,
        "candidates": payload.get("candidates") or [],
    }


def _normalize_hall_skill_tags(required_skills: list[str] | None) -> list[str]:
    normalized = _normalize_str_list(required_skills)
    if normalized == ["inspection"]:
        return []
    return normalized[:3]


def _pick_recommended_team_ids(
    candidates: list[dict[str, Any]],
    *,
    preferred_team_name: str | None,
    limit: int = 2,
) -> list[str]:
    preferred_ids: list[str] = []
    fallback_ids: list[str] = []
    for candidate in candidates:
        team_id = str(candidate.get("team_id") or "").strip()
        if not team_id:
            continue
        if team_id not in fallback_ids:
            fallback_ids.append(team_id)
        team_name = str(candidate.get("team_name") or "").strip()
        if preferred_team_name and team_name and preferred_team_name in team_name and team_id not in preferred_ids:
            preferred_ids.append(team_id)
        if len(fallback_ids) >= limit and len(preferred_ids) >= limit:
            break

    if preferred_ids:
        return preferred_ids[:limit]
    return fallback_ids[:limit]


def _pick_recommended_user_ids(
    candidates: list[dict[str, Any]],
    *,
    source_assignee_id: str | None = None,
    limit: int = 3,
) -> list[str]:
    user_ids: list[str] = []
    for candidate in candidates:
        user_id = str(candidate.get("user_id") or "").strip()
        if not user_id or user_id == source_assignee_id:
            continue
        if not bool(candidate.get("dispatch_enabled", True)):
            continue
        if int(candidate.get("score") or 0) <= 0:
            continue
        if user_id not in user_ids:
            user_ids.append(user_id)
        if len(user_ids) >= limit:
            break
    return user_ids


async def derive_dispatch_hall_targets(
    db: AsyncSession,
    *,
    work_order: WorkOrder,
    entry_type: str,
    source_assignee_id: str | None = None,
    target_team_ids: list[str] | None = None,
    target_skill_tags: list[str] | None = None,
    target_user_ids: list[str] | None = None,
) -> dict[str, Any]:
    resolved_team_ids = _normalize_str_list(target_team_ids)
    resolved_skill_tags = _normalize_str_list(target_skill_tags)
    resolved_user_ids = _normalize_str_list(target_user_ids)

    # 定向班组协同时优先保持严格班组可见，避免未明确请求对象时暴露过宽。
    if entry_type == "support_request" and resolved_team_ids and not resolved_skill_tags and not resolved_user_ids:
        return {
            "visibility_scope": "team_only",
            "target_team_ids": resolved_team_ids,
            "target_skill_tags": [],
            "target_user_ids": [],
            "requirement": None,
        }

    if not (resolved_team_ids or resolved_skill_tags or resolved_user_ids):
        context = await _load_hall_recommendation_context(db, work_order=work_order)
        requirement = context.get("requirement") or {}
        ranked_candidates = [
            item for item in (context.get("candidates") or [])
            if isinstance(item, dict)
        ]
        visible_candidates = [
            item for item in ranked_candidates
            if str(item.get("user_id") or "").strip() != source_assignee_id
            and bool(item.get("dispatch_enabled", True))
            and int(item.get("score") or 0) > 0
        ]
        resolved_skill_tags = _normalize_hall_skill_tags(requirement.get("required_skills"))
        resolved_team_ids = _pick_recommended_team_ids(
            visible_candidates,
            preferred_team_name=str(requirement.get("preferred_team_name") or "").strip() or None,
        )
        resolved_user_ids = _pick_recommended_user_ids(
            visible_candidates,
            source_assignee_id=source_assignee_id,
        )
        return {
            "visibility_scope": _derive_visibility_scope(
                target_team_ids=resolved_team_ids,
                target_skill_tags=resolved_skill_tags,
                target_user_ids=resolved_user_ids,
            ),
            "target_team_ids": resolved_team_ids,
            "target_skill_tags": resolved_skill_tags,
            "target_user_ids": resolved_user_ids,
            "requirement": requirement,
        }

    return {
        "visibility_scope": _derive_visibility_scope(
            target_team_ids=resolved_team_ids,
            target_skill_tags=resolved_skill_tags,
            target_user_ids=resolved_user_ids,
        ),
        "target_team_ids": resolved_team_ids,
        "target_skill_tags": resolved_skill_tags,
        "target_user_ids": resolved_user_ids,
        "requirement": None,
    }


def serialize_dispatch_hall_application(
    application: DispatchHallApplication,
    *,
    applicant_user: User | None = None,
    handled_user: User | None = None,
) -> dict[str, Any]:
    return {
        "id": application.id,
        "hall_entry_id": application.hall_entry_id,
        "applicant_user_id": application.applicant_user_id,
        "applicant_username": getattr(applicant_user, "username", None),
        "application_type": application.application_type,
        "status": application.status,
        "note": application.note,
        "handle_note": application.handle_note,
        "handled_by": application.handled_by,
        "handled_by_username": getattr(handled_user, "username", None),
        "handled_at": _dt_to_iso(application.handled_at),
        "created_at": _dt_to_iso(application.created_at),
        "updated_at": _dt_to_iso(application.updated_at),
    }


def serialize_dispatch_hall_entry(
    entry: DispatchHallEntry,
    *,
    assigned_user: User | None = None,
    assigned_by_user: User | None = None,
    created_by_user: User | None = None,
    work_order_summary: dict[str, Any] | None = None,
    source_dispatch_summary: dict[str, Any] | None = None,
    applications: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    application_payloads = applications or []
    application_stats = {
        "total": len(application_payloads),
        "pending": sum(1 for item in application_payloads if item.get("status") == "pending"),
        "approved": sum(1 for item in application_payloads if item.get("status") == "approved"),
        "rejected": sum(1 for item in application_payloads if item.get("status") == "rejected"),
        "withdrawn": sum(1 for item in application_payloads if item.get("status") == "withdrawn"),
    }
    latest_application = sorted(
        application_payloads,
        key=lambda item: item.get("updated_at") or item.get("created_at") or "",
        reverse=True,
    )[0] if application_payloads else None
    risk_score = 0
    if entry.entry_type == "takeover_candidate":
        risk_score += 50
    if entry.overdue_level == "overdue":
        risk_score += 30
    elif entry.overdue_level == "warning":
        risk_score += 15
    risk_score += application_stats["pending"] * 10
    return {
        "id": entry.id,
        "work_order_id": entry.work_order_id,
        "incident_id": entry.incident_id,
        "source_dispatch_id": entry.source_dispatch_id,
        "entry_type": entry.entry_type,
        "status": entry.status,
        "visibility_scope": entry.visibility_scope,
        "target_team_ids": _json_loads_list(entry.target_team_ids_json),
        "target_skill_tags": _json_loads_list(entry.target_skill_tags_json),
        "target_user_ids": _json_loads_list(entry.target_user_ids_json),
        "reason": entry.reason,
        "support_reason": entry.support_reason,
        "sla_stage": entry.sla_stage,
        "overdue_level": entry.overdue_level,
        "allow_direct_claim": bool(entry.allow_direct_claim),
        "assigned_to": entry.assigned_to,
        "assigned_to_name": getattr(assigned_user, "username", None),
        "assigned_team_id": entry.assigned_team_id,
        "assigned_by": entry.assigned_by,
        "assigned_by_name": getattr(assigned_by_user, "username", None),
        "created_by": entry.created_by,
        "created_by_name": getattr(created_by_user, "username", None),
        "expired_at": _dt_to_iso(entry.expired_at),
        "assigned_at": _dt_to_iso(entry.assigned_at),
        "closed_at": _dt_to_iso(entry.closed_at),
        "created_at": _dt_to_iso(entry.created_at),
        "updated_at": _dt_to_iso(entry.updated_at),
        "work_order": work_order_summary,
        "source_dispatch": source_dispatch_summary,
        "applications": application_payloads,
        "application_stats": application_stats,
        "latest_application": latest_application,
        "risk_score": risk_score,
    }


async def list_dispatch_hall_entries(
    db: AsyncSession,
    *,
    viewer: User | None = None,
    status_filter: list[str] | None = None,
    entry_type_filter: list[str] | None = None,
    assigned_to: str | None = None,
    work_order_id: str | None = None,
    incident_id: str | None = None,
    source_dispatch_id: str | None = None,
    building_id: str | None = None,
    target_team_id: str | None = None,
    sort_by: str = "ops_priority",
    page: int = 1,
    page_size: int = 20,
) -> tuple[list[DispatchHallEntry], int]:
    query = select(DispatchHallEntry)
    if building_id:
        query = query.join(WorkOrder, WorkOrder.id == DispatchHallEntry.work_order_id).where(WorkOrder.building_id == building_id)
    if status_filter:
        query = query.where(DispatchHallEntry.status.in_(status_filter))
    if entry_type_filter:
        query = query.where(DispatchHallEntry.entry_type.in_(entry_type_filter))
    if assigned_to:
        query = query.where(DispatchHallEntry.assigned_to == assigned_to)
    if work_order_id:
        query = query.where(DispatchHallEntry.work_order_id == work_order_id)
    if incident_id:
        query = query.where(DispatchHallEntry.incident_id == incident_id)
    if source_dispatch_id:
        query = query.where(DispatchHallEntry.source_dispatch_id == source_dispatch_id)
    if target_team_id:
        query = query.where(DispatchHallEntry.target_team_ids_json.contains(target_team_id))

    if sort_by == "oldest":
        query = query.order_by(DispatchHallEntry.created_at.asc(), DispatchHallEntry.id.asc())
    elif sort_by == "updated":
        query = query.order_by(DispatchHallEntry.updated_at.desc(), DispatchHallEntry.created_at.desc())
    else:
        query = query.order_by(
            DispatchHallEntry.entry_type.desc(),
            DispatchHallEntry.overdue_level.desc().nullslast(),
            DispatchHallEntry.updated_at.desc(),
            DispatchHallEntry.created_at.desc(),
            DispatchHallEntry.id.desc(),
        )
    items = list((await db.execute(query)).scalars().all())

    if viewer is not None and getattr(viewer, "role", None) == "ops":
        items = [item for item in items if _hall_entry_visible_to_user(item, viewer)]

    if sort_by == "ops_priority":
        counts = await load_dispatch_hall_application_counts(db, hall_entry_ids=[item.id for item in items])
        items.sort(
            key=lambda item: (
                counts.get(item.id, {}).get("pending", 0),
                item.entry_type == "takeover_candidate",
                item.overdue_level == "overdue",
                item.updated_at or item.created_at,
            ),
            reverse=True,
        )

    total = len(items)
    offset = max(page - 1, 0) * page_size
    return items[offset: offset + page_size], total


async def load_dispatch_hall_application_counts(
    db: AsyncSession,
    *,
    hall_entry_ids: list[str],
) -> dict[str, dict[str, int]]:
    if not hall_entry_ids:
        return {}
    result = await db.execute(
        select(
            DispatchHallApplication.hall_entry_id,
            DispatchHallApplication.status,
            sa_func.count(DispatchHallApplication.id),
        )
        .where(DispatchHallApplication.hall_entry_id.in_(hall_entry_ids))
        .group_by(DispatchHallApplication.hall_entry_id, DispatchHallApplication.status)
    )
    grouped: dict[str, dict[str, int]] = {}
    for entry_id, status, count in result.all():
        bucket = grouped.setdefault(entry_id, {"total": 0, "pending": 0, "approved": 0, "rejected": 0, "withdrawn": 0})
        bucket[str(status)] = int(count)
        bucket["total"] += int(count)
    return grouped


async def get_dispatch_hall_entry_by_id(
    db: AsyncSession,
    hall_entry_id: str,
) -> DispatchHallEntry | None:
    return await db.get(DispatchHallEntry, hall_entry_id)


async def get_dispatch_hall_application_by_id(
    db: AsyncSession,
    application_id: str,
) -> DispatchHallApplication | None:
    return await db.get(DispatchHallApplication, application_id)


async def load_dispatch_hall_applications_by_entry_ids(
    db: AsyncSession,
    *,
    hall_entry_ids: list[str],
) -> dict[str, list[DispatchHallApplication]]:
    if not hall_entry_ids:
        return {}
    result = await db.execute(
        select(DispatchHallApplication)
        .where(DispatchHallApplication.hall_entry_id.in_(hall_entry_ids))
        .order_by(DispatchHallApplication.created_at.asc())
    )
    grouped: dict[str, list[DispatchHallApplication]] = {}
    for item in result.scalars().all():
        grouped.setdefault(item.hall_entry_id, []).append(item)
    return grouped


async def _find_latest_hall_entry(
    db: AsyncSession,
    *,
    work_order_id: str | None = None,
    source_dispatch_id: str | None,
    entry_type: str,
    statuses: set[str] | None = None,
) -> DispatchHallEntry | None:
    query = select(DispatchHallEntry).where(DispatchHallEntry.entry_type == entry_type)
    if work_order_id is not None:
        query = query.where(DispatchHallEntry.work_order_id == work_order_id)
    if source_dispatch_id is None:
        query = query.where(DispatchHallEntry.source_dispatch_id.is_(None))
    else:
        query = query.where(DispatchHallEntry.source_dispatch_id == source_dispatch_id)
    if statuses:
        query = query.where(DispatchHallEntry.status.in_(list(statuses)))
    query = query.order_by(DispatchHallEntry.created_at.desc()).limit(1)
    return (await db.execute(query)).scalar_one_or_none()


async def create_or_reopen_support_hall_entry(
    db: AsyncSession,
    *,
    work_order: WorkOrder,
    source_dispatch_id: str | None,
    source_assignee_id: str | None = None,
    created_by: str | None = None,
    target_team_ids: list[str] | None = None,
    target_skill_tags: list[str] | None = None,
    target_user_ids: list[str] | None = None,
    reason: str | None = None,
    support_reason: str | None = None,
) -> DispatchHallEntry:
    now = datetime.now(timezone.utc)
    target_plan = await derive_dispatch_hall_targets(
        db,
        work_order=work_order,
        entry_type="support_request",
        source_assignee_id=source_assignee_id,
        target_team_ids=target_team_ids,
        target_skill_tags=target_skill_tags,
        target_user_ids=target_user_ids,
    )
    entry = await _find_latest_hall_entry(
        db,
        work_order_id=work_order.id,
        source_dispatch_id=source_dispatch_id,
        entry_type="support_request",
        statuses=_OPEN_ENTRY_STATUSES,
    )
    if entry is None:
        entry = DispatchHallEntry(
            work_order_id=work_order.id,
            incident_id=work_order.incident_id,
            source_dispatch_id=source_dispatch_id,
            entry_type="support_request",
            status="open",
            created_by=created_by,
            created_at=now,
        )
        db.add(entry)

    entry.status = "open"
    entry.visibility_scope = str(target_plan["visibility_scope"] or "all_ops")
    entry.target_team_ids_json = _json_dumps_list(target_plan.get("target_team_ids"))
    entry.target_skill_tags_json = _json_dumps_list(target_plan.get("target_skill_tags"))
    entry.target_user_ids_json = _json_dumps_list(target_plan.get("target_user_ids"))
    entry.reason = reason
    entry.support_reason = support_reason
    entry.sla_stage = "waiting_support"
    entry.overdue_level = None
    entry.allow_direct_claim = False
    entry.assigned_to = None
    entry.assigned_team_id = None
    entry.assigned_by = None
    entry.assigned_at = None
    entry.closed_at = None
    entry.expired_at = None
    entry.updated_at = now
    await db.flush()
    if hasattr(db, "execute") and hasattr(db, "get"):
        from app.services.notification_service import create_notifications_for_dispatch_hall_open

        try:
            await create_notifications_for_dispatch_hall_open(
                db,
                hall_entry=entry,
                work_order=work_order,
                actor_id=created_by,
            )
        except (AttributeError, AssertionError):
            logger.debug("skip notification side effects for lightweight dispatch-hall db stub", exc_info=True)
    return entry


async def create_or_reopen_takeover_hall_entry(
    db: AsyncSession,
    *,
    work_order: WorkOrder,
    source_dispatch_id: str | None,
    source_assignee_id: str | None = None,
    created_by: str | None = None,
    target_team_ids: list[str] | None = None,
    target_skill_tags: list[str] | None = None,
    target_user_ids: list[str] | None = None,
    reason: str | None = None,
    sla_stage: str | None = None,
    overdue_level: str | None = None,
) -> DispatchHallEntry:
    now = datetime.now(timezone.utc)
    target_plan = await derive_dispatch_hall_targets(
        db,
        work_order=work_order,
        entry_type="takeover_candidate",
        source_assignee_id=source_assignee_id,
        target_team_ids=target_team_ids,
        target_skill_tags=target_skill_tags,
        target_user_ids=target_user_ids,
    )
    entry = await _find_latest_hall_entry(
        db,
        work_order_id=work_order.id,
        source_dispatch_id=source_dispatch_id,
        entry_type="takeover_candidate",
        statuses=_OPEN_ENTRY_STATUSES,
    )
    if entry is None:
        entry = DispatchHallEntry(
            work_order_id=work_order.id,
            incident_id=work_order.incident_id,
            source_dispatch_id=source_dispatch_id,
            entry_type="takeover_candidate",
            status="open",
            created_by=created_by,
            created_at=now,
        )
        db.add(entry)

    entry.status = "open"
    entry.visibility_scope = str(target_plan["visibility_scope"] or "all_ops")
    entry.target_team_ids_json = _json_dumps_list(target_plan.get("target_team_ids"))
    entry.target_skill_tags_json = _json_dumps_list(target_plan.get("target_skill_tags"))
    entry.target_user_ids_json = _json_dumps_list(target_plan.get("target_user_ids"))
    entry.reason = reason
    entry.support_reason = None
    entry.sla_stage = sla_stage
    entry.overdue_level = overdue_level or "overdue"
    entry.allow_direct_claim = False
    entry.assigned_to = None
    entry.assigned_team_id = None
    entry.assigned_by = None
    entry.assigned_at = None
    entry.closed_at = None
    entry.expired_at = None
    entry.updated_at = now
    await db.flush()
    if hasattr(db, "execute") and hasattr(db, "get"):
        from app.services.notification_service import create_notifications_for_dispatch_hall_open

        try:
            await create_notifications_for_dispatch_hall_open(
                db,
                hall_entry=entry,
                work_order=work_order,
                actor_id=created_by,
            )
        except (AttributeError, AssertionError):
            logger.debug("skip notification side effects for lightweight dispatch-hall db stub", exc_info=True)
    return entry


async def apply_to_dispatch_hall_entry(
    db: AsyncSession,
    *,
    hall_entry: DispatchHallEntry,
    applicant_user_id: str,
    application_type: str,
    note: str | None = None,
) -> DispatchHallApplication:
    expected_type = "support" if hall_entry.entry_type == "support_request" else "takeover"
    if hall_entry.entry_type not in {"support_request", "takeover_candidate"}:
        raise ValueError("当前共享工单类型不支持申请")
    if application_type != expected_type:
        raise ValueError("当前共享工单类型与申请动作不匹配")
    if hall_entry.status != "open":
        raise ValueError("当前共享工单不接受新的申请")

    result = await db.execute(
        select(DispatchHallApplication)
        .where(
            DispatchHallApplication.hall_entry_id == hall_entry.id,
            DispatchHallApplication.applicant_user_id == applicant_user_id,
            DispatchHallApplication.application_type == application_type,
            DispatchHallApplication.status == "pending",
        )
        .limit(1)
    )
    existing = result.scalar_one_or_none()
    if existing is not None:
        raise ValueError("你已经提交过申请，请勿重复操作")

    now = datetime.now(timezone.utc)
    application = DispatchHallApplication(
        hall_entry_id=hall_entry.id,
        applicant_user_id=applicant_user_id,
        application_type=application_type,
        status="pending",
        note=note,
        created_at=now,
        updated_at=now,
    )
    db.add(application)
    hall_entry.updated_at = now
    await db.flush()
    return application


async def approve_dispatch_hall_application(
    db: AsyncSession,
    *,
    application: DispatchHallApplication,
    actor_id: str | None = None,
    handle_note: str | None = None,
) -> DispatchHallApplication:
    if application.status != "pending":
        raise ValueError("当前申请已处理")
    now = datetime.now(timezone.utc)
    application.status = "approved"
    application.handled_by = actor_id
    application.handled_at = now
    application.handle_note = handle_note
    application.updated_at = now
    await db.flush()
    return application


async def reject_dispatch_hall_application(
    db: AsyncSession,
    *,
    application: DispatchHallApplication,
    actor_id: str | None = None,
    handle_note: str | None = None,
) -> DispatchHallApplication:
    if application.status != "pending":
        raise ValueError("当前申请已处理")
    now = datetime.now(timezone.utc)
    application.status = "rejected"
    application.handled_by = actor_id
    application.handled_at = now
    application.handle_note = handle_note
    application.updated_at = now
    await db.flush()
    return application


async def withdraw_dispatch_hall_application(
    db: AsyncSession,
    *,
    application: DispatchHallApplication,
    actor_id: str,
) -> DispatchHallApplication:
    if application.status != "pending":
        raise ValueError("当前申请不处于可撤回状态")
    if application.applicant_user_id != actor_id:
        raise ValueError("只能撤回自己提交的申请")

    now = datetime.now(timezone.utc)
    application.status = "withdrawn"
    application.handled_by = actor_id
    application.handled_at = now
    application.handle_note = "维修人员已主动撤回申请"
    application.updated_at = now

    hall_entry = await db.get(DispatchHallEntry, application.hall_entry_id)
    if hall_entry is not None:
        hall_entry.updated_at = now

    await db.flush()
    return application


async def assign_support_hall_entry(
    db: AsyncSession,
    *,
    hall_entry: DispatchHallEntry,
    assigned_user: User,
    actor_id: str | None = None,
    application: DispatchHallApplication | None = None,
    handle_note: str | None = None,
) -> DispatchHallEntry:
    if hall_entry.entry_type != "support_request":
        raise ValueError("当前共享工单不支持协同指派")
    if hall_entry.status not in {"open", "assigned"}:
        raise ValueError("当前共享工单已关闭，无法继续指派")
    if getattr(assigned_user, "role", None) != "ops" or not getattr(assigned_user, "is_active", False):
        raise ValueError("目标维修人员不存在或不可用")
    if application is not None:
        if application.hall_entry_id != hall_entry.id:
            raise ValueError("所选申请不属于当前共享工单")
        if application.application_type != "support":
            raise ValueError("当前申请类型不匹配")

    now = datetime.now(timezone.utc)
    team_id = _user_team_id(assigned_user)
    hall_entry.status = "assigned"
    hall_entry.assigned_to = assigned_user.id
    hall_entry.assigned_team_id = team_id
    hall_entry.assigned_by = actor_id
    hall_entry.assigned_at = now
    hall_entry.updated_at = now

    result = await db.execute(
        select(DispatchHallApplication).where(DispatchHallApplication.hall_entry_id == hall_entry.id)
    )
    for item in result.scalars().all():
        if item.status != "pending":
            continue
        if application is not None and item.id == application.id:
            item.status = "approved"
            item.handled_by = actor_id
            item.handled_at = now
            item.handle_note = handle_note
            item.updated_at = now
        else:
            item.status = "rejected"
            item.handled_by = actor_id
            item.handled_at = now
            item.handle_note = handle_note or "本轮协同已指派给其他维修人员"
            item.updated_at = now

    await db.flush()
    return hall_entry


async def close_dispatch_hall_entry(
    db: AsyncSession,
    *,
    hall_entry: DispatchHallEntry,
    actor_id: str | None = None,
    handle_note: str | None = None,
) -> DispatchHallEntry:
    if hall_entry.status in {"closed", "expired"}:
        return hall_entry

    now = datetime.now(timezone.utc)
    hall_entry.status = "closed"
    hall_entry.closed_at = now
    hall_entry.updated_at = now

    result = await db.execute(
        select(DispatchHallApplication).where(DispatchHallApplication.hall_entry_id == hall_entry.id)
    )
    for item in result.scalars().all():
        if item.status != "pending":
            continue
        item.status = "rejected"
        item.handled_by = actor_id
        item.handled_at = now
        item.handle_note = handle_note or "共享工单已关闭"
        item.updated_at = now

    await db.flush()
    work_order = await db.get(WorkOrder, hall_entry.work_order_id)
    if hasattr(db, "execute") and hasattr(db, "get"):
        from app.services.notification_service import create_notifications_for_dispatch_hall_closed

        try:
            await create_notifications_for_dispatch_hall_closed(
                db,
                hall_entry=hall_entry,
                work_order=work_order,
                actor_id=actor_id,
            )
        except (AttributeError, AssertionError):
            logger.debug("skip notification side effects for lightweight dispatch-hall db stub", exc_info=True)
    return hall_entry


async def accept_assigned_support_hall_entry(
    db: AsyncSession,
    *,
    hall_entry: DispatchHallEntry,
    actor_id: str,
) -> DispatchHallEntry:
    if hall_entry.entry_type != "support_request":
        raise ValueError("当前共享工单不支持协同确认")
    if hall_entry.status != "assigned":
        raise ValueError("当前协同任务不处于待确认状态")
    if hall_entry.assigned_to != actor_id:
        raise ValueError("只能确认分配给自己的协同任务")

    now = datetime.now(timezone.utc)
    hall_entry.status = "accepted"
    hall_entry.updated_at = now
    await db.flush()
    return hall_entry


async def reject_assigned_support_hall_entry(
    db: AsyncSession,
    *,
    hall_entry: DispatchHallEntry,
    actor_id: str,
    note: str | None = None,
) -> DispatchHallEntry:
    if hall_entry.entry_type != "support_request":
        raise ValueError("当前共享工单不支持协同拒绝")
    if hall_entry.status not in {"assigned", "accepted"}:
        raise ValueError("当前协同任务不处于可拒绝状态")
    if hall_entry.assigned_to != actor_id:
        raise ValueError("只能拒绝分配给自己的协同任务")

    now = datetime.now(timezone.utc)
    hall_entry.status = "open"
    hall_entry.assigned_to = None
    hall_entry.assigned_team_id = None
    hall_entry.assigned_by = None
    hall_entry.assigned_at = None
    hall_entry.updated_at = now
    if note:
        hall_entry.reason = note

    result = await db.execute(
        select(DispatchHallApplication).where(
            DispatchHallApplication.hall_entry_id == hall_entry.id,
            DispatchHallApplication.applicant_user_id == actor_id,
            DispatchHallApplication.application_type == "support",
            DispatchHallApplication.status == "approved",
        )
    )
    approved_application = result.scalar_one_or_none()
    if approved_application is not None:
        approved_application.status = "rejected"
        approved_application.handled_by = actor_id
        approved_application.handled_at = now
        approved_application.handle_note = note or "已指派协同被维修人员拒绝"
        approved_application.updated_at = now

    await db.flush()
    return hall_entry


async def close_open_hall_entries_for_dispatch(
    db: AsyncSession,
    *,
    source_dispatch_id: str,
    entry_types: list[str] | None = None,
    actor_id: str | None = None,
    handle_note: str | None = None,
) -> int:
    query = select(DispatchHallEntry).where(
        DispatchHallEntry.source_dispatch_id == source_dispatch_id,
        DispatchHallEntry.status.in_(list(_OPEN_ENTRY_STATUSES)),
    )
    if entry_types:
        query = query.where(DispatchHallEntry.entry_type.in_(entry_types))

    entries = list((await db.execute(query)).scalars().all())
    for entry in entries:
        await close_dispatch_hall_entry(
            db,
            hall_entry=entry,
            actor_id=actor_id,
            handle_note=handle_note,
        )
    return len(entries)
