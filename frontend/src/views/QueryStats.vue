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
          <div
            class="qs-dropdown"
            :class="{ 'qs-dropdown--open': dropdownBuildingOpen }"
            @click.stop="dropdownBuildingOpen = !dropdownBuildingOpen; dropdownChartOpen = false"
          >
            <span class="qs-dropdown-value">{{ buildingOptions.find(b => b.key === selectedBuilding)?.label }}</span>
            <Icon icon="mdi:chevron-down" width="14" class="qs-dropdown-arrow" :class="{ 'qs-dropdown-arrow--open': dropdownBuildingOpen }" />
            <Transition name="qs-drop">
              <div v-if="dropdownBuildingOpen" class="qs-dropdown-list" @click.stop>
                <div
                  v-for="b in buildingOptions" :key="b.key"
                  class="qs-dropdown-item"
                  :class="{ 'qs-dropdown-item--selected': selectedBuilding === b.key }"
                  @click="selectedBuilding = b.key; dropdownBuildingOpen = false"
                >
                  <Icon v-if="selectedBuilding === b.key" icon="mdi:check" width="13" class="qs-item-check" />
                  <span>{{ b.label }}</span>
                </div>
              </div>
            </Transition>
          </div>
        </div>
        <div class="filter-item">
          <label class="filter-label">
            <Icon icon="mdi:calendar-start" width="13" class="label-icon" />
            开始日期
          </label>
          <input type="date" v-model="startDate" class="filter-input" />
        </div>
        <div class="filter-item">
          <label class="filter-label">
            <Icon icon="mdi:calendar-end" width="13" class="label-icon" />
            结束日期
          </label>
          <input type="date" v-model="endDate" class="filter-input" />
        </div>
        <div class="filter-item">
          <label class="filter-label">
            <Icon icon="mdi:chart-box-outline" width="13" class="label-icon" />
            图表类型
          </label>
          <div
            class="qs-dropdown"
            :class="{ 'qs-dropdown--open': dropdownChartOpen }"
            @click.stop="dropdownChartOpen = !dropdownChartOpen; dropdownBuildingOpen = false"
          >
            <span class="qs-dropdown-value">{{ CHART_OPTIONS.find(c => c.value === chartType)?.label }}</span>
            <Icon icon="mdi:chevron-down" width="14" class="qs-dropdown-arrow" :class="{ 'qs-dropdown-arrow--open': dropdownChartOpen }" />
            <Transition name="qs-drop">
              <div v-if="dropdownChartOpen" class="qs-dropdown-list" @click.stop>
                <div
                  v-for="opt in CHART_OPTIONS" :key="opt.value"
                  class="qs-dropdown-item"
                  :class="{ 'qs-dropdown-item--selected': chartType === opt.value }"
                  @click="chartType = opt.value; dropdownChartOpen = false"
                >
                  <Icon v-if="chartType === opt.value" icon="mdi:check" width="13" class="qs-item-check" />
                  <span>{{ opt.label }}</span>
                </div>
              </div>
            </Transition>
          </div>
        </div>
        <button
          class="query-btn"
          @click="handleQuery"
          :disabled="loading"
          aria-label="查询数据"
        >
          <Icon :icon="loading ? 'mdi:loading' : 'mdi:magnify'" width="16" :class="{ spin: loading }" />
          {{ loading ? '查询中...' : '查询' }}
        </button>
        <button
          class="report-btn"
          @click="openReportPreview()"
          :disabled="!queryResult && !devicesData"
          title="生成报表"
          aria-label="生成报表"
        >
          <Icon icon="mdi:file-chart-outline" width="15" />
          报表
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
          <label
            v-for="p in allParams" :key="p.key"
            class="param-checkbox"
            :class="{ checked: p.checked, 'param-checkbox--device': p.key === 'device_status' }"
          >
            <input type="checkbox" v-model="p.checked" />
            <span class="check-box">
              <Icon v-if="p.checked" icon="mdi:check" width="11" class="check-icon" />
            </span>
            <Icon v-if="p.key === 'device_status'" icon="mdi:devices" width="13" class="param-special-icon" />
            {{ p.label }}
          </label>
        </div>
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

    <!-- ══════════════ 数据展示：表格 ══════════════ -->
    <div class="chart-card" v-if="queryResult && hasEnergyParams && viewMode === 'data'">
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
              <th v-for="p in getCheckedEnergyParams()" :key="p.key">{{ p.label }}</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="(row, idx) in queryResult.records" :key="idx">
              <td class="sticky-col date-cell">{{ row.day?.slice(0, 10) }}</td>
              <td v-for="p in getCheckedEnergyParams()" :key="p.key" class="num-cell">
                {{ formatTableVal(row[PARAM_FIELD_MAP[p.key] || p.key]) }}
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

    <!-- ══════════════ 统计分析：能耗图表 ══════════════ -->
    <div class="chart-card" v-if="queryResult && hasEnergyParams && viewMode === 'analysis'">
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

    <!-- ══════════════ 设备运行状态区块（数据展示） ══════════════ -->
    <template v-if="deviceStatusChecked && devicesData && viewMode === 'data'">
      <!-- 设备状态卡片 -->
      <div class="section-card">
        <div class="section-card-header">
          <Icon icon="mdi:card-multiple-outline" width="17" class="section-icon" />
          <span>{{ buildingLabel }} — 设备状态快照</span>
          <span class="section-subtitle">最后更新：{{ lastSeenFormatted }}</span>
          <button class="card-action-btn" style="margin-left:auto" @click="handleQuery" title="刷新">
            <Icon icon="mdi:refresh" width="16" />
          </button>
        </div>
        <div class="device-cards-grid">
          <div
            v-for="dev in devicesData.devices"
            :key="dev.device_id"
            class="dev-card"
            :class="[`dev-card--${dev.device_type}`, `health-${dev.health_status}`]"
          >
            <div class="dev-card-head">
              <div class="dev-icon-wrap" :class="`dev-icon--${dev.device_type}`">
                <Icon :icon="DEVICE_ICONS[dev.device_type] || 'mdi:chip'" width="22" />
              </div>
              <div class="dev-title-group">
                <span class="dev-name">{{ DEVICE_NAMES[dev.device_type] || dev.device_type }}</span>
                <span class="dev-id">{{ dev.device_id }}</span>
              </div>
              <div class="dev-badges">
                <span class="dev-badge" :class="`badge-run-${dev.running_state}`">
                  <span class="badge-dot"></span>
                  {{ RUNNING_LABELS[dev.running_state] || dev.running_state }}
                </span>
                <span class="dev-badge" :class="`badge-health-${dev.health_status}`">
                  <Icon :icon="HEALTH_ICONS[dev.health_status] || 'mdi:help-circle'" width="11" />
                  {{ HEALTH_LABELS[dev.health_status] || dev.health_status }}
                </span>
              </div>
            </div>
            <div class="dev-metrics">
              <template v-if="dev.device_type === 'ac'">
                <div class="dev-metric">
                  <span class="dev-metric-label"><Icon icon="mdi:lightning-bolt" width="12" />当前功率</span>
                  <span class="dev-metric-value">{{ dev.latest_power_kw != null ? dev.latest_power_kw.toFixed(1) + ' kW' : '—' }}</span>
                </div>
                <div class="dev-metric">
                  <span class="dev-metric-label"><Icon icon="mdi:thermometer-chevron-up" width="12" />供水温度</span>
                  <span class="dev-metric-value">{{ dev.latest_supply_temp_c != null ? dev.latest_supply_temp_c.toFixed(1) + ' °C' : '—' }}</span>
                </div>
                <div class="dev-metric">
                  <span class="dev-metric-label"><Icon icon="mdi:thermometer-chevron-down" width="12" />回水温度</span>
                  <span class="dev-metric-value">{{ dev.latest_return_temp_c != null ? dev.latest_return_temp_c.toFixed(1) + ' °C' : '—' }}</span>
                </div>
                <div class="dev-metric" v-if="dev.latest_supply_temp_c != null && dev.latest_return_temp_c != null">
                  <span class="dev-metric-label"><Icon icon="mdi:swap-vertical" width="12" />供回水温差</span>
                  <span class="dev-metric-value" :class="Math.abs(dev.latest_supply_temp_c - dev.latest_return_temp_c) < 3 ? 'val-warn' : ''">
                    {{ Math.abs(dev.latest_supply_temp_c - dev.latest_return_temp_c).toFixed(1) }} °C
                  </span>
                </div>
              </template>
              <template v-else-if="dev.device_type === 'electricity'">
                <div class="dev-metric">
                  <span class="dev-metric-label"><Icon icon="mdi:lightning-bolt" width="12" />当前功率</span>
                  <span class="dev-metric-value">{{ dev.latest_power_kw != null ? dev.latest_power_kw.toFixed(1) + ' kW' : '—' }}</span>
                </div>
                <div class="dev-metric">
                  <span class="dev-metric-label"><Icon icon="mdi:gauge" width="12" />在线状态</span>
                  <span class="dev-metric-value">{{ dev.online_status === 'online' ? '在线' : dev.online_status }}</span>
                </div>
              </template>
              <template v-else-if="dev.device_type === 'water'">
                <div class="dev-metric">
                  <span class="dev-metric-label"><Icon icon="mdi:water" width="12" />当前流量</span>
                  <span class="dev-metric-value">{{ dev.latest_flow_rate != null ? dev.latest_flow_rate.toFixed(1) + ' L' : '—' }}</span>
                </div>
                <div class="dev-metric">
                  <span class="dev-metric-label"><Icon icon="mdi:gauge" width="12" />在线状态</span>
                  <span class="dev-metric-value">{{ dev.online_status === 'online' ? '在线' : dev.online_status }}</span>
                </div>
              </template>
              <div class="dev-metric dev-metric--full">
                <span class="dev-metric-label"><Icon icon="mdi:clock-outline" width="12" />最后更新</span>
                <span class="dev-metric-value dev-metric-time">{{ formatTs(dev.last_seen_at) }}</span>
              </div>
            </div>
          </div>
        </div>
      </div>

      <!-- 异常归因记录 -->
      <div class="section-card">
        <div class="section-card-header">
          <Icon icon="mdi:alert-circle-outline" width="17" class="section-icon section-icon--warn" />
          <span>异常归因记录</span>
          <span class="section-subtitle">近 7 天 / 最多显示 10 条</span>
          <span v-if="attributionsData && attributionsData.total > 0" class="section-badge section-badge--warn">{{ attributionsData.total }} 条</span>
          <span v-else class="section-badge section-badge--ok">正常</span>
        </div>
        <div class="attrib-empty" v-if="!attributionsData || attributionsData.total === 0">
          <Icon icon="mdi:check-circle-outline" width="28" />
          <span>该楼宇近期无异常归因记录</span>
        </div>
        <div class="attrib-table-wrap" v-else>
          <table class="attrib-table">
            <thead>
              <tr>
                <th>时间</th>
                <th>设备</th>
                <th>规则</th>
                <th class="num-col">实际值</th>
                <th class="num-col">期望值</th>
                <th class="num-col">偏差</th>
                <th class="num-col">归因得分</th>
                <th>归因原因</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="(atr, idx) in (attributionsData.attributions || []).slice(0, 10)" :key="idx">
                <td class="ts-cell">{{ formatTs(atr.timestamp) }}</td>
                <td>
                  <span class="dev-type-chip" :class="`chip-${atr.device_type}`">
                    <Icon :icon="DEVICE_ICONS[atr.device_type] || 'mdi:chip'" width="11" />
                    {{ DEVICE_NAMES[atr.device_type] || atr.device_type }}
                  </span>
                </td>
                <td><span class="rule-chip">{{ RULE_LABELS[atr.rule_triggered] || atr.rule_triggered }}</span></td>
                <td class="num-col">{{ atr.actual_value != null ? Number(atr.actual_value).toFixed(2) : '—' }}</td>
                <td class="num-col">{{ atr.expected_value != null ? Number(atr.expected_value).toFixed(2) : '—' }}</td>
                <td class="num-col" :class="deviationClass(atr.deviation_pct)">
                  {{ atr.deviation_pct != null ? (atr.deviation_pct > 0 ? '+' : '') + Number(atr.deviation_pct).toFixed(1) + '%' : '—' }}
                </td>
                <td class="num-col score-cell">
                  <div class="score-bar-wrap">
                    <div class="score-bar" :style="{ width: ((atr.attribution_score || 0) * 100).toFixed(0) + '%' }"></div>
                  </div>
                  {{ atr.attribution_score != null ? Number(atr.attribution_score).toFixed(3) : '—' }}
                </td>
                <td class="reason-cell">{{ atr.attribution_reason || '—' }}</td>
              </tr>
            </tbody>
          </table>
        </div>
        <div class="device-summary-row" v-if="attributionsData && attributionsData.device_summary?.length">
          <span class="summary-label">设备异常汇总：</span>
          <div class="summary-chip" v-for="ds in attributionsData.device_summary" :key="ds.device_id">
            <Icon :icon="DEVICE_ICONS[ds.device_type] || 'mdi:chip'" width="12" />
            {{ DEVICE_NAMES[ds.device_type] || ds.device_type }}
            <span class="summary-count">{{ ds.anomaly_count }} 次</span>
          </div>
        </div>
      </div>
    </template>

    <!-- ══════════════ 设备运行状态图表（统计分析） ══════════════ -->
    <template v-if="deviceStatusChecked && devicesData && viewMode === 'analysis'">
      <!-- 运行状态时间线（甘特图） -->
      <div class="section-card">
        <div class="section-card-header">
          <Icon icon="mdi:chart-gantt" width="17" class="section-icon" />
          <span>设备运行状态时间线</span>
          <span class="chart-date-range">{{ startDate }} ~ {{ endDate }}</span>
        </div>
        <div v-if="deviceHistory.length === 0" class="dev-chart-empty">
          <Icon icon="mdi:chart-timeline-variant" width="32" />
          <span>暂无设备遥测历史数据</span>
        </div>
        <div v-else class="device-chart-container" ref="ganttChartRef"></div>
      </div>

      <!-- 健康状态分布 + 功率趋势 并排 -->
      <div class="device-charts-row">
        <!-- 健康状态分布环形图 -->
        <div class="section-card device-charts-row-item">
          <div class="section-card-header">
            <Icon icon="mdi:heart-pulse" width="17" class="section-icon" />
            <span>设备健康状态分布</span>
          </div>
          <div v-if="deviceHistory.length === 0" class="dev-chart-empty">
            <Icon icon="mdi:heart-pulse" width="32" />
            <span>暂无数据</span>
          </div>
          <div v-else class="device-chart-container device-chart-container--half" ref="healthPieRef"></div>
        </div>

        <!-- 设备功率/流量趋势 -->
        <div class="section-card device-charts-row-item">
          <div class="section-card-header">
            <Icon icon="mdi:chart-timeline-variant" width="17" class="section-icon" />
            <span>设备功率/流量趋势</span>
            <div class="device-chart-tabs">
              <button
                v-for="dt in DEVICE_TAB_OPTIONS" :key="dt.key"
                class="dev-tab-btn"
                :class="{ active: activeDeviceChart === dt.key }"
                @click="activeDeviceChart = dt.key"
              >
                <Icon :icon="DEVICE_ICONS[dt.key]" width="13" />
                {{ dt.label }}
              </button>
            </div>
          </div>
          <div v-if="filteredHistory.length === 0" class="dev-chart-empty">
            <Icon icon="mdi:chart-line-variant" width="32" />
            <span>该设备暂无遥测历史数据</span>
          </div>
          <div v-else class="device-chart-container device-chart-container--half" ref="deviceChartRef"></div>
        </div>
      </div>
    </template>

    <!-- ══════════════ 空状态 ══════════════ -->
    <div class="content-placeholder" v-if="!queryResult && !devicesData && !loading">
      <div class="empty-state">
        <div class="empty-icon-wrap">
          <Icon icon="mdi:chart-bar" width="40" />
        </div>
        <p class="empty-title">暂无数据</p>
        <p class="empty-desc">选择筛选条件后点击查询按钮</p>
      </div>
    </div>

    <!-- ══════════════ 加载骨架 ══════════════ -->
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
import { useReportExport } from '@/composables/useReportExport'

