from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException

from app.api import routes_workorder
from app.services import auto_dispatch_service
from app.services.auto_dispatch_service import (
    build_auto_dispatch_evaluation,
    build_auto_dispatch_rollout_gate,
)


def _work_order(**overrides):
    data = {
        "id": "wo-1",
        "ticket_id": "WO-001",
        "status": "pending_dispatch",
        "approval_status": "approved",
        "dispatch_summary_status": "pending_dispatch",
        "current_dispatch_id": None,
    }
    data.update(overrides)
    return SimpleNamespace(**data)


def _candidate(**overrides):
    data = {
        "user_id": "ops-1",
        "username": "张工",
        "phone": "13800000001",
        "team_id": "team-1",
        "team_name": "暖通班",
        "shift_status": "on_duty",
        "dispatch_enabled": True,
        "score": 132,
        "current_active_orders": 1,
        "max_active_orders": 4,
        "load_ratio": 0.25,
        "matched_skill_names": ["暖通"],
        "badges": ["暖通班", "值班中"],
        "recommend_reason": "技能贴合：暖通",
    }
    data.update(overrides)
    return data


def _dispatch_task(**overrides):
    now = datetime.now(timezone.utc)
    data = {
        "id": "dispatch-1",
        "assigned_to": "ops-1",
        "attempt_no": 1,
        "dispatch_status": "assigned",
        "accept_deadline_at": now - timedelta(minutes=5),
        "arrive_deadline_at": now + timedelta(minutes=25),
        "finish_deadline_at": now + timedelta(minutes=90),
    }
    data.update(overrides)
    return SimpleNamespace(**data)


@pytest.mark.asyncio
async def test_auto_dispatch_evaluation_returns_ready_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        auto_dispatch_service,
        "list_dispatch_candidates",
        AsyncMock(
            return_value={
                "requirement": {"required_skills": ["hvac"], "preferred_team_name": "暖通班"},
                "candidates": [_candidate(score=132), _candidate(user_id="ops-2", username="李工", score=101)],
            }
        ),
    )

    payload = await build_auto_dispatch_evaluation(
        SimpleNamespace(),
        work_order=_work_order(),
        min_score=110,
        min_gap=10,
    )

    assert payload["readonly"] is True
    assert payload["eligible"] is True
    assert payload["decision"] == "ready"
    assert payload["strategy"] == "high_confidence_dispatch"
    assert payload["confidence"] == "high"
    assert payload["apply_payload"] == {
        "ticket_id": "WO-001",
        "assigned_to": "ops-1",
        "dispatch_mode": "auto",
        "selection_reason": payload["selection_reason"],
    }


@pytest.mark.asyncio
async def test_auto_dispatch_evaluation_uses_low_confidence_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        auto_dispatch_service,
        "list_dispatch_candidates",
        AsyncMock(
            return_value={
                "requirement": {"required_skills": ["hvac"], "preferred_team_name": "暖通班"},
                "candidates": [_candidate(score=108), _candidate(user_id="ops-2", username="李工", score=105)],
            }
        ),
    )

    payload = await build_auto_dispatch_evaluation(
        SimpleNamespace(),
        work_order=_work_order(),
        min_score=110,
        min_gap=10,
    )

    assert payload["eligible"] is True
    assert payload["strategy"] == "low_confidence_fallback_dispatch"
    assert payload["confidence"] == "low"
    assert payload["apply_payload"]["dispatch_mode"] == "auto_fallback"
    assert {item["reason"] for item in payload["high_confidence_blockers"]} == {
        "top_score_below_threshold",
        "score_gap_below_threshold",
    }


@pytest.mark.asyncio
async def test_auto_dispatch_evaluation_blocks_existing_dispatch(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        auto_dispatch_service,
        "list_dispatch_candidates",
        AsyncMock(
            return_value={
                "requirement": {"required_skills": [], "preferred_team_name": "综合运维班"},
                "candidates": [_candidate(score=132)],
            }
        ),
    )

    payload = await build_auto_dispatch_evaluation(
        SimpleNamespace(),
        work_order=_work_order(status="dispatched", current_dispatch_id="dispatch-1"),
    )

    assert payload["eligible"] is False
    assert "current_dispatch_exists" in {item["reason"] for item in payload["blockers"]}
    assert "status_invalid" in {item["reason"] for item in payload["blockers"]}


