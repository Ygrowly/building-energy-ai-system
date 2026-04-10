<template>
  <div class="thinking-cursor" :class="{ finished: isFinished }">
    <!-- 头部：Cursor 风格 "Thought for Xs" -->
    <div class="th-header" @click="toggle">
      <!-- 折叠箭头 -->
      <span class="th-chevron" :class="{ open: !collapsed }">
        <svg width="10" height="10" viewBox="0 0 10 10">
          <path d="M3 1.5L7 5L3 8.5" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>
        </svg>
      </span>

      <!-- 标题文字 -->
      <span class="th-title">
        <template v-if="isFinished">
          已思考 {{ displayDuration }}
        </template>
        <template v-else>
          思考中
          <span class="th-elapsed" v-if="elapsedSeconds > 0">{{ elapsedSeconds }}s</span>
          <span class="th-dots">
            <span></span><span></span><span></span>
          </span>
        </template>
      </span>
    </div>

    <!-- 折叠内容区 -->
    <Transition name="th-slide">
      <div v-if="!collapsed" class="th-body" ref="bodyEl">
        <TransitionGroup name="th-step-appear" tag="div">
          <template v-for="(step, idx) in visibleSteps" :key="step.id">
            <!-- 普通状态步骤（工具调用等） -->
            <div v-if="step.streamContent == null" class="th-step" :class="isToolStep(step.agent) ? 'is-tool' : 'is-think'">
              <span class="th-step-icon" :class="{ breathing: isVisibleActive(idx) }" :style="{ background: agentColor(step.agent) }"></span>
              <span class="th-step-label" :style="{ color: agentColor(step.agent) }">{{ agentLabel(step.agent, idx) }}</span>
              <span class="th-step-msg">{{ typewriterText(step) }}<span v-if="isTyping(step)" class="th-type-cursor"></span></span>
            </div>

            <!-- 流式推理内容 -->
            <div v-else class="th-stream-block">
              <div class="th-stream-header">
                <span class="th-step-icon" :class="{ breathing: isVisibleActive(idx) }" :style="{ background: agentColor(step.agent) }"></span>
                <span class="th-step-label" :style="{ color: agentColor(step.agent) }">{{ agentLabel(step.agent, idx) }}</span>
              </div>
              <div class="th-stream-content">
                <span>{{ step.streamContent }}</span>
                <span v-if="!isFinished" class="th-stream-cursor"></span>
              </div>
            </div>
          </template>
        </TransitionGroup>

        <!-- 加载中 -->
        <div v-if="!isFinished && visibleSteps.length === 0" class="th-step is-loading">
          <span class="th-step-icon breathing" style="background: #D1C4BC"></span>
          <span class="th-step-label thinking-anim">推理中</span>
          <span class="th-loading-dots">
            <span></span><span></span><span></span>
          </span>
        </div>
      </div>
    </Transition>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, watch, nextTick, onMounted, onUnmounted } from 'vue'
import type { ThinkingStep } from '@/stores/chatStore'

const props = defineProps<{
  steps: ThinkingStep[]
  isFinished: boolean
  duration?: number
  startTime?: number
}>()

const collapsed = ref(true)
const bodyEl = ref<HTMLElement>()
const elapsedSeconds = ref(0)
let timer: ReturnType<typeof setInterval> | null = null

// ── 逐行显示队列 ──
const _visibleCount = ref(0)
const _STEP_DELAY = 350 // 行间延迟 ms
let _revealTimer: ReturnType<typeof setTimeout> | null = null

const visibleSteps = computed(() => props.steps.slice(0, _visibleCount.value))

function _scheduleReveal() {
  if (_revealTimer) return
  if (_visibleCount.value >= props.steps.length) return
  _revealTimer = setTimeout(() => {
    _revealTimer = null
    _visibleCount.value++
    // 对新可见的步骤启动打字机
    const step = props.steps[_visibleCount.value - 1]
    if (step && step.streamContent == null) _startTypewriter(step)
    // 还有更多？继续排队
    if (_visibleCount.value < props.steps.length) _scheduleReveal()
  }, _STEP_DELAY)
}