// ── 报表集成 ──
const { registerSection, captureChart, setReportMeta, openPreview } = useReportExport('querystats')

// ── 筛选状态 ──
const buildingOptions = [
  { key: 'Education', label: '教学楼' },
  { key: 'Office', label: '办公楼' },
  { key: 'Public services', label: '公共楼' },
]
const CHART_OPTIONS = [
  { value: 'line',  label: '折线图' },
  { value: 'bar',   label: '柱状图' },
  { value: 'mixed', label: '混合（折线+柱状）' },
]
const selectedBuilding = ref('Office')
const startDate = ref('2016-04-01')
const endDate = ref('2016-05-02')
const chartType = ref('mixed')

// ── 自定义下拉状态 ──
const dropdownBuildingOpen = ref(false)
const dropdownChartOpen    = ref(false)
function closeQsDropdowns() {
  dropdownBuildingOpen.value = false
  dropdownChartOpen.value    = false
}
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
  if (viewMode.value === 'analysis') {
    await nextTick()
    if (queryResult.value && hasEnergyParams.value) {
      renderChart(queryResult.value, getCheckedEnergyParams())
    }
    if (devicesData.value && deviceStatusChecked.value) {
      renderGanttChart()
      renderHealthPie()
      renderDeviceChart()
    }
  }
})
onMounted(() => nextTick(updateSlider))

