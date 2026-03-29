"""
AI 审批引擎：查询特殊事件 -> 调用 LLM 判断 -> 写回工单。

设计原则：
  1. 无生效事件 -> 直接批准（跳过 LLM）
  2. 有生效事件 -> LLM 判断事件能否解释该异常
  3. LLM 调用失败 -> 降级批准（fail-open，ai_fallback=True）
  4. 并发安全 -> SELECT FOR UPDATE 行锁
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.db.models import WorkOrder, WorkOrderAnomalyLink
from app.services.context_event_service import (
    query_active_events,
    serialize_context_event,
)
from app.services.work_order_service import apply_ai_review

logger = logging.getLogger(__name__)
settings = get_settings()

# ---------------------------------------------------------------------------
# LLM 配置
# ---------------------------------------------------------------------------
_LLM_TIMEOUT = 10
_LLM_MAX_RETRIES = 1
_LLM_RETRY_DELAY = 1

_SYSTEM_PROMPT = (
    "你是一名建筑能源管理系统的 AI 审批员。你的职责是判断：给定的异常工单，"
    "在当前已知的特殊事件背景下，是否仍然需要派发维修。\n\n"
    "## 判断原则\n"
    "- 你不需要重新判断异常是否存在（异常检测系统已确认）\n"
    "- 你只需要判断：当前生效的特殊事件，是否能合理解释这次异常\n"
    "- 合理解释意味着该事件在时间和空间上与异常相关，且事件的性质能导致这类能耗偏离\n"
    "- 如果没有任何事件能解释，必须批准派单（decision: approve）\n"
    "- 如果有多个事件都能解释，选择最相关的一个作为主因\n\n"
    "## 典型判断逻辑\n"
    "- 加班（overtime）可以解释：非工作时段的电耗/暖通异常、延长时段的水耗异常\n"
    "- 装修（renovation）可以解释：电耗异常、水耗异常（施工用水）\n"
    "- 极端高温（extreme_heat）可以解释：空调能耗过高、供回水温度偏离\n"
    "- 极端高温 不能解释：水耗异常（除非有合理关联）\n"
    "- 极端低温（extreme_cold）可以解释：暖通能耗过高\n"
    "- 台风/暴雨 可以解释：水耗异常（可能是传感器受影响或应急排水）\n"
    "- 计划维护（maintenance_window）可以解释：任何类型的异常（维护期间波动正常）\n"
    "- 事件已过期（不在 grace_period 内）：不能解释\n\n"
    "## 输出格式\n"
    "严格输出以下 JSON，不要输出任何其他内容：\n"
    '{"decision": "approve 或 reject", "reason": "一句话理由", '
    '"matched_event_ids": ["事件ID"] 或 null}'
)


# ---------------------------------------------------------------------------
# 核心审批函数
# ---------------------------------------------------------------------------
async def review_work_order(db: AsyncSession, work_order_id: str) -> None:
    """对一个 pending_review 工单执行 AI 审批。"""
    # 行锁防并发
    result = await db.execute(
        select(WorkOrder)
        .where(WorkOrder.id == work_order_id)
        .with_for_update(skip_locked=True)
    )
    wo = result.scalar_one_or_none()

    if not wo:
        logger.warning("工单不存在: %s", work_order_id)
        return

    # 幂等：已审批则跳过
    if wo.ai_reviewed_at is not None or wo.status != "pending_review":
        logger.debug("工单已审批或非 pending_review，跳过: %s", wo.ticket_id)
        return

    # 收集异常证据
    links_result = await db.execute(
        select(WorkOrderAnomalyLink)
        .where(WorkOrderAnomalyLink.work_order_id == wo.id)
    )
    links = list(links_result.scalars().all())
    anomaly_timestamp = links[0].data_timestamp if links else wo.created_at

    # 查询生效的特殊事件
    active_events = await query_active_events(
        db, building_id=wo.building_id, anomaly_timestamp=anomaly_timestamp,
    )

    # 无生效事件 -> 直接批准
    if not active_events:
        logger.info("无生效特殊事件，直接批准: %s", wo.ticket_id)
        await apply_ai_review(
            db, work_order=wo,
            decision="approve",
            reason="无生效特殊事件，直接批准派单",
        )
        return

    # 有事件 -> 调用 LLM
    llm_input = _build_llm_input(wo, links, active_events)
    llm_result = await _call_llm_with_retry(llm_input)

    if llm_result is None:
        logger.warning("LLM 调用失败，降级批准: %s", wo.ticket_id)
        await apply_ai_review(
            db, work_order=wo,
            decision="approve",
            reason="AI 审批 LLM 调用失败，降级批准",
            fallback=True,
        )
        return

    # 解析结果
    decision = llm_result.get("decision", "approve")
    reason = llm_result.get("reason", "")
    matched_ids = llm_result.get("matched_event_ids")

    if decision not in ("approve", "reject"):
        decision = "approve"
        reason = "LLM 返回非法决定，降级批准"
        matched_ids = None

    await apply_ai_review(
        db, work_order=wo,
        decision=decision,
        reason=reason,
        matched_event_ids=matched_ids if decision == "reject" else None,
        fallback=False,
    )
    logger.info("AI 审批完成: %s -> %s (%s)", wo.ticket_id, decision, reason[:50])


# ---------------------------------------------------------------------------
# LLM 输入构建
# ---------------------------------------------------------------------------
def _build_llm_input(
    wo: WorkOrder,
    links: list[WorkOrderAnomalyLink],
    events: list[Any],
) -> str:
    info: dict[str, Any] = {
        "ticket_id": wo.ticket_id,
        "building_id": wo.building_id,
        "device_id": wo.device_id,
        "issue_description": wo.issue_description,
    }
    if links:
        f = links[0]
        info.update({
            "rule_triggered": f.rule_triggered,
            "hvac_root_cause": f.hvac_root_cause,
            "anomaly_timestamp": f.data_timestamp.isoformat() if f.data_timestamp else None,
            "actual_value": f.actual_value,
            "expected_value": f.expected_value,
            "deviation_pct": f.deviation_pct,
        })
    payload = {
        "work_order": info,
        "active_events": [serialize_context_event(ev) for ev in events],
    }
    return json.dumps(payload, ensure_ascii=False, default=str)


# ---------------------------------------------------------------------------
# LLM 调用（含重试与降级）
# ---------------------------------------------------------------------------
async def _call_llm_with_retry(user_input: str) -> dict[str, Any] | None:
    for attempt in range(_LLM_MAX_RETRIES + 1):
        try:
            raw = await _call_llm(user_input)
            parsed = _parse_llm_response(raw)
            if parsed:
                return parsed
            logger.warning("LLM 响应解析失败 (attempt %d): %s", attempt + 1, raw[:200])
        except Exception as e:
            logger.warning("LLM 调用异常 (attempt %d): %s", attempt + 1, e)
        if attempt < _LLM_MAX_RETRIES:
            await asyncio.sleep(_LLM_RETRY_DELAY)
    return None


async def _call_llm(user_input: str) -> str:
    from langchain_openai import ChatOpenAI
    from langchain_core.messages import SystemMessage, HumanMessage

    model_name = (
        settings.LLM_MODEL_REVIEW
        or settings.LLM_MODEL_DIAGNOSE
        or settings.LLM_MODEL
    )
    llm = ChatOpenAI(
        model=model_name,
        api_key=settings.LLM_API_KEY,
        base_url=settings.LLM_BASE_URL,
        temperature=0.0,
        max_tokens=512,
        timeout=_LLM_TIMEOUT,
    )
    messages = [
        SystemMessage(content=_SYSTEM_PROMPT),
        HumanMessage(content=user_input),
    ]
    response = await asyncio.wait_for(
        llm.ainvoke(messages),
        timeout=_LLM_TIMEOUT + 5,
    )
    return response.content


# ---------------------------------------------------------------------------
# LLM 响应解析
# ---------------------------------------------------------------------------
_JSON_BLOCK_RE = re.compile(r'```(?:json)?\s*(\{.*?\})\s*```', re.DOTALL)
_JSON_DECISION_RE = re.compile(r'\{[^{}]*"decision"[^{}]*\}', re.DOTALL)


def _parse_llm_response(raw: str) -> dict[str, Any] | None:
    """从 LLM 响应中解析 JSON。支持 markdown code block 包裹。"""
    # 直接解析
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass

    # markdown code block
    match = _JSON_BLOCK_RE.search(raw)
    if match:
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            pass

    # 正则提取含 decision 的 JSON
    match = _JSON_DECISION_RE.search(raw)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            pass

    return None
