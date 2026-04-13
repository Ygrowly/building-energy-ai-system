from __future__ import annotations

import pytest

from app.db import notification_schema


@pytest.mark.asyncio
async def test_ensure_notification_tables_creates_tables_columns_and_indexes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    statements: list[str] = []

    class _FakeConn:
        async def execute(self, clause) -> None:
            statements.append(str(clause))

    class _FakeBegin:
        async def __aenter__(self) -> _FakeConn:
            return _FakeConn()

        async def __aexit__(self, exc_type, exc, tb) -> None:
            return None

    class _FakeEngine:
        def begin(self) -> _FakeBegin:
            return _FakeBegin()

    async def _run_startup_db_op_with_retry(_name, operation, **_kwargs) -> None:
        await operation()

    monkeypatch.setattr(notification_schema, "engine", _FakeEngine())
    monkeypatch.setattr(
        notification_schema,
        "_run_startup_db_op_with_retry",
        _run_startup_db_op_with_retry,
    )

    await notification_schema.ensure_notification_tables()

    sql = "\n".join(statements)
    assert "CREATE TABLE IF NOT EXISTS notification_records" in sql
    assert "CREATE TABLE IF NOT EXISTS notification_recipients" in sql
    assert "ADD COLUMN IF NOT EXISTS payload_json" in sql
    assert "ADD COLUMN IF NOT EXISTS recipient_role" in sql
    assert "CREATE INDEX IF NOT EXISTS idx_notification_record_category_time" in sql
    assert "CREATE INDEX IF NOT EXISTS idx_notification_recipient_user_read" in sql
