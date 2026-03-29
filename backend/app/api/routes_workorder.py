"""
工单管理接口（v2：数据库持久化 + AI 审批闭环 + 反馈闭环）。

端点：
  GET  /api/work-orders                          — 工单列表（分页、筛选）
  GET  /api/work-orders/{ticket_id}              — 单个工单详情
  POST /api/work-orders/approve                  — 兼容旧前端的审批接口
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
from sqlalchemy.orm import selectinload
from sqlalchemy.future import select

from app.core.cache import delete_cache_by_prefix, get_or_compute_json
from app.core.config import get_settings
from app.core.security import get_current_user, get_current_user_optional
from app.db.models import WorkOrder, User
from app.db.session import get_db_session, AsyncSessionLocal
from app.services.work_order_service import (
    create_work_order,
    get_work_order_by_ticket_id,
    list_work_orders as svc_list_work_orders,
    serialize_work_order,
    transition_status,
    validate_transition,
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
                await delete_cache_by_prefix("workorders:")
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
        await delete_cache_by_prefix("workorders:")
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
                    await delete_cache_by_prefix("workorders:")
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


class AdminReviewRequest(BaseModel):
    action: str = Field(
        ..., pattern=r"^(confirm|override_approve|override_reject|close_escalated)$"
    )
    notes: str | None = None


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

    cache_key = f"workorders:list:{status or 'all'}:{building_id or ''}:{page}:{page_size}"
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
        # eagerly load anomaly_links
        for wo in items:
            await db.refresh(wo, ["anomaly_links"])

        return {
            "total": total,
            "page": page,
            "page_size": page_size,
            "work_orders": [serialize_work_order(wo) for wo in items],
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
        await db.refresh(wo, ["anomaly_links"])
        return serialize_work_order(wo)

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
                db, work_order=wo, new_status="admin_override_approved",
                action="admin_override", actor_type="admin",
                detail={"action": "override_approve", "notes": req.reason},
            )
            await transition_status(
                db, work_order=wo, new_status="dispatched",
                action="dispatch", actor_type="system",
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
        await delete_cache_by_prefix("workorders:")

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
        if wo.status == "auto_approved":
            wo.admin_action = "override_reject"
            wo.admin_notes = req.reason
            wo.admin_reviewed_at = now
            await transition_status(
                db, work_order=wo, new_status="admin_override_rejected",
                action="admin_override", actor_type="admin",
                detail={"action": "override_reject", "notes": req.reason},
            )
            await transition_status(
                db, work_order=wo, new_status="closed",
                action="close", actor_type="admin",
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
        await delete_cache_by_prefix("workorders:")

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
    await delete_cache_by_prefix("workorders:")

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
            db, work_order=wo, new_status="admin_override_approved",
            action="admin_override", actor_type="admin", actor_id=user.id,
            detail={"admin_action": "override_approve", "notes": req.notes},
        )
        await transition_status(
            db, work_order=wo, new_status="dispatched",
            action="dispatch", actor_type="system",
        )

    elif req.action == "override_reject":
        if wo.status != "auto_approved":
            raise HTTPException(
                status_code=409,
                detail=f"override_reject 要求状态为 auto_approved（未派发前），当前为 {wo.status}",
            )
        await transition_status(
            db, work_order=wo, new_status="admin_override_rejected",
            action="admin_override", actor_type="admin", actor_id=user.id,
            detail={"admin_action": "override_reject", "notes": req.notes},
        )
        await transition_status(
            db, work_order=wo, new_status="closed",
            action="close", actor_type="admin", actor_id=user.id,
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
    await delete_cache_by_prefix("workorders:")

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

    if wo.status not in ("auto_approved", "auto_rejected"):
        raise HTTPException(
            status_code=409,
            detail=f"仅 auto_approved 或 auto_rejected 状态可重审，当前为 {wo.status}",
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

    await delete_cache_by_prefix("workorders:")

    return {
        "ticket_id": ticket_id,
        "message": "AI 重审已触发，请稍后查看结果",
    }
