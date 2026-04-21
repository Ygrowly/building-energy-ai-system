from __future__ import annotations

import json
import logging
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Literal

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.cache import delete_cache_by_prefix
from app.db.models import (
    AiAssistantActionAudit,
    AiAssistantMessage,
    AiAssistantSession,
    DispatchHallEntry,
    DispatchTask,
    User,
    WorkOrder,
)
from app.services.ai_model_provider import get_model_provider, parse_json_object
from app.services.audit_log_service import write_work_order_audit_log
from app.services.dispatch_event_service import record_dispatch_event
from app.services.dispatch_hall_service import (
    accept_assigned_support_hall_entry,
    get_dispatch_hall_entry_by_id,
    reject_assigned_support_hall_entry,
    serialize_dispatch_hall_entry,
)
from app.services.maintenance_experience_service import schedule_experience_capture
from app.services.dispatch_service import (
    complete_dispatch_task,
    get_current_dispatch_task,
    get_dispatch_task_by_id,
    reject_dispatch_task,
)
from app.services.work_order_service import (
    get_work_order_by_ticket_id,
    record_worker_dispatch_action,
    transition_status,
)
from app.services.work_order_status_dimensions import sync_work_order_status_dimensions

logger = logging.getLogger(__name__)

WorkerAiAction = Literal[
    "accept",
    "arrive",
    "start",
    "request_support",
    "support_resolved",
    "accept_support",
    "reject_support",
    "reject",
    "complete",
]

_PENDING_ACTIONS: dict[str, dict[str, Any]] = {}

_ACTION_LABELS: dict[str, str] = {
    "accept": "确认接单",
    "arrive": "确认到场",
    "start": "开始处理",
    "request_support": "请求协同",
    "support_resolved": "协同已解决",
    "accept_support": "确认协同",
    "reject_support": "无法支援",
    "reject": "无法接单/退回改派",
    "complete": "处理完成",
}

_REASON_REQUIRED = {"request_support", "reject", "reject_support"}
_CONFIRM_REQUIRED = set(_ACTION_LABELS)
_DIRECT_ACTIONS = {"accept", "arrive", "start", "request_support", "support_resolved"}


@dataclass
class WorkerIntent:
    action: WorkerAiAction | None
    confidence: float
    reason: str | None = None
    result: str | None = None
    reply: str | None = None


def _clean_text(text: str | None) -> str:
    return (text or "").strip()


def _humanize_worker_reply_text(text: str | None) -> str:
    cleaned = _clean_text(text)
    if not cleaned:
        return ""

    direct_replacements = (
        ('BMS说“下班了”', 'BMS 显示当前不是正常占用时段'),
        ('BMS说"下班了"', 'BMS 显示当前不是正常占用时段'),
        ("流程卡", "维修建议"),
        ("步骤卡片", "维修建议"),
        ("当前步骤", "这一步"),
        ("命中规则", "判断到"),
        ("闭环", "把关键信息补齐"),
    )
    for source, target in direct_replacements:
        cleaned = cleaned.replace(source, target)

    regex_replacements: list[tuple[re.Pattern[str], str | Callable[[re.Match[str]], str]]] = [
        (re.compile(r"step[_\s-]*(\d+)", re.IGNORECASE), lambda match: f"第{match.group(1)}步"),
        (re.compile(r"completed", re.IGNORECASE), "已完成"),
        (re.compile(r"pending", re.IGNORECASE), "待确认"),
        (re.compile(r"needs_support", re.IGNORECASE), "需要协同"),
        (re.compile(r"uncertain", re.IGNORECASE), "待核实"),
        (re.compile(r"worker_observation", re.IGNORECASE), "现场记录"),
        (re.compile(r"event_type", re.IGNORECASE), ""),
        (re.compile(r"plan_id", re.IGNORECASE), ""),
        (re.compile(r"dispatch_id", re.IGNORECASE), ""),
        (re.compile(r"status", re.IGNORECASE), ""),
        (re.compile(r"(?:咱们|我们)?还在第\d+步[，,、]?\s*别跳步[，,、]?", re.IGNORECASE), "先别急着往后跳，"),
        (re.compile(r"(?:现在|目前|当前)?第\d+步才刚开始[，,、]?", re.IGNORECASE), "眼下先把这一步的关键信息补齐，"),
        (re.compile(r"(?:现在|目前|当前)?还在第\d+步(?:，也就是第\d+步)?[:：]?", re.IGNORECASE), "眼下先别急着往后跳，"),
        (re.compile(r"(?:咱们|我们)?仍处在第\d+步[^，。；]*协同前[，,、]?", re.IGNORECASE), "先把眼前这几个关键信息补齐，"),
        (re.compile(r"第\d+步的", re.IGNORECASE), "这一步的"),
        (re.compile(r"第\d+步才算把关键信息补齐", re.IGNORECASE), "这一步才算把关键信息补齐"),
        (re.compile(r"(?:但|不过)?系统里只确认", re.IGNORECASE), "从你现在补充的情况看，"),
        (re.compile(r"虽标了已完成却没传回实际读数", re.IGNORECASE), "但关键读数还没补齐"),
    ]
    for pattern, replacement in regex_replacements:
        cleaned = pattern.sub(replacement, cleaned)

    cleaned = re.sub(r"[ \t]{2,}", " ", cleaned)
    cleaned = re.sub(r"([，。；！？])\1+", r"\1", cleaned)
    cleaned = re.sub(r"([，。；！？])\s+([，。；！？])", r"\2", cleaned)
    return cleaned.strip()


def _is_confirm(text: str) -> bool:
    normalized = _clean_text(text)
    return normalized in {"确认", "确定", "是", "好的", "可以", "执行", "提交", "确认执行"} or any(
        token in normalized for token in ("确认提交", "帮我提交", "执行吧", "可以提交")
    )


def _is_cancel(text: str) -> bool:
    normalized = _clean_text(text)
    return normalized in {"取消", "不要", "否", "不用", "先不"} or any(
        token in normalized for token in ("先别", "不执行", "取消执行")
    )


