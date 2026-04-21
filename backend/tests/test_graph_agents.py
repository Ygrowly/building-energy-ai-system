"""
单智能体单元测试 — Phase 3 沙盒验证。

策略：
- mock ChatOpenAI，不发真实 LLM 请求
- mock call_tool，不连接数据库
- 验证每个 Agent 的路由逻辑、熔断机制、HITL 触发等核心行为
"""
from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from app.graph.state import initial_state
from app.graph.workflow import build_graph, _route_from_router


# ===========================================================================
# 工具函数
# ===========================================================================
def _make_llm_response(content: str):
    """构造 mock LLM 响应对象。"""
    mock_resp = MagicMock()
    mock_resp.content = content
    return mock_resp


# ===========================================================================
# 1. State 初始化测试
# ===========================================================================
class TestAgentState:
    def test_initial_state_defaults(self):
        state = initial_state()
        assert state["messages"] == []
        assert state["current_agent"] == "router"
        assert state["hop_count"] == 0
        assert state["intent"] is None
        assert state["confidence"] == 0.0
        assert state["building_id"] is None
        assert state["artifacts"] == []
        assert state["pending_action"] is None
        assert state["error"] is None

    def test_initial_state_evidence_empty(self):
        state = initial_state()
        assert state["evidence"] == []


