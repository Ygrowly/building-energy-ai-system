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
          <input type="date" v-model="startDate" class="filter-input" :min="dataRangeStore.minDate" :max="dataRangeStore.maxDate" />
        </div>
        <div class="filter-item">
          <label class="filter-label">
            <Icon icon="mdi:calendar-end" width="13" class="label-icon" />
            结束日期
          </label>
          <input type="date" v-model="endDate" class="filter-input" :min="dataRangeStore.minDate" :max="dataRangeStore.maxDate" />
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
            :class="{ checked: p.checked }"
          >
            <input type="checkbox" v-model="p.checked" />
            <span class="check-box">
              <Icon v-if="p.checked" icon="mdi:check" width="11" class="check-icon" />
            </span>
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
    <div class="chart-card" v-if="queryResult && checkedParams.length && viewMode === 'data'">
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
              <th v-for="p in checkedParams" :key="p.key">{{ p.label }}</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="(row, idx) in queryResult.records" :key="idx">
              <td class="sticky-col date-cell">{{ row.day?.slice(0, 10) }}</td>
              <td v-for="p in checkedParams" :key="p.key" class="num-cell">
                {{ formatTableVal(getRowValue(row, p.key), p.key, row) }}
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

    <!-- ══════════════ 统计分析：多图表 ══════════════ -->
    <template v-if="queryResult && viewMode === 'analysis'">
      <div
        v-for="group in activeChartGroups"
        :key="group.id"
        class="chart-card"
      >
        <div class="chart-card-header">
          <div class="chart-card-title">
            <Icon :icon="group.icon" width="18" class="chart-title-icon" />
            <span>{{ buildingLabel }} {{ group.title }}</span>
            <span class="chart-date-range">{{ startDate }} ~ {{ endDate }}</span>
          </div>
          <div class="chart-card-actions">
            <button class="card-action-btn" title="刷新数据" @click="handleQuery" aria-label="刷新数据">
              <Icon icon="mdi:refresh" width="16" />
            </button>
          </div>
        </div>
        <div class="chart-container" :ref="(el: any) => setChartRef(group.id, el)"></div>
      </div>
    </template>

    <!-- ══════════════ 空状态 ══════════════ -->
    <div class="content-placeholder" v-if="!queryResult && !loading">
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
import { useDataRangeStore } from '@/stores/dataRangeStore'
import * as echarts from 'echarts'
import { useReportExport } from '@/composables/useReportExport'

// ── 报表集成 ──
const { registerSection, captureChart, setReportMeta } = useReportExport('querystats')

const dataRangeStore = useDataRangeStore()

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
const startDate = ref('')
const endDate = ref('')
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
  if (viewMode.value === 'analysis' && queryResult.value && checkedParams.value.length) {
    await nextTick()
    renderAllCharts()
  }
})
onMounted(() => nextTick(updateSlider))

// ── 监测参数 ──
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

const DEVICE_SUB_PARAMS = [
  { key: 'device_normal_rate', label: '正常设备数/总数' },
  { key: 'ac_avg_power_kw', label: 'AC功率 (kW)' },
  { key: 'ac_cop', label: 'COP值' },
  { key: 'supply_return_delta', label: '供回水温差 (°C)' },
]

const checkedParams = computed(() => {
  const base = allParams.filter(p => p.checked && p.key !== 'device_status')
  if (deviceStatusChecked.value) {
    return [...base, ...DEVICE_SUB_PARAMS.map(d => ({ ...d, checked: true }))]
  }
  return base
})

// ── 图表分组定义 ──
interface ChartGroup {
  id: string
  title: string
  icon: string
  paramKeys: string[]
}

const CHART_GROUPS: ChartGroup[] = [
  {
    id: 'energy',
    title: '能耗总览',
    icon: 'mdi:lightning-bolt',
    paramKeys: ['electricity_kwh', 'water_m3', 'hac_energy'],
  },
  {
    id: 'cop',
    title: 'COP 与空调性能分析',
    icon: 'mdi:air-conditioner',
    paramKeys: ['ac_cop'],
  },
  {
    id: 'temperature',
    title: '环境与温度',
    icon: 'mdi:thermometer',
    paramKeys: ['air_temp_c', 'sim_supply_temp_c', 'sim_return_temp_c', 'dew_temp_c', 'humidity_rh_pct'],
  },
]

