<template>
  <section class="rva-section">
    <div class="section-header">
      <h2 class="section-title">
        <Icon icon="mdi:chart-areaspline-variant" width="16" class="title-icon" />
        实际 vs 国标期望对比
      </h2>
      <span class="gb-badge">
        <Icon icon="mdi:certificate-outline" width="12" />
        GB 双阈值物理基线
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
                 min="2016-04-01" max="2016-05-02" />
        </div>
        <div class="form-item">
          <label class="form-label">结束日期</label>
          <input type="date" v-model="form.endDate" class="form-input"
                 min="2016-04-01" max="2016-05-02" />
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
      <p class="form-hint">建议查询跨度 ≤ 3 天（逐小时数据）· 有效范围：2016-04-01 ~ 2016-05-02</p>
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
            {{ buildingDisplayName }} · {{ currentMetricLabel }} 实际 vs 国标期望
            <span class="chart-range">（{{ form.startDate }} ~ {{ form.endDate }}，逐小时）</span>
          </span>
          <div class="legend-pills">
            <span class="legend-pill actual">
              <span class="pill-dot" style="background:#6c8ef5;"></span> 实际值
            </span>
            <span class="legend-pill rated">
              <span class="pill-dot" style="background:#6c8ef5;opacity:0.4;border:1px dashed #6c8ef5;"></span> 国标期望
            </span>
            <span class="legend-pill dev">
              <span class="pill-dot" style="background:#f59e0b;opacity:0.6;"></span> 偏差 %
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
                <th>国标期望</th>
                <th>偏差</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="(r, i) in anomalyRows.slice(0, 20)" :key="i" class="anomaly-row">
                <td>{{ formatTs(r.timestamp) }}</td>
                <td>
                  <span class="mode-chip" :class="r.hvac_mode.toLowerCase()">{{ r.hvac_mode }}</span>
                </td>
                <td class="num-cell">{{ (r.schedule_factor * 100).toFixed(0) }}%</td>
                <td class="num-cell actual-val">
                  {{ r.actual != null ? r.actual.toFixed(3) : '—' }} {{ currentUnit }}
                </td>
                <td class="num-cell rated-val">{{ r.rated.toFixed(3) }} {{ currentUnit }}</td>
                <td class="num-cell">
                  <span class="dev-badge" :class="devClass(r.deviation_pct)">
                    {{ r.deviation_pct != null ? (r.deviation_pct >= 0 ? '+' : '') + r.deviation_pct.toFixed(1) + '%' : '—' }}
                  </span>
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
      <p class="empty-sub">图表将展示逐小时实际值与国标 GB 期望值的对比，并高亮异常时段</p>
    </div>
  </section>
</template>

<script setup lang="ts">
import { ref, computed, watch, nextTick, onUnmounted } from 'vue'
import { Icon } from '@iconify/vue'
import * as echarts from 'echarts'
import { apiFetch } from '@/api/http'

// ── Props ────────────────────────────────────────────────────────────────────
const props = defineProps<{
  buildings: Array<{ building_type: string; display_name: string }>
  activeBuildingType?: string
}>()

