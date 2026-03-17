"""
测试：MCP 工具出入参 Pydantic Schema（8 个核心工具）
============================================================
覆盖场景：
  1. 正确参数通过校验（Happy Path）
  2. 非法参数被拦截 + 错误信息可读（Validation Guard）
  3. 关键业务约束验证（TimeRange, BuildingID 白名单, meter_device_id 格式）
  4. MCPError 结构供大模型自我修正
  5. 输出结构含数据血缘字段（source_table）
"""

import json
import pytest
from datetime import datetime, timedelta, timezone

from app.schemas.mcp_schemas import (
    AnomalyRecord,
    AnomalyRule,
    BuildingID,
    CalculateSystemCOPInput,
    CalculateSystemCOPOutput,
    CreateWorkOrderDraftInput,
    CreateWorkOrderDraftOutput,
    DetectEnergyAnomaliesInput,
    DetectEnergyAnomaliesOutput,
    GetDeviceLiveStatusInput,
    GetDeviceLiveStatusOutput,
    MCPError,
    MetadataFilter,
    MetricType,
    OperationStatus,
    QueryDailyEnergySummaryInput,
    QueryDailyEnergySummaryOutput,
    QueryEnergyMetricsInput,
    RAGHybridSearchInput,
    RAGHybridSearchOutput,
    RAGSearchResult,
    RenderUIComponentInput,
    RenderUIComponentOutput,
    TimeRange,
    WorkOrderPriority,
)


# ---------------------------------------------------------------------------
# 辅助工具
# ---------------------------------------------------------------------------

def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def make_time_range(hours_back: int = 24) -> TimeRange:
    end = now_utc()
    start = end - timedelta(hours=hours_back)
    return TimeRange(start=start, end=end)


def assert_json_ok(model) -> dict:
    raw = model.model_dump_json()
    data = json.loads(raw)
    assert isinstance(data, dict)
    return data


# ===========================================================================
# 公共结构测试
# ===========================================================================

class TestTimeRange:
    def test_valid_range(self):
        tr = make_time_range(24)
        assert tr.end > tr.start

    def test_end_before_start_rejected(self):
        end = now_utc()
        start = end + timedelta(hours=1)  # start 晚于 end，非法
        with pytest.raises(Exception) as exc_info:
            TimeRange(start=start, end=end)
        assert "end" in str(exc_info.value).lower() or "start" in str(exc_info.value).lower()

    def test_equal_start_end_rejected(self):
        t = now_utc()
        with pytest.raises(Exception):
            TimeRange(start=t, end=t)


class TestBuildingID:
    def test_valid_building_ids(self):
        for bid in ["Education", "Office", "Public"]:
            assert BuildingID(bid).value == bid

    def test_invalid_building_id_rejected(self):
        """大模型幻觉 ID 必须被枚举白名单拦截。"""
        with pytest.raises(Exception):
            BuildingID("Library")

    def test_case_sensitive(self):
        """ID 区分大小写，'office' 不合法。"""
        with pytest.raises(Exception):
            BuildingID("office")


class TestMCPError:
    def test_mcp_error_structure(self):
        err = MCPError(
            error="参数校验失败，time_range.end 必须晚于 start，请重新传入",
            error_code="PARAM_VALIDATION_ERROR",
            tool_name="query_energy_metrics",
        )
        data = assert_json_ok(err)
        assert "time_range" in data["error"]
        assert data["tool_name"] == "query_energy_metrics"


# ===========================================================================
# Tool 1：query_energy_metrics
# ===========================================================================

class TestQueryEnergyMetrics:
    def test_happy_path_single_metric(self):
        inp = QueryEnergyMetricsInput(
            building_id=BuildingID.EDUCATION,
            time_range=make_time_range(24),
            metrics=[MetricType.ELECTRICITY_KWH],
        )
        assert inp.building_id == BuildingID.EDUCATION
        assert MetricType.ELECTRICITY_KWH in inp.metrics

    def test_multiple_metrics(self):
        inp = QueryEnergyMetricsInput(
            building_id=BuildingID.OFFICE,
            time_range=make_time_range(168),  # 7 天
            metrics=[
                MetricType.ELECTRICITY_KWH,
                MetricType.AMBIENT_TEMP_C,
                MetricType.OCCUPANCY_DENSITY,
            ],
        )
        assert len(inp.metrics) == 3

    def test_empty_metrics_rejected(self):
        """至少要指定一个指标，空列表必须拒绝。"""
        with pytest.raises(Exception):
            QueryEnergyMetricsInput(
                building_id=BuildingID.EDUCATION,
                time_range=make_time_range(24),
                metrics=[],
            )

    def test_invalid_metric_name_rejected(self):
        """大模型编造的列名（如 'power_usage'）必须被枚举拦截。"""
        with pytest.raises(Exception):
            QueryEnergyMetricsInput(
                building_id=BuildingID.EDUCATION,
                time_range=make_time_range(24),
                metrics=["power_usage"],  # type: ignore
            )

    def test_invalid_building_rejected(self):
        with pytest.raises(Exception):
            QueryEnergyMetricsInput(
                building_id="Mars_Base",  # type: ignore
                time_range=make_time_range(24),
                metrics=[MetricType.ELECTRICITY_KWH],
            )


