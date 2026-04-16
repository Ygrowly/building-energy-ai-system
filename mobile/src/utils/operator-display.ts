import type { NotificationItem } from '../api/notification'
import type {
  BatchDispatchRecommendation,
  DispatchRequirement,
  WorkOrder,
} from '../api/workorder'
import {
  DISPATCH_EXECUTION_STATUS_LABEL,
  PRIORITY_LABEL,
  STATUS_LABEL,
  WORKER_RESULT_LABEL,
} from '../constants/status'
import {
  formatBuildingLabel,
  formatDeviceLabel,
  formatWorkOrderTitle,
  sanitizeDisplayText,
} from './display'

export type OperatorNotificationTone = 'info' | 'warning' | 'danger' | 'success'
export type OperatorChipTone = 'neutral' | 'accent' | 'warning' | 'danger' | 'success'

export interface OperatorNotificationChipView {
  text: string
  tone: OperatorChipTone
}

export interface OperatorNotificationCardView {
  tone: OperatorNotificationTone
  iconText: string
  eventLabel: string
  title: string
  subtitle: string
  detail: string
  chips: OperatorNotificationChipView[]
}

interface OperatorNotificationCardContext {
  workOrder?: WorkOrder | null
}

export interface OperatorDispatchRequirementView {
  summary: string
  buildingText: string
  priorityText: string
  preferredTeamText: string
  skillTexts: string[]
}

export interface OperatorBatchRecommendationView {
  title: string
  ticketTag: string
  buildingText: string
  priorityText: string
  requirementText: string
  chosenCandidateText: string
  selectionReason: string
  scoreGapText: string
}

const OPERATOR_SKILL_LABELS: Record<string, string> = {
  hvac: '暖通空调',
  electrical: '电气配电',
  plumbing: '给排水',
  controls: '楼宇自控',
  inspection: '现场巡检',
}

const OPERATOR_SHIFT_LABELS: Record<string, string> = {
  on_duty: '值班中',
  standby: '待命',
  off_duty: '离岗',
}

const OPERATOR_NOTIFICATION_EVENT_LABELS: Record<string, string> = {
  assigned: '已派单',
  auto_assigned: '自动派工',
  accepted: '已接单',
  arrived: '已到场',
  started: '开始处理',
  support_requested: '发起协同',
  support_resolved: '协同已完成',
  dispatch_support_resolved: '协同已解决',
  rejected: '已拒单',
  cancelled: '已取消',
  transferred: '已改派',
  reminded: '已催办',
  timeout_warning: '临近超时',
  timeout_overdue: '已超时',
  support_assigned: '协同已指派',
  support_worker_accepted: '协同已接单',
  support_worker_rejected: '协同已拒绝',
  worker_feedback: '维修反馈',
  close: '已关闭',
  admin_override: '人工处理',
  dispatch_hall_takeover_open: '接管大厅已开启',
  dispatch_hall_support_open: '协同大厅已开启',
  dispatch_hall_closed: '工单大厅已关闭',
}

const OPERATOR_HALL_ENTRY_LABELS: Record<string, string> = {
  support_request: '共享协同',
  takeover_candidate: '待接管',
}

const OPERATOR_HALL_APPLICATION_LABELS: Record<string, string> = {
  support: '申请协同',
  takeover: '申请接管',
}

const OPERATOR_STATUS_LABELS: Record<string, string> = {
  ...STATUS_LABEL,
  ...DISPATCH_EXECUTION_STATUS_LABEL,
  assigned: '已派单',
  open: '开放中',
  approved: '已同意',
  rejected: '已驳回',
  withdrawn: '已撤回',
  expired: '已过期',
}

const OPERATOR_METRIC_LABELS: Record<string, string> = {
  electricity_kwh: '用电量',
  water_l: '水耗',
  hac_energy: '空调能耗',
  sim_supply_temp_c: '供水温度',
  sim_return_temp_c: '回水温度',
}

const OPERATOR_TEXT_TOKEN_LABELS: Record<string, string> = {
  ...OPERATOR_SKILL_LABELS,
  ...OPERATOR_SHIFT_LABELS,
  ...OPERATOR_HALL_ENTRY_LABELS,
  ...OPERATOR_HALL_APPLICATION_LABELS,
  ...OPERATOR_NOTIFICATION_EVENT_LABELS,
  ...OPERATOR_STATUS_LABELS,
  electricity_kwh: '用电量',
  water_l: '水耗',
  hac_energy: '空调能耗',
  sim_supply_temp_c: '供水温度',
  sim_return_temp_c: '回水温度',
  hall_takeover: '大厅接管',
  hall_support: '大厅协同',
}

