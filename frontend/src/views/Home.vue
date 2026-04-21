<template>
  <div class="home-page">
    <header class="pg-header">
      <div class="pg-greeting">
        <h1 class="pg-title">
          你好，{{ displayName }}！
          <DotLottieVue class="pg-wave-lottie" src="/Hello%20World.json" autoplay loop />
        </h1>
        <p class="pg-sub">今天有什么可以为你效劳的？</p>
      </div>
      <div class="capsule-switcher" ref="capsuleRef">
        <div class="capsule-slider" :style="sliderStyle" />
        <button
          v-for="opt in buildingOptions"
          :key="opt.value"
          :ref="(el) => setBtnRef(el, opt.value)"
          class="capsule-btn"
          :class="{ active: activeBuilding === opt.value }"
          type="button"
          @click="handleBuildingSelect(opt.value)"
        >
          {{ opt.label }}
        </button>
      </div>
      <!-- 右侧：天气 + 铃铛 合并卡片 -->
      <div class="header-right-group">
        <div class="weather-widget"
            data-pick-id="weather"
            data-pick-type="weather"
            data-pick-title="天气信息"
            :data-pick-subtitle="`温度 ${weatherTemp != null ? Number(weatherTemp).toFixed(1) + '°C' : '--'}，湿度 ${weatherHumi ?? '--'}%`">
          <div class="weather-date">
            <Icon icon="mdi:calendar-month" width="13" />
            <span>{{ todayDisplay }}</span>
          </div>
          <div class="weather-divider"></div>
          <div class="weather-metrics">
            <div class="weather-item">
              <Icon icon="mdi:thermometer" width="14" class="weather-icon temp-icon" />
              <span class="weather-val">{{ weatherTemp != null ? Number(weatherTemp).toFixed(1) : '--' }}<small>°C</small></span>
            </div>
            <div class="weather-item">
              <Icon icon="mdi:water-percent" width="14" class="weather-icon humi-icon" />
              <span class="weather-val">{{ weatherHumi ?? '--' }}<small>%</small></span>
            </div>
          </div>
        </div>

        <div class="header-group-divider"></div>

        <button class="home-bell-btn" @click="notifStore.requestOpenMessages()" aria-label="消息中心">
          <Icon icon="mdi:bell-outline" width="17" />
          <span v-if="notifStore.unreadCount > 0" class="home-bell-dot"></span>
        </button>

      </div>
    </header>

    <section class="kpi-strip">
      <div
        v-for="k in kpis"
        :key="k.label"
        class="kpi-card"
        :data-pick-id="'kpi-' + k.label"
        data-pick-type="kpi"
        :data-pick-title="k.label"
        :data-pick-subtitle="String(k.value)"
      >
        <div class="kpi-ico" :class="k.anim" :style="{ background: k.bg, color: k.color }">
          <Icon :icon="k.icon" width="20" />
        </div>
        <div class="kpi-body">
          <span class="kpi-val">{{ k.value }}</span>
          <span class="kpi-lbl">{{ k.label }}</span>
        </div>
        <div class="kpi-right">
          <span class="kpi-tag" :style="{ color: k.color, background: k.bg }">{{ k.tag }}</span>
          <span v-if="k.change != null" class="kpi-trend" :class="k.change >= 0 ? 'up' : 'down'">
            <Icon :icon="k.change >= 0 ? 'mdi:trending-up' : 'mdi:trending-down'" width="14" />
            {{ k.change >= 0 ? '+' : '' }}{{ k.change }}%
          </span>
        </div>
      </div>
    </section>

    <HomeAllOverviewSection
      v-if="activeBuilding === 'all'"
      :ai-steward-loading="aiStewardLoading"
      :ai-steward-props="aiStewardCardData"
      :overview-data="overviewData"
      :anomaly-data="anomalyData"
      :overview-series-bundle="homeBundle?.overview_series ?? null"
      :use-bundle="true"
      :bundle-pending="homeBundleLoading"
      :sankey-data="sankeyData"
      @refresh="handleAiStewardRefresh"
      @view-all="handleAiStewardViewAll"
    />
    <HomeTeachingSection
      v-else-if="activeBuilding === 'Education'"
      :data-date="dataDateForSections"
      :bundle="sectionBundles.Education ?? null"
      :use-bundle="true"
      :bundle-pending="sectionOverviewLoading.Education"
      :chart-bundle-pending="sectionChartLoading.Education"
    />
    <HomeOfficeSection
      v-else-if="activeBuilding === 'Office'"
      :data-date="dataDateForSections"
      :overview-data="overviewData"
      :bundle="sectionBundles.Office ?? null"
      :use-bundle="true"
      :bundle-pending="sectionOverviewLoading.Office"
      :chart-bundle-pending="sectionChartLoading.Office"
    />
    <HomePublicSection
      v-else-if="activeBuilding === 'Public services'"
      :data-date="dataDateForSections"
      :bundle="sectionBundles['Public services'] ?? null"
      :use-bundle="true"
      :bundle-pending="sectionOverviewLoading['Public services']"
      :chart-bundle-pending="sectionChartLoading['Public services']"
    />
  </div>
</template>

<script setup lang="ts">
import { ref, computed, watch, onMounted, onUnmounted, nextTick } from 'vue'
import { Icon } from '@iconify/vue'
import { DotLottieVue } from '@lottiefiles/dotlottie-vue'
import { cachedApiFetch, peekCachedApi } from '@/api/cached'
import { isAbortError, startPerfSpan } from '@/utils/perf'
import { useBuildingStore } from '@/stores/buildingStore'
import { useAuthStore } from '@/stores/authStore'
import { useNotificationStore } from '@/stores/notificationCenterStore'
import HomeAllOverviewSection from '@/components/home/HomeAllOverviewSection.vue'
import HomeTeachingSection from '@/components/home/HomeTeachingSection.vue'
import HomeOfficeSection from '@/components/home/HomeOfficeSection.vue'
import HomePublicSection from '@/components/home/HomePublicSection.vue'
import { BUILDING_TYPE_ORDER, HOME_BUILDING_FILTER_OPTIONS, type BuildingFilterValue } from '@/constants/buildings'
import { MC } from '@/utils/homeCharts'
import { useReportExport } from '@/composables/useReportExport'
import type { ReportCardItem } from '@/stores/reportStore'

const buildingStore = useBuildingStore()
const authStore     = useAuthStore()
const notifStore    = useNotificationStore()
const { registerSection, setReportMeta } = useReportExport('home', {
  activateScopePrefixes: ['home'],
})

const displayName = computed(() => authStore.user?.username ?? '访客')

