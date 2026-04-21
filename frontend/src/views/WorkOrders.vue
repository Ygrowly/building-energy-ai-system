<template>
  <WorkOrdersShell
    :workspace-config="workspaceConfig"
    :workspace-switch-items="workspaceSwitchItems"
    :workspace-mode="workspaceMode"
    :tabs="tabs"
    :active-tab="activeTab"
    :auto-dispatch-review-status="autoDispatchReviewStatus"
    :loading="loading"
    :batch-preview-loading="batchPreviewLoading"
    :all-orders-count="allOrders.length"
    :hall-entries-count="hallEntries.length"
    :overdue-count="overdueCount"
    :hall-support-count="hallSupportCount"
    :hall-takeover-count="hallTakeoverCount"
    :hall-pending-application-count="hallPendingApplicationCount"
    :fetch-error="fetchError"
    :is-current-tab-empty="isCurrentTabEmpty"
    :empty-message="emptyMessage"
    :tab-count="tabCount"
    @switch-workspace="switchWorkspace"
    @switch-tab="switchTab"
    @switch-auto-dispatch-review-status="switchAutoDispatchReviewStatus"
    @open-batch-dispatch="openBatchDispatchPanel"
    @refresh="fetchOrders"
  >
    <WorkOrdersWorkspacePane
      :workspace-mode="workspaceMode"
      :main-pane-props="mainPaneProps"
      @approve="approveHallApplication"
      @reject="rejectHallApplication"
      @suggest="openHallReassignSuggestion"
      @nudge="nudgeHallOwner"
      @close-entry="closeHallEntry"
      @toggle-expand="toggleExpand"
      @run-action="runAction"
      @start-reject="startReject"
      @update-reject-reason="(reason) => { rejectReason = reason }"
      @cancel-reject="cancelReject"
    />

    <template #overlays>
      <WorkOrdersOverlayPane
        :dispatch-panel="dispatchPanel"
        :dispatch-submitting="dispatchSubmitting"
        :batch-panel="batchPanel"
        :batch-preview-loading="batchPreviewLoading"
        :batch-dispatch-applying="batchDispatchApplying"
        :batch-sample-options="batchSampleOptions"
        :batch-worker-cap-options="batchWorkerCapOptions"
        :batch-priority-options="batchPriorityOptions"
        :batch-options="batchOptions"
        :batch-worker-loads="batchWorkerLoads"
        :retryable-batch-failures="retryableBatchFailures"
        :priority-labels="PRIORITY_LABELS"
        :status-labels="STATUS_LABELS"
        :building-name="buildingName"
        :shift-label="shiftLabel"
        @close-dispatch="closeDispatchPanel"
        @confirm-candidate="confirmDispatchCandidate"
        @close-batch="closeBatchDispatchPanel"
        @refresh-preview="refreshBatchDispatchPreview"
        @select-sample-size="selectBatchSampleSize"
        @select-priority="selectBatchPriority"
        @select-worker-cap="selectBatchWorkerCap"
        @retry-failed="retryBatchFailedItems"
        @review-failed="reviewBatchFailedItem"
        @confirm-dispatch="confirmBatchDispatch"
      />
    </template>
  </WorkOrdersShell>
</template>

<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import WorkOrdersOverlayPane from '@/components/workorders/WorkOrdersOverlayPane.vue'
import WorkOrdersShell from '@/components/workorders/WorkOrdersShell.vue'
import WorkOrdersWorkspacePane from '@/components/workorders/WorkOrdersWorkspacePane.vue'
import { useBatchDispatch } from '@/composables/workorders/useBatchDispatch'
import { useDispatchHallAdmin } from '@/composables/workorders/useDispatchHallAdmin'
import { useWorkOrderActions } from '@/composables/workorders/useWorkOrderActions'
import { useWorkOrderPresentation } from '@/composables/workorders/useWorkOrderPresentationUi'
import { useWorkOrdersData } from '@/composables/workorders/useWorkOrdersData'
import {
  EXECUTION_LABELS,
  PRIORITY_LABELS,
  STATUS_LABELS,
  WORK_ORDER_WORKSPACE_CONFIG,
  type WorkOrderTabKey,
  type WorkOrderWorkspaceMode,
} from '@/constants/workOrders'
import { apiFetch } from '@/api/http'
import { cachedApiFetch, peekCachedApi, invalidateCachedApi } from '@/api/cached'
import { useChatStore } from '@/stores/chatStore'
import { useBuildingStore } from '@/stores/buildingStore'
import { useReportExport } from '@/composables/useReportExport'

