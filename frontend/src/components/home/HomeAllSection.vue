<script setup lang="ts">
import { ref, computed, watch, onMounted, onUnmounted, nextTick } from 'vue'
import * as echarts from 'echarts'
import { useBuildingStore } from '@/stores/buildingStore'
import { apiFetch } from '@/api/http'
import { MC, gc, EUI_BASELINE, buildHeatmapCells } from '@/utils/homeCharts'
import HomeActionCards from './HomeActionCards.vue'
import { useReportExport } from '@/composables/useReportExport'

const props = defineProps<{
  overviewData: any
  anomalyData: any[]
  sankeyData: {
    nodes: { name: string }[]
    links: { source: string; target: string; value: number }[]
  } | null
}>()

const buildingStore = useBuildingStore()
const { captureChart } = useReportExport('home-charts')

// HVAC 图实时数据
const hvacApiData = ref<{ outdoorTemp: number[]; actualHvac: number[]; simOptHvac: number[] } | null>(null)

// 多楼栋能耗饼图切换
type CompareMetric = 'electricity' | 'water' | 'hac'
const compareMetric = ref<CompareMetric>('electricity')
const COMPARE_METRICS: { key: CompareMetric; label: string }[] = [
  { key: 'electricity', label: '当日用电' },
  { key: 'water', label: '当日用水' },
  { key: 'hac', label: '当日暖通' },
]

const radarEl   = ref<HTMLElement | null>(null)
const hvacEl    = ref<HTMLElement | null>(null)
const compareEl = ref<HTMLElement | null>(null)
const riskEl    = ref<HTMLElement | null>(null)
const sankeyEl  = ref<HTMLElement | null>(null)
const anomalyEl = ref<HTMLElement | null>(null)

let instances: echarts.ECharts[] = []

const ghDays = ['周一', '周二', '周三', '周四', '周五', '周六', '周日']
const ghData = ref<Array<{ d: number; h: number; v: number }>>([])
const ghMaxVal = ref(1)
const ghTip = ref<{ show: boolean; x: number; y: number; text: string }>({
  show: false,
  x: 0,
  y: 0,
  text: '',
})

const ghLegendColors = computed(() => {
  const dark = document.documentElement.dataset.theme !== 'light'
  return dark
    ? ['#161b22', '#0e4429', '#006d32', '#26a641', '#39d353']
    : ['#ebedf0', '#9be9a8', '#40c463', '#30a14e', '#216e39']
})

function getGhColor(v: number): string {
  const dark = document.documentElement.dataset.theme !== 'light'
  const ratio = Math.min(v / ghMaxVal.value, 1)
  const dk = ['#161b22', '#0e4429', '#006d32', '#26a641', '#39d353']
  const lt = ['#ebedf0', '#9be9a8', '#40c463', '#30a14e', '#216e39']
  const palette = dark ? dk : lt
  const breaks = [0.1, 0.3, 0.55, 0.75]
  let idx = 0
  for (const br of breaks) {
    if (ratio > br) idx++
  }
  return palette[idx]
}

function showGhTip(e: MouseEvent, cell: { d: number; h: number; v: number }) {
  const offHours = cell.d >= 5 || cell.h < 8 || cell.h > 18
  const anomaly = cell.v > ghMaxVal.value * 0.65 && offHours ? ' 非工时偏高' : ''
  ghTip.value = {
    show: true,
    text: `${ghDays[cell.d]} ${cell.h}:00 · ${cell.v} ${anomaly}`,
    x: e.clientX + 14,
    y: e.clientY - 42,
  }
}
function hideGhTip() {
  ghTip.value.show = false
}

const _SANKEY_SOURCE_COLORS: Record<string, string> = {
  水耗异常: MC.teal,
  电耗超标: MC.blue,
  空调过耗: MC.terra,
  标注异常: MC.rose,
  夜间高耗: MC.lav,
}
const _SANKEY_TARGET_COLORS: Record<string, string> = {
  主机效能衰退: MC.rose,
  水力失调: MC.blue,
  非预期开机: MC.lav,
  其他空调故障: MC.sage,
  管网漏损: MC.teal,
  负荷过载: MC.terra,
  数据标注: MC.lav,
  夜间异常运行: MC.lav,
}