def _looks_like_action_only(text: str) -> bool:
    return text in {
        "确认接单",
        "接单",
        "到场",
        "确认到场",
        "开始处理",
        "开始维修",
        "请求协同",
        "需要协同",
        "需要支援",
        "无法接单",
        "退回改派",
        "无法支援",
        "处理完成",
        "完成处理",
    }


def _looks_like_bare_ack(text: str) -> bool:
    normalized = _clean_text(text).lower()
    return normalized in {
        "可以",
        "好的",
        "好",
        "行",
        "嗯",
        "嗯嗯",
        "ok",
        "继续",
        "确认",
        "确定",
    }


def _looks_like_greeting(text: str) -> bool:
    normalized = _clean_text(text).lower()
    return normalized in {"你好", "您好", "在吗", "在不在", "hello", "hi", "哈喽", "喂"}


def _looks_like_guidance_question(text: str) -> bool:
    normalized = _clean_text(text)
    if not normalized:
        return False
    action_tokens = (
        "确认接单",
        "接单",
        "确认到场",
        "我已到场",
        "开始处理",
        "开始维修",
        "请求协同",
        "需要协同",
        "处理完成",
        "维修完成",
        "退回改派",
        "无法接单",
        "确认协同",
        "无法支援",
    )
    if any(token in normalized for token in action_tokens):
        return False
    guidance_tokens = (
        "下一步",
        "接下来",
        "下面",
        "后面",
        "步骤",
        "第一步",
        "第二步",
        "做什么",
        "做些啥",
        "做些什么",
        "怎么做",
        "怎么查",
        "怎么排查",
        "怎么处理",
        "看哪里",
        "查哪里",
        "先查",
        "帮我判断",
        "要注意什么",
        "怎么办",
    )
    return any(token in normalized for token in guidance_tokens) or normalized.endswith(("？", "?"))


def _extract_reason(text: str, action: str | None = None) -> str | None:
    cleaned = _clean_text(text)
    if not cleaned:
        return None
    patterns = [
        r"(?:原因是|因为|理由是|备注是|协同原因是|拒绝原因是)(?P<reason>.+)$",
        r"(?:请求协同|需要协同|需要支援|无法接单|退回改派|无法支援)[:：]?(?P<reason>.+)$",
    ]
    for pattern in patterns:
        match = re.search(pattern, cleaned)
        if match:
            reason = _clean_text(match.group("reason"))
            if reason:
                return reason
    if action in _REASON_REQUIRED and len(cleaned) >= 4 and not _looks_like_action_only(cleaned):
        return cleaned
    return None


def classify_worker_intent_by_rules(message: str) -> WorkerIntent:
    text = _clean_text(message)
    if not text:
        return WorkerIntent(action=None, confidence=0.0)

    reason = _extract_reason(text)

    if any(token in text for token in ("协同已解决", "支援已解决", "问题恢复", "恢复处理", "协同完成")):
        return WorkerIntent(action="support_resolved", confidence=0.9, reason=reason)
    if any(token in text for token in ("确认协同", "我来支援", "接受协同", "响应协同")):
        return WorkerIntent(action="accept_support", confidence=0.9, reason=reason)
    if any(token in text for token in ("无法支援", "拒绝协同", "不能支援")):
        return WorkerIntent(action="reject_support", confidence=0.9, reason=reason)
    if any(token in text for token in ("请求协同", "需要协同", "申请协同", "需要支援", "请求支援")):
        return WorkerIntent(action="request_support", confidence=0.9, reason=reason)
    if any(token in text for token in ("无法接单", "无法处理", "退回改派", "拒单", "不能接")):
        return WorkerIntent(action="reject", confidence=0.9, reason=reason)
    if any(token in text for token in ("处理完成", "维修完成", "已经修好", "已修复", "完成处理", "提交完成")):
        result = "false_alarm" if any(token in text for token in ("误报", "虚警")) else "fixed"
        if any(token in text for token in ("升级", "外协")):
            result = "escalated"
        return WorkerIntent(action="complete", confidence=0.9, reason=reason, result=result)
    if any(token in text for token in ("开始处理", "开始维修", "开始排查", "开始干", "启动处理")):
        return WorkerIntent(action="start", confidence=0.9, reason=reason)
    if any(token in text for token in ("确认到场", "我已到场", "已到场", "到现场", "到场了")):
        return WorkerIntent(action="arrive", confidence=0.9, reason=reason)
    if any(token in text for token in ("确认接单", "我接了", "接单", "接受工单", "立即接单")):
        return WorkerIntent(action="accept", confidence=0.9, reason=reason)

    return WorkerIntent(action=None, confidence=0.0)


async def classify_worker_intent(message: str, *, context_summary: str = "") -> WorkerIntent:
    rule_intent = classify_worker_intent_by_rules(message)
    if rule_intent.confidence >= 0.8:
        return rule_intent

    text = _clean_text(message)
    if _looks_like_greeting(text) or _looks_like_bare_ack(text) or _looks_like_guidance_question(text):
        return WorkerIntent(action=None, confidence=1.0)

    provider = get_model_provider()
    if provider is None:
        return rule_intent

    system_prompt = (
        "你是维修端 AI 维小修的动作意图识别器。"
        "只能从 accept, arrive, start, request_support, support_resolved, "
        "accept_support, reject_support, reject, complete 中选择 action；"
        "如果用户不是要执行工单状态动作，action 返回 null。"
        "必须只输出合法 JSON 对象，不要输出 Markdown，不要解释。"
        "reason 只填写用户明确说出的现场原因或备注，不要写你的分析过程；没有明确原因就返回 null。"
        "reply 只能是简短澄清语，不要说已记录、已提交、已执行或已完成，因为真正执行前还需要二次确认。"
    )
    user_prompt = {
        "context": context_summary,
        "message": message,
        "schema": {
            "action": "string|null",
            "confidence": "0~1",
            "reason": "string|null",
            "result": "fixed|false_alarm|escalated|null",
            "reply": "string|null",
        },
    }
    try:
        raw = await provider.chat(
            [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": json.dumps(user_prompt, ensure_ascii=False)},
            ],
            response_schema={"type": "object"},
            temperature=0,
        )
    except Exception as exc:
        logger.info("维小修模型意图识别降级为规则: %s", exc)
        return rule_intent

    parsed = parse_json_object(raw) or {}
    action = parsed.get("action")
    try:
        confidence = float(parsed.get("confidence") or 0)
    except (TypeError, ValueError):
        confidence = 0.0
    if action in {None, "", "null"}:
        return WorkerIntent(
            action=None,
            confidence=confidence,
            reply=None,
        )
    if action not in _ACTION_LABELS:
        return rule_intent
    return WorkerIntent(
        action=action,
        confidence=confidence,
        reason=_clean_text(parsed.get("reason")) or rule_intent.reason,
        result=parsed.get("result") if parsed.get("result") in {"fixed", "false_alarm", "escalated"} else rule_intent.result,
        reply=_clean_text(parsed.get("reply")) or None,
    )


