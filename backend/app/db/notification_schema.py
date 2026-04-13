from __future__ import annotations

from sqlalchemy import text

from app.db.session import _run_startup_db_op_with_retry, engine, logger


async def ensure_notification_tables() -> None:
    """
    Ensure notification center tables exist before routes start reading them.

    Historical deployments may miss migration 025, which causes
    /api/notifications to fail with 500 and surface as a browser CORS/network
    error on the mobile H5 client.
    """

    async def _op() -> None:
        async with engine.begin() as conn:
            await conn.execute(
                text(
                    """
                    CREATE TABLE IF NOT EXISTS notification_records (
                        id VARCHAR PRIMARY KEY,
                        category VARCHAR(32) NOT NULL,
                        event_type VARCHAR(64) NOT NULL,
                        source_type VARCHAR(64) NOT NULL,
                        source_id VARCHAR(128) NOT NULL,
                        aggregate_type VARCHAR(64) NOT NULL,
                        aggregate_id VARCHAR(128) NOT NULL,
                        title VARCHAR(255) NOT NULL,
                        body TEXT NOT NULL,
                        severity VARCHAR(16) NOT NULL DEFAULT 'info',
                        payload_json TEXT NULL,
                        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                    )
                    """
                )
            )
            await conn.execute(
                text(
                    """
                    CREATE TABLE IF NOT EXISTS notification_recipients (
                        id VARCHAR PRIMARY KEY,
                        notification_id VARCHAR NOT NULL REFERENCES notification_records(id) ON DELETE CASCADE,
                        user_id VARCHAR NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                        recipient_role VARCHAR(20) NOT NULL,
                        source_type VARCHAR(64) NOT NULL,
                        source_id VARCHAR(128) NOT NULL,
                        is_read BOOLEAN NOT NULL DEFAULT FALSE,
                        read_at TIMESTAMPTZ NULL,
                        delivered_at TIMESTAMPTZ NULL,
                        last_pushed_at TIMESTAMPTZ NULL,
                        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                    )
                    """
                )
            )

            # Backfill columns for partially rolled-out schemas so ORM SELECTs
            # do not fail with UndefinedColumnError.
            await conn.execute(
                text(
                    """
                    ALTER TABLE notification_records
                    ADD COLUMN IF NOT EXISTS payload_json TEXT NULL
                    """
                )
            )
            await conn.execute(
                text(
                    """
                    ALTER TABLE notification_recipients
                    ADD COLUMN IF NOT EXISTS recipient_role VARCHAR(20)
                    """
                )
            )
            await conn.execute(
                text(
                    """
                    UPDATE notification_recipients
                    SET recipient_role = COALESCE(NULLIF(recipient_role, ''), 'ops')
                    WHERE recipient_role IS NULL OR recipient_role = ''
                    """
                )
            )
            await conn.execute(
                text(
                    """
                    ALTER TABLE notification_recipients
                    ALTER COLUMN recipient_role SET NOT NULL
                    """
                )
            )
            await conn.execute(
                text(
                    """
                    ALTER TABLE notification_recipients
                    ADD COLUMN IF NOT EXISTS delivered_at TIMESTAMPTZ NULL
                    """
                )
            )
            await conn.execute(
                text(
                    """
                    ALTER TABLE notification_recipients
                    ADD COLUMN IF NOT EXISTS last_pushed_at TIMESTAMPTZ NULL
                    """
                )
            )

            await conn.execute(
                text(
                    """
                    CREATE UNIQUE INDEX IF NOT EXISTS uq_notification_record_source_idx
                    ON notification_records (source_type, source_id)
                    """
                )
            )
            await conn.execute(
                text(
                    """
                    CREATE UNIQUE INDEX IF NOT EXISTS uq_notification_recipient_source_user_idx
                    ON notification_recipients (source_type, source_id, user_id)
                    """
                )
            )
            await conn.execute(
                text(
                    """
                    CREATE UNIQUE INDEX IF NOT EXISTS uq_notification_recipient_notification_user_idx
                    ON notification_recipients (notification_id, user_id)
                    """
                )
            )
            await conn.execute(
                text(
                    """
                    CREATE INDEX IF NOT EXISTS idx_notification_record_category_time
                    ON notification_records (category, created_at DESC)
                    """
                )
            )
            await conn.execute(
                text(
                    """
                    CREATE INDEX IF NOT EXISTS idx_notification_record_aggregate
                    ON notification_records (aggregate_type, aggregate_id)
                    """
                )
            )
            await conn.execute(
                text(
                    """
                    CREATE INDEX IF NOT EXISTS idx_notification_recipient_user_time
                    ON notification_recipients (user_id, created_at DESC)
                    """
                )
            )
            await conn.execute(
                text(
                    """
                    CREATE INDEX IF NOT EXISTS idx_notification_recipient_user_read
                    ON notification_recipients (user_id, is_read)
                    """
                )
            )
            await conn.execute(
                text(
                    """
                    CREATE INDEX IF NOT EXISTS idx_notification_recipient_notification
                    ON notification_recipients (notification_id)
                    """
                )
            )

    try:
        await _run_startup_db_op_with_retry("ensure_notification_tables", _op)
    except Exception as exc:
        logger.warning("ensure_notification_tables failed and was skipped: %s", exc)
