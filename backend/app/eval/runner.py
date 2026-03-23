from __future__ import annotations

import asyncio
import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from langchain_core.messages import HumanMessage

from app.eval.cases import CASES
from app.eval.models import (
    EvalCase,
    EvalResult,
    McpSchemaCase,
    McpToolListCase,
    RagFallbackCase,
    RagMetadataFilterCase,
    RouterEvalCase,
    RouterFastPathCase,
    WorkOrderDraftCase,
    GraphE2ECase,
)


def _mock_settings_for_rag(*, api_key: str = "", dataset_id: str = "", api_url: str = "http://ragflow.test:9380"):
    s = MagicMock()
    s.RAGFLOW_API_KEY = api_key
    s.RAGFLOW_DATASET_ID = dataset_id
    s.RAGFLOW_API_URL = api_url
    s.RAGFLOW_RERANK_ID = ""
    return s


def _mock_settings_for_llm():
    s = MagicMock()
    s.LLM_API_KEY = "test-key"
    s.LLM_BASE_URL = "http://llm.test"
    s.LLM_MODEL = "test-model"
    return s


async def _run_router_case(case: RouterEvalCase) -> EvalResult:
    from app.graph.state import initial_state
    from app.graph.nodes import router_agent

    # ensure cached router LLM doesn't leak across cases
    if hasattr(router_agent, "reset_router_llm_cache"):
        router_agent.reset_router_llm_cache()

    state = initial_state()
    if case.inp.building_id:
        state["building_id"] = case.inp.building_id
    state["messages"] = [HumanMessage(content=case.inp.user_message)]

    mock_resp = MagicMock()
    mock_resp.content = json.dumps(case.mock_llm_json, ensure_ascii=False)

    with (
        patch("app.graph.nodes.router_agent.ChatOpenAI") as MockLLM,
        patch("app.graph.nodes.router_agent.get_settings", return_value=_mock_settings_for_llm()),
    ):
        instance = MockLLM.return_value
        instance.ainvoke = AsyncMock(return_value=mock_resp)
        result_state = await router_agent.router_node(state)

    expected = case.expected
    got_intent = result_state.get("intent")
    got_agent = result_state.get("current_agent")
    got_building_id = result_state.get("building_id")

    ok = (
        got_intent == expected.intent
        and got_agent == expected.next_agent
        and got_building_id == expected.building_id
    )
    detail = f"intent={got_intent}, agent={got_agent}, building_id={got_building_id}"
    return EvalResult(name=case.name, type=case.type, passed=ok, detail=detail)


async def _run_rag_fallback_case(case: RagFallbackCase) -> EvalResult:
    from app.services import rag_engine

    mock_settings = _mock_settings_for_rag(api_key="", dataset_id="")
    with patch("app.services.rag_engine.get_settings", return_value=mock_settings):
        out = await rag_engine.search_ragflow(case.query, top_k=case.top_k)

    contents = "\n".join([r.content for r in out.results]) if hasattr(out, "results") else ""
    ok = True
    if case.expect_contains_any:
        ok = any(s in contents for s in case.expect_contains_any)
    detail = f"results={len(getattr(out, 'results', []) or [])}, reranked={getattr(out, 'reranked', None)}"
    return EvalResult(name=case.name, type=case.type, passed=ok, detail=detail)


async def _run_rag_metadata_filter_case(case: RagMetadataFilterCase) -> EvalResult:
    from app.mcp.tools.rag_search import rag_hybrid_search
    from app.schemas.mcp_schemas import MetadataFilter, RAGHybridSearchInput, RAGHybridSearchOutput, RAGSearchResult

    # stub out networked retrieval and capture metadata_filter passed in
    captured: dict[str, Any] = {}

    async def _fake_search_ragflow(*, query: str, metadata_filter: dict | None = None, enable_rerank: bool = True, top_k: int = 3):
        captured["query"] = query
        captured["metadata_filter"] = metadata_filter
        return RAGHybridSearchOutput(
            results=[
                RAGSearchResult(
                    content="stub",
                    parent_section="stub",
                    source_doc="stub",
                    page=1,
                    similarity=1.0,
                    rerank_score=None,
                )
            ],
            query=query,
            total_retrieved=1,
            reranked=False,
        )

    # rag_hybrid_search imports search_ragflow directly, so patch its local symbol.
    with patch("app.mcp.tools.rag_search.search_ragflow", side_effect=_fake_search_ragflow):
        inp = RAGHybridSearchInput(
            query=case.query,
            metadata_filter=MetadataFilter(device_id=case.device_id, building_type=case.building_type),
            enable_rerank=False,
            top_k=2,
        )
        _ = await rag_hybrid_search(inp)

    expected = case.expected_metadata_filter
    ok = (captured.get("metadata_filter") == expected)
    detail = f"metadata_filter={captured.get('metadata_filter')}"
    return EvalResult(name=case.name, type=case.type, passed=ok, detail=detail)


