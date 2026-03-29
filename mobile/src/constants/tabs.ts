import type { TabItem } from '../components/TabBar.vue'

export const OPERATOR_TABS: TabItem[] = [
  { name: 'overview',   label: '总览', icon: '📊', path: '/pages/operator/overview/index' },
  { name: 'alerts',     label: '告警', icon: '🔔', path: '/pages/operator/alerts/index' },
  { name: 'workorders', label: '工单', icon: '📋', path: '/pages/operator/workorders/index' },
  { name: 'profile',    label: '我的', icon: '👤', path: '/pages/operator/profile/index' },
]

export const WORKER_TABS: TabItem[] = [
  { name: 'pending', label: '待处理', icon: '📥', path: '/pages/worker/pending/index' },
  { name: 'active',  label: '进行中', icon: '🔧', path: '/pages/worker/active/index' },
  { name: 'history', label: '历史',   icon: '📂', path: '/pages/worker/history/index' },
  { name: 'profile', label: '我的',   icon: '👤', path: '/pages/worker/profile/index' },
]
