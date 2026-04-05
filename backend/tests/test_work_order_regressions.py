from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.api import routes_workorder
from app.db.models import WorkOrder, WorkOrderAuditLog
from app.db import session as db_session_module
from app.db.session import _build_connect_args
from app.services.work_order_service import assign_work_order, create_work_order, list_dispatch_candidates


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


def test_build_connect_args_uses_tls_for_remote_hosts_by_default() -> None:
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


class _FakeDispatchDb:
    def __init__(self, results):
        self._results = list(results)

    async def execute(self, _query):
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