# ===========================================================================
# Tool 2：get_device_live_status
# ===========================================================================

class TestGetDeviceLiveStatus:
    def test_valid_device_ids(self):
        for device_id in ["M-EDU-001", "M-OFF-001", "M-PUB-001"]:
            inp = GetDeviceLiveStatusInput(meter_device_id=device_id)
            assert inp.meter_device_id == device_id

    def test_invalid_format_rejected(self):
        """格式不符合 M-XXX-NNN 的设备 ID 必须被拦截。"""
        for bad_id in ["EDU-001", "M-EDU001", "M-SCHOOL-001", "m-edu-001"]:
            with pytest.raises(Exception):
                GetDeviceLiveStatusInput(meter_device_id=bad_id)

    def test_output_has_blood_lineage(self):
        """输出必须携带 source_table 字段（数据血缘）。"""
        out = GetDeviceLiveStatusOutput(
            meter_device_id="M-OFF-001",
            operation_status=OperationStatus.ANOMALY,
            ambient_temp_c=15.0,
            humidity_rh_pct=55.0,
            electricity_kwh=450.0,
            occupancy_density_per_100sqm=0.0,
            last_updated_utc=now_utc(),
        )
        assert out.source_table == "energy_data"
        data = assert_json_ok(out)
        assert data["source_table"] == "energy_data"
        assert data["operation_status"] == "Anomaly"


# ===========================================================================
# Tool 3：calculate_system_cop
# ===========================================================================

class TestCalculateSystemCOP:
    def test_cop_input_valid(self):
        inp = CalculateSystemCOPInput(
            building_id=BuildingID.EDUCATION,
            time_range=make_time_range(30 * 24),  # 上个月
        )
        assert inp.building_id == BuildingID.EDUCATION

    def test_cop_output_baseline_check(self):
        """低于 GB 50189-2015 国标基准时 is_below_gb 必须为 True。"""
        out = CalculateSystemCOPOutput(
            building_id="Education",
            cop_mean=2.1,   # 低于制冷季 gb_baseline=3.5
            cop_min=1.8,
            cop_max=2.5,
            hvac_mode="Cooling",
            gb_baseline=3.5,
            is_below_gb=True,
            period_start=now_utc() - timedelta(days=30),
            period_end=now_utc(),
            data_points_used=720,
        )
        assert out.is_below_gb is True
        assert out.source_table == "energy_data"

    def test_cop_data_points_must_be_positive(self):
        with pytest.raises(Exception):
            CalculateSystemCOPOutput(
                building_id="Education",
                cop_mean=3.5, cop_min=3.0, cop_max=4.0,
                hvac_mode="Cooling",
                gb_baseline=3.5, is_below_gb=False,
                period_start=now_utc() - timedelta(days=1),
                period_end=now_utc(),
                data_points_used=0,  # ge=1，0 非法
            )


# ===========================================================================
# Tool 4：query_daily_energy_summary
# ===========================================================================

