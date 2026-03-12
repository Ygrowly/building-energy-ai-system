"""
普通数据查询接口（非 AI，直接查 DB）。

端点：
  GET /api/buildings                       — 获取所有建筑列表
  GET /api/buildings/{building_type}/status — 获取建筑最新设备状态（按 building_type）
  GET /api/buildings/{building_type}/energy — 获取建筑每日能耗趋势（按 building_type）
  GET /api/overview                         — 获取 Dashboard KPI 汇总（全局总览）
  GET /api/tools                            — 列出所有可用 MCP 工具（调试用）
"""
from __future__ import annotations

import logging
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AnomalyEvent, Building, DailyEnergySummary, EnergyData
from app.db.session import get_db_session
from app.mcp.server import list_tools

logger = logging.getLogger(__name__)

router = APIRouter(tags=["数据"])

_BUILDING_ICONS = {
    "Education": "🏫",
    "Office": "🏢",
    "Public": "🏛️",
}
_BUILDING_NAMES = {
    "Education": "教学楼",
    "Office": "办公楼",
    "Public": "公共楼",
}


# ---------------------------------------------------------------------------
# 建筑列表
# ---------------------------------------------------------------------------
@router.get("/buildings", summary="获取所有建筑列表")
async def get_buildings(db: AsyncSession = Depends(get_db_session)):
    """返回 buildings 表中所有建筑的基本信息。"""
    try:
        result = await db.execute(
            select(Building).order_by(Building.building_type)
        )
        buildings = result.scalars().all()
        return [
            {
                "building_id": b.building_id,
                "building_type": b.building_type,
                "display_name": _BUILDING_NAMES.get(b.building_type, b.building_type),
                "icon": _BUILDING_ICONS.get(b.building_type, "🏠"),
                "sqm": b.sqm,
                "meter_device_id": b.meter_device_id,
            }
            for b in buildings
        ]
    except Exception as exc:
        logger.error("查询建筑列表失败: %s", exc)
        raise HTTPException(status_code=500, detail=f"数据库查询失败: {exc}")


# ---------------------------------------------------------------------------
# 建筑最新设备状态（按 building_type 查询）
# ---------------------------------------------------------------------------
@router.get("/buildings/{building_type}/status", summary="获取建筑最新设备状态")
async def get_building_status(
    building_type: str,
    db: AsyncSession = Depends(get_db_session),
):
    """查询指定建筑最新一条传感器读数（实时状态快照）。building_type 如 'Office'。"""
    bld_result = await db.execute(
        select(Building).where(Building.building_type == building_type)
    )
    building = bld_result.scalar_one_or_none()
    if not building:
        raise HTTPException(status_code=404, detail=f"建筑类型 {building_type} 不存在")

    result = await db.execute(
        select(EnergyData)
        .where(EnergyData.building_id == building.building_id)
        .order_by(EnergyData.timestamp.desc())
        .limit(1)
    )
    latest = result.scalar_one_or_none()
    if not latest:
        raise HTTPException(status_code=404, detail=f"建筑 {building_type} 暂无数据")

    return {
        "building_type": building_type,
        "display_name": _BUILDING_NAMES.get(building_type, building_type),
        "icon": _BUILDING_ICONS.get(building_type, "🏠"),
        "meter_device_id": building.meter_device_id,
        "sqm": building.sqm,
        "last_updated_utc": latest.timestamp.isoformat() if latest.timestamp else None,
        "operation_status": latest.operation_status,
        "electricity_kwh": latest.electricity_kwh,
        "water_m3": latest.water_m3,
        "hvac_energy_kwh": latest.hvac_energy_kwh,
        "hvac_supply_temp_c": latest.hvac_supply_temp_c,
        "hvac_return_temp_c": latest.hvac_return_temp_c,
        "ambient_temp_c": latest.ambient_temp_c,
        "humidity_rh_pct": latest.humidity_rh_pct,
        "occupancy_density_per_100sqm": latest.occupancy_density_per_100sqm,
    }


