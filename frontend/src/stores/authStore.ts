import { ref, computed } from 'vue'
import { defineStore } from 'pinia'
import {
  apiLogin,
  apiRegister,
  apiRefreshToken,
  apiLogout,
  type UserInfo,
} from '@/api/auth'

const REFRESH_TOKEN_KEY = 'rt'

export const useAuthStore = defineStore('auth', () => {
  // Access Token 只存内存，页面刷新丢失后由 RT 自动换取
  const accessToken = ref<string | null>(null)
  // Refresh Token 存 localStorage，跨刷新保持登录状态
  const refreshToken = ref<string | null>(localStorage.getItem(REFRESH_TOKEN_KEY))
  const user = ref<UserInfo | null>(null)

  const isLoggedIn = computed(() => !!accessToken.value)

  // ── initSession 幂等保护 ────────────────────────────────
  // 防止路由守卫在同一次导航中被多次调用时重复触发 refresh
  let _initPromise: Promise<boolean> | null = null

  // ── 持久化 refreshToken ──────────────────────────────────
  function _saveRT(rt: string) {
    refreshToken.value = rt
    localStorage.setItem(REFRESH_TOKEN_KEY, rt)
  }

  function _clearTokens() {
    accessToken.value = null
    refreshToken.value = null
    user.value = null
    localStorage.removeItem(REFRESH_TOKEN_KEY)
  }

  // ── 登录 ─────────────────────────────────────────────────
  async function login(username: string, password: string) {
    const data = await apiLogin(username, password)
    accessToken.value = data.access_token
    _saveRT(data.refresh_token)
    user.value = data.user
  }

  // ── 注册 ─────────────────────────────────────────────────
  async function register(username: string, password: string, email?: string, phone?: string) {
    const data = await apiRegister(username, password, email, phone)
    accessToken.value = data.access_token
    _saveRT(data.refresh_token)
    user.value = data.user
  }

  // ── 拉取当前用户信息 ─────────────────────────────────────
  async function _fetchMe() {
    if (!accessToken.value) return
    try {
      const API_BASE = (import.meta.env.VITE_API_BASE as string | undefined) ?? ''
      const res = await fetch(`${API_BASE}/api/auth/me`, {
        headers: { Authorization: `Bearer ${accessToken.value}` },
      })
      if (res.ok) user.value = await res.json() as UserInfo
    } catch {
      // 非关键操作，静默忽略
    }
  }

  // ── Token 自动续期（供 http.ts 在 401 时调用）────────────
  async function refresh() {
    if (!refreshToken.value) throw new Error('no_refresh_token')
    const data = await apiRefreshToken(refreshToken.value)
    accessToken.value = data.access_token
    _saveRT(data.refresh_token)
  }

  // ── 应用启动时静默恢复登录态 ─────────────────────────────
  // 同一次页面加载只允许执行一次，后续调用复用同一个 Promise
  function initSession(): Promise<boolean> {
    if (!refreshToken.value) return Promise.resolve(false)
    if (_initPromise) return _initPromise

    _initPromise = (async () => {
      try {
        await refresh()
        await _fetchMe()
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
    refreshToken,
    user,
    isLoggedIn,
    login,
    register,
    refresh,
    logout,
    initSession,
    _clearTokens,
  }
})
