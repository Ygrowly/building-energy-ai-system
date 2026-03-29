import { get, post } from './request'

export type WorkOrderStatus =
  | 'new'
  | 'pending_ai_review'
  | 'ai_approved'
  | 'ai_rejected'
  | 'dispatched'
  | 'completed'
  | 'false_alarm'
  | 'escalated'
  | 'closed'

export type Priority = 'high' | 'medium' | 'low'

export type WorkerFeedback = 'fixed' | 'false_alarm' | 'escalated'

export interface WorkOrder {
  id: string
  ticket_id: string
  building_id: string
  building_name?: string
  anomaly_type: string
  description: string
  priority: Priority
  status: WorkOrderStatus
  source: 'auto_detect' | 'prediction' | 'manual'
  created_at: string
  updated_at: string
  ai_decision?: 'approved' | 'rejected'
  ai_reasoning?: string
  worker_feedback?: WorkerFeedback
  worker_note?: string
  admin_override?: boolean
  assigned_to?: string
}

export interface WorkOrderListResponse {
  items: WorkOrder[]
  total: number
  page: number
  page_size: number
}

export interface WorkOrderListParams {
  page?: number
  page_size?: number
  status?: WorkOrderStatus | WorkOrderStatus[]
  priority?: Priority
  building_id?: string
  assigned_to_me?: boolean
}

export const workOrderApi = {
  list(params?: WorkOrderListParams): Promise<WorkOrderListResponse> {
    return get<WorkOrderListResponse>('/api/work-orders', params as Record<string, unknown>)
  },

  get(ticketId: string): Promise<WorkOrder> {
    return get<WorkOrder>(`/api/work-orders/${ticketId}`)
  },

  // 维修人员提交反馈
  workerFeedback(
    ticketId: string,
    feedback: WorkerFeedback,
    note?: string,
  ): Promise<WorkOrder> {
    return post<WorkOrder>(`/api/work-orders/${ticketId}/worker-feedback`, {
      feedback,
      note,
    })
  },

  // 管理员/运维人员审阅（可覆盖AI决策）
  adminReview(
    ticketId: string,
    action: 'approve' | 'reject' | 'confirm',
    reason?: string,
  ): Promise<WorkOrder> {
    return post<WorkOrder>(`/api/work-orders/${ticketId}/admin-review`, {
      action,
      reason,
    })
  },

  // 手动触发 AI 重审
  triggerAiReview(ticketId: string): Promise<WorkOrder> {
    return post<WorkOrder>(`/api/work-orders/${ticketId}/ai-review-trigger`)
  },
}
