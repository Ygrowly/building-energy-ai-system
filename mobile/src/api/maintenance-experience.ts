import { get, post } from './request'

export type MaintenanceExperienceFeedbackType = 'helpful' | 'unhelpful' | 'incorrect'

export type MaintenanceExperienceSourceType =
  | 'worker_note'
  | 'operator_note'
  | 'completion_summary'
  | 'step_event'

export interface MaintenanceExperienceConflictFlag {
  type?: string | null
  message?: string | null
}

export interface MaintenanceExperienceItem {
  id: string
  source_type: MaintenanceExperienceSourceType | string
  source_work_order_id?: string | null
  source_dispatch_id?: string | null
  source_step_plan_id?: string | null
  contributor_user_id?: string | null
  contributor_role?: string | null
  building_id?: string | null
  device_id?: string | null
  device_type?: string | null
  fault_type?: string | null
  organized_text?: string | null
  source_text?: string | null
  fault_keywords?: string[]
  symptom_tags?: string[]
  suggested_steps?: string[]
  safety_notes?: string[]
  applicable_conditions?: string[]
  conflict_flags?: MaintenanceExperienceConflictFlag[]
  vector_index_status?: string | null
  usage_count?: number
  helpful_count?: number
  unhelpful_count?: number
  incorrect_count?: number
  is_active?: boolean
  score?: number | null
  created_at?: string | null
  updated_at?: string | null
}

export interface MaintenanceExperienceRecommendation {
  experience_id: string
  source_work_order_id?: string | null
  organized_text?: string | null
  confidence?: number | null
  helpful_count?: number
  safety_notes?: string[]
  conflict_flags?: MaintenanceExperienceConflictFlag[]
}

export interface MaintenanceExperienceSearchResponse {
  query: string
  items: MaintenanceExperienceItem[]
  total: number
  sort_by: 'score' | 'recent' | 'usage' | string
}

export interface MaintenanceExperienceCreatePayload {
  source_type: MaintenanceExperienceSourceType | string
  source_text: string
  source_work_order_id?: string | null
  source_dispatch_id?: string | null
  source_step_plan_id?: string | null
  contributor_user_id?: string | null
  contributor_role?: string | null
  building_id?: string | null
  device_id?: string | null
  device_type?: string | null
  fault_type?: string | null
}

export interface MaintenanceExperienceSearchParams {
  query?: string | null
  building_id?: string | null
  device_type?: string | null
  fault_type?: string | null
  limit?: number
  include_inactive?: boolean
  sort_by?: 'score' | 'recent' | 'usage'
}

export interface MaintenanceExperienceFeedbackResponse {
  ok: boolean
  experience_id: string
  feedback: MaintenanceExperienceFeedbackType | string
  helpful_count: number
  unhelpful_count: number
  incorrect_count: number
}

export const maintenanceExperienceApi = {
  search(params: MaintenanceExperienceSearchParams): Promise<MaintenanceExperienceSearchResponse> {
    return get<MaintenanceExperienceSearchResponse>('/api/maintenance-experiences/search', params as Record<string, unknown>)
  },
  create(payload: MaintenanceExperienceCreatePayload): Promise<MaintenanceExperienceItem & { status?: string }> {
    return post<MaintenanceExperienceItem & { status?: string }>('/api/maintenance-experiences', payload)
  },
  feedback(
    experienceId: string,
    payload: {
      feedback: MaintenanceExperienceFeedbackType
      work_order_id?: string | null
      note?: string | null
    },
  ): Promise<MaintenanceExperienceFeedbackResponse> {
    return post<MaintenanceExperienceFeedbackResponse>(`/api/maintenance-experiences/${experienceId}/feedback`, payload)
  },
}
