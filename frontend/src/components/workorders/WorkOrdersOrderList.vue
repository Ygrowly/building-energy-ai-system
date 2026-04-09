<template>
  <div class="order-list">
    <div
      class="order-card"
      v-for="wo in orders"
      :key="wo.ticket_id"
      :class="statusCardClassValue(wo)"
    >
      <div class="card-header" @click="$emit('toggle-expand', wo.ticket_id)">
        <div class="card-header-left">
          <span class="priority-badge" :class="'p-' + (wo.priority ?? 'medium').toLowerCase()">
            {{ priorityLabels[wo.priority] ?? wo.priority ?? '普通' }}
          </span>
          <div class="card-title-block">
            <p class="card-title">{{ wo.issue_description || wo.ticket_id }}</p>
            <p class="card-meta">
              工单 {{ wo.ticket_id }} · {{ buildingNameValue(wo.building_id) }} · {{ formatTimeValue(wo.created_at) }}
            </p>
          </div>
        </div>
        <div class="card-header-right">
          <span class="status-chip" :class="statusChipClassValue(wo.status)">
            {{ statusLabels[wo.status] ?? wo.status }}
          </span>
          <span
            v-if="executionStatusForOrderValue(wo)"
            class="execution-chip"
            :class="executionChipClassValue(executionStatusForOrderValue(wo))"
          >
            {{ executionLabels[executionStatusForOrderValue(wo)] ?? executionStatusForOrderValue(wo) }}
          </span>
          <span class="expand-btn">{{ expandedId === wo.ticket_id ? '▲' : '▼' }}</span>
        </div>
      </div>

      <Transition name="slide">
        <div class="card-body" v-if="expandedId === wo.ticket_id">
          <div class="detail-grid">
            <div class="detail-row" v-for="row in detailRowsValue(wo)" :key="row.label">
              <span class="detail-label">{{ row.label }}</span>
              <span class="detail-val" :class="row.cls">{{ row.value }}</span>
            </div>
          </div>

          <div class="timeline-block" v-if="timelineRowsValue(wo).length || isTimelineLoadingValue(wo.ticket_id) || timelineErrorValue(wo.ticket_id)">
            <p class="section-title">执行时间线</p>
            <p v-if="isTimelineLoadingValue(wo.ticket_id)" class="timeline-hint">加载完整派工历史...</p>
            <p v-if="timelineErrorValue(wo.ticket_id)" class="timeline-hint error">{{ timelineErrorValue(wo.ticket_id) }}</p>
            <div class="timeline-item" v-for="item in timelineRowsValue(wo)" :key="item.time + item.label">
              <span class="timeline-dot" />
              <div class="timeline-content">
                <span class="timeline-time">{{ item.time }}</span>
                <span class="timeline-label">{{ item.label }}</span>
                <span v-if="item.note" class="timeline-note">{{ item.note }}</span>
              </div>
            </div>
          </div>

          <div class="action-bar" v-if="actionsForOrderValue(wo).length">
            <template v-for="action in actionsForOrderValue(wo)" :key="action.action">
              <button
                v-if="action.action !== 'reject_pending'"
                class="action-btn"
                :class="action.className"
                @click="$emit('run-action', wo, action.action)"
                :disabled="actionLoading === wo.ticket_id + ':' + action.action"
              >
                {{ actionLoading === wo.ticket_id + ':' + action.action ? '处理中...' : action.label }}
              </button>
              <button
                v-else
                class="action-btn danger"
                @click="$emit('start-reject', wo.ticket_id)"
                :disabled="actionLoading === wo.ticket_id + ':' + action.action"
              >
                驳回
              </button>
            </template>
          </div>

          <div class="reject-area" v-if="rejectingId === wo.ticket_id">
            <input
              :value="rejectReason"
              placeholder="输入驳回原因"
              @input="$emit('update-reject-reason', ($event.target as HTMLInputElement).value)"
              @keyup.enter="$emit('run-action', wo, 'reject_pending')"
              class="reject-input"
            />
            <button class="btn-reject-confirm" @click="$emit('run-action', wo, 'reject_pending')">确认驳回</button>
            <button class="btn-cancel" @click="$emit('cancel-reject')">取消</button>
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
</template>

<script setup lang="ts">
import { Icon } from '@iconify/vue'
import { PropType } from 'vue'

defineEmits<{
  'toggle-expand': [ticketId: string]
  'run-action': [wo: any, action: string]
  'start-reject': [ticketId: string]
  'update-reject-reason': [reason: string]
  'cancel-reject': []
}>()

