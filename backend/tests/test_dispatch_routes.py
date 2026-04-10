from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

from app.api import routes_admin, routes_dispatch, routes_workorder


def _make_team(name: str = "暖通班", team_id: str = "team-1"):
    return SimpleNamespace(id=team_id, name=name)


def _make_user(user_id: str, username: str, role: str = "ops"):
    return SimpleNamespace(
        id=user_id,
        username=username,
        phone=f"1380000{user_id[-4:]}",
        role=role,
        is_active=True,
        worker_profile=SimpleNamespace(team=_make_team()),
    )


def _make_dispatch_task(
    *,
    dispatch_id: str = "dispatch-1",
    assigned_to: str = "ops-1",
    attempt_no: int = 1,
    dispatch_status: str = "assigned",
):
    now = datetime.now(timezone.utc)
    return SimpleNamespace(
        id=dispatch_id,
        work_order_id="wo-1",
        incident_id="incident-1",
        attempt_no=attempt_no,
        is_current=attempt_no == 1,
        dispatch_mode="manual",
        dispatch_status=dispatch_status,
        assigned_team_id="team-1",
        assigned_to=assigned_to,
        assigned_by="admin-1",
        selection_reason="推荐分最高",
        candidate_snapshot_json=None,
        dispatch_profile_snapshot_json=None,
        worker_result=None,
        reject_reason=None,
        cancel_reason=None,
        support_reason=None,
        support_team_id=None,
        transfer_from_dispatch_id=None,
        assigned_at=now - timedelta(minutes=20 - attempt_no),
        accept_deadline_at=now + timedelta(minutes=10),
        accepted_at=None,
        arrive_deadline_at=now + timedelta(minutes=30),
        arrived_at=None,
        start_deadline_at=now + timedelta(minutes=45),
        processing_started_at=None,
        finish_deadline_at=now + timedelta(minutes=90),
        completed_at=None,
        closed_at=None,
        reminder_count=0,
        last_reminded_at=None,
        timeout_level="normal",
        latest_note="等待接单",
        created_at=now - timedelta(minutes=21 - attempt_no),
        updated_at=now - timedelta(minutes=20 - attempt_no),
    )


def _make_dispatch_event(
    *,
    event_id: str,
    dispatch_task_id: str,
    event_type: str,
    created_at: datetime,
    payload: dict | None = None,
):
    return SimpleNamespace(
        id=event_id,
        dispatch_task_id=dispatch_task_id,
        work_order_id="wo-1",
        incident_id="incident-1",
        event_type=event_type,
        actor_type="worker",
        actor_id="ops-1",
        payload_json=None if payload is None else __import__("json").dumps(payload, ensure_ascii=False),
        created_at=created_at,
    )


def _make_audit_log(action: str, created_at: datetime):
    return SimpleNamespace(
        id=f"audit-{action}",
        action=action,
        old_status="pending_dispatch",
        new_status="dispatched",
        actor_type="admin",
        actor_id="admin-1",
        detail_json=None,
        created_at=created_at,
    )


def _make_work_order(
    *,
    work_order_id: str = "wo-1",
    ticket_id: str = "WO-001",
    status: str = "dispatched",
):
    return SimpleNamespace(
        id=work_order_id,
        ticket_id=ticket_id,
        work_order_id=work_order_id,
        status=status,
        worker_result=None,
        worker_notes=None,
        worker_feedback_at=None,
        dispatch_blocked_reason=None,
    )


class _ScalarResult:
    def __init__(self, items):
        self._items = items

    def scalars(self):
        return SimpleNamespace(all=lambda: self._items)


@pytest.mark.asyncio
async def test_list_dispatch_tasks_endpoint_scopes_ops_user_to_self(monkeypatch: pytest.MonkeyPatch) -> None:
    dispatch_task = _make_dispatch_task()
    assigned_user = _make_user("ops-1", "张工")
    mock_list_dispatch_tasks = AsyncMock(return_value=([dispatch_task], 1))

    monkeypatch.setattr(routes_dispatch, "list_dispatch_tasks", mock_list_dispatch_tasks)
    monkeypatch.setattr(
        routes_dispatch,
        "_load_assigned_users_by_ids",
        AsyncMock(return_value={"ops-1": assigned_user}),
    )

    response = await routes_dispatch.list_dispatch_tasks_endpoint(
        assigned_to=None,
        work_order_id=None,
        incident_id=None,
        status=None,
        current_only=True,
        include_events=False,
        page=1,
        page_size=20,
        db=SimpleNamespace(),
        user=SimpleNamespace(id="ops-1", role="ops"),
    )

    assert mock_list_dispatch_tasks.await_args.kwargs["assigned_to"] == "ops-1"
    assert response["total"] == 1
    assert response["dispatch_tasks"][0]["assigned_to_name"] == "张工"


@pytest.mark.asyncio
async def test_list_dispatch_tasks_endpoint_rejects_cross_user_query_for_ops() -> None:
    with pytest.raises(HTTPException) as exc_info:
        await routes_dispatch.list_dispatch_tasks_endpoint(
            assigned_to="ops-2",
            work_order_id=None,
            incident_id=None,
            status=None,
            current_only=None,
            include_events=False,
            page=1,
            page_size=20,
            db=SimpleNamespace(),
            user=SimpleNamespace(id="ops-1", role="ops"),
        )

    assert exc_info.value.status_code == 403


@pytest.mark.asyncio
async def test_get_work_order_timeline_endpoint_returns_dispatch_history(monkeypatch: pytest.MonkeyPatch) -> None:
    now = datetime.now(timezone.utc)
    dispatch_one = _make_dispatch_task(dispatch_id="dispatch-1", assigned_to="ops-1", attempt_no=1)
    dispatch_two = _make_dispatch_task(dispatch_id="dispatch-2", assigned_to="ops-2", attempt_no=2, dispatch_status="accepted")
    dispatch_one_event = _make_dispatch_event(
        event_id="evt-1",
        dispatch_task_id="dispatch-1",
        event_type="assigned",
        created_at=now - timedelta(minutes=30),
        payload={"selection_reason": "第一次派工"},
    )
    dispatch_two_event = _make_dispatch_event(
        event_id="evt-2",
        dispatch_task_id="dispatch-2",
        event_type="accepted",
        created_at=now - timedelta(minutes=10),
        payload={"notes": "已确认接单"},
    )
    work_order = SimpleNamespace(id="wo-1", ticket_id="WO-001", assigned_to="ops-2")
    current_dispatch = dispatch_two
    audit_logs = [
        _make_audit_log("create", now - timedelta(minutes=40)),
        _make_audit_log("dispatch_reassign", now - timedelta(minutes=15)),
    ]

    async def _fake_cache(_key, _ttl, compute):
        return await compute()

    monkeypatch.setattr(
        routes_workorder,
        "get_work_order_by_ticket_id",
        AsyncMock(return_value=work_order),
    )
    monkeypatch.setattr(
        routes_workorder,
        "get_current_dispatch_task",
        AsyncMock(return_value=current_dispatch),
    )
    monkeypatch.setattr(
        routes_workorder,
        "list_dispatch_tasks_for_work_order",
        AsyncMock(return_value=[dispatch_one, dispatch_two]),
    )
    monkeypatch.setattr(
        routes_workorder,
        "load_dispatch_events_by_task_ids",
        AsyncMock(
            return_value={
                "dispatch-1": [dispatch_one_event],
                "dispatch-2": [dispatch_two_event],
            }
        ),
    )
    monkeypatch.setattr(
        routes_workorder,
        "_load_users_by_ids",
        AsyncMock(
            return_value={
                "ops-1": _make_user("ops-1", "张工"),
                "ops-2": _make_user("ops-2", "李工"),
            }
        ),
    )
    monkeypatch.setattr(
        routes_workorder,
        "serialize_work_order",
        lambda *args, **kwargs: {
            "ticket_id": "WO-001",
            "current_dispatch": {"id": "dispatch-2"},
        },
    )
    monkeypatch.setattr(routes_workorder, "get_or_compute_json", _fake_cache)

    db = SimpleNamespace(execute=AsyncMock(return_value=_ScalarResult(audit_logs)))
    response = await routes_workorder.get_work_order_timeline_endpoint(
        ticket_id="WO-001",
        db=db,
    )

    assert response["ticket_id"] == "WO-001"
    assert len(response["dispatch_tasks"]) == 2
    assert response["dispatch_tasks"][1]["assigned_to_name"] == "李工"
    assert any(item["attempt_no"] == 2 for item in response["timeline"])
    assert any(item["label"] == "工单已创建" for item in response["timeline"])


