from __future__ import annotations

from app.eval.models import (
    McpSchemaCase,
    McpToolListCase,
    RagFallbackCase,
    RagMetadataFilterCase,
    RouterEvalCase,
    RouterEvalExpected,
    RouterEvalInput,
    RouterFastPathCase,
    WorkOrderDraftCase,
    GraphE2ECase,
)


CASES = [
    RouterEvalCase(
        name="router:data_query:building+time",
        inp=RouterEvalInput(user_message="图书馆昨天的用电量是多少？"),
        mock_llm_json={
            "intent": "data_query",
            "confidence": 0.95,
            "next_agent": "data_agent",
            "building_id": "Education",
            "device_id": None,
            "time_context": {"start": "2016-04-24T00:00:00Z", "end": "2016-04-24T23:59:59Z"},
            "clarification_question": None,
        },
        expected=RouterEvalExpected(intent="data_query", next_agent="data_agent", building_id="Education"),
    ),
    RouterEvalCase(
        name="router:knowledge_query:routed_to_diagnose",
        inp=RouterEvalInput(user_message="GB 50189 对空调COP有什么要求？"),
        mock_llm_json={
            "intent": "knowledge_query",
            "confidence": 0.91,
            "next_agent": "diagnose_agent",
            "building_id": None,
            "device_id": None,
            "time_context": None,
            "clarification_question": None,
        },
        expected=RouterEvalExpected(intent="knowledge_query", next_agent="diagnose_agent", building_id=None),
    ),
    RouterEvalCase(
        name="router:inherit_building_id",
        inp=RouterEvalInput(user_message="那空调系统呢？", building_id="Office"),
        mock_llm_json={
            "intent": "data_query",
            "confidence": 0.88,
            "next_agent": "data_agent",
            "building_id": None,
            "device_id": None,
            "time_context": None,
            "clarification_question": None,
        },
        expected=RouterEvalExpected(intent="data_query", next_agent="data_agent", building_id="Office"),
    ),
    RouterFastPathCase(
        name="router:fast_path:greeting",
        message="你好",
        expect_reply_contains_any=["你好", "欢迎"],
    ),
    RagFallbackCase(
        name="rag:fallback:cop",
        query="空调COP能效比下降是什么原因？",
        top_k=2,
        expect_contains_any=["COP", "能效"],
    ),
    RagMetadataFilterCase(
        name="rag:metadata_filter:wired",
        query="请给我这台设备的维护要点",
        device_id="M-OFF-001",
        building_type="Office",
        expected_metadata_filter={"device_id": "M-OFF-001", "building_type": "Office"},
    ),
    McpSchemaCase(
        name="mcp:schema:error_on_missing_params",
        tool_name="query_energy_metrics",
        args={},
        expect_error_code="PARAM_VALIDATION_ERROR",
    ),
    McpToolListCase(
        name="mcp:tool_list:contains_core_tools",
        expect_contains_tools=[
            "query_energy_metrics",
            "rag_hybrid_search",
            "create_work_order_draft",
        ],
    ),
    WorkOrderDraftCase(
        name="hitl:work_order:draft_shape",
        args={
            "device_id": "Fox_office_Alice_hvac",
            "building_id": "Office",
            "issue_description": "凌晨时段电耗异常升高，疑似空调系统存在异常运行或控制策略失效。",
            "suggested_action": "现场检查BMS排程与阀门状态，必要时安排检修。",
            "priority": "high",
            "evidence_timestamp": "2016-04-10T03:00:00Z",
        },
        expected_status="pending_approval",
    ),
    McpSchemaCase(
        name="mcp:rag:works_without_db",
        tool_name="rag_hybrid_search",
        args={
            "query": "COP 下降 原因",
            "metadata_filter": {"device_id": None, "building_type": None},
            "enable_rerank": False,
            "top_k": 2,
        },
        expect_error_code=None,
    ),
    GraphE2ECase(
        name="graph:e2e:router_to_diagnose_to_hitl",
        user_message="办公楼凌晨电耗异常升高，帮我分析原因并生成工单草稿。",
        router_mock_llm_json={
            "intent": "fault_diagnosis",
            "confidence": 0.93,
            "next_agent": "diagnose_agent",
            "building_id": "Office",
            "device_id": "M-OFF-001",
            "time_context": {"start": "2016-04-10T03:00:00Z", "end": "2016-04-10T04:00:00Z"},
            "clarification_question": None,
        },
        expect_pending_action=True,
        expect_artifact_component_type="WorkOrderCard",
        expect_evidence_type="rag",
    ),
]
