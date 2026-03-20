/**
 * 对话状态管理 (Pinia) — 对接后端会话 API（乐观更新版）
 *
 * 性能策略：
 *  - 本地消息缓存（_msgCache）：切换 Tab 立即显示，无需等待 API
 *  - 乐观新建会话：先插入临时 Tab，后台 POST 再替换真实 session_id
 *  - 乐观关闭会话：立即从列表移除，后台 DELETE 不阻塞 UI
 *  - onDone 只更新当前会话元数据（延迟 500ms 单次 GET），不重载整个列表
 */
import { defineStore } from 'pinia'
import { ref, computed, watch } from 'vue'
import { sendChatMessage, approveWorkOrder } from '@/api/stream_client'
import { apiFetch } from '@/api/http'
import type { ArtifactEvent } from '@/api/stream_client'

export type MessageRole = 'user' | 'ai' | 'artifact' | 'error'

export interface ThinkingStep {
  id: string
  agent: string
  message: string
}

export interface ChatMessage {
  id: string
  role: MessageRole
  content: string
  artifact?: ArtifactEvent
  timestamp: Date
  thinkingSteps?: ThinkingStep[]
  thinkingFinished?: boolean
}

export interface AgentStatus {
  name: string
  label: string
  status: 'idle' | 'thinking' | 'done' | 'error'
  message?: string
}

export interface SessionInfo {
  session_id: string
  title: string
  created_at: string
  updated_at: string
  message_count: number
  last_message: string | null
  building_id: string | null
  is_archived: boolean
  has_pending_action: boolean
}

// ── 本地消息缓存（key = session_id）────────────────────────────────────────
const _msgCache = new Map<string, ChatMessage[]>()
const TAB_STORAGE_KEY = 'chat_open_tab_ids'

// ── Artifact 持久化（localStorage，跨会话切换保留图表）────────────────────────
const ARTIFACT_STORAGE_PREFIX = 'chat_art_'

/** 将单条 artifact 消息持久化到 localStorage（以 artifact_id 或 msg.id 去重） */
function _saveArtifactToStorage(sessionId: string, msg: ChatMessage) {
  if (!msg.artifact) return
  try {
    const key = `${ARTIFACT_STORAGE_PREFIX}${sessionId}`
    const existing: Record<string, unknown> = JSON.parse(localStorage.getItem(key) ?? '{}')
    const storeKey = msg.artifact.artifact_id ?? msg.id
    existing[storeKey] = { ...msg, timestamp: (msg.timestamp as Date).toISOString() }
    localStorage.setItem(key, JSON.stringify(existing))
  } catch {
    // localStorage 可能已满或不可用，静默忽略
  }
}

/** 从 localStorage 加载指定会话的所有 artifact 消息，按时间戳升序排列 */
function _loadArtifactsFromStorage(sessionId: string): ChatMessage[] {
  try {
    const key = `${ARTIFACT_STORAGE_PREFIX}${sessionId}`
    const stored = localStorage.getItem(key)
    if (!stored) return []
    const parsed = JSON.parse(stored) as Record<string, Record<string, unknown>>
    return Object.values(parsed).map(m => ({
      ...(m as ChatMessage),
      timestamp: new Date(m.timestamp as string),
    }))
  } catch {
    return []
  }
}

/** 删除指定会话在 localStorage 中的 artifact 缓存 */
function _deleteArtifactsFromStorage(sessionId: string) {
  try {
    localStorage.removeItem(`${ARTIFACT_STORAGE_PREFIX}${sessionId}`)
  } catch { /* 静默忽略 */ }
}

/** 将 artifact 缓存从旧 sessionId 迁移到新 sessionId */
function _migrateArtifactStorage(oldId: string, newId: string) {
  try {
    const key = `${ARTIFACT_STORAGE_PREFIX}${oldId}`
    const data = localStorage.getItem(key)
    if (!data) return
    localStorage.setItem(`${ARTIFACT_STORAGE_PREFIX}${newId}`, data)
    localStorage.removeItem(key)
  } catch { /* 静默忽略 */ }
}

