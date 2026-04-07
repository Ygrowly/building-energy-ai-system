import { computed, ref, type Ref } from 'vue'
import { apiFetch } from '@/api/http'

type BatchPriority = 'all' | 'high' | 'medium' | 'low'

interface UseBatchDispatchOptions {
  activeTab: Ref<string>
  allOrders: Ref<any[]>
  expandedId: Ref<string | null>
  fetchError: Ref<string>
  fetchOrders: () => Promise<void>
  ensureTimeline: (ticketId: string) => Promise<void>
  openDispatchPanel: (wo: any, mode: 'dispatch' | 'reassign') => Promise<void>
}

interface BatchPreviewResponse {
  recommendations?: Array<{
    ticket_id: string
    chosen_candidate?: { user_id?: string } | null
    selection_reason?: string | null
  }>
  worker_loads?: Array<{
    planned_count: number
    current_active_orders: number
  }>
}

interface BatchApplyResponse {
  failed_count: number
  failed: Array<{
    ticket_id: string
    assigned_to: string
    dispatch_mode?: string
    selection_reason?: string | null
    reason: string
    retryable: boolean
  }>
}

const batchPriorityValues = new Set<string>(['all', 'high', 'medium', 'low'])

export function useBatchDispatch(options: UseBatchDispatchOptions) {
  const batchPreviewLoading = ref(false)
  const batchDispatchApplying = ref(false)
  const batchPanel = ref({
    visible: false,
    preview: null as BatchPreviewResponse | null,
    result: null as BatchApplyResponse | null,
  })
  const batchOptions = ref({
    sampleSize: 10,
    priority: 'all' as BatchPriority,
    maxPerWorker: 2,
  })

  const batchSampleOptions = [5, 10, 15]
  const batchWorkerCapOptions = [1, 2, 3]
  const batchPriorityOptions: Array<{ label: string; value: BatchPriority }> = [
    { label: '全部', value: 'all' },
    { label: '高优先', value: 'high' },
    { label: '中优先', value: 'medium' },
    { label: '低优先', value: 'low' },
  ]

  const batchWorkerLoads = computed(() => (batchPanel.value.preview?.worker_loads || [])
    .filter(item => item.planned_count > 0 || item.current_active_orders > 0)
    .slice(0, 8))
  const retryableBatchFailures = computed(() => (batchPanel.value.result?.failed || []).filter(item => item.retryable))

  function closeBatchDispatchPanel() {
    if (batchDispatchApplying.value) return
    batchPanel.value = {
      visible: false,
      preview: null,
      result: null,
    }
  }

  async function refreshBatchDispatchPreview() {
    batchPreviewLoading.value = true
    try {
      const preview = await apiFetch<BatchPreviewResponse>('/api/work-orders/batch-dispatch-preview?' + new URLSearchParams({
        sample_size: String(batchOptions.value.sampleSize),
        scan_limit: String(Math.max(batchOptions.value.sampleSize * 4, batchOptions.value.sampleSize)),
        min_score: '100',
        min_gap: '10',
        max_per_worker: String(batchOptions.value.maxPerWorker),
        ...(batchOptions.value.priority !== 'all' ? { priority: batchOptions.value.priority } : {}),
      }).toString())
      batchPanel.value = {
        visible: true,
        preview,
        result: null,
      }
    } catch (e: any) {
      options.fetchError.value = e.message || '批量推荐加载失败'
      closeBatchDispatchPanel()
    } finally {
      batchPreviewLoading.value = false
    }
  }

  async function openBatchDispatchPanel() {
    options.activeTab.value = 'pending_dispatch'
    batchPanel.value = {
      visible: true,
      preview: null,
      result: null,
    }
    await refreshBatchDispatchPreview()
  }

  async function selectBatchSampleSize(size: number) {
    if (batchOptions.value.sampleSize === size) return
    batchOptions.value.sampleSize = size
    if (batchPanel.value.visible) await refreshBatchDispatchPreview()
  }

  async function selectBatchPriority(priority: string) {
    if (!batchPriorityValues.has(priority)) return
    if (batchOptions.value.priority === priority) return
    batchOptions.value.priority = priority as BatchPriority
    if (batchPanel.value.visible) await refreshBatchDispatchPreview()
  }

  async function selectBatchWorkerCap(cap: number) {
    if (batchOptions.value.maxPerWorker === cap) return
    batchOptions.value.maxPerWorker = cap
    if (batchPanel.value.visible) await refreshBatchDispatchPreview()
  }

  async function confirmBatchDispatch() {
    const recommendations = batchPanel.value.preview?.recommendations || []
    if (!recommendations.length) return
    batchDispatchApplying.value = true
    try {
      const response = await apiFetch<BatchApplyResponse>('/api/work-orders/batch-dispatch', {
        method: 'POST',
        body: JSON.stringify({
          items: recommendations
            .filter(item => item.chosen_candidate?.user_id)
            .map(item => ({
              ticket_id: item.ticket_id,
              assigned_to: item.chosen_candidate!.user_id,
              dispatch_mode: 'assisted',
              selection_reason: item.selection_reason,
            })),
        }),
      })
      await options.fetchOrders()
      await refreshBatchDispatchPreview()
      batchPanel.value = {
        ...batchPanel.value,
        visible: true,
        result: response,
      }
      if (response.failed_count === 0) {
        closeBatchDispatchPanel()
      }
    } catch (e: any) {
      options.fetchError.value = e.message || '批量派工失败'
    } finally {
      batchDispatchApplying.value = false
    }
  }

  async function retryBatchFailedItems(ticketId?: string) {
    const failedItems = ticketId
      ? retryableBatchFailures.value.filter(item => item.ticket_id === ticketId)
      : retryableBatchFailures.value
    if (!failedItems.length) return
    batchDispatchApplying.value = true
    try {
      const response = await apiFetch<BatchApplyResponse>('/api/work-orders/batch-dispatch', {
        method: 'POST',
        body: JSON.stringify({
          items: failedItems.map(item => ({
            ticket_id: item.ticket_id,
            assigned_to: item.assigned_to,
            dispatch_mode: item.dispatch_mode || 'assisted',
            selection_reason: item.selection_reason || item.reason,
          })),
        }),
      })
      await options.fetchOrders()
      await refreshBatchDispatchPreview()
      batchPanel.value = {
        ...batchPanel.value,
        visible: true,
        result: response,
      }
      if (response.failed_count === 0) {
        closeBatchDispatchPanel()
      }
    } catch (e: any) {
      options.fetchError.value = e.message || '失败项重试失败'
    } finally {
      batchDispatchApplying.value = false
    }
  }

  async function reviewBatchFailedItem(ticketId: string) {
    let target = options.allOrders.value.find(item => item.ticket_id === ticketId)
    if (!target) {
      await options.fetchOrders()
      target = options.allOrders.value.find(item => item.ticket_id === ticketId)
    }
    if (!target) return
    options.activeTab.value = 'pending_dispatch'
    options.expandedId.value = ticketId
    closeBatchDispatchPanel()
    try {
      await options.ensureTimeline(ticketId)
      await options.openDispatchPanel(target, 'dispatch')
    } catch (e: any) {
      options.fetchError.value = e.message || '人工复核打开失败'
    }
  }

  function shiftLabel(status?: string | null) {
    const labels: Record<string, string> = {
      on_duty: '值班中',
      standby: '待命',
      off_duty: '离岗',
    }
    return labels[status || ''] || '值班中'
  }

  return {
    batchPanel,
    batchOptions,
    batchPreviewLoading,
    batchDispatchApplying,
    batchSampleOptions,
    batchWorkerCapOptions,
    batchPriorityOptions,
    batchWorkerLoads,
    retryableBatchFailures,
    closeBatchDispatchPanel,
    refreshBatchDispatchPreview,
    openBatchDispatchPanel,
    selectBatchSampleSize,
    selectBatchPriority,
    selectBatchWorkerCap,
    confirmBatchDispatch,
    retryBatchFailedItems,
    reviewBatchFailedItem,
    shiftLabel,
  }
}
