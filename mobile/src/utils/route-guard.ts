import { useAuthStore } from '../stores/auth'
import { ALLOWED_ROLES, type UserRole } from '../constants/roles'

/**
 * 页面级路由守卫。在页面 onLoad / setup 中调用。
 * 返回 false 表示无权访问（已自动跳转）。
 */
export function useRouteGuard(requiredRoles: UserRole[]): boolean {
  const authStore = useAuthStore()

  if (!authStore.isLoggedIn) {
    uni.reLaunch({ url: '/pages/login/index' })
    return false
  }

  const role = authStore.user?.role
  if (!role || !requiredRoles.includes(role as UserRole)) {
    uni.showToast({ title: '无权访问该页面', icon: 'none' })
    setTimeout(() => uni.reLaunch({ url: '/pages/login/index' }), 1500)
    return false
  }

  return true
}
