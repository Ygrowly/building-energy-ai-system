"""
KPI 基线仿真器（notebook 主链路版）
====================================
从 simulate_kpis_from_cleaned(1).ipynb 提炼的物理仿真逻辑，
在楼宇级别按小时计算"额定/期望"KPI（不含随机噪声），
输出结构可直接写入 kpi_expected_hourly 表。

与旧版 gb_simulator.py 的区别：
  - 参数按三类建筑（office/teaching/library）+ 季节分层，不再只有 Office/Education/Public 三个常量集。
  - 供回水温度、空调能耗、用水量的计算路径完全与 notebook 对齐。
  - 单位：用水量以 m3 为主，内部中间态用 L，入库前统一换算。
  - 纯函数，无 I/O，可在异步上下文中安全调用。
"""
from __future__ import annotations

import copy
from dataclasses import dataclass
from typing import Literal

import numpy as np

# ---------------------------------------------------------------------------
# 建筑类型规范化
# ---------------------------------------------------------------------------
BuildingUsage = Literal["office", "teaching", "library"]

# primaryspaceusage → 内部 usage
_USAGE_MAP: dict[str, BuildingUsage] = {
    "office": "office",
    "Office": "office",
    "教学": "teaching",
    "education": "teaching",
    "Education": "teaching",
    "teaching": "teaching",
    "library": "library",
    "Library": "library",
    "public": "library",
    "Public": "library",
    "public services": "library",
    "Public services": "library",
    "Public Services": "library",
}

# building_id 中的字符串线索
_BUILDING_ID_KEYWORDS: list[tuple[list[str], BuildingUsage]] = [
    (["Fox_public", "library", "图书", "阅览"], "library"),
    (["Fox_education", "Fox_teach", "教学", "classroom", "teach", "edu"], "teaching"),
    (["Fox_office", "office", "admin", "办公"], "office"),
]


def normalize_building_usage(
    building_id: str,
    primary_space_usage: str | None = None,
    building_type_hint: str | None = None,
) -> BuildingUsage:
    """
    将多种来源的建筑类型信息规范化为 office/teaching/library。

    优先级：building_id 明确前缀 > building_type_hint > primary_space_usage
    """
    # 1. building_id 字符串线索
    bid_l = (building_id or "").lower()
    for keywords, usage in _BUILDING_ID_KEYWORDS:
        if any(k.lower() in bid_l for k in keywords):
            return usage

    # 2. 明确的 building_type_hint（来自 buildings 表的 primary_space_usage）
    hint = (building_type_hint or "").strip()
    if hint in _USAGE_MAP:
        return _USAGE_MAP[hint]

    # 3. primaryspaceusage 列
    psu = (primary_space_usage or "").strip()
    if psu in _USAGE_MAP:
        return _USAGE_MAP[psu]

    # 默认教学楼（与 notebook DEFAULT_BUILDING_TYPE 一致）
    return "teaching"


