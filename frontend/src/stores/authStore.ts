import { ref, computed } from 'vue'
import { defineStore } from 'pinia'
import {
  apiLogin,
  apiRegister,
  apiRefreshToken,
  apiLogout,
  type UserInfo,
} from '@/api/auth'
import { clearCachedApi } from '@/api/cached'

const ACCESS_TOKEN_KEY = 'at'
const ACCESS_TOKEN_EXPIRES_AT_KEY = 'at_exp'
const REFRESH_TOKEN_KEY = 'rt'
const USER_KEY = 'auth_user'
const ACCESS_TOKEN_SKEW_MS = 30_000

function readStoredString(key: string): string | null {
  const value = localStorage.getItem(key)
  return value && value.trim() ? value : null
}

function readStoredNumber(key: string): number | null {
  const value = Number(localStorage.getItem(key))
  return Number.isFinite(value) ? value : null
}

function readStoredUser(): UserInfo | null {
  const raw = localStorage.getItem(USER_KEY)
  if (!raw) return null

  try {
    return JSON.parse(raw) as UserInfo
  } catch {
    localStorage.removeItem(USER_KEY)
    return null
  }
}

function isAccessTokenUsable(token: string | null, expiresAt: number | null): boolean {
  return Boolean(token && expiresAt && expiresAt - ACCESS_TOKEN_SKEW_MS > Date.now())
}

