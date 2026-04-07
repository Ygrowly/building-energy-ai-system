from __future__ import annotations

from pathlib import Path

from scripts.run_sql_migration import _split_sql_statements


ROOT_DIR = Path(__file__).resolve().parents[1]
MIGRATIONS_DIR = ROOT_DIR / "migrations"


def _migration_text(name: str) -> str:
    return (MIGRATIONS_DIR / name).read_text(encoding="utf-8")


def test_dispatch_migration_files_exist_in_sequence() -> None:
    expected = [
        "017_work_order_dispatch_phase1.sql",
        "018_worker_dispatch_profiles.sql",
        "019_dispatch_tasks_phase3.sql",
        "020_dispatch_hall_phase1.sql",
        "021_dispatch_query_indexes.sql",
        "022_dispatch_hall_visibility_scope_length.sql",
    ]
    actual = [
        path.name
        for path in sorted(MIGRATIONS_DIR.glob("*.sql"))
        if 17 <= int(path.name.split("_", 1)[0]) <= 22
    ]
    assert actual == expected


def test_migration_017_contains_pending_dispatch_transition_and_dispatch_timestamps() -> None:
    sql = _migration_text("017_work_order_dispatch_phase1.sql")

    assert "ALTER TABLE work_orders" in sql
    assert "ADD COLUMN IF NOT EXISTS assigned_at" in sql
    assert "ADD COLUMN IF NOT EXISTS accepted_at" in sql
    assert "ADD COLUMN IF NOT EXISTS arrived_at" in sql
    assert "ADD COLUMN IF NOT EXISTS processing_started_at" in sql
    assert "SET status = 'pending_dispatch'" in sql
    assert "WHERE status = 'auto_approved'" in sql


def test_migration_018_creates_worker_profile_dependency_chain() -> None:
    sql = _migration_text("018_worker_dispatch_profiles.sql")
    statements = _split_sql_statements(sql)

    assert any("CREATE TABLE IF NOT EXISTS worker_teams" in stmt for stmt in statements)
    assert any("CREATE TABLE IF NOT EXISTS worker_skills" in stmt for stmt in statements)
    assert any("CREATE TABLE IF NOT EXISTS worker_profiles" in stmt for stmt in statements)
    assert any("CREATE TABLE IF NOT EXISTS worker_profile_skills" in stmt for stmt in statements)
    assert any("INSERT INTO worker_profiles" in stmt for stmt in statements)
    assert any("WHERE u.role = 'ops'" in stmt for stmt in statements)
    assert any("INSERT INTO worker_profile_skills" in stmt for stmt in statements)


def test_migration_019_keeps_backfill_do_block_and_dispatch_dependencies() -> None:
    sql = _migration_text("019_dispatch_tasks_phase3.sql")
    statements = _split_sql_statements(sql)

    assert any("CREATE TABLE IF NOT EXISTS dispatch_tasks" in stmt for stmt in statements)
    assert any("CREATE TABLE IF NOT EXISTS dispatch_events" in stmt for stmt in statements)

    do_blocks = [stmt for stmt in statements if stmt.startswith("DO $$")]
    assert len(do_blocks) == 1
    backfill_block = do_blocks[0]
    assert "LEFT JOIN worker_profiles wp ON wp.user_id = wo.assigned_to" in backfill_block
    assert "WHERE wo.assigned_to IS NOT NULL" in backfill_block
    assert "wo.current_dispatch_id IS NULL" in backfill_block
    assert "wo.status IN ('dispatched', 'completed', 'false_alarm', 'escalated', 'closed')" in backfill_block
    assert "INSERT INTO dispatch_tasks" in backfill_block
    assert "UPDATE work_orders" in backfill_block
    assert "UPDATE anomaly_incidents" in backfill_block


def test_migration_019_adds_current_dispatch_foreign_keys_after_table_creation() -> None:
    sql = _migration_text("019_dispatch_tasks_phase3.sql")
    dispatch_table_pos = sql.index("CREATE TABLE IF NOT EXISTS dispatch_tasks")
    fk_work_order_pos = sql.index("ADD CONSTRAINT fk_work_orders_current_dispatch")
    fk_incident_pos = sql.index("ADD CONSTRAINT fk_incidents_current_dispatch")

    assert dispatch_table_pos < fk_work_order_pos < fk_incident_pos
    assert "FOREIGN KEY (current_dispatch_id) REFERENCES dispatch_tasks(id)" in sql


def test_migration_020_creates_dispatch_hall_tables_and_indexes() -> None:
    sql = _migration_text("020_dispatch_hall_phase1.sql")
    statements = _split_sql_statements(sql)

    assert any("CREATE TABLE IF NOT EXISTS dispatch_hall_entries" in stmt for stmt in statements)
    assert any("CREATE TABLE IF NOT EXISTS dispatch_hall_applications" in stmt for stmt in statements)
    assert any("REFERENCES dispatch_tasks(id)" in stmt for stmt in statements)
    assert any("REFERENCES worker_teams(id)" in stmt for stmt in statements)
    assert any("CREATE INDEX IF NOT EXISTS idx_dispatch_hall_type_status" in stmt for stmt in statements)
    assert any("CREATE INDEX IF NOT EXISTS idx_dispatch_hall_application_entry_status" in stmt for stmt in statements)


def test_migration_021_adds_dispatch_query_indexes() -> None:
    sql = _migration_text("021_dispatch_query_indexes.sql")
    statements = _split_sql_statements(sql)

    assert any("CREATE INDEX IF NOT EXISTS idx_incident_workflow_last_seen" in stmt for stmt in statements)
    assert any("CREATE INDEX IF NOT EXISTS idx_incident_assignee_last_seen" in stmt for stmt in statements)
    assert any("CREATE INDEX IF NOT EXISTS idx_wo_status_pending_dispatch_created" in stmt for stmt in statements)
    assert any("CREATE INDEX IF NOT EXISTS idx_dispatch_assignee_current_time" in stmt for stmt in statements)
    assert any("CREATE INDEX IF NOT EXISTS idx_dispatch_current_status_assigned_at" in stmt for stmt in statements)
    assert any("CREATE INDEX IF NOT EXISTS idx_dispatch_hall_status_type_created" in stmt for stmt in statements)
    assert any("CREATE INDEX IF NOT EXISTS idx_dispatch_hall_application_entry_created" in stmt for stmt in statements)


def test_migration_022_widens_dispatch_hall_visibility_scope() -> None:
    sql = _migration_text("022_dispatch_hall_visibility_scope_length.sql")

    assert "ALTER TABLE dispatch_hall_entries" in sql
    assert "ALTER COLUMN visibility_scope TYPE VARCHAR(32)" in sql
