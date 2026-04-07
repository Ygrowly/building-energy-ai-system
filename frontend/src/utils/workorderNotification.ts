export type WorkorderNotificationCategory =
  | 'pending_review'
  | 'pending_dispatch'
  | 'hall_application'
  | 'takeover_recommendation'
  | 'pending_accept'
  | 'warning'
  | 'overdue'
  | 'waiting_support'
  | 'pending_close'

export type WorkorderNotificationTone = 'pending' | 'warning' | 'danger' | 'success'
export type WorkorderNotificationStage = 'accept' | 'arrive' | 'finish' | null

export interface WorkorderNotificationIncident {
  id: string
  incident_id: string
  building_id: string
  workflow_status: string | null
  summary_text?: string | null
  created_at?: string | null
  updated_at?: string | null
  dispatch_blocked_reason?: string | null
  latest_dispatch_note?: string | null
  current_work_order?: {
    ticket_id?: string | null
    status?: string | null
    worker_result?: string | null
    assigned_to_name?: string | null
    execution_status?: string | null
    sla_status?: string | null
    sla_minutes_left?: number | null
    dispatch_at?: string | null
    updated_at?: string | null
    dispatch_blocked_reason?: string | null
  } | null
  current_dispatch?: {
    id: string
    dispatch_status?: string | null
    assigned_to_name?: string | null
    support_reason?: string | null
    latest_note?: string | null
    execution_status?: string | null
    sla_status?: string | null
    sla_minutes_left?: number | null
    dispatch_at?: string | null
    updated_at?: string | null
  } | null
}

export interface WorkorderNotificationItem {
  id: string
  incidentId: string
  ticketId: string | null
  buildingId: string
  workflowStatus: string | null
  category: WorkorderNotificationCategory
  tone: WorkorderNotificationTone
  title: string
  subtitle: string
  detail: string
  tag: string
  dispatchStage: WorkorderNotificationStage
  occurredAt: string | null
  sortWeight: number
  hallEntryId?: string | null
  applicationId?: string | null
}

export interface WorkorderNotificationHallApplication {
  id: string
  applicant_user_id: string
  applicant_username: string | null
  application_type: string
  status: string
  note: string | null
  created_at: string | null
  updated_at: string | null
}

export interface WorkorderNotificationHallEntry {
  id: string
  incident_id: string | null
  entry_type: string
  status: string
  reason?: string | null
  support_reason?: string | null
  created_at?: string | null
  updated_at?: string | null
  work_order?: {
    ticket_id?: string | null
    building_id?: string | null
    issue_description?: string | null
  } | null
  applications: WorkorderNotificationHallApplication[]
}

export interface WorkorderNotificationGroups {
  review: WorkorderNotificationItem[]
  execution: WorkorderNotificationItem[]
  closing: WorkorderNotificationItem[]
}

function summarizeText(value?: string | null): string {
  return (value || '').trim() || '异常事件待处理'
}

function buildingLabel(buildingId?: string | null): string {
  const map: Record<string, string> = {
    Office: '办公楼',
    Education: '教学楼',
    'Public services': '公共楼',
    Public: '公共楼',
  }
  return map[buildingId ?? ''] ?? buildingId ?? '未知楼栋'
}

function getExecutionStatus(incident: WorkorderNotificationIncident): string | null {
  return incident.current_dispatch?.execution_status
    || incident.current_work_order?.execution_status
    || null
}

function getSlaStatus(incident: WorkorderNotificationIncident): string | null {
  return incident.current_dispatch?.sla_status
    || incident.current_work_order?.sla_status
    || null
}

function getSlaMinutesLeft(incident: WorkorderNotificationIncident): number | null {
  const currentDispatchMinutes = incident.current_dispatch?.sla_minutes_left
  if (currentDispatchMinutes !== null && currentDispatchMinutes !== undefined) return currentDispatchMinutes
  const currentOrderMinutes = incident.current_work_order?.sla_minutes_left
  return currentOrderMinutes !== undefined ? currentOrderMinutes : null
}

function getAssignedName(incident: WorkorderNotificationIncident): string {
  return incident.current_dispatch?.assigned_to_name
    || incident.current_work_order?.assigned_to_name
    || '责任人'
}

function getOccurredAt(incident: WorkorderNotificationIncident): string | null {
  return incident.current_dispatch?.updated_at
    || incident.current_dispatch?.dispatch_at
    || incident.current_work_order?.updated_at
    || incident.current_work_order?.dispatch_at
    || incident.updated_at
    || incident.created_at
    || null
}

