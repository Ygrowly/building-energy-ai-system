<template>
  <view class="page">
    <NavBar :title="readonly ? '工单' : '工单'" bg-color="#E4EDB8" text-color="#5f7137" :show-back="true" />

    <view v-if="loading" class="loading-box">
      <text>工单详情加载中...</text>
    </view>

    <template v-else-if="order">
      <scroll-view scroll-y class="page-scroll">
        <view class="hero-panel">
          <view class="hero-badges">
            <text class="hero-badge priority">{{ priorityText }}</text>
            <text class="hero-badge status">{{ statusText }}</text>
            <text v-if="executionText" class="hero-badge plain">{{ executionText }}</text>
          </view>

          <text class="hero-title">{{ summaryText }}</text>
          <text class="hero-location">{{ buildingLabel }} · {{ locationLabel }}</text>

          <view class="hero-meta">
            <view class="meta-card">
              <text class="meta-label">工单编号</text>
              <text class="meta-value">{{ order.ticket_id.slice(-10) }}</text>
            </view>
            <view class="meta-card">
              <text class="meta-label">派单时间</text>
              <text class="meta-value">{{ formatDateTime(order.dispatch_at || order.created_at) }}</text>
            </view>
            <view class="meta-card">
              <text class="meta-label">SLA状态</text>
              <text class="meta-value">{{ slaText }}</text>
            </view>
          </view>
        </view>

        <view class="content-shell">
          <view class="segment-row">
            <view
              v-for="tab in detailTabs"
              :key="tab.key"
              class="segment-item"
              :class="{ active: activeTab === tab.key }"
              @click="activeTab = tab.key"
            >
              <text>{{ tab.label }}</text>
            </view>
          </view>

          <view v-if="activeTab === 'order'" class="detail-stack">
            <view class="section-card">
              <view v-for="row in orderRows" :key="row.label" class="info-row">
                <text class="row-label">{{ row.label }}</text>
                <text class="row-value" :class="{ wrap: row.wrap }">{{ row.value }}</text>
              </view>
            </view>

            <view v-if="dispatchInsightRows.length || dispatchHistoryCards.length" class="section-card">
              <text class="section-title">{{ dispatchSectionTitle }}</text>
              <view v-for="row in dispatchInsightRows" :key="row.label" class="info-row">
                <text class="row-label">{{ row.label }}</text>
                <text class="row-value" :class="{ wrap: row.wrap }">{{ row.value }}</text>
              </view>

              <view v-if="dispatchHistoryCards.length" class="dispatch-history-list">
                <view
                  v-for="card in dispatchHistoryCards"
                  :key="card.id"
                  class="dispatch-history-card"
                >
                  <view class="dispatch-history-head">
                    <text class="dispatch-history-title">{{ card.title }}</text>
                    <text class="dispatch-history-status">{{ card.status }}</text>
                  </view>
                  <text class="dispatch-history-meta">{{ card.meta }}</text>
                  <text
                    v-for="note in card.notes"
                    :key="card.id + note"
                    class="dispatch-history-note"
                  >{{ note }}</text>
                </view>
              </view>
            </view>
          </view>

          <view v-else-if="activeTab === 'customer'" class="section-card">
            <view v-for="row in customerRows" :key="row.label" class="info-row">
              <text class="row-label">{{ row.label }}</text>
              <text class="row-value" :class="{ wrap: row.wrap }">{{ row.value }}</text>
            </view>
          </view>

          <view v-else class="service-stack">
            <view class="section-card" v-if="serviceTimeline.length">
              <text class="section-title">服务记录</text>
              <view v-for="item in serviceTimeline" :key="item.label + item.time" class="timeline-item">
                <view class="timeline-dot" />
                <view class="timeline-content">
                  <text class="timeline-time">{{ item.time }}</text>
                  <text class="timeline-label">{{ item.label }}</text>
                  <text v-if="item.note" class="timeline-note">{{ item.note }}</text>
                </view>
              </view>
            </view>

            <view class="section-card" v-if="aiReasonText">
              <text class="section-title">AI审批分析</text>
              <text class="note-text">{{ aiReasonText }}</text>
            </view>

            <view class="section-card" v-if="evidenceTimeline.length">
              <text class="section-title">异常证据</text>
              <view v-for="item in evidenceTimeline" :key="item.id" class="evidence-item">
                <text class="evidence-time">{{ item.time }}</text>
                <text class="evidence-text">{{ item.text }}</text>
              </view>
            </view>

            <view class="section-card" v-if="readonly && order.worker_result">
              <text class="section-title">维修结果</text>
              <text class="feedback-result">{{ workerResultText }}</text>
              <text v-if="order.worker_notes" class="note-text">{{ order.worker_notes }}</text>
            </view>

            <view class="section-card" v-if="!readonly">
              <text class="section-title">AI辅助维修</text>
              <AiChat :order="order" />
            </view>
          </view>
        </view>

        <view v-if="!readonly && progressActions.length" class="action-card">
          <text class="action-title">执行推进</text>
          <view class="action-row">
            <button
              v-for="item in progressActions"
              :key="item.action"
              class="action-btn plain"
              :loading="actionLoading === item.action"
              @click="submitWorkerAction(item.action)"
            >{{ item.label }}</button>
          </view>
          <textarea
            v-model="workerNote"
            class="note-input"
            maxlength="500"
            placeholder="补充接单、到场、处理现场或协同原因"
          />
        </view>

        <view v-if="!readonly && canSubmitFeedback" class="action-card">
          <text class="action-title">提交维修结果</text>
          <view class="action-row">
            <button class="action-btn fixed" :loading="feedbackLoading === 'fixed'" @click="submitFeedback('fixed')">已修复</button>
            <button class="action-btn false-alarm" :loading="feedbackLoading === 'false_alarm'" @click="submitFeedback('false_alarm')">误报</button>
            <button class="action-btn escalate" :loading="feedbackLoading === 'escalated'" @click="submitFeedback('escalated')">升级处理</button>
          </view>
          <textarea
            v-model="workerNote"
            class="note-input"
            maxlength="500"
            placeholder="补充处理过程、现场情况或后续建议"
          />
        </view>
      </scroll-view>
    </template>
  </view>
