<template>
  <section class="rva-section">
    <div class="section-header">
      <h2 class="section-title">
        <Icon icon="mdi:chart-areaspline-variant" width="16" class="title-icon" />
        实际 vs 仿真基线对比
      </h2>
      <span class="gb-badge" :class="expectedSourceBadgeClass">
        <Icon :icon="usingNotebook ? 'mdi:brain' : 'mdi:certificate-outline'" width="12" />
        {{ usingNotebook ? 'Notebook 仿真基线' : 'GB 实时估算（回退）' }}
      </span>
    </div>

    <!-- 查询表单 -->
    <div class="rva-form">
      <div class="form-row">
        <div class="form-item">
          <label class="form-label">楼宇</label>
          <select v-model="form.buildingType" class="form-select">
            <option v-for="b in buildings" :key="b.building_type" :value="b.building_type">
              {{ b.display_name }}
            </option>
          </select>
        </div>
        <div class="form-item">
          <label class="form-label">开始日期</label>
          <input type="date" v-model="form.startDate" class="form-input"
                 :min="dataRangeStore.minDate" :max="dataRangeStore.maxDate" />
        </div>
        <div class="form-item">
          <label class="form-label">结束日期</label>
          <input type="date" v-model="form.endDate" class="form-input"
                 :min="dataRangeStore.minDate" :max="dataRangeStore.maxDate" />
        </div>
        <div class="form-item">
          <label class="form-label">监测指标</label>
          <div class="metric-tabs">
            <button
              v-for="m in metricOptions" :key="m.key"
              class="metric-tab"
              :class="{ active: form.metric === m.key }"
              @click="form.metric = m.key"
            >
              <Icon :icon="m.icon" width="13" />
              {{ m.label }}
            </button>
          </div>
        </div>
        <button class="query-btn" @click="fetchData" :disabled="loading">
          <Icon :icon="loading ? 'mdi:loading' : 'mdi:magnify'" width="14" class="btn-icon"
                :class="{ spin: loading }" />
          {{ loading ? '查询中...' : '查询' }}
        </button>
      </div>
      <p class="form-hint">建议查询跨度 ≤ 3 天（逐小时数据）· 有效范围：{{ dataRangeStore.minDate || '...' }} ~ {{ dataRangeStore.maxDate || '...' }}</p>
    </div>

    <!-- 错误提示 -->
    <div v-if="error" class="error-bar">
      <Icon icon="mdi:alert" width="14" class="bar-icon" /> {{ error }}
    </div>

    <!-- 图表 + 摘要区 -->
    <div v-if="records.length > 0" class="rva-results">

      <!-- 摘要统计条 -->
      <div class="summary-bar">
        <div class="summary-item">
          <span class="si-label"><Icon icon="mdi:clock-outline" width="12" /> 总小时数</span>
          <span class="si-val">{{ summary.total_hours }}</span>
        </div>
        <div class="summary-item" :class="summary.anomaly_hours > 0 ? 'warn' : 'ok'">
          <span class="si-label">
            <Icon :icon="summary.anomaly_hours > 0 ? 'mdi:alert-circle' : 'mdi:check-circle'" width="12" />
            异常小时
          </span>
          <span class="si-val">{{ summary.anomaly_hours }}</span>
        </div>
        <div class="summary-item" :class="summary.anomaly_rate_pct > 10 ? 'warn' : 'ok'">
          <span class="si-label"><Icon icon="mdi:percent" width="12" /> 异常率</span>
          <span class="si-val">{{ summary.anomaly_rate_pct }}%</span>
        </div>
        <div class="summary-item">
          <span class="si-label"><Icon icon="mdi:trending-up" width="12" /> 平均偏差</span>
          <span class="si-val" :class="avgDev > 15 ? 'warn-text' : avgDev > 5 ? 'caution-text' : 'ok-text'">
            {{ avgDev >= 0 ? '+' : '' }}{{ avgDev }}%
          </span>
        </div>
        <div class="summary-item">
          <span class="si-label"><Icon icon="mdi:snowflake" width="12" /> HVAC 主要工况</span>
          <span class="si-val">{{ dominantMode }}</span>
        </div>
        <div class="summary-item" v-if="hvacDiagCount > 0">
          <span class="si-label"><Icon icon="mdi:wrench-outline" width="12" /> 空调根因</span>
          <span class="si-val warn-text">{{ hvacDiagCount }} 条</span>
        </div>
        <div class="summary-spacer"></div>
        <span class="gb-ref">
          <Icon icon="mdi:book-open-outline" width="11" />
          期望值基于 {{ currentMetricGbRef }}
        </span>
      </div>

      <!-- 主图表 -->
      <div class="chart-container">
        <div class="chart-header">
          <span class="chart-title">
            {{ buildingDisplayName }} · {{ currentMetricLabel }} 实际 vs 仿真基线
            <span class="chart-range">（{{ form.startDate }} ~ {{ form.endDate }}，逐小时）</span>
          </span>
          <div class="legend-pills">
            <span class="legend-pill actual">
              <span class="pill-dot" :style="`background:${METRIC_COLORS[form.metric]?.actual ?? '#3b82f6'};`"></span> 实际值
            </span>
            <span class="legend-pill rated">
              <span class="pill-dot" :style="`background:${METRIC_COLORS[form.metric]?.actual ?? '#3b82f6'};opacity:0.35;border:1px dashed ${METRIC_COLORS[form.metric]?.actual ?? '#3b82f6'};`"></span>
              {{ usingNotebook ? 'Notebook 基线' : 'GB 期望' }}
            </span>
            <span class="legend-pill dev">
              <span class="pill-dot" style="background:#f59e0b;opacity:0.7;"></span> 偏差 %
            </span>
          </div>
        </div>
        <div ref="chartEl" class="chart-body"></div>
      </div>

      <!-- 异常明细表（仅在有异常时展示） -->
      <div v-if="anomalyRows.length > 0" class="anomaly-table-section">
        <div class="table-header">
          <span class="table-title">
            <Icon icon="mdi:alert-circle-outline" width="14" class="title-icon" />
            异常时段明细
          </span>
          <span class="table-count">{{ anomalyRows.length }} 条超限记录</span>
        </div>
        <div class="data-table-wrap">
          <table class="data-table">
            <thead>
              <tr>
                <th>时间</th>
                <th>HVAC 工况</th>
                <th>负荷率</th>
                <th>实际值</th>
                <th>基线期望</th>
                <th>偏差</th>
                <th>异常阶段</th>
                <th>空调根因</th>
                <th>供水偏差</th>
                <th>回水偏差</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="(r, i) in anomalyRows.slice(0, 20)" :key="i" class="anomaly-row">
                <td>{{ formatTs(r.timestamp) }}</td>
                <td>
                  <span class="mode-chip" :class="(r.hvac_mode || '').toLowerCase()">{{ r.hvac_mode || '—' }}</span>
                </td>
                <td class="num-cell">{{ r.schedule_factor != null ? (r.schedule_factor * 100).toFixed(0) + '%' : '—' }}</td>
                <td class="num-cell actual-val">
                  {{ r.actual != null ? r.actual.toFixed(3) : '—' }} {{ currentUnit }}
                </td>
                <td class="num-cell rated-val">{{ r.rated != null ? r.rated.toFixed(3) : '—' }} {{ currentUnit }}</td>
                <td class="num-cell">
                  <span class="dev-badge" :class="devClass(r.deviation_pct)">
                    {{ r.deviation_pct != null ? (r.deviation_pct >= 0 ? '+' : '') + r.deviation_pct.toFixed(1) + '%' : '—' }}
                  </span>
                </td>
                <td>
                  <span v-if="r.anomaly_phase" class="phase-chip" :class="r.anomaly_phase">
                    {{ r.anomaly_phase === 'ramp' ? '上升期' : '全量期' }}
                  </span>
                  <span v-else class="phase-chip none">—</span>
                </td>
                <td>
                  <span v-if="r.hvac_diagnosis" class="diag-chip" :class="r.hvac_diagnosis">
                    {{ diagLabel(r.hvac_diagnosis) }}
                  </span>
                  <span v-else>—</span>
                </td>
                <td class="num-cell">
                  <span v-if="r.supply_dev_c != null" :class="Math.abs(r.supply_dev_c) > 1.5 ? 'warn-text' : ''">
                    {{ r.supply_dev_c > 0 ? '+' : '' }}{{ r.supply_dev_c.toFixed(1) }}℃
                  </span>
                  <span v-else>—</span>
                </td>
                <td class="num-cell">
                  <span v-if="r.return_dev_c != null" :class="Math.abs(r.return_dev_c) > 2.0 ? 'warn-text' : ''">
                    {{ r.return_dev_c > 0 ? '+' : '' }}{{ r.return_dev_c.toFixed(1) }}℃
                  </span>
                  <span v-else>—</span>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
        <p v-if="anomalyRows.length > 20" class="table-more">
          仅展示前 20 条，共 {{ anomalyRows.length }} 条超限记录
        </p>
      </div>
    </div>

    <!-- 空状态 -->
    <div class="empty-chart" v-else-if="!loading && !error">
      <div class="empty-icon"><Icon icon="mdi:chart-areaspline-variant" width="44" /></div>
      <p>选择楼宇、日期范围和监测指标后点击查询</p>
      <p class="empty-sub">图表将展示逐小时实际值与仿真基线的对比，并高亮异常时段及根因诊断</p>
    </div>
  </section>
