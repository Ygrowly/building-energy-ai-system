"""
Router Agent（智能前台）节点。

职责：
1. 意图识别 & 置信度评估
2. 低置信度（< 0.7）触发反问澄清
3. 从对话中提取实体（建筑 ID、时间、设备 ID）
4. 死循环熔断：hop_count > 5 强制终止
5. 路由分发到 data_agent / diagnose_agent / end
6. 关键词快速通道：对常见问候/闲聊直接回复，跳过 LLM 调用
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

from app.core.config import get_settings
from app.graph.state import AgentState, IntentType, NextNode

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# System Prompt — 路由智能前台
# ---------------------------------------------------------------------------
# 注意：ROUTER_SYSTEM_PROMPT 是模板字符串，{building_list} 在运行时由
# build_router_system_prompt() 函数动态替换为数据库最新楼宇列表。
# ---------------------------------------------------------------------------
_ROUTER_SYSTEM_PROMPT_TEMPLATE = """你是楼宇能耗管理系统的智能助手（Router Agent）。
你的核心职责是：【识别用户意图】→【提取实体】→【决定如何响应】。

**对于通用对话（问候、闲聊、系统介绍等），你要亲切地直接回复。**
**对于专业业务问题，你负责路由到后续专家 Agent 处理，自己不给出数据或诊断结论。**

## 系统数据库结构（供你提取实体时参考）
- buildings 表：楼宇静态信息（building_id, primary_space_usage, sqm, timezone）
- devices 表：设备信息（device_id, building_id, device_type），device_type 取值：electricity / water / ac
- energy_data 表：时序能耗数据（electricity_kwh, water_m3, chilledwater_kwh 等）
- anomaly_events 表：异常事件（rule_triggered, meter_device_id, is_resolved）

## 你管辖的建筑（当前系统真实列表，动态更新）
{building_list}

## 你能识别的意图类型
| intent | 含义 | 触发条件示例 |
|--------|------|------------|
| general_chat | 通用对话，Router 直接友好回复 | "你好"、"你是谁"、"你能做什么"、"谢谢"、"再见"、"帮我介绍一下系统" |
| data_query | 查询能耗/设备状态/对比数据/楼宇列表 | "用了多少电"、"昨天图书馆的数据"、"哪栋楼最费电"、"有哪些楼宇"、"有哪些设备" |
| cop_analysis | 计算空调能效比 COP | "能效比"、"COP"、"制冷效率"、"HVAC 性能" |
| fault_diagnosis | 故障诊断/异常分析 | "为什么这么高"、"有没有问题"、"凌晨异常"、"传感器跳变" |
| work_order | 生成维修工单 | "派单"、"报修"、"维修"、"工单" |
| knowledge_query | 查询建筑规范/技术标准/运维知识/节能法规 | "GB 55015 规定"、"建筑节能标准"、"供暖设计规范"、"预测性维护要求"、"设施管理标准"、"能效等级限值"、"智能化系统规范"、"建筑电气规范"、"设施运维指南"、"知识库"、"手册"、"规范要求"、"标准规定" |
| clarify | 问题太模糊需追问 | 代词不明确、缺少关键实体时 |
| unknown | 与楼宇能耗管理完全无关 | "股票行情"、"天气预报"、"今天午饭吃什么" |

## 你的工作流程
1. 解析用户最新消息 + 历史上下文
2. 识别意图，打分置信度（0.0~1.0）
3. 若 intent=general_chat：在 direct_reply 字段填写友好回复，next_agent=end
4. 若 intent=clarify：在 direct_reply 字段填写反问语句，next_agent=end
5. 若置信度 < 0.7 且意图不明确：返回 intent=clarify + 反问语句
6. 跨楼对比问题（如"哪栋楼用电最多"）识别为 data_query，building_id 设为 null
7. 业务意图（data_query/cop_analysis/fault_diagnosis/work_order）：提取实体并路由
8. 提取 device_id 时：若用户提到设备类型（如"空调"、"电表"）可在 device_id 填写类型提示，
   后续 Diagnose Agent 会从 devices 表查取真实 device_id