# ===========================================================================
# 2. Router Agent 测试
# ===========================================================================
class TestRouterAgent:

    @pytest.fixture
    def base_state(self):
        state = initial_state()
        state["messages"] = [HumanMessage(content="图书馆昨天的用电量是多少？")]
        return state

    @pytest.mark.asyncio
    async def test_clear_data_query_intent(self, base_state):
        """明确的数据查询意图 → data_agent。"""
        mock_response_json = json.dumps({
            "intent": "data_query",
            "confidence": 0.95,
            "next_agent": "data_agent",
            "building_id": "Education",
            "device_id": None,
            "time_context": {"start": "2024-01-24T00:00:00Z", "end": "2024-01-24T23:59:59Z"},
            "clarification_question": None,
        })

        with patch("app.graph.nodes.router_agent.ChatOpenAI") as MockLLM:
            instance = MockLLM.return_value
            instance.ainvoke = AsyncMock(return_value=_make_llm_response(mock_response_json))

            from app.graph.nodes.router_agent import router_node
            result = await router_node(base_state)

        assert result["intent"] == "data_query"
        assert result["confidence"] == 0.95
        assert result["current_agent"] == "data_agent"
        assert result["building_id"] == "Education"
        assert result["hop_count"] == 1

    @pytest.mark.asyncio
    async def test_ambiguous_query_triggers_clarification(self):
        """模糊指令（"那个有问题"）→ intent=clarify，反问。"""
        state = initial_state()
        state["messages"] = [HumanMessage(content="那个好像有点问题。")]

        mock_response_json = json.dumps({
            "intent": "clarify",
            "confidence": 0.3,
            "next_agent": "router",
            "building_id": None,
            "device_id": None,
            "time_context": None,
            "clarification_question": "您是指哪栋建筑的哪个设备出现了问题？",
        })

        with patch("app.graph.nodes.router_agent.ChatOpenAI") as MockLLM:
            instance = MockLLM.return_value
            instance.ainvoke = AsyncMock(return_value=_make_llm_response(mock_response_json))

            from app.graph.nodes.router_agent import router_node
            result = await router_node(state)

        assert result["intent"] == "clarify"
        assert result["current_agent"] == "router"
        # 消息列表中应有反问
        ai_messages = [m for m in result["messages"] if isinstance(m, AIMessage)]
        assert len(ai_messages) == 1
        assert "哪栋建筑" in ai_messages[0].content

    @pytest.mark.asyncio
    async def test_unrelated_query_routed_to_end(self):
        """无关问题（"天气怎么样"）→ intent=unknown，next_agent=end。"""
        state = initial_state()
        state["messages"] = [HumanMessage(content="今天天气怎么样？")]

        mock_response_json = json.dumps({
            "intent": "unknown",
            "confidence": 0.98,
            "next_agent": "end",
            "building_id": None,
            "device_id": None,
            "time_context": None,
            "clarification_question": None,
        })

        with patch("app.graph.nodes.router_agent.ChatOpenAI") as MockLLM:
            instance = MockLLM.return_value
            instance.ainvoke = AsyncMock(return_value=_make_llm_response(mock_response_json))

            from app.graph.nodes.router_agent import router_node
            result = await router_node(state)

        assert result["intent"] == "unknown"
        assert result["current_agent"] == "end"
        ai_messages = [m for m in result["messages"] if isinstance(m, AIMessage)]
        assert "超出" in ai_messages[0].content or "范围" in ai_messages[0].content

    @pytest.mark.asyncio
    async def test_circuit_breaker_at_max_hops(self):
        """hop_count > 5 触发死循环熔断，强制结束。"""
        state = initial_state()
        state["hop_count"] = 5  # 再加1就超过阈值
        state["messages"] = [HumanMessage(content="继续查询。")]

        # 熔断逻辑不调用 LLM
        from app.graph.nodes.router_agent import router_node
        result = await router_node(state)

        assert result["current_agent"] == "end"
        assert result["hop_count"] == 6
        ai_messages = [m for m in result["messages"] if isinstance(m, AIMessage)]
        assert "熔断" in ai_messages[0].content or "人工" in ai_messages[0].content

    @pytest.mark.asyncio
    async def test_context_inheritance(self):
        """多轮对话上下文继承：building_id 从上一轮状态传入。"""
        state = initial_state()
        state["building_id"] = "Office"  # 上一轮已确定建筑
        state["messages"] = [
            HumanMessage(content="图书馆昨天的电费"),
            AIMessage(content="[Router] 意图确认"),
            HumanMessage(content="那空调系统呢？"),
        ]

        # 省略建筑名，但上下文有 building_id=Office
        mock_response_json = json.dumps({
            "intent": "data_query",
            "confidence": 0.88,
            "next_agent": "data_agent",
            "building_id": None,  # 用户没说建筑名
            "device_id": None,
            "time_context": None,
            "clarification_question": None,
        })

        with patch("app.graph.nodes.router_agent.ChatOpenAI") as MockLLM:
            instance = MockLLM.return_value
            instance.ainvoke = AsyncMock(return_value=_make_llm_response(mock_response_json))

            from app.graph.nodes.router_agent import router_node
            result = await router_node(state)

        # building_id 应继承自之前状态
        assert result["building_id"] == "Office"

    @pytest.mark.asyncio
    async def test_fault_diagnosis_routed_to_diagnose_agent(self):
        """故障诊断意图 → diagnose_agent。"""
        state = initial_state()
        state["messages"] = [HumanMessage(content="办公楼凌晨3点的电耗很高，有没有问题？")]

        mock_response_json = json.dumps({
            "intent": "fault_diagnosis",
            "confidence": 0.92,
            "next_agent": "diagnose_agent",
            "building_id": "Office",
            "device_id": "M-OFF-001",
            "time_context": {"start": "2024-01-25T03:00:00Z", "end": "2024-01-25T04:00:00Z"},
            "clarification_question": None,
        })

        with patch("app.graph.nodes.router_agent.ChatOpenAI") as MockLLM:
            instance = MockLLM.return_value
            instance.ainvoke = AsyncMock(return_value=_make_llm_response(mock_response_json))

            from app.graph.nodes.router_agent import router_node
            result = await router_node(state)

        assert result["current_agent"] == "diagnose_agent"
        assert result["building_id"] == "Office"
        assert result["device_id"] == "M-OFF-001"

    @pytest.mark.asyncio
    async def test_invalid_json_from_llm_triggers_fallback(self):
        """LLM 返回非 JSON 时，安全降级为 clarify。"""
        state = initial_state()
        state["messages"] = [HumanMessage(content="查数据")]

        with patch("app.graph.nodes.router_agent.ChatOpenAI") as MockLLM:
            instance = MockLLM.return_value
            instance.ainvoke = AsyncMock(
                return_value=_make_llm_response("我不知道该怎么办")  # 非JSON
            )

            from app.graph.nodes.router_agent import router_node
            result = await router_node(state)

        # 降级为 clarify
        assert result["intent"] == "clarify"

    def test_fast_path_defers_aggregate_anomaly_question_to_llm(self):
        """“总能耗为什么高”类问题应视为复合意图，不应被快速路由为纯诊断。"""
        from app.graph.nodes.router_agent import _try_fast_path

        result = _try_fast_path("4月18日办公楼总能耗为什么这么高？")
        assert result is None