@pytest.mark.asyncio
async def test_auto_dispatch_evaluation_uses_hall_fallback_when_no_person_available(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        auto_dispatch_service,
        "list_dispatch_candidates",
        AsyncMock(
            return_value={
                "requirement": {"required_skills": ["hvac"], "preferred_team_name": "暖通班"},
                "candidates": [_candidate(score=40, current_active_orders=4, max_active_orders=4)],
            }
        ),
    )

    payload = await build_auto_dispatch_evaluation(
        SimpleNamespace(),
        work_order=_work_order(),
        min_score=110,
        min_gap=10,
        fallback_min_score=80,
    )

    assert payload["eligible"] is False
    assert payload["strategy"] == "hall_fallback"
    assert payload["hall_fallback"]["entry_type"] == "takeover_candidate"
    assert payload["apply_payload"] is None


def test_auto_dispatch_rollout_gate_allows_matching_work_order() -> None:
    gate = build_auto_dispatch_rollout_gate(
        _work_order(building_id="Fox_public_Henry", priority="high", dispatch_profile_json='{"required_skills":["hvac"]}'),
        allowed_buildings=["Fox_public_Henry"],
        allowed_priorities=["high"],
        allowed_required_skills=["hvac", "electrical"],
    )

    assert gate["allowed"] is True
    assert gate["blockers"] == []


def test_auto_dispatch_rollout_gate_blocks_non_matching_dimensions() -> None:
    gate = build_auto_dispatch_rollout_gate(
        _work_order(building_id="Fox_office_Alice", priority="medium", dispatch_profile_json='{"required_skills":["plumbing"]}'),
        allowed_buildings=["Fox_public_Henry"],
        allowed_priorities=["high"],
        allowed_required_skills=["hvac"],
    )

    assert gate["allowed"] is False
    assert {item["reason"] for item in gate["blockers"]} == {
        "rollout_building_not_allowed",
        "rollout_priority_not_allowed",
        "rollout_skill_not_allowed",
    }


@pytest.mark.asyncio
async def test_execute_auto_dispatch_stays_readonly_when_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    mock_assign = AsyncMock()
    monkeypatch.setattr(auto_dispatch_service, "assign_work_order", mock_assign)
    monkeypatch.setattr(
        auto_dispatch_service,
        "list_dispatch_candidates",
        AsyncMock(
            return_value={
                "requirement": {"required_skills": ["hvac"], "preferred_team_name": "暖通班"},
                "candidates": [_candidate(score=132), _candidate(user_id="ops-2", username="李工", score=101)],
            }
        ),
    )

    payload = await auto_dispatch_service.execute_auto_dispatch(
        SimpleNamespace(),
        work_order=_work_order(),
        actor_id="admin-1",
        enabled=False,
    )

    assert payload["executed"] is False
    assert payload["reason"] == "auto_dispatch_execution_disabled"
    mock_assign.assert_not_awaited()


@pytest.mark.asyncio
async def test_execute_auto_dispatch_assigns_when_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    work_order = _work_order()
    assigned_user = SimpleNamespace(id="ops-1", username="张工", role="ops", is_active=True)

    async def _fake_assign(*args, **kwargs):
        kwargs["work_order"].current_dispatch_id = "dispatch-1"
        kwargs["work_order"].status = "dispatched"
        return kwargs["work_order"]

    monkeypatch.setattr(
        auto_dispatch_service,
        "list_dispatch_candidates",
        AsyncMock(
            return_value={
                "requirement": {"required_skills": ["hvac"], "preferred_team_name": "暖通班"},
                "candidates": [_candidate(score=132), _candidate(user_id="ops-2", username="李工", score=101)],
            }
        ),
    )
    monkeypatch.setattr(auto_dispatch_service, "_load_auto_dispatch_assignee", AsyncMock(return_value=assigned_user))
    mock_assign = AsyncMock(side_effect=_fake_assign)
    monkeypatch.setattr(auto_dispatch_service, "assign_work_order", mock_assign)

    payload = await auto_dispatch_service.execute_auto_dispatch(
        SimpleNamespace(),
        work_order=work_order,
        actor_id="admin-1",
        enabled=True,
    )

    assert payload["executed"] is True
    assert payload["dispatch_id"] == "dispatch-1"
    assert mock_assign.await_args.kwargs["dispatch_mode"] == "auto"
    assert mock_assign.await_args.kwargs["actor_type"] == "system"
    assert mock_assign.await_args.kwargs["candidate_snapshot"]["auto_dispatch"] is True