</template>

<script setup lang="ts">
import { ref, computed, watch, nextTick, onMounted, onUnmounted } from 'vue'
import { Icon } from '@iconify/vue'
import * as echarts from '@/utils/echarts'
import { apiFetch } from '@/api/http'
import { useDataRangeStore } from '@/stores/dataRangeStore'

const dataRangeStore = useDataRangeStore()

// ── Props ────────────────────────────────────────────────────────────────────
const props = defineProps<{
  buildings: Array<{ building_type: string; display_name: string }>
  activeBuildingType?: string
}>()

// ── 状态 ─────────────────────────────────────────────────────────────────────
const form = ref({
  buildingType: props.activeBuildingType || 'Office',
  startDate: '',
  endDate: '',
  metric: 'electricity',
})

const loading  = ref(false)
const error    = ref('')
const records  = ref<any[]>([])
const summary  = ref({ total_hours: 0, anomaly_hours: 0, anomaly_rate_pct: 0 })
const currentUnit = ref('kWh')

const chartEl  = ref<HTMLElement | null>(null)
let chartInst: echarts.ECharts | null = null
let ro: ResizeObserver | null = null

// ── 同步父组件选中楼宇 ────────────────────────────────────────────────────────
watch(() => props.activeBuildingType, (v) => {
  if (v) form.value.buildingType = v
})

