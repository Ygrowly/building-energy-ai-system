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

const workEl  = ref<HTMLElement | null>(null)
const euiEl   = ref<HTMLElement | null>(null)
const trendEl = ref<HTMLElement | null>(null)
const sparkEl = ref<HTMLElement | null>(null)
const rankEl  = ref<HTMLElement | null>(null)
let instances: echarts.ECharts[] = []

const peakValley  = ref<any>(null)
const anomalies   = ref<any[]>([])

// EUI 比值：当日能源强度 / 国标基准（1.0× = 合规）
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
    {
      label: '峰值',
      value: pv?.peak_value != null ? Number(pv.peak_value).toFixed(2) : '--',
      unit: 'kWh·日',
      desc: '近 7 日最高单日用电量，反映峰时用能水平',
    },
    {
      label: '谷值',
      value: pv?.valley_value != null ? Number(pv.valley_value).toFixed(2) : '--',
      unit: 'kWh·日',
      desc: '近 7 日最低单日用电量，通常对应节假日或停工日',
    },
    {
      label: '峰谷比',
      value: pv?.peak_valley_ratio != null ? Number(pv.peak_valley_ratio).toFixed(2) : '--',
      unit: '',
      desc: '峰值与谷值之比，比值越大表示用能波动越剧烈',
    },
    {
      label: '夜间异常采样',
      value: String(pv?.night_abnormal_hours ?? 0),
      unit: '次',
      desc: '非工作时段（22:00–6:00）检测到的异常用电次数',
    },
  ]
})

function disposeAll() {
  instances.forEach((c) => c.dispose())
  instances = []
}

// ── 工作时段能耗带状图 ─────────────────────────────────────────────────────────
function renderWorkBand(hourly: { hour: number; avg_value: number }[]) {
  if (!workEl.value) return
  const c = gc()
  const cats = Array.from({ length: 24 }, (_, i) => String(i))
  const data = cats.map((_, h) => {
    const row = hourly.find((x) => x.hour === h)
    return row?.avg_value != null ? Number(row.avg_value) : null
  })

  const inst = echarts.init(workEl.value)
  inst.setOption({
    backgroundColor: 'transparent',
    grid: { top: 36, right: 16, bottom: 36, left: 52 },
    tooltip: {
      trigger: 'axis',
      backgroundColor: c.ttBg,
      borderColor: c.ttBr,
      textStyle: { color: c.ttText },
      formatter: (params: any[]) => {
        const p = params[0]
        return `${p.axisValue}:00&nbsp;&nbsp;<b>${p.value != null ? p.value.toFixed(2) : '--'} kWh/h</b>`
      },
    },
    xAxis: {
      type: 'category',
      data: cats,
      name: '时',
      nameTextStyle: { color: c.axis, fontSize: 10 },
      axisLabel: { color: c.axis, fontSize: 10 },
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
        lineStyle: { color: MC.blue, width: 2.5 },
        areaStyle: {
          color: {
            type: 'linear', x: 0, y: 0, x2: 0, y2: 1,
            colorStops: [
              { offset: 0, color: `${MC.blue}35` },
              { offset: 1, color: `${MC.blue}05` },
            ],
          },
        },
        // 工作时段 8–18 参考带
        markArea: {
          silent: true,
          itemStyle: { color: `${MC.sage}22`, borderWidth: 0 },
          data: [[{ xAxis: '8', name: '工作时段' }, { xAxis: '18' }]],
          label: { show: true, position: 'insideTopLeft', fontSize: 9, color: MC.sage, offset: [4, 4] },
        },
      },
    ],
  })
  instances.push(inst)
}

// ── EUI 合规仪表 ──────────────────────────────────────────────────────────────
function renderEuiGauge(ratio: number | null) {
  if (!euiEl.value) return
  const c = gc()
  const r = ratio == null ? 0 : Math.min(Math.max(ratio, 0), 2.2)

  const colorBands: [number, string][] = [
    [0.5, '#22c55e'],   // 绿：<1.0×
    [0.75, '#f59e0b'],  // 橙：1.0–1.5×
    [1.0, '#ef4444'],   // 红：>1.5×
  ]

  const inst = echarts.init(euiEl.value)
  inst.setOption({
    backgroundColor: 'transparent',
    series: [
      {
        type: 'gauge',
        center: ['50%', '60%'],
        radius: '85%',
        min: 0,
        max: 2,
        splitNumber: 4,
        axisLine: {
          lineStyle: {
            width: 16,
            color: colorBands,
          },
        },
        pointer: { width: 5, length: '68%', itemStyle: { color: MC.blue } },
        axisTick: { show: false },
        splitLine: { show: false },
        axisLabel: {
          color: c.axis,
          fontSize: 10,
          distance: 14,
          formatter: (v: number) => `${v.toFixed(1)}×`,
        },
        title: {
          show: true,
          offsetCenter: [0, '82%'],
          color: c.axis,
          fontSize: 11,
        },
        detail: {
          valueAnimation: true,
          formatter: (v: number) => (ratio == null ? '--' : `${v.toFixed(2)}×`),
          color: c.ttText,
          fontSize: 20,
          fontWeight: 700,
          offsetCenter: [0, '30%'],
        },
        data: [{ value: r, name: 'EUI 相对国标' }],
      },
    ],
  })
  instances.push(inst)
}

