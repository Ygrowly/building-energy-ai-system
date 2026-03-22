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
from datetime import datetime, timezone

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
_ELEC_ABS_THR = 5.0             # 电耗：固定绝对偏差最小值（kWh），防止夜间低负荷误报
_HAC_REL_THR = 0.20             # 空调：相对偏差阈值
_HAC_ABS_THR = 20.0             # 空调：绝对偏差（kWh）

# 异常偏差判断阈值（用于 get_building_rated_values 中的 anomaly_hours 统计）
_ANOMALY_REL_THR = 0.15         # 任意一项偏差超过 15% 即视为"该小时有异常"


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
    return MCPError(
        error="异常监测模块已下线，等待重新开发。",
        error_code="ANOMALY_MODULE_DISABLED",
        tool_name="detect_energy_anomalies",
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
    return MCPError(
        error="额定期望值模块已下线，等待重新开发。",
        error_code="RATED_VALUE_MODULE_DISABLED",
        tool_name="get_building_rated_values",
    )
