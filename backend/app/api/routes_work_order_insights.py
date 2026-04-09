from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import get_current_user
from app.db.models import User
from app.db.session import get_db_session
from app.services.work_order_insights_service import (
    build_work_order_insight_metrics,
    build_work_order_insight_query_response,
)

router = APIRouter(prefix="/work-order-insights", tags=["工单运营洞察"])


class WorkOrderInsightQueryRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=500)


def _require_role(user: User, *roles: str) -> None:
    if user.role not in roles:
        raise HTTPException(status_code=403, detail="权限不足")


@router.get("/metrics", summary="获取工单运营洞察指标")
async def get_work_order_insight_metrics(
    db: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
):
    _require_role(user, "admin", "manager")
    return await build_work_order_insight_metrics(db)


@router.post("/query", summary="只读工单运营问询")
async def query_work_order_insights(
    req: WorkOrderInsightQueryRequest,
    db: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
):
    _require_role(user, "admin", "manager")
    metrics = await build_work_order_insight_metrics(db)
    return build_work_order_insight_query_response(
        question=req.question,
        metrics=metrics,
    )
