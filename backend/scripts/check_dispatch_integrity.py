"""
派工执行层一致性巡检脚本（只读）。

用途：
1. 巡检 work_orders / anomaly_incidents / dispatch_tasks 三者之间的 current_dispatch 一致性
2. 识别 is_current 冲突、责任人投影不一致、attempt_no 重复等脏数据
3. 为上线巡检、日常巡检和问题排查提供统一出口

用法：
    cd backend
    python scripts/check_dispatch_integrity.py
    python scripts/check_dispatch_integrity.py --json
    python scripts/check_dispatch_integrity.py --strict
"""
from __future__ import annotations

import argparse
import asyncio
import json
import ssl
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import asyncpg

ROOT_DIR = Path(__file__).resolve().parents[1]
ENV_PATH = ROOT_DIR / ".env"

ACTIVE_DISPATCH_STATUSES = (
    "assigned",
    "accepted",
    "arrived",
    "processing",
    "waiting_support",
)

INVALID_CURRENT_DISPATCH_STATUSES = (
    "cancelled",
    "transferred",
    "rejected",
)

CHECK_DEFINITIONS: tuple[dict[str, str], ...] = (
    {
        "name": "work_orders_dispatched_without_current_dispatch",
        "label": "已派单工单缺少 current_dispatch 指针",
        "severity": "high",
        "count_sql": """
            SELECT COUNT(*)
            FROM work_orders
            WHERE status = 'dispatched'
              AND current_dispatch_id IS NULL
        """,
        "sample_sql": """
            SELECT id, ticket_id, status, assigned_to, current_dispatch_id, pending_dispatch_at, updated_at
            FROM work_orders
            WHERE status = 'dispatched'
              AND current_dispatch_id IS NULL
            ORDER BY updated_at DESC NULLS LAST
            LIMIT $1
        """,
    },
    {
        "name": "work_orders_pending_dispatch_with_stale_assignment",
        "label": "待派工工单仍残留责任人或派工指针",
        "severity": "high",
        "count_sql": """
            SELECT COUNT(*)
            FROM work_orders
            WHERE status = 'pending_dispatch'
              AND (
                current_dispatch_id IS NOT NULL
                OR assigned_to IS NOT NULL
              )
        """,
        "sample_sql": """
            SELECT id, ticket_id, status, assigned_to, current_dispatch_id, pending_dispatch_at, updated_at
            FROM work_orders
            WHERE status = 'pending_dispatch'
              AND (
                current_dispatch_id IS NOT NULL
                OR assigned_to IS NOT NULL
              )
            ORDER BY updated_at DESC NULLS LAST
            LIMIT $1
        """,
    },
    {
        "name": "work_orders_broken_current_dispatch_ref",
        "label": "工单 current_dispatch_id 指向不存在的 dispatch_task",
        "severity": "high",
        "count_sql": """
            SELECT COUNT(*)
            FROM work_orders wo
            LEFT JOIN dispatch_tasks dt ON dt.id = wo.current_dispatch_id
            WHERE wo.current_dispatch_id IS NOT NULL
              AND dt.id IS NULL
        """,
        "sample_sql": """
            SELECT wo.id, wo.ticket_id, wo.status, wo.current_dispatch_id, wo.assigned_to, wo.updated_at
            FROM work_orders wo
            LEFT JOIN dispatch_tasks dt ON dt.id = wo.current_dispatch_id
            WHERE wo.current_dispatch_id IS NOT NULL
              AND dt.id IS NULL
            ORDER BY wo.updated_at DESC NULLS LAST
            LIMIT $1
        """,
    },
    {
        "name": "work_orders_current_dispatch_not_marked_current",
        "label": "工单 current_dispatch 指向了非当前派工任务",
        "severity": "high",
        "count_sql": """
            SELECT COUNT(*)
            FROM work_orders wo
            JOIN dispatch_tasks dt ON dt.id = wo.current_dispatch_id
            WHERE wo.current_dispatch_id IS NOT NULL
              AND dt.is_current = FALSE
        """,
        "sample_sql": """
            SELECT wo.id, wo.ticket_id, wo.status, wo.current_dispatch_id, dt.dispatch_status, dt.is_current, wo.updated_at
            FROM work_orders wo
            JOIN dispatch_tasks dt ON dt.id = wo.current_dispatch_id
            WHERE wo.current_dispatch_id IS NOT NULL
              AND dt.is_current = FALSE
            ORDER BY wo.updated_at DESC NULLS LAST
            LIMIT $1
        """,
    },
    {
        "name": "work_orders_current_dispatch_assignee_mismatch",
        "label": "工单 assigned_to 与 current_dispatch.assigned_to 不一致",
        "severity": "high",
        "count_sql": """
            SELECT COUNT(*)
            FROM work_orders wo
            JOIN dispatch_tasks dt ON dt.id = wo.current_dispatch_id
            WHERE wo.current_dispatch_id IS NOT NULL
              AND COALESCE(wo.assigned_to, '') <> COALESCE(dt.assigned_to, '')
        """,
        "sample_sql": """
            SELECT wo.id, wo.ticket_id, wo.assigned_to AS work_order_assigned_to,
                   dt.assigned_to AS dispatch_assigned_to, wo.current_dispatch_id, wo.updated_at
            FROM work_orders wo
            JOIN dispatch_tasks dt ON dt.id = wo.current_dispatch_id
            WHERE wo.current_dispatch_id IS NOT NULL
              AND COALESCE(wo.assigned_to, '') <> COALESCE(dt.assigned_to, '')
            ORDER BY wo.updated_at DESC NULLS LAST
            LIMIT $1
        """,
    },
    {
        "name": "dispatch_tasks_current_without_work_order_pointer",
        "label": "当前派工任务未被工单 current_dispatch 正确指向",
        "severity": "high",
        "count_sql": """
            SELECT COUNT(*)
            FROM dispatch_tasks dt
            JOIN work_orders wo ON wo.id = dt.work_order_id
            WHERE dt.is_current = TRUE
              AND COALESCE(wo.current_dispatch_id, '') <> dt.id
        """,
        "sample_sql": """
            SELECT dt.id, dt.work_order_id, wo.ticket_id, dt.dispatch_status, dt.assigned_to,
                   wo.current_dispatch_id, wo.updated_at
            FROM dispatch_tasks dt
            JOIN work_orders wo ON wo.id = dt.work_order_id
            WHERE dt.is_current = TRUE
              AND COALESCE(wo.current_dispatch_id, '') <> dt.id
            ORDER BY wo.updated_at DESC NULLS LAST
            LIMIT $1
        """,
    },
    {
        "name": "duplicate_current_dispatch_tasks",
        "label": "同一工单存在多个 is_current = true 的派工任务",
        "severity": "high",
        "count_sql": """
            SELECT COUNT(*)
            FROM (
                SELECT work_order_id
                FROM dispatch_tasks
                WHERE is_current = TRUE
                GROUP BY work_order_id
                HAVING COUNT(*) > 1
            ) t
        """,
        "sample_sql": """
            SELECT dt.work_order_id,
                   wo.ticket_id,
                   COUNT(*) AS current_task_count,
                   ARRAY_AGG(dt.id ORDER BY dt.created_at DESC) AS dispatch_ids,
                   ARRAY_AGG(dt.dispatch_status ORDER BY dt.created_at DESC) AS dispatch_statuses
            FROM dispatch_tasks dt
            LEFT JOIN work_orders wo ON wo.id = dt.work_order_id
            WHERE dt.is_current = TRUE
            GROUP BY dt.work_order_id, wo.ticket_id
            HAVING COUNT(*) > 1
            ORDER BY COUNT(*) DESC, MAX(dt.updated_at) DESC NULLS LAST
            LIMIT $1
        """,
    },
    {
        "name": "dispatch_tasks_current_but_terminal",
        "label": "当前派工任务已处于无效终态但仍保持 is_current = true",
        "severity": "high",
        "count_sql": """
            SELECT COUNT(*)
            FROM dispatch_tasks
            WHERE is_current = TRUE
              AND dispatch_status = ANY($1::text[])
        """,
        "sample_sql": """
            SELECT id, work_order_id, incident_id, attempt_no, dispatch_status, assigned_to, updated_at
            FROM dispatch_tasks
            WHERE is_current = TRUE
              AND dispatch_status = ANY($1::text[])
            ORDER BY updated_at DESC NULLS LAST
            LIMIT $2
        """,
    },
    {
        "name": "dispatch_tasks_non_current_but_active",
        "label": "非当前派工任务仍停留在活跃状态",
        "severity": "medium",
        "count_sql": """
            SELECT COUNT(*)
            FROM dispatch_tasks
            WHERE is_current = FALSE
              AND dispatch_status = ANY($1::text[])
        """,
        "sample_sql": """
            SELECT id, work_order_id, incident_id, attempt_no, dispatch_status, assigned_to, updated_at
            FROM dispatch_tasks
            WHERE is_current = FALSE
              AND dispatch_status = ANY($1::text[])
            ORDER BY updated_at DESC NULLS LAST
            LIMIT $2
        """,
    },
    {
        "name": "dispatch_tasks_duplicate_attempt_no",
        "label": "同一工单的 attempt_no 出现重复",
        "severity": "medium",
        "count_sql": """
            SELECT COUNT(*)
            FROM (
                SELECT work_order_id, attempt_no
                FROM dispatch_tasks
                GROUP BY work_order_id, attempt_no
                HAVING COUNT(*) > 1
            ) t
        """,
        "sample_sql": """
            SELECT dt.work_order_id,
                   wo.ticket_id,
                   dt.attempt_no,
                   COUNT(*) AS duplicated_count,
                   ARRAY_AGG(dt.id ORDER BY dt.created_at DESC) AS dispatch_ids
            FROM dispatch_tasks dt
            LEFT JOIN work_orders wo ON wo.id = dt.work_order_id
            GROUP BY dt.work_order_id, wo.ticket_id, dt.attempt_no
            HAVING COUNT(*) > 1
            ORDER BY COUNT(*) DESC, MAX(dt.updated_at) DESC NULLS LAST
            LIMIT $1
        """,
    },
    {
        "name": "incidents_broken_current_dispatch_ref",
        "label": "incident current_dispatch_id 指向不存在的 dispatch_task",
        "severity": "high",
        "count_sql": """
            SELECT COUNT(*)
            FROM anomaly_incidents ai
            LEFT JOIN dispatch_tasks dt ON dt.id = ai.current_dispatch_id
            WHERE ai.current_dispatch_id IS NOT NULL
              AND dt.id IS NULL
        """,
        "sample_sql": """
            SELECT ai.id, ai.incident_id, ai.current_work_order_id, ai.current_dispatch_id,
                   ai.current_dispatch_status, ai.current_assigned_to, ai.updated_at
            FROM anomaly_incidents ai
            LEFT JOIN dispatch_tasks dt ON dt.id = ai.current_dispatch_id
            WHERE ai.current_dispatch_id IS NOT NULL
              AND dt.id IS NULL
            ORDER BY ai.updated_at DESC NULLS LAST
            LIMIT $1
        """,
    },
    {
        "name": "incident_work_order_dispatch_pointer_mismatch",
        "label": "incident 与工单的 current_dispatch 指针不一致",
        "severity": "high",
        "count_sql": """
            SELECT COUNT(*)
            FROM anomaly_incidents ai
            JOIN work_orders wo ON wo.id = ai.current_work_order_id
            WHERE COALESCE(ai.current_dispatch_id, '') <> COALESCE(wo.current_dispatch_id, '')
        """,
        "sample_sql": """
            SELECT ai.id, ai.incident_id, wo.ticket_id,
                   ai.current_dispatch_id AS incident_dispatch_id,
                   wo.current_dispatch_id AS work_order_dispatch_id,
                   ai.updated_at
            FROM anomaly_incidents ai
            JOIN work_orders wo ON wo.id = ai.current_work_order_id
            WHERE COALESCE(ai.current_dispatch_id, '') <> COALESCE(wo.current_dispatch_id, '')
            ORDER BY ai.updated_at DESC NULLS LAST
            LIMIT $1
        """,
    },
    {
        "name": "incident_dispatch_status_projection_mismatch",
        "label": "incident current_dispatch_status 与 dispatch_task.dispatch_status 不一致",
        "severity": "medium",
        "count_sql": """
            SELECT COUNT(*)
            FROM anomaly_incidents ai
            JOIN dispatch_tasks dt ON dt.id = ai.current_dispatch_id
            WHERE COALESCE(ai.current_dispatch_status, '') <> COALESCE(dt.dispatch_status, '')
        """,
        "sample_sql": """
            SELECT ai.id, ai.incident_id, ai.current_dispatch_id,
                   ai.current_dispatch_status AS incident_dispatch_status,
                   dt.dispatch_status AS actual_dispatch_status,
                   ai.updated_at
            FROM anomaly_incidents ai
            JOIN dispatch_tasks dt ON dt.id = ai.current_dispatch_id
            WHERE COALESCE(ai.current_dispatch_status, '') <> COALESCE(dt.dispatch_status, '')
            ORDER BY ai.updated_at DESC NULLS LAST
            LIMIT $1
        """,
    },
    {
        "name": "incident_dispatch_assignee_projection_mismatch",
        "label": "incident current_assigned_to 与 dispatch_task.assigned_to 不一致",
        "severity": "medium",
        "count_sql": """
            SELECT COUNT(*)
            FROM anomaly_incidents ai
            JOIN dispatch_tasks dt ON dt.id = ai.current_dispatch_id
            WHERE COALESCE(ai.current_assigned_to, '') <> COALESCE(dt.assigned_to, '')
        """,
        "sample_sql": """
            SELECT ai.id, ai.incident_id, ai.current_dispatch_id,
                   ai.current_assigned_to AS incident_assigned_to,
                   dt.assigned_to AS actual_assigned_to,
                   ai.updated_at
            FROM anomaly_incidents ai
            JOIN dispatch_tasks dt ON dt.id = ai.current_dispatch_id
            WHERE COALESCE(ai.current_assigned_to, '') <> COALESCE(dt.assigned_to, '')
            ORDER BY ai.updated_at DESC NULLS LAST
            LIMIT $1
        """,
    },
)


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


