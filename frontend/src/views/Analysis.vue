<template>
  <div class="analysis">
    <header class="page-header">
      <h1>📊 能源透视</h1>
      <span class="subtitle">能耗趋势 · 报表导出 · 数据血缘</span>
    </header>

    <!-- AI 引导 -->
    <div class="hint-card">
      <div>
        <p class="hint-title">💬 在右侧控制台输入分析指令，AI 将自动生成图表</p>
        <p class="hint-examples">例如：「对比教学楼和办公楼 2016 年 4 月每天的用电量」</p>
      </div>
    </div>

    <!-- ── 能耗趋势查询 ── -->
    <section class="section">
      <h2 class="section-title">📈 能耗趋势查询</h2>

      <!-- 查询表单 -->
      <div class="query-form">
        <div class="form-row">
          <div class="form-item">
            <label class="form-label">楼宇</label>
            <select v-model="trendForm.buildingType" class="form-select">
              <option
                v-for="b in buildingStore.buildings"
                :key="b.building_type"
                :value="b.building_type"
              >
                {{ b.icon }} {{ b.display_name }}
              </option>
            </select>
          </div>
          <div class="form-item">
            <label class="form-label">开始日期</label>
            <input
              type="date" v-model="trendForm.startDate"
              class="form-input"
              min="2016-04-01" max="2016-05-02"
            />
          </div>
          <div class="form-item">
            <label class="form-label">结束日期</label>
            <input
              type="date" v-model="trendForm.endDate"
              class="form-input"
              min="2016-04-01" max="2016-05-02"
            />
          </div>
          <div class="form-item form-item-check">
            <label class="form-label">含用水</label>
            <input type="checkbox" v-model="trendForm.includeWater" class="form-check" />
          </div>
          <button class="query-btn" @click="fetchTrend" :disabled="trendLoading">
            {{ trendLoading ? '查询中...' : '🔍 查询' }}
          </button>
        </div>
        <p class="form-hint">数据库有效范围：2016-04-01 ~ 2016-05-02</p>
      </div>

      <!-- 加载 / 错误 -->
      <div v-if="trendLoading" class="loading-bar">正在加载能耗数据...</div>
      <div v-if="trendError" class="error-bar">⚠️ {{ trendError }}</div>

      <!-- 图表区域 -->
      <div class="chart-container" v-if="trendData.length > 0">
        <div class="chart-header">
          <span class="chart-title">
            {{ trendBuildingName }} · 能耗趋势
            <span class="chart-range">({{ trendForm.startDate }} ~ {{ trendForm.endDate }})</span>
          </span>
          <span class="chart-source">数据来源：daily_energy_summary 物化视图</span>
        </div>
        <div ref="chartEl" class="chart-body"></div>
        <!-- 数据摘要 -->
        <div class="chart-summary">
          <div class="summary-item">
            <span class="summary-label">总用电</span>
            <span class="summary-val">{{ totalElectricity.toFixed(1) }} kWh</span>
          </div>
          <div class="summary-item" v-if="trendForm.includeWater">
            <span class="summary-label">总用水</span>
            <span class="summary-val">{{ totalWater.toFixed(1) }} m³</span>
          </div>
          <div class="summary-item">
            <span class="summary-label">平均气温</span>
            <span class="summary-val">{{ avgTemp.toFixed(1) }} °C</span>
          </div>
          <div class="summary-item">
            <span class="summary-label">日均用电</span>
            <span class="summary-val">{{ (totalElectricity / trendData.length).toFixed(1) }} kWh</span>
          </div>
          <div class="summary-item">
            <span class="summary-label">数据记录</span>
            <span class="summary-val">{{ trendData.length }} 天</span>
          </div>
        </div>
      </div>

      <!-- 未查询时的空状态 -->
      <div class="empty-chart" v-else-if="!trendLoading && !trendError">
        <div class="empty-icon">📈</div>
        <p>选择楼宇和日期范围后点击查询</p>
        <p class="empty-sub">将显示该楼宇的每日能耗趋势折线图</p>
      </div>
    </section>

    <!-- ── 报表导出 ── -->
    <section class="section">
      <h2 class="section-title">📥 报表导出</h2>

      <div class="export-form">
        <div class="form-row">
          <div class="form-item">
            <label class="form-label">楼宇</label>
            <select v-model="exportForm.buildingType" class="form-select">
              <option
                v-for="b in buildingStore.buildings"
                :key="b.building_type"
                :value="b.building_type"
              >
                {{ b.icon }} {{ b.display_name }}
              </option>
            </select>
          </div>
          <div class="form-item">
            <label class="form-label">开始日期</label>
            <input
              type="date" v-model="exportForm.startDate"
              class="form-input"
              min="2016-04-01" max="2016-05-02"
            />
          </div>
          <div class="form-item">
            <label class="form-label">结束日期</label>
            <input
              type="date" v-model="exportForm.endDate"
              class="form-input"
              min="2016-04-01" max="2016-05-02"
            />
          </div>
          <div class="form-item">
            <label class="form-label">报表类型</label>
            <select v-model="exportForm.reportType" class="form-select">
              <option value="daily_summary">每日汇总</option>
              <option value="energy_detail">原始明细</option>
            </select>
          </div>
          <button class="download-btn" @click="triggerDownload">
            ⬇️ 下载 CSV
          </button>
        </div>

        <div class="export-preview">
          <span class="export-label">预览下载 URL：</span>
          <code class="export-url">{{ exportUrl }}</code>
        </div>
        <p class="form-hint">
          每日汇总：来自 daily_energy_summary 物化视图（日期/用电/温度/人员）&nbsp;|&nbsp;
          原始明细：来自 energy_data 时序表（逐小时读数）
        </p>
      </div>
    </section>

    <!-- ── 数据血缘视图 ── -->
    <section class="section">
      <h2 class="section-title">🔗 数据流向（血缘视图）</h2>
      <div class="lineage-flow">
        <div class="lineage-node source">
          <div class="node-icon">📂</div>
          <div class="node-label">CSV 原始数据</div>
          <div class="node-sub">传感器读数</div>
        </div>
        <div class="lineage-arrow">→</div>
        <div class="lineage-node table">
          <div class="node-icon">🗄️</div>
          <div class="node-label">energy_data</div>
          <div class="node-sub">时序表 · PostgreSQL</div>
        </div>
        <div class="lineage-arrow">→</div>
        <div class="lineage-node view">
          <div class="node-icon">⚡</div>
          <div class="node-label">daily_energy_summary</div>
          <div class="node-sub">物化视图 · 预聚合</div>
        </div>
        <div class="lineage-arrow">→</div>
        <div class="lineage-node api">
          <div class="node-icon">🔌</div>
          <div class="node-label">REST API</div>
          <div class="node-sub">/api/buildings/{type}/energy</div>
        </div>
        <div class="lineage-arrow">→</div>
        <div class="lineage-node ai">
          <div class="node-icon">🤖</div>
          <div class="node-label">AI 分析结论</div>
          <div class="node-sub">LangGraph Agent</div>
        </div>
      </div>
    </section>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, watch, nextTick, onMounted } from 'vue'
