"""
API 接口单元测试 — Phase 4。

策略：
- 使用 httpx.AsyncClient + ASGITransport 直接测试 FastAPI 应用
- mock 数据库依赖（get_db_session）和 LangGraph 图
- 不发真实 LLM/DB 请求
"""
from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from main import app


# ===========================================================================
# 测试客户端 fixture
# ===========================================================================
@pytest.fixture
async def client():
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        yield ac


# ===========================================================================
# 1. 健康检查
# ===========================================================================
class TestHealthCheck:
    @pytest.mark.asyncio
    async def test_health_returns_ok(self, client):
        resp = await client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert "env" in data

    @pytest.mark.asyncio
    async def test_health_db_returns_status(self, client):
        """DB 健康检查：mock 数据库，验证端点可调用。"""
        mock_result = MagicMock()
        mock_result.fetchone.return_value = (1,)

        mock_session = AsyncMock()
        mock_session.execute = AsyncMock(return_value=mock_result)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=None)

        with patch("app.db.session.AsyncSessionLocal", return_value=mock_session):
            resp = await client.get("/health/db")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"


# ===========================================================================
# 2. 工具列表
# ===========================================================================
class TestToolsEndpoint:
    @pytest.mark.asyncio
    async def test_tools_returns_8_tools(self, client):
        resp = await client.get("/api/tools")
        assert resp.status_code == 200
        data = resp.json()
        assert "tools" in data
        assert len(data["tools"]) == 8

    @pytest.mark.asyncio
    async def test_tools_contain_expected_names(self, client):
        resp = await client.get("/api/tools")
        tool_names = [t["name"] for t in resp.json()["tools"]]
        for expected in [
            "query_energy_metrics",
            "calculate_system_cop",
            "rag_hybrid_search",
            "render_ui_component",
            "create_work_order_draft",
        ]:
            assert expected in tool_names


# ===========================================================================
# 3. 建筑数据接口（mock DB）
# ===========================================================================
def _mock_building(building_id: str = "Office"):
    b = MagicMock()
    b.building_id = building_id
    b.name = f"{building_id} Building"
    b.area_sqm = 5000.0
    b.meter_device_id = f"M-{building_id[:3].upper()}-001"
    b.location = "Campus A"
    return b


def _mock_energy_row():
    row = MagicMock()
    row.timestamp = MagicMock()
    row.timestamp.isoformat.return_value = "2024-01-25T03:00:00+00:00"
    row.operation_status = "Anomaly"
    row.electricity_kwh = 450.0
    row.water_m3 = 2.5
    row.hvac_energy_kwh = 85.0
    row.hvac_supply_temp_c = 8.0
    row.hvac_return_temp_c = 14.0
    row.ambient_temp_c = 15.0
    row.humidity_rh_pct = 55.0
    row.occupancy_density_per_100sqm = 0.0
    return row


def _make_db_mock(scalar_result=None, scalars_all=None):
    """构造一个 mock AsyncSession。"""
    mock_scalar_result = MagicMock()
    mock_scalar_result.scalar_one_or_none.return_value = scalar_result
    mock_scalar_result.scalars.return_value.all.return_value = scalars_all or []

    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(return_value=mock_scalar_result)
    return mock_session


class TestBuildingsEndpoint:
    @pytest.mark.asyncio
    async def test_get_buildings_list(self, client):
        """GET /api/buildings 返回建筑列表。"""
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [
            _mock_building("Education"),
            _mock_building("Office"),
            _mock_building("Public"),
        ]
        mock_session = AsyncMock()
        mock_session.execute = AsyncMock(return_value=mock_result)

        async def _override():
            yield mock_session

        app.dependency_overrides[__import__("app.db.session", fromlist=["get_db_session"]).get_db_session] = _override

        try:
            resp = await client.get("/api/buildings")
            assert resp.status_code == 200
            data = resp.json()
            assert len(data) == 3
            ids = [b["building_id"] for b in data]
            assert "Education" in ids
        finally:
            app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_building_status_not_found(self, client):
        """查询不存在的建筑返回 404。"""
        from app.db.session import get_db_session

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_session = AsyncMock()
        mock_session.execute = AsyncMock(return_value=mock_result)

        async def _override():
            yield mock_session

        app.dependency_overrides[get_db_session] = _override

        try:
            resp = await client.get("/api/buildings/InvalidBuilding/status")
            assert resp.status_code == 404
        finally:
            app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_building_status_returns_sensor_data(self, client):
        """查询存在的建筑返回传感器数据。"""
        from app.db.session import get_db_session

        call_count = 0

        async def mock_execute(query):
            nonlocal call_count
            call_count += 1
            mock_result = MagicMock()
            if call_count == 1:
                mock_result.scalar_one_or_none.return_value = _mock_building("Office")
            else:
                mock_result.scalar_one_or_none.return_value = _mock_energy_row()
            return mock_result

        mock_session = AsyncMock()
        mock_session.execute = mock_execute

        async def _override():
            yield mock_session

        app.dependency_overrides[get_db_session] = _override

        try:
            resp = await client.get("/api/buildings/Office/status")
            assert resp.status_code == 200
            data = resp.json()
            assert data["building_id"] == "Office"
            assert data["electricity_kwh"] == 450.0
            assert data["operation_status"] == "Anomaly"
            assert data["occupancy_density_per_100sqm"] == 0.0
        finally:
            app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_energy_trend_invalid_date_range(self, client):
        """start_date > end_date 返回 400。"""
        from app.db.session import get_db_session

        mock_session = AsyncMock()

        async def _override():
            yield mock_session

        app.dependency_overrides[get_db_session] = _override

        try:
            resp = await client.get(
                "/api/buildings/Office/energy",
                params={"start_date": "2024-02-01", "end_date": "2024-01-01"},
            )
            assert resp.status_code == 400
        finally:
            app.dependency_overrides.clear()


