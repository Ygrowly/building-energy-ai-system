"""
建筑 KPI 异常检测（规则引擎）

与 inject_building_anomalies.ipynb / detect_building_anomalies.ipynb 配套：
- 症状层：水耗、总电、空调电、供水温度偏离
- 根因层：在空调电异常时，供回水温与温差做 A/B/C 诊断

依赖：pandas, numpy
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Literal, Optional

import numpy as np
import pandas as pd

EPS = 1e-6

# 渐进段（inject 的 anomaly_phase=ramp）建议用更松的门槛做「早期异常」提示
DEFAULT_RAMP_THRESHOLD_FACTOR = 0.62

# 默认阈值（与 notebook 一致）
DEFAULT_WATER_REL = 0.20
DEFAULT_WATER_ABS = 1000.0
DEFAULT_ELEC_REL = 0.15
DEFAULT_ELEC_ABS_FRAC = 0.10  # 相对「基线非空调电」的绝对增量比例
DEFAULT_HVAC_REL = 0.20
# 与 inject 类型 5 等一致：增量常为「恰好 +20」，须用 >= 而非 >
DEFAULT_HVAC_ABS = 20.0
DEFAULT_SUPPLY_ABS_DEV_C = 1.5
# 回水偏离（开窗/旁通等会推回水温度）；与基线对比
DEFAULT_RETURN_ABS_DEV_C = 2.0


@dataclass
class DetectionThresholds:
    water_rel: float = DEFAULT_WATER_REL
    water_abs: float = DEFAULT_WATER_ABS
    elec_rel: float = DEFAULT_ELEC_REL
    elec_abs_frac: float = DEFAULT_ELEC_ABS_FRAC
    hvac_rel: float = DEFAULT_HVAC_REL
    hvac_abs: float = DEFAULT_HVAC_ABS
    supply_abs_dev_c: float = DEFAULT_SUPPLY_ABS_DEV_C
    return_abs_dev_c: float = DEFAULT_RETURN_ABS_DEV_C


BASELINE_COLS = [
    "water_l",
    "electricity_kwh",
    "hac_energy",
    "sim_supply_temp_c",
    "sim_return_temp_c",
]

# 症状标志 → 设备维度表 device_type（与 fwwb01_device_dimension.csv 一致）
DEFAULT_SYMPTOM_TO_DEVICE_TYPES: dict[str, tuple[str, ...]] = {
    "flag_water": ("water",),
    "flag_electricity": ("electricity",),
    "flag_hvac_energy": ("ac",),
    # 供回水温在维度表中无单独设备，约定归到冷站/空调计量单元 ac
    "flag_supply_deviation": ("ac",),
    "flag_return_deviation": ("ac",),
}

DEVICE_TYPE_ORDER = ("water", "electricity", "ac")


def load_baseline_csv(path: str) -> pd.DataFrame:
    b = pd.read_csv(path)
    b["timestamp"] = pd.to_datetime(b["timestamp"])
    return b


def merge_expected_from_baseline(
    df: pd.DataFrame,
    baseline: pd.DataFrame,
    baseline_cols: Optional[list[str]] = None,
) -> pd.DataFrame:
    """
    将基线表中的 KPI 列合并为 *_exp 期望列（与 detect notebook 一致）。
    """
    cols = baseline_cols or BASELINE_COLS
    key = ["timestamp", "building_id"]
    missing = [c for c in cols if c not in baseline.columns]
    if missing:
        raise ValueError(f"基线表缺少列: {missing}")
    base_sub = baseline[key + cols].rename(columns={c: f"{c}_exp" for c in cols})
    out = df.merge(base_sub, on=key, how="left")
    exp_missing = [c for c in base_sub.columns if c.endswith("_exp") and out[c].isna().all()]
    if exp_missing:
        raise ValueError(f"合并后以下期望列全为空，请检查键对齐: {exp_missing}")
    return out


def _hvac_diagnosis_vectorized(
    ts: pd.Series,
    hac_anom: np.ndarray,
    supply_dev: np.ndarray,
    cooling_like: np.ndarray,
    dT: np.ndarray,
    dT_e: np.ndarray,
    h: np.ndarray,
    h_e: np.ndarray,
) -> np.ndarray:
    """与 notebook 中 for 循环逻辑等价的向量化诊断。"""
    n = len(hac_anom)
    diag = np.full(n, "", dtype=object)
    ts = pd.to_datetime(ts)
    hr = ts.dt.hour.to_numpy()
    dow = ts.dt.dayofweek.to_numpy()

    hac = hac_anom.astype(bool)
    a = hac & supply_dev & cooling_like
    b = (
        hac
        & ~a
        & cooling_like
        & (dT < 3.0)
        & ((dT_e >= 3.0) | (h > h_e * 1.1))
    )
    offhours = (dow >= 5) | (hr < 7) | (hr > 20)
    c = hac & ~a & ~b & (h > 15.0) & (h_e < 8.0) & (dT >= 2.5) & offhours
    other = hac & ~a & ~b & ~c

    diag[a] = "A_chiller_or_sensor_supply"
    diag[b] = "B_low_delta_t_bypass"
    diag[c] = "C_offhours_schedule_or_stuck_on"
    diag[other] = "HVAC_high_other"
    return diag


def _soft_symptom_masks(
    w: np.ndarray,
    w_e: np.ndarray,
    e: np.ndarray,
    e_e: np.ndarray,
    h: np.ndarray,
    h_e: np.ndarray,
    sup: np.ndarray,
    sup_e: np.ndarray,
    ret: np.ndarray,
    ret_e: np.ndarray,
    th: DetectionThresholds,
    factor: float,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """低于满幅度阈值的症状布尔量，用于 ramp / 早期预警（factor 建议 0.55~0.7，越小越易触发）。"""
    f = float(factor)
    if f <= 0 or f > 1.0:
        raise ValueError("factor 应在 (0, 1] 内，为满幅度阈值的乘子（<1 表示放宽、更易报软症状）")

    base_elec_exp = np.maximum(e_e - h_e, 0.0)
    dw = w - w_e
    rw = dw / np.maximum(w_e, EPS)
    water_soft = (rw > th.water_rel * f) & (dw > th.water_abs * f)

    de = e - e_e
    re = de / np.maximum(e_e, EPS)
    elec_soft = (re > th.elec_rel * f) & (de > th.elec_abs_frac * f * np.maximum(base_elec_exp, 1.0))

    dh = h - h_e
    rh = dh / np.maximum(h_e, EPS)
    hac_soft = (rh > th.hvac_rel * f) & (dh >= th.hvac_abs * f)

    supply_soft = np.abs(sup - sup_e) > th.supply_abs_dev_c * f
    dret = ret - ret_e
    return_soft = np.abs(dret) > th.return_abs_dev_c * f

    soft_any = water_soft | elec_soft | hac_soft | supply_soft | return_soft
    return water_soft, elec_soft, hac_soft, supply_soft, return_soft, soft_any


def detect_building_kpi_anomalies(
    df: pd.DataFrame,
    *,
    thresholds: Optional[DetectionThresholds] = None,
    inplace: bool = False,
    include_soft_symptoms: bool = False,
    soft_threshold_factor: float = DEFAULT_RAMP_THRESHOLD_FACTOR,
) -> pd.DataFrame:
    """
    要求 df 已含合并后的 *_exp 列（与 merge_expected_from_baseline 输出一致）。

    新增列：
    - flag_water, flag_electricity, flag_hvac_energy, flag_supply_deviation, flag_return_deviation
    - flag_symptom_any（以上任一为真）
    - hvac_diagnosis
    - （可选）flag_*_soft、flag_return_deviation_soft、flag_symptom_soft_any
    """
    th = thresholds or DetectionThresholds()
    if not inplace:
        df = df.copy()

    req = [
        "water_l",
        "water_l_exp",
        "electricity_kwh",
        "electricity_kwh_exp",
        "hac_energy",
        "hac_energy_exp",
        "sim_supply_temp_c",
        "sim_supply_temp_c_exp",
        "sim_return_temp_c",
        "sim_return_temp_c_exp",
    ]
    miss = [c for c in req if c not in df.columns]
    if miss:
        raise ValueError(f"缺少列（请先合并基线）: {miss}")

    w = df["water_l"].to_numpy(dtype=float)
    w_e = df["water_l_exp"].to_numpy(dtype=float)
    e = df["electricity_kwh"].to_numpy(dtype=float)
    e_e = df["electricity_kwh_exp"].to_numpy(dtype=float)
    h = df["hac_energy"].to_numpy(dtype=float)
    h_e = df["hac_energy_exp"].to_numpy(dtype=float)
    sup = df["sim_supply_temp_c"].to_numpy(dtype=float)
    sup_e = df["sim_supply_temp_c_exp"].to_numpy(dtype=float)
    ret = df["sim_return_temp_c"].to_numpy(dtype=float)
    ret_e = df["sim_return_temp_c_exp"].to_numpy(dtype=float)

    base_elec_exp = np.maximum(e_e - h_e, 0.0)

    dw = w - w_e
    rw = dw / np.maximum(w_e, EPS)
    water_anom = (rw > th.water_rel) & (dw > th.water_abs)

    de = e - e_e
    re = de / np.maximum(e_e, EPS)
    elec_anom = (re > th.elec_rel) & (de > th.elec_abs_frac * np.maximum(base_elec_exp, 1.0))

    dh = h - h_e
    rh = dh / np.maximum(h_e, EPS)
    hac_anom = (rh > th.hvac_rel) & (dh >= th.hvac_abs)

    dT = ret - sup
    dT_e = ret_e - sup_e
    cooling_like = (sup > 3.0) & (sup < 14.0) & (h > 1.0)
    supply_dev = np.abs(sup - sup_e) > th.supply_abs_dev_c
    return_dev = np.abs(ret - ret_e) > th.return_abs_dev_c

    df["flag_water"] = water_anom
    df["flag_electricity"] = elec_anom
    df["flag_hvac_energy"] = hac_anom
    df["flag_supply_deviation"] = supply_dev
    df["flag_return_deviation"] = return_dev
    df["flag_symptom_any"] = water_anom | elec_anom | hac_anom | supply_dev | return_dev

    if include_soft_symptoms:
        ws, es, hs, ss, rs, sany = _soft_symptom_masks(
            w, w_e, e, e_e, h, h_e, sup, sup_e, ret, ret_e, th, soft_threshold_factor
        )
        df["flag_water_soft"] = ws
        df["flag_electricity_soft"] = es
        df["flag_hvac_energy_soft"] = hs
        df["flag_supply_deviation_soft"] = ss
        df["flag_return_deviation_soft"] = rs
        df["flag_symptom_soft_any"] = sany
        df["flag_symptom_union_any"] = df["flag_symptom_any"] | df["flag_symptom_soft_any"]

    df["hvac_diagnosis"] = _hvac_diagnosis_vectorized(
        df["timestamp"], hac_anom, supply_dev, cooling_like, dT, dT_e, h, h_e
    )

    return df


DetectionMode = Literal["strict", "soft", "union"]


def evaluate_symptom_recall(
    df: pd.DataFrame,
    labels: pd.DataFrame,
    *,
    label_phase: Optional[str] = None,
    detection_mode: DetectionMode = "strict",
) -> dict[str, Any]:
    """
    标签表中每个 (timestamp, building_id) 是否被症状规则检出。

    - **label_phase**：若标签含 `anomaly_phase`（与 inject 配套），可传 ``\"full\"`` / ``\"ramp\"`` 只评该阶段；\
      ``None`` 表示全部标签行（去重键仍为 timestamp+building_id）。
    - **detection_mode**：
      - ``strict``：仅满幅度 flag_*（默认）
      - ``soft``：仅 flag_*_soft（需检测时已 ``include_soft_symptoms=True``）
      - ``union``：strict 或 soft 任一为真（推荐用于与 ramp+full 混合评估）

    返回统计字典；labels 可选 anomaly_type_id、anomaly_phase。
    """
    labels = labels.copy()
    labels["timestamp"] = pd.to_datetime(labels["timestamp"])

    if label_phase is not None:
        if "anomaly_phase" not in labels.columns:
            raise ValueError("标签表无 anomaly_phase 列，无法按 label_phase 过滤")
        labels = labels.loc[labels["anomaly_phase"].astype(str).str.lower() == label_phase.lower()]
        if len(labels) == 0:
            return {
                "n_label_hours": 0,
                "symptom_recall": 0.0,
                "missed_keys": pd.DataFrame(),
                "label_phase_filter": label_phase,
                "detection_mode": detection_mode,
            }

    keys = labels[["timestamp", "building_id"]].drop_duplicates()

    flag_cols = [
        "flag_water",
        "flag_electricity",
        "flag_hvac_energy",
        "flag_supply_deviation",
        "flag_return_deviation",
    ]
    soft_cols = [
        "flag_water_soft",
        "flag_electricity_soft",
        "flag_hvac_energy_soft",
        "flag_supply_deviation_soft",
        "flag_return_deviation_soft",
    ]

    need = ["timestamp", "building_id"] + flag_cols
    if detection_mode in ("soft", "union"):
        miss_soft = [c for c in soft_cols if c not in df.columns]
        if miss_soft:
            raise ValueError(
                f"detection_mode={detection_mode} 需要软症状列 {soft_cols}，"
                "请先对 df 调用 detect_building_kpi_anomalies(..., include_soft_symptoms=True)"
            )
        need = need + soft_cols

    merged = keys.merge(df[need], on=["timestamp", "building_id"], how="left")

    hard = (
        merged["flag_water"]
        | merged["flag_electricity"]
        | merged["flag_hvac_energy"]
        | merged["flag_supply_deviation"]
        | merged["flag_return_deviation"]
    ).fillna(False)

    if detection_mode == "strict":
        caught = hard
    elif detection_mode == "soft":
        caught = (
            merged["flag_water_soft"]
            | merged["flag_electricity_soft"]
            | merged["flag_hvac_energy_soft"]
            | merged["flag_supply_deviation_soft"]
            | merged["flag_return_deviation_soft"]
        ).fillna(False)
    else:
        soft = (
            merged["flag_water_soft"]
            | merged["flag_electricity_soft"]
            | merged["flag_hvac_energy_soft"]
            | merged["flag_supply_deviation_soft"]
            | merged["flag_return_deviation_soft"]
        ).fillna(False)
        caught = hard | soft

    recall = float(caught.mean()) if len(merged) else 0.0
    out: dict[str, Any] = {
        "n_label_hours": len(merged),
        "symptom_recall": recall,
        "missed_keys": merged[~caught],
        "label_phase_filter": label_phase,
        "detection_mode": detection_mode,
    }
    if "anomaly_type_id" in labels.columns:
        by_type = labels.merge(df[need], on=["timestamp", "building_id"], how="left")
        by_hard = (
            by_type["flag_water"]
            | by_type["flag_electricity"]
            | by_type["flag_hvac_energy"]
            | by_type["flag_supply_deviation"]
            | by_type["flag_return_deviation"]
        ).fillna(False)
        if detection_mode == "strict":
            by_type["caught"] = by_hard
        elif detection_mode == "soft":
            by_type["caught"] = (
                by_type["flag_water_soft"]
                | by_type["flag_electricity_soft"]
                | by_type["flag_hvac_energy_soft"]
                | by_type["flag_supply_deviation_soft"]
                | by_type["flag_return_deviation_soft"]
            ).fillna(False)
        else:
            by_soft = (
                by_type["flag_water_soft"]
                | by_type["flag_electricity_soft"]
                | by_type["flag_hvac_energy_soft"]
                | by_type["flag_supply_deviation_soft"]
                | by_type["flag_return_deviation_soft"]
            ).fillna(False)
            by_type["caught"] = by_hard | by_soft
        out["recall_by_anomaly_type"] = by_type.groupby("anomaly_type_id")["caught"].mean()

    if "anomaly_phase" in labels.columns and len(labels) > 0:
        by_ph = labels.merge(df[need], on=["timestamp", "building_id"], how="left")
        ph_hard = (
            by_ph["flag_water"]
            | by_ph["flag_electricity"]
            | by_ph["flag_hvac_energy"]
            | by_ph["flag_supply_deviation"]
            | by_ph["flag_return_deviation"]
        ).fillna(False)
        if detection_mode == "strict":
            by_ph["caught"] = ph_hard
        elif detection_mode == "soft":
            by_ph["caught"] = (
                by_ph["flag_water_soft"]
                | by_ph["flag_electricity_soft"]
                | by_ph["flag_hvac_energy_soft"]
                | by_ph["flag_supply_deviation_soft"]
                | by_ph["flag_return_deviation_soft"]
            ).fillna(False)
        else:
            ph_soft = (
                by_ph["flag_water_soft"]
                | by_ph["flag_electricity_soft"]
                | by_ph["flag_hvac_energy_soft"]
                | by_ph["flag_supply_deviation_soft"]
                | by_ph["flag_return_deviation_soft"]
            ).fillna(False)
            by_ph["caught"] = ph_hard | ph_soft
        out["recall_by_anomaly_phase"] = by_ph.groupby("anomaly_phase")["caught"].mean()

    return out


def load_device_dimension_csv(path: str) -> pd.DataFrame:
    """设备维度表：building_id, device_id, device_type（如 ac / electricity / water）。"""
    d = pd.read_csv(path)
    req = ["building_id", "device_id", "device_type"]
    miss = [c for c in req if c not in d.columns]
    if miss:
        raise ValueError(f"设备维度表缺少列: {miss}")
    return d


def _device_type_lookup(device_dimension: pd.DataFrame) -> dict[str, dict[str, str]]:
    """building_id -> device_type -> device_id"""
    lut: dict[str, dict[str, str]] = {}
    for _, r in device_dimension.iterrows():
        bid = str(r["building_id"])
        typ = str(r["device_type"]).strip().lower()
        lut.setdefault(bid, {})[typ] = str(r["device_id"])
    return lut


def attribute_anomaly_devices(
    df: pd.DataFrame,
    device_dimension: pd.DataFrame,
    *,
    symptom_to_types: Optional[dict[str, tuple[str, ...]]] = None,
    include_soft_flags: bool = False,
    add_ac_when_hvac_diagnosis: bool = True,
    inplace: bool = False,
) -> pd.DataFrame:
    """
    在已有检测标志的 df 上，按 `fwwb01_device_dimension.csv` 类维度表归因设备。

    - 每建筑每种 device_type 对应唯一 device_id（与示例 CSV 一致）。
    - 供/回水温异常无单独设备类型时，约定归 **ac**。
    - 若 ``add_ac_when_hvac_diagnosis`` 且 ``hvac_diagnosis`` 非空，也会纳入 **ac**（与根因层一致）。

    新增列：
    - ``attributed_device_ids``：JSON 数组字符串，设备 id 按 water → electricity → ac 排序
    - ``attributed_device_types``：JSON 数组字符串，涉及的 device_type 同上顺序
    """
    mp = symptom_to_types or DEFAULT_SYMPTOM_TO_DEVICE_TYPES
    if not inplace:
        df = df.copy()
    lut = _device_type_lookup(device_dimension)

    # 软标志映射（与硬规则同设备类型）
    soft_map = {k + "_soft": v for k, v in mp.items()}

    def types_for_row(row: pd.Series) -> set[str]:
        types: set[str] = set()
        for col, dev_types in mp.items():
            if col in row.index and bool(row[col]):
                types.update(dev_types)
        if include_soft_flags:
            for col, dev_types in soft_map.items():
                if col in row.index and bool(row[col]):
                    types.update(dev_types)
        if add_ac_when_hvac_diagnosis and "hvac_diagnosis" in row.index:
            d = row["hvac_diagnosis"]
            if d is not None and str(d).strip():
                types.add("ac")
        return types

    ids_out: list[str] = []
    types_out: list[str] = []
    for _, row in df.iterrows():
        bid = str(row["building_id"])
        need = types_for_row(row)
        blut = lut.get(bid, {})
        ordered_ids: list[str] = []
        ordered_types: list[str] = []
        for t in DEVICE_TYPE_ORDER:
            if t in need and t in blut:
                ordered_types.append(t)
                ordered_ids.append(blut[t])
        ids_out.append(json.dumps(ordered_ids, ensure_ascii=False))
        types_out.append(json.dumps(ordered_types, ensure_ascii=False))

    df["attributed_device_ids"] = ids_out
    df["attributed_device_types"] = types_out
    return df


def run_detection_pipeline(
    anom_csv_path: str,
    baseline_csv_path: str,
    *,
    sort: bool = True,
    thresholds: Optional[DetectionThresholds] = None,
    include_soft_symptoms: bool = False,
    soft_threshold_factor: float = DEFAULT_RAMP_THRESHOLD_FACTOR,
) -> pd.DataFrame:
    """读入异常 KPI CSV + 基线 CSV，合并并检测，返回带标记的 DataFrame。"""
    df = pd.read_csv(anom_csv_path)
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    if sort:
        df = df.sort_values(["building_id", "timestamp"]).reset_index(drop=True)
    base = load_baseline_csv(baseline_csv_path)
    df = merge_expected_from_baseline(df, base)
    return detect_building_kpi_anomalies(
        df,
        thresholds=thresholds,
        include_soft_symptoms=include_soft_symptoms,
        soft_threshold_factor=soft_threshold_factor,
    )


__all__ = [
    "DEFAULT_RAMP_THRESHOLD_FACTOR",
    "DEFAULT_RETURN_ABS_DEV_C",
    "DetectionMode",
    "DetectionThresholds",
    "BASELINE_COLS",
    "EPS",
    "load_baseline_csv",
    "merge_expected_from_baseline",
    "detect_building_kpi_anomalies",
    "evaluate_symptom_recall",
    "run_detection_pipeline",
]
