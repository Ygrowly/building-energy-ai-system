from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AiAssistantMessage, AiAssistantSession, User
from app.services.work_order_insights_service import (
    build_work_order_insight_metrics,
    build_work_order_insight_query_response,
)
from app.services.work_order_review_context_service import build_work_order_review_context


def _extract_ticket_id(text: str) -> str | None:
    match = re.search(r"WO-\d{8}-\d{3,}", text or "", re.IGNORECASE)
    return match.group(0).upper() if match else None


def _detect_blocked_actions(text: str) -> list[str]:
    normalized = text or ""
    blocked: list[str] = []
    if any(token in normalized for token in ("改派", "派给")):
        blocked.append("reassign_dispatch")
    if any(token in normalized for token in ("关闭", "确认关闭")):
        blocked.append("close_work_order")
    if any(token in normalized for token in ("审批", "通过审批", "驳回")):
        blocked.append("approve_work_order")
    if "取消派工" in normalized:
        blocked.append("cancel_dispatch")
    if "拒绝" in normalized and "拒单" not in normalized:
        blocked.append("reject")
    return list(dict.fromkeys(blocked))


async def _ensure_session(
    db: AsyncSession,
    *,
    session_id: str,
    user: User,
    state: dict[str, Any] | None = None,
) -> AiAssistantSession:
    session = await db.get(AiAssistantSession, session_id)
    now = datetime.now(timezone.utc)
    if session is None:
        session = AiAssistantSession(
            id=session_id,
            assistant_name="yun_xiao_wei",
            user_id=user.id,
            role=user.role,
            session_state_json=json.dumps(state or {}, ensure_ascii=False, default=str),
            readonly=True,
            created_at=now,
            updated_at=now,
        )
        db.add(session)
    else:
        session.updated_at = now
        session.session_state_json = json.dumps(state or {}, ensure_ascii=False, default=str)
        session.readonly = True
    await db.flush()
    return session


async def _append_message(
    db: AsyncSession,
    *,
    session_id: str,
    role: str,
    content: str,
    content_type: str = "text",
) -> None:
    db.add(
        AiAssistantMessage(
            id=str(uuid.uuid4()),
            session_id=session_id,
            role=role,
            content=content,
            content_type=content_type,
        )
    )


def _timeline_answer(context: dict[str, Any], question: str) -> str:
    work_order = context.get("work_order") or {}
    current_dispatch = context.get("current_dispatch") or {}
    dispatch_tasks = context.get("dispatch_tasks") or []
    audit_logs = context.get("audit_logs") or []
    risk_flags = context.get("risk_flags") or []
    ticket_id = context.get("ticket_id") or work_order.get("ticket_id") or "这张工单"
    assignee = (
        current_dispatch.get("assigned_to_name")
        or current_dispatch.get("assigned_to")
        or work_order.get("assigned_to_name")
        or "暂无当前责任人"
    )
    status = work_order.get("status") or "--"
    dispatch_status = current_dispatch.get("dispatch_status") or current_dispatch.get("execution_status") or "--"
    accepted_at = current_dispatch.get("accepted_at") or work_order.get("accepted_at")
    arrived_at = current_dispatch.get("arrived_at") or work_order.get("arrived_at")
    started_at = current_dispatch.get("processing_started_at") or work_order.get("processing_started_at")
    latest_note = current_dispatch.get("latest_note") or work_order.get("dispatch_blocked_reason") or ""

    risk_text = ""
    if risk_flags:
        risk_text = " 风险提示：" + "；".join(str(item.get("message") or item.get("code")) for item in risk_flags[:3])

    if any(token in question for token in ("谁接", "责任人", "谁处理", "谁接的")):
        return f"{ticket_id} 当前责任人是 {assignee}，派工阶段为 {dispatch_status}。"

    if any(token in question for token in ("流程", "过程", "时间线", "到哪一步")):
        steps = [
            f"当前状态 {status}",
            f"派工阶段 {dispatch_status}",
            f"责任人 {assignee}",
        ]
        if accepted_at:
            steps.append(f"已接单 {accepted_at}")
        if arrived_at:
            steps.append(f"已到场 {arrived_at}")
        if started_at:
            steps.append(f"已开始处理 {started_at}")
        if latest_note:
            steps.append(f"最新备注 {latest_note}")
        if dispatch_tasks:
            steps.append(f"历史派工尝试 {len(dispatch_tasks)} 次")
        if audit_logs:
            steps.append(f"审计记录 {len(audit_logs)} 条")
        return f"{ticket_id} 的流程概况：" + "；".join(steps) + "。" + risk_text

    return context.get("ai_context_summary") or f"{ticket_id} 当前状态为 {status}，责任人是 {assignee}，派工阶段为 {dispatch_status}。" + risk_text


