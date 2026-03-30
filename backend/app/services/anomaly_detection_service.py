"""
异常监测服务（anomaly_detection_service）
==========================================
直接移植 detect_building_kpi_anomalies(1).ipynb 中的双阈值 + 空调根因检测规则。
# #region agent log
# Debug instrumentation for session e8ce47
# #endregion

检测逻辑两层：
  第一层 — 并行症状 flags（5 项，逐行独立判定）：
    flag_water, flag_electricity, flag_hvac_energy,
    flag_supply_deviation, flag_return_deviation
  软症状 — 阈值的 50% 灵敏度，用于 anomaly_phase=ramp 检测：
    flag_symptom_soft_any, flag_symptom_union_any

  第二层 — 空调根因（仅在 flag_hvac_energy=True 时才诊断）：
    A_low_efficiency: 制冷 + 供水偏离 + 空调过耗
    B_small_deltaT  : 制冷 + 空调过耗 + 小温差 (return-supply < 3)
    C_unexpected_on : 低日程 + 期望空调很低但实际很高

单位约定：water 单位为 **升 (L)**（与 energy_data.water_m3 列实际存储一致）。

检测结果写入：
  kpi_anomaly_flags  — 每楼每小时细粒度症状
  anomaly_events     — 汇总后的事件（每条 flag 生成一条事件记录）
"""
from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

import os
import time

from app.db.models import Building, EnergyData, KpiExpectedHourly

logger = logging.getLogger(__name__)

# #region agent log
_DBG_LOG_PATH = os.path.join(os.path.dirname(__file__), "..", "..", "..", "debug-e8ce47.log")
def _dbg_ad(hypothesis: str, location: str, message: str, data: dict):
    try:
        entry = json.dumps({"sessionId": "e8ce47", "runId": "rebuild", "hypothesisId": hypothesis, "location": location, "message": message, "data": data, "timestamp": int(time.time()*1000)}, default=str)
        with open(_DBG_LOG_PATH, "a", encoding="utf-8") as f:
            f.write(entry + "\n")
    except Exception:
        pass
# #endregion

# ---------------------------------------------------------------------------
# 检测阈值（与 notebook detect_building_kpi_anomalies 中 DetectionThresholds 一致）
# ---------------------------------------------------------------------------
_EPS = 1e-6

# 满幅度阈值
_WATER_REL = 0.20     # 相对偏差 > 20%
_WATER_ABS = 1000.0   # 绝对偏差 > 1000 L

_ELEC_REL = 0.15      # 相对偏差 > 15%
# 绝对阈值：0.10 × max(e_e - h_e, 1)  （动态，见计算）

_HAC_REL = 0.20       # 相对偏差 > 20%
_HAC_ABS = 20.0       # 绝对偏差 ≥ 20 kWh

_SUPPLY_DEV = 1.5     # |supply - supply_e| > 1.5 ℃
_RETURN_DEV = 2.0     # |return - return_e| > 2.0 ℃

# 软症状：阈值 × 0.62（与 notebook DEFAULT_RAMP_THRESHOLD_FACTOR 一致）
_SOFT_FACTOR = 0.62

# 空调根因判定参数
_SMALL_DELTA_T_THRESHOLD = 3.0   # (return - supply) < 3 ℃ → 小温差
_UNEXPECTED_ON_SCHEDULE_MAX = 0.12  # S ≤ 0.12 时视为非营业
_UNEXPECTED_ON_HAC_MARGIN = 5.0     # 实际 hac > expected + 5 kWh


# ---------------------------------------------------------------------------
# 内部辅助
# ---------------------------------------------------------------------------
def _diagnose_hvac(
    *,
    supply: float | None,
    ret: float | None,
    supply_e: float | None,
    return_e: float | None,
    hac_actual: float | None,
    hac_expected: float | None,
    hour: int,
    dayofweek: int,
) -> str:
    """
    第二层 HVAC 根因诊断（仅当 flag_hvac_energy 为 True 时调用）。
    与 notebook _hvac_diagnosis_vectorized 对齐。
    优先级：A > B > C > other
    """
    h = hac_actual or 0.0
    h_e = hac_expected or 0.0
    sup = supply if supply is not None else 0.0
    sup_e = supply_e if supply_e is not None else 0.0
    ret_val = ret if ret is not None else 0.0
    ret_e_val = return_e if return_e is not None else 0.0

    dT = ret_val - sup
    dT_e = ret_e_val - sup_e
    cooling_like = (sup > 3.0) and (sup < 14.0) and (h > 1.0)
    supply_dev = abs(sup - sup_e) > _SUPPLY_DEV

    # A: 制冷工况 + 供水偏离
    if supply_dev and cooling_like:
        return "A_low_efficiency"

    # B: 制冷 + 小温差（旁通或大流量）
    if cooling_like and dT < _SMALL_DELTA_T_THRESHOLD and (dT_e >= _SMALL_DELTA_T_THRESHOLD or h > h_e * 1.1):
        return "B_small_deltaT"

    # C: 非营业时段 + 空调能耗异常高
    # ISO dayofweek: 6=Sat, 7=Sun ↔ notebook pandas dayofweek >= 5
    offhours = (dayofweek >= 6) or (hour < 7) or (hour > 20)
    if h > 15.0 and h_e < 8.0 and dT >= 2.5 and offhours:
        return "C_unexpected_on"

    return "other_hvac"


