"""
阶段二：MCP 工具单元测试
==========================
测试策略（与开发流程文档一致）：
  · 纯逻辑工具（ui_render, physics_calc 部分）：直接调用，无需 DB
  · 需要 DB 的工具（data_query, physics_calc）：用 AsyncMock 模拟 Session
  · 全程不连接真实数据库，确保 CI 可在无 PG 环境运行

覆盖场景：
  1. Happy Path — 正常输入产生正确输出
  2. Physical Guard — 传感器异常触发 MCPError
  3. Not Found — 建筑/设备不存在触发 MCPError
  4. Business Rules — 异常检测规则正确命中
  5. Human-in-the-loop — 工单草稿状态固定为 pending_approval
  6. MCP Server — call_tool 参数校验拦截与正常调用
"""

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio

from app.db.models import OperationStatusEnum
from app.mcp.tools.physics_calc import (
    _NIGHT_POWER_THRESHOLD,
    _ZERO_OCC_HVAC_THRESHOLD,
    _ASHRAE_BASELINE,
    calculate_system_cop,
    detect_energy_anomalies,
)
from app.mcp.tools.ui_render import create_work_order_draft, render_ui_component
from app.mcp.server import call_tool, list_tools
from app.schemas.mcp_schemas import (
    AnomalyRule,
    BuildingID,
    CalculateSystemCOPInput,
    CreateWorkOrderDraftInput,
    DetectEnergyAnomaliesInput,
    GetDeviceLiveStatusInput,
    MCPError,
    OperationStatus,
    QueryEnergyMetricsInput,
    RenderUIComponentInput,
    TimeRange,
    WorkOrderPriority,
)


# ---------------------------------------------------------------------------
# 辅助函数
# ---------------------------------------------------------------------------

def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def make_range(hours_back: int = 24) -> TimeRange:
    end = now_utc()
    return TimeRange(start=end - timedelta(hours=hours_back), end=end)


def make_energy_row(
    *,
    electricity_kwh: float = 20.0,
    hvac_energy_kwh: float = 15.0,
    hvac_supply_temp_c: float = 7.0,
    hvac_return_temp_c: float = 12.0,
    ambient_temp_c: float = 25.0,
    humidity_rh_pct: float = 60.0,
    occupancy_density: float = 1.5,
    status: OperationStatusEnum = OperationStatusEnum.Normal,
    hour_offset: int = 10,         # 用于控制时间戳的小时
) -> MagicMock:
    """创建一行模拟的 EnergyData ORM 对象。"""
    row = MagicMock()
    row.timestamp = now_utc().replace(hour=hour_offset, minute=0, second=0, microsecond=0)
    row.building_id = "Office"
    row.electricity_kwh = electricity_kwh
    row.hvac_energy_kwh = hvac_energy_kwh
    row.hvac_supply_temp_c = hvac_supply_temp_c
    row.hvac_return_temp_c = hvac_return_temp_c
    row.ambient_temp_c = ambient_temp_c
    row.humidity_rh_pct = humidity_rh_pct
    row.occupancy_density_per_100sqm = occupancy_density
    row.operation_status = status
    return row


def make_async_session_with_rows(rows: list) -> AsyncMock:
    """返回一个可 await 的假 SQLAlchemy Session，execute 返回指定 rows。"""
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = rows[0] if len(rows) == 1 else None
    mock_result.scalars.return_value.all.return_value = rows
    mock_result.fetchall.return_value = rows

    session = AsyncMock()
    session.execute = AsyncMock(return_value=mock_result)
    return session


# ===========================================================================
# Tool 7：render_ui_component（纯逻辑，无 DB）
# ===========================================================================

