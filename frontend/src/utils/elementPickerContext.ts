import { getInstanceByDom } from '@/utils/echarts'

export interface PickedElementContext {
  id: string
  type: string
  title: string
  subtitle?: string
  pageTitle?: string
  sectionTitle?: string
  purpose?: string
  businessMeaning?: string
  textSummary?: string
  dataSummary?: string[]
}

const METRIC_DETAIL_RE = /(\d|kWh|kW|m³|m3|℃|COP|占比|同比|环比|总用电|总用水|总能耗|空调能耗)/i

const SECTION_TITLE_SELECTORS = [
  '[data-pick-section-title]',
  '.page-title',
  '.section-title',
  '.module-title',
  '.panel-title',
  '.card-title',
  '.cpanel-title',
  'h1',
  'h2',
  'h3',
  'h4',
]

function normalizeText(value: string | null | undefined): string {
  return String(value ?? '')
    .replace(/\s+/g, ' ')
    .replace(/[：:]\s*$/, '')
    .trim()
}

function truncate(value: string, max = 180): string {
  if (value.length <= max) return value
  return `${value.slice(0, Math.max(0, max - 1))}…`
}

function dedupe(items: Array<string | null | undefined>, max = 6): string[] {
  const seen = new Set<string>()
  const result: string[] = []
  for (const item of items) {
    const normalized = normalizeText(item)
    if (!normalized || seen.has(normalized)) continue
    seen.add(normalized)
    result.push(normalized)
    if (result.length >= max) break
  }
  return result
}

function findSectionTitle(el: HTMLElement): string {
  let current: HTMLElement | null = el
  while (current) {
    for (const selector of SECTION_TITLE_SELECTORS) {
      const candidate = current.querySelector<HTMLElement>(selector)
      const text = normalizeText(candidate?.innerText || candidate?.textContent)
      if (text) return truncate(text, 80)
    }

    let sibling: HTMLElement | null = current.previousElementSibling as HTMLElement | null
    while (sibling) {
      for (const selector of SECTION_TITLE_SELECTORS) {
        const candidate = sibling.matches(selector)
          ? sibling
          : sibling.querySelector<HTMLElement>(selector)
        const text = normalizeText(candidate?.innerText || candidate?.textContent)
        if (text) return truncate(text, 80)
      }
      sibling = sibling.previousElementSibling as HTMLElement | null
    }

    current = current.parentElement
  }
  return ''
}

function inferPurpose(type: string, title: string, subtitle: string): string {
  const combined = `${title} ${subtitle}`.toLowerCase()
  if (combined.includes('占比') || combined.includes('构成')) {
    return '用于展示不同楼宇或指标之间的构成占比，帮助判断分配结构是否失衡。'
  }
  if (combined.includes('额定') || combined.includes('基线') || combined.includes('期望')) {
    return '用于对比实际运行值与额定/基线期望值，帮助识别运行偏差和超限程度。'
  }
  if (combined.includes('排行')) {
    return '用于做横向排序比较，快速识别高值、低值和异常样本。'
  }
  if (combined.includes('热力图')) {
    return '用于展示二维时段分布，帮助识别全天节律、高峰时段和持续异常。'
  }
  if (type === 'kpi') {
    return '用于概括展示当前最关键的单项指标、偏差或状态结果。'
  }
  if (type === 'timeline') {
    return '用于串联事件发生顺序、时间节点和状态变化。'
  }
  if (type === 'heatmap') {
    return '用于观察不同日期或时段上的分布密度、节律和异常聚集。'
  }
  if (type === 'chart') {
    return '用于展示指标趋势、对比关系或结构分布，支持从数据变化中解释业务现象。'
  }
  return '用于补充当前页面的状态说明和业务判断依据。'
}

function inferBusinessMeaning(title: string, subtitle: string): string {
  const combined = `${title} ${subtitle}`.toLowerCase()
  if (combined.includes('标准煤')) {
    return '“标准煤”表示把电、水等不同能源折算为统一口径后的综合能耗，便于横向比较总体负荷。'
  }
  if (combined.includes('额定') || combined.includes('期望')) {
    return '“额定/期望”通常表示系统基线、设计值或模型期望，“实际”表示真实运行数据，两者差值反映偏离程度。'
  }
  if (combined.includes('占比')) {
    return '占比越高，说明对应楼宇或子系统在当前总量中的贡献越大，需要结合业务场景判断是否合理。'
  }
  if (combined.includes('排行')) {
    return '排名靠前通常意味着该时段或对象对总能耗贡献更大，需要结合日期、天气和使用场景解释。'
  }
  return subtitle
    ? `该元素重点说明：${subtitle}`
    : '需要结合页面上下文解释指标口径、业务意义和数据变化。'
}