async def _fetch_count(conn: asyncpg.Connection, sql: str, *args: Any) -> int:
    return int(await conn.fetchval(sql, *args) or 0)


async def _fetch_distribution(
    conn: asyncpg.Connection,
    *,
    table_name: str,
    column_name: str,
) -> dict[str, int]:
    rows = await conn.fetch(
        f"""
        SELECT {column_name} AS bucket, COUNT(*) AS cnt
        FROM {table_name}
        GROUP BY {column_name}
        ORDER BY {column_name}
        """
    )
    return {str(row["bucket"]): int(row["cnt"]) for row in rows}


async def _collect_check_result(
    conn: asyncpg.Connection,
    *,
    definition: dict[str, str],
    sample_limit: int,
) -> dict[str, Any]:
    name = definition["name"]
    if name == "dispatch_tasks_current_but_terminal":
        count = await _fetch_count(conn, definition["count_sql"], list(INVALID_CURRENT_DISPATCH_STATUSES))
        samples = await conn.fetch(definition["sample_sql"], list(INVALID_CURRENT_DISPATCH_STATUSES), sample_limit)
    elif name == "dispatch_tasks_non_current_but_active":
        count = await _fetch_count(conn, definition["count_sql"], list(ACTIVE_DISPATCH_STATUSES))
        samples = await conn.fetch(definition["sample_sql"], list(ACTIVE_DISPATCH_STATUSES), sample_limit)
    else:
        count = await _fetch_count(conn, definition["count_sql"])
        samples = await conn.fetch(definition["sample_sql"], sample_limit)

    return {
        "name": definition["name"],
        "label": definition["label"],
        "severity": definition["severity"],
        "count": count,
        "samples": [dict(row) for row in samples],
    }


