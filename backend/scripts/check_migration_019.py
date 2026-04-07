"""
019 派工执行层迁移验数脚本（只读）。

用途：
1. 检查 019 所需表结构是否已落库
2. 检查历史工单是否存在可回填候选
3. 识别“状态已 dispatched 但没有派工实体”的不可恢复旧数据
4. 输出当前库的风险摘要，便于上线前验收

用法：
    cd backend
    python scripts/check_migration_019.py
    python scripts/check_migration_019.py --json
"""
from __future__ import annotations

import argparse
import asyncio
import json
import ssl
from pathlib import Path
from typing import Any

import asyncpg

ROOT_DIR = Path(__file__).resolve().parents[1]
ENV_PATH = ROOT_DIR / ".env"

BACKFILL_STATUSES = ("dispatched", "completed", "false_alarm", "escalated", "closed")


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


async def _table_exists(conn: asyncpg.Connection, table_name: str) -> bool:
    return bool(await conn.fetchval(
        """
        SELECT EXISTS (
            SELECT 1
            FROM information_schema.tables
            WHERE table_schema = 'public'
              AND table_name = $1
        )
        """,
        table_name,
    ))


async def _column_exists(conn: asyncpg.Connection, table_name: str, column_name: str) -> bool:
    return bool(await conn.fetchval(
        """
        SELECT EXISTS (
            SELECT 1
            FROM information_schema.columns
            WHERE table_schema = 'public'
              AND table_name = $1
              AND column_name = $2
        )
        """,
        table_name,
        column_name,
    ))


async def _fetch_count(conn: asyncpg.Connection, sql: str) -> int:
    return int(await conn.fetchval(sql) or 0)


async def _fetch_status_distribution(conn: asyncpg.Connection) -> dict[str, int]:
    rows = await conn.fetch(
        """
        SELECT status, COUNT(*) AS cnt
        FROM work_orders
        GROUP BY status
        ORDER BY status
        """
    )
    return {str(row["status"]): int(row["cnt"]) for row in rows}


async def _fetch_samples(conn: asyncpg.Connection, *, limit: int) -> dict[str, list[dict[str, Any]]]:
    recoverable = await conn.fetch(
        """
        SELECT ticket_id, status, assigned_to, assigned_at, worker_feedback_at, current_dispatch_id, created_at
        FROM work_orders
        WHERE assigned_to IS NOT NULL
          AND current_dispatch_id IS NULL
          AND status = ANY($1::text[])
        ORDER BY created_at DESC NULLS LAST
        LIMIT $2
        """,
        list(BACKFILL_STATUSES),
        limit,
    )
    unrecoverable = await conn.fetch(
        """
        SELECT ticket_id, status, ai_decision, assigned_to, assigned_at, current_dispatch_id,
               pending_dispatch_at, created_at, updated_at
        FROM work_orders
        WHERE status = 'dispatched'
          AND assigned_to IS NULL
          AND current_dispatch_id IS NULL
        ORDER BY created_at DESC NULLS LAST
        LIMIT $1
        """,
        limit,
    )
    incident_mismatch = await conn.fetch(
        """
        SELECT ai.incident_id, wo.ticket_id, ai.current_dispatch_id AS incident_dispatch_id,
               wo.current_dispatch_id AS work_order_dispatch_id
        FROM anomaly_incidents ai
        JOIN work_orders wo ON wo.id = ai.current_work_order_id
        WHERE COALESCE(ai.current_dispatch_id, '') <> COALESCE(wo.current_dispatch_id, '')
        ORDER BY ai.updated_at DESC NULLS LAST
        LIMIT $1
        """,
        limit,
    )
    return {
        "recoverable_backfill_candidates": [dict(row) for row in recoverable],
        "unrecoverable_dispatched_without_assignment": [dict(row) for row in unrecoverable],
        "incident_projection_mismatch": [dict(row) for row in incident_mismatch],
    }


