"""
修复 019 迁移后遗留的“孤儿 dispatched 工单”。

适用场景：
- work_orders.status = 'dispatched'
- assigned_to IS NULL
- current_dispatch_id IS NULL
- 没有 accepted / arrived / processing / feedback 痕迹
- AI 已审批通过（ai_decision = 'approve'）

修复策略：
- 将工单回退为 pending_dispatch
- 补 pending_dispatch_at
- 清空 current_dispatch / 执行轨迹投影
- 同步 incident 读模型回 pending_dispatch / open

默认仅 dry-run，不写库。

用法：
    cd backend
    python scripts/repair_019_reset_orphan_dispatched.py
    python scripts/repair_019_reset_orphan_dispatched.py --apply
"""
from __future__ import annotations

import argparse
import asyncio
import json
import ssl
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import asyncpg

ROOT_DIR = Path(__file__).resolve().parents[1]
ENV_PATH = ROOT_DIR / ".env"
BACKUP_DIR = ROOT_DIR / "runtime" / "migration_019_repair"


def _load_env(path: Path) -> dict[str, str]:
    env: dict[str, str] = {}
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


async def _connect() -> asyncpg.Connection:
    env = _load_env(ENV_PATH)
    url = env.get("SYNC_DATABASE_URL") or env.get("DATABASE_URL")
    if not url:
        raise RuntimeError("未在 backend/.env 中找到 SYNC_DATABASE_URL / DATABASE_URL")

    ssl_ctx = ssl.create_default_context()
    ssl_ctx.check_hostname = False
    ssl_ctx.verify_mode = ssl.CERT_NONE
    return await asyncpg.connect(url, ssl=ssl_ctx)


BROKEN_SCOPE_SQL = """
SELECT *
FROM work_orders
WHERE status = 'dispatched'
  AND assigned_to IS NULL
  AND current_dispatch_id IS NULL
"""

CANDIDATE_SQL = """
SELECT *
FROM work_orders
WHERE status = 'dispatched'
  AND assigned_to IS NULL
  AND current_dispatch_id IS NULL
  AND accepted_at IS NULL
  AND arrived_at IS NULL
  AND processing_started_at IS NULL
  AND worker_feedback_at IS NULL
  AND ai_decision = 'approve'
"""


async def collect_candidates(conn: asyncpg.Connection) -> dict[str, Any]:
    broken_rows = await conn.fetch(BROKEN_SCOPE_SQL)
    candidate_rows = await conn.fetch(CANDIDATE_SQL)

    broken_ids = {str(row["id"]) for row in broken_rows}
    candidate_ids = {str(row["id"]) for row in candidate_rows}
    risky_ids = broken_ids - candidate_ids

    risky_rows = [dict(row) for row in broken_rows if str(row["id"]) in risky_ids]
    incident_rows = await conn.fetch(
        """
        SELECT *
        FROM anomaly_incidents
        WHERE current_work_order_id = ANY($1::text[])
        ORDER BY updated_at DESC NULLS LAST
        """,
        list(candidate_ids) or [""],
    ) if candidate_ids else []

    return {
        "broken_rows": [dict(row) for row in broken_rows],
        "candidate_rows": [dict(row) for row in candidate_rows],
        "risky_rows": risky_rows,
        "incident_rows": [dict(row) for row in incident_rows],
    }


def build_backup_payload(snapshot: dict[str, Any]) -> dict[str, Any]:
    candidate_rows = snapshot["candidate_rows"]
    incident_rows = snapshot["incident_rows"]
    risky_rows = snapshot["risky_rows"]
    return {
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "candidate_count": len(candidate_rows),
        "risky_count": len(risky_rows),
        "incident_count": len(incident_rows),
        "candidate_work_orders": candidate_rows,
        "impacted_incidents": incident_rows,
        "risky_work_orders": risky_rows,
    }


def write_backup_file(payload: dict[str, Any]) -> Path:
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    path = BACKUP_DIR / f"repair_019_backup_{ts}.json"
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=_json_default),
        encoding="utf-8",
    )
    return path


