<template>
  <div class="workorders">
    <header class="page-header">
      <h1><Icon icon="mdi:clipboard-list" width="22" class="page-icon" /> 工单管理</h1>
      <span class="subtitle">人机协同 · 审批派单 · HITL 闭环</span>
    </header>

    <!-- 无 Session 警告：审批需要 AI 会话 -->
    <div class="session-warn" v-if="!chatStore.sessionId">
      <span class="warn-icon"><Icon icon="mdi:alert" width="18" /></span>
      <div>
        <p class="warn-title">审批功能需要先建立 AI 会话</p>
        <p class="warn-sub">请在右侧控制台向 AI 发送任意消息，建立会话后即可在此页面审批工单。</p>
      </div>
    </div>

    <!-- 状态筛选 + 刷新 -->
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
          <span class="tab-count" v-if="tab.value === 'pending_approval'">{{ pendingCount }}</span>
        </button>
      </div>
      <button class="refresh-btn" @click="fetchOrders" :disabled="loading">
        <Icon :icon="loading ? 'mdi:loading' : 'mdi:refresh'" width="14" class="btn-icon" />
        {{ loading ? '刷新中...' : '刷新' }}
      </button>
    </div>

    <!-- 加载 / 错误 -->
    <div v-if="loading" class="loading-bar">加载工单列表...</div>
    <div v-if="fetchError" class="error-bar"><Icon icon="mdi:alert" width="14" class="bar-icon" /> {{ fetchError }}</div>

    <!-- 工单列表 -->
    <div v-if="!loading && filteredOrders.length > 0" class="order-list">
      <div
        class="order-card"
        v-for="wo in filteredOrders"
        :key="wo.ticket_id"
        :class="statusCardClass(wo.status)"
      >
        <!-- 卡片头部 -->
        <div class="card-header" @click="toggleExpand(wo.ticket_id)">
          <div class="card-header-left">
            <span class="priority-badge" :class="'p-' + (wo.priority ?? 'medium').toLowerCase()">
              {{ wo.priority ?? 'Medium' }}
            </span>
            <div class="card-title-block">
              <p class="card-title">{{ wo.issue_description ?? wo.ticket_id }}</p>
              <p class="card-meta">
                工单 {{ wo.ticket_id }} · 设备 {{ wo.device_id ?? '—' }} · {{ buildingName(wo.building_id) }}
                · {{ formatTime(wo.created_at) }}
              </p>
            </div>
          </div>
          <div class="card-header-right">
            <span class="status-chip" :class="statusChipClass(wo.status)">
              {{ STATUS_LABELS[wo.status] ?? wo.status }}
            </span>
            <span class="expand-btn">{{ expandedId === wo.ticket_id ? '▲' : '▼' }}</span>
          </div>
        </div>

        <!-- 展开详情 -->
        <Transition name="slide">
          <div class="card-body" v-if="expandedId === wo.ticket_id">
            <div class="detail-grid">
              <div class="detail-row" v-for="row in detailRows(wo)" :key="row.label">
                <span class="detail-label">{{ row.label }}</span>
                <span class="detail-val" :class="row.cls">{{ row.value }}</span>
              </div>
            </div>

            <!-- 审批操作（仅 pending_approval 状态显示） -->
            <div class="action-bar" v-if="wo.status === 'pending_approval'">
              <div v-if="!chatStore.sessionId" class="action-no-session">
                <Icon icon="mdi:alert" width="14" class="bar-icon" /> 需先在 AI 控制台建立会话才能审批
              </div>
              <template v-else>
                <button
                  class="btn-approve"
                  @click="approve(wo.ticket_id, true)"
                  :disabled="approving === wo.ticket_id"
                >
                  <Icon icon="mdi:check-circle" width="14" class="btn-icon" />
                  {{ approving === wo.ticket_id ? '处理中...' : '批准派单' }}
                </button>
                <button
                  class="btn-reject"
                  @click="startReject(wo.ticket_id)"
                  :disabled="approving === wo.ticket_id"
                >
                  <Icon icon="mdi:close-circle" width="14" class="btn-icon" /> 驳回
                </button>
              </template>
            </div>

            <!-- 驳回原因输入框 -->
            <div class="reject-area" v-if="rejectingId === wo.ticket_id">
              <input
                v-model="rejectReason"
                placeholder="驳回原因（可选）"
                @keyup.enter="approve(wo.ticket_id, false)"
                class="reject-input"
              />
              <button class="btn-reject-confirm" @click="approve(wo.ticket_id, false)">
                确认驳回
              </button>
              <button class="btn-cancel" @click="rejectingId = null; rejectReason = ''">
                取消
              </button>
            </div>

            <!-- 操作结果提示 -->
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

    <!-- 空状态 -->
    <div v-if="!loading && filteredOrders.length === 0 && !fetchError" class="empty-state">
      <p class="empty-icon"><Icon icon="mdi:clipboard-list" width="40" /></p>
      <p>{{ emptyMessage }}</p>
      <p class="empty-sub">可通过右侧 AI 控制台触发故障诊断，AI 将自动生成工单待审批。</p>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { Icon } from '@iconify/vue'
