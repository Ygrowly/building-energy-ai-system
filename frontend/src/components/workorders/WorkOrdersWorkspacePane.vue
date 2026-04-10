<template>
  <component
    :is="paneComponent"
    :main-pane-props="mainPaneProps"
    @approve="forwardApprove"
    @reject="forwardReject"
    @suggest="forwardSuggest"
    @nudge="forwardNudge"
    @close-entry="forwardCloseEntry"
    @toggle-expand="forwardToggleExpand"
    @run-action="forwardRunAction"
    @start-reject="forwardStartReject"
    @update-reject-reason="forwardUpdateRejectReason"
    @cancel-reject="forwardCancelReject"
  />
</template>

<script setup lang="ts">
import { computed, PropType, type Component } from 'vue'
import type { WorkOrderWorkspaceMode } from '@/constants/workOrders'
import WorkOrdersDispatchPane from './WorkOrdersDispatchPane.vue'
import WorkOrdersOverviewPane from './WorkOrdersOverviewPane.vue'
import WorkOrdersReviewPane from './WorkOrdersReviewPane.vue'
import WorkOrdersTrackingPane from './WorkOrdersTrackingPane.vue'

defineOptions({
  inheritAttrs: false,
})

const emit = defineEmits<{
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

function forwardApprove(entry: any, application: any) {
  emit('approve', entry, application)
}

function forwardReject(entry: any, application: any) {
  emit('reject', entry, application)
}

function forwardSuggest(entry: any) {
  emit('suggest', entry)
}

function forwardNudge(entry: any) {
  emit('nudge', entry)
}

function forwardCloseEntry(entry: any) {
  emit('close-entry', entry)
}

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

const props = defineProps({
  workspaceMode: {
    type: String as PropType<WorkOrderWorkspaceMode>,
    required: true,
  },
  mainPaneProps: {
    type: Object as PropType<Record<string, unknown>>,
    required: true,
  },
})

const workspacePaneMap: Record<WorkOrderWorkspaceMode, Component> = {
  all: WorkOrdersOverviewPane,
  review: WorkOrdersReviewPane,
  dispatch: WorkOrdersDispatchPane,
  tracking: WorkOrdersTrackingPane,
}

const paneComponent = computed(() => workspacePaneMap[props.workspaceMode] ?? WorkOrdersOverviewPane)
</script>
