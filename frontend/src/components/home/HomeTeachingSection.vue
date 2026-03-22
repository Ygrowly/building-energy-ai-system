<script setup lang="ts">
import { ref, computed, watch, onMounted, onUnmounted, nextTick } from 'vue'
import * as echarts from 'echarts'
import { apiFetch } from '@/api/http'
import { MC, gc, buildHeatmapCells, isoDate } from '@/utils/homeCharts'
import HomeActionCards from './HomeActionCards.vue'
import HomeMiniMetricCards from './HomeMiniMetricCards.vue'

const props = defineProps<{
  dataDate: string
}>()

const BT = 'Education'

const ghDays = ['周一', '周二', '周三', '周四', '周五', '周六', '周日']
const ghData = ref<Array<{ d: number; h: number; v: number }>>([])
const ghMaxVal = ref(1)
const ghTip = ref({ show: false, x: 0, y: 0, text: '' })

const ghLegendColors = computed(() => {
  const dark = document.documentElement.dataset.theme !== 'light'
  return dark
    ? ['#161b22', '#0e4429', '#006d32', '#26a641', '#39d353']
    : ['#ebedf0', '#9be9a8', '#40c463', '#30a14e', '#216e39']
})

function getGhColor(v: number): string {
  const ratio = Math.min(v / ghMaxVal.value, 1)
  const dark = document.documentElement.dataset.theme !== 'light'
  const palette = dark
    ? ['#161b22', '#0e4429', '#006d32', '#26a641', '#39d353']
    : ['#ebedf0', '#9be9a8', '#40c463', '#30a14e', '#216e39']
  const breaks = [0.1, 0.3, 0.55, 0.75]
  let idx = 0
  for (const br of breaks) if (ratio > br) idx++
  return palette[idx]
}

function showGhTip(e: MouseEvent, cell: { d: number; h: number; v: number }) {
  const isTeach = (h: number) =>
    (h >= 8 && h < 12) || (h >= 14 && h < 18) || (h >= 19 && h < 22)
  const off = cell.d >= 5 || !isTeach(cell.h)
  const flag = cell.v > ghMaxVal.value * 0.6 && off ? ' 授课外偏高' : ''
  ghTip.value = {
    show: true,
    text: `${ghDays[cell.d]} ${cell.h}:00 · ${cell.v}${flag}`,
    x: e.clientX + 14,
    y: e.clientY - 42,
  }
}
function hideGhTip() {
  ghTip.value.show = false
}

const ratedEl = ref<HTMLElement | null>(null)
const weekdayEl = ref<HTMLElement | null>(null)
const hvacEl = ref<HTMLElement | null>(null)
let instances: echarts.ECharts[] = []

const ratedSummary = ref<{ anomaly_hours?: number } | null>(null)
const statusSnap = ref<any>(null)
const anomalies = ref<any[]>([])

const deltaTSupplyReturn = computed(() => {
  const s = statusSnap.value
  if (s?.sim_supply_temp_c == null || s?.sim_return_temp_c == null) return null
  return Math.abs(Number(s.sim_supply_temp_c) - Number(s.sim_return_temp_c))
})

const miniCards = computed(() => {
  const ah = ratedSummary.value?.anomaly_hours ?? 0
  return [
    { label: '偏差异常小时', value: String(ah) },
    { label: '供回水温差 °C', value: deltaTSupplyReturn.value != null ? deltaTSupplyReturn.value.toFixed(1) : '--' },
  ]
})

function disposeAll() {
  instances.forEach((c) => c.dispose())
  instances = []
}

function renderRated(records: any[]) {
  if (!ratedEl.value) return
  const c = gc()
  const actual = records.map((r: any) => r.actual ?? 0)
  const rated = records.map((r: any) => r.rated ?? 0)
  const labels = records.map((r: any) => {
    const t = r.timestamp?.slice(11, 16) ?? ''
    return t
  })

  const inst = echarts.init(ratedEl.value)
  inst.setOption({
    backgroundColor: 'transparent',
    grid: { top: 32, right: 16, bottom: 40, left: 52 },
    tooltip: { trigger: 'axis', backgroundColor: c.ttBg, borderColor: c.ttBr, textStyle: { color: c.ttText } },
    legend: { top: 4, textStyle: { color: c.axis, fontSize: 10 } },
    xAxis: {
      type: 'category',
      data: labels,
      axisLabel: { color: c.axis, fontSize: 9, interval: Math.floor(labels.length / 8) },
      axisLine: { lineStyle: { color: c.grid } },
    },
    yAxis: {
      type: 'value',
      name: 'kWh',
      nameTextStyle: { color: c.axis, fontSize: 10 },
      axisLabel: { color: c.axis, fontSize: 10 },
      splitLine: { lineStyle: { color: c.grid, type: 'dashed' } },
    },
    series: [
      { name: '实际', type: 'line', data: actual, smooth: true, symbol: 'none', lineStyle: { color: MC.blue, width: 2 } },
      { name: '国标期望', type: 'line', data: rated, smooth: true, symbol: 'none', lineStyle: { color: MC.sage, width: 1.5, type: 'dashed' } },
    ],
  })
  instances.push(inst)
}

