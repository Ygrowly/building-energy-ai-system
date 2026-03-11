import { createRouter, createWebHistory } from 'vue-router'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    {
      path: '/',
      redirect: '/dashboard',
    },
    {
      path: '/dashboard',
      name: 'Dashboard',
      component: () => import('@/views/Dashboard.vue'),
      meta: { title: '驾驶舱' },
    },
    {
      path: '/operations',
      name: 'Operations',
      component: () => import('@/views/Operations.vue'),
      meta: { title: '智慧运维' },
    },
    {
      path: '/workorders',
      name: 'WorkOrders',
      component: () => import('@/views/WorkOrders.vue'),
      meta: { title: '工单管理' },
    },
  ],
})

router.afterEach((to) => {
  document.title = `${to.meta.title ?? ''} — 楼宇能耗智能管理系统`
})

export default router
