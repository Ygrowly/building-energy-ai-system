<template>
  <view class="page">
    <NavBar title="我的工单" bg-color="#E4EDB8" text-color="#5f7137">
      <template #right>
        <text class="nav-action" @click="loadData">↻</text>
      </template>
    </NavBar>

    <view class="tab-row">
      <view
        v-for="tab in orderTabs"
        :key="tab.value"
        class="tab-item"
        :class="{ active: activeTab === tab.value }"
        @click="activeTab = tab.value"
      >
        <text class="tab-label">{{ tab.label }}</text>
        <text class="tab-count" :class="{ loading: isInitialLoading }">{{ tab.countText }}</text>
      </view>
    </view>

    <scroll-view scroll-y class="list-area">
      <view v-if="loading && !taskCards.length">
        <view v-for="index in 3" :key="index" class="skeleton-card" />
      </view>

      <view
        v-for="card in filteredTaskCards"
        :key="card.key"
        class="workorder-card"
        :class="cardToneClass(card)"
        @click="openDetail(card, activeTab === 'completed')"
      >
        <view class="card-head">
          <view class="ticket-row">
            <text class="ticket-id">{{ shortTicket(card.ticketId) }}</text>
            <text class="copy-btn" @click.stop="copyTicket(card.ticketId)">复制</text>
          </view>
          <text class="status-badge" :class="statusToneClass(card)">{{ statusText(card) }}</text>
        </view>

        <text class="card-title">{{ card.title }}</text>
        <view class="location-row">
          <text class="location-text">{{ card.building }} / {{ card.location }}</text>
          <text class="distance-text">{{ dueText(card) }}</text>
        </view>

        <view v-if="cardFlags(card).length" class="flag-row">
          <text
            v-for="flag in cardFlags(card)"
            :key="`${card.key}:${flag.label}`"
            class="flag-badge"
            :class="flag.tone"
          >{{ flag.label }}</text>
        </view>

        <view class="detail-panel">
          <view class="detail-line">
            <text class="detail-label">工单类型</text>
            <text class="detail-value">{{ typeText(card) }}</text>
          </view>
          <view class="detail-line">
            <text class="detail-label">处理进度</text>
            <text class="detail-value accent" :class="progressToneClass(card)">{{ progressText(card) }}</text>
          </view>
          <view class="detail-line">
            <text class="detail-label">派单时间</text>
            <text class="detail-value">{{ timeText(card) }}</text>
          </view>
          <view v-if="attentionText(card)" class="detail-line">
            <text class="detail-label">重点提示</text>
            <text class="detail-value multiline highlight">{{ attentionText(card) }}</text>
          </view>
          <view class="detail-line">
            <text class="detail-label">建议措施</text>
            <text class="detail-value multiline">{{ noteText(card) }}</text>
          </view>
        </view>

        <view class="action-row" :class="{ triple: canOpenWorkerAiFromCard(card) && activeTab !== 'completed' }">
          <view class="ghost-btn" @click.stop="callContact(card)">联系TA</view>
          <view
            v-if="canOpenWorkerAiFromCard(card) && activeTab !== 'completed'"
            class="ghost-btn"
            @click.stop="openDetail(card)"
          >
            工单详情
          </view>
          <view class="primary-btn" @click.stop="handlePrimaryAction(card, activeTab === 'completed')">
            {{ actionLabel(card) }}
          </view>
        </view>
      </view>

      <view v-if="!loading && !filteredTaskCards.length" class="empty-card">
        <text class="empty-icon">单</text>
        <text class="empty-title">当前分类暂无我的工单</text>
        <text class="empty-subtitle">正式派给我的工单和协同任务会第一时间同步到这里</text>
      </view>

      <view class="worker-tabbar-spacer" />
    </scroll-view>

    <TabBar :tabs="WORKER_TABS" current="workorders" theme="worker" />
  </view>
</template>

<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { onShow } from '@dcloudio/uni-app'
import NavBar from '../../../components/NavBar.vue'
import TabBar from '../../../components/TabBar.vue'
import { useAuthStore } from '../../../stores/auth'
import { incidentApi, type Incident } from '../../../api/incident'
import { workOrderApi, type DispatchHallEntry, type WorkOrder } from '../../../api/workorder'
import { useRouteGuard } from '../../../utils/route-guard'
import { WORKER_ROLES } from '../../../constants/roles'
import { WORKER_TABS } from '../../../constants/tabs'
import { DISPATCH_EXECUTION_STATUS_LABEL } from '../../../constants/status'
import { formatDateTime } from '../../../utils/format'
import { formatBuildingLabel, formatDeviceLabel, formatRuleLabel, formatSystemLabel, sanitizeDisplayText } from '../../../utils/display'
import { getCache, setCache } from '../../../utils/cache'
import { subscribeWorkerOrdersUpdated } from '../../../utils/worker-sync'
import {
  getWorkerDashboardStats,
  getWorkerExecutionStatus,
  getWorkerOrderBucket,
  isWorkerOverdueIncident,
  isWorkerReassignedIncident,
  isWorkerWaitingSupportIncident,
} from '../../../utils/worker-ui'

useRouteGuard(WORKER_ROLES)

