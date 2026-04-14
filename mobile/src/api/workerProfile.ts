import { get, patch } from './request'

export interface WorkerTeamInfo {
  id: string
  team_code: string
  name: string
  description?: string | null
  service_buildings: string[]
  is_active: boolean
  created_at?: string | null
}

export interface WorkerProfileSkill {
  skill_id: string
  code?: string | null
  name?: string | null
  category?: string | null
  proficiency: number
  is_primary: boolean
}

export interface WorkerProfileItem {
  user: {
    id: string
    username: string
    email?: string | null
    phone?: string | null
    role: string
    is_active: boolean
    created_at?: string | null
  }
  profile_exists: boolean
  team: WorkerTeamInfo | null
  team_id?: string | null
  job_title?: string | null
  shift_status: string
  dispatch_enabled: boolean
  max_active_orders: number
  active_orders: number
  capacity_ratio: number
  accepts_emergency: boolean
  service_buildings: string[]
  notes?: string | null
  skills: WorkerProfileSkill[]
  created_at?: string | null
  updated_at?: string | null
}

export interface WorkerProfileSelfUpdatePayload {
  shift_status?: 'on_duty' | 'standby' | 'busy' | 'off_duty' | string
  dispatch_enabled?: boolean
  accepts_emergency?: boolean
  notes?: string | null
}

export interface WorkerProfileListResponse {
  total: number
  profiles: WorkerProfileItem[]
  summary: {
    workers_total: number
    dispatch_enabled: number
    on_duty: number
    over_capacity: number
  }
}

export interface WorkerProfileOptionsResponse {
  teams: WorkerTeamInfo[]
  buildings: Array<{
    building_id: string
    primary_space_usage?: string | null
    sqm?: number | null
  }>
}

export const workerProfileApi = {
  list(): Promise<WorkerProfileListResponse> {
    return get<WorkerProfileListResponse>('/api/worker-profiles')
  },

  options(): Promise<WorkerProfileOptionsResponse> {
    return get<WorkerProfileOptionsResponse>('/api/worker-profiles/options')
  },

  me(): Promise<WorkerProfileItem> {
    return get<WorkerProfileItem>('/api/worker-profiles/me')
  },

  updateMe(payload: WorkerProfileSelfUpdatePayload): Promise<WorkerProfileItem> {
    return patch<WorkerProfileItem>('/api/worker-profiles/me', payload)
  },
}
