"""
Bootstrap dispatch workers, teams, skills, and profiles for phase-3 rollout.

Default behavior is dry-run only.

Usage:
    cd backend
    python scripts/bootstrap_dispatch_workers.py
    python scripts/bootstrap_dispatch_workers.py --apply --reset-passwords
    python scripts/bootstrap_dispatch_workers.py --json
"""
from __future__ import annotations

import argparse
import asyncio
import json
import ssl
import sys
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import asyncpg

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.security import hash_password

ROOT_DIR = Path(__file__).resolve().parents[1]
ENV_PATH = ROOT_DIR / ".env"
RUNTIME_DIR = ROOT_DIR / "runtime" / "dispatch_worker_bootstrap"
DEFAULT_PASSWORD = "test1234"


class DryRunRollback(Exception):
    """Internal control-flow exception used to rollback dry-run transactions."""


@dataclass(frozen=True)
class TeamSeed:
    id: str
    team_code: str
    name: str
    description: str


@dataclass(frozen=True)
class SkillSeed:
    id: str
    code: str
    name: str
    category: str
    description: str


@dataclass(frozen=True)
class SkillLinkSeed:
    code: str
    proficiency: int
    is_primary: bool


@dataclass(frozen=True)
class WorkerSeed:
    username: str
    phone: str
    team_code: str
    job_title: str
    shift_status: str
    dispatch_enabled: bool
    max_active_orders: int
    accepts_emergency: bool
    notes: str
    skills: tuple[SkillLinkSeed, ...]


TEAM_SEEDS: tuple[TeamSeed, ...] = (
    TeamSeed(
        id="team_ops_general",
        team_code="ops_general",
        name="综合运维班",
        description="负责基础巡检、跨专业支援和兜底派工。",
    ),
    TeamSeed(
        id="team_hvac",
        team_code="hvac",
        name="暖通班",
        description="负责空调、冷机、风机盘管、供回水等暖通类故障。",
    ),
    TeamSeed(
        id="team_electrical",
        team_code="electrical",
        name="电气班",
        description="负责照明、配电、电力中断与电气安全类故障。",
    ),
    TeamSeed(
        id="team_plumbing",
        team_code="plumbing",
        name="给排水班",
        description="负责漏水、阀门、给排水和管路类故障。",
    ),
    TeamSeed(
        id="team_controls",
        team_code="controls",
        name="自控班",
        description="负责 BMS、自控联动、传感与控制类故障。",
    ),
)

SKILL_SEEDS: tuple[SkillSeed, ...] = (
    SkillSeed(
        id="skill_inspection",
        code="inspection",
        name="基础巡检",
        category="general",
        description="适合做基础排查、复位和现场确认。",
    ),
    SkillSeed(
        id="skill_hvac",
        code="hvac",
        name="暖通维修",
        category="hvac",
        description="空调、冷机、供回水、风机等暖通问题处理。",
    ),
    SkillSeed(
        id="skill_electrical",
        code="electrical",
        name="电气维修",
        category="electrical",
        description="配电、照明、电力与跳闸类问题处理。",
    ),
    SkillSeed(
        id="skill_plumbing",
        code="plumbing",
        name="给排水维修",
        category="plumbing",
        description="漏水、阀门、排水和管路类问题处理。",
    ),
    SkillSeed(
        id="skill_controls",
        code="controls",
        name="自控运维",
        category="controls",
        description="BMS、传感、联动、自控类问题处理。",
    ),
)

