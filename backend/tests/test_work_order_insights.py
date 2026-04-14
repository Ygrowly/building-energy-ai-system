from __future__ import annotations

from datetime import date
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from app.api import routes_work_order_insights
from app.services.work_order_insights_service import (
    build_work_order_insight_query_response,
    infer_work_order_insight_intent,
)


def _metrics_payload() -> dict:
    return {
        "generated_at": "2026-04-08T12:00:00+00:00",
        "readonly": True,
        "summary": {
            "work_orders_total": 12,
            "pending_review": 1,
            "pending_dispatch": 3,
            "auto_rejected": 0,
            "dispatched": 4,
            "pending_close": 2,
            "closed": 2,
            "by_status": {},
        },
        "dispatch": {
            "current_total": 4,
            "active_total": 4,
            "waiting_support": 1,
            "warning": 1,
            "overdue": 2,
            "overdue_rate": 0.5,
            "reassigned_attempts": 3,
            "completed_attempts": 5,
            "rejected_attempts": 1,
            "cancelled_attempts": 1,
            "by_status": {},
            "current_by_timeout": {},
        },
        "durations": {
            "sample_size": 6,
            "avg_accept_minutes": 8.5,
            "avg_arrive_minutes": 18.0,
            "avg_start_minutes": 6.0,
            "avg_complete_minutes": 64.0,
        },
        "worker_loads": {
            "active_assignees": 2,
            "over_capacity": 1,
            "top_active": [
                {
                    "user_id": "ops-1",
                    "username": "张工",
                    "team_name": "暖通班",
                    "active_orders": 4,
                    "max_active_orders": 4,
                    "capacity_ratio": 1.0,
                    "over_capacity": True,
                }
            ],
        },
        "building_hotspots": [],
        "auto_dispatch": {
            "enabled": True,
            "allow_low_confidence": False,
            "allow_hall_fallback": False,
            "rules": {
                "min_score": 105,
                "min_gap": 10,
                "require_on_duty": True,
                "fallback_min_score": 80,
                "fallback_allow_standby": True,
            },
            "rollout": {
                "allowed_buildings": ["Fox_public_Henry"],
                "allowed_priorities": ["high"],
                "allowed_required_skills": ["hvac"],
            },
            "tasks": {
                "total_auto": 2,
                "current_auto": 1,
                "by_mode": {"auto": 2},
                "current_by_mode": {"auto": 1},
            },
            "observations": {
                "rollout_skipped": 3,
                "attempt_skipped": 4,
                "hall_fallback_created": 0,
                "by_action": {},
                "recent_sample_size": 0,
                "recent_reason_counts": {},
                "recent_strategy_counts": {},
                "recent_rollout_blocker_counts": {},
                "recent": [],
            },
        },
        "watchlist": [{"level": "high", "code": "dispatch_overdue", "message": "有超时"}],
    }


def test_infer_work_order_insight_intent_matches_core_keywords() -> None:
    assert infer_work_order_insight_intent("现在有哪些超时风险") == "risk"
    assert infer_work_order_insight_intent("维修员负载怎么样") == "worker_load"
    assert infer_work_order_insight_intent("待派工还有多少") == "dispatch"
    assert infer_work_order_insight_intent("自动派工灰度命中怎么样") == "auto_dispatch"
    assert infer_work_order_insight_intent("今天闭环情况") == "closure"
    assert infer_work_order_insight_intent("总体情况") == "summary"


def test_build_work_order_insight_query_response_is_readonly() -> None:
    payload = build_work_order_insight_query_response(
        question="维修员负载怎么样",
        metrics=_metrics_payload(),
    )

    assert payload["readonly"] is True
    assert payload["intent"] == "worker_load"
    assert "张工" in payload["answer"]
    assert payload["metrics"]["summary"]["work_orders_total"] == 12


def test_build_work_order_insight_query_response_summarizes_auto_dispatch() -> None:
    payload = build_work_order_insight_query_response(
        question="自动派工灰度命中怎么样",
        metrics=_metrics_payload(),
    )

    assert payload["intent"] == "auto_dispatch"
    assert "高置信阈值为 105 分" in payload["answer"]
    assert "灰度拦截 3 次" in payload["answer"]


@pytest.mark.asyncio
async def test_work_order_insight_metrics_endpoint_rejects_ops() -> None:
    with pytest.raises(HTTPException) as exc_info:
        await routes_work_order_insights.get_work_order_insight_metrics(
            db=SimpleNamespace(),
            user=SimpleNamespace(id="ops-1", role="ops"),
        )

    assert exc_info.value.status_code == 403


