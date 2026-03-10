"""
测试：Generative UI SSE 渲染协议
============================================================
覆盖场景：
  1. 正确数据能通过校验（Happy Path）
  2. 错误数据被拦截并返回清晰错误（Validation Guard）
  3. 各事件类型可序列化为 JSON（前端可直接推送）
  4. ArtifactEvent 三种 Payload 均可正确构建
  5. ThinkingEvent hop_count 上限（熔断边界）
"""

import json
import pytest
from datetime import datetime, timezone

from app.schemas.genui_protocol import (
    AgentName,
    ArtifactEvent,
    ChartPayload,
    ChartSeries,
    DataSourcePayload,
    DoneEvent,
    ErrorEvent,
    SSEEventType,
    TextEvent,
    ThinkingEvent,
    WidgetType,
    WorkOrderPayload,
)


# ---------------------------------------------------------------------------
# 辅助函数
# ---------------------------------------------------------------------------

def assert_json_serializable(model) -> dict:
    """验证 Pydantic 模型可序列化为合法 JSON，返回 dict 供进一步断言。"""
    raw = model.model_dump_json()
    data = json.loads(raw)
    assert isinstance(data, dict)
    return data


# ===========================================================================
# ThinkingEvent 测试
# ===========================================================================

class TestThinkingEvent:
    def test_happy_path(self):
        event = ThinkingEvent(
            agent=AgentName.DATA,
            message="正在查询 energy_data 按天聚合数据…",
            hop_count=1,
        )
        assert event.type == SSEEventType.THINKING
        assert event.agent == AgentName.DATA
        data = assert_json_serializable(event)
        assert data["type"] == "thinking"
        assert data["hop_count"] == 1

    def test_hop_count_zero_allowed(self):
        event = ThinkingEvent(agent=AgentName.ROUTER, message="开始路由…", hop_count=0)
        assert event.hop_count == 0

    def test_hop_count_max_allowed(self):
        """hop_count=5 是熔断临界值，应允许通过。"""
        event = ThinkingEvent(agent=AgentName.ROUTER, message="即将熔断…", hop_count=5)
        assert event.hop_count == 5

    def test_hop_count_exceeds_max_rejected(self):
        """hop_count > 5 违反熔断上限，必须被拦截。"""
        with pytest.raises(Exception):
            ThinkingEvent(agent=AgentName.ROUTER, message="超限", hop_count=6)

    def test_invalid_agent_name_rejected(self):
        """非法 Agent 名称必须被枚举校验拦截。"""
        with pytest.raises(Exception):
            ThinkingEvent(agent="ghost_agent", message="幻觉 Agent", hop_count=0)  # type: ignore


# ===========================================================================
# TextEvent 测试
# ===========================================================================

class TestTextEvent:
    def test_streaming_text(self):
        event = TextEvent(content="办公楼昨晚凌晨 3 点用电量为 ", is_final=False)
        assert event.type == SSEEventType.TEXT
        assert event.is_final is False

    def test_final_text(self):
        event = TextEvent(content="450 kWh，已标记为 Anomaly。[1]", is_final=True)
        assert event.is_final is True

    def test_json_serializable(self):
        event = TextEvent(content="测试文本")
        data = assert_json_serializable(event)
        assert data["type"] == "text"
        assert data["is_final"] is False


# ===========================================================================
# ArtifactEvent 测试 — ChartPayload
# ===========================================================================

class TestArtifactChartEvent:
    def _make_chart_payload(self) -> ChartPayload:
        return ChartPayload(
            title="教学楼 vs 办公楼 近7日每日总电耗",
            x_label="日期",
            y_label="电耗",
            unit="kWh",
            series=[
                ChartSeries(
                    name="Education（教学楼）",
                    data=[1200.5, 1350.0, 980.3, 1100.0, 1420.0, 1300.5, 1250.0],
                    timestamps=[
                        "2023-10-19", "2023-10-20", "2023-10-21", "2023-10-22",
                        "2023-10-23", "2023-10-24", "2023-10-25",
                    ],
                ),
                ChartSeries(
                    name="Office（办公楼）",
                    data=[800.0, 820.5, 750.0, 900.0, 880.0, 860.0, 450.0],
                    timestamps=[
                        "2023-10-19", "2023-10-20", "2023-10-21", "2023-10-22",
                        "2023-10-23", "2023-10-24", "2023-10-25",
                    ],
                ),
            ],
            source_table="energy_data",
            meter_ids=["M-EDU-001", "M-OFF-001"],
            query_ms=12,
        )

    def test_bar_chart_artifact(self):
        event = ArtifactEvent(
            artifact_id="artifact_001",
            widget=WidgetType.BAR_CHART,
            payload=self._make_chart_payload(),
        )
        assert event.type == SSEEventType.ARTIFACT
        assert event.widget == WidgetType.BAR_CHART
        data = assert_json_serializable(event)
        assert data["type"] == "artifact"
        assert data["payload"]["query_ms"] == 12
        assert "M-EDU-001" in data["payload"]["meter_ids"]

    def test_chart_series_must_have_at_least_one(self):
        """series 为空时必须拒绝。"""
        with pytest.raises(Exception):
            ChartPayload(
                title="空图", x_label="x", y_label="y", unit="kWh",
                series=[],  # 违反 min_length=1
                source_table="energy_data",
                meter_ids=[],
            )


