BEGIN;

CREATE TABLE IF NOT EXISTS maintenance_experiences (
    id VARCHAR PRIMARY KEY,
    source_type VARCHAR(32) NOT NULL,
    source_work_order_id VARCHAR(64) NULL,
    source_dispatch_id VARCHAR NULL,
    source_step_plan_id VARCHAR NULL,
    contributor_user_id VARCHAR NULL REFERENCES users(id) ON DELETE SET NULL,
    contributor_role VARCHAR(32) NULL,
    building_id VARCHAR NULL REFERENCES buildings(building_id) ON DELETE SET NULL,
    device_id VARCHAR(128) NULL,
    device_type VARCHAR(64) NULL,
    fault_type VARCHAR(128) NULL,
    fault_keywords_json TEXT NULL,
    symptom_tags_json TEXT NULL,
    source_text TEXT NOT NULL,
    organized_text TEXT NULL,
    suggested_steps_json TEXT NULL,
    safety_notes_json TEXT NULL,
    applicable_conditions_json TEXT NULL,
    conflict_flags_json TEXT NULL,
    model_provider VARCHAR(32) NULL,
    model_name VARCHAR(64) NULL,
    vector_index_status VARCHAR(24) NOT NULL DEFAULT 'pending',
    vector_ref TEXT NULL,
    usage_count INTEGER NOT NULL DEFAULT 0,
    helpful_count INTEGER NOT NULL DEFAULT 0,
    unhelpful_count INTEGER NOT NULL DEFAULT 0,
    incorrect_count INTEGER NOT NULL DEFAULT 0,
    is_active BOOLEAN NOT NULL DEFAULT true,
    deactivated_by VARCHAR NULL REFERENCES users(id) ON DELETE SET NULL,
    deactivated_reason TEXT NULL,
    deactivated_at TIMESTAMPTZ NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS maintenance_experience_usage_logs (
    id VARCHAR PRIMARY KEY,
    experience_id VARCHAR NOT NULL REFERENCES maintenance_experiences(id) ON DELETE CASCADE,
    work_order_id VARCHAR(64) NULL,
    dispatch_id VARCHAR NULL,
    assistant_session_id VARCHAR(128) NULL,
    usage_type VARCHAR(24) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS maintenance_experience_feedback (
    id VARCHAR PRIMARY KEY,
    experience_id VARCHAR NOT NULL REFERENCES maintenance_experiences(id) ON DELETE CASCADE,
    user_id VARCHAR NULL REFERENCES users(id) ON DELETE SET NULL,
    work_order_id VARCHAR(64) NULL,
    feedback VARCHAR(24) NOT NULL,
    note TEXT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_maintenance_experience_active_time
    ON maintenance_experiences (is_active, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_maintenance_experience_building_time
    ON maintenance_experiences (building_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_maintenance_experience_device_type_time
    ON maintenance_experiences (device_type, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_maintenance_experience_fault_time
    ON maintenance_experiences (fault_type, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_maintenance_experience_source_work_order
    ON maintenance_experiences (source_work_order_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_maintenance_experience_vector_status
    ON maintenance_experiences (vector_index_status, updated_at DESC);

CREATE INDEX IF NOT EXISTS idx_maintenance_experience_usage_exp_time
    ON maintenance_experience_usage_logs (experience_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_maintenance_experience_usage_work_order
    ON maintenance_experience_usage_logs (work_order_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_maintenance_experience_usage_session
    ON maintenance_experience_usage_logs (assistant_session_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_maintenance_experience_feedback_exp_time
    ON maintenance_experience_feedback (experience_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_maintenance_experience_feedback_user_time
    ON maintenance_experience_feedback (user_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_maintenance_experience_feedback_work_order
    ON maintenance_experience_feedback (work_order_id, created_at DESC);

COMMIT;
