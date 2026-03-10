"""
阶段二：原子能力库 —— 业务动作与 UI 渲染工具（Tool 7 / 8）
============================================================
工具清单：
  render_ui_component     → Tool 7  生成前端组件渲染指令（Artifact JSON）
  create_work_order_draft → Tool 8  生成工单草稿（Human-in-the-loop，不写 DB）
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from app.schemas.mcp_schemas import (
    CreateWorkOrderDraftInput,
    CreateWorkOrderDraftOutput,
    MCPError,
    RenderUIComponentInput,
    RenderUIComponentOutput,
)


# ===========================================================================
# Tool 7：render_ui_component
# ===========================================================================

def render_ui_component(
    inp: RenderUIComponentInput,
) -> RenderUIComponentOutput | MCPError:
    """
    生成结构化 Artifact 渲染指令，通知前端选择对应 Vue 组件渲染。
    前端 SSE 监听到 type='artifact' 事件后，根据 widget 类型渲染：
      LineChart / BarChart → DynamicChart.vue
      Gauge               → DynamicChart.vue（gauge 模式）
      WorkOrderCard       → WorkOrderCard.vue
    """
    # 组件类型 → 前端 widget 标识符映射
    _widget_map = {
        "LineChart":     "line-chart",
        "BarChart":      "bar-chart",
        "Gauge":         "gauge",
        "WorkOrderCard": "work-order-card",
    }
    widget = _widget_map.get(inp.component_type)
    if widget is None:
        return MCPError(
            error=f"不支持的组件类型 '{inp.component_type}'，合法值：{list(_widget_map.keys())}",
            error_code="INVALID_COMPONENT_TYPE",
            tool_name="render_ui_component",
        )

    artifact_id = f"artifact_{uuid.uuid4().hex[:8]}"
    return RenderUIComponentOutput(
        artifact_id=artifact_id,
        widget=widget,
    )


# ===========================================================================
# Tool 8：create_work_order_draft
# ===========================================================================

def create_work_order_draft(
    inp: CreateWorkOrderDraftInput,
) -> CreateWorkOrderDraftOutput | MCPError:
    """
    Human-in-the-loop 核心工具。
    此函数绝对不写入生产数据库，只生成临时草稿并通知前端渲染审批卡片。
    真正的派单操作需用户在前端点击"批准"后，由独立的 API 端点执行。

    ticket_id 格式：temp_{8位uuid}，让前端和后端都知道这是"待确认的临时单"。
    """
    ticket_id = f"temp_{uuid.uuid4().hex[:8]}"
    now_utc = datetime.now(timezone.utc)

    return CreateWorkOrderDraftOutput(
        ticket_id=ticket_id,
        device_id=inp.device_id,
        building_id=inp.building_id,
        priority=inp.priority,
        issue_description=inp.issue_description,
        suggested_action=inp.suggested_action,
        created_at=now_utc,
    )