async def _run_mcp_schema_case(case: McpSchemaCase) -> EvalResult:
    from app.mcp.server import call_tool
    from app.schemas.mcp_schemas import MCPError

    # Force RAG tool to stay offline/deterministic.
    mock_settings = _mock_settings_for_rag(api_key="", dataset_id="")
    with patch("app.services.rag_engine.get_settings", return_value=mock_settings):
        res = await call_tool(case.tool_name, case.args, session=None)

    if isinstance(res, MCPError):
        ok = case.expect_error_code == res.error_code
        detail = f"error_code={res.error_code}, tool={res.tool_name}"
        return EvalResult(name=case.name, type=case.type, passed=ok, detail=detail)

    ok = case.expect_error_code is None
    detail = f"ok_type={type(res).__name__}"
    return EvalResult(name=case.name, type=case.type, passed=ok, detail=detail)


async def _run_mcp_tool_list_case(case: McpToolListCase) -> EvalResult:
    from app.mcp.server import list_tools

    tools = list_tools()
    names = {t.get("name") for t in tools}
    missing = [n for n in case.expect_contains_tools if n not in names]
    ok = len(missing) == 0
    detail = "missing=" + ",".join(missing) if missing else f"tools={len(names)}"
    return EvalResult(name=case.name, type=case.type, passed=ok, detail=detail)


async def _run_work_order_draft_case(case: WorkOrderDraftCase) -> EvalResult:
    from app.mcp.server import call_tool
    from app.schemas.mcp_schemas import MCPError

    res = await call_tool("create_work_order_draft", case.args, session=None)
    if isinstance(res, MCPError):
        return EvalResult(name=case.name, type=case.type, passed=False, detail=f"error_code={res.error_code}")

    status = getattr(res, "status", None) or (res.get("status") if isinstance(res, dict) else None)
    ok = status == case.expected_status
    detail = f"status={status}"
    return EvalResult(name=case.name, type=case.type, passed=ok, detail=detail)


async def _run_router_fast_path_case(case: RouterFastPathCase) -> EvalResult:
    from app.graph.state import initial_state
    from app.graph.nodes.router_agent import router_node
    from langchain_core.messages import AIMessage

    state = initial_state()
    state["messages"] = [HumanMessage(content=case.message)]
    out = await router_node(state)
    messages = out.get("messages") or []
    reply = ""
    for m in messages:
        if isinstance(m, AIMessage):
            reply = str(m.content)
            break
    ok = True
    if case.expect_reply_contains_any:
        ok = any(s in reply for s in case.expect_reply_contains_any)
    detail = f"reply={reply[:60]}"
    return EvalResult(name=case.name, type=case.type, passed=ok, detail=detail)


