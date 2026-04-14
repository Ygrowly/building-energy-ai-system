from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import get_current_user
from app.db.models import User
from app.db.session import get_db_session
from app.services.maintenance_experience_service import (
    add_maintenance_experience_feedback,
    create_maintenance_experience,
    deactivate_maintenance_experience,
    search_maintenance_experiences,
)

router = APIRouter(prefix="/maintenance-experiences", tags=["经验库"])


class MaintenanceExperienceCreateRequest(BaseModel):
    source_type: str = Field(..., min_length=1, max_length=32)
    source_work_order_id: str | None = Field(default=None, max_length=64)
    source_dispatch_id: str | None = Field(default=None, max_length=128)
    source_step_plan_id: str | None = Field(default=None, max_length=128)
    contributor_user_id: str | None = Field(default=None, max_length=128)
    contributor_role: str | None = Field(default=None, max_length=32)
    building_id: str | None = Field(default=None, max_length=64)
    device_id: str | None = Field(default=None, max_length=128)
    device_type: str | None = Field(default=None, max_length=64)
    fault_type: str | None = Field(default=None, max_length=128)
    source_text: str = Field(..., min_length=1, max_length=4000)


class MaintenanceExperienceFeedbackRequest(BaseModel):
    work_order_id: str | None = Field(default=None, max_length=64)
    feedback: str = Field(..., min_length=1, max_length=24)
    note: str | None = Field(default=None, max_length=1000)


class MaintenanceExperienceDeactivateRequest(BaseModel):
    reason: str | None = Field(default=None, max_length=1000)


@router.post("", summary="新增维修经验")
async def create_experience(
    req: MaintenanceExperienceCreateRequest,
    db: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
):
    return await create_maintenance_experience(
        db,
        actor_user_id=user.id,
        actor_role=user.role,
        source_type=req.source_type,
        source_text=req.source_text,
        source_work_order_id=req.source_work_order_id,
        source_dispatch_id=req.source_dispatch_id,
        source_step_plan_id=req.source_step_plan_id,
        contributor_user_id=req.contributor_user_id,
        contributor_role=req.contributor_role,
        building_id=req.building_id,
        device_id=req.device_id,
        device_type=req.device_type,
        fault_type=req.fault_type,
    )


@router.get("/search", summary="搜索维修经验")
async def search_experiences(
    query: str | None = Query(default=None, max_length=200),
    building_id: str | None = Query(default=None, max_length=64),
    device_type: str | None = Query(default=None, max_length=64),
    fault_type: str | None = Query(default=None, max_length=128),
    limit: int = Query(default=5, ge=1, le=20),
    include_inactive: bool = Query(default=False),
    sort_by: str = Query(default="score", pattern="^(score|recent|usage)$"),
    db: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
):
    return await search_maintenance_experiences(
        db,
        actor_role=user.role,
        query=query,
        building_id=building_id,
        device_type=device_type,
        fault_type=fault_type,
        limit=limit,
        include_inactive=include_inactive,
        sort_by=sort_by,
    )


@router.post("/{experience_id}/feedback", summary="提交经验反馈")
async def feedback_experience(
    experience_id: str,
    req: MaintenanceExperienceFeedbackRequest,
    db: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
):
    return await add_maintenance_experience_feedback(
        db,
        actor_user_id=user.id,
        actor_role=user.role,
        experience_id=experience_id,
        feedback=req.feedback,
        work_order_id=req.work_order_id,
        note=req.note,
    )


@router.post("/{experience_id}/deactivate", summary="停用经验")
async def deactivate_experience(
    experience_id: str,
    req: MaintenanceExperienceDeactivateRequest,
    db: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
):
    return await deactivate_maintenance_experience(
        db,
        actor_user_id=user.id,
        actor_role=user.role,
        experience_id=experience_id,
        reason=req.reason,
    )
