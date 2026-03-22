"""
管理员后台接口（导入 & 重算）
==============================
端点：
  POST /api/admin/import/kpi-baseline      — 导入 notebook 期望值 CSV
  POST /api/admin/import/device-telemetry  — 导入设备遥测 CSV（或生成演示数据）
  POST /api/admin/rebuild/anomaly-flags    — 对已有 energy_data+expected 重跑检测
  POST /api/admin/rebuild/anomaly-events   — 从 kpi_anomaly_flags 汇总写 anomaly_events
  POST /api/admin/rebuild/device-status    — 从 device_telemetry_hourly 刷新 device_status_latest

所有接口均需 admin 角色 JWT。
"""
from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone, timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Query
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import get_current_user
from app.db.models import User  # noqa: F401 — others accessed via raw SQL
from app.db.session import get_db_session
from app.services.building_anomaly_detection import (
    DetectionThresholds,
    assign_anomaly_phase,
    attribute_anomaly_to_devices,
    detect_single_hour,
)
from app.services.kpi_importer import (
    bulk_upsert_anomaly_flags,
    bulk_upsert_energy_data,
    bulk_upsert_expected_hourly,
    parse_baseline_csv,
    parse_flags_csv,
    parse_simulated_kpi_csv,
)

logger = logging.getLogger(__name__)
router = APIRouter(tags=["管理员"])


# ---------------------------------------------------------------------------
# 鉴权：要求 admin 角色
# ---------------------------------------------------------------------------

async def require_admin(current_user: User = Depends(get_current_user)) -> User:
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="需要 admin 权限")
    return current_user


# ---------------------------------------------------------------------------
# 1. 导入 notebook KPI 基线 CSV
# ---------------------------------------------------------------------------

@router.post("/admin/import/kpi-baseline", summary="导入 notebook 期望值 CSV")
async def import_kpi_baseline(
    file: UploadFile = File(..., description="kpi_baseline_for_detection.csv 或含 *_nominal 列的仿真 CSV"),
    source_version: str = Query("notebook_v1", description="基线版本标签"),
    also_import_energy: bool = Query(True, description="同时将实际值列导入 energy_data"),
    db: AsyncSession = Depends(get_db_session),
    _: User = Depends(require_admin),
):
    """
    将 notebook 产出的 CSV 文件导入数据库：
    - 含 *_nominal 列 → kpi_expected_hourly
    - 含实际值列（electricity_kwh / water_l 等）→ energy_data（若 also_import_energy=True）
    """
    import tempfile, os
    content = await file.read()
    with tempfile.NamedTemporaryFile(delete=False, suffix=".csv") as tmp:
        tmp.write(content)
        tmp_path = tmp.name

    try:
        energy_rows, expected_rows = parse_simulated_kpi_csv(tmp_path)
        # 若不含 nominal 列则尝试作为基线 CSV
        if not expected_rows:
            expected_rows = parse_baseline_csv(tmp_path, source_version=source_version)

        written_energy = 0
        if also_import_energy and energy_rows:
            written_energy = await bulk_upsert_energy_data(db, energy_rows)
        written_expected = await bulk_upsert_expected_hourly(db, expected_rows)

        return {
            "status": "ok",
            "energy_data_rows": written_energy,
            "kpi_expected_rows": written_expected,
            "source_version": source_version,
        }
    finally:
        os.unlink(tmp_path)


# ---------------------------------------------------------------------------
# 2. 导入设备遥测 CSV（或生成演示数据）
# ---------------------------------------------------------------------------