function disposeAll() {
  instances.forEach((c) => c.dispose())
  instances = []
}

function renderRadar() {
  if (!radarEl.value) return
  const c = gc()
  const blds: any[] = props.overviewData?.buildings ?? []
  const bldStore = buildingStore.buildings

  const keys  = ['Education', 'Office', 'Public services']
  const names = ['教学楼', '办公楼', '公共楼']
  const colors = [MC.blue, MC.sage, MC.terra]

  // 五维：用电、用水、暖通、EUI偏离、告警数 — 各项归一化到 0-100
  const maxElec    = Math.max(...blds.map((b) => Number(b.total_electricity_kwh ?? 0)), 1)
  const maxWater   = Math.max(...blds.map((b) => Number(b.total_water_m3 ?? 0)), 1)
  const maxHac     = Math.max(...blds.map((b) => Number(b.total_hac_energy_kwh ?? 0)), 1)
  const maxAnomaly = Math.max(...keys.map((k) => props.anomalyData.filter((a: any) => a.building_type === k).length), 1)

  const seriesData = keys.map((k, i) => {
    const b    = blds.find((x) => x.building_type === k)
    const meta = bldStore.find((x) => x.building_type === k)
    const sqm  = meta?.sqm ?? 10000
    const elec = Number(b?.total_electricity_kwh ?? 0)
    const water = Number(b?.total_water_m3 ?? 0)
    const hac  = Number(b?.total_hac_energy_kwh ?? 0)
    const intensity = elec / sqm
    const baseline  = EUI_BASELINE[k] ?? 70
    const euiRatio  = baseline > 0 ? Math.min((intensity * 365) / baseline, 2.5) : 0
    const anomalyCnt = props.anomalyData.filter((a: any) => a.building_type === k).length

    return {
      name: names[i],
      value: [
        +(elec  / maxElec    * 100).toFixed(1),
        +(water / maxWater   * 100).toFixed(1),
        +(hac   / maxHac     * 100).toFixed(1),
        +(euiRatio / 2.5     * 100).toFixed(1),
        +(anomalyCnt / maxAnomaly * 100).toFixed(1),
      ],
      lineStyle:  { color: colors[i], width: 2 },
      itemStyle:  { color: colors[i] },
      areaStyle:  { color: colors[i], opacity: 0.10 },
    }
  })

  const inst = echarts.init(radarEl.value)
  inst.setOption({
    backgroundColor: 'transparent',
    tooltip: {
      backgroundColor: c.ttBg,
      borderColor: c.ttBr,
      textStyle: { color: c.ttText, fontSize: 11 },
      formatter: (p: any) => {
        const v = p.data.value as number[]
        const lines = [
          `<b>${p.data.name}</b>`,
          `用电占比：${v[0]}`,
          `用水占比：${v[1]}`,
          `暖通占比：${v[2]}`,
          `EUI 偏离：${v[3]}`,
          `告警占比：${v[4]}`,
        ]
        return lines.join('<br/>')
      },
    },
    legend: {
      top: 4,
      textStyle: { color: c.axis, fontSize: 10 },
      itemStyle: { borderWidth: 0 },
    },
    radar: {
      indicator: [
        { name: '用电', max: 100 },
        { name: '用水', max: 100 },
        { name: '暖通', max: 100 },
        { name: 'EUI\n偏离', max: 100 },
        { name: '告警数', max: 100 },
      ],
      center: ['50%', '54%'],
      radius: '65%',
      axisLine:  { lineStyle: { color: c.grid } },
      splitLine: { lineStyle: { color: c.grid } },
      splitArea: { show: false },
      axisName:  { color: c.axis, fontSize: 10 },
    },
    series: [
      {
        type: 'radar',
        symbol: 'circle',
        symbolSize: 5,
        data: seriesData,
      },
    ],
  })
  instances.push(inst)
}

