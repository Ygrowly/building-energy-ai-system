from __future__ import annotations

import argparse
import asyncio
import csv
import json
import logging
import os
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


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
    if not env_path.is_file():
        return
    _merge_env_file(env_path, override=False)


_load_backend_env()

from sqlalchemy import select, text
from sqlalchemy.exc import SQLAlchemyError

from app.db.models import Building
from app.db.session import AsyncSessionLocal
from app.services.pipeline_refresh_service import run_pipeline_for_buildings

logger = logging.getLogger("sensor_replay")

CSV_NUMERIC_FIELDS = (
    "air_temp_c",
    "dew_temp_c",
    "humidity_rh_pct",
    "water_m3",
    "electricity_kwh",
    "sim_supply_temp_c",
    "sim_return_temp_c",
    "hac_energy",
)
CSV_REQUIRED_FIELDS = ("timestamp", "building_id", *CSV_NUMERIC_FIELDS)
DEFAULT_CSV_PATH = REPO_ROOT / "data_2026_apr_dec.csv"
DEFAULT_STATE_DIR = BACKEND_DIR / "runtime"
ROUND_INTERVAL_SECONDS = 3600.0


@dataclass(frozen=True)
class ReplayRow:
    source_timestamp: datetime
    building_id: str
    values: dict[str, float | None]


@dataclass(frozen=True)
class ReplayRound:
    index: int
    source_timestamp: datetime
    rows: tuple[ReplayRow, ...]


