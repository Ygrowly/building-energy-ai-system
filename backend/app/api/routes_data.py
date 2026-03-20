"""
普通数据查询接口（非 AI，直接查 DB）。

端点：
  GET /api/buildings                       — 获取所有建筑列表
  GET /api/buildings/{building_type}/status — 获取建筑最新设备状态（按 building_type）
  GET /api/buildings/{building_type}/energy — 获取建筑每日能耗趋势（按 building_type）
  GET /api/overview                         — 获取 Dashboard KPI 汇总（全局总览）
  GET /api/anomalies/sankey                  — 异常根因桑基图聚合数据
  GET /api/tools                            — 列出所有可用 MCP 工具（调试用）
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.cache import cache_bucket, get_or_compute_json
from app.core.config import get_settings
from app.db.models import AnomalyEvent, Building, DailyEnergySummary, Device, EnergyData
from app.db.session import get_db_session
from app.mcp.server import list_tools
from app.services.gb_simulator import calculate_rated_values

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
    "water":       ("water_m3",        "m³"),
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
    """
    逐小时返回指定建筑的"实际值 vs 国标 GB 期望值"对比数据。

    期望值由 gb_simulator 实时计算（基于 GB/T 51161、GB 50034、GB 50189、
    GB 50736、GB 50015 五项国标），不依赖外部存储。

    返回字段：
      timestamp        — ISO 8601 时间戳（UTC）
      actual           — 实际值（来自 energy_data 表）
      rated            — 国标期望值
      deviation_pct    — 偏差百分比（正数=超标，负数=低于期望）
      hvac_mode        — 当前 HVAC 工况（Cooling / Heating / Ventilation）
      schedule_factor  — 当前小时建筑负荷率 S
      is_anomaly       — 是否异常（|偏差| > 15% 且满足绝对值阈值）
    """
    if start_date > end_date:
        raise HTTPException(status_code=400, detail="start_date 不能晚于 end_date")
    if (end_date - start_date).days > 7:
        raise HTTPException(status_code=400, detail="查询跨度不能超过 7 天（168 小时）")
    if metric not in _METRIC_COLS:
        raise HTTPException(status_code=400, detail=f"metric 只能为：{list(_METRIC_COLS.keys())}")

    col_name, unit = _METRIC_COLS[metric]
    abs_thresholds = {"electricity": None, "water": 1.0, "hac_energy": 20.0}
    rel_threshold  = {"electricity": 0.15, "water": 0.20, "hac_energy": 0.20}
    abs_thr = abs_thresholds[metric]
    rel_thr = rel_threshold[metric]

    # 查建筑元数据
    bld_result = await db.execute(
        select(Building.building_id, Building.sqm, Building.primary_space_usage)
        .where(Building.primary_space_usage == building_type)
    )
    bld_row = bld_result.fetchone()
    if not bld_row:
        raise HTTPException(status_code=404, detail=f"建筑类型 {building_type} 不存在")
    building_id, sqm, usage = bld_row
    sqm = sqm or 1000.0

    # 查时段内所有小时记录
    result = await db.execute(
        select(
            EnergyData.timestamp,
            EnergyData.electricity_kwh,
            EnergyData.water_m3,
            EnergyData.hac_energy,
            EnergyData.sim_supply_temp_c,
            EnergyData.sim_return_temp_c,
            EnergyData.air_temp_c,
            EnergyData.dew_temp_c,
        )
        .where(EnergyData.building_id == building_id)
        .where(EnergyData.timestamp >= start_date)
        .where(EnergyData.timestamp < end_date + timedelta(days=1))
        .order_by(EnergyData.timestamp.asc())
    )
    rows = result.fetchall()

    records = []
    anomaly_count = 0
    eps = 1e-6

    for ts, elec, water, hac, supply, ret, air_t, dew_t in rows:
        try:
            rated = calculate_rated_values(
                sqm=sqm,
                primary_space_usage=usage or "Office",
                hour=ts.hour,
                dayofweek=ts.isoweekday(),
                air_temp=air_t or 20.0,
                dew_temp=dew_t or 10.0,
            )
        except Exception:
            continue

        actual_val: float | None = {
            "electricity": elec,
            "water":       water,
            "hac_energy":  hac,
        }[metric]
        rated_val: float = {
            "electricity": rated.rated_electricity_kwh,
            "water":       rated.rated_water_m3,
            "hac_energy":  rated.rated_hac_energy,
        }[metric]

        dev_pct: float | None = None
        is_anomaly = False
        if actual_val is not None and rated_val > eps:
            delta = actual_val - rated_val
            dev_pct = round(delta / rated_val * 100, 2)
            # 异常判定：满足相对阈值 AND 绝对阈值（电耗只用相对阈值）
            if abs_thr is None:
                is_anomaly = dev_pct > rel_thr * 100
            else:
                is_anomaly = dev_pct > rel_thr * 100 and delta > abs_thr

        if is_anomaly:
            anomaly_count += 1

        records.append({
            "timestamp":       ts_utc.isoformat(),
            "actual":          round(actual_val, 4) if actual_val is not None else None,
            "rated":           round(rated_val, 4),
            "deviation_pct":   dev_pct,
            "hvac_mode":       rated.hvac_mode,
            "schedule_factor": rated.schedule_factor,
            "is_anomaly":      is_anomaly,
        })

    return {
        "building_type":   building_type,
        "metric":          metric,
        "unit":            unit,
        "primary_space_usage": usage,
        "sqm":             sqm,
        "start_date":      start_date.isoformat(),
        "end_date":        end_date.isoformat(),
        "records":         records,
        "summary": {
            "total_hours":      len(records),
            "anomaly_hours":    anomaly_count,
            "anomaly_rate_pct": round(anomaly_count / len(records) * 100, 1) if records else 0,
        },
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
    """
    从 anomaly_events 表读取近期异常告警，供 Dashboard 和运维页展示。
    数据由后台 anomaly_detector 服务持续写入，不再在请求时实时计算规则。

    若 anomaly_events 表尚未创建（迁移 002 未执行），自动降级为实时规则计算模式。
    """
    cache_key = f"anomalies_recent:{hours}:{building_type or 'all'}:{cache_bucket()}"
    ttl_seconds = settings.CACHE_ANOMALIES_RECENT_TTL_SECONDS

    async def _compute() -> dict[str, Any]:
        from datetime import datetime, timedelta, timezone

        now_utc = datetime.now(timezone.utc)
        start_time = now_utc - timedelta(hours=hours)

        try:
            # ── 主路径：读 anomaly_events 表 ──────────────────────────────────
            # 时间窗口以数据自身最大时间戳为基准（兼容历史数据集，不依赖 NOW()）
            max_ts_row = await db.execute(
                text(
                    "SELECT MAX(data_timestamp) FROM anomaly_events WHERE is_resolved = false"
                )
            )
            max_data_ts = max_ts_row.scalar()

            if max_data_ts is None:
                return {
                    "anomalies": [],
                    "total": 0,
                    "check_period": {
                        "start": None,
                        "end": None,
                        "hours": hours,
                    },
                    "source": "anomaly_events",
                }

            from datetime import timedelta
            window_start = max_data_ts - timedelta(hours=hours)

            stmt = (
                select(AnomalyEvent, Building.primary_space_usage)
                .outerjoin(
                    Building, AnomalyEvent.building_id == Building.building_id
                )
                .where(AnomalyEvent.data_timestamp >= window_start)
                .where(AnomalyEvent.is_resolved.is_(False))
                .order_by(AnomalyEvent.data_timestamp.desc())
            )
            if building_type:
                stmt = stmt.where(Building.primary_space_usage == building_type)

            result = await db.execute(stmt)
            rows = result.fetchall()

            # actual_value 使用扫描时存入的值（anomaly_events.actual_value）
            # 扫描器遍历 energy_data 每一行，已正确取对应字段：
            #   electricity_overload → electricity_kwh
            #   water_leak           → water_m3
            #   hvac_overconsumption → hac_energy
            # 注意：energy_data 无主键，可能存在重复行（正常+注入异常各一条），
            #       扫描时对异常行触发告警并存入正确的 actual_value，此处直接使用。
            anomalies = [
                {
                    "timestamp": ev.data_timestamp.isoformat(),
                    "building_type": usage,
                    "building_id": ev.building_id,
                    "meter_device_id": ev.meter_device_id,
                    "rule": ev.rule_triggered,
                    "message": ev.message,
                    "actual_value": ev.actual_value,
                    "threshold": ev.threshold_value,
                    "expected_value": ev.expected_value,
                    "deviation_pct": ev.deviation_pct,
                    "anomaly_status": "Anomaly",
                }
                for ev, usage in rows[:100]
            ]
            events = rows  # 用于 total 计数

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

        except Exception as exc:
            exc_type = type(exc).__name__
            exc_msg = str(exc)

            # ── 连接级别错误（网络断开、连接池耗尽等）──────────────────────────
            # 此时 db session 已损坏，不能再用同一连接重试，直接返回安全空响应。
            # 典型特征：ConnectionError / asyncpg connection_lost / InterfaceError
            _conn_keywords = (
                "connection_lost",
                "ConnectionError",
                "InterfaceError",
                "connection",
                "connect",
                "asyncpg",
            )
            is_connection_error = (
                "ConnectionError" in exc_type
                or "InterfaceError" in exc_type
                or any(kw in exc_msg for kw in _conn_keywords)
            )
            if is_connection_error:
                logger.error(
                    "数据库连接异常，/api/anomalies/recent 返回空结果（请检查 DB 连接）: %s: %s",
                    exc_type,
                    exc_msg,
                )
                return {
                    "anomalies": [],
                    "total": 0,
                    "check_period": {
                        "start": start_time.isoformat(),
                        "end": now_utc.isoformat(),
                        "hours": hours,
                    },
                    "source": "connection_error",
                    "error": "数据库连接异常，请稍后重试",
                }

            # ── 表不存在等 DDL 错误 → 降级为实时规则计算（兼容迁移未执行）────
            logger.warning(
                "anomaly_events 表不可用，降级为实时规则计算（%s: %s）"
                "——请执行迁移 002_create_anomaly_events.sql",
                exc_type,
                exc_msg,
            )
            try:
                return await _fallback_realtime_anomalies(
                    start_time, now_utc, hours, building_type, db
                )
            except Exception as fb_exc:
                # 降级路径也失败（例如 session 已污染），返回安全空响应
                logger.error(
                    "降级路径执行失败: %s: %s",
                    type(fb_exc).__name__,
                    fb_exc,
                )
                return {
                    "anomalies": [],
                    "total": 0,
                    "check_period": {
                        "start": start_time.isoformat(),
                        "end": now_utc.isoformat(),
                        "hours": hours,
                    },
                    "source": "fallback_error",
                    "error": "告警数据暂时不可用",
                }

    return await get_or_compute_json(cache_key, ttl_seconds, _compute)


async def _fallback_realtime_anomalies(
    start_time,
    now_utc,
    hours: int,
    building_type: str | None,
    db: AsyncSession,
) -> dict:
    """降级：实时扫描 energy_data 计算异常（兼容新 schema）。"""
    from datetime import timezone

    query = (
        select(EnergyData, Building.primary_space_usage)
        .join(Building, EnergyData.building_id == Building.building_id)
        .where(EnergyData.timestamp >= start_time)
    )
    if building_type:
        query = query.where(Building.primary_space_usage == building_type)
    query = query.order_by(EnergyData.timestamp.desc())

    result = await db.execute(query)
    rows = result.fetchall()

    anomalies = []
    for row in rows:
        ed, usage = row
        ts = ed.timestamp
        hour_utc = ts.hour if ts.tzinfo else ts.replace(tzinfo=timezone.utc).hour
        hour_local = (hour_utc + 8) % 24  # 转换为 CST（UTC+8）
        display = _BUILDING_NAMES.get(usage or "", usage or ed.building_id)

        # 降级路径中 meter_device_id 使用 building_id + '_elec' 格式（与 migration 008 约定一致）
        meter_id = ed.building_id + "_elec"

        if (
            ed.electricity_kwh is not None
            and 0 <= hour_local < 6
            and ed.electricity_kwh > 50
        ):
            anomalies.append({
                "timestamp": ts.isoformat(),
                "building_type": usage,
                "building_id": ed.building_id,
                "meter_device_id": meter_id,
                "rule": "night_high_power",
                "message": f"{display}夜间能耗异常：{ed.electricity_kwh:.1f} kWh",
                "actual_value": ed.electricity_kwh,
                "threshold": 50.0,
                "anomaly_status": "Anomaly",
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
# 异常根因桑基图（Sankey）聚合数据
# ---------------------------------------------------------------------------
_RULE_LABEL = {
    "water_leak": "水耗异常",
    "electricity_overload": "电耗超标",
    "hvac_overconsumption": "空调过耗",
    "db_flagged": "标注异常",
    "night_high_power": "夜间高耗",
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
    聚合 anomaly_events 中所有未解决异常的 rule_triggered → hvac_root_cause 流向与频次，
    供前端 Sankey 图渲染。

    返回格式:
      { nodes: [{name}], links: [{source, target, value}] }
    """
    try:
        # 聚合所有未解决异常：按 (rule_triggered, hvac_root_cause) 计数
        stmt = text("""
            SELECT rule_triggered,
                   hvac_root_cause,
                   COUNT(*) AS cnt
              FROM anomaly_events
             WHERE is_resolved = false
             GROUP BY rule_triggered, hvac_root_cause
             ORDER BY cnt DESC
        """)
        result = await db.execute(stmt)
        rows = result.fetchall()

        node_set: set[str] = set()
        links: list[dict] = []

        for rule, root_cause, cnt in rows:
            source = _RULE_LABEL.get(rule, rule or "未知规则")
            node_set.add(source)

            if root_cause and root_cause in _ROOT_CAUSE_LABEL:
                target = _ROOT_CAUSE_LABEL[root_cause]
            else:
                # 非 HVAC 规则没有 root_cause，映射到通用目标
                target = {
                    "water_leak": "管网漏损",
                    "electricity_overload": "负荷过载",
                    "db_flagged": "数据标注",
                    "night_high_power": "夜间异常运行",
                }.get(rule, "未分类")
            node_set.add(target)
            links.append({"source": source, "target": target, "value": cnt})

        nodes = [{"name": n} for n in sorted(node_set)]
        return {"nodes": nodes, "links": links}

    except Exception as exc:
        logger.warning("sankey 聚合查询失败，返回空数据: %s: %s", type(exc).__name__, exc)
        return {"nodes": [], "links": []}


# ---------------------------------------------------------------------------
# 调试：列出 MCP 工具
# ---------------------------------------------------------------------------
@router.get("/tools", summary="列出所有 MCP 工具（调试）")
async def get_tools():
    """返回当前注册的所有 MCP 工具名称与描述，用于开发调试。"""
    return {"tools": list_tools()}