@pytest.mark.asyncio
async def test_batch_dispatch_preview_endpoint_returns_preview(monkeypatch: pytest.MonkeyPatch) -> None:
    preview_payload = {
        "pending_dispatch_total": 15,
        "scanned_count": 10,
        "selected_count": 4,
        "sample_size": 4,
        "scan_limit": 10,
        "selection_rules": {"min_score": 100, "min_gap": 10, "max_per_worker": 2},
        "filters": {"building_id": None, "priority": None},
        "recommendations": [{"ticket_id": "WO-001"}],
        "skipped_summary": [{"reason": "score_gap_below_threshold", "count": 2}],
        "planned_assignments": [{"user_id": "ops-1", "username": "张工", "count": 2}],
        "worker_loads": [{"user_id": "ops-1", "username": "张工", "planned_count": 2}],
        "skipped_examples": [{"ticket_id": "WO-009", "reason": "score_gap_below_threshold"}],
    }
    mock_preview = AsyncMock(return_value=preview_payload)
    monkeypatch.setattr(routes_workorder, "build_batch_dispatch_preview", mock_preview)

    response = await routes_workorder.batch_dispatch_preview_endpoint(
        sample_size=4,
        scan_limit=10,
        min_score=100,
        min_gap=10,
        building_id=None,
        priority=None,
        max_per_worker=2,
        db=SimpleNamespace(),
        user=SimpleNamespace(id="manager-1", role="manager"),
    )

    assert response["selected_count"] == 4
    assert response["recommendations"][0]["ticket_id"] == "WO-001"
    assert mock_preview.await_args.kwargs["sample_size"] == 4
    assert mock_preview.await_args.kwargs["max_per_worker"] == 2


@pytest.mark.asyncio
async def test_batch_dispatch_work_orders_returns_partial_success(monkeypatch: pytest.MonkeyPatch) -> None:
    assigned_user = _make_user("ops-1", "张工")
    assigned_user.worker_profile.team_id = "team-1"
    work_order = SimpleNamespace(
        id="wo-1",
        ticket_id="WO-001",
        status="pending_dispatch",
        current_dispatch_id="dispatch-1",
    )

    async def fake_get_work_order_by_ticket_id(_db, ticket_id: str):
        return work_order if ticket_id == "WO-001" else None

    monkeypatch.setattr(routes_workorder, "get_work_order_by_ticket_id", fake_get_work_order_by_ticket_id)
    monkeypatch.setattr(
        routes_workorder,
        "_load_users_by_ids",
        AsyncMock(return_value={"ops-1": assigned_user}),
    )
    monkeypatch.setattr(routes_workorder, "assign_work_order", AsyncMock(return_value=work_order))
    monkeypatch.setattr(routes_workorder, "_invalidate_related_cache", AsyncMock())

    db = SimpleNamespace(commit=AsyncMock(), rollback=AsyncMock())
    req = routes_workorder.BatchDispatchApplyRequest(
        items=[
            routes_workorder.BatchDispatchApplyItemRequest(
                ticket_id="WO-001",
                assigned_to="ops-1",
                selection_reason="推荐分最高",
            ),
            routes_workorder.BatchDispatchApplyItemRequest(
                ticket_id="WO-404",
                assigned_to="ops-1",
            ),
        ]
    )

    response = await routes_workorder.batch_dispatch_work_orders(
        req=req,
        db=db,
        user=SimpleNamespace(id="manager-1", role="manager"),
    )

    assert response["requested_count"] == 2
    assert response["dispatched_count"] == 1
    assert response["failed_count"] == 1
    assert response["applied"][0]["ticket_id"] == "WO-001"
    assert response["failed"][0]["ticket_id"] == "WO-404"
    assert response["failed"][0]["reason_code"] == "work_order_missing"
    assert response["failed"][0]["manual_review_recommended"] is False
    db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_update_dispatch_task_action_support_resolved_clears_blocking_state() -> None:
    from app.services import dispatch_service

    now = datetime.now(timezone.utc)
    dispatch_task = _make_dispatch_task(dispatch_status="waiting_support")
    dispatch_task.support_reason = "等待暖通班支援"
    dispatch_task.support_team_id = "team-hvac"
    dispatch_task.worker_result = "needs_parts"
    work_order = SimpleNamespace(
        id="wo-1",
        ticket_id="WO-001",
        incident_id=None,
        priority="medium",
        status="dispatched",
        current_dispatch_id=dispatch_task.id,
        assigned_to=dispatch_task.assigned_to,
        assigned_at=dispatch_task.assigned_at,
        accepted_at=dispatch_task.accepted_at,
        arrived_at=dispatch_task.arrived_at,
        processing_started_at=dispatch_task.processing_started_at,
        updated_at=now,
        worker_result="needs_parts",
        worker_feedback_at=now - timedelta(minutes=5),
        dispatch_blocked_reason="等待暖通班支援",
    )
    db = SimpleNamespace(add=MagicMock())

    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.setattr(dispatch_service, "close_open_hall_entries_for_dispatch", AsyncMock())

        await dispatch_service.update_dispatch_task_action(
            db,
            work_order=work_order,
            dispatch_task=dispatch_task,
            action="support_resolved",
            actor_type="worker",
            actor_id="ops-1",
            notes="暖通班已到场，继续处理",
        )

    assert dispatch_task.dispatch_status == "processing"
    assert dispatch_task.support_reason is None
    assert dispatch_task.support_team_id is None
    assert dispatch_task.worker_result is None
    assert work_order.dispatch_blocked_reason is None
    assert work_order.worker_result is None
    assert work_order.worker_feedback_at is None


@pytest.mark.asyncio
async def test_cancel_dispatch_task_marks_task_cancelled_and_clears_projection() -> None:
    from app.services import dispatch_service

    now = datetime.now(timezone.utc)
    dispatch_task = _make_dispatch_task(dispatch_status="accepted")
    work_order = SimpleNamespace(
        id="wo-1",
        ticket_id="WO-001",
        incident_id=None,
        priority="medium",
        status="dispatched",
        current_dispatch_id=dispatch_task.id,
        assigned_to=dispatch_task.assigned_to,
        assigned_at=dispatch_task.assigned_at,
        accepted_at=dispatch_task.accepted_at,
        arrived_at=dispatch_task.arrived_at,
        processing_started_at=dispatch_task.processing_started_at,
        updated_at=now,
    )
    db = SimpleNamespace(add=MagicMock())

    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.setattr(dispatch_service, "close_open_hall_entries_for_dispatch", AsyncMock())

        await dispatch_service.cancel_dispatch_task(
            db,
            work_order=work_order,
            dispatch_task=dispatch_task,
            actor_type="admin",
            actor_id="admin-1",
            reason="现场条件变化，撤回本次派工",
        )

    assert dispatch_task.dispatch_status == "cancelled"
    assert dispatch_task.cancel_reason == "现场条件变化，撤回本次派工"
    assert dispatch_task.is_current is False
    assert work_order.current_dispatch_id is None
    assert work_order.assigned_to is None


@pytest.mark.asyncio
async def test_nudge_dispatch_task_increments_reminder_and_keeps_projection() -> None:
    from app.services.dispatch_service import nudge_dispatch_task

    now = datetime.now(timezone.utc)
    dispatch_task = _make_dispatch_task(dispatch_status="accepted")
    dispatch_task.reminder_count = 0
    dispatch_task.last_reminded_at = None
    work_order = SimpleNamespace(
        id="wo-1",
        ticket_id="WO-001",
        incident_id=None,
        priority="medium",
        status="dispatched",
        current_dispatch_id=dispatch_task.id,
        assigned_to=dispatch_task.assigned_to,
        assigned_at=dispatch_task.assigned_at,
        accepted_at=dispatch_task.accepted_at,
        arrived_at=dispatch_task.arrived_at,
        processing_started_at=dispatch_task.processing_started_at,
        updated_at=now,
        dispatch_blocked_reason=None,
    )
    db = SimpleNamespace(add=MagicMock())

    await nudge_dispatch_task(
        db,
        work_order=work_order,
        dispatch_task=dispatch_task,
        actor_type="admin",
        actor_id="manager-1",
        message="请尽快到场反馈现场进展",
    )

    assert dispatch_task.reminder_count == 1
    assert dispatch_task.last_reminded_at is not None
    assert dispatch_task.latest_note == "请尽快到场反馈现场进展"
    assert work_order.current_dispatch_id == dispatch_task.id
    assert work_order.assigned_to == dispatch_task.assigned_to


@pytest.mark.asyncio
async def test_support_resolved_dispatch_task_endpoint_updates_work_order(monkeypatch: pytest.MonkeyPatch) -> None:
    dispatch_task = _make_dispatch_task(dispatch_status="waiting_support")
    work_order = SimpleNamespace(
        id="wo-1",
        ticket_id="WO-001",
        work_order_id="wo-1",
        status="dispatched",
        worker_result="needs_parts",
        worker_feedback_at=datetime.now(timezone.utc),
        worker_notes="等待协同",
        dispatch_blocked_reason="等待协同",
    )
    db = SimpleNamespace(commit=AsyncMock())

    monkeypatch.setattr(routes_dispatch, "get_dispatch_task_by_id", AsyncMock(return_value=dispatch_task))
    monkeypatch.setattr(routes_dispatch, "_load_work_order", AsyncMock(return_value=work_order))
    monkeypatch.setattr(routes_dispatch, "update_dispatch_task_action", AsyncMock(return_value=dispatch_task))
    monkeypatch.setattr(routes_dispatch, "_write_audit_log", AsyncMock())
    monkeypatch.setattr(routes_dispatch, "_invalidate_related_cache", AsyncMock())

    response = await routes_dispatch.support_resolved_dispatch_task(
        dispatch_id=dispatch_task.id,
        req=routes_dispatch.SupportResolvedRequest(notes="协同班组已到场"),
        db=db,
        user=SimpleNamespace(id="ops-1", role="ops"),
    )

    assert response["dispatch_id"] == dispatch_task.id
    assert work_order.worker_result is None
    assert work_order.worker_feedback_at is None
    assert work_order.dispatch_blocked_reason is None