class LockFile:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.acquired = False

    def _read_payload(self) -> dict[str, Any] | None:
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        return payload if isinstance(payload, dict) else None

    def _can_reclaim(self) -> bool:
        payload = self._read_payload()
        if payload and payload.get("released_at"):
            return True
        pid = payload.get("pid") if payload else None
        if isinstance(pid, int) and _pid_is_running(pid):
            return False
        return True

    def acquire(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        reclaimed_existing = False
        if self.path.exists():
            if not self._can_reclaim():
                raise RuntimeError(
                    f"检测到已有运行中的回放实例，锁文件存在: {self.path}"
                )
            logger.warning("检测到陈旧锁文件，已自动接管: %s", self.path)
            try:
                self.path.unlink(missing_ok=True)
            except PermissionError:
                reclaimed_existing = True
        payload = {
            "pid": os.getpid(),
            "started_at": datetime.now(timezone.utc).isoformat(),
        }
        try:
            open_mode = "w" if reclaimed_existing else "x"
            with self.path.open(open_mode, encoding="utf-8") as fh:
                json.dump(payload, fh, ensure_ascii=False, indent=2)
            self.acquired = True
        except FileExistsError as exc:
            raise RuntimeError(
                f"检测到已有运行中的回放实例，锁文件存在: {self.path}"
            ) from exc

    def release(self) -> None:
        if not self.acquired:
            return
        try:
            self.path.unlink(missing_ok=True)
        except PermissionError:
            payload = {
                "pid": os.getpid(),
                "released_at": datetime.now(timezone.utc).isoformat(),
            }
            self.path.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        finally:
            self.acquired = False

    def __enter__(self) -> "LockFile":
        self.acquire()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.release()


def _pid_is_running(pid: int) -> bool:
    if pid <= 0:
        return False
    if pid == os.getpid():
        return True
    try:
        os.kill(pid, 0)
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def _parse_float(raw: str | None, *, field_name: str, row_number: int) -> float | None:
    if raw is None:
        return None
    value = raw.strip()
    if not value:
        return None
    try:
        return float(value)
    except ValueError as exc:
        raise ValueError(f"第 {row_number} 行字段 {field_name} 不是合法数值: {raw!r}") from exc


def load_replay_rounds(csv_path: Path) -> list[ReplayRound]:
    if not csv_path.is_file():
        raise FileNotFoundError(f"未找到 CSV 文件: {csv_path}")

    rounds_by_ts: dict[datetime, list[ReplayRow]] = {}
    with csv_path.open("r", encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        header = tuple(reader.fieldnames or ())
        missing = [field for field in CSV_REQUIRED_FIELDS if field not in header]
        if missing:
            raise ValueError(f"CSV 缺少必要列: {', '.join(missing)}")

        for row_number, raw in enumerate(reader, start=2):
            try:
                source_timestamp = datetime.fromisoformat((raw.get("timestamp") or "").strip())
            except ValueError as exc:
                raise ValueError(f"第 {row_number} 行 timestamp 非法: {raw.get('timestamp')!r}") from exc

            building_id = (raw.get("building_id") or "").strip()
            if not building_id:
                raise ValueError(f"第 {row_number} 行 building_id 为空")

            values = {
                field: _parse_float(raw.get(field), field_name=field, row_number=row_number)
                for field in CSV_NUMERIC_FIELDS
            }
            row = ReplayRow(
                source_timestamp=source_timestamp,
                building_id=building_id,
                values=values,
            )
            rounds_by_ts.setdefault(source_timestamp, []).append(row)

    rounds: list[ReplayRound] = []
    for index, source_timestamp in enumerate(sorted(rounds_by_ts.keys())):
        rows = tuple(rounds_by_ts[source_timestamp])
        rounds.append(
            ReplayRound(
                index=index,
                source_timestamp=source_timestamp,
                rows=rows,
            )
        )
    if not rounds:
        raise ValueError("CSV 中没有可回放的数据")
    return rounds


async def validate_building_ids(rounds: list[ReplayRound]) -> None:
    csv_buildings = sorted({row.building_id for round_item in rounds for row in round_item.rows})
    try:
        async with AsyncSessionLocal() as session:
            result = await session.execute(select(Building.building_id))
            db_buildings = {row[0] for row in result.fetchall()}
    except (OSError, SQLAlchemyError) as exc:
        raise RuntimeError(
            "数据库连接失败。请先确认 backend/.env 中的 DATABASE_URL 可达，"
            "并确认目标 PostgreSQL/Supabase 实例已允许当前机器连接。"
        ) from exc

    invalid = [bid for bid in csv_buildings if bid not in db_buildings]
    if invalid:
        raise ValueError(f"CSV 中存在未注册楼宇 ID: {', '.join(invalid)}")


def load_checkpoint(checkpoint_path: Path) -> dict[str, Any] | None:
    if not checkpoint_path.is_file():
        return None
    try:
        payload = json.loads(checkpoint_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"checkpoint 文件损坏，请删除后重试: {checkpoint_path}") from exc
    if not isinstance(payload, dict):
        raise RuntimeError(f"checkpoint 内容非法，请删除后重试: {checkpoint_path}")
    return payload


def save_checkpoint(
    checkpoint_path: Path,
    *,
    next_round_index: int,
    round_item: ReplayRound,
    ingest_ts: datetime,
) -> None:
    checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "next_round_index": next_round_index,
        "source_hour_index": round_item.index,
        "source_timestamp": round_item.source_timestamp.isoformat(sep=" "),
        "last_ingest_ts": ingest_ts.isoformat(),
        "rows_written": len(round_item.rows),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    serialized = json.dumps(payload, ensure_ascii=False, indent=2)
    temp_path = checkpoint_path.with_name(f"{checkpoint_path.name}.{os.getpid()}.tmp")
    temp_path.write_text(
        serialized,
        encoding="utf-8",
    )
    try:
        temp_path.replace(checkpoint_path)
    except PermissionError:
        checkpoint_path.write_text(serialized, encoding="utf-8")
        try:
            temp_path.unlink(missing_ok=True)
        except PermissionError:
            pass


def _ensure_utc_timestamp(ts: datetime) -> datetime:
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return ts.astimezone(timezone.utc)


def _align_to_hour(ts: datetime) -> datetime:
    return _ensure_utc_timestamp(ts).replace(minute=0, second=0, microsecond=0)


def _parse_checkpoint_timestamp(raw: Any) -> datetime | None:
    if not isinstance(raw, str) or not raw.strip():
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    return _ensure_utc_timestamp(parsed)


def build_ingest_anchor(
    checkpoint: dict[str, Any] | None,
    *,
    now: datetime | None = None,
) -> datetime:
    anchor = _align_to_hour(now or datetime.now(timezone.utc))
    if not checkpoint:
        return anchor
    last_ingest_ts = _parse_checkpoint_timestamp(checkpoint.get("last_ingest_ts"))
    if last_ingest_ts is None:
        return anchor
    next_after_checkpoint = _align_to_hour(last_ingest_ts) + timedelta(hours=1)
    if next_after_checkpoint > anchor:
        return next_after_checkpoint
    return anchor


async def load_existing_round_actual_timestamps(
    round_item: ReplayRound,
) -> dict[str, datetime]:
    building_ids = sorted({row.building_id for row in round_item.rows if row.building_id})
    if not building_ids:
        return {}

    source_timestamp = _ensure_utc_timestamp(round_item.source_timestamp)
    try:
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                text(
                    """
                    SELECT building_id, timestamp
                    FROM energy_data
                    WHERE source_timestamp = :source_timestamp
                      AND building_id = ANY(:building_ids)
                    """
                ),
                {
                    "source_timestamp": source_timestamp,
                    "building_ids": building_ids,
                },
            )
            rows = result.fetchall()
    except (OSError, SQLAlchemyError) as exc:
        raise RuntimeError("读取已有回放状态失败，请确认数据库连接可用") from exc

    existing: dict[str, datetime] = {}
    for building_id, actual_ts in rows:
        if actual_ts is None:
            continue
        existing[str(building_id)] = _ensure_utc_timestamp(actual_ts)
    return existing


async def _delete_pipeline_outputs_for_timestamp(
    building_ids: list[str],
    target_timestamp: datetime,
) -> dict[str, int]:
    if not building_ids:
        return {}

    target_timestamp = _ensure_utc_timestamp(target_timestamp)
    params = {
        "building_ids": building_ids,
        "target_timestamp": target_timestamp,
    }
    sql_map = {
        "anomaly_device_attributions": """
            DELETE FROM anomaly_device_attributions
            WHERE building_id = ANY(:building_ids)
              AND timestamp = :target_timestamp
        """,
        "anomaly_events": """
            DELETE FROM anomaly_events
            WHERE building_id = ANY(:building_ids)
              AND data_timestamp = :target_timestamp
        """,
        "kpi_anomaly_flags": """
            DELETE FROM kpi_anomaly_flags
            WHERE building_id = ANY(:building_ids)
              AND timestamp = :target_timestamp
        """,
        "kpi_expected_hourly": """
            DELETE FROM kpi_expected_hourly
            WHERE building_id = ANY(:building_ids)
              AND timestamp = :target_timestamp
        """,
        "device_telemetry_hourly": """
            DELETE FROM device_telemetry_hourly
            WHERE building_id = ANY(:building_ids)
              AND timestamp = :target_timestamp
        """,
    }

    counts: dict[str, int] = {}
    async with AsyncSessionLocal() as session:
        for table_name, sql in sql_map.items():
            result = await session.execute(text(sql), params)
            counts[table_name] = int(result.rowcount or 0)
        await session.commit()
    return counts


async def _rebuild_latest_device_status(building_ids: list[str]) -> int:
    if not building_ids:
        return 0
    async with AsyncSessionLocal() as session:
        await session.execute(
            text("DELETE FROM device_status_latest WHERE building_id = ANY(:building_ids)"),
            {"building_ids": building_ids},
        )
        result = await session.execute(
            text(
                """
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
                WHERE building_id = ANY(:building_ids)
                ORDER BY device_id, timestamp DESC
                """
            ),
            {"building_ids": building_ids},
        )
        await session.commit()
        return int(result.rowcount or 0)


async def cleanup_stale_round_outputs(
    existing_actual_timestamps: dict[str, datetime],
    *,
    current_ingest_ts: datetime,
) -> dict[str, Any]:
    current_ingest_ts = _ensure_utc_timestamp(current_ingest_ts)
    grouped: dict[datetime, list[str]] = {}

    for building_id, actual_ts in existing_actual_timestamps.items():
        normalized_ts = _ensure_utc_timestamp(actual_ts)
        if normalized_ts == current_ingest_ts:
            continue
        grouped.setdefault(normalized_ts, []).append(building_id)

    if not grouped:
        return {"deleted": {}, "status_rebuilt": 0}

    deleted: dict[str, dict[str, int]] = {}
    affected_buildings: set[str] = set()
    for target_timestamp in sorted(grouped.keys()):
        building_ids = sorted(set(grouped[target_timestamp]))
        deleted[target_timestamp.isoformat()] = await _delete_pipeline_outputs_for_timestamp(
            building_ids,
            target_timestamp,
        )
        affected_buildings.update(building_ids)

    rebuilt = await _rebuild_latest_device_status(sorted(affected_buildings))
    return {
        "deleted": deleted,
        "status_rebuilt": rebuilt,
    }


async def ingest_round(round_item: ReplayRound, ingest_ts: datetime) -> list[str]:
    ingest_ts = _ensure_utc_timestamp(ingest_ts)
    params: list[dict[str, Any]] = []
    building_ids: list[str] = []
    for row in round_item.rows:
        params.append(
            {
                "timestamp": ingest_ts,
                "source_timestamp": _ensure_utc_timestamp(row.source_timestamp),
                "building_id": row.building_id,
                **row.values,
            }
        )
        building_ids.append(row.building_id)

    sql = text(
        """
        INSERT INTO energy_data (
            timestamp,
            building_id,
            source_timestamp,
            air_temp_c,
            dew_temp_c,
            humidity_rh_pct,
            water_m3,
            electricity_kwh,
            sim_supply_temp_c,
            sim_return_temp_c,
            hac_energy
        )
        VALUES (
            :timestamp,
            :building_id,
            :source_timestamp,
            :air_temp_c,
            :dew_temp_c,
            :humidity_rh_pct,
            :water_m3,
            :electricity_kwh,
            :sim_supply_temp_c,
            :sim_return_temp_c,
            :hac_energy
        )
        ON CONFLICT (building_id, source_timestamp) DO UPDATE SET
            timestamp = EXCLUDED.timestamp,
            air_temp_c = EXCLUDED.air_temp_c,
            dew_temp_c = EXCLUDED.dew_temp_c,
            humidity_rh_pct = EXCLUDED.humidity_rh_pct,
            water_m3 = EXCLUDED.water_m3,
            electricity_kwh = EXCLUDED.electricity_kwh,
            sim_supply_temp_c = EXCLUDED.sim_supply_temp_c,
            sim_return_temp_c = EXCLUDED.sim_return_temp_c,
            hac_energy = EXCLUDED.hac_energy
        """
    )

    try:
        async with AsyncSessionLocal() as session:
            await session.execute(sql, params)
            await session.commit()
    except (OSError, SQLAlchemyError) as exc:
        raise RuntimeError(
            "写入 energy_data 失败。请先确认已执行 "
            "`python backend/scripts/run_migration_016.py`，"
            "并检查 energy_data.source_timestamp 与唯一索引是否已生效。"
        ) from exc

    deduped: list[str] = []
    seen: set[str] = set()
    for bid in building_ids:
        if bid not in seen:
            seen.add(bid)
            deduped.append(bid)
    return deduped


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="按 CSV 模拟传感器实时接入并刷新下游链路")
    parser.add_argument("--csv-path", type=Path, default=DEFAULT_CSV_PATH)
    parser.add_argument(
        "--checkpoint-file",
        type=Path,
        default=DEFAULT_STATE_DIR / "sensor_replay_checkpoint.json",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="从 checkpoint 恢复（默认行为，除非显式传 --reset）",
    )
    parser.add_argument("--reset", action="store_true", help="忽略 checkpoint，从第一轮重新开始")
    parser.add_argument("--dry-run", action="store_true", help="仅校验 CSV 与数据库楼宇，不写库也不启动长跑")
    parser.add_argument("--log-level", default="INFO")
    return parser