# ---------------------------------------------------------------------------
# 国标参数模板（与 notebook GB_PARAM_TEMPLATE 对齐）
# ---------------------------------------------------------------------------
_GB_PARAMS: dict[BuildingUsage, dict] = {
    "office": {
        "internal": {
            "W_peak": 0.36,          # L/(m²·h) 峰值用水定额
            "P_base": 22.0,          # W/m² 照明+插座功率密度
            "q_person": 12.0,        # W/m² 人员散热
            "U_envelope": 5.0,       # W/(m²·K) 围护简化传热系数
            "water_base_wm2": 0.004, # L/(m²·h) 基线用水
            "water_weather_wm2_per_deg": 0.002,  # L/(m²·h)/℃ 高温补水
        },
        "hvac": {
            "cop": {"cooling": 3.6, "heating": 2.7},
            "pump_wm2": {"run": 1.00, "standby": 0.15},
            "vent_wm2": {"active": 2.2, "minimum": 0.6},
            "hysteresis": {
                "cool_on_ta": 24.0, "cool_off_ta": 22.0,
                "cool_on_q": 22.0,  "cool_off_q": 14.0,
                "heat_on_ta": 14.0, "heat_off_ta": 16.0,
                "heat_on_qenv": -18.0,
            },
            "extreme_force_on": {"low_ta": 8.0, "high_ta": 30.0},
            "min_on_load_kw": 0.05,
        },
    },
    "teaching": {
        "internal": {
            "W_peak": 0.48,
            "P_base": 24.0,
            "q_person": 13.0,
            "U_envelope": 5.3,
            "water_base_wm2": 0.008,
            "water_weather_wm2_per_deg": 0.0022,
        },
        "hvac": {
            "cop": {"cooling": 3.4, "heating": 2.6},
            "pump_wm2": {"run": 1.05, "standby": 0.16},
            "vent_wm2": {"active": 2.6, "minimum": 0.7},
            "hysteresis": {
                "cool_on_ta": 24.0, "cool_off_ta": 22.0,
                "cool_on_q": 24.0,  "cool_off_q": 15.0,
                "heat_on_ta": 14.0, "heat_off_ta": 16.0,
                "heat_on_qenv": -20.0,
            },
            "extreme_force_on": {"low_ta": 7.0, "high_ta": 31.0},
            "min_on_load_kw": 0.05,
        },
    },
    "library": {
        "internal": {
            "W_peak": 0.30,
            "P_base": 20.0,
            "q_person": 11.0,
            "U_envelope": 4.6,
            "water_base_wm2": 0.0028,
            "water_weather_wm2_per_deg": 0.0015,
        },
        "hvac": {
            "cop": {"cooling": 3.8, "heating": 2.9},
            "pump_wm2": {"run": 0.85, "standby": 0.12},
            "vent_wm2": {"active": 1.8, "minimum": 0.5},
            "hysteresis": {
                "cool_on_ta": 24.5, "cool_off_ta": 22.5,
                "cool_on_q": 20.0,  "cool_off_q": 13.0,
                "heat_on_ta": 13.5, "heat_off_ta": 16.0,
                "heat_on_qenv": -16.0,
            },
            "extreme_force_on": {"low_ta": 7.0, "high_ta": 31.0},
            "min_on_load_kw": 0.04,
        },
    },
}

# 同一校园统一围护与冷热源参数（与 notebook UNIFY_CLIMATE_AND_PLANT_ACROSS_TYPES=True 对齐）
# 三类建筑共享 office 的 U_envelope/water_base/hvac 参数，只保留日程 S 和内热差异。
_UNIFY_CLIMATE_AND_PLANT = True

if _UNIFY_CLIMATE_AND_PLANT:
    _ref = _GB_PARAMS["office"]
    _ref_hvac = copy.deepcopy(_ref["hvac"])
    _ref_u = _ref["internal"]["U_envelope"]
    _ref_wb = _ref["internal"]["water_base_wm2"]
    _ref_ww = _ref["internal"]["water_weather_wm2_per_deg"]
    for _u in _GB_PARAMS:
        _GB_PARAMS[_u]["internal"]["U_envelope"] = _ref_u
        _GB_PARAMS[_u]["internal"]["water_base_wm2"] = _ref_wb
        _GB_PARAMS[_u]["internal"]["water_weather_wm2_per_deg"] = _ref_ww
        _GB_PARAMS[_u]["hvac"] = copy.deepcopy(_ref_hvac)

# ---------------------------------------------------------------------------
# 时间系数 S(hour, is_weekday) — 与 notebook 完全对齐
# ---------------------------------------------------------------------------

def _schedule_factor(usage: BuildingUsage, hour: int, is_weekday: bool) -> float:
    """返回 S ∈ [0.08, 1.0]，代表当前小时建筑活动水平。"""
    h = int(hour)
    if usage == "office":
        if not is_weekday:
            return 0.08
        if h <= 6:
            return 0.08
        if h == 7:
            return 0.2
        if h == 8:
            return 0.6
        if 9 <= h <= 17:
            return 1.0
        if 18 <= h <= 20:
            return 0.35
        return 0.10

    if usage == "teaching":
        if not is_weekday:
            return 0.15
        if h <= 6:
            return 0.08
        if h == 7:
            return 0.2
        if 8 <= h <= 12:
            return 1.0
        if h == 13:
            return 0.45
        if 14 <= h <= 17:
            return 1.0
        if 18 <= h <= 21:
            return 0.75
        return 0.10

    # library
    if h <= 6:
        return 0.10
    if h == 7:
        return 0.2
    if 8 <= h <= 21:
        return 0.85
    return 0.15


