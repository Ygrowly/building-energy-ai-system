"""
Diagnose Agent（故障诊断专家）节点。

职责：
- 混合 RAG 检索运维手册（rag_hybrid_search）
- 基于规则的异常检测（detect_energy_anomalies）
- 综合数据 + 知识库进行归因分析
- 生成工单草稿（create_work_order_draft）—— 必须 Human-in-the-loop 审批
- 渲染诊断报告 / 工单卡片（render_ui_component）

边界：
- 不自行下结论，必须引用知识库依据
- 所有工单操作必须通过 HITL 授权，不直接写入数据库
- 不查询纯数据（那是 Data Agent 的职责）
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

from app.core.config import get_settings
from app.db.session import AsyncSessionLocal
from app.graph.state import AgentState, update_context_summary
from app.graph.evidence import extract_evidence
from app.graph.tool_payloads import build_tool_content_and_artifact, extract_tool_payload
from app.mcp.server import call_tool
from app.mcp.tools.data_query import get_buildings_cache
from app.schemas.mcp_schemas import (
    CreateWorkOrderDraftInput,
    DetectEnergyAnomaliesInput,
    GetBuildingRatedValuesInput,
    GetDeviceLiveStatusInput,
    QueryEnergyMetricsInput,
    RAGHybridSearchInput,
    RenderUIComponentInput,
    WebSearchInput,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# System Prompt — 故障诊断专家
# ---------------------------------------------------------------------------
_DIAGNOSE_PROMPT_TEMPLATE = """你是一个楼宇能耗管理系统的专家（Diagnose & Knowledge Agent）。
你同时具备两种能力：**故障诊断**（结合实时数据 + 知识库）和**知识查询**（直接检索建筑规范/技术标准）。

**当前系统日期：{today}** — 所有时间判断以此为准，当前年份为 {year} 年。

## 数据库设备体系（故障诊断时使用）
系统使用 devices 表管理所有计量设备，每台设备有唯一 device_id，通过 building_id 关联楼宇：
- electricity（电表）→ 对应 energy_data.electricity_kwh
- water（水表）      → 对应 energy_data.water_m3
- ac（空调/暖通）    → 对应 hac_energy, sim_supply_temp_c, sim_return_temp_c

当前数据库完整设备清单（创建工单时直接从此表取 device_id，禁止编造）：
| building_type（工具参数值） | device_id                    | device_type |
|-----------------------------|------------------------------|-------------|
| Education（教学楼）         | EM_AC_Fox_education_Louie    | ac          |
| Education（教学楼）         | EM_ELE_Fox_education_Louie   | electricity |
| Education（教学楼）         | EM_WAT_Fox_education_Louie   | water       |
| Office（办公楼）            | EM_AC_Fox_office_Alice       | ac          |
| Office（办公楼）            | EM_ELE_Fox_office_Alice      | electricity |
| Office（办公楼）            | EM_WAT_Fox_office_Alice      | water       |
| Public services（公共楼）   | EM_AC_Fox_public_Henry       | ac          |
| Public services（公共楼）   | EM_ELE_Fox_public_Henry      | electricity |
| Public services（公共楼）   | EM_WAT_Fox_public_Henry      | water       |

⚠️ 重要：device_id 必须严格使用上表中的值，禁止自行编造或修改！

## 你的专属工具
1. query_energy_metrics         — 查询时序原始数据（事实核查用）
2. get_device_live_status       — 查询楼宇下所有设备实时状态（device_id、online_status、power_kw 等）
3. get_building_rated_values    — ⭐ 查询国标（GB）期望值 vs 实际值逐小时对比（解释异常的核心依据）
4. detect_energy_anomalies      — 基于 GB 双阈值规则检测异常，输出根因诊断码
5. rag_hybrid_search            — 检索建筑规范/运维手册/技术标准
6. render_ui_component          — 渲染诊断报告卡片或工单卡片
7. create_work_order_draft      — 生成维修工单草稿（须人工确认才能提交）
8. web_search（仅联网模式可用）  — 联网搜索补充信息，RAG 知识库不足时使用

---

## 异常检测规则体系（你必须了解）

### 第一层：并行双阈值检测
系统对三个子系统并行检测，**百分比偏差 AND 绝对偏差**双条件同时满足才触发：

