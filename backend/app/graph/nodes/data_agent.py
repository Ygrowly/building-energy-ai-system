"""
Data Agent（数据分析师）—— 两阶段架构 v2。

Phase 1 (data_react_node):
  ReAct 循环调用工具收集数据，不生成详细分析文本。
  运行 viz_engine 生成图表 + chart_manifest。

Phase 2 (data_synthesis_node):
  Synthesis LLM 看到 工具结果摘要 + 图表清单 → 生成精准分析文字。
  文字中的锚点关键词与图表完美对齐。

严禁：自己做加减乘除；查询不在白名单的建筑；跨越权限。
"""
from __future__ import annotations

import json
import logging
import time
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import StructuredTool
from langchain_openai import ChatOpenAI
from langgraph.prebuilt import create_react_agent
from pydantic import BaseModel

from app.core.config import get_settings
from app.db.session import AsyncSessionLocal
from app.graph.state import AgentState, update_context_summary
from app.graph.evidence import extract_evidence
from app.schemas.mcp_schemas import MCPError
from app.mcp.server import call_tool
from app.schemas.mcp_schemas import (
    CalculateSystemCOPInput,
    CompareMetricAcrossBuildingsInput,
    CompareTimePeriodsInput,
    DetectEnergyAnomaliesInput,
    ForecastKPIInput,
    GenerateReportInput,
    GetDeviceLiveStatusInput,
    QueryDailyEnergySummaryInput,
    QueryEnergyMetricsInput,
    RenderUIComponentInput,
)
from app.graph.viz_engine import generate_viz_artifacts, build_chart_manifest, build_data_summary

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# System Prompt — ReAct 阶段（只做工具调用 + 简要摘要）
# ---------------------------------------------------------------------------
DATA_AGENT_SYSTEM_PROMPT = """你是一个楼宇能耗管理系统的数据分析师（Data Agent）。
你拥有只读数据库权限，负责所有数据查询、统计分析和图表生成工作。

## 你的专属工具（严格按此列表调用，不允许猜测工具名称）
1. list_available_buildings — 列出全部楼宇。**仅当上下文未提供楼宇列表时才调用**
2. query_energy_metrics — 查询指定建筑、时间段、指标的原始时序数据（小时级）
3. get_device_live_status — 查询楼宇下所有设备实时状态
4. query_daily_energy_summary — 查询单栋楼按天汇总的能耗趋势（含用电、用水、空调三个指标）
5. calculate_system_cop — 计算空调系统能效比（严禁自己算）
6. detect_energy_anomalies — 基于规则检测能耗异常
7. compare_metric_across_buildings — 多栋楼同一指标横向汇总对比，building_ids 传空则自动对比全部楼宇
8. compare_time_periods — 同环比分析（当期 vs 基期），返回变化量和变化率
9. render_ui_component — 生成前端图表/卡片渲染指令（有数值结果时必须调用）
10. generate_report — 生成 CSV 报表下载链接，用户要求"导出/生成报表"时调用

## 建筑 ID 说明
- building_id 使用 building_type 值：'Education'、'Office'、'Public services'
- **上下文已提供楼宇列表时，直接使用，禁止再调用 list_available_buildings**

## 数据时间范围
- 数据库有效数据：2016-04-01 ~ 2016-05-02
- 用户未指定时间时，优先使用上下文中的时间范围，否则默认 2016-04-01 ~ 2016-05-02
- 禁止使用 2024/2025/2026 等数据库中不存在的日期

## 工具选择指南
| 场景 | 首选工具 |
|------|---------|
| 多楼横向总量/均值对比 | compare_metric_across_buildings |
| 单楼日趋势 | query_daily_energy_summary |
| 多楼日趋势对比 | 对每栋楼各调一次 query_daily_energy_summary |
| 原始小时数据 | query_energy_metrics |
| 故障/异常分析 | detect_energy_anomalies |
| 预测未来能耗/预测异常 | building_kpi_forecast_6h_12h |

## 效率规范（重要）
- **完成一个任务的工具调用次数通常不超过 5 次**（查询 + 渲染），超过说明选错了工具
- 开始前先制定查询计划，每种数据只查一次，不重复调用相同工具
- 多楼数据渲染时，把所有系列合并进一个 render_ui_component 调用

## 工作规范
1. 先调工具获取真实数据，再组织自然语言回答
2. 有数值结果时，必须调用 render_ui_component 可视化
3. 工具报错时，分析原因并修正参数后最多重试 2 次
4. 数据确实不存在时，如实说明，不要编造

## render_ui_component 的 data_payload 格式规范（严格遵守）

**LineChart / BarChart（折线图/柱状图）**：
```json
{
  "series": [
    {
      "name": "教学楼",
      "data": [1500.0, 1480.0, 1620.0],
      "timestamps": ["2016-04-01", "2016-04-02", "2016-04-03"]
    },
    {
      "name": "办公楼",
      "data": [980.0, 1020.0, 950.0],
      "timestamps": ["2016-04-01", "2016-04-02", "2016-04-03"]
    }
  ]
}
```
关键约束：
- `data` 字段必须是**纯数字数组**（float），不能是对象或字符串
- `timestamps` 是与 `data` 等长的日期字符串列表，格式 "YYYY-MM-DD"
- 每个楼宇一个 series 对象，多楼宇合并进同一次 render_ui_component 调用

**Gauge（仪表盘）**：`{"value": 3.5}`

## 禁止事项
- 禁止自行计算 COP、总耗电量等（必须调工具）
- 禁止输出未经工具返回的数字
- 禁止查询白名单外的建筑
- 禁止冗余重复的工具调用
- 禁止在 data_payload 的 data 字段中放对象（必须是数字）"""

