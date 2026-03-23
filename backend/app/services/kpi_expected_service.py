"""
额定期望值计算服务（kpi_expected_service）
==========================================
直接移植 simulate_kpis_from_cleaned(1).ipynb 中的无噪声 nominal 计算逻辑。

关键约定：
  - energy_data.water_m3 列实际存储的是 **升 (L)**（与 notebook water_l 一致）。
  - 输出的 water_m3_expected 同样是 **升 (L)**。
  - HVAC 工况判定（制冷/供暖/过渡）需要对每栋楼按时间序逐行走滞回状态机；
    因此本服务以"楼栋"为最小批处理单位，不支持单行独立计算。
  - UNIFY_CLIMATE_AND_PLANT_ACROSS_TYPES = True（与 notebook 一致）：
    所有建筑使用 office 的围护/设备参数，仅保留各自的 P_base/q_person/W_peak/S(h)。
"""
from __future__ import annotations

import json
import logging
import os
import time
from datetime import timezone
from typing import Any

# #region agent log
_DBG_LOG_PATH = os.path.join(os.path.dirname(__file__), "..", "..", "..", "debug-e8ce47.log")
def _dbg(hypothesis: str, location: str, message: str, data: dict):
    try:
        entry = json.dumps({"sessionId": "e8ce47", "runId": "rebuild", "hypothesisId": hypothesis, "location": location, "message": message, "data": data, "timestamp": int(time.time()*1000)}, default=str)
        with open(_DBG_LOG_PATH, "a", encoding="utf-8") as f:
            f.write(entry + "\n")
    except Exception:
        pass
# #endregion

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Building, EnergyData, KpiExpectedHourly

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 建筑类型映射
# ---------------------------------------------------------------------------
_BUILDING_ID_TO_TYPE: dict[str, str] = {
    "Fox_public_Henry": "library",
}
_PRIMARYSPACEUSAGE_TO_TYPE: dict[str, str] = {
    "office": "office",
    "education": "teaching",
    "public services": "library",
    "public service": "library",
    "public_services": "library",
}
_DEFAULT_TYPE = "teaching"


def _classify_usage(building_id: str, primary_space_usage: str | None) -> str:
    if building_id in _BUILDING_ID_TO_TYPE:
        return _BUILDING_ID_TO_TYPE[building_id]
    psu = (primary_space_usage or "").strip().lower()
    if psu in _PRIMARYSPACEUSAGE_TO_TYPE:
        return _PRIMARYSPACEUSAGE_TO_TYPE[psu]
    bid_l = building_id.lower()
    if "office" in bid_l or "admin" in bid_l:
        return "office"
    if "teach" in bid_l or "edu" in bid_l or "class" in bid_l:
        return "teaching"
    if "library" in bid_l:
        return "library"
    return _DEFAULT_TYPE


# ---------------------------------------------------------------------------
# 统一参数（UNIFY_CLIMATE_AND_PLANT_ACROSS_TYPES = True）
# 围护/设备全部用 office 参数；仅 P_base / q_person / W_peak 按类型区分
# ---------------------------------------------------------------------------

# 统一 HVAC / 围护参数（office 基准）
_U_ENV = 5.0          # W/(m²·K)
_WATER_BASE = 0.004   # L/(m²·h)
_WATER_WEATHER = 0.002  # L/(m²·h)/℃  (Ta > 26 部分)

_COP_COOLING = 3.6
_COP_HEATING = 2.7

_PUMP_RUN_WM2 = 1.00      # W/m²
_PUMP_STANDBY_WM2 = 0.15  # W/m²
_VENT_ACTIVE_WM2 = 2.2    # W/m²
_VENT_MIN_WM2 = 0.6       # W/m²

_COOL_ON_TA = 24.0
_COOL_OFF_TA = 22.0
_COOL_ON_Q = 22.0
_COOL_OFF_Q = 14.0
_HEAT_ON_TA = 14.0
_HEAT_OFF_TA = 16.0
_HEAT_ON_QENV = -18.0

_FORCE_ON_LOW_TA = 8.0
_FORCE_ON_HIGH_TA = 30.0
_MIN_ON_LOAD_KW = 0.05

# 供回水温度基准
_COOLING_SUPPLY_T = 7.0
_COOLING_DELTA_T = 5.0    # 额定温差 ΔT (回水 - 供水)
_HEATING_SUPPLY_T = 60.0
_HEATING_DELTA_T = 10.0   # 额定温差 (供水 - 回水)

