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

import asyncio
import logging
import time
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import StructuredTool
from langchain_openai import ChatOpenAI
from langgraph.prebuilt import create_react_agent
from pydantic import BaseModel

from app.core.config import get_settings
from app.core.data_range import get_data_range
from app.db.session import AsyncSessionLocal
from app.graph.state import AgentState, update_context_summary
from app.graph.evidence import extract_evidence
from app.graph.tool_payloads import build_tool_content_and_artifact, extract_tool_payload
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
)
from app.graph.viz_engine import generate_viz_artifacts, build_chart_manifest, build_data_summary

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# System Prompt — ReAct 阶段（只做工具调用 + 简要摘要）
# ---------------------------------------------------------------------------
_DATA_REACT_PROMPT_TEMPLATE = """你是一个楼宇能耗管理系统的数据分析师（Data Agent）。
你拥有只读数据库权限，负责通过工具调用收集数据。
**你只需要调用工具收集数据，不需要生成详细分析文本。**
分析文本会由下游 Synthesis 模块基于你收集的数据自动生成。

**当前系统日期：{today}** — 所有时间判断以此为准。

## 你的专属工具
1. list_available_buildings — 列出全部楼宇。**仅当上下文未提供楼宇列表时才调用**
2. query_energy_metrics — 查询指定建筑、时间段、指标的原始时序数据（小时级）
3. get_device_live_status — 查询楼宇下所有设备实时状态
4. query_daily_energy_summary — 查询单栋楼按天/周/月汇总的能耗趋势（含用电、用水、空调三个指标）
5. calculate_system_cop — 计算空调系统能效比（严禁自己算）
6. detect_energy_anomalies — 基于规则检测能耗异常
7. compare_metric_across_buildings — 多栋楼同一指标横向汇总对比
8. compare_time_periods — 同环比分析（当期 vs 基期）
9. generate_report — 生成 CSV 报表下载链接
10. building_kpi_forecast_6h_12h — 预测楼宇未来 6/12 小时 KPI

## 建筑 ID 说明
- building_id 使用 building_type 值：'Education'、'Office'、'Public services'
- **上下文已提供楼宇列表时，直接使用，禁止再调用 list_available_buildings**

## 数据时间范围（极其重要，必须严格遵守）
- 今天是 **{today}**，当前年份是 **{year} 年**
- **所有工具调用的日期必须来自上下文中的【查询时间范围】**，该范围已由系统自动计算
- 严禁自行编造日期，严禁使用 {year} 年以外或不在上下文范围内的日期
- 参考今天日期 {today} 判断"最近一周""上个月"等相对时间

## 粒度选择指南（query_daily_energy_summary 的 granularity 参数）
| 用户意图/时间跨度 | 推荐粒度 | 说明 |
|---|---|---|
| 某一天的详细数据 | day | 单天只有 1 条日汇总 |
| 1~2 周趋势 | day | 7~14 个数据点，适合折线图 |
| 1~3 个月趋势 | day | 30~90 个数据点，清晰展示波动 |
| 3~6 个月趋势 | week | 12~26 个数据点，避免过密 |
| 半年~1年趋势 | month | 6~12 个数据点 |
| 1年以上趋势 | month | 避免数据点过多 |
| "春季"/"夏季"等季节性分析 | day | 约 90 天，能看到季节内部波动 |
| 不确定时 | day | 默认选 day，后端会自动纠正 |

**核心原则：趋势分析至少需要 7 个数据点。如果预计数据点不足 7，降低粒度。**

## 工具选择指南
| 场景 | 首选工具 |
|------|---------|
| 多楼横向总量/均值对比 | compare_metric_across_buildings |
| 单楼日趋势 | query_daily_energy_summary |
| 多楼日趋势对比 | 对每栋楼各调一次 query_daily_energy_summary |
| 原始小时数据 | query_energy_metrics |
| 故障/异常分析 | detect_energy_anomalies |
| 预测未来能耗/预测异常 | building_kpi_forecast_6h_12h |

## 效率规范
- **完成一个任务的工具调用次数通常不超过 5 次**
- 开始前先制定查询计划，每种数据只查一次
- 多楼趋势对比：对每栋楼调用一次 query_daily_energy_summary（图表由 viz_engine 自动合并）

## 禁止事项
- 禁止自行计算 COP、总耗电量等（必须调工具）
- 禁止输出未经工具返回的数字
- 禁止查询白名单外的建筑
- 禁止冗余重复的工具调用
- 禁止生成详细分析文本（只做简要的数据确认即可）"""


