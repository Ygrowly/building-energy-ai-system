from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.api import routes_workorder
from app.db.models import WorkOrder, WorkOrderAuditLog
from app.db import session as db_session_module
from app.db.session import _build_connect_args
from app.services.work_order_service import create_work_order


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