type Candidate = any
type PendingFocus = { ticketId: string; action: 'expand' | 'dispatch' | 'reassign' }
type AutoDispatchInsightFilters = Record<string, string>
type AutoReassignShadowFilters = Record<string, string>
type AutoDispatchRunHealthFilters = Record<string, string>
type WorkOrderOperationInsightFilters = Record<string, string>

const chatStore = useChatStore()
const buildingStore = useBuildingStore()
const route = useRoute()
const router = useRouter()
const { registerSection, setReportMeta } = useReportExport('workorders', {
  activateScopePrefixes: ['workorders'],
})

const actionLoading = ref<string | null>(null)
const rejectingId = ref<string | null>(null)
const rejectReason = ref('')
const actionResult = ref<Record<string, { type: 'success' | 'error'; message: string }>>({})
const workOrderOperationInsights = ref<any | null>(null)
const workOrderOperationInsightLoading = ref(false)
const workOrderOperationInsightError = ref('')
const autoDispatchInsights = ref<any | null>(null)
const autoDispatchInsightLoading = ref(false)
const autoDispatchInsightError = ref('')
const autoDispatchInsightExplanation = ref<any | null>(null)
const autoDispatchInsightExplanationSource = ref('')
const autoDispatchInsightQuestion = ref('请解释当前自动派工和大厅兜底是否稳定')
const autoDispatchInsightExplainLoading = ref(false)
const autoDispatchInsightExplainError = ref('')
const autoReassignShadowInsights = ref<any | null>(null)
const autoReassignShadowInsightLoading = ref(false)
const autoReassignShadowInsightError = ref('')
const autoDispatchRunHealthInsights = ref<any | null>(null)
const autoDispatchRunHealthLoading = ref(false)
const autoDispatchRunHealthError = ref('')

function localDateInput(date: Date) {
  const local = new Date(date.getTime() - date.getTimezoneOffset() * 60000)
  return local.toISOString().slice(0, 10)
}

const today = new Date()
const sevenDaysAgo = new Date(today)
sevenDaysAgo.setDate(today.getDate() - 6)
const autoDispatchInsightFilters = ref<AutoDispatchInsightFilters>({
  date_from: localDateInput(sevenDaysAgo),
  date_to: localDateInput(today),
  building_id: '',
  priority: '',
  required_skill: '',
  dispatch_mode: '',
})
const workOrderOperationInsightFilters = ref<WorkOrderOperationInsightFilters>({
  status: '',
  dispatch_status: '',
  timeout_level: '',
})
const autoReassignShadowInsightFilters = ref<AutoReassignShadowFilters>({
  trigger_reason: '',
  eligible: '',
  current_dispatch_status: '',
})
const autoDispatchRunHealthFilters = ref<AutoDispatchRunHealthFilters>({
  trigger_source: '',
  slow_threshold_ms: '8000',
})

const autoDispatchInsightSkillOptions = [
  { label: '暖通 hvac', value: 'hvac' },
  { label: '给排水 plumbing', value: 'plumbing' },
  { label: '电气 electrical', value: 'electrical' },
  { label: '自控 controls', value: 'controls' },
  { label: '巡检 inspection', value: 'inspection' },
]

const dispatchSubmitting = ref<string | null>(null)
const dispatchPanel = ref({
  visible: false,
  mode: 'dispatch' as 'dispatch' | 'reassign',
  ticketId: null as string | null,
  dispatchId: null as string | null,
  requirement: null as any | null,
  candidates: [] as Candidate[],
})
const pendingFocus = ref<PendingFocus | null>(null)
const suppressRouteQuerySync = ref(false)

