<template>
  <div class="query-stats">
    <!-- 筛选面板 -->
    <div class="filter-panel">
      <!-- 第一行：筛选条件 -->
      <div class="filter-row">
        <div class="filter-item">
          <label class="filter-label">
            <Icon icon="mdi:office-building-outline" width="13" class="label-icon" />
            楼宇
          </label>
          <div class="input-wrap">
            <Icon icon="mdi:chevron-down" width="14" class="select-arrow" />
            <select v-model="selectedBuilding" class="filter-select">
              <option v-for="b in buildingOptions" :key="b.key" :value="b.key">{{ b.label }}</option>
            </select>
          </div>
        </div>
        <div class="filter-item">
          <label class="filter-label">
            <Icon icon="mdi:calendar-start" width="13" class="label-icon" />
            开始日期
          </label>
          <input type="date" v-model="startDate" class="filter-input" min="2016-04-01" max="2016-05-02" />
        </div>
        <div class="filter-item">
          <label class="filter-label">
            <Icon icon="mdi:calendar-end" width="13" class="label-icon" />
            结束日期
          </label>
          <input type="date" v-model="endDate" class="filter-input" min="2016-04-01" max="2016-05-02" />
        </div>
        <div class="filter-item">
          <label class="filter-label">
            <Icon icon="mdi:chart-box-outline" width="13" class="label-icon" />
            图表类型
          </label>
          <div class="input-wrap">
            <Icon icon="mdi:chevron-down" width="14" class="select-arrow" />
            <select v-model="chartType" class="filter-select">
              <option value="line">折线图</option>
              <option value="bar">柱状图</option>
              <option value="mixed">混合（折线+柱状）</option>
            </select>
          </div>
        </div>
        <button class="query-btn" @click="handleQuery" :disabled="loading" aria-label="查询数据">
          <Icon :icon="loading ? 'mdi:loading' : 'mdi:magnify'" width="16" :class="{ spin: loading }" />
          {{ loading ? '查询中...' : '查询' }}
        </button>
      </div>

      <!-- 分隔线 -->
      <div class="filter-divider"></div>

      <!-- 第二行：监测参数 + 视图切换 -->
      <div class="filter-bottom">
        <div class="params-row">
          <span class="params-label">
            <Icon icon="mdi:tune-variant" width="14" />
            监测参数
          </span>
          <label v-for="p in allParams" :key="p.key" class="param-checkbox" :class="{ checked: p.checked }">
            <input type="checkbox" v-model="p.checked" />
            <span class="check-box">
              <Icon v-if="p.checked" icon="mdi:check" width="11" class="check-icon" />
            </span>
            {{ p.label }}
          </label>
        </div>

        <!-- 数据展示 / 统计分析 切换 -->
        <div class="view-toggle" ref="toggleRef">
          <div class="toggle-slider" :style="sliderStyle"></div>
          <button
            class="toggle-btn"
            ref="btnDataRef"
            :class="{ active: viewMode === 'data' }"
            @click="viewMode = 'data'"
            aria-label="数据展示视图"
          >
            <Icon icon="mdi:table" width="14" />
            数据展示
          </button>
          <button
            class="toggle-btn"
            ref="btnAnalysisRef"
            :class="{ active: viewMode === 'analysis' }"
            @click="viewMode = 'analysis'"
            aria-label="统计分析视图"
          >
            <Icon icon="mdi:chart-line" width="14" />
            统计分析
          </button>
        </div>
      </div>
    </div>

    <!-- 数据展示：表格 -->
    <div class="chart-card" v-if="queryResult && viewMode === 'data'">
      <div class="chart-card-header">
        <div class="chart-card-title">
          <Icon icon="mdi:table" width="18" class="chart-title-icon" />
          <span>{{ buildingLabel }} 能耗数据</span>
          <span class="chart-date-range">{{ startDate }} ~ {{ endDate }}</span>
        </div>
        <div class="chart-card-actions">
          <button class="card-action-btn" title="刷新数据" @click="handleQuery" aria-label="刷新数据">
            <Icon icon="mdi:refresh" width="16" />
          </button>
        </div>
      </div>
      <div class="data-table-wrap">
        <table class="data-table">
          <thead>
            <tr>
              <th class="sticky-col">日期</th>
              <th v-for="p in getCheckedParams()" :key="p.key">{{ p.label }}</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="(row, idx) in queryResult.records" :key="idx">
              <td class="sticky-col date-cell">{{ row.day?.slice(0, 10) }}</td>
              <td v-for="p in getCheckedParams()" :key="p.key" class="num-cell">
                {{ formatTableVal(row[PARAM_FIELD_MAP[p.key] || p.key]) }}
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

    <!-- 统计分析：图表 -->
    <div class="chart-card" v-if="queryResult && viewMode === 'analysis'">
      <div class="chart-card-header">
        <div class="chart-card-title">
          <Icon icon="mdi:chart-areaspline" width="18" class="chart-title-icon" />
          <span>{{ buildingLabel }} 能耗趋势</span>
          <span class="chart-date-range">{{ startDate }} ~ {{ endDate }}</span>
        </div>
        <div class="chart-card-actions">
          <button class="card-action-btn" title="刷新数据" @click="handleQuery" aria-label="刷新数据">
            <Icon icon="mdi:refresh" width="16" />
          </button>
        </div>
      </div>
      <div class="chart-container" ref="chartRef"></div>
    </div>

    <!-- 空状态 -->
    <div class="content-placeholder" v-if="!queryResult && !loading">
      <div class="empty-state">
        <div class="empty-icon-wrap">
          <Icon icon="mdi:chart-bar" width="40" />
        </div>
        <p class="empty-title">暂无数据</p>
        <p class="empty-desc">选择筛选条件后点击查询按钮</p>
      </div>
    </div>

    <!-- 加载骨架：数据展示（表格） -->
    <div class="chart-card skeleton-card" v-if="loading && viewMode === 'data'">
      <div class="skeleton-header">
        <div class="skeleton-line skeleton-title-line"></div>
        <div class="skeleton-line skeleton-badge-line"></div>
      </div>
      <div class="skeleton-table">
        <div class="skeleton-table-head">
          <div class="skeleton-line skeleton-th" v-for="i in 4" :key="i"></div>
        </div>
        <div class="skeleton-table-row" v-for="i in 8" :key="i">
          <div class="skeleton-line skeleton-td" v-for="j in 4" :key="j" :style="{ width: j === 1 ? '90px' : `${50 + Math.random() * 40}px` }"></div>
        </div>
      </div>
    </div>

    <!-- 加载骨架：统计分析（图表） -->
    <div class="chart-card skeleton-card" v-if="loading && viewMode === 'analysis'">
      <div class="skeleton-header">
        <div class="skeleton-line skeleton-title-line"></div>
        <div class="skeleton-line skeleton-badge-line"></div>
      </div>
      <div class="skeleton-chart">
        <div class="skeleton-bar" v-for="i in 12" :key="i" :style="{ height: `${20 + Math.random() * 60}%` }"></div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, computed, watch, onMounted, onUnmounted, nextTick } from 'vue'
