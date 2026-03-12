<template>
  <div class="thinking-block" :class="{ 'is-finished': isFinished }">
    <!-- 头部：点击折叠/展开（仅完成后可交互） -->
    <div class="th-header" :class="{ 'is-collapsed': collapsed }" @click="toggleCollapse">
      <span class="th-icon">
        <Icon icon="mdi:brain" width="14" />
      </span>

      <span class="th-label">
        <!-- 思考中：动画标题 + 最新步骤预览 -->
        <template v-if="!isFinished">
          <span class="th-animating">
            正在思考
            <span class="dot-wave">
              <span></span><span></span><span></span>
            </span>
          </span>
          <span v-if="latestStep" class="th-preview">{{ latestStep.message }}</span>
        </template>

        <!-- 思考完成：步骤摘要 -->
        <template v-else>
          <span class="th-summary">
            已思考 <strong>{{ steps.length }}</strong> 步
          </span>
          <span v-if="toolStepCount > 0" class="th-tool-badge">
            <Icon icon="mdi:function-variant" width="11" />
            {{ toolStepCount }} 次工具调用
          </span>
        </template>
      </span>

      <!-- 折叠时：明确的展开提示文字 -->
      <span v-if="isFinished && collapsed" class="th-expand-hint">点击展开</span>

      <Icon
        v-if="isFinished"
        :icon="collapsed ? 'mdi:chevron-down' : 'mdi:chevron-up'"
        width="15"
        class="th-chevron"
        :class="{ rotated: !collapsed }"
      />
    </div>

    <!-- 内容体：固定高度可滚动，无滚动条 -->
    <Transition name="th-expand">
      <div v-if="!collapsed" class="th-body" ref="bodyEl">
        <div
          v-for="step in steps"
          :key="step.id"
          class="step-row"
          :class="step.agent === 'tool' ? 'step-tool' : 'step-think'"
        >
          <span class="step-icon-wrap">
            <Icon :icon="stepIcon(step.agent)" width="12" />
          </span>
          <div class="step-content">
            <span class="step-agent-tag">{{ agentLabel(step.agent) }}</span>
            <span class="step-msg">{{ step.message }}</span>
          </div>
        </div>

        <!-- 正在思考时的加载指示器 -->
        <div v-if="!isFinished" class="step-loading-row">
          <span></span><span></span><span></span>
        </div>
      </div>
    </Transition>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, watch, nextTick } from 'vue'
import { Icon } from '@iconify/vue'
import type { ThinkingStep } from '@/stores/chatStore'

const props = defineProps<{
  steps: ThinkingStep[]
  isFinished: boolean
}>()

const collapsed = ref(false)
const bodyEl = ref<HTMLElement>()

function toggleCollapse() {
  if (props.isFinished) {
    collapsed.value = !collapsed.value
  }
}

const latestStep = computed(() => props.steps[props.steps.length - 1] ?? null)

const toolStepCount = computed(() => props.steps.filter(s => s.agent === 'tool').length)

// 思考进行中：有新步骤则自动滚动到底部
watch(() => props.steps.length, async () => {
  if (!props.isFinished) {
    await nextTick()
    if (bodyEl.value) {
      bodyEl.value.scrollTop = bodyEl.value.scrollHeight
    }
  }
})

// 思考完成后保持展开，让用户可自行决定是否折叠

function stepIcon(agent: string): string {
  const map: Record<string, string> = {
    router:         'mdi:shuffle-variant',
    data_agent:     'mdi:chart-bar',
    diagnose_agent: 'mdi:microscope',
    tool:           'mdi:function-variant',
    agent:          'mdi:brain',           // create_react_agent 内部推理节点
    tools:          'mdi:tools',           // create_react_agent 内部工具节点
  }
  return map[agent] ?? 'mdi:thought-bubble-outline'
}

function agentLabel(agent: string): string {
  const map: Record<string, string> = {
    router:         '路由',
    data_agent:     '数据分析',
    diagnose_agent: '故障诊断',
    tool:           '工具调用',
    agent:          '推理',               // create_react_agent 内部推理节点
    tools:          '工具执行',           // create_react_agent 内部工具节点
  }
  return map[agent] ?? agent
}
</script>

<style scoped>
/* ─── 容器 ───────────────────────────────────────── */
.thinking-block {
  border: 1px solid var(--border);
  border-left: 3px solid var(--thinking-color);
  border-radius: 8px;
  overflow: hidden;
  font-size: 12px;
  background: var(--accent-glow);
  margin-bottom: 6px;
  flex-shrink: 0;
  box-shadow: var(--card-shadow);
}

/* ─── 头部 ───────────────────────────────────────── */
.th-header {
  display: flex;
  align-items: center;
  gap: 7px;
  padding: 8px 12px;
  cursor: default;
  user-select: none;
  color: var(--thinking-color);
  min-height: 36px;
  transition: background 0.15s;
}

.is-finished .th-header {
  cursor: pointer;
}
.is-finished .th-header:hover {
  background: rgba(108, 142, 245, 0.07);
}

