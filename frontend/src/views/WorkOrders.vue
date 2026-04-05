<template>
  <div class="workorders">
    <header class="page-header">
      <h1><Icon icon="mdi:clipboard-list" width="22" class="page-icon" /> 工单管理</h1>
      <span class="subtitle">AI 审阅 · 派工中心 · 执行跟踪</span>
    </header>

    <div class="toolbar">
      <div class="tab-group">
        <button
          v-for="tab in tabs"
          :key="tab.value"
          class="tab-btn"
          :class="{ active: activeTab === tab.value }"
          @click="switchTab(tab.value)"
        >
          {{ tab.label }}
          <span class="tab-count" v-if="tabCount(tab.value) > 0">{{ tabCount(tab.value) }}</span>
        </button>
      </div>
      <button class="refresh-btn" @click="fetchOrders" :disabled="loading">
        <Icon :icon="loading ? 'mdi:loading' : 'mdi:refresh'" width="14" class="btn-icon" />
        {{ loading ? '刷新中...' : '刷新' }}
      </button>
    </div>

    <div class="summary-strip" v-if="allOrders.length">
      <div class="summary-pill">
        <span class="summary-value">{{ allOrders.length }}</span>
        <span class="summary-label">工单总数</span>
      </div>
      <div class="summary-pill warning">
        <span class="summary-value">{{ tabCount('pending_dispatch') }}</span>
        <span class="summary-label">待派工</span>
      </div>
      <div class="summary-pill active">
        <span class="summary-value">{{ tabCount('dispatched') }}</span>
        <span class="summary-label">执行中</span>
      </div>
      <div class="summary-pill danger">
        <span class="summary-value">{{ overdueCount }}</span>
        <span class="summary-label">高风险</span>
      </div>
    </div>

    <div v-if="loading" class="loading-bar">加载工单列表...</div>
    <div v-if="fetchError" class="error-bar"><Icon icon="mdi:alert" width="14" class="bar-icon" /> {{ fetchError }}</div>

    <div v-if="!loading && filteredOrders.length > 0" class="order-list">
      <div
        class="order-card"
        v-for="wo in filteredOrders"
        :key="wo.ticket_id"
        :class="statusCardClass(wo)"
      >
        <div class="card-header" @click="toggleExpand(wo.ticket_id)">
          <div class="card-header-left">
            <span class="priority-badge" :class="'p-' + (wo.priority ?? 'medium').toLowerCase()">
              {{ PRIORITY_LABELS[wo.priority] ?? wo.priority ?? '普通' }}
            </span>
            <div class="card-title-block">
              <p class="card-title">{{ wo.issue_description || wo.ticket_id }}</p>
              <p class="card-meta">
                工单 {{ wo.ticket_id }} · {{ buildingName(wo.building_id) }} · {{ formatTime(wo.created_at) }}
              </p>
            </div>
          </div>
          <div class="card-header-right">
            <span class="status-chip" :class="statusChipClass(wo.status)">
              {{ STATUS_LABELS[wo.status] ?? wo.status }}
            </span>
            <span
              v-if="wo.execution_status"
              class="execution-chip"
              :class="executionChipClass(wo.execution_status)"
            >
              {{ EXECUTION_LABELS[wo.execution_status] ?? wo.execution_status }}
            </span>
            <span class="expand-btn">{{ expandedId === wo.ticket_id ? '▲' : '▼' }}</span>
          </div>
        </div>

        <Transition name="slide">
          <div class="card-body" v-if="expandedId === wo.ticket_id">
            <div class="detail-grid">
              <div class="detail-row" v-for="row in detailRows(wo)" :key="row.label">
                <span class="detail-label">{{ row.label }}</span>
                <span class="detail-val" :class="row.cls">{{ row.value }}</span>
              </div>
            </div>

            <div class="timeline-block" v-if="timelineRows(wo).length">
              <p class="section-title">执行时间线</p>
              <div class="timeline-item" v-for="item in timelineRows(wo)" :key="item.time + item.label">
                <span class="timeline-dot" />
                <div class="timeline-content">
                  <span class="timeline-time">{{ item.time }}</span>
                  <span class="timeline-label">{{ item.label }}</span>
                  <span v-if="item.note" class="timeline-note">{{ item.note }}</span>
                </div>
              </div>
            </div>

            <div class="action-bar" v-if="actionsForOrder(wo).length">
              <template v-for="action in actionsForOrder(wo)" :key="action.action">
                <button
                  v-if="action.action !== 'reject_pending'"
                  class="action-btn"
                  :class="action.className"
                  @click="runAction(wo, action.action)"
                  :disabled="actionLoading === wo.ticket_id + ':' + action.action"
                >
                  {{ actionLoading === wo.ticket_id + ':' + action.action ? '处理中...' : action.label }}
                </button>
                <button
                  v-else
                  class="action-btn danger"
                  @click="startReject(wo.ticket_id)"
                  :disabled="actionLoading === wo.ticket_id + ':' + action.action"
                >
                  驳回
                </button>
              </template>
            </div>

            <div class="reject-area" v-if="rejectingId === wo.ticket_id">
              <input
                v-model="rejectReason"
                placeholder="输入驳回原因"
                @keyup.enter="runAction(wo, 'reject_pending')"
                class="reject-input"
              />
              <button class="btn-reject-confirm" @click="runAction(wo, 'reject_pending')">确认驳回</button>
              <button class="btn-cancel" @click="cancelReject">取消</button>
            </div>

            <div class="action-result success" v-if="actionResult[wo.ticket_id]?.type === 'success'">
              <Icon icon="mdi:check-circle" width="14" class="bar-icon" /> {{ actionResult[wo.ticket_id].message }}
            </div>
            <div class="action-result error" v-if="actionResult[wo.ticket_id]?.type === 'error'">
              <Icon icon="mdi:alert" width="14" class="bar-icon" /> {{ actionResult[wo.ticket_id].message }}
            </div>
          </div>
        </Transition>
      </div>
    </div>

    <div v-if="!loading && filteredOrders.length === 0 && !fetchError" class="empty-state">
      <p class="empty-icon"><Icon icon="mdi:clipboard-list" width="40" /></p>
      <p>{{ emptyMessage }}</p>
      <p class="empty-sub">系统会根据 AI 审阅、派工和执行推进自动更新这里的状态。</p>
    </div>

    <div v-if="dispatchPanel.visible" class="dispatch-mask" @click="closeDispatchPanel">
      <div class="dispatch-sheet" @click.stop>
        <div class="dispatch-header">
          <div>
            <p class="dispatch-title">{{ dispatchPanel.mode === 'reassign' ? '改派中心' : '派工中心' }}</p>
            <p class="dispatch-subtitle">{{ dispatchPanel.requirement?.summary || '为当前工单选择最合适的维修人员' }}</p>
          </div>
          <button class="link-btn" @click="closeDispatchPanel">关闭</button>
        </div>

        <div class="dispatch-requirement" v-if="dispatchPanel.requirement">
          <span class="req-chip">{{ dispatchPanel.requirement.building_id }}</span>
          <span class="req-chip">{{ PRIORITY_LABELS[dispatchPanel.requirement.priority] ?? dispatchPanel.requirement.priority }}</span>
          <span class="req-chip">{{ dispatchPanel.requirement.preferred_team_name }}</span>
        </div>

        <div class="candidate-list">
          <div class="candidate-card" v-for="candidate in dispatchPanel.candidates" :key="candidate.user_id">
            <div class="candidate-head">
              <div>
                <p class="candidate-name">{{ candidate.username }}</p>
                <p class="candidate-meta">{{ candidate.team_name || '综合运维班' }} · {{ candidate.job_title || '维修工程师' }}</p>
              </div>
              <span class="score-pill">推荐分 {{ candidate.score }}</span>
            </div>
            <p class="candidate-note">{{ candidate.recommend_reason }}</p>
            <div class="candidate-tags">
              <span class="candidate-tag" v-for="badge in candidate.badges" :key="badge">{{ badge }}</span>
            </div>
            <button
              class="action-btn primary full"
              @click="confirmDispatchCandidate(candidate)"
              :disabled="dispatchSubmitting === candidate.user_id"
            >
              {{ dispatchSubmitting === candidate.user_id ? '提交中...' : (dispatchPanel.mode === 'reassign' ? '改派给TA' : '派给TA') }}
            </button>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { Icon } from '@iconify/vue'