import { apiFetch } from '@/api/http'
import { useChatStore } from '@/stores/chatStore'
import { useBuildingStore } from '@/stores/buildingStore'

const chatStore = useChatStore()
const buildingStore = useBuildingStore()

// ── 数据 ──────────────────────────────────────────
const loading = ref(false)
const fetchError = ref('')
const allOrders = ref<any[]>([])

const activeTab = ref<string>('all')
const expandedId = ref<string | null>(null)
const approving = ref<string | null>(null)
const rejectingId = ref<string | null>(null)
const rejectReason = ref('')
const actionResult = ref<Record<string, { type: 'success' | 'error'; message: string }>>({})

const tabs = [
  { label: '全部', value: 'all' },
  { label: '待审批', value: 'pending_approval' },
  { label: '已批准', value: 'approved' },
  { label: '已驳回', value: 'rejected' },
]

const STATUS_LABELS: Record<string, string> = {
  pending_approval: '待审批',
  approved: '已批准',
  rejected: '已驳回',
}

// ── 计算 ──────────────────────────────────────────
const filteredOrders = computed(() => {
  if (activeTab.value === 'all') return allOrders.value
  return allOrders.value.filter(o => o.status === activeTab.value)
})

const pendingCount = computed(() =>
  allOrders.value.filter(o => o.status === 'pending_approval').length,
)

const emptyMessage = computed(() => {
  const map: Record<string, string> = {
    all: '暂无工单记录',
    pending_approval: '暂无待审批工单',
    approved: '暂无已批准工单',
    rejected: '暂无已驳回工单',
  }
  return map[activeTab.value] ?? '暂无数据'
})

// ── 获取工单列表 ──────────────────────────────────
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

onMounted(fetchOrders)

// ── 交互 ──────────────────────────────────────────
function switchTab(val: string) {
  activeTab.value = val
  expandedId.value = null
}

function toggleExpand(id: string) {
  expandedId.value = expandedId.value === id ? null : id
  rejectingId.value = null
  rejectReason.value = ''
}

function startReject(id: string) {
  rejectingId.value = id
  rejectReason.value = ''
}

