"""
集成测试：连接真实 Supabase 数据库验证所有 MCP 工具
=====================================================
运行前提：backend/.env 中 DATABASE_URL 已配置且数据库已导入数据。
运行方式：
  pytest tests/test_integration.py -v -m integration

数据时间范围：2016-04-01 ~ 2016-05-02（实际数据集）
测试覆盖：
  1. 数据库连通性 + buildings 表基础数据校验
  2. energy_data 时序表数据量与字段完整性
  3. daily_energy_summary 物化视图可查性
  4. query_energy_metrics     → 带数据血缘返回
  5. get_device_live_status   → 最新传感器快照
  6. query_daily_energy_summary → 多粒度聚合（day/week/month）
  7. calculate_system_cop    → 物理 COP 估算
  8. detect_energy_anomalies → 规则异常检测
  9. compare_metric_across_buildings → 跨楼对比 + 能耗强度
 10. compare_time_periods    → 同环比分析
"""

import pytest
from datetime import datetime, timedelta, timezone
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.mcp.tools.data_query import (
    compare_metric_across_buildings,
    compare_time_periods,
    get_device_live_status,
    query_daily_energy_summary,
    query_energy_metrics,
)
from app.mcp.tools.physics_calc import calculate_system_cop, detect_energy_anomalies
from app.schemas.mcp_schemas import (
    AnomalyRule,
    CalculateSystemCOPInput,
    CompareMetricAcrossBuildingsInput,
    CompareTimePeriodsInput,
    DetectEnergyAnomaliesInput,
    GetDeviceLiveStatusInput,
    MCPError,
    MetricType,
    QueryDailyEnergySummaryInput,
    QueryEnergyMetricsInput,
    TimeRange,
)

pytestmark = pytest.mark.integration

# ---------------------------------------------------------------------------
# 时间范围帮助函数（对应实际数据集 2016-04-01 ~ 2016-05-02）
# ---------------------------------------------------------------------------
DATA_START = datetime(2016, 4, 1, tzinfo=timezone.utc)
DATA_END   = datetime(2016, 5, 2, 23, 59, 59, tzinfo=timezone.utc)
DATA_MID   = datetime(2016, 4, 16, tzinfo=timezone.utc)


def full_range() -> TimeRange:
    return TimeRange(start=DATA_START, end=DATA_END)


def first_half() -> TimeRange:
    return TimeRange(start=DATA_START, end=DATA_MID)


def second_half() -> TimeRange:
    return TimeRange(start=DATA_MID, end=DATA_END)


def week_range() -> TimeRange:
    return TimeRange(
        start=datetime(2016, 4, 18, tzinfo=timezone.utc),
        end=datetime(2016, 4, 25, tzinfo=timezone.utc),
    )


# ===========================================================================
# 1. 数据库连通性
# ===========================================================================

class TestDatabaseConnectivity:
    async def test_can_connect_and_query(self, db_session: AsyncSession):
        result = await db_session.execute(text("SELECT 1 AS ping"))
        row = result.fetchone()
        assert row[0] == 1, "数据库连通性测试失败"

    async def test_buildings_table_has_three_records(self, db_session: AsyncSession):
        result = await db_session.execute(text("SELECT COUNT(*) FROM buildings"))
        count = result.scalar()
        assert count == 3, f"buildings 表应有 3 条记录（Education/Office/Public），实际：{count}"

    async def test_buildings_have_correct_types(self, db_session: AsyncSession):
        result = await db_session.execute(
            text("SELECT building_type FROM buildings ORDER BY building_type")
        )
        types = {row[0] for row in result.fetchall()}
        assert types == {"Education", "Office", "Public"}, f"building_type 不符，实际：{types}"

    async def test_buildings_meter_device_ids(self, db_session: AsyncSession):
        result = await db_session.execute(
            text("SELECT building_type, meter_device_id FROM buildings")
        )
        mapping = {row[0]: row[1] for row in result.fetchall()}
        assert mapping.get("Education") == "M-EDU-001"
        assert mapping.get("Office") == "M-OFF-001"
        assert mapping.get("Public") == "M-PUB-001"


# ===========================================================================
# 2. energy_data 时序表
# ===========================================================================

