import type { Incident } from '../api/incident'
import { DISPATCH_EXECUTION_STATUS_LABEL } from '../constants/status'
import {
  formatBuildingLabel,
  formatDeviceLabel,
  formatRuleLabel,
  formatSystemLabel,
  sanitizeDisplayText,
} from './display'
import { formatMetricValue, formatPct, formatServerDateTime } from './format'

const PRIORITY_SLA_MINUTES: Record<string, number> = {
  high: 30,
  medium: 60,
  low: 120,
}

function toTime(value?: string | null): number | null {
  if (!value) return null
  const ts = new Date(value).getTime()
  return Number.isNaN(ts) ? null : ts
}

function unique(values: Array<string | null | undefined>): string[] {
  const seen = new Set<string>()
  return values.filter((value): value is string => {
    if (!value) return false
    if (seen.has(value)) return false
    seen.add(value)
    return true
  })
}

function getFallbackSlaMinutes(priority?: string | null): number {
  return PRIORITY_SLA_MINUTES[priority || 'medium'] || 60
}

export function resolveExecutionStatus(incident: Incident): string {
  const order = incident.current_work_order
  if (!order) return 'pending_accept'
  if (order.execution_status) return order.execution_status

  if (order.status === 'dispatched') {
    if (order.worker_result === 'needs_parts') return 'waiting_support'
    const dueAt = resolveSlaDueAt(incident)
    const dueTs = toTime(dueAt)
    if (dueTs && dueTs < Date.now()) return 'overdue'
    if (order.assigned_to) return 'processing'
    return 'pending_accept'
  }

  return order.status || 'pending_accept'
}

export function resolveExecutionLabel(incident: Incident): string {
  const status = resolveExecutionStatus(incident)
  return DISPATCH_EXECUTION_STATUS_LABEL[status] || sanitizeDisplayText(status)
}

export function resolveSlaDueAt(incident: Incident): string | null {
  const order = incident.current_work_order
  if (!order) return null
  if (order.sla_due_at) return order.sla_due_at

  const dispatchAt = order.dispatch_at || order.updated_at || order.created_at
  const dispatchTs = toTime(dispatchAt)
  if (!dispatchTs) return null
  const dueTs = dispatchTs + getFallbackSlaMinutes(order.priority) * 60 * 1000
  return new Date(dueTs).toISOString()
}

export function resolveSlaMeta(incident: Incident): {
  tone: 'normal' | 'warning' | 'overdue'
  text: string
  minutesLeft: number | null
} {
  const order = incident.current_work_order
  const dueAt = resolveSlaDueAt(incident)
  const dueTs = toTime(dueAt)
  if (!order || !dueTs) {
    return { tone: 'normal', text: 'SLA 待确认', minutesLeft: null }
  }

  const rawMinutes = order.sla_minutes_left
  const minutesLeft = rawMinutes ?? Math.floor((dueTs - Date.now()) / 60000)
  if (minutesLeft < 0) {
    return { tone: 'overdue', text: `已超时 ${Math.abs(minutesLeft)} 分钟`, minutesLeft }
  }
  if (minutesLeft <= 30) {
    return { tone: 'warning', text: `${minutesLeft} 分钟后超时`, minutesLeft }
  }
  return { tone: 'normal', text: `SLA 剩余 ${minutesLeft} 分钟`, minutesLeft }
}

export function buildLocationPath(incident: Incident): string {
  const building = formatBuildingLabel(incident.building_id)
  const system = formatSystemLabel(incident.rule_triggered)
  const deviceLabel = formatDeviceLabel(incident.device_id, incident.building_id)
  const compactDevice = deviceLabel.replace(building, '').trim()
  return unique([building, system, compactDevice || null]).join(' / ')
}

export function buildAnomalySummary(incident: Incident): string {
  const parts: string[] = []
  if (incident.latest_actual_value !== null) {
    parts.push(`当前 ${formatMetricValue(incident.latest_actual_value)}`)
  }
  if (incident.latest_expected_value !== null) {
    parts.push(`基线 ${formatMetricValue(incident.latest_expected_value)}`)
  }
  const deviation = incident.peak_deviation_pct
  if (deviation !== null && deviation !== undefined) {
    parts.push(`偏差 ${formatPct(deviation)}`)
  }
  const duration = buildDurationText(incident)
  if (duration) {
    parts.push(`持续 ${duration}`)
  }
  if (incident.anomaly_count) {
    parts.push(`连续 ${incident.anomaly_count} 次`)
  }
  return parts.join('  ')
}

