<template>
  <div class="chart-card">
    <div class="chart-header">
      <span class="chart-title">{{ title }}</span>
      <button class="source-btn" @click="showSource = !showSource" :title="showSource ? '收起数据来源' : '展开数据来源'">
        <Icon :icon="showSource ? 'mdi:database-eye-off' : 'mdi:database-eye'" width="13" />
        数据来源
        <Icon :icon="showSource ? 'mdi:chevron-up' : 'mdi:chevron-down'" width="12" />
      </button>
    </div>

    <!-- 骨架屏（数据加载中） -->
    <div v-if="!chartReady" class="skeleton">
      <div class="skeleton-bar" v-for="i in 7" :key="i" :style="{ height: `${20 + i * 10}%` }"></div>
    </div>

    <!-- ECharts 图表 -->
    <div v-else ref="chartEl" class="chart-body"></div>

    <!-- 数据溯源面板 -->
    <Transition name="src-panel">
      <div class="source-panel" v-if="showSource">
        <!-- 动态展示 source_info 所有字段 -->
        <template v-if="sourceRows.length > 0">
          <div class="source-row" v-for="row in sourceRows" :key="row.key">
            <span class="source-key">
              <Icon :icon="row.icon" width="12" />
              {{ row.label }}
            </span>
            <span class="source-val" :class="{ success: row.isTime }">{{ row.val }}</span>
          </div>
        </template>
        <!-- 无 source_info 时的 fallback -->
        <div v-else class="source-row">
          <span class="source-key"><Icon icon="mdi:database" width="12" /> 数据来源表</span>
          <span class="source-val">energy_data</span>
        </div>
      </div>
    </Transition>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, nextTick } from 'vue'
import { Icon } from '@iconify/vue'
import * as echarts from 'echarts'
import type { ArtifactEvent } from '@/api/stream_client'

const props = defineProps<{
  artifact: ArtifactEvent
}>()

const chartEl = ref<HTMLElement>()
const showSource = ref(false)
const chartReady = ref(false)

const title = props.artifact.title ?? '能耗图表'
const sourceInfo = props.artifact.source_info as Record<string, unknown> | undefined

// ── 数据溯源字段处理 ────────────────────────────────────────────────────────

/** 字段名 → 中文标签映射（LLM 可能传多种字段名，统一转为可读文本） */
const FIELD_LABELS: Record<string, string> = {
  source_table:      '数据来源表',
  base_table:        '基础表',
  source_view:       '物化视图',
  meter_device_id:   '设备 ID',
  meter_ids:         '设备列表',
  query_time_ms:     '查询耗时',
  query_ms:          '查询耗时',
  building_id:       '楼宇',
  building_type:     '楼宇类型',
  aggregation:       '聚合方式',
  total_count:       '数据量',
  data_points:       '数据点',
}

const FIELD_ICONS: Record<string, string> = {
  source_table:    'mdi:database',
  base_table:      'mdi:table',
  source_view:     'mdi:view-dashboard',
  meter_device_id: 'mdi:antenna',
  meter_ids:       'mdi:antenna',
  query_time_ms:   'mdi:timer-outline',
  query_ms:        'mdi:timer-outline',
  building_id:     'mdi:office-building',
  building_type:   'mdi:office-building',
}

/** 是否为"耗时"类字段（显示绿色 + ms 单位） */
function isTimeField(key: string) {
  return key === 'query_time_ms' || key === 'query_ms'
}

/** 将字段值格式化为显示字符串 */
function fmtVal(key: string, val: unknown): string {
  if (val === null || val === undefined) return '—'
  if (Array.isArray(val)) return val.join(', ')
  if (isTimeField(key)) return `${val} ms`
  return String(val)
}

/**
 * 动态计算可展示的 source_info 条目列表。
 * 排除 null/undefined 值及复杂嵌套对象（只展平一层）。
 */
const sourceRows = computed(() => {
  if (!sourceInfo || typeof sourceInfo !== 'object') return []
  return Object.entries(sourceInfo)
    .filter(([, v]) => v !== null && v !== undefined && (typeof v !== 'object' || Array.isArray(v)))
    .map(([k, v]) => ({
      key: k,
      label: FIELD_LABELS[k] ?? k,
      icon: FIELD_ICONS[k] ?? 'mdi:information-outline',
      val: fmtVal(k, v),
      isTime: isTimeField(k),
    }))
})

// 多系列配色盘
const PALETTE = ['#6c8ef5', '#4ade80', '#f59e0b', '#f87171', '#a78bfa', '#38bdf8']