// ── 近 7 天趋势 + 气温 ─────────────────────────────────────────────────────────
function renderTrend(records: any[]) {
  if (!trendEl.value) return
  const c = gc()
  const days = records.map((r: any) => (r.day || '').slice(5))
  const elec = records.map((r: any) => (r.total_electricity_kwh != null ? Number(r.total_electricity_kwh) : null))
  const temp = records.map((r: any) => (r.avg_ambient_temp != null ? Number(r.avg_ambient_temp) : null))

  const inst = echarts.init(trendEl.value)
  inst.setOption({
    backgroundColor: 'transparent',
    grid: { top: 36, right: 52, bottom: 32, left: 52 },
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
      axisLabel: { color: c.axis, fontSize: 10 },
      axisLine: { lineStyle: { color: c.grid } },
      axisTick: { show: false },
    },
    yAxis: [
      {
        type: 'value',
        name: 'kWh',
        nameTextStyle: { color: c.axis, fontSize: 10 },
        axisLabel: { color: c.axis, fontSize: 10 },
        splitLine: { lineStyle: { color: c.grid, type: 'dashed' } },
        axisLine: { show: false },
      },
      {
        type: 'value',
        name: '°C',
        nameTextStyle: { color: MC.terra, fontSize: 10 },
        axisLabel: { color: MC.terra, fontSize: 10 },
        splitLine: { show: false },
        axisLine: { show: false },
      },
    ],
    series: [
      {
        name: '用电',
        type: 'bar',
        data: elec,
        barMaxWidth: 28,
        itemStyle: {
          color: {
            type: 'linear', x: 0, y: 0, x2: 0, y2: 1,
            colorStops: [
              { offset: 0, color: MC.sage },
              { offset: 1, color: `${MC.sage}80` },
            ],
          },
          borderRadius: [3, 3, 0, 0],
        },
      },
      {
        name: '均温',
        type: 'line',
        yAxisIndex: 1,
        data: temp,
        smooth: true,
        symbol: 'circle',
        symbolSize: 5,
        connectNulls: false,
        lineStyle: { color: MC.terra, width: 2.5 },
        itemStyle: { color: MC.terra },
      },
    ],
  })
  instances.push(inst)
}

// ── 峰谷效率 Sparkline ─────────────────────────────────────────────────────────
function renderSparkline(daily: { day: string; total: number }[]) {
  if (!sparkEl.value) return
  const c = gc()
  const vals = daily.map((d) => d.total)
  const labels = daily.map((d) => d.day.slice(5))

  const inst = echarts.init(sparkEl.value)
  inst.setOption({
    backgroundColor: 'transparent',
    grid: { top: 8, right: 8, bottom: 20, left: 8 },
    tooltip: {
      trigger: 'axis',
      backgroundColor: c.ttBg,
      borderColor: c.ttBr,
      textStyle: { color: c.ttText, fontSize: 11 },
      formatter: (params: any[]) => `${params[0].axisValue}&nbsp;<b>${params[0].value?.toFixed(1) ?? '--'} kWh</b>`,
    },
    xAxis: {
      type: 'category',
      data: labels,
      axisLabel: { color: c.axis, fontSize: 9 },
      axisLine: { show: false },
      axisTick: { show: false },
    },
    yAxis: { type: 'value', show: false },
    series: [
      {
        type: 'line',
        data: vals,
        smooth: true,
        symbol: 'none',
        lineStyle: { color: MC.terra, width: 2 },
        areaStyle: {
          color: {
            type: 'linear', x: 0, y: 0, x2: 0, y2: 1,
            colorStops: [
              { offset: 0, color: `${MC.terra}35` },
              { offset: 1, color: `${MC.terra}05` },
            ],
          },
        },
      },
    ],
  })
  instances.push(inst)
}