def _detect_flags(
    *,
    water: float | None,
    water_e: float | None,
    elec: float | None,
    elec_e: float | None,
    hac: float | None,
    hac_e: float | None,
    supply: float | None,
    supply_e: float | None,
    ret: float | None,
    return_e: float | None,
    hour: int,
    dayofweek: int,
    soft: bool = False,
) -> dict[str, Any]:
    """
    计算单行的所有症状 flags。与 notebook detect_building_kpi_anomalies 对齐。
    soft=True 时使用软阈值（factor=0.62）。
    """
    factor = _SOFT_FACTOR if soft else 1.0
    eps = _EPS

    # flag_water
    fw = False
    if water is not None and water_e is not None and water_e > eps:
        delta_w = water - water_e
        rel_w = delta_w / max(water_e, eps)
        fw = rel_w > _WATER_REL * factor and delta_w > _WATER_ABS * factor

    # flag_electricity
    fe = False
    if elec is not None and elec_e is not None and elec_e > eps:
        delta_e = elec - elec_e
        rel_e = delta_e / max(elec_e, eps)
        base_load = max((elec_e or 0.0) - (hac_e or 0.0), 1.0)
        abs_e = 0.10 * base_load * factor
        fe = rel_e > _ELEC_REL * factor and delta_e > abs_e

    # flag_hvac_energy
    fh = False
    if hac is not None and hac_e is not None and hac_e > eps:
        delta_h = hac - hac_e
        rel_h = delta_h / max(hac_e, eps)
        fh = rel_h > _HAC_REL * factor and delta_h >= _HAC_ABS * factor

    # flag_supply_deviation（与 notebook 一致，不跳过任何行）
    fs = False
    if supply is not None and supply_e is not None:
        fs = abs(supply - supply_e) > _SUPPLY_DEV * factor

    # flag_return_deviation（与 notebook 一致，不跳过任何行）
    fr = False
    if ret is not None and return_e is not None:
        fr = abs(ret - return_e) > _RETURN_DEV * factor

    # HVAC 根因（仅满幅度时诊断）
    hvac_diag: str | None = None
    if fh and not soft:
        hvac_diag = _diagnose_hvac(
            supply=supply,
            ret=ret,
            supply_e=supply_e,
            return_e=return_e,
            hac_actual=hac,
            hac_expected=hac_e,
            hour=hour,
            dayofweek=dayofweek,
        )

    return {
        "flag_water": fw,
        "flag_electricity": fe,
        "flag_hvac_energy": fh,
        "flag_supply_deviation": fs,
        "flag_return_deviation": fr,
        "hvac_diagnosis": hvac_diag,
    }


# ---------------------------------------------------------------------------
# 主批处理函数：检测单楼，写 kpi_anomaly_flags
# ---------------------------------------------------------------------------
async def detect_for_building(
    building_id: str,
    db: AsyncSession,
) -> list[dict[str, Any]]:
    """
    JOIN energy_data + kpi_expected_hourly，应用检测规则，
    返回可直接 upsert 到 kpi_anomaly_flags 的字典列表。
    """
    rows_result = await db.execute(text("""
        SELECT
            e.timestamp,
            e.electricity_kwh,
            e.water_m3,
            e.hac_energy,
            e.sim_supply_temp_c,
            e.sim_return_temp_c,
            x.electricity_kwh_expected,
            x.water_m3_expected,
            x.hac_energy_expected,
            x.sim_supply_temp_c_expected,
            x.sim_return_temp_c_expected,
            x.schedule_factor,
            x.hvac_mode
        FROM energy_data e
        JOIN kpi_expected_hourly x
            ON x.building_id = e.building_id AND x.timestamp = e.timestamp
        WHERE e.building_id = :bid
        ORDER BY e.timestamp ASC
    """), {"bid": building_id})
    rows = rows_result.fetchall()

    if not rows:
        logger.info("detect_for_building: 楼 %s 无可检测行（kpi_expected_hourly 可能为空）", building_id)
        return []

    flag_rows: list[dict[str, Any]] = []

    for row in rows:
        (ts, elec, water, hac, supply, ret,
         elec_e, water_e, hac_e, supply_e, return_e,
         sched_f, hvac_mode) = row

        if hasattr(ts, "tzinfo") and ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)

        # 满幅度 flags
        full = _detect_flags(
            water=water, water_e=water_e,
            elec=elec, elec_e=elec_e,
            hac=hac, hac_e=hac_e,
            supply=supply, supply_e=supply_e,
            ret=ret, return_e=return_e,
            hour=ts.hour, dayofweek=ts.isoweekday(),
            soft=False,
        )

        # 软症状 flags（factor=0.62 灵敏度）
        soft = _detect_flags(
            water=water, water_e=water_e,
            elec=elec, elec_e=elec_e,
            hac=hac, hac_e=hac_e,
            supply=supply, supply_e=supply_e,
            ret=ret, return_e=return_e,
            hour=ts.hour, dayofweek=ts.isoweekday(),
            soft=True,
        )

        flag_soft_any = (
            soft["flag_water"] or soft["flag_electricity"] or
            soft["flag_hvac_energy"] or soft["flag_supply_deviation"] or
            soft["flag_return_deviation"]
        )
        flag_union_any = flag_soft_any or (
            full["flag_water"] or full["flag_electricity"] or
            full["flag_hvac_energy"] or full["flag_supply_deviation"] or
            full["flag_return_deviation"]
        )

        # anomaly_phase: full 有任一满幅度 flag, ramp 仅有软症状
        any_full = (
            full["flag_water"] or full["flag_electricity"] or
            full["flag_hvac_energy"] or full["flag_supply_deviation"] or
            full["flag_return_deviation"]
        )
        if any_full:
            phase = "full"
        elif flag_soft_any:
            phase = "ramp"
        else:
            phase = None

        # evidence_json：记录实际值与期望值用于 UI 展示
        evidence = {
            "elec": elec, "elec_e": elec_e,
            "water": water, "water_e": water_e,
            "hac": hac, "hac_e": hac_e,
            "supply": supply, "supply_e": supply_e,
            "return": ret, "return_e": return_e,
        }

        flag_rows.append({
            "timestamp": ts,
            "building_id": building_id,
            "flag_water": full["flag_water"],
            "flag_electricity": full["flag_electricity"],
            "flag_hvac_energy": full["flag_hvac_energy"],
            "flag_supply_deviation": full["flag_supply_deviation"],
            "flag_return_deviation": full["flag_return_deviation"],
            "flag_symptom_soft_any": flag_soft_any,
            "flag_symptom_union_any": flag_union_any,
            "anomaly_phase": phase,
            "hvac_diagnosis": full["hvac_diagnosis"],
            "detection_mode": "union",
            "source_version": "notebook_v1",
            "evidence_json": json.dumps(evidence, default=str),
        })

    # #region agent log
    full_count = sum(1 for r in flag_rows if r.get("anomaly_phase") == "full")
    ramp_count = sum(1 for r in flag_rows if r.get("anomaly_phase") == "ramp")
    flag_water_count = sum(1 for r in flag_rows if r["flag_water"])
    flag_elec_count = sum(1 for r in flag_rows if r["flag_electricity"])
    flag_hac_count = sum(1 for r in flag_rows if r["flag_hvac_energy"])
    flag_supply_count = sum(1 for r in flag_rows if r["flag_supply_deviation"])
    flag_return_count = sum(1 for r in flag_rows if r["flag_return_deviation"])
    _dbg_ad("H_STATS", f"anomaly_detection_service.py:detect_for_building:{building_id}", "detection-summary", {
        "building_id": building_id, "total_rows": len(flag_rows),
        "full": full_count, "ramp": ramp_count,
        "flag_water": flag_water_count, "flag_electricity": flag_elec_count,
        "flag_hac": flag_hac_count, "flag_supply": flag_supply_count, "flag_return": flag_return_count,
    })
    # #endregion
    logger.info("detect_for_building: 楼 %s 检测了 %d 行", building_id, len(flag_rows))
    return flag_rows