# 每类建筑独有的内部参数
_TYPE_PARAMS: dict[str, dict[str, float]] = {
    "office":   {"P_base": 22.0, "q_person": 12.0, "W_peak": 0.36},
    "teaching": {"P_base": 24.0, "q_person": 13.0, "W_peak": 0.48},
    "library":  {"P_base": 20.0, "q_person": 11.0, "W_peak": 0.30},
}


# ---------------------------------------------------------------------------
# 日程系数 S(h, is_weekday)
# ---------------------------------------------------------------------------
def _s_office(h: int, is_weekday: bool) -> float:
    if not is_weekday:
        return 0.08
    if h <= 6:
        return 0.08
    if h == 7:
        return 0.20
    if h == 8:
        return 0.60
    if 9 <= h <= 17:
        return 1.00
    if 18 <= h <= 20:
        return 0.35
    return 0.10


def _s_teaching(h: int, is_weekday: bool) -> float:
    if not is_weekday:
        return 0.15
    if h <= 6:
        return 0.08
    if h == 7:
        return 0.20
    if 8 <= h <= 12:
        return 1.00
    if h == 13:
        return 0.45
    if 14 <= h <= 17:
        return 1.00
    if 18 <= h <= 21:
        return 0.75
    return 0.10


def _s_library(h: int, _is_weekday: bool) -> float:
    if h <= 6:
        return 0.10
    if h == 7:
        return 0.20
    if 8 <= h <= 21:
        return 0.85
    return 0.15


_S_FUNCS = {
    "office": _s_office,
    "teaching": _s_teaching,
    "library": _s_library,
}


def _schedule_factor(usage: str, hour: int, dayofweek: int) -> float:
    """dayofweek: 1=Monday … 7=Sunday (ISO).

    The notebook's source CSV uses pandas dayofweek encoding (Mon=0 … Sun=6)
    and applies ``clip(1,7)`` then ``weekday = dow <= 5``.  Under that
    mapping Saturday (raw=5, clipped=5) is treated as a weekday; only
    Sunday (raw=6, clipped=6) counts as a weekend day.  We replicate that
    here: ISO dayofweek 7 (Sunday) → weekend, everything else → weekday.
    """
    is_weekday = dayofweek != 7  # only Sunday is weekend
    s = _S_FUNCS[usage](hour, is_weekday)
    return min(max(s, 0.08), 1.0)