async def _invalidate_related_cache() -> None:
    await delete_cache_by_prefix("workorders:")
    await delete_cache_by_prefix("incidents:")
    await delete_cache_by_prefix("operations:bundle:")


async def _ensure_session(
    db: AsyncSession,
    *,
    session_id: str,
    user: User,
    work_order: WorkOrder | None,
    state: dict[str, Any] | None = None,
) -> AiAssistantSession:
    session = await db.get(AiAssistantSession, session_id)
    now = datetime.now(timezone.utc)
    if session is None:
        session = AiAssistantSession(
            id=session_id,
            assistant_name="wei_xiao_xiu",
            user_id=user.id,
            role=user.role,
            work_order_id=work_order.id if work_order else None,
            session_state_json=json.dumps(state or {}, ensure_ascii=False, default=str),
            readonly=False,
            created_at=now,
            updated_at=now,
        )
        db.add(session)
    else:
        session.updated_at = now
        session.work_order_id = session.work_order_id or (work_order.id if work_order else None)
        session.session_state_json = json.dumps(state or {}, ensure_ascii=False, default=str)
    await db.flush()
    return session


async def _append_message(
    db: AsyncSession,
    *,
    session_id: str,
    role: str,
    content: str,
    content_type: str = "text",
    model_provider: str | None = None,
    model_name: str | None = None,
) -> None:
    db.add(
        AiAssistantMessage(
            id=str(uuid.uuid4()),
            session_id=session_id,
            role=role,
            content=content,
            content_type=content_type,
            model_provider=model_provider,
            model_name=model_name,
        )
    )


async def _record_action_audit(
    db: AsyncSession,
    *,
    session_id: str,
    work_order: WorkOrder | None,
    action: str,
    user: User,
    dispatch_id: str | None = None,
    hall_entry_id: str | None = None,
    confirmation_text: str | None = None,
    execution_status: str = "pending",
    backend_action_ref: str | None = None,
    error_message: str | None = None,
) -> None:
    db.add(
        AiAssistantActionAudit(
            id=str(uuid.uuid4()),
            session_id=session_id,
            work_order_id=work_order.id if work_order else None,
            dispatch_id=dispatch_id,
            hall_entry_id=hall_entry_id,
            proposed_action=action,
            confirmation_text=confirmation_text,
            execution_status=execution_status,
            backend_action_ref=backend_action_ref,
            error_message=error_message,
        )
    )
    if work_order is not None:
        await write_work_order_audit_log(
            db,
            work_order_id=work_order.id,
            action=f"ai_worker_{execution_status}",
            old_status=work_order.status,
            new_status=work_order.status,
            actor_type="ai",
            actor_id=user.id,
            detail={
                "session_id": session_id,
                "action": action,
                "dispatch_id": dispatch_id,
                "hall_entry_id": hall_entry_id,
                "confirmation_text": confirmation_text,
                "backend_action_ref": backend_action_ref,
                "error_message": error_message,
            },
        )


async def _resolve_work_order(
    db: AsyncSession,
    *,
    ticket_id: str | None,
    dispatch_id: str | None,
    hall_entry_id: str | None,
) -> tuple[WorkOrder | None, DispatchTask | None, DispatchHallEntry | None]:
    hall_entry = await get_dispatch_hall_entry_by_id(db, hall_entry_id) if hall_entry_id else None
    dispatch_task = await get_dispatch_task_by_id(db, dispatch_id) if dispatch_id else None

    work_order: WorkOrder | None = None
    if ticket_id:
        work_order = await get_work_order_by_ticket_id(db, ticket_id)
    elif dispatch_task is not None:
        work_order = await db.get(WorkOrder, dispatch_task.work_order_id)
    elif hall_entry is not None:
        work_order = await db.get(WorkOrder, hall_entry.work_order_id)

    if work_order is not None and dispatch_task is None:
        dispatch_task = await get_current_dispatch_task(db, work_order=work_order)

    return work_order, dispatch_task, hall_entry


async def get_worker_ai_history(
    db: AsyncSession,
    *,
    ticket_id: str,
    dispatch_id: str | None,
    hall_entry_id: str | None,
    limit: int,
    user: User,
) -> dict[str, Any]:
    work_order, dispatch_task, hall_entry = await _resolve_work_order(
        db,
        ticket_id=ticket_id,
        dispatch_id=dispatch_id,
        hall_entry_id=hall_entry_id,
    )
    if work_order is None:
        raise HTTPException(status_code=404, detail="工单不存在")
    _assert_worker_permission(user, work_order, dispatch_task, hall_entry)

    session_filters = [
        AiAssistantSession.assistant_name == "wei_xiao_xiu",
        AiAssistantSession.work_order_id == work_order.id,
        AiAssistantSession.user_id == user.id,
    ]
    latest_session_result = await db.execute(
        select(AiAssistantSession.id)
        .where(*session_filters)
        .order_by(AiAssistantSession.updated_at.desc())
        .limit(1)
    )
    latest_session_id = latest_session_result.scalar_one_or_none()

    history_limit = max(limit * 3, limit)
    message_result = await db.execute(
        select(AiAssistantMessage, AiAssistantSession.id)
        .join(AiAssistantSession, AiAssistantMessage.session_id == AiAssistantSession.id)
        .where(*session_filters)
        .order_by(AiAssistantMessage.created_at.desc())
        .limit(history_limit)
    )
    rows = list(reversed(message_result.all()))
    messages = [
        {
            "id": message.id,
            "session_id": session_id,
            "role": "ai" if message.role == "assistant" else message.role,
            "content": message.content,
            "content_type": message.content_type,
            "created_at": message.created_at.isoformat() if message.created_at else None,
        }
        for message, session_id in rows
        if message.role in {"user", "assistant"} and not _is_worker_ai_action_history_message(message)
    ][-limit:]
    visible_session_id = messages[-1]["session_id"] if messages else None
    return {
        "assistant": "维小修",
        "ticket_id": work_order.ticket_id,
        "session_id": visible_session_id or latest_session_id,
        "messages": messages,
    }