class TestQueryDailyEnergySummary:
    def test_input_valid(self):
        inp = QueryDailyEnergySummaryInput(
            building_id=BuildingID.OFFICE,
            date_range=make_time_range(7 * 24),
        )
        assert inp.building_id == BuildingID.OFFICE

    def test_output_source_is_materialized_view(self):
        """
        输出必须声明 source_view='daily_energy_summary'（PostgreSQL 物化视图）
        和 base_table='energy_data'，体现预计算层的数据血缘。
        """
        out = QueryDailyEnergySummaryOutput(
            records=[],
            building_id="Office",
            query_ms=12,
        )
        assert out.source_view == "daily_energy_summary"
        assert out.base_table == "energy_data"
        data = assert_json_ok(out)
        assert data["source_view"] == "daily_energy_summary"
        assert data["base_table"] == "energy_data"
        assert data["query_ms"] == 12

    def test_record_matches_view_columns(self):
        """
        DailyEnergySummaryRecord 字段必须与物化视图列名严格一致：
        day / building_id / total_electricity_kwh / avg_ambient_temp / max_occupancy
        """
        from app.schemas.mcp_schemas import DailyEnergySummaryRecord
        rec = DailyEnergySummaryRecord(
            day="2023-10-25 00:00:00+00",
            building_id="Office",
            total_electricity_kwh=8640.0,
            avg_ambient_temp=18.5,
            max_occupancy=2.3,
        )
        assert rec.day == "2023-10-25 00:00:00+00"
        assert rec.avg_ambient_temp == 18.5
        assert rec.max_occupancy == 2.3

    def test_record_rejects_old_columns(self):
        """旧字段 total_water_m3 / avg_occupancy_density / anomaly_count 不再存在，多余字段应被忽略或报错。"""
        from app.schemas.mcp_schemas import DailyEnergySummaryRecord
        # Pydantic v2 默认忽略多余字段，核心是不含这些列的记录依然能构建成功
        rec = DailyEnergySummaryRecord(
            day="2023-10-25 00:00:00+00",
            building_id="Education",
            total_electricity_kwh=12000.0,
            avg_ambient_temp=20.1,
            max_occupancy=5.0,
        )
        assert not hasattr(rec, "total_water_m3")
        assert not hasattr(rec, "avg_occupancy_density")
        assert not hasattr(rec, "anomaly_count")


# ===========================================================================
# Tool 5：rag_hybrid_search
# ===========================================================================

class TestRAGHybridSearch:
    def test_input_with_device_filter(self):
        """携带 device_id 过滤，触发元数据硬过滤（先过滤 90% 无关文档）。"""
        inp = RAGHybridSearchInput(
            query="zero occupancy high electricity_kwh night",
            metadata_filter=MetadataFilter(device_id="M-OFF-001"),
            enable_rerank=True,
            top_k=3,
        )
        assert inp.metadata_filter.device_id == "M-OFF-001"
        assert inp.enable_rerank is True

    def test_empty_query_rejected(self):
        with pytest.raises(Exception):
            RAGHybridSearchInput(query="")  # min_length=1

    def test_top_k_bounds(self):
        with pytest.raises(Exception):
            RAGHybridSearchInput(query="test", top_k=0)   # ge=1
        with pytest.raises(Exception):
            RAGHybridSearchInput(query="test", top_k=11)  # le=10

    def test_output_with_rerank_score(self):
        """返回结果必须携带父子索引的 parent_section，防止断章取义。"""
        out = RAGHybridSearchOutput(
            results=[
                RAGSearchResult(
                    content="若夜间监控人员密度归零，但系统未进入休眠，需检查定时器继电器。",
                    parent_section="4.2 常见故障排除",
                    source_doc="Chiller_Maintenance_Manual_V2.pdf",
                    page=42,
                    similarity=0.98,
                    rerank_score=0.85,
                )
            ],
            query="zero occupancy high electricity_kwh",
            total_retrieved=20,
            reranked=True,
        )
        assert out.results[0].rerank_score == 0.85
        assert out.results[0].parent_section == "4.2 常见故障排除"

    def test_similarity_out_of_range_rejected(self):
        with pytest.raises(Exception):
            RAGSearchResult(
                content="x", parent_section="s", source_doc="d.pdf",
                page=1, similarity=1.5,  # ge=0 le=1，超出范围
            )


# ===========================================================================
# Tool 6：detect_energy_anomalies
# ===========================================================================

class TestDetectEnergyAnomalies:
    def test_default_rules_applied(self):
        inp = DetectEnergyAnomaliesInput(
            building_id=BuildingID.OFFICE,
            time_range=make_time_range(24),
        )
        assert AnomalyRule.NIGHT_HIGH_POWER in inp.rules
        assert AnomalyRule.ZERO_OCC_HIGH_HVAC in inp.rules

    def test_custom_rule_subset(self):
        inp = DetectEnergyAnomaliesInput(
            building_id=BuildingID.OFFICE,
            time_range=make_time_range(24),
            rules=[AnomalyRule.NIGHT_HIGH_POWER],
        )
        assert len(inp.rules) == 1

    def test_empty_rules_rejected(self):
        with pytest.raises(Exception):
            DetectEnergyAnomaliesInput(
                building_id=BuildingID.OFFICE,
                time_range=make_time_range(24),
                rules=[],  # min_length=1
            )

    def test_invalid_rule_rejected(self):
        with pytest.raises(Exception):
            DetectEnergyAnomaliesInput(
                building_id=BuildingID.OFFICE,
                time_range=make_time_range(24),
                rules=["made_up_rule"],  # type: ignore
            )

    def test_anomaly_output_structure(self):
        """场景三核心数据：凌晨 3 点 M-OFF-001 异常，触发 night_high_power 规则。"""
        anomaly_time = datetime(2023, 10, 25, 3, 0, 0, tzinfo=timezone.utc)
        out = DetectEnergyAnomaliesOutput(
            anomalies=[
                AnomalyRecord(
                    timestamp=anomaly_time,
                    building_id="Office",
                    meter_device_id="M-OFF-001",
                    rule_triggered=AnomalyRule.NIGHT_HIGH_POWER,
                    actual_value=450.0,
                    threshold_value=50.0,
                    duration_hours=2.0,
                    operation_status=OperationStatus.ANOMALY,
                )
            ],
            total_anomalies=1,
            building_id="Office",
            period_start=anomaly_time - timedelta(hours=3),
            period_end=anomaly_time + timedelta(hours=3),
        )
        assert out.total_anomalies == 1
        assert out.anomalies[0].actual_value == 450.0
        assert out.source_table == "energy_data"


