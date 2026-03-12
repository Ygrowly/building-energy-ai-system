<template>
  <div class="dashboard">
    <!-- 加载状态 -->
    <div v-if="loading" class="loading-bar">正在加载数据...</div>
    <div v-if="error" class="error-bar"><Icon icon="mdi:alert" width="14" class="bar-icon" /> {{ error }}</div>

    <!-- KPI 卡片 -->
    <div class="kpi-grid">
      <div class="kpi-card" v-for="kpi in kpis" :key="kpi.label">
        <div class="kpi-icon"><Icon :icon="kpi.icon" width="28" /></div>
        <div class="kpi-body">
          <div class="kpi-value">{{ kpi.value }}</div>
          <div class="kpi-label">{{ kpi.label }}</div>
        </div>
        <div v-if="kpi.trend !== null" class="kpi-trend" :class="kpi.trend > 0 ? 'up' : 'down'">
          {{ kpi.trend > 0 ? '▲' : '▼' }} {{ Math.abs(kpi.trend) }}%
        </div>
        <div v-else class="kpi-trend neutral">—</div>
      </div>
    </div>

    <!-- 建筑选择器（胶囊滑动样式） -->
    <div class="building-selector-wrap">
      <div class="building-selector">
        <!-- 滑动指示器 -->
        <div class="selector-indicator"></div>
        <!-- 选项 -->
        <button
          v-for="b in buildingStore.buildings"
          :key="b.building_type"
          class="selector-option"
          :class="{ active: selectedBuildingType === b.building_type }"
          @click="selectBuilding(b.building_type)"
        >
          {{ b.display_name }}
        </button>
      </div>
    </div>

    <!-- 当前选中建筑设备状态 -->
    <section class="section" v-if="currentBuildingData">
      <h2 class="section-title">
        <Icon :icon="getBuildingIcon(selectedBuildingType)" width="16" class="title-icon" />
        {{ currentBuildingData.display_name }} — 设备状态
      </h2>
      <div class="building-detail" :class="currentBuildingData.operation_status !== 'Normal' ? 'anomaly' : ''">
        <div class="detail-header">
          <div class="detail-name-row">
            <span class="detail-icon"><Icon :icon="getBuildingIcon(selectedBuildingType)" width="24" /></span>
            <span class="detail-name">{{ currentBuildingData.display_name }}</span>
            <span class="status-chip" :class="currentBuildingData.operation_status !== 'Normal' ? 'anomaly' : 'normal'">
              <Icon :icon="currentBuildingData.operation_status !== 'Normal' ? 'mdi:alert-circle' : 'mdi:check-circle'" width="12" />
              {{ currentBuildingData.operation_status !== 'Normal' ? currentBuildingData.operation_status : '正常运行' }}
            </span>
          </div>
          <div class="detail-meta">
            建筑面积 {{ currentBuildingData.sqm ? currentBuildingData.sqm.toLocaleString() : '—' }} ㎡
            · 设备 ID：{{ currentBuildingData.meter_device_id ?? '—' }}
            · 数据日期：{{ dataDate }}
          </div>
        </div>
        <div class="detail-metrics">
          <div class="detail-metric">
            <div class="dm-icon electricity"><Icon icon="mdi:lightning-bolt" width="22" /></div>
            <div class="dm-body">
              <div class="dm-value">{{ (currentBuildingData.total_electricity_kwh ?? 0).toFixed(1) }}</div>
              <div class="dm-label">日用电 (kWh)</div>
            </div>
          </div>
          <div class="detail-metric">
            <div class="dm-icon water"><Icon icon="mdi:water" width="22" /></div>
            <div class="dm-body">
              <div class="dm-value">{{ (currentBuildingData.total_water_m3 ?? 0).toFixed(1) }}</div>
              <div class="dm-label">日用水 (m³)</div>
            </div>
          </div>
          <div class="detail-metric">
            <div class="dm-icon temp"><Icon icon="mdi:thermometer" width="22" /></div>
            <div class="dm-body">
              <div class="dm-value">{{ (currentBuildingData.avg_ambient_temp ?? 0).toFixed(1) }}°C</div>
              <div class="dm-label">平均气温</div>
            </div>
          </div>
          <div class="detail-metric">
            <div class="dm-icon intensity"><Icon icon="mdi:ruler-square" width="22" /></div>
            <div class="dm-body">
              <div class="dm-value">{{ currentBuildingData.energy_intensity_kwh_per_sqm ?? '—' }}</div>
              <div class="dm-label">能耗强度 (kWh/㎡)</div>
            </div>
          </div>
          <div class="detail-metric">
            <div class="dm-icon people"><Icon icon="mdi:account-group" width="22" /></div>
            <div class="dm-body">
              <div class="dm-value">{{ currentBuildingData.occupancy_count ?? '—' }}</div>
              <div class="dm-label">在场人数</div>
            </div>
          </div>
        </div>
      </div>
    </section>

    <!-- 异常告警区块 -->
    <section class="section">
      <div class="section-header">
        <h2 class="section-title"><Icon icon="mdi:alert-circle" width="16" class="title-icon" /> 异常告警</h2>
        <button class="refresh-btn" @click="fetchAnomalies" :disabled="anomalyLoading">
          <Icon :icon="anomalyLoading ? 'mdi:loading' : 'mdi:refresh'" width="14" class="btn-icon" />
          {{ anomalyLoading ? '刷新中...' : '刷新' }}
        </button>
      </div>

      <!-- 来自 Overview 的楼宇级异常 -->
      <div v-if="anomalyBuildings.length > 0" class="anomaly-list">
        <div class="anomaly-item" v-for="b in anomalyBuildings" :key="b.building_type">
          <div class="anomaly-left">
            <span class="anomaly-priority high">HIGH</span>
            <div>
              <p class="anomaly-title">{{ b.display_name }} — 运行状态异常 ({{ b.operation_status }})</p>
              <p class="anomaly-meta">数据日期：{{ dataDate }} · 最新用电：{{ (b.total_electricity_kwh ?? 0).toFixed(1) }} kWh</p>
            </div>
          </div>
          <span class="anomaly-status pending">待处理</span>
        </div>
      </div>

      <!-- 来自 /api/anomalies/recent 的规则告警 -->
      <div v-if="recentAnomalies.length > 0" class="anomaly-list" style="margin-top: 8px;">
        <div class="anomaly-item" v-for="(a, idx) in recentAnomalies.slice(0, 10)" :key="idx">
          <div class="anomaly-left">
            <span class="anomaly-priority medium">RULE</span>
            <div>
              <p class="anomaly-title">{{ a.message }}</p>
              <p class="anomaly-meta">{{ formatTime(a.timestamp) }} · 设备 {{ a.meter_device_id }}</p>
            </div>
          </div>
          <span class="anomaly-status" :class="a.operation_status === 'Anomaly' ? 'alert' : 'warn'">
            {{ a.operation_status ?? '—' }}
          </span>
        </div>
      </div>

      <!-- 全部正常 -->
      <div
        v-if="!anomalyLoading && anomalyBuildings.length === 0 && recentAnomalies.length === 0"
        class="no-anomaly"
      >
        <Icon icon="mdi:check-circle" width="16" class="bar-icon" /> 所有楼宇当前运行正常，暂无告警记录
      </div>

      <div v-if="anomalyError" class="error-bar" style="margin-top: 8px;">
        <Icon icon="mdi:alert" width="14" class="bar-icon" /> 告警加载失败：{{ anomalyError }}
      </div>
    </section>

    <!-- 能耗趋势查询 -->
    <section class="section">
      <h2 class="section-title"><Icon icon="mdi:trending-up" width="16" class="title-icon" /> 能耗趋势查询</h2>

      <!-- 查询表单 -->
      <div class="query-form">
        <div class="form-row">
          <div class="form-item">
            <label class="form-label">楼宇</label>
            <select v-model="trendForm.buildingType" class="form-select">
              <option v-for="b in buildingStore.buildings" :key="b.building_type" :value="b.building_type">
                {{ b.display_name }}
              </option>
            </select>
          </div>
          <div class="form-item">
            <label class="form-label">开始日期</label>
            <input type="date" v-model="trendForm.startDate" class="form-input" min="2016-04-01" max="2016-05-02" />
          </div>
          <div class="form-item">
            <label class="form-label">结束日期</label>
            <input type="date" v-model="trendForm.endDate" class="form-input" min="2016-04-01" max="2016-05-02" />
          </div>
          <div class="form-item">
            <label class="form-label">图表类型</label>
            <select v-model="trendForm.chartType" class="form-select form-select-sm">
              <option value="mixed">混合（折线+柱状）</option>
              <option value="line">折线图</option>
              <option value="bar">柱状图</option>
            </select>
          </div>
          <button class="query-btn" @click="fetchTrend" :disabled="trendLoading">
            <Icon icon="mdi:magnify" width="14" class="btn-icon" />
            {{ trendLoading ? '查询中...' : '查询' }}
          </button>
        </div>
        <div class="params-row">
          <span class="form-label" style="white-space:nowrap;">监测参数</span>
          <label class="param-check" v-for="p in paramOptions" :key="p.key">
            <input type="checkbox" v-model="trendForm.params" :value="p.key" class="form-check" />
            <span>{{ p.label }}</span>
          </label>
        </div>
        <p class="form-hint">数据库有效范围：2016-04-01 ~ 2016-05-02</p>
      </div>

      <!-- 加载 / 错误 -->
      <div v-if="trendLoading" class="loading-bar" style="margin-top:12px;">正在加载能耗数据...</div>
      <div v-if="trendError" class="error-bar" style="margin-top:12px;">
        <Icon icon="mdi:alert" width="14" class="bar-icon" /> {{ trendError }}
      </div>

      <!-- 查询结果 -->
      <div v-if="trendData.length > 0" class="trend-results">

        <!-- 图表区域 -->
        <div class="chart-container">
          <div class="chart-header">
            <span class="chart-title">
              {{ trendBuildingName }} · 能耗趋势
              <span class="chart-range">（{{ trendForm.startDate }} ~ {{ trendForm.endDate }}）</span>
            </span>
            <span class="chart-source">数据来源：daily_energy_summary 物化视图</span>
          </div>
          <div ref="chartEl" class="chart-body"></div>
        </div>

        <!-- 数据明细表 -->
        <div class="data-table-section">
          <div class="table-header">
            <span class="table-title"><Icon icon="mdi:table" width="14" class="title-icon" /> 数据明细</span>
            <span class="table-count">共 {{ trendData.length }} 条记录</span>
          </div>
          <div class="data-table-wrap">
            <table class="data-table">
              <thead>
                <tr>
                  <th>日期</th>
                  <th v-if="trendForm.params.includes('electricity')">日用电 (kWh)</th>
                  <th v-if="trendForm.params.includes('water')">日用水 (m³)</th>
                  <th v-if="trendForm.params.includes('temperature')">平均气温 (°C)</th>
                  <th v-if="trendForm.params.includes('intensity')">能耗强度 (kWh/㎡)</th>
                  <th v-if="trendForm.params.includes('occupancy')">在场人数</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="(row, idx) in trendData" :key="idx">
                  <td>{{ formatDay(row.day) }}</td>
                  <td v-if="trendForm.params.includes('electricity')" class="num-cell">
                    {{ row.total_electricity_kwh != null ? Number(row.total_electricity_kwh).toFixed(2) : '—' }}
                  </td>
                  <td v-if="trendForm.params.includes('water')" class="num-cell">
                    {{ row.total_water_m3 != null ? Number(row.total_water_m3).toFixed(2) : '—' }}
                  </td>
                  <td v-if="trendForm.params.includes('temperature')" class="num-cell">
                    {{ row.avg_ambient_temp != null ? Number(row.avg_ambient_temp).toFixed(1) : '—' }}
                  </td>
                  <td v-if="trendForm.params.includes('intensity')" class="num-cell">
                    {{ computeIntensity(row) }}
                  </td>
                  <td v-if="trendForm.params.includes('occupancy')" class="num-cell">
                    {{ row.occupancy_count ?? '—' }}
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>

        <!-- 统计报表 -->
        <div class="report-card">
          <div class="report-header">
            <div class="report-title-row">
              <span class="report-title"><Icon icon="mdi:file-chart" width="16" class="title-icon" /> 统计报表</span>
              <span class="report-meta">{{ trendBuildingName }} · {{ trendForm.startDate }} ~ {{ trendForm.endDate }}</span>
            </div>
            <div class="report-actions">
              <button class="export-btn csv-btn" @click="exportCSV">
                <Icon icon="mdi:download" width="14" class="btn-icon" /> 导出 CSV
              </button>
              <button class="export-btn json-btn" @click="exportJSON">
                <Icon icon="mdi:code-json" width="14" class="btn-icon" /> 导出 JSON
              </button>
            </div>
          </div>
          <div class="stats-grid">
            <!-- 用电统计 -->
            <template v-if="trendForm.params.includes('electricity')">
              <div class="stat-group">
                <div class="stat-group-title"><Icon icon="mdi:lightning-bolt" width="13" /> 用电量 (kWh)</div>
                <div class="stat-items">
                  <div class="stat-item">
                    <span class="stat-label">合计</span>
                    <span class="stat-val electricity">{{ stats.elec.total.toFixed(1) }}</span>
                  </div>
                  <div class="stat-item">
                    <span class="stat-label">日均</span>
                    <span class="stat-val electricity">{{ stats.elec.avg.toFixed(2) }}</span>
                  </div>
                  <div class="stat-item">
                    <span class="stat-label">最大</span>
                    <span class="stat-val electricity">{{ stats.elec.max.toFixed(2) }}</span>
                  </div>
                  <div class="stat-item">
                    <span class="stat-label">最小</span>
                    <span class="stat-val electricity">{{ stats.elec.min.toFixed(2) }}</span>
                  </div>
                </div>
              </div>
            </template>
            <!-- 用水统计 -->
            <template v-if="trendForm.params.includes('water')">
              <div class="stat-group">
                <div class="stat-group-title"><Icon icon="mdi:water" width="13" /> 用水量 (m³)</div>
                <div class="stat-items">
                  <div class="stat-item">
                    <span class="stat-label">合计</span>
                    <span class="stat-val water">{{ stats.water.total.toFixed(1) }}</span>
                  </div>
                  <div class="stat-item">
                    <span class="stat-label">日均</span>
                    <span class="stat-val water">{{ stats.water.avg.toFixed(2) }}</span>
                  </div>
                  <div class="stat-item">
                    <span class="stat-label">最大</span>
                    <span class="stat-val water">{{ stats.water.max.toFixed(2) }}</span>
                  </div>
                  <div class="stat-item">
                    <span class="stat-label">最小</span>
                    <span class="stat-val water">{{ stats.water.min.toFixed(2) }}</span>
                  </div>
                </div>
              </div>
            </template>
            <!-- 气温统计 -->
            <template v-if="trendForm.params.includes('temperature')">
              <div class="stat-group">
                <div class="stat-group-title"><Icon icon="mdi:thermometer" width="13" /> 环境温度 (°C)</div>
                <div class="stat-items">
                  <div class="stat-item">
                    <span class="stat-label">平均</span>
                    <span class="stat-val temp">{{ stats.temp.avg.toFixed(1) }}</span>
                  </div>
                  <div class="stat-item">
                    <span class="stat-label">最高</span>
                    <span class="stat-val temp">{{ stats.temp.max.toFixed(1) }}</span>
                  </div>
                  <div class="stat-item">
                    <span class="stat-label">最低</span>
                    <span class="stat-val temp">{{ stats.temp.min.toFixed(1) }}</span>
                  </div>
                  <div class="stat-item">
                    <span class="stat-label">记录天数</span>
                    <span class="stat-val temp">{{ trendData.length }}</span>
                  </div>
                </div>
              </div>
            </template>
          </div>
        </div>
      </div>

      <!-- 空状态 -->
      <div class="empty-chart" v-else-if="!trendLoading && !trendError">
        <div class="empty-icon"><Icon icon="mdi:chart-timeline-variant" width="44" /></div>
        <p>选择楼宇、日期范围和监测参数后点击查询</p>
        <p class="empty-sub">查询结果将同时展示趋势图表、数据明细表和统计报表</p>
      </div>
    </section>

    <!-- 提示用户使用 AI -->
    <div class="ai-hint">
      <Icon icon="mdi:lightbulb" width="16" class="bar-icon" />
      <span>提示：在右侧控制台询问 AI 进行深度分析，例如「办公楼今天有没有能耗异常？」</span>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, computed, watch, nextTick } from 'vue'
