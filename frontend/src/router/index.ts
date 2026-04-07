import { createRouter, createWebHistory } from 'vue-router'
import { useAuthStore } from '@/stores/authStore'

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
      path: '/workorders/review',
      name: 'WorkOrderReview',
      component: () => import('@/views/WorkOrders.vue'),
      meta: { title: '工单审阅', requiresAuth: true, workOrderMode: 'review' },
    },
    {
      path: '/workorders/dispatch',
      name: 'WorkOrderDispatchCenter',
      component: () => import('@/views/WorkOrders.vue'),
      meta: { title: '派工中心', requiresAuth: true, workOrderMode: 'dispatch' },
    },
    {
      path: '/workorders/tracking',
      name: 'WorkOrderTracking',
      component: () => import('@/views/WorkOrders.vue'),
      meta: { title: '执行跟踪', requiresAuth: true, workOrderMode: 'tracking' },
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

const KEEP_ALIVE_ROUTE_NAMES = new Set([
  'Home',
  'Operations',
  'WorkOrders',
  'DataCenter',
  'QueryStats',
])

router.getRoutes().forEach((route) => {
  if (route.name && KEEP_ALIVE_ROUTE_NAMES.has(String(route.name))) {
    route.meta.keepAlive = true
  }
})

router.beforeEach(async (to) => {
  const authStore = useAuthStore()
  const requiresAuth = to.meta.requiresAuth !== false

  if (requiresAuth && !authStore.isLoggedIn) {
    const ok = await authStore.initSession()
    if (!ok) return { name: 'Login', query: { redirect: to.fullPath } }
  }

  if (to.name === 'Login' && authStore.isLoggedIn) {
    return { name: 'Home' }
  }
})

router.afterEach((to) => {
  document.title = `${to.meta.title ?? ''} - 楼宇能耗智能管理系统`
})

export default router
