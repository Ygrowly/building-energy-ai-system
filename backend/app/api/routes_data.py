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
):
    if metric not in _METRIC_COLS:
        raise HTTPException(status_code=400, detail=f"metric 只能为：{list(_METRIC_COLS.keys())}")
    actual_col, expected_col, unit = _METRIC_COLS[metric]

    bld_result = await db.execute(
        select(Building.building_id).where(Building.primary_space_usage == building_type)
    )
    building_id = bld_result.scalar_one_or_none()
    if not building_id:
        raise HTTPException(status_code=404, detail=f"建筑类型 {building_type} 不存在")

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
    """), {"bid": building_id, "t0": start_dt, "t1": end_dt})
    rows = rows_result.fetchall()

    if not rows:
        return {
            "building_type": building_type,
            "building_id": building_id,
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
        "building_type": building_type,
        "building_id": building_id,
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

        return {
            "data_date": target_day.isoformat() if hasattr(target_day, "isoformat") else str(target_day),
            "kpis": {
                "total_electricity_kwh": round(total_electricity, 2),
                "total_water_m3": round(total_water, 2),
                "total_hac_energy_kwh": round(total_hac, 2),
                "total_carbon_kg": round(total_electricity * 0.5703, 2),
                "anomaly_count": len(anomaly_building_ids),
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
    db: AsyncSession = Depends(get_db_session),
):
    # 以 anomaly_events 表中最新数据时间戳为窗口终点（数据集是历史数据）
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

    # 可选：按建筑类型过滤
    building_filter = ""
    params: dict[str, Any] = {"t0": window_start, "t1": max_ts}
    if building_type:
        bld_result = await db.execute(
            select(Building.building_id).where(Building.primary_space_usage == building_type)
        )
        bid = bld_result.scalar_one_or_none()
        if bid:
            building_filter = " AND ae.building_id = :bid"
            params["bid"] = bid

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
          AND ae.is_resolved = false
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
    """
    从 anomaly_events 聚合桑基图数据：
      异常规则  →  HVAC 根因（仅 hvac_overconsumption 有根因）
    非 HVAC 类规则直接作为终点节点。
    """
    agg_result = await db.execute(text("""
        SELECT
            rule_triggered,
            hvac_root_cause,
            COUNT(*) AS cnt
        FROM anomaly_events
        WHERE is_resolved = false
        GROUP BY rule_triggered, hvac_root_cause
        ORDER BY cnt DESC
    """))
    rows = agg_result.fetchall()

    if not rows:
        return {
            "nodes": [],
            "links": [],
            "module_status": "no_data",
            "message": "anomaly_events 暂无数据，请先调用 /api/admin/rebuild-all",
        }

    # 收集节点名称（去重）
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
            cause_label = rule_label + "(直接)"

        src_idx = _node_idx(rule_label)
        tgt_idx = _node_idx(cause_label)
        links.append({"source": src_idx, "target": tgt_idx, "value": int(cnt)})

    nodes = [{"name": n} for n in node_set]
    return {
        "nodes": nodes,
        "links": links,
        "module_status": "ok",
    }


# ---------------------------------------------------------------------------
# 实时风险预警（预警通知 Tab 数据源）
# ---------------------------------------------------------------------------

_BUILDING_DISPLAY: dict[str, str] = {
    "Education": "教学楼",
    "Office":    "办公楼",
    "Public":    "图书馆",
    "Public services": "图书馆",
}

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

    buildings_result = await db.execute(select(Building))
    buildings = buildings_result.scalars().all()

    risk_items: list[dict] = []

    for building in buildings:
        latest_result = await db.execute(
            select(EnergyData)
            .where(EnergyData.building_id == building.building_id)
            .order_by(EnergyData.timestamp.desc())
            .limit(1)
        )
        latest: EnergyData | None = latest_result.scalar_one_or_none()
        if not latest:
            continue

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
            "building_name":        _BUILDING_DISPLAY.get(
                                        building.primary_space_usage or "",
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


# ---------------------------------------------------------------------------
# 调试：列出 MCP 工具
# ---------------------------------------------------------------------------
@router.get("/tools", summary="列出所有 MCP 工具（调试）")
async def get_tools():
    """返回当前注册的所有 MCP 工具名称与描述，用于开发调试。"""
    return {"tools": list_tools()}