const workspaceSwitchItems: Array<{ mode: WorkOrderWorkspaceMode; label: string; icon: string; path: string }> = [
  { mode: 'all', label: '总览', icon: 'mdi:view-dashboard-outline', path: '/workorders' },
  { mode: 'review', label: '工单审阅', icon: 'mdi:clipboard-check-outline', path: '/workorders/review' },
  { mode: 'dispatch', label: '派工中心', icon: 'mdi:account-hard-hat-outline', path: '/workorders/dispatch' },
  { mode: 'tracking', label: '执行跟踪', icon: 'mdi:timeline-check-outline', path: '/workorders/tracking' },
]

const workspaceMode = computed<WorkOrderWorkspaceMode>(() => {
  const rawMode = route.meta.workOrderMode
  if (typeof rawMode === 'string' && rawMode in WORK_ORDER_WORKSPACE_CONFIG) {
    return rawMode as WorkOrderWorkspaceMode
  }
  return 'all'
})
const workspaceConfig = computed(() => WORK_ORDER_WORKSPACE_CONFIG[workspaceMode.value])
const tabs = computed(() => workspaceConfig.value.tabs)

const {
  loading,
  fetchError,
  allOrders,
  autoDispatchReviewOrders,
  autoDispatchReviewStatus,
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
  switchAutoDispatchReviewStatus,
  toggleExpand,
  ensureTimeline,
  isTimelineLoading,
  timelineError,
} = useWorkOrdersData({
  route,
  defaultTab: workspaceConfig.value.defaultTab,
  onSelectionReset: cancelReject,
  onOrdersLoaded: maybeHandlePendingFocus,
})

const {
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
} = useWorkOrderPresentation({
  orderTimelines,
  statusLabels: STATUS_LABELS,
  executionLabels: EXECUTION_LABELS,
  getBuildingName: (id) => buildingStore.getBuildingName(id),
})

const {
  runAction,
  openDispatchPanel,
  closeDispatchPanel,
  confirmDispatchCandidate,
  actionsForOrder,
} = useWorkOrderActions({
  currentSessionId: () => chatStore.currentSessionId,
  rejectReason,
  actionLoading,
  actionResult,
  dispatchPanel,
  dispatchSubmitting,
  fetchOrders,
  cancelReject,
  currentDispatchForOrder,
})

const {
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
} = useBatchDispatch({
  activeTab,
  allOrders,
  expandedId,
  fetchError,
  fetchOrders,
  ensureTimeline,
  openDispatchPanel,
})

const {
  hallPendingApplicationCount,
  hallSupportCount,
  hallTakeoverCount,
  hallPendingApplications,
  hallEntryTitle,
  hallEntryOwner,
  hallEntryReason,
  hallEmptyHint,
  canSuggestHallTakeover,
  canNudgeHallOwner,
  hallActionKey,
  approveHallApplication,
  rejectHallApplication,
  closeHallEntry,
  openHallReassignSuggestion,
  nudgeHallOwner,
} = useDispatchHallAdmin({
  hallEntries,
  actionLoading,
  fetchError,
  dispatchPanel,
  fetchOrders,
  closeDispatchPanel,
})

const autoDispatchInsightBuildingOptions = computed(() => (
  buildingStore.buildings.map(item => ({
    value: item.building_id,
    label: buildingStore.getBuildingName(item.building_id),
  }))
))

function buildAutoDispatchInsightQuery() {
  const params = new URLSearchParams()
  Object.entries(autoDispatchInsightFilters.value).forEach(([key, value]) => {
    if (value) params.set(key, value)
  })
  params.set('page', '1')
  params.set('page_size', '20')
  return params.toString()
}

function buildWorkOrderOperationInsightQuery() {
  const params = new URLSearchParams()
  const sharedFilters = autoDispatchInsightFilters.value
  const sharedKeys = ['date_from', 'date_to', 'building_id', 'priority', 'required_skill'] as const
  sharedKeys.forEach((key) => {
    const value = sharedFilters[key]
    if (value) params.set(key, value)
  })
  Object.entries(workOrderOperationInsightFilters.value).forEach(([key, value]) => {
    if (value) params.set(key, value)
  })
  params.set('page', '1')
  params.set('page_size', '20')
  return params.toString()
}

