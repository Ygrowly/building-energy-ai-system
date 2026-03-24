"""
预测服务层（forecast_service）
==============================
将 forecast_multi_6_12h_bundle.pkl 封装为可复用的预测服务，
负责模型加载、特征构造、推理执行和预警判定。

特征契约（41 维）：
  - 30 个 lag 特征：5 KPI x 6 滞后 (1,2,3,6,12,24)
  - 4 个 rolling 统计：w_mean24, e_mean24, hac_mean24, e_std24
  - 3 个时间特征：hour, dow, month
  - 4 个气象特征：Ta, Tdew, hum, rh

数据库字段映射：
  water_l       ← energy_data.water_m3  （列名虽含 m3，项目统一按 L 使用）
  electricity_kwh ← energy_data.electricity_kwh
  sim_supply_temp_c ← energy_data.sim_supply_temp_c
  sim_return_temp_c ← energy_data.sim_return_temp_c
  hac_energy    ← energy_data.hac_energy
  Ta            ← energy_data.air_temp_c
  Tdew          ← energy_data.dew_temp_c
  rh            ← energy_data.humidity_rh_pct
  hum           ← 由 Ta + Tdew 推导（绝对湿度 g/m³）
"""
from __future__ import annotations

import logging
import math
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import EnergyData, KpiExpectedHourly
from app.schemas.mcp_schemas import (
    ForecastedMetric,
    ForecastFromFeaturesOutput,
    ForecastKPIOutput,
    MCPError,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 模型单例加载
# ---------------------------------------------------------------------------
_ARTIFACT: dict | None = None
_PKL_PATH = Path(__file__).resolve().parents[2] / "forecast_multi_6_12h_bundle.pkl"

_LOAD_ERROR: str | None = None


def _get_artifact() -> dict | None:
    """懒加载 pkl artifact，进程内缓存。加载失败记录错误信息，不抛异常。"""
    global _ARTIFACT, _LOAD_ERROR
    if _ARTIFACT is not None:
        return _ARTIFACT
    if _LOAD_ERROR is not None:
        return None
    try:
        import joblib
        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            _ARTIFACT = joblib.load(_PKL_PATH)
        logger.info(
            "forecast model loaded: %s, features=%d, targets=%d",
            _ARTIFACT.get("model_name", "unknown"),
            len(_ARTIFACT.get("feature_cols", [])),
            len(_ARTIFACT.get("target_cols", [])),
        )
        return _ARTIFACT
    except Exception as exc:
        _LOAD_ERROR = str(exc)
        logger.error("forecast model load failed: %s", _LOAD_ERROR)
        return None


# ---------------------------------------------------------------------------
# 预警阈值（与 anomaly_detection_service 保持一致）
# ---------------------------------------------------------------------------
_THRESHOLDS: dict[str, dict[str, float]] = {
    "water_l":            {"rel": 0.20, "abs": 1000.0},
    "electricity_kwh":    {"rel": 0.15, "abs": 5.0},
    "hac_energy":         {"rel": 0.20, "abs": 20.0},
    "sim_supply_temp_c":  {"rel": 999,  "abs": 999},
    "sim_return_temp_c":  {"rel": 999,  "abs": 999},
}

_HISTORY_ROWS_MIN = 25


# ---------------------------------------------------------------------------
# DB 列 → 模型特征的字段映射
# ---------------------------------------------------------------------------
_DB_COL_TO_KPI = {
    "water_m3":          "water_l",
    "electricity_kwh":   "electricity_kwh",
    "sim_supply_temp_c": "sim_supply_temp_c",
    "sim_return_temp_c": "sim_return_temp_c",
    "hac_energy":        "hac_energy",
}

_KPI_NAMES = ["water_l", "electricity_kwh", "sim_supply_temp_c", "sim_return_temp_c", "hac_energy"]
_LAG_STEPS = [1, 2, 3, 6, 12, 24]


def _absolute_humidity(ta: float, tdew: float) -> float:
    """Magnus 公式推导绝对湿度 (g/m³)。"""
    if ta is None or tdew is None or math.isnan(ta) or math.isnan(tdew):
        return 0.0
    e_dew = 6.112 * math.exp(17.67 * tdew / (tdew + 243.5))
    return e_dew * 2.1674 / (273.15 + ta)


# ---------------------------------------------------------------------------
# 特征构造
# ---------------------------------------------------------------------------
def _build_features(df_input: pd.DataFrame, feature_cols: list[str]) -> pd.DataFrame:
    """
    从原始 energy_data 行构造模型所需的 41 维特征矩阵。
    输入 df 须按 timestamp 升序排列，至少 25 行。
    返回仅包含最后一行（最新时刻）的特征 DataFrame。
    """
    df = df_input.copy()

    for db_col, kpi_name in _DB_COL_TO_KPI.items():
        if kpi_name not in df.columns:
            df[kpi_name] = df[db_col]

    for kpi in _KPI_NAMES:
        for lag in _LAG_STEPS:
            df[f"{kpi}_lag{lag}"] = df[kpi].shift(lag)

    df["w_mean24"]   = df["water_l"].rolling(24, min_periods=1).mean()
    df["e_mean24"]   = df["electricity_kwh"].rolling(24, min_periods=1).mean()
    df["hac_mean24"] = df["hac_energy"].rolling(24, min_periods=1).mean()
    df["e_std24"]    = df["electricity_kwh"].rolling(24, min_periods=1).std().fillna(0)

    if "timestamp" in df.columns:
        ts_col = pd.to_datetime(df["timestamp"], utc=True)
    elif df.index.name == "timestamp":
        ts_col = pd.to_datetime(df.index, utc=True)
    else:
        ts_col = pd.to_datetime(df.iloc[:, 0], utc=True)

    df["hour"]  = ts_col.dt.hour
    df["dow"]   = ts_col.dt.dayofweek
    df["month"] = ts_col.dt.month

    df["Ta"]   = df["air_temp_c"]
    df["Tdew"] = df["dew_temp_c"]
    df["rh"]   = df["humidity_rh_pct"]
    df["hum"]  = df.apply(
        lambda r: _absolute_humidity(r.get("Ta", 0), r.get("Tdew", 0)),
        axis=1,
    )

    last_row = df.iloc[[-1]]

    missing = set(feature_cols) - set(last_row.columns)
    if missing:
        raise ValueError(f"无法构造的特征列：{sorted(missing)}")

    return last_row[feature_cols].copy()


# ---------------------------------------------------------------------------
# 预警判定
# ---------------------------------------------------------------------------
def _assess_risk(
    metric_name: str,
    predicted: float,
    expected: float | None,
) -> tuple[str, str | None, float | None]:
    """返回 (risk_level, rule_triggered, deviation_pct)。"""
    if expected is None or abs(expected) < 1e-9:
        return "normal", None, None

    dev_pct = (predicted - expected) / abs(expected) * 100
    thr = _THRESHOLDS.get(metric_name)
    if thr is None:
        return "normal", None, round(dev_pct, 2)

    delta = predicted - expected
    rel_exceeded = (delta / abs(expected)) > thr["rel"]
    abs_exceeded = delta > thr["abs"]

    if rel_exceeded and abs_exceeded:
        rule_map = {
            "water_l": "water_leak",
            "electricity_kwh": "electricity_overload",
            "hac_energy": "hvac_overconsumption",
        }
        return "warning", rule_map.get(metric_name), round(dev_pct, 2)

    return "normal", None, round(dev_pct, 2)


# ---------------------------------------------------------------------------
# 预测结果持久化
# ---------------------------------------------------------------------------
async def _persist_predictions(
    building_id: str,
    as_of: datetime,
    metrics: list[ForecastedMetric],
    model_name: str,
    session: AsyncSession,
) -> int:
    """将预测预警写入 predicted_anomaly_events 表，返回写入行数。"""
    rows = []
    for m in metrics:
        if m.risk_level == "normal":
            continue
        forecast_for = as_of + timedelta(hours=m.horizon_h)
        rows.append({
            "id": str(uuid.uuid4()),
            "as_of_timestamp": as_of,
            "forecast_for_timestamp": forecast_for,
            "horizon_h": m.horizon_h,
            "building_id": building_id,
            "metric_name": m.metric_name,
            "predicted_value": m.predicted_value,
            "expected_value": m.expected_value,
            "deviation_pct": m.deviation_pct,
            "risk_level": m.risk_level,
            "rule_triggered": m.rule_triggered,
            "model_name": model_name,
        })

    if not rows:
        return 0

    await session.execute(text("""
        INSERT INTO predicted_anomaly_events
          (id, as_of_timestamp, forecast_for_timestamp, horizon_h,
           building_id, metric_name, predicted_value, expected_value,
           deviation_pct, risk_level, rule_triggered, model_name)
        VALUES
          (:id, :as_of_timestamp, :forecast_for_timestamp, :horizon_h,
           :building_id, :metric_name, :predicted_value, :expected_value,
           :deviation_pct, :risk_level, :rule_triggered, :model_name)
        ON CONFLICT (id) DO NOTHING
    """), rows)
    await session.commit()
    return len(rows)


# ---------------------------------------------------------------------------
# 调试入口：features 直传
# ---------------------------------------------------------------------------
def forecast_from_raw_features(
    features: dict[str, float],
) -> ForecastFromFeaturesOutput | MCPError:
    """
    接受完整的特征字典，直接调用模型 predict，返回原始预测输出。
    纯 CPU 运算，不涉及数据库。
    """
    artifact = _get_artifact()
    if artifact is None:
        return MCPError(
            error=f"预测模型加载失败：{_LOAD_ERROR or '文件不存在'} (路径: {_PKL_PATH})",
            error_code="MODEL_LOAD_FAILED",
            tool_name="building_kpi_forecast_from_features",
        )

    pipe = artifact["pipeline"]
    feature_cols: list[str] = artifact["feature_cols"]
    target_cols: list[str] = artifact["target_cols"]
    model_name: str = artifact["model_name"]
    horizons: list[int] = artifact["horizons_h"]

    missing = set(feature_cols) - set(features.keys())
    if missing:
        return MCPError(
            error=f"缺少 {len(missing)} 个特征列：{sorted(missing)}",
            error_code="FEATURE_MISMATCH",
            tool_name="building_kpi_forecast_from_features",
        )

    X = pd.DataFrame([{col: features[col] for col in feature_cols}])

    try:
        Y_hat = pipe.predict(X)
    except Exception as exc:
        return MCPError(
            error=f"模型推理失败：{exc}",
            error_code="PREDICT_FAILED",
            tool_name="building_kpi_forecast_from_features",
        )

    predictions = {col: round(float(val), 4) for col, val in zip(target_cols, Y_hat[0])}

    return ForecastFromFeaturesOutput(
        model_name=model_name,
        horizons_h=horizons,
        target_cols=target_cols,
        predictions=predictions,
        feature_count_received=len(features),
        feature_count_expected=len(feature_cols),
    )


# ---------------------------------------------------------------------------
# 主入口
# ---------------------------------------------------------------------------
async def forecast_building_kpi(
    building_id: str,
    session: AsyncSession,
    as_of: datetime | None = None,
    include_expected_comparison: bool = True,
) -> ForecastKPIOutput | MCPError:
    """
    对指定楼宇执行 6h / 12h KPI 预测，返回预测值和预测预警。
    """
    artifact = _get_artifact()
    if artifact is None:
        return MCPError(
            error=f"预测模型加载失败：{_LOAD_ERROR or '文件不存在'} (路径: {_PKL_PATH})",
            error_code="MODEL_LOAD_FAILED",
            tool_name="building_kpi_forecast_6h_12h",
        )

    pipe = artifact["pipeline"]
    feature_cols: list[str] = artifact["feature_cols"]
    target_cols: list[str] = artifact["target_cols"]
    target_kpis: list[str] = artifact["target_kpis"]
    model_name: str = artifact["model_name"]
    horizons: list[int] = artifact["horizons_h"]

    from app.mcp.tools.data_query import get_building_info
    _meter_id, actual_bid = await get_building_info(session, building_id)
    if actual_bid is None:
        return MCPError(
            error=f"未找到建筑类型 '{building_id}'，请先调用 list_available_buildings 确认合法值",
            error_code="BUILDING_NOT_FOUND",
            tool_name="building_kpi_forecast_6h_12h",
        )

    # --- 查询历史数据 ---
    query = (
        select(
            EnergyData.timestamp,
            EnergyData.water_m3,
            EnergyData.electricity_kwh,
            EnergyData.sim_supply_temp_c,
            EnergyData.sim_return_temp_c,
            EnergyData.hac_energy,
            EnergyData.air_temp_c,
            EnergyData.dew_temp_c,
            EnergyData.humidity_rh_pct,
        )
        .where(EnergyData.building_id == actual_bid)
        .order_by(EnergyData.timestamp.desc())
        .limit(48)
    )
    if as_of is not None:
        query = query.where(EnergyData.timestamp <= as_of)

    result = await session.execute(query)
    rows = result.fetchall()

    if len(rows) < _HISTORY_ROWS_MIN:
        return MCPError(
            error=(
                f"建筑 '{building_id}' 的历史数据不足（需要至少 {_HISTORY_ROWS_MIN} 行，"
                f"当前仅 {len(rows)} 行），无法构造完整的滞后特征"
            ),
            error_code="INSUFFICIENT_HISTORY",
            tool_name="building_kpi_forecast_6h_12h",
        )

    col_names = [
        "timestamp", "water_m3", "electricity_kwh",
        "sim_supply_temp_c", "sim_return_temp_c", "hac_energy",
        "air_temp_c", "dew_temp_c", "humidity_rh_pct",
    ]
    df = pd.DataFrame([dict(zip(col_names, r)) for r in rows])
    df = df.sort_values("timestamp").reset_index(drop=True)
    df = df.ffill().fillna(0)

    actual_as_of = df["timestamp"].iloc[-1]
    if hasattr(actual_as_of, "tzinfo") and actual_as_of.tzinfo is None:
        actual_as_of = actual_as_of.replace(tzinfo=timezone.utc)

    # --- 构造特征 ---
    try:
        X = _build_features(df, feature_cols)
    except ValueError as exc:
        return MCPError(
            error=str(exc),
            error_code="FEATURE_MISMATCH",
            tool_name="building_kpi_forecast_6h_12h",
        )

    # --- 推理 ---
    try:
        Y_hat = pipe.predict(X)
    except Exception as exc:
        return MCPError(
            error=f"模型推理失败：{exc}",
            error_code="PREDICT_FAILED",
            tool_name="building_kpi_forecast_6h_12h",
        )

    predictions = dict(zip(target_cols, Y_hat[0]))

    # --- 获取基线期望值 ---
    expected_map: dict[str, dict[int, float]] = {}
    if include_expected_comparison:
        for h in horizons:
            future_ts = actual_as_of + timedelta(hours=h)
            exp_result = await session.execute(
                select(
                    KpiExpectedHourly.water_m3_expected,
                    KpiExpectedHourly.electricity_kwh_expected,
                    KpiExpectedHourly.hac_energy_expected,
                    KpiExpectedHourly.sim_supply_temp_c_expected,
                    KpiExpectedHourly.sim_return_temp_c_expected,
                )
                .where(KpiExpectedHourly.building_id == actual_bid)
                .where(KpiExpectedHourly.timestamp == future_ts)
            )
            exp_row = exp_result.fetchone()
            if exp_row is not None:
                expected_map.setdefault("water_l", {})[h] = float(exp_row[0]) if exp_row[0] is not None else None
                expected_map.setdefault("electricity_kwh", {})[h] = float(exp_row[1]) if exp_row[1] is not None else None
                expected_map.setdefault("hac_energy", {})[h] = float(exp_row[2]) if exp_row[2] is not None else None
                expected_map.setdefault("sim_supply_temp_c", {})[h] = float(exp_row[3]) if exp_row[3] is not None else None
                expected_map.setdefault("sim_return_temp_c", {})[h] = float(exp_row[4]) if exp_row[4] is not None else None

    # --- 组装输出 ---
    metrics: list[ForecastedMetric] = []
    for kpi in target_kpis:
        for h in horizons:
            col_name = f"y_{kpi}_tplus{h}h"
            pred_val = float(predictions.get(col_name, 0.0))
            exp_val = expected_map.get(kpi, {}).get(h)

            risk_level, rule_triggered, dev_pct = _assess_risk(kpi, pred_val, exp_val)

            metrics.append(ForecastedMetric(
                metric_name=kpi,
                horizon_h=h,
                predicted_value=round(pred_val, 4),
                expected_value=round(exp_val, 4) if exp_val is not None else None,
                deviation_pct=dev_pct,
                risk_level=risk_level,
                rule_triggered=rule_triggered,
            ))

    warnings_count = sum(1 for m in metrics if m.risk_level != "normal")

    # --- 持久化预警 ---
    persisted = False
    if warnings_count > 0:
        try:
            n = await _persist_predictions(
                building_id=building_id,
                as_of=actual_as_of,
                metrics=metrics,
                model_name=model_name,
                session=session,
            )
            persisted = n > 0
            logger.info("forecast: 楼 %s 写入 %d 条预测预警", building_id, n)
        except Exception as exc:
            logger.warning("forecast: 预测预警持久化失败（降级返回）: %s", exc)

    return ForecastKPIOutput(
        building_id=building_id,
        as_of_timestamp=actual_as_of,
        model_name=model_name,
        horizons_h=horizons,
        metrics=metrics,
        warnings_count=warnings_count,
        data_rows_used=len(df),
        persisted=persisted,
    )