9. 以下任意情形识别为 knowledge_query（路由到 diagnose_agent 进行 RAG 检索）：
   - 提问涉及国家标准/行业标准/地方标准/建筑规范（如 GB、JGJ、DB 开头的标准编号）
   - 询问规范条文、技术要求、设计标准、限值指标
   - 询问设备维护规程、运维手册、设施管理知识
   - 含"规定"、"标准"、"规范"、"要求"、"指南"、"手册"、"知识库"等词
   - 询问节能、建筑电气、暖通空调、智能化系统的技术规定

## 输出格式（严格 JSON，不要加 Markdown 代码块）
{{
  "intent": "<意图类型>",
  "confidence": <0.0~1.0>,
  "next_agent": "<data_agent|diagnose_agent|end>",
  "building_id": "<building_type 值，如 Education|null>",
  "device_id": "<设备类型提示或具体 device_id，如 'HVAC'|null>",
  "time_context": {{"start": "<ISO8601|null>", "end": "<ISO8601|null>"}},
  "direct_reply": "<当 intent=general_chat 或 clarify 时填写的直接回复，其他情况为 null>"
}}

## 边界规则
- general_chat 时，要友好、简洁地介绍自己和系统能力，不要捏造数据
- 系统监管 3 类设备：电表（electricity）、水表（water）、空调/暖通（ac）
- 业务查询时，禁止自行给出数据数字、诊断结论——交给后续专家节点
- 禁止幻造不在上方建筑列表内的建筑名
- intent=unknown 仅用于与楼宇能耗管理系统毫无关联的问题（如股票、天气、美食等）
- 涉及建筑/节能/设备/设施/智能化/暖通等领域的知识性问题，即使没有具体楼宇，也应识别为 knowledge_query 而非 unknown"""


def build_router_system_prompt(building_types: list[str] | None = None) -> str:
    """
    用数据库真实楼宇列表动态生成 Router System Prompt。
    building_types 为 None 时使用内置默认值（降级保护）。
    """
    if not building_types:
        building_types = ["Education", "Office", "Public services"]
    building_list = "\n".join(f"- {b}" for b in building_types)
    return _ROUTER_SYSTEM_PROMPT_TEMPLATE.format(building_list=building_list)


# 向后兼容：模块加载时生成一份默认 prompt（无 DB 时可用）
ROUTER_SYSTEM_PROMPT = build_router_system_prompt()


# ---------------------------------------------------------------------------
# 意图 → 下一节点映射
# ---------------------------------------------------------------------------
_INTENT_ROUTING: dict[IntentType | str, NextNode] = {
    "data_query":      "data_agent",
    "cop_analysis":    "data_agent",
    "fault_diagnosis": "diagnose_agent",
    "work_order":      "diagnose_agent",
    "knowledge_query": "diagnose_agent",  # 知识库/规范查询 → RAG 检索
    "general_chat":    "end",             # Router 直接回复，无需下游 Agent
    "clarify":         "router",          # 继续等待用户澄清
    "unknown":         "end",
}

# 意图置信度阈值
CONFIDENCE_THRESHOLD = 0.7
# 死循环熔断阈值
MAX_HOPS = 5

# ---------------------------------------------------------------------------
# 关键词快速通道（跳过 LLM，直接回复常见问候/闲聊）
# 格式：(编译好的正则, 回复文字)
# 仅在消息长度 <= 30 字符时生效，防止误匹配含关键词的业务问题
# ---------------------------------------------------------------------------
_FAST_PATH_RULES: list[tuple[re.Pattern[str], str]] = [
    (
        re.compile(r'^(你好|您好|hi|hello|哈喽|嗨|hey)\s*[!！。.,]*\s*$', re.IGNORECASE),
        "你好！我是楼宇能耗管理系统的智能运维助手。\n\n"
        "我可以帮您：\n"
        "• 查询各楼宇能耗数据（电、水、冷量）\n"
        "• 分析设备异常与故障诊断\n"
        "• 生成维修工单\n"
        "• 导出能耗报表\n\n"
        "有什么可以帮助您的吗？",
    ),
    (
        re.compile(r'^(谢谢|感谢|谢了|多谢|thx|thanks|thank\s*you)\s*[!！。.,~～]*\s*$', re.IGNORECASE),
        "不客气！如还有其他问题，随时可以向我提问。",
    ),
    (
        re.compile(r'^(再见|拜拜|bye|goodbye|晚安|回头见|下次再聊)\s*[!！。.,~～]*\s*$', re.IGNORECASE),
        "再见！有能耗管理相关问题欢迎随时回来咨询。",
    ),
    (
        re.compile(r'^(你是谁|你是什么|介绍一下你自己|你叫什么|你能做什么|你有什么功能)\s*[?？!！。]*\s*$', re.IGNORECASE),
        "我是楼宇能耗管理系统的 AI 运维助手，基于多智能体架构（Router + 数据分析 + 故障诊断）构建。\n\n"
        "**我能做的事：**\n"
        "• **数据查询** — 任意楼宇、任意时段的电 / 水 / 冷量数据\n"
        "• **趋势对比** — 多楼宇横向对比、同比环比分析\n"
        "• **故障诊断** — 异常能耗识别、设备健康评估\n"
        "• **COP 计算** — 空调系统制冷能效比分析\n"
        "• **工单生成** — 自动创建并推送维修工单\n"
        "• **报表导出** — 生成 CSV 能耗报表\n\n"
        "直接用自然语言提问即可，例如：「教学楼昨天用了多少电？」",
    ),
    (
        re.compile(r'^(好的?|好的好的|ok|okay|嗯|嗯嗯|明白|收到|了解)\s*[!！。.,~～]*\s*$', re.IGNORECASE),
        "好的，如果有其他问题随时告诉我！",
    ),
]

_FAST_PATH_MAX_LEN = 30  # 超过此长度不走快速通道，避免误匹配


def _try_fast_path(message: str) -> str | None:
    """
    检查消息是否匹配关键词快速通道。
    匹配则返回直接回复字符串；否则返回 None，走正常 LLM 路径。
    """
    msg = message.strip()
    if len(msg) > _FAST_PATH_MAX_LEN:
        return None
    for pattern, reply in _FAST_PATH_RULES:
        if pattern.match(msg):
            return reply
    return None


_cached_router_llm: ChatOpenAI | None = None
_router_llm_lock: Any = None


def _get_router_llm_lock() -> Any:
    import threading
    global _router_llm_lock
    if _router_llm_lock is None:
        _router_llm_lock = threading.Lock()
    return _router_llm_lock


def _get_router_llm() -> ChatOpenAI:
    """获取路由 LLM 单例（首次调用时初始化，锁保护避免并发重复创建）。"""
    global _cached_router_llm
    with _get_router_llm_lock():
        if _cached_router_llm is None:
            settings = get_settings()
            if not (settings.LLM_API_KEY or "").strip():
                logger.warning(
                    "LLM_API_KEY 未配置，将使用 placeholder；生产环境请在 .env 中设置 LLM_API_KEY"
                )
            _cached_router_llm = ChatOpenAI(
                model=settings.LLM_MODEL,
                api_key=settings.LLM_API_KEY or "placeholder",
                base_url=settings.LLM_BASE_URL,
                temperature=0.0,   # 路由不需要创意，确定性优先
                max_tokens=512,
            )
    return _cached_router_llm


def _parse_router_output(raw: str) -> dict[str, Any]:
    """解析 LLM 返回的 JSON，容错处理。"""
    raw = raw.strip()
    # 移除可能的 Markdown 代码块包装
    raw = re.sub(r"^```(?:json)?\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw)
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        logger.warning("Router LLM 返回了无效 JSON: %s", raw[:200])
        return {
            "intent": "clarify",
            "confidence": 0.0,
            "next_agent": "router",
            "building_id": None,
            "device_id": None,
            "time_context": None,
            "direct_reply": "抱歉，我没有理解您的意思，能否请您重新描述一下？",
        }


async def router_node(state: AgentState) -> dict[str, Any]:
    """
    LangGraph 节点函数：Router Agent。

    接收当前状态，调用 LLM 分析意图，返回状态更新字典。
    """
    hop_count = state.get("hop_count", 0) + 1

    # ── 死循环熔断 ──
    if hop_count > MAX_HOPS:
        logger.warning("Router: hop_count=%d 超过阈值，触发熔断", hop_count)
        circuit_break_msg = AIMessage(
            content=(
                "⚠️ 任务处理流程过于复杂，系统已触发安全熔断。"
                "建议您联系人工运维专家进行处理。"
            )
        )
        return {
            "messages": [circuit_break_msg],
            "current_agent": "end",
            "hop_count": hop_count,
            "intent": "unknown",
            "confidence": 0.0,
        }

    # ── 关键词快速通道（跳过 LLM，零延迟回复常见问候/闲聊）──────────────────
    history = state.get("messages", [])
    last_human = next(
        (m for m in reversed(history) if isinstance(m, HumanMessage)), None
    )
    if last_human:
        fast_reply = _try_fast_path(str(last_human.content))
        if fast_reply is not None:
            logger.debug("Router 快速通道命中: %r", str(last_human.content)[:40])
            return {
                "messages": [AIMessage(content=fast_reply)],
                "current_agent": "end",
                "intent": "general_chat",
                "confidence": 1.0,
                "hop_count": hop_count,
            }

    # ── 准备历史消息（history 已在快速通道处取出）──
    # 全局 messages 已只含 Human + 最终 AI，取最近 6 条（3 轮）即可
    recent_history = history[-6:] if len(history) > 6 else history

    # ── 上下文提示（结构化实体 + 历史摘要 → 替代冗长原始消息）──────────
    ctx_parts: list[str] = []

    # 历史摘要（比原始消息更紧凑）
    context_summary = state.get("context_summary", "")
    if context_summary:
        ctx_parts.append(f"历史对话摘要:\n{context_summary}")

    if state.get("building_id"):
        ctx_parts.append(f"已知建筑: {state['building_id']}")
    if state.get("time_context"):
        ctx_parts.append(f"已知时间范围: {state['time_context']}")
    if state.get("device_id"):
        ctx_parts.append(f"已知设备: {state['device_id']}")

    context_hint = "\n".join(ctx_parts)

    # 动态注入楼宇列表（优先取 state 中缓存的列表，减少 DB 查询）
    building_types: list[str] | None = state.get("available_buildings")
    system_content = build_router_system_prompt(building_types)
    if context_hint:
        system_content += f"\n\n## 当前上下文\n{context_hint}"

    llm_messages = [SystemMessage(content=system_content)] + list(recent_history)

    # ── 调用 LLM ──
    llm = _get_router_llm()
    try:
        response = await llm.ainvoke(llm_messages)
        # P3：多模态返回 content 可能为 list，统一转为 str 再解析
        content = response.content
        if isinstance(content, list):
            raw_output = "".join(
                c.get("text", "") for c in content if isinstance(c, dict)
            )
        else:
            raw_output = str(content or "")
    except Exception as exc:
        logger.error("Router LLM 调用失败: %s", exc)
        error_msg = AIMessage(content="系统暂时无法处理您的请求，请稍后重试。")
        return {
            "messages": [error_msg],
            "current_agent": "end",
            "hop_count": hop_count,
            "error": str(exc),
        }

    parsed = _parse_router_output(raw_output)

    intent: IntentType = parsed.get("intent", "unknown")
    confidence: float = float(parsed.get("confidence", 0.0))
    next_agent: NextNode = parsed.get("next_agent", "end")
    building_id: str | None = parsed.get("building_id") or state.get("building_id")
    device_id: str | None = parsed.get("device_id") or state.get("device_id")
    raw_time = parsed.get("time_context")
    time_context = raw_time if isinstance(raw_time, dict) else state.get("time_context")
    # direct_reply 统一承接 general_chat 直接回复 和 clarify 反问
    direct_reply: str | None = parsed.get("direct_reply") or parsed.get("clarification_question")

    # 验证 next_agent
    if next_agent not in ("data_agent", "diagnose_agent", "router", "end"):
        next_agent = _INTENT_ROUTING.get(intent, "end")

    # ── 构造 AI 回复消息 ──
    if intent == "general_chat" and direct_reply:
        # Router 直接友好回复，不进入下游节点
        ai_msg = AIMessage(content=direct_reply)
    elif intent == "clarify" and direct_reply:
        ai_msg = AIMessage(content=direct_reply)
    elif intent == "unknown":
        ai_msg = AIMessage(
            content=(
                "很抱歉，这个问题超出了楼宇能耗管理系统的服务范围。"
                "我可以帮您查询建筑能耗数据、分析设备故障或生成维修工单。"
            )
        )
    else:
        ai_msg = AIMessage(
            content=f"[Router] 意图确认：{intent}（置信度 {confidence:.0%}），"
                    f"正在转接 {next_agent}..."
        )

    return {
        "messages": [ai_msg],
        "current_agent": next_agent,
        "intent": intent,
        "confidence": confidence,
        "hop_count": hop_count,
        "building_id": building_id,
        "device_id": device_id,
        "time_context": time_context,
    }
