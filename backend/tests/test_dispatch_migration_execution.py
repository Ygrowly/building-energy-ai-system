from __future__ import annotations

import asyncio
from datetime import datetime
import hashlib
import os
import shutil
import socket
import subprocess
import time
import uuid
from pathlib import Path
from typing import Any

import asyncpg
import pytest
import pytest_asyncio

from app.db.session import _build_connect_args
from scripts.run_sql_migration import _split_sql_statements


pytestmark = pytest.mark.integration

ROOT_DIR = Path(__file__).resolve().parents[1]
MIGRATIONS_DIR = ROOT_DIR / "migrations"
ENV_PATH = ROOT_DIR / ".env"


def _docker_available() -> bool:
    if shutil.which("docker") is None:
        return False
    result = subprocess.run(
        ["docker", "info"],
        capture_output=True,
        text=True,
        check=False,
    )
    return result.returncode == 0


def _pick_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


async def _wait_for_postgres(dsn: str, timeout_seconds: int = 60) -> None:
    started_at = time.time()
    last_error: Exception | None = None
    while time.time() - started_at < timeout_seconds:
        try:
            conn = await asyncpg.connect(dsn)
            await conn.close()
            return
        except Exception as exc:  # pragma: no cover - only used during container bootstrap
            last_error = exc
            await asyncio.sleep(1)
    raise RuntimeError(f"临时 Postgres 未在 {timeout_seconds}s 内就绪: {last_error}")


def _docker_run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["docker", *args],
        capture_output=True,
        text=True,
        check=False,
    )


def _load_env(path: Path) -> dict[str, str]:
    env: dict[str, str] = {}
    if not path.exists():
        return env
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        env[key.strip()] = value.strip()
    return env


def _configured_database_connection() -> tuple[str, dict[str, Any]]:
    env = _load_env(ENV_PATH)
    database_url = env.get("DATABASE_URL") or os.environ.get("DATABASE_URL")
    sync_database_url = env.get("SYNC_DATABASE_URL") or os.environ.get("SYNC_DATABASE_URL")
    connect_source = database_url or sync_database_url
    if not connect_source:
        raise RuntimeError("未找到可用的 DATABASE_URL / SYNC_DATABASE_URL，无法执行迁移集成测试")

    dsn = (sync_database_url or connect_source).replace("postgresql+asyncpg://", "postgresql://")
    connect_args = _build_connect_args(connect_source)
    return dsn, {
        key: value
        for key, value in connect_args.items()
        if key in {"ssl", "server_settings"}
    }


@pytest.fixture(scope="module")
def base_database_connection():
    if _docker_available():
        host_port = _pick_free_port()
        container_name = f"dispatch-migrate-{uuid.uuid4().hex[:8]}"
        image = "postgres:16-alpine"
        run_result = _docker_run(
            "run",
            "-d",
            "--rm",
            "--name",
            container_name,
            "-e",
            "POSTGRES_PASSWORD=postgres",
            "-e",
            "POSTGRES_DB=dispatch_test",
            "-p",
            f"{host_port}:5432",
            image,
        )
        if run_result.returncode == 0:
            dsn = f"postgresql://postgres:postgres@127.0.0.1:{host_port}/dispatch_test"
            try:
                asyncio.run(_wait_for_postgres(dsn))
                yield {
                    "dsn": dsn,
                    "connect_args": {},
                }
                return
            finally:
                _docker_run("rm", "-f", container_name)

    dsn, connect_args = _configured_database_connection()
    yield {
        "dsn": dsn,
        "connect_args": connect_args,
    }


@pytest_asyncio.fixture
async def migration_conn(base_database_connection):
    conn = await asyncpg.connect(
        base_database_connection["dsn"],
        **base_database_connection["connect_args"],
    )
    schema_name = f"dispatch_migrate_{uuid.uuid4().hex[:8]}"
    try:
        await conn.execute(f"CREATE SCHEMA {schema_name}")
        await conn.execute(f"SET search_path TO {schema_name}")
        yield conn
    finally:
        try:
            await conn.execute("SET search_path TO public")
            await conn.execute(f"DROP SCHEMA IF EXISTS {schema_name} CASCADE")
        finally:
            await conn.close()


async def _execute_sql_text(conn: asyncpg.Connection, sql_text: str) -> None:
    for statement in _split_sql_statements(sql_text):
        await conn.execute(statement)


