import type { Incident, IncidentCurrentWorkOrder } from '../api/incident'
import { formatDateTime, formatRelativeTime } from './format'
import { formatBuildingLabel, formatDeviceLabel, formatRuleLabel, formatSystemLabel, sanitizeDisplayText } from './display'

export type WorkerOrderBucket = 'pending_start' | 'in_progress' | 'completed'

export interface WorkerDashboardStats {
  pendingStart: number
  inProgress: number
  todayCount: number
  overdueCount: number
  completedCount: number
}

export interface WorkerFeatureOrder {
  ticketId: string
  title: string
  building: string
  location: string
  time: string
  timeTag: string
  priorityLabel: string
  actionLabel: string
}

export interface WorkerMessageCard {
  key: 'customer' | 'notice' | 'bulletin'
  label: string
  count: number
  accent: string
}

export interface WorkerMessageItem {
  id: string
  category: 'customer' | 'notice' | 'bulletin'
  title: string
  excerpt: string
  time: string
  unread: number
  incidentId?: string
  ticketId?: string
  readonly?: boolean
}

const COMPLETED_STATUSES = new Set(['completed', 'closed', 'false_alarm', 'escalated'])
const PENDING_EXECUTION_STATUSES = new Set(['pending_accept'])
const PRIORITY_WEIGHT: Record<string, number> = { high: 3, medium: 2, low: 1 }
const PRIORITY_LABEL_MAP: Record<string, string> = {
  high: '高优先',
  medium: '中优先',
  low: '低优先',
}

function getOrder(incident?: Incident | null): IncidentCurrentWorkOrder | null {
  return incident?.current_work_order ?? null
}

export function getWorkerExecutionStatus(incident?: Incident | null): string {
  const order = getOrder(incident)
  if (!order) return 'pending_accept'
  if (order.execution_status) return order.execution_status
  if (order.arrived_at || order.latest_progress_at) return 'processing'
  if (order.accepted_at) return 'accepted'
  return 'pending_accept'
}

export function isWorkerCompletedIncident(incident?: Incident | null): boolean {
  if (!incident) return false
  return COMPLETED_STATUSES.has(incident.workflow_status || '') || COMPLETED_STATUSES.has(getOrder(incident)?.status || '')
}

export function isWorkerPendingStartIncident(incident?: Incident | null): boolean {
  if (!incident || isWorkerCompletedIncident(incident)) return false
  return PENDING_EXECUTION_STATUSES.has(getWorkerExecutionStatus(incident))
}

export function isWorkerInProgressIncident(incident?: Incident | null): boolean {
  if (!incident || isWorkerCompletedIncident(incident)) return false
  return !isWorkerPendingStartIncident(incident)
}

export function isWorkerOverdueIncident(incident?: Incident | null): boolean {
  const order = getOrder(incident)
  if (!order || isWorkerCompletedIncident(incident)) return false
  return order.sla_status === 'overdue' || getWorkerExecutionStatus(incident) === 'overdue'
}

export function getWorkerOrderBucket(incident: Incident): WorkerOrderBucket {
  if (isWorkerCompletedIncident(incident)) return 'completed'
  return isWorkerPendingStartIncident(incident) ? 'pending_start' : 'in_progress'
}

function isToday(value?: string | null): boolean {
  if (!value) return false
  const now = new Date()
  const today = `${now.getFullYear()}-${`${now.getMonth() + 1}`.padStart(2, '0')}-${`${now.getDate()}`.padStart(2, '0')}`
  return formatDateTime(value).slice(0, 10) === today
}

export function getWorkerDashboardStats(incidents: Incident[]): WorkerDashboardStats {
  return {
    pendingStart: incidents.filter(item => isWorkerPendingStartIncident(item)).length,
    inProgress: incidents.filter(item => isWorkerInProgressIncident(item)).length,
    todayCount: incidents.filter(item => isToday(getOrder(item)?.dispatch_at || item.created_at)).length,
    overdueCount: incidents.filter(item => isWorkerOverdueIncident(item)).length,
    completedCount: incidents.filter(item => isWorkerCompletedIncident(item)).length,
  }
}

function getPriorityWeight(incident: Incident) {
  return PRIORITY_WEIGHT[incident.priority] || 0
}