@pytest.mark.asyncio
async def test_execute_auto_dispatch_assigns_low_confidence_when_fallback_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    work_order = _work_order()
    assigned_user = SimpleNamespace(id="ops-1", username="张工", role="ops", is_active=True)

    async def _fake_assign(*args, **kwargs):
        kwargs["work_order"].current_dispatch_id = "dispatch-1"
        kwargs["work_order"].status = "dispatched"
        return kwargs["work_order"]

    monkeypatch.setattr(
        auto_dispatch_service,
        "list_dispatch_candidates",
        AsyncMock(
            return_value={
                "requirement": {"required_skills": ["hvac"], "preferred_team_name": "暖通班"},
                "candidates": [_candidate(score=108), _candidate(user_id="ops-2", username="李工", score=105)],
            }
        ),
    )
    monkeypatch.setattr(auto_dispatch_service, "_load_auto_dispatch_assignee", AsyncMock(return_value=assigned_user))
    mock_assign = AsyncMock(side_effect=_fake_assign)
    monkeypatch.setattr(auto_dispatch_service, "assign_work_order", mock_assign)

    payload = await auto_dispatch_service.execute_auto_dispatch(
        SimpleNamespace(),
        work_order=work_order,
        actor_id="admin-1",
        enabled=True,
        allow_low_confidence_fallback=True,
    )

    assert payload["executed"] is True
    assert payload["evaluation"]["strategy"] == "low_confidence_fallback_dispatch"
    assert mock_assign.await_args.kwargs["dispatch_mode"] == "auto_fallback"


@pytest.mark.asyncio
async def test_execute_auto_dispatch_creates_hall_fallback_when_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    hall_entry = SimpleNamespace(id="hall-1")
    monkeypatch.setattr(
        auto_dispatch_service,
        "list_dispatch_candidates",
        AsyncMock(
            return_value={
                "requirement": {"required_skills": ["hvac"], "preferred_team_name": "暖通班"},
                "candidates": [_candidate(score=40, current_active_orders=4, max_active_orders=4)],
            }
        ),
    )
    mock_hall = AsyncMock(return_value=hall_entry)
    monkeypatch.setattr(auto_dispatch_service, "create_or_reopen_takeover_hall_entry", mock_hall)
    monkeypatch.setattr(auto_dispatch_service, "write_work_order_audit_log", AsyncMock())

    payload = await auto_dispatch_service.execute_auto_dispatch(
        SimpleNamespace(),
        work_order=_work_order(),
        actor_id="admin-1",
        enabled=True,
        create_hall_fallback=True,
    )

    assert payload["action_taken"] is True
    assert payload["executed"] is False
    assert payload["hall_entry_id"] == "hall-1"
    mock_hall.assert_awaited_once()


@pytest.mark.asyncio
async def test_auto_reassign_evaluation_excludes_current_assignee(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        auto_dispatch_service,
        "list_dispatch_candidates",
        AsyncMock(
            return_value={
                "requirement": {"required_skills": ["hvac"], "preferred_team_name": "暖通班"},
                "candidates": [
                    _candidate(user_id="ops-1", username="当前责任人", score=150),
                    _candidate(user_id="ops-2", username="李工", score=132),
                    _candidate(user_id="ops-3", username="王工", score=101),
                ],
            }
        ),
    )

    payload = await auto_dispatch_service.build_auto_reassign_evaluation(
        SimpleNamespace(),
        work_order=_work_order(status="dispatched"),
        current_dispatch=_dispatch_task(assigned_to="ops-1"),
        min_score=110,
        min_gap=10,
    )

    assert payload["eligible"] is True
    assert payload["top_candidate"]["user_id"] == "ops-2"
    assert payload["apply_payload"]["from_dispatch_id"] == "dispatch-1"
    assert payload["apply_payload"]["dispatch_mode"] == "reassigned"


@pytest.mark.asyncio
async def test_auto_reassign_evaluation_blocks_non_overdue_dispatch(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        auto_dispatch_service,
        "list_dispatch_candidates",
        AsyncMock(
            return_value={
                "requirement": {"required_skills": ["hvac"], "preferred_team_name": "暖通班"},
                "candidates": [_candidate(user_id="ops-2", username="李工", score=132)],
            }
        ),
    )

    payload = await auto_dispatch_service.build_auto_reassign_evaluation(
        SimpleNamespace(),
        work_order=_work_order(status="dispatched"),
        current_dispatch=_dispatch_task(accept_deadline_at=datetime.now(timezone.utc) + timedelta(minutes=5)),
    )

    assert payload["eligible"] is False
    assert "dispatch_not_overdue" in {item["reason"] for item in payload["blockers"]}


