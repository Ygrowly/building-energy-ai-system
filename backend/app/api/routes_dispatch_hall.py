from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.cache import delete_cache_by_prefix
from app.core.security import get_current_user
from app.db.models import (
    DispatchTask,
    User,
    WorkOrder,
    WorkerProfile,
    WorkerProfileSkill,
)
from app.db.session import get_db_session
from app.services.audit_log_service import write_work_order_audit_log as _write_audit_log
from app.services.dispatch_hall_service import (
    approve_dispatch_hall_application,
    accept_assigned_support_hall_entry,
    apply_to_dispatch_hall_entry,
    assign_support_hall_entry,
    can_view_dispatch_hall_entry,
    close_dispatch_hall_entry,
    get_dispatch_hall_application_by_id,
    get_dispatch_hall_entry_by_id,
    list_dispatch_hall_entries,
    load_dispatch_hall_applications_by_entry_ids,
    reject_assigned_support_hall_entry,
    reject_dispatch_hall_application,
    serialize_dispatch_hall_application,
    serialize_dispatch_hall_entry,
    withdraw_dispatch_hall_application,
)
from app.services.dispatch_service import (
    get_dispatch_task_by_id,
    reassign_dispatch_task,
    serialize_dispatch_task,
)
from app.services.dispatch_event_service import record_dispatch_event

router = APIRouter(prefix="/dispatch-hall", tags=["共享工单大厅"])


def _require_role(user: User, *roles: str) -> None:
    if user.role not in roles:
        raise HTTPException(status_code=403, detail="权限不足")


async def _invalidate_related_cache() -> None:
    await delete_cache_by_prefix("workorders:")
    await delete_cache_by_prefix("incidents:")


async def _load_user_with_worker_context(db: AsyncSession, user_id: str | None) -> User | None:
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


async def _load_users_by_ids(db: AsyncSession, user_ids: list[str]) -> dict[str, User]:
    unique_user_ids = [user_id for user_id in dict.fromkeys(user_ids) if user_id]
    if not unique_user_ids:
        return {}
    result = await db.execute(
        select(User)
        .options(
            selectinload(User.worker_profile).selectinload(WorkerProfile.team),
            selectinload(User.worker_profile)
            .selectinload(WorkerProfile.skill_links)
            .selectinload(WorkerProfileSkill.skill),
        )
        .where(User.id.in_(unique_user_ids))
    )
    return {item.id: item for item in result.scalars().all()}


async def _load_work_order(db: AsyncSession, work_order_id: str) -> WorkOrder:
    work_order = await db.get(WorkOrder, work_order_id)
    if work_order is None:
        raise HTTPException(status_code=404, detail="关联工单不存在")
    return work_order


async def _resolve_viewer_context(db: AsyncSession, user: User) -> User:
    loaded = await _load_user_with_worker_context(db, user.id)
    return loaded or user


