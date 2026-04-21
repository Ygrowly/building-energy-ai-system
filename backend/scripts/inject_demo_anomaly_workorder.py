"""
Inject one demo anomaly event and immediately materialize an incident/work order.

Default behavior is to write one new anomaly event, create a new pending-review
incident/work order, and clear relevant caches so the information center can
pick up:

- recent anomalies +1 when the injected timestamp falls inside the current
  `/api/anomalies/recent?hours=168` window
- pending-review work order dynamics +1

Usage:
  cd backend
  python scripts/inject_demo_anomaly_workorder.py

Preview without writing:
  python scripts/inject_demo_anomaly_workorder.py --dry-run
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path


def _ensure_import_path() -> tuple[Path, Path]:
    repo_root = Path(__file__).resolve().parents[2]
    backend_dir = repo_root / "backend"
    if str(backend_dir) not in sys.path:
        sys.path.insert(0, str(backend_dir))
    return repo_root, backend_dir


REPO_ROOT, BACKEND_DIR = _ensure_import_path()


def _merge_env_file(
    env_path: Path,
    *,
    override: bool = False,
    env: dict[str, str] | None = None,
) -> None:
    target_env = os.environ if env is None else env
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if not key:
            continue
        if value and len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        if override or key not in target_env:
            target_env[key] = value


def _load_backend_env() -> None:
    env_path = BACKEND_DIR / ".env"
    if env_path.is_file():
        _merge_env_file(env_path, override=False)


_load_backend_env()

from sqlalchemy import func, select, text

from app.core.buildings import BUILDING_TYPE_TO_ID, normalize_building_type
from app.core.cache import delete_cache_by_prefix
from app.db.models import AnomalyEvent, AnomalyIncident, Device
from app.db.session import AsyncSessionLocal
from app.services.incident_service import create_or_merge_alert_incident


DEFAULT_BUILDING_ID = "Fox_office_Alice"
DEFAULT_DEVICE_KIND = "ac"
DEVICE_KIND_CHOICES = ("ac", "electricity", "water")
DEFAULT_RULE_BY_DEVICE_KIND = {
    "ac": "flag_hvac_energy",
    "electricity": "flag_electricity",
    "water": "flag_water",
}


@dataclass(frozen=True)
class Snapshot:
    max_anomaly_ts: datetime | None
    recent_anomaly_count: int
    pending_review_count: int


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Insert one demo anomaly event and generate a pending-review work order.",
    )
    parser.add_argument(
        "--building-id",
        default=DEFAULT_BUILDING_ID,
        help="Building ID or building type alias. Default: Fox_office_Alice",
    )
    parser.add_argument(
        "--device-kind",
        choices=DEVICE_KIND_CHOICES,
        default=DEFAULT_DEVICE_KIND,
        help="Device type used to auto-resolve device_id. Default: ac",
    )
    parser.add_argument(
        "--device-id",
        default="",
        help="Explicit device_id. When omitted, the script resolves one by building + device-kind.",
    )
    parser.add_argument(
        "--rule",
        default="",
        help="Explicit anomaly rule. Default follows device-kind.",
    )
    parser.add_argument(
        "--root-cause",
        default="B_small_deltaT",
        help="HVAC root cause. Only meaningful for HVAC-style rules.",
    )
    parser.add_argument(
        "--actual",
        type=float,
        default=88.0,
        help="Actual observed value. Default: 88.0",
    )
    parser.add_argument(
        "--expected",
        type=float,
        default=22.0,
        help="Expected baseline value. Default: 22.0",
    )
    parser.add_argument(
        "--threshold",
        type=float,
        default=None,
        help="Optional threshold value. Default: expected * 1.30",
    )
    parser.add_argument(
        "--timestamp",
        default="",
        help="Optional ISO-8601 timestamp. Default: current UTC time",
    )
    parser.add_argument(
        "--hours",
        type=int,
        default=168,
        help="Recent anomaly window used by the information center. Default: 168 hours",
    )
    parser.add_argument(
        "--severity",
        default="critical",
        help="Stored anomaly severity. Default: critical",
    )
    parser.add_argument(
        "--message",
        default="",
        help="Optional anomaly message shown in recent anomalies.",
    )
    parser.add_argument(
        "--source",
        default="script_inject",
        help="event_source field. Default: script_inject",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview the write without mutating the database.",
    )
    parser.add_argument(
        "--skip-cache-clear",
        action="store_true",
        help="Do not clear backend caches after writing.",
    )
    return parser.parse_args()


def _ensure_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _parse_timestamp(raw: str) -> datetime:
    return _ensure_utc(datetime.fromisoformat(raw)) or datetime.now(timezone.utc)


def _now_event_timestamp() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def _resolve_building_id(raw_value: str) -> str:
    normalized = normalize_building_type(raw_value)
    if normalized:
        return BUILDING_TYPE_TO_ID[normalized]
    return raw_value.strip() or DEFAULT_BUILDING_ID


async def _resolve_device_id(
    *,
    building_id: str,
    device_id: str,
    device_kind: str,
) -> str:
    explicit = device_id.strip()
    if explicit:
        return explicit

    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(Device.device_id)
            .where(
                Device.building_id == building_id,
                Device.device_type == device_kind,
            )
            .order_by(Device.device_id.asc())
            .limit(1)
        )
        resolved = result.scalar_one_or_none()

    if not resolved:
        raise RuntimeError(
            f"Could not resolve device for building={building_id!r}, device_kind={device_kind!r}",
        )
    return resolved


async def _capture_snapshot(hours: int) -> Snapshot:
    async with AsyncSessionLocal() as db:
        max_ts = _ensure_utc(await db.scalar(select(func.max(AnomalyEvent.data_timestamp))))

        recent_anomaly_count = 0
        if max_ts is not None:
            window_start = max_ts - timedelta(hours=hours)
            recent_anomaly_count = int(
                await db.scalar(
                    select(func.count(AnomalyEvent.id)).where(
                        AnomalyEvent.data_timestamp >= window_start,
                        AnomalyEvent.data_timestamp <= max_ts,
                    )
                )
                or 0
            )

        pending_review_count = int(
            await db.scalar(
                select(func.count(AnomalyIncident.id)).where(
                    AnomalyIncident.workflow_status == "pending_review",
                    AnomalyIncident.is_active == True,  # noqa: E712
                )
            )
            or 0
        )

    return Snapshot(
        max_anomaly_ts=max_ts,
        recent_anomaly_count=recent_anomaly_count,
        pending_review_count=pending_review_count,
    )


async def _event_exists(
    *,
    data_timestamp: datetime,
    building_id: str,
) -> bool:
    async with AsyncSessionLocal() as db:
        existing = await db.scalar(
            select(AnomalyEvent.id).where(
                AnomalyEvent.data_timestamp == data_timestamp,
                AnomalyEvent.building_id == building_id,
            )
        )
    return existing is not None


async def _resolve_unique_event_timestamp(
    *,
    base_timestamp: datetime,
    building_id: str,
) -> datetime:
    candidate = base_timestamp
    for _ in range(120):
        if not await _event_exists(data_timestamp=candidate, building_id=building_id):
            return candidate
        candidate = candidate + timedelta(seconds=1)
    raise RuntimeError(
        f"Could not find a unique timestamp near {base_timestamp.isoformat()} for building {building_id}.",
    )


def _recent_window_bounds(
    *,
    snapshot: Snapshot,
    hours: int,
) -> tuple[datetime | None, datetime | None]:
    if snapshot.max_anomaly_ts is None:
        return None, None
    return snapshot.max_anomaly_ts - timedelta(hours=hours), snapshot.max_anomaly_ts


async def _clear_relevant_caches() -> None:
    for prefix in (
        "anomalies:",
        "incidents:",
        "workorders:",
        "overview:",
        "home:bundle:",
        "operations:bundle:",
    ):
        await delete_cache_by_prefix(prefix)


async def _insert_event_row(
    *,
    db,
    event_ts: datetime,
    building_id: str,
    device_id: str,
    rule: str,
    actual_value: float,
    threshold_value: float,
    expected_value: float,
    deviation_pct: float | None,
    root_cause: str | None,
    message: str,
    source: str,
    severity: str,
) -> tuple[str, datetime | None]:
    insert_sql = text(
        """
        INSERT INTO anomaly_events (
            data_timestamp,
            building_id,
            meter_device_id,
            rule_triggered,
            actual_value,
            threshold_value,
            expected_value,
            deviation_pct,
            hvac_root_cause,
            message,
            is_resolved,
            anomaly_phase,
            symptom_flags_json,
            event_source,
            severity
        )
        VALUES (
            :data_timestamp,
            :building_id,
            :meter_device_id,
            :rule_triggered,
            :actual_value,
            :threshold_value,
            :expected_value,
            :deviation_pct,
            :hvac_root_cause,
            :message,
            :is_resolved,
            :anomaly_phase,
            CAST(:symptom_flags_json AS jsonb),
            :event_source,
            :severity
        )
        RETURNING id::text, detected_at
        """
    )
    row = (
        await db.execute(
            insert_sql,
            {
                "data_timestamp": event_ts,
                "building_id": building_id,
                "meter_device_id": device_id,
                "rule_triggered": rule,
                "actual_value": actual_value,
                "threshold_value": threshold_value,
                "expected_value": expected_value,
                "deviation_pct": deviation_pct,
                "hvac_root_cause": root_cause,
                "message": message,
                "is_resolved": False,
                "anomaly_phase": "full",
                "symptom_flags_json": "null",
                "event_source": source,
                "severity": severity,
            },
        )
    ).one()
    return str(row[0]), _ensure_utc(row[1])


async def _load_inserted_event(
    *,
    db,
    event_ts: datetime,
    building_id: str,
) -> AnomalyEvent:
    event = (
        await db.execute(
            select(AnomalyEvent).where(
                AnomalyEvent.data_timestamp == event_ts,
                AnomalyEvent.building_id == building_id,
                )
            )
        ).scalar_one()
    return event


async def _run(args: argparse.Namespace) -> int:
    before = await _capture_snapshot(args.hours)
    building_id = _resolve_building_id(args.building_id)
    device_id = await _resolve_device_id(
        building_id=building_id,
        device_id=args.device_id,
        device_kind=args.device_kind,
    )

    requested_event_ts = (
        _parse_timestamp(args.timestamp)
        if args.timestamp.strip()
        else _now_event_timestamp()
    )
    event_ts = await _resolve_unique_event_timestamp(
        base_timestamp=requested_event_ts,
        building_id=building_id,
    )

    rule = args.rule.strip() or DEFAULT_RULE_BY_DEVICE_KIND[args.device_kind]
    expected_value = float(args.expected)
    actual_value = float(args.actual)
    threshold_value = (
        float(args.threshold)
        if args.threshold is not None
        else round(expected_value * 1.30, 2)
    )
    deviation_pct = (
        round(((actual_value - expected_value) / expected_value) * 100, 2)
        if expected_value
        else None
    )
    root_cause = args.root_cause.strip() or None
    if rule not in {"hvac_overconsumption", "flag_hvac_energy"}:
        root_cause = None

    message = args.message.strip() or (
        f"脚本注入异常数据：{building_id} 在 {event_ts.isoformat()} 触发 {rule}，"
        f"用于验证信息中心异常告警和工单联动。"
    )

    recent_start, recent_end = _recent_window_bounds(snapshot=before, hours=args.hours)
    visible_in_recent_window = (
        recent_start is None
        or recent_end is None
        or (recent_start <= event_ts <= recent_end)
    )

    print("== Injection Preview ==")
    print(f"building_id: {building_id}")
    print(f"device_id:   {device_id}")
    print(f"rule:        {rule}")
    print(f"root_cause:  {root_cause or '-'}")
    print(f"requested_timestamp: {requested_event_ts.isoformat()}")
    print(f"timestamp:   {event_ts.isoformat()}")
    print(f"actual:      {actual_value}")
    print(f"expected:    {expected_value}")
    print(f"threshold:   {threshold_value}")
    print(f"deviation:   {deviation_pct if deviation_pct is not None else '-'}")
    print(f"severity:    {args.severity}")
    print(f"recent anomalies before:      {before.recent_anomaly_count}")
    print(f"pending_review dynamics before: {before.pending_review_count}")
    if recent_start and recent_end:
        print(f"recent_window_by_api: {recent_start.isoformat()} -> {recent_end.isoformat()}")
        print(f"visible_in_recent_window: {visible_in_recent_window}")
        if not visible_in_recent_window:
            print(
                "warning: this timestamp is outside the current /api/anomalies/recent window, "
                "so recent anomaly count may not increase."
            )

    if args.dry_run:
        print("dry_run:     true")
        return 0

    async with AsyncSessionLocal() as db:
        inserted_event_id, _detected_at = await _insert_event_row(
            db=db,
            event_ts=event_ts,
            building_id=building_id,
            device_id=device_id,
            rule=rule,
            actual_value=actual_value,
            threshold_value=threshold_value,
            expected_value=expected_value,
            deviation_pct=deviation_pct,
            root_cause=root_cause,
            message=message,
            source=args.source.strip() or "script_inject",
            severity=args.severity.strip() or "critical",
        )

        event = await _load_inserted_event(
            db=db,
            event_ts=event_ts,
            building_id=building_id,
        )

        incident, work_order, created_new = await create_or_merge_alert_incident(
            db,
            event=event,
        )
        if incident is None or work_order is None:
            await db.rollback()
            raise RuntimeError("Failed to materialize incident/work order from the injected anomaly event.")
        if not created_new:
            await db.rollback()
            raise RuntimeError(
                "The injected anomaly would merge into an existing incident instead of creating a new work order. "
                "Use --timestamp with a later value or change the building/rule/device combination."
            )

        await db.commit()

    if not args.skip_cache_clear:
        await _clear_relevant_caches()

    after = await _capture_snapshot(args.hours)

    print("== Injection Result ==")
    print(f"anomaly_event_id:  {inserted_event_id}")
    print(f"incident_id:       {incident.incident_id}")
    print(f"incident_row_id:   {incident.id}")
    print(f"work_order_id:     {work_order.id}")
    print(f"ticket_id:         {work_order.ticket_id}")
    print(
        "recent anomalies:  "
        f"{before.recent_anomaly_count} -> {after.recent_anomaly_count} "
        f"({after.recent_anomaly_count - before.recent_anomaly_count:+d})"
    )
    print(
        "pending_review dynamics: "
        f"{before.pending_review_count} -> {after.pending_review_count} "
        f"({after.pending_review_count - before.pending_review_count:+d})"
    )
    print(f"cache_cleared:     {not args.skip_cache_clear}")
    return 0


def main() -> int:
    args = _parse_args()
    return asyncio.run(_run(args))


if __name__ == "__main__":
    raise SystemExit(main())