export const useChatStore = defineStore('chat', () => {
  const sessionList = ref<SessionInfo[]>([])       // 全量历史（含已关闭的 Tab）
  const openTabIds = ref<string[]>([])             // 顶栏中展示的 Tab ID 列表
  const sessionListLoading = ref(false)
  const currentSessionId = ref<string | null>(null)
  const messages = ref<ChatMessage[]>([])
  const isLoading = ref(false)
  const currentAgentStatus = ref<AgentStatus | null>(null)
  const pendingWorkOrder = ref<ArtifactEvent | null>(null)

  // per-session 联网搜索开关（key = session_id），防止跨 Tab 相互干扰
  const _webSearchBySession = ref<Record<string, boolean>>({})

  const webSearchEnabled = computed<boolean>({
    get: () => (currentSessionId.value ? (_webSearchBySession.value[currentSessionId.value] ?? false) : false),
    set: (v: boolean) => {
      if (currentSessionId.value) _webSearchBySession.value[currentSessionId.value] = v
    },
  })

  /** 顶栏 Tab 列表（按 openTabIds 顺序，来自 sessionList） */
  const openTabs = computed<SessionInfo[]>(() =>
    openTabIds.value
      .map(id => sessionList.value.find(s => s.session_id === id))
      .filter((s): s is SessionInfo => s !== undefined)
  )

  const currentSession = computed(() =>
    sessionList.value.find(s => s.session_id === currentSessionId.value) ?? null
  )
  const hasMessages = computed(() => messages.value.length > 0)

  const agentLabelMap: Record<string, string> = {
    router: '路由前台',
    data_agent: '数据分析师',
    diagnose_agent: '故障诊断专家',
    tool: '工具调用',
    web_search: '联网搜索',
  }

  // ── 加载会话列表 ───────────────────────────────────────────────────────────
  async function loadSessionList() {
    sessionListLoading.value = true
    try {
      const res = await apiFetch<{ sessions: SessionInfo[]; total: number }>('/api/chat/sessions')
      sessionList.value = res.sessions
    } catch (e) {
      console.warn('[chatStore] 加载会话列表失败:', e)
    } finally {
      sessionListLoading.value = false
    }
  }

  // ── 持久化 openTabIds 到 localStorage ─────────────────────────────────────
  watch(openTabIds, (ids) => {
    localStorage.setItem(TAB_STORAGE_KEY, JSON.stringify(ids))
  }, { deep: true })

  // ── 初始化 ─────────────────────────────────────────────────────────────────
  async function init() {
    await loadSessionList()
    if (sessionList.value.length > 0) {
      // 尝试从 localStorage 恢复上次打开的 Tab
      const saved = JSON.parse(localStorage.getItem(TAB_STORAGE_KEY) ?? '[]') as string[]
      const validIds = saved.filter(id => sessionList.value.some(s => s.session_id === id))

      const tabIds = validIds.length > 0 ? validIds : [sessionList.value[0].session_id]
      openTabIds.value = tabIds
      currentSessionId.value = tabIds[0]
      messages.value = _msgCache.get(tabIds[0]) ?? []
      if (!_msgCache.has(tabIds[0])) _loadMessages(tabIds[0])
    } else {
      newSession()
    }
  }

  // ── 后台加载消息（不阻塞 UI） ──────────────────────────────────────────────
  async function _loadMessages(sessionId: string) {
    try {
      const res = await apiFetch<{
        messages: { role: string; content: string }[]
        total: number
      }>(`/api/chat/sessions/${sessionId}/messages`)

      const parsed: ChatMessage[] = res.messages.map(m => ({
        id: crypto.randomUUID(),
        role: (m.role === 'user' ? 'user' : 'ai') as MessageRole,
        content: typeof m.content === 'string' ? m.content : JSON.stringify(m.content),
        timestamp: new Date(),
        thinkingSteps: [],
        thinkingFinished: true,
      }))

      // 从 localStorage 恢复本会话生成的 artifact（图表、工单等），追加到文本消息之后
      const cachedArtifacts = _loadArtifactsFromStorage(sessionId)
      if (cachedArtifacts.length > 0) {
        // artifact 按原始时间戳排序，保留生成顺序
        cachedArtifacts.sort((a, b) => a.timestamp.getTime() - b.timestamp.getTime())
        parsed.push(...cachedArtifacts)
      }

      _msgCache.set(sessionId, parsed)
      // 只有仍处于该会话时才更新显示
      if (currentSessionId.value === sessionId) {
        messages.value = parsed
      }
    } catch {
      // 空会话或网络错误，忽略
    }
  }

  // ── 新建会话（仅本地，不写后端；发第一条消息时再真正创建） ──────────────────
  function newSession(title = '新对话') {
    const tempId = `temp-${crypto.randomUUID()}`
    const now = new Date().toISOString()

    const tempSession: SessionInfo = {
      session_id: tempId, title, created_at: now, updated_at: now,
      message_count: 0, last_message: null, building_id: null,
      is_archived: false, has_pending_action: false,
    }
    sessionList.value.unshift(tempSession)
    openTabIds.value.unshift(tempId)
    currentSessionId.value = tempId
    messages.value = []
    _msgCache.set(tempId, [])
    currentAgentStatus.value = null
    pendingWorkOrder.value = null
    // 不调用后端，空会话永远不进数据库
  }

  // ── 内部：将临时会话提交到后端，返回真实 session_id ──────────────────────
  async function _persistTempSession(tempId: string): Promise<string> {
    const sess = sessionList.value.find(s => s.session_id === tempId)
    const info = await apiFetch<SessionInfo>('/api/chat/sessions', {
      method: 'POST',
      body: JSON.stringify({ title: sess?.title ?? '新对话' }),
    })
    // 替换 sessionList 中的临时条目
    const idx = sessionList.value.findIndex(s => s.session_id === tempId)
    if (idx !== -1) sessionList.value[idx] = info
    // 替换 openTabIds
    const tabIdx = openTabIds.value.indexOf(tempId)
    if (tabIdx !== -1) openTabIds.value[tabIdx] = info.session_id
    // 迁移消息缓存
    const cached = _msgCache.get(tempId) ?? []
    _msgCache.delete(tempId)
    _msgCache.set(info.session_id, cached)
    if (currentSessionId.value === tempId) currentSessionId.value = info.session_id
    // 迁移 artifact localStorage 缓存（temp-id → 真实 session_id）
    _migrateArtifactStorage(tempId, info.session_id)
    return info.session_id
  }

  // ── 切换会话（缓存命中即刻显示，未命中后台加载；从历史打开时自动加入 Tab） ─
  function switchSession(targetId: string) {
    if (currentSessionId.value === targetId) return

    // 若从历史记录打开，将其加入 openTabIds
    if (!openTabIds.value.includes(targetId)) {
      openTabIds.value.unshift(targetId)
    }

    currentSessionId.value = targetId
    currentAgentStatus.value = null
    pendingWorkOrder.value = null

    // 缓存命中 → 立即显示
    const cached = _msgCache.get(targetId)
    if (cached !== undefined) {
      messages.value = cached
    } else {
      // 缓存未命中 → 先清空（防止展示上一个会话消息），后台拉取
      messages.value = []
      _loadMessages(targetId)
    }
  }

  // ── 关闭 Tab（仅从顶栏移除，不删 sessionList，会话保留在历史记录） ─────────
  function removeTab(id: string) {
    openTabIds.value = openTabIds.value.filter(tid => tid !== id)
    _msgCache.delete(id)
    delete _webSearchBySession.value[id]
    if (currentSessionId.value === id) {
      if (openTabIds.value.length > 0) {
        switchSession(openTabIds.value[0])
      } else {
        // 所有 Tab 都关了，从历史中打开第一个，否则新建
        if (sessionList.value.length > 0) {
          switchSession(sessionList.value[0].session_id)
        } else {
          newSession()
        }
      }
    }
  }

  // ── 删除会话（乐观移除，后台 DELETE，彻底删除） ────────────────────────────
  function closeSession(id: string) {
    // 1. 立即从 Tab 列表和历史中移除
    openTabIds.value = openTabIds.value.filter(tid => tid !== id)
    sessionList.value = sessionList.value.filter(s => s.session_id !== id)
    _msgCache.delete(id)
    _deleteArtifactsFromStorage(id)
    delete _webSearchBySession.value[id]

    if (currentSessionId.value === id) {
      if (openTabIds.value.length > 0) {
        switchSession(openTabIds.value[0])
      } else if (sessionList.value.length > 0) {
        switchSession(sessionList.value[0].session_id)
      } else {
        newSession()
      }
    }

    // 2. 后台删除（不阻塞；临时会话未写后端，跳过）
    if (!id.startsWith('temp-')) {
      apiFetch(`/api/chat/sessions/${id}`, { method: 'DELETE' }).catch(e =>
        console.warn('[chatStore] 删除会话失败:', e)
      )
    }
  }

  // ── 内部：追加消息 ─────────────────────────────────────────────────────────
  function _addMsg(role: MessageRole, content: string, extra?: Partial<ChatMessage>) {
    const msg: ChatMessage = {
      id: crypto.randomUUID(), role, content, timestamp: new Date(), ...extra,
    }
    messages.value.push(msg)
    // 同步缓存（仅当缓存与 messages.value 不是同一数组时才额外 push，避免重复）
    const sid = currentSessionId.value
    if (sid) {
      const cache = _msgCache.get(sid)
      if (!cache) {
        _msgCache.set(sid, messages.value)
      } else if (cache !== messages.value) {
        cache.push(msg)
      }
      // artifact 消息额外持久化到 localStorage，确保切换会话后仍可恢复
      if (role === 'artifact') {
        _saveArtifactToStorage(sid, msg)
      }
    }
  }

  // ── 发送消息 ───────────────────────────────────────────────────────────────
  async function sendMessage(userText: string) {
    if (!userText.trim() || isLoading.value) return
    if (!currentSessionId.value) newSession()

    // 如果当前是临时会话，先向后端创建真实会话
    if (currentSessionId.value!.startsWith('temp-')) {
      try {
        await _persistTempSession(currentSessionId.value!)
      } catch (e) {
        _addMsg('error', `创建会话失败：${(e as Error).message}`)
        return
      }
    }

    _addMsg('user', userText)
    isLoading.value = true

    const aiMsgId = crypto.randomUUID()
    const aiMsg: ChatMessage = {
      id: aiMsgId, role: 'ai', content: '', timestamp: new Date(),
      thinkingSteps: [], thinkingFinished: false,
    }
    messages.value.push(aiMsg)
    // 同步缓存（仅当缓存与 messages.value 不是同一数组时才额外 push，避免重复）
    const _sid = currentSessionId.value
    if (_sid) {
      const cache = _msgCache.get(_sid)
      if (!cache) {
        _msgCache.set(_sid, messages.value)
      } else if (cache !== messages.value) {
        cache.push(aiMsg)
      }
    }

    let textStarted = false
    const sessionIdAtStart = currentSessionId.value!

    try {
      const newBackendId = await sendChatMessage(userText, sessionIdAtStart, {
        onThinking(e) {
          const label = agentLabelMap[e.agent] ?? e.agent
          currentAgentStatus.value = { name: e.agent, label, status: 'thinking', message: e.message }
          const m = messages.value.find(x => x.id === aiMsgId)
          if (m) {
            if (!m.thinkingSteps) m.thinkingSteps = []
            m.thinkingSteps.push({ id: crypto.randomUUID(), agent: e.agent, message: e.message })
          }
        },
        onText(e) {
          const m = messages.value.find(x => x.id === aiMsgId)
          if (m) {
            m.content += e.content
            if (!textStarted) { textStarted = true; m.thinkingFinished = true }
          }
          if (e.is_final) currentAgentStatus.value = null
        },
        onArtifact(e) {
          _addMsg('artifact', e.title ?? '生成式组件', { artifact: e })
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
          const m = messages.value.find(x => x.id === aiMsgId)
          if (m && !m.thinkingFinished) m.thinkingFinished = true

          // 乐观更新当前会话元数据
          const sid = currentSessionId.value
          const idx = sid ? sessionList.value.findIndex(s => s.session_id === sid) : -1
          if (idx !== -1) {
            sessionList.value[idx] = {
              ...sessionList.value[idx],
              message_count: sessionList.value[idx].message_count + 1,
              last_message: userText,
              updated_at: new Date().toISOString(),
            }
          }
          // 延迟 600ms 拉一次单条会话信息（后端此时已写完标题）
          setTimeout(() => _refreshCurrentSession(), 600)
        },
        onNetworkError(err) {
          _addMsg('error', `网络错误：${err.message}`)
          isLoading.value = false
        },
      }, webSearchEnabled.value)
      void newBackendId // session_id 已在 _persistTempSession 中迁移
    } catch (err) {
      _addMsg('error', `请求失败：${(err as Error).message}`)
      isLoading.value = false
    }
  }

  // ── 后台刷新当前会话元数据（仅更新标题等，不清消息） ─────────────────────
  async function _refreshCurrentSession() {
    const sid = currentSessionId.value
    if (!sid || sid.startsWith('temp-')) return
    try {
      const updated = await apiFetch<SessionInfo>(`/api/chat/sessions/${sid}`)
      const idx = sessionList.value.findIndex(s => s.session_id === sid)
      if (idx !== -1) sessionList.value[idx] = updated
    } catch { /* 忽略 */ }
  }

  // ── 工单审批 ───────────────────────────────────────────────────────────────
  async function approveOrder(approved: boolean, reason?: string) {
    if (!pendingWorkOrder.value || !currentSessionId.value) return
    const ticketId = (pendingWorkOrder.value.data_payload as Record<string, string>)?.ticket_id
    if (!ticketId) return
    const result = await approveWorkOrder(currentSessionId.value, ticketId, approved, reason)
    pendingWorkOrder.value = null
    _addMsg('ai', approved
      ? `✅ 工单 ${ticketId} 已批准，正在推送至运维班组。`
      : `❌ 工单 ${ticketId} 已驳回。${reason ?? ''}`
    )
    return result
  }

  // ── 重命名会话 ─────────────────────────────────────────────────────────────
  async function renameSession(id: string, newTitle: string) {
    const idx = sessionList.value.findIndex(s => s.session_id === id)
    if (idx === -1 || !newTitle.trim()) return
    // 乐观更新（临时会话只改本地，不写后端）
    sessionList.value[idx] = { ...sessionList.value[idx], title: newTitle.trim() }
    if (id.startsWith('temp-')) return
    try {
      await apiFetch(`/api/chat/sessions/${id}`, {
        method: 'PATCH',
        body: JSON.stringify({ title: newTitle.trim() }),
      })
    } catch (e) {
      console.warn('[chatStore] 重命名失败:', e)
    }
  }

  // ── 联网搜索开关（当前会话级别）──────────────────────────────────────────
  function toggleWebSearch() {
    webSearchEnabled.value = !webSearchEnabled.value
  }

  // ── 清除当前会话消息（前端清屏） ──────────────────────────────────────────
  function clearSession() {
    const sid = currentSessionId.value
    messages.value = []
    if (sid) _msgCache.set(sid, [])
    isLoading.value = false
    currentAgentStatus.value = null
    pendingWorkOrder.value = null
  }

  return {
    sessionList, openTabs, sessionListLoading,
    currentSessionId, currentSession,
    messages, isLoading, currentAgentStatus, pendingWorkOrder, hasMessages,
    webSearchEnabled,
    init, loadSessionList, newSession, switchSession, removeTab, closeSession,
    sendMessage, approveOrder, clearSession, renameSession, toggleWebSearch,
  }
})