import { apiFetch } from '@/api/http'
import { useChatStore } from '@/stores/chatStore'
import { useBuildingStore } from '@/stores/buildingStore'
import { useReportExport } from '@/composables/useReportExport'

type WorkOrderItem = any
type Candidate = any
type TabKey = 'all' | 'pending_review' | 'pending_dispatch' | 'auto_rejected' | 'dispatched' | 'pending_close' | 'closed'
type ActionKey = 'approve_pending' | 'reject_pending' | 'override_approve' | 'dispatch' | 'reassign' | 'confirm' | 'close_escalated'

interface OrderAction {
  action: ActionKey
  label: string
  className: string
}

const chatStore = useChatStore()
const buildingStore = useBuildingStore()
const { registerSection, setReportMeta } = useReportExport('workorders')

const loading = ref(false)
const fetchError = ref('')
const allOrders = ref<WorkOrderItem[]>([])
const activeTab = ref<TabKey>('pending_dispatch')
const expandedId = ref<string | null>(null)
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

const tabs: Array<{ label: string; value: TabKey }> = [
  { label: '全部', value: 'all' },
  { label: '待AI审阅', value: 'pending_review' },
  { label: '待派工', value: 'pending_dispatch' },
  { label: 'AI已驳回', value: 'auto_rejected' },
  { label: '执行中', value: 'dispatched' },
  { label: '待关闭', value: 'pending_close' },
  { label: '已关闭', value: 'closed' },
]