def build_report(
    *,
    schema: dict[str, Any],
    metrics: dict[str, Any],
    status_distribution: dict[str, int],
    samples: dict[str, list[dict[str, Any]]],
) -> dict[str, Any]:
    findings: list[str] = []
    recommendations: list[str] = []

    if not schema["dispatch_tasks_exists"] or not schema["dispatch_events_exists"]:
        findings.append("019 结构未完整落库：dispatch_tasks / dispatch_events 至少有一张表不存在。")
        recommendations.append("先执行 019 迁移，再做后续验数。")

    audit_log_exists = schema.get("work_order_audit_log_exists", schema.get("work_order_audit_logs_exists", False))
    if not audit_log_exists:
        findings.append("真实库缺少 work_order_audit_log 表，无法依赖审计日志恢复历史派工责任人。")
        recommendations.append("如需恢复历史责任人，只能依赖外部日志、备份或业务侧重新派工。")

    if metrics["recoverable_backfill_candidates"] > 0:
        findings.append(
            f"存在 {metrics['recoverable_backfill_candidates']} 条可回填旧工单：assigned_to 不为空，但 current_dispatch_id 为空。"
        )
        recommendations.append("可考虑在备份后重跑/补跑 legacy_backfill 回填逻辑。")

    if metrics["dispatched_without_assignment"] > 0:
        findings.append(
            f"存在 {metrics['dispatched_without_assignment']} 条不可直接回填旧工单：状态已是 dispatched，但 assigned_to 与 current_dispatch_id 都为空。"
        )
        recommendations.append(
            "这批数据无法由 019 自动恢复责任人；需要业务决策是改回 pending_dispatch 重新派工，还是从外部日志恢复责任人。"
        )

    if metrics["dispatch_tasks_total"] == 0 and metrics["work_orders_total"] > 0:
        findings.append("当前库已有工单，但 dispatch_tasks 为空，第三阶段执行层尚未在真实数据上形成闭环。")

    if metrics["pending_dispatch_missing_timestamp"] > 0:
        findings.append(
            f"存在 {metrics['pending_dispatch_missing_timestamp']} 条待派工工单缺少 pending_dispatch_at。"
        )
        recommendations.append("执行 pending_dispatch_at 补齐脚本或重新运行 019 中对应 UPDATE。")

    if metrics["incident_projection_mismatch"] > 0:
        findings.append(
            f"存在 {metrics['incident_projection_mismatch']} 条 incident 与 work_order 的 current_dispatch 投影不一致。"
        )
        recommendations.append("修复 incident 读模型投影，再重新跑验数。")

    if metrics["work_orders_broken_current_dispatch_ref"] > 0 or metrics["incidents_broken_current_dispatch_ref"] > 0:
        findings.append("存在 current_dispatch_id 悬挂引用。")
        recommendations.append("先修复悬挂引用，再进行后续上线或回填。")

    if metrics["duplicate_current_dispatch_tasks"] > 0:
        findings.append(
            f"存在 {metrics['duplicate_current_dispatch_tasks']} 个工单出现多个 is_current=TRUE 的 dispatch_task。"
        )
        recommendations.append("先修复唯一 current dispatch，再开放执行流转。")

    if not findings:
        findings.append("019 结构与核心回填检查未发现阻塞问题。")

    if not recommendations:
        recommendations.append("可以继续进入接口联调与真实执行流回归。")

    return {
        "schema": schema,
        "metrics": metrics,
        "status_distribution": status_distribution,
        "samples": samples,
        "findings": findings,
        "recommendations": recommendations,
    }


