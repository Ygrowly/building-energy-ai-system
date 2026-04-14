import { apiFetch } from '@/api/http'

export type MaintenanceExperienceSourceType =
  | 'worker_note'
  | 'operator_note'
  | 'completion_summary'
  | 'step_event'

export type MaintenanceExperienceFeedbackType = 'helpful' | 'unhelpful' | 'incorrect'

export interface MaintenanceExperienceConflictFlag {
  type?: string | null
  message?: string | null
}

export interface MaintenanceExperienceItem {
  id: string
  source_type: string
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
  status?: string
}

export interface MaintenanceExperienceSearchResponse {
  query: string
  items: MaintenanceExperienceItem[]
  total: number
  sort_by: 'score' | 'recent' | 'usage' | string
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

export interface MaintenanceExperienceFeedbackResponse {
  ok: boolean
  experience_id: string
  feedback: string
  helpful_count: number
  unhelpful_count: number
  incorrect_count: number
}

function buildQuery(params: MaintenanceExperienceSearchParams) {
  const search = new URLSearchParams()
  Object.entries(params).forEach(([key, value]) => {
    if (value === undefined || value === null || value === '') return
    search.set(key, String(value))
  })
  return search.toString()
}

export const maintenanceExperienceApi = {
  search(params: MaintenanceExperienceSearchParams = {}): Promise<MaintenanceExperienceSearchResponse> {
    const query = buildQuery(params)
    return apiFetch<MaintenanceExperienceSearchResponse>(
      query ? `/api/maintenance-experiences/search?${query}` : '/api/maintenance-experiences/search',
    )
  },
  create(payload: MaintenanceExperienceCreatePayload): Promise<MaintenanceExperienceItem> {
    return apiFetch<MaintenanceExperienceItem>('/api/maintenance-experiences', {
      method: 'POST',
      body: JSON.stringify(payload),
    })
  },
  feedback(
    experienceId: string,
    payload: {
      feedback: MaintenanceExperienceFeedbackType
      work_order_id?: string | null
      note?: string | null
    },
  ): Promise<MaintenanceExperienceFeedbackResponse> {
    return apiFetch<MaintenanceExperienceFeedbackResponse>(`/api/maintenance-experiences/${experienceId}/feedback`, {
      method: 'POST',
      body: JSON.stringify(payload),
    })
  },
}
