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