function extractTextSummary(el: HTMLElement, title: string, subtitle: string): string {
  const text = normalizeText(el.innerText || el.textContent)
  if (!text) return ''
  let summary = text
  for (const token of dedupe([title, subtitle], 2)) {
    if (summary.startsWith(token)) {
      summary = summary.slice(token.length).trim()
    }
  }
  return truncate(summary, 260)
}

function findChartRoot(el: HTMLElement): HTMLElement | null {
  const candidates = [el, ...Array.from(el.querySelectorAll<HTMLElement>('*'))]
  for (const candidate of candidates) {
    try {
      if (getInstanceByDom(candidate)) return candidate
    } catch {
      // ignore stale or non-chart nodes
    }
  }
  return null
}

function toNumber(value: unknown): number | null {
  if (typeof value === 'number' && Number.isFinite(value)) return value
  if (typeof value === 'string') {
    const parsed = Number(value)
    return Number.isFinite(parsed) ? parsed : null
  }
  return null
}

function summarizeSeriesData(
  seriesName: string,
  data: unknown[],
  axisLabels: string[],
): string {
  const samples: string[] = []
  const numericValues: number[] = []

  data.slice(0, 4).forEach((item, index) => {
    if (Array.isArray(item) && item.length >= 2) {
      const label = normalizeText(String(item[0]))
      const value = toNumber(item[1])
      if (label && value != null) {
        samples.push(`${label}=${value}`)
        numericValues.push(value)
      }
      return
    }

    if (item && typeof item === 'object') {
      const record = item as Record<string, unknown>
      const label = normalizeText(String(record.name ?? axisLabels[index] ?? ''))
      const value = toNumber(record.value)
      if (value != null) {
        samples.push(label ? `${label}=${value}` : String(value))
        numericValues.push(value)
      }
      return
    }

    const primitive = toNumber(item)
    if (primitive != null) {
      const label = axisLabels[index]
      samples.push(label ? `${label}=${primitive}` : String(primitive))
      numericValues.push(primitive)
    }
  })

  data.forEach((item) => {
    if (Array.isArray(item) && item.length >= 2) {
      const value = toNumber(item[1])
      if (value != null) numericValues.push(value)
      return
    }
    if (item && typeof item === 'object') {
      const value = toNumber((item as Record<string, unknown>).value)
      if (value != null) numericValues.push(value)
      return
    }
    const primitive = toNumber(item)
    if (primitive != null) numericValues.push(primitive)
  })

  const numericSummary = numericValues.length > 0
    ? `最小 ${Math.min(...numericValues)}，最大 ${Math.max(...numericValues)}`
    : ''

  return truncate(
    [
      `系列“${seriesName || '未命名'}”共 ${data.length} 个点`,
      numericSummary,
      samples.length ? `样例：${samples.join('、')}` : '',
    ].filter(Boolean).join('；'),
    180,
  )
}

function extractChartSummary(el: HTMLElement): string[] {
  const chartRoot = findChartRoot(el)
  if (!chartRoot) return []

  try {
    const option = getInstanceByDom(chartRoot)?.getOption() as Record<string, unknown> | undefined
    if (!option) return []

    const xAxis = Array.isArray(option.xAxis) ? option.xAxis[0] : option.xAxis
    const axisLabels = Array.isArray((xAxis as Record<string, unknown> | undefined)?.data)
      ? ((xAxis as Record<string, unknown>).data as unknown[]).map((item) => normalizeText(String(item)))
      : []

    const legendData = Array.isArray(option.legend)
      ? option.legend.flatMap((item) => {
          const data = (item as Record<string, unknown>).data
          return Array.isArray(data) ? data.map((value) => normalizeText(String(value))) : []
        })
      : Array.isArray((option.legend as Record<string, unknown> | undefined)?.data)
        ? ((option.legend as Record<string, unknown>).data as unknown[]).map((value) => normalizeText(String(value)))
        : []

    const seriesList = Array.isArray(option.series) ? option.series : []
    const seriesSummary = seriesList
      .slice(0, 3)
      .map((series) => {
        const record = series as Record<string, unknown>
        const name = normalizeText(String(record.name ?? ''))
        const data = Array.isArray(record.data) ? record.data : []
        return data.length ? summarizeSeriesData(name, data, axisLabels) : ''
      })
      .filter(Boolean)

    return dedupe([
      legendData.length ? `图例：${legendData.join('、')}` : '',
      axisLabels.length ? `横轴样例：${axisLabels.slice(0, 4).join('、')}` : '',
      ...seriesSummary,
    ])
  } catch {
    return []
  }
}