async def handle_operator_ai_chat(
    db: AsyncSession,
    *,
    message: str,
    session_id: str | None,
    ticket_id: str | None,
    scope: dict[str, Any] | None,
    include_evidence: bool,
    user: User,
) -> dict[str, Any]:
    if user.role not in {"admin", "manager"}:
        raise HTTPException(status_code=403, detail="运小维第一版仅面向运维管理角色开放")

    text = (message or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="消息不能为空")
    session_id = session_id or f"opai_{uuid.uuid4().hex}"
    await _ensure_session(db, session_id=session_id, user=user, state={"scope": scope or {}})
    await _append_message(db, session_id=session_id, role="user", content=text)

    blocked_actions = _detect_blocked_actions(text)
    if blocked_actions:
        answer = "我可以帮你查看工单状态、候选人建议和流程依据，但运小维第一版只做查和解释，不会直接执行改派、关闭或审批。"
        await _append_message(db, session_id=session_id, role="assistant", content=answer)
        await db.commit()
        return {
            "assistant": "运小维",
            "session_id": session_id,
            "answer": answer,
            "readonly": True,
            "facts": [],
            "metrics": {},
            "evidence_refs": [],
            "suggested_followups": ["查看这张工单的流程", "查看当前责任人和超时风险"],
            "blocked_actions": blocked_actions,
        }

    resolved_ticket_id = ticket_id or _extract_ticket_id(text)
    if resolved_ticket_id:
        context = await build_work_order_review_context(db, ticket_id=resolved_ticket_id)
        if context is None:
            raise HTTPException(status_code=404, detail=f"工单 {resolved_ticket_id} 不存在")
        answer = _timeline_answer(context, text)
        evidence_refs = [
            "work_order.status",
            "current_dispatch.assigned_to",
            "current_dispatch.dispatch_status",
            "dispatch_tasks",
            "audit_logs",
        ] if include_evidence else []
        await _append_message(db, session_id=session_id, role="assistant", content=answer)
        await db.commit()
        return {
            "assistant": "运小维",
            "session_id": session_id,
            "answer_type": "single_work_order_summary",
            "answer": answer,
            "readonly": True,
            "facts": context,
            "metrics": {},
            "evidence_refs": evidence_refs,
            "suggested_followups": ["查看是否超时", "查看派工和协同记录"],
            "blocked_actions": [],
        }

    metrics = await build_work_order_insight_metrics(db)
    response = build_work_order_insight_query_response(question=text, metrics=metrics)
    answer = response.get("answer") or "我已查询工单运营指标。"
    await _append_message(db, session_id=session_id, role="assistant", content=answer)
    await db.commit()
    return {
        "assistant": "运小维",
        "session_id": session_id,
        "answer_type": response.get("intent", "operations_metric"),
        "answer": answer,
        "readonly": True,
        "facts": [],
        "metrics": response.get("metrics") or metrics,
        "evidence_refs": ["work_order_insights.metrics"] if include_evidence else [],
        "suggested_followups": ["查看超时工单", "查看维修人员负载", "查看待关闭工单"],
        "blocked_actions": [],
    }
