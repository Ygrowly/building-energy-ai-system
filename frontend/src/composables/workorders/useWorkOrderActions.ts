import type { Ref } from 'vue'
import { apiFetch } from '@/api/http'

type ActionKey = 'approve_pending' | 'reject_pending' | 'override_approve' | 'dispatch' | 'reassign' | 'execute_auto_reassign' | 'nudge' | 'resolve_support' | 'cancel_dispatch' | 'confirm' | 'close_escalated' | 'mark_auto_dispatch_reviewed' | 'mark_auto_dispatch_needs_reassign'

interface OrderAction {
  action: ActionKey
  label: string
  className: string
}

interface UseWorkOrderActionsOptions {
  currentSessionId: () => string | null | undefined
  rejectReason: Ref<string>
  actionLoading: Ref<string | null>
  actionResult: Ref<Record<string, { type: 'success' | 'error'; message: string }>>
  dispatchPanel: Ref<any>
  dispatchSubmitting: Ref<string | null>
  fetchOrders: () => Promise<void>
  cancelReject: () => void
  currentDispatchForOrder: (wo: any) => any
}

export function useWorkOrderActions(options: UseWorkOrderActionsOptions) {
  function clearActionResult(ticketId: string) {
    options.actionResult.value = { ...options.actionResult.value, [ticketId]: undefined as any }
  }

  function setActionResult(ticketId: string, type: 'success' | 'error', message: string) {
    options.actionResult.value = {
      ...options.actionResult.value,
      [ticketId]: { type, message },
    }
  }

  function autoDispatchReviewStatusForOrder(wo: any, currentDispatch: any) {
    return wo.auto_dispatch_review_state?.status
      || currentDispatch?.auto_dispatch_review_state?.status
      || (
        wo.admin_action === 'auto_dispatch_reviewed'
          ? 'reviewed'
          : wo.admin_action === 'auto_dispatch_needs_reassign'
            ? 'needs_reassign'
            : ''
      )
  }

  function formatAutoReassignBlockers(evaluation: any) {
    const blockers = Array.isArray(evaluation?.blockers) ? evaluation.blockers : []
    if (blockers.length) {
      return blockers.map((item: any) => item.label || item.reason).filter(Boolean).join('、')
    }
    if (evaluation?.decision === 'manual_review') return '当前评估建议人工复核'
    return '当前没有满足自动重派条件的候选人'
  }

  function autoReassignCandidateLabel(evaluation: any) {
    const candidate = evaluation?.top_candidate || {}
    return candidate.username
      ? `${candidate.username}${candidate.score != null ? `（${candidate.score}分）` : ''}`
      : evaluation?.apply_payload?.assigned_to || '推荐人员'
  }

  async function executeAutoReassignWithConfirmation(wo: any) {
    const ticketId = wo.ticket_id
    const evaluation = await apiFetch<any>(`/api/work-orders/${ticketId}/auto-reassign-evaluation`)

    if (!evaluation?.eligible || !evaluation?.apply_payload) {
      setActionResult(ticketId, 'error', `暂不满足自动重派：${formatAutoReassignBlockers(evaluation)}`)
      return
    }

    const confirmText = [
      `确认按自动评估把工单 ${ticketId} 改派给 ${autoReassignCandidateLabel(evaluation)} 吗？`,
      evaluation.selection_reason ? `依据：${evaluation.selection_reason}` : '',
      evaluation.current_dispatch_id ? `原派工：${evaluation.current_dispatch_id}` : '',
    ].filter(Boolean).join('\n')

    if (!window.confirm(confirmText)) return

    const result = await apiFetch<any>(`/api/work-orders/${ticketId}/auto-reassign`, { method: 'POST' })
    setActionResult(
      ticketId,
      result?.action_taken ? 'success' : 'error',
      result?.message || (result?.action_taken ? '自动重派已执行' : '自动重派未执行'),
    )
    if (result?.action_taken) {
      await options.fetchOrders()
    }
  }

  async function runAction(wo: any, action: string) {
    const actionKey = action as ActionKey
    const ticketId = wo.ticket_id
    const currentDispatch = options.currentDispatchForOrder(wo)
    clearActionResult(ticketId)
    options.actionLoading.value = `${ticketId}:${actionKey}`
    try {
      if (actionKey === 'approve_pending') {
        if (!options.currentSessionId()) throw new Error('请先在 AI 控制台建立会话')
        await apiFetch('/api/work-orders/approve', {
          method: 'POST',
          body: JSON.stringify({ session_id: options.currentSessionId(), ticket_id: ticketId, approved: true }),
        })
      } else if (actionKey === 'reject_pending') {
        if (!options.currentSessionId()) throw new Error('请先在 AI 控制台建立会话')
        await apiFetch('/api/work-orders/approve', {
          method: 'POST',
          body: JSON.stringify({
            session_id: options.currentSessionId(),
            ticket_id: ticketId,
            approved: false,
            reason: options.rejectReason.value || undefined,
          }),
        })
        options.cancelReject()
      } else if (actionKey === 'override_approve') {
        await apiFetch(`/api/work-orders/${ticketId}/admin-review`, {
          method: 'POST',
          body: JSON.stringify({ action: 'override_approve' }),
        })
      } else if (actionKey === 'dispatch') {
        await openDispatchPanel(wo, 'dispatch')
        options.actionLoading.value = null
        return
      } else if (actionKey === 'reassign') {
        await openDispatchPanel(wo, 'reassign')
        options.actionLoading.value = null
        return
      } else if (actionKey === 'execute_auto_reassign') {
        await executeAutoReassignWithConfirmation(wo)
        return
      } else if (actionKey === 'mark_auto_dispatch_reviewed') {
        await apiFetch(`/api/work-orders/${ticketId}/auto-dispatch-review`, {
          method: 'POST',
          body: JSON.stringify({ action: 'reviewed' }),
        })
      } else if (actionKey === 'mark_auto_dispatch_needs_reassign') {
        const notes = window.prompt('记录需改派原因', '自动派工复核后建议改派')
        if (notes === null) {
          options.actionLoading.value = null
          return
        }
        await apiFetch(`/api/work-orders/${ticketId}/auto-dispatch-review`, {
          method: 'POST',
          body: JSON.stringify({
            action: 'needs_reassign',
            notes: notes || '自动派工复核后建议改派',
          }),
        })
      } else if (actionKey === 'nudge') {
        if (!currentDispatch?.id) throw new Error('当前派工任务不存在')
        await apiFetch(`/api/dispatch-tasks/${currentDispatch.id}/nudge`, {
          method: 'POST',
          body: JSON.stringify({
            message: currentDispatch?.execution_status === 'overdue'
              ? '当前工单已超时，请立即处理并同步现场进展'
              : '请尽快跟进当前工单，并同步处理进度',
          }),
        })
      } else if (actionKey === 'resolve_support') {
        if (!currentDispatch?.id) throw new Error('当前派工任务不存在')
        await apiFetch(`/api/dispatch-tasks/${currentDispatch.id}/support-resolved`, {
          method: 'POST',
          body: JSON.stringify({ notes: '协同事项已解决，恢复处理中' }),
        })
      } else if (actionKey === 'cancel_dispatch') {
        if (!currentDispatch?.id) throw new Error('当前派工任务不存在')
        const reason = window.prompt('请输入取消派工原因', '现场条件变化，当前派工撤回')
        if (!reason) {
          options.actionLoading.value = null
          return
        }
        await apiFetch(`/api/dispatch-tasks/${currentDispatch.id}/cancel`, {
          method: 'POST',
          body: JSON.stringify({ reason }),
        })
      } else if (actionKey === 'confirm') {
        await apiFetch(`/api/work-orders/${ticketId}/admin-review`, {
          method: 'POST',
          body: JSON.stringify({ action: 'confirm' }),
        })
      } else if (actionKey === 'close_escalated') {
        await apiFetch(`/api/work-orders/${ticketId}/admin-review`, {
          method: 'POST',
          body: JSON.stringify({ action: 'close_escalated' }),
        })
      }

      setActionResult(ticketId, 'success', '操作已执行，列表已刷新')
      await options.fetchOrders()
    } catch (e: any) {
      setActionResult(ticketId, 'error', e.message || '操作失败')
    } finally {
      options.actionLoading.value = null
    }
  }

  async function openDispatchPanel(wo: any, mode: 'dispatch' | 'reassign') {
    const data = await apiFetch<any>(`/api/work-orders/${wo.ticket_id}/dispatch-candidates`)
    options.dispatchPanel.value = {
      visible: true,
      mode,
      ticketId: wo.ticket_id,
      dispatchId: wo.current_dispatch?.id ?? null,
      requirement: data?.requirement ?? null,
      candidates: data?.candidates ?? [],
    }
  }

  function closeDispatchPanel() {
    if (options.dispatchSubmitting.value) return
    options.dispatchPanel.value = {
      visible: false,
      mode: 'dispatch',
      ticketId: null,
      dispatchId: null,
      requirement: null,
      candidates: [],
    }
  }

  async function confirmDispatchCandidate(candidate: any) {
    if (!options.dispatchPanel.value.ticketId) return
    options.dispatchSubmitting.value = candidate.user_id
    try {
      if (options.dispatchPanel.value.mode === 'reassign' && options.dispatchPanel.value.dispatchId) {
        await apiFetch(`/api/dispatch-tasks/${options.dispatchPanel.value.dispatchId}/reassign`, {
          method: 'POST',
          body: JSON.stringify({
            assigned_to: candidate.user_id,
            reason: `调度改派：${candidate.recommend_reason}`,
            dispatch_mode: 'reassigned',
          }),
        })
      } else {
        await apiFetch(`/api/work-orders/${options.dispatchPanel.value.ticketId}/dispatch`, {
          method: 'POST',
          body: JSON.stringify({
            assigned_to: candidate.user_id,
            dispatch_mode: 'manual',
            selection_reason: candidate.recommend_reason,
          }),
        })
      }
      closeDispatchPanel()
      await options.fetchOrders()
    } finally {
      options.dispatchSubmitting.value = null
    }
  }

  function autoDispatchReviewActionsForOrder(wo: any): OrderAction[] {
    const currentDispatch = options.currentDispatchForOrder(wo)
    const reviewStatus = autoDispatchReviewStatusForOrder(wo, currentDispatch)
    if (
      (currentDispatch?.auto_dispatch_review || currentDispatch?.candidate_snapshot?.auto_dispatch)
      && !['reviewed', 'needs_reassign'].includes(reviewStatus || '')
    ) {
      return [
        { action: 'mark_auto_dispatch_reviewed', label: '标记已复核', className: 'primary' },
        { action: 'mark_auto_dispatch_needs_reassign', label: '需改派', className: 'danger' },
      ]
    }
    return []
  }

  function actionsForOrder(wo: any): OrderAction[] {
    const reviewActions = autoDispatchReviewActionsForOrder(wo)
    if (wo.status === 'pending_review') {
      return [
        { action: 'approve_pending', label: 'AI通过转待派工', className: 'primary' },
        { action: 'reject_pending', label: '驳回', className: 'danger' },
      ]
    }
    if (wo.status === 'auto_rejected') {
      return [{ action: 'override_approve', label: '转待派工', className: 'primary' }]
    }
    if (wo.status === 'pending_dispatch' || wo.status === 'auto_approved' || wo.status === 'admin_override_approved') {
      return [{ action: 'dispatch', label: '立即派工', className: 'primary' }]
    }
    if (wo.status === 'dispatched') {
      const currentDispatch = options.currentDispatchForOrder(wo)
      const executionStatus = currentDispatch?.execution_status || wo.execution_status
      const reviewStatus = autoDispatchReviewStatusForOrder(wo, currentDispatch)
      const actions: OrderAction[] = [...reviewActions, { action: 'reassign', label: '改派', className: 'secondary' }]
      if (currentDispatch?.id && (executionStatus === 'overdue' || reviewStatus === 'needs_reassign')) {
        actions.unshift({ action: 'execute_auto_reassign', label: '自动重派', className: 'danger' })
      }
      if (['pending_accept', 'overdue', 'waiting_support'].includes(executionStatus || '')) {
        actions.unshift({ action: 'nudge', label: '催办', className: 'secondary' })
      }
      if (executionStatus === 'waiting_support') {
        actions.unshift({ action: 'resolve_support', label: '恢复处理', className: 'secondary' })
      }
      if (['pending_accept', 'accepted'].includes(executionStatus || '')) {
        actions.push({ action: 'cancel_dispatch', label: '取消派工', className: 'danger' })
      }
      return actions
    }
    if (['completed', 'false_alarm'].includes(wo.status)) {
      return [...reviewActions, { action: 'confirm', label: '确认关闭', className: 'secondary' }]
    }
    if (wo.status === 'escalated') {
      return [...reviewActions, { action: 'close_escalated', label: '关闭升级', className: 'secondary' }]
    }
    return reviewActions
  }

  return {
    runAction,
    openDispatchPanel,
    closeDispatchPanel,
    confirmDispatchCandidate,
    actionsForOrder,
  }
}