DATA_REACT_PROMPT = DATA_AGENT_SYSTEM_PROMPT


# ---------------------------------------------------------------------------
# 将 MCP call_tool 包装为 LangChain StructuredTool
# ---------------------------------------------------------------------------
def _make_mcp_tool(
    tool_name: str,
    description: str,
    args_schema: type[BaseModel] | None = None,
) -> StructuredTool:
    async def _invoke(**kwargs: Any) -> str:
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
        "计算指定建筑空调系统的能效比 COP 并与 GB 50189-2015 国标基准对比。默认时间范围：2016-04-01 ~ 2016-05-02。",
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
        "生成前端图表/卡片渲染指令（LineChart/BarChart/Gauge/WorkOrderCard/ReportDownload）。",
        args_schema=RenderUIComponentInput,
    ),
    _make_mcp_tool(
        "generate_report",
        "生成统计报表 CSV 下载链接。用户说'生成报表'/'导出数据'时调用。"
        "返回下载 URL，前端渲染为下载按钮。默认时间范围：2016-04-01 ~ 2016-05-02。",
        args_schema=GenerateReportInput,
    ),
    _make_mcp_tool(
        "building_kpi_forecast_6h_12h",
        "基于 ML 模型预测楼宇未来第 6、12 小时的 5 项 KPI"
        "（水耗 water_l、电耗 electricity_kwh、供水温度、回水温度、空调能耗），"
        "并与国标基线对比生成预测预警。"
        "适用：'未来6小时会不会超标'、'预测一下办公楼接下来的用电'。",
        args_schema=ForecastKPIInput,
    ),
]


# ---------------------------------------------------------------------------
# ReAct Agent 缓存
# ---------------------------------------------------------------------------
_cached_react_agent_full = None
_cached_react_agent_no_list = None
_react_agent_lock: Any = None


def _get_react_agent_lock() -> Any:
    import threading
    global _react_agent_lock
    if _react_agent_lock is None:
        _react_agent_lock = threading.Lock()
    return _react_agent_lock


def reset_data_agent_cache() -> None:
    """Reset cached Agent instances (used by eval/tests)."""
    global _cached_react_agent_full, _cached_react_agent_no_list, _react_agent_lock
    _cached_react_agent_full = None
    _cached_react_agent_no_list = None
    _react_agent_lock = None


_MAX_HISTORY_MESSAGES = 8