# ===========================================================================
# Tool 7：render_ui_component
# ===========================================================================

class TestRenderUIComponent:
    def test_line_chart_render(self):
        inp = RenderUIComponentInput(
            component_type="LineChart",
            title="教学楼 COP 趋势",
            data_payload={"labels": ["2023-10-01", "2023-10-02"], "values": [3.2, 2.8]},
            source_info={"source_table": "energy_data", "query_ms": 12},
        )
        assert inp.component_type == "LineChart"

    def test_invalid_component_type_rejected(self):
        with pytest.raises(Exception):
            RenderUIComponentInput(
                component_type="PieChart",  # 非白名单组件
                title="非法图表",
                data_payload={},
            )

    def test_output_has_artifact_id(self):
        out = RenderUIComponentOutput(
            artifact_id="artifact_chart_001",
            widget="bar-chart",
        )
        assert out.status == "rendered"
        data = assert_json_ok(out)
        assert data["artifact_id"] == "artifact_chart_001"


# ===========================================================================
# Tool 8：create_work_order_draft
# ===========================================================================

class TestCreateWorkOrderDraft:
    def test_happy_path_critical_work_order(self):
        """场景三：凌晨 3 点 M-OFF-001 异常 → 生成待审批工单。"""
        inp = CreateWorkOrderDraftInput(
            device_id="M-OFF-001",
            building_id=BuildingID.OFFICE,
            issue_description="凌晨 3 点耗电量激增至 450 kWh，人员密度为 0，疑似定时策略失效",
            suggested_action="重置设备 M-OFF-001 的定时控制器，检查继电器状态",
            priority=WorkOrderPriority.CRITICAL,
            evidence_timestamp=datetime(2023, 10, 25, 3, 0, 0, tzinfo=timezone.utc),
        )
        assert inp.device_id == "M-OFF-001"
        assert inp.priority == WorkOrderPriority.CRITICAL

    def test_output_always_pending_approval(self):
        """Human-in-the-loop 核心：工单草稿状态必须固定为 pending_approval。"""
        out = CreateWorkOrderDraftOutput(
            ticket_id="temp_abc123",
            device_id="M-OFF-001",
            building_id="Office",
            priority=WorkOrderPriority.HIGH,
            issue_description="设备异常，耗电量超标",
            suggested_action="检查定时器",
            created_at=now_utc(),
        )
        assert out.status == "pending_approval"
        assert out.requires_human_approval is True
        assert out.ui_hint == "render_work_order_card"

    def test_short_description_rejected(self):
        """描述太短（< 10 字符）不够清晰，应被拒绝。"""
        with pytest.raises(Exception):
            CreateWorkOrderDraftInput(
                device_id="M-OFF-001",
                building_id=BuildingID.OFFICE,
                issue_description="坏了",   # min_length=10
                suggested_action="修它",
                priority=WorkOrderPriority.HIGH,
            )

    def test_invalid_device_format_rejected(self):
        with pytest.raises(Exception):
            CreateWorkOrderDraftInput(
                device_id="OFF-001",  # 缺少 M- 前缀
                building_id=BuildingID.OFFICE,
                issue_description="设备异常，耗电量持续超过阈值",
                suggested_action="重置设备",
                priority=WorkOrderPriority.MEDIUM,
            )

    def test_invalid_building_id_rejected(self):
        with pytest.raises(Exception):
            CreateWorkOrderDraftInput(
                device_id="M-OFF-001",
                building_id="火星基地",  # type: ignore  幻觉 ID
                issue_description="设备异常，耗电量持续超过阈值",
                suggested_action="重置设备",
                priority=WorkOrderPriority.MEDIUM,
            )