/** 始终显示客户端实际今天日期，与后端数据日期无关 */
const todayDisplay = computed(() => {
  const d = new Date()
  const y = d.getFullYear()
  const m = String(d.getMonth() + 1).padStart(2, '0')
  const day = String(d.getDate()).padStart(2, '0')
  return `${y}-${m}-${day}`
})

const dataDate = ref('')
const weatherTemp = ref<number | null>(null)
const weatherHumi = ref<number | null>(null)
const overviewData = ref<any>(null)
const anomalyData = ref<any[]>([])
const predictionData = ref<any>(null)
const aiStewardLoading = ref(false)
const homeBundle = ref<any>(null)
const homeBundleLoading = ref(false)
const sectionBundles = ref<Record<string, any | null>>({
  Education: null,
  Office: null,
  'Public services': null,
})
const sectionOverviewLoading = ref<Record<string, boolean>>({
  Education: false,
  Office: false,
  'Public services': false,
})
const sectionChartLoading = ref<Record<string, boolean>>({
  Education: false,
  Office: false,
  'Public services': false,
})
const sankeyData = ref<{
  nodes: { name: string }[]
  links: { source: string | number; target: string | number; value: number }[]
} | null>(null)
const HOME_BUNDLE_PATH = '/api/home/overview-bundle'
const HOME_PREDICTIONS_PATH = '/api/predictions/recent?hours=168'
const HOME_CACHE_TTL = 60_000
const SECTION_OVERVIEW_CACHE_TTL = 60_000
const SECTION_CHART_CACHE_TTL = 300_000
const AI_STEWARD_ELECTRICITY_PRICE = 0.85
const SECTION_BUILDING_TYPES = BUILDING_TYPE_ORDER as readonly Exclude<BuildingFilterValue, 'all'>[]
let homeLoadController: AbortController | null = null
const sectionOverviewInFlight = new Map<string, Promise<void>>()
const sectionChartInFlight = new Map<string, Promise<void>>()

type IdleWindow = Window & {
  requestIdleCallback?: (
    callback: (deadline: { didTimeout: boolean; timeRemaining: () => number }) => void,
    options?: { timeout?: number },
  ) => number
  cancelIdleCallback?: (handle: number) => void
}

let sectionPrefetchTimer = 0
let sectionPrefetchIdleHandle: number | null = null

const buildingOptions = HOME_BUILDING_FILTER_OPTIONS
const activeBuilding = ref<BuildingFilterValue>('all')
const capsuleRef = ref<HTMLElement | null>(null)
const btnRefs = new Map<string, HTMLElement>()

function setBtnRef(el: unknown, key: string) {
  if (el) btnRefs.set(key, el as HTMLElement)
}

function getSectionBundlePath(
  buildingType: Exclude<BuildingFilterValue, 'all'>,
  scope: 'overview' | 'charts' | 'all' = 'all',
) {
  return `/api/home/section-bundle?building_type=${encodeURIComponent(buildingType)}&scope=${scope}`
}

function getSectionOverviewBundlePath(buildingType: Exclude<BuildingFilterValue, 'all'>) {
  return getSectionBundlePath(buildingType, 'overview')
}

function getSectionChartBundlePath(buildingType: Exclude<BuildingFilterValue, 'all'>) {
  return getSectionBundlePath(buildingType, 'charts')
}

function applySectionBundle(buildingType: Exclude<BuildingFilterValue, 'all'>, data: any) {
  if (!data) return
  sectionBundles.value[buildingType] = {
    ...(sectionBundles.value[buildingType] ?? {}),
    ...data,
  }
}

const sliderStyle = computed(() => {
  const el = btnRefs.get(activeBuilding.value)
  if (!el || !capsuleRef.value) return { opacity: '0' }
  const parentRect = capsuleRef.value.getBoundingClientRect()
  const btnRect = el.getBoundingClientRect()
  return {
    width: `${btnRect.width}px`,
    transform: `translateX(${btnRect.left - parentRect.left}px)`,
    opacity: '1',
  }
})

const forceSliderUpdate = ref(0)
watch(activeBuilding, () => {
  nextTick(() => {
    forceSliderUpdate.value++
  })
})

function handleBuildingSelect(value: BuildingFilterValue) {
  activeBuilding.value = value
}

/** 子组件 API 用 YYYY-MM-DD；无数据时给今天避免空请求 */
const dataDateForSections = computed(() => {
  const d = dataDate.value
  if (d && d.length >= 10) return d.slice(0, 10)
  return new Date().toISOString().slice(0, 10)
})

const CARBON_FACTOR = 0.5703
const REPORT_BUILDING_ORDER = BUILDING_TYPE_ORDER
const SANKEY_LABEL_MAP: Record<string, string> = {
  water_leak: '水耗异常',
  electricity_overload: '电耗过载',
  hvac_overconsumption: 'HVAC 过耗',
  supply_temp_deviation: '供水温度偏离',
  return_temp_deviation: '回水温度偏离',
  db_flagged: '标注异常',
  night_high_power: '夜间高耗',
  flag_water: '水耗偏高',
  flag_electricity: '总电耗偏高',
  flag_hvac_energy: 'HVAC 能耗偏高',
  flag_supply_deviation: '供水温度偏离',
  flag_return_deviation: '回水温度偏离',
  A_low_efficiency: '主机效率衰退',
  B_small_deltaT: '水力失调',
  C_unexpected_on: '非预期开机',
  other_hvac: '其他 HVAC 故障',
}
const kpis = computed(() => {
  void forceSliderUpdate.value
  const ov = overviewData.value
  if (!ov) return []
  const sel = activeBuilding.value
  const buildings: any[] = ov.buildings ?? []
  const chg = ov.kpis_change ?? {}

  let elec = 0,
    water = 0,
    hac = 0
  let elecChg: number | null = null,
    waterChg: number | null = null
  let hacChg: number | null = null,
    carbonChg: number | null = null

  if (sel === 'all') {
    elec = Number(ov.kpis?.total_electricity_kwh ?? 0)
    water = Number(ov.kpis?.total_water_m3 ?? 0)
    hac = Number(ov.kpis?.total_hac_energy_kwh ?? 0)
    elecChg = chg.total_electricity_pct ?? null
    waterChg = chg.total_water_pct ?? null
    hacChg = chg.total_hac_pct ?? null
    carbonChg = chg.total_carbon_pct ?? null
  } else {
    const b = buildings.find((x: any) => x.building_type === sel)
    elec = b ? Number(b.total_electricity_kwh ?? 0) : 0
    water = b ? Number(b.total_water_m3 ?? 0) : 0
    hac = b ? Number(b.total_hac_energy_kwh ?? 0) : 0
    elecChg = b?.electricity_change_pct ?? null
    waterChg = b?.water_change_pct ?? null
    hacChg = b?.hac_change_pct ?? null
    carbonChg = b?.carbon_change_pct ?? null
  }
  const carbon = elec * CARBON_FACTOR

  return [
    {
      icon: 'mdi:lightning-bolt',
      label: '日总用电 (kWh)',
      value: elec.toFixed(1),
      change: elecChg,
      tag: '今日',
      bg: 'rgba(122,170,142,0.14)',
      color: MC.sage,
      anim: 'anim-bolt',
    },
    {
      icon: 'mdi:water',
      label: '日总用水 (m³)',
      value: water.toFixed(1),
      change: waterChg,
      tag: '今日',
      bg: 'rgba(123,159,199,0.14)',
      color: MC.blue,
      anim: 'anim-drop',
    },
    {
      icon: 'mdi:snowflake',
      label: '空调能耗 (kWh)',
      value: hac.toFixed(1),
      change: hacChg,
      tag: '今日',
      bg: 'rgba(155,143,196,0.14)',
      color: MC.lav,
      anim: 'anim-spin',
    },
    {
      icon: 'mdi:leaf',
      label: '碳排放量 (kg)',
      value: carbon.toFixed(1),
      change: carbonChg,
      tag: 'CO₂',
      bg: 'rgba(196,149,106,0.14)',
      color: MC.terra,
      anim: 'anim-breathe',
    },
  ]
})

