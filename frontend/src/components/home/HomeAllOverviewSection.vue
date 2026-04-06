<script setup lang="ts">
import { computed, ref, watch, onMounted, onUnmounted, nextTick } from 'vue'
import * as echarts from 'echarts'
import { apiFetch } from '@/api/http'
import {
  MC,
  gc,
  isoDate,
  STANDARD_COAL_ELECTRICITY_FACTOR,
  STANDARD_COAL_WATER_FACTOR,
  ELECTRICITY_CARBON_FACTOR,
} from '@/utils/homeCharts'
import HomeAiStewardCard from './HomeAiStewardCard.vue'
import HomeBuildingEnergyShareCard from './HomeBuildingEnergyShareCard.vue'
import { useReportExport } from '@/composables/useReportExport'

const props = defineProps<{
  overviewData: any
  anomalyData: any[]
  aiStewardLoading?: boolean
  sankeyData: {
    nodes: { name: string }[]
    links: { source: string | number; target: string | number; value: number }[]
  } | null
}>()

const emit = defineEmits<{
  (e: 'refresh'): void
  (e: 'view-all'): void
  (e: 'view-curve'): void
  (e: 'apply-strategy'): void
}>()

type OverviewMetricTab = 'energy' | 'carbon'

interface DailyEnergyRecord {
  day: string
  actualElectricityKwh: number
  actualWaterM3: number
  expectedElectricityKwh: number | null
  expectedWaterM3: number | null
  actualKgce: number
  expectedKgce: number | null
  actualCarbonKg: number
  expectedCarbonKg: number | null
}

const BUILDING_TYPES = ['Education', 'Office', 'Public services'] as const

const metricTab = ref<OverviewMetricTab>('energy')
const energyEl = ref<HTMLElement | null>(null)
const sankeyEl = ref<HTMLElement | null>(null)
const dailyRecords = ref<DailyEnergyRecord[]>([])
const overviewHint = ref('')

const { captureChart } = useReportExport('home-charts')

let instances: echarts.ECharts[] = []

const tabOptions: Array<{ key: OverviewMetricTab; label: string }> = [
  { key: 'energy', label: '总能耗' },
  { key: 'carbon', label: '碳排放' },
]

const chartMeta = computed(() => {
  if (metricTab.value === 'energy') {
    return {
      title: '总能耗 vs 额定期望',
      subtitle: '近 7 天总电与总水统一折算为标准煤（kgce）',
      unit: 'kgce',
      actualLabel: '真实总能耗',
      expectedLabel: '额定期望',
      actualKey: 'actualKgce' as const,
      expectedKey: 'expectedKgce' as const,
      actualColor: MC.blue,
      expectedColor: '#bfdbfe',
    }
  }

  return {
    title: '碳排放 vs 额定期望',
    subtitle: '近 7 天按总用电折算碳排放（kg）',
    unit: 'kg',
    actualLabel: '真实碳排放',
    expectedLabel: '额定期望',
    actualKey: 'actualCarbonKg' as const,
    expectedKey: 'expectedCarbonKg' as const,
    actualColor: MC.sage,
    expectedColor: '#bbf7d0',
  }
})

const SANKEY_RULE_LABELS: Record<string, string> = {
  water_leak: '水耗异常',
  electricity_overload: '电耗超标',
  hvac_overconsumption: '空调过耗',
  supply_temp_deviation: '供水温度偏离',
  return_temp_deviation: '回水温度偏离',
  db_flagged: '标注异常',
  night_high_power: '夜间高耗',
  flag_water: '水耗偏高',
  flag_electricity: '总电耗偏高',
  flag_hvac_energy: '空调能耗偏高',
  flag_supply_deviation: '供水温度偏离',
  flag_return_deviation: '回水温度偏离',
}

const SANKEY_ROOT_CAUSE_LABELS: Record<string, string> = {
  A_low_efficiency: '主机效率衰退',
  B_small_deltaT: '水力失调',
  C_unexpected_on: '非预期开机',
  other_hvac: '其他空调故障',
}

