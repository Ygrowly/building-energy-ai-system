"""
异常检测后台服务（升级版 v2）— 双阈值 GB 物理规则 + 分层 HVAC 根因诊断
============================================================================

架构：双层检测
  第一层（并行发现层）：同时对三个子系统运行双阈值判定
    - water_leak           水耗：偏差 > 20% 且 绝对偏差 > 1.0 m³
    - electricity_overload 总电耗：偏差 > 15% 且 绝对偏差 > 期望的 10%
    - hvac_overconsumption 空调：偏差 > 20% 且 绝对偏差 > 20 kWh

  第二层（根因诊断层，仅对 hvac_overconsumption 触发）：
    - A_low_efficiency     主机效能衰退：供水温度偏离国标期望 > 1.5℃
    - B_small_deltaT       水力失调（大流量小温差）：供回水温差 < 3℃
    - C_unexpected_on      非预期开机：负荷率系数 ≤ 0.05 但空调仍大量运行

核心改进（相比旧版）：
  - 用 gb_simulator 计算每条记录的物理期望值，取代"批次均值 × 3"的统计法
  - 采用"百分比 + 绝对值"双满足条件，消除夜间低值下的垃圾告警
  - HVAC 根因写入 hvac_root_cause 字段，前端/工单可直接渲染诊断原因
  - 平行检测水耗/电耗/空调，避免单一通路下的告警掩蔽效应
  - INSERT SQL 新增 expected_value / deviation_pct / hvac_root_cause 三列

数据库对齐：
  - anomaly_events 表须已执行 010_upgrade_anomaly_events.sql
  - meter_device_id 优先取 devices 表中 ElectricityMeter 类型设备 ID
"""
from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AnomalyEvent, Building, Device, EnergyData
from app.db.session import AsyncSessionLocal
from app.services.gb_simulator import RatedValues, calculate_rated_values

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 调度常量
# ---------------------------------------------------------------------------
_SCAN_BATCH_HOURS = 24      # 每批扫描的时间窗口（小时）

# ---------------------------------------------------------------------------
# 第一层：双阈值检测阈值
# ---------------------------------------------------------------------------

# 水耗：相对偏差阈值 + 绝对偏差最小值
_WATER_REL_THRESHOLD = 0.20    # 20%
_WATER_ABS_THRESHOLD = 1.0     # 1.0 m³（过滤管网微小波动）

# 总电耗：相对偏差阈值 + 固定绝对偏差最小值（防止夜间低负荷时微小差异误报）
_ELEC_REL_THRESHOLD = 0.15     # 15%
_ELEC_ABS_THRESHOLD = 5.0      # 5 kWh（绝对差值不足 5 kWh 不触发，过滤夜间待机底噪）

# 空调能耗：相对偏差阈值 + 绝对偏差最小值
_HAC_REL_THRESHOLD = 0.20      # 20%
_HAC_ABS_THRESHOLD = 20.0      # 20 kWh（过滤夜间停机时的设备底噪）

# ---------------------------------------------------------------------------
# 第二层：HVAC 根因诊断阈值
# ---------------------------------------------------------------------------

# 诊断 A：供水温度偏离期望超过此值，判定主机效能衰退
_HAC_SUPPLY_TEMP_DEVIATION = 1.5   # ℃

# 诊断 B：供回水实际温差小于此值，判定水力失调/大流量小温差
_HAC_MIN_DELTA_T = 3.0              # ℃

# 诊断 C：当设计负荷率系数低于此值时，空调不应运行
_SCHEDULE_OFF_THRESHOLD = 0.05

# 诊断 C 额外条件：空调实际能耗超出期望此值，才认为是"明显的异常运行"
_HAC_UNEXPECTED_ABS_EXCESS = 30.0  # kWh

# ---------------------------------------------------------------------------
# 兜底规则（保留向后兼容）
# ---------------------------------------------------------------------------
_BUILDING_NAMES: dict[str, str] = {
    "Education": "教学楼",
    "Office": "办公楼",
    "Public": "图书馆",
    "Public services": "图书馆",
}


# ---------------------------------------------------------------------------
# 辅助函数：预加载电表设备 ID
# ---------------------------------------------------------------------------

async def _load_meter_device_ids(session: AsyncSession) -> dict[str, str]:
    """
    一次性从 devices 表加载所有楼宇的主计量表设备 ID（ElectricityMeter 优先）。
    返回 {building_id: meter_device_id}；若无则退化为 building_id（向后兼容）。
    """
    result = await session.execute(
        select(Device.building_id, Device.device_id)
        .where(Device.device_type == "ElectricityMeter")
        .order_by(Device.building_id)
    )
    return {row[0]: row[1] for row in result.fetchall()}


# ---------------------------------------------------------------------------
# 核心：HVAC 根因诊断（第二层）
# ---------------------------------------------------------------------------