# ---------------------------------------------------------------------------
# 按天能耗趋势（按 building_type 查询）
# ---------------------------------------------------------------------------
@router.get("/buildings/{building_type}/energy", summary="获取建筑每日能耗趋势")
async def get_building_energy_trend(
    building_type: str,
    start_date: date = Query(..., description="开始日期 YYYY-MM-DD"),
    end_date: date = Query(..., description="结束日期 YYYY-MM-DD"),
    include_water: bool = Query(False, description="是否包含每日用水量（需额外查 energy_data 表）"),
    db: AsyncSession = Depends(get_db_session),
):
    """
    从物化视图查询按天汇总的能耗趋势。building_type 如 'Office'。
    include_water=true 时额外从 energy_data 表聚合每日用水量。
    """
    if start_date > end_date:
        raise HTTPException(status_code=400, detail="start_date 不能晚于 end_date")

    bld_result = await db.execute(
        select(Building.building_id).where(Building.building_type == building_type)
    )
    building_id = bld_result.scalar_one_or_none()
    if not building_id:
        raise HTTPException(status_code=404, detail=f"建筑类型 {building_type} 不存在")

    result = await db.execute(
        select(DailyEnergySummary)
        .where(
            DailyEnergySummary.building_id == building_id,
            DailyEnergySummary.day >= start_date,
            DailyEnergySummary.day <= end_date,
        )
        .order_by(DailyEnergySummary.day)
    )
    rows = result.scalars().all()

    water_by_day: dict[str, float] = {}
    if include_water:
        water_result = await db.execute(
            text("""
                SELECT date_trunc('day', timestamp)::date AS day,
                       SUM(water_m3) AS total_water_m3
                FROM energy_data
                WHERE building_id = :bid
                  AND timestamp >= :sd AND timestamp <= :ed
                GROUP BY day ORDER BY day
            """),
            {"bid": building_id, "sd": start_date, "ed": end_date},
        )
        for wr in water_result.fetchall():
            water_by_day[wr[0].isoformat() if hasattr(wr[0], 'isoformat') else str(wr[0])] = float(wr[1] or 0)

    records = []
    for r in rows:
        day_str = r.day.isoformat() if r.day else None
        rec = {
            "day": day_str,
            "total_electricity_kwh": r.total_electricity_kwh,
            "avg_ambient_temp": r.avg_ambient_temp,
            "max_occupancy": r.max_occupancy,
        }
        if include_water and day_str:
            day_key = day_str[:10] if day_str else ""
            rec["total_water_m3"] = water_by_day.get(day_key, 0.0)
        records.append(rec)

    return {
        "building_type": building_type,
        "building_id": building_id,
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "source": "daily_energy_summary (materialized view)",
        "records": records,
        "count": len(records),
    }