function num(value: unknown): number | null {
  const n = Number(value)
  return Number.isFinite(n) ? n : null
}

function avg(values: Array<number | null | undefined>): number | null {
  const valid = values.filter((value): value is number => value != null && Number.isFinite(value))
  if (!valid.length) return null
  return valid.reduce((sum, value) => sum + value, 0) / valid.length
}

function formatDateTimeLabel(value: string | null | undefined): string {
  if (!value) return '--'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value.slice(0, 16).replace('T', ' ')
  const month = String(date.getMonth() + 1).padStart(2, '0')
  const day = String(date.getDate()).padStart(2, '0')
  const hour = String(date.getHours()).padStart(2, '0')
  const minute = String(date.getMinutes()).padStart(2, '0')
  return `${month}-${day} ${hour}:${minute}`
}

function formatPredictionMetric(metric: string | null | undefined): string {
  switch (metric) {
    case 'electricity_kwh':
      return '用电负荷'
    case 'water_l':
    case 'water_m3':
      return '用水负荷'
    case 'hac_energy':
      return '空调能耗'
    case 'sim_supply_temp_c':
      return '供水温度'
    case 'sim_return_temp_c':
      return '回水温度'
    default:
      return '运行指标'
  }
}

function formatPredictionValue(metric: string | null | undefined, value: unknown): string {
  const n = num(value)
  if (n == null) return '--'
  switch (metric) {
    case 'electricity_kwh':
    case 'hac_energy':
      return `${n.toFixed(1)} kWh`
    case 'water_l':
      return `${n.toFixed(1)} L`
    case 'water_m3':
      return `${n.toFixed(2)} m³`
    case 'sim_supply_temp_c':
    case 'sim_return_temp_c':
      return `${n.toFixed(1)}℃`
    default:
      return n.toFixed(1)
  }
}

const aiStewardCardData = computed(() => {
  const targetDate = dataDate.value?.slice(0, 10) ?? ''
  const overviewSeries = homeBundle.value?.overview_series ?? {}
  const predictions: any[] = predictionData.value?.predictions ?? []
  const predictionCount = Number(predictionData.value?.total ?? overviewData.value?.kpis?.prediction_warning_count ?? 0)
  const anomalyCount = Array.isArray(anomalyData.value) ? anomalyData.value.length : 0

  let avoidedKwh = 0
  for (const buildingType of REPORT_BUILDING_ORDER) {
    const records: any[] = overviewSeries?.[buildingType]?.rated_electricity?.records ?? []
    for (const record of records) {
      if ((record?.timestamp ?? '').slice(0, 10) !== targetDate) continue
      const actual = num(record?.actual) ?? 0
      const rated = num(record?.rated) ?? 0
      avoidedKwh += Math.max(rated - actual, 0)
    }
  }
  avoidedKwh = Number(avoidedKwh.toFixed(1))

  const savedCost = Number((avoidedKwh * AI_STEWARD_ELECTRICITY_PRICE).toFixed(2))
  const reducedCarbon = Number((avoidedKwh * CARBON_FACTOR).toFixed(1))

  let statusText = '状态: 极佳'
  let statusTone: 'success' | 'warning' | 'danger' | 'neutral' = 'success'
  if (anomalyCount > 0) {
    statusText = anomalyCount >= 5 ? '状态: 关注' : '状态: 稳定'
    statusTone = anomalyCount >= 5 ? 'danger' : 'warning'
  } else if (predictionCount > 0) {
    statusText = '状态: 稳定'
    statusTone = 'warning'
  }

  const futurePredictions = [...predictions]
    .filter((item) => item?.forecast_for_timestamp)
    .sort((a, b) => {
      const aTime = new Date(a.forecast_for_timestamp).getTime()
      const bTime = new Date(b.forecast_for_timestamp).getTime()
      return aTime - bTime
    })
  const nextPrediction = futurePredictions[0] ?? null

  const reportTitle = targetDate
    ? `${targetDate} AI 运行成效简报 (00:00 - 24:00)`
    : '昨日 AI 运行成效简报 (00:00 - 24:00)'
  const reportDesc = avoidedKwh > 0
    ? '根据后端额定基线与实际运行数据复盘，系统昨日保持平稳运行，并形成以下节能收益：'
    : '根据后端额定基线与实际运行数据复盘，系统昨日整体贴近基准运行，当前未形成明显节能结余。'

  let forecastTitle = '近期负荷前瞻'
  let forecastText = '预测预警模型当前未发现新增高风险偏离，系统将持续监测未来 6-12 小时负荷变化。'
  if (nextPrediction) {
    const deviationPct = Math.abs(num(nextPrediction.deviation_pct) ?? 0)
    const riskLabel = nextPrediction.risk_level === 'critical' ? '高风险' : '预警'
    forecastTitle = '预测预警前瞻'
    forecastText =
      `${nextPrediction.building_name ?? nextPrediction.building_type ?? '目标楼宇'}将在 ${formatDateTimeLabel(nextPrediction.forecast_for_timestamp)} ` +
      `出现${formatPredictionMetric(nextPrediction.metric_name)}偏离，预测值 ${formatPredictionValue(nextPrediction.metric_name, nextPrediction.predicted_value)}，` +
      `较期望值偏离 ${deviationPct.toFixed(1)}%（${riskLabel}）。`
  }

  const educationSection = sectionBundles.value.Education ?? null
  const educationDevices: any[] = educationSection?.status?.devices ?? []
  const educationAcDevices = educationDevices.filter((device) => device?.device_type === 'ac')
  const latestSupply = avg(educationAcDevices.map((device) => num(device?.latest_supply_temp_c)))
  const latestReturn = avg(educationAcDevices.map((device) => num(device?.latest_return_temp_c)))
  const hourlySupplyProfile: any[] = educationSection?.load_profile_supply_temp?.hourly_profile ?? []
  const avgSupply = avg(hourlySupplyProfile.map((item) => num(item?.avg_value)))

  let optimizeText = '系统正在结合教学楼供回水温与近 14 日运行曲线，持续评估可落地的调优空间。'
  if (latestSupply != null) {
    const parts = [`教学楼空调设备最新供水温度 ${latestSupply.toFixed(1)}℃`]
    if (latestReturn != null) {
      parts.push(`回水温度 ${latestReturn.toFixed(1)}℃`)
    }
    if (avgSupply != null) {
      const delta = Number((latestSupply - avgSupply).toFixed(1))
      if (Math.abs(delta) >= 0.5) {
        parts.push(`较近 14 日小时均值 ${avgSupply.toFixed(1)}℃${delta > 0 ? '偏高' : '偏低'} ${Math.abs(delta).toFixed(1)}℃`)
      } else {
        parts.push(`与近 14 日小时均值 ${avgSupply.toFixed(1)}℃基本一致`)
      }
    }
    optimizeText = `${parts.join('，')}。系统将持续评估供回水温差与节能优化空间。`
  } else {
    const hvacTopBuilding = [...(overviewData.value?.buildings ?? [])]
      .sort((a, b) => Number(b?.total_hac_energy_kwh ?? 0) - Number(a?.total_hac_energy_kwh ?? 0))[0]
    if (hvacTopBuilding) {
      optimizeText =
        `${hvacTopBuilding.display_name}当日空调能耗 ${Number(hvacTopBuilding.total_hac_energy_kwh ?? 0).toFixed(1)} kWh，` +
        '当前为全局 HVAC 重点关注楼宇。系统将继续跟踪其运行优化空间。'
    }
  }

  return {
    statusText,
    statusTone,
    reportTitle,
    reportDesc,
    stats: [
      { label: '节省电费', value: savedCost.toFixed(2), prefix: '￥' },
      { label: '减少碳排放', value: reducedCarbon.toFixed(1), suffix: 'kg' },
      { label: '避免无效电耗', value: avoidedKwh.toFixed(1), suffix: 'kWh' },
    ],
    forecastTitle,
    forecastText,
    optimizeTitle: '深度寻优潜力',
    optimizeText,
  }
})