const activeChartGroups = computed(() => {
  const checked = new Set(checkedParams.value.map(p => p.key))
  const groups: ChartGroup[] = []
  for (const g of CHART_GROUPS) {
    if (g.id === 'cop') {
      groups.push(g)
    } else {
      if (g.paramKeys.some(k => checked.has(k))) groups.push(g)
    }
  }
  return groups
})

// ── ECharts 多实例管理 ──
const chartRefs = new Map<string, HTMLElement>()
const chartInstances = new Map<string, echarts.ECharts>()

function setChartRef(groupId: string, el: any) {
  if (el) chartRefs.set(groupId, el as HTMLElement)
  else chartRefs.delete(groupId)
}

const PARAM_COLORS: Record<string, string> = {
  electricity_kwh: '#3ba272',
  water_m3: '#5470c6',
  hac_energy: '#ee6666',
  sim_supply_temp_c: '#73c0de',
  sim_return_temp_c: '#fc8452',
  air_temp_c: '#fac858',
  humidity_rh_pct: '#9a60b4',
  dew_temp_c: '#91cc75',
  device_normal_rate: '#26a69a',
  ac_avg_power_kw: '#ef5350',
  ac_cop: '#ff7043',
  supply_return_delta: '#ea7ccc',
}

// ── 统一查询 ──
async function handleQuery() {
  const params = checkedParams.value
  if (params.length === 0) return

  loading.value = true
  queryResult.value = null

  try {
    const resp = await apiFetch<any>(
      `/api/buildings/${selectedBuilding.value}/energy?start_date=${startDate.value}&end_date=${endDate.value}&include_water=true&include_device_status=true`
    )
    queryResult.value = resp

    await nextTick()

    if (viewMode.value === 'analysis' && queryResult.value) {
      await nextTick()
      renderAllCharts()
    }

    registerReportSections(params)
  } catch (e: any) {
    console.error('查询失败', e)
  } finally {
    loading.value = false
  }
}