function renderWeekday(weekly: { weekday: number; label?: string; avg_value: number }[]) {
  if (!weekdayEl.value) return
  const c = gc()
  const labels = weekly.map((w) => w.label || `周${w.weekday}`)
  const vals = weekly.map((w) => w.avg_value)

  const inst = echarts.init(weekdayEl.value)
  inst.setOption({
    backgroundColor: 'transparent',
    grid: { top: 28, right: 12, bottom: 28, left: 40 },
    tooltip: { trigger: 'axis', backgroundColor: c.ttBg, borderColor: c.ttBr, textStyle: { color: c.ttText } },
    xAxis: {
      type: 'category',
      data: labels,
      axisLabel: { color: c.axis, fontSize: 10, rotate: 30 },
      axisLine: { lineStyle: { color: c.grid } },
    },
    yAxis: {
      type: 'value',
      name: '均负荷',
      nameTextStyle: { color: c.axis, fontSize: 10 },
      axisLabel: { color: c.axis, fontSize: 10 },
      splitLine: { lineStyle: { color: c.grid, type: 'dashed' } },
    },
    series: [
      {
        name: '用电',
        type: 'bar',
        data: vals,
        itemStyle: {
          color: (p: any) => (p.dataIndex < 5 ? MC.blue : MC.teal),
        },
      },
    ],
  })
  instances.push(inst)
}

function renderHvacTriplet(hourlyAir: number[], supply: number, ret: number) {
  if (!hvacEl.value) return
  const c = gc()
  const hours = Array.from({ length: 24 }, (_, i) => `${i}h`)
  const supplyArr = new Array(24).fill(supply)
  const retArr = new Array(24).fill(ret)

  const inst = echarts.init(hvacEl.value)
  inst.setOption({
    backgroundColor: 'transparent',
    grid: { top: 28, right: 16, bottom: 32, left: 48 },
    tooltip: { trigger: 'axis', backgroundColor: c.ttBg, borderColor: c.ttBr, textStyle: { color: c.ttText } },
    legend: { top: 2, textStyle: { color: c.axis, fontSize: 9 } },
    xAxis: {
      type: 'category',
      data: hours,
      axisLabel: { color: c.axis, fontSize: 9, interval: 3 },
      axisLine: { lineStyle: { color: c.grid } },
    },
    yAxis: {
      type: 'value',
      name: '°C',
      nameTextStyle: { color: c.axis, fontSize: 10 },
      axisLabel: { color: c.axis, fontSize: 10 },
      splitLine: { lineStyle: { color: c.grid, type: 'dashed' } },
    },
    series: [
      { name: '室外(逐时均)', type: 'line', data: hourlyAir, smooth: true, symbol: 'none', lineStyle: { color: MC.terra, width: 2 } },
      { name: '供水(快照)', type: 'line', data: supplyArr, symbol: 'none', lineStyle: { color: MC.blue, type: 'dashed' } },
      { name: '回水(快照)', type: 'line', data: retArr, symbol: 'none', lineStyle: { color: MC.lav, type: 'dashed' } },
    ],
  })
  instances.push(inst)
}

async function loadAll() {
  const endD = props.dataDate ? new Date(props.dataDate + 'T12:00:00Z') : new Date()
  const startD = new Date(endD)
  startD.setUTCDate(startD.getUTCDate() - 6)

  try {
    const [lp, rv, ax, lpAir] = await Promise.all([
      apiFetch<any>(`/api/buildings/${encodeURIComponent(BT)}/load-profile?metric=electricity&days=14`),
      apiFetch<any>(
        `/api/buildings/${encodeURIComponent(BT)}/rated-vs-actual?start_date=${isoDate(startD)}&end_date=${isoDate(endD)}&metric=electricity`,
      ),
      apiFetch<any>(`/api/anomalies/recent?hours=168&building_type=${encodeURIComponent(BT)}`),
      apiFetch<any>(`/api/buildings/${encodeURIComponent(BT)}/load-profile?metric=air_temp&days=14`).catch(() => ({
        hourly_profile: [],
      })),
    ])

    const st = await apiFetch<any>(`/api/buildings/${encodeURIComponent(BT)}/status`).catch(() => null)

    statusSnap.value = st
    anomalies.value = ax?.anomalies ?? []
    ratedSummary.value = rv?.summary ?? null

    const cells = buildHeatmapCells(lp.hourly_profile || [], lp.weekday_profile || [])
    ghData.value = cells
    ghMaxVal.value = Math.max(...cells.map((x) => x.v), 1)

    disposeAll()
    renderRated(rv?.records || [])
    renderWeekday(lp.weekday_profile || [])
    const airH = Array.from({ length: 24 }, (_, h) => {
      const row = lpAir.hourly_profile?.find((x: any) => x.hour === h)
      return Number(row?.avg_value ?? 20)
    })
    const supply = Number(st?.sim_supply_temp_c ?? 7)
    const ret = Number(st?.sim_return_temp_c ?? 12)
    renderHvacTriplet(airH, supply, ret)
    nextTick(() => instances.forEach((i) => i.resize()))
  } catch {
    ghData.value = buildHeatmapCells(
      Array.from({ length: 24 }, (_, hour) => ({ hour, avg_value: 30 })),
      Array.from({ length: 7 }, (_, i) => ({ weekday: i + 1, avg_value: i < 5 ? 70 : 30 })),
    )
    ghMaxVal.value = 100
  }
}