function isVisibleActive(visibleIdx: number): boolean {
  return !props.isFinished && visibleIdx === visibleSteps.value.length - 1
}

// ── 打字机效果 ──
const _twProgress = ref<Record<string, number>>({})
const _twTimers: Record<string, ReturnType<typeof setInterval>> = {}
const _TW_SPEED = 25 // 每字符间隔 ms

function typewriterText(step: ThinkingStep): string {
  const msg = step.message || ''
  const progress = _twProgress.value[step.id]
  if (progress === undefined || progress >= msg.length) return msg
  return msg.slice(0, progress)
}

function isTyping(step: ThinkingStep): boolean {
  const progress = _twProgress.value[step.id]
  return progress !== undefined && progress < (step.message?.length ?? 0)
}

function _startTypewriter(step: ThinkingStep) {
  if (!step.message || _twTimers[step.id]) return
  _twProgress.value[step.id] = 0
  _twTimers[step.id] = setInterval(() => {
    const current = _twProgress.value[step.id] ?? 0
    if (current >= (step.message?.length ?? 0)) {
      clearInterval(_twTimers[step.id])
      delete _twTimers[step.id]
      return
    }
    _twProgress.value[step.id] = current + 1
  }, _TW_SPEED)
}

function _finishTypewriter(stepId: string) {
  if (_twTimers[stepId]) {
    clearInterval(_twTimers[stepId])
    delete _twTimers[stepId]
  }
  delete _twProgress.value[stepId]
}

// 思考进行中：实时计时
onMounted(() => {
  if (!props.isFinished && props.startTime) {
    timer = setInterval(() => {
      elapsedSeconds.value = Math.round((performance.now() - props.startTime!) / 1000)
    }, 1000)
  }
})

onUnmounted(() => {
  if (timer) clearInterval(timer)
  if (_revealTimer) { clearTimeout(_revealTimer); _revealTimer = null }
  for (const id of Object.keys(_twTimers)) {
    clearInterval(_twTimers[id])
    delete _twTimers[id]
  }
})

// 思考完成时：立即显示全部 + 停止动画
watch(() => props.isFinished, (finished) => {
  if (finished) {
    if (timer) { clearInterval(timer); timer = null }
    if (_revealTimer) { clearTimeout(_revealTimer); _revealTimer = null }
    _visibleCount.value = props.steps.length
    for (const id of Object.keys(_twTimers)) _finishTypewriter(id)
  }
})

// 新步骤出现时触发逐行显示队列
watch(() => props.steps.length, (newLen) => {
  if (newLen > 0 && collapsed.value) {
    collapsed.value = false
  }
  // 有新步骤待显示，启动逐行队列
  if (newLen > _visibleCount.value) {
    // 已显示的步骤中，正在打字的立即完成（让位给新行）
    for (let i = 0; i < _visibleCount.value; i++) {
      const step = props.steps[i]
      if (step && step.streamContent == null) _finishTypewriter(step.id)
    }
    _scheduleReveal()
  }
})

// 自动滚动到底部
watch(() => {
  const last = props.steps[props.steps.length - 1]
  return last?.streamContent?.length ?? 0
}, async () => {
  if (!props.isFinished && bodyEl.value) {
    await nextTick()
    bodyEl.value.scrollTop = bodyEl.value.scrollHeight
  }
})

const displayDuration = computed(() => {
  const secs = props.duration ?? elapsedSeconds.value
  if (secs < 1) return '<1s'
  if (secs >= 60) return `${Math.floor(secs / 60)}m ${secs % 60}s`
  return `${secs}s`
})

function toggle() {
  collapsed.value = !collapsed.value
}

function isToolStep(agent: string) {
  return agent === 'tool' || agent === 'tools'
}

