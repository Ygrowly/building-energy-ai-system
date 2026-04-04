/** 数字格式化：超过万显示 x.x万 */
export function formatNum(n: number | null | undefined): string {
  if (n === undefined || n === null) return '--'
  if (n >= 10000) return (n / 10000).toFixed(1) + '万'
  if (n >= 100) return n.toFixed(0)
  return n.toFixed(1)
}

/** 百分比变化格式化：+12.3% / -5.1% / -- */
export function formatPct(pct: number | null | undefined): string {
  if (pct === undefined || pct === null) return '--'
  const prefix = pct > 0 ? '+' : ''
  return `${prefix}${pct.toFixed(1)}%`
}

/** 指标数值格式化：统一保留 1 位小数，避免展示长浮点尾数 */
export function formatMetricValue(value: number | null | undefined): string {
  if (value === undefined || value === null || Number.isNaN(value)) return '--'
  return value.toFixed(1)
}

/** 按接口原始时刻显示，避免浏览器自动时区换算造成 8 小时偏移 */
export function formatServerDateTime(iso: string | null | undefined): string {
  if (!iso) return '--'
  const normalized = iso
    .replace('T', ' ')
    .replace(/(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$/, '')
  return normalized.slice(0, 16)
}

/** 相对时间：刚刚 / N分钟前 / N小时前 / M/D HH:mm */
export function formatRelativeTime(iso: string | null | undefined): string {
  if (!iso) return '--'
  const d = new Date(iso)
  const diff = (Date.now() - d.getTime()) / 1000
  if (diff < 60) return '刚刚'
  if (diff < 3600) return `${Math.floor(diff / 60)}分钟前`
  if (diff < 86400) return `${Math.floor(diff / 3600)}小时前`
  return `${d.getMonth() + 1}/${d.getDate()} ${d.getHours().toString().padStart(2, '0')}:${d.getMinutes().toString().padStart(2, '0')}`
}

/** 完整日期时间 */
export function formatDateTime(iso: string | null | undefined): string {
  return formatServerDateTime(iso)
}

/** 仅日期 */
export function formatDate(iso: string | null | undefined): string {
  if (!iso) return '--'
  return formatServerDateTime(iso).slice(0, 10)
}