import * as echarts from 'echarts'
import { apiFetch } from '@/api/http'
import { useBuildingStore } from '@/stores/buildingStore'

const buildingStore = useBuildingStore()

// ── 趋势查询表单 ──────────────────────────────────
const trendForm = ref({
  buildingType: 'Office',
  startDate: '2016-04-01',
  endDate: '2016-05-02',
  includeWater: true,
})

const trendLoading = ref(false)
const trendError = ref('')
const trendData = ref<any[]>([])
const trendBuildingName = ref('')

// ── 报表导出表单 ──────────────────────────────────
const exportForm = ref({
  buildingType: 'Office',
  startDate: '2016-04-01',
  endDate: '2016-05-02',
  reportType: 'daily_summary',
})

// ── 图表 DOM ──────────────────────────────────────
const chartEl = ref<HTMLElement | null>(null)
let chartInstance: echarts.ECharts | null = null

// ── 计算属性 ──────────────────────────────────────
const totalElectricity = computed(() =>
  trendData.value.reduce((s: number, r: any) => s + (r.total_electricity_kwh ?? 0), 0),
)

const totalWater = computed(() =>
  trendData.value.reduce((s: number, r: any) => s + (r.total_water_m3 ?? 0), 0),
)

const avgTemp = computed(() => {
  const valid = trendData.value.filter((r: any) => r.avg_ambient_temp != null)
  if (!valid.length) return 0
  return valid.reduce((s: number, r: any) => s + r.avg_ambient_temp, 0) / valid.length
})