const STATUS_LABELS: Record<string, string> = {
  pending_review: '待AI审阅',
  pending_dispatch: '待派工',
  auto_rejected: 'AI已驳回',
  dispatched: '已派单',
  completed: '已修复',
  false_alarm: '误报',
  escalated: '已升级',
  auto_approved: 'AI已批准',
  admin_override_approved: '管理员批准',
  admin_override_rejected: '管理员驳回',
  closed: '已关闭',
}

const EXECUTION_LABELS: Record<string, string> = {
  pending_dispatch: '待派工',
  pending_accept: '待接单',
  accepted: '已接单',
  arrived: '已到场',
  processing: '处理中',
  waiting_support: '待协同',
  overdue: '已超时',
}

const PRIORITY_LABELS: Record<string, string> = {
  high: '高优先',
  medium: '中优先',
  low: '低优先',
}

const filteredOrders = computed(() => allOrders.value.filter(wo => matchesTab(wo, activeTab.value)))
const overdueCount = computed(() => allOrders.value.filter(wo => wo.execution_status === 'overdue' || wo.sla_status === 'overdue').length)

const emptyMessage = computed(() => {
  const map: Record<TabKey, string> = {
    all: '暂无工单记录',
    pending_review: '暂无待AI审阅工单',
    pending_dispatch: '暂无待派工工单',
    auto_rejected: '暂无 AI 驳回工单',
    dispatched: '暂无执行中的工单',
    pending_close: '暂无待关闭工单',
    closed: '暂无已关闭工单',
  }
  return map[activeTab.value]
})

function matchesTab(wo: WorkOrderItem, tab: TabKey) {
  if (tab === 'all') return true
  if (tab === 'pending_close') return ['completed', 'false_alarm', 'escalated'].includes(wo.status)
  if (tab === 'closed') return wo.status === 'closed'
  return wo.status === tab
}

function tabCount(tab: TabKey) {
  return allOrders.value.filter(wo => matchesTab(wo, tab)).length
}

async function fetchOrders() {
  loading.value = true
  fetchError.value = ''
  try {
    const data = await apiFetch<any>('/api/work-orders')
    allOrders.value = data?.work_orders ?? []
  } catch (e: any) {
    fetchError.value = e.message
  } finally {
    loading.value = false
  }
}

function switchTab(tab: TabKey) {
  activeTab.value = tab
  expandedId.value = null
  cancelReject()
}

function toggleExpand(ticketId: string) {
  expandedId.value = expandedId.value === ticketId ? null : ticketId
  cancelReject()
}

function startReject(ticketId: string) {
  rejectingId.value = ticketId
  rejectReason.value = ''
}

function cancelReject() {
  rejectingId.value = null
  rejectReason.value = ''
}

function clearActionResult(ticketId: string) {
  actionResult.value = { ...actionResult.value, [ticketId]: undefined as any }
}

