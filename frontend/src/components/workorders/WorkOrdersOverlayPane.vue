<template>
  <WorkOrdersDispatchSheet
    :visible="dispatchPanel.visible"
    :panel="dispatchPanel"
    :priority-labels="priorityLabels"
    :dispatch-submitting="dispatchSubmitting"
    @close="$emit('close-dispatch')"
    @confirm-candidate="$emit('confirm-candidate', $event)"
  />

  <WorkOrdersBatchSheet
    :visible="batchPanel.visible"
    :panel="batchPanel"
    :batch-preview-loading="batchPreviewLoading"
    :batch-dispatch-applying="batchDispatchApplying"
    :batch-sample-options="batchSampleOptions"
    :batch-worker-cap-options="batchWorkerCapOptions"
    :batch-priority-options="batchPriorityOptions"
    :batch-options="batchOptions"
    :batch-worker-loads="batchWorkerLoads"
    :retryable-batch-failures="retryableBatchFailures"
    :priority-labels="priorityLabels"
    :status-labels="statusLabels"
    :building-name="buildingName"
    :shift-label="shiftLabel"
    @close="$emit('close-batch')"
    @refresh-preview="$emit('refresh-preview')"
    @select-sample-size="$emit('select-sample-size', $event)"
    @select-priority="$emit('select-priority', $event)"
    @select-worker-cap="$emit('select-worker-cap', $event)"
    @retry-failed="$emit('retry-failed')"
    @review-failed="$emit('review-failed', $event)"
    @confirm-dispatch="$emit('confirm-dispatch')"
  />
</template>

<script setup lang="ts">
import { PropType } from 'vue'
import WorkOrdersBatchSheet from './WorkOrdersBatchSheet.vue'
import WorkOrdersDispatchSheet from './WorkOrdersDispatchSheet.vue'

defineEmits<{
  'close-dispatch': []
  'confirm-candidate': [candidate: any]
  'close-batch': []
  'refresh-preview': []
  'select-sample-size': [size: number]
  'select-priority': [priority: string]
  'select-worker-cap': [cap: number]
  'retry-failed': []
  'review-failed': [item: any]
  'confirm-dispatch': []
}>()

defineProps({
  dispatchPanel: {
    type: Object as PropType<any>,
    required: true,
  },
  dispatchSubmitting: {
    type: String as PropType<string | null>,
    default: null,
  },
  batchPanel: {
    type: Object as PropType<any>,
    required: true,
  },
  batchPreviewLoading: {
    type: Boolean,
    required: true,
  },
  batchDispatchApplying: {
    type: Boolean,
    required: true,
  },
  batchSampleOptions: {
    type: Array as PropType<number[]>,
    required: true,
  },
  batchWorkerCapOptions: {
    type: Array as PropType<number[]>,
    required: true,
  },
  batchPriorityOptions: {
    type: Array as PropType<Array<{ label: string; value: string }>>,
    required: true,
  },
  batchOptions: {
    type: Object as PropType<any>,
    required: true,
  },
  batchWorkerLoads: {
    type: Array as PropType<any[]>,
    required: true,
  },
  retryableBatchFailures: {
    type: Array as PropType<any[]>,
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
  buildingName: {
    type: Function as PropType<(id: string) => string>,
    required: true,
  },
  shiftLabel: {
    type: Function as PropType<(value?: string | null) => string>,
    required: true,
  },
})
</script>