const exportUrl = computed(() => {
  const f = exportForm.value
  const API_BASE = (import.meta.env.VITE_API_BASE as string | undefined) ?? ''
  return `${API_BASE}/api/reports/export?building_type=${f.buildingType}&start_date=${f.startDate}&end_date=${f.endDate}&report_type=${f.reportType}`
})

// ── 同步 trendForm 楼宇到 buildingStore ─────────
watch(() => buildingStore.buildings, (list) => {
  if (list.length > 0) {
    trendForm.value.buildingType = list[0].building_type
    exportForm.value.buildingType = list[0].building_type
  }
}, { immediate: true })

// ── 能耗趋势查询 ─────────────────────────────────
async function fetchTrend() {
  const { buildingType, startDate, endDate, includeWater } = trendForm.value
  if (!buildingType || !startDate || !endDate) return

  trendLoading.value = true
  trendError.value = ''
  trendData.value = []
  destroyChart()

  try {
    const url = `/api/buildings/${buildingType}/energy?start_date=${startDate}&end_date=${endDate}&include_water=${includeWater}`
    const data = await apiFetch<any>(url)
    trendData.value = data?.records ?? []
    trendBuildingName.value = buildingStore.buildings.find(b => b.building_type === buildingType)?.display_name ?? buildingType
    await nextTick()
    renderChart()
  } catch (e: any) {
    trendError.value = e.message
  } finally {
    trendLoading.value = false
  }
}

// ── ECharts 渲染 ─────────────────────────────────
function renderChart() {
  if (!chartEl.value || trendData.value.length === 0) return

  destroyChart()
  chartInstance = echarts.init(chartEl.value, 'dark')

  // day 字段为 ISO 串 "2016-04-02T00:00:00+00:00"，截取 MM-DD 部分
  const days = trendData.value.map((r: any) => (r.day ?? '').slice(5, 10))
  const elec = trendData.value.map((r: any) => +(r.total_electricity_kwh ?? 0).toFixed(2))
  const temp = trendData.value.map((r: any) => +(r.avg_ambient_temp ?? 0).toFixed(1))
  const water = trendForm.value.includeWater
    ? trendData.value.map((r: any) => +(r.total_water_m3 ?? 0).toFixed(2))
    : []

  const series: echarts.SeriesOption[] = [
    {
      name: '日用电 (kWh)',
      type: 'line',
      yAxisIndex: 0,
      data: elec,
      smooth: true,
      lineStyle: { color: '#6c8ef5', width: 2 },
      areaStyle: {
        color: {
          type: 'linear', x: 0, y: 0, x2: 0, y2: 1,
          colorStops: [
            { offset: 0, color: 'rgba(108,142,245,0.35)' },
            { offset: 1, color: 'rgba(108,142,245,0.02)' },
          ],
        },
      },
      itemStyle: { color: '#6c8ef5' },
    },
    {
      name: '平均气温 (°C)',
      type: 'line',
      yAxisIndex: 1,
      data: temp,
      smooth: true,
      lineStyle: { color: '#fbbf24', width: 2, type: 'dashed' },
      itemStyle: { color: '#fbbf24' },
      symbol: 'none',
    },
  ]

  if (trendForm.value.includeWater && water.length) {
    series.push({
      name: '日用水 (m³)',
      type: 'bar',
      yAxisIndex: 0,
      data: water,
      barMaxWidth: 14,
      itemStyle: { color: 'rgba(34,211,238,0.55)', borderRadius: [3, 3, 0, 0] },
    })
  }

  chartInstance.setOption({
    backgroundColor: 'transparent',
    grid: { top: 36, right: 60, bottom: 40, left: 64 },
    legend: {
      top: 4,
      textStyle: { color: '#9399b8', fontSize: 12 },
    },
    tooltip: {
      trigger: 'axis',
      backgroundColor: '#22253a',
      borderColor: '#2e3148',
      textStyle: { color: '#e8eaf6', fontSize: 12 },
    },
    xAxis: {
      type: 'category',
      data: days,
      axisLabel: { color: '#9399b8', fontSize: 11, rotate: days.length > 20 ? 30 : 0 },
      axisLine: { lineStyle: { color: '#2e3148' } },
    },
    yAxis: [
      {
        type: 'value',
        name: 'kWh / m³',
        nameTextStyle: { color: '#555a7a', fontSize: 11 },
        axisLabel: { color: '#9399b8', fontSize: 11 },
        splitLine: { lineStyle: { color: '#2e3148', type: 'dashed' } },
      },
      {
        type: 'value',
        name: '°C',
        nameTextStyle: { color: '#555a7a', fontSize: 11 },
        axisLabel: { color: '#9399b8', fontSize: 11 },
        splitLine: { show: false },
      },
    ],
    series,
  })

  window.addEventListener('resize', handleResize)
}