async def apply_repair(conn: asyncpg.Connection, candidate_ids: list[str]) -> dict[str, int]:
    if not candidate_ids:
        return {"work_orders_updated": 0, "incidents_updated": 0}

    async with conn.transaction():
        work_orders_updated = await conn.execute(
            """
            UPDATE work_orders
            SET status = 'pending_dispatch',
                pending_dispatch_at = COALESCE(pending_dispatch_at, ai_reviewed_at, updated_at, created_at, NOW()),
                dispatch_blocked_reason = NULL,
                current_dispatch_id = NULL,
                assigned_to = NULL,
                assigned_at = NULL,
                accepted_at = NULL,
                arrived_at = NULL,
                processing_started_at = NULL,
                updated_at = NOW()
            WHERE id = ANY($1::text[])
            """,
            candidate_ids,
        )
        incidents_updated = await conn.execute(
            """
            UPDATE anomaly_incidents
            SET workflow_status = 'pending_dispatch',
                incident_status = 'open',
                is_active = TRUE,
                resolved_at = NULL,
                current_dispatch_id = NULL,
                current_dispatch_status = NULL,
                current_assigned_to = NULL,
                current_assigned_team_id = NULL,
                current_accept_deadline_at = NULL,
                current_arrive_deadline_at = NULL,
                current_finish_deadline_at = NULL,
                last_dispatch_at = NULL,
                dispatch_overdue_flag = FALSE,
                dispatch_blocked_reason = NULL,
                latest_dispatch_note = 'AI审批已通过，等待调度人员派工',
                updated_at = NOW()
            WHERE current_work_order_id = ANY($1::text[])
            """,
            candidate_ids,
        )

    return {
        "work_orders_updated": int(work_orders_updated.split()[-1]),
        "incidents_updated": int(incidents_updated.split()[-1]),
    }


def print_summary(snapshot: dict[str, Any], backup_path: Path | None = None, applied: dict[str, int] | None = None) -> None:
    candidate_rows = snapshot["candidate_rows"]
    risky_rows = snapshot["risky_rows"]
    incident_rows = snapshot["incident_rows"]
    print("=== Repair 019 Orphan Dispatched ===")
    print(f"- broken_rows: {len(snapshot['broken_rows'])}")
    print(f"- safe_candidates: {len(candidate_rows)}")
    print(f"- risky_rows: {len(risky_rows)}")
    print(f"- impacted_incidents: {len(incident_rows)}")
    if backup_path:
        print(f"- backup_file: {backup_path}")
    if applied:
        print(f"- work_orders_updated: {applied['work_orders_updated']}")
        print(f"- incidents_updated: {applied['incidents_updated']}")

    print("\n[Samples]")
    for row in candidate_rows[:5]:
        print(f"- candidate: {json.dumps(row, ensure_ascii=False, default=_json_default)}")
    for row in risky_rows[:5]:
        print(f"- risky: {json.dumps(row, ensure_ascii=False, default=_json_default)}")


async def _async_main(args: argparse.Namespace) -> int:
    conn = await _connect()
    try:
        snapshot = await collect_candidates(conn)
        if snapshot["risky_rows"]:
            print_summary(snapshot)
            print("\n[ABORT] 检测到不安全样本，未执行修复。请先人工确认 risky_rows。")
            return 2

        backup_payload = build_backup_payload(snapshot)
        backup_path = write_backup_file(backup_payload)

        if not args.apply:
            print_summary(snapshot, backup_path=backup_path)
            print("\n[DRY-RUN] 未写库。确认无误后可执行：python scripts/repair_019_reset_orphan_dispatched.py --apply")
            return 0

        applied = await apply_repair(
            conn,
            [str(row["id"]) for row in snapshot["candidate_rows"]],
        )
        print_summary(snapshot, backup_path=backup_path, applied=applied)
        print("\n[APPLIED] 已完成修复。建议立刻执行 python scripts/check_migration_019.py 复核。")
        return 0
    finally:
        await conn.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="将无责任人的 dispatched 工单安全回退到 pending_dispatch")
    parser.add_argument("--apply", action="store_true", help="真正写库；默认仅 dry-run")
    args = parser.parse_args()
    return asyncio.run(_async_main(args))


if __name__ == "__main__":
    raise SystemExit(main())