def configure_logging(level_name: str) -> None:
    level = getattr(logging, level_name.upper(), logging.INFO)
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s - %(message)s",
        force=True,
    )


async def replay(args: argparse.Namespace) -> int:
    rounds = load_replay_rounds(args.csv_path)
    await validate_building_ids(rounds)

    logger.info(
        "已加载 %d 轮回放数据，范围 %s -> %s",
        len(rounds),
        rounds[0].source_timestamp,
        rounds[-1].source_timestamp,
    )

    if args.dry_run:
        logger.info("dry-run 完成：CSV 校验通过，数据库楼宇校验通过")
        return 0

    checkpoint = None if args.reset else load_checkpoint(args.checkpoint_file)
    start_index = int(checkpoint.get("next_round_index", 0)) if checkpoint else 0
    if start_index >= len(rounds):
        logger.info("checkpoint 指向末尾，无需继续回放")
        return 0

    logger.info("从第 %d/%d 轮开始回放", start_index + 1, len(rounds))
    schedule_anchor = time.monotonic()
    ingest_anchor = build_ingest_anchor(checkpoint)

    for offset, round_item in enumerate(rounds[start_index:]):
        if offset > 0:
            target_monotonic = schedule_anchor + offset * ROUND_INTERVAL_SECONDS
            wait_seconds = target_monotonic - time.monotonic()
            if wait_seconds > 0:
                logger.info("等待 %.1f 秒后执行下一轮", wait_seconds)
                await asyncio.sleep(wait_seconds)

        ingest_ts = ingest_anchor + timedelta(seconds=offset * ROUND_INTERVAL_SECONDS)
        existing_actual_timestamps = await load_existing_round_actual_timestamps(round_item)
        cleanup_summary = await cleanup_stale_round_outputs(
            existing_actual_timestamps,
            current_ingest_ts=ingest_ts,
        )
        if cleanup_summary["deleted"]:
            logger.info(
                "已清理旧派生数据，源时间=%s，写入时间=%s，清理摘要=%s",
                round_item.source_timestamp,
                ingest_ts.isoformat(),
                cleanup_summary,
            )
        logger.info(
            "开始回放第 %d/%d 轮，源时间=%s，写入时间=%s，行数=%d",
            round_item.index + 1,
            len(rounds),
            round_item.source_timestamp,
            ingest_ts.isoformat(),
            len(round_item.rows),
        )

        building_ids = await ingest_round(round_item, ingest_ts)
        expected_summary, detection_summary = await run_pipeline_for_buildings(
            building_ids,
            clear_mode="scoped",
            target_timestamps={ingest_ts},
        )
        save_checkpoint(
            args.checkpoint_file,
            next_round_index=round_item.index + 1,
            round_item=round_item,
            ingest_ts=ingest_ts,
        )
        logger.info(
            "第 %d 轮完成，buildings=%s expected=%s detection=%s",
            round_item.index + 1,
            ",".join(building_ids),
            expected_summary,
            detection_summary,
        )

    logger.info("全部回放轮次已完成")
    return 0


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
    except Exception:
        pass

    parser = build_parser()
    args = parser.parse_args()
    configure_logging(args.log_level)

    lock_path = args.checkpoint_file.with_suffix(args.checkpoint_file.suffix + ".lock")
    with LockFile(lock_path):
        try:
            return asyncio.run(replay(args))
        except KeyboardInterrupt:
            logger.warning("回放被手动中断")
            return 130
        except Exception as exc:
            logger.error("传感器回放启动失败: %s", exc)
            return 1


if __name__ == "__main__":
    raise SystemExit(main())
