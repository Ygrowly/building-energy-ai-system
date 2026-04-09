-- 023: work_orders 三维状态投影
-- 目标：
--   1. 保留旧 work_orders.status 兼容字段
--   2. 新增 approval_status / dispatch_summary_status / work_result
--   3. 基于现有工单状态与 current_dispatch 回填新字段

ALTER TABLE work_orders
    ADD COLUMN IF NOT EXISTS approval_status VARCHAR(32),
    ADD COLUMN IF NOT EXISTS dispatch_summary_status VARCHAR(32),
    ADD COLUMN IF NOT EXISTS work_result VARCHAR(32);

UPDATE work_orders AS wo
SET
    approval_status = CASE
        WHEN wo.status = 'pending_review' THEN 'pending_review'
        WHEN wo.status IN ('auto_rejected', 'admin_override_rejected') THEN 'rejected'
        WHEN wo.status = 'closed' AND wo.admin_action = 'override_reject' THEN 'rejected'
        WHEN wo.ai_decision = 'reject'
             AND wo.status IN ('auto_rejected', 'closed')
             AND COALESCE(wo.admin_action, '') <> 'override_approve' THEN 'rejected'
        ELSE 'approved'
    END,
    dispatch_summary_status = CASE
        WHEN wo.status IN ('pending_review', 'auto_rejected', 'admin_override_rejected') THEN NULL
        WHEN wo.status IN ('pending_dispatch', 'auto_approved', 'admin_override_approved') THEN 'pending_dispatch'
        WHEN (
            SELECT dt.dispatch_status
            FROM dispatch_tasks dt
            WHERE dt.id = wo.current_dispatch_id
        ) IN ('assigned', 'accepted', 'arrived', 'processing', 'waiting_support', 'completed', 'cancelled', 'escalated')
        THEN (
            SELECT dt.dispatch_status
            FROM dispatch_tasks dt
            WHERE dt.id = wo.current_dispatch_id
        )
        WHEN (
            SELECT dt.dispatch_status
            FROM dispatch_tasks dt
            WHERE dt.id = wo.current_dispatch_id
        ) IN ('rejected', 'transferred') THEN 'pending_dispatch'
        WHEN wo.status = 'dispatched' THEN 'assigned'
        WHEN wo.status IN ('completed', 'false_alarm', 'closed') THEN 'completed'
        WHEN wo.status = 'escalated' THEN 'escalated'
        ELSE NULL
    END,
    work_result = COALESCE(
        NULLIF(wo.worker_result, ''),
        CASE
            WHEN wo.status = 'completed' THEN 'fixed'
            WHEN wo.status = 'false_alarm' THEN 'false_alarm'
            WHEN wo.status = 'escalated' THEN 'escalated'
            ELSE NULL
        END
    );

CREATE INDEX IF NOT EXISTS idx_wo_approval_status
    ON work_orders(approval_status);

CREATE INDEX IF NOT EXISTS idx_wo_dispatch_summary_status
    ON work_orders(dispatch_summary_status);

CREATE INDEX IF NOT EXISTS idx_wo_work_result
    ON work_orders(work_result);

CREATE INDEX IF NOT EXISTS idx_wo_approval_dispatch_created
    ON work_orders(approval_status, dispatch_summary_status, created_at DESC);
