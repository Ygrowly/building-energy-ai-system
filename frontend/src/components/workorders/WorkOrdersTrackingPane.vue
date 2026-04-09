<template>
  <WorkOrdersOrderOnlyPane v-bind="mainPaneProps" v-on="$attrs" />
</template>

<script setup lang="ts">
import { PropType } from 'vue'
import WorkOrdersOrderOnlyPane from './WorkOrdersOrderOnlyPane.vue'

type WorkOrdersOrderOnlyPaneProps = InstanceType<typeof WorkOrdersOrderOnlyPane>['$props']

defineOptions({
  inheritAttrs: false,
})

defineProps({
  mainPaneProps: {
    type: Object as PropType<WorkOrdersOrderOnlyPaneProps>,
    required: true,
  },
})
</script>
