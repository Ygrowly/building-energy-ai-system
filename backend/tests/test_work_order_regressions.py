from __future__ import annotations

import json
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.api import routes_workorder
from app.db.models import WorkOrder, WorkOrderAuditLog
from app.db import session as db_session_module
from app.db.session import _build_connect_args
from app.services.dispatch_service import serialize_dispatch_task
from app.services.work_order_service import (
    assign_work_order,
    build_batch_dispatch_preview,
    create_work_order,
    list_dispatch_candidates,
    list_work_orders,
    serialize_work_order,
    _load_dispatch_active_counts,
)


class DummyAsyncSession:
    def __init__(self) -> None:
        self.added: list[object] = []

    def add(self, obj: object) -> None:
        self.added.append(obj)

    async def flush(self) -> None:
        return None


@pytest.mark.asyncio
async def test_create_work_order_preserves_explicit_ticket_id() -> None:
    db = DummyAsyncSession()

    wo = await create_work_order(
        db,
        ticket_id="temp_abc123",
        building_id="Fox_office_Alice",
        issue_description="test issue",
        suggested_action="test action",
    )

    assert wo.ticket_id == "temp_abc123"
    assert any(isinstance(item, WorkOrder) for item in db.added)
    assert any(isinstance(item, WorkOrderAuditLog) for item in db.added)


@pytest.mark.asyncio
async def test_work_order_list_cache_key_includes_user_and_filters(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, str] = {}

    async def fake_list_work_orders(*args, **kwargs):
        return [], 0

    async def fake_get_or_compute_json(cache_key, ttl_seconds, compute):
        captured["cache_key"] = cache_key
        return await compute()

    monkeypatch.setattr(routes_workorder, "svc_list_work_orders", fake_list_work_orders)
    monkeypatch.setattr(routes_workorder, "get_or_compute_json", fake_get_or_compute_json)

    user = SimpleNamespace(id="ops-user-1", role="ops")
    response = await routes_workorder.list_work_orders_endpoint(
        status="pending_review,dispatched",
        building_id="Fox_office_Alice",
        priority="high",
        ai_fallback=True,
        page=2,
        page_size=10,
        db=SimpleNamespace(),
        user=user,
    )

    assert response["total"] == 0
    assert captured["cache_key"] == (
        "workorders:list:"
        "ops-user-1:"
        "pending_review,dispatched:"
        "Fox_office_Alice:"
        "high:"
        "True:"
        "ops-user-1:"
        "2:10"
    )


@pytest.mark.asyncio
async def test_work_order_list_prefers_current_dispatch_assignee(monkeypatch: pytest.MonkeyPatch) -> None:
    work_order = SimpleNamespace(
        id="wo-1",
        ticket_id="WO-001",
        assigned_to="ops-legacy",
        anomaly_links=[],
    )
    current_dispatch = SimpleNamespace(id="dispatch-1", assigned_to="ops-1")
    assigned_user = SimpleNamespace(id="ops-1", username="张工")

    async def fake_get_or_compute_json(_cache_key, _ttl_seconds, compute):
        return await compute()

    monkeypatch.setattr(routes_workorder, "svc_list_work_orders", AsyncMock(return_value=([work_order], 1)))
    monkeypatch.setattr(
        routes_workorder,
        "load_current_dispatches_by_work_order_ids",
        AsyncMock(return_value={"wo-1": current_dispatch}),
    )
    monkeypatch.setattr(
        routes_workorder,
        "_load_users_by_ids",
        AsyncMock(return_value={"ops-1": assigned_user}),
    )
    monkeypatch.setattr(
        routes_workorder,
        "serialize_work_order",
        lambda wo, *, assigned_user=None, current_dispatch=None, **_kwargs: {
            "ticket_id": wo.ticket_id,
            "assigned_to_name": assigned_user.username if assigned_user else None,
            "dispatch_assigned_to": getattr(current_dispatch, "assigned_to", None),
        },
    )
    monkeypatch.setattr(routes_workorder, "get_or_compute_json", fake_get_or_compute_json)

    response = await routes_workorder.list_work_orders_endpoint(
        status=None,
        building_id=None,
        priority=None,
        ai_fallback=None,
        page=1,
        page_size=20,
        db=SimpleNamespace(),
        user=SimpleNamespace(id="manager-1", role="manager"),
    )

    assert response["total"] == 1
    assert response["work_orders"][0]["assigned_to_name"] == "张工"
    loaded_user_ids = routes_workorder._load_users_by_ids.await_args.args[1]
    assert loaded_user_ids == ["ops-1"]


