"""
LangGraph 全局状态定义。

所有节点共享同一份 AgentState，通过 Annotated 指定合并策略：
- messages: 追加合并（LangGraph 内置 add_messages 减少器）
- 其他字段: 直接覆盖（最新值获胜）
"""
from __future__ import annotations

from typing import Annotated, Any, Literal

from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages
from typing_extensions import TypedDict


# ---------------------------------------------------------------------------
# 意图类型枚举（字面量，便于路由判断）
# ---------------------------------------------------------------------------
IntentType = Literal[
    "data_query",       # 查询能耗数据 / 设备状态
    "cop_analysis",     # 能效比计算
    "fault_diagnosis",  # 故障诊断
    "work_order",       # 生成工单
    "clarify",          # 需要反问澄清
    "unknown",          # 无法识别
]

# 下一个节点路由目标
NextNode = Literal["router", "data_agent", "diagnose_agent", "end"]


class AgentState(TypedDict):
    """多智能体全局共享状态。"""

    # -----------------------------------------------------------------------
    # 核心对话
    # -----------------------------------------------------------------------
    messages: Annotated[list[BaseMessage], add_messages]
    """所有历史消息（用户 + AI + Tool），由 add_messages 追加合并。"""

    # -----------------------------------------------------------------------
    # 路由元数据
    # -----------------------------------------------------------------------
    current_agent: NextNode
    """当前负责处理的 Agent 节点名称。"""

    intent: IntentType | None
    """Router 识别到的用户意图。"""

    confidence: float
    """意图置信度 [0.0, 1.0]，< 0.7 触发反问。"""

    hop_count: int
    """图内节点跳转计数，> 5 触发死循环熔断。"""

    # -----------------------------------------------------------------------
    # 上下文实体（从对话中提取，供多轮继承）
    # -----------------------------------------------------------------------
    building_id: str | None
    """当前上下文建筑 ID（如 "Office", "Education", "Public"）。"""

    time_context: dict[str, str] | None
    """时间上下文，如 {"start": "2024-01-01T00:00:00Z", "end": "2024-01-02T00:00:00Z"}。"""

    device_id: str | None
    """当前上下文设备 ID（如 "M-OFF-001"）。"""

    # -----------------------------------------------------------------------
    # 证据链（数据血缘 + RAG 溯源）
    # -----------------------------------------------------------------------
    evidence: list[dict[str, Any]]
    """
    数据血缘证据列表。每个元素示例：
    {
        "type": "db_query",
        "source_table": "energy_data",
        "meter_device_id": "M-OFF-001",
        "timestamp": "2024-01-25T03:00:00Z"
    }
    或 RAG 来源：
    {
        "type": "rag",
        "source_doc": "Chiller_Manual_V2.pdf",
        "page": 42,
        "similarity": 0.98
    }
    """

    # -----------------------------------------------------------------------
    # 生成式 UI 指令（Artifacts）
    # -----------------------------------------------------------------------
    artifacts: list[dict[str, Any]]
    """
    生成式 UI 渲染指令列表，供 SSE 推送到前端。
    结构遵循 genui_protocol.py 中的 ArtifactEvent 规范。
    """

    # -----------------------------------------------------------------------
    # 人机协同（HITL）
    # -----------------------------------------------------------------------
    pending_action: dict[str, Any] | None
    """
    待审批的高危操作。非 None 时前端弹出确认卡片。
    示例：{"type": "work_order", "ticket_id": "temp_001", "description": "..."}
    """

    # -----------------------------------------------------------------------
    # 错误与状态
    # -----------------------------------------------------------------------
    error: str | None
    """最近一次系统级错误信息（工具调用失败等）。"""

    available_buildings: list[str] | None
    """
    当前系统中所有楼宇的 building_type 列表（如 ['Education', 'Office', 'Public']）。
    由对话初始化时从数据库查询注入，供 RouterAgent System Prompt 动态替换。
    为 None 时 RouterAgent 使用默认白名单降级。
    """


def initial_state(available_buildings: list[str] | None = None) -> AgentState:
    """创建空白初始状态，用于新会话。"""
    return AgentState(
        messages=[],
        current_agent="router",
        intent=None,
        confidence=0.0,
        hop_count=0,
        building_id=None,
        time_context=None,
        device_id=None,
        evidence=[],
        artifacts=[],
        pending_action=None,
        error=None,
        available_buildings=available_buildings,
    )
