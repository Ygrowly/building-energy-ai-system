<template>
  <div class="chart-card">
    <div class="chart-header">
      <span class="chart-title">{{ title }}</span>
      <button class="source-btn" @click="showSource = !showSource" title="数据溯源">
        🔍 数据来源
      </button>
    </div>

    <!-- 骨架屏（数据加载中） -->
    <div v-if="!chartReady" class="skeleton">
      <div class="skeleton-bar" v-for="i in 7" :key="i" :style="{ height: `${20 + i * 10}%` }"></div>
    </div>

    <!-- ECharts 图表 -->
    <div v-else ref="chartEl" class="chart-body"></div>

    <!-- 数据溯源面板 -->
    <div class="source-panel" v-if="showSource">
      <div class="source-row">
        <span class="source-key">📦 数据来源</span>
        <span class="source-val">{{ sourceInfo?.source_table ?? 'energy_data' }}</span>
      </div>
      <div class="source-row" v-if="sourceInfo?.meter_device_id">
        <span class="source-key">📡 设备 ID</span>
        <span class="source-val">{{ sourceInfo.meter_device_id }}</span>
      </div>
      <div class="source-row" v-if="sourceInfo?.query_time_ms">
        <span class="source-key">⚡ 查询耗时</span>
        <span class="source-val success">{{ sourceInfo.query_time_ms }} ms</span>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, watch, nextTick } from 'vue'
import * as echarts from 'echarts'
import type { ArtifactEvent } from '@/api/stream_client'

const props = defineProps<{
  artifact: ArtifactEvent
}>()

const chartEl = ref<HTMLElement>()
const showSource = ref(false)
const chartReady = ref(false)

const title = props.artifact.title ?? '能耗图表'
const sourceInfo = props.artifact.source_info as Record<string, unknown> | undefined

function buildOption() {
  const payload = props.artifact.data_payload as Record<string, unknown> | unknown[]
  const widget = props.artifact.widget ?? props.artifact.component_type ?? 'LineChart'

  if (Array.isArray(payload)) {
    // payload = [{label, value}, ...] 或 [[x, y], ...]
    const xData = payload.map((d: unknown) => {
      const item = d as Record<string, unknown>
      return String(item.label ?? item.day ?? item.timestamp ?? item[0] ?? '')
    })
    const yData = payload.map((d: unknown) => {
      const item = d as Record<string, unknown>
      return Number(item.value ?? item.total_electricity_kwh ?? item[1] ?? 0)
    })

    if (widget === 'BarChart') {
      return {
        grid: { top: 20, right: 20, bottom: 40, left: 50 },
        xAxis: { type: 'category', data: xData, axisLabel: { color: '#9399b8', fontSize: 11 } },
        yAxis: { type: 'value', axisLabel: { color: '#9399b8', fontSize: 11 } },
        series: [{ type: 'bar', data: yData, itemStyle: { color: '#6c8ef5', borderRadius: [4, 4, 0, 0] } }],
        tooltip: { trigger: 'axis' },
      }
    }
    return {
      grid: { top: 20, right: 20, bottom: 40, left: 50 },
      xAxis: { type: 'category', data: xData, axisLabel: { color: '#9399b8', fontSize: 11 } },
      yAxis: { type: 'value', axisLabel: { color: '#9399b8', fontSize: 11 } },
      series: [{
        type: 'line', data: yData, smooth: true,
        lineStyle: { color: '#6c8ef5', width: 2 },
        areaStyle: { color: { type: 'linear', x: 0, y: 0, x2: 0, y2: 1, colorStops: [{ offset: 0, color: 'rgba(108,142,245,0.3)' }, { offset: 1, color: 'rgba(108,142,245,0)' }] } },
        itemStyle: { color: '#6c8ef5' },
      }],
      tooltip: { trigger: 'axis' },
    }
  }

  // Gauge
  if (widget === 'Gauge') {
    const val = Number((payload as Record<string, unknown>).value ?? 0)
    return {
      series: [{
        type: 'gauge', startAngle: 200, endAngle: -20,
        min: 0, max: 6,
        splitNumber: 6,
        axisLine: { lineStyle: { width: 20, color: [[0.3, '#4ade80'], [0.7, '#fbbf24'], [1, '#f87171']] } },
        pointer: { itemStyle: { color: 'auto' } },
        detail: { valueAnimation: true, fontSize: 28, color: 'auto', formatter: '{value} COP' },
        data: [{ value: val }],
      }],
    }
  }

  return {}
}

async function initChart() {
  await nextTick()
  if (!chartEl.value) return
  const chart = echarts.init(chartEl.value, 'dark')
  chart.setOption(buildOption())
  window.addEventListener('resize', () => chart.resize())
}

onMounted(async () => {
  chartReady.value = true
  await initChart()
})
</script>

<style scoped>
.chart-card {
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: 10px;
  overflow: hidden;
  margin: 8px 0;
}

.chart-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 12px 16px 8px;
}

.chart-title {
  font-weight: 600;
  color: var(--text-primary);
  font-size: 13px;
}

.source-btn {
  background: none;
  border: 1px solid var(--border);
  border-radius: 4px;
  color: var(--text-secondary);
  font-size: 11px;
  padding: 3px 8px;
  cursor: pointer;
  transition: all 0.2s;
}
.source-btn:hover { border-color: var(--accent); color: var(--accent); }

.skeleton {
  height: 200px;
  display: flex;
  align-items: flex-end;
  gap: 8px;
  padding: 16px;
}
.skeleton-bar {
  flex: 1;
  background: var(--bg-hover);
  border-radius: 4px 4px 0 0;
  animation: shimmer 1.5s infinite;
}
@keyframes shimmer {
  0%, 100% { opacity: 0.5; }
  50% { opacity: 1; }
}

.chart-body {
  width: 100%;
  height: 220px;
}

.source-panel {
  border-top: 1px solid var(--border);
  padding: 10px 16px;
  background: var(--bg-panel);
}

.source-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 3px 0;
  font-size: 12px;
}
.source-key { color: var(--text-muted); }
.source-val { color: var(--text-secondary); font-family: monospace; }
.source-val.success { color: var(--success); }
</style>