// ── 监测参数（含设备运行状态） ──
const allParams = reactive([
  { key: 'electricity_kwh', label: '日用电 (kWh)', checked: true },
  { key: 'water_m3', label: '日用水 (m³)', checked: false },
  { key: 'hac_energy', label: '暖通空调能耗 (kWh)', checked: false },
  { key: 'sim_supply_temp_c', label: '供水温度 (°C)', checked: false },
  { key: 'sim_return_temp_c', label: '回水温度 (°C)', checked: false },
  { key: 'air_temp_c', label: '环境温度 (°C)', checked: true },
  { key: 'humidity_rh_pct', label: '相对湿度 (%)', checked: false },
  { key: 'dew_temp_c', label: '露点温度 (°C)', checked: false },
  { key: 'device_status', label: '设备运行状态', checked: false },
])

const deviceStatusChecked = computed(() => allParams.find(p => p.key === 'device_status')!.checked)
const hasEnergyParams = computed(() => allParams.some(p => p.key !== 'device_status' && p.checked))

function getCheckedEnergyParams() {
  return allParams.filter(p => p.key !== 'device_status' && p.checked)
}

// ── ECharts（能耗） ──
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

// ── 统一查询 ──
async function handleQuery() {
  const energyParams = getCheckedEnergyParams()
  const wantDevice = deviceStatusChecked.value
  if (energyParams.length === 0 && !wantDevice) return

  loading.value = true
  queryResult.value = null
  devicesData.value = null
  attributionsData.value = null

  try {
    const promises: Promise<any>[] = []

    if (energyParams.length > 0) {
      promises.push(
        apiFetch<any>(
          `/api/buildings/${selectedBuilding.value}/energy?start_date=${startDate.value}&end_date=${endDate.value}&include_water=true`
        )
      )
    } else {
      promises.push(Promise.resolve(null))
    }

    if (wantDevice) {
      promises.push(
        apiFetch<any>(
          `/api/buildings/${selectedBuilding.value}/devices?start_date=${startDate.value}&end_date=${endDate.value}`
        )
      )
      promises.push(
        apiFetch<any>(
          `/api/anomalies/attributions?building_type=${encodeURIComponent(selectedBuilding.value)}`
        )
      )
    } else {
      promises.push(Promise.resolve(null))
      promises.push(Promise.resolve(null))
    }

    const [energyResp, devResp, attrResp] = await Promise.all(promises)

    if (energyResp) queryResult.value = energyResp
    if (devResp) devicesData.value = devResp
    if (attrResp) attributionsData.value = attrResp

    await nextTick()

    if (viewMode.value === 'analysis') {
      if (queryResult.value && hasEnergyParams.value) {
        renderChart(queryResult.value, energyParams)
      }
      if (devicesData.value && wantDevice) {
        renderGanttChart()
        renderHealthPie()
        renderDeviceChart()
      }
    }

    // 数据加载完成后注册报表段落
    registerReportSections(energyParams, wantDevice)
  } catch (e: any) {
    console.error('查询失败', e)
  } finally {
    loading.value = false
  }
}

