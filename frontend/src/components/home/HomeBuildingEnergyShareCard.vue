<script setup lang="ts">
import { computed } from 'vue'
import { Icon } from '@iconify/vue'
import {
  HOME_BUILDING_COLORS,
  HOME_BUILDING_ORDER,
  type HomeBuildingType,
} from '@/utils/homeCharts'
import { BUILDING_TYPE_LABELS } from '@/constants/buildings'

const props = defineProps<{
  overviewData: any
}>()

type BuildingShareMetricKey = 'electricity' | 'water' | 'hvac'

interface BuildingShareSegment {
  buildingType: HomeBuildingType
  label: string
  color: string
  value: number
  percent: number
}

interface BuildingShareRow {
  key: BuildingShareMetricKey
  title: string
  icon: string
  totalValueText: string
  unit: string
  hasData: boolean
  segments: BuildingShareSegment[]
}

const SHARE_BUILDING_COLORS = HOME_BUILDING_ORDER.reduce((palette, buildingType) => {
  palette[buildingType] = shiftColor(HOME_BUILDING_COLORS[buildingType], -0.2)
  return palette
}, {} as Record<HomeBuildingType, string>)

const FALLBACK_BUILDING_LABELS: Record<HomeBuildingType, string> = BUILDING_TYPE_LABELS

const buildingLabels = computed<Record<HomeBuildingType, string>>(() => {
  const labels = { ...FALLBACK_BUILDING_LABELS }
  const buildings: any[] = props.overviewData?.buildings ?? []

  buildings.forEach((building) => {
    const buildingType = building?.building_type as HomeBuildingType | undefined
    if (!buildingType || !(buildingType in labels)) return
    labels[buildingType] = String(building?.display_name || labels[buildingType])
  })

  return labels
})

function formatValue(value: number | null | undefined, digits = 1): string {
  const numeric = Number(value ?? 0)
  return Number.isFinite(numeric) ? numeric.toFixed(digits) : '0.0'
}

function createSegments(
  totalValue: number,
  valueResolver: (building: any) => number,
): BuildingShareSegment[] {
  const buildings: any[] = props.overviewData?.buildings ?? []

  return HOME_BUILDING_ORDER.map((buildingType) => {
    const building = buildings.find((item) => item?.building_type === buildingType)
    const value = valueResolver(building)
    const percent = totalValue > 0 ? (value / totalValue) * 100 : 0

    return {
      buildingType,
      label: buildingLabels.value[buildingType],
      color: SHARE_BUILDING_COLORS[buildingType],
      value,
      percent: Number.isFinite(percent) ? percent : 0,
    }
  })
}

const rows = computed<BuildingShareRow[]>(() => {
  const kpis = props.overviewData?.kpis ?? {}
  const totalElectricity = Number(kpis.total_electricity_kwh ?? 0)
  const totalWater = Number(kpis.total_water_m3 ?? 0)
  const totalHvac = Number(kpis.total_hac_energy_kwh ?? 0)

  return [
    {
      key: 'electricity',
      title: '今日总用电',
      icon: 'mdi:lightning-bolt',
      unit: 'kWh',
      hasData: totalElectricity > 0,
      totalValueText: `今日总用电 ${formatValue(totalElectricity)} kWh`,
      segments: createSegments(totalElectricity, (building) => Number(building?.total_electricity_kwh ?? 0)),
    },
    {
      key: 'water',
      title: '今日总用水',
      icon: 'mdi:water',
      unit: 'm³',
      hasData: totalWater > 0,
      totalValueText: `今日总用水 ${formatValue(totalWater)} m³`,
      segments: createSegments(totalWater, (building) => Number(building?.total_water_m3 ?? 0)),
    },
    {
      key: 'hvac',
      title: '今日空调能耗',
      icon: 'mdi:snowflake',
      unit: 'kWh',
      hasData: totalHvac > 0,
      totalValueText: `今日空调能耗 ${formatValue(totalHvac)} kWh`,
      segments: createSegments(totalHvac, (building) => Number(building?.total_hac_energy_kwh ?? 0)),
    },
  ]
})

