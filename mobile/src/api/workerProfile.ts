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

export const workerProfileApi = {
  me(): Promise<WorkerProfileItem> {
    return get<WorkerProfileItem>('/api/worker-profiles/me')
  },

  updateMe(payload: WorkerProfileSelfUpdatePayload): Promise<WorkerProfileItem> {
    return patch<WorkerProfileItem>('/api/worker-profiles/me', payload)
  },
}
