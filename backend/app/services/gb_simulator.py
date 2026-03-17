"""
国标（GB）期望值仿真器
======================
基于 5 项中国国家标准，根据建筑类型、时序信息和环境参数，
实时计算每个时刻的能耗和水耗期望值，用于异常检测的"物理基线"。

依据标准：
  - GB/T 51161-2016  《民用建筑能耗标准》
  - GB 50034-2013    《建筑照明设计标准》
  - GB 50189-2015    《公共建筑节能设计标准》
  - GB 50736-2012    《民用建筑供暖通风与空气调节设计规范》
  - GB 50015-2019    《建筑给水排水设计标准》

输入：sqm, primary_space_usage, hour(本地时间), dayofweek(1=周一,7=周日),
      air_temp(℃), dew_temp(℃)
输出：RatedValues dataclass（无随机噪声，作为纯物理基准）

注意：此模块为纯函数（无 I/O），可在异步上下文中安全调用。
"""
from __future__ import annotations

from dataclasses import dataclass

# ---------------------------------------------------------------------------
# 建筑功率密度常量（照明 + 插座，W/㎡）— GB 50034-2013 / GB 50189-2015
# ---------------------------------------------------------------------------
_P_BASE: dict[str, float] = {
    "Office": 25.0,
    "Education": 20.0,
    "Public": 15.0,
}

# 峰值用水定额（L/㎡/h）— GB 50015-2019
# 办公楼 ≈ 40L/(人·天)，教学楼 ≈ 30L/(人·天)，图书馆 ≈ 4L/(人·天)
_W_PEAK: dict[str, float] = {
    "Office": 0.4,
    "Education": 1.0,
    "Public": 0.06,
}

# 人员散热估算（W/㎡）— 与功率密度分开计算，代表人体代谢散热
_Q_PERSON: dict[str, float] = {
    "Office": 10.0,
    "Education": 15.0,
    "Public": 8.0,
}

# 设计峰值冷/热负荷指标（W/㎡）
_Q_DESIGN_DENSITY = 100.0  # kW/(kW)，即 100 W/㎡ 折算

# 空调系统综合 COP — GB 50189-2015
_COP_COOLING = 3.5   # 含冷机 + 水泵 + 冷却塔
_COP_HEATING = 2.5   # 含热泵/锅炉 + 水泵

# 围护结构简化传热系数（W/㎡/℃）
_U_COEFF = 5.0

# 室内设计温度（℃）— GB 50189-2015
_T_IN_SUMMER = 26.0
_T_IN_WINTER = 20.0

# 供冷/供热标准供水温度与温差 — GB 50736-2012
_COOLING_SUPPLY_T = 7.0
_COOLING_RATED_DELTA_T = 5.0    # 制冷季额定供回水温差

_HEATING_SUPPLY_T = 60.0
_HEATING_RATED_DELTA_T = 10.0   # 供暖季额定供回水温差

# 过渡季/停机状态的通风基准电耗（W/㎡）
_VENTILATION_POWER_DENSITY = 2.0


@dataclass
class RatedValues:
    """
    国标期望值（每小时，无噪声的纯物理基线）。
    用于与 energy_data 中的实际值比较，触发双阈值告警。
    """
    rated_water_m3: float           # 期望水耗（m³/h）
    rated_electricity_kwh: float    # 期望总电耗（kWh/h）
    rated_hac_energy: float         # 期望空调能耗（kWh/h）
    expected_supply_temp: float     # 期望供水温度（℃）
    expected_return_temp: float     # 期望回水温度（℃）
    hvac_mode: str                  # "Cooling" | "Heating" | "Ventilation"
    schedule_factor: float          # 当前时刻建筑负荷率 S ∈ [0.05, 1.0]


def _normalize_usage(primary_space_usage: str) -> str:
    """
    统一建筑类型标识（兼容 DB 中的 'Public' 和 CSV 中的 'Public services'）。
    返回值只有三种：'Office' | 'Education' | 'Public'
    """
    s = (primary_space_usage or "").strip()
    if s.startswith("Public"):
        return "Public"
    if s in ("Education", "Teaching Building", "Teaching"):
        return "Education"
    return "Office"


def _get_schedule_factor(usage: str, hour: int, dayofweek: int) -> float:
    """
    计算时间系数 S ∈ [0.05, 1.0]，代表当前小时建筑的负荷率。

    dayofweek：1=周一 … 7=周日（与 Python isoweekday() 一致）
    0.05 为建筑最低基准负荷（保安 + 待机设备），非零以避免除零错误。
    """
    is_weekend = dayofweek >= 6  # 6=周六, 7=周日

    if usage == "Office":
        if is_weekend:
            return 0.05
        # 工作日
        if hour < 8:
            return 0.05
        if hour == 8:
            return 0.5
        if hour <= 17:
            return 1.0
        if hour <= 20:
            return 0.3
        return 0.05

    if usage == "Education":
        if is_weekend:
            return 0.2  # 部分自习室开放
        # 工作日
        if hour < 8:
            return 0.05
        if hour <= 12:
            return 1.0
        if hour == 13:
            return 0.4  # 午休
        if hour <= 17:
            return 1.0
        if hour <= 21:
            return 0.8  # 晚自习
        return 0.05

    # Public（图书馆）— 全周开放
    if hour < 8 or hour >= 22:
        return 0.05
    return 0.8