# ===========================================================================
# 4. SSE 对话接口
# ===========================================================================
class TestChatEndpoint:
    @pytest.mark.asyncio
    async def test_chat_returns_sse_stream(self, client):
        """POST /api/chat 返回 text/event-stream。"""
        from langchain_core.messages import AIMessage

        mock_graph = AsyncMock()

        # astream_events 产生一个 text 事件
        async def _mock_events(state, version):
            yield {
                "event": "on_chain_end",
                "name": "data_agent",
                "data": {
                    "output": {
                        "messages": [AIMessage(content="图书馆昨日用电 1520 kWh。")]
                    }
                },
            }

        mock_graph.astream_events = _mock_events
        mock_graph.ainvoke = AsyncMock(return_value={
            "messages": [],
            "hop_count": 1,
            "artifacts": [],
            "pending_action": None,
        })

        with patch("app.api.routes_chat.get_graph", return_value=mock_graph):
            resp = await client.post(
                "/api/chat",
                json={"message": "图书馆昨天的用电量是多少？"},
            )

        assert resp.status_code == 200
        assert "text/event-stream" in resp.headers["content-type"]

        # 解析 SSE 事件
        events = []
        for line in resp.text.split("\n"):
            if line.startswith("data: "):
                events.append(json.loads(line[6:]))

        event_types = [e["type"] for e in events]
        assert "thinking" in event_types
        assert "done" in event_types

    @pytest.mark.asyncio
    async def test_chat_empty_message_rejected(self, client):
        """空消息返回 422。"""
        resp = await client.post("/api/chat", json={"message": ""})
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_chat_creates_session(self, client):
        """对话接口自动创建 session_id。"""
        from langchain_core.messages import AIMessage

        mock_graph = AsyncMock()

        async def _mock_events(state, version):
            yield {
                "event": "on_chain_end",
                "name": "router",
                "data": {"output": {"messages": [AIMessage(content="好的，正在处理...")]}},
            }

        mock_graph.astream_events = _mock_events
        mock_graph.ainvoke = AsyncMock(return_value={
            "messages": [], "hop_count": 1, "artifacts": [], "pending_action": None,
        })

        with patch("app.api.routes_chat.get_graph", return_value=mock_graph):
            resp = await client.post(
                "/api/chat",
                json={"message": "测试"},
            )

        assert resp.status_code == 200
        # 响应头中包含 session id
        assert "x-session-id" in resp.headers

    @pytest.mark.asyncio
    async def test_session_not_found_returns_404(self, client):
        """查询不存在的会话返回 404。"""
        resp = await client.get("/api/chat/sessions/nonexistent-id")
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_approve_nonexistent_session_returns_404(self, client):
        """审批不存在会话的工单返回 404。"""
        resp = await client.post(
            "/api/chat/approve",
            json={
                "session_id": "ghost-session",
                "ticket_id": "temp_001",
                "approved": True,
            },
        )
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_clear_session(self, client):
        """清除会话后查询返回 404。"""
        from app.api.routes_chat import _sessions
        from app.graph.state import initial_state

        test_sid = "test-clear-session"
        _sessions[test_sid] = initial_state()

        resp = await client.delete(f"/api/chat/sessions/{test_sid}")
        assert resp.status_code == 200
        assert resp.json()["status"] == "cleared"

        resp2 = await client.get(f"/api/chat/sessions/{test_sid}")
        assert resp2.status_code == 404
