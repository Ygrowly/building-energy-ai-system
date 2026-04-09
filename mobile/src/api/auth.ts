import { post, get, patch, request } from './request'
import type { UserRole } from '../constants/roles'

/** 对齐后端 UserResponse */
export interface WorkerTeamInfo {
  id: string
  team_code: string
  name: string
}

export interface WorkerSkillInfo {
  skill_id?: string
  code: string
  name: string
  category?: string | null
  proficiency: number
  is_primary: boolean
}

export interface WorkerProfileInfo {
  user_id: string
  team?: WorkerTeamInfo | null
  job_title?: string | null
  shift_status: 'on_duty' | 'standby' | 'off_duty' | string
  dispatch_enabled: boolean
  max_active_orders: number
  accepts_emergency: boolean
  service_buildings: string[]
  skills: WorkerSkillInfo[]
  notes?: string | null
}

export interface UserInfo {
  id: string
  username: string
  email: string | null
  phone: string | null
  role: UserRole
  is_active: boolean
  created_at: string
  worker_profile?: WorkerProfileInfo | null
}

/** 对齐后端 LoginResponse / RegisterResponse */
export interface AuthResponse {
  access_token: string
  refresh_token: string
  token_type: 'bearer'
  expires_in: number
  user: UserInfo
}

export interface RefreshResponse {
  access_token: string
  refresh_token: string
  token_type: 'bearer'
  expires_in: number
}

/** @deprecated 保持向后兼容 */
export type LoginResponse = AuthResponse

export const authApi = {
  login(username: string, password: string): Promise<AuthResponse> {
    return request<AuthResponse>({
      url: '/api/auth/login',
      method: 'POST',
      data: { username, password },
      skipAuth: true,
    })
  },

  register(
    username: string,
    password: string,
    email?: string,
    phone?: string,
  ): Promise<AuthResponse> {
    return request<AuthResponse>({
      url: '/api/auth/register',
      method: 'POST',
      skipAuth: true,
      data: {
        username,
        password,
        ...(email ? { email } : {}),
        ...(phone ? { phone } : {}),
      },
    })
  },

  logout(refreshToken: string): Promise<void> {
    return request<void>({
      url: '/api/auth/logout',
      method: 'POST',
      skipAuth: true,
      data: { refresh_token: refreshToken },
    })
  },

  refresh(refreshToken: string): Promise<RefreshResponse> {
    return request<RefreshResponse>({
      url: '/api/auth/refresh',
      method: 'POST',
      skipAuth: true,
      data: { refresh_token: refreshToken },
    })
  },

  me(): Promise<UserInfo> {
    return get<UserInfo>('/api/auth/me')
  },

  changePassword(oldPassword: string, newPassword: string): Promise<void> {
    return post<void>('/api/auth/change-password', {
      old_password: oldPassword,
      new_password: newPassword,
    })
  },

  updateProfile(profile: { username?: string; email?: string | null; phone?: string | null }): Promise<UserInfo> {
    return patch<UserInfo>('/api/auth/me', profile)
  },
}