async def _apply_migration(conn: asyncpg.Connection, migration_name: str) -> None:
    sql_text = (MIGRATIONS_DIR / migration_name).read_text(encoding="utf-8")
    await _execute_sql_text(conn, sql_text)


async def _create_pre_dispatch_base_schema(conn: asyncpg.Connection) -> None:
    await _execute_sql_text(
        conn,
        """
        CREATE TABLE users (
            id TEXT PRIMARY KEY,
            username VARCHAR(50) NOT NULL,
            role VARCHAR(20) NOT NULL DEFAULT 'resident',
            is_active BOOLEAN NOT NULL DEFAULT TRUE
        );

        CREATE TABLE work_orders (
            id TEXT PRIMARY KEY,
            ticket_id VARCHAR(64) NOT NULL UNIQUE,
            status VARCHAR(32) NOT NULL DEFAULT 'pending_review',
            priority VARCHAR(16) NOT NULL DEFAULT 'medium',
            incident_id TEXT,
            ai_decision VARCHAR(16),
            ai_reviewed_at TIMESTAMPTZ,
            worker_result VARCHAR(32),
            worker_notes TEXT,
            worker_feedback_at TIMESTAMPTZ,
            assigned_to TEXT REFERENCES users(id) ON DELETE SET NULL,
            created_at TIMESTAMPTZ NOT NULL,
            updated_at TIMESTAMPTZ NOT NULL,
            closed_at TIMESTAMPTZ
        );

        CREATE TABLE anomaly_incidents (
            id TEXT PRIMARY KEY,
            incident_id VARCHAR(64) NOT NULL UNIQUE,
            current_work_order_id TEXT REFERENCES work_orders(id) ON DELETE SET NULL,
            workflow_status VARCHAR(32),
            incident_status VARCHAR(32) NOT NULL DEFAULT 'open',
            first_seen_at TIMESTAMPTZ,
            last_seen_at TIMESTAMPTZ,
            is_active BOOLEAN NOT NULL DEFAULT TRUE,
            created_at TIMESTAMPTZ NOT NULL,
            updated_at TIMESTAMPTZ NOT NULL
        );
        """,
    )


def _legacy_dispatch_id(work_order_id: str) -> str:
    return hashlib.md5(f"{work_order_id}-dispatch-1".encode("utf-8")).hexdigest()


def _dt(value: str) -> datetime:
    return datetime.fromisoformat(value)


