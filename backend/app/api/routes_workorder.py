"""
工单管理接口（v2：数据库持久化 + AI 审批闭环 + 反馈闭环）。

端点：
  GET  /api/work-orders                          — 工单列表（分页、筛选）
  GET  /api/work-orders/{ticket_id}              — 单个工单详情
  POST /api/work-orders/approve                  — 兼容旧前端的审批接口
  GET  /api/work-orders/{ticket_id}/dispatch-candidates — 派工候选人
  POST /api/work-orders/{ticket_id}/dispatch     — 派工
  POST /api/work-orders/{ticket_id}/worker-action — 维修执行动作
  POST /api/work-orders/{ticket_id}/worker-feedback  — 维修人员反馈
  POST /api/work-orders/{ticket_id}/admin-review     — 管理员监督/覆盖
  POST /api/work-orders/{ticket_id}/ai-review-trigger — 手动触发 AI 重审
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload

from app.core.cache import delete_cache_by_prefix, get_or_compute_json
from app.core.config import get_settings
from app.core.security import get_current_user, get_current_user_optional
from app.db.models import WorkOrder, User, WorkerProfile, WorkerProfileSkill
from app.db.session import get_db_session, AsyncSessionLocal
from app.services.dispatch_service import (
    complete_dispatch_task,
    get_current_dispatch_task,
    load_current_dispatches_by_work_order_ids,
    load_dispatch_events_by_task_ids,
)
from app.services.work_order_service import (
    create_work_order,
    get_work_order_by_ticket_id,
    list_work_orders as svc_list_work_orders,
    list_dispatch_candidates,
    serialize_work_order,
    transition_status,
    assign_work_order,
    record_worker_dispatch_action,
    apply_ai_review,
)

logger = logging.getLogger(__name__)
settings = get_settings()

router = APIRouter(prefix="/work-orders", tags=["工单"])


# ---------------------------------------------------------------------------
# 角色校验工具
# ---------------------------------------------------------------------------
def _require_role(user: User, *roles: str) -> None:
    if user.role not in roles:
        raise HTTPException(status_code=403, detail="权限不足")


async def _invalidate_related_cache() -> None:
    await delete_cache_by_prefix("workorders:")
    await delete_cache_by_prefix("incidents:")


# ---------------------------------------------------------------------------
# 工单注册（供 routes_chat.py 调用，替代旧的内存字典）
# ---------------------------------------------------------------------------
async def register_pending_order(order_data: dict[str, Any]) -> WorkOrder | None:
    """
    从 Diagnose Agent 的 pending_action 注册待审批工单到数据库。
    在独立 session 中执行，不依赖请求级 session。
    返回创建的 WorkOrder 对象（或 None）。
    """
    ticket_id = order_data.get("ticket_id")
    if not ticket_id:
        return None

    try:
        async with AsyncSessionLocal() as db:
            # 去重：检查是否已存在同一 ticket_id
            existing = await get_work_order_by_ticket_id(db, ticket_id)
            if existing:
                logger.debug("工单已存在，跳过注册: %s", ticket_id)
                return existing

            wo = await create_work_order(
                db,
                ticket_id=ticket_id,
                building_id=order_data.get("building_id", ""),
                device_id=order_data.get("device_id"),
                issue_description=order_data.get("issue_description", ""),
                suggested_action=order_data.get("suggested_action", ""),
                priority=order_data.get("priority", "medium"),
                session_id=order_data.get("session_id"),
            )
            await db.commit()

            # 非阻塞缓存失效
            try:
                await _invalidate_related_cache()
            except Exception:
                pass

            logger.info("工单注册成功: ticket_id=%s wo_id=%s", wo.ticket_id, wo.id)

            # 触发异步 AI 审批
            import asyncio
            asyncio.create_task(_trigger_ai_review(wo.id))

            return wo
    except Exception:
        logger.exception("工单注册失败")
        return None


async def _trigger_ai_review(work_order_id: str) -> None:
    """在独立 session 中触发 AI 审批（后台任务，不阻塞主流程）。"""
    try:
        from app.services.ai_review_service import review_work_order
        async with AsyncSessionLocal() as db:
            await review_work_order(db, work_order_id)
            await db.commit()
        await _invalidate_related_cache()
        logger.info("AI 审批完成: work_order_id=%s", work_order_id)
    except Exception:
        logger.exception("AI 审批失败（降级处理）: work_order_id=%s", work_order_id)
        # 降级：如果审批服务本身异常，将工单标记为 fallback approve
        try:
            async with AsyncSessionLocal() as db:
                wo = await db.get(WorkOrder, work_order_id)
                if wo and wo.status == "pending_review":
                    await apply_ai_review(
                        db,
                        work_order=wo,
                        decision="approve",
                        reason="AI 审批服务异常，降级批准",
                        fallback=True,
                    )
                    await db.commit()
                    await _invalidate_related_cache()
        except Exception:
            logger.exception("降级批准也失败了: work_order_id=%s", work_order_id)


# ---------------------------------------------------------------------------
# 请求模型
# ---------------------------------------------------------------------------
class ApproveRequest(BaseModel):
    session_id: str
    ticket_id: str
    approved: bool = True
    reason: str | None = None


class WorkerFeedbackRequest(BaseModel):
    result: str = Field(..., pattern=r"^(fixed|false_alarm|escalated|needs_parts)$")
    notes: str | None = None


class DispatchRequest(BaseModel):
    assigned_to: str
    dispatch_mode: str = Field(default="manual", pattern=r"^(manual|assisted|auto|reassigned|escalation)$")
    assigned_team_id: str | None = None
    selection_reason: str | None = None
    notes: str | None = None


class WorkerActionRequest(BaseModel):
    action: str = Field(..., pattern=r"^(accept|arrive|start|request_support)$")
    notes: str | None = None
    support_team_id: str | None = None


class AdminReviewRequest(BaseModel):
    action: str = Field(
        ..., pattern=r"^(confirm|override_approve|override_reject|close_escalated)$"
    )
    notes: str | None = None


async def _load_assigned_users(
    db: AsyncSession,
    work_orders: list[WorkOrder],
) -> dict[str, User]:
    assigned_user_ids = [wo.assigned_to for wo in work_orders if wo.assigned_to]
    if not assigned_user_ids:
        return {}
    result = await db.execute(
        select(User)
        .options(
            selectinload(User.worker_profile).selectinload(WorkerProfile.team),
            selectinload(User.worker_profile)
            .selectinload(WorkerProfile.skill_links)
            .selectinload(WorkerProfileSkill.skill),
        )
        .where(User.id.in_(assigned_user_ids))
    )
    return {user.id: user for user in result.scalars().all()}


# ---------------------------------------------------------------------------
# GET /api/work-orders — 工单列表
# ---------------------------------------------------------------------------
@router.get("", summary="获取工单列表")
async def list_work_orders_endpoint(
    status: str | None = Query(None, description="按状态过滤，逗号分隔多值"),
    building_id: str | None = Query(None),
    priority: str | None = Query(None),
    ai_fallback: bool | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db_session),
    user: User | None = Depends(get_current_user_optional),
):
    """返回工单列表，支持分页和多维度筛选。管理员看全部，维修人员只看自己的。"""

    status_filter = [s.strip() for s in status.split(",") if s.strip()] if status else None
    assigned_to = None
    if user and user.role == "ops":
        assigned_to = user.id

    user_scope = user.id if user else "anonymous"
    cache_key = (
        "workorders:list:"
        f"{user_scope}:"
        f"{status or 'all'}:"
        f"{building_id or ''}:"
        f"{priority or 'all'}:"
        f"{ai_fallback if ai_fallback is not None else 'all'}:"
        f"{assigned_to or 'all'}:"
        f"{page}:{page_size}"
    )
    ttl = settings.CACHE_WORKORDERS_TTL_SECONDS

    async def _compute() -> dict[str, Any]:
        items, total = await svc_list_work_orders(
            db,
            status_filter=status_filter,
            building_id=building_id,
            priority=priority,
            ai_fallback=ai_fallback,
            assigned_to=assigned_to,
            page=page,
            page_size=page_size,
        )
        assigned_users_by_id = await _load_assigned_users(db, items)
        current_dispatches = await load_current_dispatches_by_work_order_ids(
            db,
            work_order_ids=[wo.id for wo in items],
        )
        return {
            "total": total,
            "page": page,
            "page_size": page_size,
            "work_orders": [
                serialize_work_order(
                    wo,
                    assigned_user=assigned_users_by_id.get(wo.assigned_to or ""),
                    current_dispatch=current_dispatches.get(wo.id),
                )
                for wo in items
            ],
        }

    return await get_or_compute_json(cache_key, ttl, _compute)


# ---------------------------------------------------------------------------
# GET /api/work-orders/{ticket_id} — 单个工单详情
# ---------------------------------------------------------------------------
@router.get("/{ticket_id}", summary="获取单个工单详情")
async def get_work_order_endpoint(
    ticket_id: str,
    db: AsyncSession = Depends(get_db_session),
):
    cache_key = f"workorders:detail:{ticket_id}"
    ttl = settings.CACHE_WORKORDERS_TTL_SECONDS

    async def _compute() -> dict[str, Any]:
        wo = await get_work_order_by_ticket_id(db, ticket_id)
        if not wo:
            raise HTTPException(status_code=404, detail=f"工单 {ticket_id} 不存在")
        assigned_user = None
        if wo.assigned_to:
            result = await db.execute(
                select(User)
                .options(
                    selectinload(User.worker_profile).selectinload(WorkerProfile.team),
                    selectinload(User.worker_profile)
                    .selectinload(WorkerProfile.skill_links)
                    .selectinload(WorkerProfileSkill.skill),
                )
                .where(User.id == wo.assigned_to)
            )
            assigned_user = result.scalar_one_or_none()
        current_dispatch = await get_current_dispatch_task(db, work_order=wo)
        dispatch_events = []
        if current_dispatch is not None:
            dispatch_events_map = await load_dispatch_events_by_task_ids(
                db,
                dispatch_task_ids=[current_dispatch.id],
            )
            dispatch_events = dispatch_events_map.get(current_dispatch.id, [])
        return serialize_work_order(
            wo,
            assigned_user=assigned_user,
            current_dispatch=current_dispatch,
            dispatch_events=dispatch_events,
        )

    return await get_or_compute_json(cache_key, ttl, _compute)


# ---------------------------------------------------------------------------
# POST /api/work-orders/approve — 兼容旧前端审批接口
# ---------------------------------------------------------------------------
@router.post("/approve", summary="审批工单（兼容旧接口）")
async def approve_work_order(
    req: ApproveRequest,
    db: AsyncSession = Depends(get_db_session),
):
    """
    兼容旧前端的审批接口。
    approved=True → 管理员手动批准（override_approve 或 confirm）
    approved=False → 管理员手动驳回（override_reject）
    """
    wo = await get_work_order_by_ticket_id(db, req.ticket_id)
    if not wo:
        raise HTTPException(status_code=404, detail=f"工单 {req.ticket_id} 不存在")

    now = datetime.now(timezone.utc)

    if req.approved:
        # 根据当前状态决定操作
        if wo.status == "auto_rejected":
            wo.admin_action = "override_approve"
            wo.admin_notes = req.reason
            wo.admin_reviewed_at = now
            await transition_status(
                db, work_order=wo, new_status="pending_dispatch",
                action="admin_override", actor_type="admin",
                detail={"action": "override_approve", "notes": req.reason},
            )
        elif wo.status in ("completed", "false_alarm"):
            wo.admin_action = "confirm"
            wo.admin_reviewed_at = now
            await transition_status(
                db, work_order=wo, new_status="closed",
                action="close", actor_type="admin",
            )
        elif wo.status == "pending_review":
            # 前端旧逻辑：直接批准 pending 工单
            await apply_ai_review(
                db, work_order=wo, decision="approve",
                reason=req.reason or "管理员手动批准",
            )
        else:
            raise HTTPException(
                status_code=409,
                detail=f"当前状态 {wo.status} 不支持批准操作",
            )

        await db.commit()
        await _invalidate_related_cache()

        # 清理 session pending_action（兼容旧逻辑）
        try:
            from app.api.routes_chat import _sessions
            state = _sessions.get(req.session_id)
            if state:
                state["pending_action"] = None
        except Exception:
            pass

        return {
            "status": wo.status,
            "ticket_id": req.ticket_id,
            "message": f"工单 {req.ticket_id} 已处理（{wo.status}）。",
        }
    else:
        if wo.status in ("pending_dispatch", "auto_approved"):
            wo.admin_action = "override_reject"
            wo.admin_notes = req.reason
            wo.admin_reviewed_at = now
            await transition_status(
                db, work_order=wo, new_status="closed",
                action="admin_override", actor_type="admin",
                detail={"action": "override_reject", "notes": req.reason},
            )
        elif wo.status == "pending_review":
            await apply_ai_review(
                db, work_order=wo, decision="reject",
                reason=req.reason or "管理员手动驳回",
            )
        else:
            raise HTTPException(
                status_code=409,
                detail=f"当前状态 {wo.status} 不支持驳回操作",
            )

        await db.commit()
        await _invalidate_related_cache()

        try:
            from app.api.routes_chat import _sessions
            state = _sessions.get(req.session_id)
            if state:
                state["pending_action"] = None
        except Exception:
            pass

        return {
            "status": wo.status,
            "ticket_id": req.ticket_id,
            "message": f"工单 {req.ticket_id} 已驳回。",
            "reason": req.reason,
        }


# ---------------------------------------------------------------------------
# GET /api/work-orders/{ticket_id}/dispatch-candidates — 派工候选人
# ---------------------------------------------------------------------------
@router.get("/{ticket_id}/dispatch-candidates", summary="获取派工候选人")
async def get_dispatch_candidates(
    ticket_id: str,
    db: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
):
    _require_role(user, "admin", "manager")

    wo = await get_work_order_by_ticket_id(db, ticket_id)
    if not wo:
        raise HTTPException(status_code=404, detail="工单不存在")
    if wo.status not in ("pending_dispatch", "auto_approved", "admin_override_approved"):
        raise HTTPException(status_code=409, detail=f"当前状态 {wo.status} 不支持派工")

    candidate_payload = await list_dispatch_candidates(db, work_order=wo)
    return {
        "ticket_id": ticket_id,
        "status": wo.status,
        "requirement": candidate_payload["requirement"],
        "candidates": candidate_payload["candidates"],
    }


# ---------------------------------------------------------------------------
# POST /api/work-orders/{ticket_id}/dispatch — 派工
# ---------------------------------------------------------------------------
@router.post("/{ticket_id}/dispatch", summary="派工")
async def dispatch_work_order(
    ticket_id: str,
    req: DispatchRequest,
    db: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
):
    _require_role(user, "admin", "manager")

    wo = await get_work_order_by_ticket_id(db, ticket_id)
    if not wo:
        raise HTTPException(status_code=404, detail="工单不存在")

    assigned_user_result = await db.execute(
        select(User)
        .options(
            selectinload(User.worker_profile).selectinload(WorkerProfile.team),
            selectinload(User.worker_profile)
            .selectinload(WorkerProfile.skill_links)
            .selectinload(WorkerProfileSkill.skill),
        )
        .where(User.id == req.assigned_to)
    )
    assigned_user = assigned_user_result.scalar_one_or_none()
    if not assigned_user or assigned_user.role != "ops" or not assigned_user.is_active:
        raise HTTPException(status_code=404, detail="目标维修人员不存在或不可用")

    try:
        candidate_snapshot = {
            "user_id": assigned_user.id,
            "username": assigned_user.username,
            "phone": assigned_user.phone,
            "team_name": getattr(getattr(assigned_user.worker_profile, "team", None), "name", None),
            "assigned_team_id": req.assigned_team_id,
            "dispatch_mode": req.dispatch_mode,
        }
        await assign_work_order(
            db,
            work_order=wo,
            assigned_user=assigned_user,
            actor_type="admin",
            actor_id=user.id,
            dispatch_mode=req.dispatch_mode,
            candidate_snapshot=candidate_snapshot,
            notes=req.selection_reason or req.notes,
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    await db.commit()
    await _invalidate_related_cache()

    return {
        "status": wo.status,
        "ticket_id": ticket_id,
        "dispatch_id": wo.current_dispatch_id,
        "message": f"工单已派给 {assigned_user.username}",
    }


# ---------------------------------------------------------------------------
# POST /api/work-orders/{ticket_id}/worker-action — 维修执行动作
# ---------------------------------------------------------------------------
@router.post("/{ticket_id}/worker-action", summary="维修执行动作")
async def worker_action(
    ticket_id: str,
    req: WorkerActionRequest,
    db: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
):
    _require_role(user, "ops", "admin", "manager")

    wo = await get_work_order_by_ticket_id(db, ticket_id)
    if not wo:
        raise HTTPException(status_code=404, detail="工单不存在")
    if user.role == "ops" and wo.assigned_to != user.id:
        raise HTTPException(status_code=403, detail="只能操作派发给自己的工单")

    try:
        await record_worker_dispatch_action(
            db,
            work_order=wo,
            action=req.action,
            actor_id=user.id,
            notes=req.notes,
            support_team_id=req.support_team_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    await db.commit()
    await _invalidate_related_cache()

    return {
        "status": wo.status,
        "ticket_id": ticket_id,
        "message": f"执行动作已记录：{req.action}",
    }


# ---------------------------------------------------------------------------
# POST /api/work-orders/{ticket_id}/worker-feedback — 维修人员反馈
# ---------------------------------------------------------------------------
@router.post("/{ticket_id}/worker-feedback", summary="维修人员提交反馈")
async def worker_feedback(
    ticket_id: str,
    req: WorkerFeedbackRequest,
    db: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
):
    _require_role(user, "ops", "admin", "manager")

    wo = await get_work_order_by_ticket_id(db, ticket_id)
    if not wo:
        raise HTTPException(status_code=404, detail="工单不存在")

    if wo.status != "dispatched":
        raise HTTPException(
            status_code=409,
            detail=f"工单状态为 {wo.status}，仅 dispatched 状态可提交反馈",
        )

    # ops 角色只能反馈派发给自己的工单
    if user.role == "ops" and wo.assigned_to and wo.assigned_to != user.id:
        raise HTTPException(status_code=403, detail="只能反馈派发给自己的工单")

    now = datetime.now(timezone.utc)
    wo.worker_result = req.result
    wo.worker_notes = req.notes
    wo.worker_feedback_at = now
    current_dispatch = await get_current_dispatch_task(db, work_order=wo)
    if current_dispatch is None:
        raise HTTPException(status_code=409, detail="当前工单缺少有效派工任务")
    await complete_dispatch_task(
        db,
        work_order=wo,
        dispatch_task=current_dispatch,
        actor_type="worker",
        actor_id=user.id,
        result=req.result,
        notes=req.notes,
    )

    # needs_parts 不变更状态，仅记录
    if req.result != "needs_parts":
        status_map = {
            "fixed": "completed",
            "false_alarm": "false_alarm",
            "escalated": "escalated",
        }
        new_status = status_map[req.result]
        await transition_status(
            db, work_order=wo, new_status=new_status,
            action="worker_feedback", actor_type="worker", actor_id=user.id,
            detail={"result": req.result, "notes": req.notes},
        )

    await db.commit()
    await _invalidate_related_cache()

    return {
        "status": wo.status,
        "ticket_id": ticket_id,
        "message": f"反馈已记录：{req.result}",
    }


# ---------------------------------------------------------------------------
# POST /api/work-orders/{ticket_id}/admin-review — 管理员监督/覆盖
# ---------------------------------------------------------------------------
@router.post("/{ticket_id}/admin-review", summary="管理员审阅/覆盖")
async def admin_review(
    ticket_id: str,
    req: AdminReviewRequest,
    db: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
):
    _require_role(user, "admin", "manager")

    wo = await get_work_order_by_ticket_id(db, ticket_id)
    if not wo:
        raise HTTPException(status_code=404, detail="工单不存在")

    now = datetime.now(timezone.utc)
    wo.admin_action = req.action
    wo.admin_notes = req.notes
    wo.admin_reviewed_by = user.id
    wo.admin_reviewed_at = now

    if req.action == "confirm":
        if wo.status not in ("completed", "false_alarm"):
            raise HTTPException(
                status_code=409,
                detail=f"confirm 操作要求工单状态为 completed 或 false_alarm，当前为 {wo.status}",
            )
        await transition_status(
            db, work_order=wo, new_status="closed",
            action="close", actor_type="admin", actor_id=user.id,
            detail={"admin_action": "confirm", "notes": req.notes},
        )

    elif req.action == "override_approve":
        if wo.status != "auto_rejected":
            raise HTTPException(
                status_code=409,
                detail=f"override_approve 要求状态为 auto_rejected，当前为 {wo.status}",
            )
        # 检查 48h 审阅窗口
        if wo.ai_reviewed_at:
            elapsed = (now - wo.ai_reviewed_at).total_seconds()
            if elapsed > 48 * 3600:
                raise HTTPException(
                    status_code=409,
                    detail="已超过 48 小时审阅窗口，无法推翻",
                )
        await transition_status(
            db, work_order=wo, new_status="pending_dispatch",
            action="admin_override", actor_type="admin", actor_id=user.id,
            detail={"admin_action": "override_approve", "notes": req.notes},
        )

    elif req.action == "override_reject":
        if wo.status not in ("pending_dispatch", "auto_approved"):
            raise HTTPException(
                status_code=409,
                detail=f"override_reject 要求状态为 pending_dispatch（未派发前），当前为 {wo.status}",
            )
        await transition_status(
            db, work_order=wo, new_status="closed",
            action="close", actor_type="admin", actor_id=user.id,
            detail={"admin_action": "override_reject", "notes": req.notes},
        )

    elif req.action == "close_escalated":
        if wo.status != "escalated":
            raise HTTPException(
                status_code=409,
                detail=f"close_escalated 要求状态为 escalated，当前为 {wo.status}",
            )
        await transition_status(
            db, work_order=wo, new_status="closed",
            action="close", actor_type="admin", actor_id=user.id,
            detail={"admin_action": "close_escalated", "notes": req.notes},
        )

    await db.commit()
    await _invalidate_related_cache()

    return {
        "status": wo.status,
        "ticket_id": ticket_id,
        "message": f"管理员操作已执行：{req.action}",
    }


# ---------------------------------------------------------------------------
# POST /api/work-orders/{ticket_id}/ai-review-trigger — 手动重审
# ---------------------------------------------------------------------------
@router.post("/{ticket_id}/ai-review-trigger", summary="手动触发 AI 重审")
async def ai_review_trigger(
    ticket_id: str,
    db: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
):
    _require_role(user, "admin", "manager")

    wo = await get_work_order_by_ticket_id(db, ticket_id)
    if not wo:
        raise HTTPException(status_code=404, detail="工单不存在")

    if wo.status not in ("pending_dispatch", "auto_rejected", "auto_approved"):
        raise HTTPException(
            status_code=409,
            detail=f"仅 pending_dispatch 或 auto_rejected 状态可重审，当前为 {wo.status}",
        )

    # 重置 AI 审批字段，回到 pending_review 重新审
    wo.status = "pending_review"
    wo.ai_decision = None
    wo.ai_reason = None
    wo.ai_matched_event_ids = None
    wo.ai_reviewed_at = None
    wo.ai_fallback = False
    wo.updated_at = datetime.now(timezone.utc)
    await db.commit()

    import asyncio
    asyncio.create_task(_trigger_ai_review(wo.id))

    await _invalidate_related_cache()

    return {
        "ticket_id": ticket_id,
        "message": "AI 重审已触发，请稍后查看结果",
    }
