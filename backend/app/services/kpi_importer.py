"""
KPI 数据导入服务（CSV → 数据库）
================================
实现 notebook 产出的各类 CSV 文件到 Postgres 的幂等导入。

支持的输入文件类型：
  1. 原始能耗 CSV（含 timestamp, building_id, electricity_kwh, water_m3, ...）
     → energy_data
  2. notebook 生成的 simulated KPI CSV（含 *_nominal 列）
     → kpi_expected_hourly（从 *_nominal 列提取）+ energy_data（实际列）
  3. 基线 CSV（kpi_baseline_for_detection.csv）
     → kpi_expected_hourly
  4. 检测 flags CSV（kpi_detection_flags.csv）
     → kpi_anomaly_flags

统一规则：
  - 单位：water_l(L) → water_m3(m³)  / 1000.0
  - 时间：timestamp 字符串 → timestamptz（UTC，若无时区信息视为本地 UTC+8 并转换）
  - 建筑类型映射：office/teaching/library → Office/Education/Public services
  - Upsert：(timestamp, building_id) 唯一键，重复导入幂等
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone, timedelta
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 建筑类型映射
# ---------------------------------------------------------------------------

_USAGE_TO_PRIMARY: dict[str, str] = {
    "office":    "Office",
    "teaching":  "Education",
    "library":   "Public services",
    # 已是规范值的直通
    "Office":           "Office",
    "Education":        "Education",
    "Public services":  "Public services",
    "Public":           "Public services",
}


def normalize_primary_space_usage(val: str | None) -> str:
    """将各种来源的建筑类型统一为 DB 规范值。"""
    if not val:
        return "Education"
    return _USAGE_TO_PRIMARY.get(str(val).strip(), str(val).strip())


# ---------------------------------------------------------------------------
# 时间戳规范化
# ---------------------------------------------------------------------------

def parse_timestamp_utc(ts_str: str) -> str:
    """
    将字符串时间戳解析为 UTC ISO 8601 字符串。

    规则：
    - 若已含时区信息（+HH:MM 或 Z），直接转 UTC。
    - 若无时区信息，视为 CST (UTC+8)，转 UTC 后输出。
    """
    ts_str = str(ts_str).strip()
    # 尝试多种格式
    for fmt in (
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%d %H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%dT%H:%M",
        "%Y-%m-%d %H:%M",
    ):
        try:
            dt = datetime.strptime(ts_str, fmt)
            if dt.tzinfo is None:
                # 无时区：视为 CST (UTC+8)，转 UTC
                dt = dt.replace(tzinfo=timezone(timedelta(hours=8)))
            return dt.astimezone(timezone.utc).isoformat()
        except ValueError:
            continue
    raise ValueError(f"无法解析时间戳：{ts_str!r}")


# ---------------------------------------------------------------------------
# 字段映射与单位换算
# ---------------------------------------------------------------------------

# notebook CSV 列 → energy_data 列
_ENERGY_DATA_COL_MAP: dict[str, str] = {
    "electricity_kwh": "electricity_kwh",
    "water_l":         "water_m3",          # L → m³ 需额外 /1000
    "water_m3":        "water_m3",
    "hac_energy":      "hac_energy",
    "sim_supply_temp_c": "sim_supply_temp_c",
    "sim_return_temp_c": "sim_return_temp_c",
    "airTemperature":  "air_temp_c",
    "air_temp_c":      "air_temp_c",
    "dewTemperature":  "dew_temp_c",
    "dew_temp_c":      "dew_temp_c",
    "humidity":        "humidity_rh_pct",
    "humidity_rh_pct": "humidity_rh_pct",
}

# notebook nominal 列 → kpi_expected_hourly 列
_EXPECTED_COL_MAP: dict[str, str] = {
    "water_l_nominal":              "water_m3_expected",   # L → m³
    "electricity_kwh_nominal":      "electricity_kwh_expected",
    "hac_energy_nominal":           "hac_energy_expected",
    "sim_supply_temp_c_nominal":    "sim_supply_temp_c_expected",
    "sim_return_temp_c_nominal":    "sim_return_temp_c_expected",
    "humidity_rh_pct_nominal":      "humidity_rh_pct_expected",
    # 基线 CSV 可能直接以 _expected 结尾
    "water_m3_expected":            "water_m3_expected",
    "electricity_kwh_expected":     "electricity_kwh_expected",
    "hac_energy_expected":          "hac_energy_expected",
    "sim_supply_temp_c_expected":   "sim_supply_temp_c_expected",
    "sim_return_temp_c_expected":   "sim_return_temp_c_expected",
    "humidity_rh_pct_expected":     "humidity_rh_pct_expected",
}

# flag CSV 列 → kpi_anomaly_flags 列
_FLAGS_COL_MAP: dict[str, str] = {
    "flag_water":               "flag_water",
    "flag_electricity":         "flag_electricity",
    "flag_hvac_energy":         "flag_hvac_energy",
    "flag_supply_deviation":    "flag_supply_deviation",
    "flag_return_deviation":    "flag_return_deviation",
    "flag_symptom_soft_any":    "flag_symptom_soft_any",
    "flag_symptom_union_any":   "flag_symptom_union_any",
    "hvac_diagnosis":           "hvac_diagnosis",
    "anomaly_phase":            "anomaly_phase",
}


def _safe_float(v: Any) -> float | None:
    if v is None:
        return None
    try:
        f = float(v)
        import math
        return None if math.isnan(f) or math.isinf(f) else f
    except (TypeError, ValueError):
        return None


def _safe_bool(v: Any) -> bool:
    if isinstance(v, bool):
        return v
    if isinstance(v, str):
        return v.strip().lower() in ("true", "1", "yes")
    return bool(v)


# ---------------------------------------------------------------------------
# 行级转换函数
# ---------------------------------------------------------------------------

def row_to_energy_data(row: dict) -> dict | None:
    """将单行 CSV 行转换为 energy_data 表 INSERT 字典。返回 None 则跳过。"""
    try:
        ts = parse_timestamp_utc(row.get("timestamp", ""))
    except ValueError as e:
        logger.warning("跳过无效时间戳 %s: %s", row.get("timestamp"), e)
        return None

    bid = str(row.get("building_id", "")).strip()
    if not bid:
        return None

    result: dict[str, Any] = {"timestamp": ts, "building_id": bid}
    for src_col, dst_col in _ENERGY_DATA_COL_MAP.items():
        if src_col not in row:
            continue
        v = _safe_float(row[src_col])
        if v is None:
            continue
        if src_col == "water_l":
            v = v / 1000.0  # L → m³
        result[dst_col] = v

    return result


def row_to_expected_hourly(
    row: dict,
    source_version: str = "notebook_v1",
) -> dict | None:
    """将单行 CSV 转换为 kpi_expected_hourly INSERT 字典。"""
    try:
        ts = parse_timestamp_utc(row.get("timestamp", ""))
    except ValueError as e:
        logger.warning("跳过无效时间戳 %s: %s", row.get("timestamp"), e)
        return None

    bid = str(row.get("building_id", "")).strip()
    if not bid:
        return None

    # 建筑用途（内部 usage 或 primaryspaceusage）
    psu_raw = row.get("primaryspaceusage") or row.get("primary_space_usage") or row.get("building_usage") or ""
    building_usage = str(psu_raw).strip()

    result: dict[str, Any] = {
        "timestamp": ts,
        "building_id": bid,
        "building_usage": building_usage,
        "source_version": source_version,
    }

    # 元数据
    if "schedule_factor" in row or "sim_time_factor_s" in row:
        result["schedule_factor"] = _safe_float(row.get("schedule_factor") or row.get("sim_time_factor_s"))
    if "hvac_mode" in row:
        result["hvac_mode"] = str(row["hvac_mode"]).strip() or None

    # nominal 列（可能是 L，需换算）
    for src_col, dst_col in _EXPECTED_COL_MAP.items():
        if src_col not in row:
            continue
        v = _safe_float(row[src_col])
        if v is None:
            continue
        if src_col == "water_l_nominal":
            v = v / 1000.0  # L → m³
        result[dst_col] = v

    # 至少需要有一个期望值列
    kpi_cols = {
        "water_m3_expected", "electricity_kwh_expected",
        "hac_energy_expected", "sim_supply_temp_c_expected",
    }
    if not any(c in result for c in kpi_cols):
        return None

    return result


def row_to_anomaly_flags(
    row: dict,
    source_version: str = "notebook_v1",
) -> dict | None:
    """将单行 flags CSV 转换为 kpi_anomaly_flags INSERT 字典。"""
    try:
        ts = parse_timestamp_utc(row.get("timestamp", ""))
    except ValueError as e:
        logger.warning("跳过无效时间戳 %s: %s", row.get("timestamp"), e)
        return None

    bid = str(row.get("building_id", "")).strip()
    if not bid:
        return None

    result: dict[str, Any] = {
        "timestamp": ts,
        "building_id": bid,
        "detection_mode": "union",
        "source_version": source_version,
    }

    for src_col, dst_col in _FLAGS_COL_MAP.items():
        if src_col not in row:
            continue
        v = row[src_col]
        if dst_col.startswith("flag_"):
            result[dst_col] = _safe_bool(v)
        else:
            result[dst_col] = str(v).strip() if v is not None else None

    return result


# ---------------------------------------------------------------------------
# 批量 CSV 解析（不含 DB 写入，纯 Python 用于测试和验证）
# ---------------------------------------------------------------------------

def parse_simulated_kpi_csv(path: str) -> tuple[list[dict], list[dict]]:
    """
    解析 simulate_kpis_from_cleaned(1) 输出的 CSV，
    同时返回 (energy_data_rows, expected_rows)。
    """
    import csv
    energy_rows: list[dict] = []
    expected_rows: list[dict] = []

    with open(path, encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            er = row_to_energy_data(row)
            if er:
                energy_rows.append(er)
            xr = row_to_expected_hourly(row)
            if xr:
                expected_rows.append(xr)

    logger.info(
        "解析 %s: energy_data=%d 行, expected=%d 行",
        path, len(energy_rows), len(expected_rows),
    )
    return energy_rows, expected_rows


def parse_baseline_csv(path: str, source_version: str = "notebook_v1") -> list[dict]:
    """解析 kpi_baseline_for_detection.csv，返回 kpi_expected_hourly 行。"""
    import csv
    rows: list[dict] = []
    with open(path, encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            r = row_to_expected_hourly(row, source_version=source_version)
            if r:
                rows.append(r)
    logger.info("解析基线 CSV %s: %d 行", path, len(rows))
    return rows


def parse_flags_csv(path: str, source_version: str = "notebook_v1") -> list[dict]:
    """解析 kpi_detection_flags.csv，返回 kpi_anomaly_flags 行。"""
    import csv
    rows: list[dict] = []
    with open(path, encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            r = row_to_anomaly_flags(row, source_version=source_version)
            if r:
                rows.append(r)
    logger.info("解析 flags CSV %s: %d 行", path, len(rows))
    return rows


# ---------------------------------------------------------------------------
# 数据库写入（异步，使用 sqlalchemy async session）
# ---------------------------------------------------------------------------

_ENERGY_DATA_UPSERT = """
INSERT INTO energy_data
    (timestamp, building_id,
     electricity_kwh, water_m3, hac_energy,
     sim_supply_temp_c, sim_return_temp_c,
     air_temp_c, dew_temp_c, humidity_rh_pct)