type OrderTab = 'in_progress' | 'pending_start' | 'completed'
type WorkerCardFlag = { label: string; tone: 'support' | 'overdue' | 'reassigned' | 'ai' }
type WorkerTaskCard =
  | {
      key: string
      kind: 'incident'
      bucket: OrderTab
      ticketId: string
      title: string
      building: string
      location: string
      incident: Incident
    }
  | {
      key: string
      kind: 'work_order'
      bucket: OrderTab
      ticketId: string
      title: string
      building: string
      location: string
      workOrder: WorkOrder
    }
  | {
      key: string
      kind: 'support'
      bucket: Exclude<OrderTab, 'completed'>
      ticketId: string
      title: string
      building: string
      location: string
      hallEntry: DispatchHallEntry
    }

const incidents = ref<Incident[]>([])
const workOrders = ref<WorkOrder[]>([])
const supportEntries = ref<DispatchHallEntry[]>([])
const loading = ref(false)
const activeTab = ref<OrderTab>('in_progress')
const hasLoadedOnce = ref(false)
const authStore = useAuthStore()
let unsubscribeWorkerSync: (() => void) | null = null
const isInitialLoading = computed(() => (
  loading.value
  && !hasLoadedOnce.value
  && !incidents.value.length
  && !workOrders.value.length
  && !supportEntries.value.length
))

const stats = computed(() => {
  const incidentStats = getWorkerDashboardStats(incidents.value)
  const directOrderStats = getDirectWorkOrderStats(directWorkOrders.value)
  const pendingSupport = visibleSupportEntries.value.filter(entry => entry.status === 'assigned').length
  const activeSupport = visibleSupportEntries.value.filter(entry => entry.status === 'accepted').length
  return {
    ...incidentStats,
    pendingStart: incidentStats.pendingStart + directOrderStats.pendingStart + pendingSupport,
    inProgress: incidentStats.inProgress + directOrderStats.inProgress + activeSupport,
    todayCount: incidentStats.todayCount + directOrderStats.todayCount + visibleSupportEntries.value.length,
    completedCount: incidentStats.completedCount + directOrderStats.completedCount,
  }
})
const orderTabs = computed(() => [
  {
    label: '进行中',
    value: 'in_progress' as const,
    count: stats.value.inProgress,
    countText: isInitialLoading.value ? '...' : String(stats.value.inProgress),
  },
  {
    label: '待开始',
    value: 'pending_start' as const,
    count: stats.value.pendingStart,
    countText: isInitialLoading.value ? '...' : String(stats.value.pendingStart),
  },
  {
    label: '已完成',
    value: 'completed' as const,
    count: stats.value.completedCount,
    countText: isInitialLoading.value ? '...' : String(stats.value.completedCount),
  },
])
const taskCards = computed<WorkerTaskCard[]>(() => {
  const incidentCards = incidents.value.map<WorkerTaskCard>((incident) => ({
    key: `incident:${incident.id}`,
    kind: 'incident',
    bucket: getWorkerOrderBucket(incident),
    ticketId: incident.current_work_order?.ticket_id || incident.incident_id,
    title: incident.summary_text,
    building: formatBuildingLabel(incident.building_id),
    location: formatDeviceLabel(incident.device_id, incident.building_id) || formatSystemLabel(incident.rule_triggered),
    incident,
  }))
  const workOrderCards = directWorkOrders.value.map<WorkerTaskCard>((workOrder) => ({
    key: `work_order:${workOrder.id}`,
    kind: 'work_order',
    bucket: getDirectWorkOrderBucket(workOrder),
    ticketId: workOrder.ticket_id,
    title: sanitizeDisplayText(workOrder.issue_description) || workOrder.ticket_id,
    building: formatBuildingLabel(workOrder.building_id),
    location: formatDeviceLabel(workOrder.device_id, workOrder.building_id) || formatSystemLabel(workOrder.dispatch_profile?.preferred_team_name),
    workOrder,
  }))
  const supportCards = visibleSupportEntries.value.map<WorkerTaskCard>((entry) => {
    const workOrder = entry.work_order
    return {
      key: `support:${entry.id}`,
      kind: 'support',
      bucket: entry.status === 'assigned' ? 'pending_start' : 'in_progress',
      ticketId: workOrder?.ticket_id || entry.id,
      title: sanitizeDisplayText(entry.support_reason || entry.reason || workOrder?.issue_description) || '协同任务待处理',
      building: formatBuildingLabel(workOrder?.building_id),
      location: formatDeviceLabel(workOrder?.device_id, workOrder?.building_id) || '协同现场待确认',
      hallEntry: entry,
    }
  })
  return [...incidentCards, ...workOrderCards, ...supportCards]
})

const filteredTaskCards = computed(() => taskCards.value.filter(item => item.bucket === activeTab.value))
const visibleSupportEntries = computed(() => supportEntries.value.filter(isSupportEntryAssignedToMe))
const directWorkOrders = computed(() => {
  const incidentTickets = new Set(
    incidents.value
      .map(item => item.current_work_order?.ticket_id)
      .filter(Boolean) as string[],
  )
  return workOrders.value.filter(item => item.ticket_id && !incidentTickets.has(item.ticket_id))
})
const WORKER_AI_READY_STATUSES = new Set(['processing', 'waiting_support', 'supporting'])