async def upsert_anomaly_flags(
    rows: list[dict[str, Any]],
    db: AsyncSession,
) -> int:
    """幂等 upsert kpi_anomaly_flags，按 (building_id, timestamp) 冲突处理。"""
    if not rows:
        return 0

    await db.execute(
        text("""
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
            ON CONFLICT (timestamp, building_id)
            DO UPDATE SET
              flag_water               = EXCLUDED.flag_water,
              flag_electricity         = EXCLUDED.flag_electricity,
              flag_hvac_energy         = EXCLUDED.flag_hvac_energy,
              flag_supply_deviation    = EXCLUDED.flag_supply_deviation,
              flag_return_deviation    = EXCLUDED.flag_return_deviation,
              flag_symptom_soft_any    = EXCLUDED.flag_symptom_soft_any,
              flag_symptom_union_any   = EXCLUDED.flag_symptom_union_any,
              anomaly_phase            = EXCLUDED.anomaly_phase,
              hvac_diagnosis           = EXCLUDED.hvac_diagnosis,
              detection_mode           = EXCLUDED.detection_mode,
              source_version           = EXCLUDED.source_version,
              evidence_json            = EXCLUDED.evidence_json
        """),
        rows,
    )
    await db.commit()
    return len(rows)


# ---------------------------------------------------------------------------
# anomaly_events 生成：从 kpi_anomaly_flags 汇总
# ---------------------------------------------------------------------------
_FLAG_TO_RULE = {
    "flag_water":            "water_leak",
    "flag_electricity":      "electricity_overload",
    "flag_hvac_energy":      "hvac_overconsumption",
    "flag_supply_deviation": "supply_temp_deviation",
    "flag_return_deviation": "return_temp_deviation",
}

_BUILDING_DISPLAY_NAMES = {
    "Education": "教学楼",
    "Office": "办公楼",
    "Public services": "公共楼",
}

_RULE_MESSAGES: dict[str, str] = {
    "water_leak":            "水耗异常",
    "electricity_overload":  "总电耗超标",
    "hvac_overconsumption":  "空调能耗过高",
    "supply_temp_deviation": "供水温度偏离",
    "return_temp_deviation": "回水温度偏离",
}


