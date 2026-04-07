from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest


ROOT_DIR = Path(__file__).resolve().parents[1]


def _load_script_module(module_name: str, relative_path: str):
    path = ROOT_DIR / relative_path
    spec = importlib.util.spec_from_file_location(module_name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


check_migration_019 = _load_script_module("check_migration_019_test", "scripts/check_migration_019.py")
repair_019 = _load_script_module("repair_019_test", "scripts/repair_019_reset_orphan_dispatched.py")


class _FakeConn:
    def __init__(self) -> None:
        self.closed = False

    async def close(self) -> None:
        self.closed = True


def test_check_migration_019_build_report_flags_unrecoverable_data() -> None:
    report = check_migration_019.build_report(
        schema={
            "dispatch_tasks_exists": True,
            "dispatch_events_exists": True,
            "work_order_audit_log_exists": False,
            "work_orders.current_dispatch_id": True,
            "work_orders.pending_dispatch_at": True,
            "anomaly_incidents.current_dispatch_id": True,
            "anomaly_incidents.current_dispatch_status": True,
        },
        metrics={
            "work_orders_total": 12,
            "anomaly_incidents_total": 4,
            "users_total": 3,
            "worker_profiles_total": 1,
            "dispatch_tasks_total": 0,
            "dispatch_events_total": 0,
            "dispatch_tasks_legacy_backfill_total": 0,
            "work_orders_with_current_dispatch": 0,
            "incidents_with_current_dispatch": 0,
            "recoverable_backfill_candidates": 2,
            "dispatched_without_assignment": 5,
            "pending_dispatch_missing_timestamp": 1,
            "work_orders_broken_current_dispatch_ref": 0,
            "incidents_broken_current_dispatch_ref": 0,
            "duplicate_current_dispatch_tasks": 0,
            "incident_projection_mismatch": 1,
        },
        status_distribution={"pending_dispatch": 7, "dispatched": 5},
        samples={
            "recoverable_backfill_candidates": [{"ticket_id": "WO-001"}],
            "unrecoverable_dispatched_without_assignment": [{"ticket_id": "WO-002"}],
            "incident_projection_mismatch": [{"incident_id": "INC-1"}],
        },
    )

    assert any("缺少 work_order_audit_log 表" in item for item in report["findings"])
    assert any("不可直接回填旧工单" in item for item in report["findings"])
    assert any("第三阶段执行层尚未在真实数据上形成闭环" in item for item in report["findings"])
    assert any("外部日志恢复责任人" in item for item in report["recommendations"])
    assert any("修复 incident 读模型投影" in item for item in report["recommendations"])


def test_repair_019_build_backup_payload_counts_rows() -> None:
    payload = repair_019.build_backup_payload(
        {
            "candidate_rows": [{"id": "wo-1"}, {"id": "wo-2"}],
            "incident_rows": [{"id": "inc-1"}],
            "risky_rows": [{"id": "wo-risk"}],
        }
    )

    assert payload["candidate_count"] == 2
    assert payload["incident_count"] == 1
    assert payload["risky_count"] == 1
    assert payload["candidate_work_orders"][0]["id"] == "wo-1"


@pytest.mark.asyncio
async def test_repair_019_async_main_aborts_when_risky_rows(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_conn = _FakeConn()
    write_backup_called = False

    async def _fake_connect():
        return fake_conn

    async def _fake_collect(_conn):
        return {
            "broken_rows": [{"id": "wo-1"}],
            "candidate_rows": [],
            "risky_rows": [{"id": "wo-risk"}],
            "incident_rows": [],
        }

    def _fake_write_backup(_payload):
        nonlocal write_backup_called
        write_backup_called = True
        return ROOT_DIR / "runtime" / "noop.json"

    monkeypatch.setattr(repair_019, "_connect", _fake_connect)
    monkeypatch.setattr(repair_019, "collect_candidates", _fake_collect)
    monkeypatch.setattr(repair_019, "write_backup_file", _fake_write_backup)
    monkeypatch.setattr(repair_019, "print_summary", lambda *args, **kwargs: None)

    rc = await repair_019._async_main(SimpleNamespace(apply=False))

    assert rc == 2
    assert write_backup_called is False
    assert fake_conn.closed is True


@pytest.mark.asyncio
async def test_repair_019_async_main_apply_calls_repair(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_conn = _FakeConn()
    applied_ids: list[str] = []

    async def _fake_connect():
        return fake_conn

    async def _fake_collect(_conn):
        return {
            "broken_rows": [{"id": "wo-1"}],
            "candidate_rows": [{"id": "wo-1"}, {"id": "wo-2"}],
            "risky_rows": [],
            "incident_rows": [{"id": "inc-1"}],
        }

    async def _fake_apply(_conn, candidate_ids):
        applied_ids.extend(candidate_ids)
        return {"work_orders_updated": 2, "incidents_updated": 1}

    monkeypatch.setattr(repair_019, "_connect", _fake_connect)
    monkeypatch.setattr(repair_019, "collect_candidates", _fake_collect)
    monkeypatch.setattr(repair_019, "apply_repair", _fake_apply)
    monkeypatch.setattr(repair_019, "write_backup_file", lambda _payload: ROOT_DIR / "runtime" / "noop.json")
    monkeypatch.setattr(repair_019, "print_summary", lambda *args, **kwargs: None)

    rc = await repair_019._async_main(SimpleNamespace(apply=True))

    assert rc == 0
    assert applied_ids == ["wo-1", "wo-2"]
    assert fake_conn.closed is True
