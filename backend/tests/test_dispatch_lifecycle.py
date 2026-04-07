from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.api import routes_dispatch, routes_workorder
from app.db.models import (
    AnomalyIncident,
    DispatchEvent,
    DispatchTask,
    User,
    WorkOrder,
    WorkOrderAuditLog,
    WorkerProfile,
    WorkerTeam,
)
from app.services import dispatch_service, work_order_service
from app.services.work_order_service import assign_work_order


class _FakeAsyncSession:
    def __init__(self, *, incident: AnomalyIncident):
        self.incidents = {incident.id: incident}
        self.dispatch_tasks: dict[str, DispatchTask] = {}
        self.dispatch_events: list[DispatchEvent] = []
        self.audit_logs: list[WorkOrderAuditLog] = []
        self._pending: list[object] = []
        self.commit_calls = 0
        self.rollback_calls = 0

    def add(self, item: object) -> None:
        self._pending.append(item)

    async def flush(self) -> None:
        while self._pending:
            item = self._pending.pop(0)
            if getattr(item, "id", None) in (None, ""):
                setattr(item, "id", str(uuid4()))

            if isinstance(item, DispatchTask):
                self.dispatch_tasks[item.id] = item
            elif isinstance(item, DispatchEvent):
                self.dispatch_events.append(item)
            elif isinstance(item, WorkOrderAuditLog):
                self.audit_logs.append(item)

    async def commit(self) -> None:
        self.commit_calls += 1
        await self.flush()

    async def rollback(self) -> None:
        self.rollback_calls += 1

    async def get(self, model: type, obj_id: str):
        if model is AnomalyIncident:
            return self.incidents.get(obj_id)
        if model is DispatchTask:
            return self.dispatch_tasks.get(obj_id)
        return None

    async def execute(self, *_args, **_kwargs):
        raise AssertionError("此测试不应触发真实 SQL execute")


def _make_ops_user() -> User:
    team = WorkerTeam(id="team-hvac", team_code="hvac_team", name="暖通班")
    profile = WorkerProfile(
        user_id="ops-1",
        team_id=team.id,
        max_active_orders=4,
        dispatch_enabled=True,
        accepts_emergency=True,
    )
    profile.team = team

    user = User(
        id="ops-1",
        username="张工",
        phone="13800001234",
        role="ops",
        is_active=True,
    )
    user.worker_profile = profile
    return user


def _make_work_order(*, incident_id: str) -> WorkOrder:
    now = datetime.now(timezone.utc)
    return WorkOrder(
        id="wo-1",
        ticket_id="WO-LIFECYCLE-001",
        building_id="Fox_office_Alice",
        device_id="ahu-01",
        issue_description="AHU 送风温度异常偏高，疑似阀门卡滞",
        suggested_action="请暖通班优先检查冷冻水阀和控制信号",
        priority="high",
        status="pending_dispatch",
        source="manual",
        incident_id=incident_id,
        pending_dispatch_at=now,
        created_at=now,
        updated_at=now,
    )


def _make_incident(*, work_order_id: str) -> AnomalyIncident:
    now = datetime.now(timezone.utc)
    return AnomalyIncident(
        id="incident-db-1",
        incident_id="INC-LIFECYCLE-001",
        source="auto_detect",
        building_id="Fox_office_Alice",
        device_id="ahu-01",
        rule_triggered="supply_temp_high",
        hvac_root_cause="valve_stuck",
        merge_key="auto_detect|Fox_office_Alice|ahu-01|supply_temp_high|valve_stuck",
        workflow_status="pending_dispatch",
        incident_status="open",
        priority="high",
        first_seen_at=now,
        last_seen_at=now,
        continuity_expires_at=now,
        anomaly_count=1,
        summary_text="AHU 送风温度连续异常",
        is_active=True,
        current_work_order_id=work_order_id,
        created_at=now,
        updated_at=now,
    )