// ── 审批 ──────────────────────────────────────────
async function approve(ticketId: string, approved: boolean) {
  if (!chatStore.sessionId) return

  approving.value = ticketId
  actionResult.value = { ...actionResult.value, [ticketId]: undefined as any }

  try {
    const result = await apiFetch<any>('/api/work-orders/approve', {
      method: 'POST',
      body: JSON.stringify({
        session_id: chatStore.sessionId,
        ticket_id: ticketId,
        approved,
        reason: approved ? undefined : (rejectReason.value || undefined),
      }),
    })

    // 更新本地状态，不需要重新请求
    const order = allOrders.value.find(o => o.ticket_id === ticketId)
    if (order) {
      order.status = approved ? 'approved' : 'rejected'
      if (!approved) order.reject_reason = rejectReason.value
    }

    actionResult.value = {
      ...actionResult.value,
      [ticketId]: { type: 'success', message: result.message },
    }
    rejectingId.value = null
    rejectReason.value = ''
  } catch (e: any) {
    actionResult.value = {
      ...actionResult.value,
      [ticketId]: { type: 'error', message: e.message },
    }
  } finally {
    approving.value = null
  }
}

// ── 工具函数 ──────────────────────────────────────
function buildingName(id: string): string {
  if (!id) return '—'
  return buildingStore.getBuildingName(id)
}

function formatTime(iso: string): string {
  if (!iso) return '—'
  try {
    return new Date(iso).toLocaleString('zh-CN', {
      month: '2-digit', day: '2-digit',
      hour: '2-digit', minute: '2-digit',
    })
  } catch {
    return iso
  }
}

function statusCardClass(status: string): Record<string, boolean> {
  return {
    'status-pending': status === 'pending_approval',
    'status-approved': status === 'approved',
    'status-rejected': status === 'rejected',
  }
}

function statusChipClass(status: string): Record<string, boolean> {
  return {
    'chip-pending':  status === 'pending_approval',
    'chip-approved': status === 'approved',
    'chip-rejected': status === 'rejected',
  }
}

function detailRows(wo: any) {
  return [
    { label: '工单 ID',  value: wo.ticket_id,          cls: 'mono accent' },
    { label: '设备 ID',  value: wo.device_id ?? '—',   cls: 'mono' },
    { label: '楼宇',     value: buildingName(wo.building_id) },
    { label: '优先级',   value: wo.priority ?? '—' },
    { label: '问题描述', value: wo.issue_description ?? '—' },
    { label: '建议操作', value: wo.suggested_action ?? '—',   cls: 'warning-text' },
    { label: '状态',     value: STATUS_LABELS[wo.status] ?? wo.status },
    { label: '创建时间', value: formatTime(wo.created_at),    cls: 'muted' },
    wo.reject_reason ? { label: '驳回原因', value: wo.reject_reason, cls: 'danger-text' } : null,
  ].filter(Boolean)
}
</script>

<style scoped>
.workorders { padding: 24px; }
.page-header { margin-bottom: 20px; }
.page-header h1 { font-size: 22px; font-weight: 700; margin-bottom: 4px; }
.subtitle { color: var(--text-secondary); font-size: 13px; }

/* 无 Session 警告 */
.session-warn {
  display: flex;
  gap: 12px;
  align-items: flex-start;
  background: rgba(251,191,36,0.08);
  border: 1px solid rgba(251,191,36,0.35);
  border-radius: 10px;
  padding: 14px 16px;
  margin-bottom: 20px;
  font-size: 13px;
}
.warn-icon { display: flex; align-items: center; color: var(--warning); flex-shrink: 0; }
.warn-title { font-weight: 600; color: var(--warning); margin-bottom: 4px; }
.warn-sub { font-size: 12px; color: var(--text-secondary); }

/* 工具栏 */
.toolbar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 16px;
}

.tab-group { display: flex; gap: 4px; }

.tab-btn {
  background: none;
  border: 1px solid var(--border);
  border-radius: 6px;
  color: var(--text-secondary);
  font-size: 13px;
  padding: 6px 14px;
  cursor: pointer;
  transition: all 0.2s;
  display: flex;
  align-items: center;
  gap: 6px;
}
.tab-btn:hover { background: var(--bg-hover); }
.tab-btn.active {
  background: var(--accent-glow);
  border-color: var(--border-accent);
  color: var(--accent);
  font-weight: 600;
}

