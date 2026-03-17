"""
异常检测后台服务。

职责：
  1. 扫描 energy_data，对每条记录运行 4 条规则
  2. 将检测到的异常持久化写入 anomaly_events 表
  3. 支持全量历史扫描（首次启动）和增量扫描（此后定期执行）

数据库设计对齐：
  meter_device_id 字段现在优先取 devices 表中该楼宇的 ElectricityMeter 类型设备 ID，
  而非原先使用 building_id 充当的占位符。
  通过在扫描开始时一次性预查 devices 表构建映射缓存，避免 N+1 查询。

规则列表（以 Supabase 实际 schema 为准）：
  night_high_power  — 本地时间（UTC+8）0-6 点，electricity_kwh > 50
  high_hac_energy   — hac_energy 超当日批次均值 3 倍（暖通空调过耗）
  sensor_spike      — electricity_kwh 超当日批次均值 3 倍（传感器跳变）
  db_flagged        — energy_data.anomaly_status = 'Anomaly'（存量标注兜底）
"""
from __future__ import annotations

import asyncio
import logging
import statistics
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AnomalyEvent, Building, Device, EnergyData
from app.db.session import AsyncSessionLocal

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 阈值常量（与 physics_calc.py 保持一致，但夜间判断改用本地时间）
# ---------------------------------------------------------------------------
_TIMEZONE_OFFSET_H = 8          # 中国标准时 UTC+8
_NIGHT_START_LOCAL = 0          # 本地时间夜间开始（小时）
_NIGHT_END_LOCAL = 6            # 本地时间夜间结束（小时）
_NIGHT_POWER_THRESHOLD = 50.0   # kWh
_SPIKE_MULTIPLIER = 3.0         # 超过均值 N 倍判定为跳变
_SCAN_BATCH_HOURS = 24          # 每批扫描的时间窗口（小时）

_HIGH_HAC_ENERGY_MULTIPLIER = 3.0  # hac_energy 超均值 N 倍判定为暖通过耗

_BUILDING_NAMES: dict[str, str] = {
    "Education": "教学楼",
    "Office": "办公楼",
    "Public": "公共楼",
}


# ---------------------------------------------------------------------------
# 核心：单批次扫描并持久化
# ---------------------------------------------------------------------------

async def _load_meter_device_ids(session: AsyncSession) -> dict[str, str]:
    """
    一次性从 devices 表加载所有楼宇的主计量表设备 ID（ElectricityMeter 类型优先）。
    返回 {building_id: meter_device_id} 映射。
    若某楼宇无设备记录，退化为 building_id（向后兼容）。
    """
    result = await session.execute(
        select(Device.building_id, Device.device_id)
        .where(Device.device_type == "ElectricityMeter")
        .order_by(Device.building_id)
    )
    return {row[0]: row[1] for row in result.fetchall()}


