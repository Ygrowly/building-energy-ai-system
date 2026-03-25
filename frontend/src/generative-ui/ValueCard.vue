<template>
  <div class="value-card" :class="{ 'value-card--inline': inline }">
    <div class="card-header">
      <span class="card-title">{{ title }}</span>
      <button class="source-btn" @click="showSource = !showSource" :title="showSource ? '收起数据来源' : '展开数据来源'">
        <Icon :icon="showSource ? 'mdi:database-eye-off' : 'mdi:database-eye'" width="13" />
        数据来源
        <Icon :icon="showSource ? 'mdi:chevron-up' : 'mdi:chevron-down'" width="12" />
      </button>
    </div>

    <!-- 简单数值模式 -->
    <div v-if="mode === 'simple'" class="simple-body">
      <div class="big-value">{{ formattedValue }}</div>
      <div class="unit">{{ payload.unit }}</div>
      <div v-if="payload.label" class="label">{{ payload.label }}</div>
    </div>

    <!-- 同环比对比模式 -->
    <div v-else-if="mode === 'comparison'" class="comparison-body">
      <div class="periods">
        <div class="period">
          <div class="period-label">{{ payload.period_a?.label }}</div>
          <div class="period-value">{{ fmtNum(payload.period_a?.value) }} <span class="period-unit">{{ payload.unit }}</span></div>
        </div>
        <div class="vs-divider">
          <Icon icon="mdi:swap-horizontal" width="20" />
        </div>
        <div class="period">
          <div class="period-label">{{ payload.period_b?.label }}</div>
          <div class="period-value">{{ fmtNum(payload.period_b?.value) }} <span class="period-unit">{{ payload.unit }}</span></div>
        </div>
      </div>
      <div class="delta-row">
        <span class="delta-badge" :class="deltaClass">
          <Icon :icon="deltaIcon" width="14" />
          {{ deltaText }}
        </span>
      </div>
    </div>

    <!-- 数据溯源面板 -->
    <Transition name="src-panel">
      <div class="source-panel" v-if="showSource">
        <template v-if="sourceRows.length > 0">
          <div class="source-row" v-for="row in sourceRows" :key="row.key">
            <span class="source-key">
              <Icon :icon="row.icon" width="12" />
              {{ row.label }}
            </span>
            <span class="source-val">{{ row.val }}</span>
          </div>
        </template>
        <div v-else class="source-row">
          <span class="source-key"><Icon icon="mdi:database" width="12" /> 数据来源表</span>
          <span class="source-val">energy_data</span>
        </div>
      </div>
    </Transition>
  </div>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import { Icon } from '@iconify/vue'
import type { ArtifactEvent } from '@/api/stream_client'

const props = defineProps<{
  artifact: ArtifactEvent
  /** 内嵌在 AI 气泡内时为 true，调整样式以融入气泡 */
  inline?: boolean
}>()

const showSource = ref(false)
const title = props.artifact.title ?? '数据概览'
const payload = (props.artifact.data_payload ?? {}) as Record<string, any>
const sourceInfo = props.artifact.source_info as Record<string, unknown> | undefined
const mode = computed(() => payload.mode || 'simple')

// ── 数值格式化 ──
function fmtNum(val: unknown): string {
  if (val === null || val === undefined) return '—'
  const n = Number(val)
  if (isNaN(n)) return String(val)
  if (Math.abs(n) >= 1000) return Math.round(n).toLocaleString()
  return n.toFixed(2)
}

const formattedValue = computed(() => fmtNum(payload.value))

// ── 同环比变化 ──
const deltaClass = computed(() => {
  const d = Number(payload.delta ?? 0)
  if (d > 0) return 'up'
  if (d < 0) return 'down'
  return 'flat'
})

const deltaIcon = computed(() => {
  const d = Number(payload.delta ?? 0)
  if (d > 0) return 'mdi:trending-up'
  if (d < 0) return 'mdi:trending-down'
  return 'mdi:trending-neutral'
})

const deltaText = computed(() => {
  const d = Number(payload.delta ?? 0)
  const pct = payload.delta_pct
  const sign = d >= 0 ? '+' : ''
  let text = `${sign}${fmtNum(d)} ${payload.unit || ''}`
  if (pct !== null && pct !== undefined) {
    text += ` (${d >= 0 ? '+' : ''}${Number(pct).toFixed(1)}%)`
  }
  return text
})