function keepStartedOrdersVisible() {
  if (activeTab.value !== 'pending_start') return
  const hasPendingStart = taskCards.value.some(item => item.bucket === 'pending_start')
  const hasInProgress = taskCards.value.some(item => item.bucket === 'in_progress')
  if (!hasPendingStart && hasInProgress) {
    activeTab.value = 'in_progress'
  }
}

function isSupportEntryAssignedToMe(entry: DispatchHallEntry) {
  const userId = authStore.user?.id
  if (!userId) return false
  if (!['assigned', 'accepted'].includes(entry.status)) return false
  return entry.assigned_to === userId
}

function getDirectWorkOrderExecutionStatus(workOrder?: WorkOrder | null): string {
  const dispatch = workOrder?.current_dispatch
  if (dispatch?.execution_status) return dispatch.execution_status
  if (workOrder?.execution_status) return workOrder.execution_status
  if (dispatch?.dispatch_status) {
    if (dispatch.sla_status === 'overdue') return 'overdue'
    return dispatch.dispatch_status === 'assigned' ? 'pending_accept' : dispatch.dispatch_status
  }
  if (workOrder?.arrived_at || workOrder?.latest_progress_at) return 'processing'
  if (workOrder?.accepted_at) return 'accepted'
  return 'pending_accept'
}

function isDirectWorkOrderCompleted(workOrder?: WorkOrder | null) {
  return ['completed', 'closed', 'false_alarm', 'escalated'].includes(workOrder?.status || '')
}

function isDirectWorkOrderPendingStart(workOrder?: WorkOrder | null) {
  if (!workOrder || isDirectWorkOrderCompleted(workOrder)) return false
  return getDirectWorkOrderExecutionStatus(workOrder) === 'pending_accept'
}

function isDirectWorkOrderOverdue(workOrder?: WorkOrder | null) {
  if (!workOrder || isDirectWorkOrderCompleted(workOrder)) return false
  return workOrder.current_dispatch?.sla_status === 'overdue'
    || workOrder.sla_status === 'overdue'
    || getDirectWorkOrderExecutionStatus(workOrder) === 'overdue'
}

function isDirectWorkOrderWaitingSupport(workOrder?: WorkOrder | null) {
  if (!workOrder || isDirectWorkOrderCompleted(workOrder)) return false
  return getDirectWorkOrderExecutionStatus(workOrder) === 'waiting_support'
}

function isProcessingStage(value?: string | null) {
  return WORKER_AI_READY_STATUSES.has(String(value || '').toLowerCase())
}

function hasStartedCurrentDispatch(dispatch?: {
  processing_started_at?: string | null
  execution_status?: string | null
  dispatch_status?: string | null
} | null) {
  return Boolean(
    dispatch?.processing_started_at
      || isProcessingStage(dispatch?.execution_status)
      || isProcessingStage(dispatch?.dispatch_status),
  )
}

function hasStartedWorkOrderWithoutDispatch(workOrder?: WorkOrder | null) {
  return Boolean(
    workOrder
      && !workOrder.current_dispatch
      && (
        workOrder.processing_started_at
        || isProcessingStage(workOrder.execution_status)
      ),
  )
}

function canOpenWorkerAiFromCard(card: WorkerTaskCard) {
  if (activeTab.value === 'completed') return false
  if (card.kind === 'support') {
    return card.hallEntry.status === 'accepted'
  }
  if (card.kind === 'work_order') {
    const dispatch = card.workOrder.current_dispatch
    return dispatch
      ? hasStartedCurrentDispatch(dispatch)
      : hasStartedWorkOrderWithoutDispatch(card.workOrder)
  }

  const order = card.incident.current_work_order
  const dispatch = card.incident.current_dispatch
  return dispatch
    ? hasStartedCurrentDispatch(dispatch)
    : Boolean(
      order?.processing_started_at
        || isProcessingStage(order?.execution_status),
    )
}

function isDirectWorkOrderReassigned(workOrder?: WorkOrder | null) {
  const dispatch = workOrder?.current_dispatch
  if (!dispatch || isDirectWorkOrderCompleted(workOrder)) return false
  return Boolean(dispatch.transfer_from_dispatch_id) || (dispatch.attempt_no || 0) > 1
}

function getDirectWorkOrderBucket(workOrder: WorkOrder): OrderTab {
  if (isDirectWorkOrderCompleted(workOrder)) return 'completed'
  return isDirectWorkOrderPendingStart(workOrder) ? 'pending_start' : 'in_progress'
}

function isToday(value?: string | null): boolean {
  if (!value) return false
  const now = new Date()
  const today = `${now.getFullYear()}-${`${now.getMonth() + 1}`.padStart(2, '0')}-${`${now.getDate()}`.padStart(2, '0')}`
  return formatDateTime(value).slice(0, 10) === today
}