VALUES
    (:timestamp, :building_id,
     :electricity_kwh, :water_m3, :hac_energy,
     :sim_supply_temp_c, :sim_return_temp_c,
     :air_temp_c, :dew_temp_c, :humidity_rh_pct)
ON CONFLICT (building_id, timestamp) DO UPDATE SET
    electricity_kwh    = EXCLUDED.electricity_kwh,
    water_m3           = EXCLUDED.water_m3,
    hac_energy         = EXCLUDED.hac_energy,
    sim_supply_temp_c  = EXCLUDED.sim_supply_temp_c,
    sim_return_temp_c  = EXCLUDED.sim_return_temp_c,
    air_temp_c         = EXCLUDED.air_temp_c,
    dew_temp_c         = EXCLUDED.dew_temp_c,
    humidity_rh_pct    = EXCLUDED.humidity_rh_pct
"""

_EXPECTED_UPSERT = """
INSERT INTO kpi_expected_hourly
    (timestamp, building_id, building_usage, schedule_factor, hvac_mode, source_version,
     water_m3_expected, electricity_kwh_expected, hac_energy_expected,
     sim_supply_temp_c_expected, sim_return_temp_c_expected, humidity_rh_pct_expected)
VALUES
    (:timestamp, :building_id, :building_usage, :schedule_factor, :hvac_mode, :source_version,
     :water_m3_expected, :electricity_kwh_expected, :hac_energy_expected,
     :sim_supply_temp_c_expected, :sim_return_temp_c_expected, :humidity_rh_pct_expected)