async function loadHvacData() {
  // 取所有楼的 hac_energy + air_temp 小时均值并合并
  const types = ['Education', 'Office', 'Public services']
  const hacSum = new Array(24).fill(0)
  const tempSum = new Array(24).fill(0)
  let n = 0
  try {
    for (const bt of types) {
      const [rHac, rRv] = await Promise.all([
        apiFetch<any>(`/api/buildings/${encodeURIComponent(bt)}/load-profile?metric=hac_energy&days=14`),
        apiFetch<any>(`/api/buildings/${encodeURIComponent(bt)}/load-profile?metric=air_temp&days=14`),
      ])
      for (const x of rHac.hourly_profile || []) hacSum[x.hour] += Number(x.avg_value ?? 0)
      for (const x of rRv.hourly_profile || []) tempSum[x.hour] += Number(x.avg_value ?? 0)
      n++
    }
  } catch {
    // 保持 null，renderHvac 会显示无数据态
    return
  }
  if (!n) return

  // 用 rated-vs-actual 取一栋楼的近期数据估算"仿真最优"（用 rated 字段）
  let simHac: number[] = new Array(24).fill(0)
  try {
    const bt = 'Education'
    const rv = await apiFetch<any>(
      `/api/buildings/${encodeURIComponent(bt)}/load-profile?metric=hac_energy&days=7`,
    )
    // load-profile 已是均值；仿真最优暂设为实际均值 × 0.85（节能潜力估算）
    for (const x of rv.hourly_profile || []) simHac[x.hour] = Number(x.avg_value ?? 0) * 0.85 * n
  } catch {
    simHac = hacSum.map((v) => v * 0.85)
  }

  hvacApiData.value = {
    outdoorTemp: tempSum.map((v) => parseFloat((v / n).toFixed(1))),
    actualHvac: hacSum.map((v) => parseFloat((v / n).toFixed(1))),
    simOptHvac: simHac.map((v) => parseFloat((v / n).toFixed(1))),
  }
}

function renderHvac() {
  if (!hvacEl.value) return
  const c = gc()
  const hours = Array.from({ length: 24 }, (_, i) => `${i}:00`)

  if (!hvacApiData.value) {
    const inst = echarts.getInstanceByDom(hvacEl.value) || echarts.init(hvacEl.value)
    inst.setOption({
      backgroundColor: 'transparent',
      title: { text: '暖通数据加载中…', left: 'center', top: 'middle', textStyle: { color: c.axis, fontSize: 13 } },
    })
    instances.push(inst)
    return
  }

  const { outdoorTemp, actualHvac, simOptHvac } = hvacApiData.value

  const inst = echarts.init(hvacEl.value)
  inst.setOption({
    backgroundColor: 'transparent',
    grid: { top: 32, right: 18, bottom: 36, left: 52 },
    tooltip: {
      trigger: 'axis',
      backgroundColor: c.ttBg,
      borderColor: c.ttBr,
      textStyle: { color: c.ttText, fontSize: 11 },
    },
    legend: { top: 6, textStyle: { color: c.axis, fontSize: 10 }, itemWidth: 12 },
    xAxis: {
      type: 'category',
      data: hours,
      axisLabel: { color: c.axis, fontSize: 10, interval: 3 },
      axisLine: { lineStyle: { color: c.grid } },
      splitLine: { show: false },
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
        min: 0,
        max: 40,
        nameTextStyle: { color: c.axis, fontSize: 10 },
        axisLabel: { color: c.axis, fontSize: 10 },
        splitLine: { show: false },
      },
    ],
    series: [
      {
        name: '室外气温',
        type: 'line',
        yAxisIndex: 1,
        data: outdoorTemp,
        smooth: true,
        symbol: 'none',
        lineStyle: { width: 0 },
        areaStyle: {
          color: {
            type: 'linear',
            x: 0,
            y: 0,
            x2: 0,
            y2: 1,
            colorStops: [
              { offset: 0, color: 'rgba(196,149,106,0.22)' },
              { offset: 1, color: 'rgba(196,149,106,0.02)' },
            ],
          },
        },
        z: 1,
      },
      {
        name: '实际HVAC能耗',
        type: 'line',
        yAxisIndex: 0,
        data: actualHvac,
        smooth: true,
        symbol: 'none',
        lineStyle: { color: MC.blue, width: 2.5 },
        itemStyle: { color: MC.blue },
        z: 3,
      },
      {
        name: '节能基准估算',
        type: 'line',
        yAxisIndex: 0,
        data: simOptHvac,
        smooth: true,
        symbol: 'none',
        lineStyle: { color: MC.sage, width: 2, type: 'dashed' },
        itemStyle: { color: MC.sage },
        z: 2,
      },
    ],
  })
  instances.push(inst)
}