function getDirectWorkOrderStats(items: WorkOrder[]) {
  return {
    pendingStart: items.filter(item => isDirectWorkOrderPendingStart(item)).length,
    inProgress: items.filter(item => !isDirectWorkOrderCompleted(item) && !isDirectWorkOrderPendingStart(item)).length,
    completedCount: items.filter(item => isDirectWorkOrderCompleted(item)).length,
    todayCount: items.filter(item => isToday(item.current_dispatch?.dispatch_at || item.dispatch_at || item.created_at)).length,
  }
}

async function loadData() {
  const cached = getCache<Incident[]>('worker_workorders')
  const workOrderCached = getCache<WorkOrder[]>('worker_direct_workorders')
  const supportCached = getCache<DispatchHallEntry[]>('worker_support_workorders')
  if (cached) incidents.value = cached
  if (workOrderCached) workOrders.value = workOrderCached
  if (supportCached) supportEntries.value = supportCached.filter(isSupportEntryAssignedToMe)
  loading.value = !cached && !workOrderCached && !supportCached

  try {
    const [incidentResult, workOrderResult, supportResult] = await Promise.allSettled([
      incidentApi.list({
        workflow_status: 'dispatched,completed,closed,false_alarm,escalated',
        page: 1,
        page_size: 50,
      }),
      workOrderApi.list({
        status: 'dispatched,completed,closed,false_alarm,escalated',
        page: 1,
        page_size: 50,
      }),
      workOrderApi.listDispatchHallEntries({
        status: 'assigned,accepted',
        entry_type: 'support_request',
        include_applications: true,
        page: 1,
        page_size: 50,
      }),
    ])

    if (incidentResult.status === 'fulfilled') {
      incidents.value = incidentResult.value.incidents
      setCache('worker_workorders', incidentResult.value.incidents)
      hasLoadedOnce.value = true
    }
    if (workOrderResult.status === 'fulfilled') {
      workOrders.value = workOrderResult.value.work_orders
      setCache('worker_direct_workorders', workOrderResult.value.work_orders)
      hasLoadedOnce.value = true
    }
    if (supportResult.status === 'fulfilled') {
      const supportItems = supportResult.value.hall_entries.filter(isSupportEntryAssignedToMe)
      supportEntries.value = supportItems
      setCache('worker_support_workorders', supportItems)
      hasLoadedOnce.value = true
    }
    if (incidentResult.status === 'rejected' && workOrderResult.status === 'rejected' && supportResult.status === 'rejected') {
      throw new Error('load failed')
    }
    keepStartedOrdersVisible()
  } catch {
    if (!incidents.value.length && !workOrders.value.length && !supportEntries.value.length) {
      uni.showToast({ title: '工单加载失败', icon: 'none' })
    }
  } finally {
    loading.value = false
  }
}

function shortTicket(ticketId: string) {
  return ticketId.slice(-8)
}

function typeText(card: WorkerTaskCard) {
  if (card.kind === 'support') return '协同任务'
  if (card.kind === 'work_order') return card.workOrder.dispatch_mode === 'hall_takeover' ? '接管任务' : '正式工单'
  return formatRuleLabel(card.incident.rule_triggered)
}

function noteText(card: WorkerTaskCard) {
  if (card.kind === 'support') {
    return sanitizeDisplayText(
      card.hallEntry.support_reason
      || card.hallEntry.reason
      || card.hallEntry.work_order?.suggested_action
      || '',
    ) || '请先确认协同现场与处理范围'
  }
  if (card.kind === 'work_order') {
    return sanitizeDisplayText(card.workOrder.suggested_action) || '请按标准流程排查并补充处理备注'
  }
  return sanitizeDisplayText(card.incident.current_work_order?.suggested_action) || '请按标准流程排查并补充处理备注'
}

function timeText(card: WorkerTaskCard) {
  if (card.kind === 'support') {
    return formatDateTime(card.hallEntry.assigned_at || card.hallEntry.created_at)
  }
  if (card.kind === 'work_order') {
    return formatDateTime(card.workOrder.current_dispatch?.dispatch_at || card.workOrder.dispatch_at || card.workOrder.created_at)
  }
  return formatDateTime(card.incident.current_dispatch?.dispatch_at || card.incident.current_work_order?.dispatch_at || card.incident.created_at)
}

function dueText(card: WorkerTaskCard) {
  if (card.kind === 'support') {
    return card.hallEntry.status === 'assigned' ? '待确认协同' : '协同处理中'
  }
  if (card.kind === 'work_order') {
    if (isDirectWorkOrderOverdue(card.workOrder)) return '已超时'
    const minutes = card.workOrder.current_dispatch?.sla_minutes_left ?? card.workOrder.sla_minutes_left
    if (minutes !== null && minutes !== undefined) return `剩余${minutes}分钟`
    return activeTab.value === 'completed' ? '已闭环' : '按时'
  }
  if (isWorkerOverdueIncident(card.incident)) return '已超时'
  const minutes = card.incident.current_dispatch?.sla_minutes_left ?? card.incident.current_work_order?.sla_minutes_left
  if (minutes !== null && minutes !== undefined) return `剩余${minutes}分钟`
  return activeTab.value === 'completed' ? '已闭环' : '按时'
}