.tab-count {
  background: var(--warning);
  color: #000;
  font-size: 10px;
  font-weight: 700;
  padding: 1px 6px;
  border-radius: 10px;
  min-width: 18px;
  text-align: center;
}

.refresh-btn {
  background: none;
  border: 1px solid var(--border);
  border-radius: 6px;
  color: var(--text-secondary);
  font-size: 12px;
  padding: 6px 12px;
  cursor: pointer;
  transition: all 0.2s;
}
.refresh-btn:hover { border-color: var(--accent); color: var(--accent); }
.refresh-btn:disabled { opacity: 0.5; cursor: not-allowed; }

/* 状态条 */
.loading-bar {
  background: var(--accent-glow);
  border: 1px solid var(--border-accent);
  border-radius: 8px;
  padding: 10px 16px;
  color: var(--accent);
  font-size: 13px;
  margin-bottom: 12px;
}
.error-bar {
  background: rgba(248,113,113,0.08);
  border: 1px solid rgba(248,113,113,0.22);
  border-radius: 8px;
  padding: 10px 16px;
  color: var(--danger);
  font-size: 13px;
  margin-bottom: 12px;
}

/* 工单卡片 */
.order-list { display: flex; flex-direction: column; gap: 8px; }

.order-card {
  background: var(--bg-panel);
  border: 1px solid var(--border);
  border-radius: 10px;
  overflow: hidden;
  transition: box-shadow 0.2s, border-color 0.2s;
  box-shadow: var(--card-shadow);
}
.order-card:hover {
  box-shadow: var(--card-shadow-hover);
}
.order-card.status-pending  { border-left: 4px solid var(--warning); }
.order-card.status-approved { border-left: 4px solid var(--success); }
.order-card.status-rejected { border-left: 4px solid var(--text-muted); }

.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 14px 16px;
  cursor: pointer;
  user-select: none;
  gap: 12px;
}
.card-header:hover { background: var(--bg-hover); }

.card-header-left {
  display: flex;
  align-items: center;
  gap: 12px;
  flex: 1;
  min-width: 0;
}

.priority-badge {
  font-size: 11px;
  font-weight: 700;
  padding: 3px 8px;
  border-radius: 4px;
  flex-shrink: 0;
  text-transform: uppercase;
}
.p-low      { background: rgba(74,222,128,0.15);  color: var(--success); }
.p-medium   { background: rgba(251,191,36,0.15);  color: var(--warning); }
.p-high     { background: rgba(248,113,113,0.15); color: var(--danger); }
.p-critical { background: rgba(248,113,113,0.25); color: var(--danger); }

.card-title-block { min-width: 0; }
.card-title { font-size: 13px; font-weight: 600; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; margin-bottom: 3px; }
.card-meta  { font-size: 11px; color: var(--text-muted); }

.card-header-right { display: flex; align-items: center; gap: 10px; flex-shrink: 0; }

.status-chip {
  font-size: 11px;
  padding: 3px 10px;
  border-radius: 10px;
  font-weight: 600;
}
.chip-pending  { background: rgba(251,191,36,0.15);  color: var(--warning); }
.chip-approved { background: rgba(74,222,128,0.15);  color: var(--success); }
.chip-rejected { background: rgba(148,163,184,0.15); color: var(--text-muted); }

.expand-btn { color: var(--text-muted); font-size: 11px; }

/* 展开详情 */
.card-body {
  border-top: 1px solid var(--border);
  padding: 16px;
  background: var(--bg-card);
}

.detail-grid { display: flex; flex-direction: column; gap: 0; margin-bottom: 16px; }

.detail-row {
  display: grid;
  grid-template-columns: 90px 1fr;
  gap: 8px;
  padding: 6px 0;
  border-bottom: 1px solid var(--border);
  font-size: 13px;
}
.detail-row:last-child { border-bottom: none; }

