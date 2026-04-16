import { BASE_URL, get, post } from './request'
import type { MaintenanceExperienceRecommendation } from './maintenance-experience'

export interface WorkerAiPendingAction {
  action: string
  action_label: string
  ticket_id?: string | null
  dispatch_id?: string | null
  hall_entry_id?: string | null
  reason?: string | null
  result?: string | null
  requires_reason: boolean
  needs_confirmation: boolean
  stage: 'awaiting_reason' | 'awaiting_confirmation'
}

export interface WorkerAiChatResponse {
  assistant: '维小修'
  session_id: string
  message_type: 'chat' | 'action_confirmation' | 'action_result'
  answer: string
  pending_action: WorkerAiPendingAction | null
  executed: boolean
  action_result?: Record<string, any> | null
}

export interface WorkerAiChatRequest {
  message: string
  session_id?: string | null
  ticket_id?: string | null
  dispatch_id?: string | null
  hall_entry_id?: string | null
  client_context?: Record<string, any> | null
}

export interface WorkerAiGuidanceChatRequest {
  message: string
  session_id?: string | null
  ticket_id: string
  dispatch_id?: string | null
  plan_id?: string | null
  step_id?: string | null
  client_context?: Record<string, any> | null
}

export interface WorkerAiGuidanceChatResponse {
  assistant: '维小修'
  session_id: string
  message_type: 'guidance_chat'
  answer: string
  executed: false
  plan_id: string
  step_id: string
  suggested_step_status?: WorkerAiStepStatus | null
  suggested_next_message?: string | null
  suggested_followups?: string[]
  safety_level?: 'normal' | 'caution' | 'danger' | string
}

export interface WorkerAiHistoryMessage {
  id: string
  session_id: string
  role: 'user' | 'ai'
  content: string
  content_type?: string | null
  created_at?: string | null
}

export interface WorkerAiHistoryResponse {
  assistant: '维小修'
  ticket_id: string
  session_id: string | null
  messages: WorkerAiHistoryMessage[]
}

export interface OperatorAiChatResponse {
  assistant: '运小维'
  session_id: string
  answer_type?: string
  answer: string
  readonly: boolean
  facts: any[] | Record<string, any>
  metrics: Record<string, any>
  chart?: Record<string, any> | null
  evidence_refs: string[]
  suggested_followups: string[]
  blocked_actions: string[]
}

export interface OperatorAiChatRequest {
  message: string
  session_id?: string | null
  ticket_id?: string | null
  scope?: Record<string, any> | null
  include_evidence?: boolean
  include_chart?: boolean
}

export interface AssistantStreamThinkingEvent {
  type: 'thinking'
  agent?: string
  message: string
  hop_count?: number
}

export interface AssistantStreamTextEvent {
  type: 'text'
  content: string
  is_final: boolean
}

export interface AssistantStreamResultEvent<T> {
  type: 'result'
  payload: T
}

export interface AssistantStreamDoneEvent {
  type: 'done'
  session_id: string
  hop_count?: number
}

export interface AssistantStreamErrorEvent {
  type: 'error'
  message: string
  recoverable: boolean
}

export type AssistantStreamEvent<T> =
  | AssistantStreamThinkingEvent
  | AssistantStreamTextEvent
  | AssistantStreamResultEvent<T>
  | AssistantStreamDoneEvent
  | AssistantStreamErrorEvent

export interface AssistantStreamHandlers<T> {
  onThinking?: (event: AssistantStreamThinkingEvent) => void
  onText?: (event: AssistantStreamTextEvent) => void
  onResult?: (event: AssistantStreamResultEvent<T>) => void
  onDone?: (event: AssistantStreamDoneEvent) => void
  onError?: (event: AssistantStreamErrorEvent) => void
  onNetworkError?: (error: Error) => void
}

export type WorkerAiStepStatus = 'pending' | 'completed' | 'skipped' | 'needs_support' | 'uncertain'

export interface WorkerAiStep {
  id: string
  title: string
  instruction: string
  reason?: string | null
  expected_result?: string | null
  risk_note?: string | null
  requires_photo?: boolean
  status: WorkerAiStepStatus
  note?: string | null
}