function formatSegmentTooltip(segment: BuildingShareSegment, unit: string): string {
  return `${segment.label} · ${formatValue(segment.value)} ${unit} · 占比 ${formatValue(segment.percent)}%`
}

function segmentStyle(
  segment: BuildingShareSegment,
  index: number,
  segments: BuildingShareSegment[],
) {
  const isFirst = index === 0
  const isLast = index === segments.length - 1

  return {
    width: `${segment.percent}%`,
    '--segment-focus': rgba(segment.color, 0.2),
    '--segment-radius-start': isFirst ? '999px' : '0',
    '--segment-radius-end': isLast ? '999px' : '0',
  }
}

function trackStyle(segments: BuildingShareSegment[]) {
  const visibleSegments = segments.filter((segment) => segment.percent > 0.01)
  const gradient = buildTrackGradient(visibleSegments)

  return {
    '--share-track-fill': gradient || 'linear-gradient(90deg, rgba(148, 163, 184, 0.18), rgba(148, 163, 184, 0.08))',
  }
}

function buildTrackGradient(segments: BuildingShareSegment[]) {
  if (!segments.length) return ''

  const gradientStops: string[] = []
  let cursor = 0

  segments.forEach((segment, index) => {
    const start = cursor
    const end = Math.min(100, cursor + segment.percent)
    const span = Math.max(end - start, 0)
    const blendRange = clamp(span * 0.24, 2.4, 7.5)
    const baseColor = segment.color
    const prevColor = segments[index - 1]?.color
    const nextColor = segments[index + 1]?.color
    const startCore = index === 0 ? start : Math.min(end, start + blendRange)
    const endCore = index === segments.length - 1 ? end : Math.max(start, end - blendRange)

    if (index === 0) {
      gradientStops.push(`${shiftColor(baseColor, -0.16)} ${start.toFixed(2)}%`)
    } else if (prevColor) {
      gradientStops.push(`${mixColors(prevColor, baseColor, 0.48)} ${start.toFixed(2)}%`)
    }

    if (startCore > start) {
      gradientStops.push(`${baseColor} ${startCore.toFixed(2)}%`)
    }

    gradientStops.push(`${mixColors(baseColor, '#ffffff', 0.08)} ${endCore.toFixed(2)}%`)

    if (index === segments.length - 1) {
      gradientStops.push(`${shiftColor(baseColor, -0.08)} ${end.toFixed(2)}%`)
    } else if (nextColor) {
      gradientStops.push(`${mixColors(baseColor, nextColor, 0.52)} ${end.toFixed(2)}%`)
    }

    cursor = end
  })

  return `linear-gradient(90deg, ${gradientStops.join(', ')})`
}

function clamp(value: number, min: number, max: number) {
  return Math.min(max, Math.max(min, value))
}

function shiftColor(hex: string, amount: number) {
  const { r, g, b } = hexToRgb(hex)

  if (amount >= 0) {
    return rgbToHex({
      r: Math.round(r + (255 - r) * amount),
      g: Math.round(g + (255 - g) * amount),
      b: Math.round(b + (255 - b) * amount),
    })
  }

  const ratio = 1 + amount
  return rgbToHex({
    r: Math.round(r * ratio),
    g: Math.round(g * ratio),
    b: Math.round(b * ratio),
  })
}

function mixColors(left: string, right: string, weight = 0.5) {
  const leftRgb = hexToRgb(left)
  const rightRgb = hexToRgb(right)
  const ratio = clamp(weight, 0, 1)

  return rgbToHex({
    r: Math.round(leftRgb.r + (rightRgb.r - leftRgb.r) * ratio),
    g: Math.round(leftRgb.g + (rightRgb.g - leftRgb.g) * ratio),
    b: Math.round(leftRgb.b + (rightRgb.b - leftRgb.b) * ratio),
  })
}

function rgba(hex: string, alpha: number) {
  const { r, g, b } = hexToRgb(hex)
  return `rgba(${r}, ${g}, ${b}, ${alpha})`
}