def _diagnose_hvac_root_cause(
    ed: EnergyData,
    rated: RatedValues,
) -> str:
    """
    对已确认 hvac_overconsumption 的记录进行根因分类。
    按优先级依次检查三种场景，返回诊断码。

    诊断逻辑：
      A（主机效能低）优先级最高：供水温度无法达到国标设定点。
      B（水力失调）次之：系统在运行，但供回水温差异常小，说明大量无效循环。
      C（非预期开机）最后：设计上本应关闭（负荷率≤0.05），但实际空调仍大量耗电。
    """
    supply = ed.sim_supply_temp_c
    ret = ed.sim_return_temp_c
    hac = ed.hac_energy
    rated_hac = rated.rated_hac_energy
    expected_supply = rated.expected_supply_temp

    # 诊断 A：供水温度偏离国标期望值
    if supply is not None and expected_supply is not None:
        if abs(supply - expected_supply) > _HAC_SUPPLY_TEMP_DEVIATION:
            return "A_low_efficiency"

    # 诊断 B：供回水实际温差过小（大流量小温差，水力失调）
    if supply is not None and ret is not None:
        actual_delta_t = ret - supply
        if actual_delta_t < _HAC_MIN_DELTA_T:
            return "B_small_deltaT"

    # 诊断 C：设计负荷率低（本应停机），但实际空调仍在大量运行
    if (
        rated.schedule_factor <= _SCHEDULE_OFF_THRESHOLD
        and hac is not None
        and rated_hac is not None
        and hac > rated_hac + _HAC_UNEXPECTED_ABS_EXCESS
    ):
        return "C_unexpected_on"

    return "other_hvac"


# ---------------------------------------------------------------------------
# 核心：单批次扫描并持久化
# ---------------------------------------------------------------------------