def _build_anomaly_event(
    *,
    ts: datetime,
    building_id: str,
    building_display: str,
    rule: str,
    flag_key: str,
    evidence: dict,
    flag_map: dict[str, bool],
    hvac_diag: str | None,
    phase: str | None,
    sched_f: float | None,
) -> dict[str, Any]:
    """构造单条 anomaly_events 插入字典。"""
    actual_map = {
        "flag_water":            ("water",   "L"),
        "flag_electricity":      ("elec",    "kWh"),
        "flag_hvac_energy":      ("hac",     "kWh"),
        "flag_supply_deviation": ("supply",  "℃"),
        "flag_return_deviation": ("return",  "℃"),
    }
    expected_map = {
        "flag_water":            "water_e",
        "flag_electricity":      "elec_e",
        "flag_hvac_energy":      "hac_e",
        "flag_supply_deviation": "supply_e",
        "flag_return_deviation": "return_e",
    }

    actual_key, unit = actual_map.get(flag_key, ("elec", "kWh"))
    expected_key = expected_map.get(flag_key, "elec_e")

    actual_val = evidence.get(actual_key)
    expected_val = evidence.get(expected_key)

    dev_pct: float | None = None
    if actual_val is not None and expected_val is not None and abs(expected_val) > _EPS:
        dev_pct = round((actual_val - expected_val) / abs(expected_val) * 100, 2)

    threshold_val: float | None = None
    if expected_val is not None:
        if flag_key == "flag_water":
            threshold_val = round(expected_val * (1 + _WATER_REL), 4)
        elif flag_key == "flag_electricity":
            threshold_val = round(expected_val * (1 + _ELEC_REL), 4)
        elif flag_key == "flag_hvac_energy":
            threshold_val = round(expected_val * (1 + _HAC_REL), 4)
        elif flag_key == "flag_supply_deviation":
            # 阈值 = expected ± 1.5℃（取实际偏离方向）
            direction = 1 if (actual_val is not None and actual_val >= expected_val) else -1
            threshold_val = round(expected_val + direction * _SUPPLY_DEV, 4)
        elif flag_key == "flag_return_deviation":
            # 阈值 = expected ± 2.0℃（取实际偏离方向）
            direction = 1 if (actual_val is not None and actual_val >= expected_val) else -1
            threshold_val = round(expected_val + direction * _RETURN_DEV, 4)

    rule_label = _RULE_MESSAGES.get(rule, rule)
    if actual_val is not None and expected_val is not None:
        msg = (
            f"{building_display} {rule_label}："
            f"实际 {actual_val:.2f} {unit}，"
            f"期望 {expected_val:.2f} {unit}"
        )
        if dev_pct is not None:
            msg += f"（偏差 {dev_pct:+.1f}%）"
    else:
        msg = f"{building_display} {rule_label}"

    symptom_flags_payload = {
        "flag_water":        flag_map.get("flag_water", False),
        "flag_electricity":  flag_map.get("flag_electricity", False),
        "flag_hvac_energy":  flag_map.get("flag_hvac_energy", False),
        "flag_supply_deviation": flag_map.get("flag_supply_deviation", False),
        "flag_return_deviation": flag_map.get("flag_return_deviation", False),
    }

    return {
        "id": str(uuid.uuid4()),
        "data_timestamp": ts,
        "building_id": building_id,
        "meter_device_id": building_id,
        "rule_triggered": rule,
        "actual_value": actual_val,
        "threshold_value": threshold_val,
        "expected_value": expected_val,
        "deviation_pct": dev_pct,
        "hvac_root_cause": hvac_diag if rule == "hvac_overconsumption" else None,
        "message": msg,
        "is_resolved": False,
        "anomaly_phase": phase,
        "symptom_flags_json": json.dumps(symptom_flags_payload),
        "event_source": "notebook",
        "severity": "warning",
    }