function buildAutoReassignShadowInsightQuery() {
  const params = new URLSearchParams()
  Object.entries(autoDispatchInsightFilters.value).forEach(([key, value]) => {
    if (key === 'dispatch_mode') return
    if (value) params.set(key, value)
  })
  Object.entries(autoReassignShadowInsightFilters.value).forEach(([key, value]) => {
    if (value) params.set(key, value)
  })
  params.set('page', '1')
  params.set('page_size', '20')
  return params.toString()
}

function buildAutoDispatchRunHealthQuery() {
  const params = new URLSearchParams()
  const { date_from, date_to } = autoDispatchInsightFilters.value
  if (date_from) params.set('date_from', date_from)
  if (date_to) params.set('date_to', date_to)
  Object.entries(autoDispatchRunHealthFilters.value).forEach(([key, value]) => {
    if (value) params.set(key, value)
  })
  params.set('recent_limit', '12')
  params.set('slow_limit', '10')
  return params.toString()
}

async function fetchWorkOrderOperationInsights() {
  workOrderOperationInsightLoading.value = true
  workOrderOperationInsightError.value = ''
  try {
    workOrderOperationInsights.value = await apiFetch<any>(
      `/api/work-order-insights/operations?${buildWorkOrderOperationInsightQuery()}`,
    )
  } catch (e: any) {
    workOrderOperationInsightError.value = e.message || '通用运营洞察加载失败'
  } finally {
    workOrderOperationInsightLoading.value = false
  }
}

async function fetchAutoDispatchInsights() {
  autoDispatchInsightLoading.value = true
  autoDispatchInsightError.value = ''
  try {
    autoDispatchInsights.value = await apiFetch<any>(
      `/api/work-order-insights/auto-dispatch-operations?${buildAutoDispatchInsightQuery()}`,
    )
  } catch (e: any) {
    autoDispatchInsightError.value = e.message || '自动派工洞察加载失败'
  } finally {
    autoDispatchInsightLoading.value = false
  }
}

async function fetchAutoReassignShadowInsights() {
  autoReassignShadowInsightLoading.value = true
  autoReassignShadowInsightError.value = ''
  try {
    autoReassignShadowInsights.value = await apiFetch<any>(
      `/api/work-order-insights/auto-reassign-shadow?${buildAutoReassignShadowInsightQuery()}`,
    )
  } catch (e: any) {
    autoReassignShadowInsightError.value = e.message || '自动重派影子洞察加载失败'
  } finally {
    autoReassignShadowInsightLoading.value = false
  }
}

async function fetchAutoDispatchRunHealthInsights() {
  autoDispatchRunHealthLoading.value = true
  autoDispatchRunHealthError.value = ''
  try {
    autoDispatchRunHealthInsights.value = await apiFetch<any>(
      `/api/work-order-insights/auto-dispatch-run-health?${buildAutoDispatchRunHealthQuery()}`,
    )
  } catch (e: any) {
    autoDispatchRunHealthError.value = e.message || '自动调度运行健康加载失败'
  } finally {
    autoDispatchRunHealthLoading.value = false
  }
}

function buildAutoDispatchInsightRequestBody() {
  const body: Record<string, any> = {
    question: autoDispatchInsightQuestion.value,
    use_llm: true,
  }
  Object.entries(autoDispatchInsightFilters.value).forEach(([key, value]) => {
    if (value) body[key] = value
  })
  return body
}

async function fetchAutoDispatchInsightExplanation() {
  autoDispatchInsightExplainLoading.value = true
  autoDispatchInsightExplainError.value = ''
  try {
    const data = await apiFetch<any>('/api/work-order-insights/auto-dispatch-operations/explain', {
      method: 'POST',
      body: JSON.stringify(buildAutoDispatchInsightRequestBody()),
    })
    autoDispatchInsightExplanation.value = data?.explanation ?? null
    autoDispatchInsightExplanationSource.value = data?.source ?? ''
    if (data?.insights) {
      autoDispatchInsights.value = data.insights
    }
  } catch (e: any) {
    autoDispatchInsightExplainError.value = e.message || '自动派工解读生成失败'
  } finally {
    autoDispatchInsightExplainLoading.value = false
  }
}

