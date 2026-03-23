<script setup lang="ts">
import { ref, computed, watch, onMounted, onUnmounted, nextTick } from 'vue'
import * as echarts from 'echarts'
import { useBuildingStore } from '@/stores/buildingStore'
import { apiFetch } from '@/api/http'
import { MC, gc, EUI_BASELINE, buildHeatmapCells } from '@/utils/homeCharts'
import HomeActionCards from './HomeActionCards.vue'

const props = defineProps<{
  overviewData: any
  anomalyData: any[]
  sankeyData: {
    nodes: { name: string }[]
    links: { source: string; target: string; value: number }[]
  } | null
}>()

const buildingStore = useBuildingStore()

const bubbleEl = ref<HTMLElement | null>(null)
const hvacEl = ref<HTMLElement | null>(null)
const compareEl = ref<HTMLElement | null>(null)
const riskEl = ref<HTMLElement | null>(null)
const sankeyEl = ref<HTMLElement | null>(null)
const scatterEl = ref<HTMLElement | null>(null)

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

const _SANKEY_MOCK_NODES = [
  { name: '温差过大' },
  { name: '能耗超标' },
  { name: '设备离线' },
  { name: '过滤网堵塞' },
  { name: '传感器失效' },
  { name: '冷水机故障' },
  { name: '管道泄漏' },
]
const _SANKEY_MOCK_LINKS = [
  { source: '温差过大', target: '过滤网堵塞', value: 14 },
  { source: '温差过大', target: '冷水机故障', value: 8 },
  { source: '能耗超标', target: '过滤网堵塞', value: 11 },
  { source: '能耗超标', target: '传感器失效', value: 9 },
  { source: '能耗超标', target: '管道泄漏', value: 5 },
  { source: '设备离线', target: '传感器失效', value: 17 },
  { source: '设备离线', target: '冷水机故障', value: 7 },
]

function disposeAll() {
  instances.forEach((c) => c.dispose())
  instances = []
}

