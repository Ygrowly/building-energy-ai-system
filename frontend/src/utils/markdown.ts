import { marked } from 'marked'

marked.use({ breaks: true, gfm: true })

const PLACEHOLDER_RE = /<<CHART:[^>]*>>/g
const PLACEHOLDER_CAPTURE_RE = /<<CHART:([^>]+)>>/g
const TOOL_CALL_RE = /\b(render_ui_component|create_work_order_draft|generate_report)\s*\([\s\S]*?\)\s*/g

interface RenderMarkdownOptions {
  preservePlaceholders?: boolean
}

function escapeRawHtml(text: string): string {
  // `marked` keeps raw HTML by default. Escaping angle brackets prevents
  // model/user-provided HTML from breaking out of chat bubbles or reports.
  return text.replace(/</g, '&lt;').replace(/>/g, '&gt;')
}

function injectChartSlots(text: string, preservePlaceholders: boolean): string {
  const slots: string[] = []
  const tokenized = text.replace(PLACEHOLDER_CAPTURE_RE, (_, anchor: string) => {
    const slotIndex = slots.push(anchor) - 1
    return `\n\n__CHART_SLOT_${slotIndex}__\n\n`
  })

  return tokenized.replace(/__CHART_SLOT_(\d+)__/g, (_, rawIndex: string) => {
    if (!preservePlaceholders) return ''
    const anchor = slots[Number(rawIndex)] ?? ''
    return `<div data-chart-slot="${encodeURIComponent(anchor)}"></div>`
  })
}

export function renderMarkdown(text: string, options: RenderMarkdownOptions = {}): string {
  const preservePlaceholders = options.preservePlaceholders ?? false
  let clean = text
  if (PLACEHOLDER_RE.test(clean)) {
    PLACEHOLDER_RE.lastIndex = 0
    clean = injectChartSlots(clean, preservePlaceholders)
  }
  clean = clean.replace(TOOL_CALL_RE, '')
  clean = clean.replace(/([\u2000-\u9fff\uff00-\uffef])(\*\*)/g, '$1\u200B$2')
  clean = clean.replace(/(\*\*)([\u2000-\u9fff\uff00-\uffef])/g, '$1\u200B$2')
  clean = escapeRawHtml(clean)
  if (preservePlaceholders) {
    clean = clean.replace(
      /&lt;div data-chart-slot="([^"]+)"&gt;&lt;\/div&gt;/g,
      '<div data-chart-slot="$1"></div>',
    )
  }

  let html = marked.parse(clean, { async: false }) as string
  html = html.replace(/\*\*([^*]+?)\*\*/g, '<strong>$1</strong>')
  return html
}