function updateAutoDispatchInsightFilter(key: string, value: string) {
  autoDispatchInsightFilters.value = {
    ...autoDispatchInsightFilters.value,
    [key]: value,
  }
  autoDispatchInsightExplanation.value = null
  autoDispatchInsightExplanationSource.value = ''
  void fetchAutoDispatchInsights()
  void fetchWorkOrderOperationInsights()
  void fetchAutoReassignShadowInsights()
  void fetchAutoDispatchRunHealthInsights()
}

function updateAutoDispatchInsightQuestion(value: string) {
  autoDispatchInsightQuestion.value = value
}

function updateAutoReassignShadowInsightFilter(key: string, value: string) {
  autoReassignShadowInsightFilters.value = {
    ...autoReassignShadowInsightFilters.value,
    [key]: value,
  }
  void fetchAutoReassignShadowInsights()
}

function updateWorkOrderOperationInsightFilter(key: string, value: string) {
  workOrderOperationInsightFilters.value = {
    ...workOrderOperationInsightFilters.value,
    [key]: value,
  }
  void fetchWorkOrderOperationInsights()
}

function updateAutoDispatchRunHealthFilter(key: string, value: string) {
  autoDispatchRunHealthFilters.value = {
    ...autoDispatchRunHealthFilters.value,
    [key]: value,
  }
  void fetchAutoDispatchRunHealthInsights()
}

const mainPaneProps = computed(() => ({
  loading: loading.value,
  activeTab: activeTab.value,
  hallEntries: hallEntries.value,
  filteredOrders: filteredOrders.value,
  expandedId: expandedId.value,
  actionLoading: actionLoading.value,
  rejectingId: rejectingId.value,
  rejectReason: rejectReason.value,
  actionResult: actionResult.value,
  priorityLabels: PRIORITY_LABELS,
  statusLabels: STATUS_LABELS,
  executionLabels: EXECUTION_LABELS,
  formatTime,
  buildingName,
  hallPendingApplications,
  hallEntryTitle,
  hallEntryOwner,
  hallEntryReason,
  hallEmptyHint,
  canSuggestHallTakeover,
  canNudgeHallOwner,
  hallActionKey,
  statusCardClass,
  statusChipClass,
  executionChipClass,
  executionStatusForOrder,
  detailRows,
  timelineRows,
  isTimelineLoading,
  timelineError,
  actionsForOrder,
  workOrderOperationInsights: workOrderOperationInsights.value,
  workOrderOperationInsightFilters: workOrderOperationInsightFilters.value,
  workOrderOperationInsightLoading: workOrderOperationInsightLoading.value,
  workOrderOperationInsightError: workOrderOperationInsightError.value,
  updateWorkOrderOperationInsightFilter,
  fetchWorkOrderOperationInsights,
  autoDispatchInsights: autoDispatchInsights.value,
  autoDispatchInsightFilters: autoDispatchInsightFilters.value,
  autoDispatchInsightLoading: autoDispatchInsightLoading.value,
  autoDispatchInsightError: autoDispatchInsightError.value,
  autoDispatchInsightBuildingOptions: autoDispatchInsightBuildingOptions.value,
  autoDispatchInsightSkillOptions,
  updateAutoDispatchInsightFilter,
  fetchAutoDispatchInsights,
  autoDispatchInsightExplanation: autoDispatchInsightExplanation.value,
  autoDispatchInsightExplanationSource: autoDispatchInsightExplanationSource.value,
  autoDispatchInsightQuestion: autoDispatchInsightQuestion.value,
  autoDispatchInsightExplainLoading: autoDispatchInsightExplainLoading.value,
  autoDispatchInsightExplainError: autoDispatchInsightExplainError.value,
  updateAutoDispatchInsightQuestion,
  fetchAutoDispatchInsightExplanation,
  autoReassignShadowInsights: autoReassignShadowInsights.value,
  autoReassignShadowInsightFilters: autoReassignShadowInsightFilters.value,
  autoReassignShadowInsightLoading: autoReassignShadowInsightLoading.value,
  autoReassignShadowInsightError: autoReassignShadowInsightError.value,
  updateAutoReassignShadowInsightFilter,
  fetchAutoReassignShadowInsights,
  autoDispatchRunHealthInsights: autoDispatchRunHealthInsights.value,
  autoDispatchRunHealthFilters: autoDispatchRunHealthFilters.value,
  autoDispatchRunHealthLoading: autoDispatchRunHealthLoading.value,
  autoDispatchRunHealthError: autoDispatchRunHealthError.value,
  updateAutoDispatchRunHealthFilter,
  fetchAutoDispatchRunHealthInsights,
}))

