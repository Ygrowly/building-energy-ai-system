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

      <div class="shadow-box">
        <div class="shadow-head">
          <div>
            <p class="eyebrow">自动重派一期</p>
            <h3>影子观察</h3>
            <p class="head-note">只评估，不直接改派；先看触发质量、阻断原因和大厅兜底压力。</p>
          </div>
          <button class="refresh-btn secondary" type="button" :disabled="shadowLoading" @click="refreshShadowValue">
            {{ shadowLoading ? '刷新中...' : '刷新影子观察' }}
          </button>
        </div>

        <div class="shadow-filter-grid">
          <label class="filter-field">
            <span>触发原因</span>
            <select :value="shadowFilters.trigger_reason || ''" @change="onShadowFilterInput('trigger_reason', $event)">
              <option v-for="item in shadowTriggerOptions" :key="item.value || 'all'" :value="item.value">{{ item.label }}</option>
            </select>
          </label>
          <label class="filter-field">
            <span>评估结果</span>
            <select :value="shadowFilters.eligible || ''" @change="onShadowFilterInput('eligible', $event)">
              <option v-for="item in shadowEligibleOptions" :key="item.value || 'all'" :value="item.value">{{ item.label }}</option>
            </select>
          </label>
          <label class="filter-field">
            <span>当前阶段</span>
            <select :value="shadowFilters.current_dispatch_status || ''" @change="onShadowFilterInput('current_dispatch_status', $event)">
              <option v-for="item in shadowStatusOptions" :key="item.value || 'all'" :value="item.value">{{ item.label }}</option>
            </select>
          </label>
        </div>

        <div class="shadow-setting-line">
          <span>影子模式 {{ shadowSettings.shadow_enabled ? '开启' : '关闭' }}</span>
          <span>执行器 {{ shadowSettings.execution_enabled ? '开启' : '关闭' }}</span>
          <span>阈值 {{ shadowSettings.rules?.min_score ?? 0 }} / 分差 {{ shadowSettings.rules?.min_gap ?? 0 }}</span>
          <span>楼宇 {{ (shadowSettings.rollout?.allowed_buildings || []).join(' / ') || '不限' }}</span>
          <span>优先级 {{ (shadowSettings.rollout?.allowed_priorities || []).join(' / ') || '不限' }}</span>
          <span>技能 {{ (shadowSettings.rollout?.allowed_required_skills || []).join(' / ') || '不限' }}</span>
        </div>

        <div v-if="shadowLoading" class="state-line">正在读取自动重派影子评估...</div>
        <div v-else-if="shadowError" class="state-line error">{{ shadowError }}</div>
        <template v-else>
          <div class="metric-grid">
            <div v-for="item in shadowSummaryCards" :key="item.label" class="metric-tile">
              <span>{{ item.label }}</span>
              <strong>{{ item.value }}</strong>
              <small>{{ item.hint }}</small>
            </div>
          </div>

          <div class="breakdown-grid">
            <div v-for="group in shadowBreakdownGroups" :key="group.title" class="breakdown-block">
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
            <h3>最近影子评估</h3>
            <span>{{ shadowPagination.total || 0 }} 条</span>
          </div>
          <div v-if="shadowRecords.length" class="record-list">
            <article v-for="record in shadowRecords" :key="shadowRecordKey(record)" class="record-row">
              <div class="record-main">
                <div class="record-title-line">
                  <span class="mode-chip shadow">{{ shadowTriggerLabel(record.trigger_reason) }}</span>
                  <strong>{{ record.ticket_id || '未命名工单' }}</strong>
                  <span>{{ buildingNameValue(record.building_id || '') }}</span>
                </div>
                <p>
                  {{ record.selection_reason || (record.blocker_reasons || []).join(' / ') || '当前评估未给出额外说明' }}
                </p>
                <div class="record-tags">
                  <span>{{ priorityLabel(record.priority) }}</span>
                  <span>{{ shadowStatusLabel(record.current_dispatch_status) }}</span>
                  <span>{{ (record.required_skills || []).join(' / ') || '未识别技能' }}</span>
                  <span>{{ record.assignee_name || record.team_name || '未识别责任人' }}</span>
                  <span>{{ record.within_live_rollout ? '灰度内' : '灰度外' }}</span>
                  <span>{{ record.would_execute ? '会自动改派' : '不会直接改派' }}</span>
                  <span v-if="record.would_hall_fallback">会开大厅</span>
                </div>
              </div>
              <div class="record-side">
                <span>{{ formatTimeValue(record.created_at) }}</span>
                <strong v-if="record.top_candidate?.username">候选 {{ record.top_candidate.username }}</strong>
                <strong v-else-if="record.blocker_reasons?.length">阻断 {{ record.blocker_reasons[0] }}</strong>
              </div>
            </article>
          </div>
          <p v-else class="empty-hint wide">当前筛选下暂无自动重派影子评估记录。</p>
        </template>
      </div>

      <div class="shadow-box run-health-box">
        <div class="shadow-head">
          <div>
            <p class="eyebrow">自动调度运行健康</p>
            <h3>扫描稳定性</h3>
            <p class="head-note">同一时间看业务闭环和扫描健康，方便判断“是量上来了”还是“系统抖了”。</p>
          </div>
          <button class="refresh-btn secondary" type="button" :disabled="runHealthLoading" @click="refreshRunHealthValue">
            {{ runHealthLoading ? '刷新中...' : '刷新运行健康' }}
          </button>
        </div>

        <div class="shadow-filter-grid run-health-filter-grid">
          <label class="filter-field">
            <span>运行来源</span>
            <select :value="runHealthFilters.trigger_source || ''" @change="onRunHealthFilterInput('trigger_source', $event)">
              <option v-for="item in runHealthSourceOptions" :key="item.value || 'all'" :value="item.value">{{ item.label }}</option>
            </select>
          </label>
          <label class="filter-field">
            <span>慢扫描阈值</span>
            <select :value="runHealthFilters.slow_threshold_ms || ''" @change="onRunHealthFilterInput('slow_threshold_ms', $event)">
              <option v-for="item in runHealthSlowThresholdOptions" :key="item.value" :value="item.value">{{ item.label }}</option>
            </select>
          </label>
          <div class="run-health-note">
            <span>日期范围沿用上方筛选</span>
            <span>最近 {{ runHealthSummary.total_runs ?? 0 }} 次运行</span>
            <span>异常阈值 {{ formatDuration(runHealthSummary.slow_threshold_ms ?? 0) }}</span>
          </div>
        </div>

        <div v-if="runHealthLoading" class="state-line">正在读取自动调度运行健康...</div>
        <div v-else-if="runHealthError" class="state-line error">{{ runHealthError }}</div>
        <template v-else>
          <div class="metric-grid">
            <div v-for="item in runHealthSummaryCards" :key="item.label" class="metric-tile">
              <span>{{ item.label }}</span>
              <strong>{{ item.value }}</strong>
              <small>{{ item.hint }}</small>
            </div>
          </div>

          <div class="breakdown-grid run-health-breakdown-grid">
            <div v-for="group in runHealthBreakdownGroups" :key="group.title" class="breakdown-block">
              <div class="breakdown-title">{{ group.title }}</div>
              <div v-if="group.rows.length" class="breakdown-list">
                <div v-for="row in group.rows" :key="`${group.title}-${row.key}`" class="breakdown-row">
                  <span>{{ displayRunHealthBreakdownLabel(group.key, row.label) }}</span>
                  <strong>{{ row.count }}</strong>
                </div>
              </div>
              <p v-else class="empty-hint">暂无记录</p>
            </div>

            <div class="breakdown-block">
              <div class="breakdown-title">分段耗时占比</div>
              <div v-if="runHealthTimingShares.length" class="breakdown-list">
                <div v-for="row in runHealthTimingShares" :key="row.key" class="timing-share-row">
                  <div class="timing-share-copy">
                    <span>{{ runHealthTimingLabel(row.key) }}</span>
                    <small>均值 {{ formatDuration(row.avg_ms) }}</small>
                  </div>
                  <strong>{{ formatShare(row.share) }}</strong>
                </div>
              </div>
              <p v-else class="empty-hint">暂无成功扫描样本</p>
            </div>
          </div>

          <div class="health-correlation">
            <strong>慢扫描和业务量关系</strong>
            <p>{{ runHealthCorrelationSummary }}</p>
          </div>

          <div class="records-head">
            <h3>按天趋势</h3>
            <span>{{ runHealthDailyTrend.length }} 天</span>
          </div>
          <div v-if="runHealthDailyTrend.length" class="record-list">
            <article v-for="item in runHealthDailyTrend" :key="item.day" class="record-row">
              <div class="record-main">
                <div class="record-title-line">
                  <span class="mode-chip">{{ item.day }}</span>
                  <strong>平均耗时 {{ formatDuration(item.avg_duration_ms) }}</strong>
                </div>
                <div class="record-tags">
                  <span>扫描 {{ item.run_count }}</span>
                  <span>成功 {{ item.success_count }}</span>
                  <span>失败 {{ item.failed_count }}</span>
                  <span>慢扫描 {{ item.slow_run_count }}</span>
                  <span>平均触发 {{ item.avg_auto_reassign_triggers ?? 0 }}</span>
                  <span>平均超时 {{ item.avg_overdue_events ?? 0 }}</span>
                </div>
              </div>
              <div class="record-side">
                <span>平均扫描量</span>
                <strong>{{ item.avg_scanned_count ?? 0 }}</strong>
              </div>
            </article>
          </div>
          <p v-else class="empty-hint wide">当前时间窗口内暂无运行记录。</p>

          <div class="records-head">
            <h3>最近扫描</h3>
            <span>{{ runHealthRecentRuns.length }} 条</span>
          </div>
          <div v-if="runHealthRecentRuns.length" class="record-list">
            <article v-for="record in runHealthRecentRuns" :key="runHealthRecordKey(record)" class="record-row" :class="{ 'record-row-warn': record.is_slow }">
              <div class="record-main">
                <div class="record-title-line">
                  <span class="mode-chip" :class="runHealthSourceClass(record.trigger_source)">{{ runHealthSourceLabel(record.trigger_source) }}</span>
                  <strong>{{ runHealthStatusLabel(record.run_status) }}</strong>
                  <span>{{ formatTimeValue(record.started_at) }}</span>
                </div>
                <div class="record-tags">
                  <span>扫描 {{ record.scanned_count }}</span>
                  <span>更新 {{ record.updated_count }}</span>
                  <span>超时 {{ record.overdue_events }}</span>
                  <span>重派触发 {{ record.auto_reassign_triggers }}</span>
                  <span>真执行 {{ record.auto_reassign_executed }}</span>
                  <span>影子评估 {{ record.auto_reassign_shadow_evaluated }}</span>
                </div>
                <p v-if="record.error_message">{{ record.error_message }}</p>
              </div>
              <div class="record-side">
                <span>{{ record.is_slow ? '异常偏慢' : '正常范围' }}</span>
                <strong>{{ formatDuration(record.duration_ms) }}</strong>
              </div>
            </article>
          </div>
          <p v-else class="empty-hint wide">暂无最近扫描样本。</p>

          <div class="records-head">
            <h3>慢扫描样本</h3>
            <span>{{ runHealthSlowRuns.length }} 条</span>
          </div>
          <div v-if="runHealthSlowRuns.length" class="record-list">
            <article v-for="record in runHealthSlowRuns" :key="`slow-${runHealthRecordKey(record)}`" class="record-row record-row-warn">
              <div class="record-main">
                <div class="record-title-line">
                  <span class="mode-chip warn">{{ runHealthSourceLabel(record.trigger_source) }}</span>
                  <strong>{{ formatDuration(record.duration_ms) }}</strong>
                  <span>{{ formatTimeValue(record.started_at) }}</span>
                </div>
                <div class="record-tags">
                  <span>扫描 {{ record.scanned_count }}</span>
                  <span>超时 {{ record.overdue_events }}</span>
                  <span>重派触发 {{ record.auto_reassign_triggers }}</span>
                  <span>开大厅 {{ record.auto_reassign_hall_fallbacks }}</span>
                </div>
                <div v-if="Object.keys(record.timings_ms || {}).length" class="record-tags">
                  <span v-for="(value, key) in record.timings_ms" :key="`${record.id}-${key}`">
                    {{ runHealthTimingLabel(key) }} {{ formatDuration(Number(value || 0)) }}
                  </span>
                </div>
              </div>
              <div class="record-side">
                <span>{{ runHealthStatusLabel(record.run_status) }}</span>
                <strong>{{ record.id }}</strong>
              </div>
            </article>
          </div>
          <p v-else class="empty-hint wide">当前阈值下没有慢扫描样本。</p>
        </template>
      </div>
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
  shadowInsights: {
    type: Object as PropType<any | null>,
    default: null,
  },
  shadowFilters: {
    type: Object as PropType<Record<string, string>>,
    required: true,
  },
  shadowLoading: {
    type: Boolean,
    required: true,
  },
  shadowError: {
    type: String,
    required: true,
  },
  updateShadowFilter: {
    type: Function as PropType<(key: string, value: string) => void>,
    required: true,
  },
  refreshShadow: {
    type: Function as PropType<() => void>,
    required: true,
  },
  runHealthInsights: {
    type: Object as PropType<any | null>,
    default: null,
  },
  runHealthFilters: {
    type: Object as PropType<Record<string, string>>,
    required: true,
  },
  runHealthLoading: {
    type: Boolean,
    required: true,
  },
  runHealthError: {
    type: String,
    required: true,
  },
  updateRunHealthFilter: {
    type: Function as PropType<(key: string, value: string) => void>,
    required: true,
  },
  refreshRunHealth: {
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
const shadowTriggerOptions = [
  { label: '全部触发', value: '' },
  { label: '未接单超时', value: 'assigned_overdue' },
  { label: '已接单未到场超时', value: 'accepted_overdue' },
  { label: '责任人不可用', value: 'assignee_unavailable' },
]
const shadowEligibleOptions = [
  { label: '全部结果', value: '' },
  { label: '可安全执行', value: 'true' },
  { label: '被阻断', value: 'false' },
]
const shadowStatusOptions = [
  { label: '全部阶段', value: '' },
  { label: '未接单', value: 'assigned' },
  { label: '已接单', value: 'accepted' },
  { label: '已到场', value: 'arrived' },
  { label: '处理中', value: 'processing' },
  { label: '待协同', value: 'waiting_support' },
]
const shadowTriggerLabels: Record<string, string> = {
  assigned_overdue: '未接单超时',
  accepted_overdue: '已接单未到场超时',
  assignee_unavailable: '责任人不可用',
}
const shadowRolloutLabels: Record<string, string> = {
  in_rollout: '灰度内',
  out_of_rollout: '灰度外',
}
const shadowRolloutBlockerLabels: Record<string, string> = {
  reassign_rollout_building_not_allowed: '楼宇不在灰度范围',
  reassign_rollout_priority_not_allowed: '优先级不在灰度范围',
  reassign_rollout_skill_not_allowed: '技能不在灰度范围',
}
const shadowStatusLabels: Record<string, string> = {
  assigned: '未接单',
  accepted: '已接单',
  arrived: '已到场',
  processing: '处理中',
  waiting_support: '待协同',
}
const runHealthSourceOptions = [
  { label: '全部来源', value: '' },
  { label: '手工触发', value: 'admin_api' },
  { label: '定时任务', value: 'scheduler' },
]
const runHealthSlowThresholdOptions = [
  { label: '5 秒', value: '5000' },
  { label: '8 秒', value: '8000' },
  { label: '12 秒', value: '12000' },
  { label: '20 秒', value: '20000' },
]
const runHealthSourceLabels: Record<string, string> = {
  admin_api: '手工触发',
  scheduler: '定时任务',
}
const runHealthStatusLabels: Record<string, string> = {
  success: '成功',
  failed: '失败',
}
const runHealthTimingLabels: Record<string, string> = {
  load_dispatch_tasks: '读取派工',
  load_work_orders: '读取工单',
  load_current_assignees: '读取责任人',
  prepare_candidate_context: '准备候选上下文',
  process_loop: '逐条处理',
}
const decisionLabels: Record<string, string> = {
  ready: '可执行',
  manual_review: '人工复核',
}

const summary = computed(() => props.insights?.summary || {})
const breakdowns = computed(() => props.insights?.breakdowns || {})
const records = computed(() => props.insights?.records || [])
const pagination = computed(() => props.insights?.pagination || {})
const shadowSummary = computed(() => props.shadowInsights?.summary || {})
const shadowBreakdowns = computed(() => props.shadowInsights?.breakdowns || {})
const shadowRecords = computed(() => props.shadowInsights?.records || [])
const shadowPagination = computed(() => props.shadowInsights?.pagination || {})
const shadowSettings = computed(() => props.shadowInsights?.settings || {})
const runHealthSummary = computed(() => props.runHealthInsights?.summary || {})
const runHealthBreakdowns = computed(() => props.runHealthInsights?.breakdowns || {})
const runHealthTimingShares = computed(() => props.runHealthInsights?.timing_shares || [])
const runHealthRecentRuns = computed(() => props.runHealthInsights?.recent_runs || [])
const runHealthDailyTrend = computed(() => props.runHealthInsights?.daily_trend || [])
const runHealthSlowRuns = computed(() => props.runHealthInsights?.slow_runs || [])
const runHealthCorrelation = computed(() => props.runHealthInsights?.slow_trigger_correlation || {})
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
const shadowSummaryCards = computed(() => [
  { label: '触发评估', value: shadowSummary.value.total_evaluations ?? 0, hint: `唯一工单 ${shadowSummary.value.unique_work_orders ?? 0} · 唯一派工 ${shadowSummary.value.unique_dispatches ?? 0}` },
  { label: '可安全执行', value: shadowSummary.value.eligible_total ?? 0, hint: `命中率 ${Math.round((shadowSummary.value.eligible_rate ?? 0) * 100)}% · 灰度内 ${shadowSummary.value.in_rollout_total ?? 0}` },
  { label: '灰度内会自动改派', value: shadowSummary.value.would_execute_in_rollout_total ?? 0, hint: `理论可执行 ${shadowSummary.value.would_execute_total ?? 0}` },
  { label: '会开大厅', value: shadowSummary.value.would_hall_fallback_total ?? 0, hint: `灰度外 ${shadowSummary.value.out_of_rollout_total ?? 0} · 被阻断 ${shadowSummary.value.blocked_total ?? 0}` },
])
const shadowBreakdownGroups = computed(() => [
  { key: 'trigger', title: '触发原因', rows: shadowBreakdowns.value.by_trigger || [] },
  { key: 'status', title: '当前阶段', rows: shadowBreakdowns.value.by_status || [] },
  { key: 'blocker', title: '阻断原因', rows: shadowBreakdowns.value.by_blocker || [] },
  { key: 'rollout_blocker', title: '灰度阻断', rows: shadowBreakdowns.value.by_rollout_blocker || [] },
])
const runHealthSummaryCards = computed(() => [
  {
    label: '扫描运行',
    value: runHealthSummary.value.total_runs ?? 0,
    hint: `成功 ${runHealthSummary.value.success_runs ?? 0} · 失败 ${runHealthSummary.value.failed_runs ?? 0}`,
  },
  {
    label: '平均耗时',
    value: formatDuration(runHealthSummary.value.avg_success_duration_ms ?? runHealthSummary.value.avg_duration_ms ?? 0),
    hint: `最大 ${formatDuration(runHealthSummary.value.max_duration_ms ?? 0)}`,
  },
  {
    label: '慢扫描',
    value: runHealthSummary.value.slow_runs ?? 0,
    hint: `占比 ${formatShare(runHealthSummary.value.slow_run_rate ?? 0)}`,
  },
  {
    label: '失败运行',
    value: runHealthSummary.value.failed_runs ?? 0,
    hint: `阈值 ${formatDuration(runHealthSummary.value.slow_threshold_ms ?? 0)}`,
  },
])
const runHealthBreakdownGroups = computed(() => [
  { key: 'source', title: '运行来源', rows: runHealthBreakdowns.value.by_source || [] },
  { key: 'run_status', title: '运行结果', rows: runHealthBreakdowns.value.by_status || [] },
])
const runHealthCorrelationSummary = computed(() => {
  const slowCount = runHealthCorrelation.value.slow_run_count ?? 0
  const normalCount = runHealthCorrelation.value.normal_run_count ?? 0
  if (!slowCount && !normalCount) {
    return '当前时间窗口里的成功扫描样本还不够，先继续积累数据。'
  }
  const triggerPart = runHealthCorrelation.value.slow_runs_have_higher_trigger_load
    ? `慢扫描时自动重派触发量更高，均值 ${runHealthCorrelation.value.slow_avg_auto_reassign_triggers ?? 0}，正常批次 ${runHealthCorrelation.value.normal_avg_auto_reassign_triggers ?? 0}。`
    : `慢扫描时自动重派触发量没有明显更高，均值 ${runHealthCorrelation.value.slow_avg_auto_reassign_triggers ?? 0}，正常批次 ${runHealthCorrelation.value.normal_avg_auto_reassign_triggers ?? 0}。`
  const scanPart = runHealthCorrelation.value.slow_runs_have_higher_scan_load
    ? `慢扫描时扫描量也更高，均值 ${runHealthCorrelation.value.slow_avg_scanned_count ?? 0}，正常批次 ${runHealthCorrelation.value.normal_avg_scanned_count ?? 0}。`
    : `慢扫描时扫描量没有明显更高，均值 ${runHealthCorrelation.value.slow_avg_scanned_count ?? 0}，正常批次 ${runHealthCorrelation.value.normal_avg_scanned_count ?? 0}。`
  return `慢扫描样本 ${slowCount} 次，正常样本 ${normalCount} 次。${triggerPart}${scanPart}`
})

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

function refreshShadowValue() {
  props.refreshShadow()
}

function refreshRunHealthValue() {
  props.refreshRunHealth()
}

function onQuestionInput(event: Event) {
  props.updateExplainQuestion((event.target as HTMLInputElement).value)
}

function onShadowFilterInput(key: string, event: Event) {
  const target = event.target as HTMLInputElement | HTMLSelectElement
  props.updateShadowFilter(key, target.value)
}

function onRunHealthFilterInput(key: string, event: Event) {
  const target = event.target as HTMLInputElement | HTMLSelectElement
  props.updateRunHealthFilter(key, target.value)
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
  if (groupKey === 'trigger') return shadowTriggerLabel(value)
  if (groupKey === 'status') return shadowStatusLabel(value)
  if (groupKey === 'rollout_status') return shadowRolloutLabels[value || ''] || value || '未标记'
  if (groupKey === 'rollout_blocker') return shadowRolloutBlockerLabels[value || ''] || value || '未标记'
  if (groupKey === 'decision') return decisionLabels[value || ''] || value || '未判定'
  return value || '未标记'
}

function displayRunHealthBreakdownLabel(groupKey: string, value?: string) {
  if (groupKey === 'source') return runHealthSourceLabel(value)
  if (groupKey === 'run_status') return runHealthStatusLabel(value)
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

function formatDuration(value?: number | null) {
  const duration = Number(value || 0)
  if (!duration) return '0ms'
  if (duration >= 1000) return `${(duration / 1000).toFixed(duration >= 10000 ? 0 : 1)}s`
  return `${Math.round(duration)}ms`
}

function formatShare(value?: number | null) {
  const share = Number(value || 0)
  return `${Math.round(share * 100)}%`
}

function recordKey(record: any) {
  return record.dispatch_id || record.hall_entry_id || record.ticket_id
}

function shadowRecordKey(record: any) {
  return `${record.current_dispatch_id || record.work_order_id}-${record.created_at || ''}`
}

function shadowTriggerLabel(value?: string) {
  return shadowTriggerLabels[value || ''] || value || '其他'
}

function shadowStatusLabel(value?: string) {
  return shadowStatusLabels[value || ''] || value || '未标记'
}

function runHealthSourceLabel(value?: string) {
  return runHealthSourceLabels[value || ''] || value || '其他来源'
}

function runHealthSourceClass(value?: string) {
  return {
    fallback: value === 'admin_api',
    hall: value === 'scheduler',
  }
}

function runHealthStatusLabel(value?: string) {
  return runHealthStatusLabels[value || ''] || value || '未知状态'
}

function runHealthTimingLabel(value?: string | number) {
  const key = String(value || '')
  return runHealthTimingLabels[key] || key || '其他阶段'
}

function runHealthRecordKey(record: any) {
  return `${record.id || 'run'}-${record.started_at || ''}`
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
.shadow-box {
  display: flex;
  flex-direction: column;
  gap: 12px;
  border: 1px solid var(--border);
  border-radius: 8px;
  background: var(--bg-panel);
  padding: 16px;
}
.shadow-head {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 12px;
}
.shadow-head h3 { margin: 0 0 6px; font-size: 16px; }
.shadow-filter-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 10px;
}
.run-health-filter-grid { grid-template-columns: repeat(3, minmax(0, 1fr)); }
.run-health-note {
  display: flex;
  flex-wrap: wrap;
  align-items: flex-end;
  gap: 8px;
  min-height: 100%;
  color: var(--text-muted);
  font-size: 12px;
}
.run-health-note span {
  border-radius: 999px;
  background: rgba(148, 163, 184, 0.12);
  padding: 4px 9px;
}
.shadow-setting-line {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  color: var(--text-muted);
  font-size: 12px;
}
.shadow-setting-line span {
  border-radius: 999px;
  background: rgba(148, 163, 184, 0.12);
  padding: 4px 9px;
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
.timing-share-row {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  color: var(--text-secondary);
  font-size: 12px;
}
.timing-share-copy {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}
.timing-share-copy span,
.timing-share-copy small {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.timing-share-copy small { color: var(--text-muted); }
.timing-share-row strong { color: var(--text-primary); }
.health-correlation {
  display: flex;
  flex-direction: column;
  gap: 6px;
  border: 1px solid rgba(34, 197, 94, 0.18);
  border-radius: 8px;
  background: rgba(34, 197, 94, 0.06);
  padding: 14px;
}
.health-correlation strong { color: var(--text-primary); font-size: 13px; }
.health-correlation p { margin: 0; color: var(--text-secondary); font-size: 13px; line-height: 1.6; }
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
.record-row-warn {
  border-color: rgba(245, 158, 11, 0.24);
  background: rgba(245, 158, 11, 0.05);
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
.mode-chip.shadow { background: rgba(239, 68, 68, 0.12); color: #b91c1c; }
.mode-chip.warn { background: rgba(245, 158, 11, 0.14); color: #b45309; }
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
  .shadow-filter-grid,
  .run-health-filter-grid,
  .breakdown-grid,
  .explanation-columns { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .metric-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
}
@media (max-width: 720px) {
  .insights-head,
  .shadow-head,
  .record-row { flex-direction: column; }
  .filter-grid,
  .shadow-filter-grid,
  .run-health-filter-grid,
  .breakdown-grid,
  .metric-grid,
  .explanation-columns,
  .explain-input-row,
  .evidence-item { grid-template-columns: 1fr; }
  .record-side { align-items: flex-start; }
}
</style>