export interface WorkerAiRootCause {
  name: string
  confidence?: 'low' | 'medium' | 'high' | string
  evidence?: string[]
}

export interface WorkerAiStepPlan {
  ticket_id: string
  dispatch_id?: string | null
  plan_id: string | null
  status: 'active' | 'not_generated' | 'not_ready' | string
  plan_version: number
  summary: string
  root_cause_candidates: WorkerAiRootCause[]
  steps: WorkerAiStep[]
  safety_notes: string[]
  experience_recommendations?: MaintenanceExperienceRecommendation[]
  guidance_ready: boolean
  model_provider?: string | null
  model_name?: string | null
  updated_at?: string | null
}

export interface WorkerAiStepUpdateResponse {
  ok: boolean
  plan_id: string
  plan_version: number
  steps: WorkerAiStep[]
  next_suggestion: string
}

export interface WorkerAiImageAnalysisResponse {
  asset_id: string
  media_type: 'image'
  analysis: {
    summary: string
    observations: string[]
    uncertainties: string[]
    suggested_next_message?: string | null
  }
  suggested_next_message: string
}

export interface WorkerAiTranscribeResponse {
  asset_id: string
  media_type: 'audio'
  transcript: string
  confidence?: number | null
  fallback?: boolean
}

export interface WorkerAiTtsResponse {
  audio_url: string | null
  cache_hit: boolean
  playback_mode: 'client_native' | string
  text: string
  voice?: string | null
  cache_key?: string
  warning?: string
}

function getToken(): string | null {
  return uni.getStorageSync('access_token') || null
}

function dispatchStreamEvent<T>(
  event: AssistantStreamEvent<T>,
  handlers: AssistantStreamHandlers<T>,
) {
  switch (event.type) {
    case 'thinking':
      handlers.onThinking?.(event)
      break
    case 'text':
      handlers.onText?.(event)
      break
    case 'result':
      handlers.onResult?.(event)
      break
    case 'done':
      handlers.onDone?.(event)
      break
    case 'error':
      handlers.onError?.(event)
      break
  }
}

function parseAssistantStreamChunk<T>(
  chunk: string,
  handlers: AssistantStreamHandlers<T>,
) {
  for (const line of chunk.split('\n')) {
    if (!line.startsWith('data: ')) continue
    const raw = line.slice(6).trim()
    if (!raw) continue
    try {
      dispatchStreamEvent(JSON.parse(raw) as AssistantStreamEvent<T>, handlers)
    } catch {
      // ignore malformed partial chunks
    }
  }
}

async function streamAssistantH5<T>(
  path: string,
  payload: Record<string, unknown>,
  handlers: AssistantStreamHandlers<T>,
): Promise<string> {
  const token = getToken()
  const headers: Record<string, string> = { 'Content-Type': 'application/json' }
  if (token) headers.Authorization = `Bearer ${token}`

  const response = await fetch(`${BASE_URL}${path}`, {
    method: 'POST',
    headers,
    body: JSON.stringify(payload),
  })

  if (!response.ok) {
    handlers.onNetworkError?.(new Error(`HTTP ${response.status}`))
    return String(payload.session_id || '')
  }

  const sessionId = response.headers.get('x-session-id') ?? String(payload.session_id || '')
  const reader = response.body?.getReader()
  if (!reader) return sessionId
  const decoder = new TextDecoder()
  let buffer = ''

  try {
    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })
      const parts = buffer.split('\n\n')
      buffer = parts.pop() ?? ''
      for (const part of parts) parseAssistantStreamChunk(part, handlers)
    }
    if (buffer) parseAssistantStreamChunk(buffer, handlers)
  } catch (err) {
    handlers.onNetworkError?.(err as Error)
  }

  return sessionId
}