function progressText(card: WorkerTaskCard) {
  if (card.kind === 'support') {
    return card.hallEntry.status === 'assigned' ? '待确认协同' : '协同处理中'
  }
  if (card.kind === 'work_order') {
    const executionStatus = getDirectWorkOrderExecutionStatus(card.workOrder)
    if (executionStatus === 'waiting_support') return '等待协同支援'
    if (executionStatus === 'overdue') return '超时待处理'
    if (isDirectWorkOrderReassigned(card.workOrder)) return '转派后继续处理'
    return DISPATCH_EXECUTION_STATUS_LABEL[executionStatus] || '处理中'
  }
  const executionStatus = getWorkerExecutionStatus(card.incident)
  if (executionStatus === 'waiting_support') return '等待协同支援'
  if (executionStatus === 'overdue') return '超时待处理'
  if (isWorkerReassignedIncident(card.incident)) return '转派后继续处理'
  return DISPATCH_EXECUTION_STATUS_LABEL[executionStatus] || '处理中'
}

function statusText(card: WorkerTaskCard) {
  if (card.kind === 'support') {
    return card.hallEntry.status === 'assigned' ? '待协同' : '协同中'
  }
  if (card.kind === 'work_order') {
    if (isDirectWorkOrderOverdue(card.workOrder)) return '已超时'
    if (isDirectWorkOrderWaitingSupport(card.workOrder)) return '待协同'
    const bucket = getDirectWorkOrderBucket(card.workOrder)
    if (bucket === 'completed') return '已完成'
    if (bucket === 'pending_start') return '待开始'
    if (isDirectWorkOrderReassigned(card.workOrder)) return '已转派'
    return '待完成'
  }
  if (isWorkerOverdueIncident(card.incident)) return '已超时'
  if (isWorkerWaitingSupportIncident(card.incident)) return '待协同'
  const bucket = getWorkerOrderBucket(card.incident)
  if (bucket === 'completed') return '已完成'
  if (bucket === 'pending_start') return '待开始'
  if (isWorkerReassignedIncident(card.incident)) return '已转派'
  return '待完成'
}

function cardFlags(card: WorkerTaskCard): WorkerCardFlag[] {
  if (card.kind === 'support') {
    return [
      ...(canOpenWorkerAiFromCard(card) ? [{ label: '维小修可继续', tone: 'ai' as const }] : []),
      {
        label: card.hallEntry.status === 'assigned' ? '已指派协同' : '协同处理中',
        tone: 'support',
      },
    ]
  }
  if (card.kind === 'work_order') {
    const flags: WorkerCardFlag[] = []
    const dispatch = card.workOrder.current_dispatch
    if (canOpenWorkerAiFromCard(card)) {
      flags.push({ label: '维小修可继续', tone: 'ai' })
    }
    if (isDirectWorkOrderOverdue(card.workOrder)) {
      flags.push({ label: '已超时', tone: 'overdue' })
    }
    if (isDirectWorkOrderWaitingSupport(card.workOrder)) {
      flags.push({ label: '待协同', tone: 'support' })
    }
    if (isDirectWorkOrderReassigned(card.workOrder)) {
      const attemptNo = dispatch?.attempt_no || card.workOrder.dispatch_attempt_no || 0
      flags.push({
        label: attemptNo > 1 ? `第${attemptNo}次派工` : '已转派',
        tone: 'reassigned',
      })
    }
    return flags
  }

  const flags: WorkerCardFlag[] = []
  const dispatch = card.incident.current_dispatch
  if (canOpenWorkerAiFromCard(card)) {
    flags.push({ label: '维小修可继续', tone: 'ai' })
  }
  if (isWorkerOverdueIncident(card.incident)) {
    flags.push({ label: '已超时', tone: 'overdue' })
  }
  if (isWorkerWaitingSupportIncident(card.incident)) {
    flags.push({ label: '待协同', tone: 'support' })
  }
  if (isWorkerReassignedIncident(card.incident)) {
    const attemptNo = dispatch?.attempt_no || 0
    flags.push({
      label: attemptNo > 1 ? `第${attemptNo}次派工` : '已转派',
      tone: 'reassigned',
    })
  }
  return flags
}