@router.post("/admin/import/device-telemetry", summary="导入或生成设备遥测数据")
async def import_device_telemetry(
    generate_demo: bool = Query(False, description="若为 True 则忽略文件，按已有 energy_data 自动生成演示遥测"),
    file: UploadFile | None = File(None, description="设备遥测 CSV（含 device_id, timestamp, running_state 等列）"),
    db: AsyncSession = Depends(get_db_session),
    _: User = Depends(require_admin),
):
    """
    支持两种模式：
    1. 上传真实设备遥测 CSV。
    2. generate_demo=True：从 energy_data + devices 自动派生演示遥测写入 device_telemetry_hourly，
       同时更新 device_status_latest。
    """
    if generate_demo:
        count = await _generate_demo_telemetry(db)
        return {"status": "ok", "mode": "demo_generated", "rows_written": count}

    if file is None:
        raise HTTPException(status_code=400, detail="未上传文件且 generate_demo=False")

    import tempfile, os, csv
    content = await file.read()
    with tempfile.NamedTemporaryFile(delete=False, suffix=".csv") as tmp:
        tmp.write(content)
        tmp_path = tmp.name

    try:
        from app.services.kpi_importer import parse_timestamp_utc, _safe_float, _safe_bool
        rows: list[dict] = []
        with open(tmp_path, encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            for row in reader:
                try:
                    ts = parse_timestamp_utc(row.get("timestamp", ""))
                except ValueError:
                    continue
                did = str(row.get("device_id", "")).strip()
                bid = str(row.get("building_id", "")).strip()
                dtype = str(row.get("device_type", "")).strip()
                if not did or not bid:
                    continue
                rows.append({
                    "device_id": did,
                    "building_id": bid,
                    "timestamp": ts,
                    "device_type": dtype or "unknown",
                    "online_status": row.get("online_status"),
                    "running_state": row.get("running_state"),
                    "health_status": row.get("health_status"),
                    "power_kw": _safe_float(row.get("power_kw")),
                    "flow_rate": _safe_float(row.get("flow_rate")),
                    "supply_temp_c": _safe_float(row.get("supply_temp_c")),
                    "return_temp_c": _safe_float(row.get("return_temp_c")),
                    "source": "imported",
                })

        written = await _bulk_upsert_telemetry(db, rows)
        await _refresh_device_status_latest(db)
        return {"status": "ok", "rows_written": written}
    finally:
        os.unlink(tmp_path)


# ---------------------------------------------------------------------------
# 3. 重算楼级异常检测 flags
# ---------------------------------------------------------------------------

@router.post("/admin/rebuild/anomaly-flags", summary="重算楼级 KPI 异常 flags")
async def rebuild_anomaly_flags(
    start_date: str = Query(..., description="开始日期 YYYY-MM-DD"),
    end_date: str = Query(..., description="结束日期 YYYY-MM-DD"),
    building_id: str | None = Query(None, description="指定楼宇（空则全部）"),
    source_version: str = Query("notebook_v1"),
    db: AsyncSession = Depends(get_db_session),
    _: User = Depends(require_admin),
):
    """
    对 [start_date, end_date] 内已有的 energy_data + kpi_expected_hourly，
    用 building_anomaly_detection 重跑检测并 upsert 到 kpi_anomaly_flags。
    """
    try:
        t0 = datetime.fromisoformat(start_date).replace(tzinfo=timezone.utc)
        t1 = datetime.fromisoformat(end_date).replace(tzinfo=timezone.utc) + timedelta(days=1)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"日期格式错误：{e}")

    # 查 energy_data + expected（LEFT JOIN）
    q = text("""
        SELECT
            e.building_id, e.timestamp,
            e.electricity_kwh, e.water_m3, e.hac_energy,
            e.sim_supply_temp_c, e.sim_return_temp_c,
            x.water_m3_expected, x.electricity_kwh_expected, x.hac_energy_expected,
            x.sim_supply_temp_c_expected, x.sim_return_temp_c_expected,
            x.schedule_factor, x.hvac_mode
        FROM energy_data e
        LEFT JOIN kpi_expected_hourly x
            ON x.building_id = e.building_id AND x.timestamp = e.timestamp
        WHERE e.timestamp >= :t0 AND e.timestamp < :t1
        """ + ("AND e.building_id = :bid" if building_id else "") + """
        ORDER BY e.building_id, e.timestamp
    """)
    params: dict = {"t0": t0, "t1": t1}
    if building_id:
        params["bid"] = building_id

    result = await db.execute(q, params)
    rows = result.fetchall()
    if not rows:
        return {"status": "ok", "flags_written": 0, "message": "该时间段无数据"}

    thr = DetectionThresholds()
    flags_by_building: dict[str, list] = {}
    flags_rows: list[dict] = []

    for row in rows:
        (bid, ts, elec, water, hac, supply, ret,
         w_exp, e_exp, h_exp, s_exp, r_exp, S, hvac_mode) = row
        ts_iso = ts.isoformat() if hasattr(ts, "isoformat") else str(ts)
        actual = {
            "electricity_kwh": elec, "water_m3": water, "hac_energy": hac,
            "sim_supply_temp_c": supply, "sim_return_temp_c": ret,
        }
        expected = {
            "water_m3_expected": w_exp, "electricity_kwh_expected": e_exp,
            "hac_energy_expected": h_exp, "sim_supply_temp_c_expected": s_exp,
            "sim_return_temp_c_expected": r_exp,
        }
        flag = detect_single_hour(
            bid, ts_iso, actual, expected,
            schedule_factor=S or 1.0, thresholds=thr,
            source_version=source_version,
        )
        flags_by_building.setdefault(bid, []).append(flag)

    # 阶段推断 + 转 DB dict
    for bid, flist in flags_by_building.items():
        flist = assign_anomaly_phase(flist)
        flags_rows.extend(f.to_db_dict() for f in flist)

    written = await bulk_upsert_anomaly_flags(db, flags_rows)
    return {"status": "ok", "flags_written": written, "buildings": len(flags_by_building)}


