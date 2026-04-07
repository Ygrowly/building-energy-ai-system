from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from app.api import routes_dispatch_hall


def _make_user(user_id: str, username: str, role: str = "ops"):
    return SimpleNamespace(
        id=user_id,
        username=username,
        role=role,
        is_active=True,
        phone="13800000000",
        worker_profile=SimpleNamespace(
            team=SimpleNamespace(id="team-1", name="暖通班"),
            team_id="team-1",
            skill_links=[],
        ),
    )


def _make_hall_entry(
    *,
    entry_id: str = "hall-1",
    entry_type: str = "support_request",
    status: str = "open",
    assigned_to: str | None = None,
):
    now = datetime.now(timezone.utc)
    return SimpleNamespace(
        id=entry_id,
        work_order_id="wo-1",
        incident_id="incident-1",
        source_dispatch_id="dispatch-1",
        entry_type=entry_type,
        status=status,
        visibility_scope="all_ops",
        target_team_ids_json=None,
        target_skill_tags_json=None,
        target_user_ids_json=None,
        reason="等待支援",
        support_reason="需要暖通班协同",
        sla_stage="waiting_support",
        overdue_level=None,
        allow_direct_claim=False,
        assigned_to=assigned_to,
        assigned_team_id="team-1" if assigned_to else None,
        assigned_by="manager-1" if assigned_to else None,
        created_by="ops-1",
        expired_at=None,
        assigned_at=now - timedelta(minutes=5) if assigned_to else None,
        closed_at=None,
        created_at=now - timedelta(minutes=10),
        updated_at=now - timedelta(minutes=2),
    )


def _make_application(
    *,
    application_id: str = "app-1",
    hall_entry_id: str = "hall-1",
    applicant_user_id: str = "ops-2",
    application_type: str = "support",
):
    now = datetime.now(timezone.utc)
    return SimpleNamespace(
        id=application_id,
        hall_entry_id=hall_entry_id,
        applicant_user_id=applicant_user_id,
        application_type=application_type,
        status="pending",
        note="我可以处理",
        handle_note=None,
        handled_by=None,
        handled_at=None,
        created_at=now - timedelta(minutes=3),
        updated_at=now - timedelta(minutes=3),
    )


def _make_dispatch_task(dispatch_id: str = "dispatch-2", assigned_to: str = "ops-2"):
    now = datetime.now(timezone.utc)
    return SimpleNamespace(
        id=dispatch_id,
        work_order_id="wo-1",
        incident_id="incident-1",
        attempt_no=2,
        is_current=True,
        dispatch_mode="hall_takeover",
        dispatch_status="assigned",
        assigned_team_id="team-1",
        assigned_to=assigned_to,
        assigned_by="manager-1",
        selection_reason="超时接管",
        candidate_snapshot_json=None,
        dispatch_profile_snapshot_json=None,
        worker_result=None,
        reject_reason=None,
        cancel_reason=None,
        support_reason=None,
        support_team_id=None,
        transfer_from_dispatch_id="dispatch-1",
        assigned_at=now,
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
        latest_note="已完成接管派工",
        created_at=now,
        updated_at=now,
    )


@pytest.mark.asyncio
async def test_list_dispatch_hall_entries_endpoint_uses_viewer_scope(monkeypatch: pytest.MonkeyPatch) -> None:
    entry = _make_hall_entry()
    viewer = _make_user("ops-1", "张工")

    monkeypatch.setattr(routes_dispatch_hall, "_resolve_viewer_context", AsyncMock(return_value=viewer))
    monkeypatch.setattr(
        routes_dispatch_hall,
        "list_dispatch_hall_entries",
        AsyncMock(return_value=([entry], 1)),
    )
    monkeypatch.setattr(
        routes_dispatch_hall,
        "_serialize_hall_entries",
        AsyncMock(return_value=[{"id": entry.id, "entry_type": entry.entry_type}]),
    )

    response = await routes_dispatch_hall.list_dispatch_hall_entries_endpoint(
        status="open",
        entry_type="support_request",
        assigned_to=None,
        work_order_id=None,
        incident_id=None,
        source_dispatch_id=None,
        include_applications=False,
        page=1,
        page_size=20,
        db=SimpleNamespace(),
        user=SimpleNamespace(id="ops-1", role="ops"),
    )

    assert response["total"] == 1
    assert response["hall_entries"][0]["id"] == "hall-1"
    assert routes_dispatch_hall.list_dispatch_hall_entries.await_args.kwargs["viewer"] == viewer


