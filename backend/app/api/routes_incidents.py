from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.cache import get_or_compute_json
from app.core.config import get_settings
from app.core.security import get_current_user
from app.db.models import User, WorkOrder, WorkOrderAuditLog
from app.db.session import get_db_session
from app.services.incident_service import (
    get_incident_by_identifier,
    list_incident_event_links,
    list_incident_prediction_links,
    list_incident_work_orders,
    list_incidents,
    serialize_incident,
    serialize_incident_detail,
)

router = APIRouter(prefix="/incidents", tags=["incident"])
settings = get_settings()


def _require_role(user: User, *roles: str) -> None:
    if user.role not in roles:
        raise HTTPException(status_code=403, detail="权限不足")


@router.get("", summary="获取 incident 列表")
async def list_incidents_endpoint(
    workflow_status: str | None = Query(None, description="按当前工单状态过滤，逗号分隔多值"),
    building_id: str | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
):
    _require_role(user, "admin", "manager", "ops")

    workflow_status_filter = (
        [s.strip() for s in workflow_status.split(",") if s.strip()]
        if workflow_status else None
    )
    cache_scope = user.id if user.role == "ops" else "all"
    cache_key = f"incidents:list:{cache_scope}:{workflow_status or 'all'}:{building_id or ''}:{page}:{page_size}"
    ttl = settings.CACHE_WORKORDERS_TTL_SECONDS

    async def _compute() -> dict[str, Any]:
        items, total = await list_incidents(
            db,
            workflow_status_filter=workflow_status_filter,
            building_id=building_id,
            assigned_to=user.id if user.role == "ops" else None,
            page=page,
            page_size=page_size,
        )
        work_order_ids = [i.current_work_order_id for i in items if i.current_work_order_id]
        work_orders_by_id: dict[str, WorkOrder] = {}
        assigned_users_by_id: dict[str, User] = {}
        audit_logs_by_work_order_id: dict[str, list[WorkOrderAuditLog]] = {}
        if work_order_ids:
            result = await db.execute(
                select(WorkOrder).where(WorkOrder.id.in_(work_order_ids))
            )
            work_orders = result.scalars().all()
            work_orders_by_id = {wo.id: wo for wo in work_orders}

            assigned_user_ids = [wo.assigned_to for wo in work_orders if wo.assigned_to]
            if assigned_user_ids:
                user_result = await db.execute(
                    select(User).where(User.id.in_(assigned_user_ids))
                )
                assigned_users_by_id = {u.id: u for u in user_result.scalars().all()}

            audit_result = await db.execute(
                select(WorkOrderAuditLog)
                .where(WorkOrderAuditLog.work_order_id.in_(work_order_ids))
                .order_by(WorkOrderAuditLog.created_at.asc())
            )
            for log in audit_result.scalars().all():
                audit_logs_by_work_order_id.setdefault(log.work_order_id, []).append(log)

        serialized_incidents: list[dict[str, Any]] = []
        for incident in items:
            current_work_order = work_orders_by_id.get(incident.current_work_order_id or "")
            assigned_user = assigned_users_by_id.get(current_work_order.assigned_to or "") if current_work_order else None
            serialized_incidents.append(
                serialize_incident(
                    incident,
                    current_work_order=current_work_order,
                    assigned_user=assigned_user,
                    audit_logs=audit_logs_by_work_order_id.get(incident.current_work_order_id or "", []),
                )
            )

        return {
            "total": total,
            "page": page,
            "page_size": page_size,
            "incidents": serialized_incidents,
        }

    return await get_or_compute_json(cache_key, ttl, _compute)


@router.get("/{incident_identifier}", summary="获取 incident 详情")
async def get_incident_detail_endpoint(
    incident_identifier: str,
    db: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
):
    _require_role(user, "admin", "manager", "ops")
    cache_scope = user.id if user.role == "ops" else "all"
    cache_key = f"incidents:detail:{cache_scope}:{incident_identifier}"
    ttl = settings.CACHE_WORKORDERS_TTL_SECONDS

    async def _compute() -> dict[str, Any]:
        incident = await get_incident_by_identifier(db, incident_identifier)
        if not incident:
            raise HTTPException(status_code=404, detail="incident 不存在")

        work_orders = await list_incident_work_orders(db, incident_id=incident.id)
        if user.role == "ops":
            if not any((wo.assigned_to == user.id) for wo in work_orders):
                raise HTTPException(status_code=403, detail="只能查看派发给自己的 incident")

        current_work_order = None
        if incident.current_work_order_id:
            current_work_order = next(
                (wo for wo in work_orders if wo.id == incident.current_work_order_id),
                None,
            )
            if current_work_order is None:
                current_work_order = await db.get(WorkOrder, incident.current_work_order_id)

        assigned_users_by_id: dict[str, User] = {}
        audit_logs_by_work_order_id: dict[str, list[WorkOrderAuditLog]] = {}
        if work_orders:
            assigned_user_ids = [wo.assigned_to for wo in work_orders if wo.assigned_to]
            if assigned_user_ids:
                user_result = await db.execute(
                    select(User).where(User.id.in_(assigned_user_ids))
                )
                assigned_users_by_id = {u.id: u for u in user_result.scalars().all()}

            work_order_ids = [wo.id for wo in work_orders]
            audit_result = await db.execute(
                select(WorkOrderAuditLog)
                .where(WorkOrderAuditLog.work_order_id.in_(work_order_ids))
                .order_by(WorkOrderAuditLog.created_at.asc())
            )
            for log in audit_result.scalars().all():
                audit_logs_by_work_order_id.setdefault(log.work_order_id, []).append(log)

        event_links = await list_incident_event_links(db, incident_id=incident.id)
        prediction_links = await list_incident_prediction_links(db, incident_id=incident.id)
        return serialize_incident_detail(
            incident,
            current_work_order=current_work_order,
            work_orders=work_orders,
            event_links=event_links,
            prediction_links=prediction_links,
            assigned_users_by_id=assigned_users_by_id,
            audit_logs_by_work_order_id=audit_logs_by_work_order_id,
        )

    return await get_or_compute_json(cache_key, ttl, _compute)