const TOKEN_REGEX_CACHE = new Map<string, RegExp>()

function escapeRegExp(value: string) {
  return value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
}

function exactTokenRegex(token: string) {
  const cached = TOKEN_REGEX_CACHE.get(token)
  if (cached) return cached
  const pattern = new RegExp(`(^|[^A-Za-z0-9_-])(${escapeRegExp(token)})(?=$|[^A-Za-z0-9_-])`, 'g')
  TOKEN_REGEX_CACHE.set(token, pattern)
  return pattern
}

function pickText(...values: unknown[]): string {
  for (const value of values) {
    if (typeof value === 'string' && value.trim()) return value.trim()
    if (typeof value === 'number' && Number.isFinite(value)) return String(value)
  }
  return ''
}

function normalizeNotificationTone(tone?: string | null): OperatorNotificationTone {
  if (tone === 'danger' || tone === 'warning' || tone === 'success') return tone
  return 'info'
}

function notificationToneOf(eventType: string, severity?: string | null): OperatorNotificationTone {
  if (['timeout_overdue', 'rejected', 'support_worker_rejected'].includes(eventType)) return 'danger'
  if (['timeout_warning', 'support_requested', 'dispatch_hall_takeover_open', 'dispatch_hall_support_open'].includes(eventType)) return 'warning'
  if (['accepted', 'arrived', 'started', 'support_resolved', 'dispatch_support_resolved', 'worker_feedback', 'close'].includes(eventType)) return 'success'
  return normalizeNotificationTone(severity)
}

function notificationIconOf(eventType: string, tone: OperatorNotificationTone) {
  const map: Record<string, string> = {
    assigned: '派',
    auto_assigned: '派',
    accepted: '接',
    arrived: '场',
    started: '修',
    support_requested: '协',
    support_resolved: '协',
    dispatch_support_resolved: '协',
    rejected: '拒',
    cancelled: '消',
    transferred: '改',
    reminded: '催',
    timeout_warning: '警',
    timeout_overdue: '超',
    support_assigned: '协',
    support_worker_accepted: '协',
    support_worker_rejected: '拒',
    worker_feedback: '反',
    close: '结',
    admin_override: '审',
    dispatch_hall_takeover_open: '厅',
    dispatch_hall_support_open: '厅',
    dispatch_hall_closed: '关',
  }
  if (map[eventType]) return map[eventType]
  if (tone === 'danger') return '急'
  if (tone === 'warning') return '警'
  if (tone === 'success') return '成'
  return '工'
}

function workerResultLabel(result?: string | null) {
  if (!result) return ''
  return WORKER_RESULT_LABEL[result] || sanitizeOperatorDisplayText(result)
}

function normalizeAssigneeText(value?: string | null) {
  const text = sanitizeOperatorDisplayText(value)
  if (!text) return ''
  if (text.endsWith('责任人')) return text
  return `${text}责任人`
}

function extractAssigneeFromFallbackText(...values: Array<string | null | undefined>) {
  for (const value of values) {
    const text = sanitizeOperatorDisplayText(value)
    if (!text) continue
    const match = text.match(/^(.+?)\s*已(?:确认接单|到达现场|开始处理工单|开始处理|确认协同|拒绝协同请求|提交最新维修反馈)/)
    if (match?.[1]) return match[1].trim()
    const assignedMatch = text.match(/已(?:指派给|改派给)\s*(.+)$/)
    if (assignedMatch?.[1]) return assignedMatch[1].trim().replace(/[。；，].*$/, '')
  }
  return ''
}

export function sanitizeOperatorDisplayText(value?: string | null): string {
  if (!value) return ''

  let text = sanitizeDisplayText(value)
  Object.entries(OPERATOR_TEXT_TOKEN_LABELS).forEach(([token, label]) => {
    text = text.replace(exactTokenRegex(token), (_, prefix: string) => `${prefix}${label}`)
  })
  return text.replace(/\s{2,}/g, ' ').trim()
}

export function formatOperatorSkillLabel(code?: string | null): string {
  if (!code) return ''
  return OPERATOR_SKILL_LABELS[code] || sanitizeOperatorDisplayText(code)
}

export function formatOperatorSkillList(codes?: Array<string | null | undefined>): string[] {
  const labels = (codes || [])
    .map((code) => formatOperatorSkillLabel(code))
    .filter(Boolean)
  return Array.from(new Set(labels))
}

export function formatOperatorBuildingList(values?: Array<string | null | undefined>): string[] {
  return Array.from(new Set((values || [])
    .filter((value): value is string => typeof value === 'string' && Boolean(value.trim()))
    .map((value) => formatBuildingLabel(value))))
}

