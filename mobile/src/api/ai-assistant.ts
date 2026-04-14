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

export interface OperatorAiChatResponse {
  assistant: '运小维'
  session_id: string
  answer_type?: string
  answer: string
  readonly: boolean
  facts: any[] | Record<string, any>
  metrics: Record<string, any>
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
  guidanceChat(payload: WorkerAiGuidanceChatRequest): Promise<WorkerAiGuidanceChatResponse> {
    return post<WorkerAiGuidanceChatResponse>('/api/worker-ai/guidance/chat', payload)
  },
  getSteps(ticketId: string, params?: { auto_generate?: boolean; dispatch_id?: string | null }): Promise<WorkerAiStepPlan> {
    return get<WorkerAiStepPlan>(`/api/worker-ai/work-orders/${ticketId}/steps`, params as Record<string, unknown>)
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
}