function attentionText(card: WorkerTaskCard) {
  if (card.kind === 'support') {
    return sanitizeDisplayText(
      card.hallEntry.support_reason
      || card.hallEntry.reason
      || '',
    ) || '主责任人已发起协同，请先确认支援范围与到场计划'
  }
  if (card.kind === 'work_order') {
    const dispatch = card.workOrder.current_dispatch
    if (isDirectWorkOrderOverdue(card.workOrder)) {
      return sanitizeDisplayText(dispatch?.latest_note || dispatch?.support_reason || '')
        || '当前派工已超时，建议优先处理并及时反馈现场进展'
    }
    if (isDirectWorkOrderWaitingSupport(card.workOrder)) {
      return sanitizeDisplayText(dispatch?.support_reason || dispatch?.latest_note || '')
        || '当前工单正在等待协同或配件支持，请持续跟进'
    }
    if (isDirectWorkOrderReassigned(card.workOrder)) {
      const attemptNo = dispatch?.attempt_no || card.workOrder.dispatch_attempt_no || 0
      const reason = sanitizeDisplayText(dispatch?.selection_reason || dispatch?.latest_note || card.workOrder.latest_progress_note || '')
      return [attemptNo > 1 ? `当前已进入第 ${attemptNo} 次派工` : '当前工单已转派到你名下', reason]
        .filter(Boolean)
        .join('；')
    }
    return ''
  }

  const dispatch = card.incident.current_dispatch
  if (isWorkerOverdueIncident(card.incident)) {
    return sanitizeDisplayText(dispatch?.latest_note || dispatch?.support_reason || '')
      || '当前派工已超时，建议优先处理并及时反馈现场进展'
  }
  if (isWorkerWaitingSupportIncident(card.incident)) {
    return sanitizeDisplayText(dispatch?.support_reason || dispatch?.latest_note || '')
      || '当前工单正在等待协同或配件支持，请持续跟进'
  }
  if (isWorkerReassignedIncident(card.incident)) {
    const attemptNo = dispatch?.attempt_no || 0
    const reason = sanitizeDisplayText(dispatch?.selection_reason || dispatch?.latest_note || '')
    return [attemptNo > 1 ? `当前已进入第 ${attemptNo} 次派工` : '当前工单已转派到你名下', reason]
      .filter(Boolean)
      .join('；')
  }
  return ''
}

function statusToneClass(card: WorkerTaskCard) {
  if (card.kind === 'support') return 'support'
  if (card.kind === 'work_order') {
    if (isDirectWorkOrderOverdue(card.workOrder)) return 'overdue'
    if (isDirectWorkOrderWaitingSupport(card.workOrder)) return 'support'
    if (getDirectWorkOrderBucket(card.workOrder) === 'completed') return 'completed'
    if (getDirectWorkOrderBucket(card.workOrder) === 'pending_start') return 'pending_start'
    if (isDirectWorkOrderReassigned(card.workOrder)) return 'reassigned'
    return 'in_progress'
  }
  if (isWorkerOverdueIncident(card.incident)) return 'overdue'
  if (isWorkerWaitingSupportIncident(card.incident)) return 'support'
  if (getWorkerOrderBucket(card.incident) === 'completed') return 'completed'
  if (getWorkerOrderBucket(card.incident) === 'pending_start') return 'pending_start'
  if (isWorkerReassignedIncident(card.incident)) return 'reassigned'
  return 'in_progress'
}

function progressToneClass(card: WorkerTaskCard) {
  if (card.kind === 'support') return 'support'
  if (card.kind === 'work_order') {
    if (isDirectWorkOrderOverdue(card.workOrder)) return 'overdue'
    if (isDirectWorkOrderWaitingSupport(card.workOrder)) return 'support'
    if (isDirectWorkOrderReassigned(card.workOrder)) return 'reassigned'
    return 'normal'
  }
  if (isWorkerOverdueIncident(card.incident)) return 'overdue'
  if (isWorkerWaitingSupportIncident(card.incident)) return 'support'
  if (isWorkerReassignedIncident(card.incident)) return 'reassigned'
  return 'normal'
}

function cardToneClass(card: WorkerTaskCard) {
  if (card.kind === 'support') return 'tone-support'
  if (card.kind === 'work_order') {
    if (isDirectWorkOrderOverdue(card.workOrder)) return 'tone-overdue'
    if (isDirectWorkOrderWaitingSupport(card.workOrder)) return 'tone-support'
    if (isDirectWorkOrderReassigned(card.workOrder)) return 'tone-reassigned'
    return ''
  }
  if (isWorkerOverdueIncident(card.incident)) return 'tone-overdue'
  if (isWorkerWaitingSupportIncident(card.incident)) return 'tone-support'
  if (isWorkerReassignedIncident(card.incident)) return 'tone-reassigned'
  return ''
}

function copyTicket(ticketId: string) {
  uni.setClipboardData({ data: ticketId, showToast: true })
}

function callContact(card: WorkerTaskCard) {
  const phone = card.kind === 'support'
    ? card.hallEntry.source_dispatch?.assigned_phone
    : card.kind === 'work_order'
      ? card.workOrder.current_dispatch?.assigned_phone || card.workOrder.assigned_phone
      : card.incident.current_dispatch?.assigned_phone || card.incident.current_work_order?.assigned_phone
  if (!phone) {
    uni.showToast({ title: '暂无联系电话', icon: 'none' })
    return
  }
  uni.makePhoneCall({ phoneNumber: phone })
}

function actionLabel(card: WorkerTaskCard) {
  if (activeTab.value === 'completed') return '查看记录'
  if (canOpenWorkerAiFromCard(card)) return '进入维小修'
  if (card.kind === 'support') return card.hallEntry.status === 'assigned' ? '响应协同' : '查看协同'
  return activeTab.value === 'pending_start' ? '立即处理' : '继续处理'
}