function streamAssistantApp<T>(
  path: string,
  payload: Record<string, unknown>,
  handlers: AssistantStreamHandlers<T>,
): Promise<string> {
  return new Promise((resolve) => {
    const token = getToken()
    const headers: Record<string, string> = { 'Content-Type': 'application/json' }
    if (token) headers.Authorization = `Bearer ${token}`

    let resolvedSessionId = String(payload.session_id || '')
    let buffer = ''

    const task = (uni as any).request({
      url: `${BASE_URL}${path}`,
      method: 'POST',
      header: headers,
      data: JSON.stringify(payload),
      enableChunked: true,
      responseType: 'text',
      success() {
        resolve(resolvedSessionId)
      },
      fail(err: any) {
        handlers.onNetworkError?.(new Error(err?.errMsg || 'request failed'))
        resolve(resolvedSessionId)
      },
    })

    task.onChunkReceived?.((res: { data: ArrayBuffer }) => {
      buffer += new TextDecoder().decode(res.data)
      const parts = buffer.split('\n\n')
      buffer = parts.pop() ?? ''
      for (const part of parts) parseAssistantStreamChunk(part, handlers)
    })

    task.onHeadersReceived?.((res: { header: Record<string, string> }) => {
      resolvedSessionId = res.header?.['x-session-id'] ?? resolvedSessionId
    })
  })
}

async function streamAssistantRequest<T>(
  path: string,
  payload: Record<string, unknown>,
  handlers: AssistantStreamHandlers<T>,
): Promise<string> {
  // #ifdef H5
  return streamAssistantH5<T>(path, payload, handlers)
  // #endif

  // #ifndef H5
  return streamAssistantApp<T>(path, payload, handlers)
  // #endif
}

async function uploadWorkerAiBlob<T>(
  url: string,
  blob: Blob,
  fileField: 'image' | 'audio',
  fileName: string,
  formData: Record<string, string | null | undefined>,
): Promise<T> {
  const token = getToken()
  const body = new FormData()
  Object.entries(formData).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== '') body.append(key, value)
  })
  body.append(fileField, blob, fileName)
  const response = await fetch(BASE_URL + url, {
    method: 'POST',
    headers: token ? { Authorization: `Bearer ${token}` } : undefined,
    body,
  })
  if (!response.ok) {
    let message = `上传失败 (${response.status})`
    try {
      const parsed = await response.json()
      message = parsed.detail || message
    } catch {}
    uni.showToast({ title: message, icon: 'none' })
    throw new Error(message)
  }
  return await response.json() as T
}

function uploadWorkerAiFile<T>(
  url: string,
  filePath: string,
  fileField: 'image' | 'audio',
  formData: Record<string, string | null | undefined>,
): Promise<T> {
  const token = getToken()
  return new Promise((resolve, reject) => {
    uni.uploadFile({
      url: BASE_URL + url,
      filePath,
      name: fileField,
      header: token ? { Authorization: `Bearer ${token}` } : {},
      formData: Object.fromEntries(
        Object.entries(formData).filter(([, value]) => value !== undefined && value !== null && value !== '')
      ) as Record<string, string>,
      success: (res) => {
        if (res.statusCode >= 400) {
          let message = `上传失败 (${res.statusCode})`
          try {
            const parsed = JSON.parse(res.data || '{}')
            message = parsed.detail || message
          } catch {}
          uni.showToast({ title: message, icon: 'none' })
          reject(new Error(message))
          return
        }
        try {
          resolve(JSON.parse(res.data || '{}') as T)
        } catch {
          reject(new Error('上传响应解析失败'))
        }
      },
      fail: (err) => {
        uni.showToast({ title: '上传失败，请检查网络', icon: 'none' })
        reject(err)
      },
    })
  })
}