</template>

<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { onHide, onShow, onUnload } from '@dcloudio/uni-app'
import NavBar from '../../../components/NavBar.vue'
import AiChat from '../../../components/AiChat.vue'
import {
  workOrderApi,
  type DispatchEvent,
  type DispatchHallEntry,
  type WorkOrder,
  type WorkOrderTimelineResponse,
} from '../../../api/workorder'
import { incidentApi, type IncidentDetail } from '../../../api/incident'
import { useRouteGuard } from '../../../utils/route-guard'
import {
  DISPATCH_EXECUTION_STATUS_LABEL,
  PRIORITY_LABEL,
  SLA_STATUS_LABEL,
  STATUS_LABEL,
  WORKER_RESULT_LABEL,
  type WorkerResult,
} from '../../../constants/status'
import { formatDateTime, formatMetricValue, formatPct } from '../../../utils/format'
import {
  formatBuildingLabel,
  formatDeviceLabel,
  formatRuleLabel,
  formatSystemLabel,
  sanitizeDisplayText,
} from '../../../utils/display'
import { OPERATOR_ROLES, WORKER_ROLES } from '../../../constants/roles'
import { emitWorkerOrdersUpdated, invalidateWorkerOrderCaches } from '../../../utils/worker-sync'

const pages = getCurrentPages()
const currentPage = pages[pages.length - 1] as any
const ticketId = currentPage?.options?.ticket_id ?? ''
const incidentId = currentPage?.options?.incident_id ?? ''
const hallEntryId = currentPage?.options?.hall_entry_id ?? ''
const readonly = currentPage?.options?.readonly === '1'
const detailAllowedRoles = readonly ? [...OPERATOR_ROLES, ...WORKER_ROLES] : WORKER_ROLES

useRouteGuard(detailAllowedRoles)

const incident = ref<IncidentDetail | null>(null)
const order = ref<WorkOrder | null>(null)
const orderTimeline = ref<WorkOrderTimelineResponse | null>(null)
const hallEntry = ref<DispatchHallEntry | null>(null)
const loading = ref(false)
const actionLoading = ref<
  'accept'
  | 'arrive'
  | 'start'
  | 'request_support'
  | 'support_resolved'
  | 'reject'
  | 'accept_support'
  | 'reject_support'
  | null
>(null)
const feedbackLoading = ref<string | null>(null)
const workerNote = ref('')
const activeTab = ref<'order' | 'customer' | 'service'>('order')
const hasLoadedOnce = ref(false)
const detailVisible = ref(true)
let detailSyncTimer: ReturnType<typeof setTimeout> | null = null

const ACTIVE_SYNC_EXECUTION_STATUSES = new Set([
  'pending_accept',
  'accepted',
  'arrived',
  'processing',
  'waiting_support',
  'overdue',
])

type WorkerDispatchAction =
  | 'accept'
  | 'arrive'
  | 'start'
  | 'request_support'
  | 'support_resolved'
  | 'reject'
  | 'accept_support'
  | 'reject_support'
type TimelineItem = { time: string; label: string; note?: string; sortValue: number }
type ProgressAction = { action: WorkerDispatchAction; label: string }
type DispatchHistoryCard = { id: string; title: string; status: string; meta: string; notes: string[] }

const detailTabs = [
  { key: 'order', label: '工单信息' },
  { key: 'customer', label: '客户信息' },
  { key: 'service', label: '服务记录' },
] as const

const DISPATCH_TASK_STATUS_LABEL: Record<string, string> = {
  assigned: '待接单',
  accepted: '已接单',
  arrived: '已到场',
  processing: '处理中',
  waiting_support: '待协同',
  rejected: '已拒单',
  transferred: '已转派',
  completed: '已完成',
  escalated: '已升级',
  cancelled: '已取消',
}

const DISPATCH_MODE_LABEL: Record<string, string> = {
  manual: '人工派工',
  assisted: '辅助派工',
  auto: '自动派工',
  reassigned: '改派',
  escalation: '升级派工',
  hall_takeover: '大厅接管',
}