// ── 数据溯源 ──
const FIELD_LABELS: Record<string, string> = {
  source_table: '数据来源表', base_table: '基础表', source_view: '物化视图',
  building_id: '楼宇', date: '日期', aggregation: '聚合方式', unit: '单位',
}
const FIELD_ICONS: Record<string, string> = {
  source_table: 'mdi:database', base_table: 'mdi:table', source_view: 'mdi:view-dashboard',
  building_id: 'mdi:office-building', date: 'mdi:calendar', aggregation: 'mdi:sigma',
  unit: 'mdi:ruler',
}

const sourceRows = computed(() => {
  if (!sourceInfo || typeof sourceInfo !== 'object') return []
  return Object.entries(sourceInfo)
    .filter(([, v]) => v !== null && v !== undefined && (typeof v !== 'object' || Array.isArray(v)))
    .map(([k, v]) => ({
      key: k,
      label: FIELD_LABELS[k] ?? k,
      icon: FIELD_ICONS[k] ?? 'mdi:information-outline',
      val: Array.isArray(v) ? v.join(', ') : String(v),
    }))
})
</script>

<style scoped>
.value-card {
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: 10px;
  overflow: hidden;
  margin: 8px 0;
  flex-shrink: 0;
  box-shadow: var(--card-shadow);
}

.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 12px 16px 8px;
}

.card-title {
  font-weight: 600;
  color: var(--text-primary);
  font-size: 13px;
}

.source-btn {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  background: none;
  border: 1px solid var(--border);
  border-radius: 4px;
  color: var(--text-secondary);
  font-size: 11px;
  padding: 3px 8px;
  cursor: pointer;
  transition: all 0.2s;
}
.source-btn:hover { border-color: var(--accent); color: var(--accent); }

/* ── 简单数值 ── */
.simple-body {
  padding: 16px 24px 20px;
  text-align: center;
}

.big-value {
  font-size: 36px;
  font-weight: 700;
  color: var(--accent, #6c8ef5);
  line-height: 1.2;
  font-variant-numeric: tabular-nums;
}

.unit {
  font-size: 14px;
  color: var(--text-secondary);
  margin-top: 2px;
}

.label {
  font-size: 12px;
  color: var(--text-muted);
  margin-top: 6px;
}

/* ── 对比模式 ── */
.comparison-body {
  padding: 16px 20px 12px;
}

.periods {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 12px;
}

.period {
  flex: 1;
  text-align: center;
}

.period-label {
  font-size: 11px;
  color: var(--text-muted);
  margin-bottom: 4px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.period-value {
  font-size: 22px;
  font-weight: 700;
  color: var(--text-primary);
  font-variant-numeric: tabular-nums;
}

.period-unit {
  font-size: 12px;
  font-weight: 400;
  color: var(--text-secondary);
}

.vs-divider {
  color: var(--text-muted);
  flex-shrink: 0;
  padding: 0 4px;
}

.delta-row {
  text-align: center;
  margin-top: 10px;
}

.delta-badge {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: 12px;
  font-weight: 600;
  padding: 3px 10px;
  border-radius: 12px;
}

.delta-badge.up {
  background: rgba(248, 113, 113, 0.12);
  color: #f87171;
}

.delta-badge.down {
  background: rgba(74, 222, 128, 0.12);
  color: #4ade80;
}

.delta-badge.flat {
  background: rgba(148, 163, 184, 0.12);
  color: var(--text-secondary);
}

/* ── 溯源面板 ── */
.source-panel {
  border-top: 1px solid var(--border);
  padding: 10px 16px;
  background: var(--bg-panel);
  overflow: hidden;
}

.source-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 3px 0;
  font-size: 12px;
}

.source-key {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  color: var(--text-muted);
}

.source-val {
  color: var(--text-secondary);
  font-family: monospace;
  font-size: 11px;
  max-width: 60%;
  text-align: right;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

/* 折叠动画 */
.src-panel-enter-active { animation: srcDown 0.2s ease-out; overflow: hidden; }
.src-panel-leave-active { animation: srcUp 0.15s ease-in; overflow: hidden; }
@keyframes srcDown { from { max-height: 0; opacity: 0; } to { max-height: 200px; opacity: 1; } }
@keyframes srcUp   { from { max-height: 200px; opacity: 1; } to { max-height: 0; opacity: 0; } }

/* ── 内嵌模式 ───────────────────────────────────────────────────────── */
.value-card--inline {
  background: rgba(255, 255, 255, 0.02);
  border-color: rgba(255, 255, 255, 0.06);
  margin: 10px 0;
  box-shadow: none;
}

html[data-theme="light"] .value-card--inline {
  background: rgba(0, 0, 0, 0.02);
  border-color: rgba(0, 0, 0, 0.06);
}
</style>