function registerReportSections(energyParams: typeof allParams, wantDevice: boolean) {
  setReportMeta({
    title: `${buildingLabel.value} 查询统计报表`,
    buildingName: buildingLabel.value,
    dateRange: { start: startDate.value, end: endDate.value },
  })

  // 查询条件说明
  registerSection({
    id: 'qs-condition',
    title: '查询条件',
    type: 'text',
    order: 5,
    content: `楼宇：${buildingLabel.value}  |  日期范围：${startDate.value} ~ ${endDate.value}  |  监测参数：${energyParams.map(p => p.label).join('、') || '无'}${wantDevice ? '、设备运行状态' : ''}`,
  })

  // 能耗数据表格
  if (queryResult.value?.records?.length) {
    registerSection({
      id: 'qs-energy-table',
      title: '能耗数据明细',
      type: 'table',
      order: 10,
      columns: [
        { key: 'day', label: '日期' },
        ...energyParams.map(p => ({
          key: PARAM_FIELD_MAP[p.key] || p.key,
          label: p.label,
          align: 'right' as const,
        })),
      ],
      rows: queryResult.value.records.map((r: any) => {
        const row: Record<string, any> = { day: r.day?.slice(0, 10) ?? '' }
        energyParams.forEach(p => {
          const field = PARAM_FIELD_MAP[p.key] || p.key
          row[field] = r[field] != null ? Number(r[field]).toFixed(2) : '—'
        })
        return row
      }),
    })
  }

  // 设备状态
  if (wantDevice && devicesData.value?.devices?.length) {
    registerSection({
      id: 'qs-devices',
      title: '设备运行状态快照',
      type: 'table',
      order: 30,
      columns: [
        { key: 'device_id', label: '设备 ID' },
        { key: 'type', label: '类型' },
        { key: 'running', label: '运行状态' },
        { key: 'health', label: '健康状态' },
      ],
      rows: devicesData.value.devices.map((d: any) => ({
        device_id: d.device_id,
        type: DEVICE_NAMES[d.device_type] ?? d.device_type,
        running: RUNNING_LABELS[d.running_state] ?? d.running_state,
        health: HEALTH_LABELS[d.health_status] ?? d.health_status,
      })),
    })
  }

  // 异常归因记录
  if (wantDevice && attributionsData.value?.attributions?.length) {
    registerSection({
      id: 'qs-attributions',
      title: '异常归因记录',
      type: 'table',
      order: 40,
      columns: [
        { key: 'ts', label: '时间' },
        { key: 'device', label: '设备' },
        { key: 'rule', label: '规则' },
        { key: 'actual', label: '实际值', align: 'right' },
        { key: 'expected', label: '期望值', align: 'right' },
        { key: 'deviation', label: '偏差', align: 'right' },
        { key: 'score', label: '归因得分', align: 'right' },
      ],
      rows: (attributionsData.value.attributions || []).slice(0, 20).map((a: any) => ({
        ts: a.timestamp ? new Date(a.timestamp).toLocaleString('zh-CN') : '—',
        device: DEVICE_NAMES[a.device_type] ?? a.device_type,
        rule: RULE_LABELS[a.rule_triggered] ?? a.rule_triggered,
        actual: a.actual_value != null ? Number(a.actual_value).toFixed(2) : '—',
        expected: a.expected_value != null ? Number(a.expected_value).toFixed(2) : '—',
        deviation: a.deviation_pct != null ? `${a.deviation_pct > 0 ? '+' : ''}${Number(a.deviation_pct).toFixed(1)}%` : '—',
        score: a.attribution_score != null ? Number(a.attribution_score).toFixed(3) : '—',
      })),
    })
  }

  // 图表截图（分析视图）—— 延迟等图表渲染完成
  if (viewMode.value === 'analysis') {
    setTimeout(() => {
      if (chartRef.value && chart) captureChart(chart, 'qs-chart-energy', '能耗趋势图', 20)
      if (healthPieRef.value) {
        const inst = echarts.getInstanceByDom(healthPieRef.value)
        captureChart(inst, 'qs-chart-health', '设备健康状态分布', 35)
      }
    }, 400)
  }
}

function openReportPreview() {
  // 如果已有数据但在数据视图，先截一次图表（如果存在）
  if (viewMode.value === 'data' && chart) {
    captureChart(chart, 'qs-chart-energy', '能耗趋势图', 20)
  }
  openPreview()
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
    axisLine: { show: false }, axisTick: { show: false },
    splitLine: { lineStyle: { color: '#f0f2f5', type: 'dashed' } },
    axisLabel: { color: '#8c939a', fontSize: 11 },
  })
  if (hasTemp) yAxis.push({
    type: 'value', name: '温度', position: 'right',
    nameTextStyle: { color: '#8c939a', fontSize: 12 },
    axisLine: { show: false }, axisTick: { show: false },
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
      borderColor: '#eaedf0', borderWidth: 1,
      textStyle: { color: '#2d3239', fontSize: 12 },
      padding: [10, 14],
      extraCssText: 'box-shadow: 0 4px 16px rgba(0,0,0,0.08); border-radius: 8px;',
    },
    legend: {
      data: params.map(p => p.label), bottom: 0, icon: 'roundRect',
      itemWidth: 12, itemHeight: 8,
      textStyle: { color: '#8c939a', fontSize: 11 }, itemGap: 16,
    },
    grid: { left: 56, right: 56, top: 36, bottom: 44, containLabel: false },
    xAxis: {
      type: 'category', data: days,
      axisLabel: { rotate: days.length > 15 ? 45 : 0, color: '#8c939a', fontSize: 11 },
      axisLine: { lineStyle: { color: '#e8ebee' } },
      axisTick: { show: false },
    },
    yAxis,
    series,
    animationDuration: 600,
  })
}

// ═══════════════════════════════════════════════════════════
// 设备运行状态逻辑
// ═══════════════════════════════════════════════════════════

const DEVICE_ICONS: Record<string, string> = {
  ac:          'mdi:air-conditioner',
  electricity: 'mdi:lightning-bolt-circle',
  water:       'mdi:water-pump',
}
const DEVICE_NAMES: Record<string, string> = {
  ac:          '空调主机',
  electricity: '总电表',
  water:       '水表',
}
const RUNNING_LABELS: Record<string, string> = {
  running: '运行中',
  standby: '待机',
  unknown: '未知',
}
const HEALTH_ICONS: Record<string, string> = {
  healthy:  'mdi:check-circle',
  degraded: 'mdi:alert-circle',
  warning:  'mdi:close-circle',
  unknown:  'mdi:help-circle',
}
const HEALTH_LABELS: Record<string, string> = {
  healthy:  '正常',
  degraded: '降级',
  warning:  '告警',
  unknown:  '未知',
}
const RULE_LABELS: Record<string, string> = {
  water_leak:             '水耗偏高',
  electricity_overload:   '电耗超标',
  hvac_overconsumption:   '空调过耗',
  supply_temp_deviation:  '供水温度偏离',
  return_temp_deviation:  '回水温度偏离',
}
const DEVICE_TAB_OPTIONS: { key: 'ac' | 'electricity' | 'water'; label: string }[] = [
  { key: 'ac',          label: '空调' },
  { key: 'electricity', label: '用电' },
  { key: 'water',       label: '用水' },
]

const devicesData       = ref<any>(null)
const attributionsData  = ref<any>(null)
const activeDeviceChart = ref<'ac' | 'electricity' | 'water'>('ac')

const ganttChartRef   = ref<HTMLElement>()
const healthPieRef    = ref<HTMLElement>()
const deviceChartRef  = ref<HTMLElement>()
let ganttChart: echarts.ECharts | null = null
let healthPieChart: echarts.ECharts | null = null
let deviceChart: echarts.ECharts | null = null

const lastSeenFormatted = computed(() => {
  const d = devicesData.value?.devices?.[0]?.last_seen_at
  return d ? formatTs(d) : '—'
})

const deviceHistory = computed<any[]>(() => devicesData.value?.history || [])

const filteredHistory = computed(() =>
  deviceHistory.value.filter((h: any) => h.device_type === activeDeviceChart.value)
)