# ---------------------------------------------------------------------------
# 单行额定值计算（需要外部传入已确定的 hvac_mode）
# ---------------------------------------------------------------------------
def _compute_nominal_row(
    *,
    usage: str,
    sqm: float,
    ta: float,
    td: float,
    rh_base: float,
    hour: int,
    dayofweek: int,
    is_cooling: bool,
    is_heating: bool,
) -> dict[str, Any]:
    """
    计算单行的 nominal（无噪声）期望值。
    is_cooling / is_heating 由外部滞回状态机决定后传入。
    """
    tp = _TYPE_PARAMS[usage]
    p_base = tp["P_base"]
    q_person = tp["q_person"]
    w_peak = tp["W_peak"]

    s = _schedule_factor(usage, hour, dayofweek)

    # ── 用水 (L) ──
    water_active = sqm * w_peak * s
    water_base = sqm * _WATER_BASE
    water_weather = max(ta - 26.0, 0.0) * sqm * _WATER_WEATHER
    water_l_nominal = max(0.0, water_active + water_base + water_weather)

    # ── 热/冷负荷 ──
    t_in = 20.0 if ta < 18.0 else 26.0
    q_env = _U_ENV * (ta - t_in)
    q_internal = (p_base * s) + (q_person * s)
    q_latent = max(0.0, 15.0 * (td - 15.0)) * s
    q_total = q_env + q_internal + q_latent

    q_load = 0.0
    if is_cooling:
        q_load = sqm * max(0.0, q_env + q_internal + q_latent) / 1000.0
    elif is_heating:
        q_load = sqm * max(0.0, abs(q_env) - q_internal) / 1000.0

    # ── HVAC on/off ──
    extreme = ta < _FORCE_ON_LOW_TA or ta >= _FORCE_ON_HIGH_TA
    hvac_on = q_load > _MIN_ON_LOAD_KW and (s > 0.08 or extreme)
    # #region agent log
    if (is_cooling or is_heating) and not hvac_on and q_load > 0.5:
        _dbg("H4", "kpi_expected_service.py:_compute_nominal_row:hvac_on_rejected", "hvac-on-false-despite-load", {
            "ta": ta, "s": s, "q_load": round(q_load, 4), "extreme": extreme,
            "s_gt_008": s > 0.08, "ta_gt_force_high": ta > _FORCE_ON_HIGH_TA, "ta_lt_force_low": ta < _FORCE_ON_LOW_TA,
            "is_cooling": is_cooling, "is_heating": is_heating,
            "force_high": _FORCE_ON_HIGH_TA, "force_low": _FORCE_ON_LOW_TA,
        })
    # #endregion
    if not hvac_on:
        q_load = 0.0

    q_design = max(sqm * 100.0 / 1000.0, 1e-6)
    plr = min(max(q_load / q_design, 0.0), 1.0)

    # ── 空调能耗 ──
    e_pump_run = sqm * _PUMP_RUN_WM2 / 1000.0
    e_pump_standby = sqm * _PUMP_STANDBY_WM2 / 1000.0
    e_vent = sqm * _VENT_ACTIVE_WM2 / 1000.0 if s > 0.12 else sqm * _VENT_MIN_WM2 / 1000.0

    if hvac_on and is_cooling:
        hac_nominal = q_load / _COP_COOLING + e_pump_run + 0.5 * e_vent
    elif hvac_on and is_heating:
        hac_nominal = q_load / _COP_HEATING + e_pump_run + 0.4 * e_vent
    else:
        hac_nominal = e_pump_standby + e_vent

    # ── 用电 (kWh) ──
    e_base = sqm * p_base * s / 1000.0
    electricity_nominal = max(0.0, e_base + hac_nominal)

    # ── 供回水温度 ──
    if hvac_on and is_cooling:
        supply_t = _COOLING_SUPPLY_T
        return_t = _COOLING_SUPPLY_T + _COOLING_DELTA_T * plr
    elif hvac_on and is_heating:
        supply_t = _HEATING_SUPPLY_T
        return_t = _HEATING_SUPPLY_T - _HEATING_DELTA_T * plr
    else:
        supply_t = ta
        return_t = ta

    # ── 湿度 (%RH) ──
    humidity = float(rh_base)
    if hvac_on and is_cooling:
        humidity -= (7.0 + 11.0 * plr) * max(s, 0.12)
    elif hvac_on and is_heating:
        humidity -= (3.0 + 5.0 * plr) * max(s, 0.12)
    else:
        humidity = 0.9 * humidity + 0.1 * rh_base
    humidity = min(max(humidity, 20.0), 95.0)

    hvac_mode = "Cooling" if (is_cooling and hvac_on) else ("Heating" if (is_heating and hvac_on) else "Ventilation")

    return {
        "water_m3_expected": round(water_l_nominal, 4),
        "electricity_kwh_expected": round(max(0.0, electricity_nominal), 4),
        "hac_energy_expected": round(max(0.0, hac_nominal), 4),
        "sim_supply_temp_c_expected": round(supply_t, 4),
        "sim_return_temp_c_expected": round(return_t, 4),
        "humidity_rh_pct_expected": round(humidity, 4),
        "schedule_factor": round(s, 4),
        "hvac_mode": hvac_mode,
    }


