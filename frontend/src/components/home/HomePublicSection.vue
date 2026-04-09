<script setup lang="ts">
import { ref, computed, watch, onMounted, onUnmounted, nextTick } from 'vue'
import * as echarts from '@/utils/echarts'
import { Icon } from '@iconify/vue'
import { cachedApiFetch } from '@/api/cached'
import { MC, gc, isoDate } from '@/utils/homeCharts'
import { createDeferredTaskRunner } from '@/utils/deferredTasks'
import { isAbortError, startPerfSpan } from '@/utils/perf'
import HomeActionCards from './HomeActionCards.vue'
import HomeEnergyHeatmap from './HomeEnergyHeatmap.vue'
import HomeMiniMetricCards from './HomeMiniMetricCards.vue'

const props = defineProps<{
  dataDate: string
  bundle?: any
  useBundle?: boolean
  bundlePending?: boolean
  chartBundlePending?: boolean
}>()

const BT = 'Public services'

const dualEl    = ref<HTMLElement | null>(null)
const profileEl = ref<HTMLElement | null>(null)
const comfortEl = ref<HTMLElement | null>(null)
let instances: echarts.ECharts[] = []
let loadController: AbortController | null = null
const chartTaskRunner = createDeferredTaskRunner()

const statusSnap  = ref<any>(null)
const anomalies   = ref<any[]>([])
const ratedSummary = ref<any>(null)

// ── 舒适度评分（基于实时快照温湿度阈值规则）─────────────────────────────────
const comfortScore = computed(() => {
  const s = statusSnap.value
  if (!s) return { score: null, text: '--', temp: null, humidity: null }
  const t = Number(s.air_temp_c)
  const h = Number(s.humidity_rh_pct)
  let score = 100
  if (t < 18 || t > 28) score -= 25
  else if (t < 20 || t > 26) score -= 10
  if (h < 35 || h > 65) score -= 20
  else if (h < 40 || h > 60) score -= 8
  const text = score >= 80 ? '良好' : score >= 60 ? '一般' : '关注'
  return { score, text, temp: t, humidity: h }
})

const miniCards = computed(() => {
  const cs = comfortScore.value
  return [
    {
      label: '舒适度评分',
      value: cs.score != null ? String(cs.score) : '--',
      unit: '分',
      desc: '综合温湿度判定室内舒适程度：≥80 良好，60–79 一般，<60 需关注',
    },
    {
      label: '当前温度',
      value: cs.temp != null ? cs.temp.toFixed(2) : '--',
      unit: '°C',
      desc: '舒适区间 20–26°C，超出范围时得分降低',
    },
    {
      label: '当前湿度',
      value: cs.humidity != null ? cs.humidity.toFixed(2) : '--',
      unit: '%RH',
      desc: '舒适区间 40–60%，过高或过低均影响舒适度',
    },
  ]
})

function disposeAll() {
  instances.forEach((c) => c.dispose())
  instances = []
}