function formatTs(ts: string | null): string {
  if (!ts) return '—'
  const d = new Date(ts)
  if (isNaN(d.getTime())) return ts
  return d.toLocaleString('zh-CN', {
    year: 'numeric', month: '2-digit', day: '2-digit',
    hour: '2-digit', minute: '2-digit',
  })
}

function deviationClass(pct: number | null): string {
  if (pct == null) return ''
  if (Math.abs(pct) > 15) return 'val-warn'
  if (Math.abs(pct) > 5) return 'val-mild'
  return ''
}

// ── 甘特图：设备运行状态时间线 ──
const GANTT_COLORS: Record<string, string> = {
  running: '#4caf50',
  standby: '#bdbdbd',
  unknown: '#e0e0e0',
}

function renderGanttChart() {
  if (!ganttChartRef.value) return
  const hist = deviceHistory.value
  if (!hist.length) { ganttChart?.dispose(); ganttChart = null; return }

  if (ganttChart) ganttChart.dispose()
  ganttChart = echarts.init(ganttChartRef.value)

  const deviceTypes = [...new Set(hist.map((h: any) => h.device_type))] as string[]
  const categories = deviceTypes.map(dt => DEVICE_NAMES[dt] || dt)

  interface GanttSegment { start: number; end: number; state: string; catIdx: number }
  const segments: GanttSegment[] = []

  for (let ci = 0; ci < deviceTypes.length; ci++) {
    const devHist = hist
      .filter((h: any) => h.device_type === deviceTypes[ci])
      .sort((a: any, b: any) => new Date(a.timestamp).getTime() - new Date(b.timestamp).getTime())

    if (!devHist.length) continue

    let segStart = new Date(devHist[0].timestamp).getTime()
    let segState = devHist[0].running_state || 'unknown'

    for (let i = 1; i < devHist.length; i++) {
      const t = new Date(devHist[i].timestamp).getTime()
      const st = devHist[i].running_state || 'unknown'
      if (st !== segState) {
        segments.push({ start: segStart, end: t, state: segState, catIdx: ci })
        segStart = t
        segState = st
      }
    }
    const lastT = new Date(devHist[devHist.length - 1].timestamp).getTime()
    segments.push({ start: segStart, end: lastT + 3600000, state: segState, catIdx: ci })
  }

  const renderItem = (params: any, api: any) => {
    const catIdx = api.value(0)
    const startVal = api.coord([api.value(1), catIdx])
    const endVal = api.coord([api.value(2), catIdx])
    const barHeight = api.size([0, 1])[1] * 0.6

    return {
      type: 'rect',
      shape: {
        x: startVal[0],
        y: startVal[1] - barHeight / 2,
        width: Math.max(endVal[0] - startVal[0], 2),
        height: barHeight,
        r: 3,
      },
      style: {
        fill: GANTT_COLORS[api.value(3)] || GANTT_COLORS.unknown,
        opacity: 0.85,
      },
    }
  }

  ganttChart.setOption({
    tooltip: {
      formatter: (params: any) => {
        const d = params.data
        if (!d) return ''
        const stLabel = RUNNING_LABELS[d[3]] || d[3]
        const tStart = new Date(d[1]).toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })
        const tEnd = new Date(d[2]).toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })
        return `${categories[d[0]]}<br/>状态: ${stLabel}<br/>${tStart} ~ ${tEnd}`
      },
    },
    grid: { left: 90, right: 40, top: 20, bottom: 40 },
    xAxis: {
      type: 'time',
      axisLabel: { color: '#8c939a', fontSize: 11 },
      axisLine: { lineStyle: { color: '#e8ebee' } },
      axisTick: { show: false },
      splitLine: { lineStyle: { color: '#f0f2f5', type: 'dashed' } },
    },
    yAxis: {
      type: 'category',
      data: categories,
      axisLabel: { color: '#2d3239', fontSize: 12, fontWeight: 500 },
      axisLine: { show: false },
      axisTick: { show: false },
    },
    series: [{
      type: 'custom',
      renderItem,
      encode: { x: [1, 2], y: 0 },
      data: segments.map(s => [s.catIdx, s.start, s.end, s.state]),
      animationDuration: 600,
    }],
    legend: {
      data: [
        { name: '运行中', icon: 'roundRect', itemStyle: { color: GANTT_COLORS.running } },
        { name: '待机', icon: 'roundRect', itemStyle: { color: GANTT_COLORS.standby } },
      ],
      bottom: 0,
      textStyle: { color: '#8c939a', fontSize: 11 },
      itemWidth: 12, itemHeight: 8, itemGap: 16,
      selectedMode: false,
    },
  })
}

// ── 健康状态分布环形图 ──
const HEALTH_PIE_COLORS: Record<string, string> = {
  healthy:  '#4caf50',
  degraded: '#f59e0b',
  warning:  '#ef4444',
  unknown:  '#bdbdbd',
}

function renderHealthPie() {
  if (!healthPieRef.value) return
  const hist = deviceHistory.value
  if (!hist.length) { healthPieChart?.dispose(); healthPieChart = null; return }

  if (healthPieChart) healthPieChart.dispose()
  healthPieChart = echarts.init(healthPieRef.value)

  const counts: Record<string, number> = {}
  for (const h of hist) {
    const st = h.health_status || 'unknown'
    counts[st] = (counts[st] || 0) + 1
  }
  const total = hist.length
  const healthyCount = counts['healthy'] || 0
  const healthRate = total > 0 ? ((healthyCount / total) * 100).toFixed(1) : '0'

  const pieData = Object.entries(counts).map(([name, value]) => ({
    name: HEALTH_LABELS[name] || name,
    value,
    itemStyle: { color: HEALTH_PIE_COLORS[name] || HEALTH_PIE_COLORS.unknown },
  }))

  healthPieChart.setOption({
    tooltip: {
      trigger: 'item',
      formatter: '{b}: {c} 小时 ({d}%)',
      backgroundColor: 'rgba(255,255,255,0.96)',
      borderColor: '#eaedf0', borderWidth: 1,
      textStyle: { color: '#2d3239', fontSize: 12 },
      extraCssText: 'box-shadow:0 4px 16px rgba(0,0,0,0.08);border-radius:8px;',
    },
    legend: {
      bottom: 0, icon: 'circle',
      textStyle: { color: '#8c939a', fontSize: 11 },
      itemWidth: 8, itemHeight: 8, itemGap: 16,
    },
    graphic: [{
      type: 'group',
      left: 'center', top: 'middle',
      children: [
        {
          type: 'text',
          style: {
            text: `${healthRate}%`,
            fontSize: 22, fontWeight: 700, fill: '#2d3239',
            textAlign: 'center', textVerticalAlign: 'bottom',
          },
          left: 'center', top: -6,
        },
        {
          type: 'text',
          style: {
            text: '健康率',
            fontSize: 12, fill: '#8c939a',
            textAlign: 'center', textVerticalAlign: 'top',
          },
          left: 'center', top: 16,
        },
      ],
    }],
    series: [{
      type: 'pie',
      radius: ['50%', '72%'],
      center: ['50%', '45%'],
      avoidLabelOverlap: true,
      label: { show: false },
      emphasis: {
        label: { show: true, fontSize: 13, fontWeight: 600 },
        itemStyle: { shadowBlur: 10, shadowColor: 'rgba(0,0,0,0.12)' },
      },
      data: pieData,
      animationType: 'scale',
      animationDuration: 600,
    }],
  })
}