def _is_worker_ai_action_history_message(message: AiAssistantMessage) -> bool:
    content = _clean_text(getattr(message, "content", None))
    content_type = str(getattr(message, "content_type", "") or "")
    role = str(getattr(message, "role", "") or "")
    if not content:
        return True
    if content_type == "tool_result":
        return True
    if content_type in {"guidance_observation", "guidance_reply"}:
        return False

    action_assistant_fragments = (
        "你要执行“",
        "确认后我就替你提交",
        "确认后我会提交",
        "已完成“",
        "无需重复",
        "当前工单已",
        "当前还未",
        "当前派工阶段不支持",
        "我正在等待你确认是否执行上一条动作",
        "请回复“确认”执行",
        "好的，我已取消这次动作",
        "流程语",
        "状态机",
        "我在，咱们直接看现场",
        "这张单已经在处理中",
        "我先按你看到的现场来判断",
        "你把现象、读数、报警码或照片发我一个就行",
        "先把一个现象发我就行",
        "先看这个：",
    )
    if role == "assistant" and any(fragment in content for fragment in action_assistant_fragments):
        return True

    action_user_texts = {
        "确认",
        "取消",
        "开始处理",
        "开始维修",
        "开始排查",
        "确认接单",
        "接单",
        "我接了",
        "确认到场",
        "我已到场",
        "已到场",
        "到场了",
    }
    if role == "user" and content in action_user_texts:
        return True

    return False


def _assert_worker_permission(
    user: User,
    work_order: WorkOrder | None,
    dispatch_task: DispatchTask | None,
    hall_entry: DispatchHallEntry | None,
) -> None:
    if user.role not in {"ops", "admin", "manager"}:
        raise HTTPException(status_code=403, detail="权限不足")
    if user.role != "ops":
        return
    if hall_entry is not None:
        if hall_entry.assigned_to != user.id:
            raise HTTPException(status_code=403, detail="只能操作分配给自己的协同任务")
        return
    if dispatch_task is None or dispatch_task.assigned_to != user.id:
        raise HTTPException(status_code=403, detail="只能操作派发给自己的工单")


def _validate_worker_action_availability(
    *,
    action: str,
    work_order: WorkOrder | None,
    dispatch_task: DispatchTask | None,
    hall_entry: DispatchHallEntry | None,
) -> str | None:
    if action in {"accept_support", "reject_support"}:
        return None if hall_entry is not None else "当前缺少协同任务。"

    if action not in _ACTION_LABELS:
        return "未知动作。"
    if work_order is None or dispatch_task is None:
        return "当前工单缺少有效派工任务。"

    status = (dispatch_task.dispatch_status or "").strip().lower()
    if not status:
        return None

    if action == "accept":
        if status == "assigned":
            return None
        if status in {"accepted", "arrived"}:
            return "当前工单已接单，无需重复确认接单。"
        if status in {"processing", "waiting_support", "supporting"}:
            return "当前工单已进入处理阶段，无需重复确认接单。"
        if status in {"completed", "closed"}:
            return "当前工单已结束，不能再确认接单。"
        return "当前派工阶段不支持确认接单。"

    if action == "arrive":
        if status == "accepted":
            return None
        if status == "assigned":
            return "当前还未接单，请先确认接单。"
        if status == "arrived":
            return "当前工单已到场，无需重复确认到场。"
        if status in {"processing", "waiting_support", "supporting"}:
            return "当前工单已开始处理，无需重复确认到场。"
        if status in {"completed", "closed"}:
            return "当前工单已结束，不能再确认到场。"
        return "当前派工阶段不支持确认到场。"

    if action == "start":
        if status in {"accepted", "arrived"}:
            return None
        if status == "assigned":
            return "当前还未接单，请先确认接单。"
        if status in {"processing", "waiting_support", "supporting"}:
            return "当前工单已开始处理，无需重复开始。"
        if status in {"completed", "closed"}:
            return "当前工单已结束，不能再开始处理。"
        return "当前派工阶段不支持开始处理。"

    if action == "request_support":
        if status in {"arrived", "processing"}:
            return None
        if status == "waiting_support":
            return "当前工单已在协同处理中，无需重复申请协同。"
        if status == "assigned":
            return "当前还未接单，请先确认接单。"
        if status == "accepted":
            return "当前还未到场，请先确认到场。"
        if status in {"completed", "closed"}:
            return "当前工单已结束，不能再申请协同。"
        return "当前派工阶段不支持申请协同。"

    if action == "support_resolved":
        if status == "waiting_support":
            return None
        if status in {"processing", "arrived", "accepted", "assigned"}:
            return "当前工单不在待协同状态，无需标记协同已解决。"
        if status in {"completed", "closed"}:
            return "当前工单已结束，不能再标记协同已解决。"
        return "当前派工阶段不支持标记协同已解决。"

    if action == "reject":
        if status in {"assigned", "accepted"}:
            return None
        if status in {"arrived", "processing", "waiting_support", "supporting"}:
            return "当前工单已进入现场处理阶段，不能再退回改派。"
        if status in {"completed", "closed"}:
            return "当前工单已结束，不能再退回改派。"
        return "当前派工阶段不支持退回改派。"

    if action == "complete":
        if status in {"arrived", "processing", "waiting_support", "supporting"}:
            return None
        if status == "assigned":
            return "当前还未接单，请先确认接单。"
        if status == "accepted":
            return "当前还未开始处理，请先确认到场或开始处理。"
        if status in {"completed", "closed"}:
            return "当前工单已结束，无需重复提交处理完成。"
        return "当前派工阶段不支持提交处理完成。"

    return None