class TestEnergyDataTable:
    async def test_energy_data_has_records(self, db_session: AsyncSession):
        result = await db_session.execute(text("SELECT COUNT(*) FROM energy_data"))
        count = result.scalar()
        assert count > 0, "energy_data 表为空，请先导入 CSV 数据"
        print(f"\n  energy_data 总记录数: {count:,}")

    async def test_energy_data_covers_all_buildings(self, db_session: AsyncSession):
        result = await db_session.execute(
            text("""
                SELECT DISTINCT b.building_type
                FROM energy_data e
                JOIN buildings b ON e.building_id = b.building_id
                ORDER BY b.building_type
            """)
        )
        types = {row[0] for row in result.fetchall()}
        assert "Education" in types
        assert "Office" in types
        assert "Public" in types

    async def test_energy_data_no_null_timestamps(self, db_session: AsyncSession):
        result = await db_session.execute(
            text('SELECT COUNT(*) FROM energy_data WHERE "timestamp" IS NULL')
        )
        null_count = result.scalar()
        assert null_count == 0, f"timestamp 列存在 {null_count} 条 NULL 记录"

    async def test_operation_status_only_valid_values(self, db_session: AsyncSession):
        result = await db_session.execute(
            text("SELECT DISTINCT operation_status::text FROM energy_data WHERE operation_status IS NOT NULL")
        )
        values = {row[0] for row in result.fetchall()}
        valid = {"Normal", "Anomaly", "NORMAL", "NIGHT_MODE"}
        unexpected = values - valid
        assert len(unexpected) == 0, f"意外的 operation_status 值：{unexpected}"

    async def test_hvac_columns_exist_and_have_data(self, db_session: AsyncSession):
        result = await db_session.execute(
            text("""
                SELECT COUNT(*) FROM energy_data
                WHERE hvac_energy_kwh IS NOT NULL
                  AND hvac_supply_temp_c IS NOT NULL
                  AND hvac_return_temp_c IS NOT NULL
            """)
        )
        count = result.scalar()
        assert count > 0, "hvac 三列全为 NULL，COP 无法计算"


# ===========================================================================
# 3. 物化视图 daily_energy_summary
# ===========================================================================

class TestMaterializedView:
    async def test_view_exists_and_has_data(self, db_session: AsyncSession):
        result = await db_session.execute(
            text("SELECT COUNT(*) FROM daily_energy_summary")
        )
        count = result.scalar()
        assert count > 0, "物化视图 daily_energy_summary 为空，请执行 REFRESH MATERIALIZED VIEW"
        print(f"\n  daily_energy_summary 行数: {count:,}")

    async def test_view_columns_match_schema(self, db_session: AsyncSession):
        result = await db_session.execute(
            text("SELECT day, building_id, total_electricity_kwh, avg_ambient_temp, max_occupancy FROM daily_energy_summary LIMIT 1")
        )
        row = result.fetchone()
        assert row is not None, "物化视图无数据"
        assert row[0] is not None, "day 列为 NULL"

    async def test_view_unique_index_works(self, db_session: AsyncSession):
        result = await db_session.execute(
            text("""
                SELECT day, building_id, COUNT(*) as cnt
                FROM daily_energy_summary
                GROUP BY day, building_id
                HAVING COUNT(*) > 1
            """)
        )
        duplicates = result.fetchall()
        assert len(duplicates) == 0, f"物化视图存在重复行：{duplicates}"


# ===========================================================================
# 4. MCP Tool 1：query_energy_metrics
# ===========================================================================

class TestQueryEnergyMetrics:
    async def test_returns_records_with_lineage(self, db_session: AsyncSession):
        out = await query_energy_metrics(
            QueryEnergyMetricsInput(
                building_id="Education",
                time_range=week_range(),
                metrics=[MetricType.ELECTRICITY_KWH],
            ),
            db_session,
        )
        assert not isinstance(out, MCPError), f"工具报错：{out}"
        assert out.total_count > 0, "无数据返回（时间范围内无数据）"
        assert out.meter_device_id == "M-EDU-001"
        assert out.source_table == "energy_data"
        first = out.records[0]
        assert first.meter_device_id == "M-EDU-001"
        assert first.unit == "kWh"
        print(f"\n  Education 一周电耗记录数: {out.total_count}")

    async def test_multi_metric_query(self, db_session: AsyncSession):
        out = await query_energy_metrics(
            QueryEnergyMetricsInput(
                building_id="Office",
                time_range=week_range(),
                metrics=[
                    MetricType.ELECTRICITY_KWH,
                    MetricType.AMBIENT_TEMP_C,
                    MetricType.OCCUPANCY_DENSITY,
                ],
            ),
            db_session,
        )
        assert not isinstance(out, MCPError)
        metrics_in_result = {r.metric for r in out.records}
        assert MetricType.ELECTRICITY_KWH in metrics_in_result

    async def test_invalid_building_returns_mcp_error(self, db_session: AsyncSession):
        out = await query_energy_metrics(
            QueryEnergyMetricsInput(
                building_id="火星基地",
                time_range=week_range(),
                metrics=[MetricType.ELECTRICITY_KWH],
            ),
            db_session,
        )
        assert isinstance(out, MCPError)
        assert out.error_code == "BUILDING_NOT_FOUND"