export function formatOperatorShiftLabel(status?: string | null): string {
  if (!status) return '值班中'
  return OPERATOR_SHIFT_LABELS[status] || sanitizeOperatorDisplayText(status) || '值班中'
}

export function formatOperatorWorkOrderStatusLabel(status?: string | null): string {
  if (!status) return '处理中'
  return OPERATOR_STATUS_LABELS[status] || sanitizeOperatorDisplayText(status) || '处理中'
}

export function formatOperatorNotificationEventLabel(eventType?: string | null): string {
  if (!eventType) return '工单动态'
  return OPERATOR_NOTIFICATION_EVENT_LABELS[eventType] || sanitizeOperatorDisplayText(eventType) || '工单动态'
}

export function formatOperatorHallEntryType(entryType?: string | null): string {
  if (!entryType) return '工单大厅'
  return OPERATOR_HALL_ENTRY_LABELS[entryType] || sanitizeOperatorDisplayText(entryType) || '工单大厅'
}

export function formatOperatorHallApplicationType(type?: string | null): string {
  if (!type) return '申请协同'
  return OPERATOR_HALL_APPLICATION_LABELS[type] || sanitizeOperatorDisplayText(type) || '申请协同'
}

export function formatOperatorTicketTag(ticketId?: string | null): string {
  return `工单编号 ${ticketId || '--'}`
}

export function formatOperatorDispatchTag(dispatchId?: string | null): string {
  return `派工单号 ${dispatchId || '--'}`
}

export function formatOperatorMetricLabel(metricName?: string | null): string {
  if (!metricName) return '指标'
  return OPERATOR_METRIC_LABELS[metricName] || sanitizeOperatorDisplayText(metricName) || '指标'
}

export function formatOperatorPredictionMode(horizon?: number | string | null): string {
  if (typeof horizon === 'number' && Number.isFinite(horizon)) return `${horizon}小时窗口`
  if (typeof horizon === 'string' && horizon.trim()) return `${sanitizeOperatorDisplayText(horizon)}窗口`
  return '预测窗口'
}

export function buildOperatorDispatchRequirementView(requirement?: DispatchRequirement | null): OperatorDispatchRequirementView {
  const buildingText = formatBuildingLabel(requirement?.building_id)
  const priorityText = PRIORITY_LABEL[requirement?.priority || ''] || '中优先'
  const skillTexts = formatOperatorSkillList(requirement?.required_skills).length
    ? formatOperatorSkillList(requirement?.required_skills)
    : ['基础巡检']
  const preferredTeamText = sanitizeOperatorDisplayText(requirement?.preferred_team_name) || '系统智能推荐'
  const summary = [
    `楼宇 ${buildingText}`,
    `优先级 ${priorityText}`,
    `需求技能 ${skillTexts.join(' / ')}`,
    `建议班组 ${preferredTeamText}`,
  ].join(' · ')

  return {
    summary,
    buildingText,
    priorityText,
    preferredTeamText,
    skillTexts,
  }
}

export function buildOperatorBatchRecommendationView(item: BatchDispatchRecommendation): OperatorBatchRecommendationView {
  const requirementView = buildOperatorDispatchRequirementView(item.requirement)
  const chosenCandidateText = item.chosen_candidate
    ? [item.chosen_candidate.username, sanitizeOperatorDisplayText(item.chosen_candidate.team_name)]
      .filter(Boolean)
      .join(' · ')
    : '暂无推荐人选'

  return {
    title: '待派工单智能推荐',
    ticketTag: formatOperatorTicketTag(item.ticket_id),
    buildingText: formatBuildingLabel(item.building_id),
    priorityText: PRIORITY_LABEL[item.priority || ''] || '中优先',
    requirementText: requirementView.skillTexts.join(' / '),
    chosenCandidateText,
    selectionReason: sanitizeOperatorDisplayText(item.selection_reason) || '系统按技能、负载与响应范围综合推荐',
    scoreGapText: item.score_gap == null ? '--' : String(item.score_gap),
  }
}