def _dispatch_status(dispatch_task: DispatchTask | None) -> str:
    return (getattr(dispatch_task, "dispatch_status", None) or "").strip().lower()


def _contextual_worker_chat_answer(
    *,
    work_order: WorkOrder | None,
    dispatch_task: DispatchTask | None,
    hall_entry: DispatchHallEntry | None,
    fallback: str | None = None,
) -> str:
    if fallback:
        return fallback
    if hall_entry is not None:
        return "我在。你现在是在协同任务里，可以把现场能支援的内容、限制条件或照片发我；如果要接受或拒绝协同，再直接说“确认协同”或“无法支援，因为...”。"

    status = _dispatch_status(dispatch_task)
    if work_order is not None and (
        getattr(work_order, "processing_started_at", None)
        or status in {"processing", "waiting_support", "supporting"}
    ):
        return "我在，咱们直接看现场。你现在看到的是传感器、控制屏，还是报警记录？先把一个现象发我就行。"
    if status == "assigned":
        return "我在。这张单还没正式接下，你准备接就跟我说一声；想先看看风险点也可以先问。"
    if status == "accepted":
        return "我在。这张单已经接下来了，路上可以先问我重点看哪里；到现场后跟我说一声就行。"
    if status == "arrived":
        return "我在。既然已经到场，先告诉我眼前看到什么：设备状态、屏幕读数，或者有没有报警。"
    if status in {"completed", "closed"} or getattr(work_order, "status", None) in {"completed", "closed"}:
        return "这张单已经收尾了。我可以帮你回看处理记录、现场备注和后续注意点。"
    return "我在。你先说现场看到什么，我再陪你判断下一步。"


async def _generate_worker_chat_reply_with_model(
    *,
    message: str,
    work_order: WorkOrder | None,
    dispatch_task: DispatchTask | None,
    hall_entry: DispatchHallEntry | None,
    client_context: dict[str, Any] | None,
) -> str | None:
    provider = get_model_provider()
    if provider is None:
        return None

    work_order_context: dict[str, Any] = {}
    if work_order is not None:
        work_order_context = {
            "ticket_id": work_order.ticket_id,
            "building_id": work_order.building_id,
            "device_id": work_order.device_id,
            "issue_description": work_order.issue_description,
            "suggested_action": work_order.suggested_action,
            "priority": work_order.priority,
            "status": work_order.status,
            "accepted_at": work_order.accepted_at.isoformat() if work_order.accepted_at else None,
            "arrived_at": work_order.arrived_at.isoformat() if work_order.arrived_at else None,
            "processing_started_at": work_order.processing_started_at.isoformat() if work_order.processing_started_at else None,
        }

    dispatch_context: dict[str, Any] = {}
    if dispatch_task is not None:
        dispatch_context = {
            "dispatch_id": dispatch_task.id,
            "dispatch_status": dispatch_task.dispatch_status,
            "accepted_at": dispatch_task.accepted_at.isoformat() if dispatch_task.accepted_at else None,
            "arrived_at": dispatch_task.arrived_at.isoformat() if dispatch_task.arrived_at else None,
            "processing_started_at": dispatch_task.processing_started_at.isoformat() if dispatch_task.processing_started_at else None,
        }

    hall_context: dict[str, Any] = {}
    if hall_entry is not None:
        hall_context = {
            "hall_entry_id": hall_entry.id,
            "status": hall_entry.status,
            "entry_type": hall_entry.entry_type,
        }

    system_prompt = (
        "你是维修端 AI 助手维小修，正在陪现场维修人员处理一张工单。"
        "普通聊天、现场观察、不会做、还没开始、新手求助、下一步怎么走，都由你自然回答。"
        "接单、到场、开始处理、请求协同、处理完成等状态动作由独立动作层执行；"
        "除非用户明确要求执行这些动作，否则不要把回答写成动作菜单，也不要说已提交或已记录。"
        "不要提后端、状态机、规则、步骤卡片、流程控制这些实现词。"
        "绝对不要输出或复述 step_1、step_2、completed、pending、needs_support、uncertain、event_type、plan_id、dispatch_id 这类内部字段。"
        "如果用户在问进度，不要回答内部步骤编号；改用自然说法，例如“前面外观看过了，眼下更该核对读数和显示链路”。"
        "先回应用户当下处境，再给一个安全、可观察、非侵入的第一步；如果缺关键信息，只问一个最重要的问题。"
        "如果用户说自己是新手或还没开始，要先降低压力，再帮他定位当前位置，最后给第一步。"
        "回答要像一位耐心的维修师傅在旁边说话，尽量 2 到 4 句，不要编号长清单。"
        "不能编造读数、报警码、设备铭牌、维修记录或已经发生的现场事实。"
        "不要编造教室号、房间号、楼层、BA 工作站位置、百分比、时间差、温度值或控制画面细节，除非这些信息已在输入里明确给出。"
        "涉及带电、压力、制冷剂、泄漏、冒烟、异味、异常噪声时先提醒停下观察并找有资质人员协助。"
        "必须只输出 JSON 对象，字段 answer 是给用户看的中文回复。"
    )
    user_prompt = {
        "worker_message": message,
        "work_order": work_order_context,
        "dispatch": dispatch_context,
        "hall_entry": hall_context,
        "client_context": client_context or {},
        "output_schema": {"answer": "string"},
    }
    try:
        raw = await provider.chat(
            [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": json.dumps(user_prompt, ensure_ascii=False, default=str)},
            ],
            response_schema={"type": "object"},
            temperature=0.35,
        )
    except Exception as exc:
        logger.info("维小修自然对话生成降级为本地回复: %s", exc)
        return None

    parsed = parse_json_object(raw) or {}
    answer = _humanize_worker_reply_text(parsed.get("answer"))
    if answer:
        return answer[:1200]
    return None