const buildingLabel = computed(() => formatBuildingLabel(
  hallEntry.value?.work_order?.building_id
  || incident.value?.building_id
  || order.value?.building_id,
))
const locationLabel = computed(() => (
  formatDeviceLabel(
    hallEntry.value?.work_order?.device_id
      || incident.value?.device_id
      || order.value?.device_id,
    hallEntry.value?.work_order?.building_id
      || incident.value?.building_id
      || order.value?.building_id,
  )
  || formatSystemLabel(incident.value?.rule_triggered)
  || '现场待确认'
))
const summaryText = computed(() => (
  sanitizeDisplayText(hallEntry.value?.support_reason)
  || sanitizeDisplayText(hallEntry.value?.reason)
  || sanitizeDisplayText(hallEntry.value?.work_order?.issue_description)
  || sanitizeDisplayText(incident.value?.summary_text)
  || sanitizeDisplayText(order.value?.issue_description)
  || '工单待处理'
))
const priorityText = computed(() => PRIORITY_LABEL[
  hallEntry.value?.work_order?.priority
  || incident.value?.priority
  || order.value?.priority
  || ''
] || '普通工单')
const statusText = computed(() => {
  if (hallEntry.value) return '协同任务'
  return STATUS_LABEL[order.value?.status || ''] || '处理中'
})
const currentExecutionStatus = computed(() => {
  if (hallEntry.value) {
    return hallEntry.value.status === 'assigned' ? 'pending_accept' : 'processing'
  }
  return (
    order.value?.current_dispatch?.execution_status
    || incident.value?.current_dispatch?.execution_status
    || incident.value?.current_work_order?.execution_status
    || order.value?.execution_status
    || ''
  )
})
const executionText = computed(() => {
  if (hallEntry.value) {
    return hallEntry.value.status === 'assigned' ? '待确认协同' : '协同处理中'
  }
  return DISPATCH_EXECUTION_STATUS_LABEL[currentExecutionStatus.value] || ''
})
const slaText = computed(() => {
  if (hallEntry.value) return hallEntry.value.status === 'assigned' ? '待确认' : '协同中'
  const status = order.value?.current_dispatch?.sla_status || incident.value?.current_dispatch?.sla_status || incident.value?.current_work_order?.sla_status || order.value?.sla_status || ''
  return SLA_STATUS_LABEL[status] || '正常'
})
const aiReasonText = computed(() => sanitizeDisplayText(order.value?.ai_reason))
const workerResultText = computed(() => WORKER_RESULT_LABEL[order.value?.worker_result || ''] || '已提交')
const dispatchAttemptCount = computed(() => {
  return orderTimeline.value?.dispatch_tasks?.length || (order.value?.current_dispatch ? 1 : 0)
})
const dispatchTasks = computed(() => {
  const tasks = orderTimeline.value?.dispatch_tasks || []
  if (tasks.length) return [...tasks].sort((a, b) => (a.attempt_no || 0) - (b.attempt_no || 0))
  return order.value?.current_dispatch ? [order.value.current_dispatch] : []
})
const currentDispatchTask = computed(() => {
  if (hallEntry.value) return null
  const currentDispatchId = order.value?.current_dispatch?.id
  if (currentDispatchId) {
    return dispatchTasks.value.find(item => item.id === currentDispatchId) || order.value?.current_dispatch || null
  }
  return dispatchTasks.value[dispatchTasks.value.length - 1] || null
})
const currentBlockReason = computed(() => sanitizeDisplayText(
  hallEntry.value?.support_reason
  || hallEntry.value?.reason
  || ''
))
const currentDispatchBlockReason = computed(() => sanitizeDisplayText(
  order.value?.current_dispatch?.support_reason
  || order.value?.current_dispatch?.reject_reason
  || order.value?.dispatch_blocked_reason
  || '',
))
const latestRejectedTask = computed(() => (
  [...dispatchTasks.value].reverse().find(item => Boolean(sanitizeDisplayText(item.reject_reason))) || null
))
const latestSupportTask = computed(() => (
  [...dispatchTasks.value].reverse().find(item => Boolean(sanitizeDisplayText(item.support_reason))) || null
))
const latestTransferredTask = computed(() => {
  const currentTask = currentDispatchTask.value
  if (currentTask?.transfer_from_dispatch_id) return currentTask
  return [...dispatchTasks.value].reverse().find(item => Boolean(item.transfer_from_dispatch_id)) || null
})
const latestTransferredFromTask = computed(() => {
  const target = latestTransferredTask.value
  if (!target?.transfer_from_dispatch_id) return null
  return dispatchTasks.value.find(item => item.id === target.transfer_from_dispatch_id) || null
})
const dispatchSectionTitle = computed(() => hallEntry.value ? '协同任务信息' : '派工信息')
const dispatchModeText = computed(() => {
  if (hallEntry.value) return '工单大厅协同'
  return DISPATCH_MODE_LABEL[currentDispatchTask.value?.dispatch_mode || ''] || sanitizeDisplayText(currentDispatchTask.value?.dispatch_mode || '') || ''
})
const transferDescription = computed(() => {
  if (hallEntry.value) {
    const intro = [
      hallEntry.value.assigned_by_name ? `${hallEntry.value.assigned_by_name}已将协同任务指派给你` : '管理员已将协同任务指派给你',
      hallEntry.value.source_dispatch?.assigned_to_name ? `主责任人：${hallEntry.value.source_dispatch.assigned_to_name}` : '',
    ].filter(Boolean)
    return intro.join('；')
  }

  const currentTask = currentDispatchTask.value
  if (!currentTask) return ''

  const selectionReason = sanitizeDisplayText(currentTask.selection_reason || currentTask.latest_note || '')
  const sourceTask = latestTransferredFromTask.value
  if (currentTask.transfer_from_dispatch_id && sourceTask) {
    const sourceLabel = [
      `由第 ${sourceTask.attempt_no} 次派工`,
      sourceTask.assigned_to_name ? `（${sourceTask.assigned_to_name}）` : '',
      '转入当前责任人',
    ].join('')
    return [sourceLabel, selectionReason].filter(Boolean).join('；')
  }
  if ((currentTask.attempt_no || 0) > 1 && selectionReason) {
    return `进入第 ${currentTask.attempt_no} 次派工；${selectionReason}`
  }
  return selectionReason
})
const supportReasonText = computed(() => (
  sanitizeDisplayText(
    hallEntry.value?.support_reason
    || currentDispatchTask.value?.support_reason
    || latestSupportTask.value?.support_reason
    || '',
  )
))
const latestRejectText = computed(() => {
  const rejectedTask = latestRejectedTask.value
  if (!rejectedTask?.reject_reason) return ''
  const reason = sanitizeDisplayText(rejectedTask.reject_reason)
  if (!reason) return ''
  return rejectedTask.attempt_no ? `第 ${rejectedTask.attempt_no} 次：${reason}` : reason
})
const dispatchInsightRows = computed(() => {
  if (hallEntry.value) {
    return [
      { label: '协同状态', value: hallEntry.value.status === 'assigned' ? '待确认协同' : '协同处理中' },
      { label: '主责任人', value: hallEntry.value.source_dispatch?.assigned_to_name || '待确认' },
      { label: '协同方式', value: dispatchModeText.value },
      supportReasonText.value ? { label: '协同原因', value: supportReasonText.value, wrap: true } : null,
      transferDescription.value ? { label: '指派说明', value: transferDescription.value, wrap: true } : null,
      currentBlockReason.value ? { label: '当前说明', value: currentBlockReason.value, wrap: true } : null,
    ].filter(Boolean) as Array<{ label: string; value: string; wrap?: boolean }>
  }

  const currentTask = currentDispatchTask.value
  return [
    { label: '派工批次', value: currentTask?.attempt_no ? `第 ${currentTask.attempt_no} 次 / 累计 ${dispatchAttemptCount.value} 次` : `累计 ${dispatchAttemptCount.value} 次` },
    dispatchModeText.value ? { label: '派工方式', value: dispatchModeText.value } : null,
    currentTask?.assigned_team_name ? { label: '责任班组', value: currentTask.assigned_team_name } : null,
    supportReasonText.value ? { label: '协同原因', value: supportReasonText.value, wrap: true } : null,
    latestRejectText.value ? { label: '最近拒单', value: latestRejectText.value, wrap: true } : null,
    transferDescription.value ? { label: '转派说明', value: transferDescription.value, wrap: true } : null,
    currentDispatchBlockReason.value ? { label: '当前阻塞', value: currentDispatchBlockReason.value, wrap: true } : null,
  ].filter(Boolean) as Array<{ label: string; value: string; wrap?: boolean }>
})
const dispatchHistoryCards = computed<DispatchHistoryCard[]>(() => {
  if (hallEntry.value) return []
  return [...dispatchTasks.value]
    .sort((a, b) => (b.attempt_no || 0) - (a.attempt_no || 0))
    .slice(0, 3)
    .map(item => {
      const notes = [
        item.selection_reason
          ? `${item.transfer_from_dispatch_id || (item.attempt_no || 0) > 1 ? '转派说明' : '派工说明'}：${sanitizeDisplayText(item.selection_reason)}`
          : '',
        item.support_reason ? `协同原因：${sanitizeDisplayText(item.support_reason)}` : '',
        item.reject_reason ? `拒单原因：${sanitizeDisplayText(item.reject_reason)}` : '',
        item.cancel_reason ? `取消原因：${sanitizeDisplayText(item.cancel_reason)}` : '',
      ].filter(Boolean)

      if (!notes.length) {
        const latestNote = sanitizeDisplayText(item.latest_note || '')
        if (latestNote) notes.push(`执行说明：${latestNote}`)
      }

      const meta = [
        item.assigned_to_name || '待分配责任人',
        formatDateTime(item.assigned_at || item.accepted_at || item.arrived_at || item.completed_at),
      ].filter(Boolean).join(' · ')

      return {
        id: item.id,
        title: item.attempt_no ? `第 ${item.attempt_no} 次派工` : '派工记录',
        status: DISPATCH_TASK_STATUS_LABEL[item.dispatch_status] || sanitizeDisplayText(item.dispatch_status) || '状态更新',
        meta,
        notes,
      }
    })
})
const progressActions = computed<ProgressAction[]>(() => {
  if (hallEntry.value) {
    if (hallEntry.value.status === 'assigned') {
      return [
        { action: 'accept_support', label: '确认协同' },
        { action: 'reject_support', label: '无法支援' },
      ]
    }
    return []
  }
  switch (currentExecutionStatus.value) {
    case 'pending_accept':
      return [
        { action: 'accept' as const, label: '确认接单' },
        { action: 'reject' as const, label: '无法接单' },
      ]
    case 'accepted':
      return [
        { action: 'arrive' as const, label: '确认到场' },
        { action: 'reject' as const, label: '退回改派' },
      ]
    case 'arrived':
      return [
        { action: 'start' as const, label: '开始处理' },
        { action: 'request_support' as const, label: '申请协同' },
      ]
    case 'processing':
      return [{ action: 'request_support' as const, label: '申请协同' }]
    case 'waiting_support':
      return [
        { action: 'support_resolved' as const, label: '恢复处理' },
        { action: 'request_support' as const, label: '更新协同' },
      ]
    case 'overdue':
      if (!order.value?.accepted_at) return [
        { action: 'accept' as const, label: '立即接单' },
        { action: 'reject' as const, label: '无法接单' },
      ]
      if (!order.value?.arrived_at) return [
        { action: 'arrive' as const, label: '立即到场' },
        { action: 'reject' as const, label: '退回改派' },
      ]
      if (!order.value?.processing_started_at) return [{ action: 'start' as const, label: '开始处理' }]
      return [{ action: 'request_support' as const, label: '申请协同' }]
    default:
      return []
  }
})
const canSubmitFeedback = computed(() => !hallEntry.value && (['processing', 'waiting_support'].includes(currentExecutionStatus.value) || !!order.value?.processing_started_at))

