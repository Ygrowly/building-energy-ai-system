"""
Prepare controlled live-data samples for dispatch hall integration testing.

The script intentionally does not run a full SLA scan. Instead, it creates two
small, auditable samples from pending_dispatch work orders:

1. support_request: a worker requests support and another worker applies.
2. takeover_candidate: a simulated overdue takeover item with an applicant.

Default is dry-run. Use --apply to mutate the configured database.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import case, select
from sqlalchemy.orm import selectinload

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.cache import delete_cache_by_prefix
from app.db.models import DispatchHallApplication, DispatchHallEntry, User, WorkOrder, WorkerProfile, WorkerProfileSkill
from app.db.session import AsyncSessionLocal
from app.services.dispatch_hall_service import (
    apply_to_dispatch_hall_entry,
    can_view_dispatch_hall_entry,
    create_or_reopen_takeover_hall_entry,
)
from app.services.dispatch_service import (
    get_current_dispatch_task,
    update_dispatch_task_action,
)
from app.services.work_order_service import assign_work_order

ROOT_DIR = Path(__file__).resolve().parents[1]
RUNTIME_DIR = ROOT_DIR / "runtime" / "dispatch_hall_live_smoke"

SUPPORT_OWNER_CANDIDATES = ("ops_hvac_01", "test2")
SUPPORT_APPLICANT_CANDIDATES = ("ops_controls_01", "ops_general_02", "ops_electrical_01")
TAKEOVER_OWNER_CANDIDATES = ("ops_electrical_01", "ops_hvac_01", "test2")
TAKEOVER_APPLICANT_CANDIDATES = ("ops_plumbing_01", "ops_general_02", "ops_controls_01")
MANAGER_CANDIDATES = ("test1", "admin", "manager")


@dataclass(frozen=True)
class SmokeActors:
    manager: User
    support_owner: User
    support_applicant: User
    takeover_owner: User
    takeover_applicant: User


def _worker_context_options() -> tuple[Any, ...]:
    return (
        selectinload(User.worker_profile).selectinload(WorkerProfile.team),
        selectinload(User.worker_profile)
        .selectinload(WorkerProfile.skill_links)
        .selectinload(WorkerProfileSkill.skill),
    )


def _json_default(value: Any) -> Any:
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def _dump_json(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, default=_json_default, indent=2)


def _priority_order() -> Any:
    return case(
        (WorkOrder.priority == "high", 0),
        (WorkOrder.priority == "medium", 1),
        else_=2,
    )


def _user_summary(user: User) -> dict[str, Any]:
    profile = getattr(user, "worker_profile", None)
    team = getattr(profile, "team", None) if profile is not None else None
    return {
        "id": user.id,
        "username": user.username,
        "role": user.role,
        "team_id": getattr(profile, "team_id", None),
        "team_name": getattr(team, "name", None),
    }


def _work_order_summary(work_order: WorkOrder) -> dict[str, Any]:
    return {
        "id": work_order.id,
        "ticket_id": work_order.ticket_id,
        "status": work_order.status,
        "priority": work_order.priority,
        "building_id": work_order.building_id,
        "device_id": work_order.device_id,
        "issue_description": work_order.issue_description[:120],
    }


def _hall_entry_summary(entry: DispatchHallEntry | None) -> dict[str, Any] | None:
    if entry is None:
        return None
    return {
        "id": entry.id,
        "entry_type": entry.entry_type,
        "status": entry.status,
        "work_order_id": entry.work_order_id,
        "source_dispatch_id": entry.source_dispatch_id,
        "visibility_scope": entry.visibility_scope,
        "assigned_to": entry.assigned_to,
        "reason": entry.reason,
        "support_reason": entry.support_reason,
        "sla_stage": entry.sla_stage,
        "overdue_level": entry.overdue_level,
        "target_team_ids_json": entry.target_team_ids_json,
        "target_skill_tags_json": entry.target_skill_tags_json,
        "target_user_ids_json": entry.target_user_ids_json,
    }


def _application_summary(application: DispatchHallApplication | None) -> dict[str, Any] | None:
    if application is None:
        return None
    return {
        "id": application.id,
        "hall_entry_id": application.hall_entry_id,
        "applicant_user_id": application.applicant_user_id,
        "application_type": application.application_type,
        "status": application.status,
        "note": application.note,
    }


async def _load_first_user(db, usernames: tuple[str, ...], *, roles: set[str]) -> User | None:
    result = await db.execute(
        select(User)
        .options(*_worker_context_options())
        .where(User.username.in_(list(usernames)), User.role.in_(list(roles)), User.is_active.is_(True))
    )
    users_by_name = {user.username: user for user in result.scalars().all()}
    for username in usernames:
        user = users_by_name.get(username)
        if user is not None:
            return user
    return None


async def _load_fallback_user(db, *, roles: set[str], exclude_ids: set[str] | None = None) -> User | None:
    query = (
        select(User)
        .options(*_worker_context_options())
        .where(User.role.in_(list(roles)), User.is_active.is_(True))
        .order_by(User.username.asc())
        .limit(1)
    )
    if exclude_ids:
        query = query.where(User.id.notin_(list(exclude_ids)))
    result = await db.execute(query)
    return result.scalar_one_or_none()


async def _load_actors(db) -> SmokeActors:
    manager = await _load_first_user(db, MANAGER_CANDIDATES, roles={"admin", "manager"})
    if manager is None:
        manager = await _load_fallback_user(db, roles={"admin", "manager"})
    if manager is None:
        raise RuntimeError("缺少可用于联调的 admin/manager 用户")

    support_owner = await _load_first_user(db, SUPPORT_OWNER_CANDIDATES, roles={"ops"})
    if support_owner is None:
        support_owner = await _load_fallback_user(db, roles={"ops"})
    if support_owner is None:
        raise RuntimeError("缺少可用于联调的维修人员")

    support_applicant = await _load_first_user(db, SUPPORT_APPLICANT_CANDIDATES, roles={"ops"})
    if support_applicant is None or support_applicant.id == support_owner.id:
        support_applicant = await _load_fallback_user(db, roles={"ops"}, exclude_ids={support_owner.id})
    if support_applicant is None:
        raise RuntimeError("缺少第二个维修人员，无法构造协同申请")

    takeover_owner = await _load_first_user(db, TAKEOVER_OWNER_CANDIDATES, roles={"ops"})
    if takeover_owner is None:
        takeover_owner = await _load_fallback_user(
            db,
            roles={"ops"},
            exclude_ids={support_applicant.id},
        )
    if takeover_owner is None:
        raise RuntimeError("缺少可用于接管样本的原责任人")

    takeover_applicant = await _load_first_user(db, TAKEOVER_APPLICANT_CANDIDATES, roles={"ops"})
    if takeover_applicant is None or takeover_applicant.id == takeover_owner.id:
        takeover_applicant = await _load_fallback_user(db, roles={"ops"}, exclude_ids={takeover_owner.id})
    if takeover_applicant is None:
        raise RuntimeError("缺少第二个维修人员，无法构造接管申请")

    return SmokeActors(
        manager=manager,
        support_owner=support_owner,
        support_applicant=support_applicant,
        takeover_owner=takeover_owner,
        takeover_applicant=takeover_applicant,
    )


async def _choose_visible_applicant(
    db,
    *,
    hall_entry: DispatchHallEntry,
    preferred: User,
    exclude_ids: set[str],
) -> User:
    if preferred.id not in exclude_ids and can_view_dispatch_hall_entry(hall_entry, preferred):
        return preferred

    result = await db.execute(
        select(User)
        .options(*_worker_context_options())
        .where(User.role == "ops", User.is_active.is_(True), User.id.notin_(list(exclude_ids)))
        .order_by(User.username.asc())
    )
    for user in result.scalars().all():
        if can_view_dispatch_hall_entry(hall_entry, user):
            return user
    raise RuntimeError("未找到可见范围内的维修人员，无法构造大厅申请")


async def _load_pending_work_orders(db, *, sample_size: int) -> list[WorkOrder]:
    result = await db.execute(
        select(WorkOrder)
        .options(selectinload(WorkOrder.anomaly_links))
        .where(WorkOrder.status == "pending_dispatch")
        .order_by(_priority_order(), WorkOrder.pending_dispatch_at.asc().nulls_last(), WorkOrder.created_at.asc())
        .limit(sample_size)
    )
    work_orders = list(result.scalars().all())
    if len(work_orders) < sample_size:
        raise RuntimeError(f"待派工样本不足：需要 {sample_size} 张，实际 {len(work_orders)} 张")

    clean_samples: list[WorkOrder] = []
    for work_order in work_orders:
        current_dispatch = await get_current_dispatch_task(db, work_order=work_order)
        if current_dispatch is None:
            clean_samples.append(work_order)
    if len(clean_samples) < sample_size:
        raise RuntimeError("待派工样本中存在 current_dispatch，无法安全构造小样本联调")
    return clean_samples[:sample_size]


async def _count_hall_items(db) -> dict[str, int]:
    entries = await db.execute(select(DispatchHallEntry.status, DispatchHallEntry.entry_type))
    applications = await db.execute(select(DispatchHallApplication.status, DispatchHallApplication.application_type))

    entry_counts: dict[str, int] = {}
    for status, entry_type in entries.all():
        entry_counts[f"{entry_type}:{status}"] = entry_counts.get(f"{entry_type}:{status}", 0) + 1

    application_counts: dict[str, int] = {}
    for status, application_type in applications.all():
        application_counts[f"{application_type}:{status}"] = (
            application_counts.get(f"{application_type}:{status}", 0) + 1
        )

    return {
        "entries_total": sum(entry_counts.values()),
        "applications_total": sum(application_counts.values()),
        "entry_counts": entry_counts,
        "application_counts": application_counts,
    }


async def _prepare_support_sample(db, *, work_order: WorkOrder, actors: SmokeActors) -> dict[str, Any]:
    await assign_work_order(
        db,
        work_order=work_order,
        assigned_user=actors.support_owner,
        actor_type="admin",
        actor_id=actors.manager.id,
        dispatch_mode="manual",
        notes="工单大厅联调：协同链路样本派工",
    )
    dispatch = await get_current_dispatch_task(db, work_order=work_order)
    if dispatch is None:
        raise RuntimeError(f"{work_order.ticket_id} 派工后未生成 current_dispatch")
    await update_dispatch_task_action(
        db,
        work_order=work_order,
        dispatch_task=dispatch,
        action="accept",
        actor_type="worker",
        actor_id=actors.support_owner.id,
        notes="工单大厅联调：责任人已接单",
    )
    await update_dispatch_task_action(
        db,
        work_order=work_order,
        dispatch_task=dispatch,
        action="arrive",
        actor_type="worker",
        actor_id=actors.support_owner.id,
        notes="工单大厅联调：责任人已到场",
    )
    await update_dispatch_task_action(
        db,
        work_order=work_order,
        dispatch_task=dispatch,
        action="start",
        actor_type="worker",
        actor_id=actors.support_owner.id,
        notes="工单大厅联调：开始处理并准备申请协同",
    )
    await update_dispatch_task_action(
        db,
        work_order=work_order,
        dispatch_task=dispatch,
        action="request_support",
        actor_type="worker",
        actor_id=actors.support_owner.id,
        notes="工单大厅联调：需要跨班组协同确认",
    )

    hall_entry = (
        await db.execute(
            select(DispatchHallEntry)
            .where(
                DispatchHallEntry.source_dispatch_id == dispatch.id,
                DispatchHallEntry.entry_type == "support_request",
            )
            .order_by(DispatchHallEntry.created_at.desc())
            .limit(1)
        )
    ).scalar_one()
    applicant = await _choose_visible_applicant(
        db,
        hall_entry=hall_entry,
        preferred=actors.support_applicant,
        exclude_ids={actors.support_owner.id},
    )
    application = await apply_to_dispatch_hall_entry(
        db,
        hall_entry=hall_entry,
        applicant_user_id=applicant.id,
        application_type="support",
        note="工单大厅联调：我可协同处理",
    )
    return {
        "work_order": _work_order_summary(work_order),
        "dispatch_id": dispatch.id,
        "dispatch_status": dispatch.dispatch_status,
        "owner": _user_summary(actors.support_owner),
        "applicant": _user_summary(applicant),
        "hall_entry": _hall_entry_summary(hall_entry),
        "application": _application_summary(application),
    }


async def _prepare_takeover_sample(db, *, work_order: WorkOrder, actors: SmokeActors) -> dict[str, Any]:
    await assign_work_order(
        db,
        work_order=work_order,
        assigned_user=actors.takeover_owner,
        actor_type="admin",
        actor_id=actors.manager.id,
        dispatch_mode="manual",
        notes="工单大厅联调：接管链路样本派工",
    )
    dispatch = await get_current_dispatch_task(db, work_order=work_order)
    if dispatch is None:
        raise RuntimeError(f"{work_order.ticket_id} 派工后未生成 current_dispatch")
    hall_entry = await create_or_reopen_takeover_hall_entry(
        db,
        work_order=work_order,
        source_dispatch_id=dispatch.id,
        source_assignee_id=actors.takeover_owner.id,
        created_by=None,
        reason="工单大厅联调：模拟超时待接管，等待管理员确认",
        sla_stage=dispatch.dispatch_status,
        overdue_level="overdue",
    )
    applicant = await _choose_visible_applicant(
        db,
        hall_entry=hall_entry,
        preferred=actors.takeover_applicant,
        exclude_ids={actors.takeover_owner.id},
    )
    application = await apply_to_dispatch_hall_entry(
        db,
        hall_entry=hall_entry,
        applicant_user_id=applicant.id,
        application_type="takeover",
        note="工单大厅联调：我可接管处理",
    )
    return {
        "work_order": _work_order_summary(work_order),
        "dispatch_id": dispatch.id,
        "dispatch_status": dispatch.dispatch_status,
        "owner": _user_summary(actors.takeover_owner),
        "applicant": _user_summary(applicant),
        "hall_entry": _hall_entry_summary(hall_entry),
        "application": _application_summary(application),
    }


async def run(*, apply: bool) -> dict[str, Any]:
    async with AsyncSessionLocal() as db:
        actors = await _load_actors(db)
        work_orders = await _load_pending_work_orders(db, sample_size=2)
        before_counts = await _count_hall_items(db)

        report: dict[str, Any] = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "apply": apply,
            "actors": {
                "manager": _user_summary(actors.manager),
                "support_owner": _user_summary(actors.support_owner),
                "support_applicant": _user_summary(actors.support_applicant),
                "takeover_owner": _user_summary(actors.takeover_owner),
                "takeover_applicant": _user_summary(actors.takeover_applicant),
            },
            "selected_work_orders": [_work_order_summary(item) for item in work_orders],
            "before_counts": before_counts,
            "samples": {},
        }

        if not apply:
            report["message"] = "dry-run only; rerun with --apply to create the two hall samples"
            return report

        report["samples"]["support_request"] = await _prepare_support_sample(
            db,
            work_order=work_orders[0],
            actors=actors,
        )
        report["samples"]["takeover_candidate"] = await _prepare_takeover_sample(
            db,
            work_order=work_orders[1],
            actors=actors,
        )

        await db.commit()
        await delete_cache_by_prefix("workorders:")
        await delete_cache_by_prefix("incidents:")
        await delete_cache_by_prefix("dispatch_hall:")

    async with AsyncSessionLocal() as db:
        report["after_counts"] = await _count_hall_items(db)
    return report


def _write_report(report: dict[str, Any]) -> Path:
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    suffix = "apply" if report.get("apply") else "dry_run"
    path = RUNTIME_DIR / f"dispatch_hall_live_smoke_{suffix}_{ts}.json"
    path.write_text(_dump_json(report), encoding="utf-8")
    return path


def main() -> None:
    parser = argparse.ArgumentParser(description="Prepare live dispatch hall smoke-test samples.")
    parser.add_argument("--apply", action="store_true", help="Create real dispatch hall samples.")
    args = parser.parse_args()

    report = asyncio.run(run(apply=args.apply))
    report_path = _write_report(report)
    print(_dump_json(report))
    print(f"\n[REPORT] {report_path}")
    if not args.apply:
        print("[DRY-RUN] No database changes were committed. Re-run with --apply to create samples.")


if __name__ == "__main__":
    main()
