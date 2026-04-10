<template>
  <section class="auto-dispatch-insights">
    <div class="insights-head">
      <div>
        <p class="eyebrow">自动派工运营</p>
        <h2>派工闭环观察</h2>
        <p class="head-note">审批通过后的自动派人、低置信兜底和大厅兜底。</p>
      </div>
      <button class="refresh-btn" type="button" :disabled="loading" @click="refreshValue">
        {{ loading ? '刷新中...' : '刷新洞察' }}
      </button>
    </div>

    <div class="filter-grid">
      <label class="filter-field">
        <span>开始日期</span>
        <input type="date" :value="filters.date_from || ''" @change="onFilterInput('date_from', $event)" />
      </label>
      <label class="filter-field">
        <span>结束日期</span>
        <input type="date" :value="filters.date_to || ''" @change="onFilterInput('date_to', $event)" />
      </label>
      <label class="filter-field">
        <span>楼宇</span>
        <select :value="filters.building_id || ''" @change="onFilterInput('building_id', $event)">
          <option value="">全部楼宇</option>
          <option v-for="item in buildingOptions" :key="item.value" :value="item.value">{{ item.label }}</option>
        </select>
      </label>
      <label class="filter-field">
        <span>优先级</span>
        <select :value="filters.priority || ''" @change="onFilterInput('priority', $event)">
          <option value="">全部优先级</option>
          <option v-for="(label, value) in priorityLabels" :key="value" :value="value">{{ label }}</option>
        </select>
      </label>
      <label class="filter-field">
        <span>技能</span>
        <select :value="filters.required_skill || ''" @change="onFilterInput('required_skill', $event)">
          <option value="">全部技能</option>
          <option v-for="item in skillOptions" :key="item.value" :value="item.value">{{ item.label }}</option>
        </select>
      </label>
      <label class="filter-field">
        <span>派工模式</span>
        <select :value="filters.dispatch_mode || ''" @change="onFilterInput('dispatch_mode', $event)">
          <option value="">全部模式</option>
          <option v-for="item in modeOptions" :key="item.value" :value="item.value">{{ item.label }}</option>
        </select>
      </label>
    </div>

    <div v-if="loading" class="state-line">正在读取自动派工和大厅兜底记录...</div>
    <div v-else-if="error" class="state-line error">{{ error }}</div>

    <template v-else>
      <div class="explain-box">
        <div class="explain-head">
          <div>
            <p class="eyebrow">运营解读</p>
            <h3>自动派工稳不稳</h3>
          </div>
          <span v-if="explanation" class="source-pill">{{ explanationSourceLabel }}</span>
        </div>
        <div class="explain-input-row">
          <input
            :value="explainQuestion"
            type="text"
            maxlength="500"
            placeholder="例如：今天大厅兜底为什么变多？"
            @input="onQuestionInput"
          />
          <button type="button" class="refresh-btn secondary" :disabled="explainLoading" @click="explainValue">
            {{ explainLoading ? '解读中...' : '生成解读' }}
          </button>
        </div>
        <p v-if="explainError" class="explain-error">{{ explainError }}</p>
        <div v-if="explanation" class="explanation-content">
          <p class="explanation-summary">{{ explanation.summary }}</p>
          <div class="explanation-columns">
            <div class="explanation-column">
              <span>关键发现</span>
              <ul>
                <li v-for="item in explanation.findings || []" :key="item">{{ item }}</li>
              </ul>
            </div>
            <div class="explanation-column">
              <span>风险提示</span>
              <ul>
                <li v-for="item in explanation.risks || []" :key="item">{{ item }}</li>
              </ul>
            </div>
            <div class="explanation-column">
              <span>建议动作</span>
              <ul>
                <li v-for="item in explanation.recommendations || []" :key="item">{{ item }}</li>
              </ul>
            </div>
          </div>
          <div v-if="(explanation.evidence || []).length" class="evidence-list">
            <div v-for="item in explanation.evidence" :key="`${item.label}-${item.value}`" class="evidence-item">
              <strong>{{ item.label }}</strong>
              <span>{{ item.value }}</span>
            </div>
          </div>
        </div>
      </div>

      <div class="metric-grid">
        <div v-for="item in summaryCards" :key="item.label" class="metric-tile">
          <span>{{ item.label }}</span>
          <strong>{{ item.value }}</strong>
          <small>{{ item.hint }}</small>
        </div>
      </div>

      <div class="breakdown-grid">
        <div v-for="group in breakdownGroups" :key="group.title" class="breakdown-block">
          <div class="breakdown-title">{{ group.title }}</div>
          <div v-if="group.rows.length" class="breakdown-list">
            <div v-for="row in group.rows" :key="`${group.title}-${row.key}`" class="breakdown-row">
              <span>{{ displayBreakdownLabel(group.key, row.label) }}</span>
              <strong>{{ row.count }}</strong>
            </div>
          </div>
          <p v-else class="empty-hint">暂无记录</p>
        </div>
      </div>

      <div class="records-head">
        <h3>最近记录</h3>
        <span>{{ pagination.total || 0 }} 条</span>
      </div>
      <div v-if="records.length" class="record-list">
        <article v-for="record in records" :key="recordKey(record)" class="record-row">
          <div class="record-main">
            <div class="record-title-line">
              <span class="mode-chip" :class="modeClass(record.mode)">{{ modeLabel(record.mode) }}</span>
              <strong>{{ record.ticket_id || '未命名工单' }}</strong>
              <span>{{ buildingNameValue(record.building_id || '') }}</span>
            </div>
            <p>{{ record.reason || '暂无原因说明' }}</p>
            <div class="record-tags">
              <span>{{ priorityLabel(record.priority) }}</span>
              <span>{{ (record.required_skills || []).join(' / ') || '未识别技能' }}</span>
              <span>{{ record.assignee_name || record.team_name || '大厅待接管' }}</span>
            </div>
          </div>
          <div class="record-side">
            <span>{{ formatTimeValue(record.created_at) }}</span>
            <strong v-if="record.score">分数 {{ record.score }}</strong>
            <strong v-else-if="record.application_stats">申请 {{ record.application_stats.total || 0 }}</strong>
          </div>
        </article>
      </div>
      <p v-else class="empty-hint wide">当前筛选下暂无自动派工或大厅兜底记录。</p>
    </template>
  </section>