WORKER_SEEDS: tuple[WorkerSeed, ...] = (
    WorkerSeed(
        username="test2",
        phone="13800000002",
        team_code="ops_general",
        job_title="综合运维工程师",
        shift_status="on_duty",
        dispatch_enabled=True,
        max_active_orders=6,
        accepts_emergency=True,
        notes="历史测试账号升级为真实派工总值班。",
        skills=(
            SkillLinkSeed(code="inspection", proficiency=5, is_primary=True),
            SkillLinkSeed(code="controls", proficiency=3, is_primary=False),
        ),
    ),
    WorkerSeed(
        username="ops_hvac_01",
        phone="13800000011",
        team_code="hvac",
        job_title="暖通工程师",
        shift_status="on_duty",
        dispatch_enabled=True,
        max_active_orders=4,
        accepts_emergency=True,
        notes="暖通专业首班值守。",
        skills=(
            SkillLinkSeed(code="hvac", proficiency=5, is_primary=True),
            SkillLinkSeed(code="inspection", proficiency=4, is_primary=False),
        ),
    ),
    WorkerSeed(
        username="ops_electrical_01",
        phone="13800000012",
        team_code="electrical",
        job_title="电气工程师",
        shift_status="on_duty",
        dispatch_enabled=True,
        max_active_orders=4,
        accepts_emergency=True,
        notes="电气专业首班值守。",
        skills=(
            SkillLinkSeed(code="electrical", proficiency=5, is_primary=True),
            SkillLinkSeed(code="inspection", proficiency=4, is_primary=False),
        ),
    ),
    WorkerSeed(
        username="ops_plumbing_01",
        phone="13800000013",
        team_code="plumbing",
        job_title="给排水工程师",
        shift_status="on_duty",
        dispatch_enabled=True,
        max_active_orders=4,
        accepts_emergency=True,
        notes="给排水专业首班值守。",
        skills=(
            SkillLinkSeed(code="plumbing", proficiency=5, is_primary=True),
            SkillLinkSeed(code="inspection", proficiency=4, is_primary=False),
        ),
    ),
    WorkerSeed(
        username="ops_controls_01",
        phone="13800000014",
        team_code="controls",
        job_title="自控工程师",
        shift_status="on_duty",
        dispatch_enabled=True,
        max_active_orders=4,
        accepts_emergency=True,
        notes="自控专业首班值守。",
        skills=(
            SkillLinkSeed(code="controls", proficiency=5, is_primary=True),
            SkillLinkSeed(code="inspection", proficiency=4, is_primary=False),
        ),
    ),
    WorkerSeed(
        username="ops_general_02",
        phone="13800000015",
        team_code="ops_general",
        job_title="综合运维工程师",
        shift_status="standby",
        dispatch_enabled=True,
        max_active_orders=3,
        accepts_emergency=False,
        notes="综合运维备用班，适合作为待命补位。",
        skills=(
            SkillLinkSeed(code="inspection", proficiency=5, is_primary=True),
            SkillLinkSeed(code="electrical", proficiency=3, is_primary=False),
        ),
    ),
)


def _load_env(path: Path) -> dict[str, str]:
    env: dict[str, str] = {}
    if not path.exists():
        return env
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        env[key.strip()] = value.strip()
    return env


def _json_default(value: Any) -> Any:
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def _dump_json(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, default=_json_default)


async def _connect(retries: int = 3) -> asyncpg.Connection:
    env = _load_env(ENV_PATH)
    url = env.get("SYNC_DATABASE_URL") or env.get("DATABASE_URL")
    if not url:
        raise RuntimeError("未在 backend/.env 中找到 SYNC_DATABASE_URL / DATABASE_URL")

    ssl_ctx = ssl.create_default_context()
    ssl_ctx.check_hostname = False
    ssl_ctx.verify_mode = ssl.CERT_NONE

    last_error: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            return await asyncpg.connect(url, ssl=ssl_ctx)
        except Exception as exc:  # pragma: no cover - operational retry path
            last_error = exc
            if attempt >= retries:
                break
            await asyncio.sleep(attempt)
    assert last_error is not None
    raise last_error


async def _fetch_building_ids(conn: asyncpg.Connection) -> list[str]:
    rows = await conn.fetch("SELECT building_id FROM buildings ORDER BY building_id")
    return [str(row["building_id"]) for row in rows]


async def _ensure_team(
    conn: asyncpg.Connection,
    *,
    seed: TeamSeed,
    building_scope_json: str,
    apply_changes: bool,
) -> dict[str, Any]:
    existing = await conn.fetchrow(
        """
        SELECT id, team_code, name, description, service_buildings_json, is_active
        FROM worker_teams
        WHERE team_code = $1
           OR id = $2
        ORDER BY CASE WHEN team_code = $1 THEN 0 ELSE 1 END
        LIMIT 1
        """,
        seed.team_code,
        seed.id,
    )
    if existing is None:
        if apply_changes:
            await conn.execute(
                """
                INSERT INTO worker_teams (
                    id,
                    team_code,
                    name,
                    description,
                    service_buildings_json,
                    is_active
                ) VALUES ($1, $2, $3, $4, $5, TRUE)
                """,
                seed.id,
                seed.team_code,
                seed.name,
                seed.description,
                building_scope_json,
            )
        return {
            "action": "create",
            "team_code": seed.team_code,
            "team_id": seed.id,
            "name": seed.name,
        }

    if apply_changes:
        await conn.execute(
            """
            UPDATE worker_teams
            SET team_code = $1,
                name = $2,
                description = $3,
                service_buildings_json = $4,
                is_active = TRUE
            WHERE id = $5
            """,
            seed.team_code,
            seed.name,
            seed.description,
            building_scope_json,
            existing["id"],
        )
    return {
        "action": "update",
        "team_code": seed.team_code,
        "team_id": str(existing["id"]),
        "name": seed.name,
    }


