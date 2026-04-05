-- 019: 派单体系第三阶段改造
-- 目标：
--   1. 新增 dispatch_tasks / dispatch_events 执行层
--   2. 为 work_orders / anomaly_incidents 增加 current_dispatch 读模型字段
--   3. 将历史已派工工单回填为第一条 dispatch_task

ALTER TABLE work_orders
    ADD COLUMN IF NOT EXISTS pending_dispatch_at TIMESTAMP WITH TIME ZONE,
    ADD COLUMN IF NOT EXISTS dispatch_profile_json TEXT,
    ADD COLUMN IF NOT EXISTS dispatch_blocked_reason TEXT,
    ADD COLUMN IF NOT EXISTS current_dispatch_id TEXT;

ALTER TABLE anomaly_incidents
    ADD COLUMN IF NOT EXISTS current_dispatch_id TEXT,
    ADD COLUMN IF NOT EXISTS current_dispatch_status VARCHAR(32),
    ADD COLUMN IF NOT EXISTS current_assigned_to TEXT,
    ADD COLUMN IF NOT EXISTS current_assigned_team_id TEXT,
    ADD COLUMN IF NOT EXISTS current_accept_deadline_at TIMESTAMP WITH TIME ZONE,
    ADD COLUMN IF NOT EXISTS current_arrive_deadline_at TIMESTAMP WITH TIME ZONE,
    ADD COLUMN IF NOT EXISTS current_finish_deadline_at TIMESTAMP WITH TIME ZONE,
    ADD COLUMN IF NOT EXISTS last_dispatch_at TIMESTAMP WITH TIME ZONE,
    ADD COLUMN IF NOT EXISTS dispatch_overdue_flag BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS dispatch_blocked_reason TEXT,
    ADD COLUMN IF NOT EXISTS latest_dispatch_note TEXT;

UPDATE work_orders
SET pending_dispatch_at = COALESCE(pending_dispatch_at, ai_reviewed_at, updated_at, created_at)
WHERE status = 'pending_dispatch'
  AND pending_dispatch_at IS NULL;

CREATE TABLE IF NOT EXISTS dispatch_tasks (
    id TEXT PRIMARY KEY,
    work_order_id TEXT NOT NULL REFERENCES work_orders(id) ON DELETE CASCADE,
    incident_id TEXT REFERENCES anomaly_incidents(id) ON DELETE SET NULL,
    attempt_no INTEGER NOT NULL DEFAULT 1,
    is_current BOOLEAN NOT NULL DEFAULT TRUE,

    dispatch_mode VARCHAR(24) NOT NULL DEFAULT 'manual',
    dispatch_status VARCHAR(32) NOT NULL DEFAULT 'assigned',
    assigned_team_id TEXT REFERENCES worker_teams(id) ON DELETE SET NULL,
    assigned_to TEXT REFERENCES users(id) ON DELETE SET NULL,
    assigned_by TEXT REFERENCES users(id) ON DELETE SET NULL,
    selection_reason TEXT,
    candidate_snapshot_json TEXT,
    dispatch_profile_snapshot_json TEXT,

    worker_result VARCHAR(32),
    reject_reason TEXT,
    cancel_reason TEXT,
    support_reason TEXT,
    support_team_id TEXT REFERENCES worker_teams(id) ON DELETE SET NULL,
    transfer_from_dispatch_id TEXT REFERENCES dispatch_tasks(id) ON DELETE SET NULL,

    assigned_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    accept_deadline_at TIMESTAMP WITH TIME ZONE,
    accepted_at TIMESTAMP WITH TIME ZONE,
    arrive_deadline_at TIMESTAMP WITH TIME ZONE,
    arrived_at TIMESTAMP WITH TIME ZONE,
    start_deadline_at TIMESTAMP WITH TIME ZONE,
    processing_started_at TIMESTAMP WITH TIME ZONE,
    finish_deadline_at TIMESTAMP WITH TIME ZONE,
    completed_at TIMESTAMP WITH TIME ZONE,
    closed_at TIMESTAMP WITH TIME ZONE,

    reminder_count INTEGER NOT NULL DEFAULT 0,
    last_reminded_at TIMESTAMP WITH TIME ZONE,
    timeout_level VARCHAR(16) NOT NULL DEFAULT 'normal',
    latest_note TEXT,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),

    CONSTRAINT uq_dispatch_attempt UNIQUE (work_order_id, attempt_no)
);

