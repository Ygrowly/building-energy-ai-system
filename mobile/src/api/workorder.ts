/**
 * 工单 API — 精确对齐后端 routes_workorder.py + work_order_service.py
 */
import { get, post } from './request'
import type { WorkOrderStatus, Priority, WorkerResult, AdminAction } from '../constants/status'

/** 异常关联信息 */
export interface AnomalyLink {
  anomaly_event_id: string | null
  rule_triggered: string
  hvac_root_cause: string | null
  actual_value: number | null
  expected_value: number | null
  deviation_pct: number | null
  data_timestamp: string | null
}

/** 对齐后端 serialize_work_order 输出 */
export interface WorkOrder {
  id: string
  ticket_id: string
  building_id: string
  device_id: string | null
  issue_description: string
  suggested_action: string
  priority: Priority
  status: WorkOrderStatus
  ai_decision: 'approved' | 'rejected' | null
  ai_reason: string | null
  ai_fallback: boolean
  ai_reviewed_at: string | null
  worker_result: string | null
  worker_notes: string | null
  worker_feedback_at: string | null
  assigned_to: string | null
  assigned_at?: string | null
  assigned_to_name?: string | null
  assigned_phone?: string | null
  assigned_team_name?: string | null
  dispatch_id?: string | null
  dispatch_mode?: string | null
  dispatch_attempt_no?: number | null
  dispatch_at?: string | null
  accepted_at?: string | null
  arrived_at?: string | null
  processing_started_at?: string | null
  latest_progress_at?: string | null
  latest_progress_note?: string | null
  execution_status?: string | null
  sla_due_at?: string | null
  sla_status?: string | null
  sla_minutes_left?: number | null
  pending_dispatch_at?: string | null
  dispatch_profile?: DispatchRequirement | null
  dispatch_blocked_reason?: string | null
  admin_action: string | null
  admin_notes: string | null
  admin_reviewed_by: string | null
  admin_reviewed_at: string | null
  created_at: string
  updated_at: string
  closed_at: string | null
  source: 'auto_detect' | 'prediction' | 'manual'
  session_id: string | null
  anomaly_links: AnomalyLink[]
  current_dispatch?: DispatchTask | null
}

/** 对齐后端 GET /api/work-orders 响应（key 是 work_orders 不是 items） */
export interface WorkOrderListResponse {
  total: number
  page: number
  page_size: number
  work_orders: WorkOrder[]
}

/** 查询参数（对齐后端 Query 参数） */
export interface WorkOrderListParams {
  status?: string        // 逗号分隔的状态过滤
  building_id?: string
  priority?: string
  ai_fallback?: boolean
  page?: number
  page_size?: number
}

/** 通用操作响应 */
interface ActionResponse {
  status: string
  ticket_id: string
  message: string
  dispatch_id?: string | null
}

export interface WorkOrderAuditLog {
  id: string
  action: string
  old_status: string | null
  new_status: string
  actor_type: string
  actor_id: string | null
  detail: Record<string, any> | null
  created_at: string | null
}

export interface WorkOrderTimelineItem {
  id: string
  kind: 'work_order_audit' | 'dispatch_event'
  occurred_at: string | null
  label: string
  note: string | null
  attempt_no: number | null
  dispatch_task_id: string | null
  sort_value: string | null
}

export interface DispatchCandidate {
  user_id: string
  username: string
  phone?: string | null
  team_name?: string | null
  job_title?: string | null
  shift_status?: string
  dispatch_enabled?: boolean
  max_active_orders: number
  current_active_orders: number
  load_ratio?: number
  service_buildings: string[]
  skill_names: string[]
  matched_skill_names: string[]
  score: number
  badges: string[]
  recommend_reason: string
}

export interface DispatchRequirement {
  building_id: string
  priority: Priority
  required_skills: string[]
  preferred_team_name: string
  summary: string
}

export interface DispatchCandidatesResponse {
  ticket_id: string
  status: string
  requirement: DispatchRequirement
  candidates: DispatchCandidate[]
}

export interface DispatchEvent {
  id: string
  dispatch_task_id: string
  work_order_id: string
  incident_id: string | null
  event_type: string
  actor_type: string
  actor_id: string | null
  payload: Record<string, any> | null
  created_at: string | null
}

