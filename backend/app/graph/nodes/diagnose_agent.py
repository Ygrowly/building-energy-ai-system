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

import json
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
from app.mcp.server import call_tool
from app.schemas.mcp_schemas import (
    CreateWorkOrderDraftInput,
    DetectEnergyAnomaliesInput,
    GetBuildingRatedValuesInput,
    GetDeviceLiveStatusInput,
    QueryEnergyMetricsInput,
    RAGHybridSearchInput,
    RenderUIComponentInput,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# System Prompt — 故障诊断专家
# ---------------------------------------------------------------------------
DIAGNOSE_AGENT_SYSTEM_PROMPT = """你是一个楼宇能耗管理系统的专家（Diagnose & Knowledge Agent）。
你同时具备两种能力：**故障诊断**（结合实时数据 + 知识库）和**知识查询**（直接检索建筑规范/技术标准）。

## 数据库设备体系（故障诊断时使用）
系统使用 devices 表管理所有计量设备，每台设备有唯一 device_id，通过 building_id 关联楼宇：
- ElectricityMeter（电表） → 对应 energy_data.electricity_kwh
- WaterMeter（水表）      → 对应 energy_data.water_m3
- HVAC（空调/暖通）       → 对应 hac_energy, sim_supply_temp_c, sim_return_temp_c
- EnvSensor（环境传感器） → 对应 air_temp_c, humidity_rh_pct, dew_temp_c

⚠️ 重要：创建工单时的 device_id 必须来自 devices 表，而非自行编造！
   正确做法：先调用 list_available_buildings 获取楼宇的 devices 列表，再取对应 device_id。

## 你的专属工具（共 8 个）
1. query_energy_metrics         — 查询时序原始数据（事实核查用）
2. get_device_live_status       — 获取设备最新实时状态快照（含设备列表）
3. get_building_rated_values    — ⭐ 查询国标（GB）期望值 vs 实际值逐小时对比（解释异常的核心依据）
4. detect_energy_anomalies      — 基于 GB 双阈值规则检测异常，输出根因诊断码
5. rag_hybrid_search            — 检索建筑规范/运维手册/技术标准
6. render_ui_component          — 渲染诊断报告卡片或工单卡片
7. create_work_order_draft      — 生成维修工单草稿（须人工确认才能提交）
8. list_available_buildings     — 列出所有楼宇及其设备（工单前必须调用）

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

- 若检索结果 similarity < 0.2，提示"知识库中未找到直接相关条文，建议查阅对应原始标准"

---

## 模式二：故障诊断流程（用户描述异常/告警/能耗问题时）

**执行步骤**（Chain of Thought）：

1. 【异常发现】调用 detect_energy_anomalies 获取 rule_triggered 和 hvac_root_cause
2. 【期望对比】⭐ 调用 get_building_rated_values 获取国标期望值 vs 实际值，
   定量告诉用户"期望应该是多少，实际是多少，偏差多少"
3. 【设备定位】从 list_available_buildings 获取真实 device_id（创建工单必须）
4. 【知识检索】调用 rag_hybrid_search，传入故障类型关键词，例如：
   - hvac_root_cause=A_low_efficiency → 搜索"冷水机组效能衰退 排查"
   - hvac_root_cause=B_small_deltaT  → 搜索"压差旁通阀 水力失调 大流量小温差"
   - hvac_root_cause=C_unexpected_on → 搜索"BMS 排程控制 非预期开机"
   - rule_triggered=water_leak       → 搜索"管网漏水 检测 排查"
5. 【归因分析】结合规则诊断码 + 期望值偏差数据 + 规范条文，形成完整推理链
6. 【结论输出】格式见下方
7. 【工单生成】若需维修，先确认 device_id，再调用 create_work_order_draft

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

## 禁止事项
- 禁止在没有 get_building_rated_values 或 detect_energy_anomalies 数据支撑的情况下做故障诊断
- 禁止直接提交工单（必须先调用 create_work_order_draft 返回 pending_approval 状态）
- 禁止自行编造 device_id（必须来自 devices 表的真实数据）
- RAG 检索结果相关性不足（similarity < 0.2）时，诚实告知"知识库中未找到匹配条目"

## 工单生成规范
1. 先从楼宇设备列表确认 device_id（格式如 'Eagle_public_Henry_hvac'）
2. 调用 create_work_order_draft，device_id 必须填写真实设备 ID
3. 调用后必须渲染 WorkOrderCard 让用户确认：
```
render_ui_component(
    component_type="WorkOrderCard",
    title="维修工单待确认",
    data_payload={"ticket_id": ..., "device_id": ..., "device_type": ..., "issue": ..., "priority": ...},
    source_info={"tool": "create_work_order_draft", "status": "pending_approval"}
)
```"""


# ---------------------------------------------------------------------------
# 工具包装（与 data_agent 保持一致：注入 DB session + 解包 kwargs）
# ---------------------------------------------------------------------------
def _make_mcp_tool(
    tool_name: str,
    description: str,
    args_schema=None,
) -> StructuredTool:
    async def _invoke(**kwargs: Any) -> str:
        # 兼容 LangChain 将参数包在 'kwargs' 键的情况
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


DIAGNOSE_AGENT_TOOLS = [
    _make_mcp_tool(
        "list_available_buildings",
        "列出数据库中所有楼宇及其设备（building_type、devices 列表）。"
        "创建工单前必须先调用以获取真实的 device_id，禁止编造。无需参数，直接调用即可。",
    ),
    _make_mcp_tool(
        "query_energy_metrics",
        "查询指定建筑在时间范围内的能耗指标时序数据（事实核查用）。"
        "默认时间范围：2016-04-01 ~ 2016-05-02。",
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
        "建议时间范围不超过 7 天，默认时间范围：2016-04-01 ~ 2016-05-02。",
        args_schema=GetBuildingRatedValuesInput,
    ),
    _make_mcp_tool(
        "detect_energy_anomalies",
        "基于国标（GB）双阈值规则检测能耗异常，并对空调异常给出根因诊断。"
        "规则：water_leak / electricity_overload / hvac_overconsumption / db_flagged。"
        "空调异常时返回 hvac_root_cause：A_low_efficiency（主机效能衰退）/ "
        "B_small_deltaT（水力失调）/ C_unexpected_on（排程失效）。"
        "默认时间范围：2016-04-01 ~ 2016-05-02。",
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
        "device_id 必须来自 list_available_buildings 返回的真实设备 ID。",
        args_schema=CreateWorkOrderDraftInput,
    ),
]


_cached_diagnose_agent = None
_diagnose_agent_lock: Any = None


def _get_diagnose_agent_lock() -> Any:
    import threading
    global _diagnose_agent_lock
    if _diagnose_agent_lock is None:
        _diagnose_agent_lock = threading.Lock()
    return _diagnose_agent_lock


# 历史消息最大条数（与 data_agent 保持一致）
_MAX_HISTORY_MESSAGES = 8


def _get_diagnose_agent():
    """获取 Diagnose Agent 单例（首次调用时构建，锁保护避免并发重复创建）。"""
    global _cached_diagnose_agent
    with _get_diagnose_agent_lock():
        if _cached_diagnose_agent is None:
            settings = get_settings()
            llm = ChatOpenAI(
                model=settings.LLM_MODEL,
                api_key=settings.LLM_API_KEY or "placeholder",
                base_url=settings.LLM_BASE_URL,
                temperature=0.2,
                max_tokens=2048,   # 诊断报告允许稍长，但不超过 2048
            )
            _cached_diagnose_agent = create_react_agent(
                llm,
                tools=DIAGNOSE_AGENT_TOOLS,
                prompt=DIAGNOSE_AGENT_SYSTEM_PROMPT,
            )
    return _cached_diagnose_agent


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
    agent = _get_diagnose_agent()

    # ── 构建上下文注入消息 ─────────────────────────────────────────────
    context_parts: list[str] = []

    existing_summary = state.get("context_summary", "")
    if existing_summary:
        context_parts.append(f"【历史对话摘要（仅供参考）】\n{existing_summary}")

    available = state.get("available_buildings")
    if available:
        context_parts.append(f"【可用楼宇】: {', '.join(available)}")
    if state.get("building_id"):
        context_parts.append(f"【目标楼宇】: {state['building_id']}")
    if state.get("device_id"):
        context_parts.append(f"【目标设备】: {state['device_id']}")
    tc = state.get("time_context")
    if isinstance(tc, dict):
        start = tc.get("start") or "2016-04-01"
        end   = tc.get("end")   or "2016-05-02"
        context_parts.append(f"【诊断时间范围】: {start} ~ {end}")

    history = state.get("messages", [])
    recent  = history[-_MAX_HISTORY_MESSAGES:] if len(history) > _MAX_HISTORY_MESSAGES else history

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

    try:
        result = await agent.ainvoke(sub_state)
    except Exception as exc:
        logger.error("Diagnose Agent 执行失败: %s", exc)
        error_msg = AIMessage(
            content=f"故障诊断专家遇到了问题：{exc}。请稍后重试或联系人工运维。"
        )
        return {
            "messages": [error_msg],
            "current_agent": "end",
            "hop_count": hop_count,
            "error": str(exc),
        }

    all_messages = result.get("messages", [])
    new_messages  = all_messages[injected_count:]

    # ── 只将最终纯文字 AIMessage 写回全局 state ───────────────────────
    final_ai_msgs = [
        m for m in new_messages
        if isinstance(m, AIMessage)
        and m.content
        and not getattr(m, "tool_calls", [])
    ]
    global_msg = [final_ai_msgs[-1]] if final_ai_msgs else []

    # 收集 artifacts + 检测工单草稿（HITL）
    artifacts = list(state.get("artifacts", []))
    pending_action = state.get("pending_action")

    for msg in new_messages:
        if not isinstance(msg, ToolMessage):
            continue
        content = msg.content or ""
        try:
            data = json.loads(content)
        except (json.JSONDecodeError, TypeError):
            continue

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
        "pending_action": pending_action,
        "context_summary": new_summary,  # ★ 更新滚动摘要
    }
