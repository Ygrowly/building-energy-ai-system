from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from main import app


@pytest.fixture
async def client():
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        yield ac


def _make_user(*, user_id: str = "user-1", role: str = "admin"):
    return SimpleNamespace(id=user_id, role=role)


def _make_incident(**overrides):
    base = {
        "id": "incident-db-id",
        "incident_id": "INC-20260403-001",
        "source": "auto_detect",
        "building_id": "Fox_public_Henry",
        "device_id": "meter-1",
        "rule_triggered": "flag_electricity",
        "hvac_root_cause": None,
        "merge_key": "auto_detect|Fox_public_Henry|meter-1|flag_electricity|",
        "incident_status": "open",
        "workflow_status": "dispatched",
        "priority": "high",
        "first_seen_at": None,
        "last_seen_at": None,
        "continuity_expires_at": None,
        "anomaly_count": 3,
        "peak_deviation_pct": 72.6,
        "latest_actual_value": 65.7,
        "latest_expected_value": 7.9,
        "summary_text": "连续异常",
        "current_work_order_id": "wo-db-id",
        "current_assigned_to": "ops-1",
        "is_active": True,
        "dispatch_blocked_reason": "等待协同支援",
        "latest_dispatch_note": "已改派给张工",
        "resolved_at": None,
        "created_at": None,
        "updated_at": None,
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def _make_work_order(**overrides):
    base = {
        "id": "wo-db-id",
        "ticket_id": "WO-20260403-001",
        "status": "dispatched",
        "priority": "high",
        "ai_decision": "approved",
        "ai_reason": "连续异常",
        "ai_fallback": False,
        "worker_result": None,
        "worker_notes": None,
        "created_at": None,
        "updated_at": None,
        "assigned_to": "ops-1",
        "incident_id": None,
        "issue_description": "旧摘要",
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def _make_dispatch_task(**overrides):
    now = datetime.now(timezone.utc)
    base = {
        "id": "dispatch-1",
        "dispatch_status": "processing",
        "attempt_no": 2,
        "assigned_to": "ops-1",
        "dispatch_mode": "manual",
        "selection_reason": "调度改派：就近班组优先",
        "reject_reason": None,
        "support_reason": None,
        "transfer_from_dispatch_id": "dispatch-0",
        "assigned_at": now - timedelta(minutes=20),
        "accepted_at": now - timedelta(minutes=15),
        "arrived_at": now - timedelta(minutes=8),
        "processing_started_at": now - timedelta(minutes=5),
        "completed_at": None,
        "latest_note": "正在现场检修",
        "accept_deadline_at": now + timedelta(minutes=5),
        "arrive_deadline_at": now + timedelta(minutes=25),
        "finish_deadline_at": now + timedelta(minutes=90),
    }
    base.update(overrides)
    return SimpleNamespace(**base)


class _ScalarExecResult:
    def __init__(self, items):
        self._items = items

    def scalars(self):
        return SimpleNamespace(all=lambda: self._items)


class _BuildingExecResult:
    def __init__(self, building_ids):
        self._building_ids = building_ids

    def fetchall(self):
        return [(building_id,) for building_id in self._building_ids]


class TestIncidentRoutes:
    @pytest.mark.asyncio
    async def test_list_incidents_for_ops_returns_incident_view(self, client):
        from app.core.security import get_current_user
        from app.db.session import get_db_session

        incident = _make_incident()
        work_order = _make_work_order()
        dispatch_task = _make_dispatch_task()
        assigned_user = SimpleNamespace(
            id="ops-1",
            username="张工",
            phone="13800000001",
            worker_profile=SimpleNamespace(team=SimpleNamespace(name="暖通班")),
        )
        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(
            side_effect=[
                _ScalarExecResult([work_order]),
                _ScalarExecResult([assigned_user]),
                _ScalarExecResult([]),
            ]
        )

        async def _override_db():
            yield mock_db

        async def _override_user():
            return _make_user(user_id="ops-1", role="ops")

        async def _fake_cache(_key, _ttl, compute):
            return await compute()

        with patch(
            "app.api.routes_incidents.list_incidents",
            new=AsyncMock(return_value=([incident], 1)),
        ), patch(
            "app.api.routes_incidents.load_current_dispatches_by_work_order_ids",
            new=AsyncMock(return_value={"wo-db-id": dispatch_task}),
        ), patch("app.api.routes_incidents.get_or_compute_json", new=_fake_cache):
            app.dependency_overrides[get_db_session] = _override_db
            app.dependency_overrides[get_current_user] = _override_user
            try:
                resp = await client.get(
                    "/api/incidents?workflow_status=dispatched&page=1&page_size=20"
                )
            finally:
                app.dependency_overrides.clear()

        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        assert len(data["incidents"]) == 1
        assert data["incidents"][0]["incident_id"] == "INC-20260403-001"
        assert data["incidents"][0]["current_work_order"]["ticket_id"] == "WO-20260403-001"
        assert data["incidents"][0]["current_work_order"]["execution_status"] == "processing"
        assert data["incidents"][0]["current_work_order"]["assigned_to"] == "ops-1"
        assert data["incidents"][0]["dispatch_blocked_reason"] == "等待协同支援"
        assert data["incidents"][0]["current_dispatch"]["attempt_no"] == 2
        assert data["incidents"][0]["current_dispatch"]["selection_reason"] == "调度改派：就近班组优先"

    @pytest.mark.asyncio
    async def test_incident_detail_ops_permission_prefers_current_dispatch_assignee(self, client):
        from app.core.security import get_current_user
        from app.db.session import get_db_session

        incident = _make_incident(current_assigned_to="ops-2")
        work_order = _make_work_order(assigned_to="ops-1")
        dispatch_task = _make_dispatch_task(assigned_to="ops-2")
        mock_db = AsyncMock()

        async def _override_db():
            yield mock_db

        async def _override_user():
            return _make_user(user_id="ops-1", role="ops")

        async def _fake_cache(_key, _ttl, compute):
            return await compute()

        with patch(
            "app.api.routes_incidents.get_incident_by_identifier",
            new=AsyncMock(return_value=incident),
        ), patch(
            "app.api.routes_incidents.list_incident_work_orders",
            new=AsyncMock(return_value=[work_order]),
        ), patch(
            "app.api.routes_incidents.load_current_dispatches_by_work_order_ids",
            new=AsyncMock(return_value={"wo-db-id": dispatch_task}),
        ), patch("app.api.routes_incidents.get_or_compute_json", new=_fake_cache):
            app.dependency_overrides[get_db_session] = _override_db
            app.dependency_overrides[get_current_user] = _override_user
            try:
                resp = await client.get("/api/incidents/INC-20260403-001")
            finally:
                app.dependency_overrides.clear()

        assert resp.status_code == 403
        assert resp.json()["detail"] == "只能查看派发给自己的 incident"

    @pytest.mark.asyncio
    async def test_rebuild_incidents_supports_predictions_and_ai_review(self, client):
        from app.db.session import get_db_session

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(
            return_value=_BuildingExecResult(["Fox_public_Henry"])
        )

        async def _override_db():
            yield mock_db

        async def _fake_delete_cache_by_prefix(_prefix: str):
            return None

        with patch(
            "app.services.auto_work_order_service.auto_create_alert_orders",
            new=AsyncMock(return_value={"created": 1, "merged": 2, "skipped_dup": 3}),
        ), patch(
            "app.services.auto_work_order_service.auto_create_prediction_orders",
            new=AsyncMock(return_value={"created": 4, "merged": 5, "skipped_dup": 6}),
        ), patch(
            "app.services.auto_work_order_service.trigger_ai_review_for_pending",
            new=AsyncMock(return_value=7),
        ), patch(
            "app.api.routes_admin.delete_cache_by_prefix",
            new=_fake_delete_cache_by_prefix,
        ):
            app.dependency_overrides[get_db_session] = _override_db
            try:
                resp = await client.post(
                    "/api/admin/rebuild-incidents",
                    json={
                        "include_alerts": True,
                        "include_predictions": True,
                        "trigger_ai_review": True,
                    },
                )
            finally:
                app.dependency_overrides.clear()

        assert resp.status_code == 200
        data = resp.json()
        assert data["created"] == 5
        assert data["merged"] == 7
        assert data["skipped"] == 9
        assert data["reviewed"] == 7
        assert data["per_building"]["Fox_public_Henry"]["alerts"]["created"] == 1
        assert data["per_building"]["Fox_public_Henry"]["predictions"]["created"] == 4


class TestIncidentService:
    @pytest.mark.asyncio
    async def test_create_or_merge_alert_incident_merges_into_existing_incident(self):
        from app.services.incident_service import create_or_merge_alert_incident

        event = SimpleNamespace(
            id="event-1",
            building_id="Fox_public_Henry",
            meter_device_id="meter-1",
            rule_triggered="flag_electricity",
            hvac_root_cause=None,
            actual_value=82.0,
            expected_value=24.2,
            deviation_pct=238.5,
            data_timestamp=datetime(2026, 3, 3, 8, 0),
        )
        incident = _make_incident(
            anomaly_count=1,
            peak_deviation_pct=100.0,
            first_seen_at=event.data_timestamp,
            last_seen_at=event.data_timestamp,
            continuity_expires_at=event.data_timestamp,
            summary_text="旧摘要",
        )
        work_order = _make_work_order(issue_description="旧摘要")
        db = AsyncMock()

        with patch(
            "app.services.incident_service.check_duplicate_incident_event",
            new=AsyncMock(return_value=False),
        ), patch(
            "app.services.incident_service.find_mergeable_incident",
            new=AsyncMock(return_value=incident),
        ), patch(
            "app.services.incident_service._append_incident_event_link",
            new=AsyncMock(),
        ), patch(
            "app.services.incident_service._get_work_order",
            new=AsyncMock(return_value=work_order),
        ), patch(
            "app.services.incident_service.append_anomaly_evidence_to_work_order",
            new=AsyncMock(),
        ) as mock_append, patch(
            "app.services.incident_service.sync_incident_from_work_order",
            new=AsyncMock(),
        ), patch(
            "app.services.incident_service._write_audit_log",
            new=AsyncMock(),
        ):
            merged_incident, merged_work_order, created_new = await create_or_merge_alert_incident(
                db,
                event=event,
            )

        assert created_new is False
        assert merged_incident is incident
        assert merged_work_order is work_order
        assert incident.anomaly_count == 2
        assert incident.priority == "high"
        assert work_order.issue_description == incident.summary_text
        assert mock_append.await_count == 1

    @pytest.mark.asyncio
    async def test_create_or_merge_alert_incident_reuses_existing_work_order(self):
        from app.services.incident_service import create_or_merge_alert_incident

        event = SimpleNamespace(
            id="event-2",
            building_id="Fox_public_Henry",
            meter_device_id="meter-9",
            rule_triggered="flag_electricity",
            hvac_root_cause=None,
            actual_value=90.0,
            expected_value=30.0,
            deviation_pct=200.0,
            data_timestamp=datetime(2026, 3, 3, 9, 0),
        )
        existing_work_order = _make_work_order(
            id="wo-old",
            ticket_id="WO-OLD-001",
            incident_id=None,
        )
        db = AsyncMock()
        db.add = MagicMock()
        db.flush = AsyncMock()

        with patch(
            "app.services.incident_service.check_duplicate_incident_event",
            new=AsyncMock(return_value=False),
        ), patch(
            "app.services.incident_service.find_mergeable_incident",
            new=AsyncMock(return_value=None),
        ), patch(
            "app.services.incident_service._find_existing_work_order_for_event",
            new=AsyncMock(return_value=existing_work_order),
        ), patch(
            "app.services.incident_service.create_work_order",
            new=AsyncMock(),
        ) as mock_create_work_order, patch(
            "app.services.incident_service.sync_incident_from_work_order",
            new=AsyncMock(),
        ):
            incident, work_order, created_new = await create_or_merge_alert_incident(
                db, event=event
            )

        assert created_new is True
        assert work_order is existing_work_order
        assert incident.current_work_order_id == existing_work_order.id
        assert existing_work_order.incident_id == incident.id
        assert mock_create_work_order.await_count == 0


class TestMigration016:
    def test_split_sql_statements_keeps_do_block_intact(self):
        from scripts.run_migration_016 import _split_sql_statements

        sql = """
        CREATE TABLE sample_a (id INT);
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1) THEN
                PERFORM 1;
            END IF;
        END $$;
        CREATE TABLE sample_b (id INT);
        """

        statements = _split_sql_statements(sql)

        assert len(statements) == 3
        assert statements[0].startswith("CREATE TABLE sample_a")
        assert statements[1].startswith("DO $$")
        assert "END $$" in statements[1]
        assert statements[2].startswith("CREATE TABLE sample_b")
