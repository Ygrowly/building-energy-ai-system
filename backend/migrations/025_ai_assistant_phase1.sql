-- Phase 1：维小修 / 运小维会话与动作审计表

CREATE TABLE IF NOT EXISTS ai_assistant_sessions (
    id VARCHAR(128) PRIMARY KEY,
    assistant_name VARCHAR(32) NOT NULL,
    user_id VARCHAR NULL REFERENCES users(id) ON DELETE SET NULL,
    role VARCHAR(32) NULL,
    work_order_id VARCHAR NULL REFERENCES work_orders(id) ON DELETE SET NULL,
    session_state_json TEXT NULL,
    readonly BOOLEAN NOT NULL DEFAULT false,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS ai_assistant_messages (
    id VARCHAR PRIMARY KEY,
    session_id VARCHAR(128) NOT NULL REFERENCES ai_assistant_sessions(id) ON DELETE CASCADE,
    role VARCHAR(16) NOT NULL,
    content TEXT NOT NULL,
    content_type VARCHAR(24) NOT NULL DEFAULT 'text',
    model_provider VARCHAR(32) NULL,
    model_name VARCHAR(64) NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS ai_assistant_action_audits (
    id VARCHAR PRIMARY KEY,
    session_id VARCHAR(128) NULL REFERENCES ai_assistant_sessions(id) ON DELETE SET NULL,
    work_order_id VARCHAR NULL REFERENCES work_orders(id) ON DELETE SET NULL,
    dispatch_id VARCHAR NULL REFERENCES dispatch_tasks(id) ON DELETE SET NULL,
    hall_entry_id VARCHAR NULL REFERENCES dispatch_hall_entries(id) ON DELETE SET NULL,
    proposed_action VARCHAR(32) NOT NULL,
    confirmation_text TEXT NULL,
    execution_status VARCHAR(16) NOT NULL DEFAULT 'pending',
    backend_action_ref TEXT NULL,
    error_message TEXT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_ai_assistant_session_user
    ON ai_assistant_sessions (user_id, updated_at DESC);

CREATE INDEX IF NOT EXISTS idx_ai_assistant_session_work_order
    ON ai_assistant_sessions (work_order_id, updated_at DESC);

CREATE INDEX IF NOT EXISTS idx_ai_assistant_session_name
    ON ai_assistant_sessions (assistant_name, updated_at DESC);

CREATE INDEX IF NOT EXISTS idx_ai_assistant_message_session_time
    ON ai_assistant_messages (session_id, created_at ASC);

CREATE INDEX IF NOT EXISTS idx_ai_assistant_action_session
    ON ai_assistant_action_audits (session_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_ai_assistant_action_work_order
    ON ai_assistant_action_audits (work_order_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_ai_assistant_action_status
    ON ai_assistant_action_audits (execution_status, created_at DESC);