export interface DispatchTask {
  id: string
  dispatch_id?: string | null
  work_order_id: string
  incident_id: string | null
  attempt_no: number
  is_current: boolean
  dispatch_mode: string
  dispatch_status: string
  assigned_team_id: string | null
  assigned_team_name: string | null
  assigned_to: string | null
  assigned_to_name: string | null
  assigned_phone: string | null
  assigned_by: string | null
  selection_reason: string | null
  candidate_snapshot: Record<string, any> | null
  dispatch_profile_snapshot: Record<string, any> | null
  worker_result: string | null
  reject_reason: string | null
  cancel_reason: string | null
  support_reason: string | null
  support_team_id: string | null
  transfer_from_dispatch_id: string | null
  assigned_at: string | null
  dispatch_at?: string | null
  accept_deadline_at: string | null
  accepted_at: string | null
  arrive_deadline_at: string | null
  arrived_at: string | null
  start_deadline_at: string | null
  processing_started_at: string | null
  finish_deadline_at: string | null
  completed_at: string | null
  closed_at: string | null
  reminder_count: number
  last_reminded_at: string | null
  timeout_level: string | null
  latest_note: string | null
  latest_progress_at?: string | null
  latest_progress_note?: string | null
  created_at: string | null
  updated_at: string | null
  execution_status?: string | null
  sla_due_at?: string | null
  sla_status?: string | null
  sla_minutes_left?: number | null
  events: DispatchEvent[]
}

export interface DispatchTaskListResponse {
  total: number
  page: number
  page_size: number
  dispatch_tasks: DispatchTask[]
}

export interface DispatchHallWorkOrderSummary {
  id: string
  ticket_id: string
  building_id: string
  device_id: string | null
  priority: Priority
  status: string
  issue_description: string
  suggested_action: string
  dispatch_blocked_reason?: string | null
  incident_id?: string | null
  created_at?: string | null
  updated_at?: string | null
}

export interface DispatchHallSourceDispatchSummary {
  id: string
  dispatch_status: string
  assigned_to: string | null
  assigned_to_name: string | null
  assigned_phone: string | null
  support_reason?: string | null
  latest_note?: string | null
  assigned_at?: string | null
  accepted_at?: string | null
  arrived_at?: string | null
}

export interface DispatchHallApplication {
  id: string
  hall_entry_id: string
  applicant_user_id: string
  applicant_username: string | null
  application_type: string
  status: string
  note: string | null
  handle_note: string | null
  handled_by: string | null
  handled_by_username: string | null
  handled_at: string | null
  created_at: string | null
  updated_at: string | null
}

export interface DispatchHallEntry {
  id: string
  work_order_id: string
  incident_id: string | null
  source_dispatch_id: string | null
  entry_type: string
  status: 'open' | 'assigned' | 'accepted' | 'closed' | 'expired'
  visibility_scope: string
  target_team_ids: string[]
  target_skill_tags: string[]
  target_user_ids: string[]
  reason: string | null
  support_reason: string | null
  sla_stage: string | null
  overdue_level: string | null
  allow_direct_claim: boolean
  assigned_to: string | null
  assigned_to_name: string | null
  assigned_team_id: string | null
  assigned_by: string | null
  assigned_by_name: string | null
  created_by: string | null
  created_by_name: string | null
  expired_at: string | null
  assigned_at: string | null
  closed_at: string | null
  created_at: string | null
  updated_at: string | null
  work_order?: DispatchHallWorkOrderSummary | null
  source_dispatch?: DispatchHallSourceDispatchSummary | null
  applications: DispatchHallApplication[]
}

export interface DispatchHallListResponse {
  total: number
  page: number
  page_size: number
  hall_entries: DispatchHallEntry[]
}

export interface DispatchHallApplyResponse {
  hall_entry_id: string
  application_id: string
  message: string
}

export interface DispatchHallAssignSupportResponse {
  hall_entry: DispatchHallEntry
  message: string
}

export interface DispatchHallAssignTakeoverResponse {
  hall_entry: DispatchHallEntry
  dispatch: DispatchTask
  message: string
}

export interface WorkOrderTimelineResponse {
  ticket_id: string
  work_order: WorkOrder
  dispatch_tasks: DispatchTask[]
  audit_logs: WorkOrderAuditLog[]
  timeline: WorkOrderTimelineItem[]
}

