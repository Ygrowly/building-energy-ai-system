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
  incidentId?: string
  dispatchId?: string
  title: string
  building: string
  location: string
  time: string
  timeTag: string
  priorityLabel: string
  actionLabel: string
  workerAiReady?: boolean
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

type WorkerDispatchStage = 'accept' | 'arrive' | 'finish' | null

const COMPLETED_STATUSES = new Set(['completed', 'closed', 'false_alarm', 'escalated'])
const PENDING_EXECUTION_STATUSES = new Set(['pending_accept'])
const WORKER_AI_READY_STATUSES = new Set(['processing', 'waiting_support', 'supporting'])
const PRIORITY_WEIGHT: Record<string, number> = { high: 3, medium: 2, low: 1 }
const PRIORITY_LABEL_MAP: Record<string, string> = {
  high: '高优先',
  medium: '中优先',
  low: '低优先',
}

function getOrder(incident?: Incident | null): IncidentCurrentWorkOrder | null {
  return incident?.current_work_order ?? null
}

function getDispatch(incident?: Incident | null) {
  return incident?.current_dispatch ?? null
}

function getWorkerDispatchStage(incident?: Incident | null): WorkerDispatchStage {
  const dispatch = getDispatch(incident)
  const executionStatus = getWorkerExecutionStatus(incident)
  if (dispatch?.dispatch_status === 'assigned' || executionStatus === 'pending_accept') return 'accept'
  if (dispatch?.dispatch_status === 'accepted' || executionStatus === 'accepted') return 'arrive'
  if (dispatch?.dispatch_status && ['arrived', 'processing', 'waiting_support'].includes(dispatch.dispatch_status)) return 'finish'
  if (executionStatus && ['arrived', 'processing', 'waiting_support', 'overdue'].includes(executionStatus)) return 'finish'
  return null
}

export function getWorkerExecutionStatus(incident?: Incident | null): string {
  const dispatch = getDispatch(incident)
  const order = getOrder(incident)
  if (dispatch?.execution_status) return dispatch.execution_status
  if (!order) return 'pending_accept'
  if (order.execution_status) return order.execution_status
  if (dispatch?.dispatch_status) {
    if (dispatch.sla_status === 'overdue') return 'overdue'
    return dispatch.dispatch_status === 'assigned' ? 'pending_accept' : dispatch.dispatch_status
  }
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
  const dispatch = getDispatch(incident)
  const order = getOrder(incident)
  if ((!order && !dispatch) || isWorkerCompletedIncident(incident)) return false
  return dispatch?.sla_status === 'overdue'
    || order?.sla_status === 'overdue'
    || getWorkerExecutionStatus(incident) === 'overdue'
}

export function isWorkerWaitingSupportIncident(incident?: Incident | null): boolean {
  if (!incident || isWorkerCompletedIncident(incident)) return false
  return getWorkerExecutionStatus(incident) === 'waiting_support'
}

export function isWorkerReassignedIncident(incident?: Incident | null): boolean {
  const dispatch = getDispatch(incident)
  if (!dispatch || isWorkerCompletedIncident(incident)) return false
  return Boolean(dispatch.transfer_from_dispatch_id) || (dispatch.attempt_no || 0) > 1
}

export function getWorkerOrderBucket(incident: Incident): WorkerOrderBucket {
  if (isWorkerCompletedIncident(incident)) return 'completed'
  return isWorkerPendingStartIncident(incident) ? 'pending_start' : 'in_progress'
}

function isWorkerAiReadyStatus(value?: string | null): boolean {
  return WORKER_AI_READY_STATUSES.has(String(value || '').toLowerCase())
}

export function isWorkerAiReadyIncident(incident?: Incident | null): boolean {
  if (!incident || isWorkerCompletedIncident(incident)) return false
  const dispatch = getDispatch(incident)
  if (dispatch) {
    return Boolean(
      dispatch.processing_started_at
        || isWorkerAiReadyStatus(dispatch.execution_status)
        || isWorkerAiReadyStatus(dispatch.dispatch_status),
    )
  }
  const order = getOrder(incident)
  return Boolean(
    order?.processing_started_at
      || isWorkerAiReadyStatus(order?.execution_status),
  )
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
    todayCount: incidents.filter(item => isToday(getDispatch(item)?.dispatch_at || getOrder(item)?.dispatch_at || item.created_at)).length,
    overdueCount: incidents.filter(item => isWorkerOverdueIncident(item)).length,
    completedCount: incidents.filter(item => isWorkerCompletedIncident(item)).length,
  }
}

function getPriorityWeight(incident: Incident) {
  return PRIORITY_WEIGHT[incident.priority] || 0
}

function getDueWeight(incident: Incident) {
  const dispatch = getDispatch(incident)
  const order = getOrder(incident)
  const value = dispatch?.sla_minutes_left ?? order?.sla_minutes_left
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

  const dispatch = getDispatch(target)
  const order = getOrder(target)
  const workerAiReady = isWorkerAiReadyIncident(target)
  const building = formatBuildingLabel(target.building_id)
  const location = formatDeviceLabel(target.device_id, target.building_id) || formatSystemLabel(target.rule_triggered)
  const timeTag = dispatch?.sla_status === 'overdue' || order?.sla_status === 'overdue'
    ? '已超时'
    : dispatch?.sla_minutes_left !== null && dispatch?.sla_minutes_left !== undefined
      ? `剩余${dispatch.sla_minutes_left}分钟`
      : order?.sla_minutes_left !== null && order?.sla_minutes_left !== undefined
        ? `剩余${order.sla_minutes_left}分钟`
      : '优先跟进'

  return {
    ticketId: order?.ticket_id || target.incident_id,
    incidentId: target.incident_id,
    dispatchId: dispatch?.id || undefined,
    title: sanitizeDisplayText(target.summary_text) || formatRuleLabel(target.rule_triggered),
    building,
    location,
    time: formatDateTime(dispatch?.dispatch_at || order?.dispatch_at || target.created_at),
    timeTag,
    priorityLabel: PRIORITY_LABEL_MAP[target.priority] || '普通工单',
    actionLabel: workerAiReady ? '进入维小修' : isWorkerPendingStartIncident(target) ? '立即处理' : '继续处理',
    workerAiReady,
  }
}