@pytest.mark.asyncio
async def test_auto_dispatch_evaluation_endpoint_returns_service_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    work_order = _work_order()
    mock_eval = AsyncMock(return_value={"readonly": True, "eligible": True})
    monkeypatch.setattr(routes_workorder, "get_work_order_by_ticket_id", AsyncMock(return_value=work_order))
    monkeypatch.setattr(routes_workorder, "build_auto_dispatch_evaluation", mock_eval)

    payload = await routes_workorder.get_auto_dispatch_evaluation(
        ticket_id="WO-001",
        min_score=120,
        min_gap=15,
        require_on_duty=True,
        fallback_min_score=80,
        fallback_allow_standby=True,
        db=SimpleNamespace(),
        user=SimpleNamespace(id="admin-1", role="admin"),
    )

    assert payload == {"readonly": True, "eligible": True}
    assert mock_eval.await_args.kwargs["work_order"] is work_order
    assert mock_eval.await_args.kwargs["min_score"] == 120
    assert mock_eval.await_args.kwargs["min_gap"] == 15
    assert mock_eval.await_args.kwargs["fallback_min_score"] == 80


@pytest.mark.asyncio
async def test_execute_auto_dispatch_endpoint_commits_when_executed(monkeypatch: pytest.MonkeyPatch) -> None:
    work_order = _work_order()
    db = SimpleNamespace(commit=AsyncMock(), rollback=AsyncMock())
    mock_execute = AsyncMock(return_value={"executed": True, "action_taken": True, "dispatch_id": "dispatch-1"})
    monkeypatch.setattr(routes_workorder, "get_work_order_by_ticket_id", AsyncMock(return_value=work_order))
    monkeypatch.setattr(routes_workorder, "execute_auto_dispatch", mock_execute)
    monkeypatch.setattr(routes_workorder, "_invalidate_related_cache", AsyncMock())

    payload = await routes_workorder.execute_auto_dispatch_endpoint(
        ticket_id="WO-001",
        db=db,
        user=SimpleNamespace(id="admin-1", role="admin"),
    )

    assert payload["executed"] is True
    db.commit.assert_awaited_once()
    db.rollback.assert_not_awaited()
    assert mock_execute.await_args.kwargs["actor_id"] == "admin-1"


@pytest.mark.asyncio
async def test_auto_reassign_evaluation_endpoint_returns_service_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    work_order = _work_order(status="dispatched")
    dispatch_task = _dispatch_task()
    mock_eval = AsyncMock(return_value={"readonly": True, "eligible": False})
    monkeypatch.setattr(routes_workorder, "get_work_order_by_ticket_id", AsyncMock(return_value=work_order))
    monkeypatch.setattr(routes_workorder, "get_current_dispatch_task", AsyncMock(return_value=dispatch_task))
    monkeypatch.setattr(routes_workorder, "build_auto_reassign_evaluation", mock_eval)

    payload = await routes_workorder.get_auto_reassign_evaluation(
        ticket_id="WO-001",
        min_score=120,
        min_gap=15,
        require_on_duty=True,
        require_overdue=True,
        max_attempt_no=3,
        db=SimpleNamespace(),
        user=SimpleNamespace(id="admin-1", role="admin"),
    )

    assert payload == {"readonly": True, "eligible": False}
    assert mock_eval.await_args.kwargs["work_order"] is work_order
    assert mock_eval.await_args.kwargs["current_dispatch"] is dispatch_task


@pytest.mark.asyncio
async def test_execute_auto_reassign_stays_readonly_when_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    dispatch_task = _dispatch_task(id="dispatch-1", dispatch_status="assigned")
    monkeypatch.setattr(
        auto_dispatch_service,
        "list_dispatch_candidates",
        AsyncMock(
            return_value={
                "requirement": {"required_skills": ["hvac"], "preferred_team_name": "暖通班"},
                "candidates": [_candidate(user_id="ops-2", username="李工", score=132)],
            }
        ),
    )
    mock_reassign = AsyncMock()
    monkeypatch.setattr(auto_dispatch_service, "reassign_dispatch_task", mock_reassign)

    payload = await auto_dispatch_service.execute_auto_reassign(
        SimpleNamespace(),
        work_order=_work_order(status="dispatched"),
        current_dispatch=dispatch_task,
        enabled=False,
        require_overdue=False,
    )

    assert payload["executed"] is False
    assert payload["action_taken"] is False
    assert payload["reason"] == "auto_reassign_execution_disabled"
    mock_reassign.assert_not_awaited()


