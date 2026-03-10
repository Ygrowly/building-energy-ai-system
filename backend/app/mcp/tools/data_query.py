"""
阶段二：原子能力库 —— 数据查询工具（Tool 1 / 2 / 4）
=====================================================
工具清单：
  query_energy_metrics       → Tool 1  直查 energy_data 时序原表
  get_device_live_status     → Tool 2  取最新 1 条传感器快照
  query_daily_energy_summary → Tool 4  查物化视图 daily_energy_summary

设计约定：
  · 所有工具为 async 函数，参数类型严格绑定 Schema 枚举，防止 SQL 注入
  · 报错统一返回 MCPError 字符串（让 LLM 看懂并自我修正），绝不抛 Exception
  · 每条返回记录必须携带 source_table / meter_device_id（数据血缘溯源）
"""
from __future__ import annotations

import time
from datetime import datetime, timezone

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Building, DailyEnergySummary, EnergyData
from app.schemas.mcp_schemas import (
    BuildingInfo,
    BuildingMetricStats,
    CompareMetricAcrossBuildingsInput,
    CompareMetricAcrossBuildingsOutput,
    CompareTimePeriodsInput,
    CompareTimePeriodsOutput,
    DailyEnergySummaryRecord,
    EnergyMetricRecord,
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

# 指标 → (DB列名, 单位) 映射表
_METRIC_META: dict[MetricType, tuple[str, str]] = {
    MetricType.ELECTRICITY_KWH:    ("electricity_kwh",             "kWh"),
    MetricType.WATER_M3:           ("water_m3",                    "m³"),
    MetricType.HVAC_ENERGY_KWH:    ("hvac_energy_kwh",             "kWh"),
    MetricType.HVAC_SUPPLY_TEMP_C: ("hvac_supply_temp_c",          "°C"),
    MetricType.HVAC_RETURN_TEMP_C: ("hvac_return_temp_c",          "°C"),
    MetricType.AMBIENT_TEMP_C:     ("ambient_temp_c",              "°C"),
    MetricType.HUMIDITY_RH_PCT:    ("humidity_rh_pct",             "%RH"),
    MetricType.OCCUPANCY_DENSITY:  ("occupancy_density_per_100sqm","人/100㎡"),
}


# ---------------------------------------------------------------------------
# 公共辅助：通过 building_type 查找 meter_device_id 和真实 building_id
#
# 数据库中：
#   building_type 列 = 'Education'/'Office'/'Public'（工具传参使用此值）
#   building_id   列 = 实际资产名 'Bobcat_office_Kassandra'（energy_data 外键使用此值）
# 此函数被 data_query.py 和 physics_calc.py 共同引用，避免重复逻辑。
# ---------------------------------------------------------------------------

async def get_building_info(
    session: AsyncSession, building_type: str
) -> tuple[str, str] | tuple[None, None]:
    """
    通过 building_type（如 'Office'）查找对应建筑。
    返回 (meter_device_id, actual_building_id)，找不到返回 (None, None)。
    支持动态扩展：数据库新增楼宇后无需修改代码。
    """
    result = await session.execute(
        select(Building.meter_device_id, Building.building_id)
        .where(Building.building_type == building_type)
    )
    row = result.first()
    if row is None:
        return None, None
    return row[0], row[1]


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
    按 meter_device_id 反查 building_id，再取 energy_data 最新 1 条记录。
    场景：驾驶舱首页"实时设备状态"卡片。
    """
    # meter_device_id → building_id
    building_result = await session.execute(
        select(Building.building_id).where(
            Building.meter_device_id == inp.meter_device_id
        )
    )
    building_id = building_result.scalar_one_or_none()
    if building_id is None:
        return MCPError(
            error=f"设备 '{inp.meter_device_id}' 不存在，请核对 meter_device_id 格式（M-XXX-NNN）",
            error_code="DEVICE_NOT_FOUND",
            tool_name="get_device_live_status",
        )

    # 取最新 1 条（命中复合索引头部，极速）
    result = await session.execute(
        select(EnergyData)
        .where(EnergyData.building_id == building_id)
        .order_by(EnergyData.timestamp.desc())
        .limit(1)
    )
    row: EnergyData | None = result.scalar_one_or_none()
    if row is None:
        return MCPError(
            error=f"设备 '{inp.meter_device_id}' 暂无历史数据记录",
            error_code="NO_DATA_FOUND",
            tool_name="get_device_live_status",
        )

    return GetDeviceLiveStatusOutput(
        meter_device_id=inp.meter_device_id,
        operation_status=OperationStatus(row.operation_status.value),
        ambient_temp_c=float(row.ambient_temp_c or 0),
        humidity_rh_pct=float(row.humidity_rh_pct or 0),
        electricity_kwh=float(row.electricity_kwh or 0),
        occupancy_density_per_100sqm=float(row.occupancy_density_per_100sqm or 0),
        last_updated_utc=row.timestamp,
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

    if granularity == "day":
        # 走物化视图，最快
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
                building_id=row.building_id,
                total_electricity_kwh=float(row.total_electricity_kwh or 0),
                avg_ambient_temp=float(row.avg_ambient_temp or 0),
                max_occupancy=float(row.max_occupancy or 0),
            )
            for row in rows_orm
        ]
    else:
        # 直查 energy_data，用 date_trunc 做周/月聚合
        sql = text(f"""
            SELECT
                date_trunc(:gran, "timestamp") AS period,
                SUM(electricity_kwh)           AS total_electricity_kwh,
                AVG(ambient_temp_c)            AS avg_ambient_temp,
                MAX(occupancy_density_per_100sqm) AS max_occupancy
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
                day=str(row[0]),
                building_id=inp.building_id,
                total_electricity_kwh=float(row[1] or 0),
                avg_ambient_temp=float(row[2] or 0),
                max_occupancy=float(row[3] or 0),
            )
            for row in rows_raw
        ]

    elapsed_ms = int((time.perf_counter() - t_start) * 1000)
    return QueryDailyEnergySummaryOutput(
        records=records,
        building_id=inp.building_id,
        query_ms=elapsed_ms,
    )


