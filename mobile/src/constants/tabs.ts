import type { TabItem } from '../components/TabBar.vue'

export const OPERATOR_TABS: TabItem[] = [
  { name: 'overview',   label: '总览', icon: '/static/icons/tab-overview.svg',   iconActive: '/static/icons/tab-overview-active.svg',   path: '/pages/operator/overview/index' },
  { name: 'alerts',     label: '消息', icon: '/static/icons/tab-alert.svg',      iconActive: '/static/icons/tab-alert-active.svg',      path: '/pages/operator/alerts/index' },
  { name: 'workorders', label: '工单', icon: '/static/icons/tab-workorder.svg',  iconActive: '/static/icons/tab-workorder-active.svg',  path: '/pages/operator/workorders/index' },
  { name: 'profile',    label: '我的', icon: '/static/icons/tab-profile.svg',    iconActive: '/static/icons/tab-profile-active.svg',    path: '/pages/operator/profile/index' },
]

export const WORKER_TABS: TabItem[] = [
  { name: 'workspace', label: '工作台', icon: '/static/icons/tab-worker-home.svg', iconActive: '/static/icons/tab-worker-home-active.svg', path: '/pages/worker/pending/index' },
  { name: 'workorders', label: '工单', icon: '/static/icons/tab-worker-order.svg', iconActive: '/static/icons/tab-worker-order-active.svg', path: '/pages/worker/active/index' },
  { name: 'messages', label: '消息', icon: '/static/icons/tab-worker-message.svg', iconActive: '/static/icons/tab-worker-message-active.svg', path: '/pages/worker/history/index' },
  { name: 'profile', label: '我的', icon: '/static/icons/tab-worker-profile.svg', iconActive: '/static/icons/tab-worker-profile-active.svg', path: '/pages/worker/profile/index' },
]