@pytest.mark.asyncio
async def test_execute_auto_reassign_reassigns_when_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    work_order = _work_order(status="dispatched", current_dispatch_id="dispatch-1")
    current_dispatch = _dispatch_task(id="dispatch-1", assigned_to="ops-1", dispatch_status="assigned")
    assigned_user = SimpleNamespace(id="ops-2", username="李工", role="ops", is_active=True)
    new_dispatch = SimpleNamespace(id="dispatch-2")
    monkeypatch.setattr(
        auto_dispatch_service,
        "list_dispatch_candidates",
        AsyncMock(
            return_value={
                "requirement": {"required_skills": ["hvac"], "preferred_team_name": "暖通班"},
                "candidates": [
                    _candidate(user_id="ops-1", username="张工", score=140),
                    _candidate(user_id="ops-2", username="李工", score=132),
                    _candidate(user_id="ops-3", username="王工", score=110),
                ],
            }
        ),
    )
    monkeypatch.setattr(auto_dispatch_service, "_load_auto_dispatch_assignee", AsyncMock(return_value=assigned_user))
    mock_reassign = AsyncMock(return_value=new_dispatch)
    mock_audit = AsyncMock()
    monkeypatch.setattr(auto_dispatch_service, "reassign_dispatch_task", mock_reassign)
    monkeypatch.setattr(auto_dispatch_service, "write_work_order_audit_log", mock_audit)

    payload = await auto_dispatch_service.execute_auto_reassign(
        SimpleNamespace(),
        work_order=work_order,
        current_dispatch=current_dispatch,
        actor_id="admin-1",
        enabled=True,
        min_score=115,
        min_gap=10,
        require_overdue=False,
    )

    assert payload["executed"] is True
    assert payload["reason"] == "auto_reassign_executed"
    assert payload["dispatch_id"] == "dispatch-2"
    assert payload["assigned_to"] == "ops-2"
    assert mock_reassign.await_args.kwargs["actor_type"] == "system"
    assert mock_reassign.await_args.kwargs["dispatch_mode"] == "reassigned"
    assert mock_reassign.await_args.kwargs["candidate_snapshot"]["auto_reassign"] is True
    assert mock_reassign.await_args.kwargs["candidate_snapshot"]["from_dispatch_id"] == "dispatch-1"
    assert mock_audit.await_args.kwargs["action"] == "auto_reassign_executed"


@pytest.mark.asyncio
async def test_execute_auto_reassign_endpoint_commits_when_action_taken(monkeypatch: pytest.MonkeyPatch) -> None:
    work_order = _work_order(status="dispatched")
    dispatch_task = _dispatch_task()
    db = SimpleNamespace(commit=AsyncMock(), rollback=AsyncMock())
    mock_execute = AsyncMock(return_value={"executed": True, "action_taken": True, "dispatch_id": "dispatch-2"})
    monkeypatch.setattr(routes_workorder, "get_work_order_by_ticket_id", AsyncMock(return_value=work_order))
    monkeypatch.setattr(routes_workorder, "get_current_dispatch_task", AsyncMock(return_value=dispatch_task))
    monkeypatch.setattr(routes_workorder, "execute_auto_reassign", mock_execute)
    monkeypatch.setattr(routes_workorder, "_invalidate_related_cache", AsyncMock())

    payload = await routes_workorder.execute_auto_reassign_endpoint(
        ticket_id="WO-001",
        db=db,
        user=SimpleNamespace(id="admin-1", role="manager"),
    )

    assert payload["executed"] is True
    db.commit.assert_awaited_once()
    db.rollback.assert_not_awaited()
    assert mock_execute.await_args.kwargs["actor_id"] == "admin-1"


@pytest.mark.asyncio
async def test_execute_auto_reassign_endpoint_rolls_back_when_no_action(monkeypatch: pytest.MonkeyPatch) -> None:
    work_order = _work_order(status="dispatched")
    dispatch_task = _dispatch_task()
    db = SimpleNamespace(commit=AsyncMock(), rollback=AsyncMock())
    mock_execute = AsyncMock(
        return_value={
            "executed": False,
            "action_taken": False,
            "reason": "auto_reassign_execution_disabled",
        }
    )
    monkeypatch.setattr(routes_workorder, "get_work_order_by_ticket_id", AsyncMock(return_value=work_order))
    monkeypatch.setattr(routes_workorder, "get_current_dispatch_task", AsyncMock(return_value=dispatch_task))
    monkeypatch.setattr(routes_workorder, "execute_auto_reassign", mock_execute)
    monkeypatch.setattr(routes_workorder, "_invalidate_related_cache", AsyncMock())

    payload = await routes_workorder.execute_auto_reassign_endpoint(
        ticket_id="WO-001",
        db=db,
        user=SimpleNamespace(id="admin-1", role="manager"),
    )

    assert payload["action_taken"] is False
    db.rollback.assert_awaited_once()
    db.commit.assert_not_awaited()
    routes_workorder._invalidate_related_cache.assert_not_awaited()