// ── 指标配置 ─────────────────────────────────────────────────────────────────
const metricOptions = [
  { key: 'electricity', label: '总电耗',   icon: 'mdi:lightning-bolt',   unit: 'kWh', gbRef: 'Notebook 仿真 / GB/T 51161' },
  { key: 'water',       label: '用水量',   icon: 'mdi:water',            unit: 'L',   gbRef: 'Notebook 仿真 / GB 50015-2019' },
  { key: 'hac_energy',  label: '空调能耗', icon: 'mdi:air-conditioner',  unit: 'kWh', gbRef: 'Notebook 仿真 / GB 50189-2015' },
]

const currentMetric = computed(() => metricOptions.find(m => m.key === form.value.metric)!)
const currentMetricLabel = computed(() => currentMetric.value?.label ?? '')
const currentMetricGbRef = computed(() => currentMetric.value?.gbRef ?? '')

// ── 图表配色（按指标）— 统一蓝/绿/紫方案 ────────────────────────────────────
const METRIC_COLORS: Record<string, { actual: string; rated: string; dev: string }> = {
  electricity: { actual: '#3b82f6', rated: 'rgba(59,130,246,0.22)',  dev: '#f59e0b' },
  water:       { actual: '#22c55e', rated: 'rgba(34,197,94,0.22)',   dev: '#f59e0b' },
  hac_energy:  { actual: '#8b5cf6', rated: 'rgba(139,92,246,0.22)',  dev: '#f59e0b' },
}

// ── 楼宇显示名 ───────────────────────────────────────────────────────────────
const buildingDisplayName = computed(() =>
  props.buildings.find(b => b.building_type === form.value.buildingType)?.display_name
  ?? form.value.buildingType
)

// ── 期望值来源检测 ────────────────────────────────────────────────────────────
const usingNotebook = computed(() =>
  records.value.some(r => r.expected_source === 'notebook_baseline')
)
const expectedSourceBadgeClass = computed(() =>
  usingNotebook.value ? 'badge-notebook' : 'badge-gb'
)

// ── 空调根因诊断标签 ──────────────────────────────────────────────────────────
const _DIAG_LABELS: Record<string, string> = {
  'A_low_efficiency': 'A: 主机衰退',
  'B_small_deltaT':   'B: 水力失调',
  'C_unexpected_on':  'C: 非预期开机',
  'other_hvac':       '其他空调故障',
}
function diagLabel(code: string): string {
  return _DIAG_LABELS[code] ?? code
}

const hvacDiagCount = computed(() =>
  records.value.filter(r => r.is_anomaly && r.hvac_diagnosis).length
)

// ── 衍生数据 ─────────────────────────────────────────────────────────────────
const anomalyRows = computed(() => records.value.filter(r => r.is_anomaly))

const avgDev = computed(() => {
  const devs = records.value
    .filter(r => r.deviation_pct != null)
    .map(r => r.deviation_pct as number)
  if (!devs.length) return 0
  return +(devs.reduce((a, b) => a + b, 0) / devs.length).toFixed(1)
})

const dominantMode = computed(() => {
  const counts: Record<string, number> = {}
  records.value.forEach(r => { counts[r.hvac_mode] = (counts[r.hvac_mode] ?? 0) + 1 })
  return Object.entries(counts).sort((a, b) => b[1] - a[1])[0]?.[0] ?? '—'
})

