<script setup lang="ts">
import { ref, computed, watch, onMounted, onUnmounted, nextTick } from 'vue'
import * as echarts from '@/utils/echarts'
import { useBuildingStore } from '@/stores/buildingStore'
import { apiFetch } from '@/api/http'
import { MC, gc, EUI_BASELINE, HOME_BUILDING_COLORS } from '@/utils/homeCharts'
import HomeActionCards from './HomeActionCards.vue'
import { useReportExport } from '@/composables/useReportExport'

const props = defineProps<{
  overviewData: any
  anomalyData: any[]
  sankeyData: {
    nodes: { name: string }[]
    links: { source: string | number; target: string | number; value: number }[]
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

const _SANKEY_RULE_LABELS: Record<string, string> = {
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

const _SANKEY_ROOT_CAUSE_LABELS: Record<string, string> = {
  A_low_efficiency: '主机效能衰退',
  B_small_deltaT: '水力失调',
  C_unexpected_on: '非预期开机',
  other_hvac: '其他空调故障',
}

const _SANKEY_SOURCE_COLORS: Record<string, string> = {
  水耗异常: MC.teal,
  水耗偏高: MC.teal,
  电耗超标: MC.blue,
  总电耗偏高: MC.blue,
  空调过耗: MC.terra,
  空调能耗偏高: MC.terra,
  供水温度偏离: MC.rose,
  回水温度偏离: MC.lav,
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
  '供水温度偏离(直接)': MC.rose,
  '回水温度偏离(直接)': MC.lav,
  '水耗异常(直接)': MC.teal,
  '电耗超标(直接)': MC.blue,
  '空调过耗(直接)': MC.terra,
  '水耗偏高(直接)': MC.teal,
  '总电耗偏高(直接)': MC.blue,
  '空调能耗偏高(直接)': MC.terra,
}

function translateSankeyBaseLabel(name: string): string {
  return _SANKEY_RULE_LABELS[name] ?? _SANKEY_ROOT_CAUSE_LABELS[name] ?? name
}

function normalizeSankeyLabel(name: string): string {
  const directMatch = name.match(/^(.*)\((?:直接|direct)\)$/i)
  if (directMatch) {
    return `${translateSankeyBaseLabel(directMatch[1])}(直接)`
  }
  return translateSankeyBaseLabel(name)
}

function normalizeSankeyLinkEnd(
  value: string | number,
  nodes: Array<{ name: string }>,
): string {
  if (typeof value === 'number') {
    return normalizeSankeyLabel(nodes[value]?.name ?? String(value))
  }
  return normalizeSankeyLabel(value)
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
      bottom: 0,
      left: 'center',
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
      center: ['50%', '47%'],
      radius: '70%',
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
    color: [MC.terra, MC.blue, MC.sage],
    grid: { top: 52, left: '3%', right: '3%', bottom: '8%', containLabel: true },
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
        splitLine: { lineStyle: { color: '#f0f0f0', type: 'dashed' } },
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
        lineStyle: { color: MC.terra, width: 0 },
        itemStyle: { color: MC.terra },
        areaStyle: {
          color: {
            type: 'linear',
            x: 0,
            y: 0,
            x2: 0,
            y2: 1,
            colorStops: [
              { offset: 0, color: 'rgba(245, 158, 11, 0.24)' },
              { offset: 1, color: 'rgba(245, 158, 11, 0.03)' },
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
      colors: [],
    } as any,
    water: {
      field: 'total_water_m3',
      unit: 'm³',
      colors: [],
    } as any,
    hac: {
      field: 'total_hac_energy_kwh',
      unit: 'kWh',
      colors: [],
    } as any,
  }

  const cfg = metricMap[compareMetric.value] as any
  const pieData = blds
    .map((b) => ({
      buildingType: b.building_type,
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
      bottom: 8,
      left: 'center',
      textStyle: { color: c.axis, fontSize: 11 },
      itemWidth: 10,
      itemHeight: 10,
    },
    series: [
      {
        name: labelMap[compareMetric.value],
        type: 'pie',
        radius: ['46%', '66%'],
        center: ['50%', '48%'],
        avoidLabelOverlap: true,
        label: { show: false },
        labelLine: { show: false },
        data: pieData.map((d) => ({
          ...d,
          itemStyle: {
            color: HOME_BUILDING_COLORS[(d.buildingType ?? 'Education') as keyof typeof HOME_BUILDING_COLORS] ?? MC.blue,
          },
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

  const normalizedLinks = sd!.links.map((link) => ({
    source: normalizeSankeyLinkEnd(link.source, sd!.nodes),
    target: normalizeSankeyLinkEnd(link.target, sd!.nodes),
    value: link.value,
  }))
  const sourceNames = new Set(normalizedLinks.map((l) => l.source))
  const sourceNameList = Array.from(sourceNames)
  const targetNameList = Array.from(new Set(normalizedLinks.map((l) => l.target)))
  const sourcePalette = [MC.terra, '#14b8a6', MC.blue, '#2563eb', '#d97706', MC.rose, '#8b5cf6', '#ec4899', '#ef4444']
  const targetPalette = [MC.blue, MC.rose, MC.sage, MC.teal, MC.terra, '#8b5cf6', '#6366f1', '#ef4444', '#f97316', '#06b6d4', '#1d4ed8', '#22c55e', '#0ea5e9', '#3b82f6', '#f59e0b']
  const sourceColorMap = Object.fromEntries(sourceNameList.map((name, index) => [name, sourcePalette[index % sourcePalette.length]]))
  const targetColorMap = Object.fromEntries(targetNameList.map((name, index) => [name, targetPalette[index % targetPalette.length]]))
  const nodeNames = Array.from(
    new Set([
      ...sd!.nodes.map((n) => normalizeSankeyLabel(n.name)),
      ...normalizedLinks.flatMap((l) => [l.source, l.target]),
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

function renderAll() {
  disposeAll()
  renderRadar()
  renderHvac()
  renderPie()
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
  if (radarEl.value) {
    const inst = echarts.getInstanceByDom(radarEl.value)
    captureChart(inst, 'home-chart-radar', '楼宇多维能耗对比', 30)
  }
  if (hvacEl.value) {
    const inst = echarts.getInstanceByDom(hvacEl.value)
    captureChart(inst, 'home-chart-hvac', 'HVAC 虚实映射分析', 35)
  }
  if (compareEl.value) {
    const inst = echarts.getInstanceByDom(compareEl.value)
    captureChart(inst, 'home-chart-compare', '多楼栋能耗占比', 40)
  }
  if (sankeyEl.value) {
    const inst = echarts.getInstanceByDom(sankeyEl.value)
    captureChart(inst, 'home-chart-sankey', '异常根因桑基图', 45)
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
  await loadHvacData()
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
    <div class="bento-row bento-r2">
      <div
        class="cpanel panel-radar"
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
        class="cpanel panel-hvac"
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
      <div class="cpanel panel-compare">
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
        <div ref="compareEl" class="cpanel-body" style="height: 280px" />
      </div>
      <div class="cpanel panel-risk">
        <div class="cpanel-hd">
          <span class="cpanel-title">建筑风险排行</span>
          <span class="cpanel-sub">按待处理告警条数统计</span>
        </div>
        <div ref="riskEl" class="cpanel-body" style="height: 248px" />
      </div>
    </div>

    <div class="bento-r3">
      <div class="cpanel-col">
        <div class="cpanel panel-sankey">
          <div class="cpanel-hd">
            <span class="cpanel-title">异常根因桑基图</span>
            <span class="cpanel-sub">规则流向根因类型</span>
          </div>
          <div ref="sankeyEl" class="cpanel-body" style="height: 300px" />
        </div>
        <div class="cpanel panel-anomaly">
          <div class="cpanel-hd">
            <span class="cpanel-title">异常事件楼宇分布</span>
            <span class="cpanel-sub">近 7 天各楼宇待处理与已解决异常条数</span>
          </div>
          <div ref="anomalyEl" class="cpanel-body" style="height: 240px" />
        </div>
      </div>
      <HomeActionCards class="home-actions-panel" tab="all" :anomalies="anomalyData" />
    </div>
  </div>
</template>

<style>
/* 带切换按钮的 header 改为行布局 */
.home-all-section .cpanel-hd:has(.compare-tabs) {
  flex-direction: row;
  align-items: center;
  flex-wrap: wrap;
  justify-content: space-between;
  gap: 10px;
}

.compare-tabs {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  margin-left: auto;
  padding: 4px;
  border: 1px solid rgba(120, 140, 160, 0.18);
  border-radius: 999px;
  background: rgba(15, 23, 42, 0.05);
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.08);
}

.compare-tab {
  min-width: 68px;
  padding: 5px 12px;
  border-radius: 999px;
  border: 0;
  background: transparent;
  color: var(--text-muted, #8a95a8);
  font-size: 11px;
  font-weight: 600;
  cursor: pointer;
  transition: background-color 0.18s ease, color 0.18s ease, box-shadow 0.18s ease,
    transform 0.18s ease;
  white-space: nowrap;
}

.compare-tab:hover {
  background: rgba(148, 163, 184, 0.18);
  color: var(--text-primary, #dde3f0);
}

.compare-tab.active {
  background: rgba(20, 184, 166, 0.16);
  color: #0f766e;
  box-shadow: inset 0 0 0 1px rgba(15, 118, 110, 0.22), 0 4px 10px rgba(15, 118, 110, 0.12);
  transform: none;
}

html[data-theme='light'] .compare-tabs {
  background: #f4f7f5;
  border-color: #e2e8e4;
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.9);
}

html[data-theme='light'] .compare-tab {
  color: #64748b;
}

html[data-theme='light'] .compare-tab:hover {
  background: rgba(148, 163, 184, 0.14);
  color: #111827;
}

html[data-theme='light'] .compare-tab.active {
  background: rgba(20, 184, 166, 0.14);
  color: #0f766e;
  box-shadow: inset 0 0 0 1px rgba(15, 118, 110, 0.18), 0 4px 8px rgba(15, 118, 110, 0.08);
}
</style>