async def _ensure_skill(
    conn: asyncpg.Connection,
    *,
    seed: SkillSeed,
    apply_changes: bool,
) -> dict[str, Any]:
    existing = await conn.fetchrow(
        """
        SELECT id, code, name, category, description, is_active
        FROM worker_skills
        WHERE code = $1
           OR id = $2
        ORDER BY CASE WHEN code = $1 THEN 0 ELSE 1 END
        LIMIT 1
        """,
        seed.code,
        seed.id,
    )
    if existing is None:
        if apply_changes:
            await conn.execute(
                """
                INSERT INTO worker_skills (
                    id,
                    code,
                    name,
                    category,
                    description,
                    is_active
                ) VALUES ($1, $2, $3, $4, $5, TRUE)
                """,
                seed.id,
                seed.code,
                seed.name,
                seed.category,
                seed.description,
            )
        return {
            "action": "create",
            "code": seed.code,
            "skill_id": seed.id,
            "name": seed.name,
        }

    if apply_changes:
        await conn.execute(
            """
            UPDATE worker_skills
            SET code = $1,
                name = $2,
                category = $3,
                description = $4,
                is_active = TRUE
            WHERE id = $5
            """,
            seed.code,
            seed.name,
            seed.category,
            seed.description,
            existing["id"],
        )
    return {
        "action": "update",
        "code": seed.code,
        "skill_id": str(existing["id"]),
        "name": seed.name,
    }


async def _ensure_user(
    conn: asyncpg.Connection,
    *,
    seed: WorkerSeed,
    reset_passwords: bool,
    apply_changes: bool,
) -> dict[str, Any]:
    existing = await conn.fetchrow(
        """
        SELECT id, username, role, is_active, phone
        FROM users
        WHERE username = $1
        """,
        seed.username,
    )
    if existing is None:
        user_id = str(uuid.uuid4())
        if apply_changes:
            await conn.execute(
                """
                INSERT INTO users (
                    id,
                    username,
                    hashed_password,
                    phone,
                    role,
                    is_active
                ) VALUES ($1, $2, $3, $4, 'ops', TRUE)
                """,
                user_id,
                seed.username,
                hash_password(DEFAULT_PASSWORD),
                seed.phone,
            )
        return {
            "action": "create",
            "user_id": user_id,
            "username": seed.username,
            "password_reset": True,
        }

    if apply_changes:
        if reset_passwords:
            await conn.execute(
                """
                UPDATE users
                SET role = 'ops',
                    is_active = TRUE,
                    phone = $1,
                    hashed_password = $2
                WHERE id = $3
                """,
                seed.phone,
                hash_password(DEFAULT_PASSWORD),
                existing["id"],
            )
        else:
            await conn.execute(
                """
                UPDATE users
                SET role = 'ops',
                    is_active = TRUE,
                    phone = $1
                WHERE id = $2
                """,
                seed.phone,
                existing["id"],
            )
    return {
        "action": "update",
        "user_id": str(existing["id"]),
        "username": seed.username,
        "password_reset": bool(reset_passwords),
    }


async def _ensure_profile(
    conn: asyncpg.Connection,
    *,
    user_id: str,
    team_id: str,
    seed: WorkerSeed,
    building_scope_json: str,
    apply_changes: bool,
) -> dict[str, Any]:
    existing = await conn.fetchrow(
        """
        SELECT user_id
        FROM worker_profiles
        WHERE user_id = $1
        """,
        user_id,
    )
    now = datetime.now(timezone.utc)
    if existing is None:
        if apply_changes:
            await conn.execute(
                """
                INSERT INTO worker_profiles (
                    user_id,
                    team_id,
                    job_title,
                    shift_status,
                    dispatch_enabled,
                    max_active_orders,
                    accepts_emergency,
                    service_buildings_json,
                    notes,
                    created_at,
                    updated_at
                ) VALUES (
                    $1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $10
                )
                """,
                user_id,
                team_id,
                seed.job_title,
                seed.shift_status,
                seed.dispatch_enabled,
                seed.max_active_orders,
                seed.accepts_emergency,
                building_scope_json,
                seed.notes,
                now,
            )
        return {"action": "create", "user_id": user_id}

    if apply_changes:
        await conn.execute(
            """
            UPDATE worker_profiles
            SET team_id = $1,
                job_title = $2,
                shift_status = $3,
                dispatch_enabled = $4,
                max_active_orders = $5,
                accepts_emergency = $6,
                service_buildings_json = $7,
                notes = $8,
                updated_at = $9
            WHERE user_id = $10
            """,
            team_id,
            seed.job_title,
            seed.shift_status,
            seed.dispatch_enabled,
            seed.max_active_orders,
            seed.accepts_emergency,
            building_scope_json,
            seed.notes,
            now,
            user_id,
        )
    return {"action": "update", "user_id": user_id}


