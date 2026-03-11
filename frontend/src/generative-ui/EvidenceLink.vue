<template>
  <div class="evidence" v-if="hasInfo">
    <button class="evidence-toggle" @click="open = !open">
      <span class="evidence-icon"><Icon icon="mdi:magnify" width="13" /></span>
      <span class="evidence-label">数据来源</span>
      <span class="evidence-arrow">{{ open ? '▲' : '▼' }}</span>
    </button>

    <Transition name="slide">
      <div class="evidence-panel" v-if="open">
        <div class="ev-row" v-for="row in infoRows" :key="row.key">
          <span class="ev-icon"><Icon :icon="row.icon" width="12" /></span>
          <span class="ev-key">{{ row.label }}</span>
          <span class="ev-val" :class="row.cls">{{ row.value }}</span>
        </div>
      </div>
    </Transition>
  </div>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue'
import { Icon } from '@iconify/vue'

const props = defineProps<{
  sourceInfo?: Record<string, unknown>
}>()

const open = ref(false)

const hasInfo = computed(() =>
  props.sourceInfo && Object.keys(props.sourceInfo).length > 0,
)

const LABELS: Record<string, { label: string; icon: string; cls?: string }> = {
  source_table:    { label: '数据来源',   icon: 'mdi:package-variant' },
  meter_device_id: { label: '设备 ID',    icon: 'mdi:antenna',        cls: 'mono' },
  building_type:   { label: '楼宇',       icon: 'mdi:office-building' },
  query_time_ms:   { label: '查询耗时',   icon: 'mdi:timer-outline',  cls: 'success' },
  record_count:    { label: '数据条数',   icon: 'mdi:counter' },
  start_date:      { label: '开始日期',   icon: 'mdi:calendar-start' },
  end_date:        { label: '结束日期',   icon: 'mdi:calendar-end' },
  tool_name:       { label: '工具名称',   icon: 'mdi:tools',          cls: 'mono' },
  confidence:      { label: '置信度',     icon: 'mdi:trending-up',    cls: 'accent' },
  rag_doc_id:      { label: '知识库片段', icon: 'mdi:book-open-page-variant', cls: 'mono' },
}

const infoRows = computed(() => {
  const info = props.sourceInfo ?? {}
  return Object.entries(info)
    .filter(([, v]) => v != null && v !== '')
    .map(([key, value]) => {
      const meta = LABELS[key] ?? { label: key, icon: 'mdi:circle-small' }
      let displayVal = String(value)
      if (key === 'query_time_ms') displayVal = `${value} ms`
      if (key === 'confidence')    displayVal = `${(Number(value) * 100).toFixed(0)}%`
      return { key, label: meta.label, icon: meta.icon, value: displayVal, cls: meta.cls ?? '' }
    })
})
</script>

<style scoped>
.evidence {
  margin-top: 6px;
  border-radius: 6px;
  overflow: hidden;
  border: 1px solid var(--border);
  font-size: 12px;
}

.evidence-toggle {
  display: flex;
  align-items: center;
  gap: 6px;
  width: 100%;
  background: var(--bg-panel);
  border: none;
  color: var(--text-muted);
  padding: 6px 10px;
  cursor: pointer;
  text-align: left;
  transition: color 0.2s;
}
.evidence-toggle:hover { color: var(--accent); }

.evidence-icon  { display: flex; align-items: center; }
.evidence-label { flex: 1; font-weight: 600; }
.evidence-arrow { font-size: 10px; }

.evidence-panel {
  background: var(--bg-card);
  padding: 6px 10px 8px;
  border-top: 1px solid var(--border);
}

.ev-row {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 3px 0;
  border-bottom: 1px solid rgba(46,49,72,0.5);
}
.ev-row:last-child { border-bottom: none; }

.ev-icon  { display: flex; align-items: center; width: 16px; flex-shrink: 0; color: var(--text-muted); }
.ev-key   { color: var(--text-muted); width: 70px; flex-shrink: 0; }
.ev-val   { color: var(--text-secondary); flex: 1; word-break: break-all; }
.ev-val.mono    { font-family: monospace; color: var(--accent); }
.ev-val.success { color: var(--success); }
.ev-val.accent  { color: var(--accent); }

/* 展开动画 */
.slide-enter-active, .slide-leave-active { transition: all 0.2s ease; overflow: hidden; }
.slide-enter-from, .slide-leave-to { opacity: 0; max-height: 0; }
.slide-enter-to, .slide-leave-from { opacity: 1; max-height: 300px; }
</style>
