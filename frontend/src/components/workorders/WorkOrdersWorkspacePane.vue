<template>
  <component
    :is="paneComponent"
    :main-pane-props="mainPaneProps"
    v-on="$attrs"
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