export function getWorkerMessageCards(incidents: Incident[]): WorkerMessageCard[] {
  const pendingAcceptCount = incidents.filter(item => getWorkerExecutionStatus(item) === 'pending_accept' && !isWorkerCompletedIncident(item)).length
  const activeAlertCount = incidents.filter((item) => {
    if (isWorkerCompletedIncident(item)) return false
    const executionStatus = getWorkerExecutionStatus(item)
    return executionStatus === 'waiting_support'
      || executionStatus === 'overdue'
      || isWorkerOverdueIncident(item)
      || executionStatus === 'accepted'
      || executionStatus === 'processing'
  }).length
  const completedCount = incidents.filter(item => isWorkerCompletedIncident(item)).length

  return [
    {
      key: 'customer',
      label: '客户消息',
      count: pendingAcceptCount,
      accent: '#ff6f91',
    },
    {
      key: 'notice',
      label: '通知消息',
      count: activeAlertCount,
      accent: '#b7cc76',
    },
    {
      key: 'bulletin',
      label: '资讯通知',
      count: completedCount,
      accent: '#5fa8ff',
    },
  ]
}

export function getWorkerMessageItems(incidents: Incident[]): WorkerMessageItem[] {
  const sorted = [...incidents].sort((a, b) => {
    const aTime = new Date(getDispatch(a)?.updated_at || getOrder(a)?.updated_at || a.updated_at || 0).getTime()
    const bTime = new Date(getDispatch(b)?.updated_at || getOrder(b)?.updated_at || b.updated_at || 0).getTime()
    return bTime - aTime
  })

  const items = sorted.slice(0, 8).map(item => {
    const order = getOrder(item)
    const dispatch = getDispatch(item)
    const bucket = getWorkerOrderBucket(item)
    const executionStatus = getWorkerExecutionStatus(item)
    const dispatchStage = getWorkerDispatchStage(item)
    const slaStatus = dispatch?.sla_status || order?.sla_status || null
    const assignedTime = dispatch?.dispatch_at || order?.dispatch_at || item.updated_at
    const building = formatBuildingLabel(item.building_id)
    const summary = sanitizeDisplayText(item.summary_text) || formatRuleLabel(item.rule_triggered)
    const latestNote = sanitizeDisplayText(dispatch?.latest_note || order?.latest_progress_note || '')

    let title = `${building}工单提醒`
    let excerpt = `工单「${summary}」有新的状态变化，请及时关注。`
    let category: WorkerMessageItem['category'] = 'notice'
    let unread = 1
    let readonly = false

    if (bucket === 'completed') {
      title = `${building}服务回执`
      excerpt = `工单「${summary}」已完成处理，可查看服务记录。`
      category = 'bulletin'
      unread = 0
      readonly = true
    } else if (dispatchStage === 'accept' && slaStatus === 'warning') {
      title = `${building}接单即将超时`
      excerpt = latestNote || `工单「${summary}」已派到您名下，请尽快接单确认。`
      category = 'customer'
    } else if (dispatchStage === 'accept' && slaStatus === 'overdue') {
      title = `${building}接单已超时`
      excerpt = latestNote || `工单「${summary}」接单节点已超时，请立即接单并反馈现场计划。`
      category = 'notice'
    } else if (executionStatus === 'pending_accept') {
      title = `${building}派工成功`
      excerpt = `工单「${summary}」已派到您名下，请尽快接单。`
      category = 'customer'
    } else if (dispatchStage === 'arrive' && slaStatus === 'warning') {
      title = `${building}到场即将超时`
      excerpt = latestNote || `工单「${summary}」已接单，请尽快到场并同步现场位置。`
      category = 'notice'
    } else if (dispatchStage === 'arrive' && slaStatus === 'overdue') {
      title = `${building}到场已超时`
      excerpt = latestNote || `工单「${summary}」到场节点已超时，请尽快到场并反馈现场进展。`
      category = 'notice'
    } else if (executionStatus === 'waiting_support') {
      title = `${building}协同请求待处理`
      excerpt = `工单「${summary}」正在等待协同或配件支持，请持续跟进。`
      category = 'notice'
    } else if (isWorkerOverdueIncident(item)) {
      title = `${building}处理已超时`
      excerpt = latestNote || `工单「${summary}」处理节点已超时，请优先处理并及时反馈结果。`
      category = 'notice'
    } else if (executionStatus === 'accepted') {
      title = `${building}到场进度提醒`
      excerpt = `工单「${summary}」已接单，请尽快到场处理。`
      category = 'notice'
    } else if ((dispatchStage === 'finish' && slaStatus === 'warning') || executionStatus === 'arrived') {
      title = `${building}处理即将超时`
      excerpt = latestNote || `工单「${summary}」已到场，处理时限正在逼近，请尽快完成。`
      category = 'notice'
    } else if (executionStatus === 'processing') {
      title = `${building}处理进展提醒`
      excerpt = `工单「${summary}」正在处理中，完成后请及时提交结果。`
      category = 'notice'
    }

    return {
      id: item.id,
      category,
      title,
      excerpt,
      time: formatRelativeTime(order?.updated_at || assignedTime || item.updated_at),
      unread,
      incidentId: item.incident_id,
      ticketId: order?.ticket_id,
      readonly,
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