function renderBubble() {
  if (!bubbleEl.value) return
  const c = gc()
  const bldStore = buildingStore.buildings
  const ovData: any[] = props.overviewData?.buildings ?? []

  const items = bldStore.map((b) => {
    const ov = ovData.find((o) => o.building_type === b.building_type)
    const sqm = b.sqm ?? 10000
    const energy = ov?.total_electricity_kwh ?? 50
    const eui = energy / sqm
    const baseline = EUI_BASELINE[b.building_type] ?? 70
    const ratio = (eui * 365) / baseline
    return { sqm, eui, energy, name: b.display_name, type: b.building_type, baseline, ratio }
  })

  const sqmValues = items.map((i) => i.sqm)
  const maxSqm = sqmValues.length ? Math.max(...sqmValues) * 1.15 : 25000
  const ratioValues = items.map((i) => i.ratio)
  const maxRatio = ratioValues.length ? Math.max(...ratioValues, 1.3) * 1.15 : 2

  const deviationColor = (ratio: number) => {
    if (ratio >= 1.2)
      return { color: '#e05c5c', level: '严重超标', desc: '偏离基准 ≥20%，需紧急改造' }
    if (ratio >= 1.0)
      return { color: '#e8a64c', level: '轻度超标', desc: '偏离基准 0~20%，需关注优化' }
    if (ratio >= 0.8)
      return { color: '#7b9fc7', level: '达标', desc: '低于基准，运行正常' }
    return { color: '#5daa87', level: '优秀', desc: '远低于基准，节能表现优秀' }
  }

  const scatterData = items.map((i) => {
    const d = deviationColor(i.ratio)
    return {
      value: [
        i.sqm,
        parseFloat(i.ratio.toFixed(3)),
        parseFloat(i.energy.toFixed(1)),
        i.name,
        d.level,
        d.desc,
        parseFloat((i.eui * 365).toFixed(2)),
        i.baseline,
      ],
      itemStyle: { color: d.color, opacity: 0.85, borderColor: d.color, borderWidth: 1.5 },
    }
  })

  const inst = echarts.init(bubbleEl.value)
  inst.setOption({
    backgroundColor: 'transparent',
    grid: { top: 36, right: 20, bottom: 46, left: 56 },
    tooltip: {
      trigger: 'item',
      backgroundColor: c.ttBg,
      borderColor: c.ttBr,
      textStyle: { color: c.ttText, fontSize: 12 },
      formatter: (p: any) => {
        const d = p.data.value
        return (
          `<strong>${d[3]}</strong><br/>` +
          `状态: <span style="color:${p.data.itemStyle.color};font-weight:600">${d[4]}</span><br/>` +
          `${d[5]}<br/>` +
          `偏离比: ${d[1]}<br/>` +
          `年化 EUI: ${d[6]} kWh/㎡<br/>` +
          `国标基准: ${d[7]} kWh/㎡·年<br/>` +
          `建筑面积: ${Number(d[0]).toLocaleString()} ㎡`
        )
      },
    },
    legend: {
      top: 4,
      left: 'center',
      textStyle: { color: c.axis, fontSize: 10 },
      itemWidth: 8,
      itemHeight: 8,
      itemGap: 12,
      data: [
        { name: '严重超标', icon: 'circle', itemStyle: { color: '#e05c5c' } },
        { name: '轻度超标', icon: 'circle', itemStyle: { color: '#e8a64c' } },
        { name: '达标', icon: 'circle', itemStyle: { color: '#7b9fc7' } },
        { name: '优秀', icon: 'circle', itemStyle: { color: '#5daa87' } },
      ],
    },
    xAxis: {
      type: 'value',
      name: '建筑面积 (㎡)',
      nameLocation: 'middle',
      nameGap: 28,
      nameTextStyle: { color: c.axis, fontSize: 11 },
      axisLabel: { color: c.axis, fontSize: 10, formatter: (v: number) => `${(v / 1000).toFixed(0)}k` },
      splitLine: { lineStyle: { color: c.grid, type: 'dashed' } },
      max: maxSqm,
    },
    yAxis: {
      type: 'value',
      name: '偏离比（实际/基准）',
      nameLocation: 'middle',
      nameGap: 42,
      nameTextStyle: { color: c.axis, fontSize: 10 },
      axisLabel: { color: c.axis, fontSize: 10, formatter: (v: number) => v.toFixed(1) },
      splitLine: { lineStyle: { color: c.grid, type: 'dashed' } },
      max: maxRatio,
      min: 0,
    },
    series: [
      {
        type: 'scatter',
        data: [],
        markLine: {
          silent: true,
          symbol: 'none',
          lineStyle: { color: '#e05c5c', type: 'dashed', width: 1.5, opacity: 0.6 },
          label: { fontSize: 10, color: '#e05c5c', opacity: 0.8 },
          data: [{ yAxis: 1, label: { formatter: '国标基准线', position: 'insideEndTop' } }],
        },
      },
      {
        type: 'scatter',
        data: [],
        markArea: {
          silent: true,
          data: [
            [{ yAxis: 1, itemStyle: { color: 'rgba(224,92,92,0.04)' } }, { yAxis: maxRatio }],
            [{ yAxis: 0, itemStyle: { color: 'rgba(93,170,135,0.04)' } }, { yAxis: 1 }],
          ],
        },
      },
      {
        name: '严重超标',
        type: 'scatter',
        data: scatterData.filter((d) => d.value[4] === '严重超标'),
        symbolSize: (val: any[]) => Math.min(50, Math.max(20, Math.sqrt(val[2]) * 0.1)),
        label: {
          show: true,
          formatter: (p: any) => p.data.value[3],
          position: 'top',
          fontSize: 11,
          color: c.axis,
          distance: 6,
        },
      },
      {
        name: '轻度超标',
        type: 'scatter',
        data: scatterData.filter((d) => d.value[4] === '轻度超标'),
        symbolSize: (val: any[]) => Math.min(46, Math.max(18, Math.sqrt(val[2]) * 0.09)),
        label: {
          show: true,
          formatter: (p: any) => p.data.value[3],
          position: 'top',
          fontSize: 11,
          color: c.axis,
          distance: 6,
        },
      },
      {
        name: '达标',
        type: 'scatter',
        data: scatterData.filter((d) => d.value[4] === '达标'),
        symbolSize: (val: any[]) => Math.min(42, Math.max(16, Math.sqrt(val[2]) * 0.08)),
        label: {
          show: true,
          formatter: (p: any) => p.data.value[3],
          position: 'top',
          fontSize: 11,
          color: c.axis,
          distance: 6,
        },
      },
      {
        name: '优秀',
        type: 'scatter',
        data: scatterData.filter((d) => d.value[4] === '优秀'),
        symbolSize: (val: any[]) => Math.min(38, Math.max(14, Math.sqrt(val[2]) * 0.07)),
        label: {
          show: true,
          formatter: (p: any) => p.data.value[3],
          position: 'top',
          fontSize: 11,
          color: c.axis,
          distance: 6,
        },
      },
    ],
  })
  instances.push(inst)
}

