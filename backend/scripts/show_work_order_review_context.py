"""
Read-only helper for inspecting the AI work-order review context.

Usage:
    cd backend
    python scripts/show_work_order_review_context.py WO-20260328-010
    python scripts/show_work_order_review_context.py WO-20260328-010 --json
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.db.session import AsyncSessionLocal
from app.services.work_order_review_context_service import build_work_order_review_context

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")


def _json_default(value: Any) -> Any:
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def _print_line(label: str, value: Any) -> None:
    if value is None or value == "":
        value = "-"
    print(f"- {label}: {value}")


def _format_dispatch(dispatch: dict[str, Any] | None) -> str:
    if not dispatch:
        return "-"
    parts = [
        dispatch.get("dispatch_id") or dispatch.get("id") or "-",
        f"status={dispatch.get('dispatch_status') or '-'}",
        f"attempt={dispatch.get('attempt_no') or '-'}",
        f"assignee={dispatch.get('assigned_to_name') or dispatch.get('assigned_to') or '-'}",
    ]
    timeout_level = dispatch.get("timeout_level")
    if timeout_level:
        parts.append(f"timeout={timeout_level}")
    return " | ".join(str(item) for item in parts)


def _print_context_summary(context: dict[str, Any]) -> None:
    work_order = context.get("work_order") or {}
    current_dispatch = context.get("current_dispatch")
    dispatch_tasks = context.get("dispatch_tasks") or []
    dispatch_events = context.get("dispatch_events") or []
    audit_logs = context.get("audit_logs") or []
    hall_entries = context.get("hall_entries") or []
    risk_flags = context.get("risk_flags") or []
    anomaly_evidence = context.get("anomaly_evidence") or []

    print("=== Work Order AI Review Context ===")
    _print_line("ticket_id", context.get("ticket_id"))
    _print_line("context_type", context.get("context_type"))
    _print_line("work_order_status", work_order.get("status"))
    _print_line("priority", work_order.get("priority"))
    _print_line("building_id", work_order.get("building_id"))
    _print_line("device_id", work_order.get("device_id"))
    _print_line("current_dispatch", _format_dispatch(current_dispatch))
    _print_line("dispatch_tasks", len(dispatch_tasks))
    _print_line("dispatch_events", len(dispatch_events))
    _print_line("audit_logs", len(audit_logs))
    _print_line("hall_entries", len(hall_entries))
    _print_line("anomaly_evidence", len(anomaly_evidence))
    _print_line("risk_flags", len(risk_flags))

    if risk_flags:
        print("\n[Risk Flags]")
        for item in risk_flags:
            print(
                f"- {item.get('severity') or '-'} / {item.get('code') or '-'}: "
                f"{item.get('message') or '-'}"
            )

    if dispatch_tasks:
        print("\n[Dispatch Tasks]")
        for item in dispatch_tasks[:8]:
            print(f"- {_format_dispatch(item)}")
        if len(dispatch_tasks) > 8:
            print(f"- ... {len(dispatch_tasks) - 8} more")

    if audit_logs:
        print("\n[Audit Logs]")
        for item in audit_logs[:8]:
            actor = item.get("actor_type") or "-"
            actor_id = item.get("actor_id") or "-"
            status_change = f"{item.get('old_status') or '-'} -> {item.get('new_status') or '-'}"
            print(
                f"- {item.get('created_at') or '-'} | {item.get('action') or '-'} | "
                f"{actor}:{actor_id} | {status_change}"
            )
        if len(audit_logs) > 8:
            print(f"- ... {len(audit_logs) - 8} more")

    summary = context.get("ai_context_summary")
    if summary:
        print("\n[AI Context Summary]")
        print(summary)


async def _load_context(ticket_id: str) -> dict[str, Any] | None:
    async with AsyncSessionLocal() as db:
        return await build_work_order_review_context(db, ticket_id=ticket_id)


async def _main() -> int:
    parser = argparse.ArgumentParser(
        description="Show a read-only AI review context for one work order.",
    )
    parser.add_argument("ticket_id", help="Work order ticket id, e.g. WO-20260328-010")
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print the full context as JSON for AI/debugging pipelines.",
    )
    args = parser.parse_args()

    context = await _load_context(args.ticket_id)
    if context is None:
        print(f"[ERROR] Work order not found: {args.ticket_id}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(context, ensure_ascii=False, indent=2, default=_json_default))
    else:
        _print_context_summary(context)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main()))
