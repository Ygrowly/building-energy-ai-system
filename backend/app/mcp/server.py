"""
MCP 工具注册中心
================
将 8 个原子工具统一注册，提供单一调用入口 call_tool()。

设计约定：
  · 调用时传入 tool_name（字符串）+ args_dict（未验证的 dict）
  · 注册中心负责 Pydantic 参数校验；校验失败返回 MCPError（不抛异常）
  · 需要 DB session 的工具在 session 参数传入；纯逻辑工具 session=None
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas.mcp_schemas import MCPError

# 工具函数导入
from app.mcp.tools.data_query import (
    compare_metric_across_buildings,
    compare_time_periods,
    get_device_live_status,
    list_available_buildings,
    query_daily_energy_summary,
    query_energy_metrics,
)
from app.mcp.tools.physics_calc import (
    calculate_system_cop,
    detect_energy_anomalies,
    get_building_rated_values,
)
from app.mcp.tools.ui_render import (
    create_work_order_draft,
    generate_report,
    render_ui_component,
)
from app.mcp.tools.rag_search import rag_hybrid_search

# Schema 导入（用于参数校验）
from app.schemas.mcp_schemas import (
    CalculateSystemCOPInput,
    CompareMetricAcrossBuildingsInput,
    CompareTimePeriodsInput,
    CreateWorkOrderDraftInput,
    DetectEnergyAnomaliesInput,
    GenerateReportInput,
    GetBuildingRatedValuesInput,
    GetDeviceLiveStatusInput,
    QueryDailyEnergySummaryInput,
    QueryEnergyMetricsInput,
    RAGHybridSearchInput,
    RenderUIComponentInput,
)


@dataclass
class ToolDefinition:
    name: str
    description: str
    input_schema: type        # Pydantic BaseModel 子类
    requires_db: bool         # 是否需要注入 AsyncSession
    func: Callable


# ---------------------------------------------------------------------------
# 工具注册表
# ---------------------------------------------------------------------------

_REGISTRY: dict[str, ToolDefinition] = {}


def _register(defn: ToolDefinition) -> None:
    _REGISTRY[defn.name] = defn


_register(ToolDefinition(
    name="query_energy_metrics",
    description="查询指定建筑、时间段、指标的能耗时序原始读数（直查 energy_data 表）",
    input_schema=QueryEnergyMetricsInput,
    requires_db=True,
    func=query_energy_metrics,
))

_register(ToolDefinition(
    name="get_device_live_status",
    description="通过 meter_device_id 获取设备最新 1 条传感器快照",
    input_schema=GetDeviceLiveStatusInput,
    requires_db=True,
    func=get_device_live_status,
))

_register(ToolDefinition(
    name="calculate_system_cop",
    description=(
        "估算指定建筑指定时段的空调能效代理指标（COP proxy），"
        "与 GB 50189-2015 国标基准对比（制冷季 COP=3.5 / 供暖季 COP=2.5）。"
        "输出 hvac_mode（Cooling/Heating/Mixed）帮助选取对应国标基准。"
    ),
    input_schema=CalculateSystemCOPInput,
    requires_db=True,
    func=calculate_system_cop,
))

_register(ToolDefinition(
    name="get_building_rated_values",
    description=(
        "查询指定建筑在时间段内每小时的国标（GB）期望值，并与数据库实际值并排返回。"
        "输出包含 rated_water/rated_electricity/rated_hac_energy（期望）与 actual_*（实际）的逐小时对比，"
        "以及 water/electricity/hac 三项偏差百分比。"
        "适用场景：解释异常原因（'期望是多少，实际是多少'），或为前端渲染'实际 vs 期望'对比折线图提供数据。"
        "建议时间范围不超过 7 天（168 条）。"
    ),
    input_schema=GetBuildingRatedValuesInput,
    requires_db=True,
    func=get_building_rated_values,
))

_register(ToolDefinition(
    name="query_daily_energy_summary",
    description="查询物化视图 daily_energy_summary，获取按天汇总的能耗趋势数据",
    input_schema=QueryDailyEnergySummaryInput,
    requires_db=True,
    func=query_daily_energy_summary,
))

_register(ToolDefinition(
    name="rag_hybrid_search",
    description="调用 RAGFlow 混合检索运维手册，支持设备 ID 元数据过滤 + 语义重排序",
    input_schema=RAGHybridSearchInput,
    requires_db=False,
    func=rag_hybrid_search,
))

_register(ToolDefinition(
    name="detect_energy_anomalies",
    description=(
        "基于国标（GB）双阈值物理规则检测能耗异常，并对空调异常自动给出根因诊断。"
        "规则：water_leak（水耗偏差>20%且>1m³）/ electricity_overload（电耗偏差>15%）/ "
        "hvac_overconsumption（空调偏差>20%且>20kWh）/ db_flagged（原始标注兜底）。"
        "空调异常时输出 hvac_root_cause：A_low_efficiency（主机效能衰退）/ "
        "B_small_deltaT（水力失调/大流量小温差）/ C_unexpected_on（排程失效/非预期开机）。"
    ),
    input_schema=DetectEnergyAnomaliesInput,
    requires_db=True,
    func=detect_energy_anomalies,
))

_register(ToolDefinition(
    name="render_ui_component",
    description="生成 Generative UI 渲染指令，通知前端渲染图表或工单卡片",
    input_schema=RenderUIComponentInput,
    requires_db=False,
    func=render_ui_component,
))

_register(ToolDefinition(
    name="create_work_order_draft",
    description="生成待审批维修工单草稿（Human-in-the-loop，不写生产 DB）",
    input_schema=CreateWorkOrderDraftInput,
    requires_db=False,
    func=create_work_order_draft,
))

_register(ToolDefinition(
    name="list_available_buildings",
    description="列出数据库中所有楼宇的 building_type、meter_device_id 和面积。"
                "不确定有哪些合法 building_id 时先调此工具，再传参给其他工具。",
    input_schema=None,          # 无入参，特殊处理
    requires_db=True,
    func=list_available_buildings,
))

_register(ToolDefinition(
    name="compare_metric_across_buildings",
    description="对多栋楼在同一时段内的同一指标进行横向聚合对比（avg/sum/max/min），"
                "结果含能耗强度（kWh/㎡，仅 metric=electricity_kwh 时）。"
                "适合回答'哪栋楼用电最多'、'A楼和B楼湿度差值'等跨楼问题。"
                "building_ids 传空列表则对比所有楼宇。",
    input_schema=CompareMetricAcrossBuildingsInput,
    requires_db=True,
    func=compare_metric_across_buildings,
))

_register(ToolDefinition(
    name="compare_time_periods",
    description="对同一建筑、同一指标在两个时间段之间做同环比分析，"
                "返回当期值、基期值、绝对差值和相对变化率（%）。"
                "适合回答'本周 vs 上周用电对比'、'4月 vs 3月平均湿度变化'等时间段对比问题。",
    input_schema=CompareTimePeriodsInput,
    requires_db=True,
    func=compare_time_periods,
))

_register(ToolDefinition(
    name="generate_report",
    description="生成统计报表（CSV 下载链接），支持 daily_summary（每日汇总）和 energy_detail（原始明细）。"
                "当用户要求'生成报表'、'导出数据'时调用此工具，返回下载链接供前端渲染下载按钮。",
    input_schema=GenerateReportInput,
    requires_db=False,
    func=generate_report,
))


# ---------------------------------------------------------------------------
# 统一调用入口
# ---------------------------------------------------------------------------

def list_tools() -> list[dict[str, Any]]:
    """返回所有已注册工具的元信息（供 LLM System Prompt 使用）。"""
    return [
        {
            "name": t.name,
            "description": t.description,
            "requires_db": t.requires_db,
        }
        for t in _REGISTRY.values()
    ]


async def call_tool(
    tool_name: str,
    args_dict: dict[str, Any],
    session: AsyncSession | None = None,
) -> Any:
    """
    统一工具调用入口。
    返回值：工具的 Output Schema 实例，或 MCPError（参数校验失败 / 业务异常）。
    调用方无需 try/except，所有错误已被封装为 MCPError。
    """
    defn = _REGISTRY.get(tool_name)
    if defn is None:
        return MCPError(
            error=f"工具 '{tool_name}' 不存在，可用工具：{list(_REGISTRY.keys())}",
            error_code="TOOL_NOT_FOUND",
            tool_name=tool_name,
        )

    # 无入参工具（如 list_available_buildings）直接调用，跳过 Pydantic 校验
    if defn.input_schema is None:
        if defn.requires_db:
            if session is None:
                return MCPError(
                    error=f"工具 '{tool_name}' 需要数据库连接，但 session 未注入",
                    error_code="DB_SESSION_MISSING",
                    tool_name=tool_name,
                )
            return await defn.func(session)
        return await defn.func()

    # Pydantic 参数校验（让 Agent 看懂错误并自我修正）
    try:
        inp = defn.input_schema.model_validate(args_dict)
    except Exception as exc:
        return MCPError(
            error=f"参数校验失败：{exc}",
            error_code="PARAM_VALIDATION_ERROR",
            tool_name=tool_name,
        )

    # 调用工具函数
    if defn.requires_db:
        if session is None:
            return MCPError(
                error=f"工具 '{tool_name}' 需要数据库连接，但 session 未注入",
                error_code="DB_SESSION_MISSING",
                tool_name=tool_name,
            )
        return await defn.func(inp, session)
    else:
        result = defn.func(inp)
        # rag_hybrid_search 是 async 函数
        if hasattr(result, "__await__"):
            return await result
        return result
