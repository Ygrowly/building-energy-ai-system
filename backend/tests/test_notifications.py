from __future__ import annotations

import asyncio
from contextlib import contextmanager
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.api import routes_notifications
from app.core.security import get_current_user
from app.db.models import NotificationRecord, NotificationRecipient
from app.db.session import get_db_session
from app.services import notification_realtime_service, notification_service
from main import app


def _make_user(user_id: str, role: str, *, active: bool = True) -> SimpleNamespace:
    return SimpleNamespace(
        id=user_id,
        username=user_id,
        role=role,
        is_active=active,
    )


def _make_dispatch_task(assigned_to: str = "ops-1") -> SimpleNamespace:
    return SimpleNamespace(
        id="dispatch-1",
        work_order_id="wo-1",
        incident_id="incident-1",
        assigned_to=assigned_to,
        latest_note="等待处理",
    )


def _make_dispatch_event(
    event_type: str,
    *,
    actor_id: str | None = None,
    payload_json: str | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=f"evt-{event_type}",
        dispatch_task_id="dispatch-1",
        work_order_id="wo-1",
        incident_id="incident-1",
        event_type=event_type,
        actor_id=actor_id,
        payload_json=payload_json,
    )


def _make_result(
    *,
    scalar_one_or_none=None,
    scalars_all: list | None = None,
    scalar=None,
    rows: list | None = None,
) -> MagicMock:
    result = MagicMock()
    result.scalar_one_or_none.return_value = scalar_one_or_none
    result.scalars.return_value.all.return_value = scalars_all or []
    result.scalar.return_value = scalar
    result.all.return_value = rows or []
    return result


class _FakeDb:
    def __init__(
        self,
        *,
        execute_results: list[MagicMock] | None = None,
        get_map: dict[tuple[object, str], object] | None = None,
    ) -> None:
        self._execute_results = list(execute_results or [])
        self._get_map = get_map or {}
        self.added: list[object] = []
        self.flush_count = 0
        self.commit = AsyncMock()
        self.sync_session = SimpleNamespace(info={})

    async def execute(self, _query):
        if not self._execute_results:
            raise AssertionError("unexpected execute() call")
        return self._execute_results.pop(0)

    async def get(self, model, key: str):
        return self._get_map.get((model, key))

    def add(self, item: object) -> None:
        self.added.append(item)

    async def flush(self) -> None:
        self.flush_count += 1
        for index, item in enumerate(self.added, start=1):
            if getattr(item, "id", None) is None:
                item.id = f"generated-{self.flush_count}-{index}"


@pytest.fixture
async def client():
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as ac:
        yield ac


@contextmanager
def _override_dependencies(*, db, user):
    async def _db_dep():
        yield db

    async def _user_dep():
        return user

    app.dependency_overrides[get_db_session] = _db_dep
    app.dependency_overrides[get_current_user] = _user_dep
    try:
        yield
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_dispatch_event_recipients_for_assignment_include_assignee_and_managers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager = _make_user("manager-1", "manager")
    admin = _make_user("admin-1", "admin")
    assignee = _make_user("ops-1", "ops")

    monkeypatch.setattr(
        notification_service,
        "_load_active_role_users",
        AsyncMock(return_value=[manager, admin]),
    )

    db = _FakeDb(
        get_map={
            (notification_service.User, "ops-1"): assignee,
        }
    )
    recipients = await notification_service._dispatch_event_recipients(
        db,
        event=_make_dispatch_event("assigned"),
        dispatch_task=_make_dispatch_task("ops-1"),
        event_payload={},
    )

    assert [item.id for item in recipients] == ["manager-1", "admin-1", "ops-1"]


