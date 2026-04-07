"""
Small-batch dispatch pilot for pending work orders.

Default behavior is dry-run only. The script scans pending_dispatch work orders,
evaluates current candidates, and only selects high-confidence samples.

Usage:
    cd backend
    python scripts/pilot_dispatch_batch.py
    python scripts/pilot_dispatch_batch.py --apply
    python scripts/pilot_dispatch_batch.py --sample-size 10 --scan-limit 200 --min-score 100 --min-gap 15
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import case, select
from sqlalchemy.orm import selectinload

from app.core.cache import delete_cache_by_prefix
from app.db.models import User, WorkOrder, WorkerProfile, WorkerProfileSkill
from app.db.session import AsyncSessionLocal
from app.services.dispatch_service import list_dispatch_tasks
from app.services.work_order_service import assign_work_order, list_dispatch_candidates

ROOT_DIR = Path(__file__).resolve().parents[1]
RUNTIME_DIR = ROOT_DIR / "runtime" / "dispatch_pilot"


@dataclass
class SelectionDecision:
    ticket_id: str
    work_order_id: str
    building_id: str
    priority: str
    requirement: dict[str, Any]
    candidate_count: int
    chosen_candidate: dict[str, Any] | None
    top_candidate: dict[str, Any] | None
    second_candidate: dict[str, Any] | None
    score_gap: int | None
    skip_reason: str | None


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


async def _load_manager(db, username: str) -> User:
    result = await db.execute(
        select(User)
        .where(User.username == username)
        .limit(1)
    )
    manager = result.scalar_one_or_none()
    if manager is None:
        raise RuntimeError(f"未找到调度账号：{username}")
    if manager.role not in {"manager", "admin"}:
        raise RuntimeError(f"账号 {username} 不是 manager/admin，当前 role={manager.role}")
    if not manager.is_active:
        raise RuntimeError(f"账号 {username} 已被禁用")
    return manager


async def _load_worker_by_id(db, user_id: str) -> User | None:
    result = await db.execute(
        select(User)
        .options(
            selectinload(User.worker_profile).selectinload(WorkerProfile.team),
            selectinload(User.worker_profile)
            .selectinload(WorkerProfile.skill_links)
            .selectinload(WorkerProfileSkill.skill),
        )
        .where(User.id == user_id)
        .limit(1)
    )
    return result.scalar_one_or_none()


async def _load_work_order_by_id(db, work_order_id: str) -> WorkOrder | None:
    result = await db.execute(
        select(WorkOrder)
        .options(selectinload(WorkOrder.anomaly_links))
        .where(WorkOrder.id == work_order_id)
        .limit(1)
    )
    return result.scalar_one_or_none()


async def _scan_pending_work_orders(
    db,
    *,
    scan_limit: int,
) -> list[WorkOrder]:
    result = await db.execute(
        select(WorkOrder)
        .options(selectinload(WorkOrder.anomaly_links))
        .where(WorkOrder.status == "pending_dispatch")
        .order_by(_priority_order(), WorkOrder.pending_dispatch_at.asc().nullsfirst(), WorkOrder.created_at.asc())
        .limit(scan_limit)
    )
    return list(result.scalars().all())


def _capacity_left(candidate: dict[str, Any], planned_assignments: dict[str, int]) -> int:
    current = int(candidate.get("current_active_orders") or 0)
    max_active = int(candidate.get("max_active_orders") or 4)
    planned = planned_assignments.get(candidate["user_id"], 0)
    return max_active - current - planned


def _pick_candidate(
    *,
    candidates: list[dict[str, Any]],
    planned_assignments: dict[str, int],
    min_score: int,
    min_gap: int,
) -> tuple[dict[str, Any] | None, str | None, dict[str, Any] | None, dict[str, Any] | None, int | None]:
    if not candidates:
        return None, "no_candidates", None, None, None

    top_candidate = candidates[0]
    second_candidate = candidates[1] if len(candidates) > 1 else None
    second_score = int(second_candidate.get("score") or 0) if second_candidate else None
    score_gap = int(top_candidate.get("score") or 0) - second_score if second_score is not None else None

    if int(top_candidate.get("score") or 0) < min_score:
        return None, "top_score_below_threshold", top_candidate, second_candidate, score_gap
    if score_gap is not None and score_gap < min_gap:
        return None, "score_gap_below_threshold", top_candidate, second_candidate, score_gap
    if _capacity_left(top_candidate, planned_assignments) <= 0:
        return None, "top_candidate_over_capacity", top_candidate, second_candidate, score_gap

    return top_candidate, None, top_candidate, second_candidate, score_gap


def _selection_reason(
    *,
    top_candidate: dict[str, Any],
    score_gap: int | None,
    requirement: dict[str, Any],
) -> str:
    matched = top_candidate.get("matched_skill_names") or []
    matched_text = " / ".join(matched[:3]) if matched else "基础巡检"
    gap_text = f"，领先第二候选 {score_gap} 分" if score_gap is not None else ""
    return (
        "小批量试运行派工：按候选排序选择第一候选人，"
        f"技能匹配={matched_text}，"
        f"score={top_candidate.get('score')}"
        f"{gap_text}，"
        f"需求={','.join(requirement.get('required_skills') or [])}"
    )


async def build_pilot_plan(
    *,
    sample_size: int,
    scan_limit: int,
    min_score: int,
    min_gap: int,
) -> dict[str, Any]:
    async with AsyncSessionLocal() as db:
        pending_work_orders = await _scan_pending_work_orders(db, scan_limit=scan_limit)
        planned_assignments: dict[str, int] = defaultdict(int)
        selected: list[SelectionDecision] = []
        skipped: list[SelectionDecision] = []

        for work_order in pending_work_orders:
            payload = await list_dispatch_candidates(db, work_order=work_order)
            candidates = payload["candidates"]
            chosen, skip_reason, top_candidate, second_candidate, score_gap = _pick_candidate(
                candidates=candidates,
                planned_assignments=planned_assignments,
                min_score=min_score,
                min_gap=min_gap,
            )

            decision = SelectionDecision(
                ticket_id=work_order.ticket_id,
                work_order_id=work_order.id,
                building_id=work_order.building_id,
                priority=work_order.priority,
                requirement=payload["requirement"],
                candidate_count=len(candidates),
                chosen_candidate=chosen,
                top_candidate=top_candidate,
                second_candidate=second_candidate,
                score_gap=score_gap,
                skip_reason=skip_reason,
            )

            if chosen is None:
                skipped.append(decision)
                continue

            planned_assignments[chosen["user_id"]] += 1
            selected.append(decision)
            if len(selected) >= sample_size:
                break

        return {
            "mode": "dry_run",
            "generated_at": datetime.now(timezone.utc),
            "sample_size": sample_size,
            "scan_limit": scan_limit,
            "min_score": min_score,
            "min_gap": min_gap,
            "pending_scanned": len(pending_work_orders),
            "selected": [_decision_to_dict(item) for item in selected],
            "skipped": [_decision_to_dict(item) for item in skipped[:30]],
            "planned_assignment_count_by_user": dict(planned_assignments),
        }


def _decision_to_dict(item: SelectionDecision) -> dict[str, Any]:
    return {
        "ticket_id": item.ticket_id,
        "work_order_id": item.work_order_id,
        "building_id": item.building_id,
        "priority": item.priority,
        "requirement": item.requirement,
        "candidate_count": item.candidate_count,
        "chosen_candidate": item.chosen_candidate,
        "top_candidate": item.top_candidate,
        "second_candidate": item.second_candidate,
        "score_gap": item.score_gap,
        "skip_reason": item.skip_reason,
    }


async def apply_pilot_plan(
    *,
    manager_username: str,
    plan: dict[str, Any],
) -> dict[str, Any]:
    selected = list(plan["selected"])
    applied: list[dict[str, Any]] = []
    failed: list[dict[str, Any]] = []

    async with AsyncSessionLocal() as db:
        manager = await _load_manager(db, manager_username)

        for item in selected:
            work_order = await _load_work_order_by_id(db, item["work_order_id"])
            if work_order is None:
                failed.append({
                    "ticket_id": item["ticket_id"],
                    "reason": "work_order_missing",
                })
                continue
            if work_order.status != "pending_dispatch":
                failed.append({
                    "ticket_id": item["ticket_id"],
                    "reason": f"status_changed:{work_order.status}",
                })
                continue

            chosen_candidate = item.get("chosen_candidate") or {}
            assigned_user = await _load_worker_by_id(db, chosen_candidate.get("user_id", ""))
            if assigned_user is None:
                failed.append({
                    "ticket_id": item["ticket_id"],
                    "reason": "assigned_user_missing",
                })
                continue

            try:
                await assign_work_order(
                    db,
                    work_order=work_order,
                    assigned_user=assigned_user,
                    actor_type="admin",
                    actor_id=manager.id,
                    dispatch_mode="manual",
                    candidate_snapshot=chosen_candidate,
                    notes=_selection_reason(
                        top_candidate=chosen_candidate,
                        score_gap=item.get("score_gap"),
                        requirement=item.get("requirement") or {},
                    ),
                )
                await db.commit()
                await db.refresh(work_order)
                applied.append({
                    "ticket_id": item["ticket_id"],
                    "work_order_id": work_order.id,
                    "dispatch_id": work_order.current_dispatch_id,
                    "assigned_to": assigned_user.username,
                    "assigned_to_user_id": assigned_user.id,
                    "status": work_order.status,
                })
            except Exception as exc:
                await db.rollback()
                failed.append({
                    "ticket_id": item["ticket_id"],
                    "reason": f"{type(exc).__name__}: {exc}",
                })

    if applied:
        await delete_cache_by_prefix("workorders:")
        await delete_cache_by_prefix("incidents:")

    return {
        "mode": "apply",
        "manager_username": manager_username,
        "applied": applied,
        "failed": failed,
    }


async def collect_post_check(*, assigned_user_ids: list[str]) -> dict[str, Any]:
    async with AsyncSessionLocal() as db:
        dispatch_items, total = await list_dispatch_tasks(
            db,
            current_only=True,
            page=1,
            page_size=100,
        )
        by_user = Counter()
        current_sample: list[dict[str, Any]] = []
        user_name_map: dict[str, str] = {}

        if assigned_user_ids:
            result = await db.execute(
                select(User.id, User.username).where(User.id.in_(assigned_user_ids))
            )
            user_name_map = {str(row[0]): str(row[1]) for row in result.all()}

        for item in dispatch_items:
            if item.assigned_to in assigned_user_ids:
                by_user[item.assigned_to] += 1
            current_sample.append({
                "dispatch_id": item.id,
                "work_order_id": item.work_order_id,
                "ticket_id": None,
                "assigned_to": item.assigned_to,
                "assigned_to_name": user_name_map.get(item.assigned_to or "", item.assigned_to),
                "dispatch_status": item.dispatch_status,
                "attempt_no": item.attempt_no,
                "assigned_at": item.assigned_at,
            })

        return {
            "current_dispatch_total": total,
            "current_dispatch_by_user": {
                user_name_map.get(user_id, user_id): count for user_id, count in by_user.items()
            },
            "current_dispatch_sample": current_sample[:20],
        }


def _persist_report(report: dict[str, Any]) -> Path:
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    path = RUNTIME_DIR / f"dispatch_pilot_{stamp}.json"
    path.write_text(_dump_json(report), encoding="utf-8")
    return path


def _print_report(report: dict[str, Any], *, as_json: bool) -> None:
    if as_json:
        print(_dump_json(report))
        return

    print("")
    print(f"[MODE] {report['mode']}")
    if "sample_size" in report:
        print(
            f"[SCAN] pending_scanned={report['pending_scanned']} "
            f"selected={len(report['selected'])} "
            f"sample_size={report['sample_size']}"
        )

    if report.get("selected"):
        print("[SELECTED]")
        for item in report["selected"]:
            chosen = item["chosen_candidate"] or {}
            print(
                "  - "
                f"{item['ticket_id']} | {item['priority']} | {item['building_id']} | "
                f"skill={','.join(item['requirement'].get('required_skills') or [])} | "
                f"assign={chosen.get('username')} | score={chosen.get('score')} | gap={item.get('score_gap')}"
            )

    if report.get("skipped"):
        reason_counter = Counter(item["skip_reason"] for item in report["skipped"] if item.get("skip_reason"))
        print("[SKIPPED]")
        for reason, count in reason_counter.items():
            print(f"  - {reason}: {count}")

    if report.get("planned_assignment_count_by_user"):
        print("[PLANNED LOAD]")
        for user_id, count in report["planned_assignment_count_by_user"].items():
            print(f"  - {user_id}: +{count}")

    if report.get("applied"):
        print("[APPLIED]")
        for item in report["applied"]:
            print(
                "  - "
                f"{item['ticket_id']} -> {item['assigned_to']} | dispatch_id={item['dispatch_id']} | status={item['status']}"
            )
    if report.get("failed"):
        print("[FAILED]")
        for item in report["failed"]:
            print(f"  - {item['ticket_id']}: {item['reason']}")

    post_check = report.get("post_check")
    if post_check:
        print(f"[POST-CHECK] current_dispatch_total={post_check['current_dispatch_total']}")
        for username, count in post_check["current_dispatch_by_user"].items():
            print(f"  - {username}: {count}")

    if report.get("report_path"):
        print(f"[REPORT] {report['report_path']}")


async def main() -> int:
    parser = argparse.ArgumentParser(description="Run a small-batch dispatch pilot on pending work orders.")
    parser.add_argument("--apply", action="store_true", help="Persist dispatch tasks to the database.")
    parser.add_argument("--sample-size", type=int, default=10, help="How many work orders to select.")
    parser.add_argument("--scan-limit", type=int, default=40, help="How many pending work orders to scan.")
    parser.add_argument("--min-score", type=int, default=100, help="Minimum top candidate score.")
    parser.add_argument("--min-gap", type=int, default=10, help="Minimum score gap vs second candidate.")
    parser.add_argument("--manager-username", default="test1", help="Manager/admin username used as dispatch actor.")
    parser.add_argument("--json", action="store_true", help="Print JSON output.")
    args = parser.parse_args()

    plan = await build_pilot_plan(
        sample_size=args.sample_size,
        scan_limit=args.scan_limit,
        min_score=args.min_score,
        min_gap=args.min_gap,
    )

    report: dict[str, Any] = dict(plan)
    if args.apply:
        apply_result = await apply_pilot_plan(
            manager_username=args.manager_username,
            plan=plan,
        )
        report.update(apply_result)
        assigned_user_ids = [item["assigned_to_user_id"] for item in apply_result.get("applied", [])]
        report["post_check"] = await collect_post_check(assigned_user_ids=assigned_user_ids)
        report_path = _persist_report(report)
        report["report_path"] = str(report_path)

    _print_report(report, as_json=args.json)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