async def _run_graph_e2e_case(case: GraphE2ECase) -> EvalResult:
    from langchain_core.messages import AIMessage, ToolMessage

    from app.graph.state import initial_state
    from app.graph.workflow import build_graph

    # Build a deterministic "mock ReAct trace" for diagnose_agent.
    rag_payload = {
        "results": [
            {
                "content": "冷却塔结垢会导致 COP 下降 0.5~1.0。",
                "parent_section": "第2章 空调能效管理",
                "source_doc": "楼宇运维手册.pdf",
                "page": 12,
                "similarity": 0.9,
                "rerank_score": None,
            }
        ],
        "query": "COP 下降 原因",
        "total_retrieved": 1,
        "reranked": False,
    }

    from app.mcp.tools.ui_render import create_work_order_draft, render_ui_component
    from app.schemas.mcp_schemas import CreateWorkOrderDraftInput, RenderUIComponentInput

    draft = create_work_order_draft(CreateWorkOrderDraftInput(
        device_id="Fox_office_Alice_hvac",
        building_id="Office",
        issue_description="凌晨时段电耗异常升高，疑似空调系统存在异常运行或控制策略失效。",
        suggested_action="现场检查BMS排程与阀门状态，必要时安排检修。",
        priority="high",
        evidence_timestamp="2016-04-10T03:00:00Z",
    ))
    if hasattr(draft, "model_dump"):
        draft_payload = draft.model_dump()
    else:
        draft_payload = draft  # type: ignore[assignment]

    artifact = render_ui_component(RenderUIComponentInput(
        component_type="WorkOrderCard",
        title="工单草稿（待审批）",
        data_payload={
            "ticket_id": draft_payload.get("ticket_id"),
            "device_id": draft_payload.get("device_id"),
            "building_id": draft_payload.get("building_id"),
            "priority": draft_payload.get("priority"),
        },
        source_info={"type": "hitl"},
    ))
    artifact_payload = artifact.model_dump() if hasattr(artifact, "model_dump") else artifact  # type: ignore[assignment]

    tool_msgs = [
        ToolMessage(content=json.dumps(rag_payload, ensure_ascii=False), tool_call_id="tool_call_rag_1"),
        ToolMessage(content=json.dumps(draft_payload, ensure_ascii=False, default=str), tool_call_id="tool_call_wo_1"),
        ToolMessage(content=json.dumps(artifact_payload, ensure_ascii=False, default=str), tool_call_id="tool_call_ui_1"),
    ]
    final_ai = AIMessage(content="已结合知识库给出初步原因分析，并生成工单草稿（待审批）。")

    mock_agent_result = {"messages": []}  # filled at runtime based on injected messages

    from unittest.mock import AsyncMock

    # Patch router LLM + diagnose ReAct agent to be deterministic.
    from app.graph.nodes import router_agent
    from app.graph.nodes import diagnose_agent as diagnose_mod

    router_agent.reset_router_llm_cache()
    if hasattr(diagnose_mod, "reset_diagnose_agent_cache"):
        diagnose_mod.reset_diagnose_agent_cache()

    mock_router_resp = MagicMock()
    mock_router_resp.content = json.dumps(case.router_mock_llm_json, ensure_ascii=False)

    async def _ainvoke(sub_state: dict):
        # sub_state["messages"] includes injected context + history; append our trace.
        mock_agent_result["messages"] = list(sub_state.get("messages", [])) + tool_msgs + [final_ai]
        return mock_agent_result

    mock_agent = AsyncMock()
    mock_agent.ainvoke = AsyncMock(side_effect=_ainvoke)

    state = initial_state()
    state["messages"] = [HumanMessage(content=case.user_message)]

    with (
        patch("app.graph.nodes.router_agent.ChatOpenAI") as MockRouterLLM,
        patch("app.graph.nodes.router_agent.get_settings", return_value=_mock_settings_for_llm()),
        patch("app.graph.nodes.diagnose_agent.create_react_agent", return_value=mock_agent),
        patch("app.graph.nodes.diagnose_agent.get_settings", return_value=_mock_settings_for_llm()),
    ):
        MockRouterLLM.return_value.ainvoke = AsyncMock(return_value=mock_router_resp)
        graph = build_graph()
        out = await graph.ainvoke(state)

    ok = True
    checks: list[str] = []
    if case.expect_pending_action:
        ok = ok and bool(out.get("pending_action"))
        checks.append(f"pending_action={bool(out.get('pending_action'))}")
    if case.expect_artifact_component_type:
        arts = out.get("artifacts") or []
        ok_art = any(isinstance(a, dict) and a.get("component_type") == case.expect_artifact_component_type for a in arts)
        ok = ok and ok_art
        checks.append(f"artifact_component_type={ok_art}")
    if case.expect_evidence_type:
        ev = out.get("evidence") or []
        ok_ev = any(isinstance(e, dict) and e.get("type") == case.expect_evidence_type for e in ev)
        ok = ok and ok_ev
        checks.append(f"evidence_type={ok_ev}")

    return EvalResult(name=case.name, type=case.type, passed=ok, detail="; ".join(checks))


async def run_cases(cases: list[EvalCase] | None = None) -> list[EvalResult]:
    selected = cases or CASES
    results: list[EvalResult] = []
    for c in selected:
        if isinstance(c, RouterEvalCase):
            results.append(await _run_router_case(c))
        elif isinstance(c, RouterFastPathCase):
            results.append(await _run_router_fast_path_case(c))
        elif isinstance(c, RagFallbackCase):
            results.append(await _run_rag_fallback_case(c))
        elif isinstance(c, RagMetadataFilterCase):
            results.append(await _run_rag_metadata_filter_case(c))
        elif isinstance(c, McpSchemaCase):
            results.append(await _run_mcp_schema_case(c))
        elif isinstance(c, McpToolListCase):
            results.append(await _run_mcp_tool_list_case(c))
        elif isinstance(c, WorkOrderDraftCase):
            results.append(await _run_work_order_draft_case(c))
        elif isinstance(c, GraphE2ECase):
            results.append(await _run_graph_e2e_case(c))
        else:
            results.append(EvalResult(name=getattr(c, "name", "unknown"), type="mcp_schema", passed=False, detail="unknown case type"))
    return results


def run_sync(cases: list[EvalCase] | None = None) -> list[EvalResult]:
    return asyncio.run(run_cases(cases))


def format_summary(results: list[EvalResult]) -> str:
    total = len(results)
    passed = sum(1 for r in results if r.passed)
    lines = [f"Eval summary: {passed}/{total} passed"]
    for r in results:
        status = "PASS" if r.passed else "FAIL"
        lines.append(f"- {status} [{r.type}] {r.name}: {r.detail}")
    return "\n".join(lines)