@pytest.mark.asyncio
async def test_nudge_dispatch_task_endpoint_returns_reminder_count(monkeypatch: pytest.MonkeyPatch) -> None:
    dispatch_task = _make_dispatch_task(dispatch_status="assigned")
    dispatch_task.reminder_count = 1
    dispatch_task.last_reminded_at = datetime.now(timezone.utc)
    work_order = SimpleNamespace(
        id="wo-1",
        ticket_id="WO-001",
        status="dispatched",
    )
    db = SimpleNamespace(commit=AsyncMock())

    async def _fake_nudge(*_args, **_kwargs):
        dispatch_task.reminder_count = 2
        dispatch_task.last_reminded_at = datetime.now(timezone.utc)
        return dispatch_task

    monkeypatch.setattr(routes_dispatch, "get_dispatch_task_by_id", AsyncMock(return_value=dispatch_task))
    monkeypatch.setattr(routes_dispatch, "_load_work_order", AsyncMock(return_value=work_order))
    monkeypatch.setattr(routes_dispatch, "nudge_dispatch_task", AsyncMock(side_effect=_fake_nudge))
    monkeypatch.setattr(routes_dispatch, "_write_audit_log", AsyncMock())
    monkeypatch.setattr(routes_dispatch, "_invalidate_related_cache", AsyncMock())

    response = await routes_dispatch.nudge_dispatch_task_endpoint(
        dispatch_id=dispatch_task.id,
        req=routes_dispatch.NudgeRequest(message="请尽快接单"),
        db=db,
        user=SimpleNamespace(id="manager-1", role="manager"),
    )

    assert response["dispatch_id"] == dispatch_task.id
    assert response["reminder_count"] == 2
    assert response["status"] == "dispatched"
    db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_cancel_dispatch_task_endpoint_returns_pending_dispatch(monkeypatch: pytest.MonkeyPatch) -> None:
    dispatch_task = _make_dispatch_task(dispatch_status="assigned")
    work_order = SimpleNamespace(
        id="wo-1",
        ticket_id="WO-001",
        status="dispatched",
        dispatch_blocked_reason=None,
    )
    db = SimpleNamespace(commit=AsyncMock())

    monkeypatch.setattr(routes_dispatch, "get_dispatch_task_by_id", AsyncMock(return_value=dispatch_task))
    monkeypatch.setattr(routes_dispatch, "_load_work_order", AsyncMock(return_value=work_order))
    monkeypatch.setattr(routes_dispatch, "cancel_dispatch_task", AsyncMock(return_value=dispatch_task))
    monkeypatch.setattr(routes_dispatch, "transition_status", AsyncMock())
    monkeypatch.setattr(routes_dispatch, "_invalidate_related_cache", AsyncMock())

    response = await routes_dispatch.cancel_dispatch_task_endpoint(
        dispatch_id=dispatch_task.id,
        req=routes_dispatch.CancelRequest(reason="现场条件变化"),
        db=db,
        user=SimpleNamespace(id="manager-1", role="manager"),
    )

    assert response["status"] == "dispatched"
    assert work_order.dispatch_blocked_reason == "现场条件变化"
    assert routes_dispatch.transition_status.await_args.kwargs["new_status"] == "pending_dispatch"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("endpoint_name", "expected_action", "expected_message"),
    [
        ("accept_dispatch_task", "accept", "已确认接单"),
        ("arrive_dispatch_task", "arrive", "已确认到场"),
        ("start_dispatch_task", "start", "已开始处理"),
    ],
)
async def test_dispatch_progress_endpoints_call_update_action(
    endpoint_name: str,
    expected_action: str,
    expected_message: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dispatch_task = _make_dispatch_task(dispatch_status="assigned")
    work_order = _make_work_order()
    db = SimpleNamespace(commit=AsyncMock())

    monkeypatch.setattr(routes_dispatch, "get_dispatch_task_by_id", AsyncMock(return_value=dispatch_task))
    monkeypatch.setattr(routes_dispatch, "_load_work_order", AsyncMock(return_value=work_order))
    monkeypatch.setattr(routes_dispatch, "update_dispatch_task_action", AsyncMock(return_value=dispatch_task))
    monkeypatch.setattr(routes_dispatch, "_write_audit_log", AsyncMock())
    monkeypatch.setattr(routes_dispatch, "_invalidate_related_cache", AsyncMock())

    endpoint = getattr(routes_dispatch, endpoint_name)
    response = await endpoint(
        dispatch_id=dispatch_task.id,
        db=db,
        user=SimpleNamespace(id="ops-1", role="ops"),
    )

    assert response == {
        "dispatch_id": dispatch_task.id,
        "message": expected_message,
        "status": "dispatched",
    }
    assert routes_dispatch.update_dispatch_task_action.await_args.kwargs["action"] == expected_action
    assert routes_dispatch.update_dispatch_task_action.await_args.kwargs["actor_type"] == "worker"
    db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_request_support_dispatch_task_endpoint_sets_blocking_projection(monkeypatch: pytest.MonkeyPatch) -> None:
    dispatch_task = _make_dispatch_task(dispatch_status="processing")
    work_order = _make_work_order()
    db = SimpleNamespace(commit=AsyncMock())

    monkeypatch.setattr(routes_dispatch, "get_dispatch_task_by_id", AsyncMock(return_value=dispatch_task))
    monkeypatch.setattr(routes_dispatch, "_load_work_order", AsyncMock(return_value=work_order))
    monkeypatch.setattr(routes_dispatch, "update_dispatch_task_action", AsyncMock(return_value=dispatch_task))
    monkeypatch.setattr(routes_dispatch, "_write_audit_log", AsyncMock())
    monkeypatch.setattr(routes_dispatch, "_invalidate_related_cache", AsyncMock())

    response = await routes_dispatch.request_support_dispatch_task(
        dispatch_id=dispatch_task.id,
        req=routes_dispatch.SupportRequest(reason="需要暖通班协同", support_team_id="team-hvac"),
        db=db,
        user=SimpleNamespace(id="ops-1", role="ops"),
    )

    assert response["message"] == "已提交协同请求"
    assert work_order.worker_result == "needs_parts"
    assert work_order.worker_notes == "需要暖通班协同"
    assert routes_dispatch.update_dispatch_task_action.await_args.kwargs["action"] == "request_support"
    assert routes_dispatch.update_dispatch_task_action.await_args.kwargs["support_team_id"] == "team-hvac"


@pytest.mark.asyncio
async def test_reject_dispatch_task_endpoint_returns_pending_dispatch(monkeypatch: pytest.MonkeyPatch) -> None:
    dispatch_task = _make_dispatch_task(dispatch_status="accepted")
    work_order = _make_work_order(status="dispatched")
    db = SimpleNamespace(commit=AsyncMock())

    async def _fake_transition(*_args, **kwargs):
        work_order.status = kwargs["new_status"]

    monkeypatch.setattr(routes_dispatch, "get_dispatch_task_by_id", AsyncMock(return_value=dispatch_task))
    monkeypatch.setattr(routes_dispatch, "_load_work_order", AsyncMock(return_value=work_order))
    monkeypatch.setattr(routes_dispatch, "reject_dispatch_task", AsyncMock(return_value=dispatch_task))
    monkeypatch.setattr(routes_dispatch, "transition_status", AsyncMock(side_effect=_fake_transition))
    monkeypatch.setattr(routes_dispatch, "_invalidate_related_cache", AsyncMock())

    response = await routes_dispatch.reject_dispatch_task_endpoint(
        dispatch_id=dispatch_task.id,
        req=routes_dispatch.RejectRequest(reason="现场无法进入，暂不接单"),
        db=db,
        user=SimpleNamespace(id="ops-1", role="ops"),
    )

    assert response["message"] == "已拒单，工单返回待派工"
    assert response["status"] == "pending_dispatch"
    assert work_order.dispatch_blocked_reason == "现场无法进入，暂不接单"
    assert routes_dispatch.transition_status.await_args.kwargs["new_status"] == "pending_dispatch"
    assert routes_dispatch.reject_dispatch_task.await_args.kwargs["actor_type"] == "worker"


@pytest.mark.asyncio
async def test_complete_dispatch_task_endpoint_transitions_completed_results(monkeypatch: pytest.MonkeyPatch) -> None:
    dispatch_task = _make_dispatch_task(dispatch_status="processing")
    work_order = _make_work_order(status="dispatched")
    db = SimpleNamespace(commit=AsyncMock())

    async def _fake_transition(*_args, **kwargs):
        work_order.status = kwargs["new_status"]

    monkeypatch.setattr(routes_dispatch, "get_dispatch_task_by_id", AsyncMock(return_value=dispatch_task))
    monkeypatch.setattr(routes_dispatch, "_load_work_order", AsyncMock(return_value=work_order))
    monkeypatch.setattr(routes_dispatch, "complete_dispatch_task", AsyncMock(return_value=dispatch_task))
    monkeypatch.setattr(routes_dispatch, "transition_status", AsyncMock(side_effect=_fake_transition))
    monkeypatch.setattr(routes_dispatch, "_invalidate_related_cache", AsyncMock())

    response = await routes_dispatch.complete_dispatch_task_endpoint(
        dispatch_id=dispatch_task.id,
        req=routes_dispatch.CompleteRequest(result="fixed", notes="现场恢复正常"),
        db=db,
        user=SimpleNamespace(id="ops-1", role="ops"),
    )

    assert response["message"] == "已提交处理结果"
    assert response["status"] == "completed"
    assert work_order.worker_result == "fixed"
    assert work_order.worker_notes == "现场恢复正常"
    assert work_order.worker_feedback_at is not None
    assert routes_dispatch.transition_status.await_args.kwargs["new_status"] == "completed"
    assert routes_dispatch.complete_dispatch_task.await_args.kwargs["actor_type"] == "worker"


@pytest.mark.asyncio
async def test_complete_dispatch_task_endpoint_keeps_needs_parts_in_dispatch(monkeypatch: pytest.MonkeyPatch) -> None:
    dispatch_task = _make_dispatch_task(dispatch_status="processing")
    work_order = _make_work_order(status="dispatched")
    db = SimpleNamespace(commit=AsyncMock())

    monkeypatch.setattr(routes_dispatch, "get_dispatch_task_by_id", AsyncMock(return_value=dispatch_task))
    monkeypatch.setattr(routes_dispatch, "_load_work_order", AsyncMock(return_value=work_order))
    monkeypatch.setattr(routes_dispatch, "complete_dispatch_task", AsyncMock(return_value=dispatch_task))
    monkeypatch.setattr(routes_dispatch, "transition_status", AsyncMock())
    monkeypatch.setattr(routes_dispatch, "_write_audit_log", AsyncMock())
    monkeypatch.setattr(routes_dispatch, "_invalidate_related_cache", AsyncMock())

    response = await routes_dispatch.complete_dispatch_task_endpoint(
        dispatch_id=dispatch_task.id,
        req=routes_dispatch.CompleteRequest(result="needs_parts", notes="等待配件到货"),
        db=db,
        user=SimpleNamespace(id="ops-1", role="ops"),
    )

    assert response["status"] == "dispatched"
    assert work_order.worker_result == "needs_parts"
    routes_dispatch.transition_status.assert_not_awaited()
    routes_dispatch._write_audit_log.assert_awaited_once()
    audit_kwargs = routes_dispatch._write_audit_log.await_args.kwargs
    assert audit_kwargs["action"] == "worker_feedback"
    assert audit_kwargs["old_status"] == "dispatched"
    assert audit_kwargs["new_status"] == "dispatched"
    assert audit_kwargs["detail"]["result"] == "needs_parts"
    assert audit_kwargs["detail"]["notes"] == "等待配件到货"


@pytest.mark.asyncio
async def test_reassign_dispatch_task_endpoint_returns_new_dispatch(monkeypatch: pytest.MonkeyPatch) -> None:
    dispatch_task = _make_dispatch_task(dispatch_status="accepted")
    new_dispatch = _make_dispatch_task(dispatch_id="dispatch-2", assigned_to="ops-2", attempt_no=2)
    work_order = _make_work_order()
    assigned_user = _make_user("ops-2", "李工")
    db = SimpleNamespace(commit=AsyncMock())

    monkeypatch.setattr(routes_dispatch, "get_dispatch_task_by_id", AsyncMock(return_value=dispatch_task))
    monkeypatch.setattr(routes_dispatch, "_load_work_order", AsyncMock(return_value=work_order))
    monkeypatch.setattr(routes_dispatch, "_load_assigned_user", AsyncMock(return_value=assigned_user))
    monkeypatch.setattr(routes_dispatch, "reassign_dispatch_task", AsyncMock(return_value=new_dispatch))
    monkeypatch.setattr(routes_dispatch, "_write_audit_log", AsyncMock())
    monkeypatch.setattr(routes_dispatch, "_invalidate_related_cache", AsyncMock())

    response = await routes_dispatch.reassign_dispatch_task_endpoint(
        dispatch_id=dispatch_task.id,
        req=routes_dispatch.ReassignRequest(assigned_to="ops-2", reason="当前班组满载，改派给李工"),
        db=db,
        user=SimpleNamespace(id="manager-1", role="manager"),
    )

    assert response == {
        "dispatch_id": "dispatch-2",
        "message": "已改派给 李工",
        "status": "dispatched",
    }
    assert routes_dispatch.reassign_dispatch_task.await_args.kwargs["assigned_user"].id == "ops-2"
    assert routes_dispatch.reassign_dispatch_task.await_args.kwargs["dispatch_mode"] == "reassigned"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "endpoint_name",
    [
        "get_dispatch_task_detail",
        "accept_dispatch_task",
        "arrive_dispatch_task",
        "start_dispatch_task",
        "request_support_dispatch_task",
        "support_resolved_dispatch_task",
        "reject_dispatch_task_endpoint",
        "complete_dispatch_task_endpoint",
    ],
)
async def test_ops_user_cannot_access_or_operate_other_users_dispatch_task(
    endpoint_name: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dispatch_task = _make_dispatch_task(assigned_to="ops-2")
    monkeypatch.setattr(routes_dispatch, "get_dispatch_task_by_id", AsyncMock(return_value=dispatch_task))

    endpoint = getattr(routes_dispatch, endpoint_name)
    call_kwargs = {
        "dispatch_id": dispatch_task.id,
        "db": SimpleNamespace(),
        "user": SimpleNamespace(id="ops-1", role="ops"),
    }
    if endpoint_name == "request_support_dispatch_task":
        call_kwargs["req"] = routes_dispatch.SupportRequest(reason="需要协同", support_team_id="team-1")
    elif endpoint_name == "support_resolved_dispatch_task":
        call_kwargs["req"] = routes_dispatch.SupportResolvedRequest(notes="协同已处理")
    elif endpoint_name == "reject_dispatch_task_endpoint":
        call_kwargs["req"] = routes_dispatch.RejectRequest(reason="无法前往现场")
    elif endpoint_name == "complete_dispatch_task_endpoint":
        call_kwargs["req"] = routes_dispatch.CompleteRequest(result="fixed", notes="已恢复")

    with pytest.raises(HTTPException) as exc_info:
        await endpoint(**call_kwargs)

    assert exc_info.value.status_code == 403


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("endpoint_name", "call_kwargs"),
    [
        (
            "nudge_dispatch_task_endpoint",
            {"req": routes_dispatch.NudgeRequest(message="请尽快处理")},
        ),
        (
            "cancel_dispatch_task_endpoint",
            {"req": routes_dispatch.CancelRequest(reason="现场条件变化")},
        ),
        (
            "reassign_dispatch_task_endpoint",
            {"req": routes_dispatch.ReassignRequest(assigned_to="ops-2", reason="改派给其他班组")},
        ),
    ],
)
async def test_admin_only_dispatch_endpoints_reject_ops_users(
    endpoint_name: str,
    call_kwargs: dict[str, object],
) -> None:
    endpoint = getattr(routes_dispatch, endpoint_name)

    with pytest.raises(HTTPException) as exc_info:
        await endpoint(
            dispatch_id="dispatch-1",
            db=SimpleNamespace(),
            user=SimpleNamespace(id="ops-1", role="ops"),
            **call_kwargs,
        )

    assert exc_info.value.status_code == 403


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("endpoint_name", "call_kwargs"),
    [
        ("accept_dispatch_task", {}),
        ("arrive_dispatch_task", {}),
        ("start_dispatch_task", {}),
        (
            "request_support_dispatch_task",
            {"req": routes_dispatch.SupportRequest(reason="需要协同", support_team_id="team-1")},
        ),
        (
            "support_resolved_dispatch_task",
            {"req": routes_dispatch.SupportResolvedRequest(notes="协同已恢复")},
        ),
    ],
)
async def test_progress_dispatch_endpoints_map_value_error_to_conflict(
    endpoint_name: str,
    call_kwargs: dict[str, object],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dispatch_task = _make_dispatch_task()
    work_order = _make_work_order()

    monkeypatch.setattr(routes_dispatch, "get_dispatch_task_by_id", AsyncMock(return_value=dispatch_task))
    monkeypatch.setattr(routes_dispatch, "_load_work_order", AsyncMock(return_value=work_order))
    monkeypatch.setattr(
        routes_dispatch,
        "update_dispatch_task_action",
        AsyncMock(side_effect=ValueError("当前派工任务状态冲突")),
    )

    endpoint = getattr(routes_dispatch, endpoint_name)
    with pytest.raises(HTTPException) as exc_info:
        await endpoint(
            dispatch_id=dispatch_task.id,
            db=SimpleNamespace(),
            user=SimpleNamespace(id="ops-1", role="ops"),
            **call_kwargs,
        )

    assert exc_info.value.status_code == 409
    assert "状态冲突" in exc_info.value.detail


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("endpoint_name", "service_name", "call_kwargs", "user_role"),
    [
        (
            "nudge_dispatch_task_endpoint",
            "nudge_dispatch_task",
            {"req": routes_dispatch.NudgeRequest(message="请尽快处理")},
            "manager",
        ),
        (
            "reject_dispatch_task_endpoint",
            "reject_dispatch_task",
            {"req": routes_dispatch.RejectRequest(reason="现场条件不满足")},
            "ops",
        ),
        (
            "cancel_dispatch_task_endpoint",
            "cancel_dispatch_task",
            {"req": routes_dispatch.CancelRequest(reason="现场条件变化")},
            "manager",
        ),
        (
            "reassign_dispatch_task_endpoint",
            "reassign_dispatch_task",
            {"req": routes_dispatch.ReassignRequest(assigned_to="ops-2", reason="改派测试")},
            "manager",
        ),
    ],
)
async def test_dispatch_management_endpoints_map_value_error_to_conflict(
    endpoint_name: str,
    service_name: str,
    call_kwargs: dict[str, object],
    user_role: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dispatch_task = _make_dispatch_task()
    work_order = _make_work_order()

    monkeypatch.setattr(routes_dispatch, "get_dispatch_task_by_id", AsyncMock(return_value=dispatch_task))
    monkeypatch.setattr(routes_dispatch, "_load_work_order", AsyncMock(return_value=work_order))
    monkeypatch.setattr(
        routes_dispatch,
        service_name,
        AsyncMock(side_effect=ValueError("当前派工任务状态冲突")),
    )
    if endpoint_name == "reassign_dispatch_task_endpoint":
        monkeypatch.setattr(routes_dispatch, "_load_assigned_user", AsyncMock(return_value=_make_user("ops-2", "李工")))

    endpoint = getattr(routes_dispatch, endpoint_name)
    with pytest.raises(HTTPException) as exc_info:
        await endpoint(
            dispatch_id=dispatch_task.id,
            db=SimpleNamespace(),
            user=SimpleNamespace(id=f"{user_role}-1", role=user_role),
            **call_kwargs,
        )

    assert exc_info.value.status_code == 409
    assert "状态冲突" in exc_info.value.detail


@pytest.mark.asyncio
async def test_complete_dispatch_task_endpoint_maps_value_error_to_conflict(monkeypatch: pytest.MonkeyPatch) -> None:
    dispatch_task = _make_dispatch_task(dispatch_status="processing")
    work_order = _make_work_order(status="dispatched")

    monkeypatch.setattr(routes_dispatch, "get_dispatch_task_by_id", AsyncMock(return_value=dispatch_task))
    monkeypatch.setattr(routes_dispatch, "_load_work_order", AsyncMock(return_value=work_order))
    monkeypatch.setattr(
        routes_dispatch,
        "complete_dispatch_task",
        AsyncMock(side_effect=ValueError("当前派工任务不支持完成")),
    )

    with pytest.raises(HTTPException) as exc_info:
        await routes_dispatch.complete_dispatch_task_endpoint(
            dispatch_id=dispatch_task.id,
            req=routes_dispatch.CompleteRequest(result="fixed", notes="已修复"),
            db=SimpleNamespace(),
            user=SimpleNamespace(id="ops-1", role="ops"),
        )

    assert exc_info.value.status_code == 409
    assert "不支持完成" in exc_info.value.detail


@pytest.mark.asyncio
async def test_scan_dispatch_sla_states_updates_warning_and_overdue_tasks() -> None:
    from app.services import dispatch_service

    now = datetime.now(timezone.utc)
    warning_task = _make_dispatch_task(dispatch_id="dispatch-warning", dispatch_status="assigned")
    warning_task.timeout_level = "normal"
    warning_task.accept_deadline_at = now + timedelta(minutes=8)
    warning_task.latest_note = None
    overdue_task = _make_dispatch_task(dispatch_id="dispatch-overdue", dispatch_status="processing")
    overdue_task.timeout_level = "normal"
    overdue_task.finish_deadline_at = now - timedelta(minutes=6)
    overdue_task.latest_note = None
    warning_work_order = SimpleNamespace(
        id="wo-1",
        incident_id=None,
        assigned_to=warning_task.assigned_to,
        assigned_at=warning_task.assigned_at,
        accepted_at=warning_task.accepted_at,
        arrived_at=warning_task.arrived_at,
        processing_started_at=warning_task.processing_started_at,
        updated_at=now,
        dispatch_blocked_reason=None,
    )
    overdue_work_order = SimpleNamespace(
        id="wo-2",
        incident_id=None,
        assigned_to=overdue_task.assigned_to,
        assigned_at=overdue_task.assigned_at,
        accepted_at=overdue_task.accepted_at,
        arrived_at=overdue_task.arrived_at,
        processing_started_at=overdue_task.processing_started_at,
        updated_at=now,
        dispatch_blocked_reason=None,
    )
    warning_task.work_order_id = "wo-1"
    overdue_task.work_order_id = "wo-2"
    db = SimpleNamespace(
        add=MagicMock(),
        execute=AsyncMock(side_effect=[
            _ScalarResult([warning_task, overdue_task]),
            _ScalarResult([warning_work_order, overdue_work_order]),
        ]),
    )

    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.setattr(dispatch_service, "create_or_reopen_takeover_hall_entry", AsyncMock())
        monkeypatch.setattr(dispatch_service, "close_open_hall_entries_for_dispatch", AsyncMock())

        summary = await dispatch_service.scan_dispatch_sla_states(db, now=now)

    assert summary["scanned"] == 2
    assert summary["updated"] == 2
    assert summary["warning_events"] == 1
    assert summary["overdue_events"] == 1
    assert warning_task.timeout_level == "warning"
    assert warning_task.reminder_count == 1
    assert "即将超时" in (warning_task.latest_note or "")
    assert overdue_task.timeout_level == "overdue"
    assert overdue_task.reminder_count == 1
    assert "已超时" in (overdue_task.latest_note or "")
    assert set(summary["timings_ms"]) == {
        "load_dispatch_tasks",
        "load_work_orders",
        "load_current_assignees",
        "prepare_candidate_context",
        "process_loop",
        "total",
    }
    assert summary["timings_ms"]["total"] >= 0


@pytest.mark.asyncio
async def test_scan_dispatch_sla_admin_endpoint_clears_cache_when_updates_exist(monkeypatch: pytest.MonkeyPatch) -> None:
    db = SimpleNamespace(commit=AsyncMock(), rollback=AsyncMock())
    monkeypatch.setattr(
        routes_admin,
        "scan_dispatch_sla_states",
        AsyncMock(
            return_value={
                "scanned": 3,
                "updated": 2,
                "warning_events": 1,
                "overdue_events": 1,
                "timings_ms": {"total": 1200},
            }
        ),
    )
    monkeypatch.setattr(routes_admin, "delete_cache_by_prefix", AsyncMock())
    monkeypatch.setattr(routes_admin, "record_dispatch_operation_run", AsyncMock())

    response = await routes_admin.scan_dispatch_sla(db=db)

    assert response["status"] == "ok"
    assert response["updated"] == 2
    assert routes_admin.delete_cache_by_prefix.await_count == 2
    assert routes_admin.record_dispatch_operation_run.await_args.kwargs["run_status"] == "success"


@pytest.mark.asyncio
async def test_request_support_action_opens_dispatch_hall_entry(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services import dispatch_service

    dispatch_task = _make_dispatch_task(dispatch_status="processing")
    work_order = SimpleNamespace(
        id="wo-1",
        ticket_id="WO-001",
        incident_id=None,
        priority="medium",
        status="dispatched",
        current_dispatch_id=dispatch_task.id,
        assigned_to=dispatch_task.assigned_to,
        assigned_at=dispatch_task.assigned_at,
        accepted_at=dispatch_task.accepted_at,
        arrived_at=dispatch_task.arrived_at,
        processing_started_at=dispatch_task.processing_started_at,
        updated_at=datetime.now(timezone.utc),
        worker_result=None,
        worker_feedback_at=None,
        dispatch_blocked_reason=None,
    )
    db = SimpleNamespace(add=MagicMock())

    monkeypatch.setattr(dispatch_service, "_sync_incident_dispatch_projection", AsyncMock())
    monkeypatch.setattr(dispatch_service, "record_dispatch_event", AsyncMock())
    monkeypatch.setattr(dispatch_service, "create_or_reopen_support_hall_entry", AsyncMock())
    monkeypatch.setattr(dispatch_service, "close_open_hall_entries_for_dispatch", AsyncMock())

    await dispatch_service.update_dispatch_task_action(
        db,
        work_order=work_order,
        dispatch_task=dispatch_task,
        action="request_support",
        actor_type="worker",
        actor_id="ops-1",
        notes="需要暖通班支援",
        support_team_id="team-hvac",
    )

    dispatch_service.create_or_reopen_support_hall_entry.assert_awaited_once()
    assert dispatch_service.create_or_reopen_support_hall_entry.await_args.kwargs["target_team_ids"] == ["team-hvac"]


@pytest.mark.asyncio
async def test_support_resolved_action_closes_dispatch_hall_entry(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services import dispatch_service

    dispatch_task = _make_dispatch_task(dispatch_status="waiting_support")
    dispatch_task.support_reason = "等待暖通班支援"
    dispatch_task.support_team_id = "team-hvac"
    work_order = SimpleNamespace(
        id="wo-1",
        ticket_id="WO-001",
        incident_id=None,
        priority="medium",
        status="dispatched",
        current_dispatch_id=dispatch_task.id,
        assigned_to=dispatch_task.assigned_to,
        assigned_at=dispatch_task.assigned_at,
        accepted_at=dispatch_task.accepted_at,
        arrived_at=dispatch_task.arrived_at,
        processing_started_at=dispatch_task.processing_started_at,
        updated_at=datetime.now(timezone.utc),
        worker_result="needs_parts",
        worker_feedback_at=datetime.now(timezone.utc),
        dispatch_blocked_reason="等待暖通班支援",
    )
    db = SimpleNamespace(add=MagicMock())

    monkeypatch.setattr(dispatch_service, "_sync_incident_dispatch_projection", AsyncMock())
    monkeypatch.setattr(dispatch_service, "record_dispatch_event", AsyncMock())
    monkeypatch.setattr(dispatch_service, "create_or_reopen_support_hall_entry", AsyncMock())
    monkeypatch.setattr(dispatch_service, "close_open_hall_entries_for_dispatch", AsyncMock())

    await dispatch_service.update_dispatch_task_action(
        db,
        work_order=work_order,
        dispatch_task=dispatch_task,
        action="support_resolved",
        actor_type="worker",
        actor_id="ops-1",
        notes="协同事项已解决",
    )

    dispatch_service.close_open_hall_entries_for_dispatch.assert_awaited_once()
    assert dispatch_service.close_open_hall_entries_for_dispatch.await_args.kwargs["entry_types"] == ["support_request"]


@pytest.mark.asyncio
async def test_complete_dispatch_task_needs_parts_opens_support_hall_entry(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services import dispatch_service

    dispatch_task = _make_dispatch_task(dispatch_status="processing")
    work_order = SimpleNamespace(
        id="wo-1",
        ticket_id="WO-001",
        incident_id=None,
        priority="medium",
        status="dispatched",
        current_dispatch_id=dispatch_task.id,
        assigned_to=dispatch_task.assigned_to,
        assigned_at=dispatch_task.assigned_at,
        accepted_at=dispatch_task.accepted_at,
        arrived_at=dispatch_task.arrived_at,
        processing_started_at=dispatch_task.processing_started_at,
        updated_at=datetime.now(timezone.utc),
    )
    db = SimpleNamespace(add=MagicMock())

    monkeypatch.setattr(dispatch_service, "_sync_incident_dispatch_projection", AsyncMock())
    monkeypatch.setattr(dispatch_service, "record_dispatch_event", AsyncMock())
    monkeypatch.setattr(dispatch_service, "create_or_reopen_support_hall_entry", AsyncMock())
    monkeypatch.setattr(dispatch_service, "close_open_hall_entries_for_dispatch", AsyncMock())

    await dispatch_service.complete_dispatch_task(
        db,
        work_order=work_order,
        dispatch_task=dispatch_task,
        actor_type="worker",
        actor_id="ops-1",
        result="needs_parts",
        notes="等待配件",
    )

    dispatch_service.create_or_reopen_support_hall_entry.assert_awaited_once()
    dispatch_service.close_open_hall_entries_for_dispatch.assert_not_awaited()


@pytest.mark.asyncio
async def test_complete_dispatch_task_fixed_closes_open_hall_entries(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services import dispatch_service

    dispatch_task = _make_dispatch_task(dispatch_status="processing")
    work_order = SimpleNamespace(
        id="wo-1",
        ticket_id="WO-001",
        incident_id=None,
        priority="medium",
        status="dispatched",
        current_dispatch_id=dispatch_task.id,
        assigned_to=dispatch_task.assigned_to,
        assigned_at=dispatch_task.assigned_at,
        accepted_at=dispatch_task.accepted_at,
        arrived_at=dispatch_task.arrived_at,
        processing_started_at=dispatch_task.processing_started_at,
        updated_at=datetime.now(timezone.utc),
    )
    db = SimpleNamespace(add=MagicMock())

    monkeypatch.setattr(dispatch_service, "_sync_incident_dispatch_projection", AsyncMock())
    monkeypatch.setattr(dispatch_service, "record_dispatch_event", AsyncMock())
    monkeypatch.setattr(dispatch_service, "create_or_reopen_support_hall_entry", AsyncMock())
    monkeypatch.setattr(dispatch_service, "close_open_hall_entries_for_dispatch", AsyncMock())

    await dispatch_service.complete_dispatch_task(
        db,
        work_order=work_order,
        dispatch_task=dispatch_task,
        actor_type="worker",
        actor_id="ops-1",
        result="fixed",
        notes="现场恢复正常",
    )

    dispatch_service.close_open_hall_entries_for_dispatch.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "service_name",
    ["cancel_dispatch_task", "reject_dispatch_task"],
)
async def test_dispatch_terminal_actions_close_open_hall_entries(
    service_name: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services import dispatch_service

    dispatch_task = _make_dispatch_task(dispatch_status="accepted")
    work_order = SimpleNamespace(
        id="wo-1",
        ticket_id="WO-001",
        incident_id=None,
        priority="medium",
        status="dispatched",
        current_dispatch_id=dispatch_task.id,
        assigned_to=dispatch_task.assigned_to,
        assigned_at=dispatch_task.assigned_at,
        accepted_at=dispatch_task.accepted_at,
        arrived_at=dispatch_task.arrived_at,
        processing_started_at=dispatch_task.processing_started_at,
        updated_at=datetime.now(timezone.utc),
    )
    db = SimpleNamespace(add=MagicMock())

    monkeypatch.setattr(dispatch_service, "_sync_incident_dispatch_projection", AsyncMock())
    monkeypatch.setattr(dispatch_service, "record_dispatch_event", AsyncMock())
    monkeypatch.setattr(dispatch_service, "close_open_hall_entries_for_dispatch", AsyncMock())

    service = getattr(dispatch_service, service_name)
    await service(
        db,
        work_order=work_order,
        dispatch_task=dispatch_task,
        actor_type="admin",
        actor_id="manager-1",
        reason="需要重新调度",
    )

    dispatch_service.close_open_hall_entries_for_dispatch.assert_awaited_once()


@pytest.mark.asyncio
async def test_reassign_dispatch_task_closes_open_hall_entries_before_new_dispatch(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services import dispatch_service

    dispatch_task = _make_dispatch_task(dispatch_status="processing")
    work_order = SimpleNamespace(id="wo-1", ticket_id="WO-001", incident_id=None, priority="medium")
    assigned_user = _make_user("ops-2", "李工")
    db = SimpleNamespace(add=MagicMock())

    monkeypatch.setattr(dispatch_service, "record_dispatch_event", AsyncMock())
    monkeypatch.setattr(dispatch_service, "close_open_hall_entries_for_dispatch", AsyncMock())
    monkeypatch.setattr(
        dispatch_service,
        "create_dispatch_task",
        AsyncMock(return_value=_make_dispatch_task(dispatch_id="dispatch-2", assigned_to="ops-2", attempt_no=2)),
    )

    await dispatch_service.reassign_dispatch_task(
        db,
        work_order=work_order,
        dispatch_task=dispatch_task,
        assigned_user=assigned_user,
        actor_type="admin",
        actor_id="manager-1",
        reason="当前派工超时，改派给李工",
    )

    dispatch_service.close_open_hall_entries_for_dispatch.assert_awaited_once()


@pytest.mark.asyncio
async def test_scan_dispatch_sla_states_opens_takeover_hall_entry_for_overdue_task(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services import dispatch_service

    now = datetime.now(timezone.utc)
    overdue_task = _make_dispatch_task(dispatch_id="dispatch-overdue", dispatch_status="processing")
    overdue_task.timeout_level = "normal"
    overdue_task.finish_deadline_at = now - timedelta(minutes=6)
    overdue_task.latest_note = None
    overdue_task.work_order_id = "wo-1"
    work_order = SimpleNamespace(
        id="wo-1",
        incident_id=None,
        assigned_to=overdue_task.assigned_to,
        assigned_at=overdue_task.assigned_at,
        accepted_at=overdue_task.accepted_at,
        arrived_at=overdue_task.arrived_at,
        processing_started_at=overdue_task.processing_started_at,
        updated_at=now,
        dispatch_blocked_reason=None,
    )
    db = SimpleNamespace(
        add=MagicMock(),
        execute=AsyncMock(side_effect=[
            _ScalarResult([overdue_task]),
            _ScalarResult([work_order]),
        ]),
    )

    monkeypatch.setattr(dispatch_service, "record_dispatch_event", AsyncMock())
    monkeypatch.setattr(dispatch_service, "_sync_incident_dispatch_projection", AsyncMock())
    monkeypatch.setattr(dispatch_service, "create_or_reopen_takeover_hall_entry", AsyncMock())
    monkeypatch.setattr(dispatch_service, "close_open_hall_entries_for_dispatch", AsyncMock())

    await dispatch_service.scan_dispatch_sla_states(db, now=now)

    dispatch_service.create_or_reopen_takeover_hall_entry.assert_awaited_once()
    dispatch_service.close_open_hall_entries_for_dispatch.assert_not_awaited()


@pytest.mark.asyncio
async def test_scan_dispatch_sla_states_closes_takeover_hall_entry_after_recovery(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services import dispatch_service

    now = datetime.now(timezone.utc)
    recovered_task = _make_dispatch_task(dispatch_id="dispatch-recovered", dispatch_status="accepted")
    recovered_task.timeout_level = "overdue"
    recovered_task.arrive_deadline_at = now + timedelta(minutes=50)
    recovered_task.latest_note = None
    recovered_task.work_order_id = "wo-1"
    work_order = SimpleNamespace(
        id="wo-1",
        incident_id=None,
        assigned_to=recovered_task.assigned_to,
        assigned_at=recovered_task.assigned_at,
        accepted_at=recovered_task.accepted_at,
        arrived_at=recovered_task.arrived_at,
        processing_started_at=recovered_task.processing_started_at,
        updated_at=now,
        dispatch_blocked_reason=None,
    )
    db = SimpleNamespace(
        add=MagicMock(),
        execute=AsyncMock(side_effect=[
            _ScalarResult([recovered_task]),
            _ScalarResult([work_order]),
        ]),
    )

    monkeypatch.setattr(dispatch_service, "record_dispatch_event", AsyncMock())
    monkeypatch.setattr(dispatch_service, "_sync_incident_dispatch_projection", AsyncMock())
    monkeypatch.setattr(dispatch_service, "create_or_reopen_takeover_hall_entry", AsyncMock())
    monkeypatch.setattr(dispatch_service, "close_open_hall_entries_for_dispatch", AsyncMock())

    await dispatch_service.scan_dispatch_sla_states(db, now=now)

    dispatch_service.close_open_hall_entries_for_dispatch.assert_awaited_once()
    dispatch_service.create_or_reopen_takeover_hall_entry.assert_not_awaited()


@pytest.mark.asyncio
async def test_scan_dispatch_sla_states_executes_phase1_auto_reassign_on_assigned_overdue(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services import dispatch_service
    from app.services import work_order_service

    now = datetime.now(timezone.utc)
    overdue_task = _make_dispatch_task(dispatch_id="dispatch-overdue", dispatch_status="assigned")
    overdue_task.timeout_level = "normal"
    overdue_task.accept_deadline_at = now - timedelta(minutes=3)
    overdue_task.latest_note = None
    overdue_task.work_order_id = "wo-1"
    work_order = _make_work_order()
    work_order.id = "wo-1"
    work_order.assigned_to = overdue_task.assigned_to
    work_order.assigned_at = overdue_task.assigned_at
    work_order.accepted_at = overdue_task.accepted_at
    work_order.arrived_at = overdue_task.arrived_at
    work_order.processing_started_at = overdue_task.processing_started_at
    work_order.updated_at = now
    assignee = _make_user("ops-1", "张工")
    db = SimpleNamespace(
        add=MagicMock(),
        execute=AsyncMock(side_effect=[
            _ScalarResult([overdue_task]),
            _ScalarResult([work_order]),
            _ScalarResult([assignee]),
        ]),
    )

    monkeypatch.setattr(dispatch_service.settings, "ENABLE_AUTO_REASSIGN_EXECUTION", True)
    monkeypatch.setattr(dispatch_service.settings, "ENABLE_AUTO_REASSIGN_PHASE1_TRIGGER", True)
    monkeypatch.setattr(dispatch_service.settings, "ENABLE_AUTO_REASSIGN_SHADOW_MODE", False)
    monkeypatch.setattr(dispatch_service.settings, "AUTO_REASSIGN_TRIGGER_ASSIGNED_OVERDUE", True)
    monkeypatch.setattr(dispatch_service.settings, "AUTO_REASSIGN_TRIGGER_ACCEPTED_OVERDUE", False)
    monkeypatch.setattr(dispatch_service.settings, "AUTO_REASSIGN_TRIGGER_ASSIGNEE_UNAVAILABLE", False)
    monkeypatch.setattr(dispatch_service, "record_dispatch_event", AsyncMock())
    monkeypatch.setattr(dispatch_service, "_sync_incident_dispatch_projection", AsyncMock())
    monkeypatch.setattr(dispatch_service, "create_or_reopen_takeover_hall_entry", AsyncMock())
    monkeypatch.setattr(dispatch_service, "close_open_hall_entries_for_dispatch", AsyncMock())
    mock_prepare_context = AsyncMock(
        return_value={
            "workers": [SimpleNamespace(id="ops-2", username="李工")],
            "active_counts": {"ops-2": 1},
        }
    )
    monkeypatch.setattr(work_order_service, "prepare_dispatch_candidate_context", mock_prepare_context)
    mock_attempt = AsyncMock(return_value=({"action_taken": True, "dispatch_id": "dispatch-2"}, None))
    monkeypatch.setattr(dispatch_service, "_attempt_phase_one_auto_reassign", mock_attempt)

    summary = await dispatch_service.scan_dispatch_sla_states(db, now=now)

    assert summary["auto_reassign_triggers"] == 1
    assert summary["auto_reassign_executed"] == 1
    assert summary["auto_reassign_hall_fallbacks"] == 0
    assert mock_attempt.await_args.kwargs["trigger"]["reason"] == "assigned_overdue"
    assert mock_attempt.await_args.kwargs["dispatch_workers"] == [SimpleNamespace(id="ops-2", username="李工")]
    assert mock_attempt.await_args.kwargs["dispatch_active_counts"] == {"ops-2": 1}
    mock_prepare_context.assert_awaited_once()
    dispatch_service.create_or_reopen_takeover_hall_entry.assert_not_awaited()


@pytest.mark.asyncio
async def test_attempt_phase_one_auto_reassign_skips_live_execution_outside_rollout_and_opens_hall(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services import dispatch_service

    work_order = _make_work_order()
    work_order.id = "wo-1"
    dispatch_task = _make_dispatch_task(dispatch_id="dispatch-1", dispatch_status="assigned")
    dispatch_task.timeout_level = "warning"
    hall_entry = SimpleNamespace(id="hall-1")

    monkeypatch.setattr(
        dispatch_service,
        "_build_phase_one_auto_reassign_rollout_gate",
        lambda work_order: {
            "allowed": False,
            "blockers": [{"reason": "reassign_rollout_building_not_allowed", "label": "当前楼宇不在自动重派灰度范围内"}],
        },
    )
    mock_audit = AsyncMock()
    mock_hall = AsyncMock(return_value=hall_entry)
    monkeypatch.setattr(dispatch_service, "write_work_order_audit_log", mock_audit)
    monkeypatch.setattr(dispatch_service, "create_or_reopen_takeover_hall_entry", mock_hall)

    result, created_hall_entry = await dispatch_service._attempt_phase_one_auto_reassign(
        SimpleNamespace(),
        work_order=work_order,
        dispatch_task=dispatch_task,
        trigger={
            "reason": "assignee_unavailable",
            "label": "当前责任人客观不可用",
            "create_hall_fallback": True,
        },
    )

    assert result["action_taken"] is False
    assert result["reason"] == "auto_reassign_rollout_filtered"
    assert created_hall_entry is hall_entry
    assert mock_audit.await_args.kwargs["action"] == "auto_reassign_rollout_skipped"
    mock_hall.assert_awaited_once()


@pytest.mark.asyncio
async def test_scan_dispatch_sla_states_records_shadow_evaluation_without_live_execution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services import dispatch_service
    from app.services import work_order_service

    now = datetime.now(timezone.utc)
    overdue_task = _make_dispatch_task(dispatch_id="dispatch-shadow", dispatch_status="assigned")
    overdue_task.timeout_level = "normal"
    overdue_task.accept_deadline_at = now - timedelta(minutes=4)
    overdue_task.latest_note = None
    overdue_task.work_order_id = "wo-1"
    work_order = _make_work_order()
    work_order.id = "wo-1"
    assignee = _make_user("ops-1", "张工")
    db = SimpleNamespace(
        add=MagicMock(),
        execute=AsyncMock(side_effect=[
            _ScalarResult([overdue_task]),
            _ScalarResult([work_order]),
            _ScalarResult([assignee]),
        ]),
    )

    monkeypatch.setattr(dispatch_service.settings, "ENABLE_AUTO_REASSIGN_EXECUTION", False)
    monkeypatch.setattr(dispatch_service.settings, "ENABLE_AUTO_REASSIGN_PHASE1_TRIGGER", True)
    monkeypatch.setattr(dispatch_service.settings, "ENABLE_AUTO_REASSIGN_SHADOW_MODE", True)
    monkeypatch.setattr(dispatch_service.settings, "AUTO_REASSIGN_TRIGGER_ASSIGNED_OVERDUE", True)
    monkeypatch.setattr(dispatch_service.settings, "AUTO_REASSIGN_TRIGGER_ACCEPTED_OVERDUE", False)
    monkeypatch.setattr(dispatch_service.settings, "AUTO_REASSIGN_TRIGGER_ASSIGNEE_UNAVAILABLE", False)
    monkeypatch.setattr(dispatch_service, "record_dispatch_event", AsyncMock())
    monkeypatch.setattr(dispatch_service, "_sync_incident_dispatch_projection", AsyncMock())
    monkeypatch.setattr(dispatch_service, "create_or_reopen_takeover_hall_entry", AsyncMock(return_value=SimpleNamespace(id="hall-1")))
    monkeypatch.setattr(dispatch_service, "close_open_hall_entries_for_dispatch", AsyncMock())
    mock_prepare_context = AsyncMock(
        return_value={
            "workers": [SimpleNamespace(id="ops-2", username="李工")],
            "active_counts": {"ops-2": 1},
        }
    )
    monkeypatch.setattr(work_order_service, "prepare_dispatch_candidate_context", mock_prepare_context)
    mock_shadow = AsyncMock(
        return_value={
            "logged": True,
            "evaluation": {"eligible": True, "apply_payload": {"assigned_to": "ops-2"}},
            "would_execute": True,
            "would_hall_fallback": False,
        }
    )
    monkeypatch.setattr(dispatch_service, "_record_phase_one_auto_reassign_shadow", mock_shadow)
    mock_attempt = AsyncMock()
    monkeypatch.setattr(dispatch_service, "_attempt_phase_one_auto_reassign", mock_attempt)

    summary = await dispatch_service.scan_dispatch_sla_states(db, now=now)

    assert summary["auto_reassign_triggers"] == 1
    assert summary["auto_reassign_executed"] == 0
    assert summary["auto_reassign_shadow_evaluated"] == 1
    assert summary["auto_reassign_shadow_would_execute"] == 1
    assert summary["auto_reassign_shadow_would_hall_fallbacks"] == 0
    mock_shadow.assert_awaited_once()
    assert mock_shadow.await_args.kwargs["dispatch_workers"] == [SimpleNamespace(id="ops-2", username="李工")]
    assert mock_shadow.await_args.kwargs["dispatch_active_counts"] == {"ops-2": 1}
    mock_prepare_context.assert_awaited_once()
    mock_attempt.assert_not_awaited()
    dispatch_service.create_or_reopen_takeover_hall_entry.assert_awaited_once()


@pytest.mark.asyncio
async def test_scan_dispatch_sla_states_does_not_auto_reassign_accepted_overdue_without_prior_reminders(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services import dispatch_service

    now = datetime.now(timezone.utc)
    overdue_task = _make_dispatch_task(dispatch_id="dispatch-overdue", dispatch_status="accepted")
    overdue_task.timeout_level = "normal"
    overdue_task.arrive_deadline_at = now - timedelta(minutes=5)
    overdue_task.reminder_count = 0
    overdue_task.latest_note = None
    overdue_task.work_order_id = "wo-1"
    work_order = _make_work_order()
    work_order.id = "wo-1"
    work_order.assigned_to = overdue_task.assigned_to
    work_order.assigned_at = overdue_task.assigned_at
    work_order.accepted_at = overdue_task.accepted_at
    work_order.arrived_at = overdue_task.arrived_at
    work_order.processing_started_at = overdue_task.processing_started_at
    work_order.updated_at = now
    assignee = _make_user("ops-1", "张工")
    db = SimpleNamespace(
        add=MagicMock(),
        execute=AsyncMock(side_effect=[
            _ScalarResult([overdue_task]),
            _ScalarResult([work_order]),
            _ScalarResult([assignee]),
        ]),
    )

    monkeypatch.setattr(dispatch_service.settings, "ENABLE_AUTO_REASSIGN_EXECUTION", True)
    monkeypatch.setattr(dispatch_service.settings, "ENABLE_AUTO_REASSIGN_PHASE1_TRIGGER", True)
    monkeypatch.setattr(dispatch_service.settings, "AUTO_REASSIGN_TRIGGER_ASSIGNED_OVERDUE", False)
    monkeypatch.setattr(dispatch_service.settings, "AUTO_REASSIGN_TRIGGER_ACCEPTED_OVERDUE", True)
    monkeypatch.setattr(dispatch_service.settings, "AUTO_REASSIGN_ACCEPTED_MIN_PREVIOUS_REMINDERS", 1)
    monkeypatch.setattr(dispatch_service.settings, "AUTO_REASSIGN_TRIGGER_ASSIGNEE_UNAVAILABLE", False)
    monkeypatch.setattr(dispatch_service, "record_dispatch_event", AsyncMock())
    monkeypatch.setattr(dispatch_service, "_sync_incident_dispatch_projection", AsyncMock())
    monkeypatch.setattr(dispatch_service, "create_or_reopen_takeover_hall_entry", AsyncMock())
    monkeypatch.setattr(dispatch_service, "close_open_hall_entries_for_dispatch", AsyncMock())
    mock_attempt = AsyncMock(return_value=({"action_taken": True, "dispatch_id": "dispatch-2"}, None))
    monkeypatch.setattr(dispatch_service, "_attempt_phase_one_auto_reassign", mock_attempt)

    summary = await dispatch_service.scan_dispatch_sla_states(db, now=now)

    assert summary["auto_reassign_triggers"] == 0
    assert summary["auto_reassign_executed"] == 0
    mock_attempt.assert_not_awaited()
    dispatch_service.create_or_reopen_takeover_hall_entry.assert_awaited_once()


@pytest.mark.asyncio
async def test_scan_dispatch_sla_states_triggers_phase1_auto_reassign_when_assignee_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services import dispatch_service
    from app.services import work_order_service

    now = datetime.now(timezone.utc)
    dispatch_task = _make_dispatch_task(dispatch_id="dispatch-unavailable", dispatch_status="assigned")
    dispatch_task.timeout_level = "normal"
    dispatch_task.accept_deadline_at = now + timedelta(minutes=40)
    dispatch_task.work_order_id = "wo-1"
    work_order = _make_work_order()
    work_order.id = "wo-1"
    work_order.assigned_to = dispatch_task.assigned_to
    work_order.assigned_at = dispatch_task.assigned_at
    work_order.accepted_at = dispatch_task.accepted_at
    work_order.arrived_at = dispatch_task.arrived_at
    work_order.processing_started_at = dispatch_task.processing_started_at
    work_order.updated_at = now
    assignee = _make_user("ops-1", "张工")
    assignee.is_active = False
    db = SimpleNamespace(
        add=MagicMock(),
        execute=AsyncMock(side_effect=[
            _ScalarResult([dispatch_task]),
            _ScalarResult([work_order]),
            _ScalarResult([assignee]),
        ]),
    )

    monkeypatch.setattr(dispatch_service.settings, "ENABLE_AUTO_REASSIGN_EXECUTION", True)
    monkeypatch.setattr(dispatch_service.settings, "ENABLE_AUTO_REASSIGN_PHASE1_TRIGGER", True)
    monkeypatch.setattr(dispatch_service.settings, "ENABLE_AUTO_REASSIGN_SHADOW_MODE", False)
    monkeypatch.setattr(dispatch_service.settings, "AUTO_REASSIGN_TRIGGER_ASSIGNED_OVERDUE", False)
    monkeypatch.setattr(dispatch_service.settings, "AUTO_REASSIGN_TRIGGER_ACCEPTED_OVERDUE", False)
    monkeypatch.setattr(dispatch_service.settings, "AUTO_REASSIGN_TRIGGER_ASSIGNEE_UNAVAILABLE", True)
    monkeypatch.setattr(dispatch_service, "record_dispatch_event", AsyncMock())
    monkeypatch.setattr(dispatch_service, "_sync_incident_dispatch_projection", AsyncMock())
    monkeypatch.setattr(dispatch_service, "create_or_reopen_takeover_hall_entry", AsyncMock())
    monkeypatch.setattr(dispatch_service, "close_open_hall_entries_for_dispatch", AsyncMock())
    mock_prepare_context = AsyncMock(
        return_value={
            "workers": [SimpleNamespace(id="ops-2", username="李工")],
            "active_counts": {"ops-2": 1},
        }
    )
    monkeypatch.setattr(work_order_service, "prepare_dispatch_candidate_context", mock_prepare_context)
    mock_attempt = AsyncMock(
        return_value=(
            {"action_taken": False, "reason": "auto_reassign_not_eligible"},
            SimpleNamespace(id="hall-1"),
        )
    )
    monkeypatch.setattr(dispatch_service, "_attempt_phase_one_auto_reassign", mock_attempt)

    summary = await dispatch_service.scan_dispatch_sla_states(db, now=now)

    assert summary["updated"] == 1
    assert summary["auto_reassign_triggers"] == 1
    assert summary["auto_reassign_executed"] == 0
    assert summary["auto_reassign_hall_fallbacks"] == 1
    assert mock_attempt.await_args.kwargs["trigger"]["reason"] == "assignee_unavailable"
    assert mock_attempt.await_args.kwargs["dispatch_workers"] == [SimpleNamespace(id="ops-2", username="李工")]
    assert mock_attempt.await_args.kwargs["dispatch_active_counts"] == {"ops-2": 1}
    mock_prepare_context.assert_awaited_once()
    dispatch_service.record_dispatch_event.assert_not_awaited()