function formatMetric(value: number | null | undefined, unit: string, digits = 1): string {
  const n = Number(value ?? 0)
  return `${n.toFixed(digits)} ${unit}`
}

function formatBuildingLabel(buildingType: string): string {
  return buildingStore.getBuildingName(buildingType)
}

function buildHomeReportKpis(ov: any) {
  const totals = ov?.kpis ?? {}
  const chg = ov?.kpis_change ?? {}
  const totalElectricity = Number(totals.total_electricity_kwh ?? 0)
  const totalWater = Number(totals.total_water_m3 ?? 0)
  const totalHvac = Number(totals.total_hac_energy_kwh ?? 0)
  const totalCarbon = totalElectricity * CARBON_FACTOR

  return [
    { label: '日总用电 (kWh)', value: totalElectricity.toFixed(1), trend: chg.total_electricity_pct ?? null },
    { label: '日总用水 (m³)', value: totalWater.toFixed(1), trend: chg.total_water_pct ?? null },
    { label: 'HVAC 能耗 (kWh)', value: totalHvac.toFixed(1), trend: chg.total_hac_pct ?? null },
    { label: '碳排放量 (kg)', value: totalCarbon.toFixed(1), trend: chg.total_carbon_pct ?? null },
    { label: '预测预警', value: String(Number(totals.prediction_warning_count ?? 0)), trend: null },
  ]
}

function buildHomeBuildingCards(ov: any, anomalies: any[]) {
  const buildings: any[] = ov?.buildings ?? []
  const anomalyCountMap = new Map<string, number>()
  anomalies.forEach((item: any) => {
    const key = String(item?.building_type ?? '')
    anomalyCountMap.set(key, (anomalyCountMap.get(key) ?? 0) + 1)
  })

  return REPORT_BUILDING_ORDER
    .map((buildingType) => {
      const building = buildings.find((item: any) => item.building_type === buildingType)
      if (!building) return null
      return {
        title: formatBuildingLabel(buildingType),
        subtitle: '当日楼宇摘要',
        metrics: [
          { label: '日用电', value: formatMetric(building.total_electricity_kwh, 'kWh') },
          { label: '日用水', value: formatMetric(building.total_water_m3, 'm³') },
          { label: 'HVAC', value: formatMetric(building.total_hac_energy_kwh, 'kWh') },
          { label: '近 7 天异常', value: `${anomalyCountMap.get(buildingType) ?? 0} 条` },
        ],
      }
    })
    .filter((item): item is ReportCardItem & { subtitle: string } => item != null)
}

function resolveSankeyNodeName(value: string | number, nodes: { name: string }[]): string {
  const raw = typeof value === 'number' ? nodes[value]?.name ?? String(value) : value
  return raw.replace(/\((?:direct|直接)\)$/i, '')
}

function resolveTopSankeyCause(data: typeof sankeyData.value): string | null {
  if (!data?.links?.length) return null
  const weights = new Map<string, number>()
  data.links.forEach((link) => {
    const target = resolveSankeyNodeName(link.target, data.nodes)
    weights.set(target, (weights.get(target) ?? 0) + Number(link.value ?? 0))
  })
  const [topCause] = [...weights.entries()].sort((a, b) => b[1] - a[1])[0] ?? []
  if (!topCause) return null
  return SANKEY_LABEL_MAP[topCause] ?? topCause
}