const orderRows = computed(() => [
  { label: '工单编号', value: order.value?.ticket_id || '--' },
  { label: '工单时间', value: formatDateTime(order.value?.dispatch_at || order.value?.created_at) },
  { label: '工单类型', value: incident.value ? formatRuleLabel(incident.value.rule_triggered) : '现场维修' },
  { label: '工单内容', value: summaryText.value, wrap: true },
  { label: '建议措施', value: sanitizeDisplayText(order.value?.suggested_action) || '按标准维修流程现场排查', wrap: true },
  { label: '受理人员', value: hallEntry.value?.assigned_to_name || order.value?.assigned_to_name || '当前维修人员' },
].filter(Boolean) as Array<{ label: string; value: string; wrap?: boolean }>)

const customerRows = computed(() => [
  { label: '服务建筑', value: buildingLabel.value },
  { label: '设备位置', value: locationLabel.value },
  { label: '异常系统', value: incident.value ? formatSystemLabel(incident.value.rule_triggered) : '能源系统' },
  { label: '异常规则', value: incident.value ? formatRuleLabel(incident.value.rule_triggered) : '系统派单' },
  { label: '首次发现', value: formatDateTime(incident.value?.first_seen_at || order.value?.created_at) },
  { label: '最近异常', value: formatDateTime(incident.value?.last_seen_at || order.value?.updated_at) },
  { label: '联系电话', value: incident.value?.current_work_order?.assigned_phone || '暂无' },
])