/* 折叠时头部：更醒目的背景 + 底部无分割线 */
.is-finished .th-header.is-collapsed {
  background: rgba(108, 142, 245, 0.06);
  border-bottom: none;
}
.is-finished .th-header.is-collapsed:hover {
  background: rgba(108, 142, 245, 0.12);
}

.th-icon {
  display: flex;
  align-items: center;
  flex-shrink: 0;
  opacity: 0.85;
}

.th-label {
  flex: 1;
  display: flex;
  align-items: center;
  gap: 8px;
  overflow: hidden;
}

/* 思考中 */
.th-animating {
  display: flex;
  align-items: center;
  gap: 5px;
  white-space: nowrap;
  flex-shrink: 0;
}

.th-preview {
  color: var(--text-muted);
  font-size: 11px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  flex: 1;
}

/* 思考完成 */
.th-summary {
  color: var(--text-secondary);
  white-space: nowrap;
}
.th-summary strong {
  color: var(--thinking-color);
}

.th-tool-badge {
  display: inline-flex;
  align-items: center;
  gap: 3px;
  background: rgba(108, 142, 245, 0.12);
  border: 1px solid rgba(108, 142, 245, 0.25);
  border-radius: 10px;
  padding: 1px 7px;
  font-size: 10px;
  color: var(--thinking-color);
  white-space: nowrap;
}

.th-expand-hint {
  font-size: 10px;
  color: var(--thinking-color);
  opacity: 0.7;
  white-space: nowrap;
  letter-spacing: 0.02em;
}

.th-chevron {
  color: var(--text-muted);
  flex-shrink: 0;
  transition: transform 0.25s ease;
}
.th-chevron.rotated {
  transform: rotate(180deg);
}

/* 动态省略号 */
.dot-wave {
  display: inline-flex;
  gap: 3px;
  align-items: center;
}
.dot-wave span {
  width: 3px;
  height: 3px;
  border-radius: 50%;
  background: var(--thinking-color);
  animation: dw 1.2s infinite;
}
.dot-wave span:nth-child(2) { animation-delay: 0.2s; }
.dot-wave span:nth-child(3) { animation-delay: 0.4s; }

@keyframes dw {
  0%, 80%, 100% { transform: translateY(0); opacity: 0.35; }
  40%           { transform: translateY(-3px); opacity: 1; }
}

/* ─── 内容体：固定高度 + 无滚动条 ──────────────────── */
.th-body {
  max-height: 180px;
  overflow-y: auto;
  scrollbar-width: none;       /* Firefox */
  border-top: 1px solid var(--border);
  padding: 5px 0;
}
.th-body::-webkit-scrollbar { display: none; }   /* Chrome / Safari */

/* ─── 步骤行 ─────────────────────────────────────── */
.step-row {
  display: flex;
  align-items: flex-start;
  gap: 7px;
  padding: 4px 12px;
}

.step-icon-wrap {
  flex-shrink: 0;
  margin-top: 2px;
  opacity: 0.6;
}

.step-content {
  display: flex;
  flex-direction: column;
  gap: 1px;
  min-width: 0;
}

.step-agent-tag {
  font-size: 10px;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.04em;
  opacity: 0.55;
  line-height: 1.2;
}

.step-msg {
  color: var(--text-secondary);
  line-height: 1.5;
  word-break: break-word;
  font-size: 12px;
}

/* 普通思考步骤 */
.step-think .step-agent-tag { color: var(--thinking-color); opacity: 1; }

/* 工具调用步骤：高亮样式 */
.step-tool {
  background: rgba(108, 142, 245, 0.07);
  border-left: 2px solid rgba(108, 142, 245, 0.3);
  margin: 2px 8px;
  border-radius: 5px;
  padding: 5px 10px;
}
.step-tool .step-icon-wrap { opacity: 1; color: var(--accent); }
.step-tool .step-agent-tag { color: var(--accent); opacity: 1; }
.step-tool .step-msg {
  font-family: 'Consolas', 'Monaco', monospace;
  font-size: 11px;
  color: var(--text-primary);
}

/* 正在思考的加载指示器 */
.step-loading-row {
  display: flex;
  gap: 4px;
  padding: 6px 12px;
  align-items: center;
}
.step-loading-row span {
  width: 5px;
  height: 5px;
  border-radius: 50%;
  background: var(--thinking-color);
  opacity: 0.5;
  animation: dw 1.2s infinite;
}
.step-loading-row span:nth-child(2) { animation-delay: 0.2s; }
.step-loading-row span:nth-child(3) { animation-delay: 0.4s; }

/* ─── 折叠动画 ───────────────────────────────────── */
.th-expand-enter-active {
  animation: expandDown 0.28s ease-out;
  overflow: hidden;
}
.th-expand-leave-active {
  animation: collapseUp 0.22s ease-in;
  overflow: hidden;
}

@keyframes expandDown {
  from { max-height: 0; opacity: 0; }
  to   { max-height: 240px; opacity: 1; }
}
@keyframes collapseUp {
  from { max-height: 240px; opacity: 1; }
  to   { max-height: 0; opacity: 0; }
}
</style>
