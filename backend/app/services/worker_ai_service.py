from __future__ import annotations

import json
import logging
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Literal

from fastapi import HTTPException
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

    provider = get_model_provider()
    if provider is None:
        return rule_intent

    system_prompt = (
        "你是维修端 AI 维小修的动作意图识别器。"
        "只能从 accept, arrive, start, request_support, support_resolved, "
        "accept_support, reject_support, reject, complete 中选择 action；"
        "如果用户不是要执行工单状态动作，action 返回 null。"
        "只输出 JSON，不要输出解释。"
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
    if action not in _ACTION_LABELS:
        return rule_intent
    try:
        confidence = float(parsed.get("confidence") or 0)
    except (TypeError, ValueError):
        confidence = 0.0
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
    return f"你要执行“{label}”吗？{suffix}确认后我会提交到后端状态机。"


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
    reason = _clean_text(pending.get("reason")) or None
    if action in _REASON_REQUIRED and not reason:
        raise HTTPException(status_code=400, detail="当前动作需要原因")

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
                answer += " 已进入处理阶段。阶段二会继续接入维修步骤指导。"
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
        answer = intent.reply or "我可以帮你执行接单、到场、开始处理、请求协同和完成等工单动作。你也可以继续描述现场情况。"
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
