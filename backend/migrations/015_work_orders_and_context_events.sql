-- 015: 工单持久化 + 特殊事件 + 审计日志
-- 替代内存 _work_orders 字典，支持 AI 审批闭环

-- =========================================================================
-- 1. work_orders — 工单主表
-- =========================================================================
CREATE TABLE IF NOT EXISTS work_orders (
    id              VARCHAR PRIMARY KEY DEFAULT gen_random_uuid()::text,
    ticket_id       VARCHAR(64) UNIQUE NOT NULL,

    -- 工单基本信息
    building_id     VARCHAR NOT NULL REFERENCES buildings(building_id) ON DELETE CASCADE,
    device_id       VARCHAR(128),
    issue_description TEXT NOT NULL,
    suggested_action  TEXT NOT NULL,
    priority        VARCHAR(16) NOT NULL DEFAULT 'medium',

    -- 状态机
    status          VARCHAR(32) NOT NULL DEFAULT 'pending_review',

    -- AI 审批结果
    ai_decision         VARCHAR(16),
    ai_reason           TEXT,
    ai_matched_event_ids TEXT,
    ai_reviewed_at      TIMESTAMP WITH TIME ZONE,
    ai_fallback         BOOLEAN DEFAULT FALSE,

    -- 维修反馈
    worker_result       VARCHAR(32),
    worker_notes        TEXT,
    worker_feedback_at  TIMESTAMP WITH TIME ZONE,
    assigned_to         VARCHAR REFERENCES users(id) ON DELETE SET NULL,

    -- 管理员监督
    admin_action        VARCHAR(32),
    admin_notes         TEXT,
    admin_reviewed_by   VARCHAR REFERENCES users(id) ON DELETE SET NULL,
    admin_reviewed_at   TIMESTAMP WITH TIME ZONE,

    -- 时间戳
    created_at      TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
    updated_at      TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
    closed_at       TIMESTAMP WITH TIME ZONE,

    -- 来源追溯
    session_id      VARCHAR(128),
    created_by      VARCHAR REFERENCES users(id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_wo_status ON work_orders(status);
CREATE INDEX IF NOT EXISTS idx_wo_building ON work_orders(building_id);
CREATE INDEX IF NOT EXISTS idx_wo_created ON work_orders(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_wo_assigned ON work_orders(assigned_to) WHERE assigned_to IS NOT NULL;


-- =========================================================================
-- 2. work_order_anomaly_links — 工单与异常事件关联（含快照）
-- =========================================================================
CREATE TABLE IF NOT EXISTS work_order_anomaly_links (
    id              VARCHAR PRIMARY KEY DEFAULT gen_random_uuid()::text,
    work_order_id   VARCHAR NOT NULL REFERENCES work_orders(id) ON DELETE CASCADE,
    anomaly_event_id UUID REFERENCES anomaly_events(id) ON DELETE SET NULL,

    -- 快照字段
    rule_triggered  VARCHAR(64) NOT NULL,
    hvac_root_cause VARCHAR(64),
    actual_value    DOUBLE PRECISION,
    expected_value  DOUBLE PRECISION,
    deviation_pct   DOUBLE PRECISION,
    data_timestamp  TIMESTAMP WITH TIME ZONE NOT NULL,

    UNIQUE (work_order_id, anomaly_event_id)
);

CREATE INDEX IF NOT EXISTS idx_wo_anomaly_wo ON work_order_anomaly_links(work_order_id);
CREATE INDEX IF NOT EXISTS idx_wo_anomaly_event ON work_order_anomaly_links(anomaly_event_id);


-- =========================================================================
-- 3. context_events — 特殊事件表
-- =========================================================================
CREATE TABLE IF NOT EXISTS context_events (
    id              VARCHAR PRIMARY KEY DEFAULT gen_random_uuid()::text,
    event_type      VARCHAR(32) NOT NULL,
    category        VARCHAR(16) NOT NULL,
    building_id     VARCHAR REFERENCES buildings(building_id) ON DELETE CASCADE,

    start_time      TIMESTAMP WITH TIME ZONE NOT NULL,
    end_time        TIMESTAMP WITH TIME ZONE NOT NULL,
    grace_period_minutes INTEGER NOT NULL DEFAULT 0,
    description     TEXT,

    is_active       BOOLEAN NOT NULL DEFAULT TRUE,
    created_by      VARCHAR REFERENCES users(id) ON DELETE SET NULL,
    created_at      TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),

    CONSTRAINT chk_time_range CHECK (end_time > start_time),
    CONSTRAINT chk_grace_period CHECK (grace_period_minutes >= 0 AND grace_period_minutes <= 480)
);

CREATE INDEX IF NOT EXISTS idx_ctx_events_active ON context_events(start_time, end_time) WHERE is_active = TRUE;
CREATE INDEX IF NOT EXISTS idx_ctx_events_building ON context_events(building_id);


-- =========================================================================
-- 4. work_order_audit_log — 审计日志
-- =========================================================================
CREATE TABLE IF NOT EXISTS work_order_audit_log (
    id              VARCHAR PRIMARY KEY DEFAULT gen_random_uuid()::text,
    work_order_id   VARCHAR NOT NULL REFERENCES work_orders(id) ON DELETE CASCADE,
    action          VARCHAR(32) NOT NULL,
    old_status      VARCHAR(32),
    new_status      VARCHAR(32) NOT NULL,
    actor_type      VARCHAR(16) NOT NULL,
    actor_id        VARCHAR,
    detail_json     TEXT,
    created_at      TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_audit_wo ON work_order_audit_log(work_order_id);
CREATE INDEX IF NOT EXISTS idx_audit_time ON work_order_audit_log(created_at DESC);