CREATE INDEX IF NOT EXISTS idx_dispatch_work_order ON dispatch_tasks (work_order_id);
CREATE INDEX IF NOT EXISTS idx_dispatch_incident ON dispatch_tasks (incident_id);
CREATE INDEX IF NOT EXISTS idx_dispatch_assigned_to_status ON dispatch_tasks (assigned_to, dispatch_status);
CREATE INDEX IF NOT EXISTS idx_dispatch_team_status ON dispatch_tasks (assigned_team_id, dispatch_status);
CREATE INDEX IF NOT EXISTS idx_dispatch_current ON dispatch_tasks (work_order_id, is_current);
CREATE INDEX IF NOT EXISTS idx_dispatch_accept_deadline ON dispatch_tasks (accept_deadline_at);
CREATE INDEX IF NOT EXISTS idx_dispatch_arrive_deadline ON dispatch_tasks (arrive_deadline_at);
CREATE INDEX IF NOT EXISTS idx_dispatch_finish_deadline ON dispatch_tasks (finish_deadline_at);

CREATE TABLE IF NOT EXISTS dispatch_events (
    id TEXT PRIMARY KEY,
    dispatch_task_id TEXT NOT NULL REFERENCES dispatch_tasks(id) ON DELETE CASCADE,
    work_order_id TEXT NOT NULL REFERENCES work_orders(id) ON DELETE CASCADE,
    incident_id TEXT REFERENCES anomaly_incidents(id) ON DELETE SET NULL,
    event_type VARCHAR(32) NOT NULL,
    actor_type VARCHAR(16) NOT NULL,
    actor_id TEXT,
    payload_json TEXT,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_dispatch_event_task_time ON dispatch_events (dispatch_task_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_dispatch_event_work_order_time ON dispatch_events (work_order_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_dispatch_event_incident_time ON dispatch_events (incident_id, created_at DESC);

DO $$
DECLARE
    rec RECORD;
    v_dispatch_id TEXT;
    v_accept_minutes INTEGER;
    v_arrive_minutes INTEGER;
    v_finish_minutes INTEGER;
BEGIN
    FOR rec IN
        SELECT
            wo.id,
            wo.incident_id,
            wo.priority,
            wo.assigned_to,
            wp.team_id AS assigned_team_id,
            wo.assigned_at,
            wo.accepted_at,
            wo.arrived_at,
            wo.processing_started_at,
            wo.worker_feedback_at,
            wo.worker_result,
            wo.worker_notes,
            wo.status
        FROM work_orders wo
        LEFT JOIN worker_profiles wp ON wp.user_id = wo.assigned_to
        WHERE wo.assigned_to IS NOT NULL
          AND wo.current_dispatch_id IS NULL
          AND wo.status IN ('dispatched', 'completed', 'false_alarm', 'escalated', 'closed')
    LOOP
        v_dispatch_id := md5(rec.id || '-dispatch-1');
        v_accept_minutes := CASE rec.priority
            WHEN 'high' THEN 5
            WHEN 'low' THEN 15
            ELSE 10
        END;
        v_arrive_minutes := CASE rec.priority
            WHEN 'high' THEN 20
            WHEN 'low' THEN 60
            ELSE 30
        END;
        v_finish_minutes := CASE rec.priority
            WHEN 'high' THEN 90
            WHEN 'low' THEN 360
            ELSE 180
        END;

        INSERT INTO dispatch_tasks (
            id,
            work_order_id,
            incident_id,
            attempt_no,
            is_current,
            dispatch_mode,
            dispatch_status,
            assigned_team_id,
            assigned_to,
            selection_reason,
            worker_result,
            assigned_at,
            accept_deadline_at,
            accepted_at,
            arrive_deadline_at,
            arrived_at,
            start_deadline_at,
            processing_started_at,
            finish_deadline_at,
            completed_at,
            closed_at,
            timeout_level,
            latest_note
        )
        VALUES (
            v_dispatch_id,
            rec.id,
            rec.incident_id,
            1,
            TRUE,
            'legacy_backfill',
            CASE
                WHEN rec.status IN ('completed', 'false_alarm', 'closed') AND rec.worker_feedback_at IS NOT NULL THEN 'completed'
                WHEN rec.status = 'escalated' THEN 'escalated'
                WHEN rec.processing_started_at IS NOT NULL THEN 'processing'
                WHEN rec.arrived_at IS NOT NULL THEN 'arrived'
                WHEN rec.accepted_at IS NOT NULL THEN 'accepted'
                ELSE 'assigned'
            END,
            rec.assigned_team_id,
            rec.assigned_to,
            '由 019 迁移从历史工单回填',
            rec.worker_result,
            COALESCE(rec.assigned_at, rec.worker_feedback_at, NOW()),
            COALESCE(rec.assigned_at, NOW()) + make_interval(mins => v_accept_minutes),
            rec.accepted_at,
            COALESCE(rec.accepted_at, rec.assigned_at, NOW()) + make_interval(mins => v_arrive_minutes),
            rec.arrived_at,
            COALESCE(rec.arrived_at, rec.accepted_at, rec.assigned_at, NOW()) + make_interval(mins => 30),
            rec.processing_started_at,
            COALESCE(rec.processing_started_at, rec.arrived_at, rec.accepted_at, rec.assigned_at, NOW()) + make_interval(mins => v_finish_minutes),
            rec.worker_feedback_at,
            CASE
                WHEN rec.status IN ('completed', 'false_alarm', 'closed', 'escalated') THEN COALESCE(rec.worker_feedback_at, NOW())
                ELSE NULL
            END,
            'normal',
            rec.worker_notes
        )
        ON CONFLICT (id) DO NOTHING;

        UPDATE work_orders
        SET current_dispatch_id = v_dispatch_id
        WHERE id = rec.id
          AND current_dispatch_id IS NULL;

        UPDATE anomaly_incidents
        SET
            current_dispatch_id = v_dispatch_id,
            current_dispatch_status = (
                SELECT dispatch_status
                FROM dispatch_tasks
                WHERE id = v_dispatch_id
            ),
            current_assigned_to = rec.assigned_to,
            current_assigned_team_id = rec.assigned_team_id,
            last_dispatch_at = rec.assigned_at,
            latest_dispatch_note = rec.worker_notes
        WHERE id = rec.incident_id
          AND current_dispatch_id IS NULL;
    END LOOP;
END $$;

ALTER TABLE work_orders
    ADD CONSTRAINT fk_work_orders_current_dispatch
    FOREIGN KEY (current_dispatch_id) REFERENCES dispatch_tasks(id) ON DELETE SET NULL;

ALTER TABLE anomaly_incidents
    ADD CONSTRAINT fk_incidents_current_dispatch
    FOREIGN KEY (current_dispatch_id) REFERENCES dispatch_tasks(id) ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS idx_wo_current_dispatch ON work_orders (current_dispatch_id);
CREATE INDEX IF NOT EXISTS idx_incident_current_dispatch ON anomaly_incidents (current_dispatch_id);
CREATE INDEX IF NOT EXISTS idx_incident_dispatch_status ON anomaly_incidents (current_dispatch_status);