import { Icon } from '@iconify/vue'
import { apiFetch } from '@/api/http'
import * as echarts from 'echarts'

// ── 筛选状态 ──
const buildingOptions = [
  { key: 'Education', label: '教学楼' },
  { key: 'Office', label: '办公楼' },
  { key: 'Public services', label: '公共楼' },
]
const selectedBuilding = ref('Office')
const startDate = ref('2016-04-01')
const endDate = ref('2016-05-02')
const chartType = ref('mixed')
const loading = ref(false)
const queryResult = ref<any>(null)
const viewMode = ref<'data' | 'analysis'>('data')

const buildingLabel = computed(() =>
  buildingOptions.find(b => b.key === selectedBuilding.value)?.label ?? selectedBuilding.value
)

// 胶囊滑块
const toggleRef = ref<HTMLElement>()
const btnDataRef = ref<HTMLElement>()
const btnAnalysisRef = ref<HTMLElement>()
const sliderLeft = ref(0)
const sliderWidth = ref(0)

function updateSlider() {
  const btn = viewMode.value === 'data' ? btnDataRef.value : btnAnalysisRef.value
  const container = toggleRef.value
  if (!btn || !container) return
  sliderLeft.value = btn.offsetLeft
  sliderWidth.value = btn.offsetWidth
}