function buildHomeInsight(ov: any, anomalies: any[], data: typeof sankeyData.value): string {
  const buildings: any[] = ov?.buildings ?? []
  const totalElectricity = Number(ov?.kpis?.total_electricity_kwh ?? 0)
  const totalWater = Number(ov?.kpis?.total_water_m3 ?? 0)
  const totalHvac = Number(ov?.kpis?.total_hac_energy_kwh ?? 0)
  const predictionCount = Number(ov?.kpis?.prediction_warning_count ?? 0)

  const topElectricity = [...buildings].sort(
    (a, b) => Number(b.total_electricity_kwh ?? 0) - Number(a.total_electricity_kwh ?? 0),
  )[0]
  const topHvac = [...buildings].sort(
    (a, b) => Number(b.total_hac_energy_kwh ?? 0) - Number(a.total_hac_energy_kwh ?? 0),
  )[0]

  const anomalyCountMap = new Map<string, number>()
  anomalies.forEach((item: any) => {
    const key = String(item?.building_type ?? '')
    anomalyCountMap.set(key, (anomalyCountMap.get(key) ?? 0) + 1)
  })
  const [topAnomalyEntry] = [...anomalyCountMap.entries()].sort((a, b) => b[1] - a[1])[0] ?? []
  const topCause = resolveTopSankeyCause(data)

  const summaryLines = [
    `- 今日总用电为 **${totalElectricity.toFixed(1)} kWh**，总用水为 **${totalWater.toFixed(1)} m³**，HVAC 能耗为 **${totalHvac.toFixed(1)} kWh**。`,
    topElectricity
      ? `- **${formatBuildingLabel(topElectricity.building_type)}** 是当前综合能耗的主要贡献楼宇，用电 ${formatMetric(topElectricity.total_electricity_kwh, 'kWh')}。`
      : '- 当前暂无可用楼宇对比数据。',
    topHvac
      ? `- HVAC 负荷最高的楼宇为 **${formatBuildingLabel(topHvac.building_type)}**，暖通能耗 ${formatMetric(topHvac.total_hac_energy_kwh, 'kWh')}。`
      : '- 当前暂无 HVAC 负荷对比数据。',
  ]

  const riskLines = [
    anomalies.length > 0
      ? `- 近 7 天累计异常 **${anomalies.length}** 条，预测预警 **${predictionCount}** 条。`
      : `- 当前未发现近期异常事件，但仍有 **${predictionCount}** 条预测预警需持续跟踪。`,
    topAnomalyEntry
      ? `- 异常最集中的楼宇为 **${formatBuildingLabel(topAnomalyEntry[0])}**，共 ${topAnomalyEntry[1]} 条。`
      : '- 当前异常分布较为均匀，未出现单一楼宇集中失稳。',
    topCause
      ? `- 桑基图显示当前最主要的异常根因为 **${topCause}**。`
      : '- 当前未形成明确的根因聚集，需要结合时段与设备进一步复核。',
  ]

  const actionLines = [
    topAnomalyEntry
      ? `1. 优先复核 **${formatBuildingLabel(topAnomalyEntry[0])}** 的高频异常时段与对应设备。`
      : '1. 继续保持现有运行策略，并关注新增预测预警。',
    topHvac
      ? `2. 针对 **${formatBuildingLabel(topHvac.building_type)}** 复查 HVAC 开停策略与节能基准偏差。`
      : '2. 对关键楼宇执行一次 HVAC 运行参数抽查。',
    topCause
      ? `3. 围绕 **${topCause}** 对应回路补做一次定向排查与复盘。`
      : '3. 结合异常事件与楼宇占比图，补做一次分时段能耗复盘。',
  ]

  return [
    '### 管理摘要',
    ...summaryLines,
    '',
    '### 风险提示',
    ...riskLines,
    '',
    '### 建议动作',
    ...actionLines,
  ].join('\n')
}

function registerHomeReportSections() {
  const ov = overviewData.value
  if (!ov) return

  setReportMeta({
    title: '首页总览报表',
    subtitle: dataDate.value ? `数据日期：${dataDate.value.slice(0, 10)}` : '首页全局概览快照',
  })

  registerSection({
    id: 'home-kpi',
    title: '核心 KPI',
    type: 'kpi',
    order: 10,
    kpis: buildHomeReportKpis(ov),
  })

  const cards = buildHomeBuildingCards(ov, anomalyData.value)
  if (cards.length) {
    registerSection({
      id: 'home-buildings',
      title: '楼宇摘要卡',
      description: '按教学楼、办公楼、公共楼展示当日能耗与近 7 天异常概况。',
      type: 'cards',
      order: 20,
      cards,
    })
  }

  registerSection({
    id: 'home-insight',
    title: 'AI 洞察与建议',
    description: '基于首页总览数据自动生成的运行摘要、风险提示与建议动作。',
    type: 'text',
    contentFormat: 'markdown',
    content: buildHomeInsight(ov, anomalyData.value, sankeyData.value),
    order: 50,
  })
}

function applyOverview(data: any) {
  overviewData.value = data
  dataDate.value = data?.data_date ?? ''
  weatherTemp.value = data?.weather?.temperature ?? null
  weatherHumi.value = data?.weather?.humidity ?? null
}

function applyAnomalies(data: any) {
  anomalyData.value = data?.anomalies ?? []
}

function applySankey(data: any) {
  sankeyData.value = data?.nodes?.length && data?.links?.length ? data : null
}

function applyPredictions(data: any) {
  predictionData.value = data ?? { predictions: [], total: 0 }
}

function applyHomeBundle(data: any) {
  homeBundle.value = data ?? null
  if (data?.overview) applyOverview(data.overview)
  if (data?.anomalies) applyAnomalies(data.anomalies)
  if (data?.sankey) applySankey(data.sankey)
}

type SectionBundleStage = 'overview' | 'charts'

function getSectionStagePath(
  buildingType: Exclude<BuildingFilterValue, 'all'>,
  stage: SectionBundleStage,
) {
  return stage === 'overview'
    ? getSectionOverviewBundlePath(buildingType)
    : getSectionChartBundlePath(buildingType)
}

function getSectionStageTtl(stage: SectionBundleStage) {
  return stage === 'overview' ? SECTION_OVERVIEW_CACHE_TTL : SECTION_CHART_CACHE_TTL
}

function getSectionStageLoadingState(stage: SectionBundleStage) {
  return stage === 'overview' ? sectionOverviewLoading.value : sectionChartLoading.value
}

function getSectionStageInFlightMap(stage: SectionBundleStage) {
  return stage === 'overview' ? sectionOverviewInFlight : sectionChartInFlight
}