// ── 水电综合双轴趋势 ──────────────────────────────────────────────────────────
function renderDual(records: any[]) {
  if (!dualEl.value) return
  const c = gc()
  const days  = records.map((r: any) => (r.day || '').slice(5))
  const elec  = records.map((r: any) => r.total_electricity_kwh != null ? Number(r.total_electricity_kwh) : null)
  const water = records.map((r: any) => r.total_water_m3 != null ? Number(r.total_water_m3) : null)

  const inst = echarts.init(dualEl.value)
  inst.setOption({
    backgroundColor: 'transparent',
    grid: { top: 40, right: 56, bottom: 54, left: 56 },
    tooltip: {
      trigger: 'axis',
      backgroundColor: c.ttBg,
      borderColor: c.ttBr,
      textStyle: { color: c.ttText },
    },
    legend: {
      top: 6,
      textStyle: { color: c.axis, fontSize: 10 },
      itemStyle: { borderWidth: 0 },
    },
    xAxis: {
      type: 'category',
      data: days,
      axisLabel: { color: c.axis, fontSize: 9, rotate: 30 },
      axisLine: { lineStyle: { color: c.grid } },
      axisTick: { show: false },
    },
    dataZoom: [
      {
        type: 'slider',
        bottom: 6,
        height: 16,
        start: days.length > 14 ? Math.round((1 - 14 / days.length) * 100) : 0,
        end: 100,
        borderColor: 'transparent',
        backgroundColor: c.grid,
        fillerColor: `${MC.blue}30`,
        handleStyle: { color: MC.blue, borderColor: MC.blue },
        textStyle: { color: c.axis, fontSize: 9 },
        showDataShadow: false,
      },
      { type: 'inside', start: days.length > 14 ? Math.round((1 - 14 / days.length) * 100) : 0, end: 100 },
    ],
    yAxis: [
      {
        type: 'value',
        name: 'kWh',
        nameTextStyle: { color: MC.sage, fontSize: 10 },
        axisLabel: { color: MC.sage, fontSize: 10 },
        splitLine: { lineStyle: { color: c.grid, type: 'dashed' } },
        axisLine: { show: false },
      },
      {
        type: 'value',
        name: 'm³',
        nameTextStyle: { color: MC.blue, fontSize: 10 },
        axisLabel: { color: MC.blue, fontSize: 10 },
        splitLine: { show: false },
        axisLine: { show: false },
      },
    ],
    series: [
      {
        name: '用电(kWh)',
        type: 'bar',
        data: elec,
        barMaxWidth: 24,
        itemStyle: {
          color: {
            type: 'linear', x: 0, y: 0, x2: 0, y2: 1,
            colorStops: [
              { offset: 0, color: MC.sage },
              { offset: 1, color: `${MC.sage}70` },
            ],
          },
          borderRadius: [3, 3, 0, 0],
        },
      },
      {
        name: '用水(m³)',
        type: 'line',
        yAxisIndex: 1,
        data: water,
        smooth: true,
        symbol: 'circle',
        symbolSize: 5,
        connectNulls: false,
        lineStyle: { color: MC.blue, width: 2.5 },
        itemStyle: { color: MC.blue },
      },
    ],
  })
  instances.push(inst)
}

// ── 全天候用电剖面（24h 逐时均值）────────────────────────────────────────────
function renderProfile(hourly: { hour: number; avg_value: number }[]) {
  if (!profileEl.value) return
  const c = gc()
  const cats = Array.from({ length: 24 }, (_, i) => `${i}`)
  const data = cats.map((_, h) => {
    const row = hourly.find((x) => x.hour === h)
    return row?.avg_value != null ? Number(row.avg_value) : null
  })

  const inst = echarts.init(profileEl.value)
  inst.setOption({
    backgroundColor: 'transparent',
    grid: { top: 32, right: 16, bottom: 32, left: 52 },
    tooltip: {
      trigger: 'axis',
      backgroundColor: c.ttBg,
      borderColor: c.ttBr,
      textStyle: { color: c.ttText },
      formatter: (params: any[]) => {
        const p = params[0]
        return `${p.axisValue}:00&nbsp;&nbsp;<b>${p.value != null ? Number(p.value).toFixed(2) : '--'} kWh/h</b>`
      },
    },
    xAxis: {
      type: 'category',
      data: cats,
      name: '时',
      nameTextStyle: { color: c.axis, fontSize: 10 },
      axisLabel: { color: c.axis, fontSize: 9, interval: 3 },
      axisLine: { lineStyle: { color: c.grid } },
      axisTick: { show: false },
    },
    yAxis: {
      type: 'value',
      name: 'kWh/h',
      nameTextStyle: { color: c.axis, fontSize: 10 },
      axisLabel: { color: c.axis, fontSize: 10 },
      splitLine: { lineStyle: { color: c.grid, type: 'dashed' } },
      axisLine: { show: false },
    },
    series: [
      {
        name: '逐时均值',
        type: 'line',
        data,
        smooth: true,
        symbol: 'none',
        connectNulls: false,
        lineStyle: { color: MC.sage, width: 2.5 },
        areaStyle: {
          color: {
            type: 'linear', x: 0, y: 0, x2: 0, y2: 1,
            colorStops: [
              { offset: 0, color: `${MC.sage}35` },
              { offset: 1, color: `${MC.sage}05` },
            ],
          },
        },
      },
    ],
  })
  instances.push(inst)
}