# ===========================================================================
# 3. 条件路由函数测试（纯逻辑，无 LLM）
# ===========================================================================
class TestRouteFromRouter:
    def test_data_agent_routing(self):
        state = initial_state()
        state["current_agent"] = "data_agent"
        assert _route_from_router(state) == "data_agent"

    def test_diagnose_agent_routing(self):
        state = initial_state()
        state["current_agent"] = "diagnose_agent"
        assert _route_from_router(state) == "diagnose_agent"

    def test_router_self_loop(self):
        state = initial_state()
        state["current_agent"] = "router"
        assert _route_from_router(state) == "router"

    def test_end_routing(self):
        from langgraph.graph import END
        state = initial_state()
        state["current_agent"] = "end"
        assert _route_from_router(state) == END


# ===========================================================================
# 4. Data Agent 测试
# ===========================================================================
class TestDataAgent:

    @pytest.mark.asyncio
    async def test_data_agent_calls_query_tool(self):
        """Data Agent 正确调用 query_energy_metrics 并整合结果。"""
        state = initial_state()
        state["building_id"] = "Education"
        state["messages"] = [
            HumanMessage(content="查询图书馆昨天的用电量"),
        ]

        # mock ReAct agent 的结果
        mock_tool_result = {
            "records": [{"timestamp": "2024-01-24T10:00:00Z", "electricity_kwh": 120.5}],
            "source_table": "energy_data",
            "meter_device_id": "M-EDU-001",
            "unit": "kWh",
        }
        mock_final_answer = AIMessage(
            content="图书馆昨天共用电 120.5 kWh，数据来源：energy_data 表，设备 M-EDU-001。"
        )
        mock_agent_result = {
            "messages": list(state["messages"]) + [mock_final_answer],
        }

        with patch("app.graph.nodes.data_agent.create_react_agent") as mock_create:
            mock_agent = AsyncMock()
            mock_agent.ainvoke = AsyncMock(return_value=mock_agent_result)
            mock_create.return_value = mock_agent

            from app.graph.nodes.data_agent import data_agent_node
            result = await data_agent_node(state)

        assert result["current_agent"] == "end"
        assert result["hop_count"] == 1
        # 新增消息应包含最终答案
        assert any(
            isinstance(m, AIMessage) and "120.5" in m.content
            for m in result["messages"]
        )

    @pytest.mark.asyncio
    async def test_data_agent_handles_execution_error(self):
        """Data Agent 执行失败时优雅降级，返回错误消息。"""
        state = initial_state()
        state["messages"] = [HumanMessage(content="查询数据")]

        with patch("app.graph.nodes.data_agent.create_react_agent") as mock_create:
            mock_agent = AsyncMock()
            mock_agent.ainvoke = AsyncMock(
                side_effect=RuntimeError("LLM API 连接超时")
            )
            mock_create.return_value = mock_agent

            from app.graph.nodes.data_agent import data_agent_node
            result = await data_agent_node(state)

        assert result["current_agent"] == "end"
        assert result["error"] is not None
        ai_messages = [m for m in result["messages"] if isinstance(m, AIMessage)]
        assert len(ai_messages) == 1
        assert "数据分析师" in ai_messages[0].content