/** agent 类型 → 莫兰蒂提亮配色 */
const agentColorMap: Record<string, string> = {
  router:         '#3B82C4',  // 信息蓝
  data_agent:     '#259468',  // 数据绿
  diagnose_agent: '#D4782C',  // 警示橙
  tool:           '#7C5CB8',  // 执行紫
  tools:          '#7C5CB8',  // 执行紫
  agent:          '#8A7B96',  // 思考灰紫
}

function agentColor(agent: string): string {
  return agentColorMap[agent] ?? '#8A7B96'
}

/** 判断某个 step 是否正在执行（最后一步 + 整体未完成） */
function isActiveStep(index: number): boolean {
  return !props.isFinished && index === props.steps.length - 1
}

const _agentLabelMap: Record<string, string> = {
  router:         '路由',
  data_agent:     '数据分析师',
  diagnose_agent: '能效分析师',
  tool:           '工具调用',
  agent:          '推理',
  tools:          '工具执行',
  web_search:     '联网搜索',
}

function agentLabel(agent: string, stepIdx?: number): string {
  // 优先使用后端传来的意图驱动标签
  if (stepIdx !== undefined) {
    const step = props.steps[stepIdx]
    if (step?.displayLabel) return step.displayLabel
  }
  const fallbackMap: Record<string, string> = {
    router: '需求理解',
    data_agent: '数据采集',
    diagnose_agent: '故障诊断',
    tool: '工具调用',
    tools: '工具调用',
    agent: '推理',
    web_search: '联网搜索',
  }
  return fallbackMap[agent] ?? _agentLabelMap[agent] ?? agent
}
</script>