// ── 状态 ─────────────────────────────────────────────────────────────────────
const form = ref({
  buildingType: props.activeBuildingType || 'Office',
  startDate: '2016-04-01',
  endDate: '2016-04-03',
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
  { key: 'electricity', label: '总电耗',   icon: 'mdi:lightning-bolt',   unit: 'kWh', gbRef: 'GB/T 51161 + GB 50034 + GB 50189' },
  { key: 'water',       label: '用水量',   icon: 'mdi:water',            unit: 'm³',  gbRef: 'GB 50015-2019' },
  { key: 'hac_energy',  label: '空调能耗', icon: 'mdi:air-conditioner',  unit: 'kWh', gbRef: 'GB 50189-2015 (COP 3.5/2.5)' },
]

const currentMetric = computed(() => metricOptions.find(m => m.key === form.value.metric)!)
const currentMetricLabel = computed(() => currentMetric.value?.label ?? '')
const currentMetricGbRef = computed(() => currentMetric.value?.gbRef ?? '')

// ── 图表配色（按指标） ────────────────────────────────────────────────────────
const METRIC_COLORS: Record<string, { actual: string; rated: string; dev: string }> = {
  electricity: { actual: '#6c8ef5', rated: 'rgba(108,142,245,0.35)', dev: '#f59e0b' },
  water:       { actual: '#22d3ee', rated: 'rgba(34,211,238,0.35)',  dev: '#f59e0b' },
  hac_energy:  { actual: '#a78bfa', rated: 'rgba(167,139,250,0.35)', dev: '#f59e0b' },
}

// ── 楼宇显示名 ───────────────────────────────────────────────────────────────
const buildingDisplayName = computed(() =>
  props.buildings.find(b => b.building_type === form.value.buildingType)?.display_name
  ?? form.value.buildingType
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

  chartInst = echarts.init(chartEl.value, 'dark')

  const colors = METRIC_COLORS[form.value.metric] ?? METRIC_COLORS.electricity
  const rs     = records.value
  const unit   = currentUnit.value

  // X 轴：取时间戳的 MM-DD HH:mm 部分（本地时间近似）
  const xData = rs.map(r => {
    const d = new Date(r.timestamp)
    // UTC+8 偏移显示
    const local = new Date(d.getTime() + 8 * 3600 * 1000)
    const mo = String(local.getUTCMonth() + 1).padStart(2, '0')
    const da = String(local.getUTCDate()).padStart(2, '0')
    const hh = String(local.getUTCHours()).padStart(2, '0')
    return `${mo}-${da} ${hh}:00`
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

  chartInst.setOption({
    backgroundColor: 'transparent',
    animation: false,
    grid: [
      { top: 36, right: 72, bottom: 80, left: 64 },
    ],
    legend: { show: false },
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'cross', crossStyle: { color: '#3d445c' } },
      backgroundColor: '#101118',
      borderColor: '#1a1c28',
      textStyle: { color: '#dde3f0', fontSize: 12 },
      formatter(params: any[]) {
        const p0 = params.find((p: any) => p.seriesName === '实际值')
        const p1 = params.find((p: any) => p.seriesName === '国标期望')
        const p2 = params.find((p: any) => p.seriesName === '偏差 %')
        const idx = p0?.dataIndex ?? 0
        const r = rs[idx]
        const devStr = p2?.value != null
          ? `<span style="color:${p2.value > 15 ? '#f87171' : '#4ade80'}">${p2.value >= 0 ? '+' : ''}${p2.value}%</span>`
          : '—'
        return [
          `<b>${p0?.axisValueLabel ?? ''}</b>`,
          `<span style="color:${colors.actual}">实际: ${p0?.value ?? '—'} ${unit}</span>`,
          `<span style="color:#9399b8">期望: ${p1?.value ?? '—'} ${unit}</span>`,
          `偏差: ${devStr}`,
          `工况: <b>${r?.hvac_mode ?? '—'}</b> · 负荷率: ${((r?.schedule_factor ?? 0) * 100).toFixed(0)}%`,
        ].join('<br/>')
      },
    },
    xAxis: {
      type: 'category',
      data: xData,
      axisLabel: {
        color: '#6b7a9a', fontSize: 10,
        rotate: xData.length > 48 ? 45 : xData.length > 24 ? 30 : 0,
        interval: Math.max(0, Math.floor(xData.length / 24) - 1),
      },
      axisLine: { lineStyle: { color: '#1a1c28' } },
      axisTick: { show: false },
    },
    yAxis: [
      {
        type: 'value',
        name: unit,
        nameTextStyle: { color: '#3d445c', fontSize: 11 },
        axisLabel: { color: '#6b7a9a', fontSize: 11 },
        splitLine: { lineStyle: { color: '#1a1c28', type: 'dashed' } },
      },
      {
        type: 'value',
        name: '偏差 %',
        nameTextStyle: { color: '#3d445c', fontSize: 11 },
        axisLabel: {
          color: '#6b7a9a', fontSize: 11,
          formatter: (v: number) => `${v}%`,
        },
        splitLine: { show: false },
        axisLine: { lineStyle: { color: '#1a1c28' } },
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
        borderColor: '#1a1c28',
        fillerColor: 'rgba(108,142,245,0.12)',
        handleStyle: { color: '#6c8ef5' },
        textStyle: { color: '#6b7a9a', fontSize: 10 },
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
      // 国标期望线（先渲染，在实际线下方）
      {
        name: '国标期望',
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

onUnmounted(destroyChart)

// ── 工具函数 ─────────────────────────────────────────────────────────────────
function formatTs(iso: string): string {
  if (!iso) return '—'
  const d = new Date(iso)
  const local = new Date(d.getTime() + 8 * 3600 * 1000)
  const mo = String(local.getUTCMonth() + 1).padStart(2, '0')
  const da = String(local.getUTCDate()).padStart(2, '0')
  const hh = String(local.getUTCHours()).padStart(2, '0')
  return `${mo}-${da} ${hh}:00`
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
.rva-section { margin-bottom: 28px; }

.section-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 12px;
}

.section-title {
  font-size: 15px;
  font-weight: 700;
  color: var(--text-secondary);
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
  border-radius: 10px;
  padding: 14px 16px;
  margin-bottom: 12px;
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
  border-radius: 10px;
  padding: 0;
  overflow: hidden;
  margin-bottom: 12px;
}

.summary-item {
  display: flex;
  flex-direction: column;
  gap: 3px;
  padding: 10px 18px;
  border-right: 1px solid var(--border);
}

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
.rva-results { display: flex; flex-direction: column; gap: 12px; }

.chart-container {
  background: var(--bg-panel);
  border: 1px solid var(--border);
  border-radius: 12px;
  overflow: hidden;
  box-shadow: var(--card-shadow);
}

.chart-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 12px 16px 8px;
  border-bottom: 1px solid var(--border);
  flex-wrap: wrap;
  gap: 8px;
}

.chart-title { font-size: 13px; font-weight: 600; color: var(--text-primary); }
.chart-range { font-size: 12px; color: var(--text-muted); margin-left: 5px; font-weight: 400; }
.chart-body  { width: 100%; height: 320px; }

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
  border: 1px solid rgba(248,113,113,0.25);
  border-radius: 10px;
  overflow: hidden;
  box-shadow: var(--card-shadow);
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
  gap: 8px;
  padding: 56px 20px;
  background: var(--bg-panel);
  border: 2px dashed var(--border);
  border-radius: 12px;
  color: var(--text-secondary);
  font-size: 14px;
}
.empty-icon { display: flex; justify-content: center; color: var(--text-muted); margin-bottom: 6px; }
.empty-sub  { font-size: 12px; color: var(--text-muted); }

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

/* ══ Light Theme 适配 ══ */
html[data-theme="light"] .rva-form,
html[data-theme="light"] .chart-container,
html[data-theme="light"] .anomaly-table-section,
html[data-theme="light"] .summary-bar,
html[data-theme="light"] .empty-chart {
  background: #ffffff;
  border-color: #d0e8d8;
}

html[data-theme="light"] .chart-header,
html[data-theme="light"] .data-table th {
  background: #f2f9f4;
  border-color: #d0e8d8;
}

html[data-theme="light"] .table-header {
  background: rgba(248,113,113,0.04);
  border-color: rgba(248,113,113,0.12);
}

html[data-theme="light"] .metric-tab           { color: #3d6b4a; }
html[data-theme="light"] .metric-tab:hover     { background: #e8f5ec; color: #0f2818; }
html[data-theme="light"] .metric-tab.active    { background: rgba(34,197,94,0.1); color: #22c55e; }

html[data-theme="light"] .form-label,
html[data-theme="light"] .form-hint  { color: #6a8c72; }

html[data-theme="light"] .form-select,
html[data-theme="light"] .form-input {
  background: #f2f9f4;
  border-color: #c8dfc8;
  color: #0f2818;
}

html[data-theme="light"] .chart-title { color: #0f2818; }
html[data-theme="light"] .chart-range { color: #6a8c72; }
html[data-theme="light"] .table-title { color: #2d5c3a; }
html[data-theme="light"] .table-count { color: #6a8c72; }
html[data-theme="light"] .data-table td { color: #2d5c3a; }
html[data-theme="light"] .data-table th { color: #6a8c72; }
html[data-theme="light"] .summary-item { border-color: #d0e8d8; }
html[data-theme="light"] .si-label { color: #6a8c72; }
html[data-theme="light"] .si-val   { color: #0f2818; }
html[data-theme="light"] .gb-ref   { color: #7ab89a; }
html[data-theme="light"] .section-title { color: #2d5c3a; }
html[data-theme="light"] .empty-chart { color: #3d6b4a; border-color: #c8dfc8; }
html[data-theme="light"] .empty-sub  { color: #6a8c72; }
html[data-theme="light"] .empty-icon { color: #7ab89a; }
</style>
