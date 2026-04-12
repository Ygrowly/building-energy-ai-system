-- Migration 025: unified notification center for work order messaging

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
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_notification_record_source UNIQUE (source_type, source_id)
);

CREATE INDEX IF NOT EXISTS idx_notification_record_category_time
ON notification_records (category, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_notification_record_aggregate
ON notification_records (aggregate_type, aggregate_id);

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
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_notification_recipient_source_user UNIQUE (source_type, source_id, user_id),
    CONSTRAINT uq_notification_recipient_notification_user UNIQUE (notification_id, user_id)
);

CREATE INDEX IF NOT EXISTS idx_notification_recipient_user_time
ON notification_recipients (user_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_notification_recipient_user_read
ON notification_recipients (user_id, is_read);

CREATE INDEX IF NOT EXISTS idx_notification_recipient_notification
ON notification_recipients (notification_id);