async def collect_report(sample_limit: int = 5) -> dict[str, Any]:
    conn = await _connect()
    try:
        schema = {
            "dispatch_tasks_exists": await _table_exists(conn, "dispatch_tasks"),
            "dispatch_events_exists": await _table_exists(conn, "dispatch_events"),
            "work_order_audit_log_exists": await _table_exists(conn, "work_order_audit_log"),
            "work_orders.current_dispatch_id": await _column_exists(conn, "work_orders", "current_dispatch_id"),
            "work_orders.pending_dispatch_at": await _column_exists(conn, "work_orders", "pending_dispatch_at"),
            "anomaly_incidents.current_dispatch_id": await _column_exists(conn, "anomaly_incidents", "current_dispatch_id"),
            "anomaly_incidents.current_dispatch_status": await _column_exists(conn, "anomaly_incidents", "current_dispatch_status"),
        }

        metrics = {
            "work_orders_total": await _fetch_count(conn, "SELECT COUNT(*) FROM work_orders"),
            "anomaly_incidents_total": await _fetch_count(conn, "SELECT COUNT(*) FROM anomaly_incidents"),
            "users_total": await _fetch_count(conn, "SELECT COUNT(*) FROM users"),
            "worker_profiles_total": await _fetch_count(conn, "SELECT COUNT(*) FROM worker_profiles"),
            "dispatch_tasks_total": await _fetch_count(conn, "SELECT COUNT(*) FROM dispatch_tasks"),
            "dispatch_events_total": await _fetch_count(conn, "SELECT COUNT(*) FROM dispatch_events"),
            "dispatch_tasks_legacy_backfill_total": await _fetch_count(
                conn,
                "SELECT COUNT(*) FROM dispatch_tasks WHERE dispatch_mode = 'legacy_backfill'",
            ),
            "work_orders_with_current_dispatch": await _fetch_count(
                conn,
                "SELECT COUNT(*) FROM work_orders WHERE current_dispatch_id IS NOT NULL",
            ),
            "incidents_with_current_dispatch": await _fetch_count(
                conn,
                "SELECT COUNT(*) FROM anomaly_incidents WHERE current_dispatch_id IS NOT NULL",
            ),
            "recoverable_backfill_candidates": await _fetch_count(
                conn,
                """
                SELECT COUNT(*)
                FROM work_orders
                WHERE assigned_to IS NOT NULL
                  AND current_dispatch_id IS NULL
                  AND status = ANY(ARRAY['dispatched','completed','false_alarm','escalated','closed'])
                """,
            ),
            "dispatched_without_assignment": await _fetch_count(
                conn,
                """
                SELECT COUNT(*)
                FROM work_orders
                WHERE status = 'dispatched'
                  AND assigned_to IS NULL
                  AND current_dispatch_id IS NULL
                """,
            ),
            "pending_dispatch_missing_timestamp": await _fetch_count(
                conn,
                """
                SELECT COUNT(*)
                FROM work_orders
                WHERE status = 'pending_dispatch'
                  AND pending_dispatch_at IS NULL
                """,
            ),
            "work_orders_broken_current_dispatch_ref": await _fetch_count(
                conn,
                """
                SELECT COUNT(*)
                FROM work_orders wo
                LEFT JOIN dispatch_tasks dt ON dt.id = wo.current_dispatch_id
                WHERE wo.current_dispatch_id IS NOT NULL
                  AND dt.id IS NULL
                """,
            ),
            "incidents_broken_current_dispatch_ref": await _fetch_count(
                conn,
                """
                SELECT COUNT(*)
                FROM anomaly_incidents ai
                LEFT JOIN dispatch_tasks dt ON dt.id = ai.current_dispatch_id
                WHERE ai.current_dispatch_id IS NOT NULL
                  AND dt.id IS NULL
                """,
            ),
            "duplicate_current_dispatch_tasks": await _fetch_count(
                conn,
                """
                SELECT COUNT(*)
                FROM (
                    SELECT work_order_id
                    FROM dispatch_tasks
                    WHERE is_current = TRUE
                    GROUP BY work_order_id
                    HAVING COUNT(*) > 1
                ) t
                """,
            ),
            "incident_projection_mismatch": await _fetch_count(
                conn,
                """
                SELECT COUNT(*)
                FROM anomaly_incidents ai
                JOIN work_orders wo ON wo.id = ai.current_work_order_id
                WHERE COALESCE(ai.current_dispatch_id, '') <> COALESCE(wo.current_dispatch_id, '')
                """,
            ),
        }

        status_distribution = await _fetch_status_distribution(conn)
        samples = await _fetch_samples(conn, limit=sample_limit)
        return build_report(
            schema=schema,
            metrics=metrics,
            status_distribution=status_distribution,
            samples=samples,
        )
    finally:
        await conn.close()


def _print_report(report: dict[str, Any]) -> None:
    print("=== 019 Migration Check ===")

    print("\n[Schema]")
    for key, value in report["schema"].items():
        print(f"- {key}: {value}")

    print("\n[Metrics]")
    for key, value in report["metrics"].items():
        print(f"- {key}: {value}")

    print("\n[Work Order Status]")
    for key, value in report["status_distribution"].items():
        print(f"- {key}: {value}")

    print("\n[Findings]")
    for item in report["findings"]:
        print(f"- {item}")

    print("\n[Recommendations]")
    for item in report["recommendations"]:
        print(f"- {item}")

    print("\n[Samples]")
    for key, rows in report["samples"].items():
        print(f"- {key}: {len(rows)} rows")
        for row in rows:
            print(f"  {json.dumps(row, ensure_ascii=False, default=_json_default)}")


async def _async_main(args: argparse.Namespace) -> int:
    report = await collect_report(sample_limit=args.sample_limit)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2, default=_json_default))
    else:
        _print_report(report)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="检查 019 派工执行层迁移的真实库状态")
    parser.add_argument("--json", action="store_true", help="以 JSON 输出")
    parser.add_argument("--sample-limit", type=int, default=5, help="每类问题输出的样本数量")
    args = parser.parse_args()
    return asyncio.run(_async_main(args))


if __name__ == "__main__":
    raise SystemExit(main())
