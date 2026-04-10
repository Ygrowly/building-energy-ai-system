<template>
  <WorkOrdersAutoDispatchInsightsPanel
    v-if="activeTab === 'auto_dispatch_insights'"
    :insights="autoDispatchInsights"
    :filters="autoDispatchInsightFilters"
    :loading="autoDispatchInsightLoading"
    :error="autoDispatchInsightError"
    :priority-labels="priorityLabels"
    :building-options="autoDispatchInsightBuildingOptions"
    :skill-options="autoDispatchInsightSkillOptions"
    :building-name="buildingName"
    :format-time="formatTime"
    :update-filter="updateAutoDispatchInsightFilter"
    :refresh="fetchAutoDispatchInsights"
    :explanation="autoDispatchInsightExplanation"
    :explanation-source="autoDispatchInsightExplanationSource"
    :explain-question="autoDispatchInsightQuestion"
    :explain-loading="autoDispatchInsightExplainLoading"
    :explain-error="autoDispatchInsightExplainError"
    :update-explain-question="updateAutoDispatchInsightQuestion"
    :explain="fetchAutoDispatchInsightExplanation"
  />

  <WorkOrdersHallList
    v-else-if="!loading && activeTab === 'shared_hall' && hallEntries.length > 0"
    :hall-entries="hallEntries"
    :action-loading="actionLoading"
    :priority-labels="priorityLabels"
    :format-time="formatTime"
    :building-name="buildingName"
    :hall-pending-applications="hallPendingApplications"
    :hall-entry-title="hallEntryTitle"
    :hall-entry-owner="hallEntryOwner"
    :hall-entry-reason="hallEntryReason"
    :hall-empty-hint="hallEmptyHint"
    :can-suggest-hall-takeover="canSuggestHallTakeover"
    :can-nudge-hall-owner="canNudgeHallOwner"
    :hall-action-key="hallActionKey"
    @approve="(entry, application) => $emit('approve', entry, application)"
    @reject="(entry, application) => $emit('reject', entry, application)"
    @suggest="$emit('suggest', $event)"
    @nudge="$emit('nudge', $event)"
    @close-entry="$emit('close-entry', $event)"
  />

  <WorkOrdersOrderList
    v-else-if="!loading && filteredOrders.length > 0"
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
import WorkOrdersAutoDispatchInsightsPanel from './WorkOrdersAutoDispatchInsightsPanel.vue'
import WorkOrdersHallList from './WorkOrdersHallList.vue'
import WorkOrdersOrderList from './WorkOrdersOrderList.vue'

defineEmits<{
  approve: [entry: any, application: any]
  reject: [entry: any, application: any]
  suggest: [entry: any]
  nudge: [entry: any]
  'close-entry': [entry: any]
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
  activeTab: {
    type: String,
    required: true,
  },
  hallEntries: {
    type: Array as PropType<any[]>,
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
  hallPendingApplications: {
    type: Function as PropType<(entry: any) => any[]>,
    required: true,
  },
  hallEntryTitle: {
    type: Function as PropType<(entry: any) => string>,
    required: true,
  },
  hallEntryOwner: {
    type: Function as PropType<(entry: any) => string>,
    required: true,
  },
  hallEntryReason: {
    type: Function as PropType<(entry: any) => string>,
    required: true,
  },
  hallEmptyHint: {
    type: Function as PropType<(entry: any) => string>,
    required: true,
  },
  canSuggestHallTakeover: {
    type: Function as PropType<(entry: any) => boolean>,
    required: true,
  },
  canNudgeHallOwner: {
    type: Function as PropType<(entry: any) => boolean>,
    required: true,
  },
  hallActionKey: {
    type: Function as PropType<(entryId: string, applicationId: string, action: 'approve' | 'reject' | 'close' | 'suggest' | 'nudge') => string>,
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
  autoDispatchInsights: {
    type: Object as PropType<any | null>,
    default: null,
  },
  autoDispatchInsightFilters: {
    type: Object as PropType<Record<string, string>>,
    required: true,
  },
  autoDispatchInsightLoading: {
    type: Boolean,
    required: true,
  },
  autoDispatchInsightError: {
    type: String,
    required: true,
  },
  autoDispatchInsightBuildingOptions: {
    type: Array as PropType<Array<{ label: string; value: string }>>,
    required: true,
  },
  autoDispatchInsightSkillOptions: {
    type: Array as PropType<Array<{ label: string; value: string }>>,
    required: true,
  },
  updateAutoDispatchInsightFilter: {
    type: Function as PropType<(key: string, value: string) => void>,
    required: true,
  },
  fetchAutoDispatchInsights: {
    type: Function as PropType<() => void>,
    required: true,
  },
  autoDispatchInsightExplanation: {
    type: Object as PropType<any | null>,
    default: null,
  },
  autoDispatchInsightExplanationSource: {
    type: String,
    default: '',
  },
  autoDispatchInsightQuestion: {
    type: String,
    required: true,
  },
  autoDispatchInsightExplainLoading: {
    type: Boolean,
    required: true,
  },
  autoDispatchInsightExplainError: {
    type: String,
    required: true,
  },
  updateAutoDispatchInsightQuestion: {
    type: Function as PropType<(value: string) => void>,
    required: true,
  },
  fetchAutoDispatchInsightExplanation: {
    type: Function as PropType<() => void>,
    required: true,
  },
})
</script>