import { Icon } from '@iconify/vue'
import * as echarts from 'echarts'
import { apiFetch } from '@/api/http'
import { useBuildingStore } from '@/stores/buildingStore'

const buildingStore = useBuildingStore()

// ── 状态 ─────────────────────────────────────────────
const loading = ref(true)
const error = ref('')
const overviewData = ref<any>(null)
const dataDate = ref('')

const anomalyLoading = ref(false)
const anomalyError = ref('')
const recentAnomalies = ref<any[]>([])

// ── 选中建筑 ─────────────────────────────────────────
const selectedBuildingType = ref('Office')

// 胶囊选择器：滑动指示器定位用
const selectedBuildingIndex = computed(() =>
  buildingStore.buildings.findIndex(b => b.building_type === selectedBuildingType.value)
)
const numBuildings = computed(() => buildingStore.buildings.length || 1)

function selectBuilding(type: string) {
  selectedBuildingType.value = type
  // 同步到趋势查询表单
  trendForm.value.buildingType = type
}

// ── 获取 Overview 数据 ───────────────────────────────
async function fetchOverview() {
  loading.value = true
  error.value = ''
  try {
    const data = await apiFetch<any>('/api/overview')
    overviewData.value = data
    dataDate.value = data?.data_date ?? ''
    // 初始化选中第一个楼宇
    const buildings: any[] = data?.buildings ?? []
    if (buildings.length > 0) {
      selectedBuildingType.value = buildings[0].building_type
      trendForm.value.buildingType = buildings[0].building_type
    }
  } catch (e: any) {
    error.value = `数据加载失败：${e.message}`
  } finally {
    loading.value = false
  }
}