# ---------------------------------------------------------------------------
# 季节判断
# ---------------------------------------------------------------------------
Season = Literal["cooling", "heating", "transition"]


def classify_season(month: int | None, air_temp: float) -> Season:
    """根据月份和室外温度判断当前季节。"""
    if month is not None:
        if month in (6, 7, 8, 9):
            return "cooling"
        if month in (11, 12, 1, 2, 3):
            return "heating"
        return "transition"
    # 无月份信息时用温度粗判
    if air_temp >= 26.0:
        return "cooling"
    if air_temp <= 8.0:
        return "heating"
    return "transition"


# ---------------------------------------------------------------------------
# 输出 dataclass
# ---------------------------------------------------------------------------

@dataclass
class HourlyExpected:
    """单个楼宇、单个小时的额定期望值（无随机噪声）。"""
    building_id: str
    timestamp_utc: str       # ISO 8601 字符串（UTC）
    building_usage: str      # office / teaching / library

    # 核心 KPI 期望值
    water_m3_expected: float            # 期望用水量（m³/h）
    electricity_kwh_expected: float     # 期望总电耗（kWh/h）
    hac_energy_expected: float          # 期望空调能耗（kWh/h）
    sim_supply_temp_c_expected: float   # 期望供水温度（℃）
    sim_return_temp_c_expected: float   # 期望回水温度（℃）
    humidity_rh_pct_expected: float     # 期望湿度（%）

    # 元数据
    schedule_factor: float   # 时间系数 S
    hvac_mode: str           # "cooling" / "heating" / "transition"
    season: str
    source_version: str = "notebook_v1"


# ---------------------------------------------------------------------------
# 核心计算函数
# ---------------------------------------------------------------------------