@pytest.mark.asyncio
async def test_get_dispatch_hall_entry_detail_rejects_invisible_ops(monkeypatch: pytest.MonkeyPatch) -> None:
    entry = _make_hall_entry()
    viewer = _make_user("ops-1", "张工")

    monkeypatch.setattr(routes_dispatch_hall, "_resolve_viewer_context", AsyncMock(return_value=viewer))
    monkeypatch.setattr(routes_dispatch_hall, "get_dispatch_hall_entry_by_id", AsyncMock(return_value=entry))
    monkeypatch.setattr(routes_dispatch_hall, "can_view_dispatch_hall_entry", lambda *_args, **_kwargs: False)

    with pytest.raises(HTTPException) as exc_info:
        await routes_dispatch_hall.get_dispatch_hall_entry_detail(
            entry_id=entry.id,
            db=SimpleNamespace(),
            user=SimpleNamespace(id="ops-1", role="ops"),
        )

    assert exc_info.value.status_code == 403


@pytest.mark.asyncio
async def test_apply_support_dispatch_hall_entry_creates_application(monkeypatch: pytest.MonkeyPatch) -> None:
    entry = _make_hall_entry(entry_type="support_request")
    application = _make_application(application_type="support")
    db = SimpleNamespace(commit=AsyncMock())

    monkeypatch.setattr(routes_dispatch_hall, "_resolve_viewer_context", AsyncMock(return_value=_make_user("ops-1", "张工")))
    monkeypatch.setattr(routes_dispatch_hall, "get_dispatch_hall_entry_by_id", AsyncMock(return_value=entry))
    monkeypatch.setattr(routes_dispatch_hall, "can_view_dispatch_hall_entry", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(routes_dispatch_hall, "apply_to_dispatch_hall_entry", AsyncMock(return_value=application))
    monkeypatch.setattr(routes_dispatch_hall, "_load_work_order", AsyncMock(return_value=SimpleNamespace(id="wo-1", status="dispatched")))
    monkeypatch.setattr(routes_dispatch_hall, "_write_audit_log", AsyncMock())
    monkeypatch.setattr(routes_dispatch_hall, "_invalidate_related_cache", AsyncMock())

    response = await routes_dispatch_hall.apply_support_dispatch_hall_entry(
        entry_id=entry.id,
        req=routes_dispatch_hall.HallApplyRequest(note="我可以协同处理"),
        db=db,
        user=SimpleNamespace(id="ops-1", role="ops"),
    )

    assert response["application_id"] == "app-1"
    assert response["message"] == "已提交协同申请"
    db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_apply_takeover_dispatch_hall_entry_maps_value_error_to_conflict(monkeypatch: pytest.MonkeyPatch) -> None:
    entry = _make_hall_entry(entry_type="support_request")

    monkeypatch.setattr(routes_dispatch_hall, "_resolve_viewer_context", AsyncMock(return_value=_make_user("ops-1", "张工")))
    monkeypatch.setattr(routes_dispatch_hall, "get_dispatch_hall_entry_by_id", AsyncMock(return_value=entry))
    monkeypatch.setattr(routes_dispatch_hall, "can_view_dispatch_hall_entry", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(
        routes_dispatch_hall,
        "apply_to_dispatch_hall_entry",
        AsyncMock(side_effect=ValueError("当前共享工单类型与申请动作不匹配")),
    )

    with pytest.raises(HTTPException) as exc_info:
        await routes_dispatch_hall.apply_takeover_dispatch_hall_entry(
            entry_id=entry.id,
            req=routes_dispatch_hall.HallApplyRequest(note="我来接管"),
            db=SimpleNamespace(),
            user=SimpleNamespace(id="ops-1", role="ops"),
        )

    assert exc_info.value.status_code == 409


@pytest.mark.asyncio
async def test_assign_support_dispatch_hall_entry_returns_serialized_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    entry = _make_hall_entry(entry_type="support_request")
    application = _make_application(application_type="support")
    assigned_user = _make_user("ops-2", "李工")
    dispatch_task = _make_dispatch_task()
    db = SimpleNamespace(commit=AsyncMock())

    monkeypatch.setattr(routes_dispatch_hall, "get_dispatch_hall_entry_by_id", AsyncMock(return_value=entry))
    monkeypatch.setattr(routes_dispatch_hall, "_load_user_with_worker_context", AsyncMock(return_value=assigned_user))
    monkeypatch.setattr(routes_dispatch_hall, "get_dispatch_hall_application_by_id", AsyncMock(return_value=application))
    monkeypatch.setattr(routes_dispatch_hall, "assign_support_hall_entry", AsyncMock(return_value=entry))
    monkeypatch.setattr(routes_dispatch_hall, "_load_work_order", AsyncMock(return_value=SimpleNamespace(id="wo-1", status="dispatched")))
    monkeypatch.setattr(routes_dispatch_hall, "get_dispatch_task_by_id", AsyncMock(return_value=dispatch_task))
    monkeypatch.setattr(routes_dispatch_hall, "record_dispatch_event", AsyncMock())
    monkeypatch.setattr(routes_dispatch_hall, "_write_audit_log", AsyncMock())
    monkeypatch.setattr(routes_dispatch_hall, "_invalidate_related_cache", AsyncMock())
    monkeypatch.setattr(
        routes_dispatch_hall,
        "_serialize_hall_entries",
        AsyncMock(return_value=[{"id": entry.id, "applications": [{"id": application.id}]}]),
    )

    response = await routes_dispatch_hall.assign_support_dispatch_hall_entry_endpoint(
        entry_id=entry.id,
        req=routes_dispatch_hall.HallAssignSupportRequest(
            assigned_to="ops-2",
            application_id=application.id,
            note="优先由李工支援",
        ),
        db=db,
        user=SimpleNamespace(id="manager-1", role="manager"),
    )

    assert response["message"] == "已指派协同给 李工"
    assert response["hall_entry"]["id"] == "hall-1"
    routes_dispatch_hall.record_dispatch_event.assert_awaited_once()
    db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_assign_takeover_dispatch_hall_entry_returns_new_dispatch(monkeypatch: pytest.MonkeyPatch) -> None:
    entry = _make_hall_entry(entry_type="takeover_candidate")
    application = _make_application(application_type="takeover")
    assigned_user = _make_user("ops-2", "李工")
    source_dispatch = _make_dispatch_task(dispatch_id="dispatch-1", assigned_to="ops-1")
    new_dispatch = _make_dispatch_task(dispatch_id="dispatch-2", assigned_to="ops-2")
    db = SimpleNamespace(commit=AsyncMock())

    monkeypatch.setattr(routes_dispatch_hall, "get_dispatch_hall_entry_by_id", AsyncMock(return_value=entry))
    monkeypatch.setattr(routes_dispatch_hall, "_load_user_with_worker_context", AsyncMock(return_value=assigned_user))
    monkeypatch.setattr(routes_dispatch_hall, "get_dispatch_hall_application_by_id", AsyncMock(return_value=application))
    monkeypatch.setattr(routes_dispatch_hall, "_load_work_order", AsyncMock(return_value=SimpleNamespace(id="wo-1", status="dispatched")))
    monkeypatch.setattr(routes_dispatch_hall, "get_dispatch_task_by_id", AsyncMock(return_value=source_dispatch))
    monkeypatch.setattr(routes_dispatch_hall, "reassign_dispatch_task", AsyncMock(return_value=new_dispatch))
    monkeypatch.setattr(routes_dispatch_hall, "approve_dispatch_hall_application", AsyncMock(return_value=application))
    monkeypatch.setattr(routes_dispatch_hall, "close_dispatch_hall_entry", AsyncMock(return_value=entry))
    monkeypatch.setattr(routes_dispatch_hall, "_write_audit_log", AsyncMock())
    monkeypatch.setattr(routes_dispatch_hall, "_invalidate_related_cache", AsyncMock())
    monkeypatch.setattr(
        routes_dispatch_hall,
        "_serialize_hall_entries",
        AsyncMock(return_value=[{"id": entry.id, "status": "closed"}]),
    )

    response = await routes_dispatch_hall.assign_takeover_dispatch_hall_entry_endpoint(
        entry_id=entry.id,
        req=routes_dispatch_hall.HallAssignTakeoverRequest(
            assigned_to="ops-2",
            application_id=application.id,
            reason="当前派工超时，改由李工接管",
        ),
        db=db,
        user=SimpleNamespace(id="manager-1", role="manager"),
    )

    assert response["message"] == "已将接管任务正式派给 李工"
    assert response["hall_entry"]["status"] == "closed"
    assert response["dispatch"]["id"] == "dispatch-2"
    routes_dispatch_hall.reassign_dispatch_task.assert_awaited_once_with(
        db,
        work_order=routes_dispatch_hall._load_work_order.return_value,
        dispatch_task=source_dispatch,
        assigned_user=assigned_user,
        actor_type="admin",
        actor_id="manager-1",
        reason="当前派工超时，改由李工接管",
        dispatch_mode="hall_takeover",
        close_related_hall_entries=False,
    )
    db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_accept_support_dispatch_hall_entry_updates_assigned_support(monkeypatch: pytest.MonkeyPatch) -> None:
    entry = _make_hall_entry(entry_type="support_request", status="assigned", assigned_to="ops-1")
    source_dispatch = _make_dispatch_task(dispatch_id="dispatch-1", assigned_to="ops-main")
    db = SimpleNamespace(commit=AsyncMock())

    monkeypatch.setattr(routes_dispatch_hall, "get_dispatch_hall_entry_by_id", AsyncMock(return_value=entry))
    monkeypatch.setattr(routes_dispatch_hall, "accept_assigned_support_hall_entry", AsyncMock(return_value=entry))
    monkeypatch.setattr(routes_dispatch_hall, "_load_work_order", AsyncMock(return_value=SimpleNamespace(id="wo-1", status="dispatched")))
    monkeypatch.setattr(routes_dispatch_hall, "get_dispatch_task_by_id", AsyncMock(return_value=source_dispatch))
    monkeypatch.setattr(routes_dispatch_hall, "record_dispatch_event", AsyncMock())
    monkeypatch.setattr(routes_dispatch_hall, "_write_audit_log", AsyncMock())
    monkeypatch.setattr(routes_dispatch_hall, "_invalidate_related_cache", AsyncMock())
    monkeypatch.setattr(
        routes_dispatch_hall,
        "_serialize_hall_entries",
        AsyncMock(return_value=[{"id": entry.id, "status": "accepted"}]),
    )

    response = await routes_dispatch_hall.accept_support_dispatch_hall_entry_endpoint(
        entry_id=entry.id,
        req=routes_dispatch_hall.HallWorkerSupportActionRequest(note="我来协同"),
        db=db,
        user=SimpleNamespace(id="ops-1", role="ops"),
    )

    assert response["message"] == "已确认协同任务"
    assert response["hall_entry"]["status"] == "accepted"
    routes_dispatch_hall.record_dispatch_event.assert_awaited_once()
    db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_reject_support_dispatch_hall_entry_reopens_hall_entry(monkeypatch: pytest.MonkeyPatch) -> None:
    entry = _make_hall_entry(entry_type="support_request", status="assigned", assigned_to="ops-1")
    source_dispatch = _make_dispatch_task(dispatch_id="dispatch-1", assigned_to="ops-main")
    db = SimpleNamespace(commit=AsyncMock())

    monkeypatch.setattr(routes_dispatch_hall, "get_dispatch_hall_entry_by_id", AsyncMock(return_value=entry))
    monkeypatch.setattr(routes_dispatch_hall, "reject_assigned_support_hall_entry", AsyncMock(return_value=entry))
    monkeypatch.setattr(routes_dispatch_hall, "_load_work_order", AsyncMock(return_value=SimpleNamespace(id="wo-1", status="dispatched")))
    monkeypatch.setattr(routes_dispatch_hall, "get_dispatch_task_by_id", AsyncMock(return_value=source_dispatch))
    monkeypatch.setattr(routes_dispatch_hall, "record_dispatch_event", AsyncMock())
    monkeypatch.setattr(routes_dispatch_hall, "_write_audit_log", AsyncMock())
    monkeypatch.setattr(routes_dispatch_hall, "_invalidate_related_cache", AsyncMock())
    monkeypatch.setattr(
        routes_dispatch_hall,
        "_serialize_hall_entries",
        AsyncMock(return_value=[{"id": entry.id, "status": "open"}]),
    )

    response = await routes_dispatch_hall.reject_support_dispatch_hall_entry_endpoint(
        entry_id=entry.id,
        req=routes_dispatch_hall.HallWorkerSupportActionRequest(note="当前无法支援"),
        db=db,
        user=SimpleNamespace(id="ops-1", role="ops"),
    )

    assert response["message"] == "已拒绝协同任务，任务已退回共享大厅"
    assert response["hall_entry"]["status"] == "open"
    routes_dispatch_hall.record_dispatch_event.assert_awaited_once()
    db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_withdraw_dispatch_hall_application_endpoint_withdraws_own_application(monkeypatch: pytest.MonkeyPatch) -> None:
    application = _make_application(applicant_user_id="ops-1")
    hall_entry = _make_hall_entry(entry_type="support_request")
    db = SimpleNamespace(commit=AsyncMock())

    monkeypatch.setattr(routes_dispatch_hall, "get_dispatch_hall_application_by_id", AsyncMock(return_value=application))
    monkeypatch.setattr(routes_dispatch_hall, "withdraw_dispatch_hall_application", AsyncMock(return_value=application))
    monkeypatch.setattr(routes_dispatch_hall, "get_dispatch_hall_entry_by_id", AsyncMock(return_value=hall_entry))
    monkeypatch.setattr(routes_dispatch_hall, "_load_work_order", AsyncMock(return_value=SimpleNamespace(id="wo-1", status="dispatched")))
    monkeypatch.setattr(routes_dispatch_hall, "_write_audit_log", AsyncMock())
    monkeypatch.setattr(routes_dispatch_hall, "_invalidate_related_cache", AsyncMock())

    response = await routes_dispatch_hall.withdraw_dispatch_hall_application_endpoint(
        application_id=application.id,
        db=db,
        user=SimpleNamespace(id="ops-1", role="ops"),
    )

    assert response["application_id"] == application.id
    assert response["message"] == "已撤回申请"
    routes_dispatch_hall.withdraw_dispatch_hall_application.assert_awaited_once()
    db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_reject_dispatch_hall_application_endpoint_writes_audit(monkeypatch: pytest.MonkeyPatch) -> None:
    application = _make_application(applicant_user_id="ops-2")
    hall_entry = _make_hall_entry(entry_type="takeover_candidate")
    work_order = SimpleNamespace(id="wo-1", status="dispatched")
    db = SimpleNamespace(commit=AsyncMock())

    monkeypatch.setattr(routes_dispatch_hall, "get_dispatch_hall_application_by_id", AsyncMock(return_value=application))
    monkeypatch.setattr(routes_dispatch_hall, "reject_dispatch_hall_application", AsyncMock(return_value=application))
    monkeypatch.setattr(routes_dispatch_hall, "get_dispatch_hall_entry_by_id", AsyncMock(return_value=hall_entry))
    monkeypatch.setattr(routes_dispatch_hall, "_load_work_order", AsyncMock(return_value=work_order))
    monkeypatch.setattr(routes_dispatch_hall, "_write_audit_log", AsyncMock())
    monkeypatch.setattr(routes_dispatch_hall, "_invalidate_related_cache", AsyncMock())

    response = await routes_dispatch_hall.reject_dispatch_hall_application_endpoint(
        application_id=application.id,
        req=routes_dispatch_hall.HallRejectApplicationRequest(note="当前不适合接管"),
        db=db,
        user=SimpleNamespace(id="manager-1", role="manager"),
    )

    assert response["application_id"] == application.id
    assert response["message"] == "已驳回申请"
    routes_dispatch_hall._write_audit_log.assert_awaited_once()
    audit_kwargs = routes_dispatch_hall._write_audit_log.await_args.kwargs
    assert audit_kwargs["action"] == "dispatch_hall_reject_application"
    assert audit_kwargs["old_status"] == "dispatched"
    assert audit_kwargs["new_status"] == "dispatched"
    assert audit_kwargs["actor_id"] == "manager-1"
    assert audit_kwargs["detail"]["application_id"] == application.id
    assert audit_kwargs["detail"]["applicant_user_id"] == "ops-2"
    assert audit_kwargs["detail"]["note"] == "当前不适合接管"
    db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_withdraw_dispatch_hall_application_endpoint_blocks_other_user(monkeypatch: pytest.MonkeyPatch) -> None:
    application = _make_application(applicant_user_id="ops-9")

    monkeypatch.setattr(routes_dispatch_hall, "get_dispatch_hall_application_by_id", AsyncMock(return_value=application))

    with pytest.raises(HTTPException) as exc_info:
        await routes_dispatch_hall.withdraw_dispatch_hall_application_endpoint(
            application_id=application.id,
            db=SimpleNamespace(),
            user=SimpleNamespace(id="ops-1", role="ops"),
        )

    assert exc_info.value.status_code == 403
