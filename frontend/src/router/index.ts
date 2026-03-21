import { createRouter, createWebHistory } from 'vue-router'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    {
      path: '/login',
      name: 'Login',
      component: () => import('@/views/Login.vue'),
      meta: { title: '登录', requiresAuth: false, standaloneAuth: true },
    },
    {
      path: '/',
      redirect: '/home',
    },
    {
      path: '/home',
      name: 'Home',
      component: () => import('@/views/Home.vue'),
      meta: { title: '首页', requiresAuth: true },
    },
    {
      path: '/dashboard',
      name: 'Dashboard',
      component: () => import('@/views/Dashboard.vue'),
      meta: { title: '驾驶舱', requiresAuth: true },
    },
    {
      path: '/operations',
      name: 'Operations',
      component: () => import('@/views/Operations.vue'),
      meta: { title: '智慧运维', requiresAuth: true },
    },
    {
      path: '/workorders',
      name: 'WorkOrders',
      component: () => import('@/views/WorkOrders.vue'),
      meta: { title: '工单管理', requiresAuth: true },
    },
    {
      path: '/datacenter',
      name: 'DataCenter',
      component: () => import('@/views/DataCenter.vue'),
      meta: { title: '数据中心', requiresAuth: true },
    },
    {
      path: '/querystats',
      name: 'QueryStats',
      component: () => import('@/views/QueryStats.vue'),
      meta: { title: '查询统计', requiresAuth: true },
    },
  ],
})

// ── 全局路由守卫 ──────────────────────────────────────────
router.beforeEach(async (to) => {
  // 延迟导入，避免 Pinia 初始化前的循环依赖
  const { useAuthStore } = await import('@/stores/authStore')
  const authStore = useAuthStore()

  const requiresAuth = to.meta.requiresAuth !== false

  if (requiresAuth && !authStore.isLoggedIn) {
    // 有 refreshToken 时尝试静默恢复（页面刷新场景）
    const ok = await authStore.initSession()
    if (!ok) return { name: 'Login', query: { redirect: to.fullPath } }
  }

  // 已登录用户访问登录页，直接跳首页
  if (to.name === 'Login' && authStore.isLoggedIn) {
    return { name: 'Dashboard' }
  }
})

router.afterEach((to) => {
  document.title = `${to.meta.title ?? ''} — 楼宇能耗智能管理系统`
})

export default router