// ── 舒适度趋势（典型日：温度 + 湿度双轴）────────────────────────────────────
function renderComfort(hourlyT: (number | null)[], hourlyH: (number | null)[]) {
  if (!comfortEl.value) return
  const c = gc()
  const cats = Array.from({ length: 24 }, (_, i) => `${i}`)

  const hasT = hourlyT.some((v) => v !== null)
  const hasH = hourlyH.some((v) => v !== null)

  const series: any[] = []
  if (hasT) {
    series.push({
      name: '温度',
      type: 'line',
      data: hourlyT,
      smooth: true,
      symbol: 'none',
      connectNulls: false,
      lineStyle: { color: MC.terra, width: 2.5 },
      areaStyle: {
        color: {
          type: 'linear', x: 0, y: 0, x2: 0, y2: 1,
          colorStops: [
            { offset: 0, color: `${MC.terra}28` },
            { offset: 1, color: `${MC.terra}05` },
          ],
        },
      },
    })
  }
  if (hasH) {
    series.push({
      name: '湿度',
      type: 'line',
      yAxisIndex: 1,
      data: hourlyH,
      smooth: true,
      symbol: 'none',
      connectNulls: false,
      lineStyle: { color: MC.blue, width: 2.5, type: 'dashed' },
    })
  }

  const inst = echarts.init(comfortEl.value)
  inst.setOption({
    backgroundColor: 'transparent',
    grid: { top: 36, right: 52, bottom: 32, left: 48 },
    tooltip: {
      trigger: 'axis',
      backgroundColor: c.ttBg,
      borderColor: c.ttBr,
      textStyle: { color: c.ttText },
    },
    legend: {
      top: 6,
      textStyle: { color: c.axis, fontSize: 10 },
      itemStyle: { borderWidth: 0 },
    },
    xAxis: {
      type: 'category',
      data: cats,
      name: '时',
      nameTextStyle: { color: c.axis, fontSize: 10 },
      axisLabel: { color: c.axis, fontSize: 9, interval: 3 },
      axisLine: { lineStyle: { color: c.grid } },
      axisTick: { show: false },
    },
    yAxis: [
      {
        type: 'value',
        name: '°C',
        nameTextStyle: { color: MC.terra, fontSize: 10 },
        axisLabel: { color: MC.terra, fontSize: 10 },
        splitLine: { lineStyle: { color: c.grid, type: 'dashed' } },
        axisLine: { show: false },
        // 舒适区视觉参考带
        markLine: hasT ? {
          silent: true,
          lineStyle: { type: 'dashed', color: `${MC.terra}60`, width: 1 },
          data: [{ yAxis: 20, name: '下限 20°C' }, { yAxis: 26, name: '上限 26°C' }],
          label: { show: true, fontSize: 9, color: `${MC.terra}99` },
        } : undefined,
      },
      {
        type: 'value',
        name: '%RH',
        nameTextStyle: { color: MC.blue, fontSize: 10 },
        axisLabel: { color: MC.blue, fontSize: 10 },
        splitLine: { show: false },
        axisLine: { show: false },
      },
    ],
    series,
  })
  instances.push(inst)
}

function fmtTime(iso: string) {
  return (iso || '').replace('T', ' ').slice(0, 16)
}