function getDispatchEventLabel(event: DispatchEvent) {
  const labels: Record<string, string> = {
    assigned: '工单已派发',
    auto_assigned: '系统自动派发',
    accepted: '已接单',
    arrived: '已到场',
    started: '开始处理',
    support_requested: '已申请协同',
    support_resolved: '协同已解决',
    rejected: '已拒单',
    transferred: '已转派',
    cancelled: '已取消派工',
    timeout_warning: '临近超时',
    timeout_overdue: '已超时',
    completed: '执行完成',
    escalated: '升级处理',
  }
  return labels[event.event_type] || '状态更新'
}

function getDispatchEventNote(event: DispatchEvent) {
  const payload = event.payload || {}
  return sanitizeDisplayText(
    payload.notes
    || payload.reason
    || payload.selection_reason
    || payload.result
    || payload.message
    || payload.dispatch_mode
  )
}

const serviceTimeline = computed<TimelineItem[]>(() => {
  const timelineItems = orderTimeline.value?.timeline || []
  if (timelineItems.length) {
    return timelineItems
      .map(item => ({
        time: formatDateTime(item.occurred_at),
        label: item.attempt_no ? `第 ${item.attempt_no} 次 · ${item.label}` : item.label,
        note: sanitizeDisplayText(item.note || '') || undefined,
        sortValue: new Date(item.occurred_at || '').getTime() || 0,
      }))
      .sort((a, b) => a.sortValue - b.sortValue)
  }

  const dispatchEvents = order.value?.current_dispatch?.events || []
  if (dispatchEvents.length) {
    return dispatchEvents
      .map(item => ({
        time: formatDateTime(item.created_at),
        label: getDispatchEventLabel(item),
        note: getDispatchEventNote(item) || undefined,
        sortValue: new Date(item.created_at || '').getTime() || 0,
      }))
      .sort((a, b) => a.sortValue - b.sortValue)
  }

  return [
    { time: formatDateTime(order.value?.dispatch_at || order.value?.created_at), label: '工单已派发', note: '系统已推送到维修端。', sortValue: new Date(order.value?.dispatch_at || order.value?.created_at || '').getTime() || 0 },
    order.value?.accepted_at ? { time: formatDateTime(order.value.accepted_at), label: '已接单', note: '维修人员已确认接收工单。', sortValue: new Date(order.value.accepted_at).getTime() || 0 } : null,
    order.value?.arrived_at ? { time: formatDateTime(order.value.arrived_at), label: '已到场', note: '维修人员已到达现场。', sortValue: new Date(order.value.arrived_at).getTime() || 0 } : null,
    order.value?.updated_at ? { time: formatDateTime(order.value.updated_at), label: '最近更新', note: sanitizeDisplayText(order.value.admin_notes || order.value.worker_notes || order.value.suggested_action) || undefined, sortValue: new Date(order.value.updated_at).getTime() || 0 } : null,
    order.value?.worker_feedback_at ? { time: formatDateTime(order.value.worker_feedback_at), label: '已提交反馈', note: workerResultText.value, sortValue: new Date(order.value.worker_feedback_at).getTime() || 0 } : null,
  ].filter(Boolean) as TimelineItem[]
})

const evidenceTimeline = computed(() => {
  if (!incident.value) return []

  const events = incident.value.event_links.map(item => ({
    id: item.id,
    sortValue: new Date(item.data_timestamp || '').getTime() || 0,
    time: formatDateTime(item.data_timestamp),
    text: `实际${formatMetricValue(item.actual_value)}，预期${formatMetricValue(item.expected_value)}，偏差${formatPct(item.deviation_pct)}`,
  }))
  const predictions = incident.value.prediction_links.map(item => ({
    id: item.id,
    sortValue: new Date(item.forecast_for_timestamp || '').getTime() || 0,
    time: formatDateTime(item.forecast_for_timestamp),
    text: `预测${formatMetricValue(item.predicted_value)}，基线${formatMetricValue(item.expected_value)}，预计偏差${formatPct(item.deviation_pct)}`,
  }))

  return [...events, ...predictions].sort((a, b) => a.sortValue - b.sortValue)
})

function notifyWorkerSurfaces(reason: string) {
  emitWorkerOrdersUpdated({
    reason,
    ticketId: order.value?.ticket_id || ticketId || undefined,
    incidentId: incident.value?.incident_id || incidentId || undefined,
  })
}