def _get_react_agent(include_list_available_buildings: bool):
    """获取 ReAct Agent 单例。max_tokens 降低到 500，只做工具选择 + 简要确认。"""
    global _cached_react_agent_full, _cached_react_agent_no_list
    with _get_react_agent_lock():
        if include_list_available_buildings:
            if _cached_react_agent_full is not None:
                return _cached_react_agent_full
            settings = get_settings()
            llm = ChatOpenAI(
                model=settings.LLM_MODEL_REACT or settings.LLM_MODEL,
                api_key=settings.LLM_API_KEY or "placeholder",
                base_url=settings.LLM_BASE_URL,
                temperature=0.1,
                max_tokens=1500,   # 降低：减少单次 LLM 调用的生成量
            )
            _cached_react_agent_full = create_react_agent(
                llm, tools=DATA_AGENT_TOOLS, prompt=DATA_REACT_PROMPT,
            )
            return _cached_react_agent_full

        if _cached_react_agent_no_list is not None:
            return _cached_react_agent_no_list

        settings = get_settings()
        llm = ChatOpenAI(
            model=settings.LLM_MODEL_REACT or settings.LLM_MODEL,
            api_key=settings.LLM_API_KEY or "placeholder",
            base_url=settings.LLM_BASE_URL,
            temperature=0.1,
            max_tokens=1500,   # 降低：减少单次 LLM 调用的生成量
        )
        tools_wo_list = [t for t in DATA_AGENT_TOOLS if getattr(t, "name", "") != "list_available_buildings"]
        _cached_react_agent_no_list = create_react_agent(
            llm, tools=tools_wo_list, prompt=DATA_REACT_PROMPT,
        )
        return _cached_data_agent_no_list_buildings
    # 理论上不会到达：两种分支里都有 return。这里放一个兜底，避免异常情况下返回 None。
    return _cached_data_agent_full if include_list_available_buildings else _cached_data_agent_no_list_buildings


async def data_react_node(state: AgentState) -> dict[str, Any]:
    """
    LangGraph 节点函数：Data Agent。

    优化要点：
    1. 把路由器提取的楼宇列表/时间范围/目标楼宇注入为 SystemMessage，
       避免 agent 浪费工具调用去"发现"已知信息。
    2. 限制传入的历史消息数量，防止 token 随对话增长而膨胀。
    3. 记录耗时以便性能诊断。
    """
    t0 = time.time()
    hop_count = state.get("hop_count", 0) + 1

    # 预取楼宇列表
    available = state.get("available_buildings")
    if not available:
        try:
            async with AsyncSessionLocal() as session:
                res = await call_tool("list_available_buildings", {}, session=session)
            if not isinstance(res, MCPError):
                fetched = [b.building_type for b in (res.buildings or []) if b.building_type]
                if fetched:
                    available = fetched
                    state["available_buildings"] = fetched
        except Exception as exc:
            logger.warning("prefetch available_buildings 失败: %s", exc)

    from app.core.data_range import get_data_range
    dr = await get_data_range()

    context_parts: list[str] = []

    context_parts.append(
        f"【数据有效时间范围】: {dr.get('min_date', '未知')} ~ {dr.get('max_date', '未知')}，"
        f"默认查询范围: {dr.get('default_start', '未知')} ~ {dr.get('default_end', '未知')}"
    )

    existing_summary = state.get("context_summary", "")
    if existing_summary:
        context_parts.append(f"【历史对话摘要（仅供参考，无需重复查询）】\n{existing_summary}")

    available = state.get("available_buildings")
    if available:
        context_parts.append(
            f"【可用楼宇（直接使用，无需调用 list_available_buildings）】: "
            f"{', '.join(available)}"
        )
    if state.get("building_id"):
        context_parts.append(f"【目标楼宇】: {state['building_id']}")
    tc = state.get("time_context")
    if isinstance(tc, dict):
        start = tc.get("start") or dr.get("default_start", "")
        end   = tc.get("end")   or dr.get("default_end", "")
        if start and end:
            context_parts.append(f"【查询时间范围】: {start} ~ {end}")

    # ── 全局 messages 已只含 Human + 最终 AI（干净紧凑），取最近 N 条 ──
    history = state.get("messages", [])
    recent = history[-_MAX_HISTORY_MESSAGES:] if len(history) > _MAX_HISTORY_MESSAGES else history

    if context_parts:
        ctx_msg = SystemMessage(
            content="路由层提取的上下文（直接使用，无需重复工具调用）：\n"
                    + "\n".join(context_parts)
        )
        sub_messages = [ctx_msg] + list(recent)
    else:
        sub_messages = list(recent)

    # 在进入 ReAct 前决定工具集合
    include_list = not bool(state.get("available_buildings"))
    agent = _get_react_agent(include_list_available_buildings=include_list)

    injected_count = len(sub_messages)
    sub_state = {"messages": sub_messages}

    try:
        result = await agent.ainvoke(sub_state, config={"recursion_limit": 12})
    except Exception as exc:
        logger.error("Data Agent ReAct 执行失败: %s", exc)
        error_msg = AIMessage(
            content=f"数据分析师遇到了问题：{exc}。请检查查询参数后重试。"
        )
        return {
            "messages": [error_msg],
            "current_agent": "end",
            "hop_count": hop_count,
            "error": str(exc),
        }

    all_messages = result.get("messages", [])
    new_messages = all_messages[injected_count:]


    # 提取 evidence
    artifacts = list(state.get("artifacts", []))
    evidence = list(state.get("evidence", []))
    for msg in new_messages:
        if not isinstance(msg, ToolMessage):
            continue
        try:
            payload = json.loads(msg.content or "")
        except (json.JSONDecodeError, TypeError):
            continue
        if isinstance(payload, dict):
            evidence.extend(extract_evidence(payload))

    user_q = next(
        (str(m.content) for m in reversed(list(history)) if isinstance(m, HumanMessage)),
        "",
    )

    # viz_engine: 生成图表
    viz_artifacts = generate_viz_artifacts(new_messages, user_question=user_q)
    artifacts.extend(viz_artifacts)

    # ★ 构建 chart_manifest（供 Synthesis LLM）
    chart_manifest = build_chart_manifest(viz_artifacts)

    # ★ 构建数据摘要（供 Synthesis LLM）
    data_summary = build_data_summary(new_messages)

    tool_count = sum(1 for m in new_messages if isinstance(m, ToolMessage))
    logger.info(
        "Data Agent ReAct 完成: 工具调用=%d 图表=%d 用时=%.1fs",
        tool_count, len(viz_artifacts), time.time() - t0,
    )

    return {
        "messages": [],
        "current_agent": "data_agent",
        "hop_count": hop_count,
        "artifacts": artifacts,
        "evidence": evidence,
        "chart_manifest": chart_manifest,
        "react_data_summary": data_summary,
    }


