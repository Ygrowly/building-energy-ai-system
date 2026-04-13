-- 维小修 / 运小维 AI Phase 2：维修指导步骤、步骤事件与现场媒体

CREATE TABLE IF NOT EXISTS worker_ai_step_plans (
    id VARCHAR PRIMARY KEY,
    work_order_id VARCHAR NOT NULL REFERENCES work_orders(id) ON DELETE CASCADE,
    dispatch_id VARCHAR NULL REFERENCES dispatch_tasks(id) ON DELETE SET NULL,
    generated_from_json TEXT NULL,
    root_cause_candidates_json TEXT NULL,
    summary TEXT NOT NULL,
    steps_json TEXT NOT NULL,
    safety_notes_json TEXT NULL,
    status VARCHAR(24) NOT NULL DEFAULT 'active',
    version INTEGER NOT NULL DEFAULT 1,
    model_provider VARCHAR(32) NULL,
    model_name VARCHAR(64) NULL,
    created_by VARCHAR NULL REFERENCES users(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_worker_ai_step_plan_wo_status
    ON worker_ai_step_plans (work_order_id, status, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_worker_ai_step_plan_dispatch
    ON worker_ai_step_plans (dispatch_id, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_worker_ai_step_plan_created_by
    ON worker_ai_step_plans (created_by, updated_at DESC);

CREATE TABLE IF NOT EXISTS worker_ai_step_events (
    id VARCHAR PRIMARY KEY,
    plan_id VARCHAR NOT NULL REFERENCES worker_ai_step_plans(id) ON DELETE CASCADE,
    step_id VARCHAR(64) NOT NULL,
    user_id VARCHAR NULL REFERENCES users(id) ON DELETE SET NULL,
    event_type VARCHAR(32) NOT NULL,
    note TEXT NULL,
    payload_json TEXT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_worker_ai_step_event_plan_time
    ON worker_ai_step_events (plan_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_worker_ai_step_event_step_time
    ON worker_ai_step_events (plan_id, step_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_worker_ai_step_event_user_time
    ON worker_ai_step_events (user_id, created_at DESC);

CREATE TABLE IF NOT EXISTS ai_media_assets (
    id VARCHAR PRIMARY KEY,
    owner_user_id VARCHAR NULL REFERENCES users(id) ON DELETE SET NULL,
    work_order_id VARCHAR NOT NULL REFERENCES work_orders(id) ON DELETE CASCADE,
    dispatch_id VARCHAR NULL REFERENCES dispatch_tasks(id) ON DELETE SET NULL,
    step_id VARCHAR(64) NULL,
    media_type VARCHAR(16) NOT NULL,
    original_name VARCHAR(255) NULL,
    mime_type VARCHAR(96) NULL,
    file_size INTEGER NOT NULL DEFAULT 0,
    storage_url TEXT NOT NULL,
    transcript TEXT NULL,
    analysis_json TEXT NULL,
    model_provider VARCHAR(32) NULL,
    model_name VARCHAR(64) NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_ai_media_asset_wo_time
    ON ai_media_assets (work_order_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_ai_media_asset_owner_time
    ON ai_media_assets (owner_user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_ai_media_asset_step_time
    ON ai_media_assets (work_order_id, step_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_ai_media_asset_type_time
    ON ai_media_assets (media_type, created_at DESC);
