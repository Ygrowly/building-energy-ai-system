"""
Data Agent（数据分析师）节点。

职责：
- 能耗数据查询（query_energy_metrics）
- 设备实时状态（get_device_live_status）
- 每日趋势聚合（query_daily_energy_summary）
- COP 能效比计算（calculate_system_cop）
- 异常检测（detect_energy_anomalies）
- 渲染图表（render_ui_component）
- 自我纠错：工具调用失败时能识别错误原因并重试

严禁：自己做加减乘除；查询不在白名单的建筑；跨越权限。
"""
from __future__ import annotations

import json
import logging
from typing import Any

from langchain_core.messages import AIMessage, ToolMessage
from langchain_core.tools import StructuredTool
from langchain_openai import ChatOpenAI
from langgraph.prebuilt import create_react_agent
from pydantic import BaseModel

from app.core.config import get_settings
from app.db.session import AsyncSessionLocal
from app.graph.state import AgentState
from app.mcp.server import call_tool
from app.schemas.mcp_schemas import (
    CalculateSystemCOPInput,
    CompareMetricAcrossBuildingsInput,
    CompareTimePeriodsInput,
    DetectEnergyAnomaliesInput,
    GetDeviceLiveStatusInput,
    QueryDailyEnergySummaryInput,
    QueryEnergyMetricsInput,
    RenderUIComponentInput,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# System Prompt — 数据分析师
# ---------------------------------------------------------------------------
DATA_AGENT_SYSTEM_PROMPT = """你是一个楼宇能耗管理系统的数据分析师（Data Agent）。
你拥有只读数据库权限，负责所有数据查询、统计分析和图表生成工作。

## 你的专属工具（严格按此列表调用，不允许猜测工具名称）
1. list_available_buildings — 列出当前数据库所有楼宇（无需参数）。不确定 building_id 时必须先调此工具
2. query_energy_metrics — 查询指定建筑、时间段、指标的原始时序数据
3. get_device_live_status — 获取设备最新实时状态快照
4. query_daily_energy_summary — 查询能耗趋势，支持 granularity=day/week/month（按天/周/月聚合）
5. calculate_system_cop — 计算空调系统能效比（严禁自己算）
6. detect_energy_anomalies — 基于规则检测能耗异常
7. compare_metric_across_buildings — 多栋楼同一指标横向对比（含能耗强度 kWh/㎡），building_ids 传空则对比全部楼宇
8. compare_time_periods — 同环比分析：period_a（当期）vs period_b（基期），返回变化量和变化率
9. render_ui_component — 生成图表/卡片的前端渲染指令（当数据需要可视化时必须调用）

## 建筑 ID 说明
- building_id 使用 building_type 值，如 'Education'、'Office'、'Public'
- 如不确定当前系统有哪些楼宇，先调 list_available_buildings 获取最新列表
- 禁止使用数据库内部 building_id（如 'Bobcat_office_Kassandra'），统一使用 building_type

## 数据时间范围说明
- 数据库中最早有效数据约为 2016-04-01，最新数据约为 2016-05-02
- 用户未指定时间时，默认使用 2016-04-01 ~ 2016-05-02 作为查询范围
- 禁止使用 2024/2025/2026 等未来日期（数据库无该区间数据）

## 工作规范
1. 先调用工具获取真实数据，再组织自然语言回答
2. 每条结论必须附上数据来源（表名、设备ID、时间范围）
3. 查询结果有数值时，必须调用 render_ui_component 生成图表
4. 工具返回 error 字段时，分析原因并修正参数后重试（最多 2 次）
5. 如果数据确实不存在，如实告知，不要编造数字

## 自我纠错示例
- 工具报错 "building_id 无效" → 检查白名单，使用正确的 building_id 重试
- 工具报错 "时间格式错误" → 将时间转换为 ISO 8601 格式重试
- 工具报错 "结果为空" → 尝试扩大时间范围或换用 query_daily_energy_summary

## 禁止事项
- 禁止自行计算 COP、总耗电量等数学运算（必须调用工具）
- 禁止输出未经工具验证的数据数字
- 禁止查询白名单外的建筑"""


# ---------------------------------------------------------------------------
# 将 MCP call_tool 包装为 LangChain StructuredTool
# ---------------------------------------------------------------------------
def _make_mcp_tool(
    tool_name: str,
    description: str,
    args_schema: type[BaseModel] | None = None,
) -> StructuredTool:
    """
    将 MCP server 中的工具包装为 LangChain StructuredTool。
    args_schema 提供给 LLM 使用，确保参数名直接展开，而非包裹在 kwargs 键内。
    每次调用自动创建并关闭 AsyncSession，确保 DB session 正确注入。
    """
    async def _invoke(**kwargs: Any) -> str:
        # 兼容：LangChain 有时将所有参数包在单个 'kwargs' 键里
        if set(kwargs.keys()) == {"kwargs"} and isinstance(kwargs.get("kwargs"), dict):
            kwargs = kwargs["kwargs"]
        async with AsyncSessionLocal() as session:
            result = await call_tool(tool_name, kwargs, session=session)
        if isinstance(result, dict):
            return json.dumps(result, ensure_ascii=False, default=str)
        if hasattr(result, "model_dump"):
            return json.dumps(result.model_dump(), ensure_ascii=False, default=str)
        return str(result)

    return StructuredTool.from_function(
        coroutine=_invoke,
        name=tool_name,
        description=description,
        args_schema=args_schema,
    )


DATA_AGENT_TOOLS = [
    _make_mcp_tool(
        "list_available_buildings",
        "列出数据库中所有楼宇（building_type, meter_device_id, sqm）。无需任何参数，直接调用即可。",
    ),
    _make_mcp_tool(
        "query_energy_metrics",
        "查询指定建筑在时间范围内的能耗指标时序数据。"
        "默认时间范围：2016-04-01 ~ 2016-05-02。"
        "metrics 枚举值: electricity_kwh/water_m3/hvac_energy_kwh/"
        "hvac_supply_temp_c/hvac_return_temp_c/ambient_temp_c/humidity_rh_pct/occupancy_density_per_100sqm",
        args_schema=QueryEnergyMetricsInput,
    ),
    _make_mcp_tool(
        "get_device_live_status",
        "获取设备最新实时状态（operation_status, ambient_temp_c 等）。",
        args_schema=GetDeviceLiveStatusInput,
    ),
    _make_mcp_tool(
        "query_daily_energy_summary",
        "查询按天汇总的能耗趋势（从物化视图，毫秒级响应）。默认时间范围：2016-04-01 ~ 2016-05-02。",
        args_schema=QueryDailyEnergySummaryInput,
    ),
    _make_mcp_tool(
        "calculate_system_cop",
        "计算指定建筑空调系统的能效比 COP 并与 ASHRAE 90.1 基准对比。默认时间范围：2016-04-01 ~ 2016-05-02。",
        args_schema=CalculateSystemCOPInput,
    ),
    _make_mcp_tool(
        "detect_energy_anomalies",
        "基于物理规则检测能耗异常（夜间高功率/零人高耗/传感器尖刺）。默认时间范围：2016-04-01 ~ 2016-05-02。",
        args_schema=DetectEnergyAnomaliesInput,
    ),
    _make_mcp_tool(
        "compare_metric_across_buildings",
        "多栋楼同一指标横向聚合对比，支持 avg/sum/max/min。"
        "适合'哪栋楼用电最多'、'A楼B楼湿度差'等跨楼问题。"
        "building_ids 传空列表则对比所有楼宇。默认时间范围：2016-04-01 ~ 2016-05-02。",
        args_schema=CompareMetricAcrossBuildingsInput,
    ),
    _make_mcp_tool(
        "compare_time_periods",
        "同环比分析：对同一建筑、同一指标在两段时间之间做对比，返回变化量和变化率(%)。"
        "适合'本周vs上周'、'4月vs3月'等时间对比问题。默认时间范围在 2016-04 ~ 2016-05 内。",
        args_schema=CompareTimePeriodsInput,
    ),
    _make_mcp_tool(
        "render_ui_component",
        "生成前端图表/卡片渲染指令（LineChart/BarChart/Gauge/WorkOrderCard）。",
        args_schema=RenderUIComponentInput,
    ),
]


def _build_data_agent():
    """构建 Data Agent（LangGraph 内置 ReAct）。"""
    settings = get_settings()
    llm = ChatOpenAI(
        model=settings.LLM_MODEL,
        api_key=settings.LLM_API_KEY or "placeholder",
        base_url=settings.LLM_BASE_URL,
        temperature=0.1,
        max_tokens=2048,
    )
    return create_react_agent(
        llm,
        tools=DATA_AGENT_TOOLS,
        prompt=DATA_AGENT_SYSTEM_PROMPT,
    )


async def data_agent_node(state: AgentState) -> dict[str, Any]:
    """
    LangGraph 节点函数：Data Agent。

    使用 LangGraph 内置的 create_react_agent 运行 ReAct 循环，
    将结果合并回全局状态。
    """
    hop_count = state.get("hop_count", 0) + 1
    agent = _build_data_agent()

    # 传入当前完整消息历史
    sub_state = {"messages": state.get("messages", [])}

    try:
        result = await agent.ainvoke(sub_state)
    except Exception as exc:
        logger.error("Data Agent 执行失败: %s", exc)
        error_msg = AIMessage(
            content=f"数据分析师遇到了问题：{exc}。请检查查询参数后重试。"
        )
        return {
            "messages": [error_msg],
            "current_agent": "end",
            "hop_count": hop_count,
            "error": str(exc),
        }

    # 从 ReAct agent 结果中提取新增消息（去掉已有的历史部分）
    all_messages = result.get("messages", [])
    existing_count = len(state.get("messages", []))
    new_messages = all_messages[existing_count:]

    # 提取图表 artifacts（ToolMessage 中 render_ui_component 的返回值）
    artifacts = list(state.get("artifacts", []))
    for msg in new_messages:
        if isinstance(msg, ToolMessage) and "component_type" in (msg.content or ""):
            try:
                artifact_data = json.loads(msg.content)
                artifacts.append(artifact_data)
            except (json.JSONDecodeError, TypeError):
                pass

    return {
        "messages": new_messages,
        "current_agent": "end",
        "hop_count": hop_count,
        "artifacts": artifacts,
    }
