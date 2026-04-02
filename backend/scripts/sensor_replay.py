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
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _ensure_import_path() -> tuple[Path, Path]:
    repo_root = Path(__file__).resolve().parents[2]
    backend_dir = repo_root / "backend"
    if str(backend_dir) not in sys.path:
        sys.path.insert(0, str(backend_dir))
    return repo_root, backend_dir


REPO_ROOT, BACKEND_DIR = _ensure_import_path()

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

    def acquire(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "pid": os.getpid(),
            "started_at": datetime.now(timezone.utc).isoformat(),
        }
        try:
            with self.path.open("x", encoding="utf-8") as fh:
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
        finally:
            self.acquired = False

    def __enter__(self) -> "LockFile":
        self.acquire()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.release()


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
    return json.loads(checkpoint_path.read_text(encoding="utf-8"))


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
    checkpoint_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


async def ingest_round(round_item: ReplayRound, ingest_ts: datetime) -> list[str]:
    params: list[dict[str, Any]] = []
    building_ids: list[str] = []
    for row in round_item.rows:
        params.append(
            {
                "timestamp": ingest_ts,
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
            :air_temp_c,
            :dew_temp_c,
            :humidity_rh_pct,
            :water_m3,
            :electricity_kwh,
            :sim_supply_temp_c,
            :sim_return_temp_c,
            :hac_energy
        )
        ON CONFLICT (timestamp, building_id) DO UPDATE SET
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

    async with AsyncSessionLocal() as session:
        await session.execute(sql, params)
        await session.commit()

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

    for offset, round_item in enumerate(rounds[start_index:]):
        if offset > 0:
            target_monotonic = schedule_anchor + offset * ROUND_INTERVAL_SECONDS
            wait_seconds = target_monotonic - time.monotonic()
            if wait_seconds > 0:
                logger.info("等待 %.1f 秒后执行下一轮", wait_seconds)
                await asyncio.sleep(wait_seconds)

        ingest_ts = datetime.now(timezone.utc)
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