function getDispatchStage(incident: WorkorderNotificationIncident): WorkorderNotificationStage {
  const dispatchStatus = incident.current_dispatch?.dispatch_status
  const executionStatus = getExecutionStatus(incident)
  if (dispatchStatus === 'assigned' || executionStatus === 'pending_accept') return 'accept'
  if (dispatchStatus === 'accepted' || executionStatus === 'accepted') return 'arrive'
  if (dispatchStatus && ['arrived', 'processing', 'waiting_support'].includes(dispatchStatus)) return 'finish'
  if (executionStatus && ['arrived', 'processing', 'waiting_support', 'overdue'].includes(executionStatus)) return 'finish'
  return null
}

function getStageLabelByDispatchStage(stage: WorkorderNotificationStage): string {
  if (stage === 'accept') return '接单'
  if (stage === 'arrive') return '到场'
  if (stage === 'finish') return '处理'
  return '执行'
}

function getStageSortBoost(stage: WorkorderNotificationStage): number {
  if (stage === 'accept') return 4
  if (stage === 'arrive') return 2
  if (stage === 'finish') return 1
  return 0
}

function deriveCategory(incident: WorkorderNotificationIncident): WorkorderNotificationCategory | null {
  const workflowStatus = incident.workflow_status
  if (workflowStatus === 'pending_review') return 'pending_review'
  if (workflowStatus === 'pending_dispatch') return 'pending_dispatch'
  if (workflowStatus && ['completed', 'false_alarm', 'escalated'].includes(workflowStatus)) {
    return 'pending_close'
  }
  if (workflowStatus !== 'dispatched') return null

  const executionStatus = getExecutionStatus(incident)
  const slaStatus = getSlaStatus(incident)
  if (executionStatus === 'waiting_support') return 'waiting_support'
  if (slaStatus === 'overdue') return 'overdue'
  if (slaStatus === 'warning') return 'warning'
  if (executionStatus === 'pending_accept') return 'pending_accept'
  return null
}

function getSortWeight(category: WorkorderNotificationCategory): number {
  const weightMap: Record<WorkorderNotificationCategory, number> = {
    overdue: 100,
    takeover_recommendation: 98,
    waiting_support: 95,
    warning: 90,
    pending_accept: 80,
    hall_application: 78,
    pending_dispatch: 70,
    pending_review: 65,
    pending_close: 60,
  }
  return weightMap[category]
}

export function buildWorkorderNotificationItem(
  incident: WorkorderNotificationIncident,
): WorkorderNotificationItem | null {
  const category = deriveCategory(incident)
  if (!category) return null

  const building = buildingLabel(incident.building_id)
  const summary = summarizeText(incident.summary_text)
  const assignedName = getAssignedName(incident)
  const dispatchStage = getDispatchStage(incident)
  const stageLabel = getStageLabelByDispatchStage(dispatchStage)
  const minutesLeft = getSlaMinutesLeft(incident)
  const blockedReason = incident.current_dispatch?.support_reason
    || incident.current_work_order?.dispatch_blocked_reason
    || incident.dispatch_blocked_reason
    || incident.current_dispatch?.latest_note
    || incident.latest_dispatch_note
    || ''

  let title = `${building} 工单动态`
  let detail = ''
  let tag = ''
  let tone: WorkorderNotificationTone = 'pending'

  if (category === 'pending_review') {
    title = `${building} 待AI审阅`
    detail = '异常事件已进入审批队列，请尽快确认是否生成派工。'
    tag = '待审阅'
  } else if (category === 'pending_dispatch') {
    title = `${building} 待派工`
    detail = '审批已通过，等待分配责任人。'
    tag = '待派工'
  } else if (category === 'pending_accept') {
    title = `${building} 派工成功`
    detail = `已派给 ${assignedName}，等待接单确认。`
    tag = '已派工'
  } else if (category === 'waiting_support') {
    title = `${building} 协同请求`
    detail = blockedReason || '维修人员已申请协同或配件支持，请尽快协调。'
    tag = '协同请求'
    tone = 'warning'
  } else if (category === 'warning') {
    title = `${building} ${stageLabel}即将超时`
    detail = blockedReason || (
      minutesLeft !== null && minutesLeft !== undefined
        ? `${stageLabel}节点剩余 ${minutesLeft} 分钟，请尽快催办。`
        : `${stageLabel}节点临近超时，请尽快跟进。`
    )
    tag = `${stageLabel}临期`
    tone = 'warning'
  } else if (category === 'overdue') {
    title = `${building} ${stageLabel}已超时`
    detail = blockedReason || `${stageLabel}节点已超时，请提醒责任人并评估是否改派。`
    tag = `${stageLabel}超时`
    tone = 'danger'
  } else if (category === 'pending_close') {
    title = `${building} 完成待复核`
    const workflowStatus = incident.workflow_status
    if (workflowStatus === 'false_alarm') {
      detail = '该工单已标记为误报，等待管理员确认关闭。'
      title = `${building} 误报待关闭`
      tag = '待关闭'
    } else if (workflowStatus === 'escalated') {
      detail = '该工单已升级处理，等待管理员继续跟进。'
      title = `${building} 升级待跟进`
      tag = '待跟进'
    } else {
      detail = '该工单已完成处理，等待管理员复核关闭。'
      tag = '待复核'
    }
    tone = 'success'
  }

  return {
    id: incident.id,
    incidentId: incident.incident_id,
    ticketId: incident.current_work_order?.ticket_id ?? null,
    buildingId: incident.building_id,
    workflowStatus: incident.workflow_status,
    category,
    tone,
    title,
    subtitle: summary,
    detail,
    tag,
    dispatchStage,
    occurredAt: getOccurredAt(incident),
    sortWeight: getSortWeight(category) + getStageSortBoost(dispatchStage),
  }
}

