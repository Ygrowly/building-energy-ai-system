from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

from app.db.models import DispatchOperationRun
from app.db.session import AsyncSessionLocal

DISPATCH_SLA_SCAN_OPERATION = "dispatch_sla_scan"
DISPATCH_RUN_TRIGGER_SOURCES = ("admin_api", "scheduler")
DISPATCH_RUN_STATUSES = ("success", "failed")

logger = logging.getLogger(__name__)


def _summary_int(summary: dict[str, Any], key: str) -> int:
    try:
        return int(summary.get(key, 0) or 0)
    except (TypeError, ValueError):
        return 0


async def record_dispatch_operation_run(
    *,
    operation_type: str,
    trigger_source: str,
    run_status: str,
    started_at: datetime,
    finished_at: datetime | None = None,
    summary: dict[str, Any] | None = None,
    error_message: str | None = None,
) -> None:
    finished = finished_at or datetime.now(timezone.utc)
    started = started_at if started_at.tzinfo else started_at.replace(tzinfo=timezone.utc)
    finished = finished if finished.tzinfo else finished.replace(tzinfo=timezone.utc)
    summary_data = summary or {}
    timings = summary_data.get("timings_ms") if isinstance(summary_data.get("timings_ms"), dict) else {}
    duration_ms = _summary_int(timings, "total")
    if duration_ms <= 0:
        duration_ms = max(int((finished - started).total_seconds() * 1000), 0)

    run = DispatchOperationRun(
        operation_type=operation_type,
        trigger_source=trigger_source,
        run_status=run_status,
        scanned_count=_summary_int(summary_data, "scanned"),
        updated_count=_summary_int(summary_data, "updated"),
        warning_events=_summary_int(summary_data, "warning_events"),
        overdue_events=_summary_int(summary_data, "overdue_events"),
        auto_reassign_triggers=_summary_int(summary_data, "auto_reassign_triggers"),
        auto_reassign_executed=_summary_int(summary_data, "auto_reassign_executed"),
        auto_reassign_hall_fallbacks=_summary_int(summary_data, "auto_reassign_hall_fallbacks"),
        auto_reassign_shadow_evaluated=_summary_int(summary_data, "auto_reassign_shadow_evaluated"),
        auto_reassign_shadow_would_execute=_summary_int(summary_data, "auto_reassign_shadow_would_execute"),
        auto_reassign_shadow_would_hall_fallbacks=_summary_int(summary_data, "auto_reassign_shadow_would_hall_fallbacks"),
        duration_ms=duration_ms,
        timings_json=json.dumps(timings, ensure_ascii=False) if timings else None,
        error_message=(error_message or "")[:2000] or None,
        started_at=started,
        finished_at=finished,
    )

    try:
        async with AsyncSessionLocal() as db:
            db.add(run)
            await db.commit()
    except Exception as exc:
        logger.warning(
            "record_dispatch_operation_run 失败，已跳过。operation=%s source=%s status=%s error=%s: %s",
            operation_type,
            trigger_source,
            run_status,
            type(exc).__name__,
            exc,
        )