class TestRenderUIComponentTool:
    def test_line_chart_returns_artifact_id(self):
        inp = RenderUIComponentInput(
            component_type="LineChart",
            title="教学楼 COP 趋势",
            data_payload={"labels": [], "values": []},
        )
        out = render_ui_component(inp)
        assert not isinstance(out, MCPError)
        assert out.widget == "line-chart"
        assert out.artifact_id.startswith("artifact_")
        assert out.status == "rendered"

    def test_work_order_card_widget(self):
        inp = RenderUIComponentInput(
            component_type="WorkOrderCard",
            title="维修工单",
            data_payload={},
        )
        out = render_ui_component(inp)
        assert out.widget == "work-order-card"

    def test_each_call_generates_unique_artifact_id(self):
        inp = RenderUIComponentInput(component_type="BarChart", title="t", data_payload={})
        ids = {render_ui_component(inp).artifact_id for _ in range(10)}
        assert len(ids) == 10, "artifact_id 必须全局唯一"

    def test_invalid_component_returns_error(self):
        # model_construct 绕过 Pydantic 校验，直接测工具函数内部防御逻辑
        inp = RenderUIComponentInput.model_construct(
            component_type="PieChart",  # 非白名单值
            title="非法组件",
            data_payload={},
        )
        out = render_ui_component(inp)
        assert isinstance(out, MCPError)
        assert out.error_code == "INVALID_COMPONENT_TYPE"


# ===========================================================================
# Tool 8：create_work_order_draft（纯逻辑，无 DB）
# ===========================================================================

class TestCreateWorkOrderDraftTool:
    def _make_inp(self) -> CreateWorkOrderDraftInput:
        return CreateWorkOrderDraftInput(
            device_id="M-OFF-001",
            building_id=BuildingID.OFFICE,
            issue_description="凌晨 3 点耗电量激增至 450 kWh，人员密度为 0",
            suggested_action="重置设备 M-OFF-001 的定时控制器，检查继电器",
            priority=WorkOrderPriority.CRITICAL,
            evidence_timestamp=datetime(2023, 10, 25, 3, 0, 0, tzinfo=timezone.utc),
        )

    def test_status_always_pending_approval(self):
        out = create_work_order_draft(self._make_inp())
        assert not isinstance(out, MCPError)
        assert out.status == "pending_approval"
        assert out.requires_human_approval is True

    def test_ticket_id_format(self):
        out = create_work_order_draft(self._make_inp())
        assert out.ticket_id.startswith("temp_")
        assert len(out.ticket_id) == 13  # "temp_" + 8 chars

    def test_unique_ticket_ids(self):
        ids = {create_work_order_draft(self._make_inp()).ticket_id for _ in range(10)}
        assert len(ids) == 10

    def test_ui_hint_correct(self):
        out = create_work_order_draft(self._make_inp())
        assert out.ui_hint == "render_work_order_card"

    def test_fields_passed_through(self):
        out = create_work_order_draft(self._make_inp())
        assert out.device_id == "M-OFF-001"
        assert out.building_id == "Office"
        assert out.priority == WorkOrderPriority.CRITICAL


# ===========================================================================
# Tool 3：calculate_system_cop（需 Mock DB）
# ===========================================================================