function registerReportSections(params: typeof allParams) {
  setReportMeta({
    title: `${buildingLabel.value} 查询统计报表`,
    buildingName: buildingLabel.value,
    dateRange: { start: startDate.value, end: endDate.value },
  })

  registerSection({
    id: 'qs-condition',
    title: '查询条件',
    type: 'text',
    order: 5,
    content: `楼宇：${buildingLabel.value}  |  日期范围：${startDate.value} ~ ${endDate.value}  |  监测参数：${params.map(p => p.label).join('、') || '无'}`,
  })

  if (queryResult.value?.records?.length) {
    registerSection({
      id: 'qs-energy-table',
      title: '能耗数据明细',
      type: 'table',
      order: 10,
      columns: [
        { key: 'day', label: '日期' },
        ...params.map(p => ({
          key: p.key,
          label: p.label,
          align: 'right' as const,
        })),
      ],
      rows: queryResult.value.records.map((r: any) => {
        const row: Record<string, any> = { day: r.day?.slice(0, 10) ?? '' }
        params.forEach(p => {
          const v = getRowValue(r, p.key)
          row[p.key] = formatTableVal(v, p.key) === '-' ? '—' : formatTableVal(v, p.key)
        })
        return row
      }),
    })
  }

  if (viewMode.value === 'analysis') {
    setTimeout(() => {
      let order = 20
      for (const group of activeChartGroups.value) {
        const inst = chartInstances.get(group.id)
        if (inst) {
          captureChart(inst, `qs-chart-${group.id}`, group.title, order)
          order += 10
        }
      }
    }, 400)
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
  ac_avg_power_kw: 'ac_avg_power_kw',
  ac_cop: 'ac_cop',
  supply_return_delta: 'supply_return_delta',
  device_normal_rate: '_device_normal_rate',
}

function getRowValue(row: any, paramKey: string): any {
  if (paramKey === 'device_normal_rate') {
    const total = row.device_total
    const normal = row.device_normal
    if (total != null && total > 0) return (normal / total) * 100
    return null
  }
  const field = PARAM_FIELD_MAP[paramKey] || paramKey
  return row[field]
}

function formatDeviceNormal(row: any): string {
  const total = row?.device_total
  const normal = row?.device_normal
  if (total == null || total === 0) return '-'
  return `${normal}/${total}`
}

function formatTableVal(v: any, paramKey?: string, row?: any): string {
  if (paramKey === 'device_normal_rate') {
    return row ? formatDeviceNormal(row) : (v != null ? `${Number(v).toFixed(0)}%` : '-')
  }
  if (v == null) return '-'
  const n = Number(v)
  return isNaN(n) ? String(v) : n.toFixed(2)
}

// ── 公共 tooltip / xAxis 配置 ──
function sharedTooltip() {
  return {
    trigger: 'axis' as const,
    backgroundColor: 'rgba(255,255,255,0.96)',
    borderColor: '#eaedf0', borderWidth: 1,
    textStyle: { color: '#2d3239', fontSize: 12 },
    padding: [10, 14],
    extraCssText: 'box-shadow:0 4px 16px rgba(0,0,0,0.08);border-radius:8px;',
  }
}
function sharedXAxis(days: string[]) {
  return {
    type: 'category' as const, data: days,
    axisLabel: { rotate: days.length > 15 ? 45 : 0, color: '#8c939a', fontSize: 11 },
    axisLine: { lineStyle: { color: '#e8ebee' } },
    axisTick: { show: false },
  }
}
function makeSeriesData(records: any[], paramKey: string) {
  return records.map((r: any) => {
    const v = getRowValue(r, paramKey)
    return v != null ? Number(Number(v).toFixed(2)) : null
  })
}

// ── 渲染入口：遍历所有可见分组 ──
function renderAllCharts() {
  const data = queryResult.value
  if (!data?.records?.length) return

  for (const [id, inst] of chartInstances) {
    inst.dispose()
    chartInstances.delete(id)
  }

  for (const group of activeChartGroups.value) {
    const el = chartRefs.get(group.id)
    if (!el) continue

    const inst = echarts.init(el)
    chartInstances.set(group.id, inst)

    if (group.id === 'energy') renderEnergyChart(inst, data)
    else if (group.id === 'cop') renderCOPChart(inst, data)
    else if (group.id === 'temperature') renderTempChart(inst, data)
  }
}

// ── 图表 1: 能耗总览 ──
function renderEnergyChart(inst: echarts.ECharts, data: any) {
  const records: any[] = data.records || []
  const days = records.map((r: any) => r.day?.slice(0, 10) || '')
  const checked = new Set(checkedParams.value.map(p => p.key))

  const kwhKeys = ['electricity_kwh', 'hac_energy'].filter(k => checked.has(k))
  const hasWater = checked.has('water_m3')
  const kwhLabels: Record<string, string> = { electricity_kwh: '日用电 (kWh)', hac_energy: '暖通空调能耗 (kWh)' }

  const yAxis: any[] = []
  if (kwhKeys.length > 0) yAxis.push({
    type: 'value', name: 'kWh', position: 'left',
    nameTextStyle: { color: '#8c939a', fontSize: 12 },
    axisLine: { show: false }, axisTick: { show: false },
    splitLine: { lineStyle: { color: '#f0f2f5', type: 'dashed' } },
    axisLabel: { color: '#8c939a', fontSize: 11 },
  })
  if (hasWater) yAxis.push({
    type: 'value', name: 'm³', position: kwhKeys.length > 0 ? 'right' : 'left',
    nameTextStyle: { color: '#5470c6', fontSize: 12 },
    axisLine: { show: false }, axisTick: { show: false },
    splitLine: kwhKeys.length > 0 ? { show: false } : { lineStyle: { color: '#f0f2f5', type: 'dashed' } },
    axisLabel: { color: '#8c939a', fontSize: 11 },
  })
  if (yAxis.length === 0) yAxis.push({ type: 'value' })

  const series: any[] = []
  for (const k of kwhKeys) {
    series.push({
      name: kwhLabels[k] || k, type: 'bar', yAxisIndex: 0,
      data: makeSeriesData(records, k),
      itemStyle: { color: PARAM_COLORS[k], borderRadius: [3, 3, 0, 0] },
      barMaxWidth: 40, barGap: '35%', barCategoryGap: '40%',
      emphasis: { focus: 'series' }, animationDuration: 800,
    })
  }
  if (hasWater) {
    const waterYIdx = kwhKeys.length > 0 ? 1 : 0
    series.push({
      name: '日用水 (m³)', type: 'bar', yAxisIndex: waterYIdx,
      data: makeSeriesData(records, 'water_m3'),
      itemStyle: { color: PARAM_COLORS.water_m3, borderRadius: [3, 3, 0, 0] },
      barMaxWidth: 40, barGap: '35%', barCategoryGap: '40%',
      emphasis: { focus: 'series' }, animationDuration: 800,
    })
  }

  const hasZoom = days.length > 14
  inst.setOption({
    tooltip: sharedTooltip(),
    legend: { data: series.map(s => s.name), bottom: hasZoom ? 36 : 0, icon: 'roundRect', itemWidth: 12, itemHeight: 8, textStyle: { color: '#8c939a', fontSize: 11 }, itemGap: 16 },
    grid: { left: 56, right: hasWater && kwhKeys.length > 0 ? 56 : 20, top: 36, bottom: hasZoom ? 80 : 44, containLabel: false },
    xAxis: sharedXAxis(days),
    yAxis,
    dataZoom: hasZoom ? [
      { type: 'slider', xAxisIndex: 0, bottom: 4, height: 22, borderColor: 'transparent', backgroundColor: '#f5f6f8', fillerColor: 'rgba(76,175,80,0.15)', handleStyle: { color: '#4caf50' }, textStyle: { fontSize: 10 }, start: 0, end: 100 },
      { type: 'inside', xAxisIndex: 0 },
    ] : [],
    series,
    animationDuration: 600,
  })
}

// ── 图表 2: COP 与空调性能分析 ──
function renderCOPChart(inst: echarts.ECharts, data: any) {
  const records: any[] = data.records || []
  const days = records.map((r: any) => r.day?.slice(0, 10) || '')

  const copData = makeSeriesData(records, 'ac_cop')
  const powerData = makeSeriesData(records, 'ac_avg_power_kw')
  const deltaData = makeSeriesData(records, 'supply_return_delta')

  const copColor = '#1565c0'
  const powerColor = '#66bb6a'
  const deltaColor = '#ffa726'

  inst.setOption({
    tooltip: sharedTooltip(),
    legend: {
      data: ['COP值', 'AC功率 (kW)', '供回水温差 (°C)'],
      bottom: 0, icon: 'roundRect', itemWidth: 12, itemHeight: 8,
      textStyle: { color: '#8c939a', fontSize: 11 }, itemGap: 16,
    },
    grid: { left: 56, right: 56, top: 40, bottom: 44, containLabel: false },
    xAxis: sharedXAxis(days),
    yAxis: [
      {
        type: 'value', name: 'COP', position: 'left',
        nameTextStyle: { color: copColor, fontSize: 12, fontWeight: 600 },
        axisLine: { show: false }, axisTick: { show: false },
        splitLine: { lineStyle: { color: '#f0f2f5', type: 'dashed' } },
        axisLabel: { color: '#8c939a', fontSize: 11 },
      },
      {
        type: 'value', name: 'kW / °C', position: 'right',
        nameTextStyle: { color: '#8c939a', fontSize: 12 },
        axisLine: { show: false }, axisTick: { show: false },
        splitLine: { show: false },
        axisLabel: { color: '#8c939a', fontSize: 11 },
      },
    ],
    series: [
      {
        name: 'COP值', type: 'line', yAxisIndex: 0, z: 10,
        data: copData,
        lineStyle: { width: 3, color: copColor },
        itemStyle: { color: copColor, borderWidth: 2, borderColor: '#fff' },
        areaStyle: { color: { type: 'linear', x: 0, y: 0, x2: 0, y2: 1, colorStops: [{ offset: 0, color: 'rgba(21,101,192,0.18)' }, { offset: 1, color: 'rgba(21,101,192,0.02)' }] } },
        smooth: true, symbol: 'circle', symbolSize: 7,
        emphasis: { focus: 'series' }, animationDuration: 800,
      },
      {
        name: 'AC功率 (kW)', type: 'bar', yAxisIndex: 1, z: 1,
        data: powerData,
        itemStyle: { color: 'rgba(102,187,106,0.6)', borderRadius: [3, 3, 0, 0] },
        barMaxWidth: 24, barCategoryGap: '40%',
        emphasis: { focus: 'series', itemStyle: { color: powerColor } }, animationDuration: 800,
      },
      {
        name: '供回水温差 (°C)', type: 'line', yAxisIndex: 1, z: 5,
        data: deltaData,
        lineStyle: { width: 2.5, type: 'dashed', color: deltaColor },
        itemStyle: { color: deltaColor },
        smooth: true, symbol: 'diamond', symbolSize: 6,
        emphasis: { focus: 'series' }, animationDuration: 800,
      },
    ],
    animationDuration: 600,
  })
}

// ── 图表 3: 环境与温度 ──
function renderTempChart(inst: echarts.ECharts, data: any) {
  const records: any[] = data.records || []
  const days = records.map((r: any) => r.day?.slice(0, 10) || '')
  const checked = new Set(checkedParams.value.map(p => p.key))

  const allTempKeys = ['air_temp_c', 'sim_supply_temp_c', 'sim_return_temp_c', 'dew_temp_c']
  const userCheckedTemps = allTempKeys.filter(k => checked.has(k))
  const hasHumidity = checked.has('humidity_rh_pct')

  const autoAddKeys: string[] = []
  if (userCheckedTemps.length > 0 && userCheckedTemps.length < 3) {
    for (const k of ['sim_supply_temp_c', 'sim_return_temp_c']) {
      if (!checked.has(k)) autoAddKeys.push(k)
    }
  }
  const tempKeys = [...userCheckedTemps, ...autoAddKeys]

  const tempLabels: Record<string, string> = {
    air_temp_c: '环境温度 (°C)', sim_supply_temp_c: '供水温度 (°C)',
    sim_return_temp_c: '回水温度 (°C)', dew_temp_c: '露点温度 (°C)',
  }

  const yAxis: any[] = []
  if (tempKeys.length > 0) yAxis.push({
    type: 'value', name: '°C', position: 'left',
    nameTextStyle: { color: '#8c939a', fontSize: 12 },
    axisLine: { show: false }, axisTick: { show: false },
    splitLine: { lineStyle: { color: '#f0f2f5', type: 'dashed' } },
    axisLabel: { color: '#8c939a', fontSize: 11 },
  })
  if (hasHumidity) yAxis.push({
    type: 'value', name: '%RH', position: tempKeys.length > 0 ? 'right' : 'left',
    nameTextStyle: { color: '#9a60b4', fontSize: 12 },
    axisLine: { show: false }, axisTick: { show: false },
    splitLine: tempKeys.length > 0 ? { show: false } : { lineStyle: { color: '#f0f2f5', type: 'dashed' } },
    axisLabel: { color: '#8c939a', fontSize: 11 },
  })
  if (yAxis.length === 0) yAxis.push({ type: 'value' })

  const series: any[] = []
  for (const k of tempKeys) {
    const isAuto = autoAddKeys.includes(k)
    series.push({
      name: tempLabels[k] || k, type: 'line', yAxisIndex: 0,
      data: makeSeriesData(records, k),
      lineStyle: { width: isAuto ? 1.5 : 2.5, color: PARAM_COLORS[k], type: isAuto ? 'dashed' : 'solid', opacity: isAuto ? 0.7 : 1 },
      itemStyle: { color: PARAM_COLORS[k], opacity: isAuto ? 0.5 : 1 },
      smooth: true, symbol: isAuto ? 'none' : 'circle', symbolSize: isAuto ? 0 : 4,
      emphasis: { focus: 'series' }, animationDuration: 800,
    })
  }
  if (hasHumidity) {
    const humYIdx = tempKeys.length > 0 ? 1 : 0
    series.push({
      name: '相对湿度 (%)', type: 'line', yAxisIndex: humYIdx,
      data: makeSeriesData(records, 'humidity_rh_pct'),
      lineStyle: { width: 2, type: 'dashed', color: PARAM_COLORS.humidity_rh_pct },
      itemStyle: { color: PARAM_COLORS.humidity_rh_pct },
      smooth: true, emphasis: { focus: 'series' }, animationDuration: 800,
    })
  }

  inst.setOption({
    tooltip: sharedTooltip(),
    legend: { data: series.map(s => s.name), bottom: 0, icon: 'roundRect', itemWidth: 12, itemHeight: 8, textStyle: { color: '#8c939a', fontSize: 11 }, itemGap: 16 },
    grid: { left: 56, right: hasHumidity && tempKeys.length > 0 ? 56 : 20, top: 36, bottom: 44, containLabel: false },
    xAxis: sharedXAxis(days),
    yAxis,
    series,
    animationDuration: 600,
  })
}

// ── 全局 ──
function onResize() {
  for (const inst of chartInstances.values()) inst.resize()
}

onMounted(async () => {
  window.addEventListener('resize', onResize)
  document.addEventListener('click', closeQsDropdowns)
  await dataRangeStore.fetch()
  if (!startDate.value) startDate.value = dataRangeStore.defaultStart
  if (!endDate.value) endDate.value = dataRangeStore.defaultEnd
})
onUnmounted(() => {
  window.removeEventListener('resize', onResize)
  document.removeEventListener('click', closeQsDropdowns)
  for (const inst of chartInstances.values()) inst.dispose()
  chartInstances.clear()
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
  min-height: 420px;
  padding: 12px 16px 16px;
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