| rule_triggered        | 含义               | 阈值                          |
|-----------------------|--------------------|-------------------------------|
| water_leak            | 管网漏水/异常用水  | 偏差 > 20% 且 > 1.0 m³       |
| electricity_overload  | 总电耗异常偏高     | 偏差 > 15% 且 > 期望的 10%   |
| hvac_overconsumption  | 空调系统能耗过高   | 偏差 > 20% 且 > 20 kWh       |
| db_flagged            | 原始数据集标注异常 | 兜底规则                      |

### 第二层：HVAC 根因诊断（仅当 hvac_overconsumption 触发）
| hvac_root_cause      | 含义                             | 物理诊断依据                              |
|----------------------|----------------------------------|-------------------------------------------|
| A_low_efficiency     | 主机效能衰退                     | 供水温度偏离国标期望值 > 1.5℃             |
| B_small_deltaT       | 水力失调（大流量小温差）         | 实际供回水温差 < 3℃（正常应为 5℃）       |
| C_unexpected_on      | 非预期开机（排程失效）           | 建筑设计负荷率 ≤ 0.05 但空调仍运行        |
| other_hvac           | 空调异常但原因待查               | 上述三类均不满足                          |

### 国标基准参考（GB 50189-2015）
- 制冷季系统综合 COP 基准：**3.5**（含主机+水泵+冷却塔）
- 供暖季系统综合 COP 基准：**2.5**（热泵/锅炉综合系统）
- 标准供冷供回水温度：**7℃/12℃**（温差 5℃）
- 标准供暖供回水温度：**60℃/50℃**（温差 10℃）

---

## 模式一：知识查询流程（用户询问规范/标准/技术要求时）

**识别时机**：用户询问建筑节能规范、行业标准、设计规范、设施管理指南、设备能效标准等，
无需结合实时数据，直接从知识库检索即可。

**执行步骤**：
1. 【知识检索】直接调用 rag_hybrid_search，query 填入用户问题关键词（中文）
2. 【结果整理】提取检索到的规范条文，标注来源文档和章节
3. 【结构化回复】按以下格式输出：

> **规范依据**：《[文档名称]》
> **相关条文**：[检索到的具体内容摘要]
> **补充说明**：[如有必要，给出专业解读]

- 若检索结果 similarity < 0.2 或结果不充分：
  - 若 web_search 工具可用（联网模式），调用 web_search 搜索相关规范/标准/技术方案作为补充
  - 若 web_search 不可用，提示"知识库中未找到直接相关条文，建议查阅对应原始标准"

---

## 模式二：故障诊断流程（用户描述异常/告警/能耗问题时）

**执行步骤**（Chain of Thought）：

1. 【异常发现】调用 detect_energy_anomalies 获取 rule_triggered 和 hvac_root_cause
2. 【期望对比】⭐ 调用 get_building_rated_values 获取国标期望值 vs 实际值，
   定量告诉用户"期望应该是多少，实际是多少，偏差多少"
3. 【设备定位】若上下文已提供【楼宇设备列表】则直接读取 device_id；否则调用 list_available_buildings 获取（创建工单必须使用真实 device_id）
4. 【知识检索】调用 rag_hybrid_search，传入故障类型关键词，例如：
   - hvac_root_cause=A_low_efficiency → 搜索"冷水机组效能衰退 排查"
   - hvac_root_cause=B_small_deltaT  → 搜索"压差旁通阀 水力失调 大流量小温差"
   - hvac_root_cause=C_unexpected_on → 搜索"BMS 排程控制 非预期开机"
   - rule_triggered=water_leak       → 搜索"管网漏水 检测 排查"
4.5【联网补充】（可选）若 RAG 检索结果不充分且 web_search 可用，搜索故障类型的行业解决方案
5. 【归因分析】结合规则诊断码 + 期望值偏差数据 + 规范条文（+ 联网参考），形成完整推理链
6. 【结论输出】格式见下方
7. 【工单建议】在诊断结论中告知用户"如需生成维修工单，请回复'派单'或'生成工单'"。
   **禁止主动调用 create_work_order_draft**，仅当用户在后续消息中明确请求时才执行。

**诊断结论格式**：
> **诊断结论**：[X类故障]（根因：[hvac_root_cause 或 rule]）
> **量化依据**：
>   - 实际值：[X kWh/m³/℃]
>   - 国标期望值：[Y kWh/m³/℃]（基于 GB [标准编号]）
>   - 偏差：[+Z%]，超限 [N] 小时
> **规范依据**：《[手册名称]》第 [X] 页：[原文引用]
> **置信度**：[百分比]
> **建议操作**：[具体步骤]，涉及设备：[device_id]（[device_type]）

