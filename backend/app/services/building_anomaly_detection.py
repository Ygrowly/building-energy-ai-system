"""
建筑 KPI 规则异常检测（notebook 主链路版）
==========================================
从 detect_building_kpi_anomalies(1).ipynb 提炼的检测逻辑，
实现「并行症状层 + 空调根因层 + 相对/绝对双阈」矩阵。

层一：症状检测（每小时并行判定，5 个 flag）
  1. flag_water            水耗：>20% 且 >1000 L (=1.0 m³)
  2. flag_electricity      总电：>15% 且 >base_load * 10%
  3. flag_hvac_energy      空调电：>20% 且 >20 kWh
  4. flag_supply_deviation 供水温度偏离：|s - s_e| > 1.5℃
  5. flag_return_deviation 回水温度偏离：|r - r_e| > 2.0℃

层二：HVAC 根因（仅 flag_hvac_energy=True 时触发）
  A. A_low_efficiency   制冷 + 供水偏离 + 空调电异常
  B. B_small_deltaT     制冷 + 空调电异常 + 小温差 (r-s < 3℃)
  C. C_unexpected_on    非营业时段 + 期望空调低 + 实际高

软症状（阈值降 50%，用于捕获 ramp 相位）：
  flag_water_soft / flag_electricity_soft / flag_hvac_soft

设备归因（attribute_anomaly_devices）：
  根据激活的 flag 组合与设备类型映射，返回候选设备列表。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# ---------------------------------------------------------------------------
# 双阈值配置
# ---------------------------------------------------------------------------

@dataclass
class DetectionThresholds:
    # ── 水耗 ──
    water_rel: float = 0.20       # 相对阈值 20%
    water_abs_m3: float = 1.0     # 绝对阈值 1.0 m³ (= 1000 L)

    # ── 总电 ──
    elec_rel: float = 0.15        # 相对阈值 15%
    elec_base_frac: float = 0.10  # 绝对项：期望电耗 * 10%

    # ── 空调电 ──
    hac_rel: float = 0.20         # 相对阈值 20%
    hac_abs_kwh: float = 20.0     # 绝对阈值 20 kWh

    # ── 供回水温度偏离 ──
    supply_dev_c: float = 1.5     # 供水偏离阈值 ℃
    return_dev_c: float = 2.0     # 回水偏离阈值 ℃

    # ── 软症状（阈值 = 正常阈值 * soft_factor）──
    soft_factor: float = 0.5      # 软症状灵敏度系数

    # ── 空调根因 B ──
    min_delta_t: float = 3.0      # 供回水温差最小值（小于此值判定水力失调）

    # ── 空调根因 C ──
    schedule_off_threshold: float = 0.15  # 负荷率低于此值视为非营业
    hac_unexpected_abs_kwh: float = 30.0  # 非营业时期望 + N kWh 才判为非预期开机


DEFAULT_THRESHOLDS = DetectionThresholds()


# ---------------------------------------------------------------------------
# 输出 dataclass
# ---------------------------------------------------------------------------

@dataclass
class HourlyAnomalyFlags:
    """单楼单小时的检测结果（写入 kpi_anomaly_flags 表）。"""
    building_id: str
    timestamp_utc: str

    # 满幅度症状
    flag_water: bool = False
    flag_electricity: bool = False
    flag_hvac_energy: bool = False
    flag_supply_deviation: bool = False
    flag_return_deviation: bool = False

    # 软症状（供 ramp 阶段捕获）
    flag_water_soft: bool = False
    flag_electricity_soft: bool = False
    flag_hvac_soft: bool = False

    # 聚合 flag
    flag_symptom_soft_any: bool = False   # 任意软症状
    flag_symptom_union_any: bool = False  # 满幅度 ∪ 软症状

    # 空调根因诊断码
    hvac_diagnosis: str | None = None     # A_low_efficiency / B_small_deltaT / C_unexpected_on / other_hvac

    # 异常阶段（根据连续性推断）
    anomaly_phase: str | None = None      # ramp / full

    # 检测模式与版本
    detection_mode: str = "union"
    source_version: str = "notebook_v1"

    # 证据（偏差值等，JSON 可序列化 dict）
    evidence: dict = field(default_factory=dict)

    @property
    def is_anomaly_strict(self) -> bool:
        return any([
            self.flag_water, self.flag_electricity, self.flag_hvac_energy,
            self.flag_supply_deviation, self.flag_return_deviation,
        ])

    @property
    def is_anomaly_union(self) -> bool:
        return self.flag_symptom_union_any

    def to_db_dict(self) -> dict[str, Any]:
        """转为 kpi_anomaly_flags 表可直接 INSERT 的字典。"""
        import json
        return {
            "building_id": self.building_id,
            "timestamp": self.timestamp_utc,
            "flag_water": self.flag_water,
            "flag_electricity": self.flag_electricity,
            "flag_hvac_energy": self.flag_hvac_energy,
            "flag_supply_deviation": self.flag_supply_deviation,
            "flag_return_deviation": self.flag_return_deviation,
            "flag_symptom_soft_any": self.flag_symptom_soft_any,
            "flag_symptom_union_any": self.flag_symptom_union_any,
            "anomaly_phase": self.anomaly_phase,
            "hvac_diagnosis": self.hvac_diagnosis,
            "detection_mode": self.detection_mode,
            "source_version": self.source_version,
            "evidence_json": json.dumps(self.evidence, ensure_ascii=False),
        }


# ---------------------------------------------------------------------------
# 设备类型 → 异常 flag 映射（用于设备归因）
# ---------------------------------------------------------------------------

# device_type → 可触发的 flag 集合
_DEVICE_FLAG_MAP: dict[str, set[str]] = {
    "WaterMeter":       {"flag_water"},
    "ElectricityMeter": {"flag_electricity"},
    "HVAC":             {"flag_hvac_energy", "flag_supply_deviation", "flag_return_deviation"},
    "Chiller":          {"flag_hvac_energy", "flag_supply_deviation"},
    "Pump":             {"flag_hvac_energy", "flag_return_deviation"},
    "AHU":              {"flag_hvac_energy", "flag_return_deviation"},
    "Valve":            {"flag_return_deviation"},
    "EnvSensor":        set(),
}

# hvac_diagnosis → 优先归因设备类型
_DIAGNOSIS_DEVICE_MAP: dict[str, list[str]] = {
    "A_low_efficiency": ["Chiller", "HVAC"],
    "B_small_deltaT":   ["Pump", "Valve", "HVAC"],
    "C_unexpected_on":  ["HVAC"],
    "other_hvac":       ["HVAC"],
}


# ---------------------------------------------------------------------------
# 核心检测函数
# ---------------------------------------------------------------------------

def detect_single_hour(
    building_id: str,
    timestamp_utc: str,
    actual: dict[str, float | None],
    expected: dict[str, float | None],
    schedule_factor: float = 1.0,
    thresholds: DetectionThresholds = DEFAULT_THRESHOLDS,
    source_version: str = "notebook_v1",
) -> HourlyAnomalyFlags:
    """
    对单楼单小时做双阈值症状检测。

    Parameters
    ----------
    actual : dict
        实际观测值。键：water_m3, electricity_kwh, hac_energy,
        sim_supply_temp_c, sim_return_temp_c
    expected : dict
        notebook 基线期望值。键与 actual 相同但加 _expected 后缀或相同键。
    schedule_factor : float
        当前小时建筑活动系数 S（来自 kpi_expected_hourly.schedule_factor）。
    """
    eps = 1e-6
    result = HourlyAnomalyFlags(
        building_id=building_id,
        timestamp_utc=timestamp_utc,
        source_version=source_version,
    )
    evidence: dict[str, Any] = {}

    # ── 规则 1：水耗 ──────────────────────────────────────────────────────
    w_act = actual.get("water_m3")
    w_exp = expected.get("water_m3_expected") or expected.get("water_m3")
    if w_act is not None and w_exp is not None and w_exp > eps:
        delta_w = w_act - w_exp
        rel_w = delta_w / w_exp
        evidence["water_delta_m3"] = round(delta_w, 4)
        evidence["water_rel_pct"] = round(rel_w * 100, 2)
        if rel_w > thresholds.water_rel and delta_w > thresholds.water_abs_m3:
            result.flag_water = True
        soft_rel = thresholds.water_rel * thresholds.soft_factor
        soft_abs = thresholds.water_abs_m3 * thresholds.soft_factor
        if rel_w > soft_rel and delta_w > soft_abs:
            result.flag_water_soft = True

    # ── 规则 2：总电耗 ────────────────────────────────────────────────────
    e_act = actual.get("electricity_kwh")
    e_exp = expected.get("electricity_kwh_expected") or expected.get("electricity_kwh")
    if e_act is not None and e_exp is not None and e_exp > eps:
        delta_e = e_act - e_exp
        rel_e = delta_e / e_exp
        abs_thr_e = e_exp * thresholds.elec_base_frac
        evidence["elec_delta_kwh"] = round(delta_e, 3)
        evidence["elec_rel_pct"] = round(rel_e * 100, 2)
        if rel_e > thresholds.elec_rel and delta_e > abs_thr_e:
            result.flag_electricity = True
        soft_rel = thresholds.elec_rel * thresholds.soft_factor
        if rel_e > soft_rel and delta_e > abs_thr_e * thresholds.soft_factor:
            result.flag_electricity_soft = True

    # ── 规则 3：空调能耗 ───────────────────────────────────────────────────
    h_act = actual.get("hac_energy")
    h_exp = expected.get("hac_energy_expected") or expected.get("hac_energy")
    if h_act is not None and h_exp is not None and h_exp > eps:
        delta_h = h_act - h_exp
        rel_h = delta_h / h_exp
        evidence["hac_delta_kwh"] = round(delta_h, 3)
        evidence["hac_rel_pct"] = round(rel_h * 100, 2)
        if rel_h > thresholds.hac_rel and delta_h > thresholds.hac_abs_kwh:
            result.flag_hvac_energy = True
        soft_rel = thresholds.hac_rel * thresholds.soft_factor
        soft_abs = thresholds.hac_abs_kwh * thresholds.soft_factor
        if rel_h > soft_rel and delta_h > soft_abs:
            result.flag_hvac_soft = True

    # ── 规则 4：供水温度偏离 ───────────────────────────────────────────────
    s_act = actual.get("sim_supply_temp_c")
    s_exp = expected.get("sim_supply_temp_c_expected") or expected.get("sim_supply_temp_c")
    if s_act is not None and s_exp is not None:
        dev_s = abs(s_act - s_exp)
        evidence["supply_dev_c"] = round(s_act - s_exp, 3)
        if dev_s > thresholds.supply_dev_c:
            result.flag_supply_deviation = True

    # ── 规则 5：回水温度偏离 ───────────────────────────────────────────────
    r_act = actual.get("sim_return_temp_c")
    r_exp = expected.get("sim_return_temp_c_expected") or expected.get("sim_return_temp_c")
    if r_act is not None and r_exp is not None:
        dev_r = abs(r_act - r_exp)
        evidence["return_dev_c"] = round(r_act - r_exp, 3)
        if dev_r > thresholds.return_dev_c:
            result.flag_return_deviation = True

    # ── 软症状聚合 ─────────────────────────────────────────────────────────
    result.flag_symptom_soft_any = any([
        result.flag_water_soft,
        result.flag_electricity_soft,
        result.flag_hvac_soft,
    ])
    result.flag_symptom_union_any = result.is_anomaly_strict or result.flag_symptom_soft_any

    # ── 空调根因诊断 ────────────────────────────────────────────────────────
    if result.flag_hvac_energy:
        result.hvac_diagnosis = _diagnose_hvac(
            s_act, s_exp, r_act, h_act, h_exp, schedule_factor, thresholds,
        )
        evidence["hvac_diagnosis"] = result.hvac_diagnosis

    result.evidence = evidence
    return result


def _diagnose_hvac(
    supply_act: float | None,
    supply_exp: float | None,
    return_act: float | None,
    hac_act: float | None,
    hac_exp: float | None,
    schedule_factor: float,
    thr: DetectionThresholds,
) -> str:
    """
    空调根因诊断（仅在 flag_hvac_energy=True 时调用）。

    优先级：A > B > C > other_hvac
    """
    # 诊断 A：供水偏离 + 空调电异常（主机效能衰退）
    if supply_act is not None and supply_exp is not None:
        if abs(supply_act - supply_exp) > thr.supply_dev_c:
            return "A_low_efficiency"

    # 诊断 B：小温差（水力失调 / 旁通阀故障）
    if supply_act is not None and return_act is not None:
        delta_t = return_act - supply_act
        if delta_t < thr.min_delta_t:
            return "B_small_deltaT"

    # 诊断 C：非营业时段开机（排程失效）
    if schedule_factor <= thr.schedule_off_threshold:
        if hac_act is not None and hac_exp is not None:
            if hac_act > hac_exp + thr.hac_unexpected_abs_kwh:
                return "C_unexpected_on"

    return "other_hvac"


# ---------------------------------------------------------------------------
# 阶段推断（ramp / full）— 基于连续行滑窗
# ---------------------------------------------------------------------------

def assign_anomaly_phase(
    flags_series: list[HourlyAnomalyFlags],
    ramp_window: int = 3,
) -> list[HourlyAnomalyFlags]:
    """
    对有序的 flags_series 推断 anomaly_phase：
      - 满幅度症状（is_anomaly_strict）持续中的前 ramp_window 小时标记为 'ramp'
      - 之后持续的标记为 'full'
      - 无异常的保持 None

    注意：这是简化版本，notebook 中有更精细的连续段分析。
    """
    n = len(flags_series)
    # 先找连续段
    in_anom = False
    seg_start = 0
    for i, f in enumerate(flags_series):
        active = f.is_anomaly_union
        if active and not in_anom:
            in_anom = True
            seg_start = i
        if not active and in_anom:
            # 结束一段
            for j in range(seg_start, i):
                flags_series[j].anomaly_phase = (
                    "ramp" if (j - seg_start) < ramp_window else "full"
                )
            in_anom = False
    if in_anom:
        for j in range(seg_start, n):
            flags_series[j].anomaly_phase = (
                "ramp" if (j - seg_start) < ramp_window else "full"
            )
    return flags_series


# ---------------------------------------------------------------------------
# 设备归因
# ---------------------------------------------------------------------------

@dataclass
class DeviceAttribution:
    """单条设备归因结果（写入 anomaly_device_attributions）。"""
    building_id: str
    timestamp_utc: str
    device_id: str
    device_type: str
    attribution_role: str      # primary / secondary / supporting
    attribution_score: float   # 0.0 ~ 1.0
    attribution_reason: str
    evidence: dict = field(default_factory=dict)

    def to_db_dict(self) -> dict[str, Any]:
        import json
        return {
            "building_id": self.building_id,
            "timestamp": self.timestamp_utc,
            "device_id": self.device_id,
            "device_type": self.device_type,
            "attribution_role": self.attribution_role,
            "attribution_score": self.attribution_score,
            "attribution_reason": self.attribution_reason,
            "evidence_json": json.dumps(self.evidence, ensure_ascii=False),
        }


def attribute_anomaly_to_devices(
    flags: HourlyAnomalyFlags,
    devices: list[dict],  # [{"device_id": ..., "device_type": ...}, ...]
) -> list[DeviceAttribution]:
    """
    根据楼级 flags 和设备清单，推断最可能的故障设备。

    Parameters
    ----------
    flags : HourlyAnomalyFlags
        楼级检测结果。
    devices : list[dict]
        该楼关联的设备清单（含 device_id, device_type）。

    Returns
    -------
    list[DeviceAttribution]
        按 attribution_score 降序排列的设备归因列表。
    """
    if not flags.is_anomaly_union:
        return []

    active_flags: set[str] = set()
    if flags.flag_water:
        active_flags.add("flag_water")
    if flags.flag_electricity:
        active_flags.add("flag_electricity")
    if flags.flag_hvac_energy:
        active_flags.add("flag_hvac_energy")
    if flags.flag_supply_deviation:
        active_flags.add("flag_supply_deviation")
    if flags.flag_return_deviation:
        active_flags.add("flag_return_deviation")
    # 软症状
    if flags.flag_water_soft:
        active_flags.add("flag_water")
    if flags.flag_electricity_soft:
        active_flags.add("flag_electricity")
    if flags.flag_hvac_soft:
        active_flags.add("flag_hvac_energy")

    # 诊断优先设备类型
    priority_types: list[str] = []
    if flags.hvac_diagnosis and flags.hvac_diagnosis in _DIAGNOSIS_DEVICE_MAP:
        priority_types = _DIAGNOSIS_DEVICE_MAP[flags.hvac_diagnosis]

    results: list[DeviceAttribution] = []
    for dev in devices:
        dtype = dev.get("device_type", "")
        did = dev.get("device_id", "")
        related_flags = _DEVICE_FLAG_MAP.get(dtype, set()) & active_flags
        if not related_flags:
            continue

        # 计算归因分
        base_score = len(related_flags) / max(len(active_flags), 1)
        if dtype in priority_types:
            base_score = min(1.0, base_score + 0.3)

        role = "primary" if base_score >= 0.6 else ("secondary" if base_score >= 0.3 else "supporting")

        reasons = []
        if "flag_water" in related_flags:
            reasons.append("水耗偏高")
        if "flag_electricity" in related_flags:
            reasons.append("总电耗偏高")
        if "flag_hvac_energy" in related_flags:
            reasons.append("空调能耗偏高")
        if "flag_supply_deviation" in related_flags:
            reasons.append("供水温度偏离")
        if "flag_return_deviation" in related_flags:
            reasons.append("回水温度偏离")

        if flags.hvac_diagnosis == "A_low_efficiency" and dtype in ("Chiller", "HVAC"):
            reasons.append("主机效能衰退（供水温度无法达到设定点）")
        elif flags.hvac_diagnosis == "B_small_deltaT" and dtype in ("Pump", "Valve"):
            reasons.append("水力失调/大流量小温差（疑似旁通阀故障）")
        elif flags.hvac_diagnosis == "C_unexpected_on" and dtype == "HVAC":
            reasons.append("非预期开机（排程失效）")

        results.append(DeviceAttribution(
            building_id=flags.building_id,
            timestamp_utc=flags.timestamp_utc,
            device_id=did,
            device_type=dtype,
            attribution_role=role,
            attribution_score=round(base_score, 3),
            attribution_reason="；".join(reasons),
            evidence={**flags.evidence, "active_flags": list(related_flags)},
        ))

    results.sort(key=lambda x: x.attribution_score, reverse=True)
    return results


# ---------------------------------------------------------------------------
# 召回评估（供 notebook 验证用）
# ---------------------------------------------------------------------------

def evaluate_recall(
    flags_list: list[HourlyAnomalyFlags],
    labels: list[dict],  # [{"building_id", "timestamp", "anomaly_phase", ...}, ...]
    detection_mode: str = "union",
) -> dict:
    """
    计算症状层召回率，与 notebook evaluate_symptom_recall 对齐。

    detection_mode: 'strict' | 'union'
    """
    label_keys: set[tuple[str, str]] = {
        (str(r.get("building_id", "")), str(r.get("timestamp", "")))
        for r in labels
    }
    if not label_keys:
        return {"n_label_hours": 0, "symptom_recall": 0.0}

    hit = 0
    for f in flags_list:
        key = (f.building_id, f.timestamp_utc)
        if key not in label_keys:
            continue
        caught = f.is_anomaly_union if detection_mode == "union" else f.is_anomaly_strict
        if caught:
            hit += 1

    recall = hit / len(label_keys)
    return {
        "n_label_hours": len(label_keys),
        "symptom_recall": round(recall, 4),
        "hit_hours": hit,
    }