# ---------------------------------------------------------------------------
# 滞回状态机：判定 (is_cooling, is_heating) 序列
# ---------------------------------------------------------------------------
def _run_hvac_state_machine(
    rows: list[tuple[float, float, float]],
    building_id: str = "",
    ts_list: list | None = None,
) -> list[tuple[bool, bool]]:
    """
    rows: list of (ta, q_total, q_env) sorted by timestamp ascending.
    Returns list of (is_cooling, is_heating) same length.
    """
    results: list[tuple[bool, bool]] = []
    mode = 0  # 0=transition, 1=cooling, -1=heating
    # #region agent log
    _transition_log_count = 0
    # #endregion

    for idx, (ta, q_total, q_env) in enumerate(rows):
        prev_mode = mode
        # 离开当前工况
        if mode == 1 and ta <= _COOL_OFF_TA and q_total <= _COOL_OFF_Q:
            mode = 0
        elif mode == -1 and ta >= _HEAT_OFF_TA:
            mode = 0

        # 进入新工况
        if mode == 0:
            heat_demand = ta <= _HEAT_ON_TA or (q_env <= _HEAT_ON_QENV and ta < _HEAT_OFF_TA + 1.0)
            cool_demand = ta >= _COOL_ON_TA or q_total >= _COOL_ON_Q
            if heat_demand:
                mode = -1
            elif cool_demand:
                mode = 1

        # #region agent log
        if prev_mode != mode and _transition_log_count < 30:
            _transition_log_count += 1
            ts_str = str(ts_list[idx]) if ts_list and idx < len(ts_list) else str(idx)
            _dbg("H1", f"kpi_expected_service.py:state_machine:{building_id}", "state-transition", {
                "idx": idx, "ts": ts_str, "ta": ta, "q_total": round(q_total, 4), "q_env": round(q_env, 4),
                "prev_mode": prev_mode, "new_mode": mode,
                "cool_off_check": f"ta={ta}<=cool_off_ta={_COOL_OFF_TA}={ta<=_COOL_OFF_TA}, q_total={q_total:.2f}<=cool_off_q={_COOL_OFF_Q}={q_total<=_COOL_OFF_Q}",
            })
        # #endregion

        results.append((mode == 1, mode == -1))

    return results


# ---------------------------------------------------------------------------
# 主批处理函数
# ---------------------------------------------------------------------------
async def compute_expected_for_building(
    building_id: str,
    db: AsyncSession,
) -> list[dict[str, Any]]:
    """
    对一栋楼的所有 energy_data 行计算无噪声额定期望值，
    返回可直接 upsert 到 kpi_expected_hourly 的字典列表。
    """
    bld_result = await db.execute(
        select(Building.sqm, Building.primary_space_usage)
        .where(Building.building_id == building_id)
    )
    bld_row = bld_result.fetchone()
    if not bld_row:
        logger.warning("compute_expected_for_building: 未找到建筑 %s", building_id)
        return []

    sqm = float(bld_row[0] or 1000.0)
    usage = _classify_usage(building_id, bld_row[1])

    # 取该楼所有能耗记录，按时间戳排序
    rows_result = await db.execute(
        select(
            EnergyData.timestamp,
            EnergyData.air_temp_c,
            EnergyData.dew_temp_c,
            EnergyData.humidity_rh_pct,
        )
        .where(EnergyData.building_id == building_id)
        .order_by(EnergyData.timestamp.asc())
    )
    energy_rows = rows_result.fetchall()

    if not energy_rows:
        logger.info("compute_expected_for_building: 楼 %s 无 energy_data 行", building_id)
        return []

    # 预算 q_total / q_env（用于状态机），无需保留噪声字段
    ta_values = [float(r[1] or 20.0) for r in energy_rows]
    td_values = [float(r[2] or 10.0) for r in energy_rows]
    rh_values = [float(r[3] or 50.0) for r in energy_rows]

    # Extract timestamps to compute actual S per row for the state machine
    ts_list = [r[0] for r in energy_rows]

    state_machine_input: list[tuple[float, float, float]] = []
    for ts_row, ta, td in zip(ts_list, ta_values, td_values):
        if hasattr(ts_row, "tzinfo") and ts_row.tzinfo is None:
            ts_row = ts_row.replace(tzinfo=timezone.utc)
        s = _schedule_factor(usage, ts_row.hour, ts_row.isoweekday())

        t_in = 20.0 if ta < 18.0 else 26.0
        q_env = _U_ENV * (ta - t_in)
        tp = _TYPE_PARAMS[usage]
        q_internal = (tp["P_base"] * s) + (tp["q_person"] * s)
        q_latent = max(0.0, 15.0 * (td - 15.0)) * s
        q_total = q_env + q_internal + q_latent
        state_machine_input.append((ta, q_total, q_env))

    hvac_states = _run_hvac_state_machine(state_machine_input, building_id=building_id, ts_list=ts_list)

    # 计算每行额定值
    output_rows: list[dict[str, Any]] = []
    for (ts_row, ta, td, rh), (is_cool, is_heat) in zip(energy_rows, hvac_states):
        # ensure timezone-aware
        ts = ts_row
        if hasattr(ts, "tzinfo") and ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)

        nominal = _compute_nominal_row(
            usage=usage,
            sqm=sqm,
            ta=ta or 20.0,
            td=td or 10.0,
            rh_base=rh or 50.0,
            hour=ts.hour,
            dayofweek=ts.isoweekday(),
            is_cooling=is_cool,
            is_heating=is_heat,
        )
        # #region agent log
        _target_ts = {"2016-04-23 17:00:00", "2016-10-08 06:00:00", "2016-01-02 07:00:00", "2016-07-15 14:00:00"}
        ts_str = str(ts).replace("+00:00", "").replace(" ", " ")[:19]
        if ts_str in _target_ts or (nominal.get("hac_energy_expected", 0) < 3.0 and (is_cool or is_heat)):
            _dbg("H1_H4", f"kpi_expected_service.py:compute_row:{building_id}", "row-detail", {
                "ts": ts_str, "ta": ta, "td": td, "rh": rh, "hour": ts.hour, "dow": ts.isoweekday(),
                "is_cool": is_cool, "is_heat": is_heat, "sqm": sqm, "usage": usage,
                "s": nominal.get("schedule_factor"), "hvac_mode": nominal.get("hvac_mode"),
                "hac_expected": nominal.get("hac_energy_expected"),
                "elec_expected": nominal.get("electricity_kwh_expected"),
                "water_expected": nominal.get("water_m3_expected"),
                "supply_expected": nominal.get("sim_supply_temp_c_expected"),
                "return_expected": nominal.get("sim_return_temp_c_expected"),
            })
        # #endregion
        output_rows.append({
            "timestamp": ts,
            "building_id": building_id,
            "building_usage": bld_row[1] or usage,
            "source_version": "notebook_v1",
            **nominal,
        })

    logger.info(
        "compute_expected_for_building: 楼 %s (%s, %.0f m²) 计算了 %d 行",
        building_id, usage, sqm, len(output_rows),
    )
    return output_rows