// ── 数据请求 ─────────────────────────────────────────────────────────────────
async function fetchData() {
  const { buildingType, startDate, endDate, metric } = form.value
  if (!buildingType || !startDate || !endDate) return

  loading.value = true
  error.value = ''
  records.value = []
  destroyChart()

  try {
    const url = `/api/buildings/${buildingType}/rated-vs-actual`
      + `?start_date=${startDate}&end_date=${endDate}&metric=${metric}`
    const data = await apiFetch<any>(url)
    records.value = data?.records ?? []
    summary.value = data?.summary ?? { total_hours: 0, anomaly_hours: 0, anomaly_rate_pct: 0 }
    currentUnit.value = data?.unit ?? 'kWh'
    await nextTick()
    renderChart()
  } catch (e: any) {
    error.value = e.message ?? '数据加载失败'
  } finally {
    loading.value = false
  }
}

// ── 图表渲染 ─────────────────────────────────────────────────────────────────
function renderChart() {
  if (!chartEl.value || !records.value.length) return
  destroyChart()

  const isDark = document.documentElement.dataset.theme !== 'light'
  chartInst = echarts.init(chartEl.value, isDark ? 'dark' : undefined)

  const colors = METRIC_COLORS[form.value.metric] ?? METRIC_COLORS.electricity
  const rs     = records.value
  const unit   = currentUnit.value

  // X 轴：energy_data.timestamp 存储的即为使用时刻（本地时间），直接从字符串中提取
  const xData = rs.map(r => {
    const m = r.timestamp.match(/\d{4}-(\d{2})-(\d{2})T(\d{2})/)
    if (m) return `${m[1]}-${m[2]} ${m[3]}:00`
    return r.timestamp.slice(5, 13) + ':00'
  })

  const actualData  = rs.map(r => r.actual  != null ? +r.actual.toFixed(3)  : null)
  const ratedData   = rs.map(r => +r.rated.toFixed(3))
  const devData     = rs.map(r => r.deviation_pct != null ? +r.deviation_pct.toFixed(1) : null)

  // 异常点标记：偏差 > 20% 的点用不同颜色
  const actualStyled = actualData.map((v, i) => ({
    value: v,
    itemStyle: rs[i].is_anomaly
      ? { color: '#f87171', borderColor: '#f87171' }
      : { color: colors.actual, opacity: 0.6 },
  }))

  // 偏差柱状图按严重程度着色
  const devStyled = devData.map(v => {
    if (v == null) return { value: null }
    const c = v > 30 ? 'rgba(248,113,113,0.7)'
            : v > 15 ? 'rgba(251,191,36,0.65)'
            : v > 0  ? 'rgba(74,222,128,0.45)'
            : 'rgba(148,163,184,0.35)'
    return { value: v, itemStyle: { color: c } }
  })

  // markArea：高亮连续异常时段
  const anomalyRanges: Array<[{coord: string[]}, {coord: string[]}]> = []
  let inRange = false
  let rangeStart = ''
  rs.forEach((r, i) => {
    if (r.is_anomaly && !inRange) {
      inRange = true
      rangeStart = xData[i]
    }
    if (!r.is_anomaly && inRange) {
      inRange = false
      anomalyRanges.push([{ coord: [rangeStart, ''] }, { coord: [xData[i - 1], ''] }])
    }
  })
  if (inRange && rs.length > 0) {
    anomalyRanges.push([{ coord: [rangeStart, ''] }, { coord: [xData[rs.length - 1], ''] }])
  }

  const gridLineColor  = isDark ? 'rgba(255,255,255,0.06)' : 'rgba(0,0,0,0.06)'
  const axisLabelColor = isDark ? '#64748b' : '#9ca3af'
  const axisLineColor  = isDark ? 'rgba(255,255,255,0.08)' : 'rgba(0,0,0,0.08)'
  const tooltipBg      = isDark ? '#1e293b' : '#ffffff'
  const tooltipBorder  = isDark ? 'rgba(255,255,255,0.08)' : '#e5e7eb'
  const tooltipText    = isDark ? '#e2e8f0' : '#374151'

  chartInst.setOption({
    backgroundColor: 'transparent',
    animation: false,
    grid: [
      { top: 40, right: 76, bottom: 84, left: 68 },
    ],
    legend: { show: false },
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'cross', crossStyle: { color: axisLineColor } },
      backgroundColor: tooltipBg,
      borderColor: tooltipBorder,
      borderWidth: 1,
      textStyle: { color: tooltipText, fontSize: 12 },
      extraCssText: 'box-shadow: 0 4px 16px rgba(0,0,0,0.12); border-radius: 8px;',
      formatter(params: any[]) {
        const p0 = params.find((p: any) => p.seriesName === '实际值')
        const p1 = params.find((p: any) => p.seriesName?.includes('基线') || p.seriesName?.includes('期望'))
        const p2 = params.find((p: any) => p.seriesName === '偏差 %')
        const idx = p0?.dataIndex ?? 0
        const r = rs[idx]
        const devStr = p2?.value != null
          ? `<span style="color:${p2.value > 15 ? '#f87171' : '#4ade80'}">${p2.value >= 0 ? '+' : ''}${p2.value}%</span>`
          : '—'
        const lines = [
          `<b>${p0?.axisValueLabel ?? ''}</b>`,
          `<span style="color:${colors.actual}">实际: ${p0?.value ?? '—'} ${unit}</span>`,
          `<span style="color:#9399b8">基线: ${p1?.value ?? '—'} ${unit}</span>`,
          `偏差: ${devStr}`,
          `工况: <b>${r?.hvac_mode ?? '—'}</b> · 负荷率: ${((r?.schedule_factor ?? 0) * 100).toFixed(0)}%`,
        ]
        if (r?.anomaly_phase) {
          lines.push(`阶段: <span style="color:#f59e0b">${r.anomaly_phase === 'ramp' ? '上升期' : '全量期'}</span>`)
        }
        if (r?.hvac_diagnosis) {
          lines.push(`根因: <span style="color:#f87171">${diagLabel(r.hvac_diagnosis)}</span>`)
        }
        if (r?.supply_dev_c != null) {
          lines.push(`供水偏差: ${r.supply_dev_c > 0 ? '+' : ''}${r.supply_dev_c.toFixed(1)}℃`)
        }
        if (r?.return_dev_c != null) {
          lines.push(`回水偏差: ${r.return_dev_c > 0 ? '+' : ''}${r.return_dev_c.toFixed(1)}℃`)
        }
        if (r?.expected_source) {
          lines.push(`<span style="color:#6b7a9a;font-size:11px">来源: ${r.expected_source === 'notebook_baseline' ? 'Notebook 基线' : 'GB 实时'}</span>`)
        }
        return lines.join('<br/>')
      },
    },
    xAxis: {
      type: 'category',
      data: xData,
      axisLabel: {
        color: axisLabelColor, fontSize: 10,
        rotate: xData.length > 48 ? 45 : xData.length > 24 ? 30 : 0,
        interval: Math.max(0, Math.floor(xData.length / 24) - 1),
      },
      axisLine: { lineStyle: { color: axisLineColor } },
      axisTick: { show: false },
    },
    yAxis: [
      {
        type: 'value',
        name: unit,
        nameTextStyle: { color: axisLabelColor, fontSize: 11 },
        axisLabel: { color: axisLabelColor, fontSize: 11 },
        splitLine: { lineStyle: { color: gridLineColor, type: 'dashed' } },
        axisLine: { show: false },
        axisTick: { show: false },
      },
      {
        type: 'value',
        name: '偏差 %',
        nameTextStyle: { color: axisLabelColor, fontSize: 11 },
        axisLabel: {
          color: axisLabelColor, fontSize: 11,
          formatter: (v: number) => `${v}%`,
        },
        splitLine: { show: false },
        axisLine: { show: false },
        axisTick: { show: false },
      },
    ],
    dataZoom: [
      {
        type: 'inside',
        start: 0, end: 100,
        zoomOnMouseWheel: true,
      },
      {
        type: 'slider',
        height: 20,
        bottom: 8,
        borderColor: axisLineColor,
        fillerColor: `${colors.actual}22`,
        handleStyle: { color: colors.actual },
        textStyle: { color: axisLabelColor, fontSize: 10 },
      },
    ],
    series: [
      // 偏差柱状图（最底层）
      {
        name: '偏差 %',
        type: 'bar',
        yAxisIndex: 1,
        data: devStyled,
        barMaxWidth: 6,
        z: 1,
        markArea: anomalyRanges.length
          ? {
              silent: true,
              itemStyle: { color: 'rgba(248,113,113,0.06)', borderWidth: 0 },
              data: anomalyRanges,
            }
          : undefined,
      },
      // 基线期望线（先渲染，在实际线下方）
      {
        name: usingNotebook.value ? 'Notebook 基线' : 'GB 期望',
        type: 'line',
        yAxisIndex: 0,
        data: ratedData,
        smooth: true,
        symbol: 'none',
        z: 2,
        lineStyle: { color: colors.actual, width: 1.5, type: 'dashed', opacity: 0.5 },
        areaStyle: {
          color: {
            type: 'linear', x: 0, y: 0, x2: 0, y2: 1,
            colorStops: [
              { offset: 0, color: colors.rated },
              { offset: 1, color: 'rgba(0,0,0,0)' },
            ],
          },
        },
      },
      // 实际值线（最上层）
      {
        name: '实际值',
        type: 'line',
        yAxisIndex: 0,
        data: actualStyled,
        smooth: true,
        symbol: 'circle',
        symbolSize: (v: any, p: any) => (rs[p.dataIndex]?.is_anomaly ? 6 : 0),
        z: 3,
        lineStyle: { color: colors.actual, width: 2 },
        itemStyle: { color: colors.actual },
      },
    ],
  })

  // ResizeObserver 防止 flexbox 下宽度为 0
  ro = new ResizeObserver(() => chartInst?.resize())
  ro.observe(chartEl.value!)
}