export function buildAbsoluteApiUrl(url: string): string {
  if (!url) return url
  if (/^https?:\/\//i.test(url)) return url
  return BASE_URL + url
}

export const workerAiApi = {
  chat(payload: WorkerAiChatRequest): Promise<WorkerAiChatResponse> {
    return post<WorkerAiChatResponse>('/api/worker-ai/chat', payload)
  },
  chatStream(payload: WorkerAiChatRequest, handlers: AssistantStreamHandlers<WorkerAiChatResponse>): Promise<string> {
    return streamAssistantRequest<WorkerAiChatResponse>('/api/worker-ai/chat/stream', payload as Record<string, unknown>, handlers)
  },
  guidanceChat(payload: WorkerAiGuidanceChatRequest): Promise<WorkerAiGuidanceChatResponse> {
    return post<WorkerAiGuidanceChatResponse>('/api/worker-ai/guidance/chat', payload)
  },
  guidanceChatStream(payload: WorkerAiGuidanceChatRequest, handlers: AssistantStreamHandlers<WorkerAiGuidanceChatResponse>): Promise<string> {
    return streamAssistantRequest<WorkerAiGuidanceChatResponse>('/api/worker-ai/guidance/chat/stream', payload as Record<string, unknown>, handlers)
  },
  getSteps(ticketId: string, params?: { auto_generate?: boolean; dispatch_id?: string | null }): Promise<WorkerAiStepPlan> {
    return get<WorkerAiStepPlan>(`/api/worker-ai/work-orders/${ticketId}/steps`, params as Record<string, unknown>)
  },
  history(ticketId: string, params?: { dispatch_id?: string | null; hall_entry_id?: string | null; limit?: number }): Promise<WorkerAiHistoryResponse> {
    return get<WorkerAiHistoryResponse>(`/api/worker-ai/work-orders/${ticketId}/history`, params as Record<string, unknown>)
  },
  updateStep(ticketId: string, stepId: string, payload: {
    plan_id: string
    status: WorkerAiStepStatus
    note?: string | null
    client_version?: number | null
  }): Promise<WorkerAiStepUpdateResponse> {
    return post<WorkerAiStepUpdateResponse>(`/api/worker-ai/work-orders/${ticketId}/steps/${stepId}/update`, payload)
  },
  analyzeImage(payload: {
    ticket_id: string
    dispatch_id?: string | null
    step_id?: string | null
    prompt?: string | null
    filePath: string
  }): Promise<WorkerAiImageAnalysisResponse> {
    return uploadWorkerAiFile<WorkerAiImageAnalysisResponse>('/api/worker-ai/media/analyze-image', payload.filePath, 'image', {
      ticket_id: payload.ticket_id,
      dispatch_id: payload.dispatch_id,
      step_id: payload.step_id,
      prompt: payload.prompt,
    })
  },
  transcribeAudio(payload: {
    ticket_id: string
    dispatch_id?: string | null
    step_id?: string | null
    filePath: string
  }): Promise<WorkerAiTranscribeResponse> {
    return uploadWorkerAiFile<WorkerAiTranscribeResponse>('/api/worker-ai/media/transcribe', payload.filePath, 'audio', {
      ticket_id: payload.ticket_id,
      dispatch_id: payload.dispatch_id,
      step_id: payload.step_id,
    })
  },
  transcribeAudioBlob(payload: {
    ticket_id: string
    dispatch_id?: string | null
    step_id?: string | null
    blob: Blob
    fileName?: string
  }): Promise<WorkerAiTranscribeResponse> {
    return uploadWorkerAiBlob<WorkerAiTranscribeResponse>('/api/worker-ai/media/transcribe', payload.blob, 'audio', payload.fileName || 'voice.webm', {
      ticket_id: payload.ticket_id,
      dispatch_id: payload.dispatch_id,
      step_id: payload.step_id,
    })
  },
  tts(payload: { text: string; voice?: string | null }): Promise<WorkerAiTtsResponse> {
    return post<WorkerAiTtsResponse>('/api/worker-ai/tts', payload)
  },
}

export const operatorAiApi = {
  chat(payload: OperatorAiChatRequest): Promise<OperatorAiChatResponse> {
    return post<OperatorAiChatResponse>('/api/operator-ai/chat', payload)
  },
  chatStream(payload: OperatorAiChatRequest, handlers: AssistantStreamHandlers<OperatorAiChatResponse>): Promise<string> {
    return streamAssistantRequest<OperatorAiChatResponse>('/api/operator-ai/chat/stream', payload as Record<string, unknown>, handlers)
  },
}