function destroyChart() {
  if (chartInstance) {
    window.removeEventListener('resize', handleResize)
    chartInstance.dispose()
    chartInstance = null
  }
}

function handleResize() {
  chartInstance?.resize()
}

// ── 报表下载 ─────────────────────────────────────
function triggerDownload() {
  const a = document.createElement('a')
  a.href = exportUrl.value
  a.download = `${exportForm.value.buildingType}_${exportForm.value.reportType}_${exportForm.value.startDate}_${exportForm.value.endDate}.csv`
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
}

// ── 生命周期 ──────────────────────────────────────
onMounted(() => {
  buildingStore.fetchBuildings()
})
</script>

<style scoped>
.analysis { padding: 24px; }
.page-header { margin-bottom: 24px; }
.page-header h1 { font-size: 22px; font-weight: 700; margin-bottom: 4px; }
.subtitle { color: var(--text-secondary); font-size: 13px; }

.hint-card {
  background: var(--accent-glow);
  border: 1px solid rgba(108,142,245,0.3);
  border-radius: 10px;
  padding: 14px 18px;
  margin-bottom: 24px;
}
.hint-title    { font-weight: 600; font-size: 14px; color: var(--accent); margin-bottom: 4px; }
.hint-examples { font-size: 12px; color: var(--text-secondary); }

.section { margin-bottom: 32px; }
.section-title { font-size: 15px; font-weight: 700; margin-bottom: 14px; color: var(--text-secondary); }

/* ── 查询 / 导出表单 ── */
.query-form,
.export-form {
  background: var(--bg-panel);
  border: 1px solid var(--border);
  border-radius: 10px;
  padding: 16px 18px;
}

.form-row {
  display: flex;
  align-items: flex-end;
  gap: 12px;
  flex-wrap: wrap;
}

.form-item { display: flex; flex-direction: column; gap: 5px; }
.form-item-check { flex-direction: row; align-items: center; gap: 8px; }

.form-label { font-size: 11px; color: var(--text-muted); text-transform: uppercase; letter-spacing: 0.04em; }

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

.form-check {
  width: 16px;
  height: 16px;
  cursor: pointer;
  accent-color: var(--accent);
}

.form-hint {
  font-size: 11px;
  color: var(--text-muted);
  margin-top: 10px;
  line-height: 1.7;
}

