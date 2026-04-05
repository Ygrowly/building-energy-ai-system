from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload

from app.core.cache import delete_cache_by_prefix
from app.core.security import get_current_user
from app.db.models import DispatchTask, User, WorkOrder, WorkerProfile, WorkerProfileSkill
from app.db.session import get_db_session
from app.services.dispatch_service import (
    complete_dispatch_task,
    get_dispatch_task_by_id,
    list_dispatch_events,
    reassign_dispatch_task,
    reject_dispatch_task,
    serialize_dispatch_task,
    update_dispatch_task_action,
)
from app.services.work_order_service import _write_audit_log, transition_status

router = APIRouter(prefix="/dispatch-tasks", tags=["派工执行"])


def _require_role(user: User, *roles: str) -> None:
    if user.role not in roles:
        raise HTTPException(status_code=403, detail="权限不足")


async def _invalidate_related_cache() -> None:
    await delete_cache_by_prefix("workorders:")
    await delete_cache_by_prefix("incidents:")


async def _load_assigned_user(db: AsyncSession, user_id: str | None) -> User | None:
    if not user_id:
        return None
    result = await db.execute(
        select(User)
        .options(
            selectinload(User.worker_profile).selectinload(WorkerProfile.team),
            selectinload(User.worker_profile)
            .selectinload(WorkerProfile.skill_links)
            .selectinload(WorkerProfileSkill.skill),
        )
        .where(User.id == user_id)
    )
    return result.scalar_one_or_none()


async def _load_work_order(db: AsyncSession, work_order_id: str) -> WorkOrder:
    work_order = await db.get(WorkOrder, work_order_id)
    if work_order is None:
        raise HTTPException(status_code=404, detail="关联工单不存在")
    return work_order


class SupportRequest(BaseModel):
    reason: str | None = None
    support_team_id: str | None = None


class RejectRequest(BaseModel):
    reason: str = Field(..., min_length=1, max_length=500)


class CompleteRequest(BaseModel):
    result: str = Field(..., pattern=r"^(fixed|false_alarm|escalated|needs_parts)$")
    notes: str | None = None


class ReassignRequest(BaseModel):
    assigned_to: str
    reason: str = Field(..., min_length=1, max_length=500)
    dispatch_mode: str = Field(default="reassigned", pattern=r"^(reassigned|manual|assisted|auto|escalation)$")


@router.get("/{dispatch_id}", summary="获取派工任务详情")
async def get_dispatch_task_detail(
    dispatch_id: str,
    db: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
):
    _require_role(user, "admin", "manager", "ops")
    dispatch_task = await get_dispatch_task_by_id(db, dispatch_id)
    if dispatch_task is None:
        raise HTTPException(status_code=404, detail="派工任务不存在")
    if user.role == "ops" and dispatch_task.assigned_to != user.id:
        raise HTTPException(status_code=403, detail="只能查看派发给自己的派工任务")

    assigned_user = await _load_assigned_user(db, dispatch_task.assigned_to)
    events = await list_dispatch_events(db, dispatch_task_id=dispatch_task.id)
    return serialize_dispatch_task(dispatch_task, assigned_user=assigned_user, events=events)