function stopDetailSync() {
  if (detailSyncTimer) {
    clearTimeout(detailSyncTimer)
    detailSyncTimer = null
  }
}

function shouldKeepDetailSync() {
  if (readonly || !detailVisible.value || !order.value) return false
  return ACTIVE_SYNC_EXECUTION_STATUSES.has(currentExecutionStatus.value)
}

function scheduleDetailSyncTick(remainingMs: number) {
  stopDetailSync()
  if (remainingMs <= 0 || !shouldKeepDetailSync()) return

  const nextDelay = Math.min(4000, remainingMs)
  detailSyncTimer = setTimeout(async () => {
    if (!shouldKeepDetailSync()) {
      stopDetailSync()
      return
    }

    try {
      await loadOrder({ silent: true })
    } finally {
      scheduleDetailSyncTick(remainingMs - nextDelay)
    }
  }, nextDelay)
}

function startDetailSync(durationMs = 15000) {
  if (!shouldKeepDetailSync()) {
    stopDetailSync()
    return
  }
  scheduleDetailSyncTick(durationMs)
}

async function loadWorkOrderTimeline(targetTicketId: string) {
  try {
    orderTimeline.value = await workOrderApi.timeline(targetTicketId)
  } catch {
    orderTimeline.value = null
  }
}

async function loadOrder(options: { silent?: boolean } = {}) {
  const silent = options.silent ?? false
  if (!silent) {
    loading.value = true
  }
  try {
    incident.value = null
    orderTimeline.value = null
    hallEntry.value = null
    let effectiveTicketId = ticketId

    // 详情页优先读取工单接口，避免 incident 详情偶发超时影响主流程打开。
    if (hallEntryId) {
      hallEntry.value = await workOrderApi.dispatchHallDetail(hallEntryId)
      effectiveTicketId = hallEntry.value.work_order?.ticket_id || effectiveTicketId
    }

    if (effectiveTicketId) {
      const [orderDetail, timelineData] = await Promise.all([
        workOrderApi.detail(effectiveTicketId),
        workOrderApi.timeline(effectiveTicketId).catch(() => null),
      ])
      order.value = orderDetail
      orderTimeline.value = timelineData
    }

    if (incidentId && !readonly) {
      try {
        incident.value = await incidentApi.detail(incidentId)
        const currentTicketId = incident.value.current_work_order?.ticket_id
        if (currentTicketId && currentTicketId !== order.value?.ticket_id) {
          order.value = await workOrderApi.detail(currentTicketId)
          await loadWorkOrderTimeline(currentTicketId)
        }
      } catch {
        incident.value = null
      }
    } else if (!ticketId && incidentId) {
      incident.value = await incidentApi.detail(incidentId)
      const currentTicketId = incident.value.current_work_order?.ticket_id
      if (currentTicketId) {
        order.value = await workOrderApi.detail(currentTicketId)
        await loadWorkOrderTimeline(currentTicketId)
      }
    }
    hasLoadedOnce.value = true
  } catch {
    if (!silent) {
      if (hallEntryId) {
        invalidateWorkerOrderCaches()
      }
      uni.showToast({ title: '详情加载失败', icon: 'none' })
      uni.navigateBack()
    }
  } finally {
    if (!silent) {
      loading.value = false
    }
  }
}

async function submitWorkerAction(action: WorkerDispatchAction) {
  if (!order.value?.ticket_id && !hallEntry.value?.id) return
  if ((action === 'request_support' || action === 'reject' || action === 'reject_support') && !sanitizeDisplayText(workerNote.value)) {
    uni.showToast({ title: action === 'reject' ? '请先填写拒单原因' : '请先填写协同原因', icon: 'none' })
    return
  }
  if (action === 'support_resolved' && currentExecutionStatus.value !== 'waiting_support') {
    uni.showToast({ title: '协同状态已变化，正在刷新工单', icon: 'none' })
    await loadOrder({ silent: true })
    return
  }
  actionLoading.value = action
  try {
    if (action === 'accept_support') {
      if (!hallEntry.value?.id) {
        uni.showToast({ title: '当前协同任务不存在', icon: 'none' })
        return
      }
      await workOrderApi.acceptAssignedSupportTask(hallEntry.value.id, workerNote.value || undefined)
    } else if (action === 'reject_support') {
      if (!hallEntry.value?.id) {
        uni.showToast({ title: '当前协同任务不存在', icon: 'none' })
        return
      }
      await workOrderApi.rejectAssignedSupportTask(hallEntry.value.id, workerNote.value || '当前无法支援')
    } else if (action === 'reject') {
      const dispatchId = order.value.current_dispatch?.id
      if (!dispatchId) {
        uni.showToast({ title: '当前派工任务不存在', icon: 'none' })
        return
      }
      await workOrderApi.rejectDispatchTask(dispatchId, workerNote.value || '当前无法接单')
    } else if (action === 'request_support') {
      const dispatchId = order.value.current_dispatch?.id
      if (dispatchId) {
        await workOrderApi.requestDispatchSupport(dispatchId, workerNote.value || '需要协同支持')
      } else {
        await workOrderApi.workerAction(order.value.ticket_id, action, workerNote.value || undefined)
      }
    } else if (action === 'support_resolved') {
      const dispatchId = order.value.current_dispatch?.id
      if (dispatchId) {
        await workOrderApi.resolveDispatchSupport(dispatchId, workerNote.value || undefined)
      } else {
        await workOrderApi.workerAction(order.value.ticket_id, action, workerNote.value || undefined)
      }
    } else if (order.value.current_dispatch?.id) {
      await workOrderApi.dispatchTaskAction(order.value.current_dispatch.id, action)
    } else {
      await workOrderApi.workerAction(order.value.ticket_id, action, workerNote.value || undefined)
    }
    notifyWorkerSurfaces(`worker_action:${action}`)
    uni.showToast({ title: '状态已更新', icon: 'success' })
    if (action === 'reject' || action === 'reject_support') {
      stopDetailSync()
      setTimeout(() => uni.navigateBack(), 900)
      return
    }
    if (action !== 'request_support') {
      workerNote.value = ''
    }
    await loadOrder({ silent: true })
    startDetailSync()
  } catch {
    uni.showToast({ title: '操作失败，请稍后再试', icon: 'none' })
  } finally {
    actionLoading.value = null
  }
}

