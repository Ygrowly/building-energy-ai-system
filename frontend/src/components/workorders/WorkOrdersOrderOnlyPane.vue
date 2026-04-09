<template>
  <WorkOrdersOrderList
    v-if="!loading && filteredOrders.length > 0"
    :orders="filteredOrders"
    :expanded-id="expandedId"
    :action-loading="actionLoading"
    :rejecting-id="rejectingId"
    :reject-reason="rejectReason"
    :action-result="actionResult"
    :priority-labels="priorityLabels"
    :status-labels="statusLabels"
    :execution-labels="executionLabels"
    :status-card-class="statusCardClass"
    :status-chip-class="statusChipClass"
    :execution-chip-class="executionChipClass"
    :execution-status-for-order="executionStatusForOrder"
    :building-name="buildingName"
    :format-time="formatTime"
    :detail-rows="detailRows"
    :timeline-rows="timelineRows"
    :is-timeline-loading="isTimelineLoading"
    :timeline-error="timelineError"
    :actions-for-order="actionsForOrder"
    @toggle-expand="$emit('toggle-expand', $event)"
    @run-action="(wo, action) => $emit('run-action', wo, action)"
    @start-reject="$emit('start-reject', $event)"
    @update-reject-reason="$emit('update-reject-reason', $event)"
    @cancel-reject="$emit('cancel-reject')"
  />
</template>

<script setup lang="ts">
import { PropType } from 'vue'
import WorkOrdersOrderList from './WorkOrdersOrderList.vue'

defineEmits<{
  'toggle-expand': [ticketId: string]
  'run-action': [wo: any, action: string]
  'start-reject': [ticketId: string]
  'update-reject-reason': [reason: string]
  'cancel-reject': []
}>()

defineProps({
  loading: {
    type: Boolean,
    required: true,
  },
  filteredOrders: {
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
  formatTime: {
    type: Function as PropType<(value?: string | null) => string>,
    required: true,
  },
  buildingName: {
    type: Function as PropType<(id: string) => string>,
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
</script>