async def _serialize_hall_entries(
    db: AsyncSession,
    entries,
    *,
    include_applications: bool = False,
):
    applications_map = (
        await load_dispatch_hall_applications_by_entry_ids(
            db,
            hall_entry_ids=[entry.id for entry in entries],
        )
        if include_applications and entries else
        {}
    )
    user_ids: list[str] = []
    work_order_ids = [entry.work_order_id for entry in entries if entry.work_order_id]
    source_dispatch_ids = [entry.source_dispatch_id for entry in entries if entry.source_dispatch_id]
    for entry in entries:
        user_ids.extend([entry.assigned_to, entry.assigned_by, entry.created_by])
        for application in applications_map.get(entry.id, []):
            user_ids.extend([application.applicant_user_id, application.handled_by])
    work_orders_by_id: dict[str, WorkOrder] = {}
    if work_order_ids:
        work_order_result = await db.execute(select(WorkOrder).where(WorkOrder.id.in_(list(dict.fromkeys(work_order_ids)))))
        work_orders_by_id = {item.id: item for item in work_order_result.scalars().all()}
    source_dispatches_by_id: dict[str, DispatchTask] = {}
    if source_dispatch_ids:
        dispatch_result = await db.execute(
            select(DispatchTask).where(DispatchTask.id.in_(list(dict.fromkeys(source_dispatch_ids))))
        )
        source_dispatches_by_id = {item.id: item for item in dispatch_result.scalars().all()}
        user_ids.extend([item.assigned_to for item in source_dispatches_by_id.values() if item.assigned_to])
    users_by_id = await _load_users_by_ids(db, user_ids)

    payload = []
    for entry in entries:
        work_order = work_orders_by_id.get(entry.work_order_id)
        source_dispatch = source_dispatches_by_id.get(entry.source_dispatch_id or "")
        source_dispatch_user = users_by_id.get(getattr(source_dispatch, "assigned_to", "") or "")
        application_payloads = [
            serialize_dispatch_hall_application(
                item,
                applicant_user=users_by_id.get(item.applicant_user_id),
                handled_user=users_by_id.get(item.handled_by or ""),
            )
            for item in applications_map.get(entry.id, [])
        ]
        payload.append(
            serialize_dispatch_hall_entry(
                entry,
                assigned_user=users_by_id.get(entry.assigned_to or ""),
                assigned_by_user=users_by_id.get(entry.assigned_by or ""),
                created_by_user=users_by_id.get(entry.created_by or ""),
                work_order_summary={
                    "id": work_order.id,
                    "ticket_id": work_order.ticket_id,
                    "building_id": work_order.building_id,
                    "device_id": work_order.device_id,
                    "priority": work_order.priority,
                    "status": work_order.status,
                    "issue_description": work_order.issue_description,
                    "suggested_action": work_order.suggested_action,
                    "dispatch_blocked_reason": work_order.dispatch_blocked_reason,
                    "incident_id": work_order.incident_id,
                    "created_at": work_order.created_at.isoformat() if work_order.created_at else None,
                    "updated_at": work_order.updated_at.isoformat() if work_order.updated_at else None,
                } if work_order else None,
                source_dispatch_summary={
                    "id": source_dispatch.id,
                    "dispatch_status": source_dispatch.dispatch_status,
                    "assigned_to": source_dispatch.assigned_to,
                    "assigned_to_name": getattr(source_dispatch_user, "username", None),
                    "assigned_phone": getattr(source_dispatch_user, "phone", None),
                    "support_reason": source_dispatch.support_reason,
                    "latest_note": source_dispatch.latest_note,
                    "assigned_at": source_dispatch.assigned_at.isoformat() if source_dispatch.assigned_at else None,
                    "accepted_at": source_dispatch.accepted_at.isoformat() if source_dispatch.accepted_at else None,
                    "arrived_at": source_dispatch.arrived_at.isoformat() if source_dispatch.arrived_at else None,
                } if source_dispatch else None,
                applications=application_payloads,
            )
        )
    return payload


class HallApplyRequest(BaseModel):
    note: str | None = Field(default=None, max_length=500)


class HallAssignSupportRequest(BaseModel):
    assigned_to: str
    application_id: str | None = None
    note: str | None = Field(default=None, max_length=500)


class HallAssignTakeoverRequest(BaseModel):
    assigned_to: str
    application_id: str | None = None
    reason: str = Field(..., min_length=1, max_length=500)
    dispatch_mode: str = Field(
        default="hall_takeover",
        pattern=r"^(hall_takeover|reassigned|manual|assisted|auto|escalation)$",
    )


class HallCloseRequest(BaseModel):
    note: str | None = Field(default=None, max_length=500)


class HallRejectApplicationRequest(BaseModel):
    note: str | None = Field(default=None, max_length=500)


class HallWorkerSupportActionRequest(BaseModel):
    note: str | None = Field(default=None, max_length=500)


