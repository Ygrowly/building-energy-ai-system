<template>
  <section class="auto-review">
    <div class="auto-review-head">
      <div class="auto-review-copy">
        <p class="auto-review-title">自动派工复核</p>
        <p class="auto-review-note">{{ review.review_hint || '复核候选人、分数与当前负载' }}</p>
      </div>
      <span class="auto-review-mode" :class="{ fallback: review.dispatch_mode === 'auto_fallback' }">
        {{ review.strategy_label || dispatchModeLabel }}
      </span>
    </div>

    <div class="auto-review-state" :class="reviewState.status">
      <span>{{ reviewState.status_label || reviewStatusLabel }}</span>
      <small v-if="reviewState.notes">{{ reviewState.notes }}</small>
    </div>

    <div class="auto-review-grid">
      <div class="auto-review-item">
        <span class="auto-review-label">推荐人员</span>
        <strong>{{ selectedCandidate.username || '—' }}</strong>
        <small>{{ candidateMeta }}</small>
      </div>

      <div class="auto-review-item">
        <span class="auto-review-label">推荐分</span>
        <strong>{{ scoreText }}</strong>
        <small>{{ minScoreText }}</small>
      </div>

      <div class="auto-review-item">
        <span class="auto-review-label">分差</span>
        <strong>{{ scoreGapText }}</strong>
        <small>{{ secondCandidateText }}</small>
      </div>

      <div class="auto-review-item wide">
        <span class="auto-review-label">派工依据</span>
        <strong>{{ review.selection_reason || selectedCandidate.recommend_reason || '规则命中' }}</strong>
        <small>{{ skillText }}</small>
      </div>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, type PropType } from 'vue'

const props = defineProps({
  review: {
    type: Object as PropType<any>,
    required: true,
  },
})

const selectedCandidate = computed(() => (
  props.review.selected_candidate
  || props.review.top_candidate
  || {}
))
const secondCandidate = computed(() => props.review.second_candidate || {})
const rules = computed(() => props.review.rules || {})
const reviewState = computed(() => props.review.review_state || { status: 'pending', status_label: '待复核' })

const dispatchModeLabel = computed(() => (
  props.review.dispatch_mode === 'auto_fallback' ? '低置信兜底派工' : '高置信自动派工'
))

const reviewStatusLabel = computed(() => {
  const labels: Record<string, string> = {
    pending: '待复核',
    reviewed: '已复核',
    needs_reassign: '需改派',
  }
  return labels[reviewState.value.status] || reviewState.value.status || '待复核'
})

const candidateMeta = computed(() => {
  const loadText = selectedCandidate.value.load_text
    || (
      selectedCandidate.value.current_active_orders != null && selectedCandidate.value.max_active_orders != null
        ? `${selectedCandidate.value.current_active_orders}/${selectedCandidate.value.max_active_orders}`
        : ''
    )
  const parts = [
    selectedCandidate.value.team_name,
    selectedCandidate.value.shift_label || shiftStatusLabel(selectedCandidate.value.shift_status),
    loadText ? `负载 ${loadText}` : '',
  ].filter(Boolean)
  return parts.length ? parts.join(' · ') : '班组与负载待补充'
})

const scoreText = computed(() => {
  const score = selectedCandidate.value.score
  return score == null ? '—' : `${score} 分`
})

const scoreGapText = computed(() => {
  const gap = props.review.score_gap
  return gap == null ? '—' : `${gap} 分`
})

const minScoreText = computed(() => {
  const minScore = rules.value.min_score
  const minGap = rules.value.min_gap
  if (minScore == null && minGap == null) return '规则阈值未记录'
  return [
    minScore != null ? `达标线 ${minScore}` : '',
    minGap != null ? `分差线 ${minGap}` : '',
  ].filter(Boolean).join(' · ')
})

const secondCandidateText = computed(() => {
  if (!secondCandidate.value.username) return '暂无第二候选'
  const score = secondCandidate.value.score == null ? '' : ` ${secondCandidate.value.score} 分`
  return `第二候选 ${secondCandidate.value.username}${score}`
})

const skillText = computed(() => {
  const names = selectedCandidate.value.matched_skill_names || []
  return names.length ? `技能命中：${names.join(' / ')}` : '技能命中待补充'
})

function shiftStatusLabel(status: string | undefined) {
  const labels: Record<string, string> = {
    on_duty: '值班中',
    standby: '待命',
    off_duty: '离岗',
  }
  return status ? labels[status] || status : ''
}
</script>

<style scoped>
.auto-review {
  margin-top: 16px;
  padding: 14px;
  border: 1px solid rgba(34, 197, 94, 0.24);
  border-radius: 8px;
  background: rgba(34, 197, 94, 0.07);
}

.auto-review-head {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  align-items: flex-start;
  margin-bottom: 12px;
}

.auto-review-copy {
  min-width: 0;
}

.auto-review-title {
  font-size: 13px;
  font-weight: 700;
  color: var(--wo-text-strong, var(--text-primary));
}

.auto-review-note,
.auto-review-item small {
  color: var(--wo-text, var(--text-secondary));
  font-size: 12px;
  line-height: 1.6;
}

.auto-review-mode {
  flex-shrink: 0;
  border: 1px solid rgba(34, 197, 94, 0.32);
  border-radius: 8px;
  padding: 4px 8px;
  color: #166534;
  background: rgba(220, 252, 231, 0.84);
  font-size: 12px;
  font-weight: 700;
}

.auto-review-mode.fallback {
  border-color: rgba(245, 158, 11, 0.34);
  color: #92400e;
  background: rgba(254, 243, 199, 0.88);
}

.auto-review-state {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 12px;
  border: 1px solid rgba(245, 158, 11, 0.3);
  border-radius: 8px;
  padding: 5px 8px;
  color: #92400e;
  background: rgba(254, 243, 199, 0.72);
  font-size: 12px;
  font-weight: 700;
}

.auto-review-state.reviewed {
  border-color: rgba(34, 197, 94, 0.32);
  color: #166534;
  background: rgba(220, 252, 231, 0.8);
}

.auto-review-state.needs_reassign {
  border-color: rgba(248, 113, 113, 0.34);
  color: #b91c1c;
  background: rgba(254, 226, 226, 0.82);
}

.auto-review-state small {
  color: inherit;
  font-size: 12px;
  font-weight: 600;
  line-height: 1.5;
}

.auto-review-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 10px;
}

.auto-review-item {
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.auto-review-item.wide {
  grid-column: 1 / -1;
}

.auto-review-label {
  color: var(--wo-text-subtle, var(--text-muted));
  font-size: 12px;
  font-weight: 600;
}

.auto-review-item strong {
  color: var(--wo-text-strong, var(--text-primary));
  font-size: 13px;
  line-height: 1.6;
  word-break: break-word;
}

@media (max-width: 720px) {
  .auto-review-head {
    flex-direction: column;
  }

  .auto-review-grid {
    grid-template-columns: 1fr;
  }
}
</style>
