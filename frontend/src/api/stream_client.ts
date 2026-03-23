/**
 * SSE 流式客户端。
 *
 * 解析后端推送的 SSE 事件，按类型分发到对应处理器。
 * 事件类型：thinking | text | artifact | error | done
 */

export type SseEventType = 'thinking' | 'text' | 'artifact' | 'error' | 'done'

export interface ThinkingEvent {
  type: 'thinking'
  agent: string
  message: string
  hop_count: number
  /** LLM 流式推理 token（存在时为推理内容片段，追加到当前步骤） */
  content?: string
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
}

export interface ErrorEvent {
  type: 'error'
  message: string
  tool_name?: string
  recoverable: boolean
}

export interface DoneEvent {
  type: 'done'
  session_id: string
  hop_count: number
}

export type SseEvent = ThinkingEvent | TextEvent | ArtifactEvent | ErrorEvent | DoneEvent

export interface StreamHandlers {
  onThinking?: (e: ThinkingEvent) => void
  onText?: (e: TextEvent) => void
  onArtifact?: (e: ArtifactEvent) => void
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
export function setStreamAuthProvider(getToken: () => string | null) {
  _getToken = getToken
}

export async function sendChatMessage(
  message: string,
  sessionId: string | null,
  handlers: StreamHandlers,
  enableWebSearch = false,
): Promise<string> {
  const token = _getToken()
  const headers: Record<string, string> = { 'Content-Type': 'application/json' }
  if (token) headers['Authorization'] = `Bearer ${token}`

  const response = await fetch('/api/chat', {
    method: 'POST',
    headers,
    body: JSON.stringify({ message, session_id: sessionId, enable_web_search: enableWebSearch }),
  })

  if (!response.ok) {
    throw new Error(`HTTP ${response.status}: ${await response.text()}`)
  }

  const newSessionId = response.headers.get('x-session-id') ?? sessionId ?? crypto.randomUUID()
  const reader = response.body!.getReader()
  const decoder = new TextDecoder()
  let buffer = ''

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
          dispatchEvent(event, handlers)
        } catch {
          // 忽略无效 JSON 行
        }
      }
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

  const res = await fetch('/api/chat/approve', {
    method: 'POST',
    headers,
    body: JSON.stringify({ session_id: sessionId, ticket_id: ticketId, approved, reason }),
  })
  return res.json()
}
