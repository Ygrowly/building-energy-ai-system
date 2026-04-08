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
.p-low { background: rgba(74, 222, 128, 0.15); color: var(--success); }
.p-medium { background: rgba(251, 191, 36, 0.15); color: var(--warning); }
.p-high { background: rgba(248, 113, 113, 0.15); color: var(--danger); }
.card-title-block { min-width: 0; }
.card-title { font-size: 14px; font-weight: 700; margin-bottom: 4px; }
.card-meta { font-size: 12px; color: var(--text-muted); }
.card-header-right { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; justify-content: flex-end; }
.status-chip, .execution-chip { font-size: 11px; font-weight: 600; border-radius: 999px; padding: 4px 10px; }
.chip-pending-review { background: rgba(251, 191, 36, 0.15); color: var(--warning); }
.chip-pending-dispatch { background: rgba(59, 130, 246, 0.12); color: var(--accent); }
.chip-dispatched { background: rgba(16, 185, 129, 0.12); color: var(--success); }
.chip-rejected { background: rgba(248, 113, 113, 0.12); color: var(--danger); }
.chip-resolved { background: rgba(148, 163, 184, 0.15); color: var(--text-muted); }
.exec-pending { background: rgba(59, 130, 246, 0.1); color: var(--accent); }
.exec-active { background: rgba(16, 185, 129, 0.1); color: var(--success); }
.exec-support { background: rgba(124, 58, 237, 0.12); color: #7c3aed; }
.exec-danger { background: rgba(248, 113, 113, 0.12); color: var(--danger); }
.card-body { border-top: 1px solid var(--border); padding: 16px; background: var(--bg-card); }
.detail-grid { display: flex; flex-direction: column; gap: 0; }
.detail-row { display: grid; grid-template-columns: 100px 1fr; gap: 10px; padding: 7px 0; border-bottom: 1px solid var(--border); font-size: 13px; }
.detail-row:last-child { border-bottom: none; }
.detail-label { color: var(--text-muted); font-size: 12px; }
.detail-val.mono { font-family: monospace; }
.detail-val.accent { color: var(--accent); }
.detail-val.wrap { white-space: pre-wrap; }
.detail-val.warning-text { color: var(--warning); }
.detail-val.danger-text { color: var(--danger); }
.timeline-block { margin-top: 16px; padding-top: 16px; border-top: 1px solid var(--border); }
.section-title { font-size: 13px; font-weight: 700; margin-bottom: 10px; }
.timeline-hint { font-size: 12px; color: var(--text-muted); margin-bottom: 10px; }
.timeline-hint.error { color: var(--danger); }
.timeline-item { display: flex; gap: 12px; padding: 8px 0; }
.timeline-dot { width: 10px; height: 10px; border-radius: 50%; background: var(--accent); margin-top: 6px; flex-shrink: 0; }
.timeline-content { display: flex; flex-direction: column; gap: 4px; }
.timeline-time { font-size: 11px; color: var(--text-muted); }
.timeline-label { font-size: 13px; font-weight: 600; }
.timeline-note { font-size: 12px; color: var(--text-secondary); }
.action-bar { display: flex; gap: 8px; align-items: center; margin-top: 16px; padding-top: 14px; border-top: 1px solid var(--border); }
.action-btn { border: none; border-radius: 8px; font-size: 13px; font-weight: 600; padding: 8px 16px; cursor: pointer; }
.action-btn.primary { background: var(--accent); color: white; }
.action-btn.secondary { background: rgba(59, 130, 246, 0.12); color: var(--accent); }
.action-btn.danger { background: rgba(248, 113, 113, 0.12); color: var(--danger); }
.action-btn:disabled { opacity: 0.6; cursor: not-allowed; }
.reject-area { display: flex; gap: 8px; align-items: center; margin-top: 12px; }
.reject-input { flex: 1; background: var(--bg-panel); border: 1px solid var(--border); border-radius: 8px; color: var(--text-primary); padding: 8px 12px; }
.btn-reject-confirm, .btn-cancel { border-radius: 8px; font-size: 13px; padding: 8px 14px; cursor: pointer; }
.btn-reject-confirm { border: none; background: var(--danger); color: white; }
.btn-cancel { border: 1px solid var(--border); background: none; color: var(--text-secondary); }
.action-result { margin-top: 12px; padding: 10px 12px; border-radius: 8px; font-size: 13px; }
.action-result.success { background: rgba(74, 222, 128, 0.1); color: var(--success); border: 1px solid rgba(74, 222, 128, 0.3); }
.action-result.error { background: rgba(248, 113, 113, 0.1); color: var(--danger); border: 1px solid rgba(248, 113, 113, 0.3); }
.slide-enter-active, .slide-leave-active { transition: all 0.2s ease; }
.slide-enter-from, .slide-leave-to { opacity: 0; transform: translateY(-8px); }
</style>
