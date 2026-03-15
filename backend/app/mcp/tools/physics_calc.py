"""
阶段二：原子能力库 —— 物理计算与异常检测工具（Tool 3 / 6）
==========================================================
工具清单：
  calculate_system_cop     → Tool 3  空调能效估算（基于温差与能耗）
  detect_energy_anomalies  → Tool 6  基于规则的异常检测

物理逻辑说明（COP 估算）：
  标准 COP = 制冷量 / 耗电量。本项目数据库中没有独立的"制冷量"列，
  但有供回水温差（△T = sim_return_temp_c - sim_supply_temp_c）和
  冷冻水能耗（chilledwater_kwh）。

  工程近似：以 △T / chilledwater_kwh 作为"冷却效率代理指标"（越高越好），
  再归一化到 COP 量纲（×scaling_factor）进行 ASHRAE 90.1 横向对比。
  物理异常捕获：△T ≤ 0（供水 ≥ 回水，制冷未启动）或 energy ≈ 0 时
  直接返回 MCPError，不做虚假计算。
"""
from __future__ import annotations

import statistics
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import EnergyData
from app.mcp.tools.data_query import get_building_info
from app.schemas.mcp_schemas import (
    AnomalyRecord,
    AnomalyRule,
    CalculateSystemCOPInput,
    CalculateSystemCOPOutput,
    DetectEnergyAnomaliesInput,
    DetectEnergyAnomaliesOutput,
    MCPError,
    OperationStatus,
)

