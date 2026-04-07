<script setup lang="ts">
import { computed } from 'vue'
import { Icon } from '@iconify/vue'
import {
  HOME_BUILDING_COLORS,
  HOME_BUILDING_ORDER,
  type HomeBuildingType,
} from '@/utils/homeCharts'

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

const FALLBACK_BUILDING_LABELS: Record<HomeBuildingType, string> = {
  Education: '教学楼',
  Office: '办公楼',
  'Public services': '公共楼',
}

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
      color: HOME_BUILDING_COLORS[buildingType],
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
  const prevColor = segments[index - 1]?.color ?? segment.color
  const nextColor = segments[index + 1]?.color
  const background = nextColor
    ? `linear-gradient(90deg, ${prevColor} 0%, ${segment.color} 28%, ${segment.color} 62%, ${nextColor} 100%)`
    : segment.color

  return {
    width: `${segment.percent}%`,
    background,
  }
}
</script>

<template>
  <div class="cpanel overview-share-panel">
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
            :style="{ backgroundColor: HOME_BUILDING_COLORS[buildingType] }"
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
  color: var(--border-accent, #7aaa8e);
}

.share-row-total {
  flex-shrink: 0;
  font-size: 11px;
  color: var(--text-secondary);
}

.share-track {
  position: relative;
  display: flex;
  width: 100%;
  min-height: 12px;
  overflow: visible;
  border-radius: 999px;
  background: rgba(148, 163, 184, 0.12);
  box-shadow: inset 0 0 0 1px rgba(148, 163, 184, 0.06);
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
  min-height: 12px;
  min-width: 0;
  outline: none;
  cursor: pointer;
  transition: filter 0.18s ease;
}

.share-segment:first-child {
  border-top-left-radius: 999px;
  border-bottom-left-radius: 999px;
}

.share-segment:last-child {
  border-top-right-radius: 999px;
  border-bottom-right-radius: 999px;
}

.share-segment:hover,
.share-segment:focus-visible {
  filter: saturate(1.06) brightness(1.02);
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
  box-shadow: inset 0 0 0 2px rgba(255, 255, 255, 0.85);
}

html[data-theme='light'] .share-legend-swatch {
  box-shadow: inset 0 0 0 1px rgba(255, 255, 255, 0.78);
}

html[data-theme='light'] .share-track {
  background: #eef2f6;
  box-shadow: inset 0 0 0 1px rgba(226, 232, 240, 0.58);
}

html[data-theme='light'] .share-segment::after {
  background: rgba(255, 255, 255, 0.98);
  color: #0f172a;
  box-shadow: 0 10px 24px rgba(148, 163, 184, 0.2);
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