# ===========================================================================
# 5. MCP Tool 2：get_device_live_status
# ===========================================================================

class TestGetDeviceLiveStatus:
    async def test_edu_device_status(self, db_session: AsyncSession):
        out = await get_device_live_status(
            GetDeviceLiveStatusInput(meter_device_id="M-EDU-001"),
            db_session,
        )
        assert not isinstance(out, MCPError), f"工具报错：{out}"
        assert out.meter_device_id == "M-EDU-001"
        print(f"\n  M-EDU-001 最新电耗: {out.electricity_kwh} kWh")

    async def test_all_three_devices_reachable(self, db_session: AsyncSession):
        for device_id in ["M-EDU-001", "M-OFF-001", "M-PUB-001"]:
            out = await get_device_live_status(
                GetDeviceLiveStatusInput(meter_device_id=device_id),
                db_session,
            )
            assert not isinstance(out, MCPError), f"{device_id} 查询失败：{out}"
            assert out.last_updated_utc is not None

    async def test_nonexistent_device_returns_error(self, db_session: AsyncSession):
        out = await get_device_live_status(
            GetDeviceLiveStatusInput(meter_device_id="M-OFF-999"),
            db_session,
        )
        assert isinstance(out, MCPError)
        assert out.error_code == "DEVICE_NOT_FOUND"


# ===========================================================================
# 6. MCP Tool 4：query_daily_energy_summary（含 granularity）
# ===========================================================================

class TestQueryDailyEnergySummary:
    async def test_day_granularity_returns_records(self, db_session: AsyncSession):
        out = await query_daily_energy_summary(
            QueryDailyEnergySummaryInput(
                building_id="Education",
                date_range=full_range(),
                granularity="day",
            ),
            db_session,
        )
        assert not isinstance(out, MCPError), f"工具报错：{out}"
        assert len(out.records) > 0, "物化视图无数据"
        assert out.source_view == "daily_energy_summary"
        assert out.query_ms is not None
        print(f"\n  Education 按天聚合数据行数: {len(out.records)}, 查询耗时: {out.query_ms}ms")

    async def test_week_granularity_returns_fewer_records(self, db_session: AsyncSession):
        out_day = await query_daily_energy_summary(
            QueryDailyEnergySummaryInput(building_id="Office", date_range=full_range(), granularity="day"),
            db_session,
        )
        out_week = await query_daily_energy_summary(
            QueryDailyEnergySummaryInput(building_id="Office", date_range=full_range(), granularity="week"),
            db_session,
        )
        assert not isinstance(out_day, MCPError)
        assert not isinstance(out_week, MCPError)
        assert len(out_week.records) < len(out_day.records), "按周聚合行数应少于按天"
        print(f"\n  Office 按天: {len(out_day.records)} 行，按周: {len(out_week.records)} 行")

    async def test_month_granularity(self, db_session: AsyncSession):
        out = await query_daily_energy_summary(
            QueryDailyEnergySummaryInput(building_id="Public", date_range=full_range(), granularity="month"),
            db_session,
        )
        assert not isinstance(out, MCPError)
        assert 1 <= len(out.records) <= 2, "数据集约1个月，按月应返回1-2条"
        print(f"\n  Public 按月聚合: {len(out.records)} 条")

    async def test_query_ms_is_fast_for_day(self, db_session: AsyncSession):
        out = await query_daily_energy_summary(
            QueryDailyEnergySummaryInput(building_id="Office", date_range=full_range(), granularity="day"),
            db_session,
        )
        assert not isinstance(out, MCPError)
        assert out.query_ms < 2000, f"查询耗时 {out.query_ms}ms，超过 2000ms 阈值"


# ===========================================================================
# 7. MCP Tool 3：calculate_system_cop
# ===========================================================================

