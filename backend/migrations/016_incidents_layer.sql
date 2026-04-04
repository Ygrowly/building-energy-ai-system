-- incident 层：连续异常事件主表 + 证据时间线

CREATE TABLE IF NOT EXISTS anomaly_incidents (
    id VARCHAR PRIMARY KEY,
    incident_id VARCHAR(64) NOT NULL UNIQUE,
    source VARCHAR(32) NOT NULL DEFAULT 'auto_detect',
    building_id VARCHAR NOT NULL REFERENCES buildings(building_id) ON DELETE CASCADE,
    device_id VARCHAR(128),
    rule_triggered VARCHAR(64) NOT NULL,
    hvac_root_cause VARCHAR(64),
    merge_key VARCHAR(255) NOT NULL,
    incident_status VARCHAR(32) NOT NULL DEFAULT 'open',
    workflow_status VARCHAR(32),
    priority VARCHAR(16) NOT NULL DEFAULT 'medium',
    first_seen_at TIMESTAMPTZ NOT NULL,
    last_seen_at TIMESTAMPTZ NOT NULL,
    continuity_expires_at TIMESTAMPTZ NOT NULL,
    anomaly_count INTEGER NOT NULL DEFAULT 1,
    peak_deviation_pct DOUBLE PRECISION,
    latest_actual_value DOUBLE PRECISION,
    latest_expected_value DOUBLE PRECISION,
    summary_text TEXT NOT NULL,
    current_work_order_id VARCHAR NULL,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    resolved_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_incident_merge_key_active
ON anomaly_incidents (merge_key, is_active);

CREATE INDEX IF NOT EXISTS idx_incident_workflow_status
ON anomaly_incidents (workflow_status);

CREATE INDEX IF NOT EXISTS idx_incident_building_last_seen
ON anomaly_incidents (building_id, last_seen_at DESC);

CREATE INDEX IF NOT EXISTS idx_incident_priority_last_seen
ON anomaly_incidents (priority, last_seen_at DESC);

ALTER TABLE work_orders
ADD COLUMN IF NOT EXISTS incident_id VARCHAR NULL;

CREATE INDEX IF NOT EXISTS idx_wo_incident
ON work_orders (incident_id);

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM information_schema.table_constraints
        WHERE constraint_name = 'fk_work_orders_incident'
          AND table_name = 'work_orders'
    ) THEN
        ALTER TABLE work_orders
        ADD CONSTRAINT fk_work_orders_incident
        FOREIGN KEY (incident_id) REFERENCES anomaly_incidents(id) ON DELETE SET NULL;
    END IF;
END $$;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM information_schema.table_constraints
        WHERE constraint_name = 'fk_incident_current_work_order'
          AND table_name = 'anomaly_incidents'
    ) THEN
        ALTER TABLE anomaly_incidents
        ADD CONSTRAINT fk_incident_current_work_order
        FOREIGN KEY (current_work_order_id) REFERENCES work_orders(id) ON DELETE SET NULL;
    END IF;
END $$;

CREATE TABLE IF NOT EXISTS incident_event_links (
    id VARCHAR PRIMARY KEY,
    incident_id VARCHAR NOT NULL REFERENCES anomaly_incidents(id) ON DELETE CASCADE,
    anomaly_event_id UUID NULL REFERENCES anomaly_events(id) ON DELETE SET NULL,
    sequence_no INTEGER NOT NULL DEFAULT 1,
    data_timestamp TIMESTAMPTZ NOT NULL,
    actual_value DOUBLE PRECISION,
    expected_value DOUBLE PRECISION,
    deviation_pct DOUBLE PRECISION,
    rule_triggered VARCHAR(64) NOT NULL,
    hvac_root_cause VARCHAR(64),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_incident_event_link UNIQUE (incident_id, anomaly_event_id)
);

CREATE INDEX IF NOT EXISTS idx_incident_event_incident
ON incident_event_links (incident_id);

CREATE INDEX IF NOT EXISTS idx_incident_event_timestamp
ON incident_event_links (data_timestamp DESC);

CREATE TABLE IF NOT EXISTS incident_prediction_links (
    id VARCHAR PRIMARY KEY,
    incident_id VARCHAR NOT NULL REFERENCES anomaly_incidents(id) ON DELETE CASCADE,
    predicted_anomaly_event_id VARCHAR NULL REFERENCES predicted_anomaly_events(id) ON DELETE SET NULL,
    sequence_no INTEGER NOT NULL DEFAULT 1,
    forecast_for_timestamp TIMESTAMPTZ NOT NULL,
    metric_name VARCHAR(64) NOT NULL,
    predicted_value DOUBLE PRECISION,
    expected_value DOUBLE PRECISION,
    deviation_pct DOUBLE PRECISION,
    risk_level VARCHAR(32),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_incident_prediction_link UNIQUE (incident_id, predicted_anomaly_event_id)
);

CREATE INDEX IF NOT EXISTS idx_incident_prediction_incident
ON incident_prediction_links (incident_id);

CREATE INDEX IF NOT EXISTS idx_incident_prediction_timestamp
ON incident_prediction_links (forecast_for_timestamp DESC);
