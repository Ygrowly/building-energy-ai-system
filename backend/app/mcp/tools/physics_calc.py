"""
阶段二：原子能力库 —— 物理计算与异常检测工具（Tool 3 / 6）
==========================================================
工具清单：
  calculate_system_cop     → Tool 3  空调能效估算（基于温差与能耗）
  detect_energy_anomalies  → Tool 6  基于 GB 双阈值物理规则的异常检测

detect_energy_anomalies 升级说明（v2）：
  - 旧版使用"批次均值 × 3"的统计方法，对夜间低负荷噪声敏感，误报率高。
  - 新版调用 gb_simulator.calculate_rated_values() 为每条记录计算国标期望值，
    采用"百分比超标 + 绝对值超限"双阈值，大幅降低垃圾告警。
  - 新增 HVAC 根因诊断（A/B/C 类），为 Diagnose Agent 提供直接可用的故障原因。

物理逻辑说明（COP 估算）：
  标准 COP = 制冷量 / 耗电量。本项目数据库中没有独立的"制冷量"列，
  但有供回水温差（△T = sim_return_temp_c - sim_supply_temp_c）和
  暖通空调综合能耗（hac_energy）。

  工程近似：以 △T / hac_energy 作为"冷却效率代理指标"（越高越好），
  再归一化到 COP 量纲（×scaling_factor）进行 GB 50189-2015 国标对比。
  物理异常捕获：△T ≤ 0（供水 ≥ 回水，制冷未启动）或 energy ≈ 0 时
  直接返回 MCPError，不做虚假计算。
"""
from __future__ import annotations

import statistics
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Building, EnergyData
from app.mcp.tools.data_query import get_building_info
from app.schemas.mcp_schemas import (
    AnomalyRecord,
    AnomalyRule,
    CalculateSystemCOPInput,
    CalculateSystemCOPOutput,
    DetectEnergyAnomaliesInput,
    DetectEnergyAnomaliesOutput,
    GetBuildingRatedValuesInput,
    GetBuildingRatedValuesOutput,
    MCPError,
    OperationStatus,
    RatedActualRecord,
)
from app.services.gb_simulator import calculate_rated_values

# ---------------------------------------------------------------------------
# 物理常量
# ---------------------------------------------------------------------------
_ZERO_ENERGY_THRESHOLD = 0.1    # kWh，低于此值视为"能耗接近零"
_SCALING_FACTOR = 15.0          # △T(°C) / kWh → COP 量纲近似系数（经验值）

# GB 50189-2015 COP 基准（与 gb_simulator 中的 COP 常量对应）
_GB_COP_COOLING = 3.5           # 制冷季系统综合 COP（含主机+水泵+冷却塔）
_GB_COP_HEATING = 2.5           # 供暖季系统综合 COP（热泵/锅炉综合系统）

# GB 双阈值检测阈值（与 anomaly_detector.py 保持一致）
_WATER_REL_THR = 0.20           # 水耗：相对偏差阈值
_WATER_ABS_THR = 1.0            # 水耗：绝对偏差（m³）
_ELEC_REL_THR = 0.15            # 电耗：相对偏差阈值
_ELEC_ABS_RATIO = 0.10          # 电耗：绝对偏差为期望的比例
_HAC_REL_THR = 0.20             # 空调：相对偏差阈值
_HAC_ABS_THR = 20.0             # 空调：绝对偏差（kWh）

# 异常偏差判断阈值（用于 get_building_rated_values 中的 anomaly_hours 统计）
_ANOMALY_REL_THR = 0.15         # 任意一项偏差超过 15% 即视为"该小时有异常"

_TIMEZONE_OFFSET_H = 8          # UTC+8


# ===========================================================================
# Tool 3：calculate_system_cop
# ===========================================================================