def calculate_hourly_expected(
    building_id: str,
    sqm: float,
    primary_space_usage: str,
    timestamp_utc: str,
    hour: int,
    dayofweek: int,         # 1=周一 … 7=周日（isoweekday）
    air_temp: float,
    dew_temp: float,
    humidity_rh: float = 50.0,
    month: int | None = None,
    source_version: str = "notebook_v1",
) -> HourlyExpected:
    """
    计算单条记录的额定期望值（确定性，无噪声）。

    Parameters
    ----------
    building_id : str
    sqm : float
        建筑面积（m²），≤0 时退化为 1000。
    primary_space_usage : str
        建筑主用途（来自 buildings 表）。
    timestamp_utc : str
        ISO 8601 时间戳字符串（用于写入 kpi_expected_hourly）。
    hour : int
        本地小时（0-23）。
    dayofweek : int
        1=周一，7=周日（Python isoweekday）。
    air_temp : float
        室外气温（℃）。
    dew_temp : float
        室外露点温度（℃）。
    humidity_rh : float
        室外相对湿度（%），用于室内湿度基准。
    month : int | None
        月份（1-12），用于季节判断；None 时由气温粗判。
    """
    if not sqm or sqm <= 0:
        sqm = 1000.0

    usage = normalize_building_usage(building_id, primary_space_usage)
    p = _GB_PARAMS[usage]
    ip = p["internal"]
    hp = p["hvac"]

    is_weekday = dayofweek <= 5
    S = float(np.clip(_schedule_factor(usage, hour, is_weekday), 0.08, 1.0))
    season = classify_season(month, air_temp)

    # ── 用水（L → m³）──────────────────────────────────────────────────────
    water_active = sqm * ip["W_peak"] * S
    water_base = sqm * ip["water_base_wm2"]
    water_weather = max(air_temp - 26.0, 0.0) * sqm * ip["water_weather_wm2_per_deg"]
    water_l = max(0.0, water_active + water_base + water_weather)
    water_m3 = water_l / 1000.0

    # ── 负荷计算 ────────────────────────────────────────────────────────────
    U = ip["U_envelope"]
    T_in = 20.0 if air_temp < 18.0 else 26.0
    q_env = U * (air_temp - T_in)
    q_internal = ip["P_base"] * S + ip["q_person"] * S
    q_latent = max(0.0, 15.0 * (dew_temp - 15.0)) * S
    q_total = q_env + q_internal + q_latent

    hy = hp["hysteresis"]

    # 工况判定（简化静态版，不做逐楼滞回迭代，适合单点计算）
    cool_demand = (air_temp >= hy["cool_on_ta"]) or (q_total >= hy["cool_on_q"])
    heat_demand = (air_temp <= hy["heat_on_ta"]) or (
        q_env <= hy["heat_on_qenv"] and air_temp < hy["heat_off_ta"] + 1.0
    )

    if cool_demand and not heat_demand:
        hvac_mode = "cooling"
    elif heat_demand and not cool_demand:
        hvac_mode = "heating"
    else:
        hvac_mode = "transition"

    Q_design = sqm * 100.0 / 1000.0  # kW（100 W/m² 设计指标）

    # 空调负荷 kW
    if hvac_mode == "cooling":
        Q_load = sqm * max(0.0, q_env + q_internal + q_latent) / 1000.0
    elif hvac_mode == "heating":
        Q_load = sqm * max(0.0, abs(q_env) - q_internal) / 1000.0
    else:
        Q_load = 0.0

    # 开机判定
    hvac_on = (Q_load > hp["min_on_load_kw"]) or (
        air_temp < hp["extreme_force_on"]["low_ta"]
    ) or (air_temp > hp["extreme_force_on"]["high_ta"])
    hvac_on = hvac_on and S > 0.08
    if not hvac_on:
        Q_load = 0.0

    PLR = float(np.clip(Q_load / max(Q_design, 1e-6), 0.0, 1.0))

    # ── 供回水温度 ──────────────────────────────────────────────────────────
    if hvac_on and hvac_mode == "cooling":
        supply_t = 7.0
        return_t = 7.0 + 5.0 * PLR
    elif hvac_on and hvac_mode == "heating":
        supply_t = 60.0
        return_t = 60.0 - 10.0 * PLR
    else:
        supply_t = air_temp * 0.9
        return_t = air_temp * 0.9

    # ── 空调能耗 ────────────────────────────────────────────────────────────
    E_pump_run = sqm * hp["pump_wm2"]["run"] / 1000.0
    E_pump_standby = sqm * hp["pump_wm2"]["standby"] / 1000.0
    E_vent_active = sqm * hp["vent_wm2"]["active"] / 1000.0 if S > 0.12 else sqm * hp["vent_wm2"]["minimum"] / 1000.0

    cop = hp["cop"]["cooling"] if hvac_mode == "cooling" else hp["cop"]["heating"]

    if hvac_on and hvac_mode in ("cooling", "heating"):
        hac = Q_load / max(cop, 1e-6) + E_pump_run + (0.5 if hvac_mode == "cooling" else 0.4) * E_vent_active
    else:
        hac = E_pump_standby + E_vent_active

    # ── 总电耗 ──────────────────────────────────────────────────────────────
    E_base = sqm * ip["P_base"] * S / 1000.0
    electricity_kwh = max(0.0, E_base + hac)

    # ── 湿度（确定性估算）──────────────────────────────────────────────────
    humi = float(humidity_rh)
    if hvac_on and hvac_mode == "cooling":
        humi -= (7.0 + 11.0 * PLR) * max(S, 0.12)
    elif hvac_on and hvac_mode == "heating":
        humi -= (3.0 + 5.0 * PLR) * max(S, 0.12)
    else:
        humi = 0.9 * humi + 0.1 * humidity_rh
    humi = float(np.clip(humi, 20.0, 95.0))

    return HourlyExpected(
        building_id=building_id,
        timestamp_utc=timestamp_utc,
        building_usage=usage,
        water_m3_expected=round(max(0.0, water_m3), 5),
        electricity_kwh_expected=round(max(0.0, electricity_kwh), 4),
        hac_energy_expected=round(max(0.0, hac), 4),
        sim_supply_temp_c_expected=round(supply_t, 3),
        sim_return_temp_c_expected=round(return_t, 3),
        humidity_rh_pct_expected=round(humi, 2),
        schedule_factor=round(S, 4),
        hvac_mode=hvac_mode,
        season=season,
        source_version=source_version,
    )
