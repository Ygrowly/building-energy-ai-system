"""
LangGraph 全局状态定义。

所有节点共享同一份 AgentState，通过 Annotated 指定合并策略：
- messages: 追加合并（LangGraph 内置 add_messages 减少器）
  ★ 约定：只存放 HumanMessage 和最终 AIMessage，ToolMessage 和中间推理不入全局 state，
    避免消息列表随工具调用数量膨胀。
- context_summary: 直接覆盖（每轮滚动更新）
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
    "general_chat",     # 通用对话（问候、系统介绍、闲聊等），Router 直接回复
    "clarify",          # 需要反问澄清
    "unknown",          # 完全无关的问题（股票、天气等）
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

    # -----------------------------------------------------------------------
    # 对话历史摘要（替代冗长的全量消息列表传递）
    # -----------------------------------------------------------------------
    context_summary: str
    """
    过去对话轮次的滚动摘要（自动维护，无需 LLM 额外调用）。

    每轮结束后由 Agent 节点更新，格式示例：
        第1轮[数据查询]: 三栋楼2016年4月每日用电趋势对比，Education最高
        第2轮[故障诊断]: 办公楼凌晨异常，HVAC故障，已生成待审批工单

    传递给各 Agent 时作为 SystemMessage 注入，让 LLM 了解历史上下文
    而无需读取全部原始消息（尤其是大量 ToolMessage）。
    最多保留最近 5 轮摘要，超出时舍弃最早的。
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
        context_summary="",
    )


# ---------------------------------------------------------------------------
# 辅助：构建滚动摘要（无需 LLM，从结构化信息拼装）
# ---------------------------------------------------------------------------
_INTENT_ZH: dict[str, str] = {
    "data_query":      "数据查询",
    "cop_analysis":    "COP分析",
    "fault_diagnosis": "故障诊断",
    "work_order":      "工单",
    "general_chat":    "通用对话",
    "clarify":         "澄清",
    "unknown":         "未知",
}
_MAX_SUMMARY_TURNS = 5
_MAX_ANSWER_CHARS  = 120


def update_context_summary(
    existing_summary: str,
    intent: str | None,
    user_question: str,
    agent_answer: str,
) -> str:
    """
    将本轮摘要追加到 existing_summary，超出 _MAX_SUMMARY_TURNS 轮时舍弃最早的。

    Args:
        existing_summary: 之前积累的摘要字符串（可为空）
        intent:           本轮意图标签
        user_question:    用户问题（截取前 80 字符）
        agent_answer:     Agent 最终回答（截取前 _MAX_ANSWER_CHARS 字符）
    """
    intent_label = _INTENT_ZH.get(intent or "", intent or "任务")
    q = user_question[:80].replace("\n", " ")
    a = agent_answer[:_MAX_ANSWER_CHARS].replace("\n", " ")
    new_line = f"[{intent_label}] 问: {q} → 摘: {a}"

    lines = [l for l in existing_summary.splitlines() if l.strip()]
    lines.append(new_line)
    # 只保留最近 N 轮
    lines = lines[-_MAX_SUMMARY_TURNS:]
    return "\n".join(lines)