function hydrateHomeCache() {
  const bundle = peekCachedApi<any>(HOME_BUNDLE_PATH, { ttlMs: HOME_CACHE_TTL })
  if (bundle.data) {
    applyHomeBundle(bundle.data)
  }

  const sectionOverviewFresh: Record<string, boolean> = {}
  const sectionChartFresh: Record<string, boolean> = {}
  SECTION_BUILDING_TYPES.forEach((buildingType) => {
    const overviewSnapshot = peekCachedApi<any>(getSectionOverviewBundlePath(buildingType), {
      ttlMs: SECTION_OVERVIEW_CACHE_TTL,
    })
    const chartSnapshot = peekCachedApi<any>(getSectionChartBundlePath(buildingType), {
      ttlMs: SECTION_CHART_CACHE_TTL,
    })
    if (overviewSnapshot.data) {
      applySectionBundle(buildingType, overviewSnapshot.data)
    }
    if (chartSnapshot.data) {
      applySectionBundle(buildingType, chartSnapshot.data)
    }
    sectionOverviewFresh[buildingType] = overviewSnapshot.isFresh
    sectionChartFresh[buildingType] = chartSnapshot.isFresh
  })

  const overview = peekCachedApi<any>('/api/overview', { ttlMs: HOME_CACHE_TTL })
  const anomalies = peekCachedApi<any>('/api/anomalies/recent?hours=168', { ttlMs: HOME_CACHE_TTL })
  const sankey = peekCachedApi<any>('/api/anomalies/sankey', { ttlMs: HOME_CACHE_TTL })
  const predictions = peekCachedApi<any>(HOME_PREDICTIONS_PATH, { ttlMs: HOME_CACHE_TTL })

  if (!bundle.data && overview.data) applyOverview(overview.data)
  if (!bundle.data && anomalies.data) applyAnomalies(anomalies.data)
  if (!bundle.data && sankey.data) applySankey(sankey.data)
  if (predictions.data) applyPredictions(predictions.data)

  return {
    bundleFresh: bundle.isFresh,
    overviewFresh: overview.isFresh,
    anomaliesFresh: anomalies.isFresh,
    sankeyFresh: sankey.isFresh,
    predictionsFresh: predictions.isFresh,
    sectionOverviewFresh,
    sectionChartFresh,
  }
}

async function fetchOverview(force = false, signal?: AbortSignal) {
  try {
    const data = await cachedApiFetch<any>('/api/overview', undefined, {
      force,
      signal,
      ttlMs: HOME_CACHE_TTL,
    })
    applyOverview(data)
  } catch (error) {
    if (isAbortError(error)) return
    /* silent */
  }
}

async function fetchAnomalies(force = false, signal?: AbortSignal) {
  try {
    const data = await cachedApiFetch<any>('/api/anomalies/recent?hours=168', undefined, {
      force,
      signal,
      ttlMs: HOME_CACHE_TTL,
    })
    applyAnomalies(data)
  } catch (error) {
    if (isAbortError(error)) return
    /* silent */
  }
}

async function fetchSankeyData(force = false, signal?: AbortSignal) {
  try {
    const data = await cachedApiFetch<any>('/api/anomalies/sankey', undefined, {
      force,
      signal,
      ttlMs: HOME_CACHE_TTL,
    })
    applySankey(data)
  } catch (error) {
    if (isAbortError(error)) return
    /* silent */
  }
}

async function fetchPredictions(force = false, signal?: AbortSignal) {
  try {
    const data = await cachedApiFetch<any>(HOME_PREDICTIONS_PATH, undefined, {
      force,
      signal,
      ttlMs: HOME_CACHE_TTL,
    })
    applyPredictions(data)
  } catch (error) {
    if (isAbortError(error)) return
    /* silent */
  }
}

async function fetchSectionBundleStage(
  buildingType: Exclude<BuildingFilterValue, 'all'>,
  stage: SectionBundleStage,
  force = false,
  options: { silent?: boolean } = {},
) {
  const inFlightMap = getSectionStageInFlightMap(stage)
  const existingTask = inFlightMap.get(buildingType)
  if (existingTask) {
    await existingTask
    return
  }

  const loadingState = getSectionStageLoadingState(stage)
  if (!options.silent) {
    loadingState[buildingType] = true
  }

  const task = (async () => {
    try {
      const data = await cachedApiFetch<any>(getSectionStagePath(buildingType, stage), undefined, {
        force,
        ttlMs: getSectionStageTtl(stage),
      })
      applySectionBundle(buildingType, data)
    } catch (error) {
      if (isAbortError(error)) return
      /* silent */
    } finally {
      if (!options.silent) {
        loadingState[buildingType] = false
      }
      inFlightMap.delete(buildingType)
    }
  })()

  inFlightMap.set(buildingType, task)
  await task
}

async function ensureSectionBundleStage(
  buildingType: Exclude<BuildingFilterValue, 'all'>,
  stage: SectionBundleStage,
  options: { force?: boolean; silent?: boolean } = {},
) {
  const snapshot = peekCachedApi<any>(getSectionStagePath(buildingType, stage), {
    ttlMs: getSectionStageTtl(stage),
  })
  if (snapshot.data) {
    applySectionBundle(buildingType, snapshot.data)
  }
  if (!options.force && snapshot.isFresh) return
  await fetchSectionBundleStage(buildingType, stage, options.force ?? false, {
    silent: options.silent,
  })
}

async function ensureActiveSectionBundle(
  buildingType: Exclude<BuildingFilterValue, 'all'>,
  options: { force?: boolean } = {},
) {
  await ensureSectionBundleStage(buildingType, 'overview', { force: options.force })
  const chartSnapshot = peekCachedApi<any>(getSectionChartBundlePath(buildingType), {
    ttlMs: SECTION_CHART_CACHE_TTL,
  })
  if (chartSnapshot.data) {
    applySectionBundle(buildingType, chartSnapshot.data)
  }
  if (!options.force && chartSnapshot.isFresh) return
  sectionChartLoading.value[buildingType] = true
  const runCharts = () => {
    void ensureSectionBundleStage(buildingType, 'charts', { force: options.force })
  }
  const idleWindow = window as IdleWindow
  if (idleWindow.requestIdleCallback) {
    idleWindow.requestIdleCallback(() => runCharts(), { timeout: 360 })
    return
  }
  window.setTimeout(runCharts, 32)
}

function clearSectionPrefetchSchedule() {
  if (sectionPrefetchTimer) {
    window.clearTimeout(sectionPrefetchTimer)
    sectionPrefetchTimer = 0
  }

  const idleWindow = window as IdleWindow
  if (sectionPrefetchIdleHandle != null && idleWindow.cancelIdleCallback) {
    idleWindow.cancelIdleCallback(sectionPrefetchIdleHandle)
    sectionPrefetchIdleHandle = null
  }
}

function scheduleSectionPrefetch(exclude: BuildingFilterValue = activeBuilding.value) {
  clearSectionPrefetchSchedule()

  const targets = SECTION_BUILDING_TYPES.filter((buildingType) => buildingType !== exclude)
  if (!targets.length) return

  const runPrefetch = async () => {
    for (const buildingType of targets) {
      await ensureSectionBundleStage(buildingType, 'overview', { silent: true })
    }
  }

  const idleWindow = window as IdleWindow
  if (idleWindow.requestIdleCallback) {
    sectionPrefetchIdleHandle = idleWindow.requestIdleCallback(() => {
      sectionPrefetchIdleHandle = null
      void runPrefetch()
    }, { timeout: 1200 })
    return
  }

  sectionPrefetchTimer = window.setTimeout(() => {
    sectionPrefetchTimer = 0
    void runPrefetch()
  }, 1200)
}

