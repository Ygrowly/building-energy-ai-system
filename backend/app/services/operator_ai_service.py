from __future__ import annotations

import json
import re
import uuid
from datetime import date, datetime, time, timedelta, timezone
from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    AiAssistantMessage,
    AiAssistantSession,
    AiMediaAsset,
    DispatchTask,
    User,
    WorkOrder,
    WorkerTeam,
    WorkerAiStepEvent,
    WorkerAiStepPlan,
)
from app.core.person_name import extract_person_display_aliases, format_person_display_name
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
    match = re.search(
        r"(?<![A-Z0-9_])((?:WO(?:-[A-Z0-9]+)+)|(?:temp_[A-Z0-9_]+))(?![A-Z0-9_-])",
        text or "",
        re.IGNORECASE,
    )
    if not match:
        return None
    ticket_id = match.group(1)
    if ticket_id.upper().startswith("WO-"):
        return ticket_id.upper()
    return ticket_id


def _coerce_scope_date(value: Any) -> date | None:
    if value in (None, ""):
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    try:
        return date.fromisoformat(str(value))
    except ValueError:
        return None


def _looks_like_single_work_order_question(text: str) -> bool:
    normalized = re.sub(r"\s+", "", text or "")
    if not normalized:
        return False
    return any(
        token in normalized
        for token in (
            "流程",
            "全流程",
            "过程",
            "时间线",
            "流转",
            "链路",
            "流转链路",
            "完整链路",
            "完整流转链路",
            "到哪一步",
            "谁接",
            "责任人",
            "谁处理",
            "当前状态",
            "状态",
            "进度",
            "超时",
            "协同",
            "改派",
            "误报",
            "为什么",
            "为何",
            "原因",
        )
    )


def _looks_like_relative_work_order_query(text: str) -> bool:
    normalized = re.sub(r"\s+", "", text or "")
    if not normalized or not _looks_like_single_work_order_question(normalized):
        return False
    if any(token in normalized for token in ("统计", "汇总", "总结", "趋势", "报表", "排行", "排名", "多少单", "运营摘要")):
        return False
    relative_patterns = (
        r"(最近|最新|最后)(生成|创建)?(?:(一张|一条))?的?工单",
        r"(刚生成|刚创建|刚刚生成|刚刚创建)的?工单",
    )
    return any(re.search(pattern, normalized) for pattern in relative_patterns)


def _looks_like_previous_work_order_followup(text: str) -> bool:
    normalized = re.sub(r"\s+", "", text or "")
    if not normalized or not _looks_like_single_work_order_question(normalized):
        return False
    return any(token in normalized for token in ("这张工单", "该工单", "这个工单", "这单", "该单", "这个单"))


def _extract_person_aliases(text: str, scope: dict[str, Any] | None) -> list[str]:
    aliases: list[str] = []
    scoped_worker_name = str((scope or {}).get("worker_name") or "").strip()
    if scoped_worker_name:
        aliases.append(scoped_worker_name)
        formatted = format_person_display_name(scoped_worker_name)
        if formatted:
            aliases.append(formatted)
    aliases.extend(extract_person_display_aliases(text))
    return list(dict.fromkeys(item for item in aliases if item))


def _build_relative_scope_candidates(scope: dict[str, Any] | None) -> list[dict[str, Any]]:
    base = dict(scope or {})
    candidates: list[dict[str, Any]] = [base]

    relaxed_time_scope = dict(base)
    for key in ("date_from", "date_to", "date_label", "status", "work_order_status", "execution_status", "comparison_previous"):
        relaxed_time_scope.pop(key, None)
    if relaxed_time_scope != base:
        candidates.append(relaxed_time_scope)

    has_explicit_owner_or_location_filter = any(
        str(base.get(key) or "").strip()
        for key in ("building_id", "worker_id", "worker_name", "team_id", "team_name")
    )
    if not has_explicit_owner_or_location_filter:
        candidates.append({})

    deduped: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in candidates:
        key = json.dumps(item, ensure_ascii=False, sort_keys=True, default=str)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped


