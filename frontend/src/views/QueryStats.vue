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
            @click.stop="dropdownBuildingOpen = !dropdownBuildingOpen"
          >
            <span class="qs-dropdown-value">{{ buildingOptions.find(b => b.value === selectedBuilding)?.label }}</span>
            <Icon icon="mdi:chevron-down" width="14" class="qs-dropdown-arrow" :class="{ 'qs-dropdown-arrow--open': dropdownBuildingOpen }" />
            <Transition name="qs-drop">
              <div v-if="dropdownBuildingOpen" class="qs-dropdown-list" @click.stop>
                <div
                  v-for="b in buildingOptions" :key="b.value"
                  class="qs-dropdown-item"
                  :class="{ 'qs-dropdown-item--selected': selectedBuilding === b.value }"
                  @click="selectedBuilding = b.value; dropdownBuildingOpen = false"
                >
                  <Icon v-if="selectedBuilding === b.value" icon="mdi:check" width="13" class="qs-item-check" />
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
            ref="btnAnalysisRef"
            :class="{ active: viewMode === 'analysis' }"
            @click="viewMode = 'analysis'"
            aria-label="统计分析视图"
          >
            <Icon icon="mdi:chart-line" width="14" />
            统计分析
          </button>
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
        </div>
      </div>
    </div>

    <!-- ══════════════ 统计分析：摘要 + 图表 + 结论 ══════════════ -->
    <template v-if="queryResult && viewMode === 'analysis'">
      <section class="analysis-stack">
        <div class="kpi-grid">
          <article
            v-for="item in summaryKpis"
            :key="item.id"
            class="kpi-card"
          >
            <div class="kpi-card-top">
              <span class="kpi-label">{{ item.label }}</span>
              <Icon :icon="item.icon" width="16" class="kpi-icon" />
            </div>
            <div class="kpi-value">{{ item.value }}</div>
            <div class="kpi-subtext">{{ item.subtext }}</div>
          </article>
        </div>

        <div class="analysis-grid">
          <article
            v-for="card in analysisCards"
            :key="card.id"
            :class="[
              'chart-card',
              'analysis-card',
              `analysis-card--${card.id}`,
              `analysis-card--${card.layout}`,
            ]"
          >
            <div class="chart-card-header">
              <div class="chart-card-title">
                <Icon :icon="card.icon" width="18" class="chart-title-icon" />
                <span>{{ buildingLabel }} {{ card.title }}</span>
                <span class="chart-date-range">{{ startDate }} ~ {{ endDate }}</span>
              </div>
              <div class="chart-card-actions">
                <button class="card-action-btn" title="刷新数据" @click="handleQuery" aria-label="刷新数据">
                  <Icon icon="mdi:refresh" width="16" />
                </button>
              </div>
            </div>
            <div class="analysis-meta" v-if="card.highlights.length">
              <div
                v-for="highlight in card.highlights"
                :key="`${card.id}-${highlight.label}`"
                class="analysis-meta-item"
              >
                <span class="analysis-meta-label">{{ highlight.label }}</span>
                <span class="analysis-meta-value">{{ highlight.value }}</span>
              </div>
            </div>
            <div class="chart-container chart-container--analysis" :ref="(el: any) => setChartRef(card.id, el)"></div>
          </article>
        </div>

        <article class="chart-card insight-card">
          <div class="chart-card-header">
            <div class="chart-card-title">
              <Icon icon="mdi:lightbulb-on-outline" width="18" class="chart-title-icon" />
              <span>{{ buildingLabel }} 异常/结论区</span>
              <span class="chart-date-range">{{ startDate }} ~ {{ endDate }}</span>
            </div>
          </div>
          <div class="insight-list">
            <div
              v-for="item in analysisInsights"
              :key="item.id"
              class="insight-item"
            >
              <div class="insight-badge">{{ item.tag }}</div>
              <div class="insight-content">
                <div class="insight-title">{{ item.title }}</div>
                <div class="insight-text">{{ item.text }}</div>
              </div>
            </div>
          </div>
        </article>
      </section>
    </template>

    <!-- ══════════════ 数据展示：表格 ══════════════ -->
    <div class="chart-card" v-if="queryResult && checkedParams.length && viewMode === 'data'">
      <div class="chart-card-header">
        <div class="chart-card-title">
          <Icon icon="mdi:table" width="18" class="chart-title-icon" />
          <span>{{ buildingLabel }} 数据明细表</span>
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
import { BUILDING_TYPE_OPTIONS, getBuildingLabel, type BuildingType } from '@/constants/buildings'
import { useDataRangeStore } from '@/stores/dataRangeStore'
import * as echarts from 'echarts'
import { useReportExport } from '@/composables/useReportExport'