// ── 获取近期规则告警 ─────────────────────────────────
async function fetchAnomalies() {
  anomalyLoading.value = true
  anomalyError.value = ''
  try {
    const data = await apiFetch<any>('/api/anomalies/recent?hours=168')
    recentAnomalies.value = data?.anomalies ?? []
  } catch (e: any) {
    anomalyError.value = e.message
  } finally {
    anomalyLoading.value = false
  }
}

onMounted(() => {
  buildingStore.fetchBuildings()
  fetchOverview()
  fetchAnomalies()
})

// ── KPI 卡片 ─────────────────────────────────────────
const kpis = computed(() => {
  if (!overviewData.value) {
    return [
      { icon: 'mdi:lightning-bolt',  label: '日总用电 (kWh)',       value: '—', trend: null },
      { icon: 'mdi:water',           label: '当前用水 (m³)',         value: '—', trend: null },
      { icon: 'mdi:ruler-square',    label: '综合能耗强度 (kWh/㎡)', value: '—', trend: null },
      { icon: 'mdi:alert',           label: '异常楼宇数',            value: '—', trend: null },
    ]
  }
  const k = overviewData.value.kpis
  const buildings: any[] = overviewData.value.buildings ?? []
  const totalSqm = buildings.reduce((s: number, b: any) => s + (b.sqm ?? 0), 0)
  const intensity = totalSqm > 0
    ? buildings.reduce((s: number, b: any) => s + (b.total_electricity_kwh ?? 0), 0) / totalSqm
    : 0

  return [
    { icon: 'mdi:lightning-bolt', label: '日总用电 (kWh)',       value: Number(k.total_electricity_kwh).toFixed(1), trend: null },
    { icon: 'mdi:water',          label: '当前用水 (m³)',         value: Number(k.total_water_m3).toFixed(1),        trend: null },
    { icon: 'mdi:ruler-square',   label: '综合能耗强度 (kWh/㎡)', value: intensity.toFixed(3),                       trend: null },
    { icon: 'mdi:alert-circle',   label: '异常楼宇数',            value: String(k.anomaly_count),                    trend: null },
  ]
})