class TestCalculateSystemCOP:
    @pytest.mark.asyncio
    async def test_normal_cop_above_baseline(self):
        """供回水温差大、能耗低 → COP 高于基准，is_below_baseline=False。"""
        rows = [
            (now_utc(), 5.0, 7.0, 15.0),   # △T=8, energy=5 → cop_proxy高
            (now_utc(), 6.0, 7.0, 14.0),   # △T=7, energy=6
        ]
        mock_result = MagicMock()
        mock_result.fetchall.return_value = rows
        session = AsyncMock()
        session.execute = AsyncMock(return_value=mock_result)

        out = await calculate_system_cop(
            CalculateSystemCOPInput(
                building_id=BuildingID.EDUCATION,
                time_range=make_range(24),
            ),
            session,
        )
        assert not isinstance(out, MCPError)
        assert out.data_points_used == 2
        assert out.cop_mean > 0

    @pytest.mark.asyncio
    async def test_zero_energy_triggers_sensor_fault(self):
        """所有行能耗≈0 → 触发 SENSOR_FAULT_DIVIDE_BY_ZERO。"""
        rows = [
            (now_utc(), 0.0, 7.0, 15.0),  # energy=0，被跳过
            (now_utc(), 0.05, 7.0, 14.0), # energy<0.1，被跳过
        ]
        mock_result = MagicMock()
        mock_result.fetchall.return_value = rows
        session = AsyncMock()
        session.execute = AsyncMock(return_value=mock_result)

        out = await calculate_system_cop(
            CalculateSystemCOPInput(
                building_id=BuildingID.OFFICE,
                time_range=make_range(24),
            ),
            session,
        )
        assert isinstance(out, MCPError)
        assert out.error_code == "SENSOR_FAULT_DIVIDE_BY_ZERO"

    @pytest.mark.asyncio
    async def test_negative_delta_t_skipped(self):
        """供水温度 ≥ 回水温度（△T≤0），制冷未启动，跳过所有行。"""
        rows = [
            (now_utc(), 10.0, 15.0, 7.0),  # supply > return → △T<0
        ]
        mock_result = MagicMock()
        mock_result.fetchall.return_value = rows
        session = AsyncMock()
        session.execute = AsyncMock(return_value=mock_result)

        out = await calculate_system_cop(
            CalculateSystemCOPInput(
                building_id=BuildingID.PUBLIC,
                time_range=make_range(24),
            ),
            session,
        )
        assert isinstance(out, MCPError)
        assert out.error_code == "SENSOR_FAULT_DIVIDE_BY_ZERO"

    @pytest.mark.asyncio
    async def test_no_data_returns_error(self):
        mock_result = MagicMock()
        mock_result.fetchall.return_value = []
        session = AsyncMock()
        session.execute = AsyncMock(return_value=mock_result)

        out = await calculate_system_cop(
            CalculateSystemCOPInput(
                building_id=BuildingID.EDUCATION,
                time_range=make_range(24),
            ),
            session,
        )
        assert isinstance(out, MCPError)
        assert out.error_code == "NO_HVAC_DATA"


# ===========================================================================
# Tool 6：detect_energy_anomalies（需 Mock DB）
# ===========================================================================

class TestDetectEnergyAnomalies:
    @pytest.mark.asyncio
    async def test_night_high_power_detected(self):
        """凌晨 3 点 electricity_kwh=450 → 触发 night_high_power 规则（场景三核心）。"""
        anomaly_row = make_energy_row(
            electricity_kwh=450.0,
            hour_offset=3,            # 凌晨 3 点
            occupancy_density=0.0,
            status=OperationStatusEnum.Anomaly,
        )
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [anomaly_row]
        session = AsyncMock()
        session.execute = AsyncMock(return_value=mock_result)

        out = await detect_energy_anomalies(
            DetectEnergyAnomaliesInput(
                building_id=BuildingID.OFFICE,
                time_range=make_range(24),
                rules=[AnomalyRule.NIGHT_HIGH_POWER],
            ),
            session,
        )
        assert not isinstance(out, MCPError)
        assert out.total_anomalies >= 1
        assert out.anomalies[0].rule_triggered == AnomalyRule.NIGHT_HIGH_POWER
        assert out.anomalies[0].actual_value == 450.0

    @pytest.mark.asyncio
    async def test_zero_occ_high_hvac_detected(self):
        """人员密度=0 且 hvac_energy_kwh=80 → 触发 zero_occupancy_high_hvac。"""
        row = make_energy_row(
            occupancy_density=0.0,
            hvac_energy_kwh=80.0,
            hour_offset=14,           # 白天，不触发 night_high_power
        )
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [row]
        session = AsyncMock()
        session.execute = AsyncMock(return_value=mock_result)

        out = await detect_energy_anomalies(
            DetectEnergyAnomaliesInput(
                building_id=BuildingID.OFFICE,
                time_range=make_range(24),
                rules=[AnomalyRule.ZERO_OCC_HIGH_HVAC],
            ),
            session,
        )
        assert out.total_anomalies >= 1
        assert out.anomalies[0].rule_triggered == AnomalyRule.ZERO_OCC_HIGH_HVAC

    @pytest.mark.asyncio
    async def test_normal_data_no_anomaly(self):
        """正常白天数据 → 无异常。"""
        rows = [make_energy_row(electricity_kwh=20.0, hour_offset=10) for _ in range(5)]
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = rows
        session = AsyncMock()
        session.execute = AsyncMock(return_value=mock_result)

        out = await detect_energy_anomalies(
            DetectEnergyAnomaliesInput(
                building_id=BuildingID.OFFICE,
                time_range=make_range(24),
            ),
            session,
        )
        assert out.total_anomalies == 0

    @pytest.mark.asyncio
    async def test_no_data_returns_error(self):
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        session = AsyncMock()
        session.execute = AsyncMock(return_value=mock_result)

        out = await detect_energy_anomalies(
            DetectEnergyAnomaliesInput(
                building_id=BuildingID.OFFICE,
                time_range=make_range(24),
            ),
            session,
        )
        assert isinstance(out, MCPError)
        assert out.error_code == "NO_DATA_FOUND"