function startReject(ticketId: string) {
  rejectingId.value = ticketId
  rejectReason.value = ''
}

function cancelReject() {
  rejectingId.value = null
  rejectReason.value = ''
}

function isVisibleTab(tab: unknown): tab is WorkOrderTabKey {
  return typeof tab === 'string' && workspaceConfig.value.tabs.some((item) => item.value === tab)
}

function applyRouteTabState() {
  if (isVisibleTab(route.query.active_tab)) {
    activeTab.value = route.query.active_tab
  } else if (!isVisibleTab(activeTab.value)) {
    activeTab.value = workspaceConfig.value.defaultTab
  }
}

function syncPendingFocusFromRoute() {
  if (typeof route.query.focus_ticket !== 'string') {
    pendingFocus.value = null
    return
  }

  if (route.query.focus_action === 'dispatch' || route.query.focus_action === 'reassign') {
    pendingFocus.value = {
      ticketId: route.query.focus_ticket,
      action: route.query.focus_action,
    }
    activeTab.value = 'dispatched'
    return
  }

  pendingFocus.value = {
    ticketId: route.query.focus_ticket,
    action: 'expand',
  }
  if (isVisibleTab('all')) {
    activeTab.value = 'all'
  }
}

function switchWorkspace(path: string) {
  if (route.path === path) return
  router.push({ path })
}

async function maybeHandlePendingFocus() {
  if (!pendingFocus.value) return
  const target = [...allOrders.value, ...autoDispatchReviewOrders.value]
    .find((item) => item.ticket_id === pendingFocus.value?.ticketId)
  if (!target) return
  const focus = pendingFocus.value
  pendingFocus.value = null
  const targetTab = tabForWorkOrder(target)
  if (targetTab && isVisibleTab(targetTab)) {
    activeTab.value = targetTab
  }
  expandedId.value = focus.ticketId
  if (focus.action === 'expand') {
    void ensureTimeline(focus.ticketId)
  } else {
    await ensureTimeline(focus.ticketId)
  }
  await nextTick()
  document.getElementById(`work-order-${focus.ticketId}`)?.scrollIntoView({
    behavior: 'smooth',
    block: 'center',
  })
  if (focus.action !== 'expand') {
    if (focus.action === 'dispatch' || focus.action === 'reassign') {
    await openDispatchPanel(target, focus.action)
    }
  suppressRouteQuerySync.value = true
  await router.replace({
      path: route.path,
      query: {
        ...route.query,
        focus_ticket: undefined,
        focus_action: undefined,
      },
    })
  }
}

function tabForWorkOrder(wo: any): WorkOrderTabKey | null {
  if (wo.auto_dispatch_review_state?.status === 'pending') return 'auto_dispatch_review'
  if (wo.status === 'closed') return 'closed'
  if (wo.work_result || ['completed', 'false_alarm', 'escalated'].includes(wo.status)) return 'pending_close'
  if (wo.approval_status === 'pending_review') return 'pending_review'
  if (wo.approval_status === 'rejected') return 'auto_rejected'
  if (wo.dispatch_summary_status === 'pending_dispatch') return 'pending_dispatch'
  if (['assigned', 'accepted', 'arrived', 'processing', 'waiting_support', 'overdue'].includes(wo.dispatch_summary_status)) return 'dispatched'
  if (['pending_review', 'pending_dispatch', 'auto_rejected', 'dispatched'].includes(wo.status)) {
    return wo.status
  }
  return null
}

