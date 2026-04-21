from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.cache import delete_cache_by_prefix
from app.core.person_name import format_person_display_name
from app.core.security import get_current_user
from app.db.models import (
    Building,
    DispatchTask,
    User,
    WorkerProfile,
    WorkerProfileSkill,
    WorkerSkill,
    WorkerTeam,
)
from app.db.session import get_db_session

router = APIRouter(prefix="/worker-profiles", tags=["维修人员画像"])

_ACTIVE_DISPATCH_STATUSES = {"assigned", "accepted", "arrived", "processing", "waiting_support"}


class WorkerProfileSkillInput(BaseModel):
    skill_id: str
    proficiency: int = Field(default=3, ge=1, le=5)
    is_primary: bool = False


class WorkerProfileUpdate(BaseModel):
    team_id: str | None = None
    job_title: str | None = Field(default=None, max_length=64)
    shift_status: str | None = Field(default=None, pattern=r"^(on_duty|standby|busy|off_duty)$")
    dispatch_enabled: bool | None = None
    max_active_orders: int | None = Field(default=None, ge=1, le=20)
    accepts_emergency: bool | None = None
    service_buildings: list[str] | None = None
    notes: str | None = Field(default=None, max_length=1000)
    skills: list[WorkerProfileSkillInput] | None = None


class WorkerProfileSelfUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    shift_status: str | None = Field(default=None, pattern=r"^(on_duty|standby|busy|off_duty)$")
    dispatch_enabled: bool | None = None
    accepts_emergency: bool | None = None
    notes: str | None = Field(default=None, max_length=1000)


def _require_role(user: User, *roles: str) -> None:
    if user.role not in roles:
        raise HTTPException(status_code=403, detail="权限不足")


def _json_list(value: str | None) -> list[str]:
    if not value:
        return []
    try:
        parsed = json.loads(value)
    except Exception:
        return []
    if not isinstance(parsed, list):
        return []
    return [str(item) for item in parsed if item is not None and str(item).strip()]


def _json_dumps_list(items: list[str] | None) -> str | None:
    normalized = [str(item).strip() for item in (items or []) if str(item).strip()]
    if not normalized:
        return None
    return json.dumps(list(dict.fromkeys(normalized)), ensure_ascii=False)