.detail-label { color: var(--text-muted); font-size: 12px; align-self: center; }
.detail-val { color: var(--text-primary); word-break: break-all; }
.detail-val.mono        { font-family: monospace; }
.detail-val.accent      { color: var(--accent); }
.detail-val.muted       { color: var(--text-muted); }
.detail-val.warning-text { color: var(--warning); }
.detail-val.danger-text  { color: var(--danger); }

/* 操作区 */
.action-bar {
  display: flex;
  gap: 8px;
  align-items: center;
  padding-top: 14px;
  border-top: 1px solid var(--border);
}

.action-no-session {
  font-size: 12px;
  color: var(--warning);
}

.btn-approve {
  background: var(--success);
  border: none;
  border-radius: 6px;
  color: #000;
  font-size: 13px;
  font-weight: 600;
  padding: 8px 20px;
  cursor: pointer;
  transition: opacity 0.2s;
}
.btn-approve:hover { opacity: 0.85; }
.btn-approve:disabled { opacity: 0.5; cursor: not-allowed; }

.btn-reject {
  background: none;
  border: 1px solid var(--danger);
  border-radius: 6px;
  color: var(--danger);
  font-size: 13px;
  font-weight: 600;
  padding: 8px 20px;
  cursor: pointer;
  transition: all 0.2s;
}
.btn-reject:hover { background: rgba(248,113,113,0.1); }
.btn-reject:disabled { opacity: 0.5; cursor: not-allowed; }

.reject-area {
  display: flex;
  gap: 8px;
  align-items: center;
  margin-top: 10px;
}

.reject-input {
  flex: 1;
  background: var(--bg-panel);
  border: 1px solid var(--border);
  border-radius: 6px;
  color: var(--text-primary);
  font-size: 13px;
  padding: 7px 12px;
  transition: border-color 0.2s;
}
.reject-input:focus { outline: none; border-color: var(--danger); }

.btn-reject-confirm {
  background: var(--danger);
  border: none;
  border-radius: 6px;
  color: #fff;
  font-size: 13px;
  font-weight: 600;
  padding: 7px 16px;
  cursor: pointer;
}

.btn-cancel {
  background: none;
  border: 1px solid var(--border);
  border-radius: 6px;
  color: var(--text-secondary);
  font-size: 13px;
  padding: 7px 12px;
  cursor: pointer;
}

.action-result {
  margin-top: 10px;
  padding: 8px 12px;
  border-radius: 6px;
  font-size: 13px;
}
.action-result.success { background: rgba(74,222,128,0.1); color: var(--success); border: 1px solid rgba(74,222,128,0.3); }
.action-result.error   { background: rgba(248,113,113,0.1); color: var(--danger);  border: 1px solid rgba(248,113,113,0.3); }

/* 空状态 */
.empty-state {
  background: var(--bg-panel);
  border: 2px dashed var(--border);
  border-radius: 12px;
  padding: 48px 20px;
  text-align: center;
  color: var(--text-secondary);
  font-size: 14px;
}
.empty-icon { display: flex; justify-content: center; color: var(--text-muted); margin-bottom: 12px; }
.empty-sub  { font-size: 12px; color: var(--text-muted); margin-top: 8px; line-height: 1.7; }

/* 展开动画 */
.slide-enter-active, .slide-leave-active { transition: all 0.25s ease; overflow: hidden; }
.slide-enter-from, .slide-leave-to { opacity: 0; max-height: 0; }
.slide-enter-to, .slide-leave-from { opacity: 1; max-height: 600px; }

.page-icon { vertical-align: middle; margin-right: 6px; }
.bar-icon  { vertical-align: middle; flex-shrink: 0; }
.btn-icon  { vertical-align: middle; }

.refresh-btn, .btn-approve, .btn-reject {
  display: inline-flex;
  align-items: center;
  gap: 5px;
}

.action-result { display: flex; align-items: center; gap: 6px; }
</style>