function routeFocusFromQuery(): PendingFocus | null {
  if (
    typeof route.query.focus_ticket !== 'string'
    || (
      route.query.focus_action !== 'expand'
      && route.query.focus_action !== 'dispatch'
      && route.query.focus_action !== 'reassign'
      && route.query.focus_action != null
    )
  ) {
    return null
  }
  const action: PendingFocus['action'] = (
    route.query.focus_action === 'dispatch' || route.query.focus_action === 'reassign'
      ? route.query.focus_action
      : 'expand'
  )
  return {
    ticketId: route.query.focus_ticket,
    action,
  }
}

function captureRouteFocus() {
  const focus = routeFocusFromQuery()
  if (focus) {
    pendingFocus.value = focus
  }
}

watch(allOrders, (orders) => {
  if (!orders.length) return
  setReportMeta({ title: '工单管理报表' })
  registerSection({
    id: 'wo-kpi',
    title: '工单概览',
    type: 'kpi',
    order: 10,
    kpis: [
      { label: '工单总数', value: String(orders.length) },
      { label: '待AI审阅', value: String(tabCount('pending_review')) },
      { label: '待派工', value: String(tabCount('pending_dispatch')) },
      { label: '执行中', value: String(tabCount('dispatched')) },
    ],
  })
  registerSection({
    id: 'wo-table',
    title: '工单列表',
    type: 'table',
    order: 20,
    columns: [
      { key: 'ticket_id', label: '工单 ID', align: 'left' },
      { key: 'building', label: '楼宇', align: 'left' },
      { key: 'priority', label: '优先级', align: 'left' },
      { key: 'status', label: '主状态', align: 'left' },
      { key: 'execution', label: '执行状态', align: 'left' },
      { key: 'assignee', label: '责任人', align: 'left' },
      { key: 'created_at', label: '创建时间', align: 'left' },
    ],
    rows: orders.map(wo => ({
      ticket_id: wo.ticket_id,
      building: buildingName(wo.building_id),
      priority: PRIORITY_LABELS[wo.priority] ?? wo.priority ?? '—',
      status: statusLabelForOrder(wo),
      execution: executionLabelForOrder(wo),
      assignee: assigneeNameForOrder(wo) || '未派工',
      created_at: formatTime(wo.created_at),
    })),
  })
}, { deep: true })

onMounted(async () => {
  void buildingStore.fetchBuildings()
  applyRouteTabState()
  captureRouteFocus()
  syncPendingFocusFromRoute()
  await fetchOrders()
  if (activeTab.value === 'auto_dispatch_insights') {
    await fetchWorkOrderOperationInsights()
    await fetchAutoDispatchInsights()
    await fetchAutoReassignShadowInsights()
    await fetchAutoDispatchRunHealthInsights()
  }
})

watch(
  () => [route.query.focus_ticket, route.query.focus_action],
  async () => {
    captureRouteFocus()
    if (!pendingFocus.value) return
    if (!allOrders.value.length) {
      await fetchOrders()
      return
    }
    await maybeHandlePendingFocus()
  },
)

watch(workspaceMode, async () => {
  applyRouteTabState()
  captureRouteFocus()
  await fetchOrders()
})

watch(
  () => [
    route.query.active_tab,
    route.query.focus_ticket,
    route.query.focus_action,
    route.query.hall_entry_id,
  ] as const,
  async () => {
    if (suppressRouteQuerySync.value) {
      suppressRouteQuerySync.value = false
      return
    }
    applyRouteTabState()
    syncPendingFocusFromRoute()
    await fetchOrders()
  },
)
</script>

