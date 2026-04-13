from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AiAssistantMessage, AiAssistantSession, AiMediaAsset, User, WorkerAiStepEvent, WorkerAiStepPlan
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


def _is_guidance_query(text: str) -> bool:
    normalized = text or ""
    keywords = (
        "维修指导",
        "指导记录",
        "步骤卡片",
        "维修步骤",
        "排查步骤",
        "做到哪一步",
        "图片分析",
        "语音转写",
        "现场图片",
    )
    return any(token in normalized for token in keywords)


def _select_current_step(steps: list[dict[str, Any]]) -> dict[str, Any] | None:
    return (
        next((step for step in steps if step.get("status") in {"pending", "uncertain"}), None)
        or next((step for step in steps if step.get("status") == "needs_support"), None)
        or next((step for step in steps if step.get("status") not in {"completed", "skipped"}), None)
    )


async def _build_guidance_record_summary(
    db: AsyncSession,
    *,
    work_order_id: str,
    ticket_id: str,
) -> dict[str, Any]:
    result = await db.execute(
        select(WorkerAiStepPlan)
        .where(WorkerAiStepPlan.work_order_id == work_order_id)
        .order_by(WorkerAiStepPlan.updated_at.desc())
        .limit(1)
    )
    plan = result.scalar_one_or_none()
    if plan is None:
        answer = f"{ticket_id} 还没有维修指导记录。通常要在工单进入开始处理后，维小修才会生成步骤卡片。"
        return {
            "answer": answer,
            "facts": {"plan": None, "recent_events": [], "media_summary": {}},
            "evidence_refs": ["worker_ai_step_plans"],
            "suggested_followups": ["查看这张工单是否已开始处理", "查看当前派工阶段"],
        }

    steps = json.loads(plan.steps_json or "[]")
    if not isinstance(steps, list):
        steps = []
    current_step = _select_current_step(steps)
    status_counts = {
        "completed": sum(1 for step in steps if step.get("status") == "completed"),
        "skipped": sum(1 for step in steps if step.get("status") == "skipped"),
        "needs_support": sum(1 for step in steps if step.get("status") == "needs_support"),
        "pending": sum(1 for step in steps if step.get("status") in {"pending", "uncertain"}),
    }

    event_result = await db.execute(
        select(WorkerAiStepEvent)
        .where(WorkerAiStepEvent.plan_id == plan.id)
        .order_by(WorkerAiStepEvent.created_at.desc())
        .limit(8)
    )
    recent_events = [
        {
            "step_id": event.step_id,
            "event_type": event.event_type,
            "note": event.note,
            "created_at": event.created_at.isoformat() if event.created_at else None,
        }
        for event in event_result.scalars().all()
    ]

    media_result = await db.execute(
        select(AiMediaAsset)
        .where(AiMediaAsset.work_order_id == work_order_id)
        .order_by(AiMediaAsset.created_at.desc())
        .limit(20)
    )
    media_items = media_result.scalars().all()
    image_count = sum(1 for item in media_items if item.media_type == "image")
    audio_count = sum(1 for item in media_items if item.media_type == "audio")

    parts = [
        f"{ticket_id} 当前已有 1 份维修指导计划，版本 {plan.version}，状态 {plan.status}。",
        f"步骤进度：完成 {status_counts['completed']} 步，跳过 {status_counts['skipped']} 步，待处理 {status_counts['pending']} 步，需要协同 {status_counts['needs_support']} 步。",
    ]
    if current_step:
        parts.append(
            f"当前建议步骤是“{current_step.get('title')}”，状态为 {current_step.get('status')}。"
        )
    if recent_events:
        latest_event = recent_events[0]
        latest_note = f"，备注：{latest_event['note']}" if latest_event.get("note") else ""
        parts.append(
            f"最近一条指导记录是步骤 {latest_event.get('step_id')} 的 {latest_event.get('event_type')}，时间 {latest_event.get('created_at')}{latest_note}。"
        )
    if image_count or audio_count:
        parts.append(f"现场媒体记录：图片 {image_count} 份，语音 {audio_count} 份。")

    return {
        "answer": " ".join(parts),
        "facts": {
            "plan": {
                "plan_id": plan.id,
                "status": plan.status,
                "version": plan.version,
                "summary": plan.summary,
                "current_step": current_step,
                "status_counts": status_counts,
                "updated_at": plan.updated_at.isoformat() if plan.updated_at else None,
            },
            "recent_events": recent_events,
            "media_summary": {"image_count": image_count, "audio_count": audio_count},
        },
        "evidence_refs": [
            "worker_ai_step_plans.summary",
            "worker_ai_step_events",
            "ai_media_assets",
        ],
        "suggested_followups": ["查看当前步骤详情", "查看最近一次图片或语音记录"],
    }


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
        work_order = context.get("work_order") or {}
        if _is_guidance_query(text):
            guidance = await _build_guidance_record_summary(
                db,
                work_order_id=str(work_order.get("id") or ""),
                ticket_id=resolved_ticket_id,
            )
            answer = guidance["answer"]
            await _append_message(db, session_id=session_id, role="assistant", content=answer)
            await db.commit()
            return {
                "assistant": "运小维",
                "session_id": session_id,
                "answer_type": "worker_guidance_record",
                "answer": answer,
                "readonly": True,
                "facts": guidance["facts"],
                "metrics": {},
                "evidence_refs": guidance["evidence_refs"] if include_evidence else [],
                "suggested_followups": guidance["suggested_followups"],
                "blocked_actions": [],
            }
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