# ---------------------------------------------------------------------------
# 物理常量
# ---------------------------------------------------------------------------
_ASHRAE_BASELINE = 3.0          # ASHRAE 90.1 COP 基准
_ZERO_ENERGY_THRESHOLD = 0.1    # kWh，低于此值视为"能耗接近零"
_SCALING_FACTOR = 15.0          # △T(°C) / kWh → COP 量纲近似系数（经验值）
_NIGHT_HOUR_START = 0           # 夜间开始小时（UTC）
_NIGHT_HOUR_END = 6             # 夜间结束小时（UTC）
_NIGHT_POWER_THRESHOLD = 50.0   # kWh，夜间超此值告警
_CHILLED_SPIKE_MULTIPLIER = 3.0 # chilledwater_kwh 超均值 3 倍判定为过耗
_SPIKE_MULTIPLIER = 3.0         # 传感器跳变：超过均值 3 倍判定为 spike


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
      1. 从 energy_data 查 hvac_energy_kwh / hvac_supply_temp_c / hvac_return_temp_c
      2. 物理异常捕获（除零 / 供回水温差异常）
      3. 逐行计算 COP proxy，汇总均/最小/最大值
      4. 与 ASHRAE 90.1 基准对比，输出 is_below_baseline
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
            EnergyData.chilledwater_kwh,
            EnergyData.sim_supply_temp_c,
            EnergyData.sim_return_temp_c,
        )
        .where(EnergyData.building_id == actual_bid)
        .where(EnergyData.timestamp >= inp.time_range.start)
        .where(EnergyData.timestamp <= inp.time_range.end)
        .where(EnergyData.chilledwater_kwh.isnot(None))
        .order_by(EnergyData.timestamp.asc())
    )
    rows = result.fetchall()

    if not rows:
        return MCPError(
            error=f"建筑 '{inp.building_id}' 在指定时段内无冷冻水能耗数据",
            error_code="NO_HVAC_DATA",
            tool_name="calculate_system_cop",
        )

    cop_values: list[float] = []
    for ts, energy, supply, ret in rows:
        # 物理异常捕获 1：能耗接近零
        if energy is None or energy < _ZERO_ENERGY_THRESHOLD:
            continue

        # 物理异常捕获 2：供水温度 ≥ 回水温度（制冷未启动）
        if supply is None or ret is None:
            continue
        delta_t = ret - supply  # 正值 = 冷冻水升温 = 制冷有效
        if delta_t <= 0:
            continue

        cop_proxy = (delta_t * _SCALING_FACTOR) / energy
        cop_values.append(cop_proxy)

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

    return CalculateSystemCOPOutput(
        building_id=inp.building_id,
        cop_mean=round(cop_mean, 3),
        cop_min=round(cop_min, 3),
        cop_max=round(cop_max, 3),
        ashrae_baseline=_ASHRAE_BASELINE,
        is_below_baseline=cop_mean < _ASHRAE_BASELINE,
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
    基于预定义物理规则检测异常，严禁让大模型自己做阈值判断。
    规则白名单：
      night_high_power        → 夜间（0-6 点）electricity_kwh > 50
      zero_occupancy_high_hvac → 人员密度=0 且 hvac_energy_kwh > 30
      sensor_spike            → 某列值超过该时段均值的 3 倍
    """
    meter_id, actual_bid = await get_building_info(session, inp.building_id)
    if actual_bid is None:
        return MCPError(
            error=f"未找到建筑类型 '{inp.building_id}'，请先调用 list_available_buildings 确认合法值",
            error_code="BUILDING_NOT_FOUND",
            tool_name="detect_energy_anomalies",
        )

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

    # 用于均值类规则的预计算
    elec_vals = [r.electricity_kwh for r in rows if r.electricity_kwh is not None]
    elec_mean = statistics.mean(elec_vals) if elec_vals else 0
    chilled_vals = [r.chilledwater_kwh for r in rows if r.chilledwater_kwh is not None]
    chilled_mean = statistics.mean(chilled_vals) if chilled_vals else 0

    anomalies: list[AnomalyRecord] = []

    for row in rows:
        ts: datetime = row.timestamp
        hour_utc = ts.hour if ts.tzinfo else ts.replace(tzinfo=timezone.utc).hour
        anomaly_status = OperationStatus.ANOMALY if row.anomaly_status == "Anomaly" else OperationStatus.NORMAL

        # ── 规则 1：夜间高功率 ─────────────────────────────────────────────
        if (
            AnomalyRule.NIGHT_HIGH_POWER in inp.rules
            and row.electricity_kwh is not None
            and _NIGHT_HOUR_START <= hour_utc < _NIGHT_HOUR_END
            and row.electricity_kwh > _NIGHT_POWER_THRESHOLD
        ):
            anomalies.append(AnomalyRecord(
                timestamp=ts,
                building_id=inp.building_id,
                meter_device_id=meter_id or "",
                rule_triggered=AnomalyRule.NIGHT_HIGH_POWER,
                actual_value=row.electricity_kwh,
                threshold_value=_NIGHT_POWER_THRESHOLD,
                anomaly_status=anomaly_status,
            ))

        # ── 规则 2：冷冻水高耗（超均值 3 倍）─────────────────────────────
        if (
            AnomalyRule.HIGH_CHILLED_WATER in inp.rules
            and row.chilledwater_kwh is not None
            and chilled_mean > 0
            and row.chilledwater_kwh > chilled_mean * _CHILLED_SPIKE_MULTIPLIER
        ):
            anomalies.append(AnomalyRecord(
                timestamp=ts,
                building_id=inp.building_id,
                meter_device_id=meter_id or "",
                rule_triggered=AnomalyRule.HIGH_CHILLED_WATER,
                actual_value=row.chilledwater_kwh,
                threshold_value=round(chilled_mean * _CHILLED_SPIKE_MULTIPLIER, 2),
                anomaly_status=anomaly_status,
            ))

        # ── 规则 3：传感器跳变（电力数值超均值 3 倍）─────────────────────
        if (
            AnomalyRule.SENSOR_SPIKE in inp.rules
            and row.electricity_kwh is not None
            and elec_mean > 0
            and row.electricity_kwh > elec_mean * _SPIKE_MULTIPLIER
        ):
            anomalies.append(AnomalyRecord(
                timestamp=ts,
                building_id=inp.building_id,
                meter_device_id=meter_id or "",
                rule_triggered=AnomalyRule.SENSOR_SPIKE,
                actual_value=row.electricity_kwh,
                threshold_value=round(elec_mean * _SPIKE_MULTIPLIER, 2),
                anomaly_status=anomaly_status,
            ))

    return DetectEnergyAnomaliesOutput(
        anomalies=anomalies,
        total_anomalies=len(anomalies),
        building_id=inp.building_id,
        period_start=inp.time_range.start,
        period_end=inp.time_range.end,
    )
