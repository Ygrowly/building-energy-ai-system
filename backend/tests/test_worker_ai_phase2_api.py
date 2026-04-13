from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from httpx import ASGITransport, AsyncClient

from app.api import routes_operator_ai, routes_worker_ai
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
async def test_worker_ai_steps_endpoint_calls_service(client, monkeypatch: pytest.MonkeyPatch):
    user = SimpleNamespace(id="worker-1", role="worker", is_active=True)
    db = AsyncMock()
    _override_dependencies(user=user, db=db)
    mock_service = AsyncMock(
        return_value={
            "ticket_id": "WO-001",
            "dispatch_id": "dispatch-1",
            "plan_id": "plan-1",
            "status": "active",
            "plan_version": 2,
            "summary": "排查步骤已生成",
            "root_cause_candidates": [],
            "steps": [],
            "safety_notes": [],
            "guidance_ready": True,
        }
    )
    monkeypatch.setattr(routes_worker_ai, "get_or_create_worker_step_plan", mock_service)

    try:
        response = await client.get(
            "/api/worker-ai/work-orders/WO-001/steps",
            params={"auto_generate": "true", "dispatch_id": "dispatch-1"},
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["plan_id"] == "plan-1"
    assert mock_service.await_args.kwargs["ticket_id"] == "WO-001"
    assert mock_service.await_args.kwargs["dispatch_id"] == "dispatch-1"
    assert mock_service.await_args.kwargs["user"] == user


@pytest.mark.asyncio
async def test_worker_ai_step_update_endpoint_forwards_note(client, monkeypatch: pytest.MonkeyPatch):
    user = SimpleNamespace(id="worker-1", role="worker", is_active=True)
    db = AsyncMock()
    _override_dependencies(user=user, db=db)
    mock_service = AsyncMock(
        return_value={
            "ok": True,
            "plan_id": "plan-1",
            "plan_version": 3,
            "steps": [{"id": "step_1", "status": "completed", "note": "阀门已复位"}],
            "next_suggestion": "继续下一步。",
        }
    )
    monkeypatch.setattr(routes_worker_ai, "update_worker_step_status", mock_service)

    try:
        response = await client.post(
            "/api/worker-ai/work-orders/WO-001/steps/step_1/update",
            json={
                "plan_id": "plan-1",
                "status": "completed",
                "note": "阀门已复位",
                "client_version": 2,
            },
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["plan_version"] == 3
    assert mock_service.await_args.kwargs["step_id"] == "step_1"
    assert mock_service.await_args.kwargs["note"] == "阀门已复位"


@pytest.mark.asyncio
async def test_worker_ai_tts_endpoint_returns_server_audio_payload(client, monkeypatch: pytest.MonkeyPatch):
    user = SimpleNamespace(id="worker-1", role="worker", is_active=True)
    db = AsyncMock()
    _override_dependencies(user=user, db=db)
    mock_service = AsyncMock(
        return_value={
            "audio_url": "/api/worker-ai/tts/cache/audio-1.mp3",
            "cache_hit": False,
            "playback_mode": "server_audio",
            "text": "请继续排查。",
            "voice": "longxiaochun_v2",
            "cache_key": "audio-1",
        }
    )
    monkeypatch.setattr(routes_worker_ai, "build_tts_response", mock_service)

    try:
        response = await client.post(
            "/api/worker-ai/tts",
            json={"text": "请继续排查。"},
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["playback_mode"] == "server_audio"
    assert mock_service.await_args.kwargs["text"] == "请继续排查。"


@pytest.mark.asyncio
async def test_worker_ai_tts_cache_endpoint_returns_mp3(client, monkeypatch: pytest.MonkeyPatch):
    user = SimpleNamespace(id="worker-1", role="worker", is_active=True)
    db = AsyncMock()
    _override_dependencies(user=user, db=db)
    cache_root = Path("backend/tests/.tmp/api-tts")
    cache_root.mkdir(parents=True, exist_ok=True)
    audio_path = cache_root / "audio-1.mp3"
    audio_path.write_bytes(b"fake-mp3")
    monkeypatch.setattr(routes_worker_ai, "get_tts_cache_path", lambda _cache_key: audio_path)

    try:
        response = await client.get("/api/worker-ai/tts/cache/audio-1.mp3")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.content == b"fake-mp3"
    assert response.headers["content-type"] == "audio/mpeg"


@pytest.mark.asyncio
async def test_operator_ai_chat_endpoint_returns_guidance_record(client, monkeypatch: pytest.MonkeyPatch):
    user = SimpleNamespace(id="manager-1", role="manager", is_active=True)
    db = AsyncMock()
    _override_dependencies(user=user, db=db)
    mock_service = AsyncMock(
        return_value={
            "assistant": "运小维",
            "session_id": "opai_1",
            "answer_type": "worker_guidance_record",
            "answer": "当前维修指导已推进到第 2 步。",
            "readonly": True,
            "facts": {"plan": {"plan_id": "plan-1"}},
            "metrics": {},
            "evidence_refs": ["worker_ai_step_plans.summary"],
            "suggested_followups": ["查看当前步骤详情"],
            "blocked_actions": [],
        }
    )
    monkeypatch.setattr(routes_operator_ai, "handle_operator_ai_chat", mock_service)

    try:
        response = await client.post(
            "/api/operator-ai/chat",
            json={
                "message": "WO-001 维修指导做到哪一步了？",
                "ticket_id": "WO-001",
                "include_evidence": True,
            },
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["answer_type"] == "worker_guidance_record"
    assert mock_service.await_args.kwargs["ticket_id"] == "WO-001"
