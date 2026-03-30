/**
 * AI 对话流式客户端（uni-app 版）
 *
 * 对齐后端 POST /api/chat 接口：
 *   body: { message, session_id?, enable_web_search?, thinking_mode? }
 *   ⚠ 不支持 system_hint，工单上下文通过拼接到 message 实现
 *
 * 平台策略：
 *   H5：原生 fetch + ReadableStream
 *   App：uni.request enableChunked
 */

import { BASE_URL } from './request'
import type { WorkOrder } from './workorder'

export interface TextEvent     { type: 'text';     content: string; is_final: boolean }
export interface ThinkingEvent { type: 'thinking';  agent: string; message: string; hop_count: number; content?: string }
export interface ErrorEvent    { type: 'error';    message: string; recoverable: boolean }
export interface DoneEvent     { type: 'done';     session_id: string; hop_count: number }
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
    case 'thinking': handlers.onThinking?.(event); break
    case 'text':     handlers.onText?.(event);     break
    case 'error':    handlers.onError?.(event);    break
    case 'done':     handlers.onDone?.(event);     break
  }
}

function parseChunk(chunk: string, handlers: StreamHandlers) {
  for (const line of chunk.split('\n')) {
    if (!line.startsWith('data: ')) continue
    const raw = line.slice(6).trim()
    if (!raw) continue
    try { dispatchEvent(JSON.parse(raw), handlers) } catch { /* skip */ }
  }
}

// ---- 构建请求体（对齐后端 ChatRequest） ----
function buildBody(message: string, sessionId: string | null) {
  const body: Record<string, unknown> = {
    message,
    session_id: sessionId,
    thinking_mode: 'fast',
  }
  return body
}

// ---- H5: fetch stream ----
async function sendH5(message: string, sessionId: string | null, handlers: StreamHandlers): Promise<string> {
  const token = uni.getStorageSync('access_token')
  const headers: Record<string, string> = { 'Content-Type': 'application/json' }
  if (token) headers['Authorization'] = `Bearer ${token}`

  const response = await fetch(`${BASE_URL}/api/chat`, {
    method: 'POST',
    headers,
    body: JSON.stringify(buildBody(message, sessionId)),
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

// ---- App: uni.request enableChunked ----
function sendApp(message: string, sessionId: string | null, handlers: StreamHandlers): Promise<string> {
  return new Promise((resolve) => {
    const token = uni.getStorageSync('access_token')
    const headers: Record<string, string> = { 'Content-Type': 'application/json' }
    if (token) headers['Authorization'] = `Bearer ${token}`

    let resolvedSessionId = sessionId ?? ''
    let buffer = ''

    const task = (uni as any).request({
      url: `${BASE_URL}/api/chat`,
      method: 'POST',
      header: headers,
      data: JSON.stringify(buildBody(message, sessionId)),
      enableChunked: true,
      responseType: 'text',
      success() { resolve(resolvedSessionId) },
      fail(err: any) {
        handlers.onNetworkError?.(new Error(err.errMsg || 'request failed'))
        resolve(resolvedSessionId)
      },
    })

    task.onChunkReceived?.((res: { data: ArrayBuffer }) => {
      buffer += new TextDecoder().decode(res.data)
      const parts = buffer.split('\n\n')
      buffer = parts.pop() ?? ''
      for (const part of parts) parseChunk(part, handlers)
    })

    task.onHeadersReceived?.((res: { header: Record<string, string> }) => {
      resolvedSessionId = res.header?.['x-session-id'] ?? resolvedSessionId
    })
  })
}

/**
 * 发送消息到 AI，返回 sessionId
 */
export async function sendChatMessage(
  message: string,
  sessionId: string | null,
  handlers: StreamHandlers,
): Promise<string> {
  // #ifdef H5
  return sendH5(message, sessionId, handlers)
  // #endif

  // #ifndef H5
  return sendApp(message, sessionId, handlers)
  // #endif
}

/**
 * 为维修工单构建带上下文的首条消息
 * 将工单信息拼接到用户消息前部（后端不支持 system_hint 字段）
 */
export function buildContextMessage(order: WorkOrder, userInput: string): string {
  return `【当前工单信息 - 请基于此信息辅助维修】
工单编号：${order.ticket_id}
建筑ID：${order.building_id}
异常描述：${order.issue_description}
建议措施：${order.suggested_action}
优先级：${order.priority}
AI审批意见：${order.ai_reason || '无'}

维修人员提问：${userInput}`
}