@router.get("", summary="获取共享工单大厅列表")
async def list_dispatch_hall_entries_endpoint(
    status: str | None = None,
    entry_type: str | None = None,
    assigned_to: str | None = None,
    work_order_id: str | None = None,
    incident_id: str | None = None,
    source_dispatch_id: str | None = None,
    building_id: str | None = None,
    target_team_id: str | None = None,
    sort_by: str = "ops_priority",
    include_applications: bool = False,
    page: int = 1,
    page_size: int = 20,
    db: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
):
    _require_role(user, "admin", "manager", "ops")
    viewer = await _resolve_viewer_context(db, user)
    if user.role == "ops" and assigned_to and assigned_to != user.id:
        raise HTTPException(status_code=403, detail="维修人员只能查看自己相关的共享工单")

    status_filter = [item.strip() for item in status.split(",") if item.strip()] if status else None
    entry_type_filter = [item.strip() for item in entry_type.split(",") if item.strip()] if entry_type else None
    items, total = await list_dispatch_hall_entries(
        db,
        viewer=viewer,
        status_filter=status_filter,
        entry_type_filter=entry_type_filter,
        assigned_to=assigned_to,
        work_order_id=work_order_id,
        incident_id=incident_id,
        source_dispatch_id=source_dispatch_id,
        building_id=building_id,
        target_team_id=target_team_id,
        sort_by=sort_by,
        page=page,
        page_size=page_size,
    )
    payload = await _serialize_hall_entries(db, items, include_applications=include_applications)
    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "hall_entries": payload,
    }


@router.get("/{entry_id}", summary="获取共享工单大厅详情")
async def get_dispatch_hall_entry_detail(
    entry_id: str,
    db: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
):
    _require_role(user, "admin", "manager", "ops")
    viewer = await _resolve_viewer_context(db, user)
    entry = await get_dispatch_hall_entry_by_id(db, entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="共享工单不存在")
    if user.role == "ops" and not can_view_dispatch_hall_entry(entry, viewer):
        raise HTTPException(status_code=403, detail="当前共享工单对你不可见")

    payload = await _serialize_hall_entries(db, [entry], include_applications=True)
    return payload[0]