function hexToRgb(hex: string) {
  const normalized = hex.replace('#', '')
  const full = normalized.length === 3
    ? normalized.split('').map((char) => `${char}${char}`).join('')
    : normalized

  return {
    r: Number.parseInt(full.slice(0, 2), 16),
    g: Number.parseInt(full.slice(2, 4), 16),
    b: Number.parseInt(full.slice(4, 6), 16),
  }
}

function rgbToHex(
  rgb: {
    r: number
    g: number
    b: number
  },
) {
  return `#${[rgb.r, rgb.g, rgb.b]
    .map((channel) => clamp(Math.round(channel), 0, 255).toString(16).padStart(2, '0'))
    .join('')}`
}
</script>

<template>
  <div
    class="cpanel overview-share-panel"
    data-pick-id="chart-overview-share"
    data-pick-type="chart"
    data-pick-title="首页各项能耗楼宇占比"
    data-pick-subtitle="按用电、用水、暖通查看教学楼、办公楼、公共楼的当日分配结构"
  >
    <div class="cpanel-hd share-card-head">
      <div class="share-card-copy">
        <span class="cpanel-title">各项能耗楼宇占比</span>
        <span class="cpanel-sub">按能源类型查看不同楼宇的当日分配结构</span>
      </div>

      <div class="share-legend" aria-label="楼宇图例">
        <span
          v-for="buildingType in HOME_BUILDING_ORDER"
          :key="buildingType"
          class="share-legend-item"
        >
          <span
            class="share-legend-swatch"
            :style="{ backgroundColor: SHARE_BUILDING_COLORS[buildingType] }"
          />
          <span>{{ buildingLabels[buildingType] }}</span>
        </span>
      </div>
    </div>

    <div class="cpanel-body share-card-body">
      <div
        v-for="(row, rowIndex) in rows"
        :key="row.key"
        :class="['share-row', { 'share-row--last': rowIndex === rows.length - 1 }]"
      >
        <div class="share-row-head">
          <div class="share-row-title">
            <Icon :icon="row.icon" width="16" class="share-row-icon" />
            <span>{{ row.title }}</span>
          </div>
          <span class="share-row-total">{{ row.totalValueText }}</span>
        </div>

        <div
          v-if="row.hasData"
          class="share-track"
          :style="trackStyle(row.segments)"
          :aria-label="row.totalValueText"
          role="img"
        >
          <div
            v-for="(segment, index) in row.segments"
            :key="`${row.key}-${segment.buildingType}`"
            class="share-segment"
            :style="segmentStyle(segment, index, row.segments)"
            :data-tooltip="formatSegmentTooltip(segment, row.unit)"
            :aria-label="formatSegmentTooltip(segment, row.unit)"
            tabindex="0"
          />
        </div>

        <div v-else class="share-track share-track--empty">暂无数据</div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.overview-share-panel {
  min-width: 0;
}

.share-card-head {
  gap: 8px;
}

.share-card-copy {
  display: flex;
  flex-direction: column;
  gap: 4px;
  min-width: 0;
}

.share-legend {
  display: flex;
  flex-wrap: wrap;
  gap: 8px 12px;
  font-size: 11px;
  color: var(--text-secondary);
}

.share-legend-item {
  display: inline-flex;
  align-items: center;
  gap: 6px;
}

.share-legend-swatch {
  width: 10px;
  height: 10px;
  border-radius: 3px;
  box-shadow: inset 0 0 0 1px rgba(255, 255, 255, 0.18);
}

.share-card-body {
  display: flex;
  flex-direction: column;
  gap: 12px;
  min-height: 0;
  padding: 4px 16px 14px;
}

.share-row {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 6px 4px;
}

.share-row-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.share-row-title {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  min-width: 0;
  font-size: 11px;
  font-weight: 700;
  color: var(--text-primary);
}