# ===========================================================================
# Tool 9：list_available_buildings
# ===========================================================================

async def list_available_buildings(
    session: AsyncSession,
) -> ListBuildingsOutput:
    """
    返回数据库中所有建筑的 building_type、meter_device_id 和面积。
    Agent 在不确定有哪些合法 building_id 时，应先调用此工具再传参，
    避免因楼宇名称错误触发 BUILDING_NOT_FOUND。
    """
    result = await session.execute(
        select(
            Building.building_id,
            Building.building_type,
            Building.meter_device_id,
            Building.sqm,
        ).order_by(Building.building_type)
    )
    rows = result.fetchall()

    buildings = [
        BuildingInfo(
            building_id=r[0],
            building_type=r[1],
            meter_device_id=r[2],
            sqm=float(r[3]) if r[3] is not None else None,
        )
        for r in rows
    ]
    return ListBuildingsOutput(buildings=buildings, total=len(buildings))


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
            select(Building.building_type, Building.meter_device_id, Building.building_id, Building.sqm)
            .where(Building.building_type.in_(inp.building_ids))
        )
    else:
        bld_rows = await session.execute(
            select(Building.building_type, Building.meter_device_id, Building.building_id, Building.sqm)
        )
    buildings_map = {r[2]: (r[0], r[1], r[3]) for r in bld_rows.fetchall()}  # actual_bid → (type, meter_id, sqm)

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
        bld_type, meter_id, sqm = buildings_map[r[0]]
        agg_val = round(float(r[1]), 4)
        # 能耗强度：仅当指标为 electricity_kwh 且面积有效时计算
        intensity: float | None = None
        if inp.metric == MetricType.ELECTRICITY_KWH and sqm and sqm > 0:
            intensity = round(agg_val / sqm, 6)
        stats.append(
            BuildingMetricStats(
                building_type=bld_type,
                meter_device_id=meter_id,
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
        return MCPError(
            error="两个时段均无数据，请确认时间范围是否正确（数据覆盖 2016-04-01 ~ 2016-05-02）",
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