async def generate_anomaly_events(
    building_id: str,
    db: AsyncSession,
) -> int:
    """
    从 kpi_anomaly_flags 读取该楼有 flag 的行，
    为每个触发的 flag 生成 anomaly_events 记录（幂等 upsert）。
    返回写入行数。
    """
    # 取该楼的建筑展示名
    bld_result = await db.execute(
        select(Building.primary_space_usage)
        .where(Building.building_id == building_id)
    )
    bld_row = bld_result.fetchone()
    primary_usage = (bld_row[0] if bld_row else None) or ""
    building_display = _BUILDING_DISPLAY_NAMES.get(primary_usage, building_id)

    # 读取所有有满幅度 flag 的行（flag_symptom_union_any 包含软症状，但 anomaly_events 只写满幅度）
    flags_result = await db.execute(text("""
        SELECT
            f.timestamp,
            f.flag_water, f.flag_electricity, f.flag_hvac_energy,
            f.flag_supply_deviation, f.flag_return_deviation,
            f.anomaly_phase, f.hvac_diagnosis,
            f.evidence_json
        FROM kpi_anomaly_flags f
        WHERE f.building_id = :bid
          AND (f.flag_water OR f.flag_electricity OR f.flag_hvac_energy
               OR f.flag_supply_deviation OR f.flag_return_deviation)
        ORDER BY f.timestamp ASC
    """), {"bid": building_id})
    flag_rows = flags_result.fetchall()

    if not flag_rows:
        logger.info("generate_anomaly_events: 楼 %s 无满幅度异常 flags", building_id)
        return 0

    # 预加载对应时间戳的 expected schedule_factor
    ts_list = [r[0] for r in flag_rows]
    sched_result = await db.execute(text("""
        SELECT timestamp, schedule_factor FROM kpi_expected_hourly
        WHERE building_id = :bid AND timestamp = ANY(:ts_arr)
    """), {"bid": building_id, "ts_arr": ts_list})
    sched_map = {r[0]: r[1] for r in sched_result.fetchall()}

    event_dicts: list[dict[str, Any]] = []
    for row in flag_rows:
        (ts, fw, fe, fh, fs, fr, phase, hvac_diag, evid_json) = row

        if hasattr(ts, "tzinfo") and ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)

        if evid_json is None:
            evidence = {}
        elif isinstance(evid_json, dict):
            evidence = evid_json
        else:
            evidence = json.loads(evid_json)
        sched_f = sched_map.get(ts)

        flag_map = {
            "flag_water": fw,
            "flag_electricity": fe,
            "flag_hvac_energy": fh,
            "flag_supply_deviation": fs,
            "flag_return_deviation": fr,
        }

        # 每小时只生成一条事件，选偏差最大的规则作主规则
        _act = {"flag_water": "water", "flag_electricity": "elec",
                "flag_hvac_energy": "hac", "flag_supply_deviation": "supply",
                "flag_return_deviation": "return"}
        _exp = {"flag_water": "water_e", "flag_electricity": "elec_e",
                "flag_hvac_energy": "hac_e", "flag_supply_deviation": "supply_e",
                "flag_return_deviation": "return_e"}
        best_flag: str | None = None
        best_abs_dev = -1.0
        for flag_key, triggered in flag_map.items():
            if not triggered:
                continue
            act = evidence.get(_act.get(flag_key))
            exp = evidence.get(_exp.get(flag_key))
            abs_dev = abs((act - exp) / abs(exp)) if (
                act is not None and exp is not None and abs(exp) > _EPS
            ) else 0.0
            if best_flag is None or abs_dev > best_abs_dev:
                best_flag = flag_key
                best_abs_dev = abs_dev

        if best_flag is not None:
            rule = _FLAG_TO_RULE[best_flag]
            event_dicts.append(_build_anomaly_event(
                ts=ts,
                building_id=building_id,
                building_display=building_display,
                rule=rule,
                flag_key=best_flag,
                evidence=evidence,
                flag_map=flag_map,
                hvac_diag=hvac_diag,
                phase=phase,
                sched_f=sched_f,
            ))

    # #region agent log
    high_dev = [e for e in event_dicts if e.get("deviation_pct") is not None and abs(e["deviation_pct"]) > 500]
    for e in high_dev[:5]:
        _dbg_ad("H_HIGHDEV", f"anomaly_detection_service.py:generate_events:{building_id}", "high-deviation-event", {
            "ts": str(e.get("data_timestamp")), "rule": e.get("rule_triggered"),
            "actual": e.get("actual_value"), "expected": e.get("expected_value"),
            "deviation_pct": e.get("deviation_pct"), "threshold": e.get("threshold_value"),
            "hvac_root_cause": e.get("hvac_root_cause"),
        })
    _dbg_ad("H_EVENTS", f"anomaly_detection_service.py:generate_events:{building_id}", "events-summary", {
        "building_id": building_id, "total_events": len(event_dicts), "high_dev_events": len(high_dev),
    })
    # #endregion

    if not event_dicts:
        return 0

    await db.execute(
        text("""
            INSERT INTO anomaly_events
              (id, data_timestamp, building_id, meter_device_id,
               rule_triggered, actual_value, threshold_value, expected_value,
               deviation_pct, hvac_root_cause, message, is_resolved,
               anomaly_phase, symptom_flags_json, event_source, severity)
            VALUES
              (:id, :data_timestamp, :building_id, :meter_device_id,
               :rule_triggered, :actual_value, :threshold_value, :expected_value,
               :deviation_pct, :hvac_root_cause, :message, :is_resolved,
               :anomaly_phase, :symptom_flags_json, :event_source, :severity)
            ON CONFLICT (data_timestamp, building_id)
            DO UPDATE SET
              rule_triggered    = EXCLUDED.rule_triggered,
              actual_value      = EXCLUDED.actual_value,
              threshold_value   = EXCLUDED.threshold_value,
              expected_value    = EXCLUDED.expected_value,
              deviation_pct     = EXCLUDED.deviation_pct,
              hvac_root_cause   = EXCLUDED.hvac_root_cause,
              message           = EXCLUDED.message,
              anomaly_phase     = EXCLUDED.anomaly_phase,
              symptom_flags_json= EXCLUDED.symptom_flags_json,
              event_source      = EXCLUDED.event_source,
              severity          = EXCLUDED.severity
        """),
        event_dicts,
    )
    await db.commit()
    logger.info("generate_anomaly_events: 楼 %s 写入 %d 条事件", building_id, len(event_dicts))
    return len(event_dicts)


# ---------------------------------------------------------------------------
# 设备状态派生：从 energy_data 填充 device_telemetry_hourly + device_status_latest
# ---------------------------------------------------------------------------

# rule_triggered → 受影响的设备类型（用于归因）
_RULE_TO_DEVICE_TYPE: dict[str, str] = {
    "water_leak":            "water",
    "electricity_overload":  "electricity",
    "hvac_overconsumption":  "ac",
    "supply_temp_deviation": "ac",
    "return_temp_deviation": "ac",
}

# 设备类型 → 归因角色
_RULE_TO_ROLE: dict[str, str] = {
    "water_leak":            "primary",
    "electricity_overload":  "primary",
    "hvac_overconsumption":  "primary",
    "supply_temp_deviation": "primary",
    "return_temp_deviation": "supporting",
}


def _infer_running_state(
    hvac_mode: str | None,
    hac_energy: float | None,
    electricity_kwh: float | None,
    schedule_factor: float | None,
) -> str:
    """根据能耗和HVAC模式推断设备运行状态。"""
    s = schedule_factor or 0.0
    mode = (hvac_mode or "").lower()

    if "cooling" in mode or "heating" in mode:
        return "running"
    if s <= 0.08 and (hac_energy is None or hac_energy < 2.0):
        return "standby"
    if electricity_kwh is not None and electricity_kwh > 0:
        return "running"
    return "standby"


