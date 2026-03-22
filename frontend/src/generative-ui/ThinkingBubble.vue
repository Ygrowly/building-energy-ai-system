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
          Thought for {{ displayDuration }}
        </template>
        <template v-else>
          Thinking
          <span class="th-elapsed" v-if="elapsedSeconds > 0">{{ elapsedSeconds }}s</span>
          <span class="th-dots">
            <span></span><span></span><span></span>
          </span>
        </template>
      </span>
    </div>

    <!-- 折叠内容区 -->
    <Transition name="th-slide">
      <div v-if="!collapsed" class="th-body">
        <div
          v-for="step in steps"
          :key="step.id"
          class="th-step"
          :class="isToolStep(step.agent) ? 'is-tool' : 'is-think'"
        >
          <span class="th-step-icon">{{ isToolStep(step.agent) ? '⚡' : '💭' }}</span>
          <span class="th-step-label">{{ agentLabel(step.agent) }}</span>
          <span class="th-step-msg">{{ step.message }}</span>
        </div>

        <!-- 思考中加载 -->
        <div v-if="!isFinished" class="th-step is-loading">
          <span class="th-step-icon">💭</span>
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
import { ref, computed, onMounted, onUnmounted } from 'vue'
import type { ThinkingStep } from '@/stores/chatStore'

const props = defineProps<{
  steps: ThinkingStep[]
  isFinished: boolean
  duration?: number        // 秒，来自 thinkingDuration
  startTime?: number       // performance.now()，来自 thinkingStartTime
}>()

const collapsed = ref(true)    // 默认折叠
const elapsedSeconds = ref(0)
let timer: ReturnType<typeof setInterval> | null = null

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
})

// 完成时的显示时长
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

function agentLabel(agent: string): string {
  const map: Record<string, string> = {
    router:         '路由',
    data_agent:     '数据分析',
    diagnose_agent: '故障诊断',
    tool:           '工具调用',
    agent:          '推理',
    tools:          '工具执行',
  }
  return map[agent] ?? agent
}
</script>

<style scoped>
/* ─── 容器 ─── */
.thinking-cursor {
  margin-bottom: 4px;
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
  font-size: 13px;
  color: var(--text-muted, #888);
  display: inline-flex;
  align-items: center;
  gap: 4px;
}

.th-elapsed {
  opacity: 0.7;
  font-size: 12px;
}

/* 思考中的点动画 */
.th-dots {
  display: inline-flex;
  gap: 2px;
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
  margin-left: 8px;
  padding-left: 12px;
  border-left: 1.5px solid rgba(128, 128, 128, 0.2);
  max-height: 300px;
  overflow-y: auto;
  scrollbar-width: thin;
}

/* ─── 每一步 ─── */
.th-step {
  display: flex;
  align-items: flex-start;
  gap: 6px;
  padding: 3px 6px;
  font-size: 12px;
  line-height: 1.6;
  border-radius: 4px;
}

.th-step-icon {
  flex-shrink: 0;
  font-size: 11px;
  margin-top: 1px;
}

.th-step-label {
  font-weight: 600;
  color: var(--text-muted, #888);
  white-space: nowrap;
  flex-shrink: 0;
  font-size: 11px;
}

.th-step-msg {
  color: var(--text-secondary, #aaa);
  word-break: break-word;
  font-size: 12px;
}

/* 工具调用步骤高亮 */
.is-tool .th-step-label {
  color: var(--accent, #6c8ef5);
}
.is-tool .th-step-msg {
  font-family: 'Consolas', 'Monaco', monospace;
  font-size: 11px;
  color: var(--text-primary, #ccc);
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
  to   { max-height: 300px; opacity: 1; }
}
@keyframes slide-up {
  from { max-height: 300px; opacity: 1; }
  to   { max-height: 0; opacity: 0; }
}
</style>