</template>

<script setup lang="ts">
import { computed, PropType } from 'vue'

const props = defineProps({
  insights: {
    type: Object as PropType<any | null>,
    default: null,
  },
  filters: {
    type: Object as PropType<Record<string, string>>,
    required: true,
  },
  loading: {
    type: Boolean,
    required: true,
  },
  error: {
    type: String,
    required: true,
  },
  priorityLabels: {
    type: Object as PropType<Record<string, string>>,
    required: true,
  },
  buildingOptions: {
    type: Array as PropType<Array<{ label: string; value: string }>>,
    required: true,
  },
  skillOptions: {
    type: Array as PropType<Array<{ label: string; value: string }>>,
    required: true,
  },
  buildingName: {
    type: Function as PropType<(id: string) => string>,
    required: true,
  },
  formatTime: {
    type: Function as PropType<(value?: string | null) => string>,
    required: true,
  },
  updateFilter: {
    type: Function as PropType<(key: string, value: string) => void>,
    required: true,
  },
  refresh: {
    type: Function as PropType<() => void>,
    required: true,
  },
  explanation: {
    type: Object as PropType<any | null>,
    default: null,
  },
  explanationSource: {
    type: String,
    default: '',
  },
  explainQuestion: {
    type: String,
    required: true,
  },
  explainLoading: {
    type: Boolean,
    required: true,
  },
  explainError: {
    type: String,
    required: true,
  },
  updateExplainQuestion: {
    type: Function as PropType<(value: string) => void>,
    required: true,
  },
  explain: {
    type: Function as PropType<() => void>,
    required: true,
  },
})

const modeOptions = [
  { label: '高置信自动', value: 'auto' },
  { label: '低置信兜底', value: 'auto_fallback' },
  { label: '大厅兜底', value: 'hall_fallback' },
  { label: '灰度外进大厅', value: 'rollout_hall_fallback' },
]

const modeLabels: Record<string, string> = {
  auto: '高置信自动',
  auto_fallback: '低置信兜底',
  hall_fallback: '大厅兜底',
  rollout_hall_fallback: '灰度外进大厅',
}

const summary = computed(() => props.insights?.summary || {})
const breakdowns = computed(() => props.insights?.breakdowns || {})
const records = computed(() => props.insights?.records || [])
const pagination = computed(() => props.insights?.pagination || {})
const explanationSourceLabel = computed(() => (
  props.explanationSource === 'llm' ? 'LLM 解读' : '规则兜底'
))