@pytest.mark.asyncio
async def test_dispatch_event_recipients_for_support_assignment_include_original_support_and_managers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager = _make_user("manager-1", "manager")
    admin = _make_user("admin-1", "admin")
    original_ops = _make_user("ops-main", "ops")
    support_ops = _make_user("ops-support", "ops")

    monkeypatch.setattr(
        notification_service,
        "_load_active_role_users",
        AsyncMock(return_value=[manager, admin]),
    )

    db = _FakeDb(
        get_map={
            (notification_service.User, "ops-main"): original_ops,
            (notification_service.User, "ops-support"): support_ops,
        }
    )
    recipients = await notification_service._dispatch_event_recipients(
        db,
        event=_make_dispatch_event("support_assigned"),
        dispatch_task=_make_dispatch_task("ops-main"),
        event_payload={"assigned_to": "ops-support"},
    )

    assert {item.id for item in recipients} == {
        "manager-1",
        "admin-1",
        "ops-main",
        "ops-support",
    }


@pytest.mark.asyncio
async def test_ensure_recipients_deduplicates_existing_and_skips_actor() -> None:
    record = NotificationRecord(
        id="notification-1",
        source_type="dispatch_event",
        source_id="evt-1",
        category="workorder",
        event_type="accepted",
        aggregate_type="work_order",
        aggregate_id="wo-1",
        title="title",
        body="body",
        severity="info",
    )
    existing = NotificationRecipient(
        id="recipient-existing",
        notification_id=record.id,
        user_id="ops-2",
        recipient_role="ops",
        source_type=record.source_type,
        source_id=record.source_id,
    )
    db = _FakeDb(execute_results=[_make_result(scalars_all=[existing])])

    created = await notification_service._ensure_recipients(
        db,
        record=record,
        recipients=[
            _make_user("ops-1", "ops"),
            _make_user("ops-2", "ops"),
            _make_user("manager-1", "manager"),
        ],
        actor_id="ops-1",
    )

    assert [item.user_id for item in created] == ["manager-1"]
    pending = db.sync_session.info[notification_service._PENDING_KEY]
    assert pending["summary_user_ids"] == {"manager-1"}
    assert len(pending["created_recipient_ids"]) == 1