const props = defineProps({
  orders: {
    type: Array as PropType<any[]>,
    required: true,
  },
  expandedId: {
    type: String as PropType<string | null>,
    default: null,
  },
  actionLoading: {
    type: String as PropType<string | null>,
    default: null,
  },
  rejectingId: {
    type: String as PropType<string | null>,
    default: null,
  },
  rejectReason: {
    type: String,
    required: true,
  },
  actionResult: {
    type: Object as PropType<Record<string, { type: 'success' | 'error'; message: string }>>,
    required: true,
  },
  priorityLabels: {
    type: Object as PropType<Record<string, string>>,
    required: true,
  },
  statusLabels: {
    type: Object as PropType<Record<string, string>>,
    required: true,
  },
  executionLabels: {
    type: Object as PropType<Record<string, string>>,
    required: true,
  },
  statusCardClass: {
    type: Function as PropType<(wo: any) => Record<string, boolean>>,
    required: true,
  },
  statusChipClass: {
    type: Function as PropType<(status: string) => Record<string, boolean>>,
    required: true,
  },
  executionChipClass: {
    type: Function as PropType<(status: string) => Record<string, boolean>>,
    required: true,
  },
  executionStatusForOrder: {
    type: Function as PropType<(wo: any) => string>,
    required: true,
  },
  buildingName: {
    type: Function as PropType<(id: string) => string>,
    required: true,
  },
  formatTime: {
    type: Function as PropType<(value?: string | null) => string>,
    required: true,
  },
  detailRows: {
    type: Function as PropType<(wo: any) => Array<{ label: string; value: string; cls?: string }>>,
    required: true,
  },
  timelineRows: {
    type: Function as PropType<(wo: any) => any[]>,
    required: true,
  },
  isTimelineLoading: {
    type: Function as PropType<(ticketId: string) => boolean>,
    required: true,
  },
  timelineError: {
    type: Function as PropType<(ticketId: string) => string>,
    required: true,
  },
  actionsForOrder: {
    type: Function as PropType<(wo: any) => Array<{ action: string; label: string; className: string }>>,
    required: true,
  },
})

const statusCardClassValue = (wo: any) => props.statusCardClass(wo)
const statusChipClassValue = (status: string) => props.statusChipClass(status)
const executionChipClassValue = (status: string) => props.executionChipClass(status)
const executionStatusForOrderValue = (wo: any) => props.executionStatusForOrder(wo)
const buildingNameValue = (id: string) => props.buildingName(id)
const formatTimeValue = (value?: string | null) => props.formatTime(value)
const detailRowsValue = (wo: any) => props.detailRows(wo)
const timelineRowsValue = (wo: any) => props.timelineRows(wo)
const isTimelineLoadingValue = (ticketId: string) => props.isTimelineLoading(ticketId)
const timelineErrorValue = (ticketId: string) => props.timelineError(ticketId)
const actionsForOrderValue = (wo: any) => props.actionsForOrder(wo)
</script>

<style scoped>
.order-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
  --wo-surface: var(--bg-panel);
  --wo-surface-alt: var(--bg-card);
  --wo-border: var(--border);
  --wo-text-strong: var(--text-primary);
  --wo-text: var(--text-secondary);
  --wo-text-subtle: var(--text-muted);
  --wo-chip-info-bg: rgba(59, 130, 246, 0.14);
  --wo-chip-info-border: rgba(59, 130, 246, 0.28);
  --wo-chip-info-text: var(--accent);
  --wo-chip-success-bg: rgba(16, 185, 129, 0.14);
  --wo-chip-success-border: rgba(16, 185, 129, 0.28);
  --wo-chip-success-text: var(--success);
  --wo-chip-warning-bg: rgba(251, 191, 36, 0.16);
  --wo-chip-warning-border: rgba(251, 191, 36, 0.28);
  --wo-chip-warning-text: var(--warning);
  --wo-chip-danger-bg: rgba(248, 113, 113, 0.14);
  --wo-chip-danger-border: rgba(248, 113, 113, 0.28);
  --wo-chip-danger-text: var(--danger);
  --wo-chip-support-bg: rgba(124, 58, 237, 0.12);
  --wo-chip-support-border: rgba(124, 58, 237, 0.24);
  --wo-chip-support-text: #7c3aed;
  --wo-chip-muted-bg: rgba(148, 163, 184, 0.14);
  --wo-chip-muted-border: rgba(148, 163, 184, 0.26);
  --wo-chip-muted-text: #64748b;
}

