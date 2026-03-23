/** 首页大屏 ECharts 主题与公共常量 */

export const MC = {
  blue: '#7b9fc7',
  sage: '#7aaa8e',
  terra: '#c4956a',
  lav: '#9b8fc4',
  rose: '#c4909a',
  teal: '#7abcb3',
}

export function gc() {
  const dark = document.documentElement.dataset.theme !== 'light'
  return {
    grid: dark ? '#1a1c28' : '#d0e8d8',
    axis: dark ? '#6b7a9a' : '#6a8c72',
    ttBg: dark ? '#101118' : '#ffffff',
    ttBr: dark ? '#1a1c28' : '#d0e8d8',
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