def calculate_rated_values(
    sqm: float,
    primary_space_usage: str,
    hour: int,
    dayofweek: int,
    air_temp: float,
    dew_temp: float,
) -> RatedValues:
    """
    计算指定时刻的国标期望值（确定性，无随机噪声，用于检测基线）。

    Parameters
    ----------
    sqm : float
        建筑面积（㎡）。若为 None 或 ≤ 0，退化为默认值 1000 ㎡。
    primary_space_usage : str
        建筑主要用途，如 'Office' / 'Education' / 'Public'。
    hour : int
        当前小时（0-23，本地时间 UTC+8）。
    dayofweek : int
        星期几（1=周一，7=周日，Python isoweekday 标准）。
    air_temp : float
        室外空气温度（℃）。
    dew_temp : float
        室外露点温度（℃），用于计算潜热负荷。

    Returns
    -------
    RatedValues
        各项能耗/水耗的国标期望值，以及当前 HVAC 工况和负荷率。
    """
    if not sqm or sqm <= 0:
        sqm = 1000.0

    usage = _normalize_usage(primary_space_usage)
    S = _get_schedule_factor(usage, hour, dayofweek)

    p_base = _P_BASE.get(usage, 20.0)
    w_peak = _W_PEAK.get(usage, 0.4)
    q_person = _Q_PERSON.get(usage, 10.0)

    # ── 1. 水耗（m³/h）— GB 50015-2019 ──────────────────────────────────
    rated_water = (sqm * w_peak * S) / 1000.0

    # ── 2. 空调热力学负荷（kW）───────────────────────────────────────────
    t_in = _T_IN_SUMMER if air_temp > 20.0 else _T_IN_WINTER

    # 围护结构传热负荷（W/㎡）
    q_env = _U_COEFF * (air_temp - t_in)

    # 内部得热（照明+设备+人员）（W/㎡）
    q_internal = p_base * S + q_person * S

    # 潜热/除湿负荷（W/㎡）— 仅夏季露点超过 15℃ 时有效（GB 50736-2012）
    q_latent = (
        max(0.0, 15.0 * (dew_temp - 15.0)) * S
        if air_temp > 22.0
        else 0.0
    )

    q_total = q_env + q_internal + q_latent
    q_design_kw = sqm * _Q_DESIGN_DENSITY / 1000.0  # 额定设计总负荷（kW）

    # 工况判定
    if air_temp > 22.0 or (15.0 <= air_temp <= 22.0 and q_total > 20.0):
        mode = "Cooling"
        q_load_kw = (sqm * max(0.1, q_total)) / 1000.0
    elif air_temp < 15.0:
        mode = "Heating"
        # 供暖负荷 = 围护结构散热 - 内部得热（内部得热可抵消部分供暖需求）
        q_load_kw = (sqm * max(0.1, abs(q_env) - q_internal)) / 1000.0
    else:
        mode = "Ventilation"
        q_load_kw = 0.0

    # ── 3. 空调能耗与供回水温度 ──────────────────────────────────────────
    e_pump_base = sqm * _VENTILATION_POWER_DENSITY / 1000.0  # 水泵/风机底载（kWh）

    if S <= 0.05:  # 夜间停机
        rated_hac = 0.0
        supply_t = air_temp * 0.9   # 停机后趋向室外温度
        return_t = air_temp * 0.9
    elif mode == "Cooling":
        plr = min(1.0, q_load_kw / q_design_kw) if q_design_kw > 0 else 1.0
        rated_hac = q_load_kw / _COP_COOLING + e_pump_base
        supply_t = _COOLING_SUPPLY_T
        # 回水温度随 PLR 动态变化（满载时温差 = 额定值）
        return_t = _COOLING_SUPPLY_T + _COOLING_RATED_DELTA_T * plr
    elif mode == "Heating":
        plr = min(1.0, q_load_kw / q_design_kw) if q_design_kw > 0 else 1.0
        rated_hac = q_load_kw / _COP_HEATING + e_pump_base
        supply_t = _HEATING_SUPPLY_T
        return_t = _HEATING_SUPPLY_T - _HEATING_RATED_DELTA_T * plr
    else:  # Ventilation — 仅新风机运行
        rated_hac = e_pump_base
        supply_t = air_temp
        return_t = air_temp

    # ── 4. 总电耗（kWh/h）────────────────────────────────────────────────
    e_base = (sqm * p_base * S) / 1000.0
    rated_elec = e_base + rated_hac

    return RatedValues(
        rated_water_m3=round(max(0.0, rated_water), 4),
        rated_electricity_kwh=round(max(0.0, rated_elec), 4),
        rated_hac_energy=round(max(0.0, rated_hac), 4),
        expected_supply_temp=round(supply_t, 2),
        expected_return_temp=round(return_t, 2),
        hvac_mode=mode,
        schedule_factor=S,
    )
