"""
普通数据查询接口（非 AI，直接查 DB）。

端点：
  GET /api/buildings                       — 获取所有建筑列表
  GET /api/buildings/{building_type}/status — 获取建筑最新设备状态（按 building_type）
  GET /api/buildings/{building_type}/energy — 获取建筑每日能耗趋势（按 building_type）
  GET /api/buildings/{building_type}/load-profile — 按小时/星期聚合负荷曲线
  GET /api/buildings/{building_type}/peak-valley-stats — 峰谷与夜间高耗统计
  GET /api/overview                         — 获取 Dashboard KPI 汇总（全局总览）
  GET /api/anomalies/sankey                  — 异常根因桑基图聚合数据
  GET /api/tools                            — 列出所有可用 MCP 工具（调试用）
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.cache import cache_bucket, get_or_compute_json
from app.core.config import get_settings
from app.db.models import Building, DailyEnergySummary, Device, EnergyData
from app.db.session import get_db_session
from app.mcp.server import list_tools

logger = logging.getLogger(__name__)

router = APIRouter(tags=["数据"])
settings = get_settings()

_BUILDING_ICONS = {
    "Education": "🏫",
    "Office": "🏢",
    "Public": "🏛️",
    "Public services": "🏛️",
}
_BUILDING_NAMES = {
    "Education": "教学楼",
    "Office": "办公楼",
    "Public": "公共楼",
    "Public services": "公共楼",
}


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
                    "display_name": _BUILDING_NAMES.get(
                        b.primary_space_usage or "",
                        b.primary_space_usage or b.building_id,
                    ),
                    "icon": _BUILDING_ICONS.get(b.primary_space_usage or "", "🏠"),
                    "sqm": b.sqm,
                    "devices": dev_map.get(b.building_id, []),
                }
                for b in buildings
            ]
        except Exception as exc:
            logger.error("查询建筑列表失败: %s", exc)
            raise HTTPException(status_code=500, detail=f"数据库查询失败: {exc}")

    return await get_or_compute_json(cache_key, ttl_seconds, _compute)


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
        select(Building).where(Building.primary_space_usage == building_type)
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

    # 获取关联设备列表（电表设备 ID 用于工单创建和 RAG 过滤）
    dev_result = await db.execute(
        select(Device.device_id, Device.device_type)
        .where(Device.building_id == building.building_id)
        .order_by(Device.device_type)
    )
    devices = [{"device_id": r[0], "device_type": r[1]} for r in dev_result.fetchall()]

    return {
        "building_type": building_type,
        "display_name": _BUILDING_NAMES.get(building_type, building_type),
        "icon": _BUILDING_ICONS.get(building_type, "🏠"),
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

    cache_key = (
        f"building_energy:{building_type}:"
        f"{start_date.isoformat()}:{end_date.isoformat()}:"
        f"{int(include_water)}"
    )
    ttl_seconds = settings.CACHE_BUILDING_ENERGY_TREND_TTL_SECONDS

    async def _compute() -> dict[str, Any]:
        bld_result = await db.execute(
            select(Building.building_id).where(
                Building.primary_space_usage == building_type
            )
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
                water_by_day[
                    wr[0].isoformat() if hasattr(wr[0], 'isoformat') else str(wr[0])
                ] = float(wr[1] or 0)

        records = []
        for r in rows:
            day_str = r.day.isoformat() if r.day else None
            rec = {
                "day": day_str,
                "total_electricity_kwh": r.total_electricity_kwh,
                "avg_ambient_temp": r.avg_ambient_temp,
                "total_water_m3": r.total_water_m3,
            }
            if include_water and day_str:
                day_key = day_str[:10] if day_str else ""
                rec["total_water_m3"] = water_by_day.get(
                    day_key, r.total_water_m3 or 0.0
                )
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

    return await get_or_compute_json(cache_key, ttl_seconds, _compute)


# ---------------------------------------------------------------------------
# 实际 vs 国标期望逐小时对比（供前端"实际 vs 期望"折线图使用）
# ---------------------------------------------------------------------------
_METRIC_COLS = {
    "electricity": ("electricity_kwh", "kWh"),
    "water":       ("water_m3",        "L"),
    "hac_energy":  ("hac_energy",      "kWh"),
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
):
    if metric not in _METRIC_COLS:
        raise HTTPException(status_code=400, detail=f"metric 只能为：{list(_METRIC_COLS.keys())}")
    _, unit = _METRIC_COLS[metric]
    return {
        "building_type": building_type,
        "metric": metric,
        "unit": unit,
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "records": [],
        "summary": {"total_hours": 0, "anomaly_hours": 0, "anomaly_rate_pct": 0},
        "module_status": "disabled",
        "message": "额定期望值模块已下线，等待重新开发。",
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
):
    """从 energy_data 聚合小时均值与星期均值，供首页节律类图表使用。"""
    if metric not in _LOAD_PROFILE_METRICS:
        raise HTTPException(
            status_code=400,
            detail=f"metric 只能为：{list(_LOAD_PROFILE_METRICS.keys())}",
        )

    col = _LOAD_PROFILE_METRICS[metric]

    bld_result = await db.execute(
        select(Building.building_id).where(
            Building.primary_space_usage == building_type
        )
    )
    building_id = bld_result.scalar_one_or_none()
    if not building_id:
        raise HTTPException(status_code=404, detail=f"建筑类型 {building_type} 不存在")

    max_row = await db.execute(
        select(func.max(EnergyData.timestamp)).where(
            EnergyData.building_id == building_id
        )
    )
    max_ts = max_row.scalar()
    if max_ts is None:
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

    if max_ts.tzinfo is None:
        end_dt = max_ts.replace(tzinfo=timezone.utc)
    else:
        end_dt = max_ts.astimezone(timezone.utc)
    start_dt = end_dt - timedelta(days=days)

    hourly_sql = text(
        f"""
        SELECT EXTRACT(HOUR FROM e.timestamp)::int AS hr,
               AVG(e.{col})::float AS avg_val,
               COUNT(*)::int AS n
          FROM energy_data e
         WHERE e.building_id = :bid
           AND e.timestamp >= :t0
           AND e.timestamp <= :t1
         GROUP BY hr
         ORDER BY hr
        """
    )
    h_result = await db.execute(
        hourly_sql, {"bid": building_id, "t0": start_dt, "t1": end_dt}
    )
    hourly_map: dict[int, tuple[float, int]] = {}
    for hr, avg_val, n in h_result.fetchall():
        if hr is None:
            continue
        hourly_map[int(hr)] = (float(avg_val or 0), int(n or 0))

    hourly_profile = []
    for h in range(24):
        av, n = hourly_map.get(h, (0.0, 0))
        hourly_profile.append({
            "hour": h,
            "avg_value": round(av, 4),
            "sample_count": n,
            "anomaly_count": 0,
        })

    wd_sql = text(
        f"""
        SELECT EXTRACT(ISODOW FROM e.timestamp)::int AS wd,
               AVG(e.{col})::float AS avg_val,
               COUNT(*)::int AS n
          FROM energy_data e
         WHERE e.building_id = :bid
           AND e.timestamp >= :t0
           AND e.timestamp <= :t1
         GROUP BY wd
         ORDER BY wd
        """
    )
    wd_result = await db.execute(
        wd_sql, {"bid": building_id, "t0": start_dt, "t1": end_dt}
    )
    wd_map: dict[int, tuple[float, int]] = {}
    for wd, avg_val, n in wd_result.fetchall():
        if wd is None:
            continue
        wd_map[int(wd)] = (float(avg_val or 0), int(n or 0))

    weekday_profile = []
    for wd in range(1, 8):
        av, n = wd_map.get(wd, (0.0, 0))
        weekday_profile.append({
            "weekday": wd,
            "label": _WD_LABELS.get(wd, str(wd)),
            "avg_value": round(av, 4),
            "sample_count": n,
        })

    return {
        "building_type": building_type,
        "building_id": building_id,
        "metric": metric,
        "days": days,
        "window_end": end_dt.isoformat(),
        "window_start": start_dt.isoformat(),
        "hourly_profile": hourly_profile,
        "weekday_profile": weekday_profile,
    }


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
):
    if metric not in _PEAK_VALLEY_METRICS:
        raise HTTPException(
            status_code=400,
            detail=f"峰谷统计 metric 只能为：{sorted(_PEAK_VALLEY_METRICS)}",
        )
    col = _LOAD_PROFILE_METRICS[metric]

    bld_result = await db.execute(
        select(Building.building_id).where(
            Building.primary_space_usage == building_type
        )
    )
    building_id = bld_result.scalar_one_or_none()
    if not building_id:
        raise HTTPException(status_code=404, detail=f"建筑类型 {building_type} 不存在")

    max_row = await db.execute(
        select(func.max(EnergyData.timestamp)).where(
            EnergyData.building_id == building_id
        )
    )
    max_ts = max_row.scalar()
    if max_ts is None:
        return {
            "building_type": building_type,
            "building_id": building_id,
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
        daily_sql, {"bid": building_id, "t0": start_dt, "t1": end_dt}
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
        {"bid": building_id, "t0": start_dt, "t1": end_dt, "thr": night_threshold},
    )
    night_abnormal_hours = int(n_result.scalar() or 0)

    return {
        "building_type": building_type,
        "building_id": building_id,
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
                "display_name": _BUILDING_NAMES.get(usage or "", usage or bid),
                "icon": _BUILDING_ICONS.get(usage or "", "🏠"),
                "total_electricity_kwh": round(float(total_elec or 0), 2),
                "total_water_m3": round(float(total_w or 0), 2),
                "total_hac_energy_kwh": round(float(hac or 0), 2),
                "avg_ambient_temp": round(float(bld_avg_temp or 0), 1) if bld_avg_temp else None,
                "sqm": sqm,
                "energy_intensity_kwh_per_sqm": intensity,
                "anomaly_status": "Anomaly" if is_anomaly else "Normal",
                "latest_water_m3": latest_w,
            })

        return {
            "data_date": target_day.isoformat() if hasattr(target_day, "isoformat") else str(target_day),
            "kpis": {
                "total_electricity_kwh": round(total_electricity, 2),
                "total_water_m3": round(total_water, 2),
                "total_hac_energy_kwh": round(total_hac, 2),
                "total_carbon_kg": round(total_electricity * 0.5703, 2),
                "anomaly_count": len(anomaly_building_ids),
            },
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
    db: AsyncSession = Depends(get_db_session),
):
    return {
        "anomalies": [],
        "total": 0,
        "check_period": {
            "start": None,
            "end": None,
            "hours": hours,
        },
        "source": "disabled",
        "module_status": "disabled",
        "message": "异常监测模块已下线，等待重新开发。",
    }


# ---------------------------------------------------------------------------
# 异常根因桑基图（Sankey）聚合数据
# ---------------------------------------------------------------------------
_RULE_LABEL = {
    # 旧版规则（兼容）
    "water_leak": "水耗异常",
    "electricity_overload": "电耗超标",
    "hvac_overconsumption": "空调过耗",
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
):
    return {
        "nodes": [],
        "links": [],
        "module_status": "disabled",
        "message": "异常监测模块已下线，等待重新开发。",
    }


# ---------------------------------------------------------------------------
# 调试：列出 MCP 工具
# ---------------------------------------------------------------------------
@router.get("/tools", summary="列出所有 MCP 工具（调试）")
async def get_tools():
    """返回当前注册的所有 MCP 工具名称与描述，用于开发调试。"""
    return {"tools": list_tools()}
