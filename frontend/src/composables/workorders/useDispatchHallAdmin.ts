import { computed, type Ref } from 'vue'
import { apiFetch } from '@/api/http'

interface UseDispatchHallAdminOptions {
  hallEntries: Ref<any[]>
  actionLoading: Ref<string | null>
  fetchError: Ref<string>
  dispatchPanel: Ref<any>
  fetchOrders: () => Promise<void>
  closeDispatchPanel: () => void
}

export function useDispatchHallAdmin(options: UseDispatchHallAdminOptions) {
  const hallPendingApplicationCount = computed(() => options.hallEntries.value.reduce((sum, entry) => sum + hallPendingApplications(entry).length, 0))
  const hallSupportCount = computed(() => options.hallEntries.value.filter(entry => entry.entry_type === 'support_request').length)
  const hallTakeoverCount = computed(() => options.hallEntries.value.filter(entry => entry.entry_type === 'takeover_candidate').length)

  function hallPendingApplications(entry: any): any[] {
    return (entry.applications || []).filter((application: any) => application.status === 'pending')
  }

  function hallEntryTitle(entry: any) {
    return entry.support_reason || entry.reason || entry.work_order?.issue_description || '共享事项待处理'
  }

  function hallEntryOwner(entry: any) {
    return entry.source_dispatch?.assigned_to_name || '主责任人待确认'
  }

  function hallEntryReason(entry: any) {
    return entry.reason || entry.support_reason || entry.work_order?.dispatch_blocked_reason || '共享事项待处理'
  }

  function hallEntryIssue(entry: any) {
    return entry.work_order?.issue_description || '现场异常情况待确认'
  }

  function hallEmptyHint(entry: any) {
    if (entry.entry_type === 'takeover_candidate') {
      return '当前没有接管申请，系统已开放待接管，可先查看改派建议或催办责任人。'
    }
    return '当前没有待处理申请，可关闭该共享事项。'
  }

  function canSuggestHallTakeover(entry: any) {
    return entry.entry_type === 'takeover_candidate' && Boolean(entry.work_order?.ticket_id && entry.source_dispatch?.id)
  }

  function canNudgeHallOwner(entry: any) {
    return Boolean(entry.source_dispatch?.id)
  }

  function hallActionKey(entryId: string, applicationId: string, action: 'approve' | 'reject' | 'close' | 'suggest' | 'nudge') {
    return `hall:${entryId}:${applicationId || 'entry'}:${action}`
  }

  async function approveHallApplication(entry: any, application: any) {
    options.actionLoading.value = hallActionKey(entry.id, application.id, 'approve')
    try {
      if (entry.entry_type === 'support_request') {
        await apiFetch(`/api/dispatch-hall/${entry.id}/assign-support`, {
          method: 'POST',
          body: JSON.stringify({
            assigned_to: application.applicant_user_id,
            application_id: application.id,
            note: application.note || '工单大厅协同申请已同意',
          }),
        })
      } else {
        await apiFetch(`/api/dispatch-hall/${entry.id}/assign-takeover`, {
          method: 'POST',
          body: JSON.stringify({
            assigned_to: application.applicant_user_id,
            application_id: application.id,
            reason: `工单大厅接管申请通过：${application.note || application.applicant_username || '维修人员'}`,
            dispatch_mode: 'hall_takeover',
          }),
        })
      }
      await options.fetchOrders()
    } catch (e: any) {
      options.fetchError.value = e.message || '处理工单大厅申请失败'
    } finally {
      options.actionLoading.value = null
    }
  }

  async function rejectHallApplication(entry: any, application: any) {
    options.actionLoading.value = hallActionKey(entry.id, application.id, 'reject')
    try {
      const applicantName = application.applicant_username || '该维修人员'
      const defaultReason = `${applicantName}当前不纳入本次处理`
      const reason = window.prompt('请输入驳回原因', defaultReason)
      if (reason === null) {
        options.actionLoading.value = null
        return
      }
      await apiFetch(`/api/dispatch-hall/applications/${application.id}/reject`, {
        method: 'POST',
        body: JSON.stringify({
          note: reason.trim() || defaultReason,
        }),
      })
      await options.fetchOrders()
    } catch (e: any) {
      options.fetchError.value = e.message || '驳回工单大厅申请失败'
    } finally {
      options.actionLoading.value = null
    }
  }

  async function closeHallEntry(entry: any) {
    options.actionLoading.value = hallActionKey(entry.id, '', 'close')
    try {
      await apiFetch(`/api/dispatch-hall/${entry.id}/close`, {
        method: 'POST',
        body: JSON.stringify({
          note: '当前共享事项已结束',
        }),
      })
      options.hallEntries.value = options.hallEntries.value.filter((item) => item.id !== entry.id)
    } catch (e: any) {
      options.fetchError.value = e.message || '关闭共享事项失败'
    } finally {
      options.actionLoading.value = null
    }
  }

  async function openHallReassignSuggestion(entry: any) {
    if (!entry.work_order?.ticket_id || !entry.source_dispatch?.id) {
      options.fetchError.value = '当前共享事项缺少改派信息'
      return
    }
    options.actionLoading.value = hallActionKey(entry.id, '', 'suggest')
    try {
      const data = await apiFetch<any>(`/api/work-orders/${entry.work_order.ticket_id}/dispatch-candidates`)
      options.dispatchPanel.value = {
        visible: true,
        mode: 'reassign',
        ticketId: entry.work_order.ticket_id,
        dispatchId: entry.source_dispatch.id,
        requirement: data?.requirement ?? null,
        candidates: data?.candidates ?? [],
      }
      if (!options.dispatchPanel.value.candidates.length) {
        options.fetchError.value = '暂无改派候选人'
        options.closeDispatchPanel()
      }
    } catch (e: any) {
      options.fetchError.value = e.message || '改派候选人加载失败'
    } finally {
      options.actionLoading.value = null
    }
  }

  async function nudgeHallOwner(entry: any) {
    if (!entry.source_dispatch?.id) {
      options.fetchError.value = '当前责任人不存在'
      return
    }
    options.actionLoading.value = hallActionKey(entry.id, '', 'nudge')
    try {
      const message = entry.entry_type === 'takeover_candidate'
        ? '当前工单已超时，请尽快同步最新处理进展并反馈是否需要改派'
        : '当前工单正在等待协同，请尽快同步处理进展'
      await apiFetch(`/api/dispatch-tasks/${entry.source_dispatch.id}/nudge`, {
        method: 'POST',
        body: JSON.stringify({ message }),
      })
      await options.fetchOrders()
    } catch (e: any) {
      options.fetchError.value = e.message || '催办责任人失败'
    } finally {
      options.actionLoading.value = null
    }
  }

  return {
    hallPendingApplicationCount,
    hallSupportCount,
    hallTakeoverCount,
    hallPendingApplications,
    hallEntryTitle,
    hallEntryOwner,
    hallEntryReason,
    hallEntryIssue,
    hallEmptyHint,
    canSuggestHallTakeover,
    canNudgeHallOwner,
    hallActionKey,
    approveHallApplication,
    rejectHallApplication,
    closeHallEntry,
    openHallReassignSuggestion,
    nudgeHallOwner,
  }
}
