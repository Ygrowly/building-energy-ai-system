/**
 * 对话状态管理 (Pinia)。
 *
 * 管理：
 * - 消息列表（用户 + AI + thinking + artifact）
 * - 当前会话 ID
 * - Agent 状态（用于 Thinking Stream 可视化）
 * - 待审批工单
 */
import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { sendChatMessage, approveWorkOrder } from '@/api/stream_client'
import type { ArtifactEvent } from '@/api/stream_client'

export type MessageRole = 'user' | 'ai' | 'thinking' | 'artifact' | 'error'

export interface ChatMessage {
  id: string
  role: MessageRole
  content: string
  agent?: string      // thinking 消息的 agent 名
  artifact?: ArtifactEvent
  timestamp: Date
}

export interface AgentStatus {
  name: string
  label: string
  status: 'idle' | 'thinking' | 'done' | 'error'
  message?: string
}

export const useChatStore = defineStore('chat', () => {
  const messages = ref<ChatMessage[]>([])
  const sessionId = ref<string | null>(null)
  const isLoading = ref(false)
  const currentAgentStatus = ref<AgentStatus | null>(null)
  const pendingWorkOrder = ref<ArtifactEvent | null>(null)

  const agentLabelMap: Record<string, string> = {
    router: '路由前台',
    data_agent: '数据分析师',
    diagnose_agent: '故障诊断专家',
    tool: '工具调用',
  }

  function _addMsg(role: MessageRole, content: string, extra?: Partial<ChatMessage>) {
    messages.value.push({
      id: crypto.randomUUID(),
      role,
      content,
      timestamp: new Date(),
      ...extra,
    })
  }

  async function sendMessage(userText: string) {
    if (!userText.trim() || isLoading.value) return

    _addMsg('user', userText)
    isLoading.value = true

    // 占位 AI 消息（流式追加内容）
    const aiMsgId = crypto.randomUUID()
    messages.value.push({ id: aiMsgId, role: 'ai', content: '', timestamp: new Date() })

    try {
      sessionId.value = await sendChatMessage(userText, sessionId.value, {
        onThinking(e) {
          const label = agentLabelMap[e.agent] ?? e.agent
          currentAgentStatus.value = {
            name: e.agent,
            label,
            status: 'thinking',
            message: e.message,
          }
          // 在消息流中插入 thinking 气泡
          _addMsg('thinking', e.message, { agent: e.agent })
        },
        onText(e) {
          const aiMsg = messages.value.find(m => m.id === aiMsgId)
          if (aiMsg) {
            aiMsg.content += e.content
          }
          if (e.is_final) {
            currentAgentStatus.value = null
          }
        },
        onArtifact(e) {
          _addMsg('artifact', e.title ?? '生成式组件', { artifact: e })
          // 工单待审批
          if (e.component_type === 'WorkOrderCard' || e.widget === 'WorkOrderCard') {
            pendingWorkOrder.value = e
          }
        },
        onError(e) {
          _addMsg('error', e.message)
          currentAgentStatus.value = { name: '', label: '错误', status: 'error', message: e.message }
        },
        onDone() {
          isLoading.value = false
          currentAgentStatus.value = null
        },
        onNetworkError(err) {
          _addMsg('error', `网络错误：${err.message}`)
          isLoading.value = false
        },
      })
    } catch (err) {
      _addMsg('error', `请求失败：${(err as Error).message}`)
      isLoading.value = false
    }
  }

  async function approveOrder(approved: boolean, reason?: string) {
    if (!pendingWorkOrder.value || !sessionId.value) return
    const ticketId = (pendingWorkOrder.value.data_payload as Record<string, string>)?.ticket_id
    if (!ticketId) return

    const result = await approveWorkOrder(sessionId.value, ticketId, approved, reason)
    pendingWorkOrder.value = null
    _addMsg('ai', approved
      ? `✅ 工单 ${ticketId} 已批准，正在推送至运维班组。`
      : `❌ 工单 ${ticketId} 已驳回。${reason ?? ''}`
    )
    return result
  }

  function clearSession() {
    messages.value = []
    sessionId.value = null
    isLoading.value = false
    currentAgentStatus.value = null
    pendingWorkOrder.value = null
  }

  const hasMessages = computed(() => messages.value.length > 0)

  return {
    messages,
    sessionId,
    isLoading,
    currentAgentStatus,
    pendingWorkOrder,
    hasMessages,
    sendMessage,
    approveOrder,
    clearSession,
  }
})
