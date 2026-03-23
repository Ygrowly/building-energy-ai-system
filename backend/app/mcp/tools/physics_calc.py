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

# 检测规则到 kpi_anomaly_flags 列名的映射
_RULE_TO_FLAG_COL = {
    AnomalyRule.WATER_LEAK:           "flag_water",
    AnomalyRule.ELECTRICITY_OVERLOAD: "flag_electricity",
    AnomalyRule.HVAC_OVERCONSUMPTION: "flag_hvac_energy",
}

# kpi_anomaly_flags 中的实际值列（对应 energy_data）
_FLAG_TO_ACTUAL_COL = {
    "flag_water":      ("water_m3",        "water_m3_expected"),
    "flag_electricity": ("electricity_kwh", "electricity_kwh_expected"),
    "flag_hvac_energy": ("hac_energy",      "hac_energy_expected"),
}


async def detect_energy_anomalies(
    inp: DetectEnergyAnomaliesInput,
    session: AsyncSession,
) -> DetectEnergyAnomaliesOutput | MCPError:
    """
    从预计算的 kpi_anomaly_flags 表读取异常记录，格式化为 DetectEnergyAnomaliesOutput。
    如果 kpi_anomaly_flags 没有数据，返回 MCPError 提示先调用 /api/admin/rebuild-all。
    """
    from sqlalchemy import text as sqla_text

    _meter_id, actual_bid = await get_building_info(session, inp.building_id)
    if actual_bid is None:
        return MCPError(
            error=f"未找到建筑类型 '{inp.building_id}'，请先调用 list_available_buildings 确认合法值",
            error_code="BUILDING_NOT_FOUND",
            tool_name="detect_energy_anomalies",
        )

    # 检查 kpi_anomaly_flags 是否有数据
    check_result = await session.execute(
        sqla_text("SELECT COUNT(*) FROM kpi_anomaly_flags WHERE building_id = :bid"),
        {"bid": actual_bid},
    )
    if (check_result.scalar() or 0) == 0:
        return MCPError(
            error=(
                f"建筑 '{inp.building_id}' 的 kpi_anomaly_flags 表尚无数据。"
                "请先调用 POST /api/admin/rebuild-all 触发期望值计算和异常检测。"
            ),
            error_code="ANOMALY_FLAGS_EMPTY",
            tool_name="detect_energy_anomalies",
        )

    # 决定哪些 flag 列要查
    requested_rules = {r for r in inp.rules if r in _RULE_TO_FLAG_COL}
    if not requested_rules:
        return MCPError(
            error="当前支持的规则为 water_leak / electricity_overload / hvac_overconsumption",
            error_code="UNSUPPORTED_RULES",
            tool_name="detect_energy_anomalies",
        )

    # 构建 WHERE 条件（只返回至少一项请求规则触发的行）
    flag_conditions = " OR ".join(
        f"f.{_RULE_TO_FLAG_COL[r]}" for r in requested_rules
    )

    rows_result = await session.execute(sqla_text(f"""
        SELECT
            f.timestamp,
            f.flag_water,
            f.flag_electricity,
            f.flag_hvac_energy,
            f.hvac_diagnosis,
            e.water_m3,
            e.electricity_kwh,
            e.hac_energy,
            x.water_m3_expected,
            x.electricity_kwh_expected,
            x.hac_energy_expected
        FROM kpi_anomaly_flags f
        JOIN energy_data e ON e.building_id = f.building_id AND e.timestamp = f.timestamp
        LEFT JOIN kpi_expected_hourly x ON x.building_id = f.building_id AND x.timestamp = f.timestamp
        WHERE f.building_id = :bid
          AND f.timestamp >= :t0
          AND f.timestamp <= :t1
          AND ({flag_conditions})
        ORDER BY f.timestamp ASC
        LIMIT 500
    """), {"bid": actual_bid, "t0": inp.time_range.start, "t1": inp.time_range.end})
    rows = rows_result.fetchall()

    if not rows:
        return DetectEnergyAnomaliesOutput(
            anomalies=[],
            total_anomalies=0,
            building_id=inp.building_id,
            period_start=inp.time_range.start,
            period_end=inp.time_range.end,
        )

    anomaly_records: list[AnomalyRecord] = []
    for row in rows:
        (ts, fw, fe, fh, hvac_diag,
         water, elec, hac,
         water_e, elec_e, hac_e) = row

        if hasattr(ts, "tzinfo") and ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)

        flag_map = {
            AnomalyRule.WATER_LEAK:           (fw, water,  water_e,  1000.0 * 1.20),
            AnomalyRule.ELECTRICITY_OVERLOAD: (fe, elec,   elec_e,   (elec_e or 0) * 1.15 if elec_e else None),
            AnomalyRule.HVAC_OVERCONSUMPTION: (fh, hac,    hac_e,    (hac_e or 0) * 1.20 if hac_e else None),
        }
        for rule, (triggered, actual_v, expected_v, threshold_v) in flag_map.items():
            if rule not in requested_rules or not triggered:
                continue
            if actual_v is None:
                continue

            dev_pct: float | None = None
            if expected_v is not None and abs(expected_v) > 1e-9:
                dev_pct = round((actual_v - expected_v) / abs(expected_v) * 100, 2)

            anomaly_records.append(AnomalyRecord(
                timestamp=ts,
                building_id=inp.building_id,
                meter_device_id=_meter_id or actual_bid,
                rule_triggered=rule,
                actual_value=round(float(actual_v), 4),
                threshold_value=round(float(threshold_v), 4) if threshold_v is not None else 0.0,
                expected_value=round(float(expected_v), 4) if expected_v is not None else None,
                deviation_pct=dev_pct,
                hvac_root_cause=hvac_diag if rule == AnomalyRule.HVAC_OVERCONSUMPTION else None,
                anomaly_status=OperationStatus.ANOMALY,
            ))

    return DetectEnergyAnomaliesOutput(
        anomalies=anomaly_records,
        total_anomalies=len(anomaly_records),
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
    从 energy_data JOIN kpi_expected_hourly 读取实际值和期望值，
    格式化为 GetBuildingRatedValuesOutput。
    """
    from sqlalchemy import text as sqla_text

    _meter_id, actual_bid = await get_building_info(session, inp.building_id)
    if actual_bid is None:
        return MCPError(
            error=f"未找到建筑类型 '{inp.building_id}'，请先调用 list_available_buildings 确认合法值",
            error_code="BUILDING_NOT_FOUND",
            tool_name="get_building_rated_values",
        )

    # 检查 kpi_expected_hourly 是否有数据
    check_result = await session.execute(
        sqla_text("SELECT COUNT(*) FROM kpi_expected_hourly WHERE building_id = :bid"),
        {"bid": actual_bid},
    )
    if (check_result.scalar() or 0) == 0:
        return MCPError(
            error=(
                f"建筑 '{inp.building_id}' 的 kpi_expected_hourly 表尚无数据。"
                "请先调用 POST /api/admin/rebuild-all 触发期望值计算。"
            ),
            error_code="EXPECTED_HOURLY_EMPTY",
            tool_name="get_building_rated_values",
        )

    bld_result = await session.execute(
        select(Building.sqm, Building.primary_space_usage)
        .where(Building.building_id == actual_bid)
    )
    bld_row = bld_result.fetchone()
    sqm = float(bld_row[0] or 0) if bld_row else 0.0
    primary_usage = (bld_row[1] or inp.building_id) if bld_row else inp.building_id

    rows_result = await session.execute(sqla_text("""
        SELECT
            e.timestamp,
            e.water_m3,
            e.electricity_kwh,
            e.hac_energy,
            e.sim_supply_temp_c,
            e.sim_return_temp_c,
            x.water_m3_expected,
            x.electricity_kwh_expected,
            x.hac_energy_expected,
            x.sim_supply_temp_c_expected,
            x.sim_return_temp_c_expected,
            x.hvac_mode,
            x.schedule_factor
        FROM energy_data e
        JOIN kpi_expected_hourly x
            ON x.building_id = e.building_id AND x.timestamp = e.timestamp
        WHERE e.building_id = :bid
          AND e.timestamp >= :t0
          AND e.timestamp <= :t1
        ORDER BY e.timestamp ASC
        LIMIT 500
    """), {"bid": actual_bid, "t0": inp.time_range.start, "t1": inp.time_range.end})
    rows = rows_result.fetchall()

    if not rows:
        return MCPError(
            error=f"建筑 '{inp.building_id}' 在指定时段内 energy_data JOIN kpi_expected_hourly 无结果",
            error_code="NO_DATA_IN_RANGE",
            tool_name="get_building_rated_values",
        )

    records: list[RatedActualRecord] = []
    anomaly_hours = 0
    _EPS = 1e-9

    for row in rows:
        (ts, water, elec, hac, supply, ret,
         water_e, elec_e, hac_e, supply_e, return_e,
         hvac_mode, sched_f) = row

        if hasattr(ts, "tzinfo") and ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)

        def _dev(actual, expected):
            if actual is None or expected is None or abs(expected) < _EPS:
                return None
            return round((actual - expected) / abs(expected) * 100, 2)

        w_dev = _dev(water, water_e)
        e_dev = _dev(elec, elec_e)
        h_dev = _dev(hac, hac_e)

        is_anomaly = any(
            v is not None and abs(v) > 15.0
            for v in (w_dev, e_dev, h_dev)
        )
        if is_anomaly:
            anomaly_hours += 1

        records.append(RatedActualRecord(
            timestamp=ts,
            hvac_mode=hvac_mode or "Unknown",
            schedule_factor=round(float(sched_f), 4) if sched_f is not None else 0.5,
            rated_water_m3=round(float(water_e), 4) if water_e is not None else 0.0,
            rated_electricity_kwh=round(float(elec_e), 4) if elec_e is not None else 0.0,
            rated_hac_energy=round(float(hac_e), 4) if hac_e is not None else 0.0,
            expected_supply_temp=round(float(supply_e), 4) if supply_e is not None else 0.0,
            expected_return_temp=round(float(return_e), 4) if return_e is not None else 0.0,
            actual_water_m3=round(float(water), 4) if water is not None else None,
            actual_electricity_kwh=round(float(elec), 4) if elec is not None else None,
            actual_hac_energy=round(float(hac), 4) if hac is not None else None,
            actual_supply_temp=round(float(supply), 4) if supply is not None else None,
            actual_return_temp=round(float(ret), 4) if ret is not None else None,
            water_deviation_pct=w_dev,
            electricity_deviation_pct=e_dev,
            hac_deviation_pct=h_dev,
        ))

    return GetBuildingRatedValuesOutput(
        building_id=inp.building_id,
        primary_space_usage=primary_usage,
        sqm=sqm,
        records=records,
        total_hours=len(records),
        anomaly_hours=anomaly_hours,
        period_start=inp.time_range.start,
        period_end=inp.time_range.end,
    )
