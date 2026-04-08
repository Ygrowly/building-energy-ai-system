/** 首页大屏 ECharts 主题与公共常量 */

/** 主色板 — 高饱和、明确对比、深浅主题均可辨 */
import { BUILDING_TYPE_ORDER, type BuildingType } from '@/constants/buildings'

export const MC = {
  blue:  '#4b9ef5',  // 鲜蓝  — 实际用电 / 供水
  sage:  '#10d980',  // 鲜翠绿 — 国标期望
  terra: '#f59e0b',  // 琥珀橙 — 室外温度
  lav:   '#f97316',  // 橙红   — 回水（与供水蓝形成冷暖对比）
  rose:  '#f472b6',  // 玫红   — 预留
  teal:  '#22d3ee',  // 青色   — 周末柱 / 预留
}

export const HOME_BUILDING_ORDER = BUILDING_TYPE_ORDER
export type HomeBuildingType = BuildingType

export const HOME_BUILDING_COLORS: Record<HomeBuildingType, string> = {
  Education: MC.blue,
  Office: MC.sage,
  'Public services': MC.terra,
}

export function gc() {
  const dark = document.documentElement.dataset.theme !== 'light'
  return {
    grid:   dark ? '#252836' : '#e2ece5',
    axis:   dark ? '#7a8aaa' : '#5a7a64',
    ttBg:   dark ? '#101118' : '#ffffff',
    ttBr:   dark ? '#252836' : '#d0e8d8',
    ttText: dark ? '#dde3f0' : '#0f2818',
    dark,
  }
}

/** 国标 GB/T 51161-2016 基准 EUI (kWh/㎡·年) */
export const EUI_BASELINE: Record<string, number> = {
  Office: 75,
  Education: 50,
  'Public services': 65,
}

export const STANDARD_COAL_ELECTRICITY_FACTOR = 0.1229
export const STANDARD_COAL_WATER_FACTOR = 0.085
export const ELECTRICITY_CARBON_FACTOR = 0.5703

export function isoDate(d: Date): string {
  return d.toISOString().slice(0, 10)
}

export interface HourlyPoint {
  hour: number
  avg_value: number
  sample_count?: number
}

export interface WeekdayPoint {
  weekday: number
  label?: string
  avg_value: number
}

/**
 * 由小时曲线 + 星期曲线合成 7×24 热力图强度（无真实逐格数据时的合理近似）
 */
export function buildHeatmapCells(
  hourly: HourlyPoint[],
  weekly: WeekdayPoint[],
): Array<{ d: number; h: number; v: number }> {
  const hAvg = Array.from({ length: 24 }, (_, h) => {
    const row = hourly.find((x) => x.hour === h)
    return row?.avg_value ?? 0
  })
  const wVals = weekly.map((w) => w.avg_value).filter((v) => v > 0)
  const wMean = wVals.length ? wVals.reduce((a, b) => a + b, 0) / wVals.length : 1
  const cells: Array<{ d: number; h: number; v: number }> = []
  for (let d = 0; d < 7; d++) {
    const isoDow = d + 1
    const wdProfile = weekly.find((w) => w.weekday === isoDow)?.avg_value ?? wMean
    const factor = wMean > 1e-9 ? wdProfile / wMean : 1
    for (let h = 0; h < 24; h++) {
      const base = hAvg[h] ?? 0
      cells.push({ d, h, v: parseFloat((base * factor).toFixed(2)) })
    }
  }
  return cells
}