def _infer_health_status(
    has_anomaly: bool,
    hvac_diagnosis: str | None,
) -> str:
    """根据异常标志推断设备健康状态。"""
    if not has_anomaly:
        return "healthy"
    if hvac_diagnosis in ("A_low_efficiency", "B_small_deltaT"):
        return "degraded"
    return "warning"


async def derive_device_status(
    building_id: str,
    db: AsyncSession,
) -> tuple[int, int]:
    """
    从 energy_data + kpi_expected_hourly + kpi_anomaly_flags 派生设备状态，
    写入 device_telemetry_hourly（全量历史）和 device_status_latest（最新快照）。
    返回 (telemetry_rows, status_updated) 计数。
    """
    # 获取该楼所有设备
    dev_result = await db.execute(text(
        "SELECT device_id, device_type FROM devices WHERE building_id = :bid ORDER BY device_type"
    ), {"bid": building_id})
    devices = {row[1]: row[0] for row in dev_result.fetchall()}  # type → device_id
    if not devices:
        logger.warning("derive_device_status: 楼 %s 无设备记录", building_id)
        return 0, 0

    # 联合查询 energy_data + kpi_expected_hourly + kpi_anomaly_flags
    rows_result = await db.execute(text("""
        SELECT
            e.timestamp,
            e.electricity_kwh,
            e.water_m3,
            e.hac_energy,
            e.sim_supply_temp_c,
            e.sim_return_temp_c,
            e.air_temp_c,
            x.hvac_mode,
            x.schedule_factor,
            x.hac_energy_expected,
            COALESCE(f.flag_water, false)            AS flag_water,
            COALESCE(f.flag_electricity, false)      AS flag_electricity,
            COALESCE(f.flag_hvac_energy, false)      AS flag_hvac_energy,
            COALESCE(f.flag_supply_deviation, false) AS flag_supply_dev,
            COALESCE(f.flag_return_deviation, false) AS flag_return_dev,
            f.hvac_diagnosis,
            f.anomaly_phase
        FROM energy_data e
        LEFT JOIN kpi_expected_hourly x
            ON x.building_id = e.building_id AND x.timestamp = e.timestamp
        LEFT JOIN kpi_anomaly_flags f
            ON f.building_id = e.building_id AND f.timestamp = e.timestamp
        WHERE e.building_id = :bid
        ORDER BY e.timestamp ASC
    """), {"bid": building_id})
    rows = rows_result.fetchall()

    if not rows:
        return 0, 0

    telemetry_rows: list[dict] = []

    for row in rows:
        (ts, elec, water, hac, supply, ret, air_t,
         hvac_mode, sched_f, hac_e,
         fw, fe, fh, fs, fr, hvac_diag, phase) = row

        if hasattr(ts, "tzinfo") and ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)

        has_any_anomaly = any([fw, fe, fh, fs, fr])
        running_state = _infer_running_state(hvac_mode, hac, elec, sched_f)
        health_status = _infer_health_status(has_any_anomaly, hvac_diag)

        # 每个设备类型生成一行遥测记录
        for dev_type, device_id in devices.items():
            if dev_type == "ac":
                power_kw = float(hac) if hac is not None else None
                flow_rate = None
                supply_t = float(supply) if supply is not None else None
                return_t = float(ret) if ret is not None else None
                has_dev_anomaly = fh or fs or fr
                dev_diag = hvac_diag if (fh or fs) else None
            elif dev_type == "electricity":
                power_kw = float(elec) if elec is not None else None
                flow_rate = None
                supply_t = None
                return_t = None
                has_dev_anomaly = fe
                dev_diag = None
            elif dev_type == "water":
                power_kw = None
                flow_rate = float(water) if water is not None else None
                supply_t = None
                return_t = None
                has_dev_anomaly = fw
                dev_diag = None
            else:
                continue

            dev_running = running_state if dev_type == "ac" else (
                "running" if (power_kw is not None and power_kw > 0) or
                             (flow_rate is not None and flow_rate > 0) else "standby"
            )
            dev_health = _infer_health_status(has_dev_anomaly, dev_diag)

            payload = {
                "anomaly_phase": phase,
                "hvac_mode": hvac_mode,
                "schedule_factor": float(sched_f) if sched_f is not None else None,
                "flag_water": fw, "flag_electricity": fe,
                "flag_hvac_energy": fh,
                "flag_supply_deviation": fs, "flag_return_deviation": fr,
            }

            telemetry_rows.append({
                "device_id": device_id,
                "building_id": building_id,
                "timestamp": ts,
                "device_type": dev_type,
                "online_status": "online",
                "running_state": dev_running,
                "health_status": dev_health,
                "power_kw": power_kw,
                "flow_rate": flow_rate,
                "supply_temp_c": supply_t,
                "return_temp_c": return_t,
                "ambient_temp_c": float(air_t) if air_t is not None else None,
                "metric_payload_json": json.dumps(payload, default=str),
                "source": "energy_data_derived",
            })

    if not telemetry_rows:
        return 0, 0

    # 批量 upsert device_telemetry_hourly
    await db.execute(text("""
        INSERT INTO device_telemetry_hourly
          (device_id, building_id, timestamp, device_type,
           online_status, running_state, health_status,
           power_kw, flow_rate, supply_temp_c, return_temp_c, ambient_temp_c,
           metric_payload_json, source)
        VALUES
          (:device_id, :building_id, :timestamp, :device_type,
           :online_status, :running_state, :health_status,
           :power_kw, :flow_rate, :supply_temp_c, :return_temp_c, :ambient_temp_c,
           :metric_payload_json, :source)
        ON CONFLICT (device_id, timestamp)
        DO UPDATE SET
          running_state        = EXCLUDED.running_state,
          health_status        = EXCLUDED.health_status,
          power_kw             = EXCLUDED.power_kw,
          flow_rate            = EXCLUDED.flow_rate,
          supply_temp_c        = EXCLUDED.supply_temp_c,
          return_temp_c        = EXCLUDED.return_temp_c,
          ambient_temp_c       = EXCLUDED.ambient_temp_c,
          metric_payload_json  = EXCLUDED.metric_payload_json,
          source               = EXCLUDED.source
    """), telemetry_rows)
    await db.commit()

    # 更新 device_status_latest（每个设备取最新一行）
    latest_by_device: dict[str, dict] = {}
    for row in telemetry_rows:
        did = row["device_id"]
        if did not in latest_by_device or row["timestamp"] > latest_by_device[did]["timestamp"]:
            latest_by_device[did] = row

    status_rows = [
        {
            "device_id": r["device_id"],
            "building_id": r["building_id"],
            "device_type": r["device_type"],
            "last_seen_at": r["timestamp"],
            "online_status": r["online_status"],
            "running_state": r["running_state"],
            "health_status": r["health_status"],
            "latest_power_kw": r["power_kw"],
            "latest_flow_rate": r["flow_rate"],
            "latest_supply_temp_c": r["supply_temp_c"],
            "latest_return_temp_c": r["return_temp_c"],
            "latest_payload_json": r["metric_payload_json"],
        }
        for r in latest_by_device.values()
    ]

    await db.execute(text("""
        INSERT INTO device_status_latest
          (device_id, building_id, device_type,
           last_seen_at, online_status, running_state, health_status,
           latest_power_kw, latest_flow_rate,
           latest_supply_temp_c, latest_return_temp_c, latest_payload_json)
        VALUES
          (:device_id, :building_id, :device_type,
           :last_seen_at, :online_status, :running_state, :health_status,
           :latest_power_kw, :latest_flow_rate,
           :latest_supply_temp_c, :latest_return_temp_c, :latest_payload_json)
        ON CONFLICT (device_id)
        DO UPDATE SET
          last_seen_at         = EXCLUDED.last_seen_at,
          online_status        = EXCLUDED.online_status,
          running_state        = EXCLUDED.running_state,
          health_status        = EXCLUDED.health_status,
          latest_power_kw      = EXCLUDED.latest_power_kw,
          latest_flow_rate     = EXCLUDED.latest_flow_rate,
          latest_supply_temp_c = EXCLUDED.latest_supply_temp_c,
          latest_return_temp_c = EXCLUDED.latest_return_temp_c,
          latest_payload_json  = EXCLUDED.latest_payload_json
    """), status_rows)
    await db.commit()

    logger.info(
        "derive_device_status: 楼 %s → telemetry=%d, status_updated=%d",
        building_id, len(telemetry_rows), len(status_rows),
    )
    return len(telemetry_rows), len(status_rows)


