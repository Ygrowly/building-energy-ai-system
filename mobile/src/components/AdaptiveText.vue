<!--
  自适应文字组件（基于 @chenglou/pretext）
  - maxLines: 最大显示行数，超出截断
  - autoFit: 开启自适应字号
  - maxFontSize / minFontSize: 字号范围
-->
<template>
  <text
    :class="['adaptive-text', { truncated: isTruncated }]"
    :style="textStyle"
    @click="handleClick"
  >{{ displayText }}</text>
</template>

<script setup lang="ts">
import { ref, computed, watch, onMounted } from 'vue'
import { truncateToLines, autoFitFontSize } from '../utils/text-adapter'

const props = withDefaults(defineProps<{
  content: string
  width?: number            // 容器宽度(px)，必须传入才能启用 pretext 测量
  maxLines?: number
  fontSize?: number         // 基础字号(px)
  lineHeight?: number
  autoFit?: boolean         // 开启自适应字号
  maxFontSize?: number
  minFontSize?: number
  expandable?: boolean      // 点击展开完整内容
}>(), {
  maxLines: 2,
  fontSize: 14,
  lineHeight: 22,
  autoFit: false,
  maxFontSize: 18,
  minFontSize: 12,
  expandable: false,
})

const emit = defineEmits<{ (e: 'expand'): void }>()

const expanded = ref(false)
const displayText = ref(props.content)
const isTruncated = ref(false)
const fittedFontSize = ref(props.fontSize)

function compute() {
  if (!props.width || props.width <= 0) {
    // 无宽度信息时降级为 CSS 截断
    displayText.value = props.content
    return
  }

  if (props.autoFit) {
    fittedFontSize.value = autoFitFontSize(
      props.content,
      props.width,
      props.maxFontSize,
      props.minFontSize,
      props.maxLines,
      props.lineHeight,
    )
    displayText.value = props.content
    return
  }

  if (expanded.value) {
    displayText.value = props.content
    isTruncated.value = false
    return
  }

  const result = truncateToLines(
    props.content,
    props.width,
    props.maxLines,
    props.fontSize,
    props.lineHeight,
  )
  displayText.value = result.text
  isTruncated.value = result.truncated
}

function handleClick() {
  if (props.expandable && isTruncated.value) {
    expanded.value = true
    compute()
    emit('expand')
  }
}

const textStyle = computed(() => ({
  fontSize: `${fittedFontSize.value}px`,
  lineHeight: `${props.lineHeight}px`,
}))

watch(() => [props.content, props.width], compute)
onMounted(compute)
</script>

<style lang="scss" scoped>
.adaptive-text {
  display: block;
  color: inherit;
  word-break: break-word;
}

.truncated {
  cursor: pointer;
}
</style>