async function runAction(wo: WorkOrderItem, action: ActionKey) {
  const ticketId = wo.ticket_id
  clearActionResult(ticketId)
  actionLoading.value = `${ticketId}:${action}`
  try {
    if (action === 'approve_pending') {
      if (!chatStore.currentSessionId) throw new Error('请先在 AI 控制台建立会话')
      await apiFetch('/api/work-orders/approve', {
        method: 'POST',
        body: JSON.stringify({ session_id: chatStore.currentSessionId, ticket_id: ticketId, approved: true }),
      })
    } else if (action === 'reject_pending') {
      if (!chatStore.currentSessionId) throw new Error('请先在 AI 控制台建立会话')
      await apiFetch('/api/work-orders/approve', {
        method: 'POST',
        body: JSON.stringify({
          session_id: chatStore.currentSessionId,
          ticket_id: ticketId,
          approved: false,
          reason: rejectReason.value || undefined,
        }),
      })
      cancelReject()
    } else if (action === 'override_approve') {
      await apiFetch(`/api/work-orders/${ticketId}/admin-review`, {
        method: 'POST',
        body: JSON.stringify({ action: 'override_approve' }),
      })
    } else if (action === 'dispatch') {
      await openDispatchPanel(wo, 'dispatch')
      actionLoading.value = null
      return
    } else if (action === 'reassign') {
      await openDispatchPanel(wo, 'reassign')
      actionLoading.value = null
      return
    } else if (action === 'confirm') {
      await apiFetch(`/api/work-orders/${ticketId}/admin-review`, {
        method: 'POST',
        body: JSON.stringify({ action: 'confirm' }),
      })
    } else if (action === 'close_escalated') {
      await apiFetch(`/api/work-orders/${ticketId}/admin-review`, {
        method: 'POST',
        body: JSON.stringify({ action: 'close_escalated' }),
      })
    }

    actionResult.value = {
      ...actionResult.value,
      [ticketId]: { type: 'success', message: '操作已执行，列表已刷新' },
    }
    await fetchOrders()
  } catch (e: any) {
    actionResult.value = {
      ...actionResult.value,
      [ticketId]: { type: 'error', message: e.message || '操作失败' },
    }
  } finally {
    actionLoading.value = null
  }
}

async function openDispatchPanel(wo: WorkOrderItem, mode: 'dispatch' | 'reassign') {
  const data = await apiFetch<any>(`/api/work-orders/${wo.ticket_id}/dispatch-candidates`)
  dispatchPanel.value = {
    visible: true,
    mode,
    ticketId: wo.ticket_id,
    dispatchId: wo.current_dispatch?.id ?? null,
    requirement: data?.requirement ?? null,
    candidates: data?.candidates ?? [],
  }
}

function closeDispatchPanel() {
  if (dispatchSubmitting.value) return
  dispatchPanel.value = {
    visible: false,
    mode: 'dispatch',
    ticketId: null,
    dispatchId: null,
    requirement: null,
    candidates: [],
  }
}

async function confirmDispatchCandidate(candidate: Candidate) {
  if (!dispatchPanel.value.ticketId) return
  dispatchSubmitting.value = candidate.user_id
  try {
    if (dispatchPanel.value.mode === 'reassign' && dispatchPanel.value.dispatchId) {
      await apiFetch(`/api/dispatch-tasks/${dispatchPanel.value.dispatchId}/reassign`, {
        method: 'POST',
        body: JSON.stringify({
          assigned_to: candidate.user_id,
          reason: `调度改派：${candidate.recommend_reason}`,
          dispatch_mode: 'reassigned',
        }),
      })
    } else {
      await apiFetch(`/api/work-orders/${dispatchPanel.value.ticketId}/dispatch`, {
        method: 'POST',
        body: JSON.stringify({
          assigned_to: candidate.user_id,
          dispatch_mode: 'manual',
          selection_reason: candidate.recommend_reason,
        }),
      })
    }
    closeDispatchPanel()
    await fetchOrders()
  } finally {
    dispatchSubmitting.value = null
  }
}

function actionsForOrder(wo: WorkOrderItem): OrderAction[] {
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
    return [{ action: 'reassign', label: '改派', className: 'secondary' }]
  }
  if (['completed', 'false_alarm'].includes(wo.status)) {
    return [{ action: 'confirm', label: '确认关闭', className: 'secondary' }]
  }
  if (wo.status === 'escalated') {
    return [{ action: 'close_escalated', label: '关闭升级', className: 'secondary' }]
  }
  return []
}