# ---------------------------------------------------------------------------
# 异常归因：anomaly_events → anomaly_device_attributions
# ---------------------------------------------------------------------------

async def attribute_anomalies_to_devices(
    building_id: str,
    db: AsyncSession,
) -> int:
    """
    从 anomaly_events 按 rule_triggered 归因到具体设备，
    写入 anomaly_device_attributions。
    返回写入行数。
    """
    # 获取该楼所有设备（type → device_id）
    dev_result = await db.execute(text(
        "SELECT device_id, device_type FROM devices WHERE building_id = :bid"
    ), {"bid": building_id})
    devices = {row[1]: row[0] for row in dev_result.fetchall()}
    if not devices:
        return 0

    # 查该楼所有异常事件
    ev_result = await db.execute(text("""
        SELECT id, data_timestamp, rule_triggered, actual_value, expected_value,
               deviation_pct, hvac_root_cause, symptom_flags_json, anomaly_phase
        FROM anomaly_events
        WHERE building_id = :bid
        ORDER BY data_timestamp ASC
    """), {"bid": building_id})
    events = ev_result.fetchall()

    if not events:
        return 0

    attribution_rows: list[dict] = []

    for ev in events:
        (ev_id, ev_ts, rule, actual, expected, dev_pct,
         hvac_rc, sym_flags, phase) = ev

        # asyncpg 可能将 UUID 主键自动反序列化为 uuid.UUID 对象，统一转为 str
        ev_id = str(ev_id)

        if hasattr(ev_ts, "tzinfo") and ev_ts.tzinfo is None:
            ev_ts = ev_ts.replace(tzinfo=timezone.utc)

        dev_type = _RULE_TO_DEVICE_TYPE.get(rule)
        if dev_type is None or dev_type not in devices:
            continue

        device_id = devices[dev_type]
        role = _RULE_TO_ROLE.get(rule, "primary")

        # 归因得分：偏差越大得分越高（0~1 归一化，最大 200% 满分）
        score: float = 1.0
        if dev_pct is not None:
            score = min(abs(dev_pct) / 200.0, 1.0)

        # 归因原因文字
        reason_parts = [f"规则 {rule} 触发"]
        if dev_pct is not None:
            reason_parts.append(f"偏差 {dev_pct:+.1f}%")
        if hvac_rc:
            reason_parts.append(f"根因 {hvac_rc}")
        reason = "；".join(reason_parts)

        evidence = {
            "event_id": ev_id,
            "rule_triggered": rule,
            "actual_value": actual,
            "expected_value": expected,
            "deviation_pct": dev_pct,
            "hvac_root_cause": hvac_rc,
            "anomaly_phase": phase,
        }

        attribution_rows.append({
            "id": str(uuid.uuid4()),
            "building_id": building_id,
            "timestamp": ev_ts,
            "event_id": ev_id,
            "device_id": device_id,
            "device_type": dev_type,
            "attribution_role": role,
            "attribution_score": round(score, 4),
            "attribution_reason": reason,
            "evidence_json": json.dumps(evidence, default=str),
        })

    if not attribution_rows:
        return 0

    # 先删该楼旧数据（幂等重建，避免全局 TRUNCATE 时序问题）
    await db.execute(
        text("DELETE FROM anomaly_device_attributions WHERE building_id = :bid"),
        {"bid": building_id},
    )

    # 按 (event_id, device_id) 去重，避免触碰 deferrable 唯一约束
    seen: set[tuple] = set()
    deduped: list[dict] = []
    for row in attribution_rows:
        key = (row["event_id"], row["device_id"])
        if key not in seen:
            seen.add(key)
            deduped.append(row)
    attribution_rows = deduped

    await db.execute(text("""
        INSERT INTO anomaly_device_attributions
          (id, building_id, timestamp, event_id, device_id, device_type,
           attribution_role, attribution_score, attribution_reason, evidence_json)
        VALUES
          (:id, :building_id, :timestamp, :event_id, :device_id, :device_type,
           :attribution_role, :attribution_score, :attribution_reason, :evidence_json)
    """), attribution_rows)
    await db.commit()

    logger.info(
        "attribute_anomalies_to_devices: 楼 %s → 写入 %d 条归因",
        building_id, len(attribution_rows),
    )
    return len(attribution_rows)


