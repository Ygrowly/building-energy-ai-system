<template>
  <div class="timeline-shell">
    <div class="timeline-header">
      <p class="section-title">执行时间线</p>
      <button
        v-if="hasCollapsedSteps"
        class="timeline-toggle"
        type="button"
        @click="toggleHistory"
      >
        {{ showAll ? '收起历史' : `展开全部 ${hiddenCount} 条` }}
      </button>
    </div>

    <div v-if="loading" class="timeline-loading">
      <div class="timeline-skeleton">
        <span v-for="step in 4" :key="step" class="timeline-skeleton-step" />
      </div>
      <p class="timeline-hint">加载完整派工历史...</p>
    </div>

    <p v-else-if="error" class="timeline-hint error">{{ error }}</p>

    <template v-else-if="normalizedItems.length">
      <div class="timeline-viewport">
        <div class="timeline-track">
          <span class="timeline-line" />

          <template v-for="step in visibleSteps" :key="step.id">
            <button
              v-if="step.type === 'collapsed'"
              class="timeline-collapse"
              type="button"
              @click="showAll = true"
            >
              +{{ step.hiddenCount }}
            </button>

            <button
              v-else
              class="timeline-step"
              :class="[step.tone, { active: activeStepId === step._id }]"
              type="button"
              @click="activeStepId = step._id"
            >
              <span class="timeline-marker" />
              <span class="timeline-step-label">{{ step.label }}</span>
              <span class="timeline-step-time">{{ step.time }}</span>
            </button>
          </template>
        </div>
      </div>

      <div v-if="activeStep" class="timeline-detail" :class="activeStep.tone">
        <div class="timeline-detail-head">
          <div class="timeline-detail-main">
            <span class="timeline-detail-label">{{ activeStep.label }}</span>
            <span v-if="activeStep.attemptNo" class="timeline-detail-attempt">
              第 {{ activeStep.attemptNo }} 次派工
            </span>
          </div>
          <span class="timeline-detail-time">{{ activeStep.time }}</span>
        </div>
        <p class="timeline-detail-note">{{ activeStep.note || '当前节点暂无补充说明' }}</p>
      </div>
    </template>

    <p v-else class="timeline-hint">暂无执行时间线</p>
  </div>
</template>

<script setup lang="ts">
import { computed, ref, watch, type PropType } from 'vue'

interface TimelineItem {
  id?: string
  time?: string
  label: string
  note?: string
  tone?: string
  attemptNo?: number | null
}

interface NormalizedTimelineItem extends TimelineItem {
  _id: string
  tone: string
}

type TimelineDisplayItem =
  | (NormalizedTimelineItem & { type: 'step' })
  | { id: string; type: 'collapsed'; hiddenCount: number }

const collapseThreshold = 6

const props = defineProps({
  items: {
    type: Array as PropType<TimelineItem[]>,
    required: true,
  },
  loading: {
    type: Boolean,
    default: false,
  },
  error: {
    type: String,
    default: '',
  },
})

const showAll = ref(false)
const activeStepId = ref<string | null>(null)

const normalizedItems = computed<NormalizedTimelineItem[]>(() => (
  props.items.map((item, index) => ({
    ...item,
    _id: item.id || `timeline-step-${index}-${item.label}-${item.time || ''}`,
    tone: item.tone || 'neutral',
  }))
))

const hasCollapsedSteps = computed(() => normalizedItems.value.length > collapseThreshold)
const hiddenCount = computed(() => Math.max(normalizedItems.value.length - 5, 0))

const visibleSteps = computed<TimelineDisplayItem[]>(() => {
  if (!hasCollapsedSteps.value || showAll.value) {
    return normalizedItems.value.map(item => ({ ...item, type: 'step' as const }))
  }

  const leading = normalizedItems.value.slice(0, 2)
  const trailing = normalizedItems.value.slice(-3)

  return [
    ...leading.map(item => ({ ...item, type: 'step' as const })),
    { id: 'timeline-collapsed', type: 'collapsed' as const, hiddenCount: hiddenCount.value },
    ...trailing.map(item => ({ ...item, type: 'step' as const })),
  ]
})

const activeStep = computed(() => (
  normalizedItems.value.find(item => item._id === activeStepId.value) || normalizedItems.value[normalizedItems.value.length - 1] || null
))

watch(normalizedItems, (items) => {
  if (!items.length) {
    activeStepId.value = null
    showAll.value = false
    return
  }

  if (!items.some(item => item._id === activeStepId.value)) {
    activeStepId.value = items[items.length - 1]._id
  }
}, { immediate: true })

function toggleHistory() {
  showAll.value = !showAll.value
  if (!showAll.value && normalizedItems.value.length) {
    activeStepId.value = normalizedItems.value[normalizedItems.value.length - 1]._id
  }
}
</script>