export function buildDurationText(incident: Incident): string {
  const startTs = toTime(incident.first_seen_at)
  const endTs = incident.is_active ? Date.now() : (toTime(incident.last_seen_at) || Date.now())
  if (!startTs || !endTs || endTs < startTs) return ''
  const totalMinutes = Math.max(1, Math.floor((endTs - startTs) / 60000))
  if (totalMinutes < 60) return `${totalMinutes} 分钟`
  const hours = Math.floor(totalMinutes / 60)
  const minutes = totalMinutes % 60
  return minutes ? `${hours} 小时 ${minutes} 分钟` : `${hours} 小时`
}

export function buildStateText(incident: Incident): string {
  if (incident.workflow_status !== 'dispatched') return ''
  if (incident.is_active) return '当前仍异常'
  return '异常已恢复，待确认'
}

export function buildProgressText(incident: Incident): string {
  const order = incident.current_work_order
  if (!order) return '等待工单同步'
  if (order.latest_progress_note) return sanitizeDisplayText(order.latest_progress_note)
  if (order.worker_notes) return sanitizeDisplayText(order.worker_notes)
  if (resolveExecutionStatus(incident) === 'pending_accept') return '已派单，等待接单处理'
  return '处理中'
}

export function buildSuggestedActionText(incident: Incident): string {
  return sanitizeDisplayText(
    incident.current_work_order?.suggested_action
      || incident.current_work_order?.ai_reason
      || '建议进入详情查看趋势与处理建议'
  )
}

export function buildImpactText(incident: Incident): string {
  const deviation = Math.abs(incident.peak_deviation_pct || 0)
  const severity = deviation >= 100 ? '偏差显著，建议优先处理' : '建议持续关注处理进度'
  const activeText = incident.is_active ? '异常仍在持续' : '异常已出现回落'
  return `${activeText}，${severity}`
}

export function buildCardTimeRow(incident: Incident): string {
  const dispatchAt = incident.current_work_order?.dispatch_at || incident.current_work_order?.created_at
  const progressAt = incident.current_work_order?.latest_progress_at || incident.current_work_order?.updated_at
  const left = dispatchAt ? `派单 ${formatServerDateTime(dispatchAt).slice(5, 16)}` : ''
  const right = progressAt ? `更新 ${formatServerDateTime(progressAt).slice(5, 16)}` : ''
  return unique([left, right]).join('   ')
}

export function getDispatchSortScore(incident: Incident): number {
  const status = resolveExecutionStatus(incident)
  const priorityScore = { high: 300, medium: 200, low: 100 }[incident.priority] || 0
  const statusScore = {
    overdue: 1000,
    waiting_support: 850,
    pending_accept: 750,
    processing: 650,
    accepted: 550,
    arrived: 500,
  }[status] || 0
  const activeScore = incident.is_active ? 80 : 0
  const deviationScore = Math.min(70, Math.round(Math.abs(incident.peak_deviation_pct || 0) / 10))
  return statusScore + priorityScore + activeScore + deviationScore
}

export function getDispatchSummaryStats(incidents: Incident[]) {
  return incidents.reduce((acc, incident) => {
    const execution = resolveExecutionStatus(incident)
    const sla = resolveSlaMeta(incident)
    acc.total += 1
    if (execution === 'overdue') acc.overdue += 1
    if (sla.tone === 'warning') acc.warning += 1
    if (incident.is_active) acc.active += 1
    if (execution === 'pending_accept') acc.pendingAccept += 1
    return acc
  }, {
    total: 0,
    overdue: 0,
    warning: 0,
    active: 0,
    pendingAccept: 0,
  })
}

export function buildRuleLabel(incident: Incident): string {
  return formatRuleLabel(incident.rule_triggered)
}