# ---------------------------------------------------------------------------
# 批处理入口：所有楼栋
# ---------------------------------------------------------------------------
async def detect_and_store_all_buildings(db: AsyncSession) -> dict[str, dict[str, int]]:
    """
    对所有建筑运行检测，写入 kpi_anomaly_flags + anomaly_events。
    每栋楼使用独立 session 以避免长事务连接超时。
    返回 {building_id: {"flags": N, "events": M}}。
    """
    from app.db.session import AsyncSessionLocal

    async with AsyncSessionLocal() as cleanup_session:
        await cleanup_session.execute(text("TRUNCATE TABLE anomaly_events CASCADE"))
        await cleanup_session.execute(text("TRUNCATE TABLE anomaly_device_attributions"))
        await cleanup_session.execute(text("TRUNCATE TABLE device_telemetry_hourly"))
        await cleanup_session.commit()

    async with AsyncSessionLocal() as list_session:
        bld_result = await list_session.execute(
            select(Building.building_id).order_by(Building.building_id)
        )
        building_ids = [r[0] for r in bld_result.fetchall()]

    summary: dict[str, dict[str, int]] = {}
    for bid in building_ids:
        async with AsyncSessionLocal() as session:
            flag_rows = await detect_for_building(bid, session)
            n_flags = await upsert_anomaly_flags(flag_rows, session)

        async with AsyncSessionLocal() as session:
            n_events = await generate_anomaly_events(bid, session)

        # 方案A：派生设备遥测历史 + 设备状态快照
        async with AsyncSessionLocal() as session:
            n_telemetry, n_status = await derive_device_status(bid, session)

        # 方案A：异常归因到具体设备
        async with AsyncSessionLocal() as session:
            n_attrib = await attribute_anomalies_to_devices(bid, session)

        # 自动建工单：异常事件 → 工单 → AI 审批
        n_wo_created = 0
        wo_error: str | None = None
        if n_events > 0:
            try:
                from app.services.auto_work_order_service import auto_create_alert_orders
                async with AsyncSessionLocal() as session:
                    wo_result = await auto_create_alert_orders(session, bid)
                    n_wo_created = wo_result.get("created", 0)
                    logger.info(
                        "自动建工单结果: building=%s created=%d skipped=%d",
                        bid, n_wo_created, wo_result.get("skipped_dup", 0),
                    )
            except Exception as _wo_exc:
                import traceback as _tb
                wo_error = f"{_wo_exc}\n{_tb.format_exc()}"
                logger.error("自动建工单失败: building=%s error=%s", bid, wo_error)

        summary[bid] = {
            "flags": n_flags,
            "events": n_events,
            "telemetry": n_telemetry,
            "device_status": n_status,
            "attributions": n_attrib,
            "work_orders_created": n_wo_created,
            "wo_error": wo_error,
        }
        logger.info(
            "anomaly detect: %s → flags=%d, events=%d, telemetry=%d, status=%d, attrib=%d, wo=%d",
            bid, n_flags, n_events, n_telemetry, n_status, n_attrib, n_wo_created,
        )

    # 批量触发 AI 审批（所有 pending_review 工单）
    try:
        from app.services.auto_work_order_service import trigger_ai_review_for_pending
        async with AsyncSessionLocal() as session:
            n_reviewed = await trigger_ai_review_for_pending(session)
        logger.info("AI 审批批量完成: reviewed=%d", n_reviewed)
    except Exception:
        logger.exception("AI 审批批量触发失败")

    return summary
