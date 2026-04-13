CREATE TABLE IF NOT EXISTS dispatch_operation_runs (
    id VARCHAR PRIMARY KEY,
    operation_type VARCHAR(32) NOT NULL,
    trigger_source VARCHAR(16) NOT NULL,
    run_status VARCHAR(16) NOT NULL DEFAULT 'success',
    scanned_count INTEGER NOT NULL DEFAULT 0,
    updated_count INTEGER NOT NULL DEFAULT 0,
    warning_events INTEGER NOT NULL DEFAULT 0,
    overdue_events INTEGER NOT NULL DEFAULT 0,
    auto_reassign_triggers INTEGER NOT NULL DEFAULT 0,
    auto_reassign_executed INTEGER NOT NULL DEFAULT 0,
    auto_reassign_hall_fallbacks INTEGER NOT NULL DEFAULT 0,
    auto_reassign_shadow_evaluated INTEGER NOT NULL DEFAULT 0,
    auto_reassign_shadow_would_execute INTEGER NOT NULL DEFAULT 0,
    auto_reassign_shadow_would_hall_fallbacks INTEGER NOT NULL DEFAULT 0,
    duration_ms INTEGER NOT NULL DEFAULT 0,
    timings_json TEXT NULL,
    error_message TEXT NULL,
    started_at TIMESTAMPTZ NOT NULL,
    finished_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_dispatch_operation_runs_type_time
ON dispatch_operation_runs (operation_type, started_at DESC);

CREATE INDEX IF NOT EXISTS idx_dispatch_operation_runs_status_time
ON dispatch_operation_runs (run_status, started_at DESC);

CREATE INDEX IF NOT EXISTS idx_dispatch_operation_runs_source_time
ON dispatch_operation_runs (trigger_source, started_at DESC);