const sliderStyle = computed(() => ({
  transform: `translateX(${sliderLeft.value}px)`,
  width: `${sliderWidth.value}px`,
}))

watch(viewMode, async () => {
  await nextTick()
  updateSlider()
  if (viewMode.value === 'analysis' && queryResult.value) {
    await nextTick()
    renderChart(queryResult.value, getCheckedParams())
  }
})
onMounted(() => nextTick(updateSlider))

// 监测参数
const allParams = reactive([
  { key: 'electricity_kwh', label: '日用电 (kWh)', checked: true },
  { key: 'water_m3', label: '日用水 (m³)', checked: false },
  { key: 'hac_energy', label: '暖通空调能耗 (kWh)', checked: false },
  { key: 'sim_supply_temp_c', label: '供水温度 (°C)', checked: false },
  { key: 'sim_return_temp_c', label: '回水温度 (°C)', checked: false },
  { key: 'air_temp_c', label: '环境温度 (°C)', checked: true },
  { key: 'humidity_rh_pct', label: '相对湿度 (%)', checked: false },
  { key: 'dew_temp_c', label: '露点温度 (°C)', checked: false },
])

// ── ECharts ──
const chartRef = ref<HTMLElement>()
let chart: echarts.ECharts | null = null

const PARAM_COLORS: Record<string, string> = {
  electricity_kwh: '#3ba272',
  water_m3: '#5470c6',
  hac_energy: '#ee6666',
  sim_supply_temp_c: '#73c0de',
  sim_return_temp_c: '#fc8452',
  air_temp_c: '#fac858',
  humidity_rh_pct: '#9a60b4',
  dew_temp_c: '#91cc75',
}

function getCheckedParams() {
  return allParams.filter(p => p.checked)
}

async function handleQuery() {
  const checked = getCheckedParams()
  if (checked.length === 0) return

  loading.value = true
  queryResult.value = null

  try {
    const data = await apiFetch<any>(
      `/api/buildings/${selectedBuilding.value}/energy?start_date=${startDate.value}&end_date=${endDate.value}&include_water=true`
    )

    queryResult.value = data
    if (viewMode.value === 'analysis') {
      await nextTick()
      renderChart(data, checked)
    }
  } catch (e: any) {
    console.error('查询失败', e)
  } finally {
    loading.value = false
  }
}

const PARAM_FIELD_MAP: Record<string, string> = {
  electricity_kwh: 'total_electricity_kwh',
  water_m3: 'total_water_m3',
  hac_energy: 'total_hac_energy',
  air_temp_c: 'avg_ambient_temp',
  sim_supply_temp_c: 'avg_supply_temp',
  sim_return_temp_c: 'avg_return_temp',
  humidity_rh_pct: 'avg_humidity',
  dew_temp_c: 'avg_dew_temp',
}

function formatTableVal(v: any): string {
  if (v == null) return '-'
  const n = Number(v)
  return isNaN(n) ? String(v) : n.toFixed(2)
}

