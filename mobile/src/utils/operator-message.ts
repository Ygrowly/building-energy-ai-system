import type { Incident } from '../api/incident'
import type { DispatchHallEntry } from '../api/workorder'

export type OperatorWorkorderMessageCategory =
  | 'pending_review'
  | 'pending_dispatch'
  | 'hall_application'
  | 'takeover_recommendation'
  | 'pending_accept'
  | 'warning'
  | 'overdue'
  | 'waiting_support'
  | 'pending_close'

export type OperatorWorkorderMessageTone = 'pending' | 'warning' | 'danger' | 'success'
export type OperatorWorkorderMessageStage = 'accept' | 'arrive' | 'finish' | null

export interface OperatorWorkorderMessageItem {
  id: string
  incidentId: string
  ticketId: string | null
  buildingId: string
  category: OperatorWorkorderMessageCategory
  tone: OperatorWorkorderMessageTone
  title: string
  subtitle: string
  detail: string
  tag: string
  dispatchStage: OperatorWorkorderMessageStage
  occurredAt: string | null
  sortWeight: number
  hallEntryId?: string | null
  applicationId?: string | null
}

export interface OperatorWorkorderMessageGroups {
  review: OperatorWorkorderMessageItem[]
  execution: OperatorWorkorderMessageItem[]
  closing: OperatorWorkorderMessageItem[]
}

function summaryText(value?: string | null): string {
  return (value || '').trim() || '异常事件待处理'
}

function executionStatusOf(incident: Incident): string | null {
  return incident.current_dispatch?.execution_status
    || incident.current_work_order?.execution_status
    || null
}

function slaStatusOf(incident: Incident): string | null {
  return incident.current_dispatch?.sla_status
    || incident.current_work_order?.sla_status
    || null
}

function slaMinutesLeftOf(incident: Incident): number | null {
  const dispatchMinutes = incident.current_dispatch?.sla_minutes_left
  if (dispatchMinutes !== null && dispatchMinutes !== undefined) return dispatchMinutes
  const orderMinutes = incident.current_work_order?.sla_minutes_left
  return orderMinutes !== undefined ? orderMinutes : null
}

function occurredAtOf(incident: Incident): string | null {
  return incident.current_dispatch?.updated_at
    || incident.current_dispatch?.dispatch_at
    || incident.current_work_order?.updated_at
    || incident.current_work_order?.dispatch_at
    || incident.updated_at
    || incident.created_at
    || null
}

function dispatchStageOf(incident: Incident): OperatorWorkorderMessageStage {
  const dispatchStatus = incident.current_dispatch?.dispatch_status
  const executionStatus = executionStatusOf(incident)
  if (dispatchStatus === 'assigned' || executionStatus === 'pending_accept') return 'accept'
  if (dispatchStatus === 'accepted' || executionStatus === 'accepted') return 'arrive'
  if (dispatchStatus && ['arrived', 'processing', 'waiting_support'].includes(dispatchStatus)) return 'finish'
  if (executionStatus && ['arrived', 'processing', 'waiting_support', 'overdue'].includes(executionStatus)) return 'finish'
  return null
}

function stageLabel(stage: OperatorWorkorderMessageStage): string {
  if (stage === 'accept') return '接单'
  if (stage === 'arrive') return '到场'
  if (stage === 'finish') return '处理'
  return '执行'
}

function stageSortBoost(stage: OperatorWorkorderMessageStage): number {
  if (stage === 'accept') return 4
  if (stage === 'arrive') return 2
  if (stage === 'finish') return 1
  return 0
}

function categoryOf(incident: Incident): OperatorWorkorderMessageCategory | null {
  if (incident.workflow_status === 'pending_review') return 'pending_review'
  if (incident.workflow_status === 'pending_dispatch') return 'pending_dispatch'
  if (incident.workflow_status && ['completed', 'false_alarm', 'escalated'].includes(incident.workflow_status)) {
    return 'pending_close'
  }
  if (incident.workflow_status !== 'dispatched') return null

  const executionStatus = executionStatusOf(incident)
  const slaStatus = slaStatusOf(incident)
  if (executionStatus === 'waiting_support') return 'waiting_support'
  if (slaStatus === 'overdue') return 'overdue'
  if (slaStatus === 'warning') return 'warning'
  if (executionStatus === 'pending_accept') return 'pending_accept'
  return null
}

