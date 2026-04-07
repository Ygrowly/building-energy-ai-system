-- 020_dispatch_hall_phase1.sql
-- 共享工单大厅一期：承接未指派协同、超时待接管等共享响应池

CREATE TABLE IF NOT EXISTS dispatch_hall_entries (
    id TEXT PRIMARY KEY,
    work_order_id TEXT NOT NULL REFERENCES work_orders(id) ON DELETE CASCADE,
    incident_id TEXT NULL REFERENCES anomaly_incidents(id) ON DELETE SET NULL,
    source_dispatch_id TEXT NULL REFERENCES dispatch_tasks(id) ON DELETE SET NULL,

    entry_type VARCHAR(32) NOT NULL,
    status VARCHAR(24) NOT NULL DEFAULT 'open',
    visibility_scope VARCHAR(24) NOT NULL DEFAULT 'all_ops',

    target_team_ids_json TEXT NULL,
    target_skill_tags_json TEXT NULL,
    target_user_ids_json TEXT NULL,

    reason TEXT NULL,
    support_reason TEXT NULL,
    sla_stage VARCHAR(32) NULL,
    overdue_level VARCHAR(16) NULL,
    allow_direct_claim BOOLEAN NOT NULL DEFAULT FALSE,

    assigned_to TEXT NULL REFERENCES users(id) ON DELETE SET NULL,
    assigned_team_id TEXT NULL REFERENCES worker_teams(id) ON DELETE SET NULL,
    assigned_by TEXT NULL REFERENCES users(id) ON DELETE SET NULL,
    created_by TEXT NULL REFERENCES users(id) ON DELETE SET NULL,

    expired_at TIMESTAMPTZ NULL,
    assigned_at TIMESTAMPTZ NULL,
    closed_at TIMESTAMPTZ NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS dispatch_hall_applications (
    id TEXT PRIMARY KEY,
    hall_entry_id TEXT NOT NULL REFERENCES dispatch_hall_entries(id) ON DELETE CASCADE,
    applicant_user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    application_type VARCHAR(24) NOT NULL,
    status VARCHAR(24) NOT NULL DEFAULT 'pending',
    note TEXT NULL,
    handle_note TEXT NULL,
    handled_by TEXT NULL REFERENCES users(id) ON DELETE SET NULL,
    handled_at TIMESTAMPTZ NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_dispatch_hall_type_status
    ON dispatch_hall_entries(entry_type, status);

CREATE INDEX IF NOT EXISTS idx_dispatch_hall_work_order
    ON dispatch_hall_entries(work_order_id);

CREATE INDEX IF NOT EXISTS idx_dispatch_hall_incident
    ON dispatch_hall_entries(incident_id);

CREATE INDEX IF NOT EXISTS idx_dispatch_hall_source_dispatch
    ON dispatch_hall_entries(source_dispatch_id);

CREATE INDEX IF NOT EXISTS idx_dispatch_hall_assigned_to_status
    ON dispatch_hall_entries(assigned_to, status);

CREATE INDEX IF NOT EXISTS idx_dispatch_hall_created
    ON dispatch_hall_entries(created_at DESC);

CREATE INDEX IF NOT EXISTS idx_dispatch_hall_application_entry_status
    ON dispatch_hall_applications(hall_entry_id, status);

CREATE INDEX IF NOT EXISTS idx_dispatch_hall_application_user_status
    ON dispatch_hall_applications(applicant_user_id, status);

CREATE INDEX IF NOT EXISTS idx_dispatch_hall_application_created
    ON dispatch_hall_applications(created_at DESC);