const summaryCards = computed(() => [
  { label: '闭环事件', value: summary.value.total_events ?? 0, hint: '自动派工与大厅兜底' },
  { label: '直接派工', value: summary.value.direct_dispatch_total ?? 0, hint: `高置信 ${summary.value.high_confidence_auto ?? 0} · 低置信 ${summary.value.low_confidence_auto_fallback ?? 0}` },
  { label: '大厅兜底', value: summary.value.hall_fallback_total ?? 0, hint: `打开 ${summary.value.open_hall_fallback ?? 0} · 灰度外 ${summary.value.rollout_hall_fallback ?? 0}` },
  { label: '需改派率', value: `${Math.round((summary.value.needs_reassign_rate ?? 0) * 100)}%`, hint: `已复核 ${summary.value.reviewed ?? 0} · 需改派 ${summary.value.needs_reassign ?? 0}` },
])

const breakdownGroups = computed(() => [
  { key: 'mode', title: '模式分布', rows: breakdowns.value.by_mode || [] },
  { key: 'skill', title: '技能分布', rows: breakdowns.value.by_skill || [] },
  { key: 'building', title: '楼宇分布', rows: breakdowns.value.by_building || [] },
  { key: 'assignee', title: '人员分布', rows: breakdowns.value.by_assignee || [] },
])

function onFilterInput(key: string, event: Event) {
  const target = event.target as HTMLInputElement | HTMLSelectElement
  props.updateFilter(key, target.value)
}

function refreshValue() {
  props.refresh()
}

function explainValue() {
  props.explain()
}

function onQuestionInput(event: Event) {
  props.updateExplainQuestion((event.target as HTMLInputElement).value)
}

function modeLabel(mode?: string) {
  return modeLabels[mode || ''] || mode || '其他'
}

function modeClass(mode?: string) {
  return {
    auto: mode === 'auto',
    fallback: mode === 'auto_fallback',
    hall: mode === 'hall_fallback' || mode === 'rollout_hall_fallback',
  }
}

function displayBreakdownLabel(groupKey: string, value?: string) {
  if (groupKey === 'mode') return modeLabel(value)
  if (groupKey === 'building') return buildingNameValue(value || '')
  if (groupKey === 'priority') return priorityLabel(value)
  return value || '未标记'
}

function priorityLabel(priority?: string) {
  return props.priorityLabels[priority || ''] || priority || '普通'
}

function buildingNameValue(id: string) {
  return props.buildingName(id)
}

function formatTimeValue(value?: string | null) {
  return props.formatTime(value)
}

function recordKey(record: any) {
  return record.dispatch_id || record.hall_entry_id || record.ticket_id
}
</script>