function renderChart(data: any, params: typeof allParams) {
  if (!chartRef.value) return
  if (chart) chart.dispose()
  chart = echarts.init(chartRef.value)

  const days = (data.records || []).map((r: any) => r.day?.slice(0, 10) || '')

  const tempParams = ['air_temp_c', 'sim_supply_temp_c', 'sim_return_temp_c', 'dew_temp_c', 'humidity_rh_pct']
  const hasTemp = params.some(p => tempParams.includes(p.key))
  const hasEnergy = params.some(p => !tempParams.includes(p.key))

  const yAxis: any[] = []
  if (hasEnergy) yAxis.push({
    type: 'value', name: '能耗', position: 'left',
    nameTextStyle: { color: '#8c939a', fontSize: 12 },
    axisLine: { show: false },
    axisTick: { show: false },
    splitLine: { lineStyle: { color: '#f0f2f5', type: 'dashed' } },
    axisLabel: { color: '#8c939a', fontSize: 11 },
  })
  if (hasTemp) yAxis.push({
    type: 'value', name: '温度', position: 'right',
    nameTextStyle: { color: '#8c939a', fontSize: 12 },
    axisLine: { show: false },
    axisTick: { show: false },
    splitLine: { show: false },
    axisLabel: { color: '#8c939a', fontSize: 11 },
  })
  if (yAxis.length === 0) yAxis.push({ type: 'value' })

  const series = params.map((p) => {
    const field = PARAM_FIELD_MAP[p.key] || p.key
    const isTemp = tempParams.includes(p.key)
    const yAxisIndex = hasEnergy && hasTemp ? (isTemp ? 1 : 0) : 0

    let seriesType = 'line'
    if (chartType.value === 'bar') seriesType = 'bar'
    else if (chartType.value === 'mixed') seriesType = isTemp ? 'line' : 'bar'

    return {
      name: p.label,
      type: seriesType,
      yAxisIndex,
      data: (data.records || []).map((r: any) => r[field] != null ? Number(Number(r[field]).toFixed(2)) : null),
      itemStyle: { color: PARAM_COLORS[p.key], borderRadius: seriesType === 'bar' ? [3, 3, 0, 0] : undefined },
      lineStyle: { width: 2.5 },
      smooth: true,
      barMaxWidth: 28,
      barGap: '20%',
      emphasis: { focus: 'series' },
      animationDuration: 800,
      animationEasing: 'cubicOut',
    }
  })

  chart.setOption({
    tooltip: {
      trigger: 'axis',
      backgroundColor: 'rgba(255, 255, 255, 0.96)',
      borderColor: '#eaedf0',
      borderWidth: 1,
      textStyle: { color: '#2d3239', fontSize: 12 },
      padding: [10, 14],
      extraCssText: 'box-shadow: 0 4px 16px rgba(0,0,0,0.08); border-radius: 8px;',
    },
    legend: {
      data: params.map(p => p.label),
      bottom: 0,
      icon: 'roundRect',
      itemWidth: 12,
      itemHeight: 8,
      textStyle: { color: '#8c939a', fontSize: 11 },
      itemGap: 16,
    },
    grid: { left: 56, right: 56, top: 36, bottom: 44, containLabel: false },
    xAxis: {
      type: 'category',
      data: days,
      axisLabel: {
        rotate: days.length > 15 ? 45 : 0,
        color: '#8c939a',
        fontSize: 11,
      },
      axisLine: { lineStyle: { color: '#e8ebee' } },
      axisTick: { show: false },
    },
    yAxis,
    series,
    animationDuration: 600,
  })
}

function onResize() { chart?.resize() }

onMounted(() => { window.addEventListener('resize', onResize) })
onUnmounted(() => { window.removeEventListener('resize', onResize); chart?.dispose() })
</script>

<style scoped>
.query-stats {
  padding: 28px 32px 24px;
  height: 100%;
  display: flex;
  flex-direction: column;
  overflow-y: auto;
}

/* ── 筛选面板 ── */
.filter-panel {
  background: #fff;
  border: 1px solid #eaedf0;
  border-radius: 12px;
  padding: 20px 24px 16px;
  margin-bottom: 20px;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.04), 0 1px 2px rgba(0, 0, 0, 0.02);
}

.filter-row {
  display: flex;
  align-items: flex-end;
  gap: 14px;
  flex-wrap: wrap;
}