async def scan_and_persist(
    batch_start: datetime,
    batch_end: datetime,
    session: AsyncSession,
) -> int:
    """
    扫描 [batch_start, batch_end) 时间段内所有建筑的能耗数据，
    运行规则检测，将新增异常写入 anomaly_events（幂等 UPSERT）。
    返回本次新写入的记录数。

    meter_device_id 现在从 devices 表查取真实电表设备 ID，
    而非原先用 building_id 充当的占位符。
    """
    # 预加载设备 ID 映射（避免 N+1 查询）
    meter_id_map = await _load_meter_device_ids(session)

    result = await session.execute(
        select(EnergyData, Building.primary_space_usage)
        .join(Building, EnergyData.building_id == Building.building_id)
        .where(EnergyData.timestamp >= batch_start)
        .where(EnergyData.timestamp < batch_end)
        .order_by(EnergyData.building_id, EnergyData.timestamp.asc())
    )
    rows = result.fetchall()

    if not rows:
        return 0

    # 按建筑分组，为均值类规则预计算当批次均值
    by_building: dict[str, list[EnergyData]] = {}
    for ed, _usage in rows:
        by_building.setdefault(ed.building_id, []).append(ed)

    elec_means: dict[str, float] = {}
    hac_means: dict[str, float] = {}
    for bid, recs in by_building.items():
        elec_vals = [r.electricity_kwh for r in recs if r.electricity_kwh is not None]
        elec_means[bid] = statistics.mean(elec_vals) if elec_vals else 0.0
        hac_vals = [r.hac_energy for r in recs if r.hac_energy is not None]
        hac_means[bid] = statistics.mean(hac_vals) if hac_vals else 0.0

    now = datetime.now(timezone.utc)
    to_insert: list[dict] = []

    for ed, usage in rows:
        ts: datetime = ed.timestamp
        hour_utc = ts.hour if ts.tzinfo else ts.replace(tzinfo=timezone.utc).hour
        hour_local = (hour_utc + _TIMEZONE_OFFSET_H) % 24
        elec_mean = elec_means.get(ed.building_id, 0.0)
        hac_mean = hac_means.get(ed.building_id, 0.0)
        display = _BUILDING_NAMES.get(usage or "", usage or ed.building_id)
        # 使用 devices 表中真实电表设备 ID；若无则退化为 building_id（向后兼容）
        meter_id = meter_id_map.get(ed.building_id, ed.building_id)

        # ── 规则 1：夜间高功率（本地 0-6 点）─────────────────────────────
        if (
            ed.electricity_kwh is not None
            and _NIGHT_START_LOCAL <= hour_local < _NIGHT_END_LOCAL
            and ed.electricity_kwh > _NIGHT_POWER_THRESHOLD
        ):
            to_insert.append(_make_record(
                ts, ed, meter_id, now,
                rule="night_high_power",
                actual=ed.electricity_kwh,
                threshold=_NIGHT_POWER_THRESHOLD,
                msg=f"{display}夜间能耗异常：{ed.electricity_kwh:.1f} kWh",
            ))

        # ── 规则 2：暖通空调高耗（超批次均值 3 倍，HAC 过耗告警）──────────
        if (
            ed.hac_energy is not None
            and hac_mean > 0
            and ed.hac_energy > hac_mean * _HIGH_HAC_ENERGY_MULTIPLIER
        ):
            spike_threshold = round(hac_mean * _HIGH_HAC_ENERGY_MULTIPLIER, 2)
            to_insert.append(_make_record(
                ts, ed, meter_id, now,
                rule="high_hac_energy",
                actual=ed.hac_energy,
                threshold=spike_threshold,
                msg=f"{display}暖通空调过耗：{ed.hac_energy:.1f} kWh（超均值 3 倍）",
            ))

        # ── 规则 3：传感器跳变（用电量超批次均值 3 倍）──────────────────
        if (
            ed.electricity_kwh is not None
            and elec_mean > 0
            and ed.electricity_kwh > elec_mean * _SPIKE_MULTIPLIER
        ):
            spike_threshold = round(elec_mean * _SPIKE_MULTIPLIER, 2)
            to_insert.append(_make_record(
                ts, ed, meter_id, now,
                rule="sensor_spike",
                actual=ed.electricity_kwh,
                threshold=spike_threshold,
                msg=f"{display}传感器跳变：{ed.electricity_kwh:.1f} kWh（超均值 3 倍）",
            ))

        # ── 规则 4：DB 存量标注兜底 ───────────────────────────────────────
        if ed.anomaly_status is not None and ed.anomaly_status == "Anomaly":
            to_insert.append(_make_record(
                ts, ed, meter_id, now,
                rule="db_flagged",
                actual=None,
                threshold=None,
                msg=f"{display}运行状态异常（系统标记）",
            ))

    if not to_insert:
        return 0

    # 一次 executemany 批量写入，比逐条 execute 快几十倍，日志也只输出一行
    try:
        await session.execute(
            text("""
                INSERT INTO anomaly_events
                    (id, detected_at, data_timestamp, building_id,
                     meter_device_id, rule_triggered, actual_value, threshold_value,
                     message, is_resolved)
                VALUES
                    (:id, :detected_at, :data_timestamp, :building_id,
                     :meter_device_id, :rule_triggered, :actual_value, :threshold_value,
                     :message, false)
                ON CONFLICT (data_timestamp, building_id, rule_triggered) DO NOTHING
            """),
            to_insert,  # 传入列表 → SQLAlchemy 自动使用 executemany
        )
        await session.commit()
    except Exception as exc:
        logger.error("[AnomalyDetector] 批量写入失败，回滚本批次: %s", exc)
        await session.rollback()
        return 0

    return len(to_insert)