:global(html[data-theme="light"]) .order-list {
  --wo-surface: #ffffff;
  --wo-surface-alt: #fbfcfa;
  --wo-border: #dce7df;
  --wo-text-strong: #10231b;
  --wo-text: #42584d;
  --wo-text-subtle: #708479;
  --wo-chip-info-bg: #dbeafe;
  --wo-chip-info-border: #93c5fd;
  --wo-chip-info-text: #1d4ed8;
  --wo-chip-success-bg: #dcfce7;
  --wo-chip-success-border: #86efac;
  --wo-chip-success-text: #166534;
  --wo-chip-warning-bg: #fef3c7;
  --wo-chip-warning-border: #fcd34d;
  --wo-chip-warning-text: #b45309;
  --wo-chip-danger-bg: #fee2e2;
  --wo-chip-danger-border: #fca5a5;
  --wo-chip-danger-text: #b91c1c;
  --wo-chip-support-bg: #ede9fe;
  --wo-chip-support-border: #c4b5fd;
  --wo-chip-support-text: #6d28d9;
  --wo-chip-muted-bg: #f1f5f9;
  --wo-chip-muted-border: #cbd5e1;
  --wo-chip-muted-text: #475569;
}

.order-card {
  background: var(--wo-surface);
  border: 1px solid var(--wo-border);
  border-radius: 14px;
  overflow: hidden;
  box-shadow: var(--card-shadow);
}

.order-card.status-pending-review { border-left: 4px solid var(--warning); }
.order-card.status-pending-dispatch { border-left: 4px solid var(--accent); }
.order-card.status-dispatched { border-left: 4px solid var(--success); }
.order-card.status-rejected { border-left: 4px solid var(--danger); }
.order-card.status-resolved { border-left: 4px solid var(--wo-chip-muted-text); }

.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 16px;
  padding: 18px 20px;
  cursor: pointer;
  background: linear-gradient(180deg, rgba(255, 255, 255, 0.02), transparent);
}

:global(html[data-theme="light"]) .order-card .card-header {
  background: linear-gradient(180deg, rgba(34, 197, 94, 0.04), rgba(255, 255, 255, 0));
}

.card-header-left {
  display: flex;
  align-items: center;
  gap: 12px;
  min-width: 0;
}

.priority-badge,
.status-chip,
.execution-chip {
  display: inline-flex;
  align-items: center;
  border: 1px solid transparent;
  border-radius: 999px;
  white-space: nowrap;
  letter-spacing: 0.01em;
}

.priority-badge {
  font-size: 11px;
  font-weight: 700;
  padding: 4px 10px;
}

.p-low {
  background: var(--wo-chip-success-bg);
  border-color: var(--wo-chip-success-border);
  color: var(--wo-chip-success-text);
}

.p-medium {
  background: var(--wo-chip-warning-bg);
  border-color: var(--wo-chip-warning-border);
  color: var(--wo-chip-warning-text);
}

.p-high {
  background: var(--wo-chip-danger-bg);
  border-color: var(--wo-chip-danger-border);
  color: var(--wo-chip-danger-text);
}

.card-title-block { min-width: 0; }

.card-title {
  font-size: 15px;
  font-weight: 700;
  line-height: 1.55;
  margin-bottom: 4px;
  color: var(--wo-text-strong);
}

.card-meta {
  font-size: 12px;
  color: var(--wo-text);
}

.card-header-right {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  justify-content: flex-end;
}

.status-chip,
.execution-chip {
  font-size: 11px;
  font-weight: 700;
  padding: 4px 10px;
}

.chip-pending-review {
  background: var(--wo-chip-warning-bg);
  border-color: var(--wo-chip-warning-border);
  color: var(--wo-chip-warning-text);
}

.chip-pending-dispatch {
  background: var(--wo-chip-info-bg);
  border-color: var(--wo-chip-info-border);
  color: var(--wo-chip-info-text);
}

.chip-dispatched {
  background: var(--wo-chip-success-bg);
  border-color: var(--wo-chip-success-border);
  color: var(--wo-chip-success-text);
}

.chip-rejected {
  background: var(--wo-chip-danger-bg);
  border-color: var(--wo-chip-danger-border);
  color: var(--wo-chip-danger-text);
}

.chip-resolved {
  background: var(--wo-chip-muted-bg);
  border-color: var(--wo-chip-muted-border);
  color: var(--wo-chip-muted-text);
}

.exec-pending {
  background: var(--wo-chip-info-bg);
  border-color: var(--wo-chip-info-border);
  color: var(--wo-chip-info-text);
}

.exec-active {
  background: var(--wo-chip-success-bg);
  border-color: var(--wo-chip-success-border);
  color: var(--wo-chip-success-text);
}

.exec-support {
  background: var(--wo-chip-support-bg);
  border-color: var(--wo-chip-support-border);
  color: var(--wo-chip-support-text);
}

.exec-danger {
  background: var(--wo-chip-danger-bg);
  border-color: var(--wo-chip-danger-border);
  color: var(--wo-chip-danger-text);
}

.expand-btn {
  color: var(--wo-text-subtle);
  font-size: 12px;
  font-weight: 700;
}

