<script setup lang="ts">
import { ref, watch, onMounted, onUnmounted, nextTick } from 'vue'
import * as echarts from 'echarts'
import { MC, gc } from '@/utils/homeCharts'
import { useReportExport } from '@/composables/useReportExport'

const props = defineProps<{
  sankeyData: {
    nodes: { name: string }[]
    links: { source: string | number; target: string | number; value: number }[]
  } | null
}>()

const { captureChart } = useReportExport('home-chart-sankey')

const sankeyEl = ref<HTMLElement | null>(null)

let chart: echarts.ECharts | null = null
let ro: ResizeObserver | null = null
let captureTimer: number | null = null

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

function ensureChart() {
  if (!sankeyEl.value) return null
  const existing = echarts.getInstanceByDom(sankeyEl.value)
  if (existing) {
    chart = existing
    return chart
  }
  if (chart) {
    chart.dispose()
  }
  chart = echarts.init(sankeyEl.value)
  return chart
}

function scheduleCapture() {
  if (captureTimer != null) {
    window.clearTimeout(captureTimer)
  }
  captureTimer = window.setTimeout(() => {
    captureTimer = null
    captureChart(chart, 'home-chart-sankey', '异常根因桑基图', 30)
  }, 300)
}

function renderSankeyChart() {
  const inst = ensureChart()
  if (!inst) return

  const c = gc()
  const sd = props.sankeyData
  const hasData = !!sd && sd.nodes.length > 0 && sd.links.length > 0

  if (!hasData) {
    inst.setOption(
      {
        backgroundColor: 'transparent',
        title: {
          text: '暂无根因数据',
          left: 'center',
          top: 'middle',
          textStyle: { color: c.axis, fontSize: 12 },
        },
        series: [],
      },
      { notMerge: true },
    )
    inst.resize()
    scheduleCapture()
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

  inst.setOption(
    {
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
    },
    { notMerge: true },
  )

  inst.resize()
  scheduleCapture()
}

function handleResize() {
  chart?.resize()
}

function disposeChart() {
  if (captureTimer != null) {
    window.clearTimeout(captureTimer)
    captureTimer = null
  }
  chart?.dispose()
  chart = null
}

watch(
  () => props.sankeyData,
  async () => {
    await nextTick()
    renderSankeyChart()
  },
  { deep: true },
)

onMounted(async () => {
  await nextTick()
  renderSankeyChart()
  window.addEventListener('resize', handleResize)
  if (sankeyEl.value && typeof ResizeObserver !== 'undefined') {
    ro = new ResizeObserver(() => chart?.resize())
    ro.observe(sankeyEl.value)
  }
})

onUnmounted(() => {
  disposeChart()
  window.removeEventListener('resize', handleResize)
  ro?.disconnect()
  ro = null
})
</script>

<template>
  <div class="cpanel panel-sankey">
    <div class="cpanel-hd">
      <span class="cpanel-title">异常根因桑基图</span>
      <span class="cpanel-sub">规则流向根因类型</span>
    </div>
    <div ref="sankeyEl" class="cpanel-body" style="height: 300px" />
  </div>
</template>