// ── 当前选中建筑数据 ─────────────────────────────────
const currentBuildingData = computed(() => {
  const buildings: any[] = overviewData.value?.buildings ?? []
  const bStore = buildingStore.buildings
  const found = buildings.find((b: any) => b.building_type === selectedBuildingType.value)
  if (!found) return null
  // 合并 buildingStore 中的额外字段（如 sqm, meter_device_id）
  const extra = bStore.find(b => b.building_type === selectedBuildingType.value)
  return { ...found, sqm: extra?.sqm, meter_device_id: extra?.meter_device_id }
})

// ── 楼宇级异常（从 overview 中过滤非 Normal 状态） ───
const anomalyBuildings = computed(() => {
  const buildings: any[] = overviewData.value?.buildings ?? []
  return buildings.filter((b: any) => b.operation_status && b.operation_status !== 'Normal')
})

// ── 能耗趋势查询 ─────────────────────────────────────
const paramOptions = [
  { key: 'electricity', label: '日用电 (kWh)' },
  { key: 'water',       label: '日用水 (m³)' },
  { key: 'temperature', label: '环境温度 (°C)' },
  { key: 'intensity',   label: '能耗强度 (kWh/㎡)' },
  { key: 'occupancy',   label: '在场人数' },
]

const trendForm = ref({
  buildingType: 'Office',
  startDate: '2016-04-01',
  endDate: '2016-05-02',
  chartType: 'mixed',
  params: ['electricity', 'temperature'],
})

const trendLoading = ref(false)
const trendError = ref('')
const trendData = ref<any[]>([])
const trendBuildingName = ref('')

const chartEl = ref<HTMLElement | null>(null)
let chartInstance: echarts.ECharts | null = null

// 同步 buildingStore 楼宇列表到 trendForm
watch(() => buildingStore.buildings, (list) => {
  if (list.length > 0 && !list.find(b => b.building_type === trendForm.value.buildingType)) {
    trendForm.value.buildingType = list[0].building_type
  }
}, { immediate: true })