# ===========================================================================
# ArtifactEvent 测试 — WorkOrderPayload
# ===========================================================================

class TestArtifactWorkOrderEvent:
    def test_work_order_pending_approval(self):
        now = datetime.now(timezone.utc).isoformat()
        payload = WorkOrderPayload(
            ticket_id="temp_abc123",
            device_id="M-OFF-001",
            building_id="Office",
            priority="critical",
            issue_description="凌晨 3 点耗电量激增至 450 kWh，疑似定时策略失效",
            suggested_action="重置设备 M-OFF-001 的定时控制器",
            status="pending_approval",
            created_at=now,
        )
        event = ArtifactEvent(
            artifact_id="wo_001",
            widget=WidgetType.WORK_ORDER_CARD,
            payload=payload,
        )
        data = assert_json_serializable(event)
        assert data["payload"]["status"] == "pending_approval"
        assert data["payload"]["priority"] == "critical"

    def test_invalid_priority_rejected(self):
        """非法优先级必须被拦截。"""
        with pytest.raises(Exception):
            WorkOrderPayload(
                ticket_id="t1", device_id="M-OFF-001", building_id="Office",
                priority="urgent",  # 非白名单值
                issue_description="test", suggested_action="fix it",
                status="pending_approval", created_at="2023-10-25T03:00:00Z",
            )


# ===========================================================================
# ArtifactEvent 测试 — DataSourcePayload
# ===========================================================================

class TestArtifactDataSourceEvent:
    def test_data_source_panel(self):
        payload = DataSourcePayload(
            source_table="energy_data",
            meter_ids=["M-EDU-001"],
            query_ms=12,
            lineage=["原始传感器CSV → energy_data 表 → GROUP BY 聚合 → AI分析结论"],
        )
        event = ArtifactEvent(
            artifact_id="audit_001",
            widget=WidgetType.DATA_SOURCE_PANEL,
            payload=payload,
        )
        data = assert_json_serializable(event)
        assert data["payload"]["source_table"] == "energy_data"
        assert len(data["payload"]["lineage"]) == 1


# ===========================================================================
# ErrorEvent 测试
# ===========================================================================

class TestErrorEvent:
    def test_tool_error_human_readable(self):
        event = ErrorEvent(
            code="PARAM_VALIDATION_ERROR",
            message="time_range.end 必须晚于 time_range.start，请检查后重试",
            tool_name="query_energy_metrics",
        )
        assert event.type == SSEEventType.ERROR
        data = assert_json_serializable(event)
        assert data["type"] == "error"
        assert "time_range" in data["message"]

    def test_error_without_tool_name(self):
        """tool_name 可选，不传时应返回 None。"""
        event = ErrorEvent(code="UNKNOWN", message="未知错误")
        assert event.tool_name is None


# ===========================================================================
# DoneEvent 测试
# ===========================================================================

class TestDoneEvent:
    def test_done_event_full(self):
        event = DoneEvent(
            total_hops=3,
            agents_involved=[AgentName.ROUTER, AgentName.DATA, AgentName.DIAGNOSE],
        )
        assert event.type == SSEEventType.DONE
        data = assert_json_serializable(event)
        assert data["total_hops"] == 3
        assert "data" in data["agents_involved"]
        assert "diagnose" in data["agents_involved"]

    def test_done_hop_exceeds_limit_rejected(self):
        with pytest.raises(Exception):
            DoneEvent(total_hops=6, agents_involved=[AgentName.ROUTER])