function destroyChart() {
  ro?.disconnect()
  ro = null
  chartInst?.dispose()
  chartInst = null
}

onMounted(async () => {
  await dataRangeStore.fetch()
  if (!form.value.startDate) form.value.startDate = dataRangeStore.defaultStart
  if (!form.value.endDate) {
    const s = new Date(dataRangeStore.defaultStart)
    s.setDate(s.getDate() + 2)
    form.value.endDate = s.toISOString().slice(0, 10)
  }
})

onMounted(async () => {
  await dataRangeStore.fetch()
  if (!form.value.startDate) form.value.startDate = dataRangeStore.defaultStart
  if (!form.value.endDate) {
    const start = new Date(dataRangeStore.defaultStart)
    start.setDate(start.getDate() + 2)
    form.value.endDate = start.toISOString().slice(0, 10)
  }
})
onUnmounted(destroyChart)

// ── 工具函数 ─────────────────────────────────────────────────────────────────
function formatTs(iso: string): string {
  if (!iso) return '—'
  // energy_data.timestamp 存储的即为使用时刻（本地时间），直接从字符串中提取
  const m = iso.match(/\d{4}-(\d{2})-(\d{2})T(\d{2})/)
  if (m) return `${m[1]}-${m[2]} ${m[3]}:00`
  return iso.slice(5, 13) + ':00'
}