async def upsert_expected_hourly(
    rows: list[dict[str, Any]],
    db: AsyncSession,
) -> int:
    """
    批量 upsert 到 kpi_expected_hourly，按 (building_id, timestamp) 幂等。
    返回写入行数。
    """
    if not rows:
        return 0

    await db.execute(
        text("""
            INSERT INTO kpi_expected_hourly
              (timestamp, building_id, building_usage, schedule_factor, hvac_mode,
               source_version, water_m3_expected, electricity_kwh_expected,
               hac_energy_expected, sim_supply_temp_c_expected,
               sim_return_temp_c_expected, humidity_rh_pct_expected)
            VALUES
              (:timestamp, :building_id, :building_usage, :schedule_factor, :hvac_mode,
               :source_version, :water_m3_expected, :electricity_kwh_expected,
               :hac_energy_expected, :sim_supply_temp_c_expected,
               :sim_return_temp_c_expected, :humidity_rh_pct_expected)
            ON CONFLICT (timestamp, building_id)
            DO UPDATE SET
              building_usage           = EXCLUDED.building_usage,
              schedule_factor          = EXCLUDED.schedule_factor,
              hvac_mode                = EXCLUDED.hvac_mode,
              source_version           = EXCLUDED.source_version,
              water_m3_expected        = EXCLUDED.water_m3_expected,
              electricity_kwh_expected = EXCLUDED.electricity_kwh_expected,
              hac_energy_expected      = EXCLUDED.hac_energy_expected,
              sim_supply_temp_c_expected  = EXCLUDED.sim_supply_temp_c_expected,
              sim_return_temp_c_expected  = EXCLUDED.sim_return_temp_c_expected,
              humidity_rh_pct_expected    = EXCLUDED.humidity_rh_pct_expected
        """),
        rows,
    )
    await db.commit()
    return len(rows)


async def compute_and_store_all_buildings(db: AsyncSession) -> dict[str, int]:
    """
    对数据库中所有建筑批量计算并存储 kpi_expected_hourly。
    每栋楼使用独立 session 以避免长事务连接超时。
    返回 {building_id: rows_written}。
    """
    from app.db.session import AsyncSessionLocal

    bld_result = await db.execute(
        select(Building.building_id).order_by(Building.building_id)
    )
    building_ids = [r[0] for r in bld_result.fetchall()]

    summary: dict[str, int] = {}
    for bid in building_ids:
        async with AsyncSessionLocal() as session:
            rows = await compute_expected_for_building(bid, session)
            n = await upsert_expected_hourly(rows, session)
            summary[bid] = n
            logger.info("expected upsert: %s → %d rows", bid, n)

    return summary
