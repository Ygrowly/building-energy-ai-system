<template>
  <WorkOrdersShell
    :workspace-config="workspaceConfig"
    :workspace-switch-items="workspaceSwitchItems"
    :workspace-mode="workspaceMode"
    :tabs="tabs"
    :active-tab="activeTab"
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
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import WorkOrdersOverlayPane from '@/components/workorders/WorkOrdersOverlayPane.vue'
import WorkOrdersShell from '@/components/workorders/WorkOrdersShell.vue'
import WorkOrdersWorkspacePane from '@/components/workorders/WorkOrdersWorkspacePane.vue'
import { useBatchDispatch } from '@/composables/workorders/useBatchDispatch'
import { useDispatchHallAdmin } from '@/composables/workorders/useDispatchHallAdmin'
import { useWorkOrderActions } from '@/composables/workorders/useWorkOrderActions'
import { useWorkOrderPresentation } from '@/composables/workorders/useWorkOrderPresentation'
import { useWorkOrdersData } from '@/composables/workorders/useWorkOrdersData'
import {
  EXECUTION_LABELS,
  PRIORITY_LABELS,
  STATUS_LABELS,
  WORK_ORDER_WORKSPACE_CONFIG,
  type WorkOrderTabKey,
  type WorkOrderWorkspaceMode,
} from '@/constants/workOrders'
import { cachedApiFetch, peekCachedApi, invalidateCachedApi } from '@/api/cached'
import { useChatStore } from '@/stores/chatStore'
import { useBuildingStore } from '@/stores/buildingStore'
import { useReportExport } from '@/composables/useReportExport'

type Candidate = any

const chatStore = useChatStore()
const buildingStore = useBuildingStore()
const route = useRoute()
const router = useRouter()
const { registerSection, setReportMeta } = useReportExport('workorders')

const actionLoading = ref<string | null>(null)
const rejectingId = ref<string | null>(null)
const rejectReason = ref('')
const actionResult = ref<Record<string, { type: 'success' | 'error'; message: string }>>({})

const dispatchSubmitting = ref<string | null>(null)
const dispatchPanel = ref({
  visible: false,
  mode: 'dispatch' as 'dispatch' | 'reassign',
  ticketId: null as string | null,
  dispatchId: null as string | null,
  requirement: null as any | null,
  candidates: [] as Candidate[],
})
const pendingFocus = ref<{ ticketId: string; action: 'dispatch' | 'reassign' } | null>(null)

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

function switchWorkspace(path: string) {
  if (route.path === path) return
  router.push({ path })
}

async function maybeHandlePendingFocus() {
  if (!pendingFocus.value) return
  const target = allOrders.value.find((item) => item.ticket_id === pendingFocus.value?.ticketId)
  if (!target) return
  const focus = pendingFocus.value
  pendingFocus.value = null
  expandedId.value = focus.ticketId
  await ensureTimeline(focus.ticketId)
  await openDispatchPanel(target, focus.action)
  await router.replace({
    path: route.path,
    query: {
      ...route.query,
      focus_ticket: undefined,
      focus_action: undefined,
    },
  })
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
      status: STATUS_LABELS[wo.status] ?? wo.status,
      execution: executionLabelForOrder(wo),
      assignee: assigneeNameForOrder(wo) || '未派工',
      created_at: formatTime(wo.created_at),
    })),
  })
}, { deep: true })

onMounted(async () => {
  applyRouteTabState()
  if (typeof route.query.focus_ticket === 'string' && (route.query.focus_action === 'dispatch' || route.query.focus_action === 'reassign')) {
    pendingFocus.value = {
      ticketId: route.query.focus_ticket,
      action: route.query.focus_action,
    }
    activeTab.value = 'dispatched'
  }
  await fetchOrders()
})

watch(workspaceMode, async () => {
  applyRouteTabState()
  await fetchOrders()
})
</script>

