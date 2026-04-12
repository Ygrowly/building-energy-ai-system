import { post } from './request'

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

export const workerAiApi = {
  chat(payload: WorkerAiChatRequest): Promise<WorkerAiChatResponse> {
    return post<WorkerAiChatResponse>('/api/worker-ai/chat', payload)
  },
}

export const operatorAiApi = {
  chat(payload: OperatorAiChatRequest): Promise<OperatorAiChatResponse> {
    return post<OperatorAiChatResponse>('/api/operator-ai/chat', payload)
  },
}