function translateSankeyBaseLabel(name: string): string {
  return SANKEY_RULE_LABELS[name] ?? SANKEY_ROOT_CAUSE_LABELS[name] ?? name
}

function normalizeSankeyLabel(name: string): string {
  const directMatch = name.match(/^(.*)\((?:直接|direct)\)$/i)
  if (directMatch) return `${translateSankeyBaseLabel(directMatch[1])}(直接)`
  return translateSankeyBaseLabel(name)
}

function normalizeSankeyLinkEnd(
  value: string | number,
  nodes: Array<{ name: string }>,
): string {
  if (typeof value === 'number') return normalizeSankeyLabel(nodes[value]?.name ?? String(value))
  return normalizeSankeyLabel(value)
}

function formatNumber(value: number | null | undefined, digits = 1): string {
  if (value == null || Number.isNaN(value)) return '--'
  return Number(value).toFixed(digits)
}

function formatDeltaText(value: number | null, unit: string): string {
  if (value == null || Number.isNaN(value)) return '--'
  return `${value >= 0 ? '+' : ''}${formatNumber(value)} ${unit}`
}

function getDeltaColor(value: number | null): string {
  if (value == null || Number.isNaN(value)) return '#94a3b8'
  if (value > 0) return '#f97316'
  if (value < 0) return '#10b981'
  return '#94a3b8'
}

function getPercentColor(value: number | null): string {
  if (value == null || Number.isNaN(value)) return '#94a3b8'
  if (value > 0) return '#ef4444'
  if (value < 0) return '#10b981'
  return '#94a3b8'
}

function formatDayLabel(day: string): string {
  return day.slice(5)
}

function getDateRange() {
  const dataDate = props.overviewData?.data_date
  const endD = dataDate ? new Date(`${dataDate}T12:00:00Z`) : new Date()
  const startD = new Date(endD)
  startD.setUTCDate(startD.getUTCDate() - 6)
  return {
    startDate: isoDate(startD),
    endDate: isoDate(endD),
  }
}

function buildEmptyDayMap(startDate: string, endDate: string) {
  const map = new Map<string, DailyEnergyRecord>()
  const cursor = new Date(`${startDate}T12:00:00Z`)
  const end = new Date(`${endDate}T12:00:00Z`)
  while (cursor <= end) {
    const day = isoDate(cursor)
    map.set(day, {
      day,
      actualElectricityKwh: 0,
      actualWaterM3: 0,
      expectedElectricityKwh: null,
      expectedWaterM3: null,
      actualKgce: 0,
      expectedKgce: null,
      actualCarbonKg: 0,
      expectedCarbonKg: null,
    })
    cursor.setUTCDate(cursor.getUTCDate() + 1)
  }
  return map
}

function sumRatedByDay(
  records: Array<{ timestamp?: string; rated?: number | null }>,
  map: Map<string, DailyEnergyRecord>,
  field: 'expectedElectricityKwh' | 'expectedWaterM3',
) {
  records.forEach((record) => {
    if (!record.timestamp || record.rated == null) return
    const day = record.timestamp.slice(0, 10)
    const target = map.get(day)
    if (!target) return
    const current = target[field] ?? 0
    target[field] = current + Number(record.rated)
  })
}

function finalizeDailyRecords(map: Map<string, DailyEnergyRecord>) {
  return [...map.values()].map((record) => {
    const expectedKgce =
      record.expectedElectricityKwh != null || record.expectedWaterM3 != null
        ? Number(record.expectedElectricityKwh ?? 0) * STANDARD_COAL_ELECTRICITY_FACTOR +
          Number(record.expectedWaterM3 ?? 0) * STANDARD_COAL_WATER_FACTOR
        : null

    const expectedCarbonKg =
      record.expectedElectricityKwh != null
        ? Number(record.expectedElectricityKwh) * ELECTRICITY_CARBON_FACTOR
        : null

    return {
      ...record,
      actualKgce:
        record.actualElectricityKwh * STANDARD_COAL_ELECTRICITY_FACTOR +
        record.actualWaterM3 * STANDARD_COAL_WATER_FACTOR,
      expectedKgce,
      actualCarbonKg: record.actualElectricityKwh * ELECTRICITY_CARBON_FACTOR,
      expectedCarbonKg,
    }
  })
}