async function fetchHomeBundle(force = false) {
  homeLoadController?.abort()
  const controller = new AbortController()
  homeLoadController = controller
  const finish = startPerfSpan('home.bundle.load', { force })
  homeBundleLoading.value = true
  try {
    const data = await cachedApiFetch<any>(HOME_BUNDLE_PATH, undefined, {
      force,
      signal: controller.signal,
      ttlMs: HOME_CACHE_TTL,
    })
    if (homeLoadController !== controller || controller.signal.aborted) return
    applyHomeBundle(data)
    scheduleSectionPrefetch(activeBuilding.value)
    finish('ok', { source: 'bundle' })
  } catch (error) {
    if (isAbortError(error)) {
      finish('abort')
      return
    }
    homeBundle.value = null
    await Promise.all([
      fetchOverview(force, controller.signal),
      fetchAnomalies(force, controller.signal),
      fetchSankeyData(force, controller.signal),
      fetchPredictions(force, controller.signal),
    ])
    if (homeLoadController !== controller || controller.signal.aborted) return
    finish('ok', { source: 'fallback' })
  } finally {
    if (homeLoadController === controller) {
      homeBundleLoading.value = false
    }
  }
}

async function handleAiStewardRefresh() {
  if (aiStewardLoading.value) return
  aiStewardLoading.value = true
  try {
    await Promise.all([fetchHomeBundle(true), fetchPredictions(true)])
  } finally {
    aiStewardLoading.value = false
  }
}

function handleAiStewardViewAll() {
  activeBuilding.value = 'all'
}

const initialHomeCache = hydrateHomeCache()
homeBundleLoading.value = !initialHomeCache.bundleFresh

watch(activeBuilding, (value) => {
  if (value !== 'all') {
    void ensureActiveSectionBundle(value)
  }
  scheduleSectionPrefetch(value)
})

onMounted(async () => {
  void buildingStore.fetchBuildings()
  const tasks: Promise<void>[] = []
  if (!initialHomeCache.bundleFresh) tasks.push(fetchHomeBundle(true))
  if (!initialHomeCache.predictionsFresh) tasks.push(fetchPredictions(true))
  if (tasks.length) await Promise.all(tasks)
  scheduleSectionPrefetch(activeBuilding.value)
})

onUnmounted(() => {
  homeLoadController?.abort()
  homeLoadController = null
  clearSectionPrefetchSchedule()
})

// ── 报表集成 ─────────────────────────────────────────────────
watch(
  () => [overviewData.value, anomalyData.value, sankeyData.value],
  ([overview, anomalies]) => {
    if (!overview) return

    registerHomeReportSections()
    registerSection({
      id: 'home-anomalies',
      title: '近期异常概况',
      type: 'summary',
      order: 30,
      summaryItems: [
        { label: '异常事件总数', value: String(anomalies.length) },
        { label: '严重级别', value: `${anomalies.filter((a: any) => a.severity === 'critical').length} 条 CRITICAL` },
        { label: '告警级别', value: `${anomalies.filter((a: any) => a.severity === 'warning').length} 条 WARNING` },
      ],
    })
  },
  { deep: true, immediate: true },
)

</script>

<style scoped>
.home-page {
  container-type: inline-size;
  padding: 28px 24px 32px;
  min-height: 100%;
  background: var(--bg-dark);
  color: var(--text-primary);
  display: flex;
  flex-direction: column;
  gap: 16px;
  box-sizing: border-box;
}

.pg-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-shrink: 0;
  flex-wrap: wrap;
  gap: 10px;
}