async function loadAll() {
  loadController?.abort()
  const controller = new AbortController()
  loadController = controller
  const finish = startPerfSpan('home.public.section.load', {
    hasBundle: Boolean(props.bundle),
  })

  if (props.bundle) {
    const en = props.bundle.energy ?? { records: [] }
    const lpE = props.bundle.load_profile_electricity ?? { hourly_profile: [] }
    const lpT = props.bundle.load_profile_air_temp ?? { hourly_profile: [] }
    const lpH = props.bundle.load_profile_humidity ?? { hourly_profile: [] }
    const ax = props.bundle.anomalies ?? { anomalies: [] }
    const rv = props.bundle.rated_vs_actual_electricity ?? null
    const st = props.bundle.status ?? null

    statusSnap.value = st
    anomalies.value = ax?.anomalies ?? []
    ratedSummary.value = rv?.summary ?? null

    const hasChartPayload = Boolean(
      (en?.records?.length ?? 0) ||
      (lpE?.hourly_profile?.length ?? 0) ||
      (lpT?.hourly_profile?.length ?? 0) ||
      (lpH?.hourly_profile?.length ?? 0) ||
      (rv?.records?.length ?? 0),
    )
    if (props.chartBundlePending && !hasChartPayload) {
      finish('ok', { state: 'charts_pending' })
      return
    }

    const toHourly = (profile: any[]) =>
      Array.from({ length: 24 }, (_, h) => {
        const row = profile?.find((x: any) => x.hour === h)
        return row?.avg_value != null ? Number(row.avg_value) : null
      })

    const hourlyT = toHourly(lpT.hourly_profile)
    const hourlyH = toHourly(lpH.hourly_profile)

    chartTaskRunner.clear()
    disposeAll()
    chartTaskRunner.schedule(
      [
        () => renderDual(en.records || []),
        () => renderProfile(lpE.hourly_profile || []),
        () => renderComfort(hourlyT, hourlyH),
      ],
      () => {
        nextTick(() => instances.forEach((i) => i.resize()))
      },
    )
    finish('ok', { anomalyCount: anomalies.value.length })
    return
  }

  if (props.useBundle && props.bundlePending) {
    finish('ok', { state: 'pending' })
    return
  }

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
      cachedApiFetch<any>(`/api/buildings/${encodeURIComponent(BT)}/energy?start_date=${sd}&end_date=${ed}&include_water=true`, undefined, { signal: controller.signal }),
      cachedApiFetch<any>(`/api/buildings/${encodeURIComponent(BT)}/load-profile?metric=electricity&days=14`, undefined, { signal: controller.signal }),
      cachedApiFetch<any>(`/api/buildings/${encodeURIComponent(BT)}/load-profile?metric=air_temp&days=14`, undefined, { signal: controller.signal }).catch(() => ({ hourly_profile: [] })),
      cachedApiFetch<any>(`/api/buildings/${encodeURIComponent(BT)}/load-profile?metric=humidity&days=14`, undefined, { signal: controller.signal }).catch(() => ({ hourly_profile: [] })),
      cachedApiFetch<any>(`/api/anomalies/recent?hours=168&building_type=${encodeURIComponent(BT)}`, undefined, { signal: controller.signal }),
      cachedApiFetch<any>(`/api/buildings/${encodeURIComponent(BT)}/rated-vs-actual?start_date=${sds}&end_date=${ed}&metric=electricity`, undefined, { signal: controller.signal }).catch(() => null),
    ])

    const st = await cachedApiFetch<any>(`/api/buildings/${encodeURIComponent(BT)}/status`, undefined, { signal: controller.signal }).catch(() => null)
    if (loadController !== controller || controller.signal.aborted) return
    statusSnap.value  = st
    anomalies.value   = ax?.anomalies ?? []
    ratedSummary.value = rv?.summary ?? null

    const toHourly = (profile: any[]) =>
      Array.from({ length: 24 }, (_, h) => {
        const row = profile?.find((x: any) => x.hour === h)
        return row?.avg_value != null ? Number(row.avg_value) : null
      })

    const hourlyT = toHourly(lpT.hourly_profile)
    const hourlyH = toHourly(lpH.hourly_profile)

    chartTaskRunner.clear()
    disposeAll()
    chartTaskRunner.schedule(
      [
        () => renderDual(en.records || []),
        () => renderProfile(lpE.hourly_profile || []),
        () => renderComfort(hourlyT, hourlyH),
      ],
      () => {
        nextTick(() => instances.forEach((i) => i.resize()))
      },
    )
    finish('ok', { anomalyCount: anomalies.value.length })
  } catch (error) {
    if (isAbortError(error)) {
      finish('abort')
      return
    }
    finish('error', { message: error instanceof Error ? error.message : String(error) })
    disposeAll()
  }
}

