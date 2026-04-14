from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from httpx import ASGITransport, AsyncClient

from app.api import routes_maintenance_experiences
from app.core.security import get_current_user
from app.db.session import get_db_session
from main import app


@pytest.fixture
async def client():
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as ac:
        yield ac


def _override_dependencies(*, user, db):
    async def _db_dep():
        yield db

    async def _user_dep():
        return user

    app.dependency_overrides[get_db_session] = _db_dep
    app.dependency_overrides[get_current_user] = _user_dep


@pytest.mark.asyncio
async def test_create_maintenance_experience_endpoint_calls_service(client, monkeypatch: pytest.MonkeyPatch):
    user = SimpleNamespace(id="worker-1", role="ops", is_active=True)
    db = AsyncMock()
    _override_dependencies(user=user, db=db)
    mock_service = AsyncMock(return_value={"id": "exp-1", "status": "created", "organized_text": "先核对阀门开度。"})
    monkeypatch.setattr(routes_maintenance_experiences, "create_maintenance_experience", mock_service)

    try:
        response = await client.post(
            "/api/maintenance-experiences",
            json={
                "source_type": "worker_note",
                "source_work_order_id": "WO-20260403-005",
                "source_text": "以前处理过这个问题，先看阀门开度更快。",
            },
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["status"] == "created"
    assert mock_service.await_args.kwargs["actor_user_id"] == "worker-1"
    assert mock_service.await_args.kwargs["actor_role"] == "ops"
    assert mock_service.await_args.kwargs["source_type"] == "worker_note"


@pytest.mark.asyncio
async def test_search_maintenance_experiences_endpoint_calls_service(client, monkeypatch: pytest.MonkeyPatch):
    user = SimpleNamespace(id="manager-1", role="manager", is_active=True)
    db = AsyncMock()
    _override_dependencies(user=user, db=db)
    mock_service = AsyncMock(
        return_value={
            "query": "供水温度偏离",
            "items": [{"id": "exp-1", "organized_text": "先核对现场温度表。", "score": 0.86}],
            "total": 1,
            "sort_by": "score",
        }
    )
    monkeypatch.setattr(routes_maintenance_experiences, "search_maintenance_experiences", mock_service)

    try:
        response = await client.get(
            "/api/maintenance-experiences/search",
            params={
                "query": "供水温度偏离",
                "building_id": "Public",
                "device_type": "cold_station",
                "fault_type": "supply_water_temperature_deviation",
                "limit": 5,
            },
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["total"] == 1
    assert mock_service.await_args.kwargs["actor_role"] == "manager"
    assert mock_service.await_args.kwargs["building_id"] == "Public"
    assert mock_service.await_args.kwargs["device_type"] == "cold_station"


@pytest.mark.asyncio
async def test_feedback_maintenance_experience_endpoint_calls_service(client, monkeypatch: pytest.MonkeyPatch):
    user = SimpleNamespace(id="worker-2", role="ops", is_active=True)
    db = AsyncMock()
    _override_dependencies(user=user, db=db)
    mock_service = AsyncMock(return_value={"ok": True, "experience_id": "exp-1", "feedback": "helpful"})
    monkeypatch.setattr(routes_maintenance_experiences, "add_maintenance_experience_feedback", mock_service)

    try:
        response = await client.post(
            "/api/maintenance-experiences/exp-1/feedback",
            json={
                "work_order_id": "WO-20260411-002",
                "feedback": "helpful",
                "note": "按这个经验先查阀门，定位更快。",
            },
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["feedback"] == "helpful"
    assert mock_service.await_args.kwargs["experience_id"] == "exp-1"
    assert mock_service.await_args.kwargs["actor_user_id"] == "worker-2"


@pytest.mark.asyncio
async def test_deactivate_maintenance_experience_endpoint_calls_service(client, monkeypatch: pytest.MonkeyPatch):
    user = SimpleNamespace(id="admin-1", role="admin", is_active=True)
    db = AsyncMock()
    _override_dependencies(user=user, db=db)
    mock_service = AsyncMock(return_value={"ok": True, "status": "deactivated", "experience_id": "exp-1"})
    monkeypatch.setattr(routes_maintenance_experiences, "deactivate_maintenance_experience", mock_service)

    try:
        response = await client.post(
            "/api/maintenance-experiences/exp-1/deactivate",
            json={"reason": "经验已过期"},
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["status"] == "deactivated"
    assert mock_service.await_args.kwargs["actor_role"] == "admin"
    assert mock_service.await_args.kwargs["reason"] == "经验已过期"