.capsule-switcher {
  position: relative;
  display: inline-flex;
  align-items: center;
  background: var(--bg-panel);
  border: 1px solid var(--border);
  border-radius: 24px;
  padding: 3px;
  gap: 0;
  flex-shrink: 0;
}
.capsule-slider {
  position: absolute;
  top: 3px;
  left: 0;
  height: calc(100% - 6px);
  border-radius: 20px;
  background: var(--border-accent, rgba(122, 170, 142, 0.35));
  transition:
    transform 0.3s cubic-bezier(0.4, 0, 0.2, 1),
    width 0.3s cubic-bezier(0.4, 0, 0.2, 1);
  pointer-events: none;
  z-index: 0;
}
.capsule-btn {
  position: relative;
  z-index: 1;
  border: none;
  outline: none;
  background: transparent;
  color: var(--text-secondary);
  font-size: 12px;
  font-weight: 500;
  padding: 5px 16px;
  border-radius: 20px;
  cursor: pointer;
  transition: color 0.25s;
  white-space: nowrap;
}
.capsule-btn.active {
  color: var(--text-primary);
  font-weight: 600;
}
.capsule-btn:hover:not(.active) {
  color: var(--text-primary);
}
.pg-greeting {
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.pg-title {
  font-size: 22px;
  font-weight: 800;
  color: var(--text-primary);
  letter-spacing: -0.02em;
  line-height: 1.2;
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
}
.pg-wave-lottie {
  width: 36px;
  height: 36px;
  display: inline-block;
  flex-shrink: 0;
}
@container (max-width: 539px) {
  .pg-wave-lottie {
    width: 28px;
    height: 28px;
  }
}
@container (max-width: 399px) {
  .pg-wave-lottie {
    width: 22px;
    height: 22px;
  }
}
.pg-sub {
  font-size: 13px;
  color: var(--text-secondary);
  font-weight: 400;
}
/* ── 右侧天气+铃铛整体容器 ── */
.header-right-group {
  display: flex;
  align-items: center;
  background: var(--bg-panel);
  border: 1px solid var(--border);
  border-radius: 12px;
  padding: 0;
  overflow: hidden;
  flex-shrink: 0;
}
.header-group-divider {
  width: 1px;
  height: 22px;
  background: var(--border);
  flex-shrink: 0;
}

/* ── 消息铃铛 ── */
.home-bell-btn {
  position: relative;
  display: flex;
  align-items: center;
  justify-content: center;
  width: 42px;
  height: 38px;
  border: none;
  background: transparent;
  color: var(--text-secondary);
  cursor: pointer;
  flex-shrink: 0;
  transition: background 0.18s ease, color 0.18s ease;
}
.home-bell-dot {
  position: absolute;
  top: 7px;
  right: 8px;
  width: 7px;
  height: 7px;
  background: #e53e3e;
  border-radius: 50%;
  border: none;
}

.weather-widget {
  display: flex;
  align-items: center;
  gap: 10px;
  background: transparent;
  padding: 8px 14px;
  flex-shrink: 0;
}
.weather-date {
  display: flex;
  align-items: center;
  gap: 5px;
  font-size: 12px;
  color: var(--text-secondary);
  white-space: nowrap;
}
.weather-divider {
  width: 1px;
  height: 22px;
  background: var(--border);
  flex-shrink: 0;
}
.weather-metrics {
  display: flex;
  align-items: center;
  gap: 12px;
}
.weather-item {
  display: flex;
  align-items: center;
  gap: 4px;
}
.weather-icon {
  flex-shrink: 0;
}
.temp-icon {
  color: #e8845a;
}
.humi-icon {
  color: #5a9fd4;
}
.weather-val {
  font-size: 13px;
  font-weight: 600;
  color: var(--text-primary);
  white-space: nowrap;
}
.weather-val small {
  font-size: 10px;
  font-weight: 400;
  color: var(--text-secondary);
  margin-left: 1px;
}

.kpi-strip {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 10px;
  flex-shrink: 0;
}
.kpi-card {
  background: var(--bg-panel);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 12px 14px;
  display: flex;
  align-items: center;
  gap: 10px;
  transition: border-color 0.2s;
}
.kpi-card:hover {
  border-color: var(--border-accent);
}
.kpi-ico {
  width: 36px;
  height: 36px;
  border-radius: 10px;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  transition:
    transform 0.3s ease,
    box-shadow 0.3s ease;
}
.kpi-card:hover .kpi-ico {
  transform: scale(1.15);
  box-shadow: 0 0 12px rgba(0, 0, 0, 0.08);
}

.anim-bolt :deep(svg) {
  animation: bolt-flash 2s ease-in-out infinite;
}
@keyframes bolt-flash {
  0%,
  100% {
    opacity: 1;
    filter: drop-shadow(0 0 0px currentColor);
  }
  15% {
    opacity: 0.4;
    filter: drop-shadow(0 0 0px currentColor);
  }
  30% {
    opacity: 1;
    filter: drop-shadow(0 0 6px currentColor);
  }
  45% {
    opacity: 0.6;
  }
  60% {
    opacity: 1;
    filter: drop-shadow(0 0 3px currentColor);
  }
}

.anim-drop :deep(svg) {
  animation: drop-bounce 2.5s ease-in-out infinite;
  transform-origin: center bottom;
}
@keyframes drop-bounce {
  0%,
  100% {
    transform: translateY(0) scaleY(1);
  }
  30% {
    transform: translateY(-3px) scaleY(1.05);
  }
  50% {
    transform: translateY(1px) scaleY(0.95) scaleX(1.05);
  }
  70% {
    transform: translateY(-1px) scaleY(1.02);
  }
}

.anim-spin :deep(svg) {
  animation: snowflake-pulse 3s ease-in-out infinite;
}
@keyframes snowflake-pulse {
  0%,
  100% {
    transform: rotate(0deg) scale(1);
    opacity: 0.85;
  }
  50% {
    transform: rotate(180deg) scale(1.15);
    opacity: 1;
  }
}

.anim-breathe :deep(svg) {
  animation: co2-breathe 3s ease-in-out infinite;
}
@keyframes co2-breathe {
  0%,
  100% {
    transform: translateY(0) scale(1);
    opacity: 0.85;
  }
  50% {
    transform: translateY(-3px) scale(1.1);
    opacity: 1;
  }
}

.kpi-body {
  flex: 1;
  min-width: 0;
}
.kpi-val {
  display: block;
  font-size: 17px;
  font-weight: 700;
  color: var(--text-primary);
  line-height: 1.15;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.kpi-lbl {
  display: block;
  font-size: 10px;
  color: var(--text-muted);
  margin-top: 3px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.kpi-right {
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  gap: 10px;
  flex-shrink: 0;
}
.kpi-tag {
  font-size: 10px;
  font-weight: 600;
  padding: 2px 8px;
  border-radius: 20px;
  white-space: nowrap;
}
.kpi-trend {
  display: inline-flex;
  align-items: center;
  gap: 2px;
  font-size: 11px;
  font-weight: 600;
  padding: 2px 8px;
  border-radius: 20px;
  white-space: nowrap;
  margin-top: 2px;
}
.kpi-trend-label {
  font-weight: 400;
  opacity: 0.7;
  margin-left: 2px;
  font-size: 10px;
}
.kpi-trend.up {
  color: #e65100;
  background: rgba(230, 81, 0, 0.08);
}
.kpi-trend.down {
  color: #16a34a;
  background: rgba(22, 163, 74, 0.08);
}

@container (max-width: 899px) {
  .home-page {
    padding: 20px 18px 28px;
    gap: 14px;
  }
}

@container (max-width: 699px) {
  .pg-header {
    flex-direction: column;
    align-items: flex-start;
  }
  .capsule-switcher {
    align-self: stretch;
    justify-content: center;
  }
  .capsule-btn {
    flex: 1;
    text-align: center;
    padding: 5px 10px;
  }
  .home-page {
    padding: 16px 14px 24px;
    gap: 12px;
  }
  .kpi-strip {
    grid-template-columns: repeat(3, minmax(0, 1fr));
    gap: 8px;
  }
}

@container (max-width: 539px) {
  .capsule-btn {
    font-size: 11px;
    padding: 4px 8px;
  }
  .home-page {
    padding: 12px 10px 20px;
    gap: 10px;
  }
  .kpi-strip {
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 8px;
  }
  .kpi-card {
    padding: 10px 10px;
    gap: 8px;
  }
  .kpi-ico {
    width: 30px;
    height: 30px;
    border-radius: 8px;
  }
  .kpi-val {
    font-size: 15px;
  }
  .kpi-tag {
    display: none;
  }
}

@container (max-width: 399px) {
  .home-page {
    padding: 10px 8px 16px;
    gap: 8px;
  }
  .pg-title {
    font-size: 16px;
  }
  .pg-sub {
    display: none;
  }
  .weather-widget {
    display: none;
  }
}

html[data-theme='light'] .kpi-card {
  background: #ffffff;
  border-color: #e2e8e4;
}
html[data-theme="light"] .header-right-group {
  background: #ffffff;
  border-color: #e2e8e4;
}
html[data-theme="light"] .header-group-divider {
  background: #e2e8e4;
}
html[data-theme="light"] .weather-date {
  color: #666;
}
html[data-theme='light'] .weather-val {
  color: #111;
}
html[data-theme='light'] .weather-divider {
  background: #e2e8e4;
}
html[data-theme='light'] .capsule-switcher {
  background: #f4f7f5;
  border-color: #e2e8e4;
}
html[data-theme='light'] .capsule-slider {
  background: #ffffff;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.1);
}
html[data-theme='light'] .capsule-btn {
  color: #888;
}
html[data-theme='light'] .capsule-btn.active {
  color: #111;
}
html[data-theme='light'] .pg-title {
  color: #111;
}
html[data-theme='light'] .pg-sub {
  color: #666;
}
html[data-theme='light'] .kpi-val {
  color: #111;
}
html[data-theme='light'] .kpi-lbl {
  color: #666;
}
</style>