function devClass(pct: number | null): string {
  if (pct == null) return ''
  if (pct > 30)  return 'dev-high'
  if (pct > 15)  return 'dev-medium'
  if (pct > 0)   return 'dev-low'
  return 'dev-ok'
}
</script>

<style scoped>
.rva-section { margin-bottom: 36px; }

.section-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 14px;
}

.section-title {
  font-size: 15px;
  font-weight: 700;
  color: var(--text-secondary);
  letter-spacing: 0.01em;
}

.gb-badge {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: 11px;
  padding: 3px 10px;
  border-radius: 999px;
  background: var(--accent-glow);
  color: var(--accent);
  border: 1px solid var(--border-accent);
}

/* ── 表单 ── */
.rva-form {
  background: var(--bg-panel);
  border: 1px solid var(--border);
  border-radius: 12px;
  padding: 18px 20px;
  margin-bottom: 16px;
}

.form-row {
  display: flex;
  align-items: flex-end;
  gap: 12px;
  flex-wrap: wrap;
}

.form-item { display: flex; flex-direction: column; gap: 5px; }

.form-label {
  font-size: 11px;
  color: var(--text-muted);
  text-transform: uppercase;
  letter-spacing: 0.04em;
}

.form-select,
.form-input {
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: 6px;
  color: var(--text-primary);
  font-size: 13px;
  padding: 7px 10px;
  min-width: 130px;
  transition: border-color 0.2s;
}
.form-select:focus,
.form-input:focus { outline: none; border-color: var(--accent); }

.form-hint { font-size: 11px; color: var(--text-muted); margin-top: 10px; }

/* ── 指标切换标签 ── */
.metric-tabs {
  display: flex;
  gap: 4px;
  padding: 3px;
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: 8px;
}

.metric-tab {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 5px 12px;
  border: none;
  border-radius: 6px;
  background: transparent;
  color: var(--text-secondary);
  font-size: 12px;
  cursor: pointer;
  transition: all 0.18s;
  white-space: nowrap;
}
.metric-tab:hover { color: var(--text-primary); background: var(--bg-hover); }
.metric-tab.active {
  background: var(--accent-glow);
  color: var(--accent);
  border: 1px solid var(--border-accent);
  font-weight: 600;
}

/* ── 查询按钮 ── */
.query-btn {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  background: var(--accent);
  border: none;
  border-radius: 6px;
  color: #fff;
  font-size: 13px;
  font-weight: 600;
  padding: 8px 20px;
  cursor: pointer;
  transition: opacity 0.2s;
  align-self: flex-end;
  white-space: nowrap;
}
.query-btn:hover { opacity: 0.85; }
.query-btn:disabled { opacity: 0.5; cursor: not-allowed; }

@keyframes spin { to { transform: rotate(360deg); } }
.spin { animation: spin 0.8s linear infinite; }

/* ── 摘要条 ── */
.summary-bar {
  display: flex;
  align-items: center;
  gap: 0;
  background: var(--bg-panel);
  border: 1px solid var(--border);
  border-radius: 12px;
  padding: 0;
  overflow: hidden;
  margin-bottom: 16px;
  box-shadow: 0 1px 3px rgba(0,0,0,0.06);
}

.summary-item {
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: 14px 20px;
  border-right: 1px solid var(--border);
  transition: background 0.18s;
}
.summary-item:hover { background: var(--bg-hover); }

.summary-item.warn .si-val { color: var(--warning); }
.summary-item.ok  .si-val  { color: var(--success);  }