def _make_record(
    ts: datetime,
    ed: EnergyData,
    meter_id: str,
    now: datetime,
    *,
    rule: str,
    actual: float | None,
    threshold: float | None,
    msg: str,
) -> dict:
    return {
        "id": str(uuid.uuid4()),
        "detected_at": now,
        "data_timestamp": ts,
        "building_id": ed.building_id,
        "meter_device_id": meter_id,
        "rule_triggered": rule,
        "actual_value": actual,
        "threshold_value": threshold,
        "message": msg,
    }


# ---------------------------------------------------------------------------
# 全量历史扫描（首次运行 / anomaly_events 为空时）
# ---------------------------------------------------------------------------

async def run_full_historical_scan() -> None:
    """扫描 energy_data 表中的所有历史数据，按 24h 分批写入 anomaly_events。"""
    logger.info("[AnomalyDetector] 开始全量历史扫描...")
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            text("SELECT MIN(timestamp), MAX(timestamp) FROM energy_data")
        )
        row = result.fetchone()
        if not row or row[0] is None:
            logger.info("[AnomalyDetector] energy_data 无数据，跳过扫描")
            return

        data_start: datetime = row[0]
        data_end: datetime = row[1]

    logger.info("[AnomalyDetector] 数据范围：%s → %s", data_start, data_end)
    total = 0
    current = data_start
    while current <= data_end:
        batch_end = current + timedelta(hours=_SCAN_BATCH_HOURS)
        async with AsyncSessionLocal() as batch_session:
            count = await scan_and_persist(current, batch_end, batch_session)
            total += count
        current = batch_end

    logger.info("[AnomalyDetector] 全量扫描完成，共写入 %d 条异常记录", total)


# ---------------------------------------------------------------------------
# 增量扫描（基于 anomaly_events 中最大 data_timestamp 作水位线）
# ---------------------------------------------------------------------------

async def run_incremental_scan() -> None:
    """
    从上次最新异常记录的时间戳起，扫描到当前时刻的新数据。
    若 anomaly_events 为空，则触发全量历史扫描。
    """
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            text("SELECT MAX(data_timestamp) FROM anomaly_events")
        )
        row = result.fetchone()
        last_ts: datetime | None = row[0] if row and row[0] else None

    if last_ts is None:
        await run_full_historical_scan()
        return

    # 往前多扫 1 小时，防止边界遗漏
    scan_from = last_ts - timedelta(hours=1)
    scan_to = datetime.now(timezone.utc)

    async with AsyncSessionLocal() as session:
        count = await scan_and_persist(scan_from, scan_to, session)

    if count > 0:
        logger.info("[AnomalyDetector] 增量扫描完成，新增 %d 条异常记录", count)


# ---------------------------------------------------------------------------
# 初始扫描入口（lifespan 启动时调用）
# ---------------------------------------------------------------------------

async def initial_scan() -> None:
    """
    应用启动时执行一次：
    - anomaly_events 为空 → 全量历史扫描
    - 已有数据 → 增量扫描（补齐启动期间的缺口）
    捕获所有异常，确保不影响应用正常启动。
    """
    try:
        await run_incremental_scan()
    except Exception as exc:
        logger.error(
            "[AnomalyDetector] 初始扫描失败（anomaly_events 表是否已创建？运行迁移 002_create_anomaly_events.sql）: %s",
            exc,
        )


# ---------------------------------------------------------------------------
# 定期增量扫描任务（后台 asyncio Task）
# ---------------------------------------------------------------------------

async def start_periodic_scan(interval_seconds: int = 3600) -> None:
    """每隔 interval_seconds 秒执行一次增量扫描（默认 1 小时）。"""
    while True:
        await asyncio.sleep(interval_seconds)
        try:
            await run_incremental_scan()
        except Exception as exc:
            logger.error("[AnomalyDetector] 定期扫描失败: %s", exc)
