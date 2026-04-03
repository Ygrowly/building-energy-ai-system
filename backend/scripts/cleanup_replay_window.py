from __future__ import annotations

import argparse
import asyncio
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any


def _ensure_import_path() -> Path:
    backend_dir = Path(__file__).resolve().parents[1]
    if str(backend_dir) not in sys.path:
        sys.path.insert(0, str(backend_dir))
    return backend_dir


BACKEND_DIR = _ensure_import_path()


def _load_backend_env() -> None:
    env_path = BACKEND_DIR / ".env"
    if not env_path.is_file():
        return
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
        os.environ[key] = value


_load_backend_env()

from sqlalchemy import text

from app.db.session import AsyncSessionLocal


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="按实际写入时间窗口清理传感器回放数据及其派生表")
    parser.add_argument("--actual-start", required=True, help="实际写入时间起点，ISO8601")
    parser.add_argument("--actual-end", required=True, help="实际写入时间终点，ISO8601")
    parser.add_argument(
        "--building-id",
        action="append",
        dest="building_ids",
        default=[],
        help="可重复传入；为空则自动按 energy_data 命中的楼宇清理",
    )
    parser.add_argument("--dry-run", action="store_true", help="仅统计将要删除的记录数")
    return parser.parse_args()


def _parse_ts(raw: str) -> datetime:
    return datetime.fromisoformat(raw.replace("Z", "+00:00"))


async def _resolve_buildings(t0: datetime, t1: datetime, building_ids: list[str]) -> list[str]:
    if building_ids:
        seen: set[str] = set()
        ordered: list[str] = []
        for bid in building_ids:
            if bid and bid not in seen:
                seen.add(bid)
                ordered.append(bid)
        return ordered

    async with AsyncSessionLocal() as session:
        result = await session.execute(
            text("""
                SELECT DISTINCT building_id
                FROM energy_data
                WHERE timestamp >= :t0 AND timestamp <= :t1
                ORDER BY building_id
            """),
            {"t0": t0, "t1": t1},
        )
        return [row[0] for row in result.fetchall()]


async def _count_rows(t0: datetime, t1: datetime, building_ids: list[str]) -> dict[str, int]:
    params = {"t0": t0, "t1": t1, "bids": building_ids}
    sql_map = {
        "energy_data": """
            SELECT COUNT(*) FROM energy_data
            WHERE building_id = ANY(:bids) AND timestamp >= :t0 AND timestamp <= :t1
        """,
        "kpi_expected_hourly": """
            SELECT COUNT(*) FROM kpi_expected_hourly
            WHERE building_id = ANY(:bids) AND timestamp >= :t0 AND timestamp <= :t1
        """,
        "kpi_anomaly_flags": """
            SELECT COUNT(*) FROM kpi_anomaly_flags
            WHERE building_id = ANY(:bids) AND timestamp >= :t0 AND timestamp <= :t1
        """,
        "anomaly_events": """
            SELECT COUNT(*) FROM anomaly_events
            WHERE building_id = ANY(:bids) AND data_timestamp >= :t0 AND data_timestamp <= :t1
        """,
        "device_telemetry_hourly": """
            SELECT COUNT(*) FROM device_telemetry_hourly
            WHERE building_id = ANY(:bids) AND timestamp >= :t0 AND timestamp <= :t1
        """,
        "anomaly_device_attributions": """
            SELECT COUNT(*) FROM anomaly_device_attributions
            WHERE building_id = ANY(:bids) AND timestamp >= :t0 AND timestamp <= :t1
        """,
    }

    counts: dict[str, int] = {}
    async with AsyncSessionLocal() as session:
        for key, sql in sql_map.items():
            result = await session.execute(text(sql), params)
            counts[key] = int(result.scalar() or 0)
    return counts


async def _rebuild_latest_status(building_ids: list[str]) -> int:
    if not building_ids:
        return 0
    async with AsyncSessionLocal() as session:
        await session.execute(
            text("DELETE FROM device_status_latest WHERE building_id = ANY(:bids)"),
            {"bids": building_ids},
        )
        result = await session.execute(
            text("""
                INSERT INTO device_status_latest
                  (device_id, building_id, device_type,
                   last_seen_at, online_status, running_state, health_status,
                   latest_power_kw, latest_flow_rate,
                   latest_supply_temp_c, latest_return_temp_c, latest_payload_json)
                SELECT DISTINCT ON (device_id)
                    device_id,
                    building_id,
                    device_type,
                    timestamp,
                    online_status,
                    running_state,
                    health_status,
                    power_kw,
                    flow_rate,
                    supply_temp_c,
                    return_temp_c,
                    metric_payload_json
                FROM device_telemetry_hourly
                WHERE building_id = ANY(:bids)
                ORDER BY device_id, timestamp DESC
            """),
            {"bids": building_ids},
        )
        await session.commit()
        return result.rowcount or 0


async def cleanup_window(args: argparse.Namespace) -> int:
    t0 = _parse_ts(args.actual_start)
    t1 = _parse_ts(args.actual_end)
    if t1 < t0:
        raise ValueError("--actual-end 不能早于 --actual-start")

    building_ids = await _resolve_buildings(t0, t1, args.building_ids)
    if not building_ids:
        print("[INFO] 指定窗口内没有命中的楼宇或 energy_data 记录")
        return 0

    counts = await _count_rows(t0, t1, building_ids)
    print(f"[INFO] buildings={building_ids}")
    for table_name, count in counts.items():
        print(f"[INFO] {table_name}: {count}")

    if args.dry_run:
        print("[DONE] dry-run only")
        return 0

    params = {"t0": t0, "t1": t1, "bids": building_ids}
    delete_sql = [
        """
        DELETE FROM anomaly_device_attributions
        WHERE building_id = ANY(:bids) AND timestamp >= :t0 AND timestamp <= :t1
        """,
        """
        DELETE FROM anomaly_events
        WHERE building_id = ANY(:bids) AND data_timestamp >= :t0 AND data_timestamp <= :t1
        """,
        """
        DELETE FROM kpi_anomaly_flags
        WHERE building_id = ANY(:bids) AND timestamp >= :t0 AND timestamp <= :t1
        """,
        """
        DELETE FROM kpi_expected_hourly
        WHERE building_id = ANY(:bids) AND timestamp >= :t0 AND timestamp <= :t1
        """,
        """
        DELETE FROM device_telemetry_hourly
        WHERE building_id = ANY(:bids) AND timestamp >= :t0 AND timestamp <= :t1
        """,
        """
        DELETE FROM energy_data
        WHERE building_id = ANY(:bids) AND timestamp >= :t0 AND timestamp <= :t1
        """,
    ]

    async with AsyncSessionLocal() as session:
        for sql in delete_sql:
            await session.execute(text(sql), params)
        await session.commit()

    rebuilt = await _rebuild_latest_status(building_ids)
    print(f"[DONE] cleanup complete, rebuilt device_status_latest rows={rebuilt}")
    return 0


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
    except Exception:
        pass

    args = parse_args()
    return asyncio.run(cleanup_window(args))


if __name__ == "__main__":
    raise SystemExit(main())