function sortWeightOf(category: OperatorWorkorderMessageCategory): number {
  const map: Record<OperatorWorkorderMessageCategory, number> = {
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
  return map[category]
}

function buildOperatorHallApplicationMessageItems(entries: DispatchHallEntry[]): OperatorWorkorderMessageItem[] {
  return entries.flatMap((entry) => {
    const pendingApplications = entry.applications.filter((application) => application.status === 'pending')
    return pendingApplications.map((application) => {
      const isTakeover = application.application_type === 'takeover'
      const typeLabel = isTakeover ? '接管申请' : '协同申请'
      const summary = summaryText(
        entry.support_reason
        || entry.reason
        || entry.work_order?.issue_description,
      )
      const detail = sanitizeHallMessageDetail(
        application.applicant_username,
        typeLabel,
        application.note,
      )
      const occurredAt = application.created_at || application.updated_at || entry.updated_at || entry.created_at || null
      return {
        id: `hall:${entry.id}:${application.id}`,
        incidentId: entry.incident_id || entry.id,
        ticketId: entry.work_order?.ticket_id || null,
        buildingId: entry.work_order?.building_id || '',
        category: 'hall_application' as const,
        tone: 'pending' as const,
        title: '工单大厅申请',
        subtitle: summary,
        detail,
        tag: typeLabel,
        dispatchStage: null,
        occurredAt,
        sortWeight: sortWeightOf('hall_application'),
        hallEntryId: entry.id,
        applicationId: application.id,
      }
    })
  })
}

function sanitizeHallMessageDetail(
  applicantUsername: string | null,
  typeLabel: string,
  note: string | null,
) {
  const actor = (applicantUsername || '维修人员').trim() || '维修人员'
  const noteText = (note || '').trim()
  if (noteText) {
    return `${actor} 提交了${typeLabel}，备注：${noteText}`
  }
  return `${actor} 提交了${typeLabel}，等待管理员确认。`
}

function buildOperatorTakeoverRecommendationItems(entries: DispatchHallEntry[]): OperatorWorkorderMessageItem[] {
  return entries
    .filter((entry) => (
      entry.entry_type === 'takeover_candidate'
      && entry.status === 'open'
      && !entry.applications.some((application) => application.status === 'pending')
    ))
    .map((entry) => ({
      id: `hall-takeover:${entry.id}`,
      incidentId: entry.incident_id || entry.id,
      ticketId: entry.work_order?.ticket_id || null,
      buildingId: entry.work_order?.building_id || '',
      category: 'takeover_recommendation' as const,
      tone: 'danger' as const,
      title: '超时待接管',
      subtitle: summaryText(
        entry.reason
        || entry.support_reason
        || entry.work_order?.issue_description,
      ),
      detail: '当前派工已超时，系统已自动提醒责任人，并已开放工单大厅待接管。建议查看改派候选人。',
      tag: '待接管',
      dispatchStage: null,
      occurredAt: entry.updated_at || entry.created_at || null,
      sortWeight: sortWeightOf('takeover_recommendation'),
      hallEntryId: entry.id,
    }))
}

export function buildOperatorWorkorderMessageItems(
  incidents: Incident[],
  hallEntries: DispatchHallEntry[] = [],
): OperatorWorkorderMessageItem[] {
  const incidentItems = incidents
    .map((incident) => {
      const category = categoryOf(incident)
      if (!category) return null

      const dispatchStage = dispatchStageOf(incident)
      const assignedName = incident.current_dispatch?.assigned_to_name
        || incident.current_work_order?.assigned_to_name
        || '责任人'
      const blockedReason = incident.current_dispatch?.support_reason
        || incident.current_work_order?.dispatch_blocked_reason
        || incident.dispatch_blocked_reason
        || incident.current_dispatch?.latest_note
        || incident.latest_dispatch_note
        || ''
      const minutesLeft = slaMinutesLeftOf(incident)

      let title = '工单动态'
      let detail = ''
      let tag = ''
      let tone: OperatorWorkorderMessageTone = 'pending'

      if (category === 'pending_review') {
        title = '待AI审阅'
        detail = '异常事件已进入审批队列，请尽快确认。'
        tag = '待审阅'
      } else if (category === 'pending_dispatch') {
        title = '待派工'
        detail = '审批已通过，等待分配责任人。'
        tag = '待派工'
      } else if (category === 'pending_accept') {
        title = '派工成功'
        detail = `已派给 ${assignedName}，等待接单确认。`
        tag = '已派工'
      } else if (category === 'waiting_support') {
        title = '协同请求'
        detail = blockedReason || '维修人员已申请协同或配件支持。'
        tag = '协同请求'
        tone = 'warning'
      } else if (category === 'warning') {
        title = `${stageLabel(dispatchStage)}即将超时`
        detail = blockedReason || (
          minutesLeft !== null && minutesLeft !== undefined
            ? `${stageLabel(dispatchStage)}节点剩余 ${minutesLeft} 分钟，请尽快催办。`
            : `${stageLabel(dispatchStage)}节点临近超时，请尽快跟进。`
        )
        tag = `${stageLabel(dispatchStage)}临期`
        tone = 'warning'
      } else if (category === 'overdue') {
        title = `${stageLabel(dispatchStage)}已超时`
        detail = blockedReason || `${stageLabel(dispatchStage)}节点已超时，请提醒责任人或考虑改派。`
        tag = `${stageLabel(dispatchStage)}超时`
        tone = 'danger'
      } else if (category === 'pending_close') {
        title = '完成待复核'
        if (incident.workflow_status === 'false_alarm') {
          detail = '该工单已标记误报，等待管理员确认关闭。'
          title = '误报待关闭'
          tag = '待关闭'
        } else if (incident.workflow_status === 'escalated') {
          detail = '该工单已升级处理，等待管理员继续跟进。'
          title = '升级待跟进'
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
        category,
        tone,
        title,
        subtitle: summaryText(incident.summary_text),
        detail,
        tag,
        dispatchStage,
        occurredAt: occurredAtOf(incident),
        sortWeight: sortWeightOf(category) + stageSortBoost(dispatchStage),
      }
    })
    .filter((item): item is OperatorWorkorderMessageItem => Boolean(item))

  const hallItems = buildOperatorHallApplicationMessageItems(hallEntries)
  const takeoverItems = buildOperatorTakeoverRecommendationItems(hallEntries)

  return [...incidentItems, ...hallItems, ...takeoverItems]
    .sort((a, b) => {
      if (b.sortWeight !== a.sortWeight) return b.sortWeight - a.sortWeight
      return new Date(b.occurredAt || 0).getTime() - new Date(a.occurredAt || 0).getTime()
    })
}

export function filterOperatorWorkorderMessageItems(
  items: OperatorWorkorderMessageItem[],
  {
    buildingId = 'all',
    hours = 0,
  }: {
    buildingId?: string
    hours?: number
  } = {},
): OperatorWorkorderMessageItem[] {
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

export function groupOperatorWorkorderMessageItems(
  items: OperatorWorkorderMessageItem[],
): OperatorWorkorderMessageGroups {
  return {
    review: items.filter((item) => ['pending_review', 'pending_dispatch', 'hall_application'].includes(item.category)),
    execution: items.filter((item) =>
      ['pending_accept', 'warning', 'overdue', 'waiting_support', 'takeover_recommendation'].includes(item.category),
    ),
    closing: items.filter((item) => item.category === 'pending_close'),
  }
}