# ---------------------------------------------------------------------------
# 4. 从 kpi_anomaly_flags 重建 anomaly_events
# ---------------------------------------------------------------------------

@router.post("/admin/rebuild/anomaly-events", summary="从 kpi_anomaly_flags 重建 anomaly_events")
async def rebuild_anomaly_events(
    start_date: str = Query(..., description="开始日期 YYYY-MM-DD"),
    end_date: str = Query(..., description="结束日期 YYYY-MM-DD"),
    min_severity: str = Query("union", description="union=任意症状触发 | strict=仅满幅度"),
    db: AsyncSession = Depends(get_db_session),
    _: User = Depends(require_admin),
):
    """
    读取 kpi_anomaly_flags 中的触发行，生成汇总 anomaly_events 记录。
    已有事件通过 (data_timestamp, building_id, rule_triggered) ON CONFLICT DO NOTHING 保持幂等。
    """
    try:
        t0 = datetime.fromisoformat(start_date).replace(tzinfo=timezone.utc)
        t1 = datetime.fromisoformat(end_date).replace(tzinfo=timezone.utc) + timedelta(days=1)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    col_filter = "flag_symptom_union_any = TRUE" if min_severity == "union" else (
        "(flag_water OR flag_electricity OR flag_hvac_energy "
        "OR flag_supply_deviation OR flag_return_deviation)"
    )

    rows = (await db.execute(text(f"""
        SELECT f.building_id, f.timestamp,
               f.flag_water, f.flag_electricity, f.flag_hvac_energy,
               f.flag_supply_deviation, f.flag_return_deviation,
               f.hvac_diagnosis, f.anomaly_phase, f.evidence_json,
               b.primary_space_usage,
               x.electricity_kwh_expected, x.water_m3_expected, x.hac_energy_expected
        FROM kpi_anomaly_flags f
        JOIN buildings b ON b.building_id = f.building_id
        LEFT JOIN kpi_expected_hourly x ON x.building_id = f.building_id AND x.timestamp = f.timestamp
        LEFT JOIN energy_data e ON e.building_id = f.building_id AND e.timestamp = f.timestamp
        WHERE f.timestamp >= :t0 AND f.timestamp < :t1 AND {col_filter}
        ORDER BY f.building_id, f.timestamp
    """), {"t0": t0, "t1": t1})).fetchall()

    if not rows:
        return {"status": "ok", "events_written": 0}

    now = datetime.now(timezone.utc)
    to_insert: list[dict] = []

    _FLAG_RULE_MAP = {
        "flag_water": "flag_water",
        "flag_electricity": "flag_electricity",
        "flag_hvac_energy": "flag_hvac_energy",
        "flag_supply_deviation": "flag_supply_deviation",
        "flag_return_deviation": "flag_return_deviation",
    }
    _RULE_MSG = {
        "flag_water": "水耗偏高",
        "flag_electricity": "总电耗偏高",
        "flag_hvac_energy": "空调能耗偏高",
        "flag_supply_deviation": "供水温度偏离",
        "flag_return_deviation": "回水温度偏离",
    }
    _DIAG_MSG = {
        "A_low_efficiency": "主机效能衰退（供水温度无法达到设定点）",
        "B_small_deltaT": "水力失调（大流量小温差，疑似旁通阀故障）",
        "C_unexpected_on": "非预期开机（排程失效，设备应关闭）",
        "other_hvac": "空调能耗异常（原因待进一步排查）",
    }

    for row in rows:
        (bid, ts, fw, fe, fh, fs, fr,
         diag, phase, evid_json, psu, e_exp, w_exp, h_exp) = row

        active_flags = {
            k for k, v in {
                "flag_water": fw, "flag_electricity": fe, "flag_hvac_energy": fh,
                "flag_supply_deviation": fs, "flag_return_deviation": fr,
            }.items() if v
        }
        if not active_flags:
            continue

        meter_id = bid + "_elec"
        evid: dict[str, Any] = json.loads(evid_json) if evid_json else {}

        for flag_key in active_flags:
            rule = _FLAG_RULE_MAP[flag_key]
            msg_parts = [_RULE_MSG[flag_key]]
            if diag and flag_key == "flag_hvac_energy":
                msg_parts.append(_DIAG_MSG.get(diag, diag))

            actual_val = evid.get(
                {"flag_water": "water_delta_m3", "flag_electricity": "elec_delta_kwh",
                 "flag_hvac_energy": "hac_delta_kwh"}.get(flag_key, ""),
                None,
            )
            exp_val = {
                "flag_water": w_exp, "flag_electricity": e_exp, "flag_hvac_energy": h_exp,
            }.get(flag_key)
            dev_pct = evid.get(
                {"flag_water": "water_rel_pct", "flag_electricity": "elec_rel_pct",
                 "flag_hvac_energy": "hac_rel_pct"}.get(flag_key, ""),
                None,
            )

            to_insert.append({
                "id": str(uuid.uuid4()),
                "detected_at": now,
                "data_timestamp": ts,
                "building_id": bid,
                "meter_device_id": meter_id,
                "rule_triggered": rule,
                "actual_value": actual_val,
                "threshold_value": None,
                "expected_value": exp_val,
                "deviation_pct": dev_pct,
                "hvac_root_cause": diag if flag_key == "flag_hvac_energy" else None,
                "message": psu + " " + "；".join(msg_parts),
                "is_resolved": False,
                "anomaly_phase": phase,
                "symptom_flags_json": json.dumps(list(active_flags)),
                "event_source": "notebook",
                "severity": "critical" if phase == "full" else "warning",
            })

    if not to_insert:
        return {"status": "ok", "events_written": 0}

    # 批量幂等写入
    try:
        await db.execute(text("""
            INSERT INTO anomaly_events
                (id, detected_at, data_timestamp, building_id, meter_device_id,
                 rule_triggered, actual_value, threshold_value, expected_value,
                 deviation_pct, hvac_root_cause, message, is_resolved,
                 anomaly_phase, symptom_flags_json, event_source, severity)
            VALUES
                (:id, :detected_at, :data_timestamp, :building_id, :meter_device_id,
                 :rule_triggered, :actual_value, :threshold_value, :expected_value,
                 :deviation_pct, :hvac_root_cause, :message, :is_resolved,
                 :anomaly_phase, :symptom_flags_json, :event_source, :severity)
            ON CONFLICT (data_timestamp, building_id, rule_triggered) DO NOTHING
        """), to_insert)
        await db.commit()
    except Exception as exc:
        await db.rollback()
        logger.error("rebuild_anomaly_events 写入失败: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))

    return {"status": "ok", "events_written": len(to_insert)}


# ---------------------------------------------------------------------------
# 5. 刷新 device_status_latest
# ---------------------------------------------------------------------------

@router.post("/admin/rebuild/device-status", summary="从遥测历史刷新设备最新状态快照")
async def rebuild_device_status(
    db: AsyncSession = Depends(get_db_session),
    _: User = Depends(require_admin),
):
    """从 device_telemetry_hourly 聚合每台设备最新状态，写入 device_status_latest。"""
    await _refresh_device_status_latest(db)
    count = (await db.execute(text("SELECT COUNT(*) FROM device_status_latest"))).scalar()
    return {"status": "ok", "device_count": count}


# ---------------------------------------------------------------------------
# 内部辅助函数
# ---------------------------------------------------------------------------

async def _bulk_upsert_telemetry(session, rows: list[dict], batch_size: int = 500) -> int:
    from sqlalchemy import text as stext
    if not rows:
        return 0
    _upsert = """
    INSERT INTO device_telemetry_hourly
        (device_id, building_id, timestamp, device_type,
         online_status, running_state, health_status,
         power_kw, flow_rate, supply_temp_c, return_temp_c, source)
    VALUES
        (:device_id, :building_id, :timestamp, :device_type,
         :online_status, :running_state, :health_status,
         :power_kw, :flow_rate, :supply_temp_c, :return_temp_c, :source)
    ON CONFLICT (device_id, timestamp) DO UPDATE SET
        running_state = EXCLUDED.running_state,
        health_status = EXCLUDED.health_status,
        power_kw      = EXCLUDED.power_kw,
        flow_rate     = EXCLUDED.flow_rate,
        supply_temp_c = EXCLUDED.supply_temp_c,
        return_temp_c = EXCLUDED.return_temp_c
    """
    count = 0
    defaults = {
        "online_status": None, "running_state": None, "health_status": None,
        "power_kw": None, "flow_rate": None, "supply_temp_c": None, "return_temp_c": None,
        "source": "imported",
    }
    for i in range(0, len(rows), batch_size):
        batch = [{**defaults, **r} for r in rows[i: i + batch_size]]
        try:
            await session.execute(stext(_upsert), batch)
            await session.commit()
            count += len(batch)
        except Exception as exc:
            await session.rollback()
            logger.error("device_telemetry_hourly 写入失败: %s", exc)
    return count


async def _generate_demo_telemetry(session) -> int:
    """
    从 energy_data + devices 自动生成演示设备遥测。
    每台设备的遥测从其所属楼的同时刻 energy_data 派生。
    """
    rows_result = await session.execute(text("""
        SELECT d.device_id, d.building_id, d.device_type,
               e.timestamp, e.electricity_kwh, e.water_m3, e.hac_energy,
               e.sim_supply_temp_c, e.sim_return_temp_c, e.air_temp_c
        FROM devices d
        JOIN energy_data e ON e.building_id = d.building_id
        WHERE e.timestamp >= (
            SELECT MAX(timestamp) - INTERVAL '7 days' FROM energy_data
        )
        ORDER BY d.device_id, e.timestamp
    """))
    rows = rows_result.fetchall()
    if not rows:
        return 0

    telemetry: list[dict] = []
    for did, bid, dtype, ts, elec, water, hac, supply, ret, air in rows:
        ts_iso = ts.isoformat() if hasattr(ts, "isoformat") else str(ts)
        state = "running" if (elec or 0) > 5 else "standby"
        health = "normal"
        power = None
        flow = None
        sup = supply
        ret_t = ret
        if dtype == "ElectricityMeter":
            power = float(elec or 0)
        elif dtype == "WaterMeter":
            flow = float(water or 0) * 1000 / 3600  # m3/h → L/s
        elif dtype in ("HVAC", "Chiller", "Pump", "AHU"):
            power = float(hac or 0)
            if sup and ret_t and abs((ret_t or 0) - (sup or 0)) < 1.5:
                health = "warning"
        telemetry.append({
            "device_id": did, "building_id": bid,
            "timestamp": ts_iso, "device_type": dtype,
            "online_status": "online", "running_state": state, "health_status": health,
            "power_kw": power, "flow_rate": flow,
            "supply_temp_c": sup, "return_temp_c": ret_t,
            "source": "simulated",
        })

    written = await _bulk_upsert_telemetry(session, telemetry)
    await _refresh_device_status_latest(session)
    return written


async def _refresh_device_status_latest(session) -> None:
    """从 device_telemetry_hourly 聚合最新状态，upsert device_status_latest。"""
    await session.execute(text("""
        INSERT INTO device_status_latest
            (device_id, building_id, device_type, last_seen_at,
             online_status, running_state, health_status,
             latest_power_kw, latest_flow_rate,
             latest_supply_temp_c, latest_return_temp_c, updated_at)
        SELECT DISTINCT ON (t.device_id)
            t.device_id, t.building_id, t.device_type, t.timestamp,
            t.online_status, t.running_state, t.health_status,
            t.power_kw, t.flow_rate,
            t.supply_temp_c, t.return_temp_c,
            NOW()
        FROM device_telemetry_hourly t
        ORDER BY t.device_id, t.timestamp DESC
        ON CONFLICT (device_id) DO UPDATE SET
            last_seen_at    = EXCLUDED.last_seen_at,
            online_status   = EXCLUDED.online_status,
            running_state   = EXCLUDED.running_state,
            health_status   = EXCLUDED.health_status,
            latest_power_kw = EXCLUDED.latest_power_kw,
            latest_flow_rate = EXCLUDED.latest_flow_rate,
            latest_supply_temp_c = EXCLUDED.latest_supply_temp_c,
            latest_return_temp_c = EXCLUDED.latest_return_temp_c,
            updated_at      = NOW()
    """))
    await session.commit()