.share-row-icon {
  flex-shrink: 0;
  color: var(--border-accent, #5b876d);
}

.share-row-total {
  flex-shrink: 0;
  font-size: 11px;
  color: var(--text-secondary);
}

.share-track {
  --share-track-fill: linear-gradient(90deg, rgba(148, 163, 184, 0.18), rgba(148, 163, 184, 0.08));
  position: relative;
  display: flex;
  width: 100%;
  min-height: 10px;
  overflow: visible;
  border-radius: 999px;
  isolation: isolate;
  background:
    linear-gradient(180deg, rgba(255, 255, 255, 0.14) 0%, rgba(255, 255, 255, 0.04) 52%, rgba(255, 255, 255, 0) 100%),
    var(--share-track-fill);
  box-shadow:
    inset 0 1px 0 rgba(255, 255, 255, 0.1),
    inset 0 0 0 1px rgba(15, 23, 42, 0.08),
    0 4px 10px rgba(15, 23, 42, 0.06);
}

.share-track--empty {
  align-items: center;
  justify-content: center;
  background: linear-gradient(90deg, rgba(148, 163, 184, 0.10), rgba(148, 163, 184, 0.06));
  color: var(--text-muted);
  font-size: 10px;
}

.share-segment {
  position: relative;
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: 10px;
  min-width: 0;
  outline: none;
  cursor: pointer;
  z-index: 1;
  border-top-left-radius: var(--segment-radius-start);
  border-bottom-left-radius: var(--segment-radius-start);
  border-top-right-radius: var(--segment-radius-end);
  border-bottom-right-radius: var(--segment-radius-end);
  transition: transform 0.18s ease, box-shadow 0.18s ease, filter 0.18s ease;
}

.share-segment::before {
  content: '';
  position: absolute;
  inset: 0;
  border-radius: inherit;
  background: linear-gradient(180deg, rgba(255, 255, 255, 0.18), rgba(255, 255, 255, 0.02));
  opacity: 0;
  pointer-events: none;
  transition: opacity 0.18s ease;
}

.share-segment:hover,
.share-segment:focus-visible {
  filter: saturate(1.04) brightness(1.03);
  transform: translateY(-1px);
  box-shadow: inset 0 0 0 1px rgba(255, 255, 255, 0.32);
}

.share-segment:hover::before,
.share-segment:focus-visible::before {
  opacity: 1;
}

.share-segment::after {
  content: attr(data-tooltip);
  position: absolute;
  left: 50%;
  top: calc(100% + 8px);
  transform: translateX(-50%) translateY(-4px);
  min-width: max-content;
  max-width: 220px;
  padding: 5px 8px;
  border-radius: 7px;
  background: rgba(15, 23, 42, 0.94);
  color: #f8fafc;
  font-size: 10px;
  line-height: 1.35;
  pointer-events: none;
  opacity: 0;
  transition: opacity 0.16s ease, transform 0.16s ease;
  box-shadow: 0 8px 20px rgba(15, 23, 42, 0.18);
  z-index: 3;
}

.share-row--last .share-segment::after {
  top: auto;
  bottom: calc(100% + 8px);
  transform: translateX(-50%) translateY(4px);
}

.share-segment:hover::after,
.share-segment:focus-visible::after {
  opacity: 1;
  transform: translateX(-50%) translateY(0);
}

.share-segment:focus-visible {
  box-shadow:
    inset 0 0 0 1px rgba(255, 255, 255, 0.54),
    0 0 0 2px var(--segment-focus);
}

html[data-theme='light'] .share-legend-swatch {
  box-shadow: inset 0 0 0 1px rgba(215, 203, 203, 0.78);
}

html[data-theme='light'] .share-track {
  box-shadow:
    inset 0 1px 0 rgba(255, 255, 255, 0.72),
    inset 0 0 0 1px rgba(195, 208, 223, 0.52),
    0 4px 12px rgba(148, 163, 184, 0.16);
}

html[data-theme='light'] .share-segment::after {
  background: rgba(255, 255, 255, 0.98);
  color: #0f172a;
  box-shadow: 0 10px 24px rgba(129, 145, 166, 0.2);
}

@container (max-width: 699px) {
  .share-card-body {
    min-height: auto;
    gap: 12px;
  }

  .share-row {
    padding: 6px 0;
  }

  .share-track {
    width: 100%;
  }

  .share-row-head {
    flex-direction: column;
    align-items: flex-start;
    gap: 4px;
  }
}
</style>
