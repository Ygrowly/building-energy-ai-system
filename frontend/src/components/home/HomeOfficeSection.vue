<script setup lang="ts">
import { ref, computed, watch, onMounted, onUnmounted, nextTick } from 'vue'
import * as echarts from 'echarts'
import { apiFetch } from '@/api/http'
import { MC, gc, EUI_BASELINE, isoDate } from '@/utils/homeCharts'
import HomeActionCards from './HomeActionCards.vue'
import HomeMiniMetricCards from './HomeMiniMetricCards.vue'

const props = defineProps<{
  dataDate: string
  overviewData: any
}>()

const BT = 'Office'

const workEl = ref<HTMLElement | null>(null)
const euiEl = ref<HTMLElement | null>(null)
const trendEl = ref<HTMLElement | null>(null)
const sparkEl = ref<HTMLElement | null>(null)
const nightEl = ref<HTMLElement | null>(null)
let instances: echarts.ECharts[] = []

const peakValley = ref<any>(null)
const ratedSummary = ref<any>(null)
const anomalies = ref<any[]>([])

const euiRatio = computed(() => {
  const b = props.overviewData?.buildings?.find((x: any) => x.building_type === BT)
  const inten = Number(b?.energy_intensity_kwh_per_sqm ?? 0)
  const base = EUI_BASELINE[BT] ?? 75
  if (!inten || !base) return null
  return (inten * 365) / base
})

const miniCards = computed(() => {
  const pv = peakValley.value
  return [
    { label: '峰值 (kWh·日)', value: pv?.peak_value != null ? String(pv.peak_value) : '--' },
    { label: '谷值 (kWh·日)', value: pv?.valley_value != null ? String(pv.valley_value) : '--' },
    {
      label: '峰谷比',
      value: pv?.peak_valley_ratio != null ? String(pv.peak_valley_ratio) : '--',
    },
    { label: '夜间异常采样', value: String(pv?.night_abnormal_hours ?? 0) },
  ]
})

function disposeAll() {
  instances.forEach((c) => c.dispose())
  instances = []
}

function renderWorkBand(hourly: { hour: number; avg_value: number }[]) {
  if (!workEl.value) return
  const c = gc()
  const cats = Array.from({ length: 24 }, (_, i) => String(i))
  const data = cats.map((_, h) => {
    const row = hourly.find((x) => x.hour === h)
    return Number(row?.avg_value ?? 0)
  })

  const inst = echarts.init(workEl.value)
  inst.setOption({
    backgroundColor: 'transparent',
    grid: { top: 32, right: 16, bottom: 32, left: 48 },
    tooltip: { trigger: 'axis', backgroundColor: c.ttBg, borderColor: c.ttBr, textStyle: { color: c.ttText } },
    xAxis: {
      type: 'category',
      data: cats,
      axisLabel: { color: c.axis, fontSize: 10 },
      axisLine: { lineStyle: { color: c.grid } },
    },
    yAxis: {
      type: 'value',
      name: 'kWh/h',
      nameTextStyle: { color: c.axis, fontSize: 10 },
      axisLabel: { color: c.axis, fontSize: 10 },
      splitLine: { lineStyle: { color: c.grid, type: 'dashed' } },
    },
    series: [
      {
        name: '用电',
        type: 'line',
        data,
        smooth: true,
        symbol: 'none',
        areaStyle: { color: 'rgba(123,159,199,0.18)' },
        lineStyle: { color: MC.blue, width: 2 },
        markArea: {
          silent: true,
          itemStyle: { color: 'rgba(122,170,142,0.15)' },
          data: [[{ xAxis: '8' }, { xAxis: '18' }]],
        },
      },
    ],
  })
  instances.push(inst)
}

function renderEuiGauge(ratio: number | null) {
  if (!euiEl.value) return
  const c = gc()
  const r = ratio == null ? 1 : Math.min(Math.max(ratio, 0), 2.2)

  const inst = echarts.init(euiEl.value)
  inst.setOption({
    backgroundColor: 'transparent',
    series: [
      {
        type: 'gauge',
        center: ['50%', '58%'],
        radius: '88%',
        min: 0,
        max: 2,
        splitNumber: 4,
        axisLine: {
          lineStyle: {
            width: 14,
            color: [
              [0.5, '#5daa87'],
              [0.75, '#e8a64c'],
              [1, '#e05c5c'],
            ],
          },
        },
        pointer: { width: 4, length: '70%' },
        axisTick: { show: false },
        splitLine: { show: false },
        axisLabel: { color: c.axis, fontSize: 9, distance: 12, formatter: (v: number) => `${v.toFixed(1)}×` },
        title: { show: true, offsetCenter: [0, '78%'], color: c.axis, fontSize: 11 },
        detail: {
          valueAnimation: true,
          formatter: (v: number) => (ratio == null ? '--' : `${v.toFixed(2)}×`),
          color: c.ttText,
          fontSize: 18,
          offsetCenter: [0, '28%'],
        },
        data: [{ value: r, name: 'EUI 相对国标' }],
      },
    ],
  })
  instances.push(inst)
}

