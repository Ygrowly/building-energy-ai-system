<template>
  <div class="order-list">
    <div
      v-for="wo in orders"
      :id="`work-order-${wo.ticket_id}`"
      :key="wo.ticket_id"
      class="order-card"
      :class="statusCardClassValue(wo)"
    >
      <div class="card-header" @click="$emit('toggle-expand', wo.ticket_id)">
        <div class="card-header-left">
          <span class="priority-badge" :class="'p-' + (wo.priority ?? 'medium').toLowerCase()">
            {{ priorityLabels[wo.priority] ?? wo.priority ?? '普通' }}
          </span>

          <div class="card-title-block">
            <p class="card-title">{{ displayTitleValue(wo) }}</p>

            <div v-if="titleTagsValue(wo).length" class="title-tags">
              <span v-for="tag in titleTagsValue(wo)" :key="tag" class="title-tag">{{ tag }}</span>
            </div>

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

          <button class="expand-btn" type="button" @click.prevent.stop="$emit('toggle-expand', wo.ticket_id)">
            {{ expandedId === wo.ticket_id ? '收起' : '展开' }}
          </button>
        </div>
      </div>

      <Transition name="slide">
        <div v-if="expandedId === wo.ticket_id" class="card-body">
          <div class="detail-grid">
            <div v-for="row in detailRowsValue(wo)" :key="row.label" class="detail-row">
              <span class="detail-label">{{ row.label }}</span>
              <span class="detail-val" :class="row.cls">{{ row.value }}</span>
            </div>
          </div>

          <WorkOrdersAutoDispatchReview
            v-if="autoDispatchReviewValue(wo)"
            :review="autoDispatchReviewValue(wo)"
          />

          <WorkOrderTimeline
            v-if="timelineRowsValue(wo).length || isTimelineLoadingValue(wo.ticket_id) || timelineErrorValue(wo.ticket_id)"
            class="timeline-block"
            :items="timelineRowsValue(wo)"
            :loading="isTimelineLoadingValue(wo.ticket_id)"
            :error="timelineErrorValue(wo.ticket_id)"
          />

          <div v-if="actionsForOrderValue(wo).length" class="action-bar">
            <template v-for="action in actionsForOrderValue(wo)" :key="action.action">
              <button
                v-if="action.action !== 'reject_pending'"
                class="action-btn"
                :class="action.className"
                :disabled="actionLoading === wo.ticket_id + ':' + action.action"
                @click="$emit('run-action', wo, action.action)"
              >
                {{ actionLoading === wo.ticket_id + ':' + action.action ? '处理中...' : action.label }}
              </button>

              <button
                v-else
                class="action-btn danger"
                :disabled="actionLoading === wo.ticket_id + ':' + action.action"
                @click="$emit('start-reject', wo.ticket_id)"
              >
                驳回
              </button>
            </template>
          </div>

          <div v-if="rejectingId === wo.ticket_id" class="reject-area">
            <input
              :value="rejectReason"
              class="reject-input"
              placeholder="输入驳回原因"
              @input="$emit('update-reject-reason', ($event.target as HTMLInputElement).value)"
              @keyup.enter="$emit('run-action', wo, 'reject_pending')"
            />
            <button class="btn-reject-confirm" @click="$emit('run-action', wo, 'reject_pending')">确认驳回</button>
            <button class="btn-cancel" @click="$emit('cancel-reject')">取消</button>
          </div>

          <div v-if="actionResult[wo.ticket_id]?.type === 'success'" class="action-result success">
            <Icon icon="mdi:check-circle" width="14" class="bar-icon" /> {{ actionResult[wo.ticket_id].message }}
          </div>

          <div v-if="actionResult[wo.ticket_id]?.type === 'error'" class="action-result error">
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
import WorkOrderTimeline from './WorkOrderTimeline.vue'
import WorkOrdersAutoDispatchReview from './WorkOrdersAutoDispatchReview.vue'
import { formatWorkOrderIssueTags, formatWorkOrderIssueTitle } from '@/utils/workOrderIssue'

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
const displayTitleValue = (wo: any) => formatWorkOrderIssueTitle(wo.issue_description || wo.ticket_id, wo.ticket_id)
const titleTagsValue = (wo: any) => formatWorkOrderIssueTags(wo.issue_description)

function autoDispatchReviewValue(wo: any) {
  const dispatch = wo.current_dispatch
  if (!dispatch) return null

  const reviewState = autoDispatchReviewStateValue(wo, dispatch)
  if (dispatch.auto_dispatch_review) {
    return {
      ...dispatch.auto_dispatch_review,
      review_state: dispatch.auto_dispatch_review.review_state || reviewState,
    }
  }

  const snapshot = dispatch.candidate_snapshot
  if (!snapshot?.auto_dispatch && !['auto', 'auto_fallback'].includes(dispatch.dispatch_mode)) return null

  const isFallback = dispatch.dispatch_mode === 'auto_fallback'
  return {
    dispatch_mode: dispatch.dispatch_mode,
    strategy: snapshot?.strategy || (isFallback ? 'low_confidence_fallback_dispatch' : 'high_confidence_dispatch'),
    strategy_label: isFallback ? '低置信兜底派工' : '高置信自动派工',
    confidence: snapshot?.confidence,
    confidence_label: snapshot?.confidence === 'high' ? '高置信' : snapshot?.confidence,
    review_state: reviewState,
    review_hint: isFallback
      ? '低置信兜底派工，请管理员复核候选人、负载与现场响应情况'
      : '高置信自动派工，可抽查候选排序、分数与负载',
    selection_reason: dispatch.selection_reason,
    rules: snapshot?.rules || {},
    score_gap: snapshot?.score_gap,
    selected_candidate: isFallback && snapshot?.fallback_candidate ? snapshot.fallback_candidate : snapshot?.top_candidate,
    top_candidate: snapshot?.top_candidate,
    second_candidate: snapshot?.second_candidate,
    fallback_candidate: snapshot?.fallback_candidate,
  }
}