# ---------------------------------------------------------------------------
# Dashboard KPI 总览（全局汇总，取数据库最新一天的汇总数据）
# ---------------------------------------------------------------------------
@router.get("/overview", summary="获取 Dashboard KPI 总览")
async def get_overview(db: AsyncSession = Depends(get_db_session)):
    """
    返回所有建筑的 KPI 汇总数据（最新可用日期），供 Dashboard 使用。
    包含：各楼总用电、总用水、最新设备状态快照。
    """
    # 取数据库最新可用日期
    latest_day_result = await db.execute(
        select(func.max(DailyEnergySummary.day))
    )
    latest_day = latest_day_result.scalar()
    if not latest_day:
        return {"error": "暂无汇总数据"}

    # 取该日期所有楼宇的汇总
    summary_result = await db.execute(
        select(DailyEnergySummary, Building.building_type, Building.sqm)
        .join(Building, DailyEnergySummary.building_id == Building.building_id)
        .where(DailyEnergySummary.day == latest_day)
    )
    rows = summary_result.fetchall()

    # 各楼明细
    buildings_detail = []
    total_electricity = 0.0
    for row in rows:
        summary, btype, sqm = row
        intensity = (
            round(float(summary.total_electricity_kwh) / float(sqm), 2)
            if sqm and sqm > 0 else None
        )
        buildings_detail.append({
            "building_type": btype,
            "display_name": _BUILDING_NAMES.get(btype, btype),
            "icon": _BUILDING_ICONS.get(btype, "🏠"),
            "total_electricity_kwh": summary.total_electricity_kwh,
            "avg_ambient_temp": summary.avg_ambient_temp,
            "max_occupancy": summary.max_occupancy,
            "sqm": sqm,
            "energy_intensity_kwh_per_sqm": intensity,
        })
        total_electricity += float(summary.total_electricity_kwh or 0)

    # 取各楼最新一条记录（用于用水量和运行状态）
    latest_records_result = await db.execute(
        text("""
            SELECT DISTINCT ON (e.building_id)
                b.building_type,
                e.operation_status,
                e.water_m3,
                e.hvac_energy_kwh,
                e.ambient_temp_c,
                e.occupancy_density_per_100sqm
            FROM energy_data e
            JOIN buildings b ON e.building_id = b.building_id
            ORDER BY e.building_id, e.timestamp DESC
        """)
    )
    live_rows = latest_records_result.fetchall()

    total_water = sum(float(r[2] or 0) for r in live_rows)
    status_map: dict[str, tuple] = {r[0]: r for r in live_rows}

    # 从 anomaly_events 查询有未解决异常的楼宇集合
    # 时间窗口：数据最大时间戳往前 24h（兼容历史数据集，不依赖 NOW()）
    # 若表尚未创建（迁移未执行），回退为 energy_data.operation_status 字段
    anomaly_building_types: set[str] = set()
    try:
        recent_anomaly_result = await db.execute(
            text("""
                SELECT DISTINCT building_type
                FROM anomaly_events
                WHERE data_timestamp >= (
                    SELECT MAX(data_timestamp) FROM anomaly_events
                ) - INTERVAL '24 hours'
                  AND is_resolved = false
            """)
        )
        anomaly_building_types = {r[0] for r in recent_anomaly_result.fetchall()}
    except Exception:
        # 迁移未执行时的降级策略：使用 energy_data 中的 operation_status 字段
        for r in live_rows:
            if r[1] == "Anomaly":
                anomaly_building_types.add(r[0])

    anomaly_count = len(anomaly_building_types)

    enriched_buildings = []
    for bld in buildings_detail:
        bt = bld["building_type"]
        live = status_map.get(bt)
        enriched_buildings.append({
            **bld,
            "operation_status": "Anomaly" if bt in anomaly_building_types else "Normal",
            "latest_water_m3": float(live[2] or 0) if live else 0.0,
        })

    return {
        "data_date": latest_day.isoformat() if latest_day else None,
        "kpis": {
            "total_electricity_kwh": round(total_electricity, 2),
            "total_water_m3": round(total_water, 2),
            "anomaly_count": anomaly_count,
        },
        "buildings": enriched_buildings,
    }


# ---------------------------------------------------------------------------
# 近期异常告警（Dashboard / 运维页 统一数据源）
# ---------------------------------------------------------------------------
@router.get("/anomalies/recent", summary="获取近期异常告警")
async def get_recent_anomalies(
    hours: int = Query(168, ge=1, le=8760, description="查询最近 N 小时内的异常（默认 7 天，最大 1 年）"),
    building_type: str | None = Query(None, description="按建筑类型过滤"),
    db: AsyncSession = Depends(get_db_session),
):
    """
    从 anomaly_events 表读取近期异常告警，供 Dashboard 和运维页展示。
    数据由后台 anomaly_detector 服务持续写入，不再在请求时实时计算规则。

    若 anomaly_events 表尚未创建（迁移 002 未执行），自动降级为实时规则计算模式。
    """
    from datetime import datetime, timedelta, timezone

    now_utc = datetime.now(timezone.utc)
    start_time = now_utc - timedelta(hours=hours)

    try:
        # ── 主路径：读 anomaly_events 表 ──────────────────────────────────
        # 时间窗口以数据自身最大时间戳为基准（兼容历史数据集，不依赖 NOW()）
        max_ts_row = await db.execute(
            text("SELECT MAX(data_timestamp) FROM anomaly_events WHERE is_resolved = false")
        )
        max_data_ts = max_ts_row.scalar()

        if max_data_ts is None:
            return {
                "anomalies": [],
                "total": 0,
                "check_period": {"start": None, "end": None, "hours": hours},
                "source": "anomaly_events",
            }

        from datetime import timedelta
        window_start = max_data_ts - timedelta(hours=hours)

        stmt = (
            select(AnomalyEvent)
            .where(AnomalyEvent.data_timestamp >= window_start)
            .where(AnomalyEvent.is_resolved.is_(False))
            .order_by(AnomalyEvent.data_timestamp.desc())
        )
        if building_type:
            stmt = stmt.where(AnomalyEvent.building_type == building_type)

        result = await db.execute(stmt)
        events = result.scalars().all()

        anomalies = [
            {
                "timestamp": ev.data_timestamp.isoformat(),
                "building_type": ev.building_type,
                "meter_device_id": ev.meter_device_id,
                "rule": ev.rule_triggered,
                "message": ev.message,
                "actual_value": ev.actual_value,
                "threshold": ev.threshold_value,
                "operation_status": "Anomaly",
            }
            for ev in events[:100]
        ]

        return {
            "anomalies": anomalies,
            "total": len(events),
            "check_period": {
                "start": window_start.isoformat(),
                "end": max_data_ts.isoformat(),
                "hours": hours,
            },
            "source": "anomaly_events",
        }

    except Exception:
        # ── 降级路径：迁移未执行时实时计算（兼容旧版）────────────────────
        logger.warning("anomaly_events 表不可用，降级为实时规则计算（请执行迁移 002_create_anomaly_events.sql）")
        return await _fallback_realtime_anomalies(start_time, now_utc, hours, building_type, db)