async function submitFeedback(result: WorkerResult) {
  if (!order.value?.ticket_id) {
    uni.showToast({ title: '缺少工单编号', icon: 'none' })
    return
  }

  feedbackLoading.value = result
  const labelMap: Record<string, string> = {
    fixed: '已修复',
    false_alarm: '误报',
    escalated: '升级处理',
  }

  uni.showModal({
    title: `确认提交：${labelMap[result]}`,
    content: result === 'escalated' ? '提交后将转交管理员继续处理。' : `确认将工单标记为「${labelMap[result]}」？`,
    confirmText: '确认',
    success(res) {
      if (!res.confirm) {
        feedbackLoading.value = null
        return
      }
      doSubmit(result)
    },
    fail() {
      feedbackLoading.value = null
    },
  })
}

async function doSubmit(result: WorkerResult) {
  try {
    if (order.value?.current_dispatch?.id) {
      await workOrderApi.completeDispatchTask(
        order.value.current_dispatch.id,
        result,
        workerNote.value || undefined,
      )
    } else {
      await workOrderApi.workerFeedback(order.value!.ticket_id, result, workerNote.value || undefined)
    }
    notifyWorkerSurfaces(`worker_feedback:${result}`)
    stopDetailSync()
    uni.showToast({ title: '结果已提交', icon: 'success' })
    setTimeout(() => uni.navigateBack(), 1200)
  } catch {
    uni.showToast({ title: '提交失败，请稍后再试', icon: 'none' })
  } finally {
    feedbackLoading.value = null
  }
}

onMounted(async () => {
  await loadOrder()
  startDetailSync()
})

onShow(() => {
  detailVisible.value = true
  if (!hasLoadedOnce.value) return
  void loadOrder({ silent: true }).then(() => {
    startDetailSync(12000)
  })
})

onHide(() => {
  detailVisible.value = false
  stopDetailSync()
})

onUnload(() => {
  detailVisible.value = false
  stopDetailSync()
})

onUnmounted(() => {
  detailVisible.value = false
  stopDetailSync()
})
</script>

