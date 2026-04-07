import type { Ref } from 'vue'

interface UseWorkOrderPresentationOptions {
  orderTimelines: Ref<Record<string, any>>
  statusLabels: Record<string, string>
  executionLabels: Record<string, string>
  getBuildingName: (id: string) => string
}

function timelineTone(input: { label?: string; kind?: string; code?: string }) {
  const code = (input.code || '').toLowerCase()
  const label = input.label || ''

  if (
    ['rejected', 'cancelled', 'timeout_overdue', 'escalated'].includes(code)
    || label.includes('超时')
    || label.includes('拒单')
    || label.includes('升级')
  ) return 'danger'

  if (
    ['timeout_warning', 'support_requested', 'reminded', 'transferred'].includes(code)
    || label.includes('催办')
    || label.includes('协同')
    || label.includes('改派')
    || label.includes('转派')
  ) return 'warning'

  if (
    ['accepted', 'arrived', 'started'].includes(code)
    || label.includes('接单')
    || label.includes('到场')
    || label.includes('开始')
  ) return 'accent'

  if (
    ['assigned', 'auto_assigned', 'completed', 'support_resolved', 'worker_feedback', 'close', 'dispatch', 'create'].includes(code)
    || label.includes('创建')
    || label.includes('派工')
    || label.includes('完成')
    || label.includes('关闭')
    || label.includes('反馈')
  ) return 'success'

  return input.kind === 'work_order_audit' ? 'neutral' : 'accent'
}

function dispatchEventLabel(eventType: string) {
  const labels: Record<string, string> = {
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
  }
  return labels[eventType] || eventType
}

function buildTimelineItem(input: {
  id?: string
  time?: string | null
  label: string
  note?: string
  kind?: string
  code?: string
  attemptNo?: number | null
}) {
  return {
    id: input.id || `${input.kind || 'timeline'}:${input.label}:${input.time || ''}`,
    time: input.time || '—',
    label: input.label,
    note: input.note || '',
    kind: input.kind || 'dispatch_event',
    code: input.code || '',
    attemptNo: input.attemptNo ?? null,
    tone: timelineTone(input),
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

  function currentBlockReason(wo: any) {
    const currentDispatch = currentDispatchForOrder(wo)
    return wo.dispatch_blocked_reason
      || currentDispatch?.support_reason
      || currentDispatch?.reject_reason
      || ''
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
    return id ? options.getBuildingName(id) : '—'
  }

  function assigneeName(wo: any, currentDispatch: any) {
    return currentDispatch?.assigned_to_name
      || currentDispatch?.candidate_snapshot?.username
      || wo.current_dispatch?.assigned_to_name
      || wo.assigned_to_name
      || '未派工'
  }

  function formatSlaText(wo: any, currentDispatch: any) {
    const status = String(currentDispatch?.sla_status || wo.sla_status || '').trim()
    const minutesRaw = currentDispatch?.sla_minutes_left ?? wo.sla_minutes_left

    if (!status) return '—'
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
    const rows: Array<{ label: string; value: string; cls?: string }> = [
      { label: '工单 ID', value: wo.ticket_id, cls: 'mono accent' },
      { label: '楼宇', value: buildingName(wo.building_id) },
      { label: '当前状态', value: options.statusLabels[wo.status] ?? wo.status },
      { label: '执行进度', value: options.executionLabels[currentDispatch?.execution_status || wo.execution_status] ?? currentDispatch?.execution_status ?? wo.execution_status ?? '—' },
      { label: '责任人', value: assigneeName(wo, currentDispatch) },
      { label: '责任班组', value: currentDispatch?.assigned_team_name || wo.assigned_team_name || '—' },
      { label: '派工批次', value: dispatchAttemptCount(wo) > 0 ? `第 ${dispatchAttemptCount(wo)} 次` : '—' },
      { label: 'SLA', value: (currentDispatch?.sla_status || wo.sla_status) ? `${currentDispatch?.sla_status || wo.sla_status}${(currentDispatch?.sla_minutes_left ?? wo.sla_minutes_left) != null ? ` · 剩余 ${currentDispatch?.sla_minutes_left ?? wo.sla_minutes_left} 分钟` : ''}` : '—' },
      { label: 'AI结论', value: wo.ai_reason || '—', cls: 'wrap' },
      { label: '派工建议', value: wo.dispatch_profile?.summary || wo.suggested_action || '—', cls: 'wrap warning-text' },
      { label: '最新进展', value: wo.latest_progress_note || wo.dispatch_blocked_reason || '—', cls: 'wrap' },
    ]
    if (currentBlockReason(wo)) {
      rows.push({ label: '当前阻塞', value: currentBlockReason(wo), cls: 'wrap danger-text' })
    }
    if (latestReassignReason(wo)) {
      rows.push({ label: '最近改派', value: latestReassignReason(wo), cls: 'wrap' })
    }
    return rows
  }

  function timelineRows(wo: any) {
    const fullTimeline = timelineData(wo)?.timeline ?? []
    if (fullTimeline.length) {
      return fullTimeline.map((item: any, index: number) => buildTimelineItem({
        id: item.id || `timeline:${wo.ticket_id}:${index}`,
        time: formatTime(item.occurred_at || item.sort_value),
        label: item.attempt_no ? `第${item.attempt_no}次 · ${item.label}` : item.label,
        note: item.note || '',
        kind: item.kind || 'dispatch_event',
        code: item.event_type || item.action || '',
        attemptNo: item.attempt_no ?? null,
      }))
    }

    const events = wo.current_dispatch?.events ?? []
    if (events.length) {
      return events.map((event: any, index: number) => buildTimelineItem({
        id: event.id || `event:${wo.ticket_id}:${index}`,
        time: formatTime(event.created_at),
        label: dispatchEventLabel(event.event_type),
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
    if (!iso) return '—'
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
    detailRows,
    timelineRows,
    buildingName,
    formatTime,
    statusCardClass,
    statusChipClass,
    executionChipClass,
  }
}