async function loadOverviewSeries() {
  const { startDate, endDate } = getDateRange()
  const dayMap = buildEmptyDayMap(startDate, endDate)
  let hasExpected = false

  try {
    const responses = await Promise.all(
      BUILDING_TYPES.map(async (buildingType) => {
        const [energy, ratedElectricity, ratedWater] = await Promise.all([
          apiFetch<any>(
            `/api/buildings/${encodeURIComponent(buildingType)}/energy?start_date=${startDate}&end_date=${endDate}&include_water=true`,
          ),
          apiFetch<any>(
            `/api/buildings/${encodeURIComponent(buildingType)}/rated-vs-actual?start_date=${startDate}&end_date=${endDate}&metric=electricity`,
          ).catch(() => ({ records: [], module_status: 'no_expected_data' })),
          apiFetch<any>(
            `/api/buildings/${encodeURIComponent(buildingType)}/rated-vs-actual?start_date=${startDate}&end_date=${endDate}&metric=water`,
          ).catch(() => ({ records: [], module_status: 'no_expected_data' })),
        ])

        return { energy, ratedElectricity, ratedWater }
      }),
    )

    responses.forEach(({ energy, ratedElectricity, ratedWater }) => {
      ;(energy?.records ?? []).forEach((record: any) => {
        if (!record?.day) return
        const target = dayMap.get(record.day)
        if (!target) return
        target.actualElectricityKwh += Number(record.total_electricity_kwh ?? 0)
        target.actualWaterM3 += Number(record.total_water_m3 ?? 0)
      })

      sumRatedByDay(ratedElectricity?.records ?? [], dayMap, 'expectedElectricityKwh')
      sumRatedByDay(ratedWater?.records ?? [], dayMap, 'expectedWaterM3')

      if (ratedElectricity?.module_status === 'ok' || ratedWater?.module_status === 'ok') {
        hasExpected = true
      }
    })

    dailyRecords.value = finalizeDailyRecords(dayMap)
    overviewHint.value = hasExpected ? '' : '额定期望值暂无数据，当前仅展示真实值'
  } catch {
    dailyRecords.value = finalizeDailyRecords(dayMap)
    overviewHint.value = '总览数据加载失败，当前仅展示空状态'
  }
}