async def _resolve_relative_ticket_id(
    db: AsyncSession,
    *,
    text: str,
    scope: dict[str, Any] | None,
) -> str | None:
    resolved_scope = dict(scope or {})
    stmt = (
        select(WorkOrder.ticket_id, WorkOrder.created_at, User.username)
        .outerjoin(DispatchTask, WorkOrder.current_dispatch_id == DispatchTask.id)
        .outerjoin(User, DispatchTask.assigned_to == User.id)
        .outerjoin(WorkerTeam, DispatchTask.assigned_team_id == WorkerTeam.id)
    )

    building_id = str(resolved_scope.get("building_id") or "").strip()
    if building_id:
        stmt = stmt.where(WorkOrder.building_id == building_id)

    worker_id = str(resolved_scope.get("worker_id") or "").strip()
    if worker_id:
        stmt = stmt.where(DispatchTask.assigned_to == worker_id)

    team_id = str(resolved_scope.get("team_id") or "").strip()
    if team_id:
        stmt = stmt.where(DispatchTask.assigned_team_id == team_id)

    team_name = str(resolved_scope.get("team_name") or "").strip()
    if team_name:
        stmt = stmt.where(WorkerTeam.name == team_name)

    date_from = _coerce_scope_date(resolved_scope.get("date_from"))
    if date_from:
        start_at = datetime.combine(date_from, time.min, tzinfo=timezone.utc)
        stmt = stmt.where(WorkOrder.created_at >= start_at)
    date_to = _coerce_scope_date(resolved_scope.get("date_to"))
    if date_to:
        end_at = datetime.combine(date_to + timedelta(days=1), time.min, tzinfo=timezone.utc)
        stmt = stmt.where(WorkOrder.created_at < end_at)

    status_filters = resolved_scope.get("status")
    if isinstance(status_filters, str):
        status_filters = [status_filters]
    if isinstance(status_filters, list):
        normalized_statuses = [str(item).strip() for item in status_filters if str(item).strip()]
        if normalized_statuses:
            stmt = stmt.where(WorkOrder.status.in_(normalized_statuses))

    work_order_status = str(resolved_scope.get("work_order_status") or "").strip()
    if work_order_status:
        stmt = stmt.where(WorkOrder.status == work_order_status)

    result = await db.execute(
        stmt.order_by(WorkOrder.created_at.desc(), WorkOrder.updated_at.desc()).limit(200)
    )
    rows = list(result.all())
    if not rows:
        return None

    alias_filters = _extract_person_aliases(text, resolved_scope)
    if alias_filters:
        for ticket_value, _created_at, username in rows:
            if not username:
                continue
            formatted = format_person_display_name(username)
            if formatted and formatted in alias_filters:
                return str(ticket_value)
        return None

    return str(rows[0][0])


async def _resolve_contextual_ticket_id(
    db: AsyncSession,
    *,
    text: str,
    ticket_id: str | None,
    scope: dict[str, Any] | None,
    previous_state: dict[str, Any],
) -> tuple[str | None, str | None]:
    explicit_ticket_id = ticket_id or _extract_ticket_id(text)
    if explicit_ticket_id:
        return explicit_ticket_id, "explicit"

    previous_ticket_id = str(previous_state.get("last_ticket_id") or "").strip()
    if previous_ticket_id and _looks_like_previous_work_order_followup(text):
        return previous_ticket_id, "previous"

    if _looks_like_relative_work_order_query(text):
        for candidate_scope in _build_relative_scope_candidates(scope):
            relative_ticket_id = await _resolve_relative_ticket_id(
                db,
                text=text,
                scope=candidate_scope,
            )
            if relative_ticket_id:
                return relative_ticket_id, "relative_recent"
        return None, "relative_recent"

    return None, None


