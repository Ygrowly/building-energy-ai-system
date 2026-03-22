"""
设备状态查询接口
================
端点：
  GET /api/devices                                  — 设备列表（支持筛选）
  GET /api/devices/{device_id}/status               — 设备当前状态
  GET /api/devices/{device_id}/telemetry            — 设备历史遥测趋势
  GET /api/devices/{device_id}/anomalies            — 设备关联异常时间线
  GET /api/buildings/{building_id}/device-attributions — 楼宇最近异常归因设备
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession


from app.db.models import (
    AnomalyDeviceAttribution,
    Building,
    Device,
    DeviceStatusLatest,
    DeviceTelemetryHourly,
)
from app.db.session import get_db_session

logger = logging.getLogger(__name__)
router = APIRouter(tags=["设备"])

_HEALTH_PRIORITY = {"critical": 0, "warning": 1, "normal": 2, None: 3}


# ---------------------------------------------------------------------------
# 1. 设备列表
# ---------------------------------------------------------------------------

@router.get("/devices", summary="获取设备列表")
async def list_devices(
    building_id: str | None = Query(None, description="按楼宇筛选"),
    device_type: str | None = Query(None, description="按设备类型筛选"),
    online_status: str | None = Query(None, description="online | offline | unknown"),
    running_state: str | None = Query(None, description="running | standby | fault | off"),
    health_status: str | None = Query(None, description="normal | warning | critical"),
    keyword: str | None = Query(None, description="模糊搜索 device_id"),
    limit: int = Query(100, ge=1, le=500),
    db: AsyncSession = Depends(get_db_session),
):
    """返回设备列表，支持多条件筛选。若设备无状态记录则仍从 devices 表返回基础信息。"""
    # 主查询：devices LEFT JOIN device_status_latest
    q = text("""
        SELECT
            d.device_id, d.building_id, d.device_type,
            s.last_seen_at, s.online_status, s.running_state, s.health_status,
            s.latest_power_kw, s.latest_flow_rate,
            s.latest_supply_temp_c, s.latest_return_temp_c,
            b.primary_space_usage
        FROM devices d
        LEFT JOIN device_status_latest s ON s.device_id = d.device_id
        LEFT JOIN buildings b ON b.building_id = d.building_id
        WHERE 1=1
        """ + ("AND d.building_id = :bid " if building_id else "")
          + ("AND d.device_type = :dtype " if device_type else "")
          + ("AND s.online_status = :online " if online_status else "")
          + ("AND s.running_state = :rstate " if running_state else "")
          + ("AND s.health_status = :health " if health_status else "")
          + ("AND d.device_id ILIKE :kw " if keyword else "")
          + "ORDER BY d.building_id, d.device_type, d.device_id "
          + "LIMIT :lim"
    )
    params: dict = {"lim": limit}
    if building_id:
        params["bid"] = building_id
    if device_type:
        params["dtype"] = device_type
    if online_status:
        params["online"] = online_status
    if running_state:
        params["rstate"] = running_state
    if health_status:
        params["health"] = health_status
    if keyword:
        params["kw"] = f"%{keyword}%"

    rows = (await db.execute(q, params)).fetchall()

    _BUILDING_NAMES = {
        "Education": "教学楼",
        "Office": "办公楼",
        "Public services": "公共楼",
        "Public": "公共楼",
    }
    _DEVICE_TYPE_NAMES = {
        "ElectricityMeter": "电表",
        "WaterMeter": "水表",
        "HVAC": "空调系统",
        "Chiller": "冷机",
        "Pump": "水泵",
        "AHU": "新风机组",
        "Valve": "阀门",
        "EnvSensor": "环境传感器",
    }

    result = []
    for (did, bid, dtype, last_seen, online, rstate, health,
         pwr, flow, sup, ret, psu) in rows:
        result.append({
            "device_id": did,
            "building_id": bid,
            "building_name": _BUILDING_NAMES.get(psu or "", psu or bid),
            "device_type": dtype,
            "device_type_name": _DEVICE_TYPE_NAMES.get(dtype, dtype),
            "last_seen_at": last_seen.isoformat() if last_seen else None,
            "online_status": online or "unknown",
            "running_state": rstate or "unknown",
            "health_status": health or "unknown",
            "latest_power_kw": pwr,
            "latest_flow_rate": flow,
            "latest_supply_temp_c": sup,
            "latest_return_temp_c": ret,
        })

    # 按健康状态排序：critical > warning > normal > unknown
    result.sort(key=lambda x: _HEALTH_PRIORITY.get(x["health_status"], 3))
    return {"devices": result, "total": len(result)}


# ---------------------------------------------------------------------------
# 2. 设备当前状态
# ---------------------------------------------------------------------------

@router.get("/devices/{device_id}/status", summary="设备当前状态")
async def get_device_status(
    device_id: str,
    db: AsyncSession = Depends(get_db_session),
):
    """返回设备最新状态快照，包含最近异常摘要。"""
    dev_row = (await db.execute(
        select(Device).where(Device.device_id == device_id)
    )).scalar_one_or_none()
    if not dev_row:
        raise HTTPException(status_code=404, detail=f"设备 {device_id} 不存在")

    status_row = (await db.execute(
        select(DeviceStatusLatest).where(DeviceStatusLatest.device_id == device_id)
    )).scalar_one_or_none()

    # 最近归因异常
    recent_attr = (await db.execute(text("""
        SELECT a.timestamp, a.attribution_role, a.attribution_reason, a.attribution_score,
               ae.rule_triggered, ae.message
        FROM anomaly_device_attributions a
        LEFT JOIN anomaly_events ae ON ae.id = a.event_id
        WHERE a.device_id = :did
        ORDER BY a.timestamp DESC
        LIMIT 5
    """), {"did": device_id})).fetchall()

    return {
        "device_id": device_id,
        "building_id": dev_row.building_id,
        "device_type": dev_row.device_type,
        "last_seen_at": status_row.last_seen_at.isoformat() if status_row and status_row.last_seen_at else None,
        "online_status": status_row.online_status if status_row else "unknown",
        "running_state": status_row.running_state if status_row else "unknown",
        "health_status": status_row.health_status if status_row else "unknown",
        "latest_power_kw": status_row.latest_power_kw if status_row else None,
        "latest_flow_rate": status_row.latest_flow_rate if status_row else None,
        "latest_supply_temp_c": status_row.latest_supply_temp_c if status_row else None,
        "latest_return_temp_c": status_row.latest_return_temp_c if status_row else None,
        "recent_anomalies": [
            {
                "timestamp": r[0].isoformat() if r[0] else None,
                "attribution_role": r[1],
                "attribution_reason": r[2],
                "score": r[3],
                "rule": r[4],
                "message": r[5],
            }
            for r in recent_attr
        ],
    }


# ---------------------------------------------------------------------------
# 3. 设备历史遥测趋势
# ---------------------------------------------------------------------------

@router.get("/devices/{device_id}/telemetry", summary="设备历史遥测趋势")
async def get_device_telemetry(
    device_id: str,
    start_time: str = Query(..., description="开始时间 YYYY-MM-DDTHH:MM 或 YYYY-MM-DD"),
    end_time: str = Query(..., description="结束时间"),
    metrics: str = Query(
        "power_kw,supply_temp_c,return_temp_c",
        description="逗号分隔的指标名，可选：power_kw,flow_rate,supply_temp_c,return_temp_c,valve_open_pct",
    ),
    db: AsyncSession = Depends(get_db_session),
):
    """返回设备历史状态趋势，供前端折线图使用。"""
    dev_row = (await db.execute(
        select(Device).where(Device.device_id == device_id)
    )).scalar_one_or_none()
    if not dev_row:
        raise HTTPException(status_code=404, detail=f"设备 {device_id} 不存在")

    from app.services.kpi_importer import parse_timestamp_utc
    try:
        t0 = parse_timestamp_utc(start_time)
        t1 = parse_timestamp_utc(end_time)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    _ALLOWED_METRICS = {
        "power_kw", "flow_rate", "supply_temp_c", "return_temp_c",
        "valve_open_pct", "frequency_hz", "ambient_temp_c",
    }
    requested = [m.strip() for m in metrics.split(",") if m.strip() in _ALLOWED_METRICS]
    if not requested:
        requested = ["power_kw", "supply_temp_c", "return_temp_c"]

    select_cols = ", ".join(f"t.{m}" for m in requested)
    rows = (await db.execute(text(f"""
        SELECT t.timestamp, t.running_state, t.health_status, {select_cols}
        FROM device_telemetry_hourly t
        WHERE t.device_id = :did AND t.timestamp >= :t0 AND t.timestamp <= :t1
        ORDER BY t.timestamp ASC
    """), {"did": device_id, "t0": t0, "t1": t1})).fetchall()

    records = []
    for row in rows:
        ts, rstate, health = row[0], row[1], row[2]
        rec: dict = {
            "timestamp": ts.isoformat() if hasattr(ts, "isoformat") else str(ts),
            "running_state": rstate,
            "health_status": health,
        }
        for i, m in enumerate(requested):
            rec[m] = row[3 + i]
        records.append(rec)

    return {
        "device_id": device_id,
        "building_id": dev_row.building_id,
        "device_type": dev_row.device_type,
        "metrics": requested,
        "records": records,
        "count": len(records),
    }


# ---------------------------------------------------------------------------
# 4. 设备关联异常时间线
# ---------------------------------------------------------------------------

@router.get("/devices/{device_id}/anomalies", summary="设备关联异常时间线")
async def get_device_anomalies(
    device_id: str,
    hours: int = Query(168, ge=1, le=8760, description="回溯小时数"),
    db: AsyncSession = Depends(get_db_session),
):
    """返回归因到该设备的历史异常列表。"""
    dev_row = (await db.execute(
        select(Device).where(Device.device_id == device_id)
    )).scalar_one_or_none()
    if not dev_row:
        raise HTTPException(status_code=404, detail=f"设备 {device_id} 不存在")

    # 以 attribution 表中最新时间戳为基准
    max_ts_row = (await db.execute(text(
        "SELECT MAX(timestamp) FROM anomaly_device_attributions WHERE device_id = :did"
    ), {"did": device_id})).scalar()

    if not max_ts_row:
        return {"device_id": device_id, "anomalies": [], "total": 0}

    window_start = max_ts_row - timedelta(hours=hours)

    rows = (await db.execute(text("""
        SELECT a.timestamp, a.attribution_role, a.attribution_score,
               a.attribution_reason, a.evidence_json,
               ae.rule_triggered, ae.message, ae.anomaly_phase,
               ae.deviation_pct, ae.expected_value, ae.actual_value
        FROM anomaly_device_attributions a
        LEFT JOIN anomaly_events ae ON ae.id = a.event_id
        WHERE a.device_id = :did AND a.timestamp >= :t0
        ORDER BY a.timestamp DESC
        LIMIT 200
    """), {"did": device_id, "t0": window_start})).fetchall()

    import json as _json
    anomalies = []
    for row in rows:
        (ts, role, score, reason, evid_json, rule, msg, phase, dev_pct, exp_v, act_v) = row
        evid = _json.loads(evid_json) if evid_json else {}
        anomalies.append({
            "timestamp": ts.isoformat() if hasattr(ts, "isoformat") else str(ts),
            "attribution_role": role,
            "attribution_score": score,
            "attribution_reason": reason,
            "rule_triggered": rule,
            "message": msg,
            "anomaly_phase": phase,
            "deviation_pct": dev_pct,
            "expected_value": exp_v,
            "actual_value": act_v,
            "evidence": evid,
        })

    return {"device_id": device_id, "anomalies": anomalies, "total": len(anomalies)}


# ---------------------------------------------------------------------------
# 5. 楼宇异常归因设备列表
# ---------------------------------------------------------------------------

@router.get("/buildings/{building_id}/device-attributions", summary="楼宇最近异常归因设备")
async def get_building_device_attributions(
    building_id: str,
    hours: int = Query(168, ge=1, le=8760),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db_session),
):
    """返回某栋楼最近时段内，异常归因到的所有设备及归因详情。"""
    max_ts_row = (await db.execute(text(
        "SELECT MAX(timestamp) FROM anomaly_device_attributions WHERE building_id = :bid"
    ), {"bid": building_id})).scalar()

    if not max_ts_row:
        return {"building_id": building_id, "attributions": [], "total": 0}

    window_start = max_ts_row - timedelta(hours=hours)

    rows = (await db.execute(text("""
        SELECT a.timestamp, a.device_id, a.device_type,
               a.attribution_role, a.attribution_score, a.attribution_reason,
               a.evidence_json, ae.rule_triggered, ae.message, ae.anomaly_phase
        FROM anomaly_device_attributions a
        LEFT JOIN anomaly_events ae ON ae.id = a.event_id
        WHERE a.building_id = :bid AND a.timestamp >= :t0
        ORDER BY a.timestamp DESC, a.attribution_score DESC
        LIMIT :lim
    """), {"bid": building_id, "t0": window_start, "lim": limit})).fetchall()

    import json as _json
    attributions = []
    for row in rows:
        (ts, did, dtype, role, score, reason, evid_json, rule, msg, phase) = row
        evid = _json.loads(evid_json) if evid_json else {}
        attributions.append({
            "timestamp": ts.isoformat() if hasattr(ts, "isoformat") else str(ts),
            "device_id": did,
            "device_type": dtype,
            "attribution_role": role,
            "attribution_score": score,
            "attribution_reason": reason,
            "rule_triggered": rule,
            "message": msg,
            "anomaly_phase": phase,
            "evidence": evid,
        })

    return {"building_id": building_id, "attributions": attributions, "total": len(attributions)}
