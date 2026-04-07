<template>
  <div v-if="visible" class="dispatch-mask" @click="$emit('close')">
    <div class="dispatch-sheet batch-sheet" @click.stop>
      <div class="dispatch-header">
        <div>
          <p class="dispatch-title">批量派工建议</p>
          <p class="dispatch-subtitle">
            {{ panel.preview?.selected_count ? `已筛出 ${panel.preview.selected_count} 张高置信工单` : '按优先级、推荐分与人员容量生成分批派工建议' }}
          </p>
        </div>
        <button class="link-btn" @click="$emit('close')">关闭</button>
      </div>

      <div class="batch-config-box">
        <div class="batch-config-group">
          <span class="batch-config-label">本批次张数</span>
          <div class="batch-config-row">
            <button
              v-for="size in batchSampleOptions"
              :key="size"
              class="batch-chip"
              :class="{ active: batchOptions.sampleSize === size }"
              @click="$emit('select-sample-size', size)"
            >{{ size }} 张</button>
          </div>
        </div>

        <div class="batch-config-group">
          <span class="batch-config-label">优先级</span>
          <div class="batch-config-row">
            <button
              v-for="item in batchPriorityOptions"
              :key="item.value"
              class="batch-chip"
              :class="{ active: batchOptions.priority === item.value }"
              @click="$emit('select-priority', item.value)"
            >{{ item.label }}</button>
          </div>
        </div>

        <div class="batch-config-group">
          <span class="batch-config-label">单人批次上限</span>
          <div class="batch-config-row">
            <button
              v-for="cap in batchWorkerCapOptions"
              :key="cap"
              class="batch-chip"
              :class="{ active: batchOptions.maxPerWorker === cap }"
              @click="$emit('select-worker-cap', cap)"
            >{{ cap }} 张</button>
          </div>
        </div>

        <button class="refresh-btn inline" @click="$emit('refresh-preview')" :disabled="batchPreviewLoading">
          {{ batchPreviewLoading ? '刷新中...' : '刷新推荐' }}
        </button>
      </div>

      <div class="dispatch-requirement batch-summary-grid" v-if="panel.preview">
        <span class="req-chip">待派工 {{ panel.preview.pending_dispatch_total }}</span>
        <span class="req-chip">扫描 {{ panel.preview.scanned_count }}</span>
        <span class="req-chip">已选 {{ panel.preview.selected_count }}</span>
        <span class="req-chip">单人上限 {{ panel.preview.selection_rules.max_per_worker ?? '--' }}</span>
      </div>

      <div v-if="panel.preview?.planned_assignments?.length" class="batch-planned-strip">
        <span
          v-for="item in panel.preview.planned_assignments"
          :key="item.user_id"
          class="candidate-tag planned-tag"
        >
          {{ item.username }} +{{ item.count }}
        </span>
      </div>

      <div v-if="batchWorkerLoads.length" class="batch-load-box">
        <p class="section-title">当前负载与本批次分配</p>
        <div v-for="item in batchWorkerLoads" :key="item.user_id" class="batch-load-row">
          <div>
            <p class="candidate-name">{{ item.username }}</p>
            <p class="candidate-meta">{{ item.team_name || '综合运维班' }} · {{ shiftLabel(item.shift_status) }}</p>
          </div>
          <div class="batch-load-stats">
            <span>当前 {{ item.current_active_orders }}/{{ item.max_active_orders }}</span>
            <span v-if="item.planned_count > 0" class="accent-text">本批 +{{ item.planned_count }}</span>
            <span>余量 {{ item.capacity_left_after_batch }}</span>
          </div>
        </div>
      </div>

      <div v-if="panel.result" class="batch-result-box">
        <div class="batch-result-head">
          <div>
            <p class="section-title">本轮批量派工结果</p>
            <p class="dispatch-subtitle">
              请求 {{ panel.result.requested_count }} 张，成功 {{ panel.result.dispatched_count }} 张，失败 {{ panel.result.failed_count }} 张
            </p>
          </div>
          <button
            v-if="retryableBatchFailures.length"
            class="refresh-btn inline warn"
            @click="$emit('retry-failed')"
            :disabled="batchDispatchApplying"
          >
            重试 {{ retryableBatchFailures.length }} 张
          </button>
        </div>

        <div
          v-for="item in panel.result.failed"
          :key="`${item.ticket_id}:${item.reason_code}`"
          class="batch-result-row"
        >
          <div class="batch-result-row-top">
            <div>
              <p class="candidate-name">{{ item.ticket_id }}</p>
              <p class="candidate-meta">
                {{ item.current_status ? `当前状态 ${statusLabels[item.current_status] ?? item.current_status}` : '状态未知' }}
                <template v-if="item.assigned_to_name"> · 原推荐 {{ item.assigned_to_name }}</template>
              </p>
            </div>
            <span class="batch-result-reason">{{ item.reason }}</span>
          </div>
          <div class="batch-result-actions">
            <button
              v-if="item.retryable"
              class="action-btn secondary"
              @click="$emit('retry-failed', item.ticket_id)"
              :disabled="batchDispatchApplying"
            >重试</button>
            <button
              v-if="item.manual_review_recommended"
              class="action-btn primary"
              @click="$emit('review-failed', item.ticket_id)"
            >人工复核</button>
          </div>
        </div>
      </div>

      <div class="candidate-list batch-list">
        <div v-if="batchPreviewLoading" class="timeline-hint">正在生成推荐...</div>

        <template v-else>
          <div
            v-for="item in panel.preview?.recommendations || []"
            :key="item.ticket_id"
            class="candidate-card"
          >
            <div class="candidate-head">
              <div>
                <p class="candidate-name">{{ item.ticket_id }}</p>
                <p class="candidate-meta">{{ buildingName(item.building_id) }} · {{ priorityLabels[item.priority] ?? item.priority }}</p>
              </div>
              <span class="score-pill">差值 {{ item.score_gap ?? '--' }}</span>
            </div>
            <p class="candidate-note">
              推荐 {{ item.chosen_candidate?.username || '暂无' }}
              <template v-if="item.chosen_candidate?.team_name"> · {{ item.chosen_candidate.team_name }}</template>
            </p>
            <p class="candidate-note">{{ item.selection_reason }}</p>
          </div>

          <div v-if="!panel.preview?.recommendations?.length && panel.preview" class="timeline-hint">
            当前规则下没有可直接批量派工的工单
          </div>

          <div v-if="panel.preview?.skipped_summary?.length" class="batch-skipped-box">
            <p class="section-title">未纳入批量派工的原因</p>
            <div v-for="item in panel.preview.skipped_summary" :key="item.reason" class="batch-skip-row">
              <span>{{ item.label }}</span>
              <strong>{{ item.count }}</strong>
            </div>
          </div>

          <div v-if="panel.preview?.skipped_examples?.length" class="batch-skipped-box">
            <p class="section-title">暂未纳入示例</p>
            <div v-for="item in panel.preview.skipped_examples" :key="`${item.ticket_id}:${item.reason}`" class="batch-example-row">
              <div class="batch-result-row-top">
                <div>
                  <p class="candidate-name">{{ item.ticket_id }}</p>
                  <p class="candidate-meta">{{ buildingName(item.building_id) }} · {{ priorityLabels[item.priority] ?? item.priority }}</p>
                </div>
                <span class="batch-result-reason">{{ item.label }}</span>
              </div>
              <p class="candidate-note">
                {{ item.top_candidate ? `第一候选 ${item.top_candidate.username} · ${item.top_candidate.score} 分 · 负载 ${item.top_candidate.current_active_orders}/${item.top_candidate.max_active_orders}` : '暂无可用候选人' }}
              </p>
            </div>
          </div>
        </template>
      </div>

      <button
        class="action-btn primary full batch-submit"
        @click="$emit('confirm-dispatch')"
        :disabled="batchDispatchApplying || !panel.preview?.recommendations?.length"
      >
        {{ batchDispatchApplying ? '提交中...' : `一键派工 ${panel.preview?.recommendations?.length || 0} 张` }}
      </button>
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
  batchPreviewLoading: {
    type: Boolean,
    required: true,
  },
  batchDispatchApplying: {
    type: Boolean,
    required: true,
  },
  batchSampleOptions: {
    type: Array as PropType<number[]>,
    required: true,
  },
  batchWorkerCapOptions: {
    type: Array as PropType<number[]>,
    required: true,
  },
  batchPriorityOptions: {
    type: Array as PropType<Array<{ label: string; value: string }>>,
    required: true,
  },
  batchOptions: {
    type: Object as PropType<{ sampleSize: number; priority: string; maxPerWorker: number }>,
    required: true,
  },
  batchWorkerLoads: {
    type: Array as PropType<any[]>,
    required: true,
  },
  retryableBatchFailures: {
    type: Array as PropType<any[]>,
    required: true,
  },
  priorityLabels: {
    type: Object as PropType<Record<string, string>>,
    required: true,
  },
  statusLabels: {
    type: Object as PropType<Record<string, string>>,
    required: true,
  },
  buildingName: {
    type: Function as PropType<(id: string) => string>,
    required: true,
  },
  shiftLabel: {
    type: Function as PropType<(status?: string | null) => string>,
    required: true,
  },
})