function renderHvac() {
  if (!hvacEl.value) return
  const c = gc()
  const hours = Array.from({ length: 24 }, (_, i) => `${i}:00`)
  const outdoorTemp = [18, 17, 16, 16, 17, 18, 20, 22, 24, 26, 27, 28, 28, 27, 26, 25, 24, 23, 22, 21, 20, 20, 19, 18]
  const actualHvac = [120, 115, 110, 108, 112, 118, 136, 156, 186, 216, 234, 248, 251, 241, 224, 207, 191, 174, 160, 145, 133, 127, 123, 120]
  const simOptHvac = [108, 104, 99, 97, 101, 107, 116, 131, 157, 176, 190, 200, 206, 196, 183, 168, 153, 139, 128, 117, 111, 108, 107, 107]

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
        name: '仿真最优能耗',
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

function renderCompare() {
  if (!compareEl.value) return
  const c = gc()
  const blds: any[] = props.overviewData?.buildings ?? []
  const names = blds.map((b) => b.display_name || b.building_type)
  const elec = blds.map((b) => Number(b.total_electricity_kwh ?? 0))
  const water = blds.map((b) => Number(b.total_water_m3 ?? 0))
  const hac = blds.map((b) => Number(b.total_hac_energy_kwh ?? 0))

  const inst = echarts.init(compareEl.value)
  inst.setOption({
    backgroundColor: 'transparent',
    grid: { top: 36, right: 16, bottom: 36, left: 48 },
    tooltip: { trigger: 'axis', backgroundColor: c.ttBg, borderColor: c.ttBr, textStyle: { color: c.ttText } },
    legend: { top: 4, textStyle: { color: c.axis, fontSize: 10 } },
    xAxis: {
      type: 'category',
      data: names,
      axisLabel: { color: c.axis, fontSize: 10 },
      axisLine: { lineStyle: { color: c.grid } },
    },
    yAxis: {
      type: 'value',
      name: '当日量',
      nameTextStyle: { color: c.axis, fontSize: 10 },
      axisLabel: { color: c.axis, fontSize: 10 },
      splitLine: { lineStyle: { color: c.grid, type: 'dashed' } },
    },
    series: [
      { name: '用电 kWh', type: 'bar', data: elec, itemStyle: { color: MC.sage } },
      { name: '用水 m³', type: 'bar', data: water, itemStyle: { color: MC.blue } },
      { name: '暖通 kWh', type: 'bar', data: hac, itemStyle: { color: MC.lav } },
    ],
  })
  instances.push(inst)
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
        itemStyle: {
          color: (p: any) => [MC.blue, MC.terra, MC.teal][p.dataIndex] ?? MC.lav,
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
  const useApi = sd && sd.nodes.length > 0 && sd.links.length > 0
  const sourceNames = new Set((useApi ? sd!.links : _SANKEY_MOCK_LINKS).map((l) => l.source))
  const rawNodes = useApi ? sd!.nodes : _SANKEY_MOCK_NODES
  const nodes = rawNodes.map((n) => ({
    name: n.name,
    itemStyle: {
      color: sourceNames.has(n.name)
        ? _SANKEY_SOURCE_COLORS[n.name] ?? MC.blue
        : _SANKEY_TARGET_COLORS[n.name] ?? MC.lav,
    },
  }))
  const links = useApi ? sd!.links : _SANKEY_MOCK_LINKS

  const inst = echarts.init(sankeyEl.value)
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
        links,
        lineStyle: { color: 'gradient', opacity: 0.42 },
        label: { color: c.axis, fontSize: 11 },
      },
    ],
  })
  instances.push(inst)
}

