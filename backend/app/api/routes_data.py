"""
普通数据查询接口（非 AI，直接查 DB）。

端点：
  GET /api/buildings                              — 获取所有建筑列表
  GET /api/buildings/{building_type}/status       — 获取建筑最新设备状态（按 building_type）
  GET /api/buildings/{building_type}/devices      — 获取设备运行状态快照 + 遥测历史（方案A）
  GET /api/buildings/{building_type}/energy       — 获取建筑每日能耗趋势（按 building_type）
  GET /api/buildings/{building_type}/load-profile — 按小时/星期聚合负荷曲线
  GET /api/buildings/{building_type}/peak-valley-stats — 峰谷与夜间高耗统计
  GET /api/overview                               — 获取 Dashboard KPI 汇总（全局总览）
  GET /api/anomalies/sankey                       — 异常根因桑基图聚合数据
  GET /api/anomalies/attributions                 — 异常设备归因列表（方案A）
  GET /api/tools                                  — 列出所有可用 MCP 工具（调试用）
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import and_, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.buildings import (
    BUILDING_TYPE_ORDER,
    BUILDING_TYPE_TO_ID,
    get_building_icon,
    get_building_label,
    normalize_building_type,
)
from app.core.cache import cache_bucket, get_or_compute_json
from app.core.config import get_settings
from app.core.security import get_current_user_optional
from app.db.models import Building, DailyEnergySummary, Device, EnergyData, User
from app.db.session import AsyncSessionLocal, get_db_session
from app.mcp.server import list_tools
from app.services.kpi_expected_service import calculate_rated_values
from app.services.work_order_service import (
    list_work_orders as svc_list_work_orders,
    serialize_work_order,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["数据"])
settings = get_settings()

_COP_PROXY_SCALING_FACTOR = 15.0
_ZERO_HVAC_ENERGY_THRESHOLD = 0.1

_HOME_BUNDLE_BUILDING_TYPES = BUILDING_TYPE_ORDER
_HOME_OVERVIEW_BUNDLE_TTL_SECONDS = 60
_HOME_SECTION_BUNDLE_TTL_SECONDS = 300
_HOME_SECTION_BUNDLE_SCOPES = {"overview", "charts", "all"}


@dataclass(frozen=True)
class _BuildingContext:
    building_type: str
    building_id: str
    sqm: float | None
    display_name: str


def _get_building_context_cache(
    db: AsyncSession,
) -> dict[tuple[str, str], _BuildingContext]:
    cache = db.info.get("building_context_cache")
    if isinstance(cache, dict):
        return cache

    cache = {}
    db.info["building_context_cache"] = cache
    return cache


def _cache_building_context(
    db: AsyncSession,
    context: _BuildingContext,
) -> _BuildingContext:
    cache = _get_building_context_cache(db)
    cache[("id", context.building_id)] = context
    cache[("type", context.building_type)] = context
    return context


def _resolve_bundle_data_date(overview_payload: dict[str, Any] | None) -> date:
    data_date = overview_payload.get("data_date") if isinstance(overview_payload, dict) else None
    if isinstance(data_date, str):
        try:
            return date.fromisoformat(data_date[:10])
        except ValueError:
            pass
    return datetime.now(timezone.utc).date()


async def _get_latest_energy_data_date(db: AsyncSession) -> date:
    result = await db.execute(
        text('SELECT MAX("timestamp")::date AS latest_day FROM energy_data')
    )
    latest_day = result.scalar()
    if isinstance(latest_day, date):
        return latest_day
    return datetime.now(timezone.utc).date()


async def _resolve_building_context(
    db: AsyncSession,
    *,
    building_type: str | None = None,
    building_id: str | None = None,
) -> _BuildingContext | None:
    normalized_type = normalize_building_type(building_type) or building_type
    cache = _get_building_context_cache(db)

    if building_id:
        cached = cache.get(("id", building_id))
        if cached is not None:
            return cached

        result = await db.execute(
            select(Building).where(Building.building_id == building_id)
        )
        building = result.scalar_one_or_none()
        if not building:
            return None
        resolved_type = (
            normalize_building_type(building.primary_space_usage)
            or normalized_type
            or building.primary_space_usage
            or building.building_id
        )
        return _cache_building_context(
            db,
            _BuildingContext(
                building_type=resolved_type,
                building_id=building.building_id,
                sqm=building.sqm,
                display_name=get_building_label(
                    resolved_type,
                    resolved_type or building.building_id,
                ),
            ),
        )

    if normalized_type:
        cached = cache.get(("type", normalized_type))
        if cached is not None:
            return cached

        result = await db.execute(
            select(Building).where(Building.primary_space_usage == normalized_type)
        )
        building = result.scalar_one_or_none()
        if not building:
            return None
        return _cache_building_context(
            db,
            _BuildingContext(
                building_type=normalized_type,
                building_id=building.building_id,
                sqm=building.sqm,
                display_name=get_building_label(
                    normalized_type,
                    normalized_type or building.building_id,
                ),
            ),
        )

    return None


async def _resolve_home_building_contexts(
    db: AsyncSession,
    *,
    building_types: tuple[str, ...] = _HOME_BUNDLE_BUILDING_TYPES,
) -> dict[str, _BuildingContext]:
    normalized_types = tuple(
        normalize_building_type(building_type) or building_type
        for building_type in building_types
    )
    cache = _get_building_context_cache(db)

    missing_types = [
        building_type
        for building_type in normalized_types
        if cache.get(("type", building_type)) is None
    ]
    if missing_types:
        result = await db.execute(
            select(Building).where(Building.primary_space_usage.in_(missing_types))
        )
        for building in result.scalars():
            resolved_type = (
                normalize_building_type(building.primary_space_usage)
                or building.primary_space_usage
                or building.building_id
            )
            _cache_building_context(
                db,
                _BuildingContext(
                    building_type=resolved_type,
                    building_id=building.building_id,
                    sqm=building.sqm,
                    display_name=get_building_label(
                        resolved_type,
                        resolved_type or building.building_id,
                    ),
                ),
            )

    unresolved_types = [
        building_type
        for building_type in normalized_types
        if cache.get(("type", building_type)) is None
    ]
    if unresolved_types:
        raise HTTPException(
            status_code=404,
            detail=f"建筑类型不存在: {', '.join(unresolved_types)}",
        )

    return {
        building_type: cache[("type", building_type)]
        for building_type in normalized_types
    }


async def _require_building_context(
    db: AsyncSession,
    *,
    building_type: str | None = None,
    building_id: str | None = None,
) -> _BuildingContext:
    context = await _resolve_building_context(
        db,
        building_type=building_type,
        building_id=building_id,
    )
    if context is None:
        detail = (
            f"建筑类型 {building_type} 不存在"
            if building_type
            else f"建筑 {building_id} 不存在"
        )
        raise HTTPException(status_code=404, detail=detail)
    return context


# ---------------------------------------------------------------------------
# 数据时间范围（供前端日期选择器动态化）
# ---------------------------------------------------------------------------
@router.get("/data-range", summary="获取数据库有效时间范围")
async def get_data_range_endpoint():
    """返回 energy_data 表的 MIN/MAX 时间戳，带 10 分钟缓存。"""
    from app.core.data_range import get_data_range
    return await get_data_range()


# ---------------------------------------------------------------------------
# 建筑列表
# ---------------------------------------------------------------------------
@router.get("/buildings", summary="获取所有建筑列表")
async def get_buildings(db: AsyncSession = Depends(get_db_session)):
    """返回 buildings 表中所有建筑的基本信息（含 timezone 和关联设备列表）。"""
    cache_key = "buildings:list"
    ttl_seconds = settings.CACHE_BUILDINGS_TTL_SECONDS

    async def _compute() -> list[dict]:
        try:
            result = await db.execute(
                select(Building).order_by(Building.primary_space_usage)
            )
            buildings = result.scalars().all()

            # 一次查出所有设备（避免 N+1）
            all_bids = [b.building_id for b in buildings]
            dev_map: dict[str, list[dict]] = {bid: [] for bid in all_bids}
            if all_bids:
                dev_result = await db.execute(
                    select(Device.device_id, Device.building_id, Device.device_type)
                    .where(Device.building_id.in_(all_bids))
                    .order_by(Device.building_id, Device.device_type)
                )
                for drow in dev_result.fetchall():
                    dev_map[drow[1]].append(
                        {"device_id": drow[0], "device_type": drow[2]}
                    )

            return [
                {
                    "building_id": b.building_id,
                    "building_type": b.primary_space_usage,
                    "display_name": get_building_label(
                        b.primary_space_usage or "",
                        b.primary_space_usage or b.building_id,
                    ),
                    "icon": get_building_icon(b.primary_space_usage),
                    "sqm": b.sqm,
                    "devices": dev_map.get(b.building_id, []),
                }
                for b in buildings
            ]
        except Exception as exc:
            logger.error("查询建筑列表失败: %s", exc)
            raise HTTPException(status_code=500, detail=f"数据库查询失败: {exc}")

    return await get_or_compute_json(cache_key, ttl_seconds, _compute)


async def _get_recent_anomalies_payload(
    db: AsyncSession,
    hours: int,
    building_type: str | None,
    only_unresolved: bool,
    building_id: str | None = None,
) -> dict[str, Any]:
    max_ts_result = await db.execute(text("SELECT MAX(data_timestamp) FROM anomaly_events"))
    max_ts = max_ts_result.scalar()

    if max_ts is None:
        return {
            "anomalies": [],
            "total": 0,
            "check_period": {"start": None, "end": None, "hours": hours},
            "source": "anomaly_events",
            "module_status": "no_data",
            "message": "anomaly_events 暂无数据，请先调用 /api/admin/rebuild-all",
        }

    if hasattr(max_ts, "tzinfo") and max_ts.tzinfo is None:
        max_ts = max_ts.replace(tzinfo=timezone.utc)

    window_start = max_ts - timedelta(hours=hours)
    building_filter = ""
    resolved_filter = " AND ae.is_resolved = false" if only_unresolved else ""
    params: dict[str, Any] = {"t0": window_start, "t1": max_ts}

    resolved_building_id = building_id
    if resolved_building_id is None and building_type:
        context = await _resolve_building_context(db, building_type=building_type)
        resolved_building_id = context.building_id if context else None

    if resolved_building_id:
        building_filter = " AND ae.building_id = :bid"
        params["bid"] = resolved_building_id

    anomaly_result = await db.execute(text(f"""
        SELECT
            ae.id,
            ae.detected_at,
            ae.data_timestamp,
            ae.building_id,
            ae.meter_device_id,
            ae.rule_triggered,
            ae.actual_value,
            ae.threshold_value,
            ae.expected_value,
            ae.deviation_pct,
            ae.hvac_root_cause,
            ae.message,
            ae.is_resolved,
            ae.anomaly_phase,
            ae.symptom_flags_json,
            ae.event_source,
            ae.severity
        FROM anomaly_events ae
        WHERE ae.data_timestamp >= :t0
          AND ae.data_timestamp <= :t1
          {resolved_filter}
          {building_filter}
        ORDER BY ae.data_timestamp DESC
        LIMIT 200
    """), params)

    rows = anomaly_result.fetchall()
    anomalies = []
    for idx, row in enumerate(rows):
        (ev_id, det_at, data_ts, bid, meter_id, rule, actual, threshold,
         expected, dev_pct, hvac_rc, msg, is_res, phase, sym_flags,
         src, severity) = row
        anomalies.append({
            "idx": idx,
            "id": ev_id,
            "detected_at": det_at.isoformat() if det_at else None,
            "data_timestamp": data_ts.isoformat() if data_ts else None,
            "building_id": bid,
            "meter_device_id": meter_id,
            "rule_triggered": rule,
            "actual_value": actual,
            "threshold_value": threshold,
            "expected_value": expected,
            "deviation_pct": dev_pct,
            "message": msg,
            "is_resolved": is_res,
            "hvac_root_cause": hvac_rc,
            "anomaly_phase": phase,
            "symptom_flags_json": sym_flags,
            "event_source": src,
            "severity": severity,
        })

    return {
        "anomalies": anomalies,
        "total": len(anomalies),
        "check_period": {
            "start": window_start.isoformat(),
            "end": max_ts.isoformat(),
            "hours": hours,
        },
        "source": "anomaly_events",
        "module_status": "ok",
    }


# ---------------------------------------------------------------------------
# 建筑最新设备状态（按 building_type 查询）
# ---------------------------------------------------------------------------
@router.get("/buildings/{building_type}/status", summary="获取建筑最新设备状态")
async def get_building_status(
    building_type: str,
    db: AsyncSession = Depends(get_db_session),
    building_id: str | None = None,
):
    """查询指定建筑最新一条传感器读数（实时状态快照）。building_type 如 'Office'。"""
    building = await _require_building_context(
        db,
        building_type=building_type,
        building_id=building_id,
    )

    result = await db.execute(
        select(EnergyData)
        .where(EnergyData.building_id == building.building_id)
        .order_by(EnergyData.timestamp.desc())
        .limit(1)
    )
    latest = result.scalar_one_or_none()
    if not latest:
        raise HTTPException(status_code=404, detail=f"建筑 {building_type} 暂无数据")

    # 获取关联设备列表（电表设备 ID 用于工单创建和 RAG 过滤）
    dev_result = await db.execute(
        select(Device.device_id, Device.device_type)
        .where(Device.building_id == building.building_id)
        .order_by(Device.device_type)
    )
    devices = [{"device_id": r[0], "device_type": r[1]} for r in dev_result.fetchall()]

    return {
        "building_type": building.building_type,
        "display_name": building.display_name,
        "icon": get_building_icon(building.building_type),
        "sqm": building.sqm,
        "devices": devices,
        "last_updated_utc": latest.timestamp.isoformat() if latest.timestamp else None,
        "electricity_kwh": latest.electricity_kwh,
        "water_m3": latest.water_m3,
        "hac_energy": latest.hac_energy,
        "sim_supply_temp_c": latest.sim_supply_temp_c,
        "sim_return_temp_c": latest.sim_return_temp_c,
        "air_temp_c": latest.air_temp_c,
        "dew_temp_c": latest.dew_temp_c,
        "humidity_rh_pct": latest.humidity_rh_pct,
    }


# ---------------------------------------------------------------------------
# 设备运行状态（方案A：从 device_status_latest + device_telemetry_hourly 读取）
# ---------------------------------------------------------------------------
@router.get("/buildings/{building_type}/devices", summary="获取建筑设备运行状态")
async def get_building_devices(
    building_type: str,
    history_hours: int = Query(24, ge=1, le=168, description="返回最近 N 小时遥测历史（默认24h）"),
    start_date: str | None = Query(None, description="起始日期 YYYY-MM-DD（与 end_date 同时提供时使用绝对范围）"),
    end_date: str | None = Query(None, description="结束日期 YYYY-MM-DD（与 start_date 同时提供时使用绝对范围）"),
    db: AsyncSession = Depends(get_db_session),
):
    """
    返回建筑下所有设备的最新运行状态快照（device_status_latest）
    以及遥测趋势（device_telemetry_hourly）。

    时间窗口：
      - 同时提供 start_date + end_date 时，按绝对日期范围查询，忽略 history_hours
      - 否则回退到 history_hours 相对窗口（向后兼容）

    包含字段：
      - running_state: running | standby
      - health_status: healthy | degraded | warning
      - online_status: online | offline
      - latest_power_kw / latest_flow_rate（电表/水表能量或流量）
      - latest_supply_temp_c / latest_return_temp_c（空调供回水温）
    """
    bld_result = await db.execute(
        select(Building.building_id).where(Building.primary_space_usage == building_type)
    )
    building_id = bld_result.scalar_one_or_none()
    if not building_id:
        raise HTTPException(status_code=404, detail=f"建筑类型 {building_type} 不存在")

    # ── 最新状态快照 ──────────────────────────────────────────────────────────
    latest_result = await db.execute(text("""
        SELECT
            dsl.device_id,
            dsl.device_type,
            dsl.last_seen_at,
            dsl.online_status,
            dsl.running_state,
            dsl.health_status,
            dsl.latest_power_kw,
            dsl.latest_flow_rate,
            dsl.latest_supply_temp_c,
            dsl.latest_return_temp_c,
            dsl.latest_payload_json
        FROM device_status_latest dsl
        WHERE dsl.building_id = :bid
        ORDER BY dsl.device_type
    """), {"bid": building_id})
    latest_rows = latest_result.fetchall()

    device_snapshot: list[dict] = []
    device_ids: list[str] = []
    for row in latest_rows:
        (dev_id, dev_type, seen_at, online, running, health,
         power_kw, flow_rate, supply_t, return_t, payload_json) = row
        device_ids.append(dev_id)
        device_snapshot.append({
            "device_id": dev_id,
            "device_type": dev_type,
            "last_seen_at": seen_at.isoformat() if seen_at else None,
            "online_status": online,
            "running_state": running,
            "health_status": health,
            "latest_power_kw": float(power_kw) if power_kw is not None else None,
            "latest_flow_rate": float(flow_rate) if flow_rate is not None else None,
            "latest_supply_temp_c": float(supply_t) if supply_t is not None else None,
            "latest_return_temp_c": float(return_t) if return_t is not None else None,
            "latest_payload": payload_json if isinstance(payload_json, dict) else None,
        })

    # 若 device_status_latest 为空（未运行 rebuild-all），回退到 devices 表
    if not device_snapshot:
        dev_result = await db.execute(text(
            "SELECT device_id, device_type FROM devices WHERE building_id = :bid ORDER BY device_type"
        ), {"bid": building_id})
        for drow in dev_result.fetchall():
            device_snapshot.append({
                "device_id": drow[0],
                "device_type": drow[1],
                "last_seen_at": None,
                "online_status": "unknown",
                "running_state": "unknown",
                "health_status": "unknown",
                "latest_power_kw": None,
                "latest_flow_rate": None,
                "latest_supply_temp_c": None,
                "latest_return_temp_c": None,
                "latest_payload": None,
            })
        return {
            "building_type": building_type,
            "building_id": building_id,
            "devices": device_snapshot,
            "history": [],
            "module_status": "no_telemetry_data",
            "message": "device_status_latest 暂无数据，请先调用 /api/admin/rebuild-all",
        }

    # ── 遥测历史趋势 ────────────────────────────────────────────────────────────
    use_absolute_range = start_date is not None and end_date is not None
    history_records: list[dict] = []

    if use_absolute_range:
        try:
            t0 = datetime.strptime(start_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
            t1 = datetime.strptime(end_date, "%Y-%m-%d").replace(
                hour=23, minute=59, second=59, tzinfo=timezone.utc
            )
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail="start_date / end_date 格式应为 YYYY-MM-DD",
            )

        hist_result = await db.execute(text("""
            SELECT
                dth.timestamp,
                dth.device_id,
                dth.device_type,
                dth.running_state,
                dth.health_status,
                dth.power_kw,
                dth.flow_rate,
                dth.supply_temp_c,
                dth.return_temp_c,
                dth.ambient_temp_c
            FROM device_telemetry_hourly dth
            WHERE dth.building_id = :bid
              AND dth.timestamp >= :t0
              AND dth.timestamp <= :t1
            ORDER BY dth.timestamp ASC, dth.device_type ASC
        """), {"bid": building_id, "t0": t0, "t1": t1})

        for hrow in hist_result.fetchall():
            (ts, d_id, d_type, run_st, health_st,
             p_kw, fl, sup_t, ret_t, amb_t) = hrow
            history_records.append({
                "timestamp": ts.isoformat() if ts else None,
                "device_id": d_id,
                "device_type": d_type,
                "running_state": run_st,
                "health_status": health_st,
                "power_kw": float(p_kw) if p_kw is not None else None,
                "flow_rate": float(fl) if fl is not None else None,
                "supply_temp_c": float(sup_t) if sup_t is not None else None,
                "return_temp_c": float(ret_t) if ret_t is not None else None,
                "ambient_temp_c": float(amb_t) if amb_t is not None else None,
            })
    else:
        max_ts_result = await db.execute(text(
            "SELECT MAX(timestamp) FROM device_telemetry_hourly WHERE building_id = :bid"
        ), {"bid": building_id})
        max_ts = max_ts_result.scalar()

        if max_ts is not None:
            if hasattr(max_ts, "tzinfo") and max_ts.tzinfo is None:
                max_ts = max_ts.replace(tzinfo=timezone.utc)
            window_start = max_ts - timedelta(hours=history_hours)

            hist_result = await db.execute(text("""
                SELECT
                    dth.timestamp,
                    dth.device_id,
                    dth.device_type,
                    dth.running_state,
                    dth.health_status,
                    dth.power_kw,
                    dth.flow_rate,
                    dth.supply_temp_c,
                    dth.return_temp_c,
                    dth.ambient_temp_c
                FROM device_telemetry_hourly dth
                WHERE dth.building_id = :bid
                  AND dth.timestamp >= :t0
                  AND dth.timestamp <= :t1
                ORDER BY dth.timestamp ASC, dth.device_type ASC
            """), {"bid": building_id, "t0": window_start, "t1": max_ts})

            for hrow in hist_result.fetchall():
                (ts, d_id, d_type, run_st, health_st,
                 p_kw, fl, sup_t, ret_t, amb_t) = hrow
                history_records.append({
                    "timestamp": ts.isoformat() if ts else None,
                    "device_id": d_id,
                    "device_type": d_type,
                    "running_state": run_st,
                    "health_status": health_st,
                    "power_kw": float(p_kw) if p_kw is not None else None,
                    "flow_rate": float(fl) if fl is not None else None,
                    "supply_temp_c": float(sup_t) if sup_t is not None else None,
                    "return_temp_c": float(ret_t) if ret_t is not None else None,
                    "ambient_temp_c": float(amb_t) if amb_t is not None else None,
                })

    return {
        "building_type": building_type,
        "building_id": building_id,
        "devices": device_snapshot,
        "history": history_records,
        "history_hours": history_hours if not use_absolute_range else None,
        "start_date": start_date,
        "end_date": end_date,
        "module_status": "ok",
    }


# ---------------------------------------------------------------------------
# 异常设备归因列表（方案A：从 anomaly_device_attributions 读取）
# ---------------------------------------------------------------------------
@router.get("/anomalies/attributions", summary="异常事件的设备归因列表")
async def get_anomaly_attributions(
    building_type: str | None = Query(None, description="按建筑类型过滤（如 Office）"),
    hours: int = Query(168, ge=1, le=8760, description="查询最近 N 小时，默认 7 天"),
    db: AsyncSession = Depends(get_db_session),
):
    """
    从 anomaly_device_attributions 返回异常归因到设备的记录列表。
    每条记录包含：事件ID、设备ID、设备类型、归因角色、归因得分和归因原因。
    可用于前端"异常归因分析"和"设备故障统计"展示。
    """
    building_filter = ""
    params: dict[str, Any] = {}

    if building_type:
        bld_result = await db.execute(
            select(Building.building_id).where(Building.primary_space_usage == building_type)
        )
        bid = bld_result.scalar_one_or_none()
        if bid:
            building_filter = " AND ada.building_id = :bid"
            params["bid"] = bid

    # 以 anomaly_device_attributions 最新时间戳为基点
    max_ts_sql = "SELECT MAX(timestamp) FROM anomaly_device_attributions"
    max_ts_params: dict[str, Any] = {}
    if "bid" in params:
        max_ts_sql += " WHERE building_id = :bid"
        max_ts_params["bid"] = params["bid"]
    max_ts_result = await db.execute(text(max_ts_sql), max_ts_params)
    max_ts = max_ts_result.scalar()

    if max_ts is None:
        return {
            "attributions": [],
            "total": 0,
            "module_status": "no_data",
            "message": "anomaly_device_attributions 暂无数据，请先调用 /api/admin/rebuild-all",
        }

    if hasattr(max_ts, "tzinfo") and max_ts.tzinfo is None:
        max_ts = max_ts.replace(tzinfo=timezone.utc)
    from datetime import timedelta
    window_start = max_ts - timedelta(hours=hours)
    params["t0"] = window_start
    params["t1"] = max_ts

    atr_result = await db.execute(text(f"""
        SELECT
            ada.id,
            ada.building_id,
            ada.timestamp,
            ada.event_id,
            ada.device_id,
            ada.device_type,
            ada.attribution_role,
            ada.attribution_score,
            ada.attribution_reason,
            ada.evidence_json,
            ae.rule_triggered,
            ae.actual_value,
            ae.expected_value,
            ae.deviation_pct,
            ae.hvac_root_cause,
            ae.message AS anomaly_message
        FROM anomaly_device_attributions ada
        LEFT JOIN anomaly_events ae ON ae.id::text = ada.event_id
        WHERE ada.timestamp >= :t0
          AND ada.timestamp <= :t1
          {building_filter}
        ORDER BY ada.timestamp DESC, ada.attribution_score DESC
        LIMIT 500
    """), params)

    rows = atr_result.fetchall()
    attributions: list[dict] = []
    for row in rows:
        (atr_id, bid, ts, ev_id, dev_id, dev_type, role, score, reason,
         evidence, rule, actual, expected, dev_pct, hvac_rc, msg) = row
        attributions.append({
            "id": atr_id,
            "building_id": bid,
            "timestamp": ts.isoformat() if ts else None,
            "event_id": ev_id,
            "device_id": dev_id,
            "device_type": dev_type,
            "attribution_role": role,
            "attribution_score": float(score) if score is not None else None,
            "attribution_reason": reason,
            "evidence": evidence if isinstance(evidence, dict) else None,
            "rule_triggered": rule,
            "actual_value": actual,
            "expected_value": expected,
            "deviation_pct": dev_pct,
            "hvac_root_cause": hvac_rc,
            "anomaly_message": msg,
        })

    # 按设备汇总统计
    device_stats: dict[str, dict] = {}
    for a in attributions:
        did = a["device_id"]
        if did not in device_stats:
            device_stats[did] = {
                "device_id": did,
                "device_type": a["device_type"],
                "building_id": a["building_id"],
                "anomaly_count": 0,
                "avg_deviation_pct": 0.0,
                "max_score": 0.0,
            }
        s = device_stats[did]
        s["anomaly_count"] += 1
        s["avg_deviation_pct"] = (
            (s["avg_deviation_pct"] * (s["anomaly_count"] - 1) + (a["deviation_pct"] or 0))
            / s["anomaly_count"]
        )
        if (a["attribution_score"] or 0) > s["max_score"]:
            s["max_score"] = a["attribution_score"] or 0

    return {
        "attributions": attributions,
        "total": len(attributions),
        "device_summary": sorted(
            device_stats.values(),
            key=lambda x: x["anomaly_count"],
            reverse=True,
        ),
        "check_period": {
            "start": window_start.isoformat(),
            "end": max_ts.isoformat(),
            "hours": hours,
        },
        "module_status": "ok",
    }


# ---------------------------------------------------------------------------
# 按天能耗趋势（按 building_type 查询）
# ---------------------------------------------------------------------------
@router.get("/buildings/{building_type}/energy", summary="获取建筑每日能耗趋势")
async def get_building_energy_trend(
    building_type: str,
    start_date: date = Query(..., description="开始日期 YYYY-MM-DD"),
    end_date: date = Query(..., description="结束日期 YYYY-MM-DD"),
    include_water: bool = Query(False, description="是否包含每日用水量"),
    include_device_status: bool = Query(False, description="是否包含设备运行状态日聚合（正常数/COP/功率/温差）"),
    db: AsyncSession = Depends(get_db_session),
    building_id: str | None = None,
):
    """
    从物化视图查询按天汇总的能耗趋势。building_type 如 'Office'。
    include_device_status=true 时额外从 device_telemetry_hourly 聚合设备日运行指标。
    """
    if start_date > end_date:
        raise HTTPException(status_code=400, detail="start_date 不能晚于 end_date")

    cache_key = (
        f"building_energy:{building_type}:"
        f"{start_date.isoformat()}:{end_date.isoformat()}:"
        f"{int(include_water)}:{int(include_device_status)}"
    )
    ttl_seconds = settings.CACHE_BUILDING_ENERGY_TREND_TTL_SECONDS

    async def _compute() -> dict[str, Any]:
        building = await _require_building_context(
            db,
            building_type=building_type,
            building_id=building_id,
        )

        # ── 能耗数据：优先从物化视图查询 ──
        result = await db.execute(
            select(DailyEnergySummary)
            .where(
                DailyEnergySummary.building_id == building.building_id,
                DailyEnergySummary.day >= start_date,
                DailyEnergySummary.day <= end_date,
            )
            .order_by(DailyEnergySummary.day)
        )
        rows = result.scalars().all()

        if rows:
            records = [
                {
                    "day": r.day.isoformat() if r.day else None,
                    "total_electricity_kwh": r.total_electricity_kwh,
                    "avg_ambient_temp": r.avg_ambient_temp,
                    "total_water_m3": r.total_water_m3,
                    "total_hac_energy": r.total_hac_energy,
                    "avg_supply_temp": r.avg_supply_temp,
                    "avg_return_temp": r.avg_return_temp,
                    "avg_humidity": r.avg_humidity,
                    "avg_dew_temp": r.avg_dew_temp,
                }
                for r in rows
            ]
            source = "daily_energy_summary (materialized view)"
        else:
            logger.warning(
                "daily_energy_summary 在 %s ~ %s 无数据，回退到 energy_data 直查",
                start_date, end_date,
            )
            fallback_result = await db.execute(
                text("""
                    SELECT date_trunc('day', timestamp)::date AS day,
                           SUM(electricity_kwh)    AS total_electricity_kwh,
                           AVG(air_temp_c)         AS avg_ambient_temp,
                           SUM(water_m3)           AS total_water_m3,
                           SUM(hac_energy)         AS total_hac_energy,
                           AVG(sim_supply_temp_c)  AS avg_supply_temp,
                           AVG(sim_return_temp_c)  AS avg_return_temp,
                           AVG(humidity_rh_pct)    AS avg_humidity,
                           AVG(dew_temp_c)         AS avg_dew_temp
                    FROM energy_data
                    WHERE building_id = :bid
                      AND timestamp >= :sd AND timestamp <= :ed
                    GROUP BY day ORDER BY day
                """),
                {"bid": building.building_id, "sd": start_date, "ed": end_date},
            )
            records = [
                {
                    "day": fr[0].isoformat() if hasattr(fr[0], "isoformat") else str(fr[0]),
                    "total_electricity_kwh": float(fr[1]) if fr[1] is not None else None,
                    "avg_ambient_temp": float(fr[2]) if fr[2] is not None else None,
                    "total_water_m3": float(fr[3]) if fr[3] is not None else None,
                    "total_hac_energy": float(fr[4]) if fr[4] is not None else None,
                    "avg_supply_temp": float(fr[5]) if fr[5] is not None else None,
                    "avg_return_temp": float(fr[6]) if fr[6] is not None else None,
                    "avg_humidity": float(fr[7]) if fr[7] is not None else None,
                    "avg_dew_temp": float(fr[8]) if fr[8] is not None else None,
                }
                for fr in fallback_result.fetchall()
            ]
            source = "energy_data (fallback)"

        # ── 设备运行状态日聚合（来自 device_telemetry_hourly） ──
        if include_device_status:
            dev_result = await db.execute(
                text("""
                    SELECT
                        CAST(date_trunc('day', dth.timestamp) AS date)             AS day,
                        COUNT(DISTINCT dth.device_id)                              AS device_total,
                        COUNT(DISTINCT CASE
                            WHEN dth.health_status = 'healthy' THEN dth.device_id
                        END)                                                       AS device_normal,
                        AVG(CASE WHEN dth.device_type = 'ac'
                            THEN dth.power_kw END)                                 AS ac_avg_power_kw,
                        AVG(CASE WHEN dth.device_type = 'ac'
                            THEN ABS(dth.supply_temp_c - dth.return_temp_c) END)   AS supply_return_delta,
                        AVG(CASE WHEN dth.device_type = 'ac'
                                  AND dth.power_kw > 0
                                  AND dth.supply_temp_c IS NOT NULL
                                  AND dth.return_temp_c IS NOT NULL
                            THEN (COALESCE(dth.flow_rate, 1.0) * 4.186
                                  * ABS(dth.supply_temp_c - dth.return_temp_c))
                                 / NULLIF(dth.power_kw, 0)
                        END)                                                       AS ac_cop
                    FROM device_telemetry_hourly dth
                    WHERE dth.building_id = :bid
                      AND dth.timestamp >= :sd
                      AND dth.timestamp <  CAST(:ed AS date) + interval '1 day'
                    GROUP BY 1
                    ORDER BY 1
                """),
                {"bid": building.building_id, "sd": start_date, "ed": end_date},
            )
            fallback_cop_result = await db.execute(
                text("""
                    SELECT
                        date_trunc('day', e.timestamp)::date AS day,
                        AVG(CASE
                            WHEN e.hac_energy > :min_energy
                             AND e.sim_supply_temp_c IS NOT NULL
                             AND e.sim_return_temp_c IS NOT NULL
                            THEN ABS(e.sim_return_temp_c - e.sim_supply_temp_c)
                        END) AS supply_return_delta,
                        AVG(CASE
                            WHEN e.hac_energy > :min_energy
                            THEN e.hac_energy
                        END) AS ac_avg_power_kw,
                        AVG(CASE
                            WHEN e.hac_energy > :min_energy
                             AND e.sim_supply_temp_c IS NOT NULL
                             AND e.sim_return_temp_c IS NOT NULL
                             AND ABS(e.sim_return_temp_c - e.sim_supply_temp_c) > 0
                            THEN (:scale * ABS(e.sim_return_temp_c - e.sim_supply_temp_c))
                                 / NULLIF(e.hac_energy, 0)
                        END) AS ac_cop
                    FROM energy_data e
                    WHERE e.building_id = :bid
                      AND e.timestamp >= :sd
                      AND e.timestamp < CAST(:ed AS date) + interval '1 day'
                    GROUP BY 1
                    ORDER BY 1
                """),
                {
                    "bid": building.building_id,
                    "sd": start_date,
                    "ed": end_date,
                    "min_energy": _ZERO_HVAC_ENERGY_THRESHOLD,
                    "scale": _COP_PROXY_SCALING_FACTOR,
                },
            )
            dev_by_day: dict[str, dict] = {}
            for dr in dev_result.fetchall():
                day_str = dr[0].isoformat() if hasattr(dr[0], "isoformat") else str(dr[0])
                dev_by_day[day_str] = {
                    "device_total":         int(dr[1]) if dr[1] is not None else 0,
                    "device_normal":        int(dr[2]) if dr[2] is not None else 0,
                    "ac_avg_power_kw":      round(float(dr[3]), 2) if dr[3] is not None else None,
                    "supply_return_delta":  round(float(dr[4]), 2) if dr[4] is not None else None,
                    "ac_cop":               round(float(dr[5]), 2) if dr[5] is not None else None,
                }

            fallback_cop_by_day: dict[str, dict] = {}
            for row in fallback_cop_result.fetchall():
                day_str = row[0].isoformat() if hasattr(row[0], "isoformat") else str(row[0])
                fallback_cop_by_day[day_str] = {
                    "ac_avg_power_kw": round(float(row[2]), 2) if row[2] is not None else None,
                    "supply_return_delta": round(float(row[1]), 2) if row[1] is not None else None,
                    "ac_cop": round(float(row[3]), 2) if row[3] is not None else None,
                }

            empty_dev = {
                "device_total": 0, "device_normal": 0,
                "ac_avg_power_kw": None, "supply_return_delta": None, "ac_cop": None,
            }
            for rec in records:
                rec.update(dev_by_day.get(rec["day"], empty_dev))
                fallback = fallback_cop_by_day.get(rec["day"], {})
                if rec.get("ac_avg_power_kw") is None:
                    rec["ac_avg_power_kw"] = fallback.get("ac_avg_power_kw")
                if rec.get("supply_return_delta") is None:
                    rec["supply_return_delta"] = fallback.get("supply_return_delta")
                if rec.get("ac_cop") is None:
                    rec["ac_cop"] = fallback.get("ac_cop")

        return {
            "building_type": building.building_type,
            "building_id": building.building_id,
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
            "source": source,
            "include_device_status": include_device_status,
            "records": records,
            "count": len(records),
        }

    return await get_or_compute_json(cache_key, ttl_seconds, _compute)


# ---------------------------------------------------------------------------
# 实际 vs 国标期望逐小时对比（供前端"实际 vs 期望"折线图使用）
# ---------------------------------------------------------------------------
_METRIC_COLS = {
    "electricity": ("electricity_kwh",  "electricity_kwh_expected",  "kWh"),
    "water":       ("water_m3",         "water_m3_expected",         "L"),
    "hac_energy":  ("hac_energy",       "hac_energy_expected",       "kWh"),
}

@router.get(
    "/buildings/{building_type}/rated-vs-actual",
    summary="获取建筑逐小时实际 vs 国标期望值对比",
)
async def get_rated_vs_actual(
    building_type: str,
    start_date: date = Query(..., description="开始日期 YYYY-MM-DD（建议跨度 ≤ 7 天）"),
    end_date: date   = Query(..., description="结束日期 YYYY-MM-DD"),
    metric: str      = Query("electricity", description="指标：electricity | water | hac_energy"),
    db: AsyncSession = Depends(get_db_session),
    building_id: str | None = None,
):
    if metric not in _METRIC_COLS:
        raise HTTPException(status_code=400, detail=f"metric 只能为：{list(_METRIC_COLS.keys())}")
    actual_col, expected_col, unit = _METRIC_COLS[metric]

    building = await _require_building_context(
        db,
        building_type=building_type,
        building_id=building_id,
    )

    start_dt = datetime(start_date.year, start_date.month, start_date.day, tzinfo=timezone.utc)
    end_dt   = datetime(end_date.year,   end_date.month,   end_date.day,   tzinfo=timezone.utc) + timedelta(days=1)

    rows_result = await db.execute(text(f"""
        SELECT
            e.timestamp,
            e.{actual_col}   AS actual_val,
            x.{expected_col} AS rated_val,
            x.hvac_mode,
            x.schedule_factor,
            f.flag_water OR f.flag_electricity OR f.flag_hvac_energy
                OR f.flag_supply_deviation OR f.flag_return_deviation AS is_anomaly,
            f.anomaly_phase,
            f.hvac_diagnosis
        FROM energy_data e
        LEFT JOIN kpi_expected_hourly x
            ON x.building_id = e.building_id AND x.timestamp = e.timestamp
        LEFT JOIN kpi_anomaly_flags f
            ON f.building_id = e.building_id AND f.timestamp = e.timestamp
        WHERE e.building_id = :bid
          AND e.timestamp >= :t0
          AND e.timestamp < :t1
        ORDER BY e.timestamp ASC
    """), {"bid": building.building_id, "t0": start_dt, "t1": end_dt})
    rows = rows_result.fetchall()

    if not rows:
        return {
            "building_type": building.building_type,
            "building_id": building.building_id,
            "metric": metric,
            "unit": unit,
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
            "records": [],
            "summary": {"total_hours": 0, "anomaly_hours": 0, "anomaly_rate_pct": 0.0},
            "module_status": "no_data",
            "message": "查询范围内暂无数据。",
        }

    # Check if expected values are populated
    has_expected = any(r[2] is not None for r in rows)

    records = []
    anomaly_count = 0
    for row in rows:
        ts, actual, rated, hvac_mode, sched_f, is_anom, phase, hvac_diag = row
        ts_str = ts.isoformat() if ts else None
        dev_pct: float | None = None
        if actual is not None and rated is not None and rated > 1e-9:
            dev_pct = round((actual - rated) / rated * 100, 2)
        if is_anom:
            anomaly_count += 1
        records.append({
            "timestamp": ts_str,
            "actual": round(float(actual), 4) if actual is not None else None,
            "rated": round(float(rated), 4) if rated is not None else None,
            "deviation_pct": dev_pct,
            "hvac_mode": hvac_mode,
            "schedule_factor": round(float(sched_f), 4) if sched_f is not None else None,
            "is_anomaly": bool(is_anom) if is_anom is not None else False,
            "anomaly_phase": phase,
            "hvac_diagnosis": hvac_diag,
            "expected_source": "notebook_baseline",
        })

    total = len(records)
    anom_rate = round(anomaly_count / total * 100, 2) if total > 0 else 0.0

    return {
        "building_type": building.building_type,
        "building_id": building.building_id,
        "metric": metric,
        "unit": unit,
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "records": records,
        "summary": {
            "total_hours": total,
            "anomaly_hours": anomaly_count,
            "anomaly_rate_pct": anom_rate,
        },
        "module_status": "ok" if has_expected else "no_expected_data",
        "message": None if has_expected else "kpi_expected_hourly 暂无数据，请先调用 /api/admin/rebuild-all",
    }


# ---------------------------------------------------------------------------
# 负荷曲线：按小时 / 按星期聚合（首页节律热力图、工作时段图等）
# ---------------------------------------------------------------------------
_LOAD_PROFILE_METRICS: dict[str, str] = {
    "electricity": "electricity_kwh",
    "water": "water_m3",
    "hac_energy": "hac_energy",
    "air_temp": "air_temp_c",
    "humidity": "humidity_rh_pct",
    "supply_temp": "sim_supply_temp_c",
    "return_temp": "sim_return_temp_c",
}

_PEAK_VALLEY_METRICS: frozenset[str] = frozenset({
    "electricity",
    "water",
    "hac_energy",
})

_WD_LABELS: dict[int, str] = {
    1: "周一",
    2: "周二",
    3: "周三",
    4: "周四",
    5: "周五",
    6: "周六",
    7: "周日",
}


async def _get_latest_energy_timestamp(
    db: AsyncSession,
    building_id: str,
) -> datetime | None:
    latest_row = await db.execute(
        select(EnergyData.timestamp)
        .where(EnergyData.building_id == building_id)
        .order_by(EnergyData.timestamp.desc())
        .limit(1)
    )
    return latest_row.scalar_one_or_none()


def _build_empty_load_profile_payload(
    *,
    building_type: str,
    building_id: str,
    metric: str,
    days: int,
) -> dict[str, Any]:
    return {
        "building_type": building_type,
        "building_id": building_id,
        "metric": metric,
        "days": days,
        "window_end": None,
        "window_start": None,
        "hourly_profile": [],
        "weekday_profile": [],
    }


async def _get_load_profile_payloads(
    db: AsyncSession,
    *,
    building_type: str,
    building_id: str,
    metrics: list[str],
    days: int,
) -> dict[str, dict[str, Any]]:
    max_ts = await _get_latest_energy_timestamp(db, building_id)
    if max_ts is None:
        return {
            metric: _build_empty_load_profile_payload(
                building_type=building_type,
                building_id=building_id,
                metric=metric,
                days=days,
            )
            for metric in metrics
        }

    if max_ts.tzinfo is None:
        end_dt = max_ts.replace(tzinfo=timezone.utc)
    else:
        end_dt = max_ts.astimezone(timezone.utc)
    start_dt = end_dt - timedelta(days=days)

    select_hour_parts = ["EXTRACT(HOUR FROM e.timestamp)::int AS hr", "COUNT(*)::int AS sample_count"]
    select_weekday_parts = ["EXTRACT(ISODOW FROM e.timestamp)::int AS wd", "COUNT(*)::int AS sample_count"]
    for metric in metrics:
        col = _LOAD_PROFILE_METRICS[metric]
        select_hour_parts.append(f'AVG(e.{col})::float AS "{metric}"')
        select_weekday_parts.append(f'AVG(e.{col})::float AS "{metric}"')

    hourly_sql = text(
        f"""
        SELECT {", ".join(select_hour_parts)}
          FROM energy_data e
         WHERE e.building_id = :bid
           AND e.timestamp >= :t0
           AND e.timestamp <= :t1
         GROUP BY hr
         ORDER BY hr
        """
    )
    weekday_sql = text(
        f"""
        SELECT {", ".join(select_weekday_parts)}
          FROM energy_data e
         WHERE e.building_id = :bid
           AND e.timestamp >= :t0
           AND e.timestamp <= :t1
         GROUP BY wd
         ORDER BY wd
        """
    )

    params = {"bid": building_id, "t0": start_dt, "t1": end_dt}
    hourly_rows = (await db.execute(hourly_sql, params)).mappings().all()
    weekday_rows = (await db.execute(weekday_sql, params)).mappings().all()

    payloads: dict[str, dict[str, Any]] = {}
    for metric in metrics:
        hourly_map = {
            int(row["hr"]): (
                float(row[metric] or 0),
                int(row["sample_count"] or 0),
            )
            for row in hourly_rows
            if row["hr"] is not None
        }
        weekday_map = {
            int(row["wd"]): (
                float(row[metric] or 0),
                int(row["sample_count"] or 0),
            )
            for row in weekday_rows
            if row["wd"] is not None
        }

        payloads[metric] = {
            "building_type": building_type,
            "building_id": building_id,
            "metric": metric,
            "days": days,
            "window_end": end_dt.isoformat(),
            "window_start": start_dt.isoformat(),
            "hourly_profile": [
                {
                    "hour": hour,
                    "avg_value": round(hourly_map.get(hour, (0.0, 0))[0], 4),
                    "sample_count": hourly_map.get(hour, (0.0, 0))[1],
                    "anomaly_count": 0,
                }
                for hour in range(24)
            ],
            "weekday_profile": [
                {
                    "weekday": wd,
                    "label": _WD_LABELS.get(wd, str(wd)),
                    "avg_value": round(weekday_map.get(wd, (0.0, 0))[0], 4),
                    "sample_count": weekday_map.get(wd, (0.0, 0))[1],
                }
                for wd in range(1, 8)
            ],
        }

    return payloads


@router.get(
    "/buildings/{building_type}/load-profile",
    summary="按小时与星期聚合负荷曲线",
)
async def get_load_profile(
    building_type: str,
    metric: str = Query(
        "electricity",
        description="指标：electricity | water | hac_energy",
    ),
    days: int = Query(14, ge=1, le=90, description="回溯天数，以库内最新时间为终点"),
    db: AsyncSession = Depends(get_db_session),
    building_id: str | None = None,
):
    """从 energy_data 聚合小时均值与星期均值，供首页节律类图表使用。"""
    if metric not in _LOAD_PROFILE_METRICS:
        raise HTTPException(
            status_code=400,
            detail=f"metric 只能为：{list(_LOAD_PROFILE_METRICS.keys())}",
        )

    building = await _require_building_context(
        db,
        building_type=building_type,
        building_id=building_id,
    )
    payloads = await _get_load_profile_payloads(
        db,
        building_type=building.building_type,
        building_id=building.building_id,
        metrics=[metric],
        days=days,
    )
    return payloads[metric]


# ---------------------------------------------------------------------------
# 峰谷统计：按日汇总后的峰值、谷值、峰谷比、夜间异常小时数
# ---------------------------------------------------------------------------
@router.get(
    "/buildings/{building_type}/peak-valley-stats",
    summary="峰谷与夜间高耗统计",
)
async def get_peak_valley_stats(
    building_type: str,
    metric: str = Query("electricity", description="指标：electricity | water | hac_energy"),
    days: int = Query(7, ge=1, le=90),
    night_threshold: float = Query(
        50.0,
        description="夜间单小时判定阈值（电 kWh；水/暖通按同列数值）",
    ),
    db: AsyncSession = Depends(get_db_session),
    building_id: str | None = None,
):
    if metric not in _PEAK_VALLEY_METRICS:
        raise HTTPException(
            status_code=400,
            detail=f"峰谷统计 metric 只能为：{sorted(_PEAK_VALLEY_METRICS)}",
        )
    col = _LOAD_PROFILE_METRICS[metric]

    building = await _require_building_context(
        db,
        building_type=building_type,
        building_id=building_id,
    )

    max_ts = await _get_latest_energy_timestamp(db, building.building_id)
    if max_ts is None:
        return {
            "building_type": building.building_type,
            "building_id": building.building_id,
            "metric": metric,
            "days": days,
            "peak_value": None,
            "valley_value": None,
            "avg_value": None,
            "peak_valley_ratio": None,
            "night_abnormal_hours": 0,
            "daily_totals": [],
        }

    if max_ts.tzinfo is None:
        end_dt = max_ts.replace(tzinfo=timezone.utc)
    else:
        end_dt = max_ts.astimezone(timezone.utc)
    start_dt = end_dt - timedelta(days=days)

    daily_sql = text(
        f"""
        SELECT date_trunc('day', e.timestamp AT TIME ZONE 'UTC')::date AS d,
               SUM(e.{col})::float AS total
          FROM energy_data e
         WHERE e.building_id = :bid
           AND e.timestamp >= :t0
           AND e.timestamp <= :t1
         GROUP BY d
         ORDER BY d
        """
    )
    d_result = await db.execute(
        daily_sql, {"bid": building.building_id, "t0": start_dt, "t1": end_dt}
    )
    daily_rows = d_result.fetchall()
    daily_totals: list[dict[str, Any]] = []
    totals: list[float] = []
    for d, total in daily_rows:
        t = float(total or 0)
        totals.append(t)
        day_str = d.isoformat() if hasattr(d, "isoformat") else str(d)
        daily_totals.append({"day": day_str, "total": round(t, 4)})

    if not totals:
        peak = valley = avg = None
        ratio = None
    else:
        peak = max(totals)
        valley = min(totals)
        avg = sum(totals) / len(totals)
        ratio = round(peak / valley, 3) if valley and valley > 1e-9 else None
        peak = round(peak, 4)
        valley = round(valley, 4)
        avg = round(avg, 4)

    night_sql = text(
        f"""
        SELECT COUNT(*)::int
          FROM energy_data e
         WHERE e.building_id = :bid
           AND e.timestamp >= :t0
           AND e.timestamp <= :t1
           AND (MOD((EXTRACT(HOUR FROM e.timestamp AT TIME ZONE 'UTC')::int + 8), 24)) < 6
           AND e.{col} > :thr
        """
    )
    n_result = await db.execute(
        night_sql,
        {"bid": building.building_id, "t0": start_dt, "t1": end_dt, "thr": night_threshold},
    )
    night_abnormal_hours = int(n_result.scalar() or 0)

    return {
        "building_type": building.building_type,
        "building_id": building.building_id,
        "metric": metric,
        "days": days,
        "night_threshold": night_threshold,
        "window_end": end_dt.isoformat(),
        "window_start": start_dt.isoformat(),
        "peak_value": peak,
        "valley_value": valley,
        "avg_value": avg,
        "peak_valley_ratio": ratio,
        "night_abnormal_hours": night_abnormal_hours,
        "daily_totals": daily_totals,
    }


# ---------------------------------------------------------------------------
# Dashboard KPI 总览（全局汇总，取数据库最新一天的汇总数据）
# ---------------------------------------------------------------------------
@router.get("/overview", summary="获取 Dashboard KPI 总览")
async def get_overview(
    query_date: date | None = Query(None, alias="date", description="指定日期 YYYY-MM-DD，默认取最新日期"),
    db: AsyncSession = Depends(get_db_session),
):
    """
    返回所有建筑的 KPI 汇总数据（指定日期或最新可用日期），供 Dashboard 使用。
    包含：各楼总用电、总用水、最新设备状态快照。
    直接从 energy_data 聚合，不依赖物化视图，确保数据实时。
    """
    if query_date:
        cache_key = f"overview:date:{query_date.isoformat()}"
    else:
        cache_key = f"overview:latest:{cache_bucket()}"

    ttl_seconds = settings.CACHE_OVERVIEW_TTL_SECONDS

    async def _compute() -> dict[str, Any]:
        # 确定目标日期：优先用请求参数，否则取最新一天
        if query_date:
            target_day = query_date
        else:
            latest_ts_result = await db.execute(
                text('SELECT MAX("timestamp")::date AS latest_day FROM energy_data')
            )
            row = latest_ts_result.fetchone()
            target_day = row[0] if row else None
        if not target_day:
            return {"error": "暂无能耗数据"}

        # 用时间戳范围代替 ::date 转换，避免时区问题
        day_start = datetime(
            target_day.year,
            target_day.month,
            target_day.day,
            tzinfo=timezone.utc,
        )
        day_end = day_start + timedelta(days=1)

        # 按楼宇聚合当天数据（电、水、温度）
        daily_result = await db.execute(
            text("""
                SELECT
                    e.building_id,
                    b.primary_space_usage,
                    b.sqm,
                    SUM(e.electricity_kwh)  AS total_electricity_kwh,
                    SUM(e.water_m3)         AS total_water_m3,
                    AVG(e.air_temp_c)       AS avg_ambient_temp,
                    SUM(e.hac_energy)       AS total_hac_energy
                FROM energy_data e
                JOIN buildings b ON e.building_id = b.building_id
                WHERE e."timestamp" >= :day_start
                  AND e."timestamp" <  :day_end
                GROUP BY e.building_id, b.primary_space_usage, b.sqm
                ORDER BY b.primary_space_usage
            """),
            {"day_start": day_start, "day_end": day_end},
        )
        daily_rows = daily_result.fetchall()

        if not daily_rows:
            return {"error": f"日期 {target_day} 无能耗数据"}

        # 全局平均气温和湿度（当天所有建筑平均）
        weather_result = await db.execute(
            text("""
                SELECT
                    AVG(e.air_temp_c)       AS avg_temp,
                    AVG(e.humidity_rh_pct)  AS avg_humidity
                FROM energy_data e
                WHERE e."timestamp" >= :day_start
                  AND e."timestamp" <  :day_end
            """),
            {"day_start": day_start, "day_end": day_end},
        )
        weather_row = weather_result.fetchone()
        global_avg_temp = (
            round(float(weather_row[0]), 1)
            if weather_row and weather_row[0]
            else None
        )
        global_avg_humidity = (
            round(float(weather_row[1]), 1)
            if weather_row and weather_row[1]
            else None
        )

        # 各楼最新一条实时记录（实时读数）
        live_result = await db.execute(
            text("""
                SELECT DISTINCT ON (e.building_id)
                    e.building_id,
                    b.primary_space_usage,
                    e.water_m3,
                    e.hac_energy,
                    e.air_temp_c
                FROM energy_data e
                JOIN buildings b ON e.building_id = b.building_id
                ORDER BY e.building_id, e."timestamp" DESC
            """)
        )
        live_map: dict[str, tuple] = {r[0]: r for r in live_result.fetchall()}

        # 从 anomaly_events 查询有未解决异常的楼宇（24h 窗口）
        anomaly_building_ids: set[str] = set()
        try:
            anomaly_result = await db.execute(
                text("""
                    SELECT DISTINCT building_id
                    FROM anomaly_events
                    WHERE data_timestamp >= (
                        SELECT MAX(data_timestamp) FROM anomaly_events
                    ) - INTERVAL '24 hours'
                      AND is_resolved = false
                """)
            )
            anomaly_building_ids = {r[0] for r in anomaly_result.fetchall()}
        except Exception:
            pass

        total_electricity = 0.0
        total_water = 0.0
        total_hac = 0.0
        buildings_detail = []

        for dr in daily_rows:
            bid, usage, sqm, total_elec, total_w, bld_avg_temp, hac = dr
            live = live_map.get(bid)
            latest_w = float(live[2] or 0) if live else 0.0
            is_anomaly = bid in anomaly_building_ids
            intensity = (
                round(float(total_elec or 0) / float(sqm), 2)
                if sqm and sqm > 0
                else None
            )
            total_electricity += float(total_elec or 0)
            total_water += float(total_w or 0)
            total_hac += float(hac or 0)
            buildings_detail.append({
                "building_type": usage,
                "display_name": get_building_label(usage or "", usage or bid),
                "icon": get_building_icon(usage),
                "total_electricity_kwh": round(float(total_elec or 0), 2),
                "total_water_m3": round(float(total_w or 0), 2),
                "total_hac_energy_kwh": round(float(hac or 0), 2),
                "avg_ambient_temp": round(float(bld_avg_temp or 0), 1) if bld_avg_temp else None,
                "sqm": sqm,
                "energy_intensity_kwh_per_sqm": intensity,
                "anomaly_status": "Anomaly" if is_anomaly else "Normal",
                "latest_water_m3": latest_w,
            })

        # ---------- 昨日数据对比，计算变化百分比 ----------
        yesterday_start = day_start - timedelta(days=1)
        yesterday_end = day_start  # 即 today 的 day_start

        yesterday_result = await db.execute(
            text("""
                SELECT
                    b.primary_space_usage,
                    SUM(e.electricity_kwh)  AS total_electricity_kwh,
                    SUM(e.water_m3)         AS total_water_m3,
                    SUM(e.hac_energy)       AS total_hac_energy
                FROM energy_data e
                JOIN buildings b ON e.building_id = b.building_id
                WHERE e."timestamp" >= :yday_start
                  AND e."timestamp" <  :yday_end
                GROUP BY b.primary_space_usage
            """),
            {"yday_start": yesterday_start, "yday_end": yesterday_end},
        )
        yesterday_rows = yesterday_result.fetchall()

        def _pct(today_val: float, yest_val: float) -> float | None:
            if yest_val and yest_val > 0:
                return round((today_val - yest_val) / yest_val * 100, 1)
            return None

        # 按楼宇类型汇总昨日数据
        yest_by_type: dict[str, dict] = {}
        yest_total_elec = 0.0
        yest_total_water = 0.0
        yest_total_hac = 0.0
        for yr in yesterday_rows:
            usage, y_elec, y_water, y_hac = yr
            y_elec_f = float(y_elec or 0)
            y_water_f = float(y_water or 0)
            y_hac_f = float(y_hac or 0)
            yest_total_elec += y_elec_f
            yest_total_water += y_water_f
            yest_total_hac += y_hac_f
            yest_by_type[usage] = {
                "electricity": y_elec_f,
                "water": y_water_f,
                "hac": y_hac_f,
            }

        # 为每栋楼添加变化百分比
        for bd in buildings_detail:
            bt = bd["building_type"]
            yd = yest_by_type.get(bt)
            if yd:
                bd["electricity_change_pct"] = _pct(bd["total_electricity_kwh"], yd["electricity"])
                bd["water_change_pct"] = _pct(bd["total_water_m3"], yd["water"])
                bd["hac_change_pct"] = _pct(bd["total_hac_energy_kwh"], yd["hac"])
                bd_carbon_today = bd["total_electricity_kwh"] * 0.5703
                bd_carbon_yest = yd["electricity"] * 0.5703
                bd["carbon_change_pct"] = _pct(bd_carbon_today, bd_carbon_yest)
            else:
                bd["electricity_change_pct"] = None
                bd["water_change_pct"] = None
                bd["hac_change_pct"] = None
                bd["carbon_change_pct"] = None

        # 全局变化百分比
        kpis_change = {
            "total_electricity_pct": _pct(total_electricity, yest_total_elec),
            "total_water_pct": _pct(total_water, yest_total_water),
            "total_hac_pct": _pct(total_hac, yest_total_hac),
            "total_carbon_pct": _pct(total_electricity * 0.5703, yest_total_elec * 0.5703),
        }

        # ---------- 预测预警摘要 ----------
        prediction_warning_count = 0
        prediction_building_map: dict[str, dict] = {}
        try:
            pred_result = await db.execute(text("""
                SELECT
                    p.building_id,
                    COUNT(*) AS cnt,
                    MAX(CASE WHEN p.risk_level = 'critical' THEN 1 ELSE 0 END) AS has_critical
                FROM predicted_anomaly_events p
                WHERE p.created_at >= (
                    SELECT MAX(created_at) FROM predicted_anomaly_events
                ) - INTERVAL '24 hours'
                GROUP BY p.building_id
            """))
            for row in pred_result.fetchall():
                pbid, pcnt, pcrit = row
                prediction_warning_count += pcnt
                prediction_building_map[pbid] = {
                    "count": pcnt,
                    "risk_level": "critical" if pcrit else "warning",
                }
        except Exception:
            pass

        for bd in buildings_detail:
            bt = bd["building_type"]
            bid_for_pred = BUILDING_TYPE_TO_ID.get(bt)
            pred_info = prediction_building_map.get(bid_for_pred or "", {})
            bd["prediction_warning_count"] = pred_info.get("count", 0)
            bd["prediction_status"] = pred_info.get("risk_level", "normal")

        return {
            "data_date": target_day.isoformat() if hasattr(target_day, "isoformat") else str(target_day),
            "kpis": {
                "total_electricity_kwh": round(total_electricity, 2),
                "total_water_m3": round(total_water, 2),
                "total_hac_energy_kwh": round(total_hac, 2),
                "total_carbon_kg": round(total_electricity * 0.5703, 2),
                "anomaly_count": len(anomaly_building_ids),
                "prediction_warning_count": prediction_warning_count,
            },
            "kpis_change": kpis_change,
            "weather": {
                "temperature": global_avg_temp,
                "humidity": global_avg_humidity,
            },
            "buildings": buildings_detail,
        }

    return await get_or_compute_json(cache_key, ttl_seconds, _compute)


# ---------------------------------------------------------------------------
# 近期异常告警（Dashboard / 运维页 统一数据源）
# ---------------------------------------------------------------------------
@router.get("/anomalies/recent", summary="获取近期异常告警")
async def get_recent_anomalies(
    hours: int = Query(168, ge=1, le=8760, description="查询最近 N 小时内的异常（默认 7 天，最大 1 年）"),
    building_type: str | None = Query(None, description="按建筑类型过滤"),
    only_unresolved: bool = Query(False, description="是否只返回未解决的异常，默认返回全部"),
    db: AsyncSession = Depends(get_db_session),
    building_id: str | None = None,
):
    cache_key = (
        "anomalies:recent:"
        f"{hours}:"
        f"{building_type or 'all'}:"
        f"{building_id or 'all'}:"
        f"{'unresolved' if only_unresolved else 'all'}:"
        f"{cache_bucket()}"
    )
    ttl_seconds = settings.CACHE_ANOMALIES_RECENT_TTL_SECONDS

    async def _compute() -> dict[str, Any]:
        return await _get_recent_anomalies_payload(
            db=db,
            hours=hours,
            building_type=building_type,
            only_unresolved=only_unresolved,
            building_id=building_id,
        )

    return await get_or_compute_json(cache_key, ttl_seconds, _compute)


# ---------------------------------------------------------------------------
# 异常根因桑基图（Sankey）聚合数据
# ---------------------------------------------------------------------------
_RULE_LABEL = {
    # 旧版规则（兼容）
    "water_leak": "水耗异常",
    "electricity_overload": "电耗超标",
    "hvac_overconsumption": "空调过耗",
    "supply_temp_deviation": "供水温度偏离",
    "return_temp_deviation": "回水温度偏离",
    "db_flagged": "标注异常",
    "night_high_power": "夜间高耗",
    # notebook v2 规则
    "flag_water": "水耗偏高",
    "flag_electricity": "总电耗偏高",
    "flag_hvac_energy": "空调能耗偏高",
    "flag_supply_deviation": "供水温度偏离",
    "flag_return_deviation": "回水温度偏离",
}

_ROOT_CAUSE_LABEL = {
    "A_low_efficiency": "主机效能衰退",
    "B_small_deltaT": "水力失调",
    "C_unexpected_on": "非预期开机",
    "other_hvac": "其他空调故障",
}


@router.get("/anomalies/sankey", summary="异常根因桑基图聚合数据")
async def get_anomaly_sankey(
    db: AsyncSession = Depends(get_db_session),
    building_id: str | None = None,
):
    cache_key = f"anomalies:sankey:{building_id or 'all'}:{cache_bucket()}"
    ttl_seconds = settings.CACHE_ANOMALIES_SANKEY_TTL_SECONDS

    async def _compute() -> dict[str, Any]:
        return await _get_anomaly_sankey_payload(db, building_id=building_id)

    return await get_or_compute_json(cache_key, ttl_seconds, _compute)


async def _get_anomaly_sankey_payload(
    db: AsyncSession,
    *,
    building_id: str | None = None,
) -> dict[str, Any]:
    filters = ["is_resolved = false"]
    params: dict[str, Any] = {}
    if building_id:
        filters.append("building_id = :bid")
        params["bid"] = building_id

    agg_result = await db.execute(text(f"""
        SELECT
            rule_triggered,
            hvac_root_cause,
            COUNT(*) AS cnt
        FROM anomaly_events
        WHERE {' AND '.join(filters)}
        GROUP BY rule_triggered, hvac_root_cause
        ORDER BY cnt DESC
    """), params)
    rows = agg_result.fetchall()

    if not rows:
        return {
            "nodes": [],
            "links": [],
            "module_status": "no_data",
            "message": "anomaly_events 暂无数据，请先调用 /api/admin/rebuild-all",
        }

    node_set: list[str] = []

    def _node_idx(name: str) -> int:
        if name not in node_set:
            node_set.append(name)
        return node_set.index(name)

    links: list[dict[str, Any]] = []
    for rule, root_cause, cnt in rows:
        rule_label = _RULE_LABEL.get(rule, rule)
        if root_cause:
            cause_label = _ROOT_CAUSE_LABEL.get(root_cause, root_cause)
        else:
            cause_label = f"{rule_label}(直接)"

        src_idx = _node_idx(rule_label)
        tgt_idx = _node_idx(cause_label)
        links.append({"source": src_idx, "target": tgt_idx, "value": int(cnt)})

    nodes = [{"name": name} for name in node_set]
    return {
        "nodes": nodes,
        "links": links,
        "module_status": "ok",
    }


# ---------------------------------------------------------------------------
# 实时风险预警（预警通知 Tab 数据源）
# ---------------------------------------------------------------------------

_HVAC_MODE_LABEL: dict[str, str] = {
    "Cooling":     "制冷",
    "Heating":     "供暖",
    "Ventilation": "通风",
}


@router.get("/buildings/risk-now", summary="当前各楼宇实时能耗风险评估")
async def get_risk_now(db: AsyncSession = Depends(get_db_session)):
    """
    对所有楼宇调用 gb_simulator，返回当前时刻的实时风险等级。
    取各建筑最新一条 energy_data 中的天气数据，计算期望值后与实际比较。
    风险等级：high(偏差>30%) / medium(15-30%) / low(0-15%) / normal(无偏差或节能)
    """
    now = datetime.now(timezone.utc)

    latest_ts_subquery = (
        select(
            EnergyData.building_id.label("building_id"),
            func.max(EnergyData.timestamp).label("latest_ts"),
        )
        .group_by(EnergyData.building_id)
        .subquery()
    )

    result = await db.execute(
        select(Building, EnergyData)
        .join(
            latest_ts_subquery,
            latest_ts_subquery.c.building_id == Building.building_id,
        )
        .join(
            EnergyData,
            and_(
                EnergyData.building_id == latest_ts_subquery.c.building_id,
                EnergyData.timestamp == latest_ts_subquery.c.latest_ts,
            ),
        )
        .order_by(Building.building_id)
    )
    building_rows = result.all()

    risk_items: list[dict] = []

    for building, latest in building_rows:
        air_temp  = latest.air_temp_c  or 20.0
        dew_temp  = latest.dew_temp_c  or 10.0

        rated = calculate_rated_values(
            sqm=building.sqm or 1000.0,
            primary_space_usage=building.primary_space_usage or "Office",
            hour=now.hour,
            dayofweek=now.isoweekday(),
            air_temp=air_temp,
            dew_temp=dew_temp,
        )

        actual_hac = latest.hac_energy
        risk_level = "normal"
        deviation_pct: float | None = None
        risk_desc = "运行在期望范围内"

        if actual_hac is not None and rated.rated_hac_energy > 0.5:
            dev = (actual_hac - rated.rated_hac_energy) / rated.rated_hac_energy * 100
            deviation_pct = round(dev, 1)
            if dev >= 30:
                risk_level = "high"
                risk_desc  = f"空调能耗超预测值 {dev:.0f}%，建议立即检查"
            elif dev >= 15:
                risk_level = "medium"
                risk_desc  = f"空调能耗偏高 {dev:.0f}%，请关注运行状态"
            elif dev > 0:
                risk_level = "low"
                risk_desc  = f"空调能耗略高于预测 {dev:.0f}%"
            else:
                risk_level = "normal"
                risk_desc  = "运行在期望范围内"
        elif rated.schedule_factor <= 0.05:
            risk_desc = "当前为非工作时段，低负荷运行"

        risk_items.append({
            "building_id":          building.building_id,
            "building_name":        get_building_label(
                                        building.primary_space_usage or building.building_id,
                                        building.building_id,
                                    ),
            "building_type":        building.primary_space_usage,
            "hvac_mode":            rated.hvac_mode,
            "hvac_mode_label":      _HVAC_MODE_LABEL.get(rated.hvac_mode, rated.hvac_mode),
            "expected_hac":         round(rated.rated_hac_energy, 2),
            "expected_supply_temp": rated.expected_supply_temp,
            "schedule_factor":      rated.schedule_factor,
            "air_temp":             air_temp,
            "risk_level":           risk_level,
            "deviation_pct":        deviation_pct,
            "risk_desc":            risk_desc,
            "data_timestamp":       latest.timestamp.isoformat(),
        })

    # 高风险排最前
    _order = {"high": 0, "medium": 1, "low": 2, "normal": 3}
    risk_items.sort(key=lambda x: _order.get(x["risk_level"], 9))

    return {"risks": risk_items, "evaluated_at": now.isoformat()}


async def _get_recent_predictions_payload(
    db: AsyncSession,
    hours: int,
    building_type: str | None,
    risk_level: str | None,
) -> dict[str, Any]:
    max_ts_result = await db.execute(
        text("SELECT MAX(created_at) FROM predicted_anomaly_events")
    )
    max_ts = max_ts_result.scalar()

    if max_ts is None:
        return {
            "predictions": [],
            "total": 0,
            "check_period": {"start": None, "end": None, "hours": hours},
            "message": "predicted_anomaly_events 暂无数据，请先调用 /api/admin/run-forecast",
        }

    if hasattr(max_ts, "tzinfo") and max_ts.tzinfo is None:
        max_ts = max_ts.replace(tzinfo=timezone.utc)

    window_start = max_ts - timedelta(hours=hours)
    conditions = "WHERE p.created_at >= :t0 AND p.created_at <= :t1"
    params: dict[str, Any] = {"t0": window_start, "t1": max_ts}

    if building_type:
        bld_result = await db.execute(
            select(Building.building_id).where(
                Building.primary_space_usage == building_type
            )
        )
        bid = bld_result.scalar_one_or_none()
        if bid:
            conditions += " AND p.building_id = :bid"
            params["bid"] = bid

    if risk_level:
        conditions += " AND p.risk_level = :rlevel"
        params["rlevel"] = risk_level

    result = await db.execute(text(f"""
        SELECT
            p.id,
            p.created_at,
            p.as_of_timestamp,
            p.forecast_for_timestamp,
            p.horizon_h,
            p.building_id,
            p.metric_name,
            p.predicted_value,
            p.expected_value,
            p.deviation_pct,
            p.risk_level,
            p.rule_triggered,
            p.model_name,
            p.is_confirmed
        FROM predicted_anomaly_events p
        {conditions}
        ORDER BY p.created_at DESC
        LIMIT 200
    """), params)

    rows = result.fetchall()
    predictions = []
    for row in rows:
        (pid, created, as_of, forecast_for, horizon, bid, metric,
         pred_val, exp_val, dev_pct, rlevel, rule, model, confirmed) = row
        bt = normalize_building_type(bid) or bid
        predictions.append({
            "id": pid,
            "created_at": created.isoformat() if created else None,
            "as_of_timestamp": as_of.isoformat() if as_of else None,
            "forecast_for_timestamp": forecast_for.isoformat() if forecast_for else None,
            "horizon_h": horizon,
            "building_id": bid,
            "building_name": get_building_label(bt, bt),
            "building_type": bt,
            "metric_name": metric,
            "predicted_value": pred_val,
            "expected_value": exp_val,
            "deviation_pct": dev_pct,
            "risk_level": rlevel,
            "rule_triggered": rule,
            "model_name": model,
            "is_confirmed": confirmed,
        })

    return {
        "predictions": predictions,
        "total": len(predictions),
        "check_period": {
            "start": window_start.isoformat(),
            "end": max_ts.isoformat(),
            "hours": hours,
        },
    }


# ---------------------------------------------------------------------------
# 预测预警查询
# ---------------------------------------------------------------------------
@router.get("/predictions/recent", summary="获取近期预测预警")
async def get_recent_predictions(
    hours: int = Query(168, ge=1, le=8760, description="查询最近 N 小时内的预测预警（默认 7 天）"),
    building_type: str | None = Query(None, description="按建筑类型过滤"),
    risk_level: str | None = Query(None, description="按风险等级过滤（warning/critical）"),
    db: AsyncSession = Depends(get_db_session),
):
    cache_key = (
        "predictions:recent:"
        f"{hours}:"
        f"{building_type or 'all'}:"
        f"{risk_level or 'all'}:"
        f"{cache_bucket()}"
    )
    ttl_seconds = settings.CACHE_PREDICTIONS_RECENT_TTL_SECONDS

    async def _compute() -> dict[str, Any]:
        return await _get_recent_predictions_payload(
            db=db,
            hours=hours,
            building_type=building_type,
            risk_level=risk_level,
        )

    return await get_or_compute_json(cache_key, ttl_seconds, _compute)


@router.get("/predictions/summary", summary="预测预警按楼宇聚合摘要")
async def get_predictions_summary(
    hours: int = Query(168, ge=1, le=8760, description="统计最近 N 小时（默认 7 天）"),
    db: AsyncSession = Depends(get_db_session),
):
    """
    按楼宇聚合最近一段时间的预测预警数，返回最新预测时间与风险摘要。
    对齐 /buildings/risk-now 的返回结构。
    """
    max_ts_result = await db.execute(
        text("SELECT MAX(created_at) FROM predicted_anomaly_events")
    )
    max_ts = max_ts_result.scalar()

    if max_ts is None:
        return {"buildings": [], "latest_prediction_at": None, "total_warnings": 0}

    if hasattr(max_ts, "tzinfo") and max_ts.tzinfo is None:
        max_ts = max_ts.replace(tzinfo=timezone.utc)

    window_start = max_ts - timedelta(hours=hours)

    result = await db.execute(text("""
        SELECT
            p.building_id,
            COUNT(*) AS warning_count,
            MAX(p.created_at) AS latest,
            COUNT(DISTINCT p.metric_name) AS metric_count,
            MAX(CASE WHEN p.risk_level = 'critical' THEN 1 ELSE 0 END) AS has_critical
        FROM predicted_anomaly_events p
        WHERE p.created_at >= :t0 AND p.created_at <= :t1
        GROUP BY p.building_id
        ORDER BY warning_count DESC
    """), {"t0": window_start, "t1": max_ts})

    rows = result.fetchall()
    buildings = []
    total_warnings = 0
    for row in rows:
        bid, cnt, latest, metric_cnt, has_crit = row
        bt = normalize_building_type(bid) or bid
        total_warnings += cnt
        buildings.append({
            "building_id": bid,
            "building_type": bt,
            "building_name": get_building_label(bt, bt),
            "warning_count": cnt,
            "latest_prediction_at": latest.isoformat() if latest else None,
            "metric_count": metric_cnt,
            "risk_level": "critical" if has_crit else "warning",
        })

    return {
        "buildings": buildings,
        "latest_prediction_at": max_ts.isoformat(),
        "total_warnings": total_warnings,
    }


async def _get_home_bundle_core_payload() -> dict[str, Any]:
    async with AsyncSessionLocal() as db:
        overview = await get_overview(query_date=None, db=db)
        anomalies = await get_recent_anomalies(
            hours=168,
            building_type=None,
            only_unresolved=False,
            db=db,
        )
        sankey = await get_anomaly_sankey(db=db)
        return {
            "overview": overview,
            "anomalies": anomalies,
            "sankey": sankey,
        }


async def _get_home_bundle_for_building(
    building_type: str,
    overview_start: date,
    overview_end: date,
    public_section_start: date,
) -> dict[str, Any]:
    async with AsyncSessionLocal() as db:
        section_energy_start = public_section_start if building_type == "Public services" else overview_start
        energy = await get_building_energy_trend(
            building_type=building_type,
            start_date=section_energy_start,
            end_date=overview_end,
            include_water=True,
            include_device_status=False,
            db=db,
        )
        rated_electricity = await get_rated_vs_actual(
            building_type=building_type,
            start_date=overview_start,
            end_date=overview_end,
            metric="electricity",
            db=db,
        )
        rated_water = await get_rated_vs_actual(
            building_type=building_type,
            start_date=overview_start,
            end_date=overview_end,
            metric="water",
            db=db,
        )
        anomalies = await get_recent_anomalies(
            hours=168,
            building_type=building_type,
            only_unresolved=False,
            db=db,
        )

        overview_series = {
            "energy": energy,
            "rated_electricity": rated_electricity,
            "rated_water": rated_water,
        }

        if building_type == "Education":
            load_profile_electricity = await get_load_profile(
                building_type=building_type,
                metric="electricity",
                days=14,
                db=db,
            )
            load_profile_air_temp = await get_load_profile(
                building_type=building_type,
                metric="air_temp",
                days=14,
                db=db,
            )
            load_profile_supply_temp = await get_load_profile(
                building_type=building_type,
                metric="supply_temp",
                days=14,
                db=db,
            )
            load_profile_return_temp = await get_load_profile(
                building_type=building_type,
                metric="return_temp",
                days=14,
                db=db,
            )
            status = await get_building_status(building_type=building_type, db=db)
            section = {
                "load_profile_electricity": load_profile_electricity,
                "rated_vs_actual_electricity": rated_electricity,
                "anomalies": anomalies,
                "load_profile_air_temp": load_profile_air_temp,
                "load_profile_supply_temp": load_profile_supply_temp,
                "load_profile_return_temp": load_profile_return_temp,
                "status": status,
            }
        elif building_type == "Office":
            load_profile_electricity = await get_load_profile(
                building_type=building_type,
                metric="electricity",
                days=14,
                db=db,
            )
            peak_valley = await get_peak_valley_stats(
                building_type=building_type,
                metric="electricity",
                days=7,
                night_threshold=50.0,
                db=db,
            )
            section = {
                "load_profile_electricity": load_profile_electricity,
                "peak_valley": peak_valley,
                "energy": energy,
                "anomalies": anomalies,
            }
        else:
            load_profile_electricity = await get_load_profile(
                building_type=building_type,
                metric="electricity",
                days=14,
                db=db,
            )
            load_profile_air_temp = await get_load_profile(
                building_type=building_type,
                metric="air_temp",
                days=14,
                db=db,
            )
            load_profile_humidity = await get_load_profile(
                building_type=building_type,
                metric="humidity",
                days=14,
                db=db,
            )
            status = await get_building_status(building_type=building_type, db=db)
            section = {
                "energy": energy,
                "load_profile_electricity": load_profile_electricity,
                "load_profile_air_temp": load_profile_air_temp,
                "load_profile_humidity": load_profile_humidity,
                "anomalies": anomalies,
                "rated_vs_actual_electricity": rated_electricity,
                "status": status,
            }

        return {
            "building_type": building_type,
            "overview_series": overview_series,
            "section": section,
        }


async def _get_home_overview_series_payload(
    db: AsyncSession,
    *,
    context: _BuildingContext,
    overview_start: date,
    overview_end: date,
) -> dict[str, Any]:
    energy = await get_building_energy_trend(
        building_type=context.building_type,
        building_id=context.building_id,
        start_date=overview_start,
        end_date=overview_end,
        include_water=True,
        include_device_status=False,
        db=db,
    )
    rated_electricity = await get_rated_vs_actual(
        building_type=context.building_type,
        building_id=context.building_id,
        start_date=overview_start,
        end_date=overview_end,
        metric="electricity",
        db=db,
    )
    rated_water = await get_rated_vs_actual(
        building_type=context.building_type,
        building_id=context.building_id,
        start_date=overview_start,
        end_date=overview_end,
        metric="water",
        db=db,
    )
    return {
        "energy": energy,
        "rated_electricity": rated_electricity,
        "rated_water": rated_water,
    }


async def _get_home_section_overview_payload(
    db: AsyncSession,
    *,
    context: _BuildingContext,
) -> dict[str, Any]:
    anomalies = await get_recent_anomalies(
        hours=168,
        building_type=context.building_type,
        building_id=context.building_id,
        only_unresolved=False,
        db=db,
    )

    if context.building_type == "Office":
        peak_valley = await get_peak_valley_stats(
            building_type=context.building_type,
            building_id=context.building_id,
            metric="electricity",
            days=7,
            night_threshold=50.0,
            db=db,
        )
        return {
            "anomalies": anomalies,
            "peak_valley": peak_valley,
        }

    status = await get_building_status(
        building_type=context.building_type,
        building_id=context.building_id,
        db=db,
    )
    return {
        "anomalies": anomalies,
        "status": status,
    }


async def _get_home_section_charts_payload(
    db: AsyncSession,
    *,
    context: _BuildingContext,
    target_date: date,
) -> dict[str, Any]:
    overview_start = target_date - timedelta(days=6)
    public_section_start = target_date - timedelta(days=29)

    if context.building_type == "Education":
        load_profiles = await _get_load_profile_payloads(
            db,
            building_type=context.building_type,
            building_id=context.building_id,
            metrics=["electricity", "air_temp", "supply_temp", "return_temp"],
            days=14,
        )
        rated_electricity = await get_rated_vs_actual(
            building_type=context.building_type,
            building_id=context.building_id,
            start_date=overview_start,
            end_date=target_date,
            metric="electricity",
            db=db,
        )
        return {
            "load_profile_electricity": load_profiles["electricity"],
            "rated_vs_actual_electricity": rated_electricity,
            "load_profile_air_temp": load_profiles["air_temp"],
            "load_profile_supply_temp": load_profiles["supply_temp"],
            "load_profile_return_temp": load_profiles["return_temp"],
        }

    if context.building_type == "Office":
        energy = await get_building_energy_trend(
            building_type=context.building_type,
            building_id=context.building_id,
            start_date=overview_start,
            end_date=target_date,
            include_water=False,
            include_device_status=False,
            db=db,
        )
        load_profiles = await _get_load_profile_payloads(
            db,
            building_type=context.building_type,
            building_id=context.building_id,
            metrics=["electricity"],
            days=14,
        )
        return {
            "load_profile_electricity": load_profiles["electricity"],
            "energy": energy,
        }

    energy = await get_building_energy_trend(
        building_type=context.building_type,
        building_id=context.building_id,
        start_date=public_section_start,
        end_date=target_date,
        include_water=True,
        include_device_status=False,
        db=db,
    )
    load_profiles = await _get_load_profile_payloads(
        db,
        building_type=context.building_type,
        building_id=context.building_id,
        metrics=["electricity", "air_temp", "humidity"],
        days=14,
    )
    rated_electricity = await get_rated_vs_actual(
        building_type=context.building_type,
        building_id=context.building_id,
        start_date=overview_start,
        end_date=target_date,
        metric="electricity",
        db=db,
    )
    return {
        "energy": energy,
        "load_profile_electricity": load_profiles["electricity"],
        "load_profile_air_temp": load_profiles["air_temp"],
        "load_profile_humidity": load_profiles["humidity"],
        "rated_vs_actual_electricity": rated_electricity,
    }


def _merge_home_section_payloads(*payloads: dict[str, Any]) -> dict[str, Any]:
    merged: dict[str, Any] = {}
    for payload in payloads:
        merged.update(payload)
    return merged


async def _compute_home_overview_bundle_payload() -> dict[str, Any]:
    async with AsyncSessionLocal() as db:
        contexts = await _resolve_home_building_contexts(db)
        overview = await get_overview(query_date=None, db=db)
        anomalies = await get_recent_anomalies(
            hours=168,
            building_type=None,
            building_id=None,
            only_unresolved=False,
            db=db,
        )
        sankey = await get_anomaly_sankey(db=db, building_id=None)
        target_date = _resolve_bundle_data_date(overview)
        overview_start = target_date - timedelta(days=6)

        overview_series: dict[str, Any] = {}
        for building_type in _HOME_BUNDLE_BUILDING_TYPES:
            overview_series[building_type] = await _get_home_overview_series_payload(
                db,
                context=contexts[building_type],
                overview_start=overview_start,
                overview_end=target_date,
            )

        return {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "overview": overview,
            "anomalies": anomalies,
            "sankey": sankey,
            "overview_series": overview_series,
        }


async def _compute_home_section_bundle_payload(
    building_type: str,
    scope: str = "all",
) -> dict[str, Any]:
    async with AsyncSessionLocal() as db:
        context = await _require_building_context(db, building_type=building_type)
        target_date = await _get_latest_energy_data_date(db)
        if scope == "overview":
            payload = await _get_home_section_overview_payload(
                db,
                context=context,
            )
        elif scope == "charts":
            payload = await _get_home_section_charts_payload(
                db,
                context=context,
                target_date=target_date,
            )
        else:
            payload = _merge_home_section_payloads(
                await _get_home_section_overview_payload(
                    db,
                    context=context,
                ),
                await _get_home_section_charts_payload(
                    db,
                    context=context,
                    target_date=target_date,
                ),
            )
        return {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "data_date": target_date.isoformat(),
            "building_type": context.building_type,
            "scope": scope,
            **payload,
        }


async def _compute_home_bundle_payload() -> dict[str, Any]:
    async with AsyncSessionLocal() as db:
        contexts = await _resolve_home_building_contexts(db)
        overview = await get_overview(query_date=None, db=db)
        anomalies = await get_recent_anomalies(
            hours=168,
            building_type=None,
            building_id=None,
            only_unresolved=False,
            db=db,
        )
        sankey = await get_anomaly_sankey(db=db, building_id=None)
        target_date = _resolve_bundle_data_date(overview)
        overview_start = target_date - timedelta(days=6)

        overview_series: dict[str, Any] = {}
        sections: dict[str, Any] = {}
        for building_type in _HOME_BUNDLE_BUILDING_TYPES:
            context = contexts[building_type]
            overview_series[building_type] = await _get_home_overview_series_payload(
                db,
                context=context,
                overview_start=overview_start,
                overview_end=target_date,
            )
            sections[building_type] = _merge_home_section_payloads(
                await _get_home_section_overview_payload(
                    db,
                    context=context,
                ),
                await _get_home_section_charts_payload(
                    db,
                    context=context,
                    target_date=target_date,
                ),
            )

        return {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "overview": overview,
            "anomalies": anomalies,
            "sankey": sankey,
            "overview_series": overview_series,
            "sections": sections,
        }


@router.get("/home/overview-bundle", summary="获取首页首屏总览聚合数据")
async def get_home_overview_bundle():
    cache_key = "home:overview-bundle:v2"

    async def _compute() -> dict[str, Any]:
        return await _compute_home_overview_bundle_payload()

    return await get_or_compute_json(
        cache_key,
        _HOME_OVERVIEW_BUNDLE_TTL_SECONDS,
        _compute,
    )


@router.get("/home/section-bundle", summary="获取首页单个楼宇分区聚合数据")
async def get_home_section_bundle(
    building_type: str = Query(..., description="楼宇类型"),
    scope: str = Query("all", description="返回范围：overview | charts | all"),
):
    normalized_building_type = normalize_building_type(building_type) or building_type
    normalized_scope = scope.strip().lower()
    if normalized_scope not in _HOME_SECTION_BUNDLE_SCOPES:
        raise HTTPException(
            status_code=400,
            detail=f"scope 只能为：{sorted(_HOME_SECTION_BUNDLE_SCOPES)}",
        )
    cache_key = f"home:section-bundle:v2:{normalized_scope}:{normalized_building_type}"

    async def _compute() -> dict[str, Any]:
        return await _compute_home_section_bundle_payload(
            normalized_building_type,
            scope=normalized_scope,
        )

    return await get_or_compute_json(
        cache_key,
        _HOME_SECTION_BUNDLE_TTL_SECONDS,
        _compute,
    )


@router.get("/home/bundle", summary="获取首页聚合数据")
async def get_home_bundle():
    cache_key = f"home:bundle:latest:{cache_bucket()}"
    ttl_seconds = settings.CACHE_OVERVIEW_TTL_SECONDS

    async def _compute() -> dict[str, Any]:
        return await _compute_home_bundle_payload()

    return await get_or_compute_json(cache_key, ttl_seconds, _compute)


@router.get("/operations/bundle", summary="获取运维页聚合数据")
async def get_operations_bundle(
    anomaly_hours: int = Query(168, ge=1, le=8760, description="异常记录时间窗口（小时）"),
    prediction_hours: int = Query(168, ge=1, le=8760, description="预测预警时间窗口（小时）"),
    user: User | None = Depends(get_current_user_optional),
):
    assigned_to = user.id if user and user.role == "ops" else None
    user_scope = user.id if user else "anonymous"
    cache_key = (
        "operations:bundle:"
        f"{user_scope}:"
        f"{assigned_to or 'all'}:"
        f"{anomaly_hours}:"
        f"{prediction_hours}:"
        f"{cache_bucket()}"
    )
    ttl_seconds = settings.CACHE_WORKORDERS_TTL_SECONDS

    async def _compute() -> dict[str, Any]:
        async with AsyncSessionLocal() as db:
            anomalies = await get_recent_anomalies(
                hours=anomaly_hours,
                building_type=None,
                only_unresolved=False,
                db=db,
            )
            predictions = await get_recent_predictions(
                hours=prediction_hours,
                building_type=None,
                risk_level=None,
                db=db,
            )
            work_orders, total = await svc_list_work_orders(
                db,
                status_filter=["pending_approval"],
                building_id=None,
                priority=None,
                ai_fallback=None,
                assigned_to=assigned_to,
                page=1,
                page_size=20,
            )

            return {
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "anomaly_hours": anomaly_hours,
                "prediction_hours": prediction_hours,
                "anomalies": anomalies,
                "predictions": predictions,
                "pending_work_orders": {
                    "total": total,
                    "page": 1,
                    "page_size": 20,
                    "work_orders": [serialize_work_order(wo) for wo in work_orders],
                },
            }

    return await get_or_compute_json(cache_key, ttl_seconds, _compute)


# ---------------------------------------------------------------------------
# 调试：列出 MCP 工具
# ---------------------------------------------------------------------------
@router.get("/tools", summary="列出所有 MCP 工具（调试）")
async def get_tools():
    """返回当前注册的所有 MCP 工具名称与描述，用于开发调试。"""
    return {"tools": list_tools()}