defineEmits<{
  close: []
  'refresh-preview': []
  'select-sample-size': [size: number]
  'select-priority': [priority: string]
  'select-worker-cap': [cap: number]
  'retry-failed': [ticketId?: string]
  'review-failed': [ticketId: string]
  'confirm-dispatch': []
}>()
</script>

<style scoped>
.dispatch-mask { position: fixed; inset: 0; background: rgba(15, 23, 42, 0.4); display: flex; align-items: center; justify-content: center; z-index: 30; }
.dispatch-sheet { width: min(760px, calc(100vw - 40px)); max-height: 80vh; overflow: auto; background: var(--bg-panel); border: 1px solid var(--border); border-radius: 16px; padding: 20px; box-shadow: var(--card-shadow-hover); }
.dispatch-sheet.batch-sheet { width: min(920px, calc(100vw - 40px)); }
.dispatch-header { display: flex; justify-content: space-between; gap: 16px; align-items: flex-start; margin-bottom: 14px; }
.dispatch-title { font-size: 16px; font-weight: 700; margin-bottom: 4px; }
.dispatch-subtitle { font-size: 12px; color: var(--text-muted); }
.link-btn, .refresh-btn { background: none; border: 1px solid var(--border); border-radius: 8px; color: var(--text-secondary); font-size: 13px; padding: 8px 14px; cursor: pointer; transition: all 0.2s; }
.refresh-btn.inline { padding: 7px 12px; }
.refresh-btn.warn { border-color: rgba(245, 158, 11, 0.24); color: #b45309; background: rgba(245, 158, 11, 0.08); }
.dispatch-requirement { display: flex; flex-wrap: wrap; gap: 8px; margin-bottom: 14px; }
.req-chip, .candidate-tag, .score-pill { border-radius: 999px; padding: 4px 10px; font-size: 11px; }
.req-chip { background: rgba(59, 130, 246, 0.1); color: var(--accent); }
.score-pill { background: rgba(16, 185, 129, 0.1); color: var(--success); }
.candidate-list { display: grid; gap: 12px; }
.candidate-list.batch-list { margin-top: 16px; }
.candidate-card { border: 1px solid var(--border); border-radius: 12px; padding: 14px; background: var(--bg-card); }
.candidate-head { display: flex; justify-content: space-between; gap: 12px; align-items: flex-start; }
.candidate-name { font-size: 14px; font-weight: 700; margin-bottom: 4px; }
.candidate-meta { font-size: 12px; color: var(--text-muted); }
.candidate-note { font-size: 12px; color: var(--text-secondary); margin: 10px 0; }
.candidate-tag { background: rgba(148, 163, 184, 0.12); color: var(--text-secondary); }
.planned-tag { background: rgba(16, 185, 129, 0.1); color: var(--success); }
.batch-config-box { display: grid; gap: 12px; padding: 14px; border: 1px solid var(--border); border-radius: 12px; background: var(--bg-card); margin-bottom: 14px; }
.batch-config-group { display: grid; gap: 8px; }
.batch-config-label { font-size: 12px; color: var(--text-muted); }
.batch-config-row { display: flex; flex-wrap: wrap; gap: 8px; }
.batch-chip { border: 1px solid var(--border); background: transparent; color: var(--text-secondary); border-radius: 999px; padding: 6px 12px; font-size: 12px; cursor: pointer; }
.batch-chip.active { background: var(--accent-glow); border-color: var(--border-accent); color: var(--accent); }
.batch-summary-grid { margin-bottom: 10px; }
.batch-planned-strip { display: flex; flex-wrap: wrap; gap: 8px; margin-bottom: 14px; }
.batch-load-box, .batch-result-box, .batch-skipped-box { border: 1px solid var(--border); border-radius: 12px; background: var(--bg-card); padding: 14px; margin-bottom: 14px; }
.batch-load-row { display: flex; justify-content: space-between; gap: 16px; align-items: center; padding: 10px 0; border-bottom: 1px solid var(--border); }
.batch-load-row:last-child { border-bottom: none; padding-bottom: 0; }
.batch-load-stats { display: flex; flex-direction: column; gap: 6px; font-size: 12px; color: var(--text-secondary); text-align: right; }
.accent-text { color: var(--accent); font-weight: 600; }
.batch-result-head { display: flex; justify-content: space-between; align-items: flex-start; gap: 12px; margin-bottom: 8px; }
.batch-result-row { padding: 12px 0; border-top: 1px solid var(--border); }
.batch-result-row:first-of-type { border-top: none; }
.batch-result-row-top { display: flex; justify-content: space-between; gap: 12px; align-items: flex-start; }
.batch-result-reason { color: #b45309; font-size: 12px; font-weight: 600; text-align: right; }
.batch-result-actions { display: flex; gap: 8px; margin-top: 10px; }
.batch-skip-row { display: flex; justify-content: space-between; gap: 12px; font-size: 12px; color: var(--text-secondary); padding: 8px 0; }
.batch-example-row { padding-top: 10px; margin-top: 10px; border-top: 1px solid var(--border); }
.batch-example-row:first-of-type { border-top: none; padding-top: 0; margin-top: 0; }
.batch-submit { margin-top: 6px; }
.section-title { font-size: 13px; font-weight: 700; margin-bottom: 10px; }
.timeline-hint { font-size: 12px; color: var(--text-muted); margin-bottom: 10px; }
.action-btn { border: none; border-radius: 8px; font-size: 13px; font-weight: 600; padding: 8px 16px; cursor: pointer; }
.action-btn.primary { background: var(--accent); color: white; }
.action-btn.secondary { background: rgba(59, 130, 246, 0.12); color: var(--accent); }
.action-btn.full { width: 100%; margin-top: 12px; }
.action-btn:disabled, .refresh-btn:disabled { opacity: 0.6; cursor: not-allowed; }
</style>