// ── 日能耗排行（横向柱） ──────────────────────────────────────────────────────
function renderRank(daily: { day: string; total: number }[]) {
  if (!rankEl.value) return
  const c = gc()
  const sorted = [...daily].sort((a, b) => b.total - a.total).slice(0, 7)
  const labels = sorted.map((d) => d.day.slice(5))
  const vals = sorted.map((d) => Number(d.total.toFixed(2)))

  const maxVal = vals[0] ?? 1

  const styledVals = vals.map((v, i) => ({
    value: v,
    itemStyle: {
      color: i === 0
        ? MC.lav     // 最高日用橙红突出显示
        : { type: 'linear', x: 0, y: 0, x2: 1, y2: 0,
            colorStops: [
              { offset: 0, color: MC.blue },
              { offset: 1, color: `${MC.blue}80` },
            ] },
      borderRadius: [0, 3, 3, 0],
      opacity: 0.85 + 0.15 * (1 - i / (vals.length - 1 || 1)),
    },
  }))

  const inst = echarts.init(rankEl.value)
  inst.setOption({
    backgroundColor: 'transparent',
    grid: { top: 8, right: 64, bottom: 28, left: 48 },
    tooltip: {
      trigger: 'axis',
      backgroundColor: c.ttBg,
      borderColor: c.ttBr,
      textStyle: { color: c.ttText },
    },
    xAxis: {
      type: 'value',
      name: 'kWh',
      nameTextStyle: { color: c.axis, fontSize: 10 },
      max: Math.ceil(maxVal * 1.1),
      axisLabel: { color: c.axis, fontSize: 9 },
      splitLine: { lineStyle: { color: c.grid, type: 'dashed' } },
      axisLine: { show: false },
      axisTick: { show: false },
    },
    yAxis: {
      type: 'category',
      data: labels,
      axisLabel: { color: c.axis, fontSize: 10 },
      axisLine: { lineStyle: { color: c.grid } },
      axisTick: { show: false },
      inverse: true,
    },
    series: [
      {
        type: 'bar',
        data: styledVals,
        barMaxWidth: 18,
        label: {
          show: true,
          position: 'right',
          color: c.axis,
          fontSize: 10,
          formatter: (p: any) => p.value.toFixed(1),
        },
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
    const [lp, pv, en, ax] = await Promise.all([
      apiFetch<any>(`/api/buildings/${encodeURIComponent(BT)}/load-profile?metric=electricity&days=14`),
      apiFetch<any>(`/api/buildings/${encodeURIComponent(BT)}/peak-valley-stats?metric=electricity&days=7`),
      apiFetch<any>(`/api/buildings/${encodeURIComponent(BT)}/energy?start_date=${sd}&end_date=${ed}&include_water=false`),
      apiFetch<any>(`/api/anomalies/recent?hours=168&building_type=${encodeURIComponent(BT)}`),
    ])

    peakValley.value = pv
    anomalies.value  = ax?.anomalies ?? []

    disposeAll()
    renderWorkBand(lp.hourly_profile || [])
    renderEuiGauge(euiRatio.value)
    renderTrend(en.records || [])
    renderSparkline(pv.daily_totals || [])
    renderRank(pv.daily_totals || [])
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

    <!-- 第一行：峰谷与夜间指标 + 日能耗排行 -->
    <div class="bento-row bento-r1">
      <div class="cpanel">
        <div class="cpanel-hd">
          <span class="cpanel-title">峰谷与夜间指标</span>
          <span class="cpanel-sub">近 7 日峰值 · 谷值 · 峰谷比 · 夜间异常采样数</span>
        </div>
        <div style="padding: 12px 14px 16px">
          <HomeMiniMetricCards :cards="miniCards" />
        </div>
      </div>
      <div class="cpanel">
        <div class="cpanel-hd">
          <span class="cpanel-title">日能耗排行</span>
          <span class="cpanel-sub">近 7 日总用电量由高到低，橙色为最高能耗日</span>
        </div>
        <div ref="rankEl" class="cpanel-body" style="height: 220px" />
      </div>
    </div>

    <!-- 第二行：工作时段能耗带状图 + EUI 合规偏离 -->
    <div class="bento-row bento-r1">
      <div class="cpanel">
        <div class="cpanel-hd">
          <span class="cpanel-title">工作时段能耗带状图</span>
          <span class="cpanel-sub">24 小时逐时平均用电强度（kWh/h），绿色阴影为工作时段 8–18 时参考带</span>
        </div>
        <div ref="workEl" class="cpanel-body" style="height: 260px" />
      </div>
      <div class="cpanel">
        <div class="cpanel-hd">
          <span class="cpanel-title">EUI 合规偏离</span>
          <span class="cpanel-sub">建筑能源利用强度相对国标 75 kWh/㎡·年 的倍率，1.0× 为合规基准</span>
        </div>
        <div ref="euiEl" class="cpanel-body" style="height: 260px" />
      </div>
    </div>

    <!-- 第三行：近 7 天趋势 + (峰谷效率 spark + 建议动作) -->
    <div class="bento-row bento-r1">
      <div class="cpanel">
        <div class="cpanel-hd">
          <span class="cpanel-title">近 7 天趋势与气温</span>
          <span class="cpanel-sub">日总用电量（柱/kWh）与室外日均温度（折线/°C）双轴对比</span>
        </div>
        <div ref="trendEl" class="cpanel-body" style="height: 260px" />
      </div>
      <div class="cpanel-col">
        <div class="cpanel">
          <div class="cpanel-hd">
            <span class="cpanel-title">峰谷效率</span>
            <span class="cpanel-sub">近期日总能耗走势（kWh），反映日间用能波动</span>
          </div>
          <div ref="sparkEl" class="cpanel-body" style="height: 110px" />
        </div>
        <HomeActionCards
          tab="Office"
          :anomalies="anomalies"
          :night-abnormal-hours="peakValley?.night_abnormal_hours ?? null"
          :eui-ratio="euiRatio"
        />
      </div>
    </div>

  </div>
</template>