<style scoped>
.auto-dispatch-insights { display: flex; flex-direction: column; gap: 16px; }
.insights-head {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 16px;
  padding: 16px;
  border: 1px solid var(--border);
  border-radius: 8px;
  background: var(--bg-panel);
}
.eyebrow { margin-bottom: 4px; color: var(--accent); font-size: 12px; font-weight: 700; }
.insights-head h2 { margin: 0 0 6px; font-size: 18px; }
.head-note { color: var(--text-secondary); font-size: 13px; }
.refresh-btn {
  border: 1px solid var(--border-accent);
  border-radius: 8px;
  background: var(--accent);
  color: white;
  cursor: pointer;
  font-size: 13px;
  font-weight: 700;
  padding: 8px 14px;
  white-space: nowrap;
}
.refresh-btn:disabled { cursor: not-allowed; opacity: 0.64; }
.refresh-btn.secondary {
  border-color: var(--border);
  background: var(--bg-panel);
  color: var(--accent);
}
.filter-grid { display: grid; grid-template-columns: repeat(6, minmax(0, 1fr)); gap: 10px; }
.filter-field {
  display: flex;
  flex-direction: column;
  gap: 6px;
  color: var(--text-muted);
  font-size: 12px;
}
.filter-field input,
.filter-field select {
  width: 100%;
  min-height: 38px;
  border: 1px solid var(--border);
  border-radius: 8px;
  background: var(--bg-panel);
  color: var(--text-primary);
  font-size: 13px;
  padding: 8px 10px;
}
.state-line {
  border: 1px solid var(--border-accent);
  border-radius: 8px;
  background: var(--accent-glow);
  color: var(--accent);
  font-size: 13px;
  padding: 12px 14px;
}
.state-line.error {
  border-color: rgba(248, 113, 113, 0.24);
  background: rgba(248, 113, 113, 0.08);
  color: var(--danger);
}
.explain-box {
  display: flex;
  flex-direction: column;
  gap: 12px;
  border: 1px solid var(--border);
  border-radius: 8px;
  background: var(--bg-panel);
  padding: 16px;
}
.explain-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; }
.explain-head h3 { margin: 0; font-size: 16px; }
.source-pill {
  border-radius: 999px;
  background: rgba(16, 185, 129, 0.12);
  color: var(--success);
  font-size: 11px;
  font-weight: 700;
  padding: 4px 9px;
}
.explain-input-row { display: grid; grid-template-columns: 1fr auto; gap: 10px; }
.explain-input-row input {
  min-height: 38px;
  border: 1px solid var(--border);
  border-radius: 8px;
  background: var(--bg-card);
  color: var(--text-primary);
  font-size: 13px;
  padding: 8px 10px;
}
.explain-error { color: var(--danger); font-size: 12px; }
.explanation-content { display: flex; flex-direction: column; gap: 12px; }
.explanation-summary { color: var(--text-primary); font-size: 14px; line-height: 1.7; }
.explanation-columns { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 12px; }
.explanation-column {
  border: 1px solid var(--border);
  border-radius: 8px;
  background: var(--bg-card);
  padding: 12px;
}
.explanation-column span { display: inline-block; margin-bottom: 8px; color: var(--text-primary); font-size: 13px; font-weight: 700; }
.explanation-column ul { margin: 0; padding-left: 18px; color: var(--text-secondary); font-size: 12px; line-height: 1.7; }
.evidence-list { display: flex; flex-direction: column; gap: 8px; }
.evidence-item {
  display: grid;
  grid-template-columns: 120px 1fr;
  gap: 10px;
  color: var(--text-secondary);
  font-size: 12px;
}
.evidence-item strong { color: var(--text-primary); }
.metric-grid { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 12px; }
.metric-tile {
  display: flex;
  flex-direction: column;
  gap: 6px;
  min-height: 104px;
  border: 1px solid var(--border);
  border-radius: 8px;
  background: var(--bg-panel);
  padding: 14px;
}
.metric-tile span,
.metric-tile small { color: var(--text-muted); font-size: 12px; }
.metric-tile strong { color: var(--text-primary); font-size: 24px; }
.breakdown-grid { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 12px; }
.breakdown-block {
  border: 1px solid var(--border);
  border-radius: 8px;
  background: var(--bg-panel);
  padding: 14px;
}
.breakdown-title { margin-bottom: 10px; color: var(--text-primary); font-size: 13px; font-weight: 700; }
.breakdown-list { display: flex; flex-direction: column; gap: 8px; }
.breakdown-row { display: flex; justify-content: space-between; gap: 12px; color: var(--text-secondary); font-size: 12px; }
.breakdown-row span { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.breakdown-row strong { color: var(--text-primary); }
.records-head { display: flex; justify-content: space-between; align-items: center; color: var(--text-secondary); }
.records-head h3 { margin: 0; color: var(--text-primary); font-size: 15px; }
.record-list { display: flex; flex-direction: column; gap: 10px; }
.record-row {
  display: flex;
  justify-content: space-between;
  gap: 18px;
  border: 1px solid var(--border);
  border-radius: 8px;
  background: var(--bg-panel);
  padding: 14px;
}
.record-main { min-width: 0; }
.record-title-line { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; margin-bottom: 8px; }
.record-title-line strong { color: var(--text-primary); }
.record-title-line span:last-child { color: var(--text-muted); font-size: 12px; }
.record-main p { color: var(--text-secondary); font-size: 13px; line-height: 1.6; margin-bottom: 10px; }
.record-tags { display: flex; flex-wrap: wrap; gap: 6px; }
.record-tags span,
.mode-chip {
  border-radius: 999px;
  background: rgba(148, 163, 184, 0.12);
  color: var(--text-secondary);
  font-size: 11px;
  padding: 4px 9px;
}
.mode-chip.auto { background: rgba(16, 185, 129, 0.12); color: var(--success); }
.mode-chip.fallback { background: rgba(59, 130, 246, 0.12); color: var(--accent); }
.mode-chip.hall { background: rgba(245, 158, 11, 0.14); color: #b45309; }
.record-side {
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  gap: 8px;
  flex-shrink: 0;
  color: var(--text-muted);
  font-size: 12px;
}
.record-side strong { color: var(--text-primary); }
.empty-hint { color: var(--text-muted); font-size: 12px; }
.empty-hint.wide {
  border: 1px dashed var(--border);
  border-radius: 8px;
  padding: 20px;
  text-align: center;
}
@media (max-width: 1200px) {
  .filter-grid,
  .breakdown-grid,
  .explanation-columns { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .metric-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
}
@media (max-width: 720px) {
  .insights-head,
  .record-row { flex-direction: column; }
  .filter-grid,
  .breakdown-grid,
  .metric-grid,
  .explanation-columns,
  .explain-input-row,
  .evidence-item { grid-template-columns: 1fr; }
  .record-side { align-items: flex-start; }
}
</style>