function getWorkerAiTarget(card: WorkerTaskCard) {
  if (card.kind === 'support') {
    return {
      ticketId: card.hallEntry.work_order?.ticket_id || card.ticketId,
      incidentId: card.hallEntry.incident_id || card.hallEntry.work_order?.incident_id || '',
      dispatchId: card.hallEntry.source_dispatch_id || card.hallEntry.source_dispatch?.id || '',
      hallEntryId: card.hallEntry.id,
    }
  }
  if (card.kind === 'work_order') {
    return {
      ticketId: card.workOrder.ticket_id,
      incidentId: '',
      dispatchId: card.workOrder.current_dispatch?.id || card.workOrder.dispatch_id || '',
      hallEntryId: '',
    }
  }
  return {
    ticketId: card.incident.current_work_order?.ticket_id || card.ticketId,
    incidentId: card.incident.incident_id,
    dispatchId: card.incident.current_dispatch?.id || '',
    hallEntryId: '',
  }
}

function openWorkerAiFromCard(card: WorkerTaskCard) {
  if (!canOpenWorkerAiFromCard(card)) {
    openDetail(card)
    return
  }
  const target = getWorkerAiTarget(card)
  if (!target.ticketId) {
    uni.showToast({ title: '缺少工单编号', icon: 'none' })
    return
  }
  const query = [
    `ticket_id=${encodeURIComponent(target.ticketId)}`,
    target.incidentId ? `incident_id=${encodeURIComponent(target.incidentId)}` : '',
    target.hallEntryId ? `hall_entry_id=${encodeURIComponent(target.hallEntryId)}` : '',
    target.dispatchId ? `dispatch_id=${encodeURIComponent(target.dispatchId)}` : '',
  ].filter(Boolean).join('&')
  uni.navigateTo({ url: `/pages/worker/ai-workorder/index?${query}` })
}

function handlePrimaryAction(card: WorkerTaskCard, readonly = false) {
  if (!readonly && canOpenWorkerAiFromCard(card)) {
    openWorkerAiFromCard(card)
    return
  }
  openDetail(card, readonly)
}

function openDetail(card: WorkerTaskCard, readonly = false) {
  if (card.kind === 'support') {
    const ticketId = card.hallEntry.work_order?.ticket_id
    if (!ticketId) return
    const readonlyQuery = readonly ? '&readonly=1' : ''
    uni.navigateTo({
      url: `/pages/worker/workorder-detail/index?hall_entry_id=${card.hallEntry.id}&incident_id=${card.hallEntry.incident_id || ''}&ticket_id=${ticketId}${readonlyQuery}`,
    })
    return
  }
  if (card.kind === 'work_order') {
    const readonlyQuery = readonly ? '&readonly=1' : ''
    uni.navigateTo({
      url: `/pages/worker/workorder-detail/index?ticket_id=${card.workOrder.ticket_id}${readonlyQuery}`,
    })
    return
  }
  const ticketId = card.incident.current_work_order?.ticket_id
  if (!ticketId) return
  const readonlyQuery = readonly ? '&readonly=1' : ''
  uni.navigateTo({
    url: `/pages/worker/workorder-detail/index?incident_id=${card.incident.incident_id}&ticket_id=${ticketId}${readonlyQuery}`,
  })
}

onMounted(() => {
  unsubscribeWorkerSync = subscribeWorkerOrdersUpdated(async () => {
    await loadData()
  })
  void loadData()
})

onShow(() => {
  if (!hasLoadedOnce.value) return
  void loadData()
})

onUnmounted(() => {
  unsubscribeWorkerSync?.()
  unsubscribeWorkerSync = null
})
</script>