ON CONFLICT (building_id, timestamp) DO UPDATE SET
    building_usage             = EXCLUDED.building_usage,
    schedule_factor            = EXCLUDED.schedule_factor,
    hvac_mode                  = EXCLUDED.hvac_mode,
    source_version             = EXCLUDED.source_version,
    water_m3_expected          = EXCLUDED.water_m3_expected,
    electricity_kwh_expected   = EXCLUDED.electricity_kwh_expected,
    hac_energy_expected        = EXCLUDED.hac_energy_expected,
    sim_supply_temp_c_expected = EXCLUDED.sim_supply_temp_c_expected,
    sim_return_temp_c_expected = EXCLUDED.sim_return_temp_c_expected,
    humidity_rh_pct_expected   = EXCLUDED.humidity_rh_pct_expected
"""

_FLAGS_UPSERT = """
INSERT INTO kpi_anomaly_flags
    (timestamp, building_id,
     flag_water, flag_electricity, flag_hvac_energy,
     flag_supply_deviation, flag_return_deviation,
     flag_symptom_soft_any, flag_symptom_union_any,
     anomaly_phase, hvac_diagnosis,
     detection_mode, source_version, evidence_json)
VALUES
    (:timestamp, :building_id,
     :flag_water, :flag_electricity, :flag_hvac_energy,
     :flag_supply_deviation, :flag_return_deviation,
     :flag_symptom_soft_any, :flag_symptom_union_any,
     :anomaly_phase, :hvac_diagnosis,
     :detection_mode, :source_version, :evidence_json)