def _friendly_invalid_action_answer(
    *,
    action: str | None,
    invalid_message: str,
    work_order: WorkOrder | None,
    dispatch_task: DispatchTask | None,
    hall_entry: DispatchHallEntry | None,
) -> str:
    status = _dispatch_status(dispatch_task)
    if action == "accept" and status in {"processing", "waiting_support", "supporting"}:
        return "这张单已经进入处理了，我就不重复提交接单。我们继续看现场：你现在做到哪一步，或者下一步想先看哪里？"
    if action == "start" and status in {"processing", "waiting_support", "supporting"}:
        return "开始处理已经记录过了，不需要再点一次。你把当前读数、报警或第一步结果告诉我，我接着往下带。"
    if action == "arrive" and status in {"processing", "waiting_support", "supporting"}:
        return "到场已经记录过了，现在重点是现场排查。你可以把面板读数、报警码或照片发我，我帮你判断下一步。"
    if action == "accept" and status in {"accepted", "arrived"}:
        return "这张单已经接下来了，不用重复接单。我们继续往下走：到场后说“我已到场”，已经到场就可以描述现场情况。"
    if action == "arrive" and status == "assigned":
        return "我看这张单还没接单。你准备接的话先说“确认接单”，接下来我再陪你走到场和处理。"
    if action == "start" and status == "assigned":
        return "现在还没接单，先别直接开始处理。你准备接的话说“确认接单”，我会按顺序帮你推进。"
    if action == "start" and status == "accepted":
        return "已经接单但还没到场。到现场后先告诉我“我已到场”，再开始处理会更稳。"
    if action == "complete" and status in {"assigned", "accepted"}:
        return "现在还没进入现场处理，先不要提交完成。你可以先接单、到场，或者把现场情况发我，我帮你判断要不要继续。"
    if "无需重复" in invalid_message:
        return f"{invalid_message.rstrip('。')}，我就不重复提交了。我们继续看现场：你可以问我下一步，或直接补充读数、报警和照片。"
    if "不能再" in invalid_message or "不支持" in invalid_message:
        return f"{invalid_message} 我们先别强行改状态，你把现场情况发我，我帮你判断该走协同、升级还是补充记录。"
    return _contextual_worker_chat_answer(
        work_order=work_order,
        dispatch_task=dispatch_task,
        hall_entry=hall_entry,
        fallback=invalid_message,
    )


def _build_pending_action(
    *,
    intent: WorkerIntent,
    work_order: WorkOrder | None,
    dispatch_task: DispatchTask | None,
    hall_entry: DispatchHallEntry | None,
) -> dict[str, Any]:
    assert intent.action is not None
    return {
        "action": intent.action,
        "action_label": _ACTION_LABELS[intent.action],
        "ticket_id": work_order.ticket_id if work_order else None,
        "work_order_id": work_order.id if work_order else None,
        "dispatch_id": dispatch_task.id if dispatch_task else None,
        "hall_entry_id": hall_entry.id if hall_entry else None,
        "reason": intent.reason,
        "result": intent.result or ("fixed" if intent.action == "complete" else None),
        "requires_reason": intent.action in _REASON_REQUIRED,
        "needs_confirmation": intent.action in _CONFIRM_REQUIRED,
        "stage": "awaiting_reason" if intent.action in _REASON_REQUIRED and not intent.reason else "awaiting_confirmation",
    }


def _confirmation_answer(pending: dict[str, Any]) -> str:
    action = pending["action"]
    label = pending.get("action_label") or _ACTION_LABELS.get(action, action)
    reason = pending.get("reason")
    if pending.get("stage") == "awaiting_reason":
        if action == "request_support":
            return "你要请求协同，请先告诉我协同原因，例如缺少配件、需要电气班组支援或现场无法单人处理。"
        if action == "reject_support":
            return "你要拒绝协同，请先告诉我无法支援的原因。"
        return "你要退回/拒绝这张工单，请先告诉我原因，方便调度人员后续改派。"
    suffix = f"原因：{reason}。" if reason else ""
    if action == "complete":
        result = pending.get("result") or "fixed"
        result_label = {"fixed": "已修复", "false_alarm": "误报", "escalated": "升级处理"}.get(result, result)
        suffix = f"处理结果：{result_label}。{suffix}"
    return f"你要执行“{label}”吗？{suffix}确认后我就替你提交这一步。"


