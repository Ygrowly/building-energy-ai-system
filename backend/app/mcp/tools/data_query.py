"""
阶段二：原子能力库 —— 数据查询工具（Tool 1 / 2 / 4 / 9 / 10 / 11）
=====================================================================
工具清单：
  query_energy_metrics           → Tool 1   直查 energy_data 时序原表
  get_device_live_status         → Tool 2   查楼宇下所有设备实时状态（device_status_latest）
  query_daily_energy_summary     → Tool 4   查物化视图 daily_energy_summary
  list_available_buildings       → Tool 9   列出所有楼宇及其设备（含 timezone）
  compare_metric_across_buildings→ Tool 10  多楼宇横向对比
  compare_time_periods           → Tool 11  同环比分析

设计约定：
  · 所有工具为 async 函数，参数类型严格绑定 Schema 枚举，防止 SQL 注入
  · 报错统一返回 MCPError 字符串（让 LLM 看懂并自我修正），绝不抛 Exception
  · 每条返回记录必须携带 source_table / meter_device_id（数据血缘溯源）
  · meter_device_id 优先取 devices 表中该楼宇的 ElectricityMeter 设备 ID
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timezone

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import ProgrammingError

from app.db.models import Building, DailyEnergySummary, Device, DeviceStatusLatest, EnergyData
from app.schemas.mcp_schemas import (
    BuildingInfo,
    BuildingMetricStats,
    CompareMetricAcrossBuildingsInput,
    CompareMetricAcrossBuildingsOutput,
    CompareTimePeriodsInput,
    CompareTimePeriodsOutput,
    DailyEnergySummaryRecord,
    DeviceInfo,
    EnergyMetricRecord,
    DeviceLiveStatus,
    GetDeviceLiveStatusInput,
    GetDeviceLiveStatusOutput,
    ListBuildingsOutput,
    MCPError,
    MetricType,
    OperationStatus,
    QueryDailyEnergySummaryInput,
    QueryDailyEnergySummaryOutput,
    QueryEnergyMetricsInput,
    QueryEnergyMetricsOutput,
)

logger = logging.getLogger(__name__)

# 指标 → (DB列名, 单位) 映射表（与 Supabase energy_data 实际列名严格一致）
_METRIC_META: dict[MetricType, tuple[str, str]] = {
    MetricType.ELECTRICITY_KWH:   ("electricity_kwh",   "kWh"),
    MetricType.WATER_M3:          ("water_m3",          "m³"),
    MetricType.HAC_ENERGY:        ("hac_energy",        "kWh"),
    MetricType.SIM_SUPPLY_TEMP_C: ("sim_supply_temp_c", "°C"),
    MetricType.SIM_RETURN_TEMP_C: ("sim_return_temp_c", "°C"),
    MetricType.AIR_TEMP_C:        ("air_temp_c",        "°C"),
    MetricType.DEW_TEMP_C:        ("dew_temp_c",        "°C"),
    MetricType.HUMIDITY_RH_PCT:   ("humidity_rh_pct",   "%RH"),
}


# ---------------------------------------------------------------------------
# 公共辅助：通过 building_type 查找 meter_device_id 和真实 building_id
#
# 数据库中：
#   building_type 列 = 'Education'/'Office'/'Public services'（工具传参使用此值）
#   building_id   列 = 实际资产名 'Fox_office_Alice'（energy_data 外键使用此值）
#   meter_device_id  = devices 表中该楼宇的 electricity 设备 ID（血缘溯源首选）
# 此函数被 data_query.py 和 physics_calc.py 共同引用，避免重复逻辑。
# ---------------------------------------------------------------------------

async def get_building_info(
    session: AsyncSession, building_type: str
) -> tuple[str, str] | tuple[None, None]:
    """
    通过 primary_space_usage（如 'Office'）查找对应建筑。
    返回 (meter_device_id, actual_building_id)，找不到返回 (None, None)。

    meter_device_id 优先取 devices 表中该楼宇的 electricity 类型设备 ID；
    若 devices 表为空或无电表设备，退化为 building_id（向后兼容）。
    支持动态扩展：数据库新增楼宇后无需修改代码。
    """
    result = await session.execute(
        select(Building.building_id)
        .where(Building.primary_space_usage == building_type)
    )
    row = result.first()
    if row is None:
        return None, None
    actual_bid = row[0]

    # 优先取电表设备 ID 作为 meter_device_id（数据血缘溯源）
    dev_result = await session.execute(
        select(Device.device_id)
        .where(Device.building_id == actual_bid)
        .where(Device.device_type == "electricity")
        .limit(1)
    )
    dev_row = dev_result.first()
    meter_id = dev_row[0] if dev_row else actual_bid  # 无设备记录时退化为 building_id

    return meter_id, actual_bid


# ===========================================================================
# Tool 1：query_energy_metrics
# ===========================================================================

async def query_energy_metrics(
    inp: QueryEnergyMetricsInput,
    session: AsyncSession,
) -> QueryEnergyMetricsOutput | MCPError:
    """
    查询 energy_data 时序原表中指定建筑、时间段、指标的逐小时读数。
    利用复合索引 (building_id, timestamp DESC) 确保亚毫秒级响应。
    """
    meter_id, actual_bid = await get_building_info(session, inp.building_id)
    if meter_id is None:
        return MCPError(
            error=f"未找到建筑类型 '{inp.building_id}'，请先调用 list_available_buildings 确认合法值",
            error_code="BUILDING_NOT_FOUND",
            tool_name="query_energy_metrics",
        )

    # 动态构建 SELECT 列（只选请求的指标，节省传输量）
    col_names = [_METRIC_META[m][0] for m in inp.metrics]
    select_cols = ", ".join(f'"{c}"' for c in col_names)

    sql = text(f"""
        SELECT "timestamp", {select_cols}
        FROM energy_data
        WHERE building_id = :bid
          AND "timestamp" >= :start
          AND "timestamp" <= :end
        ORDER BY "timestamp" DESC
    """)

    result = await session.execute(
        sql,
        {
            "bid":   actual_bid,
            "start": inp.time_range.start,
            "end":   inp.time_range.end,
        },
    )
    rows = result.fetchall()

    records: list[EnergyMetricRecord] = []
    for row in rows:
        ts: datetime = row[0]
        for idx, metric in enumerate(inp.metrics):
            col_name, unit = _METRIC_META[metric]
            raw_val = row[idx + 1]
            if raw_val is None:
                continue
            records.append(
                EnergyMetricRecord(
                    timestamp=ts,
                    building_id=inp.building_id,
                    metric=metric,
                    value=float(raw_val),
                    unit=unit,
                    meter_device_id=meter_id,
                )
            )

    return QueryEnergyMetricsOutput(
        records=records,
        total_count=len(records),
        building_id=inp.building_id,
        meter_device_id=meter_id,
    )


# ===========================================================================
# Tool 2：get_device_live_status
# ===========================================================================

async def get_device_live_status(
    inp: GetDeviceLiveStatusInput,
    session: AsyncSession,
) -> GetDeviceLiveStatusOutput | MCPError:
    """
    查询指定楼宇下所有设备的实时状态快照（来自 device_status_latest 表）。
    若 device_status_latest 中暂无该楼宇数据，自动降级为 devices 表的静态设备清单。
    场景：工单设备定位、驾驶舱设备健康概览。
    """
    # building_type → building_id
    bld_result = await session.execute(
        select(Building.building_id, Building.primary_space_usage)
        .where(Building.primary_space_usage == inp.building_type)
    )
    bld_row = bld_result.first()
    if bld_row is None:
        return MCPError(
            error=f"建筑类型 '{inp.building_type}' 不存在，请先调用 list_available_buildings 确认合法值",
            error_code="BUILDING_NOT_FOUND",
            tool_name="get_device_live_status",
        )
    building_id, usage = bld_row

    # ── 优先查 device_status_latest（实时快照）────────────────────────
    live_rows_result = await session.execute(
        select(DeviceStatusLatest)
        .where(DeviceStatusLatest.building_id == building_id)
        .order_by(DeviceStatusLatest.device_type)
    )
    live_rows = live_rows_result.scalars().all()

    if live_rows:
        devices = [
            DeviceLiveStatus(
                device_id=r.device_id,
                device_type=r.device_type,
                online_status=r.online_status,
                running_state=r.running_state,
                health_status=r.health_status,
                latest_power_kw=r.latest_power_kw,
                latest_flow_rate=r.latest_flow_rate,
                latest_supply_temp_c=r.latest_supply_temp_c,
                latest_return_temp_c=r.latest_return_temp_c,
                last_seen_at=r.last_seen_at,
            )
            for r in live_rows
        ]
        return GetDeviceLiveStatusOutput(
            building_type=usage or inp.building_type,
            building_id=building_id,
            devices=devices,
            total=len(devices),
            has_live_data=True,
            source_table="device_status_latest",
        )

    # ── 降级：device_status_latest 无数据，返回 devices 静态清单 ────
    dev_rows_result = await session.execute(
        select(Device.device_id, Device.device_type)
        .where(Device.building_id == building_id)
        .order_by(Device.device_type)
    )
    dev_rows = dev_rows_result.fetchall()

    devices = [
        DeviceLiveStatus(device_id=r[0], device_type=r[1])
        for r in dev_rows
    ]
    return GetDeviceLiveStatusOutput(
        building_type=usage or inp.building_type,
        building_id=building_id,
        devices=devices,
        total=len(devices),
        has_live_data=False,
        source_table="devices",
    )


# ===========================================================================
# Tool 4：query_daily_energy_summary
# ===========================================================================

async def query_daily_energy_summary(
    inp: QueryDailyEnergySummaryInput,
    session: AsyncSession,
) -> QueryDailyEnergySummaryOutput | MCPError:
    """
    查询能耗趋势汇总数据，支持 day/week/month 三种粒度。
    - day：查物化视图 daily_energy_summary（极速，毫秒级）
    - week/month：直查 energy_data 用 date_trunc 聚合（稍慢，但支持任意粒度）
    """
    meter_id, actual_bid = await get_building_info(session, inp.building_id)
    if meter_id is None:
        return MCPError(
            error=f"未找到建筑类型 '{inp.building_id}'，请先调用 list_available_buildings 确认合法值",
            error_code="BUILDING_NOT_FOUND",
            tool_name="query_daily_energy_summary",
        )

    t_start = time.perf_counter()
    granularity = inp.granularity  # "day" | "week" | "month"

    # --- 智能粒度纠正 ---
    try:
        _start = datetime.fromisoformat(str(inp.date_range.start).replace("Z", "+00:00"))
        _end = datetime.fromisoformat(str(inp.date_range.end).replace("Z", "+00:00"))
        span_days = (_end - _start).days
    except Exception:
        span_days = 0

    original_gran = granularity
    if span_days > 0:
        if granularity == "month" and span_days <= 180:
            granularity = "day"
        elif granularity == "day" and span_days > 365:
            granularity = "week"
        elif granularity == "week" and span_days <= 14:
            granularity = "day"
        if granularity != original_gran:
            logger.info(
                "粒度自动纠正: %s -> %s (span=%d天)", original_gran, granularity, span_days,
            )

    def _format_period(raw: str, gran: str) -> str:
        s = str(raw)[:10]
        if gran == "month":
            return s[:7]  # "2026-01"
        return s          # "2026-01-15"

    _FALLBACK_SQL = text("""
        SELECT
            date_trunc('day', "timestamp")::date AS day,
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
          AND "timestamp" >= :start
          AND "timestamp" <= :end
        GROUP BY date_trunc('day', "timestamp")::date
        ORDER BY day ASC
    """)

    def _rows_to_records(rows_raw):
        return [
            DailyEnergySummaryRecord(
                day=str(row[0]),
                building_id=inp.building_id,
                total_electricity_kwh=float(row[1] or 0),
                avg_ambient_temp=float(row[2] or 0),
                total_water_m3=float(row[3] or 0),
                total_hac_energy=float(row[4] or 0),
                avg_supply_temp=float(row[5] or 0),
                avg_return_temp=float(row[6] or 0),
                avg_humidity=float(row[7] or 0),
                avg_dew_temp=float(row[8] or 0),
            )
            for row in rows_raw
        ]

    if granularity == "day":
        try:
            result = await session.execute(
                select(DailyEnergySummary)
                .where(DailyEnergySummary.building_id == actual_bid)
                .where(DailyEnergySummary.day >= inp.date_range.start)  # type: ignore[attr-defined]
                .where(DailyEnergySummary.day <= inp.date_range.end)    # type: ignore[attr-defined]
                .order_by(DailyEnergySummary.day.asc())
            )
            rows_orm = result.scalars().all()
            records = [
                DailyEnergySummaryRecord(
                    day=str(row.day),
                    building_id=inp.building_id,
                    total_electricity_kwh=float(row.total_electricity_kwh or 0),
                    avg_ambient_temp=float(row.avg_ambient_temp or 0),
                    total_water_m3=float(row.total_water_m3 or 0),
                    total_hac_energy=float(row.total_hac_energy or 0),
                    avg_supply_temp=float(row.avg_supply_temp or 0),
                    avg_return_temp=float(row.avg_return_temp or 0),
                    avg_humidity=float(row.avg_humidity or 0),
                    avg_dew_temp=float(row.avg_dew_temp or 0),
                )
                for row in rows_orm
            ]
            if not records:
                logger.info(
                    "daily_energy_summary 返回空，降级 energy_data: building=%s range=%s..%s",
                    inp.building_id, inp.date_range.start, inp.date_range.end,
                )
                fb = await session.execute(
                    _FALLBACK_SQL,
                    {"bid": actual_bid, "start": inp.date_range.start, "end": inp.date_range.end},
                )
                records = _rows_to_records(fb.fetchall())
        except ProgrammingError as exc:
            msg = str(exc).lower()
            if "daily_energy_summary" in msg and ("does not exist" in msg or "undefined" in msg):
                logger.warning(
                    "daily_energy_summary 物化视图缺失，降级 energy_data: building=%s",
                    inp.building_id,
                )
                fb = await session.execute(
                    _FALLBACK_SQL,
                    {"bid": actual_bid, "start": inp.date_range.start, "end": inp.date_range.end},
                )
                records = _rows_to_records(fb.fetchall())
                elapsed_ms = int((time.perf_counter() - t_start) * 1000)
                return QueryDailyEnergySummaryOutput(
                    records=records,
                    building_id=inp.building_id,
                    granularity=granularity,
                    date_range_days=span_days,
                    query_ms=elapsed_ms,
                )

            return MCPError(
                error=f"查询 daily_energy_summary 失败，请稍后重试。{type(exc).__name__}",
                error_code="DAILY_SUMMARY_QUERY_FAILED",
                tool_name="query_daily_energy_summary",
            )
    else:
        # 直查 energy_data，用 date_trunc 做周/月聚合
        sql = text(f"""
            SELECT
                date_trunc(:gran, "timestamp") AS period,
                SUM(electricity_kwh)           AS total_electricity_kwh,
                AVG(air_temp_c)                AS avg_ambient_temp,
                SUM(water_m3)                  AS total_water_m3,
                SUM(hac_energy)                AS total_hac_energy,
                AVG(sim_supply_temp_c)         AS avg_supply_temp,
                AVG(sim_return_temp_c)         AS avg_return_temp,
                AVG(humidity_rh_pct)           AS avg_humidity,
                AVG(dew_temp_c)                AS avg_dew_temp
            FROM energy_data
            WHERE building_id = :bid
              AND "timestamp" >= :start
              AND "timestamp" <= :end
            GROUP BY period
            ORDER BY period ASC
        """)
        result = await session.execute(
            sql,
            {
                "gran":  granularity,
                "bid":   actual_bid,
                "start": inp.date_range.start,
                "end":   inp.date_range.end,
            },
        )
        rows_raw = result.fetchall()
        records = [
            DailyEnergySummaryRecord(
                day=_format_period(str(row[0]), granularity),
                building_id=inp.building_id,
                total_electricity_kwh=float(row[1] or 0),
                avg_ambient_temp=float(row[2] or 0),
                total_water_m3=float(row[3] or 0),
                total_hac_energy=float(row[4] or 0),
                avg_supply_temp=float(row[5] or 0),
                avg_return_temp=float(row[6] or 0),
                avg_humidity=float(row[7] or 0),
                avg_dew_temp=float(row[8] or 0),
            )
            for row in rows_raw
        ]

    elapsed_ms = int((time.perf_counter() - t_start) * 1000)
    return QueryDailyEnergySummaryOutput(
        records=records,
        building_id=inp.building_id,
        granularity=granularity,
        date_range_days=span_days,
        query_ms=elapsed_ms,
    )


# ===========================================================================
# Tool 9：list_available_buildings
# ===========================================================================

# 楼宇列表缓存（启动时预加载，运行期间不变，服务重启自动刷新）
_buildings_cache: ListBuildingsOutput | None = None


async def list_available_buildings(
    session: AsyncSession,
) -> ListBuildingsOutput:
    """
    返回数据库中所有建筑的 building_type、面积、时区及关联设备列表。

    Agent 在以下场景应先调用此工具：
    1. 不确定有哪些合法 building_id 时（避免 BUILDING_NOT_FOUND）
    2. 需要 device_id 填写工单（从返回的 devices 列表中选取）
    3. 需要设备 ID 用于 rag_hybrid_search 的 metadata_filter.device_id 精准过滤

    启动时由 lifespan 预加载，后续调用直接返回缓存，0ms 响应。
    """
    global _buildings_cache
    if _buildings_cache is not None:
        return _buildings_cache

    # 查所有楼宇基本信息
    bld_result = await session.execute(
        select(
            Building.building_id,
            Building.primary_space_usage,
            Building.sqm,
        ).order_by(Building.primary_space_usage)
    )
    bld_rows = bld_result.fetchall()

    if not bld_rows:
        return ListBuildingsOutput(buildings=[], total=0)

    # 一次查出所有楼宇的设备（避免 N+1 查询）
    all_bid_list = [r[0] for r in bld_rows]
    dev_result = await session.execute(
        select(Device.device_id, Device.building_id, Device.device_type)
        .where(Device.building_id.in_(all_bid_list))
        .order_by(Device.building_id, Device.device_type)
    )
    # building_id → [DeviceInfo, ...]
    devices_by_building: dict[str, list[DeviceInfo]] = {}
    for drow in dev_result.fetchall():
        did, bid, dtype = drow
        devices_by_building.setdefault(bid, []).append(
            DeviceInfo(device_id=did, device_type=dtype)
        )

    buildings = [
        BuildingInfo(
            building_id=r[0],
            building_type=r[1] or r[0],
            sqm=float(r[2]) if r[2] is not None else None,
            devices=devices_by_building.get(r[0], []),
        )
        for r in bld_rows
    ]
    result = ListBuildingsOutput(buildings=buildings, total=len(buildings))
    _buildings_cache = result
    return result


def get_buildings_cache() -> ListBuildingsOutput | None:
    """返回启动时预加载的楼宇列表缓存（含完整 devices），无需 DB session。"""
    return _buildings_cache


# ===========================================================================
# Tool 10：compare_metric_across_buildings
# ===========================================================================

async def compare_metric_across_buildings(
    inp: CompareMetricAcrossBuildingsInput,
    session: AsyncSession,
) -> CompareMetricAcrossBuildingsOutput | MCPError:
    """
    对多栋楼在同一时间段内的同一指标做横向聚合对比。
    典型场景：
      · "A 楼和 B 楼去年供暖季的平均湿度差值"
      · "所有楼本月总用电量排名"
      · "教学楼和办公楼夏季峰值空调能耗对比"
    building_ids 为空时自动对比数据库中所有楼宇。
    """
    col_name, unit = _METRIC_META[inp.metric]
    agg_func = {"avg": "AVG", "sum": "SUM", "max": "MAX", "min": "MIN"}[inp.aggregation]

    # 确定要对比的楼宇（传空 = 全部），同时取 sqm 用于计算能耗强度
    if inp.building_ids:
        bld_rows = await session.execute(
            select(Building.primary_space_usage, Building.building_id, Building.sqm)
            .where(Building.primary_space_usage.in_(inp.building_ids))
        )
    else:
        bld_rows = await session.execute(
            select(Building.primary_space_usage, Building.building_id, Building.sqm)
        )
    buildings_map = {r[1]: (r[0], r[1], r[2]) for r in bld_rows.fetchall()}  # actual_bid → (usage, bid, sqm)

    if not buildings_map:
        return MCPError(
            error=f"未找到指定建筑 {inp.building_ids}，请先调用 list_available_buildings 确认合法值",
            error_code="BUILDING_NOT_FOUND",
            tool_name="compare_metric_across_buildings",
        )

    # 一次 SQL 查所有楼宇的聚合值，减少往返次数
    sql = text(f"""
        SELECT building_id, {agg_func}("{col_name}") AS agg_val, COUNT(*) AS cnt
        FROM energy_data
        WHERE building_id = ANY(:bids)
          AND "timestamp" >= :start
          AND "timestamp" <= :end
          AND "{col_name}" IS NOT NULL
        GROUP BY building_id
        ORDER BY agg_val DESC
    """)

    result = await session.execute(
        sql,
        {
            "bids":  list(buildings_map.keys()),
            "start": inp.time_range.start,
            "end":   inp.time_range.end,
        },
    )
    rows = result.fetchall()

    if not rows:
        return MCPError(
            error="指定时段内无数据，请确认时间范围是否正确",
            error_code="NO_DATA_FOUND",
            tool_name="compare_metric_across_buildings",
        )

    stats = []
    for r in rows:
        if r[0] not in buildings_map:
            continue
        usage, bid, sqm = buildings_map[r[0]]
        agg_val = round(float(r[1]), 4)
        # 能耗强度：仅当指标为 electricity_kwh 且面积有效时计算
        intensity: float | None = None
        if inp.metric == MetricType.ELECTRICITY_KWH and sqm and sqm > 0:
            intensity = round(agg_val / sqm, 6)
        stats.append(
            BuildingMetricStats(
                building_type=usage or bid,
                meter_device_id=bid,
                aggregated_value=agg_val,
                unit=unit,
                data_points=int(r[2]),
                sqm=float(sqm) if sqm else None,
                energy_intensity_kwh_per_sqm=intensity,
            )
        )

    return CompareMetricAcrossBuildingsOutput(
        metric=inp.metric,
        aggregation=inp.aggregation,
        results=stats,
        period_start=inp.time_range.start,
        period_end=inp.time_range.end,
    )


# ===========================================================================
# Tool 11：compare_time_periods — 同环比分析
# ===========================================================================

async def compare_time_periods(
    inp: CompareTimePeriodsInput,
    session: AsyncSession,
) -> CompareTimePeriodsOutput | MCPError:
    """
    对同一建筑、同一指标在两个时间段之间做同环比分析。
    返回当期值、基期值、绝对差值和相对变化率。
    """
    col_name, unit = _METRIC_META[inp.metric]
    agg_func = {"avg": "AVG", "sum": "SUM", "max": "MAX", "min": "MIN"}[inp.aggregation]

    meter_id, actual_bid = await get_building_info(session, inp.building_id)
    if meter_id is None:
        return MCPError(
            error=f"未找到建筑类型 '{inp.building_id}'，请先调用 list_available_buildings 确认合法值",
            error_code="BUILDING_NOT_FOUND",
            tool_name="compare_time_periods",
        )

    # 一次 SQL 查两个时段的聚合值（FILTER 子句，减少往返）
    sql = text(f"""
        SELECT
            {agg_func}("{col_name}") FILTER (WHERE "timestamp" >= :a_start AND "timestamp" <= :a_end) AS val_a,
            COUNT(*)                 FILTER (WHERE "timestamp" >= :a_start AND "timestamp" <= :a_end) AS cnt_a,
            {agg_func}("{col_name}") FILTER (WHERE "timestamp" >= :b_start AND "timestamp" <= :b_end) AS val_b,
            COUNT(*)                 FILTER (WHERE "timestamp" >= :b_start AND "timestamp" <= :b_end) AS cnt_b
        FROM energy_data
        WHERE building_id = :bid
          AND "{col_name}" IS NOT NULL
          AND "timestamp" >= :b_start
          AND "timestamp" <= :a_end
    """)

    result = await session.execute(
        sql,
        {
            "bid":     actual_bid,
            "a_start": inp.period_a.start,
            "a_end":   inp.period_a.end,
            "b_start": inp.period_b.start,
            "b_end":   inp.period_b.end,
        },
    )
    row = result.fetchone()

    if row is None or (row[0] is None and row[2] is None):
        from app.core.data_range import _fallback as _dr_fallback, _cached_range as _dr_cache
        dr = _dr_cache or _dr_fallback()
        return MCPError(
            error=f"两个时段均无数据，请确认时间范围是否正确（数据覆盖 {dr['min_date']} ~ {dr['max_date']}）",
            error_code="NO_DATA_FOUND",
            tool_name="compare_time_periods",
        )

    val_a = float(row[0]) if row[0] is not None else 0.0
    cnt_a = int(row[1]) if row[1] else 0
    val_b = float(row[2]) if row[2] is not None else 0.0
    cnt_b = int(row[3]) if row[3] else 0

    delta = round(val_a - val_b, 4)
    delta_pct: float | None = None
    if val_b != 0:
        delta_pct = round((val_a - val_b) / abs(val_b) * 100, 2)

    def _fmt_range(tr) -> str:
        return f"{tr.start.date()} ~ {tr.end.date()}"

    return CompareTimePeriodsOutput(
        building_id=inp.building_id,
        metric=inp.metric,
        aggregation=inp.aggregation,
        unit=unit,
        period_a_label=_fmt_range(inp.period_a),
        period_b_label=_fmt_range(inp.period_b),
        period_a_value=round(val_a, 4),
        period_b_value=round(val_b, 4),
        delta=delta,
        delta_pct=delta_pct,
        data_points_a=cnt_a,
        data_points_b=cnt_b,
    )