# ---------------------------------------------------------------------------
# 将 MCP call_tool 包装为 LangChain StructuredTool
# ---------------------------------------------------------------------------
_TOOL_RESPONSE_MAX_CHARS = 4000


def _truncate_tool_response(text: str, max_chars: int = _TOOL_RESPONSE_MAX_CHARS) -> str:
    """截断过长的工具返回，防止 ReAct 消息历史撑爆 LLM 上下文窗口。"""
    if len(text) <= max_chars:
        return text
    half = max_chars // 2
    return (
        text[:half]
        + f"\n\n... [结果过长，已截断中间 {len(text) - max_chars} 字符] ...\n\n"
        + text[-half:]
    )


def _make_mcp_tool(
    tool_name: str,
    description: str,
    args_schema: type[BaseModel] | None = None,
) -> StructuredTool:
    async def _invoke(**kwargs: Any) -> tuple[str, Any]:
        if set(kwargs.keys()) == {"kwargs"} and isinstance(kwargs.get("kwargs"), dict):
            kwargs = kwargs["kwargs"]
        async with AsyncSessionLocal() as session:
            result = await call_tool(tool_name, kwargs, session=session)
        return build_tool_content_and_artifact(
            tool_name=tool_name,
            result=result,
            max_chars=_TOOL_RESPONSE_MAX_CHARS,
        )

    return StructuredTool.from_function(
        coroutine=_invoke,
        name=tool_name,
        description=description,
        args_schema=args_schema,
        response_format="content_and_artifact",
    )