async def _fallback_realtime_anomalies(
    start_time,
    now_utc,
    hours: int,
    building_type: str | None,
    db: AsyncSession,
) -> dict:
    """降级：实时扫描 energy_data 计算异常（修复了时区 Bug）。"""
    from datetime import timezone

    query = (
        select(EnergyData, Building.building_type, Building.meter_device_id)
        .join(Building, EnergyData.building_id == Building.building_id)
        .where(EnergyData.timestamp >= start_time)
    )
    if building_type:
        query = query.where(Building.building_type == building_type)
    query = query.order_by(EnergyData.timestamp.desc())

    result = await db.execute(query)
    rows = result.fetchall()

    anomalies = []
    for row in rows:
        ed, btype, meter_id = row
        ts = ed.timestamp
        hour_utc = ts.hour if ts.tzinfo else ts.replace(tzinfo=timezone.utc).hour
        hour_local = (hour_utc + 8) % 24  # 转换为 CST（UTC+8）

        if (
            ed.electricity_kwh is not None
            and 0 <= hour_local < 6
            and ed.electricity_kwh > 50
        ):
            anomalies.append({
                "timestamp": ts.isoformat(),
                "building_type": btype,
                "meter_device_id": meter_id,
                "rule": "night_high_power",
                "message": f"{_BUILDING_NAMES.get(btype, btype)}夜间能耗异常：{ed.electricity_kwh:.1f} kWh",
                "actual_value": ed.electricity_kwh,
                "threshold": 50.0,
                "operation_status": "Anomaly",
            })

        if (
            ed.occupancy_density_per_100sqm is not None
            and ed.hvac_energy_kwh is not None
            and ed.occupancy_density_per_100sqm == 0
            and ed.hvac_energy_kwh > 30
        ):
            anomalies.append({
                "timestamp": ts.isoformat(),
                "building_type": btype,
                "meter_device_id": meter_id,
                "rule": "zero_occupancy_high_hvac",
                "message": f"{_BUILDING_NAMES.get(btype, btype)}无人时空调高耗：{ed.hvac_energy_kwh:.1f} kWh",
                "actual_value": ed.hvac_energy_kwh,
                "threshold": 30.0,
                "operation_status": "Anomaly",
            })

    return {
        "anomalies": anomalies[:100],
        "total": len(anomalies),
        "check_period": {
            "start": start_time.isoformat(),
            "end": now_utc.isoformat(),
            "hours": hours,
        },
        "source": "realtime_fallback",
    }


# ---------------------------------------------------------------------------
# 调试：列出 MCP 工具
# ---------------------------------------------------------------------------
@router.get("/tools", summary="列出所有 MCP 工具（调试）")
async def get_tools():
    """返回当前注册的所有 MCP 工具名称与描述，用于开发调试。"""
    return {"tools": list_tools()}