export function buildOperatorNotificationCard(
  item: NotificationItem,
  context: OperatorNotificationCardContext = {},
): OperatorNotificationCardView {
  const payload = item.payload || {}
  const ctaParams = item.cta_params || {}
  const workOrder = context.workOrder || null
  const ticketId = pickText(
    item.related_ticket_id,
    ctaParams.ticket_id,
    payload.ticket_id,
    payload.work_order?.ticket_id,
    workOrder?.ticket_id,
  )
  const dispatchId = pickText(
    item.related_dispatch_id,
    ctaParams.dispatch_id,
    payload.dispatch_id,
    payload.source_dispatch_id,
    workOrder?.dispatch_id,
  )
  const buildingId = pickText(
    payload.building_id,
    payload.work_order?.building_id,
    workOrder?.building_id,
  )
  const deviceId = pickText(
    payload.device_id,
    payload.work_order?.device_id,
    workOrder?.device_id,
  )
  const rawAssignee = pickText(
    workOrder?.assigned_to_name,
    payload.assigned_to_name,
    payload.assignee_name,
    payload.worker_name,
    payload.username,
    payload.applicant_username,
    extractAssigneeFromFallbackText(item.body, item.title),
  )
  const assignee = normalizeAssigneeText(rawAssignee)
  const fallbackTitle = sanitizeOperatorDisplayText(item.title)
  const fallbackBody = sanitizeOperatorDisplayText(item.body)
  const reasonText = sanitizeOperatorDisplayText(pickText(
    payload.support_reason,
    payload.reason,
    payload.note,
    payload.message,
    payload.issue_description,
  ))
  const workerResult = workerResultLabel(pickText(payload.result, payload.worker_result))
  const tone = notificationToneOf(item.event_type, item.severity)
  const eventLabel = formatOperatorNotificationEventLabel(item.event_type)
  const workOrderTitle = formatWorkOrderTitle({
    ruleTriggered: workOrder?.anomaly_links?.[0]?.rule_triggered || payload.rule_triggered || payload.work_order?.rule_triggered,
    summaryText: payload.issue_description || payload.message,
    issueDescription: workOrder?.issue_description,
    buildingId,
  })
  const locationText = [buildingId ? formatBuildingLabel(buildingId) : '', formatDeviceLabel(deviceId, buildingId)]
    .filter(Boolean)
    .join(' / ')

  let title = fallbackTitle || (ticketId ? `工单 ${ticketId} ${eventLabel}` : eventLabel)
  let subtitle = fallbackBody || reasonText || '请查看工单最新处理进展'

  switch (item.event_type) {
    case 'assigned':
    case 'auto_assigned':
      title = workOrderTitle ? `${workOrderTitle} 已派单` : (ticketId ? `工单 ${ticketId} 已派单` : '工单已派单')
      subtitle = assignee ? `已指派给 ${assignee}` : (fallbackBody || '系统已完成派工，请尽快接单处理')
      break
    case 'accepted':
      title = workOrderTitle ? `${workOrderTitle} 已接单` : (ticketId ? `工单 ${ticketId} 已接单` : '工单已接单')
      subtitle = assignee ? `${assignee}已确认接单` : (fallbackBody || '责任人已确认接单')
      break
    case 'arrived':
      title = workOrderTitle ? `${workOrderTitle} 已到场` : (ticketId ? `工单 ${ticketId} 已到场` : '工单已到场')
      subtitle = assignee ? `${assignee}已到达现场` : (fallbackBody || '责任人已到达现场')
      break
    case 'started':
      title = workOrderTitle ? `${workOrderTitle} 开始处理` : (ticketId ? `工单 ${ticketId} 开始处理` : '工单开始处理')
      subtitle = assignee ? `${assignee}已开始处理工单` : (fallbackBody || '责任人已开始处理工单')
      break
    case 'support_requested':
      title = workOrderTitle ? `${workOrderTitle} 发起协同` : (ticketId ? `工单 ${ticketId} 发起协同` : '工单发起协同')
      subtitle = reasonText || '当前工单需要协同支援'
      break
    case 'support_resolved':
    case 'dispatch_support_resolved':
      title = workOrderTitle ? `${workOrderTitle} 协同已完成` : (ticketId ? `工单 ${ticketId} 协同已完成` : '协同事项已完成')
      subtitle = '协同事项已解决，工单恢复正常处理'
      break
    case 'rejected':
      title = workOrderTitle ? `${workOrderTitle} 已拒单` : (ticketId ? `工单 ${ticketId} 已拒单` : '工单已拒单')
      subtitle = reasonText || '维修人员已拒绝本次派工，建议尽快改派'
      break
    case 'cancelled':
      title = workOrderTitle ? `${workOrderTitle} 已取消派工` : (ticketId ? `工单 ${ticketId} 已取消派工` : '派工已取消')
      subtitle = reasonText || '当前派工任务已取消'
      break
    case 'transferred':
      title = workOrderTitle ? `${workOrderTitle} 已改派` : (ticketId ? `工单 ${ticketId} 已改派` : '工单已改派')
      subtitle = assignee ? `已改派给 ${assignee}` : (fallbackBody || '当前工单已重新指定处理人')
      break
    case 'reminded':
      title = workOrderTitle ? `${workOrderTitle} 已催办` : (ticketId ? `工单 ${ticketId} 已催办` : '责任人已催办')
      subtitle = assignee ? `已提醒 ${assignee}尽快同步处理进展` : (fallbackBody || '已提醒责任人尽快同步处理进展')
      break
    case 'timeout_warning':
      title = workOrderTitle ? `${workOrderTitle} 临近超时` : (ticketId ? `工单 ${ticketId} 临近超时` : '工单临近超时')
      subtitle = '当前节点即将超时，请尽快跟进处理'
      break
    case 'timeout_overdue':
      title = workOrderTitle ? `${workOrderTitle} 已超时` : (ticketId ? `工单 ${ticketId} 已超时` : '工单已超时')
      subtitle = '当前节点已超时，建议立即催办或改派'
      break
    case 'support_assigned':
      title = workOrderTitle ? `${workOrderTitle} 已指派协同` : (ticketId ? `工单 ${ticketId} 已指派协同` : '协同任务已指派')
      subtitle = assignee ? `已安排 ${assignee}协同处理` : (fallbackBody || '协同人员已加入处理')
      break
    case 'support_worker_accepted':
      title = workOrderTitle ? `${workOrderTitle} 协同已接单` : (ticketId ? `工单 ${ticketId} 协同已接单` : '协同任务已接单')
      subtitle = assignee ? `${assignee}已确认协同` : (fallbackBody || '协同人员已确认接单')
      break
    case 'support_worker_rejected':
      title = workOrderTitle ? `${workOrderTitle} 协同已拒绝` : (ticketId ? `工单 ${ticketId} 协同已拒绝` : '协同任务已拒绝')
      subtitle = assignee ? `${assignee}已拒绝协同请求` : (fallbackBody || '协同人员已拒绝协同请求')
      break
    case 'worker_feedback':
      title = workOrderTitle ? `${workOrderTitle} 已提交维修反馈` : (ticketId ? `工单 ${ticketId} 已提交维修反馈` : '维修反馈已提交')
      subtitle = workerResult ? `维修结果：${workerResult}` : '责任人已提交最新维修反馈'
      break
    case 'close':
      title = workOrderTitle ? `${workOrderTitle} 已关闭` : (ticketId ? `工单 ${ticketId} 已关闭` : '工单已关闭')
      subtitle = reasonText || '当前工单已完成关闭'
      break
    case 'admin_override':
      title = workOrderTitle ? `${workOrderTitle} 已人工处理` : (ticketId ? `工单 ${ticketId} 已人工处理` : '工单已人工处理')
      subtitle = reasonText || '管理员已覆盖原处理结果'
      break
    case 'dispatch_hall_takeover_open':
      title = workOrderTitle ? `${workOrderTitle} 进入接管大厅` : (ticketId ? `工单 ${ticketId} 进入接管大厅` : '工单进入接管大厅')
      subtitle = reasonText || '当前工单已开放接管申请'
      break
    case 'dispatch_hall_support_open':
      title = workOrderTitle ? `${workOrderTitle} 进入协同大厅` : (ticketId ? `工单 ${ticketId} 进入协同大厅` : '工单进入协同大厅')
      subtitle = reasonText || '当前工单已开放协同申请'
      break
    case 'dispatch_hall_closed':
      title = workOrderTitle ? `${workOrderTitle} 已退出工单大厅` : (ticketId ? `工单 ${ticketId} 已退出工单大厅` : '工单大厅事项已关闭')
      subtitle = reasonText || '当前共享事项已关闭'
      break
    default:
      title = workOrderTitle ? `${workOrderTitle} ${eventLabel}` : (ticketId ? `工单 ${ticketId} ${eventLabel}` : (fallbackTitle || eventLabel))
      subtitle = fallbackBody || reasonText || '请查看工单最新处理进展'
      break
  }

  const detailParts = [locationText]
  if (reasonText && reasonText !== subtitle && reasonText !== title) detailParts.push(reasonText)

  const chips: OperatorNotificationChipView[] = []
  if (ticketId) chips.push({ text: formatOperatorTicketTag(ticketId), tone: 'accent' })
  if (dispatchId) chips.push({ text: formatOperatorDispatchTag(dispatchId), tone: 'neutral' })
  if (buildingId) chips.push({ text: `楼宇 ${formatBuildingLabel(buildingId)}`, tone: 'neutral' })

  return {
    tone,
    iconText: notificationIconOf(item.event_type, tone),
    eventLabel,
    title,
    subtitle,
    detail: detailParts.filter(Boolean).join(' · '),
    chips,
  }
}