# ---------------------------------------------------------------------------
# System Prompt — Synthesis 阶段（看到图表清单 → 写精准分析）
# ---------------------------------------------------------------------------
SYNTHESIS_PROMPT = """你是一个楼宇能耗管理系统的高级数据分析师。
系统已经帮你查询了数据并生成了可视化图表，现在请你撰写完整的分析报告。

{chart_manifest}

## 写作规则

### 图表占位符（最重要！必须严格遵守）
- 对于图表清单中的每一张图表，你**必须**在分析该图表的段落**结尾**单独一行插入占位符
- 占位符格式：`<<CHART:锚点关键词>>`（锚点关键词来自图表清单）
- 示例：如果有锚点为"用电"的图表，则写：
  ```
  从用电趋势图可以看出，教学楼日均用电量最高...

  <<CHART:用电>>
  ```
- 先写该图表的文字分析，分析结束后紧跟占位符，这样图表出现在分析文字下方
- 每个图表的占位符**只能出现一次**
- 占位符必须独占一行，前后各空一行
- 总结段落**不要**放任何占位符

### 内容质量
- 先给结论，再展开数据支撑
- 使用中文建筑名称：教学楼、办公楼、公共楼
- 引用具体数值（从数据摘要中获取）
- 可以用"从趋势图可以看出""如图所示"等措辞引用图表
- 若某指标未生成图表，仅用文字和数据说明，不要提及不存在的图表
- 注意数据的时间粒度（日/周/月），使用正确的时间单位描述
  - 数据摘要中标注了"X条日级/周级/月级数据"，请据此选择描述方式
  - 月级数据说"X月份"而非"X天"，周级数据说"第X周"而非"X天"

### 格式
- 使用 Markdown 格式：标题(###)、加粗(**重点**)、有序/无序列表
- 段落之间用空行分隔
- 总字数控制在 300-800 字

## 建筑中文名映射
| building_type | 中文名 |
|--------------|--------|
| Education | 教学楼 |
| Office | 办公楼 |
| Public services | 公共楼 |"""


