<template>
  <div v-if="visible" class="dispatch-mask" @click="$emit('close')">
    <div class="dispatch-sheet" @click.stop>
      <div class="dispatch-header">
        <div>
          <p class="dispatch-title">{{ panel.mode === 'reassign' ? '改派中心' : '派工中心' }}</p>
          <p class="dispatch-subtitle">{{ panel.requirement?.summary || '为当前工单选择最合适的维修人员' }}</p>
        </div>
        <button class="link-btn" @click="$emit('close')">关闭</button>
      </div>

      <div class="dispatch-requirement" v-if="panel.requirement">
        <span class="req-chip">{{ panel.requirement.building_id }}</span>
        <span class="req-chip">{{ priorityLabels[panel.requirement.priority] ?? panel.requirement.priority }}</span>
        <span class="req-chip">{{ panel.requirement.preferred_team_name }}</span>
      </div>

      <div class="candidate-list">
        <div class="candidate-card" v-for="candidate in panel.candidates" :key="candidate.user_id">
          <div class="candidate-head">
            <div>
              <p class="candidate-name">{{ candidate.username }}</p>
              <p class="candidate-meta">{{ candidate.team_name || '综合运维班' }} · {{ candidate.job_title || '维修工程师' }}</p>
            </div>
            <span class="score-pill">推荐分 {{ candidate.score }}</span>
          </div>
          <p class="candidate-note">{{ candidate.recommend_reason }}</p>
          <div class="candidate-tags">
            <span class="candidate-tag" v-for="badge in candidate.badges" :key="badge">{{ badge }}</span>
          </div>
          <button
            class="action-btn primary full"
            @click="$emit('confirm-candidate', candidate)"
            :disabled="dispatchSubmitting === candidate.user_id"
          >
            {{ dispatchSubmitting === candidate.user_id ? '提交中...' : (panel.mode === 'reassign' ? '改派给TA' : '派给TA') }}
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { PropType } from 'vue'

defineProps({
  visible: {
    type: Boolean,
    required: true,
  },
  panel: {
    type: Object as PropType<any>,
    required: true,
  },
  priorityLabels: {
    type: Object as PropType<Record<string, string>>,
    required: true,
  },
  dispatchSubmitting: {
    type: String as PropType<string | null>,
    default: null,
  },
})

defineEmits<{
  close: []
  'confirm-candidate': [candidate: any]
}>()
</script>

<style scoped>
.dispatch-mask { position: fixed; inset: 0; background: rgba(15, 23, 42, 0.4); display: flex; align-items: center; justify-content: center; z-index: 30; }
.dispatch-sheet { width: min(760px, calc(100vw - 40px)); max-height: 80vh; overflow: auto; background: var(--bg-panel); border: 1px solid var(--border); border-radius: 16px; padding: 20px; box-shadow: var(--card-shadow-hover); }
.dispatch-header { display: flex; justify-content: space-between; gap: 16px; align-items: flex-start; margin-bottom: 14px; }
.dispatch-title { font-size: 16px; font-weight: 700; margin-bottom: 4px; }
.dispatch-subtitle { font-size: 12px; color: var(--text-muted); }
.link-btn { background: none; border: 1px solid var(--border); border-radius: 8px; color: var(--text-secondary); font-size: 13px; padding: 8px 14px; cursor: pointer; transition: all 0.2s; }
.dispatch-requirement { display: flex; flex-wrap: wrap; gap: 8px; margin-bottom: 14px; }
.req-chip, .candidate-tag, .score-pill { border-radius: 999px; padding: 4px 10px; font-size: 11px; }
.req-chip { background: rgba(59, 130, 246, 0.1); color: var(--accent); }
.score-pill { background: rgba(16, 185, 129, 0.1); color: var(--success); }
.candidate-list { display: grid; gap: 12px; }
.candidate-card { border: 1px solid var(--border); border-radius: 12px; padding: 14px; background: var(--bg-card); }
.candidate-head { display: flex; justify-content: space-between; gap: 12px; align-items: flex-start; }
.candidate-name { font-size: 14px; font-weight: 700; margin-bottom: 4px; }
.candidate-meta { font-size: 12px; color: var(--text-muted); }
.candidate-note { font-size: 12px; color: var(--text-secondary); margin: 10px 0; }
.candidate-tags { display: flex; flex-wrap: wrap; gap: 6px; }
.candidate-tag { background: rgba(148, 163, 184, 0.12); color: var(--text-secondary); }
.action-btn { border: none; border-radius: 8px; font-size: 13px; font-weight: 600; padding: 8px 16px; cursor: pointer; }
.action-btn.primary { background: var(--accent); color: white; }
.action-btn.full { width: 100%; margin-top: 12px; }
.action-btn:disabled { opacity: 0.6; cursor: not-allowed; }
</style>
