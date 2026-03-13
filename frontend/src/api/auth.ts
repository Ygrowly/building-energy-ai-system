/**
 * 认证接口封装。
 * 直接用原生 fetch，不走 apiFetch，
 * 因为认证端点本身不需要 JWT Header，避免循环依赖。
 */

const API_BASE = (import.meta.env.VITE_API_BASE as string | undefined) ?? ''

export interface TokenResponse {
  access_token: string
  refresh_token: string
  token_type: string
  expires_in: number
}

export interface UserInfo {
  id: string
  username: string
  is_active: boolean
  created_at: string
}

export interface RegisterResponse extends TokenResponse {
  user: UserInfo
}

async function authFetch<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!res.ok) {
    const data = await res.json().catch(() => ({}))
    const message = (data as { detail?: string }).detail ?? `HTTP ${res.status}`
    throw new Error(message)
  }
  return res.json() as Promise<T>
}

export function apiLogin(username: string, password: string): Promise<TokenResponse> {
  return authFetch('/api/auth/login', { username, password })
}

export function apiRegister(username: string, password: string): Promise<RegisterResponse> {
  return authFetch('/api/auth/register', { username, password })
}

export function apiRefreshToken(refresh_token: string): Promise<TokenResponse> {
  return authFetch('/api/auth/refresh', { refresh_token })
}

export async function apiLogout(refresh_token: string): Promise<void> {
  await fetch(`${API_BASE}/api/auth/logout`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ refresh_token }),
  }).catch(() => {})
}