@router.post("/{dispatch_id}/accept", summary="派工任务接单")
async def accept_dispatch_task(
    dispatch_id: str,
    db: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
):
    _require_role(user, "admin", "manager", "ops")
    dispatch_task = await get_dispatch_task_by_id(db, dispatch_id)
    if dispatch_task is None:
        raise HTTPException(status_code=404, detail="派工任务不存在")
    if user.role == "ops" and dispatch_task.assigned_to != user.id:
        raise HTTPException(status_code=403, detail="只能操作派发给自己的派工任务")
    work_order = await _load_work_order(db, dispatch_task.work_order_id)

    try:
        await update_dispatch_task_action(
            db,
            work_order=work_order,
            dispatch_task=dispatch_task,
            action="accept",
            actor_type="worker" if user.role == "ops" else "admin",
            actor_id=user.id,
        )
        await _write_audit_log(
            db,
            work_order_id=work_order.id,
            action="dispatch_accept",
            old_status=work_order.status,
            new_status=work_order.status,
            actor_type="worker" if user.role == "ops" else "admin",
            actor_id=user.id,
            detail={"dispatch_id": dispatch_task.id},
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    await db.commit()
    await _invalidate_related_cache()
    return {"dispatch_id": dispatch_task.id, "message": "已确认接单", "status": work_order.status}


@router.post("/{dispatch_id}/arrive", summary="派工任务到场")
async def arrive_dispatch_task(
    dispatch_id: str,
    db: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
):
    _require_role(user, "admin", "manager", "ops")
    dispatch_task = await get_dispatch_task_by_id(db, dispatch_id)
    if dispatch_task is None:
        raise HTTPException(status_code=404, detail="派工任务不存在")
    if user.role == "ops" and dispatch_task.assigned_to != user.id:
        raise HTTPException(status_code=403, detail="只能操作派发给自己的派工任务")
    work_order = await _load_work_order(db, dispatch_task.work_order_id)

    try:
        await update_dispatch_task_action(
            db,
            work_order=work_order,
            dispatch_task=dispatch_task,
            action="arrive",
            actor_type="worker" if user.role == "ops" else "admin",
            actor_id=user.id,
        )
        await _write_audit_log(
            db,
            work_order_id=work_order.id,
            action="dispatch_arrive",
            old_status=work_order.status,
            new_status=work_order.status,
            actor_type="worker" if user.role == "ops" else "admin",
            actor_id=user.id,
            detail={"dispatch_id": dispatch_task.id},
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    await db.commit()
    await _invalidate_related_cache()
    return {"dispatch_id": dispatch_task.id, "message": "已确认到场", "status": work_order.status}


@router.post("/{dispatch_id}/start", summary="派工任务开始处理")
async def start_dispatch_task(
    dispatch_id: str,
    db: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
):
    _require_role(user, "admin", "manager", "ops")
    dispatch_task = await get_dispatch_task_by_id(db, dispatch_id)
    if dispatch_task is None:
        raise HTTPException(status_code=404, detail="派工任务不存在")
    if user.role == "ops" and dispatch_task.assigned_to != user.id:
        raise HTTPException(status_code=403, detail="只能操作派发给自己的派工任务")
    work_order = await _load_work_order(db, dispatch_task.work_order_id)

    try:
        await update_dispatch_task_action(
            db,
            work_order=work_order,
            dispatch_task=dispatch_task,
            action="start",
            actor_type="worker" if user.role == "ops" else "admin",
            actor_id=user.id,
        )
        await _write_audit_log(
            db,
            work_order_id=work_order.id,
            action="dispatch_start",
            old_status=work_order.status,
            new_status=work_order.status,
            actor_type="worker" if user.role == "ops" else "admin",
            actor_id=user.id,
            detail={"dispatch_id": dispatch_task.id},
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    await db.commit()
    await _invalidate_related_cache()
    return {"dispatch_id": dispatch_task.id, "message": "已开始处理", "status": work_order.status}


@router.post("/{dispatch_id}/request-support", summary="派工任务申请协同")
async def request_support_dispatch_task(
    dispatch_id: str,
    req: SupportRequest,
    db: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
):
    _require_role(user, "admin", "manager", "ops")
    dispatch_task = await get_dispatch_task_by_id(db, dispatch_id)
    if dispatch_task is None:
        raise HTTPException(status_code=404, detail="派工任务不存在")
    if user.role == "ops" and dispatch_task.assigned_to != user.id:
        raise HTTPException(status_code=403, detail="只能操作派发给自己的派工任务")
    work_order = await _load_work_order(db, dispatch_task.work_order_id)

    try:
        await update_dispatch_task_action(
            db,
            work_order=work_order,
            dispatch_task=dispatch_task,
            action="request_support",
            actor_type="worker" if user.role == "ops" else "admin",
            actor_id=user.id,
            notes=req.reason,
            support_team_id=req.support_team_id,
        )
        work_order.worker_result = "needs_parts"
        work_order.worker_notes = req.reason
        await _write_audit_log(
            db,
            work_order_id=work_order.id,
            action="dispatch_request_support",
            old_status=work_order.status,
            new_status=work_order.status,
            actor_type="worker" if user.role == "ops" else "admin",
            actor_id=user.id,
            detail={"dispatch_id": dispatch_task.id, "support_team_id": req.support_team_id, "reason": req.reason},
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    await db.commit()
    await _invalidate_related_cache()
    return {"dispatch_id": dispatch_task.id, "message": "已提交协同请求", "status": work_order.status}


@router.post("/{dispatch_id}/reject", summary="派工任务拒单")
async def reject_dispatch_task_endpoint(
    dispatch_id: str,
    req: RejectRequest,
    db: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
):
    _require_role(user, "admin", "manager", "ops")
    dispatch_task = await get_dispatch_task_by_id(db, dispatch_id)
    if dispatch_task is None:
        raise HTTPException(status_code=404, detail="派工任务不存在")
    if user.role == "ops" and dispatch_task.assigned_to != user.id:
        raise HTTPException(status_code=403, detail="只能操作派发给自己的派工任务")
    work_order = await _load_work_order(db, dispatch_task.work_order_id)

    try:
        await reject_dispatch_task(
            db,
            work_order=work_order,
            dispatch_task=dispatch_task,
            actor_type="worker" if user.role == "ops" else "admin",
            actor_id=user.id,
            reason=req.reason,
        )
        work_order.dispatch_blocked_reason = req.reason
        await transition_status(
            db,
            work_order=work_order,
            new_status="pending_dispatch",
            action="dispatch_reject",
            actor_type="worker" if user.role == "ops" else "admin",
            actor_id=user.id,
            detail={"dispatch_id": dispatch_task.id, "reason": req.reason},
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    await db.commit()
    await _invalidate_related_cache()
    return {"dispatch_id": dispatch_task.id, "message": "已拒单，工单返回待派工", "status": work_order.status}


@router.post("/{dispatch_id}/complete", summary="派工任务完成")
async def complete_dispatch_task_endpoint(
    dispatch_id: str,
    req: CompleteRequest,
    db: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
):
    _require_role(user, "admin", "manager", "ops")
    dispatch_task = await get_dispatch_task_by_id(db, dispatch_id)
    if dispatch_task is None:
        raise HTTPException(status_code=404, detail="派工任务不存在")
    if user.role == "ops" and dispatch_task.assigned_to != user.id:
        raise HTTPException(status_code=403, detail="只能操作派发给自己的派工任务")
    work_order = await _load_work_order(db, dispatch_task.work_order_id)

    await complete_dispatch_task(
        db,
        work_order=work_order,
        dispatch_task=dispatch_task,
        actor_type="worker" if user.role == "ops" else "admin",
        actor_id=user.id,
        result=req.result,
        notes=req.notes,
    )
    work_order.worker_result = req.result
    work_order.worker_notes = req.notes
    work_order.worker_feedback_at = datetime.now(timezone.utc)

    if req.result != "needs_parts":
        status_map = {
            "fixed": "completed",
            "false_alarm": "false_alarm",
            "escalated": "escalated",
        }
        await transition_status(
            db,
            work_order=work_order,
            new_status=status_map[req.result],
            action="worker_feedback",
            actor_type="worker" if user.role == "ops" else "admin",
            actor_id=user.id,
            detail={"dispatch_id": dispatch_task.id, "result": req.result, "notes": req.notes},
        )
    await db.commit()
    await _invalidate_related_cache()
    return {"dispatch_id": dispatch_task.id, "message": "已提交处理结果", "status": work_order.status}


@router.post("/{dispatch_id}/reassign", summary="派工任务改派")
async def reassign_dispatch_task_endpoint(
    dispatch_id: str,
    req: ReassignRequest,
    db: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
):
    _require_role(user, "admin", "manager")
    dispatch_task = await get_dispatch_task_by_id(db, dispatch_id)
    if dispatch_task is None:
        raise HTTPException(status_code=404, detail="派工任务不存在")
    work_order = await _load_work_order(db, dispatch_task.work_order_id)
    assigned_user = await _load_assigned_user(db, req.assigned_to)
    if not assigned_user or assigned_user.role != "ops" or not assigned_user.is_active:
        raise HTTPException(status_code=404, detail="目标维修人员不存在或不可用")

    try:
        new_dispatch = await reassign_dispatch_task(
            db,
            work_order=work_order,
            dispatch_task=dispatch_task,
            assigned_user=assigned_user,
            actor_type="admin",
            actor_id=user.id,
            reason=req.reason,
            dispatch_mode=req.dispatch_mode,
        )
        await _write_audit_log(
            db,
            work_order_id=work_order.id,
            action="dispatch_reassign",
            old_status=work_order.status,
            new_status=work_order.status,
            actor_type="admin",
            actor_id=user.id,
            detail={
                "from_dispatch_id": dispatch_task.id,
                "to_dispatch_id": new_dispatch.id,
                "assigned_to": assigned_user.id,
                "reason": req.reason,
            },
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    await db.commit()
    await _invalidate_related_cache()
    return {"dispatch_id": new_dispatch.id, "message": f"已改派给 {assigned_user.username}", "status": work_order.status}
