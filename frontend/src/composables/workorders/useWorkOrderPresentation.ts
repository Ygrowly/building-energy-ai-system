import type { Ref } from 'vue'

interface UseWorkOrderPresentationOptions {
  orderTimelines: Ref<Record<string, any>>
  statusLabels: Record<string, string>
  executionLabels: Record<string, string>
  getBuildingName: (id: string) => string
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
    return status ? options.executionLabels[status] ?? status : '—'
  }

  function assigneeNameForOrder(wo: any) {
    return currentDispatchForOrder(wo)?.assigned_to_name || wo.assigned_to_name || ''
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

  function detailRows(wo: any) {
    const currentDispatch = currentDispatchForOrder(wo)
    const rows: Array<{ label: string; value: string; cls?: string }> = [
      { label: '工单 ID', value: wo.ticket_id, cls: 'mono accent' },
      { label: '楼宇', value: buildingName(wo.building_id) },
      { label: '当前状态', value: options.statusLabels[wo.status] ?? wo.status },
      { label: '执行进度', value: executionLabelForOrder(wo) },
      { label: '责任人', value: assigneeNameForOrder(wo) || '未派工' },
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
      return fullTimeline.map((item: any) => ({
        time: formatTime(item.occurred_at || item.sort_value),
        label: item.attempt_no ? `第 ${item.attempt_no} 次 · ${item.label}` : item.label,
        note: item.note || '',
      }))
    }
    const events = wo.current_dispatch?.events ?? []
    if (events.length) {
      return events.map((event: any) => ({
        time: formatTime(event.created_at),
        label: dispatchEventLabel(event.event_type),
        note: event.payload?.notes || event.payload?.reason || event.payload?.result || event.payload?.selection_reason || event.payload?.message || '',
      }))
    }
    return [
      wo.dispatch_at ? { time: formatTime(wo.dispatch_at), label: '工单已派发', note: assigneeNameForOrder(wo) ? `已派给 ${assigneeNameForOrder(wo)}` : '' } : null,
      wo.accepted_at ? { time: formatTime(wo.accepted_at), label: '已接单', note: '' } : null,
      wo.arrived_at ? { time: formatTime(wo.arrived_at), label: '已到场', note: '' } : null,
      wo.processing_started_at ? { time: formatTime(wo.processing_started_at), label: '开始处理', note: wo.worker_notes || '' } : null,
      wo.worker_feedback_at ? { time: formatTime(wo.worker_feedback_at), label: '提交反馈', note: wo.worker_result || '' } : null,
    ].filter(Boolean)
  }

  function dispatchEventLabel(eventType: string) {
    const labels: Record<string, string> = {
      assigned: '人工派工',
      auto_assigned: '自动派工',
      reminded: '调度催办',
      accepted: '维修员接单',
      arrived: '维修员到场',
      started: '开始处理',
      support_requested: '申请协同',
      support_resolved: '协同解决',
      rejected: '维修员拒单',
      transferred: '调度改派',
      cancelled: '取消派工',
      timeout_warning: '临近超时',
      timeout_overdue: '已超时',
      completed: '处理完成',
      escalated: '升级处理',
    }
    Object.assign(labels, {
      support_assigned: '指派协同人员',
      support_worker_accepted: '协同人员接单',
      support_worker_rejected: '协同人员拒单',
    })
    return labels[eventType] || eventType
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
    executionStatusForOrder,
    executionLabelForOrder,
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
