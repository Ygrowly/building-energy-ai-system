"""
Data Agent（数据分析师）节点。

职责：
- 能耗数据查询（query_energy_metrics）
- 设备实时状态（get_device_live_status）
- 每日趋势聚合（query_daily_energy_summary）
- COP 能效比计算（calculate_system_cop）
- 异常检测（detect_energy_anomalies）
- 自我纠错：工具调用失败时能识别错误原因并重试
- 可视化由后处理 viz_engine 自动完成，LLM 无需关心

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
    GenerateReportInput,
    GetDeviceLiveStatusInput,
    QueryDailyEnergySummaryInput,
    QueryEnergyMetricsInput,
)
from app.graph.viz_engine import generate_viz_artifacts

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# System Prompt — 数据分析师
# ---------------------------------------------------------------------------
DATA_AGENT_SYSTEM_PROMPT = """你是一个楼宇能耗管理系统的数据分析师（Data Agent）。
你拥有只读数据库权限，负责所有数据查询和统计分析工作。

## 你的专属工具（严格按此列表调用，不允许猜测工具名称）
1. list_available_buildings — 列出全部楼宇。**仅当上下文未提供楼宇列表时才调用**
2. query_energy_metrics — 查询指定建筑、时间段、指标的原始时序数据（小时级）
3. get_device_live_status — 查询楼宇下所有设备实时状态（device_id、online_status、power_kw 等）
4. query_daily_energy_summary — 查询单栋楼按天汇总的能耗趋势
5. calculate_system_cop — 计算空调系统能效比（严禁自己算）
6. detect_energy_anomalies — 基于规则检测能耗异常
7. compare_metric_across_buildings — 多栋楼同一指标横向汇总对比，building_ids 传空则自动对比全部楼宇
8. compare_time_periods — 同环比分析（当期 vs 基期），返回变化量和变化率
9. generate_report — 生成 CSV 报表下载链接，用户要求"导出/生成报表"时调用

**重要：系统会自动根据你调用的工具和返回数据的形状决定是否生成可视化图表，你无需关心图表渲染。
专注于：选择正确的工具 → 获取数据 → 用自然语言回答用户问题。**

## 建筑 ID 说明
- building_id 使用 building_type 值：'Education'、'Office'、'Public services'
- **上下文已提供楼宇列表时，直接使用，禁止再调用 list_available_buildings**
- 禁止使用数据库内部 building_id（如 'Fox_office_Alice'）

## 建筑中文名映射（回复用户时必须使用中文名称）
| building_type | 中文名 |
|--------------|--------|
| Education | 教学楼 |
| Office | 办公楼 |
| Public services | 公共楼 |
- 调用工具时 building_id 传英文值，但在回复文本和图表 series.name 中一律使用中文名

## 数据时间范围
- 数据库有效数据：2016-04-01 ~ 2016-05-02
- 用户未指定时间时，优先使用上下文中的时间范围，否则默认 2016-04-01 ~ 2016-05-02
- 禁止使用 2024/2025/2026 等数据库中不存在的日期

## 工具选择指南（按场景选最高效工具）
| 场景 | 首选工具 |
|------|---------|
| 多楼横向总量/均值对比 | compare_metric_across_buildings（building_ids=[]，一次搞定） |
| 单楼日趋势 | query_daily_energy_summary |
| 多楼日趋势对比 | 对每栋楼各调一次 query_daily_energy_summary |
| 原始小时数据 | query_energy_metrics |
| 故障/异常分析 | detect_energy_anomalies |

## 效率规范（重要）
- **完成一个任务的工具调用次数通常不超过 4 次**，超过说明选错了工具
- 开始前先制定查询计划，每种数据只查一次，不重复调用相同工具

## 工作规范
1. 先调工具获取真实数据，再组织自然语言回答
2. 工具报错时，分析原因并修正参数后最多重试 2 次
3. 数据确实不存在时，如实说明，不要编造
4. 回答要包含关键数值，方便用户快速获取信息