@pytest.mark.asyncio
async def test_migrations_017_018_019_020_apply_cleanly_on_minimal_new_environment(
    migration_conn: asyncpg.Connection,
) -> None:
    await _create_pre_dispatch_base_schema(migration_conn)

    await migration_conn.execute(
        """
        INSERT INTO users (id, username, role, is_active)
        VALUES ('ops-1', '张工', 'ops', TRUE)
        """
    )
    await migration_conn.execute(
        """
        INSERT INTO work_orders (
            id, ticket_id, status, priority, incident_id, ai_reviewed_at, created_at, updated_at
        )
        VALUES (
            'wo-auto', 'WO-AUTO-001', 'auto_approved', 'high', 'inc-auto',
            TIMESTAMPTZ '2026-04-01 08:00:00+00',
            TIMESTAMPTZ '2026-04-01 07:50:00+00',
            TIMESTAMPTZ '2026-04-01 08:05:00+00'
        )
        """
    )
    await migration_conn.execute(
        """
        INSERT INTO anomaly_incidents (
            id, incident_id, current_work_order_id, workflow_status, incident_status, is_active, created_at, updated_at
        )
        VALUES (
            'inc-auto', 'INC-AUTO-001', 'wo-auto', 'pending_review', 'open', TRUE,
            TIMESTAMPTZ '2026-04-01 07:45:00+00',
            TIMESTAMPTZ '2026-04-01 08:05:00+00'
        )
        """
    )

    for migration_name in (
        "017_work_order_dispatch_phase1.sql",
        "018_worker_dispatch_profiles.sql",
        "019_dispatch_tasks_phase3.sql",
        "020_dispatch_hall_phase1.sql",
        "021_dispatch_query_indexes.sql",
        "022_dispatch_hall_visibility_scope_length.sql",
    ):
        await _apply_migration(migration_conn, migration_name)

    migrated = await migration_conn.fetchrow(
        """
        SELECT status, pending_dispatch_at, current_dispatch_id
        FROM work_orders
        WHERE id = 'wo-auto'
        """
    )
    assert migrated is not None
    assert migrated["status"] == "pending_dispatch"
    assert migrated["pending_dispatch_at"] is not None
    assert migrated["current_dispatch_id"] is None

    worker_profile_count = await migration_conn.fetchval("SELECT COUNT(*) FROM worker_profiles")
    dispatch_task_count = await migration_conn.fetchval("SELECT COUNT(*) FROM dispatch_tasks")
    hall_entry_count = await migration_conn.fetchval("SELECT COUNT(*) FROM dispatch_hall_entries")
    hall_application_count = await migration_conn.fetchval("SELECT COUNT(*) FROM dispatch_hall_applications")
    default_team_name = await migration_conn.fetchval(
        "SELECT name FROM worker_teams WHERE team_code = 'general_ops'"
    )
    visibility_scope_length = await migration_conn.fetchval(
        """
        SELECT character_maximum_length
        FROM information_schema.columns
        WHERE table_schema = current_schema()
          AND table_name = 'dispatch_hall_entries'
          AND column_name = 'visibility_scope'
        """
    )

    assert int(worker_profile_count or 0) == 1
    assert int(dispatch_task_count or 0) == 0
    assert int(hall_entry_count or 0) == 0
    assert int(hall_application_count or 0) == 0
    assert default_team_name == "综合运维班"
    assert visibility_scope_length == 32

    index_names = {
        row["indexname"]
        for row in await migration_conn.fetch(
            """
            SELECT indexname
            FROM pg_indexes
            WHERE schemaname = current_schema()
              AND indexname IN (
                'idx_incident_workflow_last_seen',
                'idx_incident_assignee_last_seen',
                'idx_wo_status_pending_dispatch_created',
                'idx_dispatch_assignee_current_time',
                'idx_dispatch_current_status_assigned_at',
                'idx_dispatch_hall_status_type_created',
                'idx_dispatch_hall_application_entry_created'
              )
            """
        )
    }
    assert index_names == {
        "idx_incident_workflow_last_seen",
        "idx_incident_assignee_last_seen",
        "idx_wo_status_pending_dispatch_created",
        "idx_dispatch_assignee_current_time",
        "idx_dispatch_current_status_assigned_at",
        "idx_dispatch_hall_status_type_created",
        "idx_dispatch_hall_application_entry_created",
    }


