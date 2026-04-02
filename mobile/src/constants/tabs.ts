import type { TabItem } from '../components/TabBar.vue'

export const OPERATOR_TABS: TabItem[] = [
  { name: 'overview',   label: '总览', icon: '/static/icons/tab-overview.svg',   iconActive: '/static/icons/tab-overview-active.svg',   path: '/pages/operator/overview/index' },
  { name: 'alerts',     label: '告警', icon: '/static/icons/tab-alert.svg',      iconActive: '/static/icons/tab-alert-active.svg',      path: '/pages/operator/alerts/index' },
  { name: 'workorders', label: '工单', icon: '/static/icons/tab-workorder.svg',  iconActive: '/static/icons/tab-workorder-active.svg',  path: '/pages/operator/workorders/index' },
  { name: 'profile',    label: '我的', icon: '/static/icons/tab-profile.svg',    iconActive: '/static/icons/tab-profile-active.svg',    path: '/pages/operator/profile/index' },
]

export const WORKER_TABS: TabItem[] = [
  { name: 'pending', label: '待处理', icon: '/static/icons/tab-inbox.svg',    iconActive: '/static/icons/tab-inbox-active.svg',    path: '/pages/worker/pending/index' },
  { name: 'active',  label: '进行中', icon: '/static/icons/tab-wrench.svg',   iconActive: '/static/icons/tab-wrench-active.svg',   path: '/pages/worker/active/index' },
  { name: 'history', label: '历史',   icon: '/static/icons/tab-history.svg',  iconActive: '/static/icons/tab-history-active.svg',  path: '/pages/worker/history/index' },
  { name: 'profile', label: '我的',   icon: '/static/icons/tab-profile.svg',  iconActive: '/static/icons/tab-profile-active.svg',  path: '/pages/worker/profile/index' },
]