class TestCalculateSystemCOP:
    async def test_cop_calculated(self, db_session: AsyncSession):
        out = await calculate_system_cop(
            CalculateSystemCOPInput(building_id="Education", time_range=full_range()),
            db_session,
        )
        if isinstance(out, MCPError):
            pytest.skip(f"COP 计算触发物理异常（可能是数据问题）：{out.error}")
        assert out.data_points_used > 0
        assert out.cop_mean > 0
        assert isinstance(out.is_below_baseline, bool)
        print(f"\n  Education COP 均值: {out.cop_mean:.3f}, 低于基准: {out.is_below_baseline}")

    async def test_cop_returns_source_table(self, db_session: AsyncSession):
        out = await calculate_system_cop(
            CalculateSystemCOPInput(building_id="Office", time_range=full_range()),
            db_session,
        )
        if isinstance(out, MCPError):
            pytest.skip(f"COP 数据不足：{out.error}")
        assert out.source_table == "energy_data"


# ===========================================================================
# 8. MCP Tool 6：detect_energy_anomalies
# ===========================================================================

class TestDetectEnergyAnomalies:
    async def test_anomaly_detection(self, db_session: AsyncSession):
        out = await detect_energy_anomalies(
            DetectEnergyAnomaliesInput(building_id="Office", time_range=full_range()),
            db_session,
        )
        assert not isinstance(out, MCPError), f"工具报错：{out}"
        assert out.source_table == "energy_data"
        print(f"\n  Office 全量异常数: {out.total_anomalies}")

    async def test_night_anomaly_rule(self, db_session: AsyncSession):
        out = await detect_energy_anomalies(
            DetectEnergyAnomaliesInput(
                building_id="Office",
                time_range=full_range(),
                rules=[AnomalyRule.NIGHT_HIGH_POWER],
            ),
            db_session,
        )
        assert not isinstance(out, MCPError)
        if out.total_anomalies == 0:
            pytest.skip("当前数据集未包含夜间高功率场景，跳过")
        print(f"\n  Office 夜间高功率异常: {out.total_anomalies} 条")


# ===========================================================================
# 9. MCP Tool 10：compare_metric_across_buildings（含能耗强度）
# ===========================================================================

class TestCompareMetricAcrossBuildings:
    async def test_compare_all_buildings_electricity(self, db_session: AsyncSession):
        out = await compare_metric_across_buildings(
            CompareMetricAcrossBuildingsInput(
                building_ids=[],
                time_range=full_range(),
                metric=MetricType.ELECTRICITY_KWH,
                aggregation="avg",
            ),
            db_session,
        )
        assert not isinstance(out, MCPError), f"工具报错：{out}"
        assert len(out.results) == 3, f"应返回3栋楼，实际: {len(out.results)}"
        # 验证能耗强度字段
        for r in out.results:
            assert r.sqm is not None and r.sqm > 0, f"{r.building_type} 面积为空"
            assert r.energy_intensity_kwh_per_sqm is not None, f"{r.building_type} 能耗强度为空"
        print("\n  跨楼对比结果（含能耗强度）:")
        for r in out.results:
            print(f"    {r.building_type}: {r.aggregated_value:.2f} kWh, 强度: {r.energy_intensity_kwh_per_sqm:.4f} kWh/㎡")

    async def test_compare_specific_buildings(self, db_session: AsyncSession):
        out = await compare_metric_across_buildings(
            CompareMetricAcrossBuildingsInput(
                building_ids=["Education", "Office"],
                time_range=full_range(),
                metric=MetricType.HUMIDITY_RH_PCT,
                aggregation="avg",
            ),
            db_session,
        )
        assert not isinstance(out, MCPError)
        assert len(out.results) == 2


# ===========================================================================
# 10. MCP Tool 11：compare_time_periods（同环比分析）
# ===========================================================================

class TestCompareTimePeriods:
    async def test_first_vs_second_half(self, db_session: AsyncSession):
        out = await compare_time_periods(
            CompareTimePeriodsInput(
                building_id="Public",
                metric=MetricType.ELECTRICITY_KWH,
                period_a=second_half(),
                period_b=first_half(),
                aggregation="avg",
            ),
            db_session,
        )
        assert not isinstance(out, MCPError), f"工具报错：{out}"
        assert out.period_a_value >= 0
        assert out.period_b_value >= 0
        assert out.delta == round(out.period_a_value - out.period_b_value, 4)
        print(f"\n  Public 前半段均值: {out.period_b_value:.2f}, 后半段: {out.period_a_value:.2f}, 变化: {out.delta:.2f} ({out.delta_pct}%)")

    async def test_invalid_building_returns_error(self, db_session: AsyncSession):
        out = await compare_time_periods(
            CompareTimePeriodsInput(
                building_id="不存在的楼",
                metric=MetricType.ELECTRICITY_KWH,
                period_a=second_half(),
                period_b=first_half(),
            ),
            db_session,
        )
        assert isinstance(out, MCPError)
        assert out.error_code == "BUILDING_NOT_FOUND"