<style lang="scss" scoped>
.page {
  min-height: 100vh;
  background:
    radial-gradient(circle at top, rgba(174, 203, 150, 0.22), transparent 36%),
    linear-gradient(180deg, #f5f8ef 0%, #fbfdf8 100%);
}

.nav-action {
  font-size: 36rpx;
  color: #5f7137;
}

.tab-row {
  display: flex;
  padding: 12rpx 24rpx 0;
  background: #f7faef;
}

.tab-item {
  flex: 1;
  padding: 18rpx 0 22rpx;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 6rpx;
  color: #2c2724;
  position: relative;
}

.tab-item.active::after {
  content: '';
  position: absolute;
  left: 28%;
  right: 28%;
  bottom: 0;
  height: 8rpx;
  border-radius: 999rpx;
  background: linear-gradient(90deg, #E4EDB8, #b7cc76);
}

.tab-label {
  font-size: 34rpx;
  font-weight: 700;
}

.tab-count {
  font-size: 22rpx;
  color: #808873;
}

.tab-count.loading {
  color: #94a06f;
  letter-spacing: 4rpx;
}

.list-area {
  height: calc(100vh - 320rpx);
  padding: 22rpx 24rpx 0;
  box-sizing: border-box;
}

.worker-tabbar-spacer {
  height: calc(276rpx + env(safe-area-inset-bottom, 0px));
}

.workorder-card,
.empty-card,
.skeleton-card {
  background: rgba(255, 255, 255, 0.98);
  border-radius: 30rpx;
  box-shadow: 0 14rpx 36rpx rgba(181, 196, 118, 0.08);
}

.workorder-card {
  padding: 26rpx;
  margin-bottom: 20rpx;
  border: 2rpx solid transparent;
}

.workorder-card.tone-overdue {
  border-color: rgba(255, 166, 119, 0.46);
  box-shadow: 0 16rpx 40rpx rgba(255, 164, 118, 0.16);
}

.workorder-card.tone-support {
  border-color: rgba(110, 166, 255, 0.34);
  box-shadow: 0 16rpx 40rpx rgba(110, 166, 255, 0.12);
}

.workorder-card.tone-reassigned {
  border-color: rgba(210, 185, 98, 0.34);
  box-shadow: 0 16rpx 40rpx rgba(210, 185, 98, 0.12);
}

.card-head,
.ticket-row,
.location-row,
.detail-line,
.action-row {
  display: flex;
  align-items: center;
}

.card-head,
.location-row,
.detail-line {
  justify-content: space-between;
}

.ticket-row {
  gap: 12rpx;
}

.ticket-id {
  font-size: 25rpx;
  color: #8a7e79;
}

.copy-btn {
  font-size: 22rpx;
  color: #b5aba7;
}

.status-badge {
  padding: 8rpx 18rpx;
  border-radius: 18rpx;
  font-size: 22rpx;
}

.status-badge.in_progress {
  color: #73854a;
  background: #f2f6df;
}

.status-badge.pending_start {
  color: #f6a726;
  background: #fff7e7;
}

.status-badge.support {
  color: #3c73c8;
  background: #eef5ff;
}

.status-badge.overdue {
  color: #df7b38;
  background: #fff1e8;
}

.status-badge.reassigned {
  color: #9a7b2f;
  background: #fbf4df;
}

.status-badge.completed {
  color: #67a381;
  background: #edf8f1;
}

.card-title {
  display: block;
  margin-top: 22rpx;
  font-size: 40rpx;
  line-height: 1.3;
  color: #2c2522;
  font-weight: 700;
}

.location-row {
  margin-top: 18rpx;
}

.flag-row {
  margin-top: 14rpx;
  display: flex;
  flex-wrap: wrap;
  gap: 10rpx;
}

.flag-badge {
  padding: 6rpx 14rpx;
  border-radius: 999rpx;
  font-size: 21rpx;
  font-weight: 600;
}

.flag-badge.support {
  color: #3c73c8;
  background: #eef5ff;
}

.flag-badge.overdue {
  color: #df7b38;
  background: #fff1e8;
}

.flag-badge.reassigned {
  color: #9a7b2f;
  background: #fbf4df;
}

.flag-badge.ai {
  color: #4f7136;
  background: #edf6dc;
}

.location-text,
.distance-text {
  font-size: 24rpx;
}

.location-text {
  color: #8b7a74;
  flex: 1;
  padding-right: 12rpx;
}

.distance-text {
  color: #73854a;
}

.detail-panel {
  margin-top: 20rpx;
  padding: 18rpx 20rpx;
  border-radius: 22rpx;
  background: linear-gradient(180deg, #f8faef 0%, #f2f6e2 100%);
}

.detail-line {
  gap: 18rpx;
  padding: 10rpx 0;
}

.detail-label {
  width: 118rpx;
  font-size: 24rpx;
  color: #818976;
  flex-shrink: 0;
}

.detail-value {
  flex: 1;
  text-align: left;
  font-size: 25rpx;
  line-height: 1.55;
  color: #403834;
}

.detail-value.accent {
  color: #73854a;
}

.detail-value.accent.support {
  color: #3c73c8;
}

.detail-value.accent.overdue {
  color: #df7b38;
}

.detail-value.accent.reassigned {
  color: #9a7b2f;
}

.detail-value.highlight {
  color: #6a5b55;
}

.detail-value.multiline {
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.action-row {
  gap: 16rpx;
  margin-top: 24rpx;
}

.action-row.triple {
  gap: 10rpx;
}

.ghost-btn,
.primary-btn {
  flex: 1;
  height: 82rpx;
  border-radius: 22rpx;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 28rpx;
  font-weight: 600;
}

.action-row.triple .ghost-btn,
.action-row.triple .primary-btn {
  font-size: 24rpx;
}

.ghost-btn {
  color: #73854a;
  border: 2rpx solid rgba(201, 218, 139, 0.88);
  background: #fff;
}

.primary-btn {
  color: #fff;
  background: linear-gradient(135deg, #d6e29f, #b5c875);
}

.empty-card {
  padding: 90rpx 26rpx;
  display: flex;
  flex-direction: column;
  align-items: center;
}

.empty-icon {
  width: 94rpx;
  height: 94rpx;
  border-radius: 26rpx;
  background: linear-gradient(135deg, #E4EDB8, #c2d58a);
  color: #fff;
  font-size: 38rpx;
  font-weight: 700;
  display: flex;
  align-items: center;
  justify-content: center;
}

.empty-title {
  margin-top: 20rpx;
  font-size: 30rpx;
  font-weight: 700;
  color: #2f2825;
}

.empty-subtitle {
  margin-top: 10rpx;
  font-size: 24rpx;
  line-height: 1.6;
  color: #818976;
  text-align: center;
}

.skeleton-card {
  height: 340rpx;
  margin-bottom: 20rpx;
  background: linear-gradient(90deg, rgba(245, 248, 231, 0.94), rgba(228, 237, 184, 1), rgba(245, 248, 231, 0.94));
}
</style>