export function buildWorkorderNotificationItems(
  incidents: WorkorderNotificationIncident[],
  hallEntries: WorkorderNotificationHallEntry[] = [],
): WorkorderNotificationItem[] {
  const incidentItems = incidents
    .map(buildWorkorderNotificationItem)
    .filter((item): item is WorkorderNotificationItem => Boolean(item))

  const hallItems = hallEntries.flatMap((entry) => {
    const pendingApplications = (entry.applications || []).filter((application) => application.status === 'pending')
    return pendingApplications.map((application) => {
      const typeLabel = application.application_type === 'takeover' ? '接管申请' : '协同申请'
      const actor = (application.applicant_username || '维修人员').trim() || '维修人员'
      const noteText = (application.note || '').trim()
      return {
        id: `hall:${entry.id}:${application.id}`,
        incidentId: entry.incident_id || entry.id,
        ticketId: entry.work_order?.ticket_id ?? null,
        buildingId: entry.work_order?.building_id ?? '',
        workflowStatus: 'shared_hall',
        category: 'hall_application' as const,
        tone: 'pending' as const,
        title: `${buildingLabel(entry.work_order?.building_id)} 工单大厅申请`,
        subtitle: summarizeText(entry.support_reason || entry.reason || entry.work_order?.issue_description),
        detail: noteText
          ? `${actor} 提交了${typeLabel}，备注：${noteText}`
          : `${actor} 提交了${typeLabel}，等待管理员确认。`,
        tag: typeLabel,
        dispatchStage: null,
        occurredAt: application.created_at || application.updated_at || entry.updated_at || entry.created_at || null,
        sortWeight: getSortWeight('hall_application'),
        hallEntryId: entry.id,
        applicationId: application.id,
      }
    })
  })

  const takeoverItems = hallEntries
    .filter((entry) => (
      entry.entry_type === 'takeover_candidate'
      && entry.status === 'open'
      && !(entry.applications || []).some((application) => application.status === 'pending')
    ))
    .map((entry) => ({
      id: `hall-takeover:${entry.id}`,
      incidentId: entry.incident_id || entry.id,
      ticketId: entry.work_order?.ticket_id ?? null,
      buildingId: entry.work_order?.building_id ?? '',
      workflowStatus: 'shared_hall',
      category: 'takeover_recommendation' as const,
      tone: 'danger' as const,
      title: `${buildingLabel(entry.work_order?.building_id)} 超时待接管`,
      subtitle: summarizeText(entry.reason || entry.support_reason || entry.work_order?.issue_description),
      detail: '当前派工已超时，系统已自动提醒责任人，并已开放工单大厅待接管。建议查看改派候选人。',
      tag: '待接管',
      dispatchStage: null,
      occurredAt: entry.updated_at || entry.created_at || null,
      sortWeight: getSortWeight('takeover_recommendation'),
      hallEntryId: entry.id,
    }))

  return [...incidentItems, ...hallItems, ...takeoverItems]
    .sort((a, b) => {
      if (b.sortWeight !== a.sortWeight) return b.sortWeight - a.sortWeight
      return new Date(b.occurredAt || 0).getTime() - new Date(a.occurredAt || 0).getTime()
    })
}

export function filterWorkorderNotificationItems(
  items: WorkorderNotificationItem[],
  {
    buildingId = 'all',
    hours = 0,
  }: {
    buildingId?: string
    hours?: number
  } = {},
): WorkorderNotificationItem[] {
  return items.filter((item) => {
    if (buildingId !== 'all' && item.buildingId !== buildingId) return false
    if (hours > 0) {
      if (!item.occurredAt) return false
      const cutoff = Date.now() - hours * 3600 * 1000
      if (new Date(item.occurredAt).getTime() < cutoff) return false
    }
    return true
  })
}

export function groupWorkorderNotificationItems(
  items: WorkorderNotificationItem[],
): WorkorderNotificationGroups {
  return {
    review: items.filter((item) => ['pending_review', 'pending_dispatch', 'hall_application'].includes(item.category)),
    execution: items.filter((item) =>
      ['pending_accept', 'warning', 'overdue', 'waiting_support', 'takeover_recommendation'].includes(item.category),
    ),
    closing: items.filter((item) => item.category === 'pending_close'),
  }
}