---

## 数据时间范围（极其重要，必须严格遵守）
- 今天是 **{today}**，当前年份是 **{year} 年**
- **所有工具调用的日期必须来自上下文中的【诊断时间范围】**，该范围已由系统自动计算
- 严禁自行编造日期，严禁使用 {year} 年以外或不在上下文范围内的日期
- 参考今天日期 {today} 判断"最近一周""上个月"等相对时间

## 禁止事项
- 禁止在没有 get_building_rated_values 或 detect_energy_anomalies 数据支撑的情况下做故障诊断
- 禁止直接提交工单（必须先调用 create_work_order_draft 返回 pending_approval 状态）
- 禁止自行编造 device_id（必须来自 devices 表的真实数据）
- **禁止自行编造日期**（必须使用上下文注入的时间范围）
- RAG 检索结果相关性不足（similarity < 0.2）时，诚实告知"知识库中未找到匹配条目"

## 工单生成规范（仅用户明确请求时执行）
**触发条件**：用户回复"派单""报修""生成工单""创建工单"等明确指令后才执行以下步骤。
**禁止在诊断流程中主动生成工单。**
1. 先从上方【当前数据库完整设备清单】确认 device_id（如办公楼空调：'EM_AC_Fox_office_Alice'）
2. 调用 create_work_order_draft，device_id 必须填写真实设备 ID
3. 调用后使用 render_ui_component 工具渲染 WorkOrderCard 让用户确认（component_type 填 "WorkOrderCard"）"""


# ---------------------------------------------------------------------------
# 工具包装（与 data_agent 保持一致：注入 DB session + 解包 kwargs）
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
    args_schema=None,
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


# 不含 list_available_buildings 的工具（当上下文已注入设备列表时使用）
_TOOL_LIST_BUILDINGS = _make_mcp_tool(
    "list_available_buildings",
    "列出数据库中所有楼宇及其设备（building_type、devices 列表）。"
    "仅在上下文未提供设备列表时调用，无需参数，直接调用即可。",
)

def _build_diagnose_base_tools() -> list[StructuredTool]:
    from app.core.config import get_settings as _gs
    _s = _gs()
    _tr = f"{_s.DATA_TIME_START} ~ {_s.DATA_TIME_END}"
    return [
    _make_mcp_tool(
        "query_energy_metrics",
        "查询指定建筑在时间范围内的能耗指标时序数据（事实核查用）。"
        "未指定时间时使用上下文中的默认范围。",
        args_schema=QueryEnergyMetricsInput,
    ),
    _make_mcp_tool(
        "get_device_live_status",
        "获取设备最新实时状态（operation_status, ambient_temp_c 等）。",
        args_schema=GetDeviceLiveStatusInput,
    ),
    _make_mcp_tool(
        "get_building_rated_values",
        "⭐ 核心诊断工具：查询指定建筑在时间段内每小时的国标（GB）期望值 vs 实际值对比。"
        "返回 rated_water/rated_electricity/rated_hac_energy（期望）与 actual_*（实际），"
        "以及 water/electricity/hac 三项偏差百分比。"
        "用途：向用户解释'期望是多少，实际是多少，偏差了多少'。"
        "建议时间范围不超过 7 天，未指定时间时使用上下文中的默认范围。",
        args_schema=GetBuildingRatedValuesInput,
    ),
    _make_mcp_tool(
        "detect_energy_anomalies",
        "基于国标（GB）双阈值规则检测能耗异常，并对空调异常给出根因诊断。"
        "规则：water_leak / electricity_overload / hvac_overconsumption / db_flagged。"
        "空调异常时返回 hvac_root_cause：A_low_efficiency（主机效能衰退）/ "
        "B_small_deltaT（水力失调）/ C_unexpected_on（排程失效）。"
        "未指定时间时使用上下文中的默认范围。",
        args_schema=DetectEnergyAnomaliesInput,
    ),
    _make_mcp_tool(
        "rag_hybrid_search",
        "混合检索运维手册，RAGFlow 未配置时自动降级到本地知识库。"
        "device_id 传入可精准过滤到设备相关文档。"
        "诊断时建议按根因类型搜索：A→冷水机组效能衰退，B→压差旁通阀水力失调，C→BMS排程控制。",
        args_schema=RAGHybridSearchInput,
    ),
    _make_mcp_tool(
        "render_ui_component",
        "生成诊断报告卡片或工单卡片（WorkOrderCard）的前端渲染指令。",
        args_schema=RenderUIComponentInput,
    ),
    _make_mcp_tool(
        "create_work_order_draft",
        "生成维修工单草稿（status=pending_approval，须人工确认后才正式派单）。"
        "device_id 必须来自上下文【楼宇设备列表】中的真实设备 ID。",
        args_schema=CreateWorkOrderDraftInput,
    ),
    ]


_DIAGNOSE_BASE_TOOLS = _build_diagnose_base_tools()

_WEB_SEARCH_TOOL = _make_mcp_tool(
    "web_search",
    "联网搜索：RAG 知识库信息不足时，调用此工具从互联网获取补充信息。"
    "传入简洁的搜索关键词（如'建筑空调系统节能优化方案'），返回多条参考摘要。"
    "优先使用 rag_hybrid_search，仅在 RAG 结果不充分时才调用。",
    args_schema=WebSearchInput,
)

# Chat 对话链路不再暴露工单生成能力；工单只由异常监测等独立流程产生。
_chat_work_orders_enabled = False
_DIAGNOSE_CHAT_TOOLS = [
    tool for tool in _DIAGNOSE_BASE_TOOLS
    if tool.name != "create_work_order_draft"
]
DIAGNOSE_AGENT_TOOLS = [_TOOL_LIST_BUILDINGS] + list(_DIAGNOSE_CHAT_TOOLS)


# 缓存键: (include_list_buildings, thinking_mode, enable_web_search)
_diagnose_agent_cache: dict[tuple[bool, str, bool], Any] = {}
_diagnose_agent_lock: Any = None


def _get_diagnose_agent_lock() -> Any:
    import threading
    global _diagnose_agent_lock
    if _diagnose_agent_lock is None:
        _diagnose_agent_lock = threading.Lock()
    return _diagnose_agent_lock


def reset_diagnose_agent_cache() -> None:
    """Reset cached Diagnose Agent instances (used by eval/tests)."""
    global _diagnose_agent_cache, _diagnose_agent_lock
    _diagnose_agent_cache = {}
    _diagnose_agent_lock = None


_MAX_HISTORY_MESSAGES = 8


def _build_diagnose_prompt() -> str:
    """用当前日期填充诊断 Prompt 模板。"""
    from app.core.time_context import get_today
    today = get_today()
    prompt = _DIAGNOSE_PROMPT_TEMPLATE.format(today=today, year=today.year)
    if not _chat_work_orders_enabled:
        blocked = (
            "create_work_order_draft",
            "派单",
            "报修",
            "生成工单",
            "创建工单",
            "工单建议",
            "工单生成规范",
            "WorkOrderCard",
        )
        prompt = "\n".join(
            line for line in prompt.splitlines()
            if not any(token in line for token in blocked)
        )
    return prompt


def _get_diagnose_agent(
    include_list_buildings: bool = True,
    thinking_mode: str = "fast",
    enable_web_search: bool = False,
):
    """
    获取 Diagnose Agent 实例（按日期+参数缓存，跨日自动重建）。
    """
    from app.core.time_context import get_today
    cache_key = (include_list_buildings, thinking_mode, enable_web_search, str(get_today()))
    with _get_diagnose_agent_lock():
        if cache_key in _diagnose_agent_cache:
            return _diagnose_agent_cache[cache_key]

        settings = get_settings()
        if thinking_mode == "deep" and settings.LLM_MODEL_DEEP:
            model = settings.LLM_MODEL_DEEP
            max_tok = 3000
        else:
            model = settings.LLM_MODEL_DIAGNOSE or settings.LLM_MODEL
            max_tok = 2048

        llm = ChatOpenAI(
            model=model,
            api_key=settings.LLM_API_KEY or "placeholder",
            base_url=settings.LLM_BASE_URL,
            temperature=0.2,
            max_tokens=max_tok,
            streaming=True,
            request_timeout=90,
        )
        tools = DIAGNOSE_AGENT_TOOLS if include_list_buildings else _DIAGNOSE_CHAT_TOOLS
        if enable_web_search:
            tools = list(tools) + [_WEB_SEARCH_TOOL]
        prompt = _build_diagnose_prompt()
        agent = create_react_agent(llm, tools=tools, prompt=prompt)
        _diagnose_agent_cache[cache_key] = agent
        return agent


async def diagnose_agent_node(state: AgentState) -> dict[str, Any]:
    """
    LangGraph 节点函数：Diagnose Agent。

    优化要点（与 data_agent 对齐）：
    1. 注入路由提取的上下文 + 历史摘要，避免 Agent 重复查询已知实体。
    2. 限制历史消息传入数量。
    3. 只将最终文字回复写回全局 state，ToolMessage 不入全局历史。
    4. 更新 context_summary 供下轮使用。
    """
    t0 = time.time()
    hop_count = state.get("hop_count", 0) + 1

    # ── 统一时间上下文 ─────────────────────────────────────────────────
    from app.core.data_range import get_data_range
    from app.core.time_context import build_time_context
    data_range = await get_data_range()

    # ── 构建上下文注入消息 ─────────────────────────────────────────────
    context_parts: list[str] = build_time_context(
        data_range=data_range,
        user_time_context=state.get("time_context"),
        label="诊断时间范围",
    )

    existing_summary = state.get("context_summary", "")
    if existing_summary:
        context_parts.append(f"【历史对话摘要（仅供参考）】\n{existing_summary}")

    available = state.get("available_buildings")
    include_list_tool = not bool(available)
    if available:
        cache = get_buildings_cache()
        if cache and cache.buildings:
            device_lines = []
            for b in cache.buildings:
                device_ids = [d.device_id for d in (b.devices or [])]
                device_lines.append(
                    f"  {b.building_type}：{', '.join(device_ids) if device_ids else '（无设备）'}"
                )
            context_parts.append(
                "【楼宇及设备列表（直接使用，无需调用 list_available_buildings）】:\n"
                + "\n".join(device_lines)
            )
        else:
            context_parts.append(f"【可用楼宇】: {', '.join(available)}")

    # 接力场景：Data Agent 已完成数据查询，将摘要注入供深度分析
    data_summary = state.get("react_data_summary", "")
    if data_summary.strip():
        context_parts.append(
            f"【Data Agent 已查询的数据摘要（直接用于分析，无需重复查询）】\n{data_summary}"
        )

    if state.get("building_id"):
        context_parts.append(f"【目标楼宇】: {state['building_id']}")
    if state.get("device_id"):
        context_parts.append(f"【目标设备】: {state['device_id']}")

    history = state.get("messages", [])

    # 接力场景（data_summary 非空）：只保留用户原始问题，减少无关上下文
    is_relay = bool(data_summary.strip())
    if is_relay:
        user_msgs = [m for m in history if isinstance(m, HumanMessage)]
        recent = user_msgs[-2:] if user_msgs else []
    else:
        recent = history[-_MAX_HISTORY_MESSAGES:] if len(history) > _MAX_HISTORY_MESSAGES else history

    if context_parts:
        ctx_msg = SystemMessage(
            content="路由层提取的上下文（直接使用，无需重复查询）：\n"
                    + "\n".join(context_parts)
        )
        sub_messages = [ctx_msg] + list(recent)
    else:
        sub_messages = list(recent)

    injected_count = len(sub_messages)
    sub_state = {"messages": sub_messages}

    thinking_mode = state.get("thinking_mode", "fast")
    enable_web_search = state.get("enable_web_search", False)
    agent = _get_diagnose_agent(
        include_list_buildings=include_list_tool,
        thinking_mode=thinking_mode,
        enable_web_search=enable_web_search,
    )

    _DIAGNOSE_TIMEOUT = 120
    _MAX_RETRIES = 2
    _RETRYABLE_KEYWORDS = ("connection_lost", "ConnectionReset", "RemoteDisconnected", "ServerDisconnected")

    result = None
    last_exc: Exception | None = None

    for attempt in range(1, _MAX_RETRIES + 1):
        try:
            result = await asyncio.wait_for(
                agent.ainvoke(sub_state, config={"recursion_limit": 15}),
                timeout=_DIAGNOSE_TIMEOUT,
            )
            break
        except asyncio.TimeoutError:
            logger.warning("Diagnose Agent 超时（%ds），强制终止", _DIAGNOSE_TIMEOUT)
            return {
                "messages": [AIMessage(
                    content="诊断分析耗时过长，已自动终止。建议简化问题后重试，或联系人工运维。"
                )],
                "current_agent": "end",
                "hop_count": hop_count,
                "error": "diagnose_timeout",
            }
        except Exception as exc:
            last_exc = exc
            exc_str = str(exc)
            is_retryable = any(kw in exc_str for kw in _RETRYABLE_KEYWORDS)
            if is_retryable and attempt < _MAX_RETRIES:
                logger.warning(
                    "Diagnose Agent 瞬时错误（第%d次），%.1fs 后重试: %s",
                    attempt, attempt * 2, exc_str[:120],
                )
                await asyncio.sleep(attempt * 2)
                continue
            logger.error("Diagnose Agent 执行失败（第%d次）: %s", attempt, exc)
            return {
                "messages": [AIMessage(
                    content=f"故障诊断专家遇到了问题：{exc}。请稍后重试或联系人工运维。"
                )],
                "current_agent": "end",
                "hop_count": hop_count,
                "error": str(exc),
            }

    if result is None:
        logger.error("Diagnose Agent 重试耗尽: %s", last_exc)
        return {
            "messages": [AIMessage(content="诊断服务暂时不可用，请稍后重试。")],
            "current_agent": "end",
            "hop_count": hop_count,
            "error": str(last_exc),
        }

    all_messages = result.get("messages", [])
    new_messages  = all_messages[injected_count:]

    # Debug: 帮助排查消息丢失问题
    ai_in_new = [m for m in new_messages if isinstance(m, AIMessage)]
    logger.debug(
        "Diagnose 消息统计: all=%d injected=%d new=%d ai_in_new=%d",
        len(all_messages), injected_count, len(new_messages), len(ai_in_new),
    )
    for i, m in enumerate(ai_in_new):
        has_tc = bool(getattr(m, "tool_calls", []))
        has_content = bool(m.content)
        has_rc = bool((getattr(m, "additional_kwargs", None) or {}).get("reasoning_content"))
        logger.debug("  AI[%d]: content=%s tool_calls=%s reasoning=%s", i, has_content, has_tc, has_rc)

    # ── 只将最终纯文字 AIMessage 写回全局 state ───────────────────────
    # 优先：纯文字（无 tool_calls）的 AIMessage
    final_ai_msgs = [
        m for m in new_messages
        if isinstance(m, AIMessage)
        and m.content
        and not getattr(m, "tool_calls", [])
    ]
    if not final_ai_msgs:
        # Fallback 1: 有 content 但同时携带 tool_calls 的 AIMessage（如调用了 render_ui_component）
        final_ai_msgs = [
            m for m in new_messages
            if isinstance(m, AIMessage) and m.content
        ]
    if not final_ai_msgs:
        # Fallback 2: content 为空但 reasoning_content 有内容（思考链模型）
        for m in reversed(new_messages):
            if not isinstance(m, AIMessage):
                continue
            rc = (getattr(m, "additional_kwargs", None) or {}).get("reasoning_content", "")
            if rc:
                final_ai_msgs = [AIMessage(content=rc)]
                break
    global_msg = [final_ai_msgs[-1]] if final_ai_msgs else []

    # 收集 artifacts + 检测工单草稿（HITL）
    artifacts = list(state.get("artifacts", []))
    evidence = list(state.get("evidence", []))
    pending_action = state.get("pending_action")

    for msg in new_messages:
        if not isinstance(msg, ToolMessage):
            continue
        data = extract_tool_payload(msg)
        if not isinstance(data, dict):
            continue

        evidence.extend(extract_evidence(data))

        if "component_type" in data:
            artifacts.append(data)

        if data.get("status") == "pending_approval":
            pending_action = {
                "type": "work_order",
                "ticket_id": data.get("ticket_id"),
                "device_id": data.get("device_id"),
                "building_id": data.get("building_id"),
                "issue_description": data.get("issue_description"),
                "priority": data.get("priority"),
                "suggested_action": data.get("suggested_action"),
            }

    tool_count = sum(1 for m in new_messages if isinstance(m, ToolMessage))
    logger.info(
        "Diagnose Agent 完成: 工具调用=%d 用时=%.1fs", tool_count, time.time() - t0,
    )

    # ── 滚动更新 context_summary ──────────────────────────────────────
    user_q = next(
        (str(m.content) for m in reversed(list(history)) if isinstance(m, HumanMessage)),
        "",
    )
    answer_text = str(global_msg[0].content) if global_msg else "（已生成诊断报告/工单）"
    new_summary = update_context_summary(
        existing_summary, state.get("intent"), user_q, answer_text
    )

    return {
        "messages": global_msg,          # ★ 只含最终回答
        "current_agent": "end",
        "hop_count": hop_count,
        "artifacts": artifacts,
        "evidence": evidence,
        "pending_action": pending_action,
        "context_summary": new_summary,  # ★ 更新滚动摘要
    }