def summarize_findings(findings: list[dict[str, Any]]) -> dict[str, Any]:
    failed = [item for item in findings if int(item.get("count") or 0) > 0]
    severity_counter = Counter(item["severity"] for item in failed)
    row_counter = Counter()
    for item in failed:
        row_counter[item["severity"]] += int(item.get("count") or 0)

    return {
        "healthy": not failed,
        "failed_checks": len(failed),
        "high_severity_checks": severity_counter.get("high", 0),
        "medium_severity_checks": severity_counter.get("medium", 0),
        "high_severity_rows": row_counter.get("high", 0),
        "medium_severity_rows": row_counter.get("medium", 0),
    }


def build_report_lines(report: dict[str, Any]) -> list[str]:
    summary = report["summary"]
    metrics = report["metrics"]
    lines = [
        "=== Dispatch Integrity Report ===",
        f"- generated_at: {report['generated_at']}",
        f"- work_orders_total: {metrics['work_orders_total']}",
        f"- anomaly_incidents_total: {metrics['anomaly_incidents_total']}",
        f"- dispatch_tasks_total: {metrics['dispatch_tasks_total']}",
        f"- current_dispatch_tasks_total: {metrics['current_dispatch_tasks_total']}",
        f"- failed_checks: {summary['failed_checks']}",
        f"- high_severity_checks: {summary['high_severity_checks']}",
        f"- medium_severity_checks: {summary['medium_severity_checks']}",
    ]

    failed = [item for item in report["checks"] if int(item.get("count") or 0) > 0]
    if not failed:
        lines.append("")
        lines.append("[OK] 未发现 current_dispatch / 派工投影脏数据。")
        return lines

    lines.append("")
    lines.append("[Failed Checks]")
    for item in failed:
        lines.append(
            f"- [{item['severity'].upper()}] {item['label']}: {item['count']}"
        )
        for sample in item.get("samples", [])[:2]:
            lines.append(
                f"  sample: {json.dumps(sample, ensure_ascii=False, default=_json_default)}"
            )
    return lines