<style scoped>
.workorders { padding: 24px; }
.page-header {
  margin-bottom: 20px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 18px;
  padding: 14px 16px;
  border: 1px solid rgba(62, 99, 84, 0.18);
  border-radius: 18px;
  background:
    linear-gradient(115deg, rgba(121, 213, 177, 0.16) 0%, rgba(134, 239, 172, 0.16) 42%, rgba(248, 252, 249, 0.96) 100%),
    var(--bg-panel);
  box-shadow: 0 12px 30px rgba(62, 99, 84, 0.08);
}
.header-copy { min-width: 0; }
.page-header h1 {
  font-size: 22px;
  font-weight: 700;
  margin-bottom: 4px;
  display: flex;
  align-items: center;
  gap: 8px;
  color: #0e5328;
}
.subtitle { color: var(--text-secondary); font-size: 13px; }
.workspace-pills {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  flex-shrink: 0;
  padding: 4px;
  border: 1px solid rgba(62, 99, 84, 0.18);
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.78);
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.86);
}
.workspace-pill {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  border: none;
  border-radius: 999px;
  padding: 8px 13px;
  background: transparent;
  color: #4b6358;
  font-size: 12px;
  font-weight: 700;
  white-space: nowrap;
  cursor: pointer;
  transition: all 0.18s ease;
}
.workspace-pill:hover {
  color: #166534;
  background: rgba(34, 197, 94, 0.08);
}
.workspace-pill.active {
  color: #065f46;
  background: linear-gradient(135deg, rgba(34, 197, 94, 0.16), rgba(187, 247, 208, 0.68));
  box-shadow: 0 6px 16px rgba(22, 163, 74, 0.1);
}
.toolbar { display: flex; justify-content: space-between; align-items: center; gap: 16px; margin-bottom: 16px; }
.toolbar-actions { display: flex; align-items: center; gap: 10px; }
.tab-group { display: flex; flex-wrap: wrap; gap: 6px; }
.tab-btn, .refresh-btn, .link-btn { background: none; border: 1px solid var(--border); border-radius: 8px; color: var(--text-secondary); font-size: 13px; padding: 8px 14px; cursor: pointer; transition: all 0.2s; }
.tab-btn { display: flex; align-items: center; gap: 6px; }
.tab-btn.active { background: var(--accent-glow); border-color: var(--border-accent); color: var(--accent); font-weight: 600; }
.refresh-btn.accent { background: var(--accent); border-color: var(--accent); color: white; }
.refresh-btn.inline { padding: 7px 12px; }
.refresh-btn.warn { border-color: rgba(245, 158, 11, 0.24); color: #b45309; background: rgba(245, 158, 11, 0.08); }
.tab-count { background: rgba(59, 130, 246, 0.12); color: var(--accent); border-radius: 999px; padding: 1px 8px; font-size: 11px; }
.summary-strip { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 12px; margin-bottom: 16px; }
.summary-pill { background: var(--bg-panel); border: 1px solid var(--border); border-radius: 12px; padding: 14px 16px; display: flex; flex-direction: column; gap: 4px; }
.summary-pill.warning { border-color: rgba(59, 130, 246, 0.22); }
.summary-pill.active { border-color: rgba(16, 185, 129, 0.22); }
.summary-pill.danger { border-color: rgba(248, 113, 113, 0.22); }
.summary-value { font-size: 22px; font-weight: 700; color: var(--text-primary); }
.summary-label { font-size: 12px; color: var(--text-muted); }
.loading-bar, .error-bar { border-radius: 10px; padding: 12px 16px; font-size: 13px; margin-bottom: 12px; }
.loading-bar { background: var(--accent-glow); border: 1px solid var(--border-accent); color: var(--accent); }
.error-bar { background: rgba(248,113,113,0.08); border: 1px solid rgba(248,113,113,0.24); color: var(--danger); }
.empty-state { display: flex; flex-direction: column; align-items: center; gap: 8px; padding: 100px 0; color: var(--text-muted); }
.empty-sub { font-size: 12px; }

@media (max-width: 1100px) {
  .page-header { align-items: flex-start; flex-direction: column; }
  .workspace-pills { width: 100%; overflow-x: auto; }
}
</style>
