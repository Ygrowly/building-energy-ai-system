"""
阶段一：接口契约 —— Generative UI SSE 渲染协议
=================================================
约定后端向前端推送的所有 SSE 事件类型与结构体。
前端只需根据 `type` 字段分流处理，无需解析非结构化文本。

事件类型总览：
  thinking      → Agent 思维链进度（前端展示状态气泡）
  text          → 普通文字回复（流式打字机效果）
  artifact      → 生成式 UI 组件指令（图表 / 工单卡片 / 审计面板）
  error         → 可读错误信息（供大模型自我修正用）
  done          → 本次对话流结束标记
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Annotated, Any, Literal, Optional, Union
from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# 枚举常量
# ---------------------------------------------------------------------------

class SSEEventType(str, Enum):
    """SSE 事件的顶层类型标识，前端以此做一级分流。"""
    THINKING = "thinking"
    TEXT = "text"
    ARTIFACT = "artifact"
    ERROR = "error"
    DONE = "done"


class AgentName(str, Enum):
    """多智能体名称，与 LangGraph 节点 ID 保持一致。"""
    ROUTER = "router"
    DATA = "data"
    DIAGNOSE = "diagnose"
    ACTION = "action"


class WidgetType(str, Enum):
    """Artifact 可渲染的组件类型，前端据此选择 Vue 组件。"""
    LINE_CHART = "line-chart"
    BAR_CHART = "bar-chart"
    GAUGE = "gauge"
    WORK_ORDER_CARD = "work-order-card"
    DATA_SOURCE_PANEL = "data-source-panel"
    REPORT_DOWNLOAD = "report-download"


# ---------------------------------------------------------------------------
# 事件 1：thinking — Agent 思维链进度
# ---------------------------------------------------------------------------

class ThinkingEvent(BaseModel):
    """
    后端在每次 Agent 切换或关键步骤时推送。
    前端展示效果：右侧 Console 的状态气泡（如 "🕵️ Data Agent 正在查询聚合视图…"）。
    """
    type: Literal[SSEEventType.THINKING] = SSEEventType.THINKING
    agent: AgentName
    message: str = Field(
        description="人类可读的进度描述，如 '正在查询 energy_data 按天聚合数据…'"
    )
    hop_count: int = Field(ge=0, le=5, description="当前流转跳数，超过 5 触发熔断")


# ---------------------------------------------------------------------------
# 事件 2：text — 流式文字回复
# ---------------------------------------------------------------------------

class TextEvent(BaseModel):
    """
    普通文字回复，支持流式打字机。
    `is_final=True` 时表示本段文字已完整，可渲染引用锚点 [1][2]。
    """
    type: Literal[SSEEventType.TEXT] = SSEEventType.TEXT
    content: str
    is_final: bool = False


# ---------------------------------------------------------------------------
# 事件 3：artifact — 生成式 UI 组件
# ---------------------------------------------------------------------------

class ChartSeries(BaseModel):
    """图表中单条折线/柱条的数据序列。"""
    name: str = Field(description="如 'Education（教学楼）'")
    data: list[float]
    timestamps: list[str] = Field(description="与 data 等长的 ISO8601 时间戳列表")


class ChartPayload(BaseModel):
    """
    折线图 / 柱状图的数据载体。
    同时携带审计信息，前端用于渲染"数据来源与性能分析"浮层。
    """
    title: str
    x_label: str
    y_label: str
    unit: str
    series: list[ChartSeries] = Field(min_length=1)
    # 审计信息
    source_table: str = Field(description="如 'energy_data'")
    meter_ids: list[str] = Field(description="如 ['M-EDU-001', 'M-OFF-001']")
    query_ms: Optional[int] = Field(default=None, description="查询耗时（毫秒）")


class WorkOrderPayload(BaseModel):
    """
    维修工单卡片数据。status='pending_approval' 时前端渲染黄色待审批卡片。
    用户点击"批准"后前端将 status 改为 'approved' 并回传后端。
    """
    ticket_id: str = Field(description="临时工单 ID，如 'temp_abc123'")
    device_id: str = Field(description="如 'M-OFF-001'")
    building_id: str
    priority: Literal["low", "medium", "high", "critical"]
    issue_description: str
    suggested_action: str
    status: Literal["pending_approval", "approved", "rejected"] = "pending_approval"
    created_at: str = Field(description="ISO8601 UTC 时间戳")


class DataSourcePayload(BaseModel):
    """
    "数据血缘审计"面板数据。
    用于页面 4（数据中心）或图表下方"🔍 数据来源与性能分析"浮层。
    """
    source_table: str = Field(description="直接查询的表，如 'energy_data'")
    meter_ids: list[str]
    query_ms: int
    lineage: list[str] = Field(
        description="数据流向描述列表，如 ['原始传感器CSV → energy_data 表 → GROUP BY 聚合 → AI分析结论']"
    )


class ArtifactEvent(BaseModel):
    """
    生成式 UI 渲染指令。前端拦截此事件后，根据 `widget` 选择 Vue 组件渲染。
    payload 使用带判别器的联合类型，Pydantic v2 自动路由。
    """
    type: Literal[SSEEventType.ARTIFACT] = SSEEventType.ARTIFACT
    artifact_id: str = Field(description="唯一标识，用于后续审批回调定位")
    widget: WidgetType
    payload: Annotated[
        Union[ChartPayload, WorkOrderPayload, DataSourcePayload],
        Field(description="根据 widget 类型对应不同 Payload 结构")
    ]


# ---------------------------------------------------------------------------
# 事件 4：error — 可读错误（供大模型自我修正）
# ---------------------------------------------------------------------------

class ErrorEvent(BaseModel):
    """
    严禁直接抛出系统级 Exception。
    所有工具错误必须包装为此结构，让大模型能"看懂"并自我修正调用参数。
    """
    type: Literal[SSEEventType.ERROR] = SSEEventType.ERROR
    code: str = Field(description="机器可读错误码，如 'PARAM_VALIDATION_ERROR'")
    message: str = Field(description="自然语言描述，如 'time_range.end 必须晚于 start'")
    tool_name: Optional[str] = Field(default=None, description="触发错误的 MCP 工具名")


# ---------------------------------------------------------------------------
# 事件 5：done — 对话流结束
# ---------------------------------------------------------------------------

class DoneEvent(BaseModel):
    """标记本次对话的完整流结束，前端解除流式状态。"""
    type: Literal[SSEEventType.DONE] = SSEEventType.DONE
    total_hops: int = Field(ge=0, le=5)
    agents_involved: list[AgentName]


# ---------------------------------------------------------------------------
# 总联合类型（供 FastAPI SSE 接口的响应模型使用）
# ---------------------------------------------------------------------------

SSEEvent = Union[ThinkingEvent, TextEvent, ArtifactEvent, ErrorEvent, DoneEvent]


# ---------------------------------------------------------------------------
# 会话管理 Schema（对应 Cursor 对话侧边栏功能）
# ---------------------------------------------------------------------------

class SessionInfo(BaseModel):
    """
    单个会话的元数据摘要，用于侧边栏列表展示及会话切换。
    """
    session_id: str
    title: str
    created_at: datetime
    updated_at: datetime
    message_count: int
    last_message: Optional[str] = Field(
        default=None,
        description="最近一条用户消息的前 200 字，用于列表预览",
    )
    building_id: Optional[str] = Field(
        default=None,
        description="会话绑定的楼宇类型（如 'Office'），为 None 表示未绑定",
    )
    is_archived: bool = False
    has_pending_action: bool = Field(
        default=False,
        description="当前会话是否有待审批的 HITL 工单",
    )


class SessionListResponse(BaseModel):
    """GET /api/chat/sessions 的响应体。"""
    sessions: list[SessionInfo]
    total: int


class SessionCreateRequest(BaseModel):
    """POST /api/chat/sessions 的请求体（预建命名会话）。"""
    title: Optional[str] = Field(
        default=None,
        description='会话标题，不传则使用默认值"新对话"，发送第一条消息后自动更新为消息摘要',
    )


class SessionUpdateRequest(BaseModel):
    """PATCH /api/chat/sessions/{id} 的请求体（重命名或更换绑定楼宇）。"""
    title: Optional[str] = Field(
        default=None,
        description="新标题，不传则不修改",
    )
    building_id: Optional[str] = Field(
        default=None,
        description="绑定楼宇类型，不传则不修改，传 '' 空字符串表示清除绑定",
    )