function renderOverviewEnergy() {
  if (!energyEl.value) return
  const c = gc()
  const meta = chartMeta.value
  const rows = dailyRecords.value
  const labels = rows.map((row) => formatDayLabel(row.day))
  const actualVals = rows.map((row) => Number(row[meta.actualKey]))
  const expectedVals = rows.map((row) => row[meta.expectedKey] == null ? null : Number(row[meta.expectedKey]))
  const inst = echarts.init(energyEl.value)

  inst.setOption({
    backgroundColor: 'transparent',
    color: [meta.actualColor, meta.expectedColor],
    grid: { top: 76, right: 24, bottom: 36, left: 62 },
    legend: {
      top: 18,
      left: 16,
      itemWidth: 10,
      itemHeight: 10,
      textStyle: { color: c.axis, fontSize: 11 },
      data: [
        { name: meta.actualLabel, icon: 'roundRect' },
        { name: meta.expectedLabel, icon: 'roundRect' },
      ],
    },
    tooltip: {
      trigger: 'axis',
      axisPointer: {
        type: 'shadow',
        shadowStyle: { color: c.dark ? 'rgba(255,255,255,0.03)' : 'rgba(15,40,24,0.04)' },
      },
      backgroundColor: c.ttBg,
      borderColor: c.ttBr,
      textStyle: { color: c.ttText, fontSize: 11 },
      formatter: (params: any[]) => {
        const idx = params[0]?.dataIndex ?? 0
        const row = rows[idx]
        const actual = Number(row[meta.actualKey])
        const expected = row[meta.expectedKey] == null ? null : Number(row[meta.expectedKey])
        const diff = expected == null ? null : actual - expected
        const pct = expected != null && Math.abs(expected) > 1e-9 ? (diff! / expected) * 100 : null
        const diffColor = getDeltaColor(diff)
        const pctColor = getPercentColor(pct)

        return [
          `<b>${row.day}</b>`,
          `${meta.actualLabel}: ${formatNumber(actual)} ${meta.unit}`,
          `${meta.expectedLabel}: ${formatNumber(expected)} ${meta.unit}`,
          `差值: <span style="color:${diffColor}">${formatDeltaText(diff, meta.unit)}</span>`,
          `偏差: <span style="color:${pctColor}">${pct == null ? '--' : `${pct >= 0 ? '+' : ''}${formatNumber(pct)}%`}</span>`,
        ].join('<br/>')
      },
    },
    xAxis: {
      type: 'category',
      data: labels,
      axisLabel: { color: c.axis, fontSize: 10 },
      axisLine: { lineStyle: { color: c.grid } },
      axisTick: { show: false },
    },
    yAxis: {
      type: 'value',
      name: meta.unit,
      nameLocation: 'end',
      nameGap: 18,
      nameTextStyle: { color: c.axis, fontSize: 10, padding: [0, 0, 8, 0] },
      axisLabel: { color: c.axis, fontSize: 10 },
      splitLine: { lineStyle: { color: c.grid, type: 'dashed' } },
      axisLine: { show: false },
    },
    series: [
      {
        name: meta.expectedLabel,
        type: 'bar',
        data: expectedVals,
        barWidth: 34,
        barCategoryGap: '38%',
        itemStyle: {
          borderRadius: [12, 12, 0, 0],
          color: meta.expectedColor,
          opacity: 0.76,
        },
        emphasis: { disabled: true },
        z: 1,
      },
      {
        name: meta.actualLabel,
        type: 'bar',
        data: actualVals,
        barWidth: 22,
        barGap: '-82%',
        itemStyle: {
          borderRadius: [10, 10, 0, 0],
          color: {
            type: 'linear',
            x: 0,
            y: 0,
            x2: 0,
            y2: 1,
            colorStops: [
              { offset: 0, color: meta.actualColor },
              { offset: 1, color: `${meta.actualColor}b8` },
            ],
          },
        },
        emphasis: { focus: 'series' },
        z: 3,
      },
    ],
  })

  instances.push(inst)
}

function renderSankey() {
  if (!sankeyEl.value) return
  const c = gc()
  const sd = props.sankeyData
  const hasData = !!sd && sd.nodes.length > 0 && sd.links.length > 0
  const inst = echarts.init(sankeyEl.value)

  if (!hasData) {
    inst.setOption({
      backgroundColor: 'transparent',
      title: {
        text: '暂无根因数据',
        left: 'center',
        top: 'middle',
        textStyle: { color: c.axis, fontSize: 12 },
      },
    })
    instances.push(inst)
    return
  }

  const normalizedLinks = sd.links.map((link) => ({
    source: normalizeSankeyLinkEnd(link.source, sd.nodes),
    target: normalizeSankeyLinkEnd(link.target, sd.nodes),
    value: link.value,
  }))
  const sourceNames = new Set(normalizedLinks.map((link) => link.source))
  const sourceNameList = Array.from(sourceNames)
  const targetNameList = Array.from(new Set(normalizedLinks.map((link) => link.target)))
  const sourcePalette = [MC.terra, '#14b8a6', MC.blue, '#2563eb', '#d97706', MC.rose, '#8b5cf6', '#ec4899', '#ef4444']
  const targetPalette = [MC.blue, MC.rose, MC.sage, MC.teal, MC.terra, '#8b5cf6', '#6366f1', '#ef4444', '#f97316', '#06b6d4', '#1d4ed8', '#22c55e', '#0ea5e9', '#3b82f6', '#f59e0b']
  const sourceColorMap = Object.fromEntries(
    sourceNameList.map((name, index) => [name, sourcePalette[index % sourcePalette.length]]),
  )
  const targetColorMap = Object.fromEntries(
    targetNameList.map((name, index) => [name, targetPalette[index % targetPalette.length]]),
  )
  const nodeNames = Array.from(
    new Set([
      ...sd.nodes.map((node) => normalizeSankeyLabel(node.name)),
      ...normalizedLinks.flatMap((link) => [link.source, link.target]),
    ]),
  )
  const nodes = nodeNames.map((name) => ({
    name,
    itemStyle: {
      color: sourceNames.has(name)
        ? sourceColorMap[name] ?? MC.blue
        : targetColorMap[name] ?? MC.lav,
    },
  }))

  inst.setOption({
    backgroundColor: 'transparent',
    tooltip: {
      trigger: 'item',
      backgroundColor: c.ttBg,
      borderColor: c.ttBr,
      textStyle: { color: c.ttText, fontSize: 11 },
    },
    series: [
      {
        type: 'sankey',
        left: 16,
        right: 108,
        top: 10,
        bottom: 10,
        emphasis: { focus: 'adjacency' },
        nodeGap: 10,
        nodeWidth: 12,
        data: nodes,
        links: normalizedLinks,
        lineStyle: { color: 'gradient', opacity: 0.42 },
        label: { color: c.axis, fontSize: 11 },
      },
    ],
  })
  instances.push(inst)
}

