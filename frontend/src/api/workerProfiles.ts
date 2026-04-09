import { apiFetch } from './http'

export interface WorkerTeamOption {
  id: string
  team_code: string
  name: string
  description?: string | null
  service_buildings: string[]
  is_active: boolean
  created_at?: string | null
}

export interface WorkerSkillOption {
  id: string
  code: string
  name: string
  category?: string | null
  description?: string | null
  is_active: boolean
  created_at?: string | null
}

export interface WorkerBuildingOption {
  building_id: string
  primary_space_usage?: string | null
  sqm?: number | null
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
  team: WorkerTeamOption | null
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

export interface WorkerProfilesResponse {
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
  teams: WorkerTeamOption[]
  skills: WorkerSkillOption[]
  buildings: WorkerBuildingOption[]
  shift_statuses: Array<{ value: string; label: string }>
}

export interface WorkerProfileUpdatePayload {
  team_id?: string | null
  job_title?: string | null
  shift_status?: string
  dispatch_enabled?: boolean
  max_active_orders?: number
  accepts_emergency?: boolean
  service_buildings?: string[]
  notes?: string | null
  skills?: Array<{
    skill_id: string
    proficiency: number
    is_primary: boolean
  }>
}

export function listWorkerProfiles(): Promise<WorkerProfilesResponse> {
  return apiFetch<WorkerProfilesResponse>('/api/worker-profiles')
}

export function getWorkerProfileOptions(): Promise<WorkerProfileOptionsResponse> {
  return apiFetch<WorkerProfileOptionsResponse>('/api/worker-profiles/options')
}

export function updateWorkerProfile(userId: string, payload: WorkerProfileUpdatePayload): Promise<WorkerProfileItem> {
  return apiFetch<WorkerProfileItem>(`/api/worker-profiles/${encodeURIComponent(userId)}`, {
    method: 'PATCH',
    body: JSON.stringify(payload),
  })
}