export interface BatchDispatchRecommendation {
  ticket_id: string
  work_order_id: string
  building_id: string
  priority: Priority
  issue_description: string
  suggested_action: string
  requirement: DispatchRequirement
  candidate_count: number
  chosen_candidate: DispatchCandidate | null
  top_candidate: DispatchCandidate | null
  second_candidate: DispatchCandidate | null
  score_gap: number | null
  selection_reason: string
}

export interface BatchDispatchSkippedSummary {
  reason: string
  label: string
  count: number
}

export interface BatchDispatchPlannedAssignment {
  user_id: string
  username: string
  count: number
}

export interface BatchDispatchWorkerLoad {
  user_id: string
  username: string
  team_name: string | null
  shift_status: string | null
  current_active_orders: number
  planned_count: number
  projected_active_orders: number
  max_active_orders: number
  capacity_left_now: number
  capacity_left_after_batch: number
}

export interface BatchDispatchSkippedExample {
  ticket_id: string
  work_order_id: string
  building_id: string
  priority: Priority
  issue_description: string
  requirement: DispatchRequirement
  reason: string
  label: string
  score_gap: number | null
  top_candidate: Pick<DispatchCandidate, 'user_id' | 'username' | 'team_name' | 'score' | 'current_active_orders' | 'max_active_orders'> | null
  second_candidate: Pick<DispatchCandidate, 'user_id' | 'username' | 'team_name' | 'score' | 'current_active_orders' | 'max_active_orders'> | null
}

export interface BatchDispatchPreviewResponse {
  pending_dispatch_total: number
  scanned_count: number
  selected_count: number
  sample_size: number
  scan_limit: number
  selection_rules: {
    min_score: number
    min_gap: number
    max_per_worker?: number | null
  }
  filters?: {
    building_id?: string | null
    priority?: string | null
  }
  recommendations: BatchDispatchRecommendation[]
  skipped_summary: BatchDispatchSkippedSummary[]
  planned_assignments: BatchDispatchPlannedAssignment[]
  worker_loads: BatchDispatchWorkerLoad[]
  skipped_examples: BatchDispatchSkippedExample[]
}

export interface BatchDispatchApplyItem {
  ticket_id: string
  assigned_to: string
  dispatch_mode?: 'manual' | 'assisted' | 'auto' | 'reassigned' | 'escalation'
  selection_reason?: string | null
  notes?: string | null
}

export interface BatchDispatchApplyResponse {
  requested_count: number
  dispatched_count: number
  failed_count: number
  applied: Array<{
    ticket_id: string
    dispatch_id: string | null
    assigned_to: string
    assigned_to_name: string
    status: string
  }>
  failed: Array<{
    ticket_id: string
    assigned_to: string
    assigned_to_name: string | null
    dispatch_mode?: 'manual' | 'assisted' | 'auto' | 'reassigned' | 'escalation'
    selection_reason?: string | null
    reason: string
    reason_code: string
    current_status: string | null
    retryable: boolean
    manual_review_recommended: boolean
  }>
}