function detailRows(wo: WorkOrderItem) {
  return [
    { label: '工单 ID', value: wo.ticket_id, cls: 'mono accent' },
    { label: '楼宇', value: buildingName(wo.building_id) },
    { label: '当前状态', value: STATUS_LABELS[wo.status] ?? wo.status },
    { label: '执行进度', value: EXECUTION_LABELS[wo.execution_status] ?? wo.execution_status ?? '—' },
    { label: '责任人', value: wo.assigned_to_name || '未派工' },
    { label: '责任班组', value: wo.assigned_team_name || '—' },
    { label: 'SLA', value: wo.sla_status ? `${wo.sla_status}${wo.sla_minutes_left != null ? ` · 剩余 ${wo.sla_minutes_left} 分钟` : ''}` : '—' },
    { label: 'AI结论', value: wo.ai_reason || '—', cls: 'wrap' },
    { label: '派工建议', value: wo.dispatch_profile?.summary || wo.suggested_action || '—', cls: 'wrap warning-text' },
    { label: '最新进展', value: wo.latest_progress_note || wo.dispatch_blocked_reason || '—', cls: 'wrap' },
  ]
}

function timelineRows(wo: WorkOrderItem) {
  const events = wo.current_dispatch?.events ?? []
  if (events.length) {
    return events.map((event: any) => ({
      time: formatTime(event.created_at),
      label: dispatchEventLabel(event.event_type),
      note: event.payload?.notes || event.payload?.reason || event.payload?.result || event.payload?.selection_reason || '',
    }))
  }
  return [
    wo.dispatch_at ? { time: formatTime(wo.dispatch_at), label: '工单已派发', note: wo.assigned_to_name ? `已派给 ${wo.assigned_to_name}` : '' } : null,
    wo.accepted_at ? { time: formatTime(wo.accepted_at), label: '已接单', note: '' } : null,
    wo.arrived_at ? { time: formatTime(wo.arrived_at), label: '已到场', note: '' } : null,
    wo.processing_started_at ? { time: formatTime(wo.processing_started_at), label: '开始处理', note: wo.worker_notes || '' } : null,
    wo.worker_feedback_at ? { time: formatTime(wo.worker_feedback_at), label: '提交反馈', note: wo.worker_result || '' } : null,
  ].filter(Boolean)
}

function dispatchEventLabel(eventType: string) {
  const labels: Record<string, string> = {
    assigned: '人工派工',
    auto_assigned: '自动派工',
    accepted: '维修员接单',
    arrived: '维修员到场',
    started: '开始处理',
    support_requested: '申请协同',
    rejected: '维修员拒单',
    transferred: '调度改派',
    completed: '处理完成',
    escalated: '升级处理',
  }
  return labels[eventType] || eventType
}

function buildingName(id: string) {
  return id ? buildingStore.getBuildingName(id) : '—'
}

function formatTime(iso: string) {
  if (!iso) return '—'
  try {
    return new Date(iso).toLocaleString('zh-CN', {
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
    })
  } catch {
    return iso
  }
}

function statusCardClass(wo: WorkOrderItem) {
  return {
    'status-pending-review': wo.status === 'pending_review',
    'status-pending-dispatch': wo.status === 'pending_dispatch',
    'status-dispatched': wo.status === 'dispatched',
    'status-rejected': wo.status === 'auto_rejected',
    'status-resolved': ['completed', 'false_alarm', 'escalated', 'closed'].includes(wo.status),
  }
}

function statusChipClass(status: string) {
  return {
    'chip-pending-review': status === 'pending_review',
    'chip-pending-dispatch': status === 'pending_dispatch',
    'chip-dispatched': status === 'dispatched',
    'chip-rejected': status === 'auto_rejected',
    'chip-resolved': ['completed', 'false_alarm', 'escalated', 'closed'].includes(status),
  }
}

function executionChipClass(status: string) {
  return {
    'exec-pending': ['pending_dispatch', 'pending_accept'].includes(status),
    'exec-active': ['accepted', 'arrived', 'processing'].includes(status),
    'exec-support': status === 'waiting_support',
    'exec-danger': status === 'overdue',
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
      status: STATUS_LABELS[wo.status] ?? wo.status,
      execution: EXECUTION_LABELS[wo.execution_status] ?? wo.execution_status ?? '—',
      assignee: wo.assigned_to_name || '未派工',
      created_at: formatTime(wo.created_at),
    })),
  })
}, { deep: true })