function disposeAll() {
  instances.forEach((instance) => instance.dispose())
  instances = []
}

function renderAll() {
  disposeAll()
  renderOverviewEnergy()
  renderSankey()
  nextTick(() => {
    instances.forEach((instance) => instance.resize())
    setTimeout(() => captureChartsForReport(), 500)
  })
}

function captureChartsForReport() {
  if (energyEl.value) {
    const inst = echarts.getInstanceByDom(energyEl.value)
    captureChart(inst, 'home-chart-overview-energy', chartMeta.value.title, 20)
  }
  if (sankeyEl.value) {
    const inst = echarts.getInstanceByDom(sankeyEl.value)
    captureChart(inst, 'home-chart-sankey', '异常根因桑基图', 30)
  }
}

function onResize() {
  instances.forEach((instance) => instance.resize())
}

let ro: ResizeObserver | null = null

watch(
  () => [props.overviewData?.data_date, props.sankeyData?.nodes?.length, props.sankeyData?.links?.length],
  async () => {
    await loadOverviewSeries()
    await nextTick()
    renderAll()
  },
)

watch(metricTab, () => nextTick(() => renderAll()))

onMounted(async () => {
  await loadOverviewSeries()
  await nextTick()
  setTimeout(() => {
    renderAll()
    window.addEventListener('resize', onResize)
    const el = document.querySelector('.home-page') as HTMLElement | null
    if (el && typeof ResizeObserver !== 'undefined') {
      ro = new ResizeObserver(() => instances.forEach((instance) => instance.resize()))
      ro.observe(el)
    }
  }, 60)
})

onUnmounted(() => {
  disposeAll()
  window.removeEventListener('resize', onResize)
  ro?.disconnect()
  ro = null
})

function handleStewardRefresh() {
  emit('refresh')
}

function handleStewardViewAll() {
  emit('view-all')
}

function handleStewardViewCurve() {
  energyEl.value?.scrollIntoView({ behavior: 'smooth', block: 'nearest' })
  emit('view-curve')
}

function handleStewardApplyStrategy() {
  emit('apply-strategy')
}
</script>

