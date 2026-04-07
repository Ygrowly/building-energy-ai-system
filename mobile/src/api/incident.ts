import { get } from './request'
import type { DispatchTask } from './workorder'

export interface IncidentCurrentWorkOrder {
  id: string
  ticket_id: string
  status: string
  priority: string
  ai_decision: 'approved' | 'rejected' | null
  ai_reason: string | null
  ai_fallback: boolean
  worker_result: string | null
  worker_notes: string | null
  assigned_to: string | null
  assigned_to_name?: string | null
  assigned_phone?: string | null
  assigned_team_name?: string | null
  suggested_action?: string | null
  dispatch_blocked_reason?: string | null
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
  created_at: string | null
  updated_at: string | null
}

export interface Incident {
  id: string
  incident_id: string
  source: string
  building_id: string
  device_id: string | null
  rule_triggered: string
  hvac_root_cause: string | null
  incident_status: string
  workflow_status: string | null
  priority: string
  summary_text: string
  first_seen_at: string | null
  last_seen_at: string | null
  continuity_expires_at: string | null
  anomaly_count: number
  peak_deviation_pct: number | null
  latest_actual_value: number | null
  latest_expected_value: number | null
  is_active: boolean
  resolved_at: string | null
  created_at: string | null
  updated_at: string | null
  dispatch_blocked_reason?: string | null
  latest_dispatch_note?: string | null
  current_work_order: IncidentCurrentWorkOrder | null
  current_dispatch?: (Partial<DispatchTask> & Pick<DispatchTask, 'id' | 'dispatch_status' | 'attempt_no'>) | null
}

export interface IncidentListResponse {
  total: number
  page: number
  page_size: number
  incidents: Incident[]
}

export interface IncidentEventLink {
  id: string
  data_timestamp: string | null
  actual_value: number | null
  expected_value: number | null
  deviation_pct: number | null
  rule_triggered: string
  hvac_root_cause: string | null
  type: 'event'
}

export interface IncidentPredictionLink {
  id: string
  forecast_for_timestamp: string | null
  predicted_value: number | null
  expected_value: number | null
  deviation_pct: number | null
  metric_name: string
  risk_level: string | null
  type: 'prediction'
}

export interface IncidentWorkOrder {
  id: string
  ticket_id: string
  status: string
  priority: string
  created_at: string | null
  updated_at: string | null
  worker_result: string | null
  worker_notes: string | null
  ai_decision: 'approved' | 'rejected' | null
  ai_reason: string | null
  assigned_to?: string | null
  assigned_to_name?: string | null
  assigned_phone?: string | null
  assigned_team_name?: string | null
  suggested_action?: string | null
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
}

export interface IncidentDetail extends Incident {
  work_orders: IncidentWorkOrder[]
  event_links: IncidentEventLink[]
  prediction_links: IncidentPredictionLink[]
}

export interface IncidentListParams {
  workflow_status?: string
  building_id?: string
  page?: number
  page_size?: number
}

export const incidentApi = {
  list(params?: IncidentListParams): Promise<IncidentListResponse> {
    return get<IncidentListResponse>('/api/incidents', params as Record<string, unknown>)
  },
  detail(incidentId: string): Promise<IncidentDetail> {
    return get<IncidentDetail>(`/api/incidents/${incidentId}`)
  },
}