@pytest.mark.asyncio
async def test_dispatch_lifecycle_manager_to_worker_to_close(monkeypatch: pytest.MonkeyPatch) -> None:
    work_order = _make_work_order(incident_id="incident-db-1")
    incident = _make_incident(work_order_id=work_order.id)
    ops_user = _make_ops_user()
    manager_user = SimpleNamespace(id="manager-1", role="manager")
    db = _FakeAsyncSession(incident=incident)

    async def _fake_current_dispatch(_db, *, work_order: WorkOrder):
        dispatch_id = getattr(work_order, "current_dispatch_id", None)
        if not dispatch_id:
            return None
        return db.dispatch_tasks.get(dispatch_id)

    async def _fake_get_work_order_by_ticket_id(_db, ticket_id: str):
        return work_order if ticket_id == work_order.ticket_id else None

    async def _fake_load_work_order(_db, work_order_id: str):
        return work_order if work_order_id == work_order.id else None

    async def _fake_get_dispatch_task_by_id(_db, dispatch_id: str):
        return db.dispatch_tasks.get(dispatch_id)

    async def _fake_next_attempt_no(_db, *, work_order_id: str) -> int:
        attempts = [
            item.attempt_no
            for item in db.dispatch_tasks.values()
            if item.work_order_id == work_order_id
        ]
        return max(attempts, default=0) + 1

    monkeypatch.setattr(dispatch_service, "get_current_dispatch_task", _fake_current_dispatch)
    monkeypatch.setattr(dispatch_service, "_next_attempt_no", _fake_next_attempt_no)
    monkeypatch.setattr(dispatch_service, "close_open_hall_entries_for_dispatch", AsyncMock())
    monkeypatch.setattr(work_order_service, "get_current_dispatch_task", _fake_current_dispatch)
    monkeypatch.setattr(routes_workorder, "get_work_order_by_ticket_id", _fake_get_work_order_by_ticket_id)
    monkeypatch.setattr(routes_dispatch, "get_dispatch_task_by_id", _fake_get_dispatch_task_by_id)
    monkeypatch.setattr(routes_dispatch, "_load_work_order", _fake_load_work_order)
    monkeypatch.setattr(routes_workorder, "_invalidate_related_cache", AsyncMock())
    monkeypatch.setattr(routes_dispatch, "_invalidate_related_cache", AsyncMock())

    await assign_work_order(
        db,
        work_order=work_order,
        assigned_user=ops_user,
        actor_type="admin",
        actor_id=manager_user.id,
        dispatch_mode="assisted",
        candidate_snapshot={
            "user_id": ops_user.id,
            "username": ops_user.username,
            "team_name": ops_user.worker_profile.team.name,
            "dispatch_mode": "assisted",
        },
        notes="批量派工试运行",
    )
    await db.commit()

    dispatch_task = db.dispatch_tasks[work_order.current_dispatch_id]
    assert work_order.status == "dispatched"
    assert dispatch_task.dispatch_status == "assigned"
    assert incident.workflow_status == "dispatched"
    assert incident.current_dispatch_id == dispatch_task.id
    assert incident.current_assigned_to == ops_user.id

    for action, expected_status in (
        ("accept", "accepted"),
        ("arrive", "arrived"),
        ("start", "processing"),
    ):
        response = await routes_workorder.worker_action(
            ticket_id=work_order.ticket_id,
            req=routes_workorder.WorkerActionRequest(action=action, notes=f"{action} done"),
            db=db,
            user=SimpleNamespace(id=ops_user.id, role="ops"),
        )
        assert response["status"] == "dispatched"
        assert dispatch_task.dispatch_status == expected_status
        assert incident.current_dispatch_status == expected_status

    complete_response = await routes_dispatch.complete_dispatch_task_endpoint(
        dispatch_id=dispatch_task.id,
        req=routes_dispatch.CompleteRequest(result="fixed", notes="现场恢复正常"),
        db=db,
        user=SimpleNamespace(id=ops_user.id, role="ops"),
    )
    assert complete_response["status"] == "completed"
    assert work_order.status == "completed"
    assert work_order.worker_result == "fixed"
    assert dispatch_task.dispatch_status == "completed"
    assert incident.workflow_status == "completed"
    assert incident.incident_status == "resolved"
    assert incident.is_active is False

    review_response = await routes_workorder.admin_review(
        ticket_id=work_order.ticket_id,
        req=routes_workorder.AdminReviewRequest(action="confirm", notes="管理员复核通过"),
        db=db,
        user=manager_user,
    )
    assert review_response["status"] == "closed"
    assert work_order.status == "closed"
    assert work_order.closed_at is not None
    assert incident.workflow_status == "closed"
    assert incident.incident_status == "closed"
    assert incident.is_active is False

    event_types = [item.event_type for item in db.dispatch_events]
    assert event_types == ["assigned", "accepted", "arrived", "started", "completed"]

    audit_actions = [item.action for item in db.audit_logs]
    assert audit_actions == [
        "dispatch",
        "worker_accept",
        "worker_arrive",
        "worker_start",
        "worker_feedback",
        "close",
    ]
    assert db.commit_calls == 6