async def _execute_pending_action(
    db: AsyncSession,
    *,
    pending: dict[str, Any],
    user: User,
    confirmation_text: str,
) -> dict[str, Any]:
    work_order, dispatch_task, hall_entry = await _resolve_work_order(
        db,
        ticket_id=pending.get("ticket_id"),
        dispatch_id=pending.get("dispatch_id"),
        hall_entry_id=pending.get("hall_entry_id"),
    )
    if work_order is None and pending.get("action") not in {"accept_support", "reject_support"}:
        raise HTTPException(status_code=404, detail="工单不存在")
    _assert_worker_permission(user, work_order, dispatch_task, hall_entry)

    action = pending["action"]
    invalid_message = _validate_worker_action_availability(
        action=action,
        work_order=work_order,
        dispatch_task=dispatch_task,
        hall_entry=hall_entry,
    )
    if invalid_message:
        raise HTTPException(status_code=409, detail=invalid_message)
    reason = _clean_text(pending.get("reason")) or None
    if action in _REASON_REQUIRED and not reason:
        raise HTTPException(status_code=400, detail="当前动作需要原因")

    try:
        if action in _DIRECT_ACTIONS:
            assert work_order is not None
            await record_worker_dispatch_action(
                db,
                work_order=work_order,
                action=action,
                actor_id=user.id,
                notes=reason,
                support_team_id=pending.get("support_team_id"),
            )
            backend_ref = f"work_orders/{work_order.ticket_id}/worker-action:{action}"
            dispatch_id = getattr(dispatch_task, "id", None)
        elif action == "reject":
            if work_order is None or dispatch_task is None:
                raise HTTPException(status_code=409, detail="当前工单缺少有效派工任务")
            await reject_dispatch_task(
                db,
                work_order=work_order,
                dispatch_task=dispatch_task,
                actor_type="worker" if user.role == "ops" else "admin",
                actor_id=user.id,
                reason=reason,
            )
            work_order.dispatch_blocked_reason = reason
            await transition_status(
                db,
                work_order=work_order,
                new_status="pending_dispatch",
                action="dispatch_reject",
                actor_type="worker" if user.role == "ops" else "admin",
                actor_id=user.id,
                detail={"dispatch_id": dispatch_task.id, "reason": reason, "source": "worker_ai"},
            )
            backend_ref = f"dispatch_tasks/{dispatch_task.id}/reject"
            dispatch_id = dispatch_task.id
        elif action == "complete":
            if work_order is None or dispatch_task is None:
                raise HTTPException(status_code=409, detail="当前工单缺少有效派工任务")
            result = pending.get("result") or "fixed"
            await complete_dispatch_task(
                db,
                work_order=work_order,
                dispatch_task=dispatch_task,
                actor_type="worker" if user.role == "ops" else "admin",
                actor_id=user.id,
                result=result,
                notes=reason,
            )
            work_order.worker_result = result
            work_order.worker_notes = reason
            work_order.worker_feedback_at = datetime.now(timezone.utc)
            if result != "needs_parts":
                status_map = {
                    "fixed": "completed",
                    "false_alarm": "false_alarm",
                    "escalated": "escalated",
                }
                await transition_status(
                    db,
                    work_order=work_order,
                    new_status=status_map[result],
                    action="worker_feedback",
                    actor_type="worker" if user.role == "ops" else "admin",
                    actor_id=user.id,
                    detail={"dispatch_id": dispatch_task.id, "result": result, "notes": reason, "source": "worker_ai"},
                )
            backend_ref = f"dispatch_tasks/{dispatch_task.id}/complete"
            dispatch_id = dispatch_task.id
        elif action in {"accept_support", "reject_support"}:
            if hall_entry is None:
                raise HTTPException(status_code=409, detail="当前缺少协同任务")
            if action == "accept_support":
                await accept_assigned_support_hall_entry(db, hall_entry=hall_entry, actor_id=user.id)
                event_type = "support_worker_accepted"
                audit_action = "dispatch_hall_support_accept"
            else:
                await reject_assigned_support_hall_entry(db, hall_entry=hall_entry, actor_id=user.id, note=reason)
                event_type = "support_worker_rejected"
                audit_action = "dispatch_hall_support_reject"
            work_order = await db.get(WorkOrder, hall_entry.work_order_id)
            if hall_entry.source_dispatch_id:
                source_dispatch = await get_dispatch_task_by_id(db, hall_entry.source_dispatch_id)
                if source_dispatch is not None:
                    await record_dispatch_event(
                        db,
                        dispatch_task=source_dispatch,
                        event_type=event_type,
                        actor_type="worker",
                        actor_id=user.id,
                        payload={"hall_entry_id": hall_entry.id, "note": reason, "source": "worker_ai"},
                    )
            if work_order is not None:
                await write_work_order_audit_log(
                    db,
                    work_order_id=work_order.id,
                    action=audit_action,
                    old_status=work_order.status,
                    new_status=work_order.status,
                    actor_type="worker",
                    actor_id=user.id,
                    detail={"hall_entry_id": hall_entry.id, "note": reason, "source": "worker_ai"},
                )
            backend_ref = f"dispatch_hall/{hall_entry.id}/{action}"
            dispatch_id = hall_entry.source_dispatch_id
        else:
            raise HTTPException(status_code=400, detail="未知动作")
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    if work_order is not None and dispatch_task is not None:
        sync_work_order_status_dimensions(work_order, dispatch_task=dispatch_task)

    await _record_action_audit(
        db,
        session_id=pending["session_id"],
        work_order=work_order,
        action=action,
        user=user,
        dispatch_id=dispatch_id,
        hall_entry_id=getattr(hall_entry, "id", None),
        confirmation_text=confirmation_text,
        execution_status="executed",
        backend_action_ref=backend_ref,
    )
    await db.commit()
    if action == "complete" and work_order is not None and reason:
        schedule_experience_capture(
            actor_user_id=user.id,
            actor_role=user.role,
            source_type="completion_summary",
            source_text=reason,
            source_work_order_id=work_order.ticket_id,
            source_dispatch_id=dispatch_id,
            contributor_user_id=user.id,
            contributor_role=user.role,
            building_id=work_order.building_id,
            device_id=work_order.device_id,
        )
    await _invalidate_related_cache()

    return {
        "action": action,
        "action_label": _ACTION_LABELS.get(action, action),
        "status": "success",
        "backend_action_ref": backend_ref,
        "work_order_status": getattr(work_order, "status", None),
        "dispatch_id": dispatch_id,
        "hall_entry": serialize_dispatch_hall_entry(hall_entry) if hall_entry is not None else None,
    }


