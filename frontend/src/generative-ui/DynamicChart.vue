<template>
  <div class="chart-card" :class="{ 'chart-card--inline': inline }">
    <div class="chart-header">
      <span class="chart-title">{{ title }}</span>
      <button class="source-btn" @click="showSource = !showSource" :title="showSource ? '收起数据来源' : '展开数据来源'">
        <Icon :icon="showSource ? 'mdi:database-eye-off' : 'mdi:database-eye'" width="13" />
        数据来源
        <Icon :icon="showSource ? 'mdi:chevron-up' : 'mdi:chevron-down'" width="12" />
      </button>
    </div>

    <!-- 骨架屏：inline 模式用 ChartSkeleton，独立模式用简易柱条 -->
    <ChartSkeleton v-if="!chartReady && inline" />
    <div v-else-if="!chartReady" class="skeleton">
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
import { ref, computed, onMounted, onUnmounted, nextTick, watch } from 'vue'
import { Icon } from '@iconify/vue'
import * as echarts from 'echarts'
import ChartSkeleton from '@/generative-ui/ChartSkeleton.vue'
import type { ArtifactEvent } from '@/api/stream_client'

const props = defineProps<{
  artifact: ArtifactEvent
  /** 内嵌在 AI 气泡内时为 true，调整样式以融入气泡 */
  inline?: boolean
  /** 骨架屏由外部管理时为 true，跳过内部延迟直接渲染图表 */
  skipSkeleton?: boolean
}>()

const chartEl = ref<HTMLElement>()
const showSource = ref(false)
const chartReady = ref(false)

let _chart: echarts.ECharts | null = null
let _ro: ResizeObserver | null = null
let _initRaf: number | null = null

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

const isLight = () => document.documentElement.getAttribute('data-theme') === 'light'

/** 主题感知的图表颜色 */
function themeColors() {
  if (isLight()) {
    return {
      axisLabel: '#374151',   // gray-700
      axisLine:  '#d1d5db',   // gray-300
      splitLine: '#e5e7eb',   // gray-200
      legend:    '#374151',
      tooltip:   { bg: '#ffffff', border: '#e5e7eb', text: '#1f2937' },
    }
  }
  return {
    axisLabel: '#9399b8',
    axisLine:  'rgba(255,255,255,0.1)',
    splitLine: 'rgba(255,255,255,0.06)',
    legend:    '#9399b8',
    tooltip:   { bg: '#1e1e2e', border: '#333', text: '#e0e0e0' },
  }
}

