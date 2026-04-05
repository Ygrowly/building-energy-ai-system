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
  created_at: string | null
  updated_at: string | null
  execution_status?: string | null
  sla_due_at?: string | null
  sla_status?: string | null
  sla_minutes_left?: number | null
  events: DispatchEvent[]
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

  dispatchCandidates(ticketId: string): Promise<DispatchCandidatesResponse> {
    return get<DispatchCandidatesResponse>(`/api/work-orders/${ticketId}/dispatch-candidates`)
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
    action: 'accept' | 'arrive' | 'start' | 'request_support',
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

  dispatchTaskAction(
    dispatchId: string,
    action: 'accept' | 'arrive' | 'start',
  ): Promise<{ dispatch_id: string; message: string; status: string }> {
    return post(`/api/dispatch-tasks/${dispatchId}/${action}`)
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

  rejectDispatchTask(
    dispatchId: string,
    reason: string,
  ): Promise<{ dispatch_id: string; message: string; status: string }> {
    return post(`/api/dispatch-tasks/${dispatchId}/reject`, { reason })
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
