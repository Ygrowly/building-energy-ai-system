-- 021_dispatch_query_indexes.sql
-- 派单执行层性能补强：
--   1. incident 列表：assigned_to / workflow_status + 最近时间排序
--   2. batch dispatch preview：pending_dispatch 时间窗扫描
--   3. dispatch 列表与 SLA 扫描：assigned_to / is_current / status + assigned_at
--   4. 工单大厅列表：status / entry_type + created_at
--   5. 大厅申请加载：hall_entry_id + created_at

CREATE INDEX IF NOT EXISTS idx_incident_workflow_last_seen
    ON anomaly_incidents(workflow_status, last_seen_at DESC, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_incident_assignee_last_seen
    ON anomaly_incidents(current_assigned_to, last_seen_at DESC, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_wo_status_pending_dispatch_created
    ON work_orders(status, pending_dispatch_at ASC, created_at ASC);

CREATE INDEX IF NOT EXISTS idx_dispatch_assignee_current_time
    ON dispatch_tasks(assigned_to, is_current, assigned_at DESC, attempt_no DESC);

CREATE INDEX IF NOT EXISTS idx_dispatch_current_status_assigned_at
    ON dispatch_tasks(is_current, dispatch_status, assigned_at ASC);

CREATE INDEX IF NOT EXISTS idx_dispatch_hall_status_type_created
    ON dispatch_hall_entries(status, entry_type, created_at DESC, id DESC);

CREATE INDEX IF NOT EXISTS idx_dispatch_hall_application_entry_created
    ON dispatch_hall_applications(hall_entry_id, created_at ASC);