async def calculate_system_cop(
    inp: CalculateSystemCOPInput,
    session: AsyncSession,
) -> CalculateSystemCOPOutput | MCPError:
    """
    估算指定建筑指定时段的空调能效代理指标（COP proxy）。
    步骤：
      1. 查 hac_energy + 供回水温差 + 室外气温（用于推断 HVAC 工况）
      2. 物理异常捕获（除零 / 供回水温差异常）
      3. 逐行计算 COP proxy，汇总均/最小/最大值
      4. 国标基准对比：GB 50189-2015（制冷季 COP=3.5 / 供暖季 COP=2.5）
    """
    _meter_id, actual_bid = await get_building_info(session, inp.building_id)
    if actual_bid is None:
        return MCPError(
            error=f"未找到建筑类型 '{inp.building_id}'，请先调用 list_available_buildings 确认合法值",
            error_code="BUILDING_NOT_FOUND",
            tool_name="calculate_system_cop",
        )

    result = await session.execute(
        select(
            EnergyData.timestamp,
            EnergyData.hac_energy,
            EnergyData.sim_supply_temp_c,
            EnergyData.sim_return_temp_c,
            EnergyData.air_temp_c,
        )
        .where(EnergyData.building_id == actual_bid)
        .where(EnergyData.timestamp >= inp.time_range.start)
        .where(EnergyData.timestamp <= inp.time_range.end)
        .where(EnergyData.hac_energy.isnot(None))
        .order_by(EnergyData.timestamp.asc())
    )
    rows = result.fetchall()

    if not rows:
        return MCPError(
            error=f"建筑 '{inp.building_id}' 在指定时段内无暖通空调能耗数据",
            error_code="NO_HVAC_DATA",
            tool_name="calculate_system_cop",
        )

    cop_values: list[float] = []
    air_temps: list[float] = []

    for ts, energy, supply, ret, air_t in rows:
        if energy is None or energy < _ZERO_ENERGY_THRESHOLD:
            continue
        if supply is None or ret is None:
            continue
        delta_t = ret - supply  # 正值 = 冷冻水升温 = 制冷有效
        if delta_t <= 0:
            continue

        cop_proxy = (delta_t * _SCALING_FACTOR) / energy
        cop_values.append(cop_proxy)
        if air_t is not None:
            air_temps.append(air_t)

    if not cop_values:
        return MCPError(
            error=(
                f"建筑 '{inp.building_id}' 在指定时段内 HVAC 数据全部触发物理异常校验"
                f"（能耗接近零或供回水温差 ≤ 0），无法计算 COP，疑似传感器故障"
            ),
            error_code="SENSOR_FAULT_DIVIDE_BY_ZERO",
            tool_name="calculate_system_cop",
        )

    cop_mean = statistics.mean(cop_values)
    cop_min = min(cop_values)
    cop_max = max(cop_values)

    # 推断 HVAC 工况（用于选取 GB 国标基准）
    avg_air_temp = statistics.mean(air_temps) if air_temps else 20.0
    if avg_air_temp > 22.0:
        hvac_mode = "Cooling"
        gb_baseline = _GB_COP_COOLING
    elif avg_air_temp < 15.0:
        hvac_mode = "Heating"
        gb_baseline = _GB_COP_HEATING
    else:
        hvac_mode = "Mixed"
        gb_baseline = _GB_COP_COOLING  # 过渡季默认按制冷基准

    return CalculateSystemCOPOutput(
        building_id=inp.building_id,
        cop_mean=round(cop_mean, 3),
        cop_min=round(cop_min, 3),
        cop_max=round(cop_max, 3),
        hvac_mode=hvac_mode,
        gb_baseline=gb_baseline,
        is_below_gb=cop_mean < gb_baseline,
        period_start=inp.time_range.start,
        period_end=inp.time_range.end,
        data_points_used=len(cop_values),
    )


# ===========================================================================
# Tool 6：detect_energy_anomalies
# ===========================================================================