<style scoped>
.timeline-shell {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.timeline-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.section-title {
  font-size: 13px;
  font-weight: 700;
  color: var(--wo-text-strong, var(--text-primary));
}

.timeline-toggle {
  border: 1px solid var(--wo-border, var(--border));
  border-radius: 999px;
  background: transparent;
  color: var(--wo-text, var(--text-secondary));
  font-size: 12px;
  font-weight: 600;
  padding: 4px 10px;
  cursor: pointer;
}

.timeline-loading {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.timeline-skeleton {
  display: flex;
  gap: 16px;
  overflow: hidden;
}

.timeline-skeleton-step {
  width: 128px;
  height: 54px;
  border-radius: 14px;
  flex-shrink: 0;
  background: linear-gradient(90deg, rgba(148, 163, 184, 0.1), rgba(148, 163, 184, 0.2), rgba(148, 163, 184, 0.1));
}

.timeline-hint {
  font-size: 12px;
  color: var(--wo-text, var(--text-secondary));
}

.timeline-hint.error {
  color: var(--wo-chip-danger-text, var(--danger));
}

.timeline-viewport {
  overflow-x: auto;
  overflow-y: hidden;
  padding-bottom: 4px;
}

.timeline-track {
  position: relative;
  display: flex;
  align-items: flex-start;
  gap: 16px;
  min-width: max-content;
  padding: 10px 2px 4px;
}

.timeline-line {
  position: absolute;
  top: 24px;
  left: 20px;
  right: 20px;
  height: 2px;
  border-radius: 999px;
  background: linear-gradient(90deg, rgba(34, 197, 94, 0.18), rgba(59, 130, 246, 0.2));
}

.timeline-step,
.timeline-collapse {
  position: relative;
  z-index: 1;
  min-width: 136px;
  max-width: 160px;
  padding: 0;
  border: none;
  background: transparent;
  text-align: left;
  cursor: pointer;
  flex-shrink: 0;
}

.timeline-step {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.timeline-collapse {
  margin-top: 6px;
  border: 1px dashed var(--wo-border, var(--border));
  border-radius: 999px;
  padding: 7px 12px;
  background: var(--wo-surface, var(--bg-panel));
  color: var(--wo-text, var(--text-secondary));
  font-size: 12px;
  font-weight: 700;
  align-self: center;
}

.timeline-marker {
  width: 16px;
  height: 16px;
  border-radius: 999px;
  border: 3px solid currentColor;
  background: var(--wo-surface, var(--bg-panel));
  box-shadow: 0 0 0 4px rgba(255, 255, 255, 0.72);
}

.timeline-step-label,
.timeline-step-time {
  display: block;
}

.timeline-step-label {
  color: var(--wo-text-strong, var(--text-primary));
  font-size: 12px;
  font-weight: 700;
  line-height: 1.5;
}

.timeline-step-time {
  color: var(--wo-text-subtle, var(--text-muted));
  font-size: 11px;
}

.timeline-step.success { color: var(--wo-chip-success-text, var(--success)); }
.timeline-step.accent { color: var(--wo-chip-info-text, var(--accent)); }
.timeline-step.warning { color: var(--wo-chip-warning-text, var(--warning)); }
.timeline-step.danger { color: var(--wo-chip-danger-text, var(--danger)); }
.timeline-step.neutral { color: var(--wo-chip-muted-text, var(--text-secondary)); }

.timeline-step.active .timeline-marker {
  box-shadow: 0 0 0 4px rgba(255, 255, 255, 0.72), 0 0 0 8px rgba(34, 197, 94, 0.12);
}

.timeline-step.active .timeline-step-label {
  color: currentColor;
}

.timeline-detail {
  border: 1px solid var(--wo-border, var(--border));
  border-left-width: 4px;
  border-radius: 14px;
  padding: 14px 16px;
  background: rgba(255, 255, 255, 0.55);
}

.timeline-detail.success {
  border-left-color: var(--wo-chip-success-text, var(--success));
  background: var(--wo-chip-success-bg, rgba(16, 185, 129, 0.1));
}

.timeline-detail.accent {
  border-left-color: var(--wo-chip-info-text, var(--accent));
  background: var(--wo-chip-info-bg, rgba(59, 130, 246, 0.1));
}

.timeline-detail.warning {
  border-left-color: var(--wo-chip-warning-text, var(--warning));
  background: var(--wo-chip-warning-bg, rgba(251, 191, 36, 0.12));
}

.timeline-detail.danger {
  border-left-color: var(--wo-chip-danger-text, var(--danger));
  background: var(--wo-chip-danger-bg, rgba(248, 113, 113, 0.12));
}

.timeline-detail.neutral {
  border-left-color: var(--wo-chip-muted-text, var(--text-secondary));
  background: var(--wo-chip-muted-bg, rgba(148, 163, 184, 0.12));
}

.timeline-detail-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 8px;
}

.timeline-detail-main {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.timeline-detail-label {
  color: var(--wo-text-strong, var(--text-primary));
  font-size: 13px;
  font-weight: 700;
}

.timeline-detail-attempt {
  color: var(--wo-text, var(--text-secondary));
  font-size: 12px;
}

.timeline-detail-time {
  color: var(--wo-text-subtle, var(--text-muted));
  font-size: 12px;
  white-space: nowrap;
}

.timeline-detail-note {
  color: var(--wo-text, var(--text-secondary));
  font-size: 12px;
  line-height: 1.7;
  white-space: pre-wrap;
}

@media (max-width: 720px) {
  .timeline-step,
  .timeline-collapse {
    min-width: 120px;
    max-width: 132px;
  }

  .timeline-detail-head {
    flex-direction: column;
  }
}
</style>
