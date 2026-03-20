<template>
  <div class="home-page">

    <!-- ── Page Header ─────────────────────────────────────── -->
    <header class="pg-header">
      <div class="pg-greeting">
        <h1 class="pg-title">你好，{{ displayName }}！<DotLottieVue class="pg-wave-lottie" src="/Hello%20World.json" autoplay loop /></h1>
        <p class="pg-sub">今天有什么可以为你效劳的？</p>
      </div>
      <!-- 建筑切换胶囊 -->
      <div class="capsule-switcher" ref="capsuleRef">
        <div class="capsule-slider" :style="sliderStyle"></div>
        <button
          v-for="opt in buildingOptions"
          :key="opt.key"
          :ref="(el) => setBtnRef(el, opt.key)"
          class="capsule-btn"
          :class="{ active: activeBuilding === opt.key }"
          @click="activeBuilding = opt.key"
        >{{ opt.label }}</button>
      </div>
      <div class="weather-widget"
           data-pick-id="weather"
           data-pick-type="weather"
           data-pick-title="天气信息"
           :data-pick-subtitle="`温度 ${weatherTemp != null ? Number(weatherTemp).toFixed(1) + '°C' : '--'}，湿度 ${weatherHumi ?? '--'}%`">
        <div class="weather-date">
          <Icon icon="mdi:calendar-month" width="14" />
          <span>{{ dataDate || '加载中...' }}</span>
        </div>
        <div class="weather-divider"></div>
        <div class="weather-metrics">
          <div class="weather-item">
            <Icon icon="mdi:thermometer" width="15" class="weather-icon temp-icon" />
            <span class="weather-val">{{ weatherTemp != null ? Number(weatherTemp).toFixed(1) : '--' }}<small>°C</small></span>
          </div>
          <div class="weather-item">
            <Icon icon="mdi:water-percent" width="15" class="weather-icon humi-icon" />
            <span class="weather-val">{{ weatherHumi ?? '--' }}<small>%</small></span>
          </div>
        </div>
      </div>
    </header>

    <!-- ── KPI Strip (5 cards) ─────────────────────────────── -->
    <section class="kpi-strip">
      <div v-for="k in kpis" :key="k.label" class="kpi-card"
           :data-pick-id="'kpi-' + k.label"
           data-pick-type="kpi"
           :data-pick-title="k.label"
           :data-pick-subtitle="String(k.value)">
        <div class="kpi-ico" :style="{ background: k.bg, color: k.color }">
          <Icon :icon="k.icon" width="20" />
        </div>
        <div class="kpi-body">
          <span class="kpi-val">{{ k.value }}</span>
          <span class="kpi-lbl">{{ k.label }}</span>
        </div>
        <span class="kpi-tag" :style="{ color: k.color, background: k.bg }">{{ k.tag }}</span>
      </div>
    </section>

    <!-- ── Bento Row 1: EUI Bubble Matrix + HVAC Multi-axis ── -->
    <div class="bento-row bento-r1" v-show="activeBuilding === 'all'">
      <div class="cpanel"
           data-pick-id="chart-eui-bubble"
           data-pick-type="chart"
           data-pick-title="建筑能耗强度热力象限图"
           data-pick-subtitle="按 EUI 与面积划分优先级象限，红色=紧急改造，绿色=运行良好">
        <div class="cpanel-hd">
          <span class="cpanel-title">建筑能耗强度热力象限图</span>
          <span class="cpanel-sub">按 EUI 与面积划分优先级象限，红色=紧急改造，绿色=运行良好</span>
        </div>
        <div ref="bubbleEl" class="cpanel-body" style="height:252px;"></div>
      </div>
      <div class="cpanel"
           data-pick-id="chart-hvac"
           data-pick-type="chart"
           data-pick-title="HVAC 虚实映射分析"
           data-pick-subtitle="实际暖通能耗与仿真最优值对比，背景灰带为室外温度">
        <div class="cpanel-hd">
          <span class="cpanel-title">HVAC 虚实映射分析</span>
          <span class="cpanel-sub">实际暖通能耗与仿真最优值对比，背景灰带为室外温度</span>
        </div>
        <div ref="hvacEl" class="cpanel-body" style="height:252px;"></div>
      </div>
    </div>

    <!-- ── Bento Row 2: Heatmap + Sankey / Scatter ─────────── -->
    <div class="bento-row bento-r2">
      <div class="cpanel"
           data-pick-id="chart-heatmap"
           data-pick-type="heatmap"
           data-pick-title="24h 能耗日历热力图"
           data-pick-subtitle="近 7 日逐时能耗分布，追踪非工作时段隐性浪费">
        <div class="cpanel-hd">
          <span class="cpanel-title">24h 能耗日历热力图</span>
          <span class="cpanel-sub">近 7 日逐时能耗分布，追踪非工作时段隐性浪费</span>
        </div>
        <!-- GitHub-style heatmap: pure CSS Grid, aspect-ratio:1 guarantees perfect squares -->
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
                @mouseenter="e => showGhTip(e, cell)"
                @mouseleave="hideGhTip"
              ></div>
            </div>
          </div>
          <div class="gh-x-row">
            <div class="gh-y-spacer"></div>
            <div class="gh-x-labels">
              <span v-for="h in 24" :key="h" class="gh-x-label">
                {{ [0,4,8,12,16,20].includes(h-1) ? `${h-1}h` : '' }}
              </span>
            </div>
          </div>
          <div class="gh-legend">
            <span class="gh-legend-text">低能耗</span>
            <div v-for="c in ghLegendColors" :key="c" class="gh-legend-cell" :style="{ background: c }"></div>
            <span class="gh-legend-text">高能耗</span>
          </div>
        </div>
      </div>
      <div class="cpanel-col">
        <div class="cpanel"
             data-pick-id="chart-sankey"
             data-pick-type="chart"
             data-pick-title="异常根因桑基图"
             data-pick-subtitle="触发规则流向根因类型，流量粗细表示事件频次">
          <div class="cpanel-hd">
            <span class="cpanel-title">异常根因桑基图</span>
            <span class="cpanel-sub">触发规则流向根因类型，流量粗细表示事件频次</span>
          </div>
          <div ref="sankeyEl" class="cpanel-body" style="height:172px;"></div>
        </div>
        <div class="cpanel"
             data-pick-id="chart-scatter"
             data-pick-type="chart"
             data-pick-title="健康偏离度散点"
             data-pick-subtitle="各事件指标偏离程度，颜色区分已解决与待处理">
          <div class="cpanel-hd">
            <span class="cpanel-title">健康偏离度散点</span>
            <span class="cpanel-sub">各事件指标偏离程度，颜色区分已解决与待处理</span>
          </div>
          <div ref="scatterEl" class="cpanel-body" style="height:138px;"></div>
        </div>
      </div>
    </div>

    <!-- Heatmap tooltip (Teleport so it's not clipped by overflow:hidden panels) -->
    <Teleport to="body">
      <div v-if="ghTip.show" class="gh-tooltip" :style="{ left: ghTip.x + 'px', top: ghTip.y + 'px' }">
        {{ ghTip.text }}
      </div>
    </Teleport>

  </div>
</template>

<script setup lang="ts">
import { ref, computed, watch, onMounted, onUnmounted, nextTick } from 'vue'
import { Icon } from '@iconify/vue'
import { DotLottieVue } from '@lottiefiles/dotlottie-vue'
import * as echarts from 'echarts'
import { apiFetch } from '@/api/http'
import { useBuildingStore } from '@/stores/buildingStore'
import { useAuthStore } from '@/stores/authStore'

const buildingStore = useBuildingStore()
const authStore     = useAuthStore()

// 优先显示用户名，未登录时兜底
const displayName = computed(() => authStore.user?.username ?? '访客')

const dataDate = ref('')
const weatherTemp = ref<number | null>(null)
const weatherHumi = ref<number | null>(null)
const overviewData = ref<any>(null)
const anomalyData = ref<any[]>([])

// ── 建筑切换胶囊 ─────────────────────────────────────────────
const buildingOptions = [
  { key: 'all', label: '全部' },
  { key: 'Education', label: '教学楼' },
  { key: 'Office', label: '办公楼' },
  { key: 'Public services', label: '公共楼' },
]
const activeBuilding = ref('all')
const capsuleRef = ref<HTMLElement | null>(null)
const btnRefs = new Map<string, HTMLElement>()

function setBtnRef(el: any, key: string) {
  if (el) btnRefs.set(key, el as HTMLElement)
}

const sliderStyle = computed(() => {
  const el = btnRefs.get(activeBuilding.value)
  if (!el || !capsuleRef.value) return { opacity: '0' }
  const parentRect = capsuleRef.value.getBoundingClientRect()
  const btnRect = el.getBoundingClientRect()
  return {
    width: `${btnRect.width}px`,
    transform: `translateX(${btnRect.left - parentRect.left}px)`,
    opacity: '1',
  }
})

// 强制刷新 slider 位置
const forceSliderUpdate = ref(0)
watch(activeBuilding, () => { nextTick(() => { forceSliderUpdate.value++ }) })

const bubbleEl  = ref<HTMLElement | null>(null)
const hvacEl    = ref<HTMLElement | null>(null)
const sankeyEl  = ref<HTMLElement | null>(null)
const scatterEl = ref<HTMLElement | null>(null)

let instances: echarts.ECharts[] = []

// ── Morandi palette ──────────────────────────────────────────
const MC = {
  blue:  '#7b9fc7',
  sage:  '#7aaa8e',
  terra: '#c4956a',
  lav:   '#9b8fc4',
  rose:  '#c4909a',
  teal:  '#7abcb3',
}

// Chart color adapts to light / dark theme
function gc() {
  const dark = document.documentElement.dataset.theme !== 'light'
  return {
    grid:   dark ? '#1a1c28' : '#d0e8d8',
    axis:   dark ? '#6b7a9a' : '#6a8c72',
    ttBg:   dark ? '#101118' : '#ffffff',
    ttBr:   dark ? '#1a1c28' : '#d0e8d8',
    ttText: dark ? '#dde3f0' : '#0f2818',
    dark,
  }
}

// ── KPI data ─────────────────────────────────────────────────
const CARBON_FACTOR = 0.5703 // kgCO₂/kWh
const kpis = computed(() => {
  // eslint-disable-next-line no-unused-vars
  void forceSliderUpdate.value // 触发依赖刷新
  const ov = overviewData.value
  if (!ov) return []
  const sel = activeBuilding.value
  const buildings: any[] = ov.buildings ?? []

  let elec = 0, water = 0, hac = 0
  if (sel === 'all') {
    elec  = Number(ov.kpis?.total_electricity_kwh ?? 0)
    water = Number(ov.kpis?.total_water_m3 ?? 0)
    hac   = Number(ov.kpis?.total_hac_energy_kwh ?? 0)
  } else {
    const b = buildings.find((b: any) => b.building_type === sel)
    elec  = b ? Number(b.total_electricity_kwh ?? 0) : 0
    water = b ? Number(b.total_water_m3 ?? 0) : 0
    hac   = b ? Number(b.total_hac_energy_kwh ?? 0) : 0
  }
  const carbon = elec * CARBON_FACTOR

  return [
    {
      icon: 'mdi:lightning-bolt', label: '日总用电 (kWh)',
      value: elec.toFixed(1),
      tag: '今日', bg: 'rgba(123,159,199,0.14)', color: MC.blue,
    },
    {
      icon: 'mdi:water', label: '日总用水 (m³)',
      value: water.toFixed(1),
      tag: '今日', bg: 'rgba(122,170,142,0.14)', color: MC.sage,
    },
    {
      icon: 'mdi:air-conditioner', label: '空调能耗 (kWh)',
      value: hac.toFixed(1),
      tag: '今日', bg: 'rgba(155,143,196,0.14)', color: MC.lav,
    },
    {
      icon: 'mdi:molecule-co2', label: '碳排放量 (kg)',
      value: carbon.toFixed(1),
      tag: 'CO₂', bg: 'rgba(196,149,106,0.14)', color: MC.terra,
    },
  ]
})

// ── Data fetching ────────────────────────────────────────────
async function fetchOverview() {
  try {
    const data = await apiFetch<any>('/api/overview')
    overviewData.value = data
    dataDate.value = data?.data_date ?? ''
    weatherTemp.value = data?.weather?.temperature ?? null
    weatherHumi.value = data?.weather?.humidity ?? null
  } catch { /* silent */ }
}

async function fetchAnomalies() {
  try {
    const data = await apiFetch<any>('/api/anomalies/recent?hours=168')
    anomalyData.value = data?.anomalies ?? []
  } catch { /* silent */ }
}

// ── 1. EUI Bubble Matrix (热力象限图) ────────────────────────
function renderBubble() {
  if (!bubbleEl.value) return
  const c = gc()
  const bldStore = buildingStore.buildings
  const ovData: any[] = overviewData.value?.buildings ?? []

  // 构建数据: [sqm, eui, energy, name, building_type]
  const items = bldStore.map(b => {
    const ov = ovData.find(o => o.building_type === b.building_type)
    const sqm = b.sqm ?? 10000
    const energy = ov?.total_electricity_kwh ?? (50 + Math.random() * 200)
    const eui = energy / sqm
    return { sqm, eui, energy, name: b.display_name, type: b.building_type }
  })

  // 计算 EUI 均值作为象限分界线
  const avgEui = items.length ? items.reduce((s, i) => s + i.eui, 0) / items.length : 0.2
  const avgSqm = items.length ? items.reduce((s, i) => s + i.sqm, 0) / items.length : 10000
  const maxEui = Math.max(...items.map(i => i.eui)) * 1.15
  const maxSqm = Math.max(...items.map(i => i.sqm)) * 1.15

  // 按优先级着色: 高EUI+大面积=红(P0), 高EUI+小面积=橙(P1), 低EUI+大面积=蓝(P2), 低EUI+小面积=绿(P3)
  const priorityColor = (eui: number, sqm: number) => {
    if (eui >= avgEui && sqm >= avgSqm) return { color: '#e05c5c', level: 'P0 紧急', desc: '高能耗+大面积，首要改造' }
    if (eui >= avgEui && sqm < avgSqm)  return { color: '#e8a64c', level: 'P1 重要', desc: '高能耗，需关注' }
    if (eui < avgEui && sqm >= avgSqm)  return { color: '#7b9fc7', level: 'P2 观察', desc: '面积大但效率尚可' }
    return { color: '#5daa87', level: 'P3 良好', desc: '运行效率良好' }
  }

  const scatterData = items.map(i => {
    const p = priorityColor(i.eui, i.sqm)
    return {
      value: [i.sqm, parseFloat(i.eui.toFixed(5)), parseFloat(i.energy.toFixed(1)), i.name, p.level, p.desc],
      itemStyle: { color: p.color, opacity: 0.85, borderColor: p.color, borderWidth: 1.5 },
    }
  })

  const inst = echarts.init(bubbleEl.value)
  inst.setOption({
    backgroundColor: 'transparent',
    grid: { top: 20, right: 24, bottom: 46, left: 64 },
    tooltip: {
      trigger: 'item',
      backgroundColor: c.ttBg, borderColor: c.ttBr,
      textStyle: { color: c.ttText, fontSize: 12 },
      formatter: (p: any) => {
        const d = p.data.value
        return `<strong>${d[3]}</strong><br/>` +
          `优先级: <span style="color:${p.data.itemStyle.color};font-weight:600">${d[4]}</span><br/>` +
          `${d[5]}<br/>` +
          `建筑面积: ${Number(d[0]).toLocaleString()} ㎡<br/>` +
          `EUI: ${Number(d[1]).toFixed(5)} kWh/㎡<br/>` +
          `总用电: ${d[2]} kWh`
      },
    },
    legend: {
      bottom: 2,
      textStyle: { color: c.axis, fontSize: 10 },
      itemWidth: 10, itemHeight: 10,
      data: [
        { name: 'P0 紧急', icon: 'circle', itemStyle: { color: '#e05c5c' } },
        { name: 'P1 重要', icon: 'circle', itemStyle: { color: '#e8a64c' } },
        { name: 'P2 观察', icon: 'circle', itemStyle: { color: '#7b9fc7' } },
        { name: 'P3 良好', icon: 'circle', itemStyle: { color: '#5daa87' } },
      ],
    },
    xAxis: {
      type: 'value', name: '建筑面积 (㎡)',
      nameLocation: 'middle', nameGap: 28,
      nameTextStyle: { color: c.axis, fontSize: 11 },
      axisLabel: { color: c.axis, fontSize: 10, formatter: (v: number) => `${(v / 1000).toFixed(0)}k` },
      splitLine: { lineStyle: { color: c.grid, type: 'dashed' } },
      max: maxSqm,
    },
    yAxis: {
      type: 'value', name: 'EUI (kWh/㎡)',
      nameLocation: 'middle', nameGap: 50,
      nameTextStyle: { color: c.axis, fontSize: 11 },
      axisLabel: { color: c.axis, fontSize: 10 },
      splitLine: { lineStyle: { color: c.grid, type: 'dashed' } },
      max: maxEui,
    },
    series: [
      // 背景象限区域
      {
        type: 'scatter', data: [], markArea: {
          silent: true,
          data: [
            // 右上: P0 红色区
            [{ xAxis: avgSqm, yAxis: avgEui, itemStyle: { color: 'rgba(224,92,92,0.06)' } }, { xAxis: maxSqm, yAxis: maxEui }],
            // 左上: P1 橙色区
            [{ xAxis: 0, yAxis: avgEui, itemStyle: { color: 'rgba(232,166,76,0.06)' } }, { xAxis: avgSqm, yAxis: maxEui }],
            // 右下: P2 蓝色区
            [{ xAxis: avgSqm, yAxis: 0, itemStyle: { color: 'rgba(123,159,199,0.06)' } }, { xAxis: maxSqm, yAxis: avgEui }],
            // 左下: P3 绿色区
            [{ xAxis: 0, yAxis: 0, itemStyle: { color: 'rgba(93,170,135,0.06)' } }, { xAxis: avgSqm, yAxis: avgEui }],
          ],
        },
      },
      // 均值参考线
      {
        type: 'scatter', data: [],
        markLine: {
          silent: true,
          symbol: 'none',
          lineStyle: { color: c.axis, type: 'dashed', width: 1, opacity: 0.4 },
          label: { fontSize: 9, color: c.axis },
          data: [
            { yAxis: avgEui, label: { formatter: `均值 EUI: ${avgEui.toFixed(4)}`, position: 'insideEndTop' } },
            { xAxis: avgSqm, label: { formatter: `均值面积: ${(avgSqm / 1000).toFixed(1)}k`, position: 'insideEndTop' } },
          ],
        },
      },
      // P0 紧急
      {
        name: 'P0 紧急', type: 'scatter',
        data: scatterData.filter(d => d.value[4] === 'P0 紧急'),
        symbolSize: (val: any[]) => Math.max(24, Math.sqrt(val[2]) * 0.12),
        label: { show: true, formatter: (p: any) => p.data.value[3], position: 'top', fontSize: 11, color: c.axis },
      },
      // P1 重要
      {
        name: 'P1 重要', type: 'scatter',
        data: scatterData.filter(d => d.value[4] === 'P1 重要'),
        symbolSize: (val: any[]) => Math.max(22, Math.sqrt(val[2]) * 0.1),
        label: { show: true, formatter: (p: any) => p.data.value[3], position: 'top', fontSize: 11, color: c.axis },
      },
      // P2 观察
      {
        name: 'P2 观察', type: 'scatter',
        data: scatterData.filter(d => d.value[4] === 'P2 观察'),
        symbolSize: (val: any[]) => Math.max(22, Math.sqrt(val[2]) * 0.1),
        label: { show: true, formatter: (p: any) => p.data.value[3], position: 'top', fontSize: 11, color: c.axis },
      },
      // P3 良好
      {
        name: 'P3 良好', type: 'scatter',
        data: scatterData.filter(d => d.value[4] === 'P3 良好'),
        symbolSize: (val: any[]) => Math.max(20, Math.sqrt(val[2]) * 0.08),
        label: { show: true, formatter: (p: any) => p.data.value[3], position: 'top', fontSize: 11, color: c.axis },
      },
    ],
  })
  instances.push(inst)
}

// ── 2. HVAC Virtual-Real Multi-axis ──────────────────────────
function renderHvac() {
  if (!hvacEl.value) return
  const c = gc()
  const hours = Array.from({ length: 24 }, (_, i) => `${i}:00`)
  const outdoorTemp = [18,17,16,16,17,18,20,22,24,26,27,28,28,27,26,25,24,23,22,21,20,20,19,18]
  const actualHvac  = [120,115,110,108,112,118,136,156,186,216,234,248,251,241,224,207,191,174,160,145,133,127,123,120]
  const simOptHvac  = [108,104, 99, 97,101,107,116,131,157,176,190,200,206,196,183,168,153,139,128,117,111,108,107,107]

  const inst = echarts.init(hvacEl.value)
  inst.setOption({
    backgroundColor: 'transparent',
    grid: { top: 32, right: 18, bottom: 36, left: 52 },
    tooltip: {
      trigger: 'axis',
      backgroundColor: c.ttBg, borderColor: c.ttBr,
      textStyle: { color: c.ttText, fontSize: 11 },
    },
    legend: { top: 6, textStyle: { color: c.axis, fontSize: 10 }, itemWidth: 12 },
    xAxis: {
      type: 'category', data: hours,
      axisLabel: { color: c.axis, fontSize: 10, interval: 3 },
      axisLine: { lineStyle: { color: c.grid } },
      splitLine: { show: false },
    },
    yAxis: [
      {
        type: 'value', name: 'kWh',
        nameTextStyle: { color: c.axis, fontSize: 10 },
        axisLabel: { color: c.axis, fontSize: 10 },
        splitLine: { lineStyle: { color: c.grid, type: 'dashed' } },
      },
      {
        type: 'value', name: '°C', min: 0, max: 40,
        nameTextStyle: { color: c.axis, fontSize: 10 },
        axisLabel: { color: c.axis, fontSize: 10 },
        splitLine: { show: false },
      },
    ],
    series: [
      {
        name: '室外气温', type: 'line', yAxisIndex: 1,
        data: outdoorTemp, smooth: true, symbol: 'none',
        lineStyle: { width: 0 },
        areaStyle: {
          color: {
            type: 'linear', x: 0, y: 0, x2: 0, y2: 1,
            colorStops: [
              { offset: 0, color: 'rgba(196,149,106,0.22)' },
              { offset: 1, color: 'rgba(196,149,106,0.02)' },
            ],
          },
        },
        z: 1,
      },
      {
        name: '实际HVAC能耗', type: 'line', yAxisIndex: 0,
        data: actualHvac, smooth: true, symbol: 'none',
        lineStyle: { color: MC.blue, width: 2.5 },
        itemStyle: { color: MC.blue },
        z: 3,
      },
      {
        name: '仿真最优能耗', type: 'line', yAxisIndex: 0,
        data: simOptHvac, smooth: true, symbol: 'none',
        lineStyle: { color: MC.sage, width: 2, type: 'dashed' },
        itemStyle: { color: MC.sage },
        z: 2,
      },
    ],
  })
  instances.push(inst)
}

// ── 3. GitHub-style Calendar Heatmap（纯 CSS Grid，aspect-ratio:1 正方形）────
const ghDays = ['周一', '周二', '周三', '周四', '周五', '周六', '周日']
const ghData = ref<Array<{ d: number; h: number; v: number }>>([])
const ghMaxVal = ref(1)
const ghTip = ref<{ show: boolean; x: number; y: number; text: string }>({
  show: false, x: 0, y: 0, text: '',
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
  for (const br of breaks) { if (ratio > br) idx++ }
  return palette[idx]
}

function generateGhData() {
  const result: Array<{ d: number; h: number; v: number }> = []
  let max = 0
  for (let d = 0; d < 7; d++) {
    for (let h = 0; h < 24; h++) {
      const isWorkday = d < 5
      const isWork = h >= 8 && h <= 18
      let v = isWorkday && isWork ? 80 + Math.random() * 100 : 10 + Math.random() * 25
      if ((!isWork || !isWorkday) && Math.random() < 0.09) v += 65 + Math.random() * 80
      v = parseFloat(v.toFixed(1))
      if (v > max) max = v
      result.push({ d, h, v })
    }
  }
  ghData.value = result
  ghMaxVal.value = max
}

function showGhTip(e: MouseEvent, cell: { d: number; h: number; v: number }) {
  const offHours = cell.d >= 5 || cell.h < 8 || cell.h > 18
  const anomaly  = cell.v > 90 && offHours ? ' ⚠ 非工时' : ''
  ghTip.value = {
    show: true,
    text: `${ghDays[cell.d]} ${cell.h}:00 · ${cell.v} kWh${anomaly}`,
    x: e.clientX + 14,
    y: e.clientY - 42,
  }
}

function hideGhTip() { ghTip.value.show = false }

// ── 4. Sankey Diagram ─────────────────────────────────────────
function renderSankey() {
  if (!sankeyEl.value) return
  const c = gc()

  const inst = echarts.init(sankeyEl.value)
  inst.setOption({
    backgroundColor: 'transparent',
    tooltip: {
      trigger: 'item',
      backgroundColor: c.ttBg, borderColor: c.ttBr,
      textStyle: { color: c.ttText, fontSize: 11 },
    },
    series: [{
      type: 'sankey',
      left: 16, right: 108, top: 10, bottom: 10,
      emphasis: { focus: 'adjacency' },
      nodeGap: 10, nodeWidth: 12,
      data: [
        { name: '温差过大',   itemStyle: { color: MC.terra } },
        { name: '能耗超标',   itemStyle: { color: MC.blue } },
        { name: '设备离线',   itemStyle: { color: MC.rose } },
        { name: '过滤网堵塞', itemStyle: { color: MC.lav } },
        { name: '传感器失效', itemStyle: { color: MC.lav } },
        { name: '冷水机故障', itemStyle: { color: MC.lav } },
        { name: '管道泄漏',   itemStyle: { color: MC.teal } },
      ],
      links: [
        { source: '温差过大', target: '过滤网堵塞', value: 14 },
        { source: '温差过大', target: '冷水机故障', value: 8 },
        { source: '能耗超标', target: '过滤网堵塞', value: 11 },
        { source: '能耗超标', target: '传感器失效', value: 9 },
        { source: '能耗超标', target: '管道泄漏',   value: 5 },
        { source: '设备离线', target: '传感器失效', value: 17 },
        { source: '设备离线', target: '冷水机故障', value: 7 },
      ],
      lineStyle: { color: 'gradient', opacity: 0.42 },
      label: { color: c.axis, fontSize: 11 },
    }],
  })
  instances.push(inst)
}

// ── 5. Health Deviation Scatter ───────────────────────────────
function renderScatter() {
  if (!scatterEl.value) return
  const c = gc()
  const resolved: [number, number][]   = []
  const unresolved: [number, number][] = []

  // Use real anomaly timestamps if available, else mock
  if (anomalyData.value.length > 0) {
    anomalyData.value.slice(0, 30).forEach((a: any, i: number) => {
      const dev = 5 + Math.random() * 45
      if (a.operation_status === 'Anomaly') unresolved.push([i, parseFloat(dev.toFixed(1))])
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
      trigger: 'axis', axisPointer: { type: 'cross' },
      backgroundColor: c.ttBg, borderColor: c.ttBr,
      textStyle: { color: c.ttText, fontSize: 11 },
    },
    legend: { top: 2, textStyle: { color: c.axis, fontSize: 10 }, itemWidth: 10, itemHeight: 10 },
    xAxis: {
      type: 'value', name: '事件编号',
      nameTextStyle: { color: c.axis, fontSize: 10 },
      axisLabel: { color: c.axis, fontSize: 10 },
      splitLine: { lineStyle: { color: c.grid, type: 'dashed' } },
    },
    yAxis: {
      type: 'value', name: '偏离度 %',
      nameTextStyle: { color: c.axis, fontSize: 10 },
      axisLabel: { color: c.axis, fontSize: 10 },
      splitLine: { lineStyle: { color: c.grid, type: 'dashed' } },
    },
    series: [
      {
        name: '已解决', type: 'scatter', data: resolved,
        symbolSize: 8, itemStyle: { color: MC.sage, opacity: 0.85 },
      },
      {
        name: '待处理', type: 'scatter', data: unresolved,
        symbolSize: 10, itemStyle: { color: MC.terra, opacity: 0.90 },
      },
    ],
  })
  instances.push(inst)
}

function renderAll() {
  renderBubble()
  renderHvac()
  renderSankey()
  renderScatter()
}

function onResize() {
  instances.forEach(c => c.resize())
}

// ResizeObserver 监听 canvas 容器本身的宽度变化
// 确保侧边栏折叠/Agent面板开关等场景也能触发 ECharts resize
let ro: ResizeObserver | null = null

onMounted(async () => {
  generateGhData()
  await buildingStore.fetchBuildings()
  await Promise.all([fetchOverview(), fetchAnomalies()])
  await nextTick()
  setTimeout(() => {
    renderAll()
    window.addEventListener('resize', onResize)
    // 用 ResizeObserver 兜底：容器宽度变化时也 resize
    const el = document.querySelector('.home-page') as HTMLElement | null
    if (el && typeof ResizeObserver !== 'undefined') {
      ro = new ResizeObserver(() => { instances.forEach(c => c.resize()) })
      ro.observe(el)
    }
  }, 60)
})

onUnmounted(() => {
  instances.forEach(c => c.dispose())
  instances = []
  window.removeEventListener('resize', onResize)
  ro?.disconnect()
  ro = null
})
</script>

<style scoped>
/* ─────────────────────────────────────────────────────────────
   Home page — 复用系统主题变量 + Morandi 莫兰迪配色
   背景与其他页面一致（var(--bg-dark)）；
   内容卡片用 var(--bg-panel) / var(--bg-card)；
   浅色主题对内容卡片做白底覆盖（同 Dashboard 规则）
───────────────────────────────────────────────────────────── */
.home-page {
  container-type: inline-size;

  padding: 28px 24px 32px;
  min-height: 100%;
  background: var(--bg-dark);      /* 与驾驶舱等页面底色一致 */
  color: var(--text-primary);
  display: flex;
  flex-direction: column;
  gap: 16px;
  box-sizing: border-box;
}

/* ── Header ───────────────────────────────────────────────── */
.pg-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-shrink: 0;
  flex-wrap: wrap;
  gap: 10px;
}

/* ── 建筑切换胶囊 ────────────────────────────────────────── */
.capsule-switcher {
  position: relative;
  display: inline-flex;
  align-items: center;
  background: var(--bg-panel);
  border: 1px solid var(--border);
  border-radius: 24px;
  padding: 3px;
  gap: 0;
  flex-shrink: 0;
}
.capsule-slider {
  position: absolute;
  top: 3px;
  left: 0;
  height: calc(100% - 6px);
  border-radius: 20px;
  background: var(--border-accent, rgba(122,170,142,0.35));
  transition: transform 0.3s cubic-bezier(0.4, 0, 0.2, 1), width 0.3s cubic-bezier(0.4, 0, 0.2, 1);
  pointer-events: none;
  z-index: 0;
}
.capsule-btn {
  position: relative;
  z-index: 1;
  border: none;
  outline: none;
  background: transparent;
  color: var(--text-secondary);
  font-size: 12px;
  font-weight: 500;
  padding: 5px 16px;
  border-radius: 20px;
  cursor: pointer;
  transition: color 0.25s;
  white-space: nowrap;
}
.capsule-btn.active {
  color: var(--text-primary);
  font-weight: 600;
}
.capsule-btn:hover:not(.active) {
  color: var(--text-primary);
}
.pg-greeting {
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.pg-title {
  font-size: 22px;
  font-weight: 800;
  color: var(--text-primary);
  letter-spacing: -0.02em;
  line-height: 1.2;
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
}
.pg-wave-lottie {
  width: 36px;
  height: 36px;
  display: inline-block;
  flex-shrink: 0;
}
@container (max-width: 539px) {
  .pg-wave-lottie { width: 28px; height: 28px; }
}
@container (max-width: 399px) {
  .pg-wave-lottie { width: 22px; height: 22px; }
}
.pg-sub {
  font-size: 13px;
  color: var(--text-secondary);
  font-weight: 400;
}
.weather-widget {
  display: flex;
  align-items: center;
  gap: 10px;
  background: var(--bg-panel);
  border: 1px solid var(--border);
  border-radius: 14px;
  padding: 8px 16px;
  flex-shrink: 0;
}
.weather-date {
  display: flex;
  align-items: center;
  gap: 5px;
  font-size: 12px;
  color: var(--text-secondary);
  white-space: nowrap;
}
.weather-divider {
  width: 1px;
  height: 22px;
  background: var(--border);
  flex-shrink: 0;
}
.weather-metrics {
  display: flex;
  align-items: center;
  gap: 12px;
}
.weather-item {
  display: flex;
  align-items: center;
  gap: 4px;
}
.weather-icon {
  flex-shrink: 0;
}
.temp-icon { color: #e8845a; }
.humi-icon { color: #5a9fd4; }
.weather-val {
  font-size: 13px;
  font-weight: 600;
  color: var(--text-primary);
  white-space: nowrap;
}
.weather-val small {
  font-size: 10px;
  font-weight: 400;
  color: var(--text-secondary);
  margin-left: 1px;
}

/* ── KPI Strip ────────────────────────────────────────────── */
.kpi-strip {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 10px;
  flex-shrink: 0;
}
.kpi-card {
  background: var(--bg-panel);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 12px 14px;
  display: flex;
  align-items: center;
  gap: 10px;
  transition: border-color 0.2s;
}
.kpi-card:hover {
  border-color: var(--border-accent);
}
.kpi-ico {
  width: 36px;
  height: 36px;
  border-radius: 10px;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}
.kpi-body { flex: 1; min-width: 0; }
.kpi-val {
  display: block;
  font-size: 17px;
  font-weight: 700;
  color: var(--text-primary);
  line-height: 1.15;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.kpi-lbl {
  display: block;
  font-size: 10px;
  color: var(--text-muted);
  margin-top: 3px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.kpi-tag {
  font-size: 10px;
  font-weight: 600;
  padding: 2px 8px;
  border-radius: 20px;
  flex-shrink: 0;
  white-space: nowrap;
}

/* ── Bento Rows ───────────────────────────────────────────── */
.bento-row {
  display: grid;
  gap: 14px;
  align-items: start;   /* 每个面板独立高度，不互相拉伸对齐 */
}
.bento-r1 { grid-template-columns: 1.5fr 1fr; }
.bento-r2 { grid-template-columns: 1.2fr 1fr; }

/* ── Chart Panel ─────────────────────────────────────────── */
.cpanel {
  background: var(--bg-panel);
  border: 1px solid var(--border);
  border-radius: 8px;
  overflow: hidden;
  display: flex;
  flex-direction: column;
  transition: border-color 0.2s;
}
.cpanel:hover {
  border-color: var(--border-accent);
}
.cpanel-hd {
  padding: 12px 16px 8px;
  display: flex;
  flex-direction: column;
  gap: 3px;
  flex-shrink: 0;
  min-width: 0;
}
.cpanel-title {
  font-size: 13px;
  font-weight: 700;
  color: var(--text-primary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  min-width: 0;
}
.cpanel-sub {
  font-size: 11px;
  font-weight: 400;
  color: var(--text-secondary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.cpanel-body {
  flex: 1;
  width: 100%;
}

/* ── Stacked right column ─────────────────────────────────── */
.cpanel-col {
  display: flex;
  flex-direction: column;
  gap: 14px;
  align-self: start;   /* 不被 grid 行高拉伸 */
}

/* ══════════════════════════════════════════════════════════════
   响应式 — Container Queries（基于 canvas 容器宽度）
   ≥ 900px   : 默认双列 Bento + 5列 KPI（default styles）
   700–899px : 双列 Bento 收窄 + 图表高度稍降
   < 700px   : Bento 单列 + 3列 KPI + 图表全宽拉高
   < 540px   : 2列 KPI + 减小间距 + 隐藏副标题
   < 400px   : 极窄 — 最小化字体/padding/图表高度
══════════════════════════════════════════════════════════════ */

/* ── 中宽屏 700~899px ─────────────────────────────────────── */
@container (max-width: 899px) {
  .home-page {
    padding: 20px 18px 28px;
    gap: 14px;
  }
  .bento-r1 { grid-template-columns: 1.3fr 1fr; }
  .bento-r2 { grid-template-columns: 1.1fr 1fr; }
  /* 图表高度小幅收缩 */
  .bento-r1 .cpanel-body { height: 220px !important; }
}

/* ── 单列切换 < 700px ─────────────────────────────────────── */
@container (max-width: 699px) {
  .pg-header {
    flex-direction: column;
    align-items: flex-start;
  }
  .capsule-switcher { align-self: stretch; justify-content: center; }
  .capsule-btn { flex: 1; text-align: center; padding: 5px 10px; }
  .home-page {
    padding: 16px 14px 24px;
    gap: 12px;
  }
  .kpi-strip {
    grid-template-columns: repeat(3, minmax(0, 1fr));
    gap: 8px;
  }
  .bento-r1,
  .bento-r2 {
    grid-template-columns: 1fr;
    gap: 10px;
  }
  /* 全宽后图表可以更高 */
  .bento-r1 .cpanel-body { height: 260px !important; }
  /* 右侧叠加列改为横排 */
  .cpanel-col {
    flex-direction: row;
  }
  .cpanel-col .cpanel {
    flex: 1;
    min-width: 0;
  }
  .cpanel-col .cpanel-body { height: 200px !important; }
}

/* ── 窄屏 < 540px ─────────────────────────────────────────── */
@container (max-width: 539px) {
  .capsule-btn { font-size: 11px; padding: 4px 8px; }
  .home-page {
    padding: 12px 10px 20px;
    gap: 10px;
  }
  .kpi-strip {
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 8px;
  }
  .kpi-card {
    padding: 10px 10px;
    gap: 8px;
  }
  .kpi-ico { width: 30px; height: 30px; border-radius: 8px; }
  .kpi-val { font-size: 15px; }
  .kpi-tag { display: none; }
  .cpanel-sub { display: none; }
  .bento-r1 .cpanel-body { height: 220px !important; }
  .cpanel-col { flex-direction: column; }
  .cpanel-col .cpanel-body { height: 160px !important; }
  /* 热力图缩紧 */
  .gh-wrap { padding: 10px 12px 8px; }
  .gh-cells { gap: 2px; }
  .gh-x-labels { gap: 2px; }
  .gh-x-label { font-size: 9px; }
  .gh-y-label { font-size: 9px; }
  .gh-y-col { width: 26px; }
  .gh-y-spacer { width: 26px; }
}

/* ── 极窄屏 < 400px ───────────────────────────────────────── */
@container (max-width: 399px) {
  .home-page { padding: 10px 8px 16px; gap: 8px; }
  .pg-title  { font-size: 16px; }
  .pg-sub    { display: none; }
  .weather-widget  { display: none; }
  .bento-row { gap: 8px; }
  .bento-r1 .cpanel-body { height: 180px !important; }
  .cpanel-col .cpanel-body { height: 130px !important; }
  .cpanel-hd { padding: 8px 12px 6px; }
  .cpanel-title { font-size: 12px; }
  /* 热力图极简化 */
  .gh-wrap { padding: 8px 10px 6px; }
  .gh-cells { gap: 1px; }
  .gh-x-labels { gap: 1px; }
  .gh-legend { display: none; }
}

/* ══════════════════════════════════════════════════════════════
   浅色主题：内容卡片白底覆盖（与 Dashboard 规则一致）
   --bg-panel 在浅色主题为深绿 #3e6354，需显式覆盖为白色
══════════════════════════════════════════════════════════════ */
html[data-theme="light"] .kpi-card,
html[data-theme="light"] .cpanel {
  background: #ffffff;
  border-color: #e2e8e4;
}
html[data-theme="light"] .weather-widget {
  background: #ffffff;
  border-color: #e2e8e4;
}
html[data-theme="light"] .weather-date {
  color: #666;
}
html[data-theme="light"] .weather-val {
  color: #111;
}
html[data-theme="light"] .weather-divider {
  background: #e2e8e4;
}
html[data-theme="light"] .capsule-switcher {
  background: #f4f7f5;
  border-color: #e2e8e4;
}
html[data-theme="light"] .capsule-slider {
  background: #ffffff;
  box-shadow: 0 1px 3px rgba(0,0,0,0.1);
}
html[data-theme="light"] .capsule-btn { color: #888; }
html[data-theme="light"] .capsule-btn.active { color: #111; }
html[data-theme="light"] .pg-title      { color: #111; }
html[data-theme="light"] .pg-sub        { color: #666; }
html[data-theme="light"] .cpanel-title  { color: #111; }
html[data-theme="light"] .cpanel-sub    { color: #888; }
html[data-theme="light"] .kpi-val       { color: #111; }
html[data-theme="light"] .kpi-lbl       { color: #666; }
/* 热力图坐标轴文字在浅色主题下强制深色 */
html[data-theme="light"] .gh-y-label,
html[data-theme="light"] .gh-x-label,
html[data-theme="light"] .gh-legend-text { color: #555; }

/* ── GitHub Calendar Heatmap ──────────────────────────────── */
.gh-wrap {
  padding: 14px 16px 12px;
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.gh-main {
  display: flex;
  align-items: stretch;
  gap: 8px;
}
.gh-y-col {
  display: flex;
  flex-direction: column;
  justify-content: space-around;
  width: 30px;
  flex-shrink: 0;
}
.gh-y-label {
  font-size: 11px;
  color: var(--text-muted);
  text-align: right;
  line-height: 1;
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: flex-end;
}
.gh-cells {
  flex: 1;
  display: grid;
  grid-template-columns: repeat(24, 1fr);
  gap: 3px;
}
.gh-cell {
  aspect-ratio: 1;
  border-radius: 3px;
  cursor: default;
  transition: opacity 0.1s;
}
.gh-cell:hover { opacity: 0.65; }
.gh-x-row {
  display: flex;
  align-items: center;
  gap: 8px;
}
.gh-y-spacer {
  width: 30px;
  flex-shrink: 0;
}
.gh-x-labels {
  flex: 1;
  display: grid;
  grid-template-columns: repeat(24, 1fr);
  gap: 3px;
}
.gh-x-label {
  font-size: 10px;
  color: var(--text-muted);
  text-align: center;
  white-space: nowrap;
  line-height: 1;
}
.gh-legend {
  display: flex;
  align-items: center;
  gap: 4px;
  justify-content: flex-end;
  margin-top: 2px;
}
.gh-legend-text {
  font-size: 10px;
  color: var(--text-muted);
}
.gh-legend-cell {
  width: 13px;
  height: 13px;
  border-radius: 3px;
}
</style>

<!-- Non-scoped: Teleport tooltip goes to <body>, needs global selector -->
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
  box-shadow: 0 4px 12px rgba(0,0,0,0.4);
}
</style>