function onResize() {
  instances.forEach((c) => c.resize())
}

let ro: ResizeObserver | null = null

watch(
  () => props.dataDate,
  () => {
    loadAll()
  },
)

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
  <div class="home-teach-section">
    <div class="bento-row bento-r1">
      <div class="cpanel">
        <div class="cpanel-hd">
          <span class="cpanel-title">7×24 教学节律热力图</span>
          <span class="cpanel-sub">参考作息 8-12 / 14-18 / 19-21 时授课带，授课外偏高需关注</span>
        </div>
        <div class="gh-wrap">
          <div class="gh-main">
            <div class="gh-y-col">
              <span v-for="d in ghDays" :key="d" class="gh-y-label">{{ d }}</span>
            </div>
            <div class="gh-cells">
              <div
                v-for="cell in ghData"
                :key="`${cell.d}-${cell.h}`"
                class="gh-cell"
                :style="{ background: getGhColor(cell.v) }"
                @mouseenter="(e) => showGhTip(e, cell)"
                @mouseleave="hideGhTip"
              />
            </div>
          </div>
          <div class="gh-x-row">
            <div class="gh-y-spacer" />
            <div class="gh-x-labels">
              <span v-for="h in 24" :key="h" class="gh-x-label">
                {{ [0, 4, 8, 12, 16, 20].includes(h - 1) ? `${h - 1}h` : '' }}
              </span>
            </div>
          </div>
          <div class="gh-legend">
            <span class="gh-legend-text">低</span>
            <div v-for="c in ghLegendColors" :key="c" class="gh-legend-cell" :style="{ background: c }" />
            <span class="gh-legend-text">高</span>
          </div>
        </div>
      </div>
      <div class="cpanel">
        <div class="cpanel-hd">
          <span class="cpanel-title">额定 vs 实际（电）</span>
          <span class="cpanel-sub">近 7 天逐小时对比国标期望</span>
        </div>
        <div ref="ratedEl" class="cpanel-body" style="height: 300px" />
      </div>
    </div>

    <div class="bento-row bento-r1">
      <div class="cpanel">
        <div class="cpanel-hd">
          <span class="cpanel-title">周节律对比</span>
          <span class="cpanel-sub">星期维度平均用电强度</span>
        </div>
        <div ref="weekdayEl" class="cpanel-body" style="height: 260px" />
      </div>
      <div class="cpanel">
        <div class="cpanel-hd">
          <span class="cpanel-title">供回水与室外温度</span>
          <span class="cpanel-sub">室外为逐时均值，供回水为最新快照</span>
        </div>
        <div ref="hvacEl" class="cpanel-body" style="height: 260px" />
      </div>
    </div>

    <div class="bento-row bento-r1">
      <div class="cpanel">
        <div class="cpanel-hd">
          <span class="cpanel-title">关键指标</span>
          <span class="cpanel-sub">偏差小时与供回水温差</span>
        </div>
        <div style="padding: 12px 14px 16px">
          <HomeMiniMetricCards :cards="miniCards" />
        </div>
      </div>
      <HomeActionCards
        tab="Education"
        :anomalies="anomalies"
        :rated-anomaly-hours="ratedSummary?.anomaly_hours ?? null"
        :delta-t-supply-return="deltaTSupplyReturn"
      />
    </div>

    <Teleport to="body">
      <div v-if="ghTip.show" class="gh-tooltip" :style="{ left: ghTip.x + 'px', top: ghTip.y + 'px' }">
        {{ ghTip.text }}
      </div>
    </Teleport>
  </div>
</template>

<style>
.gh-tooltip {
  position: fixed;
  background: #1a1d28;
  color: #dde3f0;
  border: 1px solid #2a2d3a;
  border-radius: 6px;
  padding: 5px 10px;
  font-size: 11px;
  pointer-events: none;
  z-index: 9999;
  white-space: nowrap;
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.4);
}
</style>
