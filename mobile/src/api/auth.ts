import { request, get, post } from './request'

export interface UserInfo {
  id: string
  username: string
  email?: string
  phone?: string
  role: 'admin' | 'operator' | 'worker'
  is_active: boolean
}

export interface LoginResponse {
  user: UserInfo
  access_token: string
  refresh_token: string
  expires_in: number
}

export const authApi = {
  login(username: string, password: string): Promise<LoginResponse> {
    return post<LoginResponse>('/api/auth/login', { username, password })
  },

  logout(refreshToken: string): Promise<void> {
    return post<void>('/api/auth/logout', { refresh_token: refreshToken })
  },

  me(): Promise<UserInfo> {
    return get<UserInfo>('/api/auth/me')
  },

  refresh(refreshToken: string): Promise<{ access_token: string; refresh_token: string; expires_in: number }> {
    return request({
      url: '/api/auth/refresh',
      method: 'POST',
      data: { refresh_token: refreshToken },
      skipAuth: true,
    })
  },

  changePassword(oldPassword: string, newPassword: string): Promise<void> {
    return post<void>('/api/auth/change-password', {
      old_password: oldPassword,
      new_password: newPassword,
    })
  },
}
