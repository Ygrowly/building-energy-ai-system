<script setup lang="ts">
import { ref, computed, watch, onMounted, onUnmounted, nextTick } from 'vue'
import * as echarts from 'echarts'
import { apiFetch } from '@/api/http'
import { MC, gc, isoDate } from '@/utils/homeCharts'
import HomeActionCards from './HomeActionCards.vue'
import HomeMiniMetricCards from './HomeMiniMetricCards.vue'

const props = defineProps<{
  dataDate: string
}>()

const BT = 'Public services'

const dualEl = ref<HTMLElement | null>(null)
const profileEl = ref<HTMLElement | null>(null)
const comfortEl = ref<HTMLElement | null>(null)
let instances: echarts.ECharts[] = []

const statusSnap = ref<any>(null)
const anomalies = ref<any[]>([])
const ratedSummary = ref<any>(null)

const comfortScore = computed(() => {
  const s = statusSnap.value
  if (!s) return { text: '--', sub: '无快照' }
  const t = Number(s.air_temp_c)
  const h = Number(s.humidity_rh_pct)
  let score = 100
  if (t < 18 || t > 28) score -= 25
  else if (t < 20 || t > 26) score -= 10
  if (h < 35 || h > 65) score -= 20
  else if (h < 40 || h > 60) score -= 8
  const text = score >= 80 ? '良好' : score >= 60 ? '一般' : '关注'
  return { text: `${score} · ${text}`, sub: `T ${t.toFixed(1)}°C  RH ${h.toFixed(0)}%` }
})

const miniCards = computed(() => [
  { label: '舒适度', value: comfortScore.value.text },
  { label: '快照', value: comfortScore.value.sub.slice(0, 18) },
])

function disposeAll() {
  instances.forEach((c) => c.dispose())
  instances = []
}

function renderDual(records: any[]) {
  if (!dualEl.value) return
  const c = gc()
  const days = records.map((r: any) => (r.day || '').slice(5))
  const elec = records.map((r: any) => Number(r.total_electricity_kwh ?? 0))
  const water = records.map((r: any) => Number(r.total_water_m3 ?? 0))

  const inst = echarts.init(dualEl.value)
  inst.setOption({
    backgroundColor: 'transparent',
    grid: { top: 36, right: 48, bottom: 28, left: 52 },
    tooltip: { trigger: 'axis', backgroundColor: c.ttBg, borderColor: c.ttBr, textStyle: { color: c.ttText } },
    legend: { top: 4, textStyle: { color: c.axis, fontSize: 10 } },
    xAxis: {
      type: 'category',
      data: days,
      axisLabel: { color: c.axis, fontSize: 9, rotate: 35 },
      axisLine: { lineStyle: { color: c.grid } },
    },
    yAxis: [
      {
        type: 'value',
        name: '电 kWh',
        nameTextStyle: { color: c.axis, fontSize: 10 },
        axisLabel: { color: c.axis, fontSize: 10 },
        splitLine: { lineStyle: { color: c.grid, type: 'dashed' } },
      },
      {
        type: 'value',
        name: '水 m³',
        nameTextStyle: { color: c.axis, fontSize: 10 },
        axisLabel: { color: c.axis, fontSize: 10 },
        splitLine: { show: false },
      },
    ],
    series: [
      { name: '用电', type: 'bar', data: elec, itemStyle: { color: MC.sage } },
      { name: '用水', type: 'line', yAxisIndex: 1, data: water, smooth: true, symbol: 'none', lineStyle: { color: MC.blue, width: 2 } },
    ],
  })
  instances.push(inst)
}

function renderProfile(hourly: { hour: number; avg_value: number }[]) {
  if (!profileEl.value) return
  const c = gc()
  const cats = Array.from({ length: 24 }, (_, i) => `${i}h`)
  const data = cats.map((_, h) => {
    const row = hourly.find((x) => x.hour === h)
    return Number(row?.avg_value ?? 0)
  })

  const inst = echarts.init(profileEl.value)
  inst.setOption({
    backgroundColor: 'transparent',
    grid: { top: 28, right: 16, bottom: 28, left: 48 },
    tooltip: { trigger: 'axis', backgroundColor: c.ttBg, borderColor: c.ttBr, textStyle: { color: c.ttText } },
    xAxis: {
      type: 'category',
      data: cats,
      axisLabel: { color: c.axis, fontSize: 9, interval: 3 },
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
        areaStyle: { color: 'rgba(16,185,129,0.15)' },
        lineStyle: { color: '#10b981', width: 2 },
      },
    ],
  })
  instances.push(inst)
}

function renderComfort(hourlyT: number[], hourlyH: number[]) {
  if (!comfortEl.value) return
  const c = gc()
  const cats = Array.from({ length: 24 }, (_, i) => `${i}h`)

  const inst = echarts.init(comfortEl.value)
  inst.setOption({
    backgroundColor: 'transparent',
    grid: { top: 32, right: 44, bottom: 28, left: 48 },
    tooltip: { trigger: 'axis', backgroundColor: c.ttBg, borderColor: c.ttBr, textStyle: { color: c.ttText } },
    legend: { top: 4, textStyle: { color: c.axis, fontSize: 10 } },
    xAxis: {
      type: 'category',
      data: cats,
      axisLabel: { color: c.axis, fontSize: 9, interval: 3 },
      axisLine: { lineStyle: { color: c.grid } },
    },
    yAxis: [
      {
        type: 'value',
        name: '°C',
        nameTextStyle: { color: c.axis, fontSize: 10 },
        axisLabel: { color: c.axis, fontSize: 10 },
        splitLine: { lineStyle: { color: c.grid, type: 'dashed' } },
      },
      {
        type: 'value',
        name: '%',
        nameTextStyle: { color: c.axis, fontSize: 10 },
        axisLabel: { color: c.axis, fontSize: 10 },
        splitLine: { show: false },
      },
    ],
    series: [
      { name: '温度', type: 'line', data: hourlyT, smooth: true, symbol: 'none', lineStyle: { color: MC.terra, width: 2 } },
      { name: '湿度', type: 'line', yAxisIndex: 1, data: hourlyH, smooth: true, symbol: 'none', lineStyle: { color: MC.blue, width: 2 } },
    ],
  })
  instances.push(inst)
}