function buildOption() {
  const payload = props.artifact.data_payload as Record<string, unknown> | unknown[]
  const rawWidget = props.artifact.widget ?? props.artifact.component_type ?? 'LineChart'
  const isBar   = rawWidget === 'BarChart' || rawWidget === 'bar-chart'
  const isGauge = rawWidget === 'Gauge'    || rawWidget === 'gauge'

  // ── Gauge ───────────────────────────────────────────────────────────────
  if (isGauge) {
    const val = Number((payload as Record<string, unknown>).value ?? 0)
    return {
      series: [{
        type: 'gauge', startAngle: 200, endAngle: -20,
        min: 0, max: 6, splitNumber: 6,
        axisLine: { lineStyle: { width: 20, color: [[0.3, '#4ade80'], [0.7, '#fbbf24'], [1, '#f87171']] } },
        pointer: { itemStyle: { color: 'auto' } },
        detail: { valueAnimation: true, fontSize: 28, color: 'auto', formatter: '{value} COP' },
        data: [{ value: val }],
      }],
    }
  }

  // ── 多系列格式：{ series: [{ name, data, timestamps? }, ...] } ──────────
  // 兼容：LLM 按 genui_protocol ChartPayload 结构传入多楼对比数据
  const objPayload = payload as Record<string, unknown>
  if (!Array.isArray(payload) && Array.isArray(objPayload.series)) {
    type SeriesItem = { name: string; data: number[]; timestamps?: string[] }
    const seriesList = objPayload.series as SeriesItem[]
    const xData: string[] = (seriesList[0]?.timestamps ?? []).map(String)
    // timestamps 为空时用数字序号作为 x 轴
    const xFallback = seriesList[0]?.data?.map((_: number, i: number) => String(i + 1)) ?? []
    const xAxis = xData.length ? xData : xFallback

    const hasLegend = seriesList.length > 1

    return {
      grid: { top: hasLegend ? 40 : 20, right: 20, bottom: 40, left: 55 },
      legend: hasLegend ? {
        top: 4,
        textStyle: { color: '#9399b8', fontSize: 11 },
      } : undefined,
      xAxis: { type: 'category', data: xAxis, axisLabel: { color: '#9399b8', fontSize: 10, rotate: 30 } },
      yAxis: { type: 'value', axisLabel: { color: '#9399b8', fontSize: 11 } },
      tooltip: { trigger: 'axis' },
      series: seriesList.map((s, i) => {
        const color = PALETTE[i % PALETTE.length]
        return isBar
          ? { type: 'bar', name: s.name, data: s.data, itemStyle: { color, borderRadius: [3, 3, 0, 0] } }
          : {
              type: 'line', name: s.name, data: s.data, smooth: true,
              lineStyle: { color, width: 2 },
              itemStyle: { color },
              areaStyle: {
                color: {
                  type: 'linear', x: 0, y: 0, x2: 0, y2: 1,
                  colorStops: [
                    { offset: 0, color: color + '4d' },
                    { offset: 1, color: color + '00' },
                  ],
                },
              },
            }
      }),
    }
  }

  // ── 单系列数组格式：[{ label/day/timestamp, value/total_electricity_kwh }, ...] ──
  if (Array.isArray(payload)) {
    const xData = payload.map((d: unknown) => {
      const item = d as Record<string, unknown>
      return String(item.label ?? item.day ?? item.timestamp ?? item[0] ?? '')
    })
    const yData = payload.map((d: unknown) => {
      const item = d as Record<string, unknown>
      return Number(item.value ?? item.total_electricity_kwh ?? item[1] ?? 0)
    })

    if (isBar) {
      return {
        grid: { top: 20, right: 20, bottom: 40, left: 55 },
        xAxis: { type: 'category', data: xData, axisLabel: { color: '#9399b8', fontSize: 10, rotate: 30 } },
        yAxis: { type: 'value', axisLabel: { color: '#9399b8', fontSize: 11 } },
        series: [{ type: 'bar', data: yData, itemStyle: { color: PALETTE[0], borderRadius: [3, 3, 0, 0] } }],
        tooltip: { trigger: 'axis' },
      }
    }
    return {
      grid: { top: 20, right: 20, bottom: 40, left: 55 },
      xAxis: { type: 'category', data: xData, axisLabel: { color: '#9399b8', fontSize: 10, rotate: 30 } },
      yAxis: { type: 'value', axisLabel: { color: '#9399b8', fontSize: 11 } },
      series: [{
        type: 'line', data: yData, smooth: true,
        lineStyle: { color: PALETTE[0], width: 2 },
        areaStyle: { color: { type: 'linear', x: 0, y: 0, x2: 0, y2: 1, colorStops: [{ offset: 0, color: 'rgba(108,142,245,0.3)' }, { offset: 1, color: 'rgba(108,142,245,0)' }] } },
        itemStyle: { color: PALETTE[0] },
      }],
      tooltip: { trigger: 'axis' },
    }
  }

  return {}
}

async function initChart() {
  await nextTick()
  if (!chartEl.value) return
  const chart = echarts.init(chartEl.value, 'dark')
  chart.setOption(buildOption())
  window.addEventListener('resize', () => chart.resize())
}

onMounted(async () => {
  chartReady.value = true
  await initChart()
})
</script>

<style scoped>
.chart-card {
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: 10px;
  overflow: hidden;
  margin: 8px 0;
  flex-shrink: 0;
  box-shadow: var(--card-shadow);
}

.chart-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 12px 16px 8px;
}

.chart-title {
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

.source-key {
  display: inline-flex;
  align-items: center;
  gap: 4px;
}

.skeleton {
  height: 200px;
  display: flex;
  align-items: flex-end;
  gap: 8px;
  padding: 16px;
}
.skeleton-bar {
  flex: 1;
  background: var(--bg-hover);
  border-radius: 4px 4px 0 0;
  animation: shimmer 1.5s infinite;
}
@keyframes shimmer {
  0%, 100% { opacity: 0.5; }
  50% { opacity: 1; }
}

.chart-body {
  width: 100%;
  height: 260px;
}

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
.source-val.success { color: var(--success); }

/* 折叠展开动画 */
.src-panel-enter-active { animation: srcDown 0.2s ease-out; overflow: hidden; }
.src-panel-leave-active { animation: srcUp 0.15s ease-in; overflow: hidden; }
@keyframes srcDown { from { max-height: 0; opacity: 0; } to { max-height: 200px; opacity: 1; } }
@keyframes srcUp   { from { max-height: 200px; opacity: 1; } to { max-height: 0; opacity: 0; } }
</style>