@pytest.mark.asyncio
async def test_mark_auto_dispatch_review_writes_audit(monkeypatch: pytest.MonkeyPatch) -> None:
    work_order = _work_order(status="dispatched", current_dispatch_id="dispatch-1")
    dispatch_task = _dispatch_task(
        id="dispatch-1",
        dispatch_mode="auto",
        candidate_snapshot_json='{"auto_dispatch": true}',
    )
    now = datetime.now(timezone.utc)
    log_entry = SimpleNamespace(
        action="auto_dispatch_reviewed",
        actor_id="admin-1",
        detail_json='{"dispatch_id": "dispatch-1", "notes": null}',
        created_at=now,
    )
    db = SimpleNamespace(flush=AsyncMock(), commit=AsyncMock())
    mock_audit = AsyncMock(return_value=log_entry)
    monkeypatch.setattr(routes_workorder, "get_work_order_by_ticket_id", AsyncMock(return_value=work_order))
    monkeypatch.setattr(routes_workorder, "get_current_dispatch_task", AsyncMock(return_value=dispatch_task))
    monkeypatch.setattr(routes_workorder, "write_work_order_audit_log", mock_audit)
    monkeypatch.setattr(routes_workorder, "_invalidate_related_cache", AsyncMock())
    monkeypatch.setattr(routes_workorder, "_load_users_by_ids", AsyncMock(return_value={}))
    monkeypatch.setattr(
        routes_workorder,
        "serialize_work_order",
        lambda *args, **kwargs: {"ticket_id": "WO-001", "current_dispatch": {"auto_dispatch_review": {}}},
    )

    payload = await routes_workorder.mark_auto_dispatch_review(
        ticket_id="WO-001",
        req=routes_workorder.AutoDispatchReviewRequest(action="reviewed"),
        db=db,
        user=SimpleNamespace(id="admin-1", role="admin"),
    )

    assert payload["review_state"]["status"] == "reviewed"
    assert payload["work_order"]["current_dispatch"]["auto_dispatch_review_state"]["status"] == "reviewed"
    assert work_order.admin_action == "auto_dispatch_reviewed"
    assert mock_audit.await_args.kwargs["action"] == "auto_dispatch_reviewed"
    assert mock_audit.await_args.kwargs["detail"]["dispatch_id"] == "dispatch-1"
    db.flush.assert_awaited_once()
    db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_mark_auto_dispatch_review_rejects_manual_dispatch(monkeypatch: pytest.MonkeyPatch) -> None:
    work_order = _work_order(status="dispatched", current_dispatch_id="dispatch-1")
    dispatch_task = _dispatch_task(
        id="dispatch-1",
        dispatch_mode="manual",
        candidate_snapshot_json="{}",
    )
    db = SimpleNamespace(flush=AsyncMock(), commit=AsyncMock())
    monkeypatch.setattr(routes_workorder, "get_work_order_by_ticket_id", AsyncMock(return_value=work_order))
    monkeypatch.setattr(routes_workorder, "get_current_dispatch_task", AsyncMock(return_value=dispatch_task))

    with pytest.raises(HTTPException) as exc_info:
        await routes_workorder.mark_auto_dispatch_review(
            ticket_id="WO-001",
            req=routes_workorder.AutoDispatchReviewRequest(action="reviewed"),
            db=db,
            user=SimpleNamespace(id="admin-1", role="manager"),
        )

    assert exc_info.value.status_code == 409
    db.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_auto_dispatch_evaluation_endpoint_rejects_ops() -> None:
    with pytest.raises(HTTPException) as exc_info:
        await routes_workorder.get_auto_dispatch_evaluation(
            ticket_id="WO-001",
            min_score=110,
            min_gap=10,
        require_on_duty=True,
        fallback_min_score=80,
        fallback_allow_standby=True,
        db=SimpleNamespace(),
        user=SimpleNamespace(id="ops-1", role="ops"),
        )

    assert exc_info.value.status_code == 403