.query-btn {
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

.download-btn {
  background: var(--success);
  border: none;
  border-radius: 6px;
  color: #000;
  font-size: 13px;
  font-weight: 600;
  padding: 8px 20px;
  cursor: pointer;
  transition: opacity 0.2s;
  align-self: flex-end;
  white-space: nowrap;
}
.download-btn:hover { opacity: 0.85; }

/* 导出 URL 预览 */
.export-preview {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  margin-top: 12px;
  flex-wrap: wrap;
}
.export-label { font-size: 12px; color: var(--text-muted); white-space: nowrap; padding-top: 2px; }
.export-url {
  font-family: monospace;
  font-size: 11px;
  color: var(--accent);
  background: rgba(108,142,245,0.08);
  border: 1px solid rgba(108,142,245,0.2);
  border-radius: 4px;
  padding: 3px 8px;
  word-break: break-all;
  flex: 1;
}

/* ── 加载 / 错误 ── */
.loading-bar {
  background: rgba(108,142,245,0.08);
  border: 1px solid rgba(108,142,245,0.25);
  border-radius: 8px;
  padding: 10px 16px;
  color: var(--accent);
  font-size: 13px;
  margin: 12px 0 0;
}
.error-bar {
  background: rgba(248,113,113,0.08);
  border: 1px solid rgba(248,113,113,0.25);
  border-radius: 8px;
  padding: 10px 16px;
  color: var(--danger);
  font-size: 13px;
  margin: 12px 0 0;
}

/* ── 图表卡片 ── */
.chart-container {
  background: var(--bg-panel);
  border: 1px solid var(--border);
  border-radius: 10px;
  overflow: hidden;
  margin-top: 12px;
}

.chart-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 12px 16px 8px;
  border-bottom: 1px solid var(--border);
}
.chart-title { font-size: 13px; font-weight: 600; color: var(--text-primary); }
.chart-range { font-size: 12px; color: var(--text-muted); margin-left: 6px; font-weight: 400; }
.chart-source { font-size: 11px; color: var(--text-muted); }

.chart-body { width: 100%; height: 260px; }

.chart-summary {
  display: flex;
  gap: 0;
  border-top: 1px solid var(--border);
  overflow-x: auto;
}
.summary-item {
  flex: 1;
  min-width: 100px;
  display: flex;
  flex-direction: column;
  align-items: center;
  padding: 10px 12px;
  border-right: 1px solid var(--border);
  gap: 3px;
}
.summary-item:last-child { border-right: none; }
.summary-label { font-size: 11px; color: var(--text-muted); }
.summary-val   { font-size: 15px; font-weight: 700; color: var(--accent); }

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
  margin-top: 12px;
}
.empty-icon { font-size: 44px; margin-bottom: 6px; }
.empty-sub  { font-size: 12px; color: var(--text-muted); }

/* ── 数据血缘 ── */
.lineage-flow {
  display: flex;
  align-items: center;
  background: var(--bg-panel);
  border: 1px solid var(--border);
  border-radius: 10px;
  padding: 20px;
  overflow-x: auto;
  gap: 0;
}

.lineage-node {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 6px;
  padding: 14px 18px;
  border-radius: 8px;
  min-width: 120px;
  text-align: center;
  flex-shrink: 0;
}
.lineage-node.source { background: rgba(74,222,128,0.08);  border: 1px solid rgba(74,222,128,0.3); }
.lineage-node.table  { background: rgba(108,142,245,0.08); border: 1px solid rgba(108,142,245,0.3); }
.lineage-node.view   { background: rgba(251,191,36,0.08);  border: 1px solid rgba(251,191,36,0.3); }
.lineage-node.api    { background: rgba(34,211,238,0.08);  border: 1px solid rgba(34,211,238,0.3); }
.lineage-node.ai     { background: rgba(167,139,250,0.08); border: 1px solid rgba(167,139,250,0.3); }

.node-icon  { font-size: 22px; }
.node-label { font-size: 12px; font-weight: 700; color: var(--text-primary); }
.node-sub   { font-size: 10px; color: var(--text-muted); }

.lineage-arrow {
  font-size: 18px;
  color: var(--text-muted);
  padding: 0 10px;
  flex-shrink: 0;
}
</style>