async def scan_and_persist(
    batch_start: datetime,
    batch_end: datetime,
    session: AsyncSession,
) -> int:
    """
    扫描 [batch_start, batch_end) 时间段内所有建筑的能耗数据，
    运行双阈值 GB 物理规则检测，将新增异常写入 anomaly_events（幂等 UPSERT）。

    每条记录的国标期望值由 gb_simulator.calculate_rated_values() 实时计算，
    不依赖批次均值，消除夜间低值下的统计噪声告警。

    Returns
    -------
    int
        本次新写入的记录数。
    """
    meter_id_map = await _load_meter_device_ids(session)

    result = await session.execute(
        select(EnergyData, Building.primary_space_usage, Building.sqm)
        .join(Building, EnergyData.building_id == Building.building_id)
        .where(EnergyData.timestamp >= batch_start)
        .where(EnergyData.timestamp < batch_end)
        .order_by(EnergyData.building_id, EnergyData.timestamp.asc())
    )
    rows = result.fetchall()

    if not rows:
        return 0

    now = datetime.now(timezone.utc)
    to_insert: list[dict] = []

    for ed, usage, sqm in rows:
        ts: datetime = ed.timestamp

        # energy_data.timestamp 存储的即为使用时刻（本地时间），直接读取
        hour_local = ts.hour
        dow_local = ts.isoweekday()  # 1=周一, 7=周日

        display = _BUILDING_NAMES.get(usage or "", usage or ed.building_id)
        meter_id = meter_id_map.get(ed.building_id, ed.building_id)

        # ── 计算国标期望值（核心改进：替代旧版"批次均值"基线）────────────
        try:
            rated = calculate_rated_values(
                sqm=sqm or 1000.0,
                primary_space_usage=usage or "Office",
                hour=hour_local,
                dayofweek=dow_local,
                air_temp=ed.air_temp_c or 20.0,
                dew_temp=ed.dew_temp_c or 10.0,
            )
        except Exception as exc:
            logger.warning(
                "[AnomalyDetector] 期望值计算失败 %s @ %s: %s",
                ed.building_id, ts, exc,
            )
            continue

        eps = 1e-6  # 避免除零

        # ══ 第一层：并行双阈值检测 ═══════════════════════════════════════

        # ── 规则 1：水耗异常（管网漏水 / 异常大量用水）──────────────────
        if ed.water_m3 is not None and rated.rated_water_m3 > eps:
            delta_w = ed.water_m3 - rated.rated_water_m3
            rel_w = delta_w / rated.rated_water_m3
            if rel_w > _WATER_REL_THRESHOLD and delta_w > _WATER_ABS_THRESHOLD:
                dev_pct = round(rel_w * 100, 2)
                to_insert.append(_make_record(
                    ts, ed, meter_id, now,
                    rule="water_leak",
                    actual=ed.water_m3,
                    expected=rated.rated_water_m3,
                    threshold=rated.rated_water_m3 * (1 + _WATER_REL_THRESHOLD),
                    deviation_pct=dev_pct,
                    hvac_root_cause=None,
                    msg=(
                        f"{display} 水耗异常：实际 {ed.water_m3:.3f} m³"
                        f"，期望 {rated.rated_water_m3:.3f} m³"
                        f"（偏差 +{dev_pct:.1f}%）"
                    ),
                ))

        # ── 规则 2：总电耗异常（异常高电耗 / 大型设备失控）──────────────
        if ed.electricity_kwh is not None and rated.rated_electricity_kwh > eps:
            delta_e = ed.electricity_kwh - rated.rated_electricity_kwh
            rel_e = delta_e / rated.rated_electricity_kwh
            if rel_e > _ELEC_REL_THRESHOLD and delta_e > _ELEC_ABS_THRESHOLD:
                dev_pct = round(rel_e * 100, 2)
                to_insert.append(_make_record(
                    ts, ed, meter_id, now,
                    rule="electricity_overload",
                    actual=ed.electricity_kwh,
                    expected=rated.rated_electricity_kwh,
                    threshold=rated.rated_electricity_kwh * (1 + _ELEC_REL_THRESHOLD),
                    deviation_pct=dev_pct,
                    hvac_root_cause=None,
                    msg=(
                        f"{display} 总电耗异常：实际 {ed.electricity_kwh:.1f} kWh"
                        f"，期望 {rated.rated_electricity_kwh:.1f} kWh"
                        f"（偏差 +{dev_pct:.1f}%）"
                    ),
                ))

        # ── 规则 3：空调能耗异常 → 触发第二层根因诊断 ────────────────────
        if ed.hac_energy is not None and rated.rated_hac_energy > eps:
            delta_h = ed.hac_energy - rated.rated_hac_energy
            rel_h = delta_h / rated.rated_hac_energy
            if rel_h > _HAC_REL_THRESHOLD and delta_h > _HAC_ABS_THRESHOLD:
                dev_pct = round(rel_h * 100, 2)

                # ── 第二层：HVAC 根因诊断 ─────────────────────────────
                root_cause = _diagnose_hvac_root_cause(ed, rated)

                # 根因诊断码 → 人类可读消息
                _cause_msg = {
                    "A_low_efficiency": "主机效能衰退（供水温度偏离设定点）",
                    "B_small_deltaT": "水力失调（大流量小温差，疑似旁通阀故障）",
                    "C_unexpected_on": "非预期开机（排程失效，设备应关闭）",
                    "other_hvac": "空调能耗异常（原因待进一步排查）",
                }.get(root_cause, "")

                to_insert.append(_make_record(
                    ts, ed, meter_id, now,
                    rule="hvac_overconsumption",
                    actual=ed.hac_energy,
                    expected=rated.rated_hac_energy,
                    threshold=rated.rated_hac_energy * (1 + _HAC_REL_THRESHOLD),
                    deviation_pct=dev_pct,
                    hvac_root_cause=root_cause,
                    msg=(
                        f"{display} 空调能耗过高：实际 {ed.hac_energy:.1f} kWh"
                        f"，期望 {rated.rated_hac_energy:.1f} kWh"
                        f"（偏差 +{dev_pct:.1f}%）— {_cause_msg}"
                    ),
                ))


    if not to_insert:
        return 0

    # 批量幂等写入（ON CONFLICT 保证扫描的幂等性）
    try:
        await session.execute(
            text("""
                INSERT INTO anomaly_events
                    (id, detected_at, data_timestamp, building_id,
                     meter_device_id, rule_triggered,
                     actual_value, threshold_value,
                     expected_value, deviation_pct, hvac_root_cause,
                     message, is_resolved)
                VALUES
                    (:id, :detected_at, :data_timestamp, :building_id,
                     :meter_device_id, :rule_triggered,
                     :actual_value, :threshold_value,
                     :expected_value, :deviation_pct, :hvac_root_cause,
                     :message, false)
                ON CONFLICT (data_timestamp, building_id, rule_triggered) DO NOTHING
            """),
            to_insert,
        )
        await session.commit()
    except Exception as exc:
        logger.error("[AnomalyDetector] 批量写入失败，回滚本批次: %s", exc)
        await session.rollback()
        return 0

    logger.debug("[AnomalyDetector] 批次 %s→%s 写入 %d 条", batch_start, batch_end, len(to_insert))
    return len(to_insert)


def _make_record(
    ts: datetime,
    ed: EnergyData,
    meter_id: str,
    now: datetime,
    *,
    rule: str,
    actual: float | None,
    expected: float | None,
    threshold: float | None,
    deviation_pct: float | None,
    hvac_root_cause: str | None,
    msg: str,
) -> dict:
    """构造单条 anomaly_events 插入字典。"""
    return {
        "id": str(uuid.uuid4()),
        "detected_at": now,
        "data_timestamp": ts,
        "building_id": ed.building_id,
        "meter_device_id": meter_id,
        "rule_triggered": rule,
        "actual_value": actual,
        "threshold_value": threshold,
        "expected_value": expected,
        "deviation_pct": deviation_pct,
        "hvac_root_cause": hvac_root_cause,
        "message": msg,
    }


# ---------------------------------------------------------------------------
# 全量历史扫描（首次运行 / anomaly_events 为空时）
# ---------------------------------------------------------------------------

async def run_full_historical_scan() -> None:
    """扫描 energy_data 表中的所有历史数据，按 24h 分批写入 anomaly_events。"""
    logger.info("[AnomalyDetector] 开始全量历史扫描（GB 双阈值规则）...")
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
            "[AnomalyDetector] 初始扫描失败"
            "（检查 anomaly_events 表是否已执行 010_upgrade_anomaly_events.sql）: %s",
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
