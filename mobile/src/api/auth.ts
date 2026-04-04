import { post, get, patch } from './request'
import type { UserRole } from '../constants/roles'

/** 对齐后端 UserResponse */
export interface UserInfo {
  id: string
  username: string
  email: string | null
  phone: string | null
  role: UserRole
  is_active: boolean
  created_at: string
}

/** 对齐后端 LoginResponse / RegisterResponse */
export interface AuthResponse {
  access_token: string
  refresh_token: string
  token_type: 'bearer'
  expires_in: number
  user: UserInfo
}

/** @deprecated 保持向后兼容 */
export type LoginResponse = AuthResponse

export const authApi = {
  login(username: string, password: string): Promise<AuthResponse> {
    return post<AuthResponse>('/api/auth/login', { username, password })
  },

  register(
    username: string,
    password: string,
    email?: string,
    phone?: string,
  ): Promise<AuthResponse> {
    return post<AuthResponse>('/api/auth/register', {
      username,
      password,
      ...(email ? { email } : {}),
      ...(phone ? { phone } : {}),
    })
  },

  logout(refreshToken: string): Promise<void> {
    return post<void>('/api/auth/logout', { refresh_token: refreshToken })
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
