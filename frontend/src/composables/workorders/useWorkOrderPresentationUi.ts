import type { Ref } from 'vue'
import { sanitizeBuildingText } from '@/constants/buildings'

interface UseWorkOrderPresentationOptions {
  orderTimelines: Ref<Record<string, any>>
  statusLabels: Record<string, string>
  executionLabels: Record<string, string>
  getBuildingName: (id: string) => string
}

const EMPTY_TEXT = '—'

const dispatchEventLabels: Record<string, string> = {
  assigned: '人工派工',
  auto_assigned: '自动派工',
  reminded: '调度催办',
  accepted: '维修人员接单',
  arrived: '维修人员到场',
  started: '开始处理',
  support_requested: '申请协同',
  support_resolved: '协同完成',
  rejected: '维修人员拒单',
  transferred: '调度改派',
  cancelled: '取消派工',
  timeout_warning: '临近超时',
  timeout_overdue: '已超时',
  completed: '处理完成',
  escalated: '升级处理',
  support_assigned: '指派协同人员',
  support_worker_accepted: '协同人员接单',
  support_worker_rejected: '协同人员拒单',
}

const auditActionLabels: Record<string, string> = {
  create: '工单已创建',
  dispatch: '工单进入派工流程',
  dispatch_accept: '维修人员确认接单',
  dispatch_arrive: '维修人员确认到场',
  dispatch_start: '维修人员开始处理',
  dispatch_request_support: '维修人员申请协同',
  dispatch_support_resolved: '协同事项已解决',
  dispatch_nudge: '调度已催办',
  dispatch_reject: '维修人员拒单，工单返回待派工',
  dispatch_reassign: '管理员改派',
  dispatch_cancel: '管理员取消当前派工',
  auto_dispatch_reviewed: '自动派工复核通过',
  auto_dispatch_needs_reassign: '自动派工需改派',
  auto_reassign_rollout_skipped: '自动重派灰度跳过',
  auto_reassign_shadow_evaluated: '自动重派影子评估',
  auto_reassign_executed: '自动重派已执行',
  worker_feedback: '维修结果已提交',
  close: '工单已关闭',
  dispatch_hall_apply_support: '共享大厅申请协同',
  dispatch_hall_apply_takeover: '共享大厅申请接管',
  dispatch_hall_assign_support: '协同任务已分派',
  dispatch_hall_assign_takeover: '接管任务已分派',
  dispatch_hall_reject_application: '共享大厅申请已驳回',
  dispatch_hall_withdraw_application: '共享大厅申请已撤回',
  dispatch_hall_close: '共享大厅事项已关闭',
  dispatch_hall_support_accept: '协同任务已接受',
  dispatch_hall_support_reject: '协同任务已拒绝',
  ai_worker_pending: '维小修等待确认',
  ai_worker_success: '维小修动作已执行',
  ai_worker_failed: '维小修动作执行失败',
  admin_override: '管理员人工干预',
  confirm: '管理员确认关闭',
  override_approve: '管理员强制通过',
  override_reject: '管理员强制驳回',
  close_escalated: '管理员关闭升级工单',
}

const approvalStatusLabels: Record<string, string> = {
  pending_review: '待 AI 审阅',
  approved: '已批准',
  rejected: '已驳回',
}

const dispatchSummaryStatusLabels: Record<string, string> = {
  pending_dispatch: '待派工',
  assigned: '待接单',
  accepted: '已接单',
  arrived: '已到场',
  processing: '处理中',
  waiting_support: '待协同',
  completed: '处理完成',
  cancelled: '已取消',
  escalated: '已升级',
}

const workResultLabels: Record<string, string> = {
  fixed: '已修复',
  false_alarm: '误报',
  escalated: '已升级',
}

const timelineNoteReplacements: Array<[RegExp, string]> = [
  [/\bhall_takeover\b/gi, '大厅接管'],
  [/\bauto_fallback\b/gi, '低置信兜底派工'],
  [/\bauto\b/gi, '自动派工'],
  [/\bmanual\b/gi, '人工派工'],
  [/\bsupport_request\b/gi, '协同申请'],
  [/\blow_confidence_fallback_dispatch\b/gi, '低置信兜底派工'],
  [/\bhigh_confidence_dispatch\b/gi, '高置信自动派工'],
]

interface TimelineItemInput {
  id?: string
  time?: string | null
  label?: string
  note?: string
  kind?: string
  code?: string
  attemptNo?: number | null
}

function mapTimelineLabel(value?: string | null, kind?: string) {
  const key = String(value || '').trim().toLowerCase()
  if (!key) return ''
  if (kind === 'work_order_audit' && auditActionLabels[key]) return auditActionLabels[key]
  return auditActionLabels[key] || dispatchEventLabels[key] || ''
}