function renderPie() {
  if (!compareEl.value) return
  const c = gc()
  const blds: any[] = props.overviewData?.buildings ?? []

  const metricMap: Record<CompareMetric, { field: string; unit: string; color: string[] }> = {
    electricity: {
      field: 'total_electricity_kwh',
      unit: 'kWh',
      colors: [MC.sage, MC.blue, MC.lav],
    } as any,
    water: {
      field: 'total_water_m3',
      unit: 'm³',
      colors: [MC.blue, MC.teal, MC.sage],
    } as any,
    hac: {
      field: 'total_hac_energy_kwh',
      unit: 'kWh',
      colors: [MC.lav, MC.terra, MC.teal],
    } as any,
  }

  const cfg = metricMap[compareMetric.value] as any
  const pieData = blds
    .map((b) => ({
      name: b.display_name || b.building_type,
      value: parseFloat(Number(b[cfg.field] ?? 0).toFixed(1)),
    }))
    .filter((d) => d.value > 0)

  const labelMap: Record<CompareMetric, string> = {
    electricity: '用电',
    water: '用水',
    hac: '暖通',
  }

  const inst = echarts.getInstanceByDom(compareEl.value) || echarts.init(compareEl.value)

  if (!pieData.length) {
    inst.setOption({
      backgroundColor: 'transparent',
      title: { text: '暂无数据', left: 'center', top: 'middle', textStyle: { color: c.axis, fontSize: 13 } },
    })
    if (!instances.includes(inst)) instances.push(inst)
    return
  }

  inst.setOption({
    backgroundColor: 'transparent',
    tooltip: {
      trigger: 'item',
      backgroundColor: c.ttBg,
      borderColor: c.ttBr,
      textStyle: { color: c.ttText, fontSize: 11 },
      formatter: (p: any) => `${p.name}<br/>${labelMap[compareMetric.value]} ${p.value} ${cfg.unit}<br/>占比 ${p.percent}%`,
    },
    legend: {
      orient: 'vertical',
      right: 16,
      top: 'middle',
      textStyle: { color: c.axis, fontSize: 11 },
      itemWidth: 10,
      itemHeight: 10,
    },
    series: [
      {
        name: labelMap[compareMetric.value],
        type: 'pie',
        radius: ['38%', '68%'],
        center: ['38%', '50%'],
        avoidLabelOverlap: true,
        label: {
          show: true,
          formatter: '{b}\n{d}%',
          color: c.axis,
          fontSize: 11,
          lineHeight: 16,
        },
        labelLine: { lineStyle: { color: c.grid } },
        data: pieData.map((d, i) => ({
          ...d,
          itemStyle: { color: cfg.colors[i % cfg.colors.length] },
        })),
        emphasis: {
          itemStyle: { shadowBlur: 10, shadowOffsetX: 0, shadowColor: 'rgba(0,0,0,0.3)' },
        },
      },
    ],
  })
  if (!instances.includes(inst)) instances.push(inst)
}

function switchCompare(metric: CompareMetric) {
  compareMetric.value = metric
  renderPie()
}