onMounted(fetchOrders)
</script>

<style scoped>
.workorders { padding: 24px; }
.page-header { margin-bottom: 20px; }
.page-header h1 { font-size: 22px; font-weight: 700; margin-bottom: 4px; display: flex; align-items: center; gap: 8px; }
.subtitle { color: var(--text-secondary); font-size: 13px; }
.toolbar { display: flex; justify-content: space-between; align-items: center; gap: 16px; margin-bottom: 16px; }
.tab-group { display: flex; flex-wrap: wrap; gap: 6px; }
.tab-btn, .refresh-btn, .link-btn { background: none; border: 1px solid var(--border); border-radius: 8px; color: var(--text-secondary); font-size: 13px; padding: 8px 14px; cursor: pointer; transition: all 0.2s; }
.tab-btn { display: flex; align-items: center; gap: 6px; }
.tab-btn.active { background: var(--accent-glow); border-color: var(--border-accent); color: var(--accent); font-weight: 600; }
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
.order-list { display: flex; flex-direction: column; gap: 10px; }
.order-card { background: var(--bg-panel); border: 1px solid var(--border); border-radius: 12px; overflow: hidden; box-shadow: var(--card-shadow); }
.order-card.status-pending-review { border-left: 4px solid var(--warning); }
.order-card.status-pending-dispatch { border-left: 4px solid var(--accent); }
.order-card.status-dispatched { border-left: 4px solid var(--success); }
.order-card.status-rejected { border-left: 4px solid var(--danger); }
.order-card.status-resolved { border-left: 4px solid var(--text-muted); }
.card-header { display: flex; justify-content: space-between; align-items: center; gap: 14px; padding: 16px; cursor: pointer; }
.card-header-left { display: flex; align-items: center; gap: 12px; min-width: 0; }
.priority-badge { font-size: 11px; font-weight: 700; padding: 4px 9px; border-radius: 999px; white-space: nowrap; }
.p-low { background: rgba(74,222,128,0.15); color: var(--success); }
.p-medium { background: rgba(251,191,36,0.15); color: var(--warning); }
.p-high { background: rgba(248,113,113,0.15); color: var(--danger); }
.card-title-block { min-width: 0; }
.card-title { font-size: 14px; font-weight: 700; margin-bottom: 4px; }
.card-meta { font-size: 12px; color: var(--text-muted); }
.card-header-right { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; justify-content: flex-end; }
.status-chip, .execution-chip { font-size: 11px; font-weight: 600; border-radius: 999px; padding: 4px 10px; }
.chip-pending-review { background: rgba(251,191,36,0.15); color: var(--warning); }
.chip-pending-dispatch { background: rgba(59,130,246,0.12); color: var(--accent); }
.chip-dispatched { background: rgba(16,185,129,0.12); color: var(--success); }
.chip-rejected { background: rgba(248,113,113,0.12); color: var(--danger); }
.chip-resolved { background: rgba(148,163,184,0.15); color: var(--text-muted); }
.exec-pending { background: rgba(59,130,246,0.1); color: var(--accent); }
.exec-active { background: rgba(16,185,129,0.1); color: var(--success); }
.exec-support { background: rgba(124,58,237,0.12); color: #7c3aed; }
.exec-danger { background: rgba(248,113,113,0.12); color: var(--danger); }
.card-body { border-top: 1px solid var(--border); padding: 16px; background: var(--bg-card); }
.detail-grid { display: flex; flex-direction: column; gap: 0; }
.detail-row { display: grid; grid-template-columns: 100px 1fr; gap: 10px; padding: 7px 0; border-bottom: 1px solid var(--border); font-size: 13px; }
.detail-row:last-child { border-bottom: none; }
.detail-label { color: var(--text-muted); font-size: 12px; }
.detail-val.mono { font-family: monospace; }
.detail-val.accent { color: var(--accent); }
.detail-val.wrap { white-space: pre-wrap; }
.detail-val.warning-text { color: var(--warning); }
.timeline-block { margin-top: 16px; padding-top: 16px; border-top: 1px solid var(--border); }
.section-title { font-size: 13px; font-weight: 700; margin-bottom: 10px; }
.timeline-item { display: flex; gap: 12px; padding: 8px 0; }
.timeline-dot { width: 10px; height: 10px; border-radius: 50%; background: var(--accent); margin-top: 6px; flex-shrink: 0; }
.timeline-content { display: flex; flex-direction: column; gap: 4px; }
.timeline-time { font-size: 11px; color: var(--text-muted); }
.timeline-label { font-size: 13px; font-weight: 600; }
.timeline-note { font-size: 12px; color: var(--text-secondary); }
.action-bar { display: flex; gap: 8px; align-items: center; margin-top: 16px; padding-top: 14px; border-top: 1px solid var(--border); }
.action-btn { border: none; border-radius: 8px; font-size: 13px; font-weight: 600; padding: 8px 16px; cursor: pointer; }
.action-btn.primary { background: var(--accent); color: white; }
.action-btn.secondary { background: rgba(59,130,246,0.12); color: var(--accent); }
.action-btn.danger { background: rgba(248,113,113,0.12); color: var(--danger); }
.action-btn.full { width: 100%; margin-top: 12px; }
.action-btn:disabled { opacity: 0.6; cursor: not-allowed; }
.reject-area { display: flex; gap: 8px; align-items: center; margin-top: 12px; }
.reject-input { flex: 1; background: var(--bg-panel); border: 1px solid var(--border); border-radius: 8px; color: var(--text-primary); padding: 8px 12px; }
.btn-reject-confirm, .btn-cancel { border-radius: 8px; font-size: 13px; padding: 8px 14px; cursor: pointer; }
.btn-reject-confirm { border: none; background: var(--danger); color: white; }
.btn-cancel { border: 1px solid var(--border); background: none; color: var(--text-secondary); }
.action-result { margin-top: 12px; padding: 10px 12px; border-radius: 8px; font-size: 13px; }
.action-result.success { background: rgba(74,222,128,0.1); color: var(--success); border: 1px solid rgba(74,222,128,0.3); }
.action-result.error { background: rgba(248,113,113,0.1); color: var(--danger); border: 1px solid rgba(248,113,113,0.3); }
.empty-state { display: flex; flex-direction: column; align-items: center; gap: 8px; padding: 100px 0; color: var(--text-muted); }
.empty-sub { font-size: 12px; }
.dispatch-mask { position: fixed; inset: 0; background: rgba(15, 23, 42, 0.4); display: flex; align-items: center; justify-content: center; z-index: 30; }
.dispatch-sheet { width: min(760px, calc(100vw - 40px)); max-height: 80vh; overflow: auto; background: var(--bg-panel); border: 1px solid var(--border); border-radius: 16px; padding: 20px; box-shadow: var(--card-shadow-hover); }
.dispatch-header { display: flex; justify-content: space-between; gap: 16px; align-items: flex-start; margin-bottom: 14px; }
.dispatch-title { font-size: 16px; font-weight: 700; margin-bottom: 4px; }
.dispatch-subtitle { font-size: 12px; color: var(--text-muted); }
.dispatch-requirement { display: flex; flex-wrap: wrap; gap: 8px; margin-bottom: 14px; }
.req-chip, .candidate-tag, .score-pill { border-radius: 999px; padding: 4px 10px; font-size: 11px; }
.req-chip { background: rgba(59,130,246,0.1); color: var(--accent); }
.score-pill { background: rgba(16,185,129,0.1); color: var(--success); }
.candidate-list { display: grid; gap: 12px; }
.candidate-card { border: 1px solid var(--border); border-radius: 12px; padding: 14px; background: var(--bg-card); }
.candidate-head { display: flex; justify-content: space-between; gap: 12px; align-items: flex-start; }
.candidate-name { font-size: 14px; font-weight: 700; margin-bottom: 4px; }
.candidate-meta { font-size: 12px; color: var(--text-muted); }
.candidate-note { font-size: 12px; color: var(--text-secondary); margin: 10px 0; }
.candidate-tags { display: flex; flex-wrap: wrap; gap: 6px; }
.candidate-tag { background: rgba(148,163,184,0.12); color: var(--text-secondary); }
.slide-enter-active, .slide-leave-active { transition: all 0.2s ease; }
.slide-enter-from, .slide-leave-to { opacity: 0; transform: translateY(-8px); }
</style>
