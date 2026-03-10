"""
多智能体图编排（LangGraph StateGraph）。

拓扑结构：
    START → router_node
    router_node --[data_query/cop_analysis]-→ data_agent_node
    router_node --[fault_diagnosis/work_order]-→ diagnose_agent_node
    router_node --[clarify]-→ router_node (等待用户下一轮)
    router_node --[unknown/end]-→ END
    data_agent_node → END
    diagnose_agent_node → END

熔断逻辑在 router_node 内部处理（hop_count > MAX_HOPS → END）。
"""
from __future__ import annotations

import logging
from typing import Any, Literal

from langgraph.graph import END, START, StateGraph

from app.graph.nodes.data_agent import data_agent_node
from app.graph.nodes.diagnose_agent import diagnose_agent_node
from app.graph.nodes.router_agent import router_node
from app.graph.state import AgentState, NextNode

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 路由函数：根据 current_agent 字段决定下一个节点
# ---------------------------------------------------------------------------
def _route_from_router(
    state: AgentState,
) -> Literal["data_agent", "diagnose_agent", "router", "__end__"]:
    """
    router_node 执行完毕后的条件边函数。
    读取 state["current_agent"] 决定下一跳目标。
    """
    next_agent: NextNode = state.get("current_agent", "end")
    mapping: dict[str, str] = {
        "data_agent":     "data_agent",
        "diagnose_agent": "diagnose_agent",
        "router":         "router",   # clarify：回到自己等用户继续
        "end":            END,
    }
    destination = mapping.get(next_agent, END)
    logger.debug("Router 路由决策: current_agent=%s → %s", next_agent, destination)
    return destination  # type: ignore[return-value]


# ---------------------------------------------------------------------------
# 构建图
# ---------------------------------------------------------------------------
def build_graph() -> Any:
    """
    组装并编译多智能体状态机图。

    返回已编译的 CompiledStateGraph，可直接调用 .invoke() / .ainvoke()。
    """
    builder = StateGraph(AgentState)

    # 注册节点
    builder.add_node("router",         router_node)
    builder.add_node("data_agent",     data_agent_node)
    builder.add_node("diagnose_agent", diagnose_agent_node)

    # 起点 → Router
    builder.add_edge(START, "router")

    # Router 的条件边
    builder.add_conditional_edges(
        "router",
        _route_from_router,
        {
            "data_agent":     "data_agent",
            "diagnose_agent": "diagnose_agent",
            "router":         "router",
            END:              END,
        },
    )

    # 专家节点完成后直接结束（Phase 4 可扩展为回到 Router 进行多轮协同）
    builder.add_edge("data_agent",     END)
    builder.add_edge("diagnose_agent", END)

    return builder.compile()


# ---------------------------------------------------------------------------
# 模块级单例（延迟初始化）
# ---------------------------------------------------------------------------
_compiled_graph = None


def get_graph() -> Any:
    """获取已编译的图（单例，首次调用时构建）。"""
    global _compiled_graph
    if _compiled_graph is None:
        _compiled_graph = build_graph()
    return _compiled_graph