function renderScatter() {
  if (!scatterEl.value) return
  const c = gc()
  const resolved: [number, number][] = []
  const unresolved: [number, number][] = []
  if (props.anomalyData.length > 0) {
    props.anomalyData.slice(0, 30).forEach((a: any, i: number) => {
      const dev = Number(a.deviation_pct ?? 5 + Math.random() * 40)
      if (a.anomaly_status === 'Anomaly' || a.operation_status === 'Anomaly')
        unresolved.push([i, parseFloat(dev.toFixed(1))])
      else resolved.push([i, parseFloat(dev.toFixed(1))])
    })
  } else {
    for (let i = 0; i < 28; i++) {
      const dev = 5 + Math.random() * 45
      if (dev > 22 && Math.random() > 0.44) unresolved.push([i, parseFloat(dev.toFixed(1))])
      else resolved.push([i, parseFloat(dev.toFixed(1))])
    }
  }

  const inst = echarts.init(scatterEl.value)
  inst.setOption({
    backgroundColor: 'transparent',
    grid: { top: 12, right: 14, bottom: 28, left: 44 },
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'cross' },
      backgroundColor: c.ttBg,
      borderColor: c.ttBr,
      textStyle: { color: c.ttText, fontSize: 11 },
    },
    legend: { top: 2, textStyle: { color: c.axis, fontSize: 10 }, itemWidth: 10, itemHeight: 10 },
    xAxis: {
      type: 'value',
      name: '事件编号',
      nameTextStyle: { color: c.axis, fontSize: 10 },
      axisLabel: { color: c.axis, fontSize: 10 },
      splitLine: { lineStyle: { color: c.grid, type: 'dashed' } },
    },
    yAxis: {
      type: 'value',
      name: '偏离度 %',
      nameTextStyle: { color: c.axis, fontSize: 10 },
      axisLabel: { color: c.axis, fontSize: 10 },
      splitLine: { lineStyle: { color: c.grid, type: 'dashed' } },
    },
    series: [
      {
        name: '已解决',
        type: 'scatter',
        data: resolved,
        symbolSize: 8,
        itemStyle: { color: MC.sage, opacity: 0.85 },
      },
      {
        name: '待处理',
        type: 'scatter',
        data: unresolved,
        symbolSize: 10,
        itemStyle: { color: MC.terra, opacity: 0.9 },
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
    const cells = buildHeatmapCells(
      Array.from({ length: 24 }, (_, hour) => ({ hour, avg_value: 40 + (hour % 12) * 3 })),
      Array.from({ length: 7 }, (_, i) => ({ weekday: i + 1, avg_value: i < 5 ? 80 : 35 })),
    )
    ghData.value = cells
    ghMaxVal.value = Math.max(...cells.map((c) => c.v), 1)
  }
}

function renderAll() {
  disposeAll()
  renderBubble()
  renderHvac()
  renderCompare()
  renderRisk()
  renderSankey()
  renderScatter()
  nextTick(() => instances.forEach((i) => i.resize()))
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
  await loadMergedHeatmap()
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
        data-pick-id="chart-eui-bubble"
        data-pick-type="chart"
        data-pick-title="建筑能耗定额偏离分析"
        data-pick-subtitle="偏离比 = 实际EUI / 国标基准值"
      >
        <div class="cpanel-hd">
          <span class="cpanel-title">建筑能耗定额偏离分析</span>
          <span class="cpanel-sub">偏离比 = 实际EUI / 国标基准值，气泡大小反映总用电量</span>
        </div>
        <div ref="bubbleEl" class="cpanel-body" style="height: 300px" />
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
          <span class="cpanel-sub">实际暖通能耗与仿真最优值对比，背景为室外温度</span>
        </div>
        <div ref="hvacEl" class="cpanel-body" style="height: 300px" />
      </div>
    </div>

    <div class="bento-row bento-r1">
      <div class="cpanel">
        <div class="cpanel-hd">
          <span class="cpanel-title">多楼栋横向对比</span>
          <span class="cpanel-sub">当日用电 / 用水 / 暖通分项对比</span>
        </div>
        <div ref="compareEl" class="cpanel-body" style="height: 280px" />
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
          <div ref="sankeyEl" class="cpanel-body" style="height: 172px" />
        </div>
        <div class="cpanel">
          <div class="cpanel-hd">
            <span class="cpanel-title">健康偏离度散点</span>
            <span class="cpanel-sub">事件偏离程度分布</span>
          </div>
          <div ref="scatterEl" class="cpanel-body" style="height: 138px" />
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
</style>