@pytest.mark.asyncio
async def test_create_notifications_for_dispatch_hall_open_only_targets_visible_ops_and_managers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    visible_ops = _make_user("ops-visible", "ops")
    manager = _make_user("manager-1", "manager")
    created = [
        NotificationRecipient(
            id="recipient-1",
            notification_id="notification-1",
            user_id="ops-visible",
            recipient_role="ops",
            source_type="dispatch_hall_open",
            source_id="hall-1:ts",
        )
    ]
    record = NotificationRecord(
        id="notification-1",
        category="workorder",
        event_type="dispatch_hall_support_open",
        source_type="dispatch_hall_open",
        source_id="hall-1:ts",
        aggregate_type="dispatch_hall_entry",
        aggregate_id="hall-1",
        title="title",
        body="body",
        severity="warning",
    )
    ensure_recipients = AsyncMock(return_value=created)

    monkeypatch.setattr(
        notification_service,
        "_load_active_role_users",
        AsyncMock(return_value=[manager]),
    )
    monkeypatch.setattr(
        notification_service,
        "_load_visible_hall_users",
        AsyncMock(return_value=[visible_ops]),
    )
    monkeypatch.setattr(
        notification_service,
        "_ensure_notification_record",
        AsyncMock(return_value=record),
    )
    monkeypatch.setattr(notification_service, "_ensure_recipients", ensure_recipients)

    hall_entry = SimpleNamespace(
        id="hall-1",
        status="open",
        entry_type="support_request",
        support_reason="需要协同",
        reason=None,
        created_by="ops-main",
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    work_order = SimpleNamespace(
        id="wo-1",
        ticket_id="WO-001",
        incident_id="incident-1",
        building_id="B-01",
    )

    result = await notification_service.create_notifications_for_dispatch_hall_open(
        _FakeDb(),
        hall_entry=hall_entry,
        work_order=work_order,
        actor_id="ops-main",
    )

    assert result == created
    recipient_users = ensure_recipients.await_args.kwargs["recipients"]
    assert {item.id for item in recipient_users} == {"ops-visible", "manager-1"}


@pytest.mark.asyncio
async def test_mark_notification_recipients_read_marks_items_and_queues_sync() -> None:
    record = NotificationRecord(
        id="notification-1",
        category="workorder",
        event_type="assigned",
        source_type="dispatch_event",
        source_id="evt-1",
        aggregate_type="work_order",
        aggregate_id="wo-1",
        title="title",
        body="body",
        severity="info",
    )
    first = NotificationRecipient(
        id="recipient-1",
        notification_id=record.id,
        user_id="ops-1",
        recipient_role="ops",
        source_type=record.source_type,
        source_id=record.source_id,
        is_read=False,
    )
    second = NotificationRecipient(
        id="recipient-2",
        notification_id=record.id,
        user_id="ops-1",
        recipient_role="ops",
        source_type=record.source_type,
        source_id="evt-2",
        is_read=False,
    )
    first.notification = record
    second.notification = record

    db = _FakeDb(execute_results=[_make_result(scalars_all=[first, second])])
    items = await notification_service.mark_notification_recipients_read(
        db,
        user_id="ops-1",
        recipient_ids=["recipient-1", "recipient-2"],
    )

    assert [item.id for item in items] == ["recipient-1", "recipient-2"]
    assert all(item.is_read for item in items)
    assert all(item.read_at is not None for item in items)
    pending = db.sync_session.info[notification_service._PENDING_KEY]
    assert pending["read_recipient_ids"] == {"recipient-1", "recipient-2"}
    assert pending["summary_user_ids"] == {"ops-1"}


def test_audit_content_for_create_generates_pending_review_notification() -> None:
    audit_log = SimpleNamespace(
        action="create",
        detail_json=None,
    )
    work_order = SimpleNamespace(
        id="wo-1",
        ticket_id="WO-001",
        incident_id="incident-1",
        building_id="Fox_office_Alice",
    )

    content = notification_service._audit_content(
        audit_log=audit_log,
        work_order=work_order,
    )

    assert content is not None
    title, body, severity, payload = content
    assert title == "WO-001 待审核"
    assert "生成工单" in body
    assert severity == "warning"
    assert payload["ticket_id"] == "WO-001"


@pytest.mark.asyncio
async def test_publish_after_commit_publishes_created_read_and_summary_events(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    record = NotificationRecord(
        id="notification-1",
        category="workorder",
        event_type="assigned",
        source_type="dispatch_event",
        source_id="evt-1",
        aggregate_type="work_order",
        aggregate_id="wo-1",
        title="title",
        body="body",
        severity="info",
        payload_json='{"ticket_id":"WO-001","cta_type":"open_workorder","cta_params":{"ticket_id":"WO-001"}}',
    )
    created_recipient = NotificationRecipient(
        id="recipient-created",
        notification_id=record.id,
        user_id="ops-1",
        recipient_role="ops",
        source_type=record.source_type,
        source_id=record.source_id,
    )
    created_recipient.notification = record

    read_recipient = NotificationRecipient(
        id="recipient-read",
        notification_id=record.id,
        user_id="manager-1",
        recipient_role="manager",
        source_type=record.source_type,
        source_id=record.source_id,
        is_read=True,
        read_at=datetime.now(timezone.utc),
    )
    read_recipient.notification = record

    fake_db = _FakeDb()
    publish_user_event = AsyncMock()

    class _AsyncSessionContext:
        async def __aenter__(self):
            return fake_db

        async def __aexit__(self, exc_type, exc, tb):
            return None

    async def _load_payloads(_db, recipient_ids):
        ids = set(recipient_ids)
        if ids == {"recipient-created"}:
            return [created_recipient]
        if ids == {"recipient-read"}:
            return [read_recipient]
        return []

    monkeypatch.setattr(notification_service, "AsyncSessionLocal", _AsyncSessionContext)
    monkeypatch.setattr(notification_service, "_load_recipient_payloads", _load_payloads)
    monkeypatch.setattr(notification_service, "publish_user_event", publish_user_event)
    monkeypatch.setattr(
        notification_service,
        "get_notification_summary",
        AsyncMock(return_value={"total_unread": 1, "categories": {"workorder": 1}, "event_types": {"assigned": 1}}),
    )

    await notification_service._publish_after_commit(
        {
            "created_recipient_ids": {"recipient-created"},
            "read_recipient_ids": {"recipient-read"},
            "summary_user_ids": {"ops-1", "manager-1"},
        }
    )

    assert created_recipient.delivered_at is None
    assert created_recipient.last_pushed_at is not None
    fake_db.commit.assert_awaited_once()
    event_types = [call.args[1] for call in publish_user_event.await_args_list]
    assert "notification.created" in event_types
    assert "notification.read" in event_types
    assert event_types.count("notification.summary") == 2


@pytest.mark.asyncio
async def test_publish_after_commit_does_not_mark_push_success_when_created_publish_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    record = NotificationRecord(
        id="notification-1",
        category="workorder",
        event_type="assigned",
        source_type="dispatch_event",
        source_id="evt-1",
        aggregate_type="work_order",
        aggregate_id="wo-1",
        title="title",
        body="body",
        severity="info",
        payload_json='{"ticket_id":"WO-001","cta_type":"open_workorder","cta_params":{"ticket_id":"WO-001"}}',
    )
    created_recipient = NotificationRecipient(
        id="recipient-created",
        notification_id=record.id,
        user_id="ops-1",
        recipient_role="ops",
        source_type=record.source_type,
        source_id=record.source_id,
    )
    created_recipient.notification = record

    fake_db = _FakeDb()

    class _AsyncSessionContext:
        async def __aenter__(self):
            return fake_db

        async def __aexit__(self, exc_type, exc, tb):
            return None

    async def _load_payloads(_db, recipient_ids):
        if set(recipient_ids) == {"recipient-created"}:
            return [created_recipient]
        return []

    async def _publish_user_event(_user_id, event_type, _payload):
        if event_type == "notification.created":
            raise RuntimeError("publish failed")
        return None

    monkeypatch.setattr(notification_service, "AsyncSessionLocal", _AsyncSessionContext)
    monkeypatch.setattr(notification_service, "_load_recipient_payloads", _load_payloads)
    monkeypatch.setattr(notification_service, "publish_user_event", AsyncMock(side_effect=_publish_user_event))
    monkeypatch.setattr(
        notification_service,
        "get_notification_summary",
        AsyncMock(return_value={"total_unread": 1, "categories": {"workorder": 1}, "event_types": {"assigned": 1}}),
    )

    await notification_service._publish_after_commit(
        {
            "created_recipient_ids": {"recipient-created"},
            "read_recipient_ids": set(),
            "summary_user_ids": {"ops-1"},
        }
    )

    assert created_recipient.delivered_at is None
    assert created_recipient.last_pushed_at is None
    fake_db.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_realtime_ticket_is_single_use_without_redis(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        notification_realtime_service,
        "get_redis_client",
        AsyncMock(return_value=None),
    )

    payload = await notification_realtime_service.issue_realtime_ticket("ops-1")
    assert payload["ticket"]
    assert payload["expires_in"] == 60

    first_user_id = await notification_realtime_service.consume_realtime_ticket(payload["ticket"])
    second_user_id = await notification_realtime_service.consume_realtime_ticket(payload["ticket"])

    assert first_user_id == "ops-1"
    assert second_user_id is None


@pytest.mark.asyncio
async def test_stream_user_events_cleans_up_background_tasks_after_disconnect(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _DisconnectingWebSocket:
        def __init__(self) -> None:
            self.closed = False

        async def send_text(self, _message: str) -> None:
            if self.closed:
                raise RuntimeError("Unexpected ASGI message 'websocket.send', after sending 'websocket.close'.")

        async def receive_text(self) -> str:
            self.closed = True
            raise WebSocketDisconnect(code=1000)

    tracked_tasks: list[asyncio.Task] = []
    original_create_task = notification_realtime_service.asyncio.create_task

    def _track_task(coro):
        task = original_create_task(coro)
        tracked_tasks.append(task)
        return task

    monkeypatch.setattr(
        notification_realtime_service,
        "get_redis_client",
        AsyncMock(return_value=None),
    )
    monkeypatch.setattr(notification_realtime_service.asyncio, "create_task", _track_task)

    try:
        await notification_realtime_service.stream_user_events(
            "ops-1",
            _DisconnectingWebSocket(),
            ping_interval_seconds=0.01,
        )
        await asyncio.sleep(0.03)

        assert tracked_tasks
        assert all(task.done() for task in tracked_tasks)
        assert all(task.cancelled() or task.exception() is None for task in tracked_tasks)
    finally:
        for task in tracked_tasks:
            if not task.done():
                task.cancel()
        for task in tracked_tasks:
            try:
                await task
            except (asyncio.CancelledError, RuntimeError, WebSocketDisconnect):
                pass


@pytest.mark.asyncio
async def test_list_notifications_api_returns_serialized_payload(
    client,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = AsyncMock()
    user = _make_user("ops-1", "ops")

    recipient = NotificationRecipient(
        id="recipient-1",
        notification_id="notification-1",
        user_id="ops-1",
        recipient_role="ops",
        source_type="dispatch_event",
        source_id="evt-1",
    )

    monkeypatch.setattr(
        routes_notifications,
        "list_notifications",
        AsyncMock(return_value=([recipient], 1)),
    )
    monkeypatch.setattr(
        routes_notifications,
        "serialize_notification_recipient",
        lambda item: {"recipient_id": item.id, "title": "工单已派发"},
    )

    with _override_dependencies(db=db, user=user):
        response = await client.get("/api/notifications")

    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 1
    assert payload["notifications"] == [{"recipient_id": "recipient-1", "title": "工单已派发"}]


@pytest.mark.asyncio
async def test_mark_all_notifications_read_api_commits(
    client,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = AsyncMock()
    user = _make_user("manager-1", "manager")

    monkeypatch.setattr(
        routes_notifications,
        "mark_all_notifications_read",
        AsyncMock(return_value=[NotificationRecipient(id="r1"), NotificationRecipient(id="r2")]),
    )

    with _override_dependencies(db=db, user=user):
        response = await client.post("/api/notifications/mark-all-read", json={"category": "workorder"})

    assert response.status_code == 200
    assert response.json()["updated"] == 2
    db.commit.assert_awaited_once()


def test_notifications_ws_rejects_invalid_ticket(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(routes_notifications, "consume_realtime_ticket", AsyncMock(return_value=None))

    with TestClient(app) as client:
        with pytest.raises(WebSocketDisconnect) as exc_info:
            with client.websocket_connect("/api/notifications/ws?ticket=invalid"):
                pass

    assert exc_info.value.code == 1008


def test_notifications_ws_bootstraps_summary_and_recent_notifications(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recipient = NotificationRecipient(
        id="recipient-1",
        notification_id="notification-1",
        user_id="ops-1",
        recipient_role="ops",
        source_type="dispatch_event",
        source_id="evt-1",
    )

    fake_db = SimpleNamespace()

    class _AsyncSessionContext:
        async def __aenter__(self):
            return fake_db

        async def __aexit__(self, exc_type, exc, tb):
            return None

    async def _fake_stream(_user_id, websocket):
        await websocket.close(code=1000)

    monkeypatch.setattr(routes_notifications, "consume_realtime_ticket", AsyncMock(return_value="ops-1"))
    monkeypatch.setattr(routes_notifications, "AsyncSessionLocal", _AsyncSessionContext)
    monkeypatch.setattr(
        routes_notifications,
        "get_notification_summary",
        AsyncMock(return_value={"total_unread": 1, "categories": {"workorder": 1}, "event_types": {"assigned": 1}}),
    )
    monkeypatch.setattr(routes_notifications, "list_notifications", AsyncMock(return_value=([recipient], 1)))
    monkeypatch.setattr(
        routes_notifications,
        "serialize_notification_recipient",
        lambda item: {"recipient_id": item.id, "title": "宸ュ崟宸叉淳鍙?", "event_type": "assigned"},
    )
    monkeypatch.setattr(routes_notifications, "stream_user_events", _fake_stream)

    with TestClient(app) as client:
        with client.websocket_connect("/api/notifications/ws?ticket=valid&page_size=5") as websocket:
            summary_message = websocket.receive_json()
            created_message = websocket.receive_json()

    assert summary_message["type"] == "notification.summary"
    assert summary_message["data"]["total_unread"] == 1
    assert created_message["type"] == "notification.created"
    assert created_message["data"]["recipient_id"] == "recipient-1"
    assert created_message["data"]["bootstrap"] is True