async def collect_report(sample_limit: int = 5) -> dict[str, Any]:
    conn = await _connect()
    try:
        metrics = {
            "work_orders_total": await _fetch_count(conn, "SELECT COUNT(*) FROM work_orders"),
            "anomaly_incidents_total": await _fetch_count(conn, "SELECT COUNT(*) FROM anomaly_incidents"),
            "dispatch_tasks_total": await _fetch_count(conn, "SELECT COUNT(*) FROM dispatch_tasks"),
            "current_dispatch_tasks_total": await _fetch_count(
                conn,
                "SELECT COUNT(*) FROM dispatch_tasks WHERE is_current = TRUE",
            ),
            "work_orders_with_current_dispatch": await _fetch_count(
                conn,
                "SELECT COUNT(*) FROM work_orders WHERE current_dispatch_id IS NOT NULL",
            ),
            "incidents_with_current_dispatch": await _fetch_count(
                conn,
                "SELECT COUNT(*) FROM anomaly_incidents WHERE current_dispatch_id IS NOT NULL",
            ),
        }
        distributions = {
            "work_order_status_distribution": await _fetch_distribution(
                conn,
                table_name="work_orders",
                column_name="status",
            ),
            "dispatch_task_status_distribution": await _fetch_distribution(
                conn,
                table_name="dispatch_tasks",
                column_name="dispatch_status",
            ),
            "incident_workflow_status_distribution": await _fetch_distribution(
                conn,
                table_name="anomaly_incidents",
                column_name="workflow_status",
            ),
        }
        checks = [
            await _collect_check_result(
                conn,
                definition=definition,
                sample_limit=sample_limit,
            )
            for definition in CHECK_DEFINITIONS
        ]
        summary = summarize_findings(checks)
        return {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "metrics": metrics,
            "distributions": distributions,
            "summary": summary,
            "checks": checks,
        }
    finally:
        await conn.close()


async def _async_main(args: argparse.Namespace) -> int:
    report = await collect_report(sample_limit=args.sample_limit)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2, default=_json_default))
    else:
        for line in build_report_lines(report):
            print(line)

    if args.strict and report["summary"]["failed_checks"] > 0:
        return 2
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="巡检派工执行层 current_dispatch / 投影一致性")
    parser.add_argument("--json", action="store_true", help="输出 JSON 报告")
    parser.add_argument("--strict", action="store_true", help="发现异常时返回非 0")
    parser.add_argument("--sample-limit", type=int, default=5, help="每类异常输出样本数，默认 5")
    args = parser.parse_args()
    return asyncio.run(_async_main(args))


if __name__ == "__main__":
    raise SystemExit(main())