.filter-item {
  display: flex;
  flex-direction: column;
  gap: 6px;
  flex: 1;
  min-width: 140px;
}

.filter-label {
  display: flex;
  align-items: center;
  gap: 4px;
  font-size: 12px;
  color: #8c939a;
  font-weight: 500;
  letter-spacing: 0.02em;
}

.label-icon { color: #b0b6be; }

.input-wrap { position: relative; }

.select-arrow {
  position: absolute;
  right: 10px;
  top: 50%;
  transform: translateY(-50%);
  color: #b0b6be;
  pointer-events: none;
  z-index: 1;
}

.filter-select,
.filter-input {
  width: 100%;
  height: 38px;
  padding: 0 12px;
  border: 1px solid #e2e5e9;
  border-radius: 8px;
  background: #fafbfc;
  color: #2d3239;
  font-size: 13px;
  outline: none;
  transition: border-color 0.2s, box-shadow 0.2s, background 0.2s;
}

.filter-select {
  appearance: none;
  -webkit-appearance: none;
  padding-right: 30px;
  cursor: pointer;
}

.filter-select:hover,
.filter-input:hover {
  border-color: #c8cdd3;
  background: #fff;
}

.filter-select:focus,
.filter-input:focus {
  border-color: #4caf50;
  background: #fff;
  box-shadow: 0 0 0 3px rgba(76, 175, 80, 0.1);
}

.query-btn {
  display: flex;
  align-items: center;
  gap: 6px;
  height: 38px;
  padding: 0 28px;
  background: linear-gradient(135deg, #4caf50 0%, #43a047 100%);
  color: #fff;
  border: none;
  border-radius: 8px;
  font-size: 14px;
  font-weight: 600;
  cursor: pointer;
  white-space: nowrap;
  transition: transform 0.15s, box-shadow 0.15s, opacity 0.15s;
  box-shadow: 0 2px 6px rgba(76, 175, 80, 0.25);
  letter-spacing: 0.02em;
  flex-shrink: 0;
}

.query-btn:hover {
  transform: translateY(-1px);
  box-shadow: 0 4px 12px rgba(76, 175, 80, 0.35);
}

.query-btn:active { transform: translateY(0); }

.query-btn:disabled {
  opacity: 0.55;
  cursor: not-allowed;
  transform: none;
  box-shadow: none;
}

/* ── 分隔线 ── */
.filter-divider {
  height: 1px;
  background: linear-gradient(90deg, transparent, #e8ebee 15%, #e8ebee 85%, transparent);
  margin: 14px 0;
}

/* ── 底部行 ── */
.filter-bottom {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 12px;
}

/* ── 监测参数 ── */
.params-row {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 4px 12px;
}

.params-label {
  display: flex;
  align-items: center;
  gap: 4px;
  font-size: 13px;
  color: #4caf50;
  font-weight: 600;
  margin-right: 2px;
}

.param-checkbox {
  display: flex;
  align-items: center;
  gap: 5px;
  font-size: 13px;
  color: #636a73;
  cursor: pointer;
  user-select: none;
  padding: 3px 8px 3px 4px;
  border-radius: 6px;
  transition: background 0.15s, color 0.15s;
}

.param-checkbox:hover {
  background: #f0f7f0;
  color: #2d3239;
}

.param-checkbox.checked { color: #2d3239; }
.param-checkbox input[type="checkbox"] { display: none; }

.check-box {
  width: 16px;
  height: 16px;
  border: 1.5px solid #ced2d8;
  border-radius: 4px;
  background: #fff;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  transition: all 0.15s;
}

.param-checkbox.checked .check-box {
  background: #4caf50;
  border-color: #4caf50;
}

.check-icon { color: #fff; }

/* ── 胶囊切换 ── */
.view-toggle {
  display: inline-flex;
  position: relative;
  border: 1px solid #e8ebee;
  border-radius: 22px;
  background: #f5f6f8;
  padding: 3px;
  flex-shrink: 0;
}

.toggle-slider {
  position: absolute;
  top: 3px;
  left: 0;
  height: calc(100% - 6px);
  border-radius: 20px;
  background: linear-gradient(135deg, #4caf50 0%, #43a047 100%);
  box-shadow: 0 2px 6px rgba(76, 175, 80, 0.25);
  transition: transform 0.3s cubic-bezier(0.4, 0, 0.2, 1), width 0.3s cubic-bezier(0.4, 0, 0.2, 1);
  z-index: 0;
}

.toggle-btn {
  display: flex;
  align-items: center;
  gap: 5px;
  padding: 6px 16px;
  font-size: 13px;
  font-weight: 500;
  border: none;
  background: transparent;
  color: #8c939a;
  cursor: pointer;
  transition: color 0.2s;
  white-space: nowrap;
  position: relative;
  z-index: 1;
  border-radius: 20px;
}

.toggle-btn:hover:not(.active) { color: #555; }
.toggle-btn.active { color: #fff; }

/* ── 图表卡片 ── */
.chart-card {
  flex: 1;
  min-height: 0;
  background: #fff;
  border: 1px solid #eaedf0;
  border-radius: 12px;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.04), 0 1px 2px rgba(0, 0, 0, 0.02);
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.chart-card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 16px 20px 0;
}

.chart-card-title {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 15px;
  font-weight: 600;
  color: #2d3239;
}

.chart-title-icon { color: #4caf50; }

.chart-date-range {
  font-size: 12px;
  font-weight: 400;
  color: #b0b6be;
  padding: 2px 10px;
  background: #f5f6f8;
  border-radius: 10px;
}

.chart-card-actions {
  display: flex;
  gap: 4px;
}

.card-action-btn {
  width: 32px;
  height: 32px;
  display: flex;
  align-items: center;
  justify-content: center;
  border: none;
  background: transparent;
  color: #b0b6be;
  border-radius: 8px;
  cursor: pointer;
  transition: background 0.15s, color 0.15s;
}

.card-action-btn:hover {
  background: #f5f6f8;
  color: #636a73;
}

.chart-container {
  flex: 1;
  min-height: 380px;
  padding: 8px 16px 12px;
}

/* ── 数据表格 ── */
.data-table-wrap {
  flex: 1;
  overflow: auto;
  padding: 12px 16px 16px;
  max-height: 520px;
}

.data-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 13px;
  white-space: nowrap;
}

.data-table thead th {
  position: sticky;
  top: 0;
  background: #f8f9fa;
  color: #636a73;
  font-weight: 600;
  font-size: 12px;
  padding: 10px 14px;
  text-align: left;
  border-bottom: 2px solid #e8ebee;
  z-index: 2;
}

.data-table tbody td {
  padding: 9px 14px;
  color: #2d3239;
  border-bottom: 1px solid #f0f2f5;
}

.data-table tbody tr:hover td {
  background: #f0f7f0;
}

.data-table .sticky-col {
  position: sticky;
  left: 0;
  z-index: 1;
}

.data-table thead .sticky-col {
  z-index: 3;
  background: #f8f9fa;
}

.data-table tbody .sticky-col {
  background: #fff;
}

.data-table tbody tr:hover .sticky-col {
  background: #f0f7f0;
}

.date-cell {
  font-weight: 500;
  color: #4caf50;
}

.num-cell {
  text-align: right;
  font-variant-numeric: tabular-nums;
}

.data-table thead th:not(.sticky-col) {
  text-align: right;
}

/* ── 空状态 ── */
.content-placeholder {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
}

.empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 12px;
  padding: 48px 0;
}

.empty-icon-wrap {
  width: 80px;
  height: 80px;
  border-radius: 50%;
  background: linear-gradient(135deg, #f0f7f0 0%, #e8f5e9 100%);
  display: flex;
  align-items: center;
  justify-content: center;
  color: #a5d6a7;
}

.empty-title {
  font-size: 15px;
  font-weight: 600;
  color: #8c939a;
  margin: 0;
}

.empty-desc {
  font-size: 13px;
  color: #b0b6be;
  margin: 0;
}

/* ── 骨架屏加载 ── */
.skeleton-card {
  padding: 20px 24px;
}

.skeleton-header {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 32px;
}

.skeleton-line {
  border-radius: 6px;
  background: linear-gradient(90deg, #f0f2f5 25%, #e8ebee 50%, #f0f2f5 75%);
  background-size: 200% 100%;
  animation: shimmer 1.5s ease-in-out infinite;
}

.skeleton-title-line {
  width: 160px;
  height: 18px;
}

.skeleton-badge-line {
  width: 100px;
  height: 14px;
}

/* ── 表格骨架 ── */
.skeleton-table {
  display: flex;
  flex-direction: column;
  gap: 0;
}

.skeleton-table-head {
  display: flex;
  gap: 20px;
  padding: 12px 16px;
  border-bottom: 2px solid #eaedf0;
}

.skeleton-th {
  width: 80px;
  height: 14px;
  flex-shrink: 0;
}

.skeleton-th:first-child { width: 90px; }

.skeleton-table-row {
  display: flex;
  gap: 20px;
  padding: 11px 16px;
  border-bottom: 1px solid #f0f2f5;
}

.skeleton-td {
  height: 13px;
  flex-shrink: 0;
}

/* ── 图表骨架 ── */
.skeleton-chart {
  display: flex;
  align-items: flex-end;
  gap: 8px;
  height: 320px;
  padding-top: 20px;
}

.skeleton-bar {
  flex: 1;
  border-radius: 4px 4px 0 0;
  background: linear-gradient(90deg, #f0f2f5 25%, #e8ebee 50%, #f0f2f5 75%);
  background-size: 200% 100%;
  animation: shimmer 1.5s ease-in-out infinite;
}

@keyframes shimmer {
  0% { background-position: 200% 0; }
  100% { background-position: -200% 0; }
}

.spin { animation: spin 1s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }

/* ── 响应式 ── */
@media (max-width: 1024px) {
  .query-stats { padding: 20px 20px 16px; }
  .filter-row { gap: 10px; }
  .filter-item { min-width: 120px; }
  .filter-bottom { flex-direction: column; align-items: flex-start; }
}

@media (max-width: 768px) {
  .query-stats { padding: 16px 14px 12px; }

  .filter-panel { padding: 16px 16px 12px; border-radius: 10px; }

  .filter-row {
    flex-direction: column;
    align-items: stretch;
    gap: 10px;
  }

  .filter-item {
    min-width: 0;
    flex: none;
  }

  .query-btn { width: 100%; justify-content: center; }

  .params-row { gap: 4px 8px; }
  .param-checkbox { font-size: 12px; padding: 2px 6px 2px 3px; }
  .param-checkbox .check-box { width: 14px; height: 14px; }

  .view-toggle { width: 100%; }
  .toggle-btn { flex: 1; justify-content: center; padding: 6px 12px; font-size: 12px; }

  .chart-card-header { padding: 12px 14px 0; }
  .chart-card-title { font-size: 14px; flex-wrap: wrap; }
  .chart-date-range { font-size: 11px; }
  .chart-container { min-height: 280px; padding: 4px 8px 8px; }
}

@media (max-width: 480px) {
  .query-stats { padding: 12px 10px 8px; }
  .filter-panel { padding: 12px 12px 10px; }
  .chart-container { min-height: 240px; }
  .params-label { font-size: 12px; }
}

/* ── prefers-reduced-motion ── */
@media (prefers-reduced-motion: reduce) {
  .toggle-slider { transition: none; }
  .query-btn { transition: none; }
  .skeleton-line, .skeleton-bar { animation: none; background: #f0f2f5; }
  .spin { animation: none; }
}
</style>