async function fetchTrend() {
  const { buildingType, startDate, endDate, params } = trendForm.value
  if (!buildingType || !startDate || !endDate) return

  trendLoading.value = true
  trendError.value = ''
  trendData.value = []
  destroyChart()

  try {
    const includeWater = params.includes('water')
    const url = `/api/buildings/${buildingType}/energy?start_date=${startDate}&end_date=${endDate}&include_water=${includeWater}`
    const data = await apiFetch<any>(url)
    trendData.value = data?.records ?? []
    trendBuildingName.value =
      buildingStore.buildings.find(b => b.building_type === buildingType)?.display_name ??
      buildingType
    await nextTick()
    renderChart()
  } catch (e: any) {
    trendError.value = e.message
  } finally {
    trendLoading.value = false
  }
}

function renderChart() {
  if (!chartEl.value || trendData.value.length === 0) return
  destroyChart()
  chartInstance = echarts.init(chartEl.value, 'dark')

  const days = trendData.value.map((r: any) => (r.day ?? '').slice(5, 10))
  const elec  = trendData.value.map((r: any) => +(r.total_electricity_kwh ?? 0).toFixed(2))
  const temp  = trendData.value.map((r: any) => +(r.avg_ambient_temp ?? 0).toFixed(1))
  const water = trendData.value.map((r: any) => +(r.total_water_m3 ?? 0).toFixed(2))
  const { chartType, params } = trendForm.value

  const series: echarts.SeriesOption[] = []

  if (params.includes('electricity')) {
    series.push({
      name: '日用电 (kWh)',
      type: chartType === 'bar' ? 'bar' : 'line',
      yAxisIndex: 0,
      data: elec,
      smooth: true,
      lineStyle: { color: '#60a5fa', width: 2 },
      areaStyle: chartType !== 'bar' ? {
        color: {
          type: 'linear', x: 0, y: 0, x2: 0, y2: 1,
          colorStops: [
            { offset: 0, color: 'rgba(96,165,250,0.30)' },
            { offset: 1, color: 'rgba(96,165,250,0.02)' },
          ],
        },
      } : undefined,
      itemStyle: { color: '#60a5fa', borderRadius: chartType === 'bar' ? [3, 3, 0, 0] : undefined },
      barMaxWidth: 18,
    })
  }

  if (params.includes('water')) {
    series.push({
      name: '日用水 (m³)',
      type: chartType === 'line' ? 'line' : 'bar',
      yAxisIndex: 0,
      data: water,
      smooth: true,
      barMaxWidth: 14,
      itemStyle: { color: 'rgba(34,211,238,0.7)', borderRadius: [3, 3, 0, 0] },
      lineStyle: { color: '#22d3ee', width: 2, type: 'dashed' },
    })
  }

  if (params.includes('temperature')) {
    series.push({
      name: '平均气温 (°C)',
      type: 'line',
      yAxisIndex: 1,
      data: temp,
      smooth: true,
      lineStyle: { color: '#fbbf24', width: 2, type: 'dashed' },
      itemStyle: { color: '#fbbf24' },
      symbol: 'none',
    })
  }

  chartInstance.setOption({
    backgroundColor: 'transparent',
    grid: { top: 40, right: 64, bottom: 40, left: 64 },
    legend: {
      top: 6,
      textStyle: { color: '#6b7a9a', fontSize: 12 },
    },
    tooltip: {
      trigger: 'axis',
      backgroundColor: '#101118',
      borderColor: '#1a1c28',
      textStyle: { color: '#dde3f0', fontSize: 12 },
    },
    xAxis: {
      type: 'category',
      data: days,
      axisLabel: { color: '#6b7a9a', fontSize: 11, rotate: days.length > 20 ? 30 : 0 },
      axisLine: { lineStyle: { color: '#1a1c28' } },
    },
    yAxis: [
      {
        type: 'value',
        name: 'kWh / m³',
        nameTextStyle: { color: '#3d445c', fontSize: 11 },
        axisLabel: { color: '#6b7a9a', fontSize: 11 },
        splitLine: { lineStyle: { color: '#1a1c28', type: 'dashed' } },
      },
      {
        type: 'value',
        name: '°C',
        nameTextStyle: { color: '#3d445c', fontSize: 11 },
        axisLabel: { color: '#6b7a9a', fontSize: 11 },
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

// ── 统计数据计算 ─────────────────────────────────────
const stats = computed(() => {
  const d = trendData.value
  const elecVals = d.map((r: any) => r.total_electricity_kwh ?? 0)
  const waterVals = d.map((r: any) => r.total_water_m3 ?? 0)
  const tempVals = d.filter((r: any) => r.avg_ambient_temp != null).map((r: any) => r.avg_ambient_temp)

  const calcStat = (arr: number[]) => {
    if (!arr.length) return { total: 0, avg: 0, max: 0, min: 0 }
    const total = arr.reduce((a, b) => a + b, 0)
    return {
      total,
      avg: total / arr.length,
      max: Math.max(...arr),
      min: Math.min(...arr),
    }
  }

  return {
    elec: calcStat(elecVals),
    water: calcStat(waterVals),
    temp: {
      avg: tempVals.length ? tempVals.reduce((a, b) => a + b, 0) / tempVals.length : 0,
      max: tempVals.length ? Math.max(...tempVals) : 0,
      min: tempVals.length ? Math.min(...tempVals) : 0,
    },
  }
})

// ── 能耗强度计算（每行） ─────────────────────────────
function computeIntensity(row: any): string {
  const sqm = buildingStore.buildings.find(b => b.building_type === trendForm.value.buildingType)?.sqm ?? 0
  if (!sqm || !row.total_electricity_kwh) return '—'
  return (row.total_electricity_kwh / sqm).toFixed(4)
}

// ── CSV / JSON 导出 ──────────────────────────────────
function exportCSV() {
  const { params } = trendForm.value
  const headers: string[] = ['日期']
  if (params.includes('electricity')) headers.push('日用电(kWh)')
  if (params.includes('water'))       headers.push('日用水(m³)')
  if (params.includes('temperature')) headers.push('平均气温(°C)')
  if (params.includes('intensity'))   headers.push('能耗强度(kWh/㎡)')
  if (params.includes('occupancy'))   headers.push('在场人数')

  const rows = trendData.value.map((r: any) => {
    const row: string[] = [formatDay(r.day)]
    if (params.includes('electricity')) row.push((r.total_electricity_kwh ?? '').toString())
    if (params.includes('water'))       row.push((r.total_water_m3 ?? '').toString())
    if (params.includes('temperature')) row.push((r.avg_ambient_temp ?? '').toString())
    if (params.includes('intensity'))   row.push(computeIntensity(r))
    if (params.includes('occupancy'))   row.push((r.occupancy_count ?? '').toString())
    return row
  })

  // 附加统计摘要
  rows.push([])
  rows.push(['--- 统计摘要 ---'])
  if (params.includes('electricity')) {
    rows.push([`用电合计(kWh)`, stats.value.elec.total.toFixed(2)])
    rows.push([`用电日均(kWh)`, stats.value.elec.avg.toFixed(2)])
    rows.push([`用电最大(kWh)`, stats.value.elec.max.toFixed(2)])
    rows.push([`用电最小(kWh)`, stats.value.elec.min.toFixed(2)])
  }
  if (params.includes('water')) {
    rows.push([`用水合计(m³)`, stats.value.water.total.toFixed(2)])
    rows.push([`用水日均(m³)`, stats.value.water.avg.toFixed(2)])
  }
  if (params.includes('temperature')) {
    rows.push([`平均气温`, stats.value.temp.avg.toFixed(1)])
    rows.push([`最高气温`, stats.value.temp.max.toFixed(1)])
    rows.push([`最低气温`, stats.value.temp.min.toFixed(1)])
  }

  const csv = [headers, ...rows].map(r => r.join(',')).join('\n')
  const blob = new Blob(['\uFEFF' + csv], { type: 'text/csv;charset=utf-8;' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `${trendBuildingName.value}_能耗报表_${trendForm.value.startDate}_${trendForm.value.endDate}.csv`
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
  URL.revokeObjectURL(url)
}

function exportJSON() {
  const payload = {
    building: trendBuildingName.value,
    building_type: trendForm.value.buildingType,
    date_range: { start: trendForm.value.startDate, end: trendForm.value.endDate },
    params: trendForm.value.params,
    records: trendData.value,
    statistics: {
      electricity: stats.value.elec,
      water: stats.value.water,
      temperature: stats.value.temp,
    },
    generated_at: new Date().toISOString(),
  }
  const blob = new Blob([JSON.stringify(payload, null, 2)], { type: 'application/json' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `${trendBuildingName.value}_能耗报表_${trendForm.value.startDate}_${trendForm.value.endDate}.json`
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
  URL.revokeObjectURL(url)
}

// ── 工具函数 ─────────────────────────────────────────
const BUILDING_ICONS: Record<string, string> = {
  Office:    'mdi:office-building',
  Teaching:  'mdi:school',
  Lab:       'mdi:flask',
  Library:   'mdi:library',
  Dormitory: 'mdi:bed',
  Gym:       'mdi:dumbbell',
}

function getBuildingIcon(type: string): string {
  return BUILDING_ICONS[type] ?? 'mdi:office-building-outline'
}

function formatTime(iso: string): string {
  try {
    return new Date(iso).toLocaleString('zh-CN', {
      month: '2-digit', day: '2-digit',
      hour: '2-digit', minute: '2-digit',
    })
  } catch {
    return iso
  }
}

function formatDay(iso: string): string {
  if (!iso) return '—'
  return iso.slice(0, 10)
}
</script>

<style scoped>
.dashboard { padding: 48px 24px 24px; }

/* ── KPI ── */
.kpi-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 8px;
  margin-bottom: 20px;
}
.kpi-card {
  background: var(--bg-panel);
  border: 1px solid var(--border);
  border-radius: 10px;
  padding: 10px 14px;
  display: flex;
  align-items: center;
  gap: 10px;
  box-shadow: var(--card-shadow);
  transition: box-shadow 0.2s, border-color 0.2s;
}
.kpi-card:hover {
  box-shadow: var(--card-shadow-hover);
  border-color: var(--border-accent);
}
.kpi-icon {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 34px;
  height: 34px;
  border-radius: 8px;
  background: var(--accent-glow);
  color: var(--accent);
  flex-shrink: 0;
}
.kpi-body { flex: 1; min-width: 0; }
.kpi-value { font-size: 18px; font-weight: 700; color: var(--text-primary); line-height: 1.2; }
.kpi-label { font-size: 10px; color: var(--text-muted); margin-top: 2px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.kpi-trend { font-size: 11px; font-weight: 600; flex-shrink: 0; }
.kpi-trend.up { color: var(--danger); }
.kpi-trend.down { color: var(--success); }
.kpi-trend.neutral { color: var(--text-muted); }

/* ── 建筑选择器 ── */
.building-selector-wrap {
  display: flex;
  justify-content: center;
  margin-bottom: 24px;
}

/* 胶囊外壳 */
.building-selector {
  position: relative;
  display: flex;
  background: var(--bg-panel);
  border: 1px solid var(--border);
  border-radius: 999px;
  padding: 4px;
}

/* 滑动指示器：宽度 = 外壳内宽 / 建筑数量 */
.selector-indicator {
  position: absolute;
  top: 4px;
  bottom: 4px;
  left: 4px;
  width: calc((100% - 8px) / v-bind(numBuildings));
  border-radius: 999px;
  background: var(--bg-card);
  box-shadow: 0 1px 6px rgba(0, 0, 0, 0.25), 0 0 0 1px var(--border-accent);
  transition: transform 0.25s cubic-bezier(0.4, 0, 0.2, 1);
  transform: translateX(calc(v-bind(selectedBuildingIndex) * 100%));
  pointer-events: none;
}

/* 各选项 */
.selector-option {
  flex: 1;
  position: relative;
  z-index: 1;
  padding: 8px 28px;
  border: none;
  background: transparent;
  cursor: pointer;
  font-size: 13px;
  font-weight: 500;
  color: var(--text-secondary);
  white-space: nowrap;
  border-radius: 999px;
  transition: color 0.2s;
}
.selector-option:hover {
  color: var(--text-primary);
}
.selector-option.active {
  color: var(--accent);
  font-weight: 600;
}

/* ── 建筑详情卡 ── */
.building-detail {
  background: var(--bg-panel);
  border: 1px solid var(--border);
  border-radius: 12px;
  overflow: hidden;
  box-shadow: var(--card-shadow);
}
.building-detail.anomaly {
  border-color: rgba(248,113,113,0.45);
}
.detail-header {
  padding: 16px 20px;
  background: var(--bg-card);
  border-bottom: 1px solid var(--border);
}
.detail-name-row {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 6px;
  color: var(--accent);
}
.detail-icon { display: flex; align-items: center; }
.detail-name { font-size: 16px; font-weight: 700; color: var(--text-primary); flex: 1; }
.detail-meta { font-size: 12px; color: var(--text-muted); }

.detail-metrics {
  display: grid;
  grid-template-columns: repeat(5, 1fr);
  gap: 0;
}
.detail-metric {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 18px 20px;
  border-right: 1px solid var(--border);
}
.detail-metric:last-child { border-right: none; }

.dm-icon {
  width: 40px;
  height: 40px;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 10px;
  flex-shrink: 0;
}
.dm-icon.electricity { background: rgba(108,142,245,0.12); color: var(--accent); }
.dm-icon.water       { background: rgba(34,211,238,0.12);  color: #22d3ee; }
.dm-icon.temp        { background: rgba(251,191,36,0.12);  color: var(--warning); }
.dm-icon.intensity   { background: rgba(167,139,250,0.12); color: #a78bfa; }
.dm-icon.people      { background: rgba(74,222,128,0.12);  color: var(--success); }

.dm-value { font-size: 20px; font-weight: 700; color: var(--text-primary); }
.dm-label { font-size: 11px; color: var(--text-muted); margin-top: 2px; }

/* ── 通用 ── */
.section { margin-bottom: 28px; }
.section-title { font-size: 15px; font-weight: 700; margin-bottom: 12px; color: var(--text-secondary); }
.section-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 12px;
}
.section-header .section-title { margin-bottom: 0; }

/* ── 告警 ── */
.refresh-btn {
  display: flex;
  align-items: center;
  gap: 4px;
  background: none;
  border: 1px solid var(--border);
  border-radius: 6px;
  color: var(--text-secondary);
  font-size: 12px;
  padding: 4px 10px;
  cursor: pointer;
  transition: all 0.2s;
}
.refresh-btn:hover { border-color: var(--accent); color: var(--accent); }
.refresh-btn:disabled { opacity: 0.5; cursor: not-allowed; }

.anomaly-list { display: flex; flex-direction: column; gap: 8px; }
.anomaly-item {
  display: flex;
  justify-content: space-between;
  align-items: center;
  background: var(--bg-panel);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 12px 16px;
}
.anomaly-left { display: flex; align-items: center; gap: 12px; }
.anomaly-priority {
  font-size: 11px;
  font-weight: 600;
  padding: 3px 8px;
  border-radius: 4px;
  flex-shrink: 0;
}
.anomaly-priority.high   { background: rgba(248,113,113,0.15); color: var(--danger); }
.anomaly-priority.medium { background: rgba(251,191,36,0.15);  color: var(--warning); }
.anomaly-title { font-size: 13px; font-weight: 500; margin-bottom: 2px; }
.anomaly-meta  { font-size: 11px; color: var(--text-muted); }
.anomaly-status {
  font-size: 12px;
  padding: 3px 10px;
  border-radius: 10px;
  flex-shrink: 0;
}
.anomaly-status.pending { background: rgba(251,191,36,0.15);  color: var(--warning); }
.anomaly-status.alert   { background: rgba(248,113,113,0.15); color: var(--danger); }
.anomaly-status.warn    { background: rgba(251,191,36,0.15);  color: var(--warning); }

.no-anomaly {
  background: rgba(74,222,128,0.08);
  border: 1px solid rgba(74,222,128,0.25);
  border-radius: 8px;
  padding: 12px 16px;
  color: var(--success);
  font-size: 13px;
  display: flex;
  align-items: center;
  gap: 8px;
}

/* ── 能耗趋势查询 ── */
.query-form {
  background: var(--bg-panel);
  border: 1px solid var(--border);
  border-radius: 10px;
  padding: 16px 18px;
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
.form-select-sm { min-width: 160px; }
.form-select:focus,
.form-input:focus { outline: none; border-color: var(--accent); }
.form-check {
  width: 14px;
  height: 14px;
  cursor: pointer;
  accent-color: var(--accent);
}
.form-hint {
  font-size: 11px;
  color: var(--text-muted);
  margin-top: 10px;
}
.params-row {
  display: flex;
  align-items: center;
  gap: 16px;
  margin-top: 12px;
  flex-wrap: wrap;
}
.param-check {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  color: var(--text-secondary);
  cursor: pointer;
}
.param-check:hover { color: var(--accent); }

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

/* ── 趋势结果区 ── */
.trend-results { display: flex; flex-direction: column; gap: 16px; }

.chart-container {
  background: var(--bg-panel);
  border: 1px solid var(--border);
  border-radius: 12px;
  overflow: hidden;
  box-shadow: var(--card-shadow);
}
.data-table-section {
  box-shadow: var(--card-shadow);
}
.report-card {
  box-shadow: var(--card-shadow);
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
.chart-body { width: 100%; height: 280px; }

/* ── 数据表 ── */
.data-table-section {
  background: var(--bg-panel);
  border: 1px solid var(--border);
  border-radius: 10px;
  overflow: hidden;
}
.table-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 12px 16px;
  border-bottom: 1px solid var(--border);
  background: var(--bg-card);
}
.table-title { font-size: 13px; font-weight: 600; color: var(--text-secondary); }
.table-count { font-size: 11px; color: var(--text-muted); }
.data-table-wrap { overflow-x: auto; max-height: 320px; overflow-y: auto; }

.data-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 12px;
}
.data-table th {
  position: sticky;
  top: 0;
  background: var(--bg-card);
  padding: 8px 14px;
  text-align: left;
  font-size: 11px;
  font-weight: 600;
  color: var(--text-muted);
  border-bottom: 1px solid var(--border);
  white-space: nowrap;
}
.data-table td {
  padding: 8px 14px;
  border-bottom: 1px solid var(--border);
  color: var(--text-secondary);
}
.data-table tr:last-child td { border-bottom: none; }
.data-table tr:hover td { background: var(--bg-hover); }
.num-cell { text-align: right; font-variant-numeric: tabular-nums; color: var(--text-primary); }

/* ── 统计报表卡 ── */
.report-card {
  background: var(--bg-panel);
  border: 1px solid var(--border);
  border-radius: 10px;
  overflow: hidden;
}
.report-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 12px 16px;
  background: var(--bg-card);
  border-bottom: 1px solid var(--border);
}
.report-title-row {
  display: flex;
  align-items: center;
  gap: 12px;
}
.report-title { font-size: 13px; font-weight: 600; color: var(--text-secondary); }
.report-meta { font-size: 12px; color: var(--text-muted); }
.report-actions { display: flex; gap: 8px; }

.export-btn {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  border: none;
  border-radius: 6px;
  font-size: 12px;
  font-weight: 600;
  padding: 6px 14px;
  cursor: pointer;
  transition: opacity 0.2s;
  white-space: nowrap;
}
.csv-btn  { background: var(--success); color: #000; }
.json-btn { background: var(--accent-glow); color: var(--accent); border: 1px solid var(--border-accent); }
.export-btn:hover { opacity: 0.8; }

.stats-grid {
  display: flex;
  gap: 0;
  flex-wrap: wrap;
}
.stat-group {
  flex: 1;
  min-width: 200px;
  padding: 14px 18px;
  border-right: 1px solid var(--border);
}
.stat-group:last-child { border-right: none; }
.stat-group-title {
  font-size: 11px;
  font-weight: 600;
  color: var(--text-muted);
  text-transform: uppercase;
  letter-spacing: 0.06em;
  margin-bottom: 10px;
  display: flex;
  align-items: center;
  gap: 5px;
}
.stat-items {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 8px;
}
.stat-item {
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.stat-label { font-size: 11px; color: var(--text-muted); }
.stat-val {
  font-size: 16px;
  font-weight: 700;
}
.stat-val.electricity { color: var(--accent); }
.stat-val.water       { color: #22d3ee; }
.stat-val.temp        { color: var(--warning); }

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

/* ── 状态栏 ── */
.loading-bar {
  background: var(--accent-glow);
  border: 1px solid var(--border-accent);
  border-radius: 8px;
  padding: 10px 16px;
  color: var(--accent);
  font-size: 13px;
  margin-bottom: 16px;
}
.error-bar {
  background: rgba(248,113,113,0.08);
  border: 1px solid rgba(248,113,113,0.25);
  border-radius: 8px;
  padding: 10px 16px;
  color: var(--danger);
  font-size: 13px;
  margin-bottom: 16px;
  display: flex;
  align-items: center;
  gap: 8px;
}

/* ── status chip ── */
.status-chip {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: 11px;
  padding: 3px 10px;
  border-radius: 10px;
  font-weight: 600;
}
.status-chip.normal  { background: rgba(74,222,128,0.15);  color: var(--success); }
.status-chip.anomaly { background: rgba(248,113,113,0.15); color: var(--danger); }

/* ── AI 提示 ── */
.ai-hint {
  display: flex;
  align-items: center;
  gap: 8px;
  background: var(--accent-glow);
  border: 1px solid var(--border-accent);
  border-radius: 8px;
  padding: 12px 16px;
  color: var(--accent);
  font-size: 13px;
  margin-bottom: 8px;
}

/* ── 图标对齐 ── */
.page-icon  { vertical-align: middle; margin-right: 6px; }
.title-icon { vertical-align: middle; margin-right: 4px; }
.bar-icon   { vertical-align: middle; flex-shrink: 0; }
.btn-icon   { vertical-align: middle; }
</style>
