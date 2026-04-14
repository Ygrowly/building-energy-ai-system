from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import get_current_user
from app.db.models import User
from app.db.session import get_db_session
from app.services.work_order_insights_service import (
    AUTO_DISPATCH_OPERATION_MODES,
    AUTO_DISPATCH_RUN_HEALTH_SOURCES,
    AUTO_REASSIGN_SHADOW_TRIGGER_REASONS,
    build_auto_dispatch_operation_insights,
    build_auto_dispatch_run_health_insights,
    build_auto_reassign_shadow_insights,
    build_work_order_insight_metrics,
    build_work_order_insight_query_response,
    build_work_order_operation_insights,
    explain_auto_dispatch_operation_insights,
)
from app.services.work_order_analysis_service import (
    build_work_order_facts_response,
    build_work_order_report_response,
)

router = APIRouter(prefix="/work-order-insights", tags=["工单运营洞察"])


class WorkOrderInsightQueryRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=500)


class WorkOrderInsightFactsRequest(BaseModel):
    question: str | None = Field(default=None, max_length=500)
    intent: str | None = Field(default=None, max_length=64)
    date_from: date | None = None
    date_to: date | None = None
    building_id: str | None = None
    worker_id: str | None = None
    worker_name: str | None = Field(default=None, max_length=128)
    team_id: str | None = None
    team_name: str | None = Field(default=None, max_length=128)
    status: list[str] | None = None
    group_by: str | None = Field(default=None, max_length=32)
    metrics: list[str] | None = None
    include_chart: bool = True


class WorkOrderInsightReportRequest(BaseModel):
    report_type: str = Field(..., max_length=32)
    question: str | None = Field(default=None, max_length=500)
    date_from: date | None = None
    date_to: date | None = None
    building_id: str | None = None
    worker_id: str | None = None
    worker_name: str | None = Field(default=None, max_length=128)
    team_id: str | None = None
    team_name: str | None = Field(default=None, max_length=128)
    status: list[str] | None = None
    group_by: str | None = Field(default=None, max_length=32)
    metrics: list[str] | None = None
    include_chart: bool = True


class AutoDispatchOperationExplainRequest(BaseModel):
    question: str | None = Field(default=None, max_length=500)
    use_llm: bool = True
    date_from: date | None = None
    date_to: date | None = None
    building_id: str | None = None
    priority: str | None = None
    required_skill: str | None = None
    dispatch_mode: str | None = None
    team_id: str | None = None
    assignee_id: str | None = None


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