DATA_AGENT_TOOLS = [
    _make_mcp_tool(
        "list_available_buildings",
        "列出数据库中所有楼宇（building_type, meter_device_id, sqm）。无需任何参数，直接调用即可。",
    ),
    _make_mcp_tool(
        "query_energy_metrics",
        "查询指定建筑在时间范围内的能耗指标时序数据。"
        "metrics 枚举值: electricity_kwh/water_m3/hac_energy/"
        "sim_supply_temp_c/sim_return_temp_c/air_temp_c/humidity_rh_pct",
        args_schema=QueryEnergyMetricsInput,
    ),
    _make_mcp_tool(
        "get_device_live_status",
        "获取设备最新实时状态（operation_status, ambient_temp_c 等）。",
        args_schema=GetDeviceLiveStatusInput,
    ),
    _make_mcp_tool(
        "query_daily_energy_summary",
        "查询按天/周/月汇总的能耗趋势（从物化视图，毫秒级响应）。"
        "granularity 参数: day（默认）/week/month。后端有智能粒度纠正。",
        args_schema=QueryDailyEnergySummaryInput,
    ),
    _make_mcp_tool(
        "calculate_system_cop",
        "计算指定建筑空调系统的能效比 COP 并与 GB 50189-2015 国标基准对比。",
        args_schema=CalculateSystemCOPInput,
    ),
    _make_mcp_tool(
        "detect_energy_anomalies",
        "基于物理规则检测能耗异常（水漏/电过载/空调过耗）。",
        args_schema=DetectEnergyAnomaliesInput,
    ),
    _make_mcp_tool(
        "compare_metric_across_buildings",
        "多栋楼同一指标横向聚合对比，支持 avg/sum/max/min。"
        "适合'哪栋楼用电最多'、'A楼B楼湿度差'等跨楼问题。"
        "building_ids 传空列表则对比所有楼宇。",
        args_schema=CompareMetricAcrossBuildingsInput,
    ),
    _make_mcp_tool(
        "compare_time_periods",
        "同环比分析：对同一建筑、同一指标在两段时间之间做对比，返回变化量和变化率(%)。"
        "适合'本周vs上周'、'4月vs3月'等时间对比问题。",
        args_schema=CompareTimePeriodsInput,
    ),
    _make_mcp_tool(
        "generate_report",
        "生成统计报表 CSV 下载链接。用户说'生成报表'/'导出数据'时调用。"
        "返回下载 URL，前端渲染为下载按钮。",
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
_react_agent_lock: Any = None


def _get_react_agent_lock() -> Any:
    import threading
    global _react_agent_lock
    if _react_agent_lock is None:
        _react_agent_lock = threading.Lock()
    return _react_agent_lock


def reset_data_agent_cache() -> None:
    """Reset cached Agent instances (used by eval/tests)."""
    global _react_agent_lock
    _react_agent_cache.clear()
    _react_agent_lock = None


_MAX_HISTORY_MESSAGES = 8


_react_agent_cache: dict[str, Any] = {}


def _build_data_react_prompt() -> str:
    """用当前日期填充 Prompt 模板。"""
    from app.core.time_context import get_today
    today = get_today()
    return _DATA_REACT_PROMPT_TEMPLATE.format(today=today, year=today.year)


def _get_react_agent(include_list_available_buildings: bool):
    """获取 ReAct Agent（按日期+工具集缓存，跨日自动重建）。"""
    from app.core.time_context import get_today
    cache_key = f"{include_list_available_buildings}:{get_today()}"

    with _get_react_agent_lock():
        if cache_key in _react_agent_cache:
            return _react_agent_cache[cache_key]

        settings = get_settings()
        llm = ChatOpenAI(
            model=settings.LLM_MODEL_REACT or settings.LLM_MODEL,
            api_key=settings.LLM_API_KEY or "placeholder",
            base_url=settings.LLM_BASE_URL,
            temperature=0.1,
            max_tokens=1500,
            request_timeout=60,
        )
        prompt = _build_data_react_prompt()
        if include_list_available_buildings:
            tools = DATA_AGENT_TOOLS
        else:
            tools = [t for t in DATA_AGENT_TOOLS if getattr(t, "name", "") != "list_available_buildings"]

        agent = create_react_agent(llm, tools=tools, prompt=prompt)
        _react_agent_cache[cache_key] = agent
        return agent


async def data_react_node(state: AgentState) -> dict[str, Any]:
    """
    LangGraph 节点：Data Agent Phase 1（ReAct 工具调用）。

    优化：
    1. 动态注入数据时间范围、楼宇列表、时间上下文
    2. 限制历史消息数量
    3. viz_engine 自动生成图表
    """
    t0 = time.time()
    hop_count = state.get("hop_count", 0) + 1

    from app.core.time_context import build_time_context
    dr = await get_data_range()

    # ── 构建上下文注入消息 ─────────────────────────────────────────────
    context_parts: list[str] = build_time_context(
        data_range=dr,
        user_time_context=state.get("time_context"),
        label="查询时间范围",
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

    # ── 取最近 N 条历史消息 ──
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

    # 提取用户问题（供 viz_engine 意图筛选）
    user_q = next(
        (str(m.content) for m in reversed(list(history)) if isinstance(m, HumanMessage)),
        "",
    )

    include_list = not bool(state.get("available_buildings"))
    agent = _get_react_agent(include_list_available_buildings=include_list)

    injected_count = len(sub_messages)
    sub_state = {"messages": sub_messages}

    _REACT_TIMEOUT = 90

    try:
        result = await asyncio.wait_for(
            agent.ainvoke(sub_state, config={"recursion_limit": 12}),
            timeout=_REACT_TIMEOUT,
        )
    except asyncio.TimeoutError:
        logger.warning("Data Agent ReAct 超时（%ds），强制终止", _REACT_TIMEOUT)
        error_msg = AIMessage(
            content="数据查询耗时过长，已自动终止。建议将问题拆分为更简单的查询后重试。"
        )
        return {
            "messages": [error_msg],
            "current_agent": "end",
            "hop_count": hop_count,
            "error": "react_timeout",
        }
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
        payload = extract_tool_payload(msg)
        if isinstance(payload, dict):
            evidence.extend(extract_evidence(payload))

    # ★ viz_engine: 生成图表
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
# Phase 2: Synthesis Prompt + LLM
# ---------------------------------------------------------------------------

SYNTHESIS_PROMPT = """你是一个楼宇能耗管理系统的高级数据分析师。
你的任务是根据工具查询结果和已生成的图表清单，撰写精准、专业的分析报告。

**当前系统日期：{today}** — 输出文本中涉及日期描述必须以此为准。

## 已生成的图表清单
{chart_manifest}

## 输出规范

### 结构
1. 用 Markdown 格式组织
2. 每个指标/维度一个分析段落
3. 在**每个分析段落的结尾**插入对应图表的占位符 `<<CHART:锚点关键词>>`

### 图表占位符规则
- 格式：`<<CHART:锚点关键词>>`
- 锚点关键词从上方图表清单中获取
- 占位符必须放在对应分析段落的**最后一行**（分析完再放图）
- 每个图表的占位符只能出现一次
- 示例：
  ```
  ## 用电量分析
  教学楼1月用电总量为 12,345 kWh，日均约 398 kWh。月中出现明显峰值...
  <<CHART:用电>>

  ## 用水量分析
  总用水量为 567 m³，整体较为平稳...
  <<CHART:用水>>
  ```

### 内容质量
- 使用工具返回的真实数据，禁止编造数字
- 给出具体数值和趋势判断
- 注意数据的时间粒度（日/周/月），使用正确的时间单位描述
- 最后给出简明的管理建议

### 差异/对比分析（当用户比较多个楼宇或时段时）
- 列出各对象的核心指标值，以表格或并列段落呈现
- 计算差值与百分比差异（如：教学楼日均 800 kWh，办公楼 320 kWh，差异约 150%）
- 从以下维度给出可能的差异原因解释：
  - 建筑面积/体量差异
  - 功能用途与运行时段（如教学楼白天满负荷、办公楼弹性工时）
  - 空调/照明等主要耗能设备差异
  - 人员密度与使用频率
- 如数据不足以定论原因，明确标注"建议结合设备台账进一步排查"

### 禁止事项
- 禁止编造工具未返回的数据
- 禁止在总结/结论段落重复放置已用过的图表占位符
- 禁止使用 render_ui_component（图表已自动生成）"""


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
                request_timeout=90,
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
                request_timeout=60,
            )
            return _cached_synthesis_llm_fast


async def data_synthesis_node(state: AgentState) -> dict[str, Any]:
    """
    Phase 2: 基于 chart_manifest + 数据摘要生成精准分析文字。
    文字中的占位符 <<CHART:锚点>> 与图表完美对齐。
    """
    t0 = time.time()

    recent_msgs = state.get("messages", [])
    if recent_msgs and isinstance(recent_msgs[-1], AIMessage) and state.get("error"):
        return {"current_agent": "end"}

    chart_manifest = state.get("chart_manifest", "")
    data_summary = state.get("react_data_summary", "")

    # 无数据早退：ReAct 阶段未获取到有效数据，跳过 LLM 合成，防止编造
    if not chart_manifest.strip() and not data_summary.strip():
        logger.warning("data_synthesis_node: 无图表清单且无数据摘要，早退")
        fallback_msg = AIMessage(
            content="很抱歉，未能查询到相关数据。请尝试：\n"
            "1. 检查楼宇名称或时间范围是否正确\n"
            "2. 将问题拆分为更具体的查询\n"
            "3. 确认所查询的数据类型（电量/水量/冷量）是否可用",
        )
        return {
            "messages": [fallback_msg],
            "current_agent": "end",
        }

    history = state.get("messages", [])
    user_q = next(
        (str(m.content) for m in reversed(list(history)) if isinstance(m, HumanMessage)),
        "",
    )

    from app.core.time_context import get_today
    system_content = SYNTHESIS_PROMPT.format(
        chart_manifest=chart_manifest, today=get_today(),
    )
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

    existing_summary = state.get("context_summary", "")
    new_summary = update_context_summary(
        existing_summary, state.get("intent"), user_q, answer_text,
    )

    return {
        "messages": [AIMessage(content=answer_text)],
        "current_agent": "end",
        "context_summary": new_summary,
    }