# ===========================================================================
# 5. Diagnose Agent 测试
# ===========================================================================
class TestDiagnoseAgent:

    @pytest.mark.asyncio
    async def test_diagnose_agent_creates_work_order_pending(self):
        """Diagnose Agent 生成工单后，pending_action 应为 pending_approval。"""
        from langchain_core.messages import ToolMessage
        from app.graph.nodes.diagnose_agent import reset_diagnose_agent_cache

        reset_diagnose_agent_cache()
        state = initial_state()
        state["messages"] = [
            HumanMessage(content="办公楼凌晨3点耗电异常，帮我派单处理。"),
        ]

        work_order_result = json.dumps({
            "status": "pending_approval",
            "ticket_id": "temp_abc123",
            "device_id": "M-OFF-001",
            "building_id": "Office",
            "issue_description": "凌晨3点高耗电异常，疑似定时策略失效",
            "priority": "High",
            "suggested_action": "检查定时控制器继电器",
        })
        tool_msg = ToolMessage(
            content=work_order_result,
            tool_call_id="tool_call_1",
        )
        final_answer = AIMessage(
            content="我已生成维修工单草稿，请确认后派单。"
        )
        mock_agent_result = {
            "messages": list(state["messages"]) + [tool_msg, final_answer],
        }

        with patch("app.graph.nodes.diagnose_agent.create_react_agent") as mock_create:
            mock_agent = AsyncMock()
            mock_agent.ainvoke = AsyncMock(return_value=mock_agent_result)
            mock_create.return_value = mock_agent

            from app.graph.nodes.diagnose_agent import diagnose_agent_node
            result = await diagnose_agent_node(state)

        # 工单草稿必须写入 pending_action
        assert result["pending_action"] is not None
        assert result["pending_action"]["ticket_id"] == "temp_abc123"
        assert result["pending_action"]["type"] == "work_order"
        assert result["pending_action"]["priority"] == "High"

    @pytest.mark.asyncio
    async def test_diagnose_agent_error_graceful_degradation(self):
        """Diagnose Agent 执行失败时优雅降级。"""
        from app.graph.nodes.diagnose_agent import reset_diagnose_agent_cache

        reset_diagnose_agent_cache()
        state = initial_state()
        state["messages"] = [HumanMessage(content="诊断故障")]

        with patch("app.graph.nodes.diagnose_agent.create_react_agent") as mock_create:
            mock_agent = AsyncMock()
            mock_agent.ainvoke = AsyncMock(
                side_effect=Exception("RAG 服务不可用")
            )
            mock_create.return_value = mock_agent

            from app.graph.nodes.diagnose_agent import diagnose_agent_node
            result = await diagnose_agent_node(state)

        assert result["current_agent"] == "end"
        assert result["error"] is not None
        ai_messages = [m for m in result["messages"] if isinstance(m, AIMessage)]
        assert "故障诊断专家" in ai_messages[0].content

    @pytest.mark.asyncio
    async def test_diagnose_agent_replaces_incomplete_answer_with_fallback_summary(self):
        """最终回答含“待补充/需调用”占位符时，应自动替换为完整兜底诊断。"""
        from app.graph.nodes.diagnose_agent import reset_diagnose_agent_cache

        reset_diagnose_agent_cache()
        state = initial_state()
        state["intent"] = "fault_diagnosis"
        state["messages"] = [HumanMessage(content="4月18日办公楼总能耗为什么这么高？")]

        anomaly_tool_call_id = "tool_call_anomaly"
        rated_tool_call_id = "tool_call_rated"
        daily_tool_call_id = "tool_call_daily"

        mock_agent_result = {
            "messages": [
                *state["messages"],
                AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "id": daily_tool_call_id,
                            "name": "query_daily_energy_summary",
                            "args": {
                                "building_id": "Office",
                                "date_range": {
                                    "start": "2026-04-18T00:00:00Z",
                                    "end": "2026-04-19T00:00:00Z",
                                },
                                "granularity": "day",
                            },
                        }
                    ],
                ),
                ToolMessage(
                    content='{"building_id":"Office","records":[{"day":"2026-04-18","building_id":"Office","total_electricity_kwh":113.3049,"avg_ambient_temp":23.6,"total_water_m3":0.0,"total_hac_energy":33.852,"avg_supply_temp":0.0,"avg_return_temp":0.0,"avg_humidity":0.0,"avg_dew_temp":0.0}],"granularity":"day","date_range_days":1}',
                    tool_call_id=daily_tool_call_id,
                    name="query_daily_energy_summary",
                ),
                AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "id": anomaly_tool_call_id,
                            "name": "detect_energy_anomalies",
                            "args": {
                                "building_id": "Office",
                                "time_range": {
                                    "start": "2026-04-18T00:00:00Z",
                                    "end": "2026-04-19T00:00:00Z",
                                },
                                "rules": ["electricity_overload", "hvac_overconsumption"],
                            },
                        }
                    ],
                ),
                ToolMessage(
                    content='{"anomalies":[],"total_anomalies":0,"building_id":"Office","period_start":"2026-04-18T00:00:00Z","period_end":"2026-04-19T00:00:00Z"}',
                    tool_call_id=anomaly_tool_call_id,
                    name="detect_energy_anomalies",
                ),
                AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "id": rated_tool_call_id,
                            "name": "get_building_rated_values",
                            "args": {
                                "building_id": "Office",
                                "time_range": {
                                    "start": "2026-04-18T00:00:00Z",
                                    "end": "2026-04-19T00:00:00Z",
                                },
                                "metrics": ["electricity"],
                            },
                        }
                    ],
                ),
                ToolMessage(
                    content='{"building_id":"Office","primary_space_usage":"Office","sqm":5000,"records":[{"timestamp":"2026-04-18T00:00:00Z","hvac_mode":"Cooling","schedule_factor":0.5,"rated_water_m3":0.0,"rated_electricity_kwh":120.0,"rated_hac_energy":0.0,"expected_supply_temp":7.0,"expected_return_temp":12.0,"actual_water_m3":0.0,"actual_electricity_kwh":113.3049,"actual_hac_energy":33.852,"actual_supply_temp":null,"actual_return_temp":null,"water_deviation_pct":0.0,"electricity_deviation_pct":-5.58,"hac_deviation_pct":0.0}],"total_hours":24,"anomaly_hours":0,"period_start":"2026-04-18T00:00:00Z","period_end":"2026-04-19T00:00:00Z"}',
                    tool_call_id=rated_tool_call_id,
                    name="get_building_rated_values",
                ),
                AIMessage(
                    content="诊断结论：未发现异常。\n量化依据：总电耗实际值：[需调用 query_energy_metrics 获取具体数值]\n建议操作：需要继续执行哪项操作？"
                ),
            ],
        }

        with patch("app.graph.nodes.diagnose_agent.create_react_agent") as mock_create:
            mock_agent = AsyncMock()
            mock_agent.ainvoke = AsyncMock(return_value=mock_agent_result)
            mock_create.return_value = mock_agent

            from app.graph.nodes.diagnose_agent import diagnose_agent_node
            result = await diagnose_agent_node(state)

        ai_messages = [m for m in result["messages"] if isinstance(m, AIMessage)]
        assert ai_messages
        final_text = ai_messages[0].content
        assert "待补充" not in final_text
        assert "需要继续执行" not in final_text
        assert "113.30 kWh" in final_text
        assert "0 条异常记录" in final_text


# ===========================================================================
# 6. 图结构测试（无 LLM 调用）
# ===========================================================================
class TestWorkflowGraph:
    def test_graph_can_be_built(self):
        """图应该能够成功编译，无异常。"""
        graph = build_graph()
        assert graph is not None

    def test_graph_has_correct_nodes(self):
        """图包含三个节点。"""
        graph = build_graph()
        node_names = set(graph.nodes.keys())
        assert "router" in node_names
        assert "data_agent" in node_names
        assert "diagnose_agent" in node_names