// ── 设备功率/流量趋势图 ──
function renderDeviceChart() {
  if (!deviceChartRef.value) return
  const hist = filteredHistory.value
  if (!hist.length) { deviceChart?.dispose(); deviceChart = null; return }

  if (deviceChart) deviceChart.dispose()
  deviceChart = echarts.init(deviceChartRef.value)

  const times = hist.map((h: any) => formatTs(h.timestamp))
  const series: any[] = []
  const yAxes: any[] = []
  const legends: string[] = []

  if (activeDeviceChart.value === 'ac') {
    yAxes.push(
      {
        type: 'value', name: '功率 kW', position: 'left',
        nameTextStyle: { color: '#ee6666', fontSize: 11 },
        axisLabel: { color: '#8c939a', fontSize: 11 },
        axisLine: { show: false }, axisTick: { show: false },
        splitLine: { lineStyle: { color: '#f0f2f5', type: 'dashed' } },
      },
      {
        type: 'value', name: '温度 °C', position: 'right',
        nameTextStyle: { color: '#5470c6', fontSize: 11 },
        axisLabel: { color: '#8c939a', fontSize: 11 },
        axisLine: { show: false }, axisTick: { show: false },
        splitLine: { show: false },
      },
    )
    series.push(
      {
        name: '空调功率', type: 'line', yAxisIndex: 0, smooth: true,
        data: hist.map((h: any) => h.power_kw != null ? +h.power_kw.toFixed(1) : null),
        lineStyle: { color: '#ee6666', width: 2.5 },
        itemStyle: { color: '#ee6666' },
        areaStyle: { color: 'rgba(238,102,102,0.08)' },
      },
      {
        name: '供水温度', type: 'line', yAxisIndex: 1, smooth: true,
        data: hist.map((h: any) => h.supply_temp_c != null ? +h.supply_temp_c.toFixed(1) : null),
        lineStyle: { color: '#5470c6', width: 2, type: 'dashed' },
        itemStyle: { color: '#5470c6' },
      },
      {
        name: '回水温度', type: 'line', yAxisIndex: 1, smooth: true,
        data: hist.map((h: any) => h.return_temp_c != null ? +h.return_temp_c.toFixed(1) : null),
        lineStyle: { color: '#73c0de', width: 2, type: 'dashed' },
        itemStyle: { color: '#73c0de' },
      },
    )
    legends.push('空调功率', '供水温度', '回水温度')
  } else if (activeDeviceChart.value === 'electricity') {
    yAxes.push({
      type: 'value', name: '功率 kW', position: 'left',
      nameTextStyle: { color: '#3ba272', fontSize: 11 },
      axisLabel: { color: '#8c939a', fontSize: 11 },
      axisLine: { show: false }, axisTick: { show: false },
      splitLine: { lineStyle: { color: '#f0f2f5', type: 'dashed' } },
    })
    series.push({
      name: '用电功率', type: 'bar', yAxisIndex: 0,
      data: hist.map((h: any) => h.power_kw != null ? +h.power_kw.toFixed(1) : null),
      itemStyle: { color: '#3ba272', borderRadius: [3, 3, 0, 0] },
      barMaxWidth: 20,
    })
    legends.push('用电功率')
  } else {
    yAxes.push({
      type: 'value', name: '流量 L', position: 'left',
      nameTextStyle: { color: '#5470c6', fontSize: 11 },
      axisLabel: { color: '#8c939a', fontSize: 11 },
      axisLine: { show: false }, axisTick: { show: false },
      splitLine: { lineStyle: { color: '#f0f2f5', type: 'dashed' } },
    })
    series.push({
      name: '用水流量', type: 'bar', yAxisIndex: 0,
      data: hist.map((h: any) => h.flow_rate != null ? +h.flow_rate.toFixed(1) : null),
      itemStyle: { color: '#5470c6', borderRadius: [3, 3, 0, 0] },
      barMaxWidth: 20,
    })
    legends.push('用水流量')
  }

  deviceChart.setOption({
    tooltip: {
      trigger: 'axis',
      backgroundColor: 'rgba(255,255,255,0.96)',
      borderColor: '#eaedf0', borderWidth: 1,
      textStyle: { color: '#2d3239', fontSize: 12 },
      padding: [10, 14],
      extraCssText: 'box-shadow:0 4px 16px rgba(0,0,0,0.08);border-radius:8px;',
    },
    legend: {
      data: legends, bottom: 0, icon: 'roundRect',
      itemWidth: 12, itemHeight: 8,
      textStyle: { color: '#8c939a', fontSize: 11 }, itemGap: 16,
    },
    grid: { left: 60, right: 60, top: 32, bottom: 44, containLabel: false },
    xAxis: {
      type: 'category', data: times,
      axisLabel: {
        rotate: times.length > 12 ? 40 : 0,
        color: '#8c939a', fontSize: 10,
        formatter: (v: string) => v.slice(5),
      },
      axisLine: { lineStyle: { color: '#e8ebee' } },
      axisTick: { show: false },
    },
    yAxis: yAxes,
    series,
    animationDuration: 500,
  })
}

// ── 全局 ──
function onResize() {
  chart?.resize()
  ganttChart?.resize()
  healthPieChart?.resize()
  deviceChart?.resize()
}

watch(activeDeviceChart, async () => {
  await nextTick()
  renderDeviceChart()
})

onMounted(() => {
  window.addEventListener('resize', onResize)
  document.addEventListener('click', closeQsDropdowns)
})
onUnmounted(() => {
  window.removeEventListener('resize', onResize)
  document.removeEventListener('click', closeQsDropdowns)
  chart?.dispose()
  ganttChart?.dispose()
  healthPieChart?.dispose()
  deviceChart?.dispose()
})
</script>

<style scoped>
.query-stats {
  padding: 28px 32px 24px;
  height: 100%;
  display: flex;
  flex-direction: column;
  overflow-y: auto;
  gap: 20px;
}

/* ── 筛选面板 ── */
.filter-panel {
  background: #fff;
  border: 1px solid #eaedf0;
  border-radius: 12px;
  padding: 20px 24px 16px;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.04), 0 1px 2px rgba(0, 0, 0, 0.02);
  flex-shrink: 0;
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

