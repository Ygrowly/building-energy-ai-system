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

# 软症状：阈值 × 0.5（50% 灵敏度，用于 ramp 阶段）
_SOFT_FACTOR = 0.5

# 空调根因判定参数
_SMALL_DELTA_T_THRESHOLD = 3.0   # (return - supply) < 3 ℃ → 小温差
_UNEXPECTED_ON_SCHEDULE_MAX = 0.12  # S ≤ 0.12 时视为非营业
_UNEXPECTED_ON_HAC_MARGIN = 5.0     # 实际 hac > expected + 5 kWh


# ---------------------------------------------------------------------------
# 内部辅助
# ---------------------------------------------------------------------------
def _diagnose_hvac(
    *,
    hvac_mode: str | None,
    supply: float | None,
    ret: float | None,
    supply_e: float | None,
    hac_actual: float | None,
    hac_expected: float | None,
    schedule_factor: float | None,
) -> str:
    """
    第二层 HVAC 根因诊断（仅当 flag_hvac_energy 为 True 时调用）。
    优先级：A > B > C > other
    """
    s = schedule_factor or 0.5
    mode = (hvac_mode or "").lower()
    is_cooling = "cool" in mode

    # A: 制冷 + 供水偏离
    if is_cooling and supply is not None and supply_e is not None:
        if abs(supply - supply_e) > _SUPPLY_DEV:
            return "A_low_efficiency"

    # B: 制冷 + 小温差
    if is_cooling and supply is not None and ret is not None:
        if (ret - supply) < _SMALL_DELTA_T_THRESHOLD:
            return "B_small_deltaT"

    # C: 非营业时段但空调能耗异常高
    if s <= _UNEXPECTED_ON_SCHEDULE_MAX:
        hac_e = hac_expected or 0.0
        hac_a = hac_actual or 0.0
        if hac_a > hac_e + _UNEXPECTED_ON_HAC_MARGIN:
            return "C_unexpected_on"

    return "other_hvac"


def _is_hvac_actually_off(
    *,
    hvac_mode: str | None,
    hac: float | None,
    hac_e: float | None,
) -> bool:
    """Determine whether HVAC is effectively off for temperature checks.

    Returns True in two scenarios:
    1. Expected mode is "Ventilation" (expected service computed hvac_on=False).
    2. Expected mode is Cooling/Heating but actual hac_energy is near zero
       while expected is significant — the actual data was generated with
       HVAC off despite the expected calculation saying ON (state machine
       divergence due to noise).
    """
    mode = (hvac_mode or "").lower()
    if "ventilation" in mode:
        return True
    if ("cool" in mode or "heat" in mode):
        actual_hac = hac if hac is not None else 0.0
        expected_hac = hac_e if hac_e is not None else 0.0
        if expected_hac > 5.0 and actual_hac < expected_hac * 0.1:
            return True
    return False


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
    hvac_mode: str | None,
    schedule_factor: float | None,
    soft: bool = False,
) -> dict[str, Any]:
    """
    计算单行的所有症状 flags。
    soft=True 时使用 50% 阈值（软症状）。
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
        # 动态绝对阈值：0.10 × max(e_e - h_e, 1)
        base_load = max((elec_e or 0.0) - (hac_e or 0.0), 1.0)
        abs_e = 0.10 * base_load * factor
        fe = rel_e > _ELEC_REL * factor and delta_e > abs_e

    # flag_hvac_energy
    fh = False
    if hac is not None and hac_e is not None and hac_e > eps:
        delta_h = hac - hac_e
        rel_h = delta_h / max(hac_e, eps)
        fh = rel_h > _HAC_REL * factor and delta_h >= _HAC_ABS * factor

    # flag_supply_deviation — skip when HVAC is actually off
    fs = False
    hvac_actually_off = _is_hvac_actually_off(
        hvac_mode=hvac_mode, hac=hac, hac_e=hac_e,
    )
    # #region agent log
    if supply is not None and supply_e is not None and abs(supply - supply_e) > _SUPPLY_DEV * factor:
        _dbg_ad("H_HVAC_OFF", "anomaly_detection_service.py:_detect_flags", "supply-dev-check", {
            "hvac_mode": hvac_mode, "hac": float(hac) if hac is not None else None,
            "hac_e": float(hac_e) if hac_e is not None else None,
            "hvac_actually_off": hvac_actually_off,
            "supply": float(supply), "supply_e": float(supply_e),
            "soft": soft,
        })
    # #endregion
    if not hvac_actually_off and supply is not None and supply_e is not None:
        fs = abs(supply - supply_e) > _SUPPLY_DEV * factor

    # flag_return_deviation — skip when HVAC is actually off
    fr = False
    if not hvac_actually_off and ret is not None and return_e is not None:
        fr = abs(ret - return_e) > _RETURN_DEV * factor

    # HVAC 根因（仅满幅度时诊断）
    hvac_diag: str | None = None
    if fh and not soft:
        hvac_diag = _diagnose_hvac(
            hvac_mode=hvac_mode,
            supply=supply,
            ret=ret,
            supply_e=supply_e,
            hac_actual=hac,
            hac_expected=hac_e,
            schedule_factor=schedule_factor,
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
            hvac_mode=hvac_mode,
            schedule_factor=sched_f,
            soft=False,
        )

        # 软症状 flags（50% 灵敏度）
        soft = _detect_flags(
            water=water, water_e=water_e,
            elec=elec, elec_e=elec_e,
            hac=hac, hac_e=hac_e,
            supply=supply, supply_e=supply_e,
            ret=ret, return_e=return_e,
            hvac_mode=hvac_mode,
            schedule_factor=sched_f,
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

        for flag_key, triggered in flag_map.items():
            if not triggered:
                continue
            rule = _FLAG_TO_RULE[flag_key]
            event_dicts.append(_build_anomaly_event(
                ts=ts,
                building_id=building_id,
                building_display=building_display,
                rule=rule,
                flag_key=flag_key,
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
            ON CONFLICT (data_timestamp, building_id, rule_triggered)
            DO UPDATE SET
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
        await cleanup_session.execute(text("TRUNCATE TABLE anomaly_events"))
        await cleanup_session.commit()

    bld_result = await db.execute(
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

        summary[bid] = {"flags": n_flags, "events": n_events}
        logger.info("anomaly detect: %s → flags=%d, events=%d", bid, n_flags, n_events)

    return summary