<template>
  <div class="home-all-section home-all-overview-section">
    <div class="overview-top-row">
      <div
        class="cpanel overview-energy-panel"
        data-pick-id="chart-overview-energy"
        data-pick-type="chart"
        :data-pick-title="chartMeta.title"
        :data-pick-subtitle="chartMeta.subtitle"
      >
        <div class="cpanel-hd">
          <div class="overview-chart-copy">
            <span class="cpanel-title">{{ chartMeta.title }}</span>
            <span class="cpanel-sub">
              {{ chartMeta.subtitle }}
              <span v-if="overviewHint" class="overview-chart-hint">{{ overviewHint }}</span>
            </span>
          </div>
          <div class="overview-tabs">
            <button
              v-for="tab in tabOptions"
              :key="tab.key"
              class="overview-tab"
              :class="{ active: metricTab === tab.key }"
              type="button"
              @click="metricTab = tab.key"
            >
              {{ tab.label }}
            </button>
          </div>
        </div>
        <div ref="energyEl" class="cpanel-body" style="height: 316px" />
      </div>

      <HomeBuildingEnergyShareCard :overview-data="overviewData" />
    </div>

    <div class="overview-bottom-row">
      <div class="cpanel panel-sankey">
        <div class="cpanel-hd">
          <span class="cpanel-title">异常根因桑基图</span>
          <span class="cpanel-sub">规则流向根因类型</span>
        </div>
        <div ref="sankeyEl" class="cpanel-body" style="height: 300px" />
      </div>
      <HomeAiStewardCard
        class="home-actions-panel"
        :loading="aiStewardLoading"
        @refresh="handleStewardRefresh"
        @view-all="handleStewardViewAll"
        @view-curve="handleStewardViewCurve"
        @apply-strategy="handleStewardApplyStrategy"
      />
    </div>
  </div>
</template>

<style>
.home-page .home-all-overview-section > .overview-bottom-row {
  grid-column: 1 / -1;
  display: grid;
  grid-template-columns: minmax(0, 3fr) minmax(0, 7fr);
  gap: 14px;
  align-items: stretch;
}

.home-page .home-all-overview-section > .overview-bottom-row > .panel-sankey,
.home-page .home-all-overview-section > .overview-bottom-row > .home-actions-panel {
  grid-column: auto;
  grid-row: auto;
  min-width: 0;
}

.home-all-overview-section .cpanel-hd:has(.overview-tabs) {
  flex-direction: row;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.overview-chart-copy {
  display: flex;
  flex-direction: column;
  gap: 3px;
  min-width: 0;
}

.overview-chart-hint {
  margin-left: 8px;
  color: var(--text-muted);
}

.overview-tabs {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 5px;
  border: 1px solid rgba(148, 163, 184, 0.16);
  border-radius: 999px;
  background: rgba(148, 163, 184, 0.12);
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.06);
}

.overview-tab {
  min-width: 72px;
  padding: 7px 14px;
  border-radius: 999px;
  border: 0;
  background: transparent;
  color: var(--text-muted, #8a95a8);
  font-size: 11px;
  font-weight: 600;
  cursor: pointer;
  transition: background-color 0.18s ease, color 0.18s ease, box-shadow 0.18s ease;
}

.overview-tab:hover {
  color: var(--text-primary, #dde3f0);
}

.overview-tab.active {
  background: #ffffff;
  color: #1d4ed8;
  box-shadow: 0 6px 14px rgba(15, 23, 42, 0.10), inset 0 0 0 1px rgba(191, 219, 254, 0.9);
}

html[data-theme='light'] .overview-tabs {
  background: #eef2f0;
  border-color: #e2e8e4;
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.9);
}

html[data-theme='light'] .overview-tab {
  color: #64748b;
}

html[data-theme='light'] .overview-tab:hover {
  color: #111827;
}

html[data-theme='light'] .overview-tab.active {
  background: #ffffff;
  color: #1d4ed8;
  box-shadow: 0 8px 16px rgba(148, 163, 184, 0.18), inset 0 0 0 1px rgba(191, 219, 254, 0.9);
}

@container (max-width: 899px) {
  .home-page .home-all-overview-section > .overview-bottom-row {
    grid-template-columns: minmax(0, 3fr) minmax(0, 7fr);
  }
}

@container (max-width: 699px) {
  .home-page .home-all-overview-section > .overview-bottom-row {
    grid-template-columns: 1fr;
    gap: 10px;
  }
}

@container (max-width: 399px) {
  .home-page .home-all-overview-section > .overview-bottom-row {
    gap: 8px;
  }
}
</style>