async function loadAll() {
  const endD = props.dataDate ? new Date(props.dataDate + 'T12:00:00Z') : new Date()
  const startD = new Date(endD)
  startD.setUTCDate(startD.getUTCDate() - 29)
  const sd = isoDate(startD)
  const ed = isoDate(endD)
  const shortStart = new Date(endD)
  shortStart.setUTCDate(shortStart.getUTCDate() - 6)
  const sds = isoDate(shortStart)

  try {
    const [en, lpE, lpT, lpH, ax, rv] = await Promise.all([
      apiFetch<any>(
        `/api/buildings/${encodeURIComponent(BT)}/energy?start_date=${sd}&end_date=${ed}&include_water=true`,
      ),
      apiFetch<any>(`/api/buildings/${encodeURIComponent(BT)}/load-profile?metric=electricity&days=14`),
      apiFetch<any>(`/api/buildings/${encodeURIComponent(BT)}/load-profile?metric=air_temp&days=14`),
      apiFetch<any>(`/api/buildings/${encodeURIComponent(BT)}/load-profile?metric=humidity&days=14`),
      apiFetch<any>(`/api/anomalies/recent?hours=168&building_type=${encodeURIComponent(BT)}`),
      apiFetch<any>(
        `/api/buildings/${encodeURIComponent(BT)}/rated-vs-actual?start_date=${sds}&end_date=${ed}&metric=electricity`,
      ).catch(() => null),
    ])

    const st = await apiFetch<any>(`/api/buildings/${encodeURIComponent(BT)}/status`).catch(() => null)
    statusSnap.value = st
    anomalies.value = ax?.anomalies ?? []
    ratedSummary.value = rv?.summary ?? null

    const hourlyT = Array.from({ length: 24 }, (_, h) => {
      const row = lpT.hourly_profile?.find((x: any) => x.hour === h)
      return Number(row?.avg_value ?? 22)
    })
    const hourlyH = Array.from({ length: 24 }, (_, h) => {
      const row = lpH.hourly_profile?.find((x: any) => x.hour === h)
      return Number(row?.avg_value ?? 50)
    })

    disposeAll()
    renderDual(en.records || [])
    renderProfile(lpE.hourly_profile || [])
    renderComfort(hourlyT, hourlyH)
    nextTick(() => instances.forEach((i) => i.resize()))
  } catch {
    disposeAll()
  }
}

watch(
  () => props.dataDate,
  () => loadAll(),
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

function fmtTime(iso: string) {
  return (iso || '').replace('T', ' ').slice(0, 16)
}
</script>

<template>
  <div class="home-public-section">
    <div class="bento-row bento-r1">
      <div class="cpanel">
        <div class="cpanel-hd">
          <span class="cpanel-title">水电综合双轴趋势</span>
          <span class="cpanel-sub">近 30 日日用电与日用水</span>
        </div>
        <div ref="dualEl" class="cpanel-body" style="height: 300px" />
      </div>
      <div class="cpanel">
        <div class="cpanel-hd">
          <span class="cpanel-title">全天候用电剖面</span>
          <span class="cpanel-sub">逐时平均（近两周）</span>
        </div>
        <div ref="profileEl" class="cpanel-body" style="height: 300px" />
      </div>
    </div>

    <div class="bento-row bento-r1">
      <div class="cpanel">
        <div class="cpanel-hd">
          <span class="cpanel-title">舒适度趋势（典型日）</span>
          <span class="cpanel-sub">逐时均温与均湿度</span>
        </div>
        <div ref="comfortEl" class="cpanel-body" style="height: 260px" />
      </div>
      <div class="cpanel">
        <div class="cpanel-hd">
          <span class="cpanel-title">舒适区评分</span>
          <span class="cpanel-sub">基于最新快照与阈值规则</span>
        </div>
        <div style="padding: 12px 14px 16px">
          <HomeMiniMetricCards :cards="miniCards" />
        </div>
      </div>
    </div>

    <div class="bento-row bento-r2">
      <div class="cpanel">
        <div class="cpanel-hd">
          <span class="cpanel-title">异常事件时间轴</span>
          <span class="cpanel-sub">近期未解决告警</span>
        </div>
        <div class="home-timeline">
          <div v-for="(a, i) in anomalies.slice(0, 14)" :key="i" class="home-timeline-item">
            <strong>{{ fmtTime(a.timestamp) }}</strong>
            {{ (a.message || a.rule || '异常').toString().slice(0, 100) }}
          </div>
          <div v-if="!anomalies.length" class="home-timeline-item">近期无未解决告警</div>
        </div>
      </div>
      <HomeActionCards
        tab="Public services"
        :anomalies="anomalies"
        :rated-anomaly-hours="ratedSummary?.anomaly_hours ?? null"
      />
    </div>
  </div>
</template>