ON CONFLICT (building_id, timestamp) DO UPDATE SET
    flag_water              = EXCLUDED.flag_water,
    flag_electricity        = EXCLUDED.flag_electricity,
    flag_hvac_energy        = EXCLUDED.flag_hvac_energy,
    flag_supply_deviation   = EXCLUDED.flag_supply_deviation,
    flag_return_deviation   = EXCLUDED.flag_return_deviation,
    flag_symptom_soft_any   = EXCLUDED.flag_symptom_soft_any,
    flag_symptom_union_any  = EXCLUDED.flag_symptom_union_any,
    anomaly_phase           = EXCLUDED.anomaly_phase,
    hvac_diagnosis          = EXCLUDED.hvac_diagnosis,
    detection_mode          = EXCLUDED.detection_mode,
    source_version          = EXCLUDED.source_version,
    evidence_json           = EXCLUDED.evidence_json
"""


def _ensure_keys(row: dict, keys: list[str], default=None) -> dict:
    """确保 dict 包含指定键（缺失的填 default）。"""
    for k in keys:
        row.setdefault(k, default)
    return row


_ENERGY_KEYS = [
    "electricity_kwh", "water_m3", "hac_energy",
    "sim_supply_temp_c", "sim_return_temp_c",
    "air_temp_c", "dew_temp_c", "humidity_rh_pct",
]
_EXPECTED_KEYS = [
    "building_usage", "schedule_factor", "hvac_mode", "source_version",
    "water_m3_expected", "electricity_kwh_expected", "hac_energy_expected",
    "sim_supply_temp_c_expected", "sim_return_temp_c_expected", "humidity_rh_pct_expected",
]
_FLAGS_KEYS = [
    "flag_water", "flag_electricity", "flag_hvac_energy",
    "flag_supply_deviation", "flag_return_deviation",
    "flag_symptom_soft_any", "flag_symptom_union_any",
    "anomaly_phase", "hvac_diagnosis",
    "detection_mode", "source_version", "evidence_json",
]


async def bulk_upsert_energy_data(session, rows: list[dict], batch_size: int = 500) -> int:
    """批量幂等写入 energy_data 表。"""
    from sqlalchemy import text
    if not rows:
        return 0
    count = 0
    for i in range(0, len(rows), batch_size):
        batch = [_ensure_keys(dict(r), _ENERGY_KEYS) for r in rows[i : i + batch_size]]
        try:
            await session.execute(text(_ENERGY_DATA_UPSERT), batch)
            await session.commit()
            count += len(batch)
        except Exception as exc:
            await session.rollback()
            logger.error("energy_data 批量写入失败 batch[%d]: %s", i, exc)
    logger.info("energy_data 写入 %d 行", count)
    return count


async def bulk_upsert_expected_hourly(session, rows: list[dict], batch_size: int = 500) -> int:
    """批量幂等写入 kpi_expected_hourly 表。"""
    from sqlalchemy import text
    if not rows:
        return 0
    count = 0
    for i in range(0, len(rows), batch_size):
        batch = [_ensure_keys(dict(r), _EXPECTED_KEYS) for r in rows[i : i + batch_size]]
        try:
            await session.execute(text(_EXPECTED_UPSERT), batch)
            await session.commit()
            count += len(batch)
        except Exception as exc:
            await session.rollback()
            logger.error("kpi_expected_hourly 批量写入失败 batch[%d]: %s", i, exc)
    logger.info("kpi_expected_hourly 写入 %d 行", count)
    return count


async def bulk_upsert_anomaly_flags(session, rows: list[dict], batch_size: int = 500) -> int:
    """批量幂等写入 kpi_anomaly_flags 表。"""
    from sqlalchemy import text
    if not rows:
        return 0
    count = 0
    for i in range(0, len(rows), batch_size):
        batch = [_ensure_keys(dict(r), _FLAGS_KEYS, default=None) for r in rows[i : i + batch_size]]
        # bool 型字段 None → False
        for row in batch:
            for fk in ("flag_water", "flag_electricity", "flag_hvac_energy",
                       "flag_supply_deviation", "flag_return_deviation",
                       "flag_symptom_soft_any", "flag_symptom_union_any"):
                if row[fk] is None:
                    row[fk] = False
        try:
            await session.execute(text(_FLAGS_UPSERT), batch)
            await session.commit()
            count += len(batch)
        except Exception as exc:
            await session.rollback()
            logger.error("kpi_anomaly_flags 批量写入失败 batch[%d]: %s", i, exc)
    logger.info("kpi_anomaly_flags 写入 %d 行", count)
    return count