export const workOrderApi = {
  /** 工单列表 */
  list(params?: WorkOrderListParams): Promise<WorkOrderListResponse> {
    return get<WorkOrderListResponse>('/api/work-orders', params as Record<string, unknown>)
  },

  /** 单个工单详情 */
  detail(ticketId: string): Promise<WorkOrder> {
    // 后端返回的是 serialize_work_order dict，直接作为 WorkOrder
    return get<WorkOrder>(`/api/work-orders/${ticketId}`)
  },

  timeline(ticketId: string): Promise<WorkOrderTimelineResponse> {
    return get<WorkOrderTimelineResponse>(`/api/work-orders/${ticketId}/timeline`)
  },

  dispatchCandidates(ticketId: string): Promise<DispatchCandidatesResponse> {
    return get<DispatchCandidatesResponse>(`/api/work-orders/${ticketId}/dispatch-candidates`)
  },

  batchDispatchPreview(params?: {
    sample_size?: number
    scan_limit?: number
    min_score?: number
    min_gap?: number
    building_id?: string
    priority?: string
    max_per_worker?: number
  }): Promise<BatchDispatchPreviewResponse> {
    return get<BatchDispatchPreviewResponse>('/api/work-orders/batch-dispatch-preview', params as Record<string, unknown>)
  },

  batchDispatch(items: BatchDispatchApplyItem[]): Promise<BatchDispatchApplyResponse> {
    return post<BatchDispatchApplyResponse>('/api/work-orders/batch-dispatch', { items })
  },

  dispatch(
    ticketId: string,
    assignedTo: string,
    notes?: string,
    dispatchMode: 'manual' | 'assisted' | 'auto' | 'reassigned' | 'escalation' = 'manual',
  ): Promise<ActionResponse> {
    return post<ActionResponse>(`/api/work-orders/${ticketId}/dispatch`, {
      assigned_to: assignedTo,
      dispatch_mode: dispatchMode,
      notes: notes || null,
    })
  },

  workerAction(
    ticketId: string,
    action: 'accept' | 'arrive' | 'start' | 'request_support' | 'support_resolved',
    notes?: string,
    supportTeamId?: string,
  ): Promise<ActionResponse> {
    return post<ActionResponse>(`/api/work-orders/${ticketId}/worker-action`, {
      action,
      notes: notes || null,
      support_team_id: supportTeamId || null,
    })
  },

  dispatchTaskDetail(dispatchId: string): Promise<DispatchTask> {
    return get<DispatchTask>(`/api/dispatch-tasks/${dispatchId}`)
  },

  listDispatchTasks(params?: {
    assigned_to?: string
    work_order_id?: string
    incident_id?: string
    status?: string
    current_only?: boolean
    include_events?: boolean
    page?: number
    page_size?: number
  }): Promise<DispatchTaskListResponse> {
    return get<DispatchTaskListResponse>('/api/dispatch-tasks', params as Record<string, unknown>)
  },

  listDispatchHallEntries(params?: {
    status?: string
    entry_type?: string
    assigned_to?: string
    work_order_id?: string
    incident_id?: string
    source_dispatch_id?: string
    include_applications?: boolean
    page?: number
    page_size?: number
  }): Promise<DispatchHallListResponse> {
    return get<DispatchHallListResponse>('/api/dispatch-hall', params as Record<string, unknown>)
  },

  dispatchHallDetail(entryId: string): Promise<DispatchHallEntry> {
    return get<DispatchHallEntry>(`/api/dispatch-hall/${entryId}`)
  },

  applyDispatchHallSupport(
    entryId: string,
    note?: string,
  ): Promise<DispatchHallApplyResponse> {
    return post<DispatchHallApplyResponse>(`/api/dispatch-hall/${entryId}/apply-support`, {
      note: note || null,
    })
  },

  applyDispatchHallTakeover(
    entryId: string,
    note?: string,
  ): Promise<DispatchHallApplyResponse> {
    return post<DispatchHallApplyResponse>(`/api/dispatch-hall/${entryId}/apply-takeover`, {
      note: note || null,
    })
  },

  assignDispatchHallSupport(
    entryId: string,
    assignedTo: string,
    applicationId?: string,
    note?: string,
  ): Promise<DispatchHallAssignSupportResponse> {
    return post<DispatchHallAssignSupportResponse>(`/api/dispatch-hall/${entryId}/assign-support`, {
      assigned_to: assignedTo,
      application_id: applicationId || null,
      note: note || null,
    })
  },

  assignDispatchHallTakeover(
    entryId: string,
    assignedTo: string,
    reason: string,
    applicationId?: string,
    dispatchMode: 'hall_takeover' | 'reassigned' | 'manual' | 'assisted' | 'auto' | 'escalation' = 'hall_takeover',
  ): Promise<DispatchHallAssignTakeoverResponse> {
    return post<DispatchHallAssignTakeoverResponse>(`/api/dispatch-hall/${entryId}/assign-takeover`, {
      assigned_to: assignedTo,
      application_id: applicationId || null,
      reason,
      dispatch_mode: dispatchMode,
    })
  },

  rejectDispatchHallApplication(
    applicationId: string,
    note?: string,
  ): Promise<{ application_id: string; message: string }> {
    return post(`/api/dispatch-hall/applications/${applicationId}/reject`, {
      note: note || null,
    })
  },

  withdrawDispatchHallApplication(
    applicationId: string,
  ): Promise<{ application_id: string; message: string }> {
    return post(`/api/dispatch-hall/applications/${applicationId}/withdraw`)
  },

  closeDispatchHallEntry(
    entryId: string,
    note?: string,
  ): Promise<{ hall_entry_id: string; message: string }> {
    return post(`/api/dispatch-hall/${entryId}/close`, {
      note: note || null,
    })
  },

  acceptAssignedSupportTask(
    entryId: string,
    note?: string,
  ): Promise<{ hall_entry: DispatchHallEntry; message: string }> {
    return post(`/api/dispatch-hall/${entryId}/accept-support`, {
      note: note || null,
    })
  },

  rejectAssignedSupportTask(
    entryId: string,
    note?: string,
  ): Promise<{ hall_entry: DispatchHallEntry; message: string }> {
    return post(`/api/dispatch-hall/${entryId}/reject-support`, {
      note: note || null,
    })
  },

  dispatchTaskAction(
    dispatchId: string,
    action: 'accept' | 'arrive' | 'start',
  ): Promise<{ dispatch_id: string; message: string; status: string }> {
    return post(`/api/dispatch-tasks/${dispatchId}/${action}`)
  },

  nudgeDispatchTask(
    dispatchId: string,
    message?: string,
  ): Promise<{ dispatch_id: string; message: string; status: string; reminder_count: number; last_reminded_at: string | null }> {
    return post(`/api/dispatch-tasks/${dispatchId}/nudge`, {
      message: message || null,
    })
  },

  requestDispatchSupport(
    dispatchId: string,
    reason: string,
    supportTeamId?: string,
  ): Promise<{ dispatch_id: string; message: string; status: string }> {
    return post(`/api/dispatch-tasks/${dispatchId}/request-support`, {
      reason,
      support_team_id: supportTeamId || null,
    })
  },

  resolveDispatchSupport(
    dispatchId: string,
    notes?: string,
  ): Promise<{ dispatch_id: string; message: string; status: string }> {
    return post(`/api/dispatch-tasks/${dispatchId}/support-resolved`, {
      notes: notes || null,
    })
  },

  rejectDispatchTask(
    dispatchId: string,
    reason: string,
  ): Promise<{ dispatch_id: string; message: string; status: string }> {
    return post(`/api/dispatch-tasks/${dispatchId}/reject`, { reason })
  },

  cancelDispatchTask(
    dispatchId: string,
    reason: string,
  ): Promise<{ dispatch_id: string; message: string; status: string }> {
    return post(`/api/dispatch-tasks/${dispatchId}/cancel`, { reason })
  },

  reassignDispatchTask(
    dispatchId: string,
    assignedTo: string,
    reason: string,
    dispatchMode: 'reassigned' | 'manual' | 'assisted' | 'auto' | 'escalation' = 'reassigned',
  ): Promise<{ dispatch_id: string; new_dispatch_id: string; message: string; status: string }> {
    return post(`/api/dispatch-tasks/${dispatchId}/reassign`, {
      assigned_to: assignedTo,
      reason,
      dispatch_mode: dispatchMode,
    })
  },

  completeDispatchTask(
    dispatchId: string,
    result: WorkerResult,
    notes?: string,
  ): Promise<{ dispatch_id: string; message: string; status: string }> {
    return post(`/api/dispatch-tasks/${dispatchId}/complete`, {
      result,
      notes: notes || null,
    })
  },

  /** 维修人员反馈（对齐后端：body 字段是 result + notes） */
  workerFeedback(
    ticketId: string,
    result: WorkerResult,
    notes?: string,
  ): Promise<ActionResponse> {
    return post<ActionResponse>(`/api/work-orders/${ticketId}/worker-feedback`, {
      result,
      notes: notes || null,
    })
  },

  /** 管理员审阅（对齐后端：body 字段是 action + notes） */
  adminReview(
    ticketId: string,
    action: AdminAction,
    notes?: string,
  ): Promise<ActionResponse> {
    return post<ActionResponse>(`/api/work-orders/${ticketId}/admin-review`, {
      action,
      notes: notes || null,
    })
  },

  /** 手动触发 AI 重审 */
  triggerAiReview(ticketId: string): Promise<{ ticket_id: string; message: string }> {
    return post(`/api/work-orders/${ticketId}/ai-review-trigger`)
  },
}
