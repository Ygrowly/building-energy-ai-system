<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { cachedApiFetch } from '@/api/cached'
import { buildHeatmapCells } from '@/utils/homeCharts'

type LoadProfilePayload = {
  hourly_profile?: Array<{ hour: number; avg_value: number | null }>
  weekday_profile?: Array<{ weekday: number; avg_value: number | null }>
}

const props = withDefaults(
  defineProps<{
    buildingTypes: string[]
    profiles?: Array<LoadProfilePayload | null | undefined>
    title?: string
    subtitle?: string
    pickId?: string
    pickTitle?: string
    pickSubtitle?: string
    useBundle?: boolean
    bundlePending?: boolean
  }>(),
  {
    profiles: () => [],
    title: '24h 能耗日历热力图',
    subtitle: '近两周逐时负荷合成的 7×24 节律',
    pickId: 'chart-heatmap',
    pickTitle: '24h 能耗日历热力图',
    pickSubtitle: '',
    useBundle: false,
    bundlePending: false,
  },
)

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

const pickSubtitleText = computed(() => props.pickSubtitle || props.subtitle)
const heatmapKey = computed(() => props.buildingTypes.join('|'))
const bundledProfiles = computed(() =>
  (props.profiles ?? []).filter((profile): profile is LoadProfilePayload => profile != null),
)

function getGhColor(v: number): string {
  const dark = document.documentElement.dataset.theme !== 'light'
  const ratio = Math.min(v / ghMaxVal.value, 1)
  const palette = dark
    ? ['#161b22', '#0e4429', '#006d32', '#26a641', '#39d353']
    : ['#ebedf0', '#9be9a8', '#40c463', '#30a14e', '#216e39']
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
    text: `${ghDays[cell.d]} ${cell.h}:00 · ${cell.v}${anomaly}`,
    x: e.clientX + 14,
    y: e.clientY - 42,
  }
}

function hideGhTip() {
  ghTip.value.show = false
}

function resetHeatmap() {
  ghData.value = []
  ghMaxVal.value = 1
}

function applyProfiles(profiles: LoadProfilePayload[]) {
  if (!profiles.length) {
    resetHeatmap()
    return
  }

  const hourlySum = new Array(24).fill(0)
  const weekdaySum = new Array(7).fill(0)

  profiles.forEach((profile) => {
    for (const point of profile.hourly_profile || []) {
      hourlySum[point.hour] += Number(point.avg_value ?? 0)
    }
    for (const point of profile.weekday_profile || []) {
      if (point.weekday >= 1 && point.weekday <= 7) {
        weekdaySum[point.weekday - 1] += Number(point.avg_value ?? 0)
      }
    }
  })

  const count = profiles.length
  const hourly = hourlySum.map((sum, hour) => ({ hour, avg_value: sum / count }))
  const weekly = weekdaySum.map((sum, index) => ({ weekday: index + 1, avg_value: sum / count }))
  const cells = buildHeatmapCells(hourly, weekly)
  ghData.value = cells
  ghMaxVal.value = Math.max(...cells.map((cell) => cell.v), 1)
}

async function loadHeatmap() {
  if (!props.buildingTypes.length) {
    resetHeatmap()
    return
  }

  if (bundledProfiles.value.length) {
    applyProfiles(bundledProfiles.value)
    return
  }

  if (props.useBundle && props.bundlePending) {
    return
  }

  try {
    const profiles = await Promise.all(
      props.buildingTypes.map((buildingType) =>
        cachedApiFetch<LoadProfilePayload>(
          `/api/buildings/${encodeURIComponent(buildingType)}/load-profile?metric=electricity&days=14`,
          undefined,
          { ttlMs: 300_000 },
        ),
      ),
    )
    applyProfiles(profiles)
  } catch {
    resetHeatmap()
  }
}

watch(
  () => [heatmapKey.value, props.bundlePending, props.useBundle, props.profiles],
  () => loadHeatmap(),
  { deep: true, immediate: true },
)
</script>

<template>
  <div
    class="cpanel"
    :data-pick-id="pickId"
    data-pick-type="heatmap"
    :data-pick-title="pickTitle"
    :data-pick-subtitle="pickSubtitleText"
  >
    <div class="cpanel-hd">
      <span class="cpanel-title">{{ title }}</span>
      <span class="cpanel-sub">{{ subtitle }}</span>
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