def _dt(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _serialize_team(team: WorkerTeam) -> dict[str, Any]:
    return {
        "id": team.id,
        "team_code": team.team_code,
        "name": team.name,
        "description": team.description,
        "service_buildings": _json_list(team.service_buildings_json),
        "is_active": team.is_active,
        "created_at": _dt(team.created_at),
    }


def _serialize_skill(skill: WorkerSkill) -> dict[str, Any]:
    return {
        "id": skill.id,
        "code": skill.code,
        "name": skill.name,
        "category": skill.category,
        "description": skill.description,
        "is_active": skill.is_active,
        "created_at": _dt(skill.created_at),
    }


def serialize_worker_profile(user: User, *, active_orders: int = 0) -> dict[str, Any]:
    profile = getattr(user, "worker_profile", None)
    skill_links = sorted(
        list(getattr(profile, "skill_links", []) or []),
        key=lambda item: (not bool(getattr(item, "is_primary", False)), getattr(getattr(item, "skill", None), "name", "")),
    )
    max_active_orders = int(getattr(profile, "max_active_orders", 4) or 4) if profile else 4
    display_username = format_person_display_name(user.username) or user.username
    return {
        "user": {
            "id": user.id,
            "username": display_username,
            "email": user.email,
            "phone": user.phone,
            "role": user.role,
            "is_active": user.is_active,
            "created_at": _dt(user.created_at),
        },
        "profile_exists": profile is not None,
        "team": _serialize_team(profile.team) if profile and profile.team else None,
        "team_id": getattr(profile, "team_id", None) if profile else None,
        "job_title": getattr(profile, "job_title", None) if profile else None,
        "shift_status": getattr(profile, "shift_status", "on_duty") if profile else "on_duty",
        "dispatch_enabled": bool(getattr(profile, "dispatch_enabled", True)) if profile else True,
        "max_active_orders": max_active_orders,
        "active_orders": active_orders,
        "capacity_ratio": round(active_orders / max(max_active_orders, 1), 3),
        "accepts_emergency": bool(getattr(profile, "accepts_emergency", True)) if profile else True,
        "service_buildings": _json_list(getattr(profile, "service_buildings_json", None)) if profile else [],
        "notes": getattr(profile, "notes", None) if profile else None,
        "skills": [
            {
                "skill_id": link.skill_id,
                "code": getattr(link.skill, "code", None),
                "name": getattr(link.skill, "name", None),
                "category": getattr(link.skill, "category", None),
                "proficiency": link.proficiency,
                "is_primary": link.is_primary,
            }
            for link in skill_links
            if getattr(link, "skill", None) is not None
        ],
        "created_at": _dt(getattr(profile, "created_at", None)) if profile else None,
        "updated_at": _dt(getattr(profile, "updated_at", None)) if profile else None,
    }


async def _invalidate_worker_profile_cache() -> None:
    await delete_cache_by_prefix("workorders:")
    await delete_cache_by_prefix("incidents:")


async def _load_worker_user(db: AsyncSession, user_id: str) -> User | None:
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


async def _load_active_dispatch_counts(db: AsyncSession) -> dict[str, int]:
    result = await db.execute(
        select(DispatchTask.assigned_to, func.count(DispatchTask.id))
        .where(
            DispatchTask.is_current.is_(True),
            DispatchTask.assigned_to.is_not(None),
            DispatchTask.dispatch_status.in_(_ACTIVE_DISPATCH_STATUSES),
        )
        .group_by(DispatchTask.assigned_to)
    )
    return {str(user_id): int(count) for user_id, count in result.all() if user_id}


@router.get("", summary="获取维修人员画像列表")
async def list_worker_profiles_endpoint(
    db: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
):
    _require_role(user, "admin", "manager")
    result = await db.execute(
        select(User)
        .options(
            selectinload(User.worker_profile).selectinload(WorkerProfile.team),
            selectinload(User.worker_profile)
            .selectinload(WorkerProfile.skill_links)
            .selectinload(WorkerProfileSkill.skill),
        )
        .where(User.role == "ops")
        .order_by(User.username.asc())
    )
    users = list(result.scalars().unique().all())
    active_counts = await _load_active_dispatch_counts(db)
    profiles = [serialize_worker_profile(item, active_orders=active_counts.get(item.id, 0)) for item in users]
    return {
        "total": len(profiles),
        "profiles": profiles,
        "summary": {
            "workers_total": len(profiles),
            "dispatch_enabled": sum(1 for item in profiles if item["dispatch_enabled"]),
            "on_duty": sum(1 for item in profiles if item["shift_status"] == "on_duty"),
            "over_capacity": sum(1 for item in profiles if item["active_orders"] >= item["max_active_orders"]),
        },
    }


@router.get("/options", summary="获取维修画像管理选项")
async def get_worker_profile_options_endpoint(
    db: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
):
    _require_role(user, "admin", "manager")
    teams = list((await db.execute(select(WorkerTeam).order_by(WorkerTeam.name.asc()))).scalars().all())
    skills = list((await db.execute(select(WorkerSkill).order_by(WorkerSkill.category.asc(), WorkerSkill.name.asc()))).scalars().all())
    buildings = list((await db.execute(select(Building).order_by(Building.building_id.asc()))).scalars().all())
    return {
        "teams": [_serialize_team(item) for item in teams],
        "skills": [_serialize_skill(item) for item in skills],
        "buildings": [
            {
                "building_id": item.building_id,
                "primary_space_usage": item.primary_space_usage,
                "sqm": item.sqm,
            }
            for item in buildings
        ],
        "shift_statuses": [
            {"value": "on_duty", "label": "值班"},
            {"value": "standby", "label": "备勤"},
            {"value": "busy", "label": "忙碌"},
            {"value": "off_duty", "label": "离岗"},
        ],
    }


@router.get("/me", summary="获取当前维修员派工画像")
async def get_my_worker_profile_endpoint(
    db: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
):
    _require_role(user, "ops")
    worker = await _load_worker_user(db, user.id)
    if worker is None:
        raise HTTPException(status_code=404, detail="维修人员不存在")
    active_counts = await _load_active_dispatch_counts(db)
    return serialize_worker_profile(worker, active_orders=active_counts.get(worker.id, 0))


@router.patch("/me", summary="维修员更新自己的派工状态")
async def update_my_worker_profile_endpoint(
    req: WorkerProfileSelfUpdate,
    db: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
):
    _require_role(user, "ops")
    worker = await _load_worker_user(db, user.id)
    if worker is None:
        raise HTTPException(status_code=404, detail="维修人员不存在")

    profile = worker.worker_profile
    if profile is None:
        profile = WorkerProfile(user_id=worker.id)
        db.add(profile)

    fields = req.model_fields_set
    if "shift_status" in fields and req.shift_status:
        profile.shift_status = req.shift_status
    if "dispatch_enabled" in fields and req.dispatch_enabled is not None:
        profile.dispatch_enabled = req.dispatch_enabled
    if "accepts_emergency" in fields and req.accepts_emergency is not None:
        profile.accepts_emergency = req.accepts_emergency
    if "notes" in fields:
        profile.notes = req.notes or None

    await db.commit()
    await _invalidate_worker_profile_cache()

    refreshed = await _load_worker_user(db, user.id)
    active_counts = await _load_active_dispatch_counts(db)
    return serialize_worker_profile(refreshed, active_orders=active_counts.get(user.id, 0))


@router.patch("/{user_id}", summary="更新维修人员画像")
async def update_worker_profile_endpoint(
    user_id: str,
    req: WorkerProfileUpdate,
    db: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
):
    _require_role(user, "admin", "manager")
    worker = await _load_worker_user(db, user_id)
    if worker is None or worker.role != "ops":
        raise HTTPException(status_code=404, detail="维修人员不存在")

    profile = worker.worker_profile
    if profile is None:
        profile = WorkerProfile(user_id=worker.id)
        db.add(profile)

    fields = req.model_fields_set
    if "team_id" in fields:
        if req.team_id:
            team = await db.get(WorkerTeam, req.team_id)
            if team is None:
                raise HTTPException(status_code=404, detail="班组不存在")
        profile.team_id = req.team_id or None
    if "job_title" in fields:
        profile.job_title = req.job_title or None
    if "shift_status" in fields and req.shift_status:
        profile.shift_status = req.shift_status
    if "dispatch_enabled" in fields and req.dispatch_enabled is not None:
        profile.dispatch_enabled = req.dispatch_enabled
    if "max_active_orders" in fields and req.max_active_orders is not None:
        profile.max_active_orders = req.max_active_orders
    if "accepts_emergency" in fields and req.accepts_emergency is not None:
        profile.accepts_emergency = req.accepts_emergency
    if "service_buildings" in fields:
        building_ids = list(dict.fromkeys([item for item in (req.service_buildings or []) if item]))
        if building_ids:
            existing = set(
                (await db.execute(select(Building.building_id).where(Building.building_id.in_(building_ids)))).scalars().all()
            )
            missing = [item for item in building_ids if item not in existing]
            if missing:
                raise HTTPException(status_code=404, detail=f"楼宇不存在：{', '.join(missing)}")
        profile.service_buildings_json = _json_dumps_list(building_ids)
    if "notes" in fields:
        profile.notes = req.notes or None
    if req.skills is not None:
        skill_ids = [item.skill_id for item in req.skills]
        if len(skill_ids) != len(set(skill_ids)):
            raise HTTPException(status_code=400, detail="技能不能重复选择")
        if skill_ids:
            existing = set((await db.execute(select(WorkerSkill.id).where(WorkerSkill.id.in_(skill_ids)))).scalars().all())
            missing = [item for item in skill_ids if item not in existing]
            if missing:
                raise HTTPException(status_code=404, detail=f"技能不存在：{', '.join(missing)}")
        await db.execute(delete(WorkerProfileSkill).where(WorkerProfileSkill.profile_user_id == worker.id))
        for item in req.skills:
            db.add(
                WorkerProfileSkill(
                    profile_user_id=worker.id,
                    skill_id=item.skill_id,
                    proficiency=item.proficiency,
                    is_primary=item.is_primary,
                )
            )

    await db.commit()
    await _invalidate_worker_profile_cache()

    refreshed = await _load_worker_user(db, user_id)
    active_counts = await _load_active_dispatch_counts(db)
    return serialize_worker_profile(refreshed, active_orders=active_counts.get(user_id, 0))