watch(
  () => [props.dataDate, props.bundle, props.bundlePending, props.chartBundlePending],
  () => loadAll(),
  { deep: true, immediate: true },
)

function onResize() {
  instances.forEach((c) => c.resize())
}

let ro: ResizeObserver | null = null

onMounted(() => {
  window.addEventListener('resize', onResize)
  const el = document.querySelector('.home-page') as HTMLElement | null
  if (el && typeof ResizeObserver !== 'undefined') {
    ro = new ResizeObserver(() => instances.forEach((c) => c.resize()))
    ro.observe(el)
  }
})

onUnmounted(() => {
  loadController?.abort()
  loadController = null
  chartTaskRunner.clear()
  disposeAll()
  window.removeEventListener('resize', onResize)
  ro?.disconnect()
  ro = null
})
</script>

<template>
  <div class="home-public-section">

    <!-- 第一行：舒适区评分 + 异常事件时间轴 -->
    <div class="bento-row bento-r1">
      <div
        class="cpanel"
        data-pick-id="public-kpi-comfort-score"
        data-pick-type="kpi"
        data-pick-title="公共楼舒适度评分"
        data-pick-subtitle="基于最新温湿度快照的室内舒适度评估"
      >
        <div class="cpanel-hd">
          <span class="cpanel-title">舒适区评分</span>
          <span class="cpanel-sub">基于最新温湿度快照判定室内热舒适程度，满分 100 分</span>
        </div>
        <div style="padding: 12px 14px 16px">
          <HomeMiniMetricCards :cards="miniCards" />
        </div>
      </div>
      <div
        class="cpanel"
        data-pick-id="public-timeline-anomalies"
        data-pick-type="timeline"
        data-pick-title="公共楼异常事件时间轴"
        data-pick-subtitle="近 7 天公共楼异常事件按时间倒序排列"
      >
        <div class="cpanel-hd">
          <span class="cpanel-title">异常事件时间轴</span>
          <span class="cpanel-sub">近 7 天内检测到的异常用能事件，按时间倒序排列</span>
        </div>
        <div class="home-timeline">
          <div
            v-for="(a, i) in anomalies.slice(0, 10)"
            :key="i"
            class="home-timeline-item"
          >
            <span class="tl-dot">
              <Icon icon="mdi:alert-circle" width="13" class="tl-icon" />
            </span>
            <div class="tl-body">
              <span class="tl-time">{{ fmtTime(a.timestamp) }}</span>
              <span class="tl-msg">{{ (a.message || a.rule || '异常').toString().slice(0, 60) }}</span>
            </div>
          </div>
          <div v-if="!anomalies.length" class="home-timeline-empty">
            <Icon icon="mdi:check-circle-outline" width="16" />
            近期无未解决告警，持续监测中
          </div>
        </div>
      </div>
    </div>

    <!-- 第二行：水电综合双轴趋势 + 全天候用电剖面 -->
    <div class="bento-row bento-r1">
      <div
        class="cpanel"
        data-pick-id="public-chart-dual-trend"
        data-pick-type="chart"
        data-pick-title="公共楼水电综合双轴趋势"
        data-pick-subtitle="近 30 日总用电量与总用水量双轴对比"
      >
        <div class="cpanel-hd">
          <span class="cpanel-title">水电综合双轴趋势</span>
          <span class="cpanel-sub">近 30 日日总用电量（柱/kWh）与日总用水量（折线/m³）双轴对比</span>
        </div>
        <div ref="dualEl" class="cpanel-body" style="height: 260px" />
      </div>
      <div
        class="cpanel"
        data-pick-id="public-chart-hourly-profile"
        data-pick-type="chart"
        data-pick-title="公共楼全天候用电剖面"
        data-pick-subtitle="24 小时逐时平均用电强度分布"
      >
        <div class="cpanel-hd">
          <span class="cpanel-title">全天候用电剖面</span>
          <span class="cpanel-sub">24 小时逐时平均用电强度（kWh/h），反映一天中的用电规律</span>
        </div>
        <div ref="profileEl" class="cpanel-body" style="height: 260px" />
      </div>
    </div>

    <!-- 第三行：舒适度趋势 + 建议动作 -->
    <div class="bento-row bento-r1">
      <div
        class="cpanel"
        data-pick-id="public-chart-comfort-trend"
        data-pick-type="chart"
        data-pick-title="公共楼舒适度趋势"
        data-pick-subtitle="逐时温度与湿度曲线，对照舒适区边界"
      >
        <div class="cpanel-hd">
          <span class="cpanel-title">舒适度趋势（典型日）</span>
          <span class="cpanel-sub">室内逐时均温（°C，实线）与均湿度（%RH，虚线），参考线为舒适区边界</span>
        </div>
        <div ref="comfortEl" class="cpanel-body" style="height: 260px" />
      </div>
      <HomeActionCards
        tab="Public services"
        :anomalies="anomalies"
        :rated-anomaly-hours="ratedSummary?.anomaly_hours ?? null"
      />
    </div>

    <div class="bento-row bento-r-full">
      <HomeEnergyHeatmap
        :building-types="[BT]"
        :profiles="[bundle?.load_profile_electricity ?? null]"
        :use-bundle="useBundle"
        :bundle-pending="chartBundlePending"
        title="24h 能耗日历热力图"
        subtitle="近两周公共楼逐时负荷合成的 7×24 节律"
        pick-id="public-chart-heatmap"
        pick-title="公共楼 24h 能耗日历热力图"
        pick-subtitle="近两周公共楼典型负荷节律"
      />
    </div>

  </div>
</template>

<style scoped>
/* ── 时间轴 ─────────────────────────────────────────────────────────────────── */
.home-timeline {
  padding: 8px 14px 12px;
  display: flex;
  flex-direction: column;
  gap: 0;
  max-height: 220px;
  overflow-y: auto;
}

.home-timeline-item {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  padding: 7px 0;
  border-bottom: 1px solid var(--border);
}
.home-timeline-item:last-child { border-bottom: none; }

.tl-dot {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 22px;
  height: 22px;
  border-radius: 50%;
  background: rgba(249, 115, 22, 0.12);
  color: #f97316;
  flex-shrink: 0;
  margin-top: 1px;
}

.tl-icon { display: block; }

.tl-body {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}

.tl-time {
  font-size: 10px;
  color: var(--text-muted);
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
}

.tl-msg {
  font-size: 12px;
  color: var(--text-secondary);
  line-height: 1.4;
  word-break: break-all;
}

.home-timeline-empty {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 16px 0;
  color: var(--text-muted);
  font-size: 13px;
}

/* Light theme */
html[data-theme="light"] .tl-dot {
  background: rgba(249, 115, 22, 0.08);
}
html[data-theme="light"] .tl-msg {
  color: #374151;
}
</style>