function buildOption() {
  const payload = props.artifact.data_payload as Record<string, unknown> | unknown[]
  const rawWidget = props.artifact.widget ?? props.artifact.component_type ?? 'LineChart'
  const isBar   = rawWidget === 'BarChart' || rawWidget === 'bar-chart'
  const isGauge = rawWidget === 'Gauge'    || rawWidget === 'gauge'
  const tc = themeColors()

  function coerceNumber(raw: unknown): number | null {
    if (raw === null || raw === undefined) return null
    if (typeof raw === 'number') return Number.isFinite(raw) ? raw : null
    if (typeof raw === 'bigint') {
      const n = Number(raw)
      return Number.isFinite(n) ? n : null
    }
    if (typeof raw === 'string') {
      const normalized = raw.replace(/,/g, '').trim()
      const direct = Number(normalized)
      if (Number.isFinite(direct)) return direct
      const matched = normalized.match(/-?\d+(?:\.\d+)?/)
      if (!matched) return null
      const extracted = Number(matched[0])
      return Number.isFinite(extracted) ? extracted : null
    }
    if (typeof raw === 'object') {
      const obj = raw as Record<string, unknown>
      const candidate = obj.value
        ?? obj.total_electricity_kwh
        ?? obj.electricity_kwh
        ?? obj.kwh
        ?? obj.amount
        ?? obj.y
        ?? obj.aggregated_value
        ?? obj.avg
        ?? obj.average
        ?? obj.mean
        ?? obj.metric_value
        ?? obj.raw_value
        ?? obj.raw
        ?? obj.score
      if (candidate !== undefined) return coerceNumber(candidate)
    }
    return null
  }

  function toNumberList(raw: unknown): (number | null)[] {
    if (Array.isArray(raw)) return raw.map(coerceNumber)
    if (raw && typeof raw === 'object') return Object.values(raw).map(coerceNumber)
    return []
  }

  function toLabelList(raw: unknown): string[] {
    if (Array.isArray(raw)) return raw.map(String)
    if (raw && typeof raw === 'object') return Object.keys(raw as Record<string, unknown>)
    return []
  }

  function deriveLabelsFromItems(raw: unknown): string[] {
    if (!Array.isArray(raw)) return []
    return raw.map((item, index) => {
      if (item && typeof item === 'object') {
        const obj = item as Record<string, unknown>
        return String(
          obj.label
          ?? obj.name
          ?? obj.category
          ?? obj.x
          ?? obj.day
          ?? obj.timestamp
          ?? index + 1,
        )
      }
      return String(index + 1)
    })
  }

  function hasPlottableValues(values: (number | null)[]): boolean {
    return values.some((v) => typeof v === 'number' && Number.isFinite(v))
  }

  function prettifyKeyLabel(key: string): string {
    return key
      .replace(/_/g, ' ')
      .replace(/\s+/g, ' ')
      .trim()
  }

  function deriveScalarEntries(obj: Record<string, unknown>) {
    const META_KEYS = new Set([
      'labels', 'categories', 'xAxis', 'xAxisData', 'x',
      'dates', 'days', 'values', 'data', 'y', 'items',
      'series', 'seriesName', 'name', 'title', 'unit',
      'source', 'source_info', 'sourceInfo', 'meta',
      'tooltip', 'legend', 'grid', 'color', 'colors',
    ])

    return Object.entries(obj)
      .filter(([key]) => !META_KEYS.has(key) && !key.startsWith('_'))
      .map(([key, value]) => {
        if (value && typeof value === 'object' && !Array.isArray(value)) {
          const item = value as Record<string, unknown>
          const num = coerceNumber(item)
          const label = String(item.label ?? item.name ?? item.category ?? prettifyKeyLabel(key))
          return { label, value: num }
        }
        return { label: prettifyKeyLabel(key), value: coerceNumber(value) }
      })
      .filter((entry) => entry.value !== null)
  }

  const baseTooltip = {
    trigger: 'axis' as const,
    backgroundColor: tc.tooltip.bg,
    borderColor: tc.tooltip.border,
    textStyle: { color: tc.tooltip.text, fontSize: 12 },
    valueFormatter: (v: number) => v != null ? v.toFixed(2) : '—',
  }

  // ── Gauge ───────────────────────────────────────────────────────────────
  if (isGauge) {
    const gp = payload as Record<string, unknown>
    const val = Number(gp.value ?? 0)
    const unit = (gp.unit as string) || ''
    const gMin = Number(gp.min ?? 0)
    const gMax = Number(gp.max ?? (Math.ceil(val * 1.5) || 6))
    const range = gMax - gMin
    const splitN = Number(gp.splitNumber ?? (range <= 10 ? Math.max(range, 2) : 5))
    const defaultColor: [number, string][] = [[0.3, '#4ade80'], [0.7, '#fbbf24'], [1, '#f87171']]
    const colorStops = (Array.isArray(gp.colorStops) ? gp.colorStops : defaultColor) as [number, string][]
    const labelDecimal = range > 10 ? 0 : 1
    const detailFmt = (v: number) => {
      const s = v >= 1000 ? Math.round(v).toString() : v.toFixed(2)
      return `${s} ${unit}`
    }
    return {
      series: [{
        type: 'gauge', startAngle: 200, endAngle: -20,
        min: gMin, max: gMax, splitNumber: splitN,
        axisLine: { lineStyle: { width: 20, color: colorStops } },
        pointer: { itemStyle: { color: 'auto' } },
        axisLabel: { fontSize: 11, color: tc.axisLabel, formatter: (v: number) => v.toFixed(labelDecimal) },
        detail: { valueAnimation: true, fontSize: 28, color: 'auto', formatter: detailFmt, offsetCenter: [0, '70%'] },
        data: [{ value: val }],
      }],
    }
  }

  const baseXAxis = (data: string[]) => ({
    type: 'category' as const,
    data,
    axisLabel: { color: tc.axisLabel, fontSize: 10, rotate: 30 },
    axisLine: { lineStyle: { color: tc.axisLine } },
  })

  const baseYAxis = () => ({
    type: 'value' as const,
    axisLabel: { color: tc.axisLabel, fontSize: 11 },
    axisLine: { lineStyle: { color: tc.axisLine } },
    splitLine: { lineStyle: { color: tc.splitLine } },
  })

  const baseCategoryYAxis = (data: string[]) => ({
    type: 'category' as const,
    data,
    axisLabel: { color: tc.axisLabel, fontSize: 10 },
    axisLine: { lineStyle: { color: tc.axisLine } },
  })

  // ── 多系列格式：{ series: [{ name, data, timestamps? }, ...] } ──────────
  const objPayload = payload as Record<string, unknown>
  if (!Array.isArray(payload) && Array.isArray(objPayload.series)) {
    type SeriesItem = Record<string, unknown>

    function extractData(s: SeriesItem): (number | null)[] {
      return toNumberList(s.data ?? s.values ?? s.y ?? s.value ?? s.electricity_kwh ?? [])
    }

    function extractTimestamps(s: SeriesItem): string[] {
      const raw = (s.timestamps ?? s.dates ?? s.days ?? s.labels ?? s.x ?? s.time ?? []) as unknown[]
      return Array.isArray(raw) ? raw.map(String) : []
    }

    const seriesList = objPayload.series as SeriesItem[]
    const xData = extractTimestamps(seriesList[0] ?? {})
    const firstData = extractData(seriesList[0] ?? {})
    const xFallback = firstData.map((_, i) => String(i + 1))
    const xAxis = xData.length ? xData : xFallback

    const hasLegend = seriesList.length > 1

    return {
      grid: { top: hasLegend ? 40 : 20, right: 20, bottom: 40, left: 55 },
      legend: hasLegend ? {
        top: 4,
        textStyle: { color: tc.legend, fontSize: 11 },
      } : undefined,
      xAxis: baseXAxis(xAxis),
      yAxis: baseYAxis(),
      tooltip: baseTooltip,
      series: seriesList.map((s, i) => {
        const color = PALETTE[i % PALETTE.length]
        const yData = extractData(s)
        return isBar
          ? { type: 'bar', name: String(s.name ?? `系列${i + 1}`), data: yData, itemStyle: { color, borderRadius: [3, 3, 0, 0] } }
          : {
              type: 'line', name: String(s.name ?? `系列${i + 1}`), data: yData, smooth: true,
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
  if (!Array.isArray(payload) && Array.isArray(objPayload.datasets)) {
    type DatasetItem = Record<string, unknown>
    const labels = toLabelList(objPayload.labels ?? objPayload.categories ?? [])
    const datasets = (objPayload.datasets as DatasetItem[]).filter(Boolean)
    const config = (objPayload.config as Record<string, unknown> | undefined) ?? {}
    const horizontal = String(config.indexAxis ?? 'x') === 'y'
    const hasLegend = datasets.length > 1

    return {
      grid: horizontal
        ? { top: hasLegend ? 40 : 20, right: 20, bottom: 20, left: 88 }
        : { top: hasLegend ? 40 : 20, right: 20, bottom: 40, left: 55 },
      legend: hasLegend ? {
        top: 4,
        textStyle: { color: tc.legend, fontSize: 11 },
      } : undefined,
      tooltip: {
        ...baseTooltip,
        trigger: 'item' as const,
      },
      xAxis: horizontal ? baseYAxis() : baseXAxis(labels),
      yAxis: horizontal ? baseCategoryYAxis(labels) : baseYAxis(),
      series: datasets.map((ds, i) => {
        const color = PALETTE[i % PALETTE.length]
        const values = toNumberList(ds.data ?? ds.values ?? [])
        const colors = Array.isArray(ds.backgroundColor)
          ? (ds.backgroundColor as unknown[]).map((c) => String(c))
          : []
        const barData = colors.length === values.length
          ? values.map((value, index) => ({
              value,
              itemStyle: { color: colors[index] },
            }))
          : values

        return {
          type: 'bar',
          name: String(ds.label ?? `系列${i + 1}`),
          data: barData,
          itemStyle: horizontal
            ? { color, borderRadius: [0, 3, 3, 0] }
            : { color, borderRadius: [3, 3, 0, 0] },
        }
      }),
    }
  }

  if (!Array.isArray(payload)) {
    const rawLabels = (
      objPayload.labels
      ?? objPayload.categories
      ?? objPayload.xAxis
      ?? objPayload.xAxisData
      ?? objPayload.x
      ?? objPayload.dates
      ?? objPayload.days
    ) as unknown
    const rawValues = (
      objPayload.values
      ?? objPayload.data
      ?? objPayload.y
      ?? objPayload.items
    ) as unknown

    const xData = toLabelList(rawLabels)
    const yData = toNumberList(rawValues)
    const itemLabels = xData.length === 0 ? deriveLabelsFromItems(rawValues) : []
    const scalarEntries = deriveScalarEntries(objPayload)
    const scalarLabels = scalarEntries.map((entry) => entry.label)
    const scalarValues = scalarEntries.map((entry) => entry.value)

    const normalizedYData = hasPlottableValues(yData)
      ? yData
      : (xData.length > 0 && scalarValues.length === xData.length ? scalarValues : scalarValues)
    const normalizedXData = xData.length
      ? xData
      : (itemLabels.length ? itemLabels : (scalarLabels.length ? scalarLabels : normalizedYData.map((_, i) => String(i + 1))))

    if (normalizedXData.length > 0 || normalizedYData.length > 0) {
      const safeXData = normalizedXData
      const seriesName = String(objPayload.seriesName ?? objPayload.name ?? title)
      if (safeXData.length > 0 && !hasPlottableValues(normalizedYData)) {
        console.warn('[DynamicChart] No plottable values in object payload', {
          title,
          rawWidget,
          payload,
        })
      }

      if (isBar) {
        return {
          grid: { top: 20, right: 20, bottom: 40, left: 55 },
          xAxis: baseXAxis(safeXData),
          yAxis: baseYAxis(),
          series: [{
            type: 'bar',
            name: seriesName,
            data: normalizedYData,
            itemStyle: { color: PALETTE[0], borderRadius: [3, 3, 0, 0] },
          }],
          tooltip: baseTooltip,
        }
      }
      return {
        grid: { top: 20, right: 20, bottom: 40, left: 55 },
        xAxis: baseXAxis(safeXData),
        yAxis: baseYAxis(),
        series: [{
          type: 'line',
          name: seriesName,
          data: normalizedYData,
          smooth: true,
          lineStyle: { color: PALETTE[0], width: 2 },
          areaStyle: { color: { type: 'linear', x: 0, y: 0, x2: 0, y2: 1, colorStops: [{ offset: 0, color: 'rgba(108,142,245,0.3)' }, { offset: 1, color: 'rgba(108,142,245,0)' }] } },
          itemStyle: { color: PALETTE[0] },
        }],
        tooltip: baseTooltip,
      }
    }
  }

  if (Array.isArray(payload)) {
    const xData = payload.map((d: unknown) => {
      const item = d as Record<string, unknown>
      return String(item.label ?? item.name ?? item.category ?? item.day ?? item.timestamp ?? item[0] ?? '')
    })
    const yData = payload.map((d: unknown) => {
      const item = d as Record<string, unknown>
      return coerceNumber(item.value ?? item.total_electricity_kwh ?? item.aggregated_value ?? item.average ?? item.avg ?? item[1] ?? 0)
    })
    if (xData.length > 0 && !hasPlottableValues(yData)) {
      console.warn('[DynamicChart] No plottable values in array payload', {
        title,
        rawWidget,
        payload,
      })
    }

    if (isBar) {
      return {
        grid: { top: 20, right: 20, bottom: 40, left: 55 },
        xAxis: baseXAxis(xData),
        yAxis: baseYAxis(),
        series: [{ type: 'bar', data: yData, itemStyle: { color: PALETTE[0], borderRadius: [3, 3, 0, 0] } }],
        tooltip: baseTooltip,
      }
    }
    return {
      grid: { top: 20, right: 20, bottom: 40, left: 55 },
      xAxis: baseXAxis(xData),
      yAxis: baseYAxis(),
      series: [{
        type: 'line', data: yData, smooth: true,
        lineStyle: { color: PALETTE[0], width: 2 },
        areaStyle: { color: { type: 'linear', x: 0, y: 0, x2: 0, y2: 1, colorStops: [{ offset: 0, color: 'rgba(108,142,245,0.3)' }, { offset: 1, color: 'rgba(108,142,245,0)' }] } },
        itemStyle: { color: PALETTE[0] },
      }],
      tooltip: baseTooltip,
    }
  }

  return {}
}

function detectTheme(): string | undefined {
  return document.documentElement.getAttribute('data-theme') === 'light' ? undefined : 'dark'
}

function clearInitRaf() {
  if (_initRaf !== null) {
    cancelAnimationFrame(_initRaf)
    _initRaf = null
  }
}

function ensureResizeObserver() {
  if (_ro || !chartEl.value) return
  _ro = new ResizeObserver(() => {
    if (!_chart) {
      void initChart()
      return
    }
    _chart.resize()
  })
  _ro.observe(chartEl.value)
}

function disposeChart() {
  clearInitRaf()
  _ro?.disconnect()
  _ro = null
  _chart?.dispose()
  _chart = null
}

async function initChart(retry = 0) {
  await nextTick()
  if (!chartReady.value || !chartEl.value) return

  const rect = chartEl.value.getBoundingClientRect()
  if ((rect.width === 0 || rect.height === 0) && retry < 10) {
    clearInitRaf()
    _initRaf = requestAnimationFrame(() => {
      void initChart(retry + 1)
    })
    return
  }

  clearInitRaf()

  const theme = detectTheme()
  const prevTheme = _chart?.getDom().getAttribute('data-chart-theme')
  if (_chart && prevTheme !== (theme ?? 'light')) {
    _chart.dispose()
    _chart = null
  }

  if (!_chart) {
    _chart = echarts.init(chartEl.value, theme)
    _chart.getDom().setAttribute('data-chart-theme', theme ?? 'light')
  }
  const opts = buildOption()
  ;(opts as Record<string, unknown>).backgroundColor = 'transparent'
  _chart.setOption(opts, true)

  // ResizeObserver 替代 window.resize：元素获得实际尺寸时立即触发，
  // 解决 ECharts 在 flexbox 布局中初始化时 canvas 宽度为 0 的问题
  _chart.resize()
  ensureResizeObserver()
}

onMounted(async () => {
  if (props.inline && !props.skipSkeleton) {
    await new Promise(r => setTimeout(r, 600))
  }
  chartReady.value = true
  await initChart()
})

watch(
  () => [
    props.artifact.widget,
    props.artifact.component_type,
    props.artifact.title,
    props.artifact.data_payload,
    props.artifact.source_info,
  ],
  async () => {
    if (!chartReady.value) return
    await initChart()
  },
  { deep: true },
)

onUnmounted(() => {
  disposeChart()
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

/* ── 内嵌模式：融入 AI 气泡 ───────────────────────────────────────────── */
.chart-card--inline {
  background: var(--bg-card);
  border-color: var(--border);
  margin: 10px 0;
  box-shadow: none;
}
</style>