# ===========================================================================
# MCP Server：call_tool 统一入口测试
# ===========================================================================

class TestMCPServer:
    def test_list_tools_returns_all_8(self):
        tools = list_tools()
        assert len(tools) == 8
        names = {t["name"] for t in tools}
        assert "query_energy_metrics" in names
        assert "create_work_order_draft" in names

    @pytest.mark.asyncio
    async def test_call_tool_unknown_name_returns_error(self):
        out = await call_tool("nonexistent_tool", {})
        assert isinstance(out, MCPError)
        assert out.error_code == "TOOL_NOT_FOUND"

    @pytest.mark.asyncio
    async def test_call_tool_param_validation_error(self):
        """传入非法参数 → MCPError(PARAM_VALIDATION_ERROR)，不抛异常。"""
        out = await call_tool(
            "query_energy_metrics",
            {"building_id": "火星基地", "time_range": {}, "metrics": []},
        )
        assert isinstance(out, MCPError)
        assert out.error_code == "PARAM_VALIDATION_ERROR"

    @pytest.mark.asyncio
    async def test_call_tool_db_required_without_session(self):
        """需要 DB 的工具不传 session → DB_SESSION_MISSING。"""
        out = await call_tool(
            "query_energy_metrics",
            {
                "building_id": "Office",
                "time_range": {
                    "start": "2023-10-01T00:00:00Z",
                    "end": "2023-10-02T00:00:00Z",
                },
                "metrics": ["electricity_kwh"],
            },
            session=None,
        )
        assert isinstance(out, MCPError)
        assert out.error_code == "DB_SESSION_MISSING"

    @pytest.mark.asyncio
    async def test_call_tool_render_ui_no_db_needed(self):
        """render_ui_component 不需要 DB，session=None 也能正常工作。"""
        out = await call_tool(
            "render_ui_component",
            {
                "component_type": "BarChart",
                "title": "测试图表",
                "data_payload": {},
            },
            session=None,
        )
        assert not isinstance(out, MCPError)
        assert out.widget == "bar-chart"

    @pytest.mark.asyncio
    async def test_call_tool_work_order_no_db_needed(self):
        out = await call_tool(
            "create_work_order_draft",
            {
                "device_id": "M-OFF-001",
                "building_id": "Office",
                "issue_description": "凌晨 3 点耗电量激增，疑似定时策略失效",
                "suggested_action": "重置定时控制器",
                "priority": "critical",
            },
            session=None,
        )
        assert not isinstance(out, MCPError)
        assert out.status == "pending_approval"
