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
  if (!iso) return '--'
  const d = new Date(iso)
  const pad = (n: number) => n.toString().padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
}

/** 仅日期 */
export function formatDate(iso: string | null | undefined): string {
  if (!iso) return '--'
  const d = new Date(iso)
  const pad = (n: number) => n.toString().padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`
}