function autoDispatchReviewStateValue(wo: any, dispatch: any) {
  if (dispatch.auto_dispatch_review_state || wo.auto_dispatch_review_state) {
    return dispatch.auto_dispatch_review_state || wo.auto_dispatch_review_state
  }

  if (wo.admin_action === 'auto_dispatch_reviewed') {
    return { status: 'reviewed', status_label: '已复核', notes: wo.admin_notes, reviewed_at: wo.admin_reviewed_at }
  }

  if (wo.admin_action === 'auto_dispatch_needs_reassign') {
    return { status: 'needs_reassign', status_label: '需改派', notes: wo.admin_notes, reviewed_at: wo.admin_reviewed_at }
  }

  return { status: 'pending', status_label: '待复核' }
}
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
  --wo-chip-success-bg: rgba(36, 160, 119, 0.14);
  --wo-chip-success-border: rgba(33, 159, 117, 0.28);
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
  background: linear-gradient(180deg, rgba(23, 183, 82, 0.04), rgba(255, 255, 255, 0));
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

.card-title-block {
  min-width: 0;
}

.card-title {
  margin-bottom: 6px;
  color: var(--wo-text-strong);
  font-size: 15px;
  font-weight: 700;
  line-height: 1.55;
}

.title-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-bottom: 6px;
}

.title-tag {
  display: inline-flex;
  align-items: center;
  padding: 3px 9px;
  border: 1px solid var(--wo-border);
  border-radius: 999px;
  background: var(--wo-surface-alt);
  color: var(--wo-text);
  font-size: 11px;
  line-height: 1.4;
}

.card-meta {
  color: var(--wo-text);
  font-size: 12px;
}

.card-header-right {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 8px;
  flex-wrap: wrap;
}

.status-chip,
.execution-chip {
  padding: 4px 10px;
  font-size: 11px;
  font-weight: 700;
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
  padding: 5px 10px;
  border: 1px solid var(--wo-border);
  border-radius: 8px;
  background: var(--wo-surface);
  color: var(--wo-text-subtle);
  font-size: 12px;
  font-weight: 700;
  cursor: pointer;
}

.expand-btn:hover {
  border-color: var(--wo-chip-info-border);
  background: var(--wo-chip-info-bg);
  color: var(--wo-chip-info-text);
}

.card-body {
  padding: 18px 20px;
  border-top: 1px solid var(--wo-border);
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

.detail-row:last-child {
  border-bottom: none;
}

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

.detail-val.mono {
  font-family: monospace;
}

.detail-val.accent {
  color: var(--wo-chip-success-text);
  font-weight: 700;
}

.detail-val.wrap {
  white-space: pre-wrap;
}

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

.action-bar {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: 16px;
  padding-top: 14px;
  border-top: 1px solid var(--wo-border);
  flex-wrap: wrap;
}

.action-btn {
  padding: 8px 16px;
  border: 1px solid transparent;
  border-radius: 8px;
  font-size: 13px;
  font-weight: 600;
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
  cursor: not-allowed;
  opacity: 0.6;
}

.reject-area {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: 12px;
  flex-wrap: wrap;
}

.reject-input {
  flex: 1;
  min-width: 220px;
  padding: 8px 12px;
  border: 1px solid var(--wo-border);
  border-radius: 8px;
  background: var(--wo-surface);
  color: var(--wo-text-strong);
}

.btn-reject-confirm,
.btn-cancel {
  padding: 8px 14px;
  border-radius: 8px;
  font-size: 13px;
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
  border: 1px solid var(--wo-chip-success-border);
  background: var(--wo-chip-success-bg);
  color: var(--wo-chip-success-text);
}

.action-result.error {
  border: 1px solid var(--wo-chip-danger-border);
  background: var(--wo-chip-danger-bg);
  color: var(--wo-chip-danger-text);
}

.bar-icon {
  margin-right: 4px;
  vertical-align: -2px;
}

@media (max-width: 960px) {
  .card-header {
    align-items: flex-start;
    flex-direction: column;
  }

  .card-header-right {
    width: 100%;
    justify-content: flex-start;
  }

  .detail-row {
    grid-template-columns: 96px 1fr;
  }
}

@media (max-width: 640px) {
  .card-header,
  .card-body {
    padding: 16px;
  }

  .card-header-left {
    align-items: flex-start;
    flex-direction: column;
  }

  .detail-row {
    grid-template-columns: 1fr;
    gap: 6px;
  }

  .reject-input {
    min-width: 0;
  }
}
</style>
