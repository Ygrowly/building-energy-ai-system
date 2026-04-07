import type { Ref } from 'vue'
import { apiFetch } from '@/api/http'

type ActionKey = 'approve_pending' | 'reject_pending' | 'override_approve' | 'dispatch' | 'reassign' | 'nudge' | 'resolve_support' | 'cancel_dispatch' | 'confirm' | 'close_escalated'

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

      options.actionResult.value = {
        ...options.actionResult.value,
        [ticketId]: { type: 'success', message: '操作已执行，列表已刷新' },
      }
      await options.fetchOrders()
    } catch (e: any) {
      options.actionResult.value = {
        ...options.actionResult.value,
        [ticketId]: { type: 'error', message: e.message || '操作失败' },
      }
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

  function actionsForOrder(wo: any): OrderAction[] {
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
      const actions: OrderAction[] = [{ action: 'reassign', label: '改派', className: 'secondary' }]
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
      return [{ action: 'confirm', label: '确认关闭', className: 'secondary' }]
    }
    if (wo.status === 'escalated') {
      return [{ action: 'close_escalated', label: '关闭升级', className: 'secondary' }]
    }
    return []
  }

  return {
    runAction,
    openDispatchPanel,
    closeDispatchPanel,
    confirmDispatchCandidate,
    actionsForOrder,
  }
}
