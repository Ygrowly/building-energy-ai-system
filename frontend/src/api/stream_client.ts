/**
 * SSE 流式客户端。
 *
 * 解析后端推送的 SSE 事件，按类型分发到对应处理器。
 * 事件类型：thinking | text | artifact | error | done
 */
import { generateId } from '@/utils/id'

export type SseEventType = 'thinking' | 'text' | 'artifact' | 'evidence' | 'error' | 'done'

export interface ThinkingEvent {
  type: 'thinking'
  agent: string
  message: string
  hop_count: number
  /** LLM 流式推理 token（存在时为推理内容片段，追加到当前步骤） */
  content?: string
  /** 后端基于 intent 动态生成的显示标签，优先于前端静态映射 */
  display_label?: string
}

export interface TextEvent {
  type: 'text'
  content: string
  is_final: boolean
}

export interface ArtifactEvent {
  type: 'artifact'
  widget?: string
  component_type?: string
  title?: string
  data_payload?: unknown
  source_info?: Record<string, unknown>
  artifact_id?: string
  /** AI 触发报表下载时后端直接返回的下载 URL（report-download widget 专用） */
  download_url?: string
  /** 锚点关键词，用于将 artifact 嵌入到 AI 文本中对应指标段落后面 */
  anchor?: string
}

export interface ErrorEvent {
  type: 'error'
  message: string
  tool_name?: string
  recoverable: boolean
}

export interface EvidenceEvent {
  type: 'evidence'
  sources: EvidenceSource[]
}

export interface EvidenceSource {
  type: 'rag'
  source_doc: string
  page?: number | null
  similarity?: number | null
  parent_section?: string | null
  doc_category?: string | null
  backend?: string | null
}

export interface DoneEvent {
  type: 'done'
  session_id: string
  hop_count: number
}

export type SseEvent = ThinkingEvent | TextEvent | ArtifactEvent | EvidenceEvent | ErrorEvent | DoneEvent

export interface StreamHandlers {
  onThinking?: (e: ThinkingEvent) => void
  onText?: (e: TextEvent) => void
  onArtifact?: (e: ArtifactEvent) => void
  onEvidence?: (e: EvidenceEvent) => void
  onError?: (e: ErrorEvent) => void
  onDone?: (e: DoneEvent) => void
  onNetworkError?: (err: Error) => void
}

/**
 * 发起对话请求，解析 SSE 流，按事件类型分发回调。
 * 返回 sessionId（从响应头读取）。
 */
// 由 main.ts 注入，和 http.ts 共用同一个 auth provider
let _getToken: () => string | null = () => null
const API_BASE = (import.meta.env.VITE_API_BASE as string | undefined) ?? ''
export function setStreamAuthProvider(getToken: () => string | null) {
  _getToken = getToken
}

export async function sendChatMessage(
  message: string,
  sessionId: string | null,
  handlers: StreamHandlers,
  enableWebSearch = false,
  thinkingMode: 'fast' | 'deep' = 'fast',
  signal?: AbortSignal,
  displayMessage?: string,
): Promise<string> {
  const token = _getToken()
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    Accept: 'text/event-stream',
    'Cache-Control': 'no-cache',
  }
  if (token) headers['Authorization'] = `Bearer ${token}`

  const response = await fetch(`${API_BASE}/api/chat`, {
    method: 'POST',
    headers,
    body: JSON.stringify({
      message,
      display_message: displayMessage,
      session_id: sessionId,
      enable_web_search: enableWebSearch,
      thinking_mode: thinkingMode,
    }),
    signal,
  })

  if (!response.ok) {
    throw new Error(`HTTP ${response.status}: ${await response.text()}`)
  }

  const contentType = response.headers.get('Content-Type') ?? response.headers.get('content-type') ?? ''
  if (!contentType.toLowerCase().includes('text/event-stream')) {
    const preview = await response.text().catch(() => '')
    throw new Error(
      `聊天接口未返回 SSE 流，Content-Type=${contentType || 'unknown'}${preview ? `，响应预览：${preview.slice(0, 120)}` : ''}`,
    )
  }

  const newSessionId = response.headers.get('x-session-id') ?? sessionId ?? generateId()
  const reader = response.body!.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  let sawDoneEvent = false

  try {
    while (true) {
      const { done, value } = await reader.read()
      if (done) break

      buffer += decoder.decode(value, { stream: true })
      const lines = buffer.split('\n')
      buffer = lines.pop() ?? ''

      for (const line of lines) {
        if (!line.startsWith('data: ')) continue
        const raw = line.slice(6).trim()
        if (!raw) continue
        try {
          const event = JSON.parse(raw) as SseEvent
          if (event.type === 'done') sawDoneEvent = true
          dispatchEvent(event, handlers)
        } catch {
          // 忽略无效 JSON 行
        }
      }
    }
    if (!sawDoneEvent) {
      throw new Error('聊天 SSE 流提前结束，未收到 done 事件')
    }
  } catch (err) {
    handlers.onNetworkError?.(err as Error)
  }

  return newSessionId
}

function dispatchEvent(event: SseEvent, handlers: StreamHandlers) {
  switch (event.type) {
    case 'thinking': handlers.onThinking?.(event); break
    case 'text':     handlers.onText?.(event); break
    case 'artifact': handlers.onArtifact?.(event); break
    case 'evidence': handlers.onEvidence?.(event); break
    case 'error':    handlers.onError?.(event); break
    case 'done':     handlers.onDone?.(event); break
  }
}

/** 审批工单 */
export async function approveWorkOrder(
  sessionId: string,
  ticketId: string,
  approved: boolean,
  reason?: string,
) {
  const token = _getToken()
  const headers: Record<string, string> = { 'Content-Type': 'application/json' }
  if (token) headers['Authorization'] = `Bearer ${token}`

  const res = await fetch(`${API_BASE}/api/chat/approve`, {
    method: 'POST',
    headers,
    body: JSON.stringify({ session_id: sessionId, ticket_id: ticketId, approved, reason }),
  })
  return res.json()
}