function renderRisk() {
  if (!riskEl.value) return
  const c = gc()
  const labels = ['教学楼', '办公楼', '公共楼']
  const keys = ['Education', 'Office', 'Public services']
  const counts = keys.map((k) => props.anomalyData.filter((a: any) => a.building_type === k).length)

  const inst = echarts.init(riskEl.value)
  inst.setOption({
    backgroundColor: 'transparent',
    grid: { top: 28, right: 24, bottom: 28, left: 72 },
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
        name: '待处理条数',
        type: 'bar',
        data: counts,
        barMaxWidth: 24,
        itemStyle: {
          borderRadius: [0, 3, 3, 0],
          color: (p: any) => {
            const v = counts[p.dataIndex]
            if (v === 0) return '#22c55e'   // 绿：无告警
            if (v <= 3)  return MC.terra    // 橙：轻微
            return '#ef4444'                // 红：需重点关注
          },
        },
        label: { show: true, position: 'right', color: c.axis, fontSize: 10 },
      },
    ],
  })
  instances.push(inst)
}

function renderSankey() {
  if (!sankeyEl.value) return
  const c = gc()
  const sd = props.sankeyData
  const hasData = sd && sd.nodes.length > 0 && sd.links.length > 0

  const inst = echarts.init(sankeyEl.value)

  if (!hasData) {
    inst.setOption({
      backgroundColor: 'transparent',
      title: { text: '暂无根因数据', left: 'center', top: 'middle', textStyle: { color: c.axis, fontSize: 12 } },
    })
    instances.push(inst)
    return
  }

  const sourceNames = new Set(sd!.links.map((l) => l.source))
  const nodes = sd!.nodes.map((n) => ({
    name: n.name,
    itemStyle: {
      color: sourceNames.has(n.name)
        ? _SANKEY_SOURCE_COLORS[n.name] ?? MC.blue
        : _SANKEY_TARGET_COLORS[n.name] ?? MC.lav,
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
        links: sd!.links,
        lineStyle: { color: 'gradient', opacity: 0.42 },
        label: { color: c.axis, fontSize: 11 },
      },
    ],
  })
  instances.push(inst)
}

function renderAnomalyDist() {
  if (!anomalyEl.value) return
  const c = gc()
  const keys   = ['Education', 'Office', 'Public services']
  const labels = ['教学楼', '办公楼', '公共楼']

  const isUnresolved = (a: any) =>
    a.anomaly_status === 'Anomaly' || a.operation_status === 'Anomaly'

  const unresolvedCnts = keys.map((k) =>
    props.anomalyData.filter((a: any) => a.building_type === k && isUnresolved(a)).length,
  )
  const resolvedCnts = keys.map((k) =>
    props.anomalyData.filter((a: any) => a.building_type === k && !isUnresolved(a)).length,
  )

  const inst = echarts.init(anomalyEl.value)

  if (props.anomalyData.length === 0) {
    inst.setOption({
      backgroundColor: 'transparent',
      title: { text: '暂无异常事件', left: 'center', top: 'middle', textStyle: { color: c.axis, fontSize: 12 } },
    })
    instances.push(inst)
    return
  }

  inst.setOption({
    backgroundColor: 'transparent',
    grid: { top: 28, right: 16, bottom: 28, left: 52 },
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'shadow' },
      backgroundColor: c.ttBg,
      borderColor: c.ttBr,
      textStyle: { color: c.ttText, fontSize: 11 },
    },
    legend: { top: 4, textStyle: { color: c.axis, fontSize: 10 }, itemStyle: { borderWidth: 0 } },
    xAxis: {
      type: 'category',
      data: labels,
      axisLabel: { color: c.axis, fontSize: 10 },
      axisLine: { lineStyle: { color: c.grid } },
      axisTick: { show: false },
    },
    yAxis: {
      type: 'value',
      name: '条',
      nameTextStyle: { color: c.axis, fontSize: 10 },
      axisLabel: { color: c.axis, fontSize: 10 },
      splitLine: { lineStyle: { color: c.grid, type: 'dashed' } },
      axisLine: { show: false },
      minInterval: 1,
    },
    series: [
      {
        name: '待处理',
        type: 'bar',
        stack: 'total',
        data: unresolvedCnts,
        barMaxWidth: 36,
        itemStyle: { color: MC.lav },
        label: {
          show: true,
          position: 'inside',
          color: '#fff',
          fontSize: 10,
          formatter: (p: any) => (p.value > 0 ? String(p.value) : ''),
        },
      },
      {
        name: '已解决',
        type: 'bar',
        stack: 'total',
        data: resolvedCnts,
        barMaxWidth: 36,
        itemStyle: { color: MC.sage, borderRadius: [4, 4, 0, 0] },
        label: {
          show: true,
          position: 'top',
          color: c.axis,
          fontSize: 10,
          formatter: (p: any) => {
            const total = unresolvedCnts[p.dataIndex] + resolvedCnts[p.dataIndex]
            return total > 0 ? `共${total}` : ''
          },
        },
      },
    ],
  })
  instances.push(inst)
}