@pytest.mark.asyncio
async def test_migration_019_backfills_legacy_dispatch_projection_correctly(
    migration_conn: asyncpg.Connection,
) -> None:
    await _create_pre_dispatch_base_schema(migration_conn)

    await migration_conn.executemany(
        """
        INSERT INTO users (id, username, role, is_active)
        VALUES ($1, $2, 'ops', TRUE)
        """,
        [
            ("ops-1", "张工"),
            ("ops-2", "李工"),
        ],
    )

    await migration_conn.executemany(
        """
        INSERT INTO work_orders (
            id, ticket_id, status, priority, incident_id, ai_reviewed_at, worker_result, worker_notes,
            worker_feedback_at, assigned_to, created_at, updated_at, closed_at
        )
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13)
        """,
        [
            (
                "wo-processing",
                "WO-LEGACY-001",
                "dispatched",
                "high",
                "inc-processing",
                _dt("2026-04-01T08:00:00+00:00"),
                None,
                "现场已接入，等待进一步处理",
                None,
                "ops-1",
                _dt("2026-04-01T07:45:00+00:00"),
                _dt("2026-04-01T08:10:00+00:00"),
                None,
            ),
            (
                "wo-completed",
                "WO-LEGACY-002",
                "completed",
                "medium",
                "inc-completed",
                _dt("2026-04-01T09:00:00+00:00"),
                "fixed",
                "阀门卡滞已处理，现场恢复正常",
                _dt("2026-04-01T10:20:00+00:00"),
                "ops-2",
                _dt("2026-04-01T08:45:00+00:00"),
                _dt("2026-04-01T10:20:00+00:00"),
                None,
            ),
            (
                "wo-escalated",
                "WO-LEGACY-003",
                "escalated",
                "low",
                "inc-escalated",
                _dt("2026-04-01T11:00:00+00:00"),
                "escalated",
                "需升级给专家组继续处理",
                _dt("2026-04-01T11:40:00+00:00"),
                "ops-1",
                _dt("2026-04-01T10:45:00+00:00"),
                _dt("2026-04-01T11:40:00+00:00"),
                _dt("2026-04-01T11:40:00+00:00"),
            ),
        ],
    )

    await migration_conn.executemany(
        """
        INSERT INTO anomaly_incidents (
            id, incident_id, current_work_order_id, workflow_status, incident_status, is_active, created_at, updated_at
        )
        VALUES ($1, $2, $3, $4, 'open', TRUE, $5, $6)
        """,
        [
            (
                "inc-processing",
                "INC-LEGACY-001",
                "wo-processing",
                "dispatched",
                _dt("2026-04-01T07:40:00+00:00"),
                _dt("2026-04-01T08:10:00+00:00"),
            ),
            (
                "inc-completed",
                "INC-LEGACY-002",
                "wo-completed",
                "completed",
                _dt("2026-04-01T08:40:00+00:00"),
                _dt("2026-04-01T10:20:00+00:00"),
            ),
            (
                "inc-escalated",
                "INC-LEGACY-003",
                "wo-escalated",
                "escalated",
                _dt("2026-04-01T10:40:00+00:00"),
                _dt("2026-04-01T11:40:00+00:00"),
            ),
        ],
    )

    await _apply_migration(migration_conn, "017_work_order_dispatch_phase1.sql")
    await migration_conn.execute(
        """
        UPDATE work_orders
        SET
            accepted_at = CASE id
                WHEN 'wo-processing' THEN TIMESTAMPTZ '2026-04-01 08:10:00+00'
                WHEN 'wo-completed' THEN TIMESTAMPTZ '2026-04-01 09:10:00+00'
                WHEN 'wo-escalated' THEN TIMESTAMPTZ '2026-04-01 11:05:00+00'
                ELSE accepted_at
            END,
            arrived_at = CASE id
                WHEN 'wo-processing' THEN TIMESTAMPTZ '2026-04-01 08:20:00+00'
                WHEN 'wo-completed' THEN TIMESTAMPTZ '2026-04-01 09:20:00+00'
                ELSE arrived_at
            END,
            processing_started_at = CASE id
                WHEN 'wo-processing' THEN TIMESTAMPTZ '2026-04-01 08:30:00+00'
                WHEN 'wo-completed' THEN TIMESTAMPTZ '2026-04-01 09:30:00+00'
                ELSE processing_started_at
            END
        WHERE id IN ('wo-processing', 'wo-completed', 'wo-escalated')
        """
    )

    await _apply_migration(migration_conn, "018_worker_dispatch_profiles.sql")
    await _apply_migration(migration_conn, "019_dispatch_tasks_phase3.sql")
    await _apply_migration(migration_conn, "020_dispatch_hall_phase1.sql")
    await _apply_migration(migration_conn, "021_dispatch_query_indexes.sql")
    await _apply_migration(migration_conn, "022_dispatch_hall_visibility_scope_length.sql")

    worker_profiles = await migration_conn.fetchval("SELECT COUNT(*) FROM worker_profiles")
    dispatch_task_count = await migration_conn.fetchval("SELECT COUNT(*) FROM dispatch_tasks")
    dispatch_event_count = await migration_conn.fetchval("SELECT COUNT(*) FROM dispatch_events")
    hall_entry_count = await migration_conn.fetchval("SELECT COUNT(*) FROM dispatch_hall_entries")
    hall_application_count = await migration_conn.fetchval("SELECT COUNT(*) FROM dispatch_hall_applications")
    assert int(worker_profiles or 0) == 2
    assert int(dispatch_task_count or 0) == 3
    assert int(dispatch_event_count or 0) == 0
    assert int(hall_entry_count or 0) == 0
    assert int(hall_application_count or 0) == 0

    processing_dispatch = await migration_conn.fetchrow(
        """
        SELECT *
        FROM dispatch_tasks
        WHERE work_order_id = 'wo-processing'
        """
    )
    completed_dispatch = await migration_conn.fetchrow(
        """
        SELECT *
        FROM dispatch_tasks
        WHERE work_order_id = 'wo-completed'
        """
    )
    escalated_dispatch = await migration_conn.fetchrow(
        """
        SELECT *
        FROM dispatch_tasks
        WHERE work_order_id = 'wo-escalated'
        """
    )

    assert processing_dispatch is not None
    assert completed_dispatch is not None
    assert escalated_dispatch is not None

    assert processing_dispatch["id"] == _legacy_dispatch_id("wo-processing")
    assert processing_dispatch["attempt_no"] == 1
    assert processing_dispatch["dispatch_mode"] == "legacy_backfill"
    assert processing_dispatch["dispatch_status"] == "processing"
    assert processing_dispatch["is_current"] is True
    assert processing_dispatch["assigned_to"] == "ops-1"
    assert processing_dispatch["assigned_team_id"] == "team_ops_general"
    assert processing_dispatch["selection_reason"] == "由 019 迁移从历史工单回填"
    assert processing_dispatch["assigned_at"].isoformat() == "2026-04-01T08:00:00+00:00"
    assert processing_dispatch["processing_started_at"].isoformat() == "2026-04-01T08:30:00+00:00"

    assert completed_dispatch["id"] == _legacy_dispatch_id("wo-completed")
    assert completed_dispatch["attempt_no"] == 1
    assert completed_dispatch["dispatch_status"] == "completed"
    assert completed_dispatch["worker_result"] == "fixed"
    assert completed_dispatch["completed_at"].isoformat() == "2026-04-01T10:20:00+00:00"
    assert completed_dispatch["closed_at"].isoformat() == "2026-04-01T10:20:00+00:00"

    assert escalated_dispatch["id"] == _legacy_dispatch_id("wo-escalated")
    assert escalated_dispatch["attempt_no"] == 1
    assert escalated_dispatch["dispatch_status"] == "escalated"
    assert escalated_dispatch["worker_result"] == "escalated"
    assert escalated_dispatch["closed_at"].isoformat() == "2026-04-01T11:40:00+00:00"

    work_orders = await migration_conn.fetch(
        """
        SELECT id, current_dispatch_id
        FROM work_orders
        ORDER BY id
        """
    )
    assert {row["id"]: row["current_dispatch_id"] for row in work_orders} == {
        "wo-completed": _legacy_dispatch_id("wo-completed"),
        "wo-escalated": _legacy_dispatch_id("wo-escalated"),
        "wo-processing": _legacy_dispatch_id("wo-processing"),
    }

    incidents = await migration_conn.fetch(
        """
        SELECT id, current_dispatch_id, current_dispatch_status, current_assigned_to,
               current_assigned_team_id, latest_dispatch_note
        FROM anomaly_incidents
        ORDER BY id
        """
    )
    incident_map = {row["id"]: row for row in incidents}

    assert incident_map["inc-processing"]["current_dispatch_id"] == _legacy_dispatch_id("wo-processing")
    assert incident_map["inc-processing"]["current_dispatch_status"] == "processing"
    assert incident_map["inc-processing"]["current_assigned_to"] == "ops-1"
    assert incident_map["inc-processing"]["current_assigned_team_id"] == "team_ops_general"
    assert incident_map["inc-processing"]["latest_dispatch_note"] == "现场已接入，等待进一步处理"

    assert incident_map["inc-completed"]["current_dispatch_id"] == _legacy_dispatch_id("wo-completed")
    assert incident_map["inc-completed"]["current_dispatch_status"] == "completed"
    assert incident_map["inc-completed"]["current_assigned_to"] == "ops-2"
    assert incident_map["inc-completed"]["current_assigned_team_id"] == "team_ops_general"
    assert incident_map["inc-completed"]["latest_dispatch_note"] == "阀门卡滞已处理，现场恢复正常"

    assert incident_map["inc-escalated"]["current_dispatch_id"] == _legacy_dispatch_id("wo-escalated")
    assert incident_map["inc-escalated"]["current_dispatch_status"] == "escalated"
    assert incident_map["inc-escalated"]["current_assigned_to"] == "ops-1"

    hall_index_names = {
        row["indexname"]
        for row in await migration_conn.fetch(
            """
            SELECT indexname
            FROM pg_indexes
            WHERE schemaname = current_schema()
              AND indexname IN (
                'idx_dispatch_hall_status_type_created',
                'idx_dispatch_hall_application_entry_created'
              )
            """
        )
    }
    assert hall_index_names == {
        "idx_dispatch_hall_status_type_created",
        "idx_dispatch_hall_application_entry_created",
    }
    assert incident_map["inc-escalated"]["current_assigned_team_id"] == "team_ops_general"
    assert incident_map["inc-escalated"]["latest_dispatch_note"] == "需升级给专家组继续处理"