function extractStructuredSummary(el: HTMLElement): string[] {
  const rows = Array.from(el.querySelectorAll<HTMLTableRowElement>('table tr'))
    .slice(0, 4)
    .map((row) => {
      const cells = Array.from(row.querySelectorAll<HTMLElement>('th,td'))
        .map((cell) => normalizeText(cell.innerText || cell.textContent))
        .filter(Boolean)
      return cells.length ? truncate(cells.join(' | '), 140) : ''
    })

  const items = Array.from(el.querySelectorAll<HTMLElement>('li'))
    .slice(0, 4)
    .map((item) => truncate(normalizeText(item.innerText || item.textContent), 120))

  return dedupe([...rows, ...items], 4)
}

function extractAttributeSummary(el: HTMLElement): string[] {
  const candidates = [el, ...Array.from(el.querySelectorAll<HTMLElement>('[aria-label],[data-tooltip],[title]'))]

  return dedupe(
    candidates.flatMap((node) => {
      const texts = [
        node.getAttribute('aria-label'),
        node.dataset.tooltip,
        node.getAttribute('title'),
      ]

      return texts
        .map((value) => truncate(normalizeText(value), 140))
        .filter((value) => value && METRIC_DETAIL_RE.test(value))
    }),
    12,
  )
}

export function buildPickedElementContext(el: HTMLElement): PickedElementContext {
  const title = normalizeText(el.dataset.pickTitle || '') || '未命名元素'
  const subtitle = normalizeText(el.dataset.pickSubtitle || '')
  const type = normalizeText(el.dataset.pickType || '') || 'unknown'

  const sectionTitle = normalizeText(el.dataset.pickSectionTitle || '') || findSectionTitle(el)
  const purpose = normalizeText(el.dataset.pickPurpose || '') || inferPurpose(type, title, subtitle)
  const businessMeaning = normalizeText(el.dataset.pickBusinessMeaning || '')
    || inferBusinessMeaning(title, subtitle)

  const dataSummary = dedupe([
    ...extractChartSummary(el),
    ...extractAttributeSummary(el),
    ...extractStructuredSummary(el),
  ], 12)

  return {
    id: normalizeText(el.dataset.pickId || ''),
    type,
    title,
    subtitle: subtitle || undefined,
    pageTitle: truncate(normalizeText(document.title), 80) || undefined,
    sectionTitle: sectionTitle || undefined,
    purpose: purpose || undefined,
    businessMeaning: businessMeaning || undefined,
    textSummary: extractTextSummary(el, title, subtitle) || undefined,
    dataSummary: dataSummary.length ? dataSummary : undefined,
  }
}

export function buildElementAnalysisPrompt(
  element: PickedElementContext,
  question: string,
): string {
  const lines = [
    '[页面元素分析上下文]',
    `元素标题：${element.title}`,
    `元素类型：${element.type}`,
  ]

  if (element.pageTitle) lines.push(`页面：${element.pageTitle}`)
  if (element.sectionTitle) lines.push(`所属模块：${element.sectionTitle}`)
  if (element.subtitle) lines.push(`元素说明：${element.subtitle}`)
  if (element.purpose) lines.push(`元素作用：${element.purpose}`)
  if (element.businessMeaning) lines.push(`业务含义：${element.businessMeaning}`)
  if (element.textSummary) lines.push(`页面可见信息：${element.textSummary}`)

  if (element.dataSummary?.length) {
    lines.push('元素详细数据（以下均为页面上已出现的具体数据，分析时必须优先引用，禁止改写成“若…则…”的假设表达）：')
    element.dataSummary.forEach((item) => lines.push(`- ${item}`))
  }

  lines.push(
    '回答要求：先解释这个页面元素在看什么，再直接基于上述具体数值分析当前分布、主次关系、差值和可能反映的问题；如果页面已给出占比/数值，必须引用这些具体值；只有页面确实没给某项关键数据时，才能明确说明缺失，禁止自行假设 40%/50%/60% 这类阈值；不要复述本提示词，也不要在回答里显式输出“[页面元素分析上下文]”等字样。',
    '[用户问题]',
    question,
  )

  return lines.join('\n')
}

export function buildElementDisplayText(
  element: PickedElementContext,
  question: string,
): string {
  return `【${element.title}页面元素】${question}`
}