function renderTrend(records: any[]) {
  if (!trendEl.value) return
  const c = gc()
  const days = records.map((r: any) => (r.day || '').slice(5))
  const elec = records.map((r: any) => Number(r.total_electricity_kwh ?? 0))
  const temp = records.map((r: any) => Number(r.avg_ambient_temp ?? 0))

  const inst = echarts.init(trendEl.value)
  inst.setOption({
    backgroundColor: 'transparent',
    grid: { top: 36, right: 44, bottom: 28, left: 48 },
    tooltip: { trigger: 'axis', backgroundColor: c.ttBg, borderColor: c.ttBr, textStyle: { color: c.ttText } },
    legend: { top: 4, textStyle: { color: c.axis, fontSize: 10 } },
    xAxis: {
      type: 'category',
      data: days,
      axisLabel: { color: c.axis, fontSize: 10 },
      axisLine: { lineStyle: { color: c.grid } },
    },
    yAxis: [
      {
        type: 'value',
        name: 'kWh',
        nameTextStyle: { color: c.axis, fontSize: 10 },
        axisLabel: { color: c.axis, fontSize: 10 },
        splitLine: { lineStyle: { color: c.grid, type: 'dashed' } },
      },
      {
        type: 'value',
        name: '°C',
        nameTextStyle: { color: c.axis, fontSize: 10 },
        axisLabel: { color: c.axis, fontSize: 10 },
        splitLine: { show: false },
      },
    ],
    series: [
      { name: '用电', type: 'bar', data: elec, itemStyle: { color: MC.sage } },
      { name: '均温', type: 'line', yAxisIndex: 1, data: temp, smooth: true, symbol: 'none', lineStyle: { color: MC.terra, width: 2 } },
    ],
  })
  instances.push(inst)
}

function renderSparkline(daily: { day: string; total: number }[]) {
  if (!sparkEl.value) return
  const c = gc()
  const vals = daily.map((d) => d.total)
  const labels = daily.map((d) => d.day.slice(5))

  const inst = echarts.init(sparkEl.value)
  inst.setOption({
    backgroundColor: 'transparent',
    grid: { top: 8, right: 8, bottom: 22, left: 8 },
    xAxis: { type: 'category', data: labels, show: false },
    yAxis: { type: 'value', show: false },
    series: [
      {
        type: 'line',
        data: vals,
        smooth: true,
        symbol: 'none',
        areaStyle: { color: 'rgba(196,149,106,0.2)' },
        lineStyle: { color: MC.terra, width: 1.5 },
      },
    ],
  })
  instances.push(inst)
}

function renderNightRank(daily: { day: string; total: number }[]) {
  if (!nightEl.value) return
  const c = gc()
  const sorted = [...daily].sort((a, b) => b.total - a.total).slice(0, 7)
  const labels = sorted.map((d) => d.day.slice(5))
  const vals = sorted.map((d) => d.total)

  const inst = echarts.init(nightEl.value)
  inst.setOption({
    backgroundColor: 'transparent',
    grid: { top: 24, right: 28, bottom: 24, left: 52 },
    tooltip: { trigger: 'axis', backgroundColor: c.ttBg, borderColor: c.ttBr, textStyle: { color: c.ttText } },
    xAxis: {
      type: 'value',
      axisLabel: { color: c.axis, fontSize: 10 },
      splitLine: { lineStyle: { color: c.grid, type: 'dashed' } },
    },
    yAxis: {
      type: 'category',
      data: labels,
      axisLabel: { color: c.axis, fontSize: 10 },
      axisLine: { lineStyle: { color: c.grid } },
    },
    series: [
      {
        type: 'bar',
        data: vals,
        itemStyle: { color: MC.blue },
        label: { show: true, position: 'right', color: c.axis, fontSize: 9 },
      },
    ],
  })
  instances.push(inst)
}