# ---------------------------------------------------------------------------
# Phase 2: data_synthesis_node — Synthesis LLM 生成精准分析
# ---------------------------------------------------------------------------
_cached_synthesis_llm_fast: ChatOpenAI | None = None
_cached_synthesis_llm_deep: ChatOpenAI | None = None
_synthesis_llm_lock: Any = None


def _get_synthesis_llm_lock() -> Any:
    import threading
    global _synthesis_llm_lock
    if _synthesis_llm_lock is None:
        _synthesis_llm_lock = threading.Lock()
    return _synthesis_llm_lock


def _get_synthesis_llm(thinking_mode: str = "fast") -> ChatOpenAI:
    """获取 Synthesis LLM（fast / deep 各缓存一份）。"""
    global _cached_synthesis_llm_fast, _cached_synthesis_llm_deep
    with _get_synthesis_llm_lock():
        settings = get_settings()
        if thinking_mode == "deep" and settings.LLM_MODEL_DEEP:
            if _cached_synthesis_llm_deep is not None:
                return _cached_synthesis_llm_deep
            _cached_synthesis_llm_deep = ChatOpenAI(
                model=settings.LLM_MODEL_DEEP,
                api_key=settings.LLM_API_KEY or "placeholder",
                base_url=settings.LLM_BASE_URL,
                temperature=0.3,
                max_tokens=3000,
                streaming=True,
            )
            return _cached_synthesis_llm_deep
        else:
            if _cached_synthesis_llm_fast is not None:
                return _cached_synthesis_llm_fast
            _cached_synthesis_llm_fast = ChatOpenAI(
                model=settings.LLM_MODEL_SYNTHESIS or settings.LLM_MODEL,
                api_key=settings.LLM_API_KEY or "placeholder",
                base_url=settings.LLM_BASE_URL,
                temperature=0.3,
                max_tokens=2000,
                streaming=True,
            )
            return _cached_synthesis_llm_fast


async def data_synthesis_node(state: AgentState) -> dict[str, Any]:
    """
    Phase 2: 基于 chart_manifest + 数据摘要生成精准分析文字。
    文字中的锚点关键词与图表完美对齐。
    """
    t0 = time.time()

    # 如果 ReAct 阶段出错（messages 中有 error AIMessage），直接结束
    recent_msgs = state.get("messages", [])
    if recent_msgs and isinstance(recent_msgs[-1], AIMessage) and state.get("error"):
        return {"current_agent": "end"}

    chart_manifest = state.get("chart_manifest", "")
    data_summary = state.get("react_data_summary", "")

    # 提取用户问题
    history = state.get("messages", [])
    user_q = next(
        (str(m.content) for m in reversed(list(history)) if isinstance(m, HumanMessage)),
        "",
    )

    # 构建 Synthesis 消息
    system_content = SYNTHESIS_PROMPT.format(chart_manifest=chart_manifest)
    messages = [
        SystemMessage(content=system_content),
        HumanMessage(content=f"用户问题：{user_q}\n\n{data_summary}"),
    ]

    thinking_mode = state.get("thinking_mode", "fast")
    llm = _get_synthesis_llm(thinking_mode)

    try:
        response = await llm.ainvoke(messages)
        answer_text = response.content if isinstance(response.content, str) else str(response.content)
    except Exception as exc:
        logger.error("Synthesis LLM 执行失败: %s", exc)
        answer_text = f"数据分析完成，但生成分析报告时遇到问题：{exc}"

    elapsed = time.time() - t0
    logger.info("Data Synthesis 完成: mode=%s 用时=%.1fs 字数=%d", thinking_mode, elapsed, len(answer_text))

    # 更新滚动摘要
    existing_summary = state.get("context_summary", "")
    new_summary = update_context_summary(
        existing_summary, state.get("intent"), user_q, answer_text,
    )

    return {
        "messages": [AIMessage(content=answer_text)],
        "current_agent": "end",
        "context_summary": new_summary,
    }