async function loadMergedHeatmap() {
  const types = ['Education', 'Office', 'Public services']
  const hourlySum = new Array(24).fill(0)
  const wdSum = new Array(7).fill(0)
  let n = 0
  try {
    for (const bt of types) {
      const r = await apiFetch<any>(
        `/api/buildings/${encodeURIComponent(bt)}/load-profile?metric=electricity&days=14`,
      )
      n++
      for (const x of r.hourly_profile || []) {
        hourlySum[x.hour] += Number(x.avg_value ?? 0)
      }
      for (const x of r.weekday_profile || []) {
        if (x.weekday >= 1 && x.weekday <= 7) wdSum[x.weekday - 1] += Number(x.avg_value ?? 0)
      }
    }
    if (!n) throw new Error('no data')
    const hourly = hourlySum.map((s, hour) => ({ hour, avg_value: s / n }))
    const weekly = wdSum.map((s, i) => ({ weekday: i + 1, avg_value: s / n }))
    const cells = buildHeatmapCells(hourly, weekly)
    ghData.value = cells
    ghMaxVal.value = Math.max(...cells.map((c) => c.v), 1)
  } catch {
    // API 失败时保持空数组，热力图显示为全空格
    ghData.value = []
    ghMaxVal.value = 1
  }
}

function renderAll() {
  disposeAll()
  renderRadar()
  renderHvac()
  renderPie()
  renderRisk()
  renderSankey()
  renderAnomalyDist()
  nextTick(() => {
    instances.forEach((i) => i.resize())
    // 图表稳定后截图注册到报表
    setTimeout(() => captureChartsForReport(), 500)
  })
}

function captureChartsForReport() {
  if (sankeyEl.value) {
    const inst = echarts.getInstanceByDom(sankeyEl.value)
    captureChart(inst, 'home-chart-sankey', '能耗异常根因流向', 25)
  }
  if (compareEl.value) {
    const inst = echarts.getInstanceByDom(compareEl.value)
    captureChart(inst, 'home-chart-compare', '各楼宇能耗对比', 22)
  }
}

function onResize() {
  instances.forEach((c) => c.resize())
}

let ro: ResizeObserver | null = null

watch(
  () => [
    props.overviewData?.data_date,
    props.anomalyData?.length,
    props.sankeyData?.nodes?.length,
    props.sankeyData?.links?.length,
  ],
  () => nextTick(() => renderAll()),
)