async function loadAll() {
  const endD = props.dataDate ? new Date(props.dataDate + 'T12:00:00Z') : new Date()
  const startD = new Date(endD)
  startD.setUTCDate(startD.getUTCDate() - 6)
  const sd = isoDate(startD)
  const ed = isoDate(endD)

  try {
    const [lp, pv, en, rv, ax] = await Promise.all([
      apiFetch<any>(`/api/buildings/${encodeURIComponent(BT)}/load-profile?metric=electricity&days=14`),
      apiFetch<any>(`/api/buildings/${encodeURIComponent(BT)}/peak-valley-stats?metric=electricity&days=7`),
      apiFetch<any>(
        `/api/buildings/${encodeURIComponent(BT)}/energy?start_date=${sd}&end_date=${ed}&include_water=false`,
      ),
      apiFetch<any>(
        `/api/buildings/${encodeURIComponent(BT)}/rated-vs-actual?start_date=${sd}&end_date=${ed}&metric=electricity`,
      ),
      apiFetch<any>(`/api/anomalies/recent?hours=168&building_type=${encodeURIComponent(BT)}`),
    ])

    peakValley.value = pv
    ratedSummary.value = rv?.summary
    anomalies.value = ax?.anomalies ?? []

    disposeAll()
    renderWorkBand(lp.hourly_profile || [])
    renderEuiGauge(euiRatio.value)
    renderTrend(en.records || [])
    renderSparkline(pv.daily_totals || [])
    renderNightRank(pv.daily_totals || [])
    nextTick(() => instances.forEach((i) => i.resize()))
  } catch {
    disposeAll()
  }
}

watch(
  () => [props.dataDate, props.overviewData],
  () => loadAll(),
  { deep: true },
)

function onResize() {
  instances.forEach((c) => c.resize())
}

let ro: ResizeObserver | null = null

onMounted(async () => {
  await loadAll()
  window.addEventListener('resize', onResize)
  const el = document.querySelector('.home-page') as HTMLElement | null
  if (el && typeof ResizeObserver !== 'undefined') {
    ro = new ResizeObserver(() => instances.forEach((c) => c.resize()))
    ro.observe(el)
  }
})

onUnmounted(() => {
  disposeAll()
  window.removeEventListener('resize', onResize)
  ro?.disconnect()
  ro = null
})
</script>

<template>
  <div class="home-office-section">
    <div class="bento-row bento-r1">
      <div class="cpanel">
        <div class="cpanel-hd">
          <span class="cpanel-title">工作时段能耗带状图</span>
          <span class="cpanel-sub">阴影为 8–18 时参考带（工作日常识区）</span>
        </div>
        <div ref="workEl" class="cpanel-body" style="height: 300px" />
      </div>
      <div class="cpanel">
        <div class="cpanel-hd">
          <span class="cpanel-title">EUI 合规偏离</span>
          <span class="cpanel-sub">相对国标 75 kWh/㎡·年 的百分比仪表</span>
        </div>
        <div ref="euiEl" class="cpanel-body" style="height: 300px" />
      </div>
    </div>

    <div class="bento-row bento-r1">
      <div class="cpanel">
        <div class="cpanel-hd">
          <span class="cpanel-title">近 7 天趋势与气温</span>
          <span class="cpanel-sub">日总用电与日均室外温度</span>
        </div>
        <div ref="trendEl" class="cpanel-body" style="height: 280px" />
      </div>
      <div class="cpanel-col">
        <div class="cpanel">
          <div class="cpanel-hd">
            <span class="cpanel-title">峰谷效率</span>
            <span class="cpanel-sub">日总量走势（spark）</span>
          </div>
          <div ref="sparkEl" class="cpanel-body" style="height: 120px" />
        </div>
        <div class="cpanel">
          <div class="cpanel-hd">
            <span class="cpanel-title">日能耗排行</span>
            <span class="cpanel-sub">近 7 日由高到低</span>
          </div>
          <div ref="nightEl" class="cpanel-body" style="height: 140px" />
        </div>
      </div>
    </div>

    <div class="bento-row bento-r1">
      <div class="cpanel">
        <div class="cpanel-hd">
          <span class="cpanel-title">峰谷与夜间指标</span>
          <span class="cpanel-sub">来自 peak-valley-stats</span>
        </div>
        <div style="padding: 12px 14px 16px">
          <HomeMiniMetricCards :cards="miniCards" />
        </div>
      </div>
      <HomeActionCards
        tab="Office"
        :anomalies="anomalies"
        :night-abnormal-hours="peakValley?.night_abnormal_hours ?? null"
        :eui-ratio="euiRatio"
      />
    </div>
  </div>
</template>
