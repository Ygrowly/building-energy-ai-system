from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    AiAssistantMessage,
    AiAssistantSession,
    AiMediaAsset,
    User,
    WorkOrder,
    WorkerAiStepEvent,
    WorkerAiStepPlan,
)
from app.services.maintenance_experience_service import (
    build_operator_experience_answer,
    looks_like_experience_query,
)
from app.services.work_order_analysis_service import (
    build_work_order_facts_response,
    extract_work_order_analysis_scope,
    infer_work_order_analysis_intent,
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


def _format_guidance_step_status(status: str | None) -> str:
    labels = {
        "pending": "待处理",
        "uncertain": "待判断",
        "needs_support": "待协同",
        "completed": "已完成",
        "skipped": "已跳过",
        "active": "进行中",
        "not_ready": "未就绪",
        "not_generated": "未生成",
    }
    normalized = (status or "").strip().lower()
    return labels.get(normalized, status or "未知")


def _format_guidance_event_type(event_type: str | None) -> str:
    labels = {
        "generate": "生成步骤卡片",
        "note": "记录备注",
        "completed": "标记完成",
        "skipped": "标记跳过",
        "needs_support": "标记待协同",
        "uncertain": "标记待判断",
        "worker_observation": "现场补充记录",
    }
    normalized = (event_type or "").strip().lower()
    return labels.get(normalized, event_type or "状态更新")


def _format_guidance_time(value: datetime | str | None) -> str:
    if value is None:
        return "--"
    if isinstance(value, datetime):
        target = value.astimezone(timezone.utc) if value.tzinfo else value.replace(tzinfo=timezone.utc)
        return target.astimezone().strftime("%Y-%m-%d %H:%M")
    text = str(value).strip()
    if not text:
        return "--"
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        target = parsed.astimezone(timezone.utc) if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
        return target.astimezone().strftime("%Y-%m-%d %H:%M")
    except ValueError:
        return text


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
        answer = f"{ticket_id} 还没有维修指导记录。通常要在工单开始处理后，维小修才会生成步骤卡片。"
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

    latest_event = recent_events[0] if recent_events else None
    latest_note = f"，备注：{latest_event['note']}" if latest_event and latest_event.get("note") else ""
    parts = [
        f"{ticket_id} 已生成 1 份维修指导，当前版本 {plan.version}，状态：{_format_guidance_step_status(plan.status)}。",
        f"步骤进度：已完成 {status_counts['completed']} 步，已跳过 {status_counts['skipped']} 步，待处理 {status_counts['pending']} 步，需要协同 {status_counts['needs_support']} 步。",
    ]
    if current_step:
        parts.append(
            f"当前进行到“{current_step.get('title')}”，状态：{_format_guidance_step_status(str(current_step.get('status') or 'pending'))}。"
        )
    if latest_event:
        parts.append(
            f"最近一条记录：步骤 {latest_event.get('step_id')} 在 {_format_guidance_time(latest_event.get('created_at'))} {_format_guidance_event_type(latest_event.get('event_type'))}{latest_note}。"
        )
    parts.append(f"现场媒体：图片 {image_count} 份，语音 {audio_count} 份。")

    return {
        "answer": "\n".join(parts),
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


def _safe_session_state(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except (TypeError, ValueError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _should_reuse_previous_analysis_scope(text: str) -> bool:
    normalized = text.strip()
    if not normalized:
        return False
    followup_tokens = ("那", "再", "继续", "换成", "改成", "拆开", "对比", "比较", "顺便", "另外", "上周", "上月")
    return any(token in normalized for token in followup_tokens) or len(normalized) <= 20


def _build_operator_analysis_scope(
    *,
    text: str,
    scope: dict[str, Any] | None,
    previous_state: dict[str, Any],
) -> dict[str, Any]:
    previous_scope = previous_state.get("analysis_scope") if isinstance(previous_state.get("analysis_scope"), dict) else None
    candidate_scope = dict(scope or {})
    if previous_scope and _should_reuse_previous_analysis_scope(text):
        merged_scope = extract_work_order_analysis_scope(
            question=text,
            scope=candidate_scope,
            previous_scope=previous_scope,
            intent=str(previous_scope.get("intent") or ""),
        )
    else:
        merged_scope = extract_work_order_analysis_scope(
            question=text,
            scope=candidate_scope,
            previous_scope=None,
            intent=None,
        )
    return merged_scope


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
    include_chart: bool = True,
    user: User,
) -> dict[str, Any]:
    if user.role not in {"admin", "manager"}:
        raise HTTPException(status_code=403, detail="运小维第一版仅面向运维管理角色开放")

    text = (message or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="消息不能为空")
    session_id = session_id or f"opai_{uuid.uuid4().hex}"
    existing_session = await db.get(AiAssistantSession, session_id) if hasattr(db, "get") else None
    previous_state = _safe_session_state(getattr(existing_session, "session_state_json", None))
    session_state: dict[str, Any] = {"scope": scope or {}}
    await _ensure_session(db, session_id=session_id, user=user, state=session_state)
    await _append_message(db, session_id=session_id, role="user", content=text)

    blocked_actions = _detect_blocked_actions(text)
    if blocked_actions:
        answer = "我可以帮你查看工单状态、候选人建议和流程依据，但运小维第一版只做查询和解释，不会直接执行改派、关闭或审批。"
        await _append_message(db, session_id=session_id, role="assistant", content=answer)
        await db.commit()
        return {
            "assistant": "运小维",
            "session_id": session_id,
            "answer": answer,
            "readonly": True,
            "facts": [],
            "metrics": {},
            "chart": None,
            "evidence_refs": [],
            "suggested_followups": ["查看这张工单的流程", "查看当前责任人和超时风险"],
            "blocked_actions": blocked_actions,
        }

    resolved_ticket_id = ticket_id or _extract_ticket_id(text)
    if resolved_ticket_id:
        context = await build_work_order_review_context(db, ticket_id=resolved_ticket_id)
        if context is None:
            raise HTTPException(status_code=404, detail=f"工单 {resolved_ticket_id} 不存在")
        work_order_data = context.get("work_order") or {}

        if looks_like_experience_query(text):
            work_order_result = await db.execute(select(WorkOrder).where(WorkOrder.ticket_id == resolved_ticket_id).limit(1))
            work_order_row = work_order_result.scalar_one_or_none()
            experience_answer = await build_operator_experience_answer(
                db,
                actor_role=user.role,
                message=text,
                work_order=work_order_row,
            )
            answer = experience_answer["answer"]
            await _append_message(db, session_id=session_id, role="assistant", content=answer)
            await db.commit()
            return {
                "assistant": "运小维",
                "session_id": session_id,
                "answer_type": "maintenance_experience_summary",
                "answer": answer,
                "readonly": True,
                "facts": experience_answer["facts"],
                "metrics": {},
                "chart": None,
                "evidence_refs": experience_answer["evidence_refs"] if include_evidence else [],
                "suggested_followups": experience_answer["suggested_followups"],
                "blocked_actions": [],
            }

        if _is_guidance_query(text):
            guidance = await _build_guidance_record_summary(
                db,
                work_order_id=str(work_order_data.get("id") or ""),
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
                "chart": None,
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
            "chart": None,
            "evidence_refs": evidence_refs,
            "suggested_followups": ["查看是否超时", "查看派工和协同记录"],
            "blocked_actions": [],
        }

    if looks_like_experience_query(text):
        experience_answer = await build_operator_experience_answer(
            db,
            actor_role=user.role,
            message=text,
            work_order=None,
        )
        answer = experience_answer["answer"]
        await _append_message(db, session_id=session_id, role="assistant", content=answer)
        await db.commit()
        return {
            "assistant": "运小维",
            "session_id": session_id,
            "answer_type": "maintenance_experience_summary",
            "answer": answer,
            "readonly": True,
            "facts": experience_answer["facts"],
            "metrics": {},
            "chart": None,
            "evidence_refs": experience_answer["evidence_refs"] if include_evidence else [],
            "suggested_followups": experience_answer["suggested_followups"],
            "blocked_actions": [],
        }

    analysis_scope = _build_operator_analysis_scope(
        text=text,
        scope=scope,
        previous_state=previous_state,
    )
    analysis_response = await build_work_order_facts_response(
        db,
        question=text,
        intent=str(analysis_scope.get("intent") or infer_work_order_analysis_intent(text)),
        scope=analysis_scope,
        include_chart=include_chart,
    )
    answer = str(analysis_response.get("answer") or "我已完成只读运营分析。")
    session_state["analysis_scope"] = analysis_response.get("facts", {}).get("scope") or analysis_scope
    session_state["last_intent"] = analysis_response.get("intent")
    await _ensure_session(db, session_id=session_id, user=user, state=session_state)
    await _append_message(db, session_id=session_id, role="assistant", content=answer)
    await db.commit()
    return {
        "assistant": "运小维",
        "session_id": session_id,
        "answer_type": analysis_response.get("intent", "operations_analysis"),
        "answer": answer,
        "readonly": True,
        "facts": analysis_response.get("facts") or {},
        "metrics": analysis_response.get("metrics") or {},
        "chart": analysis_response.get("chart"),
        "evidence_refs": analysis_response.get("evidence_refs") if include_evidence else [],
        "suggested_followups": analysis_response.get("suggested_followups") or ["查看超时工单", "按班组拆分", "对比上一周期"],
        "blocked_actions": [],
    }