## 禁止事项
- 禁止自行计算 COP、总耗电量等（必须调工具）
- 禁止输出未经工具返回的数字
- 禁止查询白名单外的建筑
- 禁止冗余重复的工具调用"""


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
        "generate_report",
        "生成统计报表 CSV 下载链接。用户说'生成报表'/'导出数据'时调用。"
        "返回下载 URL，前端渲染为下载按钮。默认时间范围：2016-04-01 ~ 2016-05-02。",
        args_schema=GenerateReportInput,
    ),
]


_cached_data_agent_full = None
_cached_data_agent_no_list_buildings = None
_data_agent_lock: Any = None


def _get_data_agent_lock() -> Any:
    import threading
    global _data_agent_lock
    if _data_agent_lock is None:
        _data_agent_lock = threading.Lock()
    return _data_agent_lock


def reset_data_agent_cache() -> None:
    """Reset cached Data Agent instances (used by eval/tests)."""
    global _cached_data_agent_full, _cached_data_agent_no_list_buildings, _data_agent_lock
    _cached_data_agent_full = None
    _cached_data_agent_no_list_buildings = None
    _data_agent_lock = None


# 历史消息最大条数（超出时截断最早的），避免 token 随对话增长而膨胀
_MAX_HISTORY_MESSAGES = 8


def _get_data_agent(include_list_available_buildings: bool):
    """
    获取 Data Agent 单例（首次调用时构建，锁保护避免并发重复创建）。
    - include_list_available_buildings=True：提供 list_available_buildings 工具
    - include_list_available_buildings=False：移除该工具，避免模型在已知楼宇列表时仍冗余调用
    """
    global _cached_data_agent_full, _cached_data_agent_no_list_buildings
    with _get_data_agent_lock():
        if include_list_available_buildings:
            if _cached_data_agent_full is not None:
                return _cached_data_agent_full
            settings = get_settings()
            llm = ChatOpenAI(
                model=settings.LLM_MODEL,
                api_key=settings.LLM_API_KEY or "placeholder",
                base_url=settings.LLM_BASE_URL,
                temperature=0.1,
                max_tokens=1500,   # 降低：减少单次 LLM 调用的生成量
            )
            _cached_data_agent_full = create_react_agent(
                llm,
                tools=DATA_AGENT_TOOLS,
                prompt=DATA_AGENT_SYSTEM_PROMPT,
            )
            return _cached_data_agent_full

        # 不提供 list_available_buildings 工具
        if _cached_data_agent_no_list_buildings is not None:
            return _cached_data_agent_no_list_buildings

        settings = get_settings()
        llm = ChatOpenAI(
            model=settings.LLM_MODEL,
            api_key=settings.LLM_API_KEY or "placeholder",
            base_url=settings.LLM_BASE_URL,
            temperature=0.1,
            max_tokens=1500,   # 降低：减少单次 LLM 调用的生成量
        )
        tools_wo_list = [t for t in DATA_AGENT_TOOLS if getattr(t, "name", "") != "list_available_buildings"]
        _cached_data_agent_no_list_buildings = create_react_agent(
            llm,
            tools=tools_wo_list,
            prompt=DATA_AGENT_SYSTEM_PROMPT,
        )
        return _cached_data_agent_no_list_buildings
    # 理论上不会到达：两种分支里都有 return。这里放一个兜底，避免异常情况下返回 None。
    return _cached_data_agent_full if include_list_available_buildings else _cached_data_agent_no_list_buildings


async def data_agent_node(state: AgentState) -> dict[str, Any]:
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
    # 是否允许 ReAct 调用 list_available_buildings：
    # - 若我们能从 state 或预取拿到 available_buildings，就移除该工具，避免冗余调用
    agent = None

    # ── 构建上下文注入消息 ─────────────────────────────────────────────
    # 将路由层提取的实体 + 历史摘要注入为 SystemMessage，
    # 避免 Agent 浪费工具调用去"重新发现"已知信息。
    context_parts: list[str] = []

    # 历史轮次摘要（比全量消息更紧凑）
    existing_summary = state.get("context_summary", "")
    if existing_summary:
        context_parts.append(f"【历史对话摘要（仅供参考，无需重复查询）】\n{existing_summary}")

    available = state.get("available_buildings")
    # 如果路由层初始化时没有把 available_buildings 写进 state，
    # 则会导致 LLM 在 ReAct 过程中额外调用 list_available_buildings。
    # 这里在进入 LLM 前先在代码层拉取一次，减少一次工具调用与思考步数。
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
    if available:
        context_parts.append(
            f"【可用楼宇（直接使用，无需调用 list_available_buildings）】: "
            f"{', '.join(available)}"
        )
    if state.get("building_id"):
        context_parts.append(f"【目标楼宇】: {state['building_id']}")
    tc = state.get("time_context")
    if isinstance(tc, dict):
        start = tc.get("start") or "2016-04-01"
        end   = tc.get("end")   or "2016-05-02"
        context_parts.append(f"【查询时间范围】: {start} ~ {end}")

    # ── 全局 messages 已只含 Human + 最终 AI（干净紧凑），取最近 N 条 ──
    history = state.get("messages", [])
    recent  = history[-_MAX_HISTORY_MESSAGES:] if len(history) > _MAX_HISTORY_MESSAGES else history

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
    agent = _get_data_agent(include_list_available_buildings=include_list)

    # injected_count 用于从结果中准确提取新增消息
    injected_count = len(sub_messages)
    sub_state = {"messages": sub_messages}

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

    # ── 从 ReAct 结果中提取所有新消息 ────────────────────────────────
    all_messages = result.get("messages", [])
    new_messages = all_messages[injected_count:]

    # ── 只将最终纯文字 AIMessage 写回全局 state ───────────────────────
    # ToolMessage 和带 tool_calls 的中间 AIMessage 只在内部使用，不污染全局历史。
    final_ai_msgs = [
        m for m in new_messages
        if isinstance(m, AIMessage)
        and m.content
        and not getattr(m, "tool_calls", [])
    ]
    global_msg = [final_ai_msgs[-1]] if final_ai_msgs else []

    # 提取 evidence（数据溯源）
    artifacts = list(state.get("artifacts", []))
    evidence = list(state.get("evidence", []))
    for msg in new_messages:
        if not isinstance(msg, ToolMessage):
            continue
        content = msg.content or ""
        try:
            payload = json.loads(content)
        except (json.JSONDecodeError, TypeError):
            continue
        if not isinstance(payload, dict):
            continue
        evidence.extend(extract_evidence(payload))

    # 提取用户原始问题（同时用于 viz_engine 和 context_summary）
    user_q = next(
        (str(m.content) for m in reversed(list(history)) if isinstance(m, HumanMessage)),
        "",
    )

    # ★ 可视化引擎：根据工具调用结果 + 用户问题自动生成 artifacts
    viz_artifacts = generate_viz_artifacts(new_messages, user_question=user_q)
    artifacts.extend(viz_artifacts)

    tool_count = sum(1 for m in new_messages if isinstance(m, ToolMessage))
    logger.info(
        "Data Agent 完成: 工具调用=%d 用时=%.1fs", tool_count, time.time() - t0,
    )
    answer_text = str(global_msg[0].content) if global_msg else "（无文字回答，已生成图表）"
    new_summary = update_context_summary(
        existing_summary, state.get("intent"), user_q, answer_text
    )

    return {
        "messages": global_msg,          # ★ 只含最终回答，不含 ToolMessage
        "current_agent": "end",
        "hop_count": hop_count,
        "artifacts": artifacts,
        "evidence": evidence,
        "context_summary": new_summary,  # ★ 更新滚动摘要
    }