@pytest.mark.asyncio
async def test_worker_action_checks_current_dispatch_assignee_before_legacy_projection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    work_order = SimpleNamespace(
        id="wo-1",
        ticket_id="WO-001",
        status="dispatched",
        assigned_to="ops-1",
    )
    current_dispatch = SimpleNamespace(id="dispatch-1", assigned_to="ops-2")

    monkeypatch.setattr(routes_workorder, "get_work_order_by_ticket_id", AsyncMock(return_value=work_order))
    monkeypatch.setattr(routes_workorder, "get_current_dispatch_task", AsyncMock(return_value=current_dispatch))

    with pytest.raises(Exception) as exc_info:
        await routes_workorder.worker_action(
            ticket_id="WO-001",
            req=routes_workorder.WorkerActionRequest(action="accept"),
            db=SimpleNamespace(),
            user=SimpleNamespace(id="ops-1", role="ops"),
        )

    assert getattr(exc_info.value, "status_code", None) == 403


@pytest.mark.asyncio
async def test_worker_feedback_allows_current_dispatch_assignee_when_legacy_projection_is_stale(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    work_order = SimpleNamespace(
        id="wo-1",
        ticket_id="WO-001",
        status="dispatched",
        assigned_to="ops-legacy",
        worker_result=None,
        worker_notes=None,
        worker_feedback_at=None,
    )
    current_dispatch = SimpleNamespace(id="dispatch-1", assigned_to="ops-2")
    db = SimpleNamespace(commit=AsyncMock())

    async def _fake_transition(*_args, **kwargs):
        work_order.status = kwargs["new_status"]

    monkeypatch.setattr(routes_workorder, "get_work_order_by_ticket_id", AsyncMock(return_value=work_order))
    monkeypatch.setattr(routes_workorder, "get_current_dispatch_task", AsyncMock(return_value=current_dispatch))
    monkeypatch.setattr(routes_workorder, "complete_dispatch_task", AsyncMock(return_value=current_dispatch))
    monkeypatch.setattr(routes_workorder, "transition_status", AsyncMock(side_effect=_fake_transition))
    monkeypatch.setattr(routes_workorder, "_invalidate_related_cache", AsyncMock())

    response = await routes_workorder.worker_feedback(
        ticket_id="WO-001",
        req=routes_workorder.WorkerFeedbackRequest(result="fixed", notes="处理完成"),
        db=db,
        user=SimpleNamespace(id="ops-2", role="ops"),
    )

    assert response["status"] == "completed"
    assert work_order.worker_result == "fixed"
    assert routes_workorder.complete_dispatch_task.await_args.kwargs["dispatch_task"] is current_dispatch
    db.commit.assert_awaited_once()


def test_build_connect_args_uses_tls_for_remote_hosts_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(db_session_module._settings, "DATABASE_SSL_MODE", "auto")
    monkeypatch.setattr(db_session_module._settings, "DATABASE_SSL_CA_FILE", "")

    remote_args = _build_connect_args("postgresql+asyncpg://user:pass@db.example.com:5432/app")
    local_args = _build_connect_args("postgresql+asyncpg://user:pass@localhost:5432/app")

    assert "ssl" in remote_args
    assert remote_args["ssl"].verify_mode.name == "CERT_NONE"
    assert "ssl" not in local_args


def test_build_connect_args_supports_verify_full_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(db_session_module._settings, "DATABASE_SSL_MODE", "verify-full")
    monkeypatch.setattr(db_session_module._settings, "DATABASE_SSL_CA_FILE", "")

    remote_args = _build_connect_args("postgresql+asyncpg://user:pass@db.example.com:5432/app")

    assert "ssl" in remote_args
    assert remote_args["ssl"].verify_mode.name == "CERT_REQUIRED"


class _FakeScalarResult:
    def __init__(self, items):
        self._items = items

    def all(self):
        return self._items


class _FakeResult:
    def __init__(self, *, scalars_items=None, rows=None):
        self._scalars_items = scalars_items
        self._rows = rows or []

    def scalars(self):
        return _FakeScalarResult(self._scalars_items or [])

    def all(self):
        return self._rows

    def scalar(self):
        return self._rows[0] if self._rows else 0


class _FakeDispatchDb:
    def __init__(self, results):
        self._results = list(results)

    async def execute(self, _query):
        return self._results.pop(0)


class _CaptureQueryDb:
    def __init__(self, results):
        self._results = list(results)
        self.queries: list[str] = []

    async def execute(self, query):
        self.queries.append(str(query))
        return self._results.pop(0)


@pytest.mark.asyncio
async def test_dispatch_candidates_prioritize_skill_building_and_load() -> None:
    hvac_skill = SimpleNamespace(code="hvac", name="暖通空调")
    inspection_skill = SimpleNamespace(code="inspection", name="现场巡检")
    hvac_link = SimpleNamespace(skill=hvac_skill, proficiency=5, is_primary=True)
    inspection_link = SimpleNamespace(skill=inspection_skill, proficiency=3, is_primary=False)

    best_worker = SimpleNamespace(
        id="ops-1",
        username="张强",
        phone="13800000001",
        role="ops",
        is_active=True,
        worker_profile=SimpleNamespace(
            team=SimpleNamespace(name="暖通班"),
            job_title="暖通工程师",
            shift_status="on_duty",
            dispatch_enabled=True,
            max_active_orders=4,
            accepts_emergency=True,
            service_buildings_json='["B-01"]',
            skill_links=[hvac_link, inspection_link],
        ),
    )
    backup_worker = SimpleNamespace(
        id="ops-2",
        username="李明",
        phone="13800000002",
        role="ops",
        is_active=True,
        worker_profile=SimpleNamespace(
            team=SimpleNamespace(name="综合运维班"),
            job_title="巡检工程师",
            shift_status="standby",
            dispatch_enabled=True,
            max_active_orders=2,
            accepts_emergency=False,
            service_buildings_json='[]',
            skill_links=[inspection_link],
        ),
    )
    db = _FakeDispatchDb([
        _FakeResult(scalars_items=[best_worker, backup_worker]),
        _FakeResult(rows=[("ops-1", 1), ("ops-2", 2)]),
    ])
    work_order = SimpleNamespace(
        building_id="B-01",
        issue_description="空调供回水温度异常，需要现场排查",
        suggested_action="优先安排暖通工程师到场检查",
        priority="high",
        anomaly_links=[],
    )

    payload = await list_dispatch_candidates(db, work_order=work_order)

    assert payload["requirement"]["required_skills"][0] == "hvac"
    assert payload["candidates"][0]["user_id"] == "ops-1"
    assert "负责该楼栋" in payload["candidates"][0]["badges"]
    assert payload["candidates"][0]["score"] > payload["candidates"][1]["score"]


@pytest.mark.asyncio
async def test_list_work_orders_filters_by_current_dispatch_assignee() -> None:
    db = _CaptureQueryDb([
        _FakeResult(rows=[0]),
        _FakeResult(scalars_items=[]),
    ])

    items, total = await list_work_orders(
        db,
        assigned_to="ops-1",
        page=1,
        page_size=20,
    )

    assert items == []
    assert total == 0
    compiled = " ".join(db.queries).lower()
    assert "current_dispatch_id" in compiled
    assert "dispatch_tasks.assigned_to" in compiled
    assert "join dispatch_tasks on work_orders.current_dispatch_id = dispatch_tasks.id" in compiled
    assert "where dispatch_tasks.assigned_to = :assigned_to_1" in compiled


@pytest.mark.asyncio
async def test_load_dispatch_active_counts_uses_current_dispatch_join() -> None:
    db = _CaptureQueryDb([
        _FakeResult(rows=[("ops-1", 2)]),
    ])

    result = await _load_dispatch_active_counts(db, worker_ids=["ops-1"])

    assert result == {"ops-1": 2}
    compiled = db.queries[0].lower()
    assert "work_orders.current_dispatch_id = dispatch_tasks.id" in compiled
    assert "dispatch_tasks.assigned_to" in compiled
    assert "work_orders.assigned_to" not in compiled


def test_serialize_work_order_prefers_current_dispatch_projection_for_top_level_fields() -> None:
    now = datetime.now(timezone.utc)
    work_order = SimpleNamespace(
        id="wo-1",
        ticket_id="WO-001",
        building_id="B-01",
        device_id="dev-1",
        issue_description="异常",
        suggested_action="处理",
        priority="high",
        status="dispatched",
        ai_decision="approved",
        ai_reason="连续异常",
        ai_fallback=False,
        ai_reviewed_at=None,
        worker_result=None,
        worker_notes=None,
        worker_feedback_at=None,
        assigned_to="ops-legacy",
        assigned_at=now,
        accepted_at=None,
        arrived_at=None,
        processing_started_at=None,
        admin_action=None,
        admin_notes=None,
        admin_reviewed_by=None,
        admin_reviewed_at=None,
        created_at=now,
        updated_at=now,
        closed_at=None,
        source="auto",
        session_id=None,
        incident_id="inc-1",
        pending_dispatch_at=None,
        dispatch_profile_json=None,
        dispatch_blocked_reason=None,
        anomaly_links=[],
    )
    current_dispatch = SimpleNamespace(
        id="dispatch-1",
        work_order_id="wo-1",
        incident_id="inc-1",
        assigned_to="ops-current",
        assigned_team_id="team-hvac",
        assigned_by="manager-1",
        selection_reason="推荐派工",
        dispatch_status="accepted",
        dispatch_mode="manual",
        attempt_no=1,
        is_current=True,
        assigned_at=now,
        accepted_at=now,
        accept_deadline_at=None,
        arrive_deadline_at=None,
        finish_deadline_at=None,
        arrived_at=None,
        start_deadline_at=None,
        processing_started_at=None,
        completed_at=None,
        closed_at=None,
        latest_progress_at=now,
        latest_progress_note="已接单",
        latest_note="已接单",
        candidate_snapshot_json=None,
        dispatch_profile_snapshot_json=None,
        worker_result=None,
        reject_reason=None,
        cancel_reason=None,
        support_reason=None,
        support_team_id=None,
        transfer_from_dispatch_id=None,
        reminder_count=0,
        last_reminded_at=None,
        timeout_level="normal",
        created_at=now,
        updated_at=now,
        sla_due_at=None,
    )
    assigned_user = SimpleNamespace(
        id="ops-current",
        username="张工",
        phone="13800000001",
        worker_profile=SimpleNamespace(team=SimpleNamespace(name="暖通班")),
    )

    payload = serialize_work_order(
        work_order,
        assigned_user=assigned_user,
        current_dispatch=current_dispatch,
    )

    assert payload["assigned_to"] == "ops-current"
    assert payload["current_dispatch"]["assigned_to"] == "ops-current"
    assert payload["assigned_to_name"] == "张工"


def test_serialize_dispatch_task_includes_auto_dispatch_review() -> None:
    now = datetime.now(timezone.utc)
    dispatch_task = SimpleNamespace(
        id="dispatch-auto-1",
        work_order_id="wo-1",
        incident_id=None,
        attempt_no=1,
        is_current=True,
        dispatch_mode="auto",
        dispatch_status="assigned",
        assigned_team_id="team-hvac",
        assigned_to="ops-1",
        assigned_by=None,
        selection_reason="自动派工：test2 推荐分 113，领先第二候选人 11 分",
        candidate_snapshot_json=json.dumps({
            "auto_dispatch": True,
            "strategy": "high_confidence_dispatch",
            "confidence": "high",
            "rules": {"min_score": 105, "min_gap": 10, "require_on_duty": True},
            "top_candidate": {
                "user_id": "ops-1",
                "username": "test2",
                "team_name": "暖通班",
                "score": 113,
                "shift_status": "on_duty",
                "current_active_orders": 0,
                "max_active_orders": 6,
                "matched_skill_names": ["暖通"],
                "recommend_reason": "技能贴合，当前值班中",
            },
            "second_candidate": {
                "user_id": "ops-2",
                "username": "ops_plumbing_01",
                "score": 102,
                "shift_status": "on_duty",
                "current_active_orders": 1,
                "max_active_orders": 4,
            },
            "fallback_candidate": None,
            "score_gap": 11,
        }, ensure_ascii=False),
        dispatch_profile_snapshot_json=None,
        worker_result=None,
        reject_reason=None,
        cancel_reason=None,
        support_reason=None,
        support_team_id=None,
        transfer_from_dispatch_id=None,
        assigned_at=now,
        accept_deadline_at=None,
        accepted_at=None,
        arrive_deadline_at=None,
        arrived_at=None,
        start_deadline_at=None,
        processing_started_at=None,
        finish_deadline_at=None,
        completed_at=None,
        closed_at=None,
        reminder_count=0,
        last_reminded_at=None,
        timeout_level="normal",
        latest_note=None,
        created_at=now,
        updated_at=now,
    )
    assigned_user = SimpleNamespace(
        id="ops-1",
        username="test2",
        phone="13800000002",
        worker_profile=SimpleNamespace(team=SimpleNamespace(id="team-hvac", name="暖通班")),
    )

    payload = serialize_dispatch_task(dispatch_task, assigned_user=assigned_user)

    review = payload["auto_dispatch_review"]
    assert review["strategy"] == "high_confidence_dispatch"
    assert review["strategy_label"] == "高置信自动派工"
    assert review["selected_candidate"]["username"] == "test2"
    assert review["selected_candidate"]["shift_label"] == "值班中"
    assert review["score_gap"] == 11
    assert review["rules"]["min_score"] == 105


@pytest.mark.asyncio
async def test_assign_work_order_passes_dispatch_context(monkeypatch: pytest.MonkeyPatch) -> None:
    work_order = SimpleNamespace(
        id="wo-1",
        ticket_id="WO-20260404-001",
        status="pending_dispatch",
        pending_dispatch_at=None,
        dispatch_blocked_reason="等待调度",
        updated_at=None,
        worker_notes=None,
        priority="high",
        building_id="Fox_public_Henry",
        issue_description="空调制冷异常",
        suggested_action="优先安排暖通班到场排查",
    )
    assigned_user = SimpleNamespace(
        id="ops-9",
        username="赵工",
        phone="13800000009",
        worker_profile=SimpleNamespace(team=SimpleNamespace(name="暖通班")),
    )

    mock_create_dispatch_task = AsyncMock()
    mock_transition_status = AsyncMock()
    monkeypatch.setattr("app.services.work_order_service.create_dispatch_task", mock_create_dispatch_task)
    monkeypatch.setattr("app.services.work_order_service.transition_status", mock_transition_status)

    await assign_work_order(
        SimpleNamespace(),
        work_order=work_order,
        assigned_user=assigned_user,
        actor_type="admin",
        actor_id="admin-1",
        notes="推荐分最高",
        dispatch_mode="assisted",
        candidate_snapshot={"user_id": "ops-9", "score": 96},
    )

    mock_create_dispatch_task.assert_awaited_once()
    kwargs = mock_create_dispatch_task.await_args.kwargs
    assert kwargs["dispatch_mode"] == "assisted"
    assert kwargs["candidate_snapshot"] == {"user_id": "ops-9", "score": 96}

    mock_transition_status.assert_awaited_once()
    transition_kwargs = mock_transition_status.await_args.kwargs
    assert transition_kwargs["new_status"] == "dispatched"
    assert transition_kwargs["detail"]["dispatch_mode"] == "assisted"


@pytest.mark.asyncio
async def test_build_batch_dispatch_preview_accounts_for_planned_capacity(monkeypatch: pytest.MonkeyPatch) -> None:
    hvac_skill = SimpleNamespace(code="hvac", name="暖通维修")
    hvac_link = SimpleNamespace(skill=hvac_skill, proficiency=5, is_primary=True)

    best_worker = SimpleNamespace(
        id="ops-1",
        username="张强",
        phone="13800000001",
        role="ops",
        is_active=True,
        worker_profile=SimpleNamespace(
            team=SimpleNamespace(name="暖通班"),
            team_id="team-hvac",
            job_title="暖通工程师",
            shift_status="on_duty",
            dispatch_enabled=True,
            max_active_orders=1,
            accepts_emergency=True,
            service_buildings_json='["Fox_public_Henry"]',
            skill_links=[hvac_link],
        ),
    )
    backup_worker = SimpleNamespace(
        id="ops-2",
        username="李明",
        phone="13800000002",
        role="ops",
        is_active=True,
        worker_profile=SimpleNamespace(
            team=SimpleNamespace(name="综合运维班"),
            team_id="team-general",
            job_title="综合工程师",
            shift_status="standby",
            dispatch_enabled=True,
            max_active_orders=4,
            accepts_emergency=False,
            service_buildings_json='["Fox_public_Henry"]',
            skill_links=[],
        ),
    )

    work_order_one = SimpleNamespace(
        id="wo-1",
        ticket_id="WO-1",
        status="pending_dispatch",
        building_id="Fox_public_Henry",
        priority="high",
        issue_description="空调告警，需要暖通处理",
        suggested_action="优先安排暖通班到场",
        anomaly_links=[],
        pending_dispatch_at=datetime.now(timezone.utc),
        created_at=datetime.now(timezone.utc),
    )
    work_order_two = SimpleNamespace(
        id="wo-2",
        ticket_id="WO-2",
        status="pending_dispatch",
        building_id="Fox_public_Henry",
        priority="high",
        issue_description="暖通温度异常，需要暖通排查",
        suggested_action="优先安排暖通班到场",
        anomaly_links=[],
        pending_dispatch_at=datetime.now(timezone.utc),
        created_at=datetime.now(timezone.utc),
    )

    db = _FakeDispatchDb([
        _FakeResult(rows=[2]),
        _FakeResult(scalars_items=[work_order_one, work_order_two]),
    ])
    monkeypatch.setattr(
        "app.services.work_order_service._load_dispatch_workers",
        AsyncMock(return_value=[best_worker, backup_worker]),
    )
    monkeypatch.setattr(
        "app.services.work_order_service._load_dispatch_active_counts",
        AsyncMock(return_value={}),
    )

    payload = await build_batch_dispatch_preview(
        db,
        sample_size=2,
        scan_limit=20,
        min_score=0,
        min_gap=0,
        max_per_worker=1,
    )

    assert payload["selected_count"] == 1
    assert payload["recommendations"][0]["ticket_id"] == "WO-1"
    assert payload["recommendations"][0]["chosen_candidate"]["user_id"] == "ops-1"
    assert payload["planned_assignments"][0]["count"] == 1
    assert payload["worker_loads"][0]["planned_count"] == 1
    assert payload["skipped_summary"][0]["reason"] in {"top_candidate_over_capacity", "batch_worker_cap_reached"}
    assert payload["skipped_examples"][0]["ticket_id"] == "WO-2"