async def detect_energy_anomalies(
    inp: DetectEnergyAnomaliesInput,
    session: AsyncSession,
) -> DetectEnergyAnomaliesOutput | MCPError:
    """
    基于国标（GB）双阈值物理规则检测异常，严禁让大模型自己做阈值判断。

    规则白名单（GB 物理规则，v2）：
      water_leak           → 水耗偏差 > 20% 且 > 1.0 m³（管网漏水）
      electricity_overload → 总电耗偏差 > 15% 且 > 期望的 10%（异常高电耗）
      hvac_overconsumption → 空调偏差 > 20% 且 > 20 kWh（空调系统过耗）
      db_flagged           → energy_data.anomaly_status = 'Anomaly'（兜底）

    每条记录的期望值由 gb_simulator.calculate_rated_values() 实时计算，
    基于国标物理模型，取代旧版"批次均值"统计基线。
    """
    meter_id, actual_bid = await get_building_info(session, inp.building_id)
    if actual_bid is None:
        return MCPError(
            error=f"未找到建筑类型 '{inp.building_id}'，请先调用 list_available_buildings 确认合法值",
            error_code="BUILDING_NOT_FOUND",
            tool_name="detect_energy_anomalies",
        )

    # 同时查询 buildings 表获取 sqm 和 primary_space_usage
    bld_result = await session.execute(
        select(Building.sqm, Building.primary_space_usage)
        .where(Building.building_id == actual_bid)
    )
    bld_row = bld_result.fetchone()
    sqm = (bld_row[0] or 1000.0) if bld_row else 1000.0
    usage = (bld_row[1] or "Office") if bld_row else "Office"

    result = await session.execute(
        select(EnergyData)
        .where(EnergyData.building_id == actual_bid)
        .where(EnergyData.timestamp >= inp.time_range.start)
        .where(EnergyData.timestamp <= inp.time_range.end)
        .order_by(EnergyData.timestamp.asc())
    )
    rows: list[EnergyData] = list(result.scalars().all())

    if not rows:
        return MCPError(
            error=f"建筑 '{inp.building_id}' 在指定时段内无数据",
            error_code="NO_DATA_FOUND",
            tool_name="detect_energy_anomalies",
        )

    anomalies: list[AnomalyRecord] = []
    eps = 1e-6

    for row in rows:
        ts: datetime = row.timestamp
        ts_utc = ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)
        ts_local = ts_utc + timedelta(hours=_TIMEZONE_OFFSET_H)
        hour_local = ts_local.hour
        dow_local = ts_local.isoweekday()

        anomaly_status = (
            OperationStatus.ANOMALY if row.anomaly_status == "Anomaly"
            else OperationStatus.NORMAL
        )

        # 计算国标期望值
        try:
            rated = calculate_rated_values(
                sqm=sqm,
                primary_space_usage=usage,
                hour=hour_local,
                dayofweek=dow_local,
                air_temp=row.air_temp_c or 20.0,
                dew_temp=row.dew_temp_c or 10.0,
            )
        except Exception:
            continue

        # ── 规则 1：水耗异常 ──────────────────────────────────────────────
        if (
            AnomalyRule.WATER_LEAK in inp.rules
            and row.water_m3 is not None
            and rated.rated_water_m3 > eps
        ):
            delta_w = row.water_m3 - rated.rated_water_m3
            rel_w = delta_w / rated.rated_water_m3
            if rel_w > _WATER_REL_THR and delta_w > _WATER_ABS_THR:
                anomalies.append(AnomalyRecord(
                    timestamp=ts,
                    building_id=inp.building_id,
                    meter_device_id=meter_id or "",
                    rule_triggered=AnomalyRule.WATER_LEAK,
                    actual_value=row.water_m3,
                    threshold_value=round(rated.rated_water_m3 * (1 + _WATER_REL_THR), 4),
                    expected_value=rated.rated_water_m3,
                    deviation_pct=round(rel_w * 100, 2),
                    anomaly_status=anomaly_status,
                ))

        # ── 规则 2：总电耗异常 ────────────────────────────────────────────
        if (
            AnomalyRule.ELECTRICITY_OVERLOAD in inp.rules
            and row.electricity_kwh is not None
            and rated.rated_electricity_kwh > eps
        ):
            delta_e = row.electricity_kwh - rated.rated_electricity_kwh
            rel_e = delta_e / rated.rated_electricity_kwh
            abs_thr_e = rated.rated_electricity_kwh * _ELEC_ABS_RATIO
            if rel_e > _ELEC_REL_THR and delta_e > abs_thr_e:
                anomalies.append(AnomalyRecord(
                    timestamp=ts,
                    building_id=inp.building_id,
                    meter_device_id=meter_id or "",
                    rule_triggered=AnomalyRule.ELECTRICITY_OVERLOAD,
                    actual_value=row.electricity_kwh,
                    threshold_value=round(rated.rated_electricity_kwh * (1 + _ELEC_REL_THR), 2),
                    expected_value=rated.rated_electricity_kwh,
                    deviation_pct=round(rel_e * 100, 2),
                    anomaly_status=anomaly_status,
                ))

        # ── 规则 3：空调能耗异常（含第二层根因诊断）─────────────────────
        if (
            AnomalyRule.HVAC_OVERCONSUMPTION in inp.rules
            and row.hac_energy is not None
            and rated.rated_hac_energy > eps
        ):
            delta_h = row.hac_energy - rated.rated_hac_energy
            rel_h = delta_h / rated.rated_hac_energy
            if rel_h > _HAC_REL_THR and delta_h > _HAC_ABS_THR:
                # 根因诊断
                root_cause = _diagnose_hvac(row, rated)
                anomalies.append(AnomalyRecord(
                    timestamp=ts,
                    building_id=inp.building_id,
                    meter_device_id=meter_id or "",
                    rule_triggered=AnomalyRule.HVAC_OVERCONSUMPTION,
                    actual_value=row.hac_energy,
                    threshold_value=round(rated.rated_hac_energy * (1 + _HAC_REL_THR), 2),
                    expected_value=rated.rated_hac_energy,
                    deviation_pct=round(rel_h * 100, 2),
                    hvac_root_cause=root_cause,
                    anomaly_status=anomaly_status,
                ))

        # ── 规则 4：db_flagged 兜底 ────────────────────────────────────
        if (
            AnomalyRule.DB_FLAGGED in inp.rules
            and row.anomaly_status == "Anomaly"
        ):
            anomalies.append(AnomalyRecord(
                timestamp=ts,
                building_id=inp.building_id,
                meter_device_id=meter_id or "",
                rule_triggered=AnomalyRule.DB_FLAGGED,
                actual_value=0.0,
                threshold_value=0.0,
                anomaly_status=OperationStatus.ANOMALY,
            ))

    return DetectEnergyAnomaliesOutput(
        anomalies=anomalies,
        total_anomalies=len(anomalies),
        building_id=inp.building_id,
        period_start=inp.time_range.start,
        period_end=inp.time_range.end,
    )


