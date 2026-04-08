import { computed, ref } from 'vue'
import { apiFetch } from '@/api/http'
import { WORK_ORDER_EMPTY_MESSAGES, type WorkOrderTabKey } from '@/constants/workOrders'

interface UseWorkOrdersDataOptions {
  route: {
    query: Record<string, unknown>
  }
  defaultTab?: WorkOrderTabKey
  onSelectionReset: () => void
  onOrdersLoaded: () => Promise<void>
}

function hallPendingApplications(entry: any): any[] {
  return (entry.applications || []).filter((application: any) => application.status === 'pending')
}

function matchesTab(wo: any, tab: WorkOrderTabKey) {
  if (tab === 'all') return true
  if (tab === 'pending_close') return ['completed', 'false_alarm', 'escalated'].includes(wo.status)
  if (tab === 'closed') return wo.status === 'closed'
  return wo.status === tab
}

function currentExecutionStatus(wo: any) {
  return wo.current_dispatch?.execution_status || wo.execution_status || ''
}

function currentSlaStatus(wo: any) {
  return wo.current_dispatch?.sla_status || wo.sla_status || ''
}

export function useWorkOrdersData(options: UseWorkOrdersDataOptions) {
  const loading = ref(false)
  const fetchError = ref('')
  const allOrders = ref<any[]>([])
  const hallEntries = ref<any[]>([])
  const activeTab = ref<WorkOrderTabKey>(options.defaultTab ?? 'pending_dispatch')
  const expandedId = ref<string | null>(null)
  const orderTimelines = ref<Record<string, any>>({})
  const timelineLoadingState = ref<Record<string, boolean>>({})
  const timelineErrorState = ref<Record<string, string>>({})

  const filteredOrders = computed(() => allOrders.value.filter(wo => matchesTab(wo, activeTab.value)))
  const overdueCount = computed(() => allOrders.value.filter(wo => currentExecutionStatus(wo) === 'overdue' || currentSlaStatus(wo) === 'overdue').length)
  const isCurrentTabEmpty = computed(() => activeTab.value === 'shared_hall' ? hallEntries.value.length === 0 : filteredOrders.value.length === 0)
  const emptyMessage = computed(() => WORK_ORDER_EMPTY_MESSAGES[activeTab.value])

  function tabCount(tab: WorkOrderTabKey) {
    if (tab === 'shared_hall') return hallEntries.value.length
    return allOrders.value.filter(wo => matchesTab(wo, tab)).length
  }

  async function fetchHallEntries(focusedHallEntryId = '') {
    const data = await apiFetch<{ hall_entries?: any[] }>(
      '/api/dispatch-hall?status=open&entry_type=support_request,takeover_candidate&include_applications=true&sort_by=ops_priority&page=1&page_size=80',
    )
    hallEntries.value = (data?.hall_entries ?? [])
      .sort((a, b) => {
        if (focusedHallEntryId) {
          if (a.id === focusedHallEntryId) return -1
          if (b.id === focusedHallEntryId) return 1
        }
        const countDiff = hallPendingApplications(b).length - hallPendingApplications(a).length
        if (countDiff !== 0) return countDiff
        if (a.entry_type !== b.entry_type) return a.entry_type === 'takeover_candidate' ? -1 : 1
        return new Date(b.updated_at || b.created_at || 0).getTime() - new Date(a.updated_at || a.created_at || 0).getTime()
      })
  }

  async function fetchOrders() {
    loading.value = true
    fetchError.value = ''
    orderTimelines.value = {}
    timelineLoadingState.value = {}
    timelineErrorState.value = {}
    try {
      if (activeTab.value === 'shared_hall') {
        const hallEntryId = typeof options.route.query.hall_entry_id === 'string' ? options.route.query.hall_entry_id : ''
        await fetchHallEntries(hallEntryId)
        return
      }

      const data = await apiFetch<any>('/api/work-orders')
      allOrders.value = data?.work_orders ?? []
      if (expandedId.value && allOrders.value.some(wo => wo.ticket_id === expandedId.value)) {
        void ensureTimeline(expandedId.value)
      }
      await options.onOrdersLoaded()
    } catch (e: any) {
      fetchError.value = e.message
    } finally {
      loading.value = false
    }
  }

  function switchTab(tab: WorkOrderTabKey) {
    activeTab.value = tab
    expandedId.value = null
    options.onSelectionReset()
    if (tab === 'shared_hall' || allOrders.value.length === 0) {
      void fetchOrders()
    }
  }

  async function toggleExpand(ticketId: string) {
    const nextId = expandedId.value === ticketId ? null : ticketId
    expandedId.value = nextId
    options.onSelectionReset()
    if (nextId) {
      await ensureTimeline(nextId)
    }
  }

  async function ensureTimeline(ticketId: string) {
    if (orderTimelines.value[ticketId] || timelineLoadingState.value[ticketId]) return
    timelineLoadingState.value = { ...timelineLoadingState.value, [ticketId]: true }
    timelineErrorState.value = { ...timelineErrorState.value, [ticketId]: '' }
    try {
      const data = await apiFetch<any>(`/api/work-orders/${ticketId}/timeline`)
      orderTimelines.value = { ...orderTimelines.value, [ticketId]: data }
    } catch (e: any) {
      timelineErrorState.value = {
        ...timelineErrorState.value,
        [ticketId]: e.message || '时间线加载失败',
      }
    } finally {
      timelineLoadingState.value = { ...timelineLoadingState.value, [ticketId]: false }
    }
  }

  function isTimelineLoading(ticketId: string) {
    return Boolean(timelineLoadingState.value[ticketId])
  }

  function timelineError(ticketId: string) {
    return timelineErrorState.value[ticketId] || ''
  }

  return {
    loading,
    fetchError,
    allOrders,
    hallEntries,
    activeTab,
    expandedId,
    orderTimelines,
    filteredOrders,
    overdueCount,
    isCurrentTabEmpty,
    emptyMessage,
    tabCount,
    fetchOrders,
    switchTab,
    toggleExpand,
    ensureTimeline,
    isTimelineLoading,
    timelineError,
  }
}
