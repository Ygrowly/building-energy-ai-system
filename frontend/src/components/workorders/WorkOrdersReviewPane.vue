<template>
  <WorkOrdersOrderOnlyPane
    v-bind="mainPaneProps"
    @toggle-expand="forwardToggleExpand"
    @run-action="forwardRunAction"
    @start-reject="forwardStartReject"
    @update-reject-reason="forwardUpdateRejectReason"
    @cancel-reject="forwardCancelReject"
  />
</template>

<script setup lang="ts">
import { PropType } from 'vue'
import WorkOrdersOrderOnlyPane from './WorkOrdersOrderOnlyPane.vue'

type WorkOrdersOrderOnlyPaneProps = InstanceType<typeof WorkOrdersOrderOnlyPane>['$props']

defineOptions({
  inheritAttrs: false,
})

const emit = defineEmits<{
  'toggle-expand': [ticketId: string]
  'run-action': [wo: any, action: string]
  'start-reject': [ticketId: string]
  'update-reject-reason': [reason: string]
  'cancel-reject': []
}>()

function forwardToggleExpand(ticketId: string) {
  emit('toggle-expand', ticketId)
}

function forwardRunAction(wo: any, action: string) {
  emit('run-action', wo, action)
}

function forwardStartReject(ticketId: string) {
  emit('start-reject', ticketId)
}

function forwardUpdateRejectReason(reason: string) {
  emit('update-reject-reason', reason)
}

function forwardCancelReject() {
  emit('cancel-reject')
}

defineProps({
  mainPaneProps: {
    type: Object as PropType<WorkOrdersOrderOnlyPaneProps>,
    required: true,
  },
})
</script>
