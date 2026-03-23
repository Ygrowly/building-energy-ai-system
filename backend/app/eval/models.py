from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel, Field


EvalCheckType = Literal[
    "router_intent",
    "router_fast_path",
    "rag_fallback",
    "rag_metadata_filter",
    "mcp_schema",
    "mcp_tool_list",
    "hitl_work_order",
    "graph_e2e",
]


class RouterEvalInput(BaseModel):
    user_message: str = Field(..., min_length=1)
    # optional inherited context
    building_id: str | None = None


class RouterEvalExpected(BaseModel):
    intent: str
    next_agent: str
    building_id: str | None = None


class RouterEvalCase(BaseModel):
    type: Literal["router_intent"] = "router_intent"
    name: str
    inp: RouterEvalInput
    # mock router LLM output payload (what RouterAgent expects to parse)
    mock_llm_json: dict[str, Any]
    expected: RouterEvalExpected


class RagFallbackCase(BaseModel):
    type: Literal["rag_fallback"] = "rag_fallback"
    name: str
    query: str
    top_k: int = 2
    expect_contains_any: list[str] = Field(default_factory=list)


class RagMetadataFilterCase(BaseModel):
    type: Literal["rag_metadata_filter"] = "rag_metadata_filter"
    name: str
    query: str
    device_id: str | None = None
    building_type: str | None = None
    expected_metadata_filter: dict[str, str] | None = None


class McpSchemaCase(BaseModel):
    type: Literal["mcp_schema"] = "mcp_schema"
    name: str
    tool_name: str
    args: dict[str, Any]
    expect_error_code: str | None = None


class McpToolListCase(BaseModel):
    type: Literal["mcp_tool_list"] = "mcp_tool_list"
    name: str
    expect_contains_tools: list[str] = Field(default_factory=list)


class WorkOrderDraftCase(BaseModel):
    type: Literal["hitl_work_order"] = "hitl_work_order"
    name: str
    args: dict[str, Any]
    expected_status: str = "pending_approval"


class RouterFastPathCase(BaseModel):
    type: Literal["router_fast_path"] = "router_fast_path"
    name: str
    message: str
    expect_reply_contains_any: list[str] = Field(default_factory=list)


class GraphE2ECase(BaseModel):
    type: Literal["graph_e2e"] = "graph_e2e"
    name: str
    user_message: str
    router_mock_llm_json: dict[str, Any]
    expect_pending_action: bool = False
    expect_artifact_component_type: str | None = None
    expect_evidence_type: str | None = None


EvalCase = (
    RouterEvalCase
    | RouterFastPathCase
    | RagFallbackCase
    | RagMetadataFilterCase
    | McpSchemaCase
    | McpToolListCase
    | WorkOrderDraftCase
    | GraphE2ECase
)


@dataclass(frozen=True)
class EvalResult:
    name: str
    type: EvalCheckType
    passed: bool
    detail: str = ""