// ── 报表集成 ──
const { registerSection, captureChart, setReportMeta } = useReportExport('querystats')

const dataRangeStore = useDataRangeStore()

// ── 筛选状态 ──
const buildingOptions = BUILDING_TYPE_OPTIONS
const selectedBuilding = ref<BuildingType>('Office')
const startDate = ref('')
const endDate = ref('')

// ── 自定义下拉状态 ──
const dropdownBuildingOpen = ref(false)
function closeQsDropdowns() {
  dropdownBuildingOpen.value = false
}
const loading = ref(false)
const queryResult = ref<any>(null)
const viewMode = ref<'data' | 'analysis'>('analysis')

const buildingLabel = computed(() =>
  getBuildingLabel(selectedBuilding.value, selectedBuilding.value)
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

interface CardHighlight {
  label: string
  value: string
}

interface AnalysisCard extends ChartGroup {
  highlights: CardHighlight[]
  layout: 'half' | 'full'
}

interface SummaryKpi {
  id: string
  label: string
  value: string
  subtext: string
  icon: string
}

interface AnalysisInsight {
  id: string
  tag: string
  title: string
  text: string
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
  {
    id: 'device',
    title: '设备运行概览',
    icon: 'mdi:cog-outline',
    paramKeys: ['device_normal_rate', 'ac_avg_power_kw'],
  },
]

const records = computed<any[]>(() => queryResult.value?.records ?? [])
const selectedParamKeys = computed(() => new Set(checkedParams.value.map(p => p.key)))
const hasEnergyParams = computed(() => ['electricity_kwh', 'water_m3', 'hac_energy'].some(k => selectedParamKeys.value.has(k)))
const hasEnvParams = computed(() => ['air_temp_c', 'sim_supply_temp_c', 'sim_return_temp_c', 'dew_temp_c', 'humidity_rh_pct'].some(k => selectedParamKeys.value.has(k)))
const hasDeviceParams = computed(() => deviceStatusChecked.value)

const activeChartGroups = computed(() => {
  const groups: ChartGroup[] = []
  if (hasEnergyParams.value) groups.push(CHART_GROUPS.find(g => g.id === 'energy')!)
  if (hasEnvParams.value) groups.push(CHART_GROUPS.find(g => g.id === 'temperature')!)
  if (hasDeviceParams.value) groups.push(CHART_GROUPS.find(g => g.id === 'device')!)
  groups.push(CHART_GROUPS.find(g => g.id === 'cop')!)
  return groups
})

const COP_LOW_THRESHOLD = 3.0

const expectedDayCount = computed(() => {
  if (!startDate.value || !endDate.value) return 0
  const start = new Date(`${startDate.value}T00:00:00`)
  const end = new Date(`${endDate.value}T00:00:00`)
  if (Number.isNaN(start.getTime()) || Number.isNaN(end.getTime()) || end < start) return 0
  return Math.floor((end.getTime() - start.getTime()) / 86400000) + 1
})

const summaryKpis = computed<SummaryKpi[]>(() => {
  const items: SummaryKpi[] = []
  const totalDays = records.value.length
  const completeRate = expectedDayCount.value > 0 ? (totalDays / expectedDayCount.value) * 100 : 0
  const avgCop = averageOf('ac_cop')
  const minCop = minPoint('ac_cop')
  const lowCopDays = records.value.filter(r => {
    const v = parseNumeric(getRowValue(r, 'ac_cop'))
    return v != null && v < COP_LOW_THRESHOLD
  }).length

  items.push({
    id: 'days',
    label: '统计天数',
    value: `${totalDays} 天`,
    subtext: expectedDayCount.value ? `查询区间共 ${expectedDayCount.value} 天` : '按日汇总结果',
    icon: 'mdi:calendar-range',
  })
  items.push({
    id: 'completion',
    label: '数据完整率',
    value: `${completeRate.toFixed(0)}%`,
    subtext: completeRate >= 95 ? '查询区间数据较完整' : '区间内存在缺失天',
    icon: 'mdi:database-check-outline',
  })
  items.push({
    id: 'avg-cop',
    label: '平均 COP',
    value: formatMetric(avgCop, '', 2),
    subtext: minCop ? `最低 ${formatMetric(minCop.value, '', 2)} · 低效 ${lowCopDays} 天` : '暂无 COP 数据',
    icon: 'mdi:air-conditioner',
  })

  if (selectedParamKeys.value.has('electricity_kwh')) {
    const total = sumOf('electricity_kwh')
    const peak = maxPoint('electricity_kwh')
    items.push({
      id: 'total-electricity',
      label: '总用电',
      value: formatMetric(total, 'kWh', 0),
      subtext: peak ? `峰值日 ${formatShortDay(peak.day)} · ${formatMetric(peak.value, 'kWh', 0)}` : '无峰值日',
      icon: 'mdi:flash-outline',
    })
  }
  if (selectedParamKeys.value.has('hac_energy')) {
    const total = sumOf('hac_energy')
    const avg = averageOf('hac_energy')
    items.push({
      id: 'total-hac',
      label: '总空调能耗',
      value: formatMetric(total, 'kWh', 0),
      subtext: avg != null ? `日均 ${formatMetric(avg, 'kWh', 1)}` : '暂无空调能耗数据',
      icon: 'mdi:fan',
    })
  }
  if (selectedParamKeys.value.has('water_m3')) {
    const total = sumOf('water_m3')
    const peak = maxPoint('water_m3')
    items.push({
      id: 'total-water',
      label: '总用水',
      value: formatMetric(total, 'm³', 1),
      subtext: peak ? `峰值日 ${formatShortDay(peak.day)} · ${formatMetric(peak.value, 'm³', 1)}` : '暂无用水峰值',
      icon: 'mdi:water-outline',
    })
  }
  if (selectedParamKeys.value.has('air_temp_c')) {
    const avg = averageOf('air_temp_c')
    const peak = maxPoint('air_temp_c')
    items.push({
      id: 'avg-air-temp',
      label: '平均环境温度',
      value: formatMetric(avg, '°C', 1),
      subtext: peak ? `最高 ${formatMetric(peak.value, '°C', 1)} · ${formatShortDay(peak.day)}` : '暂无环境温度数据',
      icon: 'mdi:thermometer',
    })
  }
  if (hasDeviceParams.value) {
    const avg = averageOf('device_normal_rate')
    const low = minPoint('device_normal_rate')
    items.push({
      id: 'device-normal-rate',
      label: '设备正常率',
      value: avg != null ? `${avg.toFixed(0)}%` : '--',
      subtext: low ? `最低 ${low.value.toFixed(0)}% · ${formatShortDay(low.day)}` : '暂无设备状态数据',
      icon: 'mdi:check-decagram-outline',
    })
  }

  return items.slice(0, 6)
})

const analysisCards = computed<AnalysisCard[]>(() => {
  const groups = [...activeChartGroups.value]
  if (groups.length === 3) {
    const copIndex = groups.findIndex(group => group.id === 'cop')
    if (copIndex === 2) {
      const [copGroup] = groups.splice(copIndex, 1)
      groups.splice(1, 0, copGroup)
    }
  }

  return groups.map((group, index) => ({
    ...group,
    highlights: buildCardHighlights(group.id),
    layout: groups.length === 1 || (groups.length === 3 && index === 2) ? 'full' : 'half',
  }))
})

const analysisInsights = computed<AnalysisInsight[]>(() => {
  const items: AnalysisInsight[] = []

  if (hasEnergyParams.value) {
    const primaryEnergyKey = selectedParamKeys.value.has('electricity_kwh')
      ? 'electricity_kwh'
      : selectedParamKeys.value.has('hac_energy')
        ? 'hac_energy'
        : 'water_m3'
    const peak = maxPoint(primaryEnergyKey)
    if (peak) {
      const labelMap: Record<string, string> = {
        electricity_kwh: '用电',
        hac_energy: '空调能耗',
        water_m3: '用水',
      }
      const unitMap: Record<string, string> = {
        electricity_kwh: 'kWh',
        hac_energy: 'kWh',
        water_m3: 'm³',
      }
      items.push({
        id: 'energy-peak',
        tag: '峰值',
        title: `${labelMap[primaryEnergyKey]}峰值日`,
        text: `${formatShortDay(peak.day)} 达到 ${formatMetric(peak.value, unitMap[primaryEnergyKey], unitMap[primaryEnergyKey] === 'm³' ? 1 : 0)}，建议结合明细排查当天负荷来源。`,
      })
    }
  }

  const lowCopDays = records.value.filter(r => {
    const v = parseNumeric(getRowValue(r, 'ac_cop'))
    return v != null && v < COP_LOW_THRESHOLD
  }).length
  if (lowCopDays > 0) {
    items.push({
      id: 'cop-warning',
      tag: 'COP',
      title: '存在低效运行时段',
      text: `统计区间内共有 ${lowCopDays} 天 COP 低于 ${COP_LOW_THRESHOLD.toFixed(1)}，建议结合功率与供回水温差联动查看低效原因。`,
    })
  } else if (records.value.length) {
    items.push({
      id: 'cop-stable',
      tag: 'COP',
      title: 'COP 整体稳定',
      text: `当前区间未出现明显低于 ${COP_LOW_THRESHOLD.toFixed(1)} 的日级 COP，空调效率表现整体平稳。`,
    })
  }

  if (hasDeviceParams.value) {
    const lowDevice = minPoint('device_normal_rate')
    if (lowDevice) {
      items.push({
        id: 'device-warning',
        tag: '设备',
        title: '设备健康波动日',
        text: `${formatShortDay(lowDevice.day)} 设备正常率最低，仅 ${lowDevice.value.toFixed(0)}%。这一天适合优先联查设备告警与能耗波动。`,
      })
    }
  }

  if (hasEnvParams.value) {
    const maxTemp = maxPoint('air_temp_c')
    const minTemp = minPoint('air_temp_c')
    if (maxTemp && minTemp) {
      items.push({
        id: 'env-range',
        tag: '环境',
        title: '环境波动范围',
        text: `环境温度在 ${formatMetric(minTemp.value, '°C', 1)} 到 ${formatMetric(maxTemp.value, '°C', 1)} 间波动，可结合能耗走势判断是否存在季节性负荷变化。`,
      })
    }
  }

  if (hasEnergyParams.value && hasEnvParams.value) {
    const energyKey = selectedParamKeys.value.has('hac_energy') ? 'hac_energy' : 'electricity_kwh'
    const corr = calculateCorrelation('air_temp_c', energyKey)
    if (corr != null) {
      const label = energyKey === 'hac_energy' ? '空调能耗' : '用电'
      const relation = Math.abs(corr) >= 0.6 ? '明显相关' : Math.abs(corr) >= 0.35 ? '存在一定相关性' : '相关性较弱'
      items.push({
        id: 'relation',
        tag: '关联',
        title: `环境温度与${label}`,
        text: `环境温度与${label}${relation}（相关系数 ${corr.toFixed(2)}），建议把这两张图结合起来看，不要只单看某一个指标。`,
      })
    }
  }

  if (!items.length) {
    items.push({
      id: 'default',
      tag: '提示',
      title: '暂无明显异常',
      text: '当前所选参数下未发现突出的异常信号，可以切换到数据展示查看逐日明细。',
    })
  }

  return items.slice(0, 5)
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

function parseNumeric(value: any) {
  if (value == null || value === '') return null
  const num = Number(value)
  return Number.isFinite(num) ? num : null
}

function getNumericValues(paramKey: string) {
  return records.value
    .map(row => {
      const value = parseNumeric(getRowValue(row, paramKey))
      return value != null ? value : null
    })
    .filter((value): value is number => value != null)
}

function sumOf(paramKey: string) {
  const values = getNumericValues(paramKey)
  return values.length ? values.reduce((sum, value) => sum + value, 0) : null
}

function averageOf(paramKey: string) {
  const values = getNumericValues(paramKey)
  return values.length ? values.reduce((sum, value) => sum + value, 0) / values.length : null
}

function maxPoint(paramKey: string) {
  const pairs = records.value
    .map(row => {
      const value = parseNumeric(getRowValue(row, paramKey))
      return value != null ? { day: row.day?.slice(0, 10) ?? '', value } : null
    })
    .filter((pair): pair is { day: string, value: number } => pair != null)
  if (!pairs.length) return null
  return pairs.reduce((best, current) => current.value > best.value ? current : best)
}

function minPoint(paramKey: string) {
  const pairs = records.value
    .map(row => {
      const value = parseNumeric(getRowValue(row, paramKey))
      return value != null ? { day: row.day?.slice(0, 10) ?? '', value } : null
    })
    .filter((pair): pair is { day: string, value: number } => pair != null)
  if (!pairs.length) return null
  return pairs.reduce((best, current) => current.value < best.value ? current : best)
}

function formatMetric(value: number | null, unit = '', digits = 1) {
  if (value == null || !Number.isFinite(value)) return '--'
  const formatter = new Intl.NumberFormat('zh-CN', {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  })
  return unit ? `${formatter.format(value)} ${unit}` : formatter.format(value)
}

function formatShortDay(day?: string) {
  if (!day) return '--'
  const [year, month, date] = day.split('-')
  if (!year || !month || !date) return day
  return `${month}/${date}`
}

function calculateCorrelation(leftKey: string, rightKey: string) {
  const pairs = records.value
    .map(row => {
      const left = parseNumeric(getRowValue(row, leftKey))
      const right = parseNumeric(getRowValue(row, rightKey))
      return left != null && right != null ? { left, right } : null
    })
    .filter((pair): pair is { left: number, right: number } => pair != null)

  if (pairs.length < 3) return null

  const leftMean = pairs.reduce((sum, pair) => sum + pair.left, 0) / pairs.length
  const rightMean = pairs.reduce((sum, pair) => sum + pair.right, 0) / pairs.length
  const numerator = pairs.reduce((sum, pair) => sum + (pair.left - leftMean) * (pair.right - rightMean), 0)
  const leftVariance = pairs.reduce((sum, pair) => sum + (pair.left - leftMean) ** 2, 0)
  const rightVariance = pairs.reduce((sum, pair) => sum + (pair.right - rightMean) ** 2, 0)
  const denominator = Math.sqrt(leftVariance * rightVariance)

  if (!denominator) return null
  return numerator / denominator
}

function buildCardHighlights(groupId: string): CardHighlight[] {
  if (groupId === 'energy') {
    const highlights: CardHighlight[] = []
    if (selectedParamKeys.value.has('electricity_kwh')) {
      highlights.push({
        label: '总用电',
        value: formatMetric(sumOf('electricity_kwh'), 'kWh', 0),
      })
    }
    if (selectedParamKeys.value.has('hac_energy')) {
      highlights.push({
        label: '日均空调能耗',
        value: formatMetric(averageOf('hac_energy'), 'kWh', 1),
      })
    }
    if (selectedParamKeys.value.has('water_m3')) {
      highlights.push({
        label: '总用水',
        value: formatMetric(sumOf('water_m3'), 'm³', 1),
      })
    }
    const peak = maxPoint(selectedParamKeys.value.has('electricity_kwh') ? 'electricity_kwh' : selectedParamKeys.value.has('hac_energy') ? 'hac_energy' : 'water_m3')
    if (peak) {
      highlights.push({
        label: '峰值日',
        value: formatShortDay(peak.day),
      })
    }
    return highlights.slice(0, 4)
  }

  if (groupId === 'temperature') {
    const highlights: CardHighlight[] = []
    if (selectedParamKeys.value.has('air_temp_c')) {
      highlights.push({
        label: '平均环境温度',
        value: formatMetric(averageOf('air_temp_c'), '°C', 1),
      })
    }
    if (selectedParamKeys.value.has('humidity_rh_pct')) {
      highlights.push({
        label: '平均湿度',
        value: formatMetric(averageOf('humidity_rh_pct'), '%', 0),
      })
    }
    const supplyAvg = averageOf('sim_supply_temp_c')
    const returnAvg = averageOf('sim_return_temp_c')
    if (supplyAvg != null && returnAvg != null) {
      highlights.push({
        label: '平均供回水温差',
        value: formatMetric(Math.abs(returnAvg - supplyAvg), '°C', 1),
      })
    }
    return highlights.slice(0, 4)
  }

  if (groupId === 'device') {
    const lowest = minPoint('device_normal_rate')
    return [
      { label: '平均正常率', value: averageOf('device_normal_rate') != null ? `${averageOf('device_normal_rate')!.toFixed(0)}%` : '--' },
      { label: '平均 AC 功率', value: formatMetric(averageOf('ac_avg_power_kw'), 'kW', 1) },
      { label: '最低正常率日', value: lowest ? `${formatShortDay(lowest.day)} · ${lowest.value.toFixed(0)}%` : '--' },
    ]
  }

  if (groupId === 'cop') {
    const avgCop = averageOf('ac_cop')
    const minCop = minPoint('ac_cop')
    const lowDays = records.value.filter(row => {
      const value = parseNumeric(getRowValue(row, 'ac_cop'))
      return value != null && value < COP_LOW_THRESHOLD
    }).length

    return [
      { label: '平均 COP', value: formatMetric(avgCop, '', 2) },
      { label: '最低 COP', value: minCop ? formatMetric(minCop.value, '', 2) : '--' },
      { label: '低效天数', value: `${lowDays} 天` },
    ]
  }

  return []
}

// ── 公共 tooltip / xAxis 配置 ──
function sharedTooltip() {
  return {
    trigger: 'axis' as const,
    backgroundColor: 'rgba(255,255,255,0.98)',
    borderColor: '#edf1f4', borderWidth: 1,
    textStyle: { color: '#2d3239', fontSize: 12 },
    padding: [10, 14],
    axisPointer: {
      type: 'line' as const,
      lineStyle: { color: 'rgba(129, 140, 155, 0.35)', width: 1 },
    },
    extraCssText: 'box-shadow:0 10px 30px rgba(15,23,42,0.08);border-radius:12px;',
  }
}

function getXAxisLabelInterval(days: string[]) {
  const len = days.length
  if (len <= 8) return 0
  if (len <= 14) return 1
  if (len <= 24) return 2
  if (len <= 45) return 3
  if (len <= 75) return 5
  return 7
}

function formatAxisDayLabel(value: string) {
  const [year, month, date] = value.split('-')
  if (!year || !month || !date) return value
  return `${month}/${date}`
}

function sharedXAxis(days: string[], options: { boundaryGap?: boolean } = {}) {
  const interval = getXAxisLabelInterval(days)
  return {
    type: 'category' as const, data: days,
    boundaryGap: options.boundaryGap ?? false,
    axisLabel: {
      interval,
      formatter: (value: string) => formatAxisDayLabel(value),
      rotate: days.length > 36 ? 28 : 0,
      color: '#7e8792',
      fontSize: 10,
      margin: 12,
      hideOverlap: true,
      showMinLabel: true,
      showMaxLabel: true,
    },
    axisLine: { lineStyle: { color: '#edf1f4' } },
    axisTick: { show: false },
  }
}

function sharedLegend(items: string[], bottom = 10) {
  return {
    data: items,
    bottom,
    left: 'center' as const,
    icon: 'roundRect',
    itemWidth: 12,
    itemHeight: 8,
    textStyle: { color: '#8c939a', fontSize: 11 },
    itemGap: 16,
  }
}

function sharedZoom() {
  return [
    {
      type: 'slider' as const,
      xAxisIndex: 0,
      bottom: 6,
      height: 18,
      borderColor: 'transparent',
      backgroundColor: '#f3f6f8',
      dataBackground: {
        lineStyle: { color: 'rgba(148,163,184,0.35)' },
        areaStyle: { color: 'rgba(226,232,240,0.65)' },
      },
      fillerColor: 'rgba(76,175,80,0.14)',
      handleSize: 14,
      handleIcon: 'M8.7,11.9v-1.2H7.3v1.2H8.7z M8.7,9.4V8.1H7.3v1.2H8.7z M8.7,6.9V5.6H7.3v1.2H8.7z',
      handleStyle: {
        color: '#ffffff',
        borderColor: '#4caf50',
        borderWidth: 1.5,
        shadowBlur: 8,
        shadowColor: 'rgba(76,175,80,0.18)',
      },
      moveHandleStyle: { color: 'rgba(76,175,80,0.22)' },
      textStyle: { fontSize: 0, color: 'transparent' },
      showDetail: false,
      brushSelect: false,
      start: 0,
      end: 100,
    },
    { type: 'inside' as const, xAxisIndex: 0 },
  ]
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
    else if (group.id === 'device') renderDeviceChart(inst, data)
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
    legend: sharedLegend(series.map(s => s.name), hasZoom ? 42 : 18),
    grid: { left: 54, right: hasWater && kwhKeys.length > 0 ? 52 : 18, top: 44, bottom: hasZoom ? 88 : 62, containLabel: false },
    xAxis: sharedXAxis(days, { boundaryGap: true }),
    yAxis,
    dataZoom: hasZoom ? sharedZoom() : [],
    series,
    animationDuration: 600,
  })
}

// ── 图表 2: COP 与空调性能分析 ──
function renderCOPChart(inst: echarts.ECharts, data: any) {
  const records: any[] = data.records || []
  const days = records.map((r: any) => r.day?.slice(0, 10) || '')
  const hasZoom = days.length > 18

  const copData = makeSeriesData(records, 'ac_cop')
  const powerData = makeSeriesData(records, 'ac_avg_power_kw')
  const deltaData = makeSeriesData(records, 'supply_return_delta')

  const copColor = '#1565c0'
  const powerColor = '#66bb6a'
  const deltaColor = '#ffa726'

  inst.setOption({
    tooltip: sharedTooltip(),
    legend: sharedLegend(['COP值', 'AC功率 (kW)', '供回水温差 (°C)'], hasZoom ? 42 : 18),
    grid: { left: 54, right: 54, top: 44, bottom: hasZoom ? 88 : 62, containLabel: false },
    xAxis: sharedXAxis(days, { boundaryGap: true }),
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
  const hasZoom = days.length > 18
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
    legend: sharedLegend(series.map(s => s.name), hasZoom ? 42 : 18),
    grid: { left: 54, right: hasHumidity && tempKeys.length > 0 ? 54 : 18, top: 44, bottom: hasZoom ? 88 : 62, containLabel: false },
    xAxis: sharedXAxis(days),
    yAxis,
    dataZoom: hasZoom ? sharedZoom() : [],
    series,
    animationDuration: 600,
  })
}

// ── 图表 4: 设备运行概览 ──
function renderDeviceChart(inst: echarts.ECharts, data: any) {
  const rows: any[] = data.records || []
  const days = rows.map((r: any) => r.day?.slice(0, 10) || '')
  const hasZoom = days.length > 18
  const normalRateData = makeSeriesData(rows, 'device_normal_rate')
  const powerData = makeSeriesData(rows, 'ac_avg_power_kw')

  inst.setOption({
    tooltip: sharedTooltip(),
    legend: sharedLegend(['设备正常率', 'AC平均功率 (kW)'], hasZoom ? 42 : 18),
    grid: { left: 54, right: 54, top: 44, bottom: hasZoom ? 88 : 62, containLabel: false },
    xAxis: sharedXAxis(days, { boundaryGap: true }),
    yAxis: [
      {
        type: 'value',
        name: '%',
        position: 'left',
        min: 0,
        max: 100,
        nameTextStyle: { color: '#26a69a', fontSize: 12 },
        axisLine: { show: false },
        axisTick: { show: false },
        splitLine: { lineStyle: { color: '#f0f2f5', type: 'dashed' } },
        axisLabel: { color: '#8c939a', fontSize: 11 },
      },
      {
        type: 'value',
        name: 'kW',
        position: 'right',
        nameTextStyle: { color: '#ef5350', fontSize: 12 },
        axisLine: { show: false },
        axisTick: { show: false },
        splitLine: { show: false },
        axisLabel: { color: '#8c939a', fontSize: 11 },
      },
    ],
    series: [
      {
        name: '设备正常率',
        type: 'line',
        yAxisIndex: 0,
        data: normalRateData,
        lineStyle: { width: 2.5, color: PARAM_COLORS.device_normal_rate },
        areaStyle: {
          color: {
            type: 'linear',
            x: 0,
            y: 0,
            x2: 0,
            y2: 1,
            colorStops: [
              { offset: 0, color: 'rgba(38,166,154,0.16)' },
              { offset: 1, color: 'rgba(38,166,154,0.02)' },
            ],
          },
        },
        itemStyle: { color: PARAM_COLORS.device_normal_rate },
        smooth: true,
        symbol: 'circle',
        symbolSize: 5,
      },
      {
        name: 'AC平均功率 (kW)',
        type: 'bar',
        yAxisIndex: 1,
        data: powerData,
        itemStyle: { color: 'rgba(239,83,80,0.58)', borderRadius: [3, 3, 0, 0] },
        barMaxWidth: 22,
      },
    ],
    dataZoom: hasZoom ? sharedZoom() : [],
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
  background:
    radial-gradient(circle at top right, rgba(76, 175, 80, 0.05), transparent 24%),
    linear-gradient(180deg, #ffffff 0%, #fbfcfd 100%);
  border: 1px solid #e8edf2;
  border-radius: 16px;
  padding: 20px 24px 16px;
  box-shadow: 0 14px 34px rgba(15, 23, 42, 0.04), 0 2px 8px rgba(15, 23, 42, 0.03);
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

/* ── 统计分析层级 ── */
.analysis-stack {
  display: flex;
  flex-direction: column;
  gap: 18px;
}
.kpi-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 14px;
}
.kpi-card {
  position: relative;
  background: linear-gradient(180deg, #ffffff 0%, #fbfcfd 100%);
  border: 1px solid #e8edf2;
  border-radius: 16px;
  padding: 16px 18px 18px;
  box-shadow: 0 12px 28px rgba(15, 23, 42, 0.04), 0 2px 8px rgba(15, 23, 42, 0.03);
  overflow: hidden;
}
.kpi-card::before {
  content: '';
  position: absolute;
  left: 0;
  top: 0;
  right: 0;
  height: 3px;
  background: linear-gradient(90deg, rgba(76,175,80,0.9), rgba(76,175,80,0.18));
}
.kpi-card-top {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 12px;
}
.kpi-label {
  font-size: 12px;
  color: #8c939a;
  font-weight: 600;
  letter-spacing: 0.02em;
}
.kpi-icon { color: #4caf50; }
.kpi-value {
  font-size: 28px;
  line-height: 1.1;
  font-weight: 700;
  color: #24303a;
  margin-bottom: 8px;
}
.kpi-subtext {
  font-size: 12px;
  color: #8c939a;
  line-height: 1.5;
}
.analysis-grid {
  display: grid;
  grid-template-columns: repeat(12, minmax(0, 1fr));
  gap: 18px;
  align-items: stretch;
}
.analysis-card {
  min-width: 0;
  grid-column: span 6;
}
.analysis-card--full {
  grid-column: 1 / -1;
}
.analysis-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  padding: 12px 20px 0;
}
.analysis-meta-item {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  min-height: 34px;
  padding: 0 12px;
  border-radius: 999px;
  background: linear-gradient(180deg, #f8fafb 0%, #f2f6f8 100%);
  border: 1px solid #edf2f5;
}
.analysis-meta-label {
  font-size: 12px;
  color: #8c939a;
}
.analysis-meta-value {
  font-size: 12px;
  color: #2d3239;
  font-weight: 600;
}
.chart-container--analysis {
  min-height: 320px;
  padding-top: 6px;
}
.analysis-card--full .chart-container--analysis {
  min-height: 300px;
}
.insight-card {
  overflow: visible;
}
.insight-list {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 14px;
  padding: 16px 20px 20px;
}
.insight-item {
  display: flex;
  gap: 12px;
  align-items: flex-start;
  padding: 18px;
  border-radius: 16px;
  background: linear-gradient(180deg, #fcfefd 0%, #f5f9f7 100%);
  border: 1px solid #e9f0ec;
  box-shadow: inset 0 1px 0 rgba(255,255,255,0.55);
}
.insight-badge {
  min-width: 44px;
  height: 24px;
  padding: 0 8px;
  border-radius: 999px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  background: #e8f5e9;
  color: #2e7d32;
  font-size: 12px;
  font-weight: 700;
}
.insight-content {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.insight-title {
  font-size: 14px;
  font-weight: 600;
  color: #24303a;
}
.insight-text {
  font-size: 13px;
  line-height: 1.6;
  color: #5f6974;
}

/* ── 图表卡片 ── */
.chart-card {
  background: linear-gradient(180deg, #ffffff 0%, #fcfdfd 100%);
  border: 1px solid #e8edf2;
  border-radius: 18px;
  box-shadow: 0 16px 34px rgba(15, 23, 42, 0.05), 0 2px 10px rgba(15, 23, 42, 0.03);
  display: flex;
  flex-direction: column;
  overflow: hidden;
  flex-shrink: 0;
}
.chart-card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 18px 22px 0;
}
.chart-card-title {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 16px;
  font-weight: 600;
  color: #24303a;
}
.chart-title-icon { color: #4caf50; }
.chart-date-range {
  font-size: 12px;
  font-weight: 500;
  color: #8c939a;
  padding: 4px 12px;
  background: linear-gradient(180deg, #f6f8fa 0%, #f0f4f7 100%);
  border: 1px solid #edf2f5;
  border-radius: 999px;
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
  color: #a8b0b9;
  border-radius: 10px;
  cursor: pointer;
  transition: background 0.15s, color 0.15s, transform 0.15s;
}
.card-action-btn:hover { background: #f5f8fa; color: #4b5563; transform: rotate(-12deg); }
.chart-container {
  min-height: 420px;
  padding: 14px 18px 18px;
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
  .kpi-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .analysis-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .analysis-card,
  .analysis-card--energy,
  .analysis-card--temperature,
  .analysis-card--device,
  .analysis-card--cop,
  .analysis-card--full { grid-column: auto; }
  .insight-list { grid-template-columns: 1fr; }
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
  .kpi-grid { grid-template-columns: 1fr; gap: 10px; }
  .kpi-card { padding: 14px 14px 12px; }
  .kpi-value { font-size: 22px; }
  .analysis-grid { grid-template-columns: 1fr; }
  .analysis-meta { padding: 10px 14px 0; gap: 8px; }
  .analysis-meta-item { min-height: 30px; padding: 0 10px; }
  .insight-list { padding: 14px; grid-template-columns: 1fr; }
  .insight-item { padding: 14px; }
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