def _diagnose_hvac(row: EnergyData, rated) -> str:
    """MCP 工具层 HVAC 根因诊断（与 anomaly_detector 保持逻辑一致）。"""
    supply = row.sim_supply_temp_c
    ret = row.sim_return_temp_c
    expected_supply = rated.expected_supply_temp

    if supply is not None and expected_supply is not None:
        if abs(supply - expected_supply) > 1.5:
            return "A_low_efficiency"

    if supply is not None and ret is not None:
        if (ret - supply) < 3.0:
            return "B_small_deltaT"

    if (
        rated.schedule_factor <= 0.05
        and row.hac_energy is not None
        and row.hac_energy > rated.rated_hac_energy + 30.0
    ):
        return "C_unexpected_on"

    return "other_hvac"


# ===========================================================================
# Tool 3b：get_building_rated_values（新增）
# ===========================================================================

async def get_building_rated_values(
    inp: GetBuildingRatedValuesInput,
    session: AsyncSession,
) -> GetBuildingRatedValuesOutput | MCPError:
    """
    查询指定建筑在时间段内每小时的国标（GB）期望值，并与数据库中的实际值并排返回。

    用途：
      1. 诊断智能体（Diagnose Agent）调用此工具，获取"应该是多少"的物理基线，
         向用户解释"为什么说这个数值是异常的"。
      2. 前端可直接用 records 渲染"实际 vs 期望"对比折线图，无需额外聚合。
      3. anomaly_hours 字段给出异常时段统计，帮助 Agent 快速定位高峰告警窗口。

    物理模型：gb_simulator.calculate_rated_values()，基于 5 项 GB 国家标准。
    """
    _meter_id, actual_bid = await get_building_info(session, inp.building_id)
    if actual_bid is None:
        return MCPError(
            error=f"未找到建筑类型 '{inp.building_id}'，请先调用 list_available_buildings 确认合法值",
            error_code="BUILDING_NOT_FOUND",
            tool_name="get_building_rated_values",
        )

    # 取建筑元数据
    bld_result = await session.execute(
        select(Building.sqm, Building.primary_space_usage)
        .where(Building.building_id == actual_bid)
    )
    bld_row = bld_result.fetchone()
    sqm = (bld_row[0] or 1000.0) if bld_row else 1000.0
    usage = (bld_row[1] or "Office") if bld_row else "Office"

    # 取时段内所有实际数据
    result = await session.execute(
        select(EnergyData)
        .where(EnergyData.building_id == actual_bid)
        .where(EnergyData.timestamp >= inp.time_range.start)
        .where(EnergyData.timestamp <= inp.time_range.end)
        .order_by(EnergyData.timestamp.asc())
    )
    rows: list[EnergyData] = list(result.scalars().all())

    if not rows:
        return MCPError(
            error=f"建筑 '{inp.building_id}' 在指定时段内无数据",
            error_code="NO_DATA_FOUND",
            tool_name="get_building_rated_values",
        )

    records: list[RatedActualRecord] = []
    anomaly_hours = 0
    eps = 1e-6

    for row in rows:
        ts: datetime = row.timestamp
        ts_utc = ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)
        ts_local = ts_utc + timedelta(hours=_TIMEZONE_OFFSET_H)

        try:
            rated = calculate_rated_values(
                sqm=sqm,
                primary_space_usage=usage,
                hour=ts_local.hour,
                dayofweek=ts_local.isoweekday(),
                air_temp=row.air_temp_c or 20.0,
                dew_temp=row.dew_temp_c or 10.0,
            )
        except Exception:
            continue

        # 计算各项偏差百分比
        def _dev_pct(actual: float | None, rated_val: float) -> float | None:
            if actual is None or rated_val < eps:
                return None
            return round((actual - rated_val) / rated_val * 100, 2)

        w_dev = _dev_pct(row.water_m3, rated.rated_water_m3)
        e_dev = _dev_pct(row.electricity_kwh, rated.rated_electricity_kwh)
        h_dev = _dev_pct(row.hac_energy, rated.rated_hac_energy)

        # 判断该小时是否存在异常偏差（任意一项超过 15%）
        devs = [d for d in (w_dev, e_dev, h_dev) if d is not None]
        if any(abs(d) > _ANOMALY_REL_THR * 100 for d in devs):
            anomaly_hours += 1

        records.append(RatedActualRecord(
            timestamp=ts,
            hvac_mode=rated.hvac_mode,
            schedule_factor=rated.schedule_factor,
            rated_water_m3=rated.rated_water_m3,
            rated_electricity_kwh=rated.rated_electricity_kwh,
            rated_hac_energy=rated.rated_hac_energy,
            expected_supply_temp=rated.expected_supply_temp,
            expected_return_temp=rated.expected_return_temp,
            actual_water_m3=row.water_m3,
            actual_electricity_kwh=row.electricity_kwh,
            actual_hac_energy=row.hac_energy,
            actual_supply_temp=row.sim_supply_temp_c,
            actual_return_temp=row.sim_return_temp_c,
            water_deviation_pct=w_dev if "water" in inp.metrics else None,
            electricity_deviation_pct=e_dev if "electricity" in inp.metrics else None,
            hac_deviation_pct=h_dev if "hac_energy" in inp.metrics else None,
        ))

    return GetBuildingRatedValuesOutput(
        building_id=inp.building_id,
        primary_space_usage=usage,
        sqm=sqm,
        records=records,
        total_hours=len(records),
        anomaly_hours=anomaly_hours,
        period_start=inp.time_range.start,
        period_end=inp.time_range.end,
    )
