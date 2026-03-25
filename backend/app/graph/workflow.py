"""
多智能体图编排（LangGraph StateGraph）—— v2 两阶段架构。

拓扑结构：
    START → router_node
    router_node --[data_query/cop_analysis]-→ data_react_node
    router_node --[fault_diagnosis/work_order]-→ diagnose_agent_node
    router_node --[clarify]-→ router_node (等待用户下一轮)
    router_node --[unknown/end]-→ END
    data_react_node → data_synthesis_node
    data_synthesis_node → END
    diagnose_agent_node → END

data_react_node:  ReAct 工具调用 + viz_engine 生成图表
data_synthesis_node:  Synthesis LLM 看到图表清单后生成精准分析文字
"""
from __future__ import annotations

import logging
from typing import Any, Literal

from langgraph.graph import END, START, StateGraph

from app.graph.nodes.data_agent import data_react_node, data_synthesis_node
from app.graph.nodes.diagnose_agent import diagnose_agent_node
from app.graph.nodes.router_agent import router_node
from app.graph.state import AgentState, NextNode

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 路由函数：根据 current_agent 字段决定下一个节点
# ---------------------------------------------------------------------------
def _route_from_router(
    state: AgentState,
) -> Literal["data_react", "diagnose_agent", "router", "__end__"]:
    """router_node 执行完毕后的条件边函数。"""
    next_agent: NextNode = state.get("current_agent", "end")
    mapping: dict[str, str] = {
        "data_agent":     "data_react",
        "diagnose_agent": "diagnose_agent",
        "router":         "router",
        "end":            END,
    }
    destination = mapping.get(next_agent, END)
    logger.debug("Router 路由决策: current_agent=%s → %s", next_agent, destination)
    return destination  # type: ignore[return-value]


# ---------------------------------------------------------------------------
# 构建图
# ---------------------------------------------------------------------------
def build_graph() -> Any:
    """组装并编译多智能体状态机图。"""
    builder = StateGraph(AgentState)

    # 注册节点
    builder.add_node("router",           router_node)
    builder.add_node("data_react",       data_react_node)
    builder.add_node("data_synthesis",   data_synthesis_node)
    builder.add_node("diagnose_agent",   diagnose_agent_node)

    # 起点 → Router
    builder.add_edge(START, "router")

    # Router 的条件边
    builder.add_conditional_edges(
        "router",
        _route_from_router,
        {
            "data_react":     "data_react",
            "diagnose_agent": "diagnose_agent",
            "router":         "router",
            END:              END,
        },
    )

    # data_react → data_synthesis → END（两阶段串联）
    builder.add_edge("data_react",     "data_synthesis")
    builder.add_edge("data_synthesis", END)

    # diagnose 直接结束
    builder.add_edge("diagnose_agent", END)

    return builder.compile()


# ---------------------------------------------------------------------------
# 模块级单例
# ---------------------------------------------------------------------------
_compiled_graph = None
_graph_lock: Any = None


def _get_graph_lock() -> Any:
    import threading
    global _graph_lock
    if _graph_lock is None:
        _graph_lock = threading.Lock()
    return _graph_lock


def get_graph() -> Any:
    """获取已编译的图（单例，首次调用时构建，锁保护）。"""
    global _compiled_graph
    lock = _get_graph_lock()
    with lock:
        if _compiled_graph is None:
            _compiled_graph = build_graph()
    return _compiled_graph