@pytest.mark.asyncio
async def test_auto_dispatch_operation_insights_endpoint_passes_filters(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mock_build = AsyncMock(return_value={"readonly": True, "summary": {"total_events": 0}})
    monkeypatch.setattr(
        routes_work_order_insights,
        "build_auto_dispatch_operation_insights",
        mock_build,
    )

    response = await routes_work_order_insights.get_auto_dispatch_operation_insights(
        date_from=date(2026, 4, 1),
        date_to=date(2026, 4, 9),
        building_id="Fox_public_Henry",
        priority="high",
        required_skill="hvac",
        dispatch_mode="hall_fallback",
        team_id="team-1",
        assignee_id="ops-1",
        page=2,
        page_size=10,
        db=SimpleNamespace(),
        user=SimpleNamespace(id="manager-1", role="manager"),
    )

    assert response["readonly"] is True
    assert mock_build.await_args.kwargs == {
        "date_from": date(2026, 4, 1),
        "date_to": date(2026, 4, 9),
        "building_id": "Fox_public_Henry",
        "priority": "high",
        "required_skill": "hvac",
        "dispatch_mode": "hall_fallback",
        "team_id": "team-1",
        "assignee_id": "ops-1",
        "page": 2,
        "page_size": 10,
    }


@pytest.mark.asyncio
async def test_auto_dispatch_operation_insights_endpoint_rejects_bad_mode() -> None:
    with pytest.raises(HTTPException) as exc_info:
        await routes_work_order_insights.get_auto_dispatch_operation_insights(
            dispatch_mode="manual",
            db=SimpleNamespace(),
            user=SimpleNamespace(id="manager-1", role="manager"),
        )

    assert exc_info.value.status_code == 400


@pytest.mark.asyncio
async def test_auto_dispatch_operation_explain_endpoint_uses_service(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mock_explain = AsyncMock(return_value={"readonly": True, "source": "deterministic"})
    monkeypatch.setattr(
        routes_work_order_insights,
        "explain_auto_dispatch_operation_insights",
        mock_explain,
    )

    response = await routes_work_order_insights.explain_auto_dispatch_operations(
        req=routes_work_order_insights.AutoDispatchOperationExplainRequest(
            question="今天自动派工稳不稳",
            use_llm=False,
            date_from=date(2026, 4, 9),
            date_to=date(2026, 4, 9),
            dispatch_mode="auto",
        ),
        db=SimpleNamespace(),
        user=SimpleNamespace(id="manager-1", role="manager"),
    )

    assert response["source"] == "deterministic"
    assert mock_explain.await_args.kwargs["question"] == "今天自动派工稳不稳"
    assert mock_explain.await_args.kwargs["use_llm"] is False
    assert mock_explain.await_args.kwargs["dispatch_mode"] == "auto"


@pytest.mark.asyncio
async def test_auto_dispatch_operation_explain_endpoint_rejects_bad_mode() -> None:
    with pytest.raises(HTTPException) as exc_info:
        await routes_work_order_insights.explain_auto_dispatch_operations(
            req=routes_work_order_insights.AutoDispatchOperationExplainRequest(
                dispatch_mode="manual",
            ),
            db=SimpleNamespace(),
            user=SimpleNamespace(id="manager-1", role="manager"),
        )

    assert exc_info.value.status_code == 400


@pytest.mark.asyncio
async def test_auto_reassign_shadow_insights_endpoint_passes_filters(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mock_build = AsyncMock(return_value={"readonly": True, "summary": {"total_evaluations": 0}})
    monkeypatch.setattr(
        routes_work_order_insights,
        "build_auto_reassign_shadow_insights",
        mock_build,
    )

    response = await routes_work_order_insights.get_auto_reassign_shadow_insights(
        date_from=date(2026, 4, 1),
        date_to=date(2026, 4, 9),
        building_id="Fox_public_Henry",
        priority="high",
        required_skill="hvac",
        trigger_reason="assigned_overdue",
        eligible=True,
        current_dispatch_status="assigned",
        team_id="team-1",
        assignee_id="ops-1",
        page=2,
        page_size=10,
        db=SimpleNamespace(),
        user=SimpleNamespace(id="manager-1", role="manager"),
    )

    assert response["readonly"] is True
    assert mock_build.await_args.kwargs == {
        "date_from": date(2026, 4, 1),
        "date_to": date(2026, 4, 9),
        "building_id": "Fox_public_Henry",
        "priority": "high",
        "required_skill": "hvac",
        "trigger_reason": "assigned_overdue",
        "eligible": True,
        "current_dispatch_status": "assigned",
        "team_id": "team-1",
        "assignee_id": "ops-1",
        "page": 2,
        "page_size": 10,
    }


@pytest.mark.asyncio
async def test_auto_reassign_shadow_insights_endpoint_rejects_bad_trigger() -> None:
    with pytest.raises(HTTPException) as exc_info:
        await routes_work_order_insights.get_auto_reassign_shadow_insights(
            trigger_reason="manual",
            db=SimpleNamespace(),
            user=SimpleNamespace(id="manager-1", role="manager"),
        )

    assert exc_info.value.status_code == 400


@pytest.mark.asyncio
async def test_auto_dispatch_run_health_insights_endpoint_passes_filters(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mock_build = AsyncMock(return_value={"readonly": True, "summary": {"total_runs": 0}})
    monkeypatch.setattr(
        routes_work_order_insights,
        "build_auto_dispatch_run_health_insights",
        mock_build,
    )

    response = await routes_work_order_insights.get_auto_dispatch_run_health_insights(
        date_from=date(2026, 4, 1),
        date_to=date(2026, 4, 9),
        trigger_source="scheduler",
        slow_threshold_ms=12000,
        recent_limit=15,
        slow_limit=8,
        db=SimpleNamespace(),
        user=SimpleNamespace(id="manager-1", role="manager"),
    )

    assert response["readonly"] is True
    assert mock_build.await_args.kwargs == {
        "date_from": date(2026, 4, 1),
        "date_to": date(2026, 4, 9),
        "trigger_source": "scheduler",
        "slow_threshold_ms": 12000,
        "recent_limit": 15,
        "slow_limit": 8,
    }


@pytest.mark.asyncio
async def test_auto_dispatch_run_health_insights_endpoint_rejects_bad_source() -> None:
    with pytest.raises(HTTPException) as exc_info:
        await routes_work_order_insights.get_auto_dispatch_run_health_insights(
            trigger_source="worker",
            db=SimpleNamespace(),
            user=SimpleNamespace(id="manager-1", role="manager"),
        )

    assert exc_info.value.status_code == 400


@pytest.mark.asyncio
async def test_work_order_insight_query_endpoint_returns_deterministic_answer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        routes_work_order_insights,
        "build_work_order_insight_metrics",
        AsyncMock(return_value=_metrics_payload()),
    )

    response = await routes_work_order_insights.query_work_order_insights(
        req=routes_work_order_insights.WorkOrderInsightQueryRequest(question="超时风险怎么样"),
        db=SimpleNamespace(),
        user=SimpleNamespace(id="manager-1", role="manager"),
    )

    assert response["readonly"] is True
    assert response["intent"] == "risk"
    assert "超时派工 2 个" in response["answer"]


@pytest.mark.asyncio
async def test_work_order_facts_endpoint_uses_phase4_service(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mock_build = AsyncMock(return_value={"readonly": True, "intent": "worker_performance"})
    monkeypatch.setattr(routes_work_order_insights, "build_work_order_facts_response", mock_build)

    response = await routes_work_order_insights.query_work_order_facts(
        req=routes_work_order_insights.WorkOrderInsightFactsRequest(
            question="这个月谁处理得最多",
            building_id="Public",
            include_chart=True,
        ),
        db=SimpleNamespace(),
        user=SimpleNamespace(id="manager-1", role="manager"),
    )

    assert response["intent"] == "worker_performance"
    assert mock_build.await_args.kwargs["scope"]["building_id"] == "Public"
    assert mock_build.await_args.kwargs["include_chart"] is True


@pytest.mark.asyncio
async def test_work_order_report_endpoint_uses_phase4_service(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mock_build = AsyncMock(return_value={"readonly": True, "report_type": "monthly_report"})
    monkeypatch.setattr(routes_work_order_insights, "build_work_order_report_response", mock_build)

    response = await routes_work_order_insights.build_work_order_report(
        req=routes_work_order_insights.WorkOrderInsightReportRequest(
            report_type="monthly",
            question="生成本月工单运营总结",
            building_id="Public",
            include_chart=False,
        ),
        db=SimpleNamespace(),
        user=SimpleNamespace(id="manager-1", role="manager"),
    )

    assert response["report_type"] == "monthly_report"
    assert mock_build.await_args.kwargs["scope"]["building_id"] == "Public"
    assert mock_build.await_args.kwargs["include_chart"] is False