<style scoped>
/* ─── 容器 ─── */
.thinking-cursor {
  margin-bottom: 6px;
  font-size: 13px;
  color: var(--text-secondary, #999);
}

/* ─── 头部 ─── */
.th-header {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  cursor: pointer;
  user-select: none;
  padding: 4px 8px;
  border-radius: 6px;
  transition: background 0.15s;
  color: var(--text-muted, #888);
}

.th-header:hover {
  background: rgba(128, 128, 128, 0.08);
}

/* 箭头 */
.th-chevron {
  display: flex;
  align-items: center;
  transition: transform 0.2s ease;
  opacity: 0.6;
  flex-shrink: 0;
}

.th-chevron.open {
  transform: rotate(90deg);
}

/* 标题 */
.th-title {
  font-size: 12.5px;
  color: var(--text-muted, #888);
  display: inline-flex;
  align-items: center;
  gap: 5px;
  letter-spacing: 0.01em;
}

.th-elapsed {
  opacity: 0.65;
  font-size: 11.5px;
  font-variant-numeric: tabular-nums;
}

/* 思考中的点动画 */
.th-dots {
  display: inline-flex;
  gap: 3px;
  align-items: center;
  margin-left: 2px;
}
.th-dots span {
  width: 3px;
  height: 3px;
  border-radius: 50%;
  background: var(--text-muted, #888);
  animation: th-bounce 1.2s infinite;
}
.th-dots span:nth-child(2) { animation-delay: 0.2s; }
.th-dots span:nth-child(3) { animation-delay: 0.4s; }

@keyframes th-bounce {
  0%, 80%, 100% { opacity: 0.3; transform: translateY(0); }
  40% { opacity: 1; transform: translateY(-2px); }
}

/* ─── 内容区 ─── */
.th-body {
  margin-top: 4px;
  margin-left: 10px;
  padding-left: 12px;
  border-left: 1.5px solid rgba(128, 128, 128, 0.18);
  max-height: 420px;
  overflow-y: auto;
  scrollbar-width: thin;
}

/* ─── 普通步骤 ─── */
.th-step {
  display: flex;
  align-items: flex-start;
  gap: 7px;
  padding: 3px 6px 3px 2px;
  font-size: 12px;
  line-height: 1.65;
  border-radius: 4px;
}

.th-step-icon {
  flex-shrink: 0;
  width: 6px;
  height: 6px;
  border-radius: 50%;
  margin-top: 5px;
}

/* 正在执行的步骤：呼吸缩放动画 */
.th-step-icon.breathing {
  animation: th-breathe 1.6s ease-in-out infinite;
}

@keyframes th-breathe {
  0%, 100% { transform: scale(1);   opacity: 0.7; }
  50%      { transform: scale(1.8); opacity: 1; }
}

.th-step-label {
  font-weight: 600;
  white-space: nowrap;
  flex-shrink: 0;
  font-size: 11px;
  letter-spacing: 0.02em;
}

.th-step-msg {
  color: var(--text-secondary, #aaa);
  word-break: break-word;
  font-size: 11.5px;
  line-height: 1.65;
  letter-spacing: 0.01em;
}

/* 打字机光标 */
.th-type-cursor {
  display: inline-block;
  width: 1.5px;
  height: 12px;
  background: currentColor;
  vertical-align: middle;
  margin-left: 1px;
  opacity: 0.6;
  animation: blink-cursor 0.8s infinite;
}

/* 工具调用步骤 */
.is-tool .th-step-msg {
  font-size: 11.5px;
  color: var(--text-secondary, #aaa);
  font-family: 'JetBrains Mono', 'Cascadia Code', Consolas, monospace;
  font-size: 11px;
}

/* ─── 流式推理内容块 ─── */
.th-stream-block {
  padding: 4px 6px 6px 2px;
  margin: 3px 0;
}

.th-stream-header {
  display: flex;
  align-items: center;
  gap: 7px;
  margin-bottom: 5px;
}

.th-stream-content {
  color: var(--text-secondary, #aaa);
  font-size: 12px;
  line-height: 1.8;
  white-space: pre-wrap;
  word-break: break-word;
  letter-spacing: 0.01em;
  padding: 8px 10px;
  background: rgba(128, 128, 128, 0.04);
  border-radius: 6px;
  border: 1px solid rgba(128, 128, 128, 0.08);
  max-height: 260px;
  overflow-y: auto;
  scrollbar-width: thin;
}

/* 流式打字光标 */
.th-stream-cursor {
  display: inline-block;
  width: 2px;
  height: 14px;
  background: var(--thinking-color, #4ade80);
  vertical-align: middle;
  border-radius: 1px;
  margin-left: 1px;
  animation: blink-cursor 0.8s infinite;
}

@keyframes blink-cursor {
  0%, 100% { opacity: 1; }
  50% { opacity: 0; }
}

/* 加载中 */
.thinking-anim {
  color: var(--thinking-color, #4ade80);
}

.th-loading-dots {
  display: inline-flex;
  gap: 3px;
  align-items: center;
  margin-left: 4px;
}
.th-loading-dots span {
  width: 3px;
  height: 3px;
  border-radius: 50%;
  background: var(--thinking-color, #4ade80);
  animation: th-bounce 1.2s infinite;
}
.th-loading-dots span:nth-child(2) { animation-delay: 0.2s; }
.th-loading-dots span:nth-child(3) { animation-delay: 0.4s; }

/* ─── 折叠动画 ─── */
.th-slide-enter-active {
  animation: slide-down 0.2s ease-out;
  overflow: hidden;
}
.th-slide-leave-active {
  animation: slide-up 0.15s ease-in;
  overflow: hidden;
}

@keyframes slide-down {
  from { max-height: 0; opacity: 0; }
  to   { max-height: 400px; opacity: 1; }
}
@keyframes slide-up {
  from { max-height: 400px; opacity: 1; }
  to   { max-height: 0; opacity: 0; }
}

/* 逐行出现动画 */
.th-step-appear-enter-active {
  transition: opacity 0.25s ease, transform 0.25s ease;
}
.th-step-appear-enter-from {
  opacity: 0;
  transform: translateY(6px);
}
</style>