export const useAuthStore = defineStore('auth', () => {
  // Access Token 只存内存，页面刷新丢失后由 RT 自动换取
  const accessToken = ref<string | null>(readStoredString(ACCESS_TOKEN_KEY))
  const accessTokenExpiresAt = ref<number | null>(readStoredNumber(ACCESS_TOKEN_EXPIRES_AT_KEY))
  // Refresh Token 存 localStorage，跨刷新保持登录状态
  const refreshToken = ref<string | null>(readStoredString(REFRESH_TOKEN_KEY))
  const user = ref<UserInfo | null>(readStoredUser())
  let _accessTokenExpiryTimer: ReturnType<typeof globalThis.setTimeout> | null = null

  const isLoggedIn = computed(() => Boolean(accessToken.value && accessTokenExpiresAt.value))

  // ── initSession 幂等保护 ────────────────────────────────
  // 防止路由守卫在同一次导航中被多次调用时重复触发 refresh
  let _initPromise: Promise<boolean> | null = null
  let _refreshPromise: Promise<void> | null = null

  // ── 持久化 refreshToken ──────────────────────────────────
  function _clearAccessTokenExpiryTimer() {
    if (_accessTokenExpiryTimer == null) return
    globalThis.clearTimeout(_accessTokenExpiryTimer)
    _accessTokenExpiryTimer = null
  }

  function _scheduleAccessTokenExpiry() {
    _clearAccessTokenExpiryTimer()
    if (!accessToken.value || !accessTokenExpiresAt.value) return

    const delayMs = accessTokenExpiresAt.value - ACCESS_TOKEN_SKEW_MS - Date.now()
    if (delayMs <= 0) {
      _clearAccessToken()
      return
    }

    _accessTokenExpiryTimer = globalThis.setTimeout(() => {
      _clearAccessToken()
    }, delayMs)
  }

  function _saveAccessToken(token: string, expiresIn: number) {
    const expiresAt = Date.now() + Math.max(expiresIn, 0) * 1000
    accessToken.value = token
    accessTokenExpiresAt.value = expiresAt
    localStorage.setItem(ACCESS_TOKEN_KEY, token)
    localStorage.setItem(ACCESS_TOKEN_EXPIRES_AT_KEY, String(expiresAt))
    _scheduleAccessTokenExpiry()
  }

  function _clearAccessToken() {
    _clearAccessTokenExpiryTimer()
    accessToken.value = null
    accessTokenExpiresAt.value = null
    localStorage.removeItem(ACCESS_TOKEN_KEY)
    localStorage.removeItem(ACCESS_TOKEN_EXPIRES_AT_KEY)
  }

  function _saveRT(rt: string) {
    refreshToken.value = rt
    localStorage.setItem(REFRESH_TOKEN_KEY, rt)
  }

  function _saveUser(nextUser: UserInfo | null) {
    user.value = nextUser
    if (nextUser) {
      localStorage.setItem(USER_KEY, JSON.stringify(nextUser))
      return
    }
    localStorage.removeItem(USER_KEY)
  }

  function _pruneExpiredAccessToken() {
    if (accessToken.value && !isAccessTokenUsable(accessToken.value, accessTokenExpiresAt.value)) {
      _clearAccessToken()
      return
    }
    _scheduleAccessTokenExpiry()
  }

  function getAccessToken() {
    _pruneExpiredAccessToken()
    return accessToken.value
  }

  function _clearTokens() {
    _clearAccessToken()
    refreshToken.value = null
    localStorage.removeItem(REFRESH_TOKEN_KEY)
    _saveUser(null)
    clearCachedApi()
  }

  _pruneExpiredAccessToken()

  // ── 登录 ─────────────────────────────────────────────────
  async function login(username: string, password: string) {
    const data = await apiLogin(username, password)
    clearCachedApi()
    _saveAccessToken(data.access_token, data.expires_in)
    _saveRT(data.refresh_token)
    _saveUser(data.user)
  }

  // ── 注册 ─────────────────────────────────────────────────
  async function register(username: string, password: string, email?: string, phone?: string) {
    const data = await apiRegister(username, password, email, phone)
    clearCachedApi()
    _saveAccessToken(data.access_token, data.expires_in)
    _saveRT(data.refresh_token)
    _saveUser(data.user)
  }

  // ── 拉取当前用户信息 ─────────────────────────────────────
  async function _fetchMe() {
    const token = getAccessToken()
    if (!token) return
    try {
      const API_BASE = (import.meta.env.VITE_API_BASE as string | undefined) ?? ''
      const res = await fetch(`${API_BASE}/api/auth/me`, {
        headers: { Authorization: `Bearer ${token}` },
      })
      if (res.ok) _saveUser(await res.json() as UserInfo)
    } catch {
      // 非关键操作，静默忽略
    }
  }

  // ── Token 自动续期（供 http.ts 在 401 时调用）────────────
  async function refresh() {
    _pruneExpiredAccessToken()
    if (isLoggedIn.value) return
    if (!refreshToken.value) throw new Error('no_refresh_token')
    if (_refreshPromise) return _refreshPromise

    _refreshPromise = (async () => {
      const data = await apiRefreshToken(refreshToken.value as string)
      _saveAccessToken(data.access_token, data.expires_in)
      _saveRT(data.refresh_token)

      if (data.user) {
        _saveUser(data.user)
        return
      }

      if (!user.value) {
        await _fetchMe()
      }
    })().finally(() => {
      _refreshPromise = null
    })

    return _refreshPromise
  }

  // ── 应用启动时静默恢复登录态 ─────────────────────────────
  // 同一次页面加载只允许执行一次，后续调用复用同一个 Promise
  function initSession(): Promise<boolean> {
    _pruneExpiredAccessToken()
    if (isLoggedIn.value) {
      void _fetchMe()
      return Promise.resolve(true)
    }

    if (!refreshToken.value) return Promise.resolve(false)
    if (_initPromise) return _initPromise

    _initPromise = (async () => {
      try {
        await refresh()
        if (!user.value) {
          void _fetchMe()
        }
        return true
      } catch {
        _clearTokens()
        return false
      } finally {
        // 完成后清除，允许登录/登出后重新初始化
        _initPromise = null
      }
    })()

    return _initPromise
  }

  // ── 退出登录 ──────────────────────────────────────────────
  async function logout() {
    const rt = refreshToken.value
    _clearTokens()
    if (rt) await apiLogout(rt)
  }

  return {
    accessToken,
    accessTokenExpiresAt,
    refreshToken,
    user,
    isLoggedIn,
    getAccessToken,
    login,
    register,
    refresh,
    logout,
    initSession,
    _clearTokens,
  }
})