async def _ensure_profile_skill(
    conn: asyncpg.Connection,
    *,
    user_id: str,
    skill_id: str,
    skill_seed: SkillLinkSeed,
    apply_changes: bool,
) -> dict[str, Any]:
    existing = await conn.fetchrow(
        """
        SELECT profile_user_id, skill_id
        FROM worker_profile_skills
        WHERE profile_user_id = $1
          AND skill_id = $2
        """,
        user_id,
        skill_id,
    )
    now = datetime.now(timezone.utc)
    if existing is None:
        if apply_changes:
            await conn.execute(
                """
                INSERT INTO worker_profile_skills (
                    profile_user_id,
                    skill_id,
                    proficiency,
                    is_primary,
                    created_at
                ) VALUES ($1, $2, $3, $4, $5)
                """,
                user_id,
                skill_id,
                skill_seed.proficiency,
                skill_seed.is_primary,
                now,
            )
        return {"action": "create", "user_id": user_id, "skill_id": skill_id}

    if apply_changes:
        await conn.execute(
            """
            UPDATE worker_profile_skills
            SET proficiency = $1,
                is_primary = $2
            WHERE profile_user_id = $3
              AND skill_id = $4
            """,
            skill_seed.proficiency,
            skill_seed.is_primary,
            user_id,
            skill_id,
        )
    return {"action": "update", "user_id": user_id, "skill_id": skill_id}


async def _collect_post_check(conn: asyncpg.Connection) -> dict[str, Any]:
    dispatch_ready = await conn.fetchval(
        """
        SELECT COUNT(*)
        FROM users u
        JOIN worker_profiles wp ON wp.user_id = u.id
        WHERE u.role = 'ops'
          AND u.is_active = TRUE
          AND wp.dispatch_enabled = TRUE
          AND wp.shift_status IN ('on_duty', 'standby')
        """
    )
    rows = await conn.fetch(
        """
        SELECT
            u.username,
            wt.name AS team_name,
            wp.job_title,
            wp.shift_status,
            wp.dispatch_enabled,
            wp.max_active_orders,
            wp.accepts_emergency,
            wp.service_buildings_json
        FROM users u
        JOIN worker_profiles wp ON wp.user_id = u.id
        LEFT JOIN worker_teams wt ON wt.id = wp.team_id
        WHERE u.role = 'ops'
          AND u.is_active = TRUE
        ORDER BY u.username
        """
    )
    return {
        "dispatch_ready_workers": int(dispatch_ready or 0),
        "workers": [dict(row) for row in rows],
    }


async def bootstrap_workers(*, apply_changes: bool, reset_passwords: bool) -> dict[str, Any]:
    conn = await _connect()
    try:
        building_ids = await _fetch_building_ids(conn)
        building_scope_json = _dump_json(building_ids)

        summary: dict[str, Any] = {
            "mode": "apply" if apply_changes else "dry_run",
            "reset_passwords": reset_passwords,
            "default_password": DEFAULT_PASSWORD if reset_passwords or not apply_changes else DEFAULT_PASSWORD,
            "building_ids": building_ids,
            "teams": [],
            "skills": [],
            "users": [],
            "profiles": [],
            "profile_skills": [],
        }

        async with conn.transaction():
            team_id_by_code: dict[str, str] = {}
            for team_seed in TEAM_SEEDS:
                item = await _ensure_team(
                    conn,
                    seed=team_seed,
                    building_scope_json=building_scope_json,
                    apply_changes=apply_changes,
                )
                team_id_by_code[team_seed.team_code] = item["team_id"]
                summary["teams"].append(item)

            skill_id_by_code: dict[str, str] = {}
            for skill_seed in SKILL_SEEDS:
                item = await _ensure_skill(
                    conn,
                    seed=skill_seed,
                    apply_changes=apply_changes,
                )
                skill_id_by_code[skill_seed.code] = item["skill_id"]
                summary["skills"].append(item)

            for worker_seed in WORKER_SEEDS:
                user_item = await _ensure_user(
                    conn,
                    seed=worker_seed,
                    reset_passwords=reset_passwords,
                    apply_changes=apply_changes,
                )
                summary["users"].append(user_item)

                profile_item = await _ensure_profile(
                    conn,
                    user_id=user_item["user_id"],
                    team_id=team_id_by_code[worker_seed.team_code],
                    seed=worker_seed,
                    building_scope_json=building_scope_json,
                    apply_changes=apply_changes,
                )
                summary["profiles"].append(profile_item)

                for skill_link in worker_seed.skills:
                    profile_skill_item = await _ensure_profile_skill(
                        conn,
                        user_id=user_item["user_id"],
                        skill_id=skill_id_by_code[skill_link.code],
                        skill_seed=skill_link,
                        apply_changes=apply_changes,
                    )
                    profile_skill_item["skill_code"] = skill_link.code
                    profile_skill_item["username"] = worker_seed.username
                    summary["profile_skills"].append(profile_skill_item)

            if not apply_changes:
                raise DryRunRollback

        post_check = await _collect_post_check(conn)
        summary["post_check"] = post_check
        return summary
    except DryRunRollback:
        if apply_changes:
            raise
        return summary
    finally:
        await conn.close()