.si-label {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: 10px;
  color: var(--text-muted);
  text-transform: uppercase;
  letter-spacing: 0.06em;
}

.si-val {
  font-size: 18px;
  font-weight: 700;
  color: var(--text-primary);
  line-height: 1;
}

.warn-text    { color: var(--danger);  }
.caution-text { color: var(--warning); }
.ok-text      { color: var(--success); }

.summary-spacer { flex: 1; }

.gb-ref {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: 11px;
  color: var(--text-muted);
  padding: 0 16px;
  white-space: nowrap;
}

/* ── 图表容器 ── */
.rva-results { display: flex; flex-direction: column; gap: 20px; }

.chart-container {
  background: var(--bg-panel);
  border: 1px solid var(--border);
  border-radius: 14px;
  overflow: hidden;
  box-shadow: 0 1px 3px rgba(0,0,0,0.06);
  transition: box-shadow 0.22s, transform 0.22s;
}
.chart-container:hover {
  box-shadow: 0 4px 16px rgba(0,0,0,0.10);
  transform: translateY(-1px);
}

.chart-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 14px 18px 10px;
  border-bottom: 1px solid var(--border);
  flex-wrap: wrap;
  gap: 8px;
}

.chart-title { font-size: 13px; font-weight: 600; color: var(--text-primary); }
.chart-range { font-size: 12px; color: var(--text-muted); margin-left: 5px; font-weight: 400; }
.chart-body  { width: 100%; height: 340px; }

.legend-pills { display: flex; align-items: center; gap: 12px; }

.legend-pill {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  font-size: 11px;
  color: var(--text-muted);
}

.pill-dot {
  display: inline-block;
  width: 10px;
  height: 10px;
  border-radius: 50%;
  flex-shrink: 0;
}

/* ── 异常明细表 ── */
.anomaly-table-section {
  background: var(--bg-panel);
  border: 1px solid rgba(248,113,113,0.22);
  border-radius: 12px;
  overflow: hidden;
  box-shadow: 0 1px 3px rgba(0,0,0,0.06);
  transition: box-shadow 0.22s;
}
.anomaly-table-section:hover {
  box-shadow: 0 4px 16px rgba(0,0,0,0.09);
}

.table-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 10px 16px;
  background: rgba(248,113,113,0.06);
  border-bottom: 1px solid rgba(248,113,113,0.15);
}

.table-title { font-size: 13px; font-weight: 600; color: var(--text-secondary); }
.table-count { font-size: 11px; color: var(--text-muted); }

.data-table-wrap { overflow-x: auto; max-height: 280px; overflow-y: auto; }

.data-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 12px;
}
.data-table th {
  position: sticky;
  top: 0;
  background: var(--bg-card);
  padding: 7px 14px;
  text-align: left;
  font-size: 11px;
  font-weight: 600;
  color: var(--text-muted);
  border-bottom: 1px solid var(--border);
  white-space: nowrap;
}
.data-table td {
  padding: 7px 14px;
  border-bottom: 1px solid var(--border);
  color: var(--text-secondary);
  white-space: nowrap;
}
.data-table tr:last-child td { border-bottom: none; }
.data-table tr.anomaly-row:hover td { background: rgba(248,113,113,0.05); }

.num-cell {
  text-align: right;
  font-variant-numeric: tabular-nums;
}
.actual-val { color: var(--text-primary); font-weight: 600; }
.rated-val  { color: var(--text-muted); }