.card-body {
  border-top: 1px solid var(--wo-border);
  padding: 18px 20px;
  background: var(--wo-surface-alt);
}

.detail-grid {
  display: flex;
  flex-direction: column;
  gap: 0;
}

.detail-row {
  display: grid;
  grid-template-columns: 112px 1fr;
  gap: 12px;
  align-items: start;
  padding: 10px 0;
  border-bottom: 1px solid var(--wo-border);
  font-size: 13px;
}

.detail-row:last-child { border-bottom: none; }

.detail-label {
  color: var(--wo-text);
  font-size: 12px;
  font-weight: 600;
}

.detail-val {
  color: var(--wo-text-strong);
  font-weight: 500;
  line-height: 1.7;
  word-break: break-word;
}

.detail-val.mono { font-family: monospace; }

.detail-val.accent {
  color: var(--wo-chip-success-text);
  font-weight: 700;
}

.detail-val.wrap { white-space: pre-wrap; }

.detail-val.warning-text {
  color: var(--wo-chip-warning-text);
  font-weight: 600;
}

.detail-val.danger-text {
  color: var(--wo-chip-danger-text);
  font-weight: 600;
}

.timeline-block {
  margin-top: 18px;
  padding-top: 18px;
  border-top: 1px solid var(--wo-border);
}

.section-title {
  font-size: 13px;
  font-weight: 700;
  margin-bottom: 10px;
  color: var(--wo-text-strong);
}

.timeline-hint {
  font-size: 12px;
  color: var(--wo-text);
  margin-bottom: 10px;
}

.timeline-hint.error { color: var(--wo-chip-danger-text); }

.timeline-item {
  display: flex;
  gap: 12px;
  padding: 8px 0;
}

.timeline-dot {
  width: 10px;
  height: 10px;
  border-radius: 50%;
  background: var(--wo-chip-info-text);
  margin-top: 6px;
  flex-shrink: 0;
}

.timeline-content {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.timeline-time {
  font-size: 11px;
  color: var(--wo-text-subtle);
}

.timeline-label {
  font-size: 13px;
  font-weight: 600;
  color: var(--wo-text-strong);
}

.timeline-note {
  font-size: 12px;
  color: var(--wo-text);
}

.action-bar {
  display: flex;
  gap: 8px;
  align-items: center;
  margin-top: 16px;
  padding-top: 14px;
  border-top: 1px solid var(--wo-border);
}

.action-btn {
  border: 1px solid transparent;
  border-radius: 8px;
  font-size: 13px;
  font-weight: 600;
  padding: 8px 16px;
  cursor: pointer;
}

.action-btn.primary {
  background: var(--accent);
  color: white;
}

.action-btn.secondary {
  background: var(--wo-chip-info-bg);
  border-color: var(--wo-chip-info-border);
  color: var(--wo-chip-info-text);
}

.action-btn.danger {
  background: var(--wo-chip-danger-bg);
  border-color: var(--wo-chip-danger-border);
  color: var(--wo-chip-danger-text);
}

.action-btn:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.reject-area {
  display: flex;
  gap: 8px;
  align-items: center;
  margin-top: 12px;
}

.reject-input {
  flex: 1;
  background: var(--wo-surface);
  border: 1px solid var(--wo-border);
  border-radius: 8px;
  color: var(--wo-text-strong);
  padding: 8px 12px;
}

.btn-reject-confirm,
.btn-cancel {
  border-radius: 8px;
  font-size: 13px;
  padding: 8px 14px;
  cursor: pointer;
}

.btn-reject-confirm {
  border: none;
  background: var(--wo-chip-danger-text);
  color: white;
}

.btn-cancel {
  border: 1px solid var(--wo-border);
  background: transparent;
  color: var(--wo-text);
}

.action-result {
  margin-top: 12px;
  padding: 10px 12px;
  border-radius: 8px;
  font-size: 13px;
}

.action-result.success {
  background: var(--wo-chip-success-bg);
  color: var(--wo-chip-success-text);
  border: 1px solid var(--wo-chip-success-border);
}

.action-result.error {
  background: var(--wo-chip-danger-bg);
  color: var(--wo-chip-danger-text);
  border: 1px solid var(--wo-chip-danger-border);
}

.slide-enter-active,
.slide-leave-active {
  transition: all 0.2s ease;
}

.slide-enter-from,
.slide-leave-to {
  opacity: 0;
  transform: translateY(-8px);
}

@media (max-width: 720px) {
  .card-header {
    align-items: flex-start;
    flex-direction: column;
  }

  .card-header-right {
    width: 100%;
    justify-content: flex-start;
  }

  .detail-row {
    grid-template-columns: 1fr;
    gap: 4px;
  }

  .reject-area {
    flex-direction: column;
    align-items: stretch;
  }
}
</style>
