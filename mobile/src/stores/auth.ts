import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { authApi, type UserInfo } from '../api/auth'
import { isOperatorRole, isWorkerRole, ALLOWED_ROLES, type UserRole } from '../constants/roles'
import { rememberLoginPersona } from '../utils/login-persona'

export const useAuthStore = defineStore('auth', () => {
  const user = ref<UserInfo | null>(null)
  const accessToken = ref<string | null>(null)
  const refreshToken = ref<string | null>(null)

  const isLoggedIn = computed(() => !!accessToken.value && !!user.value)
  const isOperator = computed(() => !!user.value && isOperatorRole(user.value.role))
  const isWorker   = computed(() => !!user.value && isWorkerRole(user.value.role))

  /**
   * 启动时从本地存储恢复状态（只恢复，不跳转）。
   * 跳转逻辑由启动页（splash）在计时结束后统一调用 redirectAfterSplash()。
   */
  function init() {
    const token       = uni.getStorageSync('access_token')
    const storedUser  = uni.getStorageSync('user_info')
    const storedRefresh = uni.getStorageSync('refresh_token')

    if (token && storedUser) {
      accessToken.value  = token
      refreshToken.value = storedRefresh
      try {
        user.value = typeof storedUser === 'string' ? JSON.parse(storedUser) : storedUser
      } catch {
        _clearTokens()
      }
    }
  }

  /** 启动页计时结束后调用：已登录 → 跳首页，未登录 → 跳登录页 */
  function redirectAfterSplash() {
    if (isLoggedIn.value && user.value) {
      redirectByRole()
    } else {
      uni.reLaunch({ url: '/pages/login/index' })
    }
  }

  function _saveAuth(res: { access_token: string; refresh_token: string; user: import('../api/auth').UserInfo }) {
    if (!ALLOWED_ROLES.includes(res.user.role as UserRole)) {
      throw new Error('当前账号角色暂不支持移动端登录')
    }
    accessToken.value = res.access_token
    refreshToken.value = res.refresh_token
    user.value = res.user
    uni.setStorageSync('access_token', res.access_token)
    uni.setStorageSync('refresh_token', res.refresh_token)
    uni.setStorageSync('user_info', JSON.stringify(res.user))
  }

  async function login(username: string, password: string) {
    const res = await authApi.login(username, password)
    rememberLoginPersona(username, res.user.role)
    _saveAuth(res)
    redirectByRole()
  }

  async function register(username: string, password: string, email?: string, phone?: string) {
    const res = await authApi.register(username, password, email, phone)
    rememberLoginPersona(username, res.user.role)
    // 注册成功后不自动登录，清空 token，让用户手动登录
    _clearTokens()
  }

  async function logout() {
    if (refreshToken.value) {
      try { await authApi.logout(refreshToken.value) } catch { /* ignore */ }
    }
    _clearTokens()
    uni.reLaunch({ url: '/pages/login/index' })
  }

  function _clearTokens() {
    user.value = null
    accessToken.value = null
    refreshToken.value = null
    uni.removeStorageSync('access_token')
    uni.removeStorageSync('refresh_token')
    uni.removeStorageSync('user_info')
  }

  /** @deprecated 请使用 _clearTokens */
  const clearAll = _clearTokens

  function redirectByRole() {
    if (!user.value) return
    if (isOperatorRole(user.value.role)) {
      uni.reLaunch({ url: '/pages/operator/overview/index' })
    } else if (isWorkerRole(user.value.role)) {
      uni.reLaunch({ url: '/pages/worker/pending/index' })
    }
  }

  return { user, accessToken, isLoggedIn, isOperator, isWorker, init, redirectAfterSplash, login, register, logout, _clearTokens }
})
