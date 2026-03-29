/**
 * AI 对话流式客户端（uni-app 版）
 *
 * 策略：
 *  - H5 平台：使用原生 fetch + ReadableStream，与网页端一致
 *  - App 平台：使用 uni.request enableChunked 模式读取 SSE 数据块
 *
 * SSE 事件类型：thinking | text | artifact | error | done
 */

const BASE_URL = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000'

export type SseEventType = 'thinking' | 'text' | 'artifact' | 'error' | 'done'

export interface TextEvent    { type: 'text';    content: string; is_final: boolean }
export interface ThinkingEvent { type: 'thinking'; agent: string; message: string; hop_count: number; content?: string }
export interface ErrorEvent   { type: 'error';   message: string; recoverable: boolean }
export interface DoneEvent    { type: 'done';    session_id: string; hop_count: number }
export type SseEvent = ThinkingEvent | TextEvent | ErrorEvent | DoneEvent

export interface StreamHandlers {
  onThinking?: (e: ThinkingEvent) => void
  onText?:     (e: TextEvent) => void
  onError?:    (e: ErrorEvent) => void
  onDone?:     (e: DoneEvent) => void
  onNetworkError?: (err: Error) => void
}

function dispatchEvent(event: SseEvent, handlers: StreamHandlers) {
  switch (event.type) {
    case 'thinking': handlers.onThinking?.(event as ThinkingEvent); break
    case 'text':     handlers.onText?.(event as TextEvent);         break
    case 'error':    handlers.onError?.(event as ErrorEvent);       break
    case 'done':     handlers.onDone?.(event as DoneEvent);         break
  }
}

function parseChunk(chunk: string, handlers: StreamHandlers) {
  const lines = chunk.split('\n')
  for (const line of lines) {
    if (!line.startsWith('data: ')) continue
    const raw = line.slice(6).trim()
    if (!raw) continue
    try {
      const event = JSON.parse(raw) as SseEvent
      dispatchEvent(event, handlers)
    } catch { /* ignore malformed */ }
  }
}

// ---- H5 平台：原生 fetch 流式读取 ----
async function sendH5(
  message: string,
  sessionId: string | null,
  handlers: StreamHandlers,
  workOrderContext?: string,
): Promise<string> {
  const token = uni.getStorageSync('access_token')
  const headers: Record<string, string> = { 'Content-Type': 'application/json' }
  if (token) headers['Authorization'] = `Bearer ${token}`

  const body: Record<string, unknown> = { message, session_id: sessionId }
  if (workOrderContext) body['system_hint'] = workOrderContext

  const response = await fetch(`${BASE_URL}/api/chat`, {
    method: 'POST',
    headers,
    body: JSON.stringify(body),
  })

  if (!response.ok) {
    handlers.onNetworkError?.(new Error(`HTTP ${response.status}`))
    return sessionId ?? ''
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
      const parts = buffer.split('\n\n')
      buffer = parts.pop() ?? ''
      for (const part of parts) parseChunk(part, handlers)
    }
    if (buffer) parseChunk(buffer, handlers)
  } catch (err) {
    handlers.onNetworkError?.(err as Error)
  }

  return newSessionId
}

// ---- App 平台：uni.request enableChunked ----
function sendApp(
  message: string,
  sessionId: string | null,
  handlers: StreamHandlers,
  workOrderContext?: string,
): Promise<string> {
  return new Promise((resolve) => {
    const token = uni.getStorageSync('access_token')
    const headers: Record<string, string> = { 'Content-Type': 'application/json' }
    if (token) headers['Authorization'] = `Bearer ${token}`

    const body: Record<string, unknown> = { message, session_id: sessionId }
    if (workOrderContext) body['system_hint'] = workOrderContext

    let resolvedSessionId = sessionId ?? ''
    let buffer = ''

    const task = (uni as any).request({
      url: `${BASE_URL}/api/chat`,
      method: 'POST',
      header: headers,
      data: JSON.stringify(body),
      enableChunked: true,
      responseType: 'text',
      success(res: any) {
        resolvedSessionId = res.header?.['x-session-id'] ?? resolvedSessionId
        resolve(resolvedSessionId)
      },
      fail(err: any) {
        handlers.onNetworkError?.(new Error(err.errMsg || 'request failed'))
        resolve(resolvedSessionId)
      },
    })

    task.onChunkReceived((res: { data: ArrayBuffer }) => {
      const decoder = new TextDecoder()
      const chunk = decoder.decode(res.data)
      buffer += chunk
      const parts = buffer.split('\n\n')
      buffer = parts.pop() ?? ''
      for (const part of parts) parseChunk(part, handlers)
    })

    task.onHeadersReceived((res: { header: Record<string, string> }) => {
      resolvedSessionId = res.header?.['x-session-id'] ?? resolvedSessionId
    })
  })
}

/**
 * 发送消息到 AI，返回 sessionId
 *
 * @param message          用户消息
 * @param sessionId        会话 ID（首次传 null）
 * @param handlers         SSE 事件回调
 * @param workOrderContext 工单上下文（维修端自动注入，让 AI 知道当前工单信息）
 */
export async function sendChatMessage(
  message: string,
  sessionId: string | null,
  handlers: StreamHandlers,
  workOrderContext?: string,
): Promise<string> {
  // #ifdef H5
  return sendH5(message, sessionId, handlers, workOrderContext)
  // #endif

  // #ifndef H5
  return sendApp(message, sessionId, handlers, workOrderContext)
  // #endif
}

/**
 * 为维修工单生成 AI 上下文提示文本
 * 注入工单信息，让 AI 直接知道现场情况
 */
export function buildWorkOrderContext(order: {
  ticket_id: string
  building_id: string
  building_name?: string
  anomaly_type: string
  description: string
  priority: string
}): string {
  return `【工单背景】
工单编号：${order.ticket_id}
建筑：${order.building_name || order.building_id}
异常类型：${order.anomaly_type}
异常描述：${order.description}
优先级：${order.priority}

请基于以上工单信息，帮助维修人员进行现场诊断和维修。`
}
