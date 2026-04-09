<template>
  <WorkOrdersMainPane v-bind="mainPaneProps" v-on="$attrs" />
</template>

<script setup lang="ts">
import { PropType } from 'vue'
import WorkOrdersMainPane from './WorkOrdersMainPane.vue'

type WorkOrdersMainPaneProps = InstanceType<typeof WorkOrdersMainPane>['$props']

defineOptions({
  inheritAttrs: false,
})

defineProps({
  mainPaneProps: {
    type: Object as PropType<WorkOrdersMainPaneProps>,
    required: true,
  },
})
</script>
