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
import WorkOrdersWorkspacePane from '@/components/workorders/WorkOrdersWorkspacePaneEnhanced.vue'
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
  color: #166534;
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