onMounted(async () => {
  await buildingStore.fetchBuildings()
  await Promise.all([loadMergedHeatmap(), loadHvacData()])
  await nextTick()
  setTimeout(() => {
    renderAll()
    window.addEventListener('resize', onResize)
    const el = document.querySelector('.home-page') as HTMLElement | null
    if (el && typeof ResizeObserver !== 'undefined') {
      ro = new ResizeObserver(() => instances.forEach((c) => c.resize()))
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
</script>

<template>
  <div class="home-all-section">
    <div class="bento-row bento-r1">
      <div
        class="cpanel"
        data-pick-id="chart-eui-radar"
        data-pick-type="chart"
        data-pick-title="楼宇多维能耗对比"
        data-pick-subtitle="用电、用水、暖通、EUI偏离、告警数五维标准化（各维最大值=100）"
      >
        <div class="cpanel-hd">
          <span class="cpanel-title">楼宇多维能耗对比</span>
          <span class="cpanel-sub">用电 · 用水 · 暖通 · EUI 偏离 · 告警数 五维标准化（各维最大值=100）</span>
        </div>
        <div ref="radarEl" class="cpanel-body" style="height: 300px" />
      </div>
      <div
        class="cpanel"
        data-pick-id="chart-hvac"
        data-pick-type="chart"
        data-pick-title="HVAC 虚实映射分析"
        data-pick-subtitle="实际暖通能耗与仿真最优值对比"
      >
        <div class="cpanel-hd">
          <span class="cpanel-title">HVAC 虚实映射分析</span>
          <span class="cpanel-sub">实际暖通能耗（实线）与节能基准估算（虚线，实际×0.85）对比，背景为室外温度</span>
        </div>
        <div ref="hvacEl" class="cpanel-body" style="height: 300px" />
      </div>
    </div>

    <div class="bento-row bento-r1">
      <div class="cpanel">
        <div class="cpanel-hd">
          <span class="cpanel-title">多楼栋能耗占比</span>
          <div class="compare-tabs">
            <button
              v-for="m in COMPARE_METRICS"
              :key="m.key"
              class="compare-tab"
              :class="{ active: compareMetric === m.key }"
              @click="switchCompare(m.key)"
            >
              {{ m.label }}
            </button>
          </div>
        </div>
        <div ref="compareEl" class="cpanel-body" style="height: 260px" />
      </div>
      <div class="cpanel">
        <div class="cpanel-hd">
          <span class="cpanel-title">建筑风险排行</span>
          <span class="cpanel-sub">按待处理告警条数统计</span>
        </div>
        <div ref="riskEl" class="cpanel-body" style="height: 280px" />
      </div>
    </div>

    <div class="bento-r3">
      <div
        class="cpanel"
        data-pick-id="chart-heatmap"
        data-pick-type="heatmap"
        data-pick-title="24h 能耗日历热力图"
        data-pick-subtitle="三栋楼合并的典型节律"
      >
        <div class="cpanel-hd">
          <span class="cpanel-title">24h 能耗日历热力图</span>
          <span class="cpanel-sub">近两周逐时负荷合成的 7×24 节律</span>
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
      <div class="cpanel-col">
        <div class="cpanel">
          <div class="cpanel-hd">
            <span class="cpanel-title">异常根因桑基图</span>
            <span class="cpanel-sub">规则流向根因类型</span>
          </div>
          <div ref="sankeyEl" class="cpanel-body" style="height: 230px" />
        </div>
        <div class="cpanel">
          <div class="cpanel-hd">
            <span class="cpanel-title">异常事件楼宇分布</span>
            <span class="cpanel-sub">近 7 天各楼宇待处理与已解决异常条数</span>
          </div>
          <div ref="anomalyEl" class="cpanel-body" style="height: 138px" />
        </div>
      </div>
      <HomeActionCards tab="all" :anomalies="anomalyData" />
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

/* 带切换按钮的 header 改为行布局 */
.home-all-section .cpanel-hd:has(.compare-tabs) {
  flex-direction: row;
  align-items: center;
  flex-wrap: wrap;
  gap: 6px;
}

.compare-tabs {
  display: flex;
  gap: 4px;
  margin-left: auto;
}

.compare-tab {
  padding: 2px 10px;
  border-radius: 12px;
  border: 1px solid rgba(120, 140, 160, 0.3);
  background: transparent;
  color: var(--color-text-secondary, #8a95a8);
  font-size: 11px;
  cursor: pointer;
  transition: all 0.18s ease;
  white-space: nowrap;
}

.compare-tab:hover {
  border-color: rgba(120, 180, 200, 0.5);
  color: var(--color-text-primary, #dde3f0);
}

.compare-tab.active {
  background: rgba(90, 160, 190, 0.18);
  border-color: rgba(90, 160, 190, 0.55);
  color: #7ec8e3;
  font-weight: 500;
}
</style>