.filter-input:hover { border-color: #c8cdd3; background: #fff; }
.filter-input:focus {
  border-color: #4caf50;
  background: #fff;
  box-shadow: 0 0 0 3px rgba(76, 175, 80, 0.1);
}

/* ── 自定义下拉 ── */
.qs-dropdown {
  position: relative;
  display: flex;
  align-items: center;
  height: 38px;
  padding: 0 10px 0 12px;
  border: 1px solid #e2e5e9;
  border-radius: 8px;
  background: #fafbfc;
  cursor: pointer;
  user-select: none;
  transition: border-color 0.2s, box-shadow 0.2s, background 0.2s;
}
.qs-dropdown:hover { border-color: #c8cdd3; background: #fff; }
.qs-dropdown--open {
  border-color: #4caf50;
  background: #fff;
  box-shadow: 0 0 0 3px rgba(76, 175, 80, 0.1);
}
.qs-dropdown-value {
  flex: 1;
  font-size: 13px;
  color: #2d3239;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.qs-dropdown-arrow {
  color: #b0b6be;
  flex-shrink: 0;
  margin-left: 4px;
  transition: transform 0.2s ease, color 0.2s;
}
.qs-dropdown-arrow--open { transform: rotate(180deg); color: #4caf50; }

.qs-dropdown-list {
  position: absolute;
  top: calc(100% + 6px);
  left: 0; right: 0;
  background: #fff;
  border: 1.5px solid #e2e5e9;
  border-radius: 10px;
  box-shadow: 0 8px 24px rgba(0,0,0,0.10), 0 2px 8px rgba(0,0,0,0.06);
  overflow: hidden;
  z-index: 200;
  padding: 4px;
}
.qs-dropdown-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 10px;
  border-radius: 7px;
  font-size: 13px;
  font-weight: 500;
  color: #374151;
  cursor: pointer;
  transition: background 0.15s, color 0.15s;
}
.qs-dropdown-item:hover { background: #f0fdf4; color: #15803d; }
.qs-dropdown-item--selected { background: #dcfce7; color: #16a34a; font-weight: 600; }
.qs-dropdown-item--selected:hover { background: #bbf7d0; }
.qs-item-check { color: #22c55e; flex-shrink: 0; }

.qs-drop-enter-active { transition: opacity 0.15s ease, transform 0.15s ease; }
.qs-drop-leave-active { transition: opacity 0.1s ease, transform 0.1s ease; }
.qs-drop-enter-from  { opacity: 0; transform: translateY(-6px) scale(0.97); }
.qs-drop-leave-to    { opacity: 0; transform: translateY(-4px) scale(0.98); }

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
.report-btn {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 0 14px;
  height: 36px;
  border: 1px solid var(--border);
  border-radius: 8px;
  background: var(--bg-card);
  color: var(--text-secondary);
  font-size: 13px;
  font-weight: 500;
  cursor: pointer;
  transition: background 0.15s, color 0.15s, border-color 0.15s;
  flex-shrink: 0;
}
.report-btn:hover:not(:disabled) {
  background: rgba(91,141,238,0.1);
  color: var(--accent);
  border-color: var(--accent);
}
.report-btn:disabled { opacity: 0.4; cursor: not-allowed; }

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
.param-checkbox:hover { background: #f0f7f0; color: #2d3239; }
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
.param-checkbox.checked .check-box { background: #4caf50; border-color: #4caf50; }
.check-icon { color: #fff; }

.param-checkbox--device {
  border: 1.5px dashed #c8cdd3;
  border-radius: 8px;
  padding: 3px 10px 3px 4px;
  margin-left: 4px;
}
.param-checkbox--device.checked {
  border-color: #4caf50;
  background: #f0fdf4;
}
.param-special-icon { color: #8c939a; margin-left: -1px; }
.param-checkbox--device.checked .param-special-icon { color: #4caf50; }

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
  background: #fff;
  border: 1px solid #eaedf0;
  border-radius: 12px;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.04), 0 1px 2px rgba(0, 0, 0, 0.02);
  display: flex;
  flex-direction: column;
  overflow: hidden;
  flex-shrink: 0;
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
.chart-card-actions { display: flex; gap: 4px; }
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
.card-action-btn:hover { background: #f5f6f8; color: #636a73; }
.chart-container {
  min-height: 380px;
  padding: 8px 16px 12px;
}

/* ── 数据表格 ── */
.data-table-wrap {
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
.data-table tbody tr:hover td { background: #f0f7f0; }
.data-table .sticky-col { position: sticky; left: 0; z-index: 1; }
.data-table thead .sticky-col { z-index: 3; background: #f8f9fa; }
.data-table tbody .sticky-col { background: #fff; }
.data-table tbody tr:hover .sticky-col { background: #f0f7f0; }
.date-cell { font-weight: 500; color: #4caf50; }
.num-cell { text-align: right; font-variant-numeric: tabular-nums; }
.data-table thead th:not(.sticky-col) { text-align: right; }

/* ── 空状态 ── */
.content-placeholder {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: 240px;
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
.empty-title { font-size: 15px; font-weight: 600; color: #8c939a; margin: 0; }
.empty-desc { font-size: 13px; color: #b0b6be; margin: 0; }

/* ── 骨架屏 ── */
.skeleton-card { padding: 20px 24px; }
.skeleton-header { display: flex; align-items: center; gap: 12px; margin-bottom: 32px; }
.skeleton-line {
  border-radius: 6px;
  background: linear-gradient(90deg, #f0f2f5 25%, #e8ebee 50%, #f0f2f5 75%);
  background-size: 200% 100%;
  animation: shimmer 1.5s ease-in-out infinite;
}
.skeleton-title-line { width: 160px; height: 18px; }
.skeleton-badge-line { width: 100px; height: 14px; }
.skeleton-table { display: flex; flex-direction: column; gap: 0; }
.skeleton-table-head { display: flex; gap: 20px; padding: 12px 16px; border-bottom: 2px solid #eaedf0; }
.skeleton-th { width: 80px; height: 14px; flex-shrink: 0; }
.skeleton-th:first-child { width: 90px; }
.skeleton-table-row { display: flex; gap: 20px; padding: 11px 16px; border-bottom: 1px solid #f0f2f5; }
.skeleton-td { height: 13px; flex-shrink: 0; }
.skeleton-chart { display: flex; align-items: flex-end; gap: 8px; height: 320px; padding-top: 20px; }
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

/* ══════════════════════════════════════════════════════════
   设备运行状态样式
══════════════════════════════════════════════════════════ */

/* 区块卡片 */
.section-card {
  background: #fff;
  border: 1px solid #eaedf0;
  border-radius: 12px;
  box-shadow: 0 1px 3px rgba(0,0,0,0.04);
  overflow: hidden;
  flex-shrink: 0;
}
.section-card-header {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 15px 20px;
  border-bottom: 1px solid #f0f2f5;
  font-size: 14px;
  font-weight: 600;
  color: #2d3239;
  flex-wrap: wrap;
}
.section-icon { color: #4caf50; flex-shrink: 0; }
.section-icon--warn { color: #f59e0b; }
.section-subtitle {
  font-size: 12px;
  font-weight: 400;
  color: #b0b6be;
  margin-left: 2px;
}
.section-badge {
  font-size: 11px;
  font-weight: 600;
  padding: 2px 10px;
  border-radius: 10px;
  margin-left: 4px;
}
.section-badge--warn { background: #fef3c7; color: #d97706; }
.section-badge--ok   { background: #dcfce7; color: #16a34a; }

/* 设备卡片网格 */
.device-cards-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 16px;
  padding: 16px 20px;
}

/* 单设备卡片 */
.dev-card {
  border: 1.5px solid #eaedf0;
  border-radius: 10px;
  padding: 16px;
  transition: box-shadow 0.2s, border-color 0.2s;
  background: #fafbfc;
}
.dev-card:hover { box-shadow: 0 4px 14px rgba(0,0,0,0.07); }
.dev-card.health-warning { border-color: #fca5a5; background: #fff8f8; }
.dev-card.health-degraded { border-color: #fcd34d; background: #fffdf0; }

.dev-card-head {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  margin-bottom: 14px;
}
.dev-icon-wrap {
  width: 40px;
  height: 40px;
  border-radius: 10px;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}
.dev-icon--ac          { background: #fee2e2; color: #ef4444; }
.dev-icon--electricity { background: #d1fae5; color: #059669; }
.dev-icon--water       { background: #dbeafe; color: #3b82f6; }

.dev-title-group { flex: 1; min-width: 0; }
.dev-name {
  display: block;
  font-size: 14px;
  font-weight: 600;
  color: #2d3239;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.dev-id {
  display: block;
  font-size: 11px;
  color: #b0b6be;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  margin-top: 2px;
}

.dev-badges {
  display: flex;
  flex-direction: column;
  gap: 4px;
  align-items: flex-end;
  flex-shrink: 0;
}
.dev-badge {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: 11px;
  font-weight: 600;
  padding: 2px 8px;
  border-radius: 10px;
  white-space: nowrap;
}
.badge-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: currentColor;
  flex-shrink: 0;
}
.badge-run-running { background: #dcfce7; color: #16a34a; }
.badge-run-standby { background: #f5f6f8; color: #8c939a; }
.badge-run-unknown { background: #f5f6f8; color: #b0b6be; }
.badge-health-healthy  { background: #dcfce7; color: #16a34a; }
.badge-health-degraded { background: #fef3c7; color: #d97706; }
.badge-health-warning  { background: #fee2e2; color: #dc2626; }
.badge-health-unknown  { background: #f5f6f8; color: #b0b6be; }

/* 设备指标行 */
.dev-metrics {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 8px;
}
.dev-metric {
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding: 8px 10px;
  background: #fff;
  border: 1px solid #f0f2f5;
  border-radius: 7px;
}
.dev-metric--full { grid-column: 1 / -1; }
.dev-metric-label {
  display: flex;
  align-items: center;
  gap: 3px;
  font-size: 11px;
  color: #b0b6be;
}
.dev-metric-value {
  font-size: 14px;
  font-weight: 600;
  color: #2d3239;
  font-variant-numeric: tabular-nums;
}
.dev-metric-time {
  font-size: 12px;
  font-weight: 400;
  color: #8c939a;
}
.val-warn  { color: #dc2626; }
.val-mild  { color: #d97706; }

/* 设备图表区域 */
.device-charts-row {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 20px;
}
.device-charts-row-item { min-width: 0; }

.device-chart-tabs {
  display: flex;
  gap: 4px;
  margin-left: 8px;
}
.dev-tab-btn {
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 4px 12px;
  font-size: 12px;
  font-weight: 500;
  border: 1.5px solid #e8ebee;
  border-radius: 14px;
  background: transparent;
  color: #8c939a;
  cursor: pointer;
  transition: all 0.15s;
}
.dev-tab-btn:hover { background: #f0fdf4; color: #16a34a; border-color: #86efac; }
.dev-tab-btn.active {
  background: #4caf50;
  color: #fff;
  border-color: #4caf50;
  box-shadow: 0 2px 6px rgba(76,175,80,0.25);
}
.device-chart-container {
  min-height: 320px;
  padding: 8px 16px 12px;
}
.device-chart-container--half {
  min-height: 280px;
}
.dev-chart-empty {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 10px;
  height: 140px;
  color: #b0b6be;
  font-size: 13px;
}

/* 归因列表 */
.attrib-empty {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 10px;
  padding: 32px 20px;
  color: #4caf50;
  font-size: 14px;
}
.attrib-table-wrap {
  overflow-x: auto;
  padding: 0 20px 12px;
}
.attrib-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 12.5px;
  white-space: nowrap;
}
.attrib-table thead th {
  padding: 10px 12px;
  font-size: 12px;
  font-weight: 600;
  color: #636a73;
  text-align: left;
  border-bottom: 2px solid #e8ebee;
  background: #f8f9fa;
  position: sticky;
  top: 0;
}
.attrib-table tbody td {
  padding: 9px 12px;
  color: #2d3239;
  border-bottom: 1px solid #f0f2f5;
  vertical-align: middle;
}
.attrib-table tbody tr:hover td { background: #f0f7f0; }
.attrib-table .num-col { text-align: right; font-variant-numeric: tabular-nums; }

.ts-cell { color: #8c939a; font-size: 12px; }

.dev-type-chip {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: 11px;
  font-weight: 600;
  padding: 2px 8px;
  border-radius: 8px;
}
.chip-ac          { background: #fee2e2; color: #dc2626; }
.chip-electricity { background: #dcfce7; color: #16a34a; }
.chip-water       { background: #dbeafe; color: #2563eb; }

.rule-chip {
  display: inline-block;
  font-size: 11px;
  padding: 2px 8px;
  border-radius: 8px;
  background: #f5f6f8;
  color: #636a73;
  font-weight: 500;
}

.score-cell {
  display: flex;
  align-items: center;
  gap: 8px;
  justify-content: flex-end;
}
.score-bar-wrap {
  width: 48px;
  height: 5px;
  background: #e8ebee;
  border-radius: 3px;
  overflow: hidden;
  flex-shrink: 0;
}
.score-bar {
  height: 100%;
  background: linear-gradient(90deg, #4caf50, #fac858);
  border-radius: 3px;
  transition: width 0.4s ease;
}

.reason-cell {
  max-width: 220px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  color: #636a73;
}

/* 设备汇总行 */
.device-summary-row {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 20px 12px;
  flex-wrap: wrap;
  border-top: 1px solid #f0f2f5;
}
.summary-label {
  font-size: 12px;
  color: #8c939a;
  font-weight: 500;
}
.summary-chip {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  font-size: 12px;
  font-weight: 600;
  padding: 3px 10px;
  background: #fff8e6;
  border: 1px solid #fde68a;
  border-radius: 10px;
  color: #b45309;
}
.summary-count {
  font-size: 11px;
  font-weight: 700;
  background: #fef3c7;
  padding: 1px 6px;
  border-radius: 6px;
  color: #d97706;
}

/* ── 响应式 ── */
@media (max-width: 1024px) {
  .query-stats { padding: 20px 20px 16px; }
  .filter-row { gap: 10px; }
  .filter-item { min-width: 120px; }
  .filter-bottom { flex-direction: column; align-items: flex-start; }
  .device-cards-grid { grid-template-columns: repeat(2, 1fr); }
  .device-charts-row { grid-template-columns: 1fr; }
}

@media (max-width: 768px) {
  .query-stats { padding: 16px 14px 12px; }
  .filter-panel { padding: 16px 16px 12px; border-radius: 10px; }
  .filter-row { flex-direction: column; align-items: stretch; gap: 10px; }
  .filter-item { min-width: 0; flex: none; }
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
  .device-cards-grid { grid-template-columns: 1fr; }
  .device-charts-row { grid-template-columns: 1fr; }
}

@media (max-width: 480px) {
  .query-stats { padding: 12px 10px 8px; }
  .filter-panel { padding: 12px 12px 10px; }
  .chart-container { min-height: 240px; }
  .params-label { font-size: 12px; }
}

@media (prefers-reduced-motion: reduce) {
  .toggle-slider { transition: none; }
  .query-btn { transition: none; }
  .skeleton-line, .skeleton-bar { animation: none; background: #f0f2f5; }
  .spin { animation: none; }
  .score-bar { transition: none; }
}
</style>