@router.post("/{entry_id}/apply-support", summary="申请协同共享工单")
async def apply_support_dispatch_hall_entry(
    entry_id: str,
    req: HallApplyRequest,
    db: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
):
    _require_role(user, "ops")
    viewer = await _resolve_viewer_context(db, user)
    entry = await get_dispatch_hall_entry_by_id(db, entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="共享工单不存在")
    if not can_view_dispatch_hall_entry(entry, viewer):
        raise HTTPException(status_code=403, detail="当前共享工单对你不可见")

    try:
        application = await apply_to_dispatch_hall_entry(
            db,
            hall_entry=entry,
            applicant_user_id=user.id,
            application_type="support",
            note=req.note,
        )
        work_order = await _load_work_order(db, entry.work_order_id)
        await _write_audit_log(
            db,
            work_order_id=work_order.id,
            action="dispatch_hall_apply_support",
            old_status=work_order.status,
            new_status=work_order.status,
            actor_type="worker",
            actor_id=user.id,
            detail={"hall_entry_id": entry.id, "application_id": application.id, "note": req.note},
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    await db.commit()
    await _invalidate_related_cache()
    return {
        "hall_entry_id": entry.id,
        "application_id": application.id,
        "message": "已提交协同申请",
    }


@router.post("/{entry_id}/apply-takeover", summary="申请接管共享工单")
async def apply_takeover_dispatch_hall_entry(
    entry_id: str,
    req: HallApplyRequest,
    db: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
):
    _require_role(user, "ops")
    viewer = await _resolve_viewer_context(db, user)
    entry = await get_dispatch_hall_entry_by_id(db, entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="共享工单不存在")
    if not can_view_dispatch_hall_entry(entry, viewer):
        raise HTTPException(status_code=403, detail="当前共享工单对你不可见")

    try:
        application = await apply_to_dispatch_hall_entry(
            db,
            hall_entry=entry,
            applicant_user_id=user.id,
            application_type="takeover",
            note=req.note,
        )
        work_order = await _load_work_order(db, entry.work_order_id)
        await _write_audit_log(
            db,
            work_order_id=work_order.id,
            action="dispatch_hall_apply_takeover",
            old_status=work_order.status,
            new_status=work_order.status,
            actor_type="worker",
            actor_id=user.id,
            detail={"hall_entry_id": entry.id, "application_id": application.id, "note": req.note},
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    await db.commit()
    await _invalidate_related_cache()
    return {
        "hall_entry_id": entry.id,
        "application_id": application.id,
        "message": "已提交接管申请",
    }


@router.post("/{entry_id}/assign-support", summary="指派共享协同工单")
async def assign_support_dispatch_hall_entry_endpoint(
    entry_id: str,
    req: HallAssignSupportRequest,
    db: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
):
    _require_role(user, "admin", "manager")
    entry = await get_dispatch_hall_entry_by_id(db, entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="共享工单不存在")
    assigned_user = await _load_user_with_worker_context(db, req.assigned_to)
    if not assigned_user or assigned_user.role != "ops" or not assigned_user.is_active:
        raise HTTPException(status_code=404, detail="目标维修人员不存在或不可用")
    application = None
    if req.application_id:
        application = await get_dispatch_hall_application_by_id(db, req.application_id)
        if application is None:
            raise HTTPException(status_code=404, detail="协同申请不存在")

    try:
        await assign_support_hall_entry(
            db,
            hall_entry=entry,
            assigned_user=assigned_user,
            actor_id=user.id,
            application=application,
            handle_note=req.note,
        )
        work_order = await _load_work_order(db, entry.work_order_id)
        if entry.source_dispatch_id:
            dispatch_task = await get_dispatch_task_by_id(db, entry.source_dispatch_id)
            if dispatch_task is not None:
                await record_dispatch_event(
                    db,
                    dispatch_task=dispatch_task,
                    event_type="support_assigned",
                    actor_type="admin",
                    actor_id=user.id,
                    payload={
                        "hall_entry_id": entry.id,
                        "assigned_to": assigned_user.id,
                        "assigned_to_name": assigned_user.username,
                        "application_id": getattr(application, "id", None),
                        "note": req.note,
                    },
                )
        await _write_audit_log(
            db,
            work_order_id=work_order.id,
            action="dispatch_hall_assign_support",
            old_status=work_order.status,
            new_status=work_order.status,
            actor_type="admin",
            actor_id=user.id,
            detail={
                "hall_entry_id": entry.id,
                "assigned_to": assigned_user.id,
                "application_id": getattr(application, "id", None),
                "note": req.note,
            },
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    await db.commit()
    await _invalidate_related_cache()
    payload = await _serialize_hall_entries(db, [entry], include_applications=True)
    return {
        "hall_entry": payload[0],
        "message": f"已指派协同给 {assigned_user.username}",
    }


@router.post("/{entry_id}/accept-support", summary="维修人员确认协同任务")
async def accept_support_dispatch_hall_entry_endpoint(
    entry_id: str,
    req: HallWorkerSupportActionRequest,
    db: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
):
    _require_role(user, "ops")
    entry = await get_dispatch_hall_entry_by_id(db, entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="共享工单不存在")
    if entry.assigned_to != user.id:
        raise HTTPException(status_code=403, detail="只能确认分配给自己的协同任务")

    try:
        await accept_assigned_support_hall_entry(
            db,
            hall_entry=entry,
            actor_id=user.id,
        )
        work_order = await _load_work_order(db, entry.work_order_id)
        if entry.source_dispatch_id:
            dispatch_task = await get_dispatch_task_by_id(db, entry.source_dispatch_id)
            if dispatch_task is not None:
                await record_dispatch_event(
                    db,
                    dispatch_task=dispatch_task,
                    event_type="support_worker_accepted",
                    actor_type="worker",
                    actor_id=user.id,
                    payload={"hall_entry_id": entry.id, "note": req.note},
                )
        await _write_audit_log(
            db,
            work_order_id=work_order.id,
            action="dispatch_hall_support_accept",
            old_status=work_order.status,
            new_status=work_order.status,
            actor_type="worker",
            actor_id=user.id,
            detail={"hall_entry_id": entry.id, "note": req.note},
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    await db.commit()
    await _invalidate_related_cache()
    payload = await _serialize_hall_entries(db, [entry], include_applications=True)
    return {
        "hall_entry": payload[0],
        "message": "已确认协同任务",
    }


@router.post("/{entry_id}/reject-support", summary="维修人员拒绝协同任务")
async def reject_support_dispatch_hall_entry_endpoint(
    entry_id: str,
    req: HallWorkerSupportActionRequest,
    db: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
):
    _require_role(user, "ops")
    entry = await get_dispatch_hall_entry_by_id(db, entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="共享工单不存在")
    if entry.assigned_to != user.id:
        raise HTTPException(status_code=403, detail="只能拒绝分配给自己的协同任务")

    try:
        await reject_assigned_support_hall_entry(
            db,
            hall_entry=entry,
            actor_id=user.id,
            note=req.note,
        )
        work_order = await _load_work_order(db, entry.work_order_id)
        if entry.source_dispatch_id:
            dispatch_task = await get_dispatch_task_by_id(db, entry.source_dispatch_id)
            if dispatch_task is not None:
                await record_dispatch_event(
                    db,
                    dispatch_task=dispatch_task,
                    event_type="support_worker_rejected",
                    actor_type="worker",
                    actor_id=user.id,
                    payload={"hall_entry_id": entry.id, "note": req.note},
                )
        await _write_audit_log(
            db,
            work_order_id=work_order.id,
            action="dispatch_hall_support_reject",
            old_status=work_order.status,
            new_status=work_order.status,
            actor_type="worker",
            actor_id=user.id,
            detail={"hall_entry_id": entry.id, "note": req.note},
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    await db.commit()
    await _invalidate_related_cache()
    payload = await _serialize_hall_entries(db, [entry], include_applications=True)
    return {
        "hall_entry": payload[0],
        "message": "已拒绝协同任务，任务已退回共享大厅",
    }


@router.post("/{entry_id}/assign-takeover", summary="指派共享接管工单")
async def assign_takeover_dispatch_hall_entry_endpoint(
    entry_id: str,
    req: HallAssignTakeoverRequest,
    db: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
):
    _require_role(user, "admin", "manager")
    entry = await get_dispatch_hall_entry_by_id(db, entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="共享工单不存在")
    assigned_user = await _load_user_with_worker_context(db, req.assigned_to)
    if not assigned_user or assigned_user.role != "ops" or not assigned_user.is_active:
        raise HTTPException(status_code=404, detail="目标维修人员不存在或不可用")
    application = None
    if req.application_id:
        application = await get_dispatch_hall_application_by_id(db, req.application_id)
        if application is None:
            raise HTTPException(status_code=404, detail="接管申请不存在")

    work_order = await _load_work_order(db, entry.work_order_id)
    if not entry.source_dispatch_id:
        raise HTTPException(status_code=409, detail="当前共享工单缺少来源派工，无法执行接管")
    source_dispatch = await get_dispatch_task_by_id(db, entry.source_dispatch_id)
    if source_dispatch is None:
        raise HTTPException(status_code=404, detail="来源派工不存在")

    try:
        new_dispatch = await reassign_dispatch_task(
            db,
            work_order=work_order,
            dispatch_task=source_dispatch,
            assigned_user=assigned_user,
            actor_type="admin",
            actor_id=user.id,
            reason=req.reason,
            dispatch_mode=req.dispatch_mode,
            close_related_hall_entries=False,
        )
        if application is not None:
            await approve_dispatch_hall_application(
                db,
                application=application,
                actor_id=user.id,
                handle_note=req.reason,
            )
        await close_dispatch_hall_entry(
            db,
            hall_entry=entry,
            actor_id=user.id,
            handle_note="共享接管已完成正式改派",
        )
        await _write_audit_log(
            db,
            work_order_id=work_order.id,
            action="dispatch_hall_assign_takeover",
            old_status=work_order.status,
            new_status=work_order.status,
            actor_type="admin",
            actor_id=user.id,
            detail={
                "hall_entry_id": entry.id,
                "application_id": getattr(application, "id", None),
                "assigned_to": assigned_user.id,
                "reason": req.reason,
                "dispatch_id": new_dispatch.id,
            },
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    await db.commit()
    await _invalidate_related_cache()
    payload = await _serialize_hall_entries(db, [entry], include_applications=True)
    return {
        "hall_entry": payload[0],
        "dispatch": serialize_dispatch_task(new_dispatch, assigned_user=assigned_user),
        "message": f"已将接管任务正式派给 {assigned_user.username}",
    }


@router.post("/applications/{application_id}/reject", summary="驳回共享工单申请")
async def reject_dispatch_hall_application_endpoint(
    application_id: str,
    req: HallRejectApplicationRequest,
    db: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
):
    _require_role(user, "admin", "manager")
    application = await get_dispatch_hall_application_by_id(db, application_id)
    if application is None:
        raise HTTPException(status_code=404, detail="共享工单申请不存在")

    try:
        await reject_dispatch_hall_application(
            db,
            application=application,
            actor_id=user.id,
            handle_note=req.note,
        )
        entry = await get_dispatch_hall_entry_by_id(db, application.hall_entry_id)
        if entry is not None:
            work_order = await _load_work_order(db, entry.work_order_id)
            await _write_audit_log(
                db,
                work_order_id=work_order.id,
                action="dispatch_hall_reject_application",
                old_status=work_order.status,
                new_status=work_order.status,
                actor_type="admin",
                actor_id=user.id,
                detail={
                    "hall_entry_id": entry.id,
                    "application_id": application.id,
                    "applicant_user_id": application.applicant_user_id,
                    "note": req.note,
                },
            )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    await db.commit()
    await _invalidate_related_cache()
    return {
        "application_id": application.id,
        "message": "已驳回申请",
    }


@router.post("/applications/{application_id}/withdraw", summary="维修人员撤回共享工单申请")
async def withdraw_dispatch_hall_application_endpoint(
    application_id: str,
    db: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
):
    _require_role(user, "ops")
    application = await get_dispatch_hall_application_by_id(db, application_id)
    if application is None:
        raise HTTPException(status_code=404, detail="共享工单申请不存在")
    if application.applicant_user_id != user.id:
        raise HTTPException(status_code=403, detail="只能撤回自己提交的申请")

    try:
        await withdraw_dispatch_hall_application(
            db,
            application=application,
            actor_id=user.id,
        )
        hall_entry = await get_dispatch_hall_entry_by_id(db, application.hall_entry_id)
        if hall_entry is not None:
            work_order = await _load_work_order(db, hall_entry.work_order_id)
            await _write_audit_log(
                db,
                work_order_id=work_order.id,
                action="dispatch_hall_withdraw_application",
                old_status=work_order.status,
                new_status=work_order.status,
                actor_type="worker",
                actor_id=user.id,
                detail={"hall_entry_id": hall_entry.id, "application_id": application.id},
            )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    await db.commit()
    await _invalidate_related_cache()
    return {
        "application_id": application.id,
        "message": "已撤回申请",
    }


@router.post("/{entry_id}/close", summary="关闭共享工单")
async def close_dispatch_hall_entry_endpoint(
    entry_id: str,
    req: HallCloseRequest,
    db: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
):
    _require_role(user, "admin", "manager")
    entry = await get_dispatch_hall_entry_by_id(db, entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="共享工单不存在")

    try:
        await close_dispatch_hall_entry(
            db,
            hall_entry=entry,
            actor_id=user.id,
            handle_note=req.note,
        )
        work_order = await _load_work_order(db, entry.work_order_id)
        await _write_audit_log(
            db,
            work_order_id=work_order.id,
            action="dispatch_hall_close",
            old_status=work_order.status,
            new_status=work_order.status,
            actor_type="admin",
            actor_id=user.id,
            detail={"hall_entry_id": entry.id, "note": req.note},
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    await db.commit()
    await _invalidate_related_cache()
    return {
        "hall_entry_id": entry.id,
        "message": "共享工单已关闭",
    }
