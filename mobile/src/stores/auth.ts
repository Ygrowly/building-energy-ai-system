import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { authApi, type UserInfo } from '../api/auth'
import { isOperatorRole, isWorkerRole, ALLOWED_ROLES, type UserRole } from '../constants/roles'

export const useAuthStore = defineStore('auth', () => {
  const user = ref<UserInfo | null>(null)
  const accessToken = ref<string | null>(null)
  const refreshToken = ref<string | null>(null)

  const isLoggedIn = computed(() => !!accessToken.value && !!user.value)
  const isOperator = computed(() => !!user.value && isOperatorRole(user.value.role))
  const isWorker   = computed(() => !!user.value && isWorkerRole(user.value.role))

  /** 启动时从本地存储恢复状态 */
  function init() {
    const token = uni.getStorageSync('access_token')
    const storedUser = uni.getStorageSync('user_info')
    const storedRefresh = uni.getStorageSync('refresh_token')

    if (token && storedUser) {
      accessToken.value = token
      refreshToken.value = storedRefresh
      try {
        user.value = typeof storedUser === 'string' ? JSON.parse(storedUser) : storedUser
        redirectByRole()
      } catch {
        clearAll()
        uni.reLaunch({ url: '/pages/login/index' })
      }
    } else {
      uni.reLaunch({ url: '/pages/login/index' })
    }
  }

  async function login(username: string, password: string) {
    const res = await authApi.login(username, password)

    // 校验角色是否允许手机端登录
    if (!ALLOWED_ROLES.includes(res.user.role as UserRole)) {
      throw new Error('当前账号角色暂不支持移动端登录')
    }

    accessToken.value = res.access_token
    refreshToken.value = res.refresh_token
    user.value = res.user

    uni.setStorageSync('access_token', res.access_token)
    uni.setStorageSync('refresh_token', res.refresh_token)
    uni.setStorageSync('user_info', JSON.stringify(res.user))

    redirectByRole()
  }

  async function logout() {
    if (refreshToken.value) {
      try { await authApi.logout(refreshToken.value) } catch { /* ignore */ }
    }
    clearAll()
    uni.reLaunch({ url: '/pages/login/index' })
  }

  function clearAll() {
    user.value = null
    accessToken.value = null
    refreshToken.value = null
    uni.removeStorageSync('access_token')
    uni.removeStorageSync('refresh_token')
    uni.removeStorageSync('user_info')
  }

  function redirectByRole() {
    if (!user.value) return
    if (isOperatorRole(user.value.role)) {
      uni.reLaunch({ url: '/pages/operator/overview/index' })
    } else if (isWorkerRole(user.value.role)) {
      uni.reLaunch({ url: '/pages/worker/pending/index' })
    }
  }

  return { user, accessToken, isLoggedIn, isOperator, isWorker, init, login, logout }
})