<style lang="scss" scoped>
.page {
  min-height: 100vh;
  background: linear-gradient(180deg, #f5f8e8 0%, #fbfcf5 42%, #fffdfb 100%);
}

.loading-box {
  padding: 120rpx 0;
  text-align: center;
  color: rgba(255, 255, 255, 0.92);
  font-size: 28rpx;
}

.page-scroll {
  height: calc(100vh - 132rpx);
  padding: 16rpx 24rpx 42rpx;
  box-sizing: border-box;
}

.hero-panel {
  padding: 28rpx 24rpx 30rpx;
  border-radius: 32rpx;
  background:
    radial-gradient(circle at top right, rgba(244, 248, 216, 0.46), transparent 32%),
    linear-gradient(135deg, #dbe7a8 0%, #c6d98b 48%, #a7bf63 100%);
  box-shadow: 0 24rpx 56rpx rgba(167, 191, 99, 0.24);
}

.hero-badges {
  display: flex;
  align-items: center;
  gap: 10rpx;
  flex-wrap: wrap;
}

.hero-badge {
  padding: 8rpx 16rpx;
  border-radius: 18rpx;
  font-size: 22rpx;
}

.hero-badge.priority {
  color: #6f8442;
  background: rgba(255, 255, 255, 0.94);
}

.hero-badge.status {
  color: #fff;
  background: rgba(255, 255, 255, 0.2);
}

.hero-badge.plain {
  color: rgba(255, 255, 255, 0.95);
  background: rgba(255, 255, 255, 0.16);
}

.hero-title {
  display: block;
  margin-top: 22rpx;
  font-size: 42rpx;
  line-height: 1.34;
  color: #fff;
  font-weight: 700;
  text-shadow: 0 6rpx 16rpx rgba(82, 97, 48, 0.16);
}

.hero-location {
  display: block;
  margin-top: 14rpx;
  font-size: 25rpx;
  color: rgba(251, 253, 245, 0.94);
}

.hero-meta {
  margin-top: 24rpx;
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 14rpx;
}

.meta-card {
  padding: 18rpx 16rpx;
  border-radius: 22rpx;
  background: rgba(255, 255, 255, 0.22);
  backdrop-filter: blur(12rpx);
  box-shadow: inset 0 0 0 1rpx rgba(255, 255, 255, 0.14);
}

.meta-label,
.meta-value {
  display: block;
}

.meta-label {
  font-size: 22rpx;
  color: rgba(247, 250, 236, 0.82);
}

.meta-value {
  margin-top: 10rpx;
  font-size: 24rpx;
  line-height: 1.4;
  color: #fff;
  font-weight: 600;
}

.content-shell {
  margin-top: 18rpx;
  padding: 18rpx;
  border-radius: 32rpx;
  background: rgba(255, 255, 255, 0.98);
  box-shadow: 0 18rpx 44rpx rgba(181, 196, 118, 0.12);
}

.detail-stack {
  display: grid;
  gap: 2rpx;
}

.segment-row {
  display: flex;
  padding: 10rpx;
  border-radius: 24rpx;
  background: #f6f9e8;
}

.segment-item {
  flex: 1;
  height: 74rpx;
  border-radius: 20rpx;
  display: flex;
  align-items: center;
  justify-content: center;

  text {
    font-size: 28rpx;
    color: #768062;
    font-weight: 600;
  }
}

.segment-item.active {
  background: #fff;
  box-shadow: 0 8rpx 18rpx rgba(181, 196, 118, 0.12);

  text {
    color: #6f8442;
  }
}

.section-card {
  margin-top: 18rpx;
  padding: 14rpx 22rpx;
  border-radius: 28rpx;
  background: linear-gradient(180deg, #fffefb 0%, #f7faef 100%);
  box-shadow: inset 0 0 0 2rpx rgba(228, 237, 184, 0.72);
}

.section-title {
  display: block;
  margin: 10rpx 0 16rpx;
  font-size: 30rpx;
  color: #302824;
  font-weight: 700;
}

.info-row {
  display: flex;
  gap: 18rpx;
  padding: 24rpx 0;
  border-bottom: 1rpx solid #edf2dc;
}

.info-row:last-child {
  border-bottom: none;
}

.row-label {
  width: 128rpx;
  flex-shrink: 0;
  font-size: 26rpx;
  color: #93827c;
}

.row-value {
  flex: 1;
  font-size: 28rpx;
  line-height: 1.6;
  color: #342b27;
}

.row-value.wrap {
  white-space: pre-wrap;
}

.service-stack {
  display: grid;
  gap: 2rpx;
}

.dispatch-history-list {
  margin-top: 16rpx;
  display: grid;
  gap: 14rpx;
}

.dispatch-history-card {
  padding: 18rpx 18rpx 16rpx;
  border-radius: 22rpx;
  background: rgba(248, 250, 240, 0.92);
  box-shadow: inset 0 0 0 1rpx rgba(228, 237, 184, 0.9);
}

.dispatch-history-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12rpx;
}

.dispatch-history-title,
.dispatch-history-status,
.dispatch-history-meta,
.dispatch-history-note {
  display: block;
}

.dispatch-history-title {
  font-size: 26rpx;
  color: #3a312d;
  font-weight: 700;
}

.dispatch-history-status {
  padding: 6rpx 14rpx;
  border-radius: 999rpx;
  background: rgba(183, 204, 118, 0.16);
  color: #6f8442;
  font-size: 22rpx;
  font-weight: 600;
}

.dispatch-history-meta {
  margin-top: 10rpx;
  font-size: 23rpx;
  color: #968680;
}

.dispatch-history-note {
  margin-top: 8rpx;
  font-size: 24rpx;
  line-height: 1.6;
  color: #6d5f59;
}

.timeline-item {
  display: flex;
  gap: 16rpx;
  padding: 18rpx 0;
}

.timeline-dot {
  width: 16rpx;
  height: 16rpx;
  margin-top: 10rpx;
  border-radius: 50%;
  background: #b7cc76;
  box-shadow: 0 0 0 8rpx rgba(183, 204, 118, 0.18);
  flex-shrink: 0;
}

.timeline-content {
  flex: 1;
}

.timeline-time,
.timeline-label,
.timeline-note,
.note-text,
.evidence-time,
.evidence-text {
  display: block;
}

.timeline-time,
.evidence-time {
  font-size: 22rpx;
  color: #a5928b;
}

.timeline-label {
  margin-top: 8rpx;
  font-size: 28rpx;
  color: #332a26;
  font-weight: 700;
}

.timeline-note,
.note-text,
.evidence-text {
  margin-top: 8rpx;
  font-size: 24rpx;
  line-height: 1.6;
  color: #7f716b;
}

.evidence-item {
  padding: 18rpx 0;
  border-bottom: 1rpx solid #edf2dc;
}

.evidence-item:last-child {
  border-bottom: none;
}

.feedback-result {
  display: block;
  font-size: 34rpx;
  color: #6f8442;
  font-weight: 700;
}

.action-card {
  margin-top: 22rpx;
  margin-bottom: 28rpx;
  padding: 26rpx 24rpx;
  border-radius: 30rpx;
  background: rgba(255, 255, 255, 0.98);
  box-shadow: 0 18rpx 42rpx rgba(181, 196, 118, 0.1);
}

.action-title {
  display: block;
  font-size: 30rpx;
  color: #322925;
  font-weight: 700;
}

.action-row {
  display: flex;
  gap: 14rpx;
  margin-top: 20rpx;
}

.action-btn {
  flex: 1;
  height: 84rpx;
  border-radius: 22rpx;
  font-size: 25rpx;
  font-weight: 600;
  border: none;
  padding: 0;
}

.action-btn.plain {
  color: #6f8442;
  background: #f5f8e8;
}

.action-btn.fixed {
  color: #fff;
  background: linear-gradient(135deg, #69c98e, #43b983);
}

.action-btn.false-alarm {
  color: #ff6b5d;
  background: #fff1ee;
}

.action-btn.escalate {
  color: #fff;
  background: linear-gradient(135deg, #d0dda0, #a9c165);
}

.note-input {
  width: 100%;
  min-height: 150rpx;
  margin-top: 18rpx;
  padding: 20rpx 22rpx;
  box-sizing: border-box;
  border-radius: 24rpx;
  background: #f8faef;
  font-size: 26rpx;
  line-height: 1.6;
  color: #342b27;
}
</style>