/* HVAC 工况徽章 */
.mode-chip {
  display: inline-block;
  font-size: 10px;
  padding: 2px 7px;
  border-radius: 4px;
  font-weight: 600;
}
.mode-chip.cooling    { background: rgba(34,211,238,0.15); color: #22d3ee; }
.mode-chip.heating    { background: rgba(251,191,36,0.15);  color: var(--warning); }
.mode-chip.ventilation{ background: rgba(74,222,128,0.15);  color: var(--success); }

/* 偏差徽章 */
.dev-badge {
  display: inline-block;
  font-size: 11px;
  font-weight: 600;
  padding: 2px 8px;
  border-radius: 4px;
}
.dev-high   { background: rgba(248,113,113,0.15); color: var(--danger);  }
.dev-medium { background: rgba(251,191,36,0.15);  color: var(--warning); }
.dev-low    { background: rgba(108,142,245,0.12); color: var(--accent);  }
.dev-ok     { background: rgba(74,222,128,0.12);  color: var(--success); }

.table-more {
  font-size: 11px;
  color: var(--text-muted);
  padding: 6px 16px;
  text-align: center;
}

/* ── 空状态 ── */
.empty-chart {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 10px;
  padding: 72px 40px;
  background: var(--bg-panel);
  border: 2px dashed var(--border);
  border-radius: 14px;
  color: var(--text-secondary);
  font-size: 14px;
  text-align: center;
}
.empty-icon {
  display: flex;
  justify-content: center;
  align-items: center;
  width: 72px;
  height: 72px;
  border-radius: 50%;
  background: var(--accent-glow);
  color: var(--accent);
  margin-bottom: 8px;
}
.empty-sub  { font-size: 12px; color: var(--text-muted); max-width: 340px; line-height: 1.6; }

/* ── 异常阶段徽章 ── */
.phase-chip {
  display: inline-block;
  font-size: 10px;
  padding: 2px 7px;
  border-radius: 4px;
  font-weight: 600;
}
.phase-chip.ramp  { background: rgba(251,191,36,0.15); color: var(--warning); }
.phase-chip.full  { background: rgba(248,113,113,0.15); color: var(--danger); }
.phase-chip.none  { color: var(--text-muted); }

/* ── 空调根因徽章 ── */
.diag-chip {
  display: inline-block;
  font-size: 10px;
  padding: 2px 7px;
  border-radius: 4px;
  font-weight: 600;
  white-space: nowrap;
}
.diag-chip.A_low_efficiency { background: rgba(248,113,113,0.12); color: #f87171; }
.diag-chip.B_small_deltaT   { background: rgba(167,139,250,0.12); color: #a78bfa; }
.diag-chip.C_unexpected_on  { background: rgba(251,191,36,0.12);  color: var(--warning); }
.diag-chip.other_hvac       { background: rgba(148,163,184,0.12); color: var(--text-muted); }

/* ── 来源徽章变体 ── */
.badge-notebook {
  background: rgba(167,139,250,0.12);
  color: #a78bfa;
  border-color: rgba(167,139,250,0.3);
}
.badge-gb {
  background: var(--accent-glow);
  color: var(--accent);
  border-color: var(--border-accent);
}

/* ── 错误 ── */
.error-bar {
  background: rgba(248,113,113,0.08);
  border: 1px solid rgba(248,113,113,0.25);
  border-radius: 8px;
  padding: 10px 16px;
  color: var(--danger);
  font-size: 13px;
  margin-bottom: 12px;
  display: flex;
  align-items: center;
  gap: 8px;
}

.title-icon { vertical-align: middle; margin-right: 4px; }
.bar-icon   { vertical-align: middle; flex-shrink: 0; }
.btn-icon   { vertical-align: middle; }

/* ══ Light Theme 适配 — SaaS Dashboard 风格 ══ */
html[data-theme="light"] .rva-form,
html[data-theme="light"] .chart-container,
html[data-theme="light"] .anomaly-table-section,
html[data-theme="light"] .summary-bar,
html[data-theme="light"] .empty-chart {
  background: #ffffff;
  border-color: #e5eae7;
}

html[data-theme="light"] .chart-header,
html[data-theme="light"] .data-table th {
  background: #f8faf9;
  border-color: #e5eae7;
}

html[data-theme="light"] .table-header {
  background: rgba(248,113,113,0.04);
  border-color: rgba(248,113,113,0.12);
}

html[data-theme="light"] .metric-tab           { color: #374151; }
html[data-theme="light"] .metric-tab:hover     { background: #f3f4f6; color: #111827; }
html[data-theme="light"] .metric-tab.active    { background: rgba(59,130,246,0.08); color: #3b82f6; border-color: rgba(59,130,246,0.25); }

html[data-theme="light"] .form-label,
html[data-theme="light"] .form-hint  { color: #6b7280; }

html[data-theme="light"] .form-select,
html[data-theme="light"] .form-input {
  background: #f9fafb;
  border-color: #e5e7eb;
  color: #111827;
}

html[data-theme="light"] .chart-title { color: #111827; }
html[data-theme="light"] .chart-range { color: #9ca3af; }
html[data-theme="light"] .table-title { color: #374151; }
html[data-theme="light"] .table-count { color: #9ca3af; }
html[data-theme="light"] .data-table td { color: #374151; }
html[data-theme="light"] .data-table th { color: #9ca3af; }
html[data-theme="light"] .summary-item { border-color: #e5eae7; }
html[data-theme="light"] .summary-item:hover { background: #f8faf9; }
html[data-theme="light"] .si-label { color: #9ca3af; }
html[data-theme="light"] .si-val   { color: #111827; }
html[data-theme="light"] .gb-ref   { color: #9ca3af; }
html[data-theme="light"] .section-title { color: #374151; }
html[data-theme="light"] .empty-chart { color: #374151; border-color: #d1d5db; }
html[data-theme="light"] .empty-sub  { color: #9ca3af; }
html[data-theme="light"] .empty-icon { background: rgba(59,130,246,0.08); color: #3b82f6; }
html[data-theme="light"] .chart-container:hover,
html[data-theme="light"] .summary-bar {
  box-shadow: 0 4px 16px rgba(0,0,0,0.07);
}
</style>