def _build_counts(summary: dict[str, Any]) -> dict[str, int]:
    return {
        "teams_total": len(summary["teams"]),
        "teams_create": sum(1 for item in summary["teams"] if item["action"] == "create"),
        "teams_update": sum(1 for item in summary["teams"] if item["action"] == "update"),
        "skills_total": len(summary["skills"]),
        "skills_create": sum(1 for item in summary["skills"] if item["action"] == "create"),
        "skills_update": sum(1 for item in summary["skills"] if item["action"] == "update"),
        "users_total": len(summary["users"]),
        "users_create": sum(1 for item in summary["users"] if item["action"] == "create"),
        "users_update": sum(1 for item in summary["users"] if item["action"] == "update"),
        "profiles_total": len(summary["profiles"]),
        "profiles_create": sum(1 for item in summary["profiles"] if item["action"] == "create"),
        "profiles_update": sum(1 for item in summary["profiles"] if item["action"] == "update"),
        "profile_skills_total": len(summary["profile_skills"]),
        "profile_skills_create": sum(1 for item in summary["profile_skills"] if item["action"] == "create"),
        "profile_skills_update": sum(1 for item in summary["profile_skills"] if item["action"] == "update"),
    }


def _persist_report(summary: dict[str, Any]) -> Path:
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    path = RUNTIME_DIR / f"dispatch_worker_bootstrap_{stamp}.json"
    report = dict(summary)
    report["default_password"] = None
    path.write_text(_dump_json(report), encoding="utf-8")
    return path


def _print_summary(summary: dict[str, Any], *, as_json: bool) -> None:
    summary = dict(summary)
    summary["counts"] = _build_counts(summary)

    if as_json:
        print(_dump_json(summary))
        return

    print("")
    print(f"[MODE] {summary['mode']}")
    print(f"[BUILDINGS] {len(summary['building_ids'])} -> {', '.join(summary['building_ids']) or '(none)'}")
    print("[COUNTS]")
    for key, value in summary["counts"].items():
        print(f"  - {key}: {value}")

    print("")
    print("[USERS]")
    for item in summary["users"]:
        action = item["action"].upper()
        reset = "yes" if item.get("password_reset") else "no"
        print(f"  - {action:<6} {item['username']}  password_reset={reset}")

    post_check = summary.get("post_check")
    if post_check:
        print("")
        print(f"[POST-CHECK] dispatch_ready_workers={post_check['dispatch_ready_workers']}")
        for worker in post_check["workers"]:
            print(
                "  - "
                f"{worker['username']} | {worker['team_name']} | {worker['shift_status']} | "
                f"dispatch_enabled={worker['dispatch_enabled']} | buildings={worker['service_buildings_json']}"
            )

    print("")
    print(f"[LOGIN PASSWORD] {DEFAULT_PASSWORD}")


async def main() -> int:
    parser = argparse.ArgumentParser(description="Bootstrap dispatch workers for real dispatch flow.")
    parser.add_argument("--apply", action="store_true", help="Persist changes to the database.")
    parser.add_argument(
        "--reset-passwords",
        action="store_true",
        help="Reset seeded worker passwords to a known default password.",
    )
    parser.add_argument("--json", action="store_true", help="Print JSON output.")
    args = parser.parse_args()

    summary = await bootstrap_workers(
        apply_changes=args.apply,
        reset_passwords=args.reset_passwords,
    )
    report_path: Path | None = None
    if args.apply:
        report_path = _persist_report(summary)
        summary["report_path"] = str(report_path)
    _print_summary(summary, as_json=args.json)
    if report_path and not args.json:
        print(f"[REPORT] {report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