@router.get("/operations", summary="获取通用工单运营洞察")
async def get_work_order_operation_insights(
    date_from: date | None = Query(None, description="统计开始日期，闭区间"),
    date_to: date | None = Query(None, description="统计结束日期，闭区间"),
    building_id: str | None = Query(None, description="楼宇 ID"),
    priority: str | None = Query(None, description="优先级"),
    required_skill: str | None = Query(None, description="派工技能标签"),
    status: str | None = Query(None, description="工单主状态"),
    dispatch_status: str | None = Query(None, description="当前派工阶段"),
    timeout_level: str | None = Query(None, description="当前超时等级"),
    team_id: str | None = Query(None, description="当前责任班组 ID"),
    assignee_id: str | None = Query(None, description="当前责任人 ID"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
):
    _require_role(user, "admin", "manager")
    return await build_work_order_operation_insights(
        db,
        date_from=date_from,
        date_to=date_to,
        building_id=building_id,
        priority=priority,
        required_skill=required_skill,
        status=status,
        dispatch_status=dispatch_status,
        timeout_level=timeout_level,
        team_id=team_id,
        assignee_id=assignee_id,
        page=page,
        page_size=page_size,
    )


@router.get("/auto-dispatch-operations", summary="获取自动派工与大厅兜底运营洞察")
async def get_auto_dispatch_operation_insights(
    date_from: date | None = Query(None, description="统计开始日期，闭区间"),
    date_to: date | None = Query(None, description="统计结束日期，闭区间"),
    building_id: str | None = Query(None, description="楼宇 ID"),
    priority: str | None = Query(None, description="优先级"),
    required_skill: str | None = Query(None, description="派工技能标签"),
    dispatch_mode: str | None = Query(None, description="auto / auto_fallback / hall_fallback / rollout_hall_fallback"),
    team_id: str | None = Query(None, description="班组 ID"),
    assignee_id: str | None = Query(None, description="维修人员 ID"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
):
    _require_role(user, "admin", "manager")
    if dispatch_mode and dispatch_mode != "all" and dispatch_mode not in AUTO_DISPATCH_OPERATION_MODES:
        raise HTTPException(status_code=400, detail="不支持的派工模式筛选")
    return await build_auto_dispatch_operation_insights(
        db,
        date_from=date_from,
        date_to=date_to,
        building_id=building_id,
        priority=priority,
        required_skill=required_skill,
        dispatch_mode=dispatch_mode,
        team_id=team_id,
        assignee_id=assignee_id,
        page=page,
        page_size=page_size,
    )


@router.post("/auto-dispatch-operations/explain", summary="解释自动派工与大厅兜底运营洞察")
async def explain_auto_dispatch_operations(
    req: AutoDispatchOperationExplainRequest,
    db: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
):
    _require_role(user, "admin", "manager")
    if req.dispatch_mode and req.dispatch_mode != "all" and req.dispatch_mode not in AUTO_DISPATCH_OPERATION_MODES:
        raise HTTPException(status_code=400, detail="不支持的派工模式筛选")
    return await explain_auto_dispatch_operation_insights(
        db,
        question=req.question,
        use_llm=req.use_llm,
        date_from=req.date_from,
        date_to=req.date_to,
        building_id=req.building_id,
        priority=req.priority,
        required_skill=req.required_skill,
        dispatch_mode=req.dispatch_mode,
        team_id=req.team_id,
        assignee_id=req.assignee_id,
    )


@router.get("/auto-reassign-shadow", summary="获取自动重派一期影子观察洞察")
async def get_auto_reassign_shadow_insights(
    date_from: date | None = Query(None, description="统计开始日期，闭区间"),
    date_to: date | None = Query(None, description="统计结束日期，闭区间"),
    building_id: str | None = Query(None, description="楼宇 ID"),
    priority: str | None = Query(None, description="优先级"),
    required_skill: str | None = Query(None, description="派工技能标签"),
    trigger_reason: str | None = Query(None, description="assigned_overdue / accepted_overdue / assignee_unavailable"),
    eligible: bool | None = Query(None, description="是否具备安全执行条件"),
    current_dispatch_status: str | None = Query(None, description="当前派工阶段"),
    team_id: str | None = Query(None, description="当前责任班组 ID"),
    assignee_id: str | None = Query(None, description="当前责任人 ID"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
):
    _require_role(user, "admin", "manager")
    if (
        trigger_reason
        and trigger_reason != "all"
        and trigger_reason not in AUTO_REASSIGN_SHADOW_TRIGGER_REASONS
    ):
        raise HTTPException(status_code=400, detail="不支持的自动重派触发原因筛选")
    return await build_auto_reassign_shadow_insights(
        db,
        date_from=date_from,
        date_to=date_to,
        building_id=building_id,
        priority=priority,
        required_skill=required_skill,
        trigger_reason=trigger_reason,
        eligible=eligible,
        current_dispatch_status=current_dispatch_status,
        team_id=team_id,
        assignee_id=assignee_id,
        page=page,
        page_size=page_size,
    )


@router.get("/auto-dispatch-run-health", summary="获取自动调度运行健康洞察")
async def get_auto_dispatch_run_health_insights(
    date_from: date | None = Query(None, description="统计开始日期，闭区间"),
    date_to: date | None = Query(None, description="统计结束日期，闭区间"),
    trigger_source: str | None = Query(None, description="admin_api / scheduler"),
    slow_threshold_ms: int = Query(8000, ge=1000, le=120000),
    recent_limit: int = Query(12, ge=1, le=50),
    slow_limit: int = Query(10, ge=1, le=50),
    db: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
):
    _require_role(user, "admin", "manager")
    if (
        trigger_source
        and trigger_source != "all"
        and trigger_source not in AUTO_DISPATCH_RUN_HEALTH_SOURCES
    ):
        raise HTTPException(status_code=400, detail="不支持的运行来源筛选")
    return await build_auto_dispatch_run_health_insights(
        db,
        date_from=date_from,
        date_to=date_to,
        trigger_source=trigger_source,
        slow_threshold_ms=slow_threshold_ms,
        recent_limit=recent_limit,
        slow_limit=slow_limit,
    )


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


@router.post("/facts", summary="参数化工单运营事实查询")
async def query_work_order_facts(
    req: WorkOrderInsightFactsRequest,
    db: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
):
    _require_role(user, "admin", "manager")
    scope = req.model_dump(exclude={"question", "intent", "include_chart"}, exclude_none=True)
    return await build_work_order_facts_response(
        db,
        question=req.question or "",
        intent=req.intent,
        scope=scope,
        include_chart=req.include_chart,
    )


@router.post("/report", summary="工单运营日报/周报/月报")
async def build_work_order_report(
    req: WorkOrderInsightReportRequest,
    db: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
):
    _require_role(user, "admin", "manager")
    scope = req.model_dump(exclude={"report_type", "question", "include_chart"}, exclude_none=True)
    return await build_work_order_report_response(
        db,
        report_type=req.report_type,
        question=req.question,
        scope=scope,
        include_chart=req.include_chart,
    )