function getDueWeight(incident: Incident) {
  const order = getOrder(incident)
  const value = order?.sla_minutes_left
  if (value === null || value === undefined) return 999999
  return value
}

export function getWorkerFeatureOrder(incidents: Incident[]): WorkerFeatureOrder | null {
  const candidates = incidents
    .filter(item => !isWorkerCompletedIncident(item))
    .sort((a, b) => {
      const overdueDelta = Number(isWorkerOverdueIncident(b)) - Number(isWorkerOverdueIncident(a))
      if (overdueDelta !== 0) return overdueDelta
      const priorityDelta = getPriorityWeight(b) - getPriorityWeight(a)
      if (priorityDelta !== 0) return priorityDelta
      return getDueWeight(a) - getDueWeight(b)
    })

  const target = candidates[0]
  if (!target) return null

  const order = getOrder(target)
  const building = formatBuildingLabel(target.building_id)
  const location = formatDeviceLabel(target.device_id, target.building_id) || formatSystemLabel(target.rule_triggered)
  const timeTag = order?.sla_status === 'overdue'
    ? '已超时'
    : order?.sla_minutes_left !== null && order?.sla_minutes_left !== undefined
      ? `剩余${order.sla_minutes_left}分钟`
      : '优先跟进'

  return {
    ticketId: order?.ticket_id || target.incident_id,
    title: sanitizeDisplayText(target.summary_text) || formatRuleLabel(target.rule_triggered),
    building,
    location,
    time: formatDateTime(order?.dispatch_at || target.created_at),
    timeTag,
    priorityLabel: PRIORITY_LABEL_MAP[target.priority] || '普通工单',
    actionLabel: isWorkerPendingStartIncident(target) ? '立即处理' : '继续处理',
  }
}

export function getWorkerMessageCards(incidents: Incident[]): WorkerMessageCard[] {
  return [
    {
      key: 'customer',
      label: '客户消息',
      count: incidents.filter(item => isWorkerPendingStartIncident(item)).length,
      accent: '#ff6f91',
    },
    {
      key: 'notice',
      label: '通知消息',
      count: incidents.filter(item => isWorkerInProgressIncident(item) || isWorkerOverdueIncident(item)).length,
      accent: '#b7cc76',
    },
    {
      key: 'bulletin',
      label: '资讯通知',
      count: Math.max(1, incidents.filter(item => isWorkerCompletedIncident(item)).length),
      accent: '#5fa8ff',
    },
  ]
}

export function getWorkerMessageItems(incidents: Incident[]): WorkerMessageItem[] {
  const sorted = [...incidents].sort((a, b) => {
    const aTime = new Date(getOrder(a)?.updated_at || a.updated_at || 0).getTime()
    const bTime = new Date(getOrder(b)?.updated_at || b.updated_at || 0).getTime()
    return bTime - aTime
  })

  const items = sorted.slice(0, 8).map(item => {
    const order = getOrder(item)
    const bucket = getWorkerOrderBucket(item)
    const title = bucket === 'completed'
      ? `${formatBuildingLabel(item.building_id)}服务回执`
      : `${formatBuildingLabel(item.building_id)}工单提醒`
    const excerpt = bucket === 'completed'
      ? `工单「${sanitizeDisplayText(item.summary_text) || formatRuleLabel(item.rule_triggered)}」已完成处理，可查看服务记录。`
      : `工单「${sanitizeDisplayText(item.summary_text) || formatRuleLabel(item.rule_triggered)}」当前状态为${bucket === 'pending_start' ? '待开始' : '进行中'}，请及时跟进。`

    return {
      id: item.id,
      category: bucket === 'completed' ? 'bulletin' : bucket === 'pending_start' ? 'customer' : 'notice',
      title,
      excerpt,
      time: formatRelativeTime(order?.updated_at || item.updated_at),
      unread: bucket === 'completed' ? 0 : 1,
      incidentId: item.incident_id,
      ticketId: order?.ticket_id,
      readonly: bucket === 'completed',
    }
  })

  if (items.length) return items

  return [{
    id: 'welcome-message',
    category: 'notice',
    title: '工单通知',
    excerpt: '当前没有新的工单动态，系统会在状态变化时同步提醒你。',
    time: '刚刚',
    unread: 0,
  }]
}