function normalizeTimelineLabel(input: { label?: string; code?: string; kind?: string }) {
  const mappedByCode = mapTimelineLabel(input.code, input.kind)
  if (mappedByCode) return mappedByCode

  const rawLabel = String(input.label || '').trim()
  if (!rawLabel) return '状态更新'

  const mappedByLabel = mapTimelineLabel(rawLabel, input.kind)
  if (mappedByLabel) return mappedByLabel

  return sanitizeBuildingText(rawLabel)
}

function normalizeTimelineNote(note?: string | null) {
  let text = sanitizeBuildingText(String(note || '').trim())
  if (!text) return ''
  timelineNoteReplacements.forEach(([pattern, replacement]) => {
    text = text.replace(pattern, replacement)
  })
  return text
}

function timelineTone(input: { label?: string; kind?: string; code?: string }) {
  const code = String(input.code || '').toLowerCase()
  const label = String(input.label || '')

  if (
    ['rejected', 'cancelled', 'timeout_overdue', 'escalated', 'dispatch_reject', 'dispatch_cancel'].includes(code)
    || label.includes('超时')
    || label.includes('拒单')
    || label.includes('升级')
    || label.includes('驳回')
  ) {
    return 'danger'
  }

  if (
    ['timeout_warning', 'support_requested', 'reminded', 'transferred', 'dispatch_request_support', 'dispatch_nudge', 'dispatch_reassign'].includes(code)
    || label.includes('催办')
    || label.includes('协同')
    || label.includes('改派')
  ) {
    return 'warning'
  }

  if (
    ['accepted', 'arrived', 'started', 'dispatch_accept', 'dispatch_arrive', 'dispatch_start'].includes(code)
    || label.includes('接单')
    || label.includes('到场')
    || label.includes('开始处理')
  ) {
    return 'accent'
  }

  if (
    ['assigned', 'auto_assigned', 'completed', 'support_resolved', 'worker_feedback', 'close', 'dispatch', 'create'].includes(code)
    || label.includes('创建')
    || label.includes('派工')
    || label.includes('完成')
    || label.includes('关闭')
    || label.includes('提交')
  ) {
    return 'success'
  }

  return input.kind === 'work_order_audit' ? 'neutral' : 'accent'
}

function buildTimelineItem(input: TimelineItemInput) {
  const label = normalizeTimelineLabel(input)
  return {
    id: input.id || `${input.kind || 'timeline'}:${label}:${input.time || ''}`,
    time: input.time || EMPTY_TEXT,
    label,
    note: normalizeTimelineNote(input.note),
    kind: input.kind || 'dispatch_event',
    code: input.code || '',
    attemptNo: input.attemptNo ?? null,
    tone: timelineTone({ label, kind: input.kind, code: input.code }),
  }
}