async def handle_worker_ai_chat(
    db: AsyncSession,
    *,
    message: str,
    session_id: str | None,
    ticket_id: str | None,
    dispatch_id: str | None,
    hall_entry_id: str | None,
    user: User,
    client_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    session_id = session_id or f"wx_{uuid.uuid4().hex}"
    text = _clean_text(message)
    if not text:
        raise HTTPException(status_code=400, detail="消息不能为空")

    work_order, dispatch_task, hall_entry = await _resolve_work_order(
        db,
        ticket_id=ticket_id,
        dispatch_id=dispatch_id,
        hall_entry_id=hall_entry_id,
    )
    if work_order is None and hall_entry is None:
        raise HTTPException(status_code=404, detail="工单不存在")
    _assert_worker_permission(user, work_order, dispatch_task, hall_entry)

    pending = _PENDING_ACTIONS.get(session_id)
    if pending is not None:
        pending["session_id"] = session_id
        if _is_cancel(text):
            _PENDING_ACTIONS.pop(session_id, None)
            await _ensure_session(db, session_id=session_id, user=user, work_order=work_order, state={})
            await _append_message(db, session_id=session_id, role="user", content=text)
            answer = "好的，我已取消这次动作。工单状态不会变化。"
            await _append_message(db, session_id=session_id, role="assistant", content=answer)
            await db.commit()
            return {
                "assistant": "维小修",
                "session_id": session_id,
                "message_type": "chat",
                "answer": answer,
                "pending_action": None,
                "executed": False,
            }

        if pending.get("stage") == "awaiting_reason":
            reason = _extract_reason(text, pending.get("action")) or text
            pending["reason"] = reason
            pending["stage"] = "awaiting_confirmation"
            _PENDING_ACTIONS[session_id] = pending
            await _ensure_session(db, session_id=session_id, user=user, work_order=work_order, state={"pending_action": pending})
            await _append_message(db, session_id=session_id, role="user", content=text)
            answer = _confirmation_answer(pending)
            await _append_message(db, session_id=session_id, role="assistant", content=answer)
            await db.commit()
            return {
                "assistant": "维小修",
                "session_id": session_id,
                "message_type": "action_confirmation",
                "answer": answer,
                "pending_action": pending,
                "executed": False,
            }

        if _is_confirm(text):
            pending["session_id"] = session_id
            await _ensure_session(db, session_id=session_id, user=user, work_order=work_order, state={"pending_action": pending})
            await _append_message(db, session_id=session_id, role="user", content=text)
            try:
                action_result = await _execute_pending_action(
                    db,
                    pending=pending,
                    user=user,
                    confirmation_text=text,
                )
            except HTTPException as exc:
                _PENDING_ACTIONS.pop(session_id, None)
                if exc.status_code >= 500:
                    raise
                answer = _friendly_invalid_action_answer(
                    action=pending.get("action"),
                    invalid_message=str(exc.detail or "当前动作执行失败，请稍后重试"),
                    work_order=work_order,
                    dispatch_task=dispatch_task,
                    hall_entry=hall_entry,
                )
                await _record_action_audit(
                    db,
                    session_id=session_id,
                    work_order=work_order,
                    action=pending.get("action") or "unknown",
                    user=user,
                    dispatch_id=pending.get("dispatch_id"),
                    hall_entry_id=pending.get("hall_entry_id"),
                    confirmation_text=text,
                    execution_status="failed",
                    error_message=answer,
                )
                await _append_message(db, session_id=session_id, role="assistant", content=answer, content_type="tool_result")
                await db.commit()
                return {
                    "assistant": "维小修",
                    "session_id": session_id,
                    "message_type": "chat",
                    "answer": answer,
                    "pending_action": None,
                    "executed": False,
                }
            except Exception:
                _PENDING_ACTIONS.pop(session_id, None)
                raise
            _PENDING_ACTIONS.pop(session_id, None)
            answer = f"已完成“{action_result['action_label']}”。"
            if action_result["action"] == "accept":
                answer += " 下一步到达现场后，你可以对我说“我已到场”。"
            elif action_result["action"] == "arrive":
                answer += " 准备排查时，你可以对我说“开始处理”。"
            elif action_result["action"] == "start":
                answer += " 我会按当前工单生成现场排查步骤，接下来你可以直接问我下一步看哪里。"
            await _append_message(db, session_id=session_id, role="assistant", content=answer, content_type="tool_result")
            await db.commit()
            return {
                "assistant": "维小修",
                "session_id": session_id,
                "message_type": "action_result",
                "answer": answer,
                "pending_action": None,
                "executed": True,
                "action_result": action_result,
            }

        answer = "我正在等待你确认是否执行上一条动作。请回复“确认”执行，或回复“取消”。"
        return {
            "assistant": "维小修",
            "session_id": session_id,
            "message_type": "action_confirmation",
            "answer": answer,
            "pending_action": pending,
            "executed": False,
        }

    context_summary = json.dumps(
        {
            "ticket_id": getattr(work_order, "ticket_id", None),
            "work_order_status": getattr(work_order, "status", None),
            "dispatch_status": getattr(dispatch_task, "dispatch_status", None),
            "hall_entry_status": getattr(hall_entry, "status", None),
            "client_context": client_context or {},
        },
        ensure_ascii=False,
        default=str,
    )
    intent = await classify_worker_intent(text, context_summary=context_summary)
    await _ensure_session(db, session_id=session_id, user=user, work_order=work_order, state={})
    await _append_message(db, session_id=session_id, role="user", content=text)

    if intent.action is None or intent.confidence < 0.65:
        answer = await _generate_worker_chat_reply_with_model(
            message=text,
            work_order=work_order,
            dispatch_task=dispatch_task,
            hall_entry=hall_entry,
            client_context=client_context,
        ) or _contextual_worker_chat_answer(
            work_order=work_order,
            dispatch_task=dispatch_task,
            hall_entry=hall_entry,
        )
        await _append_message(db, session_id=session_id, role="assistant", content=answer)
        await db.commit()
        return {
            "assistant": "维小修",
            "session_id": session_id,
            "message_type": "chat",
            "answer": answer,
            "pending_action": None,
            "executed": False,
        }

    invalid_message = _validate_worker_action_availability(
        action=intent.action,
        work_order=work_order,
        dispatch_task=dispatch_task,
        hall_entry=hall_entry,
    )
    if invalid_message:
        answer = _friendly_invalid_action_answer(
            action=intent.action,
            invalid_message=invalid_message,
            work_order=work_order,
            dispatch_task=dispatch_task,
            hall_entry=hall_entry,
        )
        await _append_message(db, session_id=session_id, role="assistant", content=answer)
        await db.commit()
        return {
            "assistant": "维小修",
            "session_id": session_id,
            "message_type": "chat",
            "answer": answer,
            "pending_action": None,
            "executed": False,
        }

    pending = _build_pending_action(
        intent=intent,
        work_order=work_order,
        dispatch_task=dispatch_task,
        hall_entry=hall_entry,
    )
    pending["session_id"] = session_id
    _PENDING_ACTIONS[session_id] = pending
    await _ensure_session(db, session_id=session_id, user=user, work_order=work_order, state={"pending_action": pending})
    await _record_action_audit(
        db,
        session_id=session_id,
        work_order=work_order,
        action=intent.action,
        user=user,
        dispatch_id=pending.get("dispatch_id"),
        hall_entry_id=pending.get("hall_entry_id"),
        execution_status="pending",
    )
    answer = _confirmation_answer(pending)
    await _append_message(db, session_id=session_id, role="assistant", content=answer)
    await db.commit()
    return {
        "assistant": "维小修",
        "session_id": session_id,
        "message_type": "action_confirmation",
        "answer": answer,
        "pending_action": pending,
        "executed": False,
    }
