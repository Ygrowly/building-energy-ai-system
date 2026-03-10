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

from app.db.models import Building, DailyEnergySummary, EnergyData
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
    anomaly_count = sum(1 for r in live_rows if r[1] == "Anomaly")

    status_map: dict[str, tuple] = {r[0]: r for r in live_rows}

    enriched_buildings = []
    for bld in buildings_detail:
        bt = bld["building_type"]
        live = status_map.get(bt)
        enriched_buildings.append({
            **bld,
            "operation_status": live[1] if live else "Normal",
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
# 近期异常告警（Dashboard 主动提示）
# ---------------------------------------------------------------------------
@router.get("/anomalies/recent", summary="获取近期异常告警")
async def get_recent_anomalies(
    hours: int = Query(24, ge=1, le=168, description="查询最近 N 小时内的异常"),
    building_type: str | None = Query(None, description="按建筑类型过滤"),
    db: AsyncSession = Depends(get_db_session),
):
    """
    检测近期能耗异常，供 Dashboard 主动提示。
    规则：夜间高功率（0-6 点 > 50kWh）/ 无人高空调（occupancy=0 且 hvac > 30kWh）。
    """
    from datetime import datetime, timedelta, timezone

    now_utc = datetime.now(timezone.utc)
    start_time = now_utc - timedelta(hours=hours)

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

        if (
            ed.electricity_kwh is not None
            and 0 <= hour_utc < 6
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
                "operation_status": ed.operation_status,
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
                "operation_status": ed.operation_status,
            })

    return {
        "anomalies": anomalies[:50],
        "total": len(anomalies),
        "check_period": {
            "start": start_time.isoformat(),
            "end": now_utc.isoformat(),
            "hours": hours,
        },
    }


# ---------------------------------------------------------------------------
# 调试：列出 MCP 工具
# ---------------------------------------------------------------------------
@router.get("/tools", summary="列出所有 MCP 工具（调试）")
async def get_tools():
    """返回当前注册的所有 MCP 工具名称与描述，用于开发调试。"""
    return {"tools": list_tools()}
