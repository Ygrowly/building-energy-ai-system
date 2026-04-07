import { marked } from 'marked'

marked.use({ breaks: true, gfm: true })

const PLACEHOLDER_RE = /<<CHART:[^>]*>>/g
const TOOL_CALL_RE = /\b(render_ui_component|create_work_order_draft|generate_report)\s*\([\s\S]*?\)\s*/g

function escapeRawHtml(text: string): string {
  // `marked` keeps raw HTML by default. Escaping angle brackets prevents
  // model/user-provided HTML from breaking out of chat bubbles or reports.
  return text.replace(/</g, '&lt;').replace(/>/g, '&gt;')
}

export function renderMarkdown(text: string): string {
  let clean = text.replace(PLACEHOLDER_RE, '')
  clean = clean.replace(TOOL_CALL_RE, '')
  clean = clean.replace(/([\u2000-\u9fff\uff00-\uffef])(\*\*)/g, '$1\u200B$2')
  clean = clean.replace(/(\*\*)([\u2000-\u9fff\uff00-\uffef])/g, '$1\u200B$2')
  clean = escapeRawHtml(clean)

  let html = marked.parse(clean, { async: false }) as string
  html = html.replace(/\*\*([^*]+?)\*\*/g, '<strong>$1</strong>')
  return html
}