def _looks_like_readonly_action_question(text: str) -> bool:
    normalized = re.sub(r"\s+", "", text or "")
    if not normalized:
        return False

    readonly_tokens = (
        "查一下",
        "查下",
        "查看",
        "查询",
        "看一下",
        "看下",
        "看看",
        "问一下",
        "想知道",
        "为什么",
        "为何",
        "原因",
        "谁",
        "后来",
        "当前",
        "流程",
        "状态",
        "进度",
        "记录",
        "依据",
        "风险",
        "超时",
        "是否",
        "是不是",
        "吗",
        "么",
        "?",
        "？",
    )
    if not any(token in normalized for token in readonly_tokens):
        return False

    write_intent_patterns = (
        r"(帮我|麻烦|请|直接|立刻|马上|现在)[^。！？]{0,20}(改派|派给|关闭|审批|驳回|取消派工|拒绝)",
        r"(把|将)[^。！？]{0,20}(改派|派给|关闭|审批|驳回|取消派工|拒绝)",
        r"(改派|派给)[^。！？]{0,12}(给|到)[^。！？]{1,20}",
        r"(关闭|确认关闭)[^。！？]{0,12}(工单|这张单|这单|单子)",
        r"(通过审批|审批通过|驳回)[^。！？]{0,12}(工单|这张单|这单|单子)",
    )
    return not any(re.search(pattern, normalized) for pattern in write_intent_patterns)


def _detect_blocked_actions(text: str) -> list[str]:
    normalized = text or ""
    if _looks_like_readonly_action_question(normalized):
        return []

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


def _is_greeting_or_smalltalk(text: str) -> bool:
    normalized = re.sub(r"\s+", "", str(text or "").strip().lower())
    if not normalized:
        return False
    exact_tokens = {
        "你好",
        "您好",
        "嗨",
        "哈喽",
        "hello",
        "hi",
        "在吗",
        "在么",
        "谢谢",
        "多谢",
        "辛苦了",
    }
    if normalized in exact_tokens:
        return True
    return any(
        token in normalized
        for token in ("你好呀", "您好呀", "hello呀", "谢谢你", "谢谢您", "辛苦啦")
    )


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
    if _is_greeting_or_smalltalk(normalized):
        return False
    followup_tokens = (
        "那",
        "再看",
        "继续",
        "然后",
        "顺便",
        "另外",
        "换成",
        "改成",
        "切换",
        "拆开",
        "拆分",
        "只看",
        "按班组",
        "按楼宇",
        "按人员",
        "按日期",
        "对比",
        "比较",
        "上周",
        "上一周",
        "上月",
        "上一月",
    )
    return any(token in normalized for token in followup_tokens)


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

    if _is_greeting_or_smalltalk(text):
        answer = "我是运小维，只做只读问询和运营分析。你可以直接问我工单进度、未完成工单情况、超时原因，或者某个时间范围内的班组、楼宇、人员统计。"
        await _append_message(db, session_id=session_id, role="assistant", content=answer)
        await db.commit()
        return {
            "assistant": "运小维",
            "session_id": session_id,
            "answer_type": "greeting",
            "answer": answer,
            "readonly": True,
            "facts": [],
            "metrics": {},
            "chart": None,
            "evidence_refs": [],
            "suggested_followups": ["查看本月工单运营总结", "未完成工单情况", "本周哪个班组超时率最高"],
            "blocked_actions": [],
        }

    resolved_ticket_id, ticket_resolution_mode = await _resolve_contextual_ticket_id(
        db,
        text=text,
        ticket_id=ticket_id,
        scope=scope,
        previous_state=previous_state,
    )
    if ticket_resolution_mode == "relative_recent" and not resolved_ticket_id:
        relative_scope = dict(scope or {})
        answer = "当前筛选范围内没有找到可直接查看全流程的最近工单。你可以补充楼宇、人员，或者直接给我工单号。"
        session_state["last_ticket_id"] = None
        await _ensure_session(db, session_id=session_id, user=user, state=session_state)
        await _append_message(db, session_id=session_id, role="assistant", content=answer)
        await db.commit()
        return {
            "assistant": "运小维",
            "session_id": session_id,
            "answer_type": "single_work_order_not_found",
            "answer": answer,
            "readonly": True,
            "facts": {"scope": relative_scope},
            "metrics": {},
            "chart": None,
            "evidence_refs": [],
            "suggested_followups": ["查看最近7天新建工单", "直接输入工单号查看流程"],
            "blocked_actions": [],
        }

    if resolved_ticket_id:
        context = await build_work_order_review_context(db, ticket_id=resolved_ticket_id)
        if context is None:
            raise HTTPException(status_code=404, detail=f"工单 {resolved_ticket_id} 不存在")
        work_order_data = context.get("work_order") or {}
        session_state["last_ticket_id"] = resolved_ticket_id
        await _ensure_session(db, session_id=session_id, user=user, state=session_state)

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