export function useWorkOrderPresentation(options: UseWorkOrderPresentationOptions) {
  function timelineData(wo: any) {
    return options.orderTimelines.value[wo.ticket_id] ?? null
  }

  function dispatchTasksForOrder(wo: any) {
    const tasks = timelineData(wo)?.dispatch_tasks
    if (Array.isArray(tasks) && tasks.length) return tasks
    return wo.current_dispatch ? [wo.current_dispatch] : []
  }

  function currentDispatchForOrder(wo: any) {
    const tasks = dispatchTasksForOrder(wo)
    return tasks.find((task: any) => task.is_current) || tasks[tasks.length - 1] || wo.current_dispatch || null
  }

  function dispatchAttemptCount(wo: any) {
    const tasks = dispatchTasksForOrder(wo)
    if (tasks.length) return tasks.length
    return wo.current_dispatch?.attempt_no || wo.dispatch_attempt_no || 0
  }

  function executionStatusForOrder(wo: any) {
    return currentDispatchForOrder(wo)?.execution_status || wo.execution_status || ''
  }

  function executionLabelForOrder(wo: any) {
    const status = executionStatusForOrder(wo)
    return status ? options.executionLabels[status] ?? status : ''
  }

  function currentBlockReason(wo: any) {
    const currentDispatch = currentDispatchForOrder(wo)
    return wo.dispatch_blocked_reason || currentDispatch?.support_reason || currentDispatch?.reject_reason || ''
  }

  function latestReassignReason(wo: any) {
    const tasks = [...dispatchTasksForOrder(wo)].reverse()
    const candidate = tasks.find((task: any) => (
      task?.selection_reason
      && (task?.transfer_from_dispatch_id || (task?.attempt_no || 0) > 1)
    ))
    return candidate?.selection_reason || ''
  }

  function buildingName(id: string) {
    return id ? options.getBuildingName(id) : EMPTY_TEXT
  }

  function assigneeName(wo: any, currentDispatch: any) {
    return (
      currentDispatch?.assigned_to_name
      || currentDispatch?.candidate_snapshot?.username
      || wo.current_dispatch?.assigned_to_name
      || wo.assigned_to_name
      || '未派工'
    )
  }

  function statusLabelForOrder(wo: any) {
    if (wo.status === 'closed') return options.statusLabels.closed ?? '已关闭'
    if (wo.approval_status === 'pending_review') return approvalStatusLabels.pending_review
    if (wo.approval_status === 'rejected') return approvalStatusLabels.rejected
    if (wo.work_result && wo.status !== 'closed') {
      return workResultLabels[wo.work_result] ? `${workResultLabels[wo.work_result]}待关闭` : wo.work_result
    }
    if (wo.dispatch_summary_status) {
      return dispatchSummaryStatusLabels[wo.dispatch_summary_status] ?? wo.dispatch_summary_status
    }
    return options.statusLabels[wo.status] ?? wo.status
  }

  function assigneeNameForOrder(wo: any) {
    return assigneeName(wo, currentDispatchForOrder(wo))
  }

  function formatSlaText(wo: any, currentDispatch: any) {
    const status = String(currentDispatch?.sla_status || wo.sla_status || '').trim()
    const minutesRaw = currentDispatch?.sla_minutes_left ?? wo.sla_minutes_left

    if (!status) return EMPTY_TEXT

    if (minutesRaw == null || Number.isNaN(Number(minutesRaw))) {
      if (status === 'overdue') return '已超时'
      if (status === 'warning') return '即将超时'
      if (status === 'normal') return '正常'
      return status
    }

    const minutes = Number(minutesRaw)
    const absMinutes = Math.abs(minutes)

    if (status === 'overdue' || minutes < 0) return `已超时 ${absMinutes} 分钟`
    if (status === 'warning') return `即将超时 · 剩余 ${absMinutes} 分钟`
    if (status === 'normal') return `正常 · 剩余 ${absMinutes} 分钟`
    return `${status} · ${minutes >= 0 ? `剩余 ${absMinutes} 分钟` : `超时 ${absMinutes} 分钟`}`
  }

  function detailRows(wo: any) {
    const currentDispatch = currentDispatchForOrder(wo)
    const autoDispatchReviewState = currentDispatch?.auto_dispatch_review?.review_state
      || currentDispatch?.auto_dispatch_review_state
      || wo.auto_dispatch_review_state

    const rows: Array<{ label: string; value: string; cls?: string }> = [
      { label: '工单 ID', value: wo.ticket_id, cls: 'mono accent' },
      { label: '楼宇', value: buildingName(wo.building_id) },
      { label: '当前状态', value: statusLabelForOrder(wo) },
      { label: '执行进度', value: options.executionLabels[currentDispatch?.execution_status || wo.execution_status] ?? currentDispatch?.execution_status ?? wo.execution_status ?? EMPTY_TEXT },
      { label: '责任人', value: assigneeName(wo, currentDispatch) },
      { label: '责任班组', value: currentDispatch?.assigned_team_name || wo.assigned_team_name || EMPTY_TEXT },
      { label: '派工批次', value: dispatchAttemptCount(wo) > 0 ? `第 ${dispatchAttemptCount(wo)} 次` : EMPTY_TEXT },
      { label: 'SLA', value: formatSlaText(wo, currentDispatch) },
      { label: 'AI 结论', value: wo.ai_reason || EMPTY_TEXT, cls: 'wrap' },
      { label: '派工建议', value: wo.dispatch_profile?.summary || wo.suggested_action || EMPTY_TEXT, cls: 'wrap warning-text' },
      { label: '最新进展', value: wo.latest_progress_note || wo.dispatch_blocked_reason || EMPTY_TEXT, cls: 'wrap' },
    ]

    if (currentBlockReason(wo)) {
      rows.push({ label: '当前阻塞', value: currentBlockReason(wo), cls: 'wrap danger-text' })
    }

    if (wo.approval_status || wo.dispatch_summary_status || wo.work_result) {
      rows.push({
        label: '状态投影',
        value: [
          approvalStatusLabels[wo.approval_status] || wo.approval_status,
          dispatchSummaryStatusLabels[wo.dispatch_summary_status] || wo.dispatch_summary_status,
          workResultLabels[wo.work_result] || wo.work_result,
        ].filter(Boolean).join(' / ') || EMPTY_TEXT,
        cls: 'wrap',
      })
    }

    if (currentDispatch?.auto_dispatch_review || currentDispatch?.candidate_snapshot?.auto_dispatch) {
      rows.push({
        label: '自动派工复核',
        value: autoDispatchReviewState?.status_label || '待复核',
        cls: autoDispatchReviewState?.status === 'needs_reassign' ? 'danger-text' : 'accent',
      })
    }

    if (latestReassignReason(wo)) {
      rows.push({ label: '最近改派', value: latestReassignReason(wo), cls: 'wrap' })
    }

    return rows
  }

  function timelineRows(wo: any) {
    const fullTimeline = timelineData(wo)?.timeline ?? []
    if (fullTimeline.length) {
      return fullTimeline.map((item: any, index: number) => {
        const timelineItem = buildTimelineItem({
          id: item.id || `timeline:${wo.ticket_id}:${index}`,
          time: formatTime(item.occurred_at || item.sort_value),
          label: item.label,
          note: item.note || '',
          kind: item.kind || 'dispatch_event',
          code: item.event_type || item.action || item.label || '',
          attemptNo: item.attempt_no ?? null,
        })

        return item.attempt_no
          ? { ...timelineItem, label: `第 ${item.attempt_no} 次 · ${timelineItem.label}` }
          : timelineItem
      })
    }

    const events = wo.current_dispatch?.events ?? []
    if (events.length) {
      return events.map((event: any, index: number) => buildTimelineItem({
        id: event.id || `event:${wo.ticket_id}:${index}`,
        time: formatTime(event.created_at),
        label: event.event_type,
        note: event.payload?.notes || event.payload?.reason || event.payload?.result || event.payload?.selection_reason || event.payload?.message || '',
        kind: 'dispatch_event',
        code: event.event_type,
      }))
    }

    return [
      wo.dispatch_at ? buildTimelineItem({ time: formatTime(wo.dispatch_at), label: '工单已派单', note: wo.assigned_to_name ? `已派给 ${wo.assigned_to_name}` : '', kind: 'dispatch_event', code: 'assigned' }) : null,
      wo.accepted_at ? buildTimelineItem({ time: formatTime(wo.accepted_at), label: '已接单', note: '', kind: 'dispatch_event', code: 'accepted' }) : null,
      wo.arrived_at ? buildTimelineItem({ time: formatTime(wo.arrived_at), label: '已到场', note: '', kind: 'dispatch_event', code: 'arrived' }) : null,
      wo.processing_started_at ? buildTimelineItem({ time: formatTime(wo.processing_started_at), label: '开始处理', note: wo.worker_notes || '', kind: 'dispatch_event', code: 'started' }) : null,
      wo.worker_feedback_at ? buildTimelineItem({ time: formatTime(wo.worker_feedback_at), label: '提交反馈', note: wo.worker_result || '', kind: 'dispatch_event', code: 'worker_feedback' }) : null,
    ].filter(Boolean)
  }

  function formatTime(iso?: string | null) {
    if (!iso) return EMPTY_TEXT
    try {
      return new Date(iso).toLocaleString('zh-CN', {
        month: '2-digit',
        day: '2-digit',
        hour: '2-digit',
        minute: '2-digit',
      })
    } catch {
      return iso
    }
  }

  function statusCardClass(wo: any) {
    return {
      'status-pending-review': wo.status === 'pending_review',
      'status-pending-dispatch': wo.status === 'pending_dispatch',
      'status-dispatched': wo.status === 'dispatched',
      'status-rejected': wo.status === 'auto_rejected',
      'status-resolved': ['completed', 'false_alarm', 'escalated', 'closed'].includes(wo.status),
    }
  }

  function statusChipClass(status: string) {
    return {
      'chip-pending-review': status === 'pending_review',
      'chip-pending-dispatch': status === 'pending_dispatch',
      'chip-dispatched': status === 'dispatched',
      'chip-rejected': status === 'auto_rejected',
      'chip-resolved': ['completed', 'false_alarm', 'escalated', 'closed'].includes(status),
    }
  }

  function executionChipClass(status: string) {
    return {
      'exec-pending': ['pending_dispatch', 'pending_accept'].includes(status),
      'exec-active': ['accepted', 'arrived', 'processing'].includes(status),
      'exec-support': status === 'waiting_support',
      'exec-danger': status === 'overdue',
    }
  }

  return {
    currentDispatchForOrder,
    executionStatusForOrder,
    executionLabelForOrder,
    statusLabelForOrder,
    assigneeNameForOrder,
    detailRows,
    timelineRows,
    buildingName,
    formatTime,
    statusCardClass,
    statusChipClass,
    executionChipClass,
  }
}
