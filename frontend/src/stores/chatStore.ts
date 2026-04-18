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
import type { ArtifactEvent, EvidenceSource } from '@/api/stream_client'
import { generateId } from '@/utils/id'

export type MessageRole = 'user' | 'ai' | 'artifact' | 'error'

export interface ThinkingStep {
  id: string
  agent: string
  message: string
  /** LLM 流式推理内容（逐 token 追加） */
  streamContent?: string
  /** 后端基于 intent 的动态显示标签（覆盖前端静态映射） */
  displayLabel?: string
}

export interface ChatMessage {
  id: string
  role: MessageRole
  content: string
  artifact?: ArtifactEvent
  /** 内嵌在该 AI 消息气泡中的 artifacts（图表/卡片），按到达顺序排列 */
  attachedArtifacts?: ArtifactEvent[]
  timestamp: Date
  thinkingSteps?: ThinkingStep[]
  thinkingFinished?: boolean
  thinkingStartTime?: number
  thinkingDuration?: number
  liked?: boolean | null
  /** RAG 引用来源列表（知识溯源） */
  evidenceSources?: EvidenceSource[]
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

function artifactType(artifact?: ArtifactEvent): string {
  return artifact?.component_type ?? artifact?.widget ?? ''
}

function isHiddenChatArtifact(artifact?: ArtifactEvent): boolean {
  return ['ReportDownload', 'report-download'].includes(artifactType(artifact))
}

function isInlineArtifact(artifact?: ArtifactEvent): boolean {
  return [
    'LineChart', 'BarChart', 'Gauge', 'ValueCard',
    'line-chart', 'bar-chart', 'gauge', 'value-card',
  ].includes(artifactType(artifact))
}

/** 将单条 artifact 消息持久化到 localStorage（以 artifact_id 或 msg.id 去重） */
function _saveArtifactToStorage(sessionId: string, msg: ChatMessage) {
  if (!msg.artifact || isHiddenChatArtifact(msg.artifact)) return
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
    return Object.values(parsed)
      .map(m => ({
        ...(m as unknown as ChatMessage),
        timestamp: new Date(m.timestamp as string),
      }))
      .filter(m => !isHiddenChatArtifact(m.artifact))
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
  // per-session 加载状态（key = session_id），实现会话间请求隔离
  const _loadingBySession = ref<Record<string, boolean>>({})
  const isLoading = computed(() => {
    const sid = currentSessionId.value
    return sid ? (_loadingBySession.value[sid] ?? false) : false
  })
  // per-session agent 状态（key = session_id）
  const _agentStatusBySession = ref<Record<string, AgentStatus | null>>({})
  const currentAgentStatus = computed(() => {
    const sid = currentSessionId.value
    return sid ? (_agentStatusBySession.value[sid] ?? null) : null
  })
  const pendingWorkOrder = ref<ArtifactEvent | null>(null)

  // per-session AbortController（用于终止生成）
  const _abortControllers = new Map<string, AbortController>()

  // per-session 联网搜索开关（key = session_id），防止跨 Tab 相互干扰
  const _webSearchBySession = ref<Record<string, boolean>>({})

  const webSearchEnabled = computed<boolean>({
    get: () => (currentSessionId.value ? (_webSearchBySession.value[currentSessionId.value] ?? false) : false),
    set: (v: boolean) => {
      if (currentSessionId.value) _webSearchBySession.value[currentSessionId.value] = v
    },
  })

  // per-session 思考模式开关
  const _thinkingModeBySession = ref<Record<string, 'fast' | 'deep'>>({})

  const thinkingMode = computed<'fast' | 'deep'>({
    get: () => (currentSessionId.value ? (_thinkingModeBySession.value[currentSessionId.value] ?? 'fast') : 'fast'),
    set: (v: 'fast' | 'deep') => {
      if (currentSessionId.value) _thinkingModeBySession.value[currentSessionId.value] = v
    },
  })

  function toggleThinkingMode() {
    thinkingMode.value = thinkingMode.value === 'fast' ? 'deep' : 'fast'
  }

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
    diagnose_agent: '能效分析师',
    tool: '工具调用',
    web_search: '联网搜索',
  }
  function resolveThinkingLabel(agent: string, displayLabel?: string) {
    if (displayLabel) return displayLabel
    const fallbackMap: Record<string, string> = {
      router: '需求理解',
      data_agent: '数据采集',
      diagnose_agent: '故障诊断',
      tool: '工具调用',
      web_search: '联网搜索',
    }
    return fallbackMap[agent] ?? agentLabelMap[agent] ?? agent
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
  let _inited = false
  async function init() {
    if (_inited) return          // 防止多次 mount 导致重复初始化
    _inited = true
    await loadSessionList()
    if (sessionList.value.length > 0) {
      // 尝试从 localStorage 恢复上次打开的 Tab
      const saved = JSON.parse(localStorage.getItem(TAB_STORAGE_KEY) ?? '[]') as string[]
      // 去重：同一个 session_id 只保留一次
      let validIds = [...new Set(saved)].filter(id => sessionList.value.some(s => s.session_id === id))

      // 多个空会话（message_count === 0）只保留第一个，避免刷新后出现多个"新对话"Tab
      const seenEmpty = new Set<boolean>()
      validIds = validIds.filter(id => {
        const sess = sessionList.value.find(s => s.session_id === id)
        if (sess && sess.message_count === 0) {
          if (seenEmpty.has(true)) return false
          seenEmpty.add(true)
        }
        return true
      })

      const tabIds = validIds.length > 0 ? validIds : [sessionList.value[0].session_id]
      openTabIds.value = tabIds
      currentSessionId.value = tabIds[0]
      const cached = _msgCache.get(tabIds[0])
      if (cached) {
        messages.value = cached
      } else {
        const empty: ChatMessage[] = []
        messages.value = empty
        _msgCache.set(tabIds[0], empty)
        _loadMessages(tabIds[0])
      }
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
        id: generateId(),
        role: (m.role === 'user' ? 'user' : 'ai') as MessageRole,
        content: typeof m.content === 'string' ? m.content : JSON.stringify(m.content),
        timestamp: new Date(),
        thinkingSteps: [],
        thinkingFinished: true,
      }))

      // 从 localStorage 恢复本会话生成的 artifact（图表、工单等），追加到文本消息之后
      const cachedArtifacts = _loadArtifactsFromStorage(sessionId)
      if (cachedArtifacts.length > 0) {
        cachedArtifacts.sort((a, b) => a.timestamp.getTime() - b.timestamp.getTime())

        // 将内联类型 artifact 重新挂到包含对应 <<CHART:anchor>> 的 AI 消息上
        for (const artMsg of cachedArtifacts) {
          const art = artMsg.artifact
          if (!art) continue
          if (!isInlineArtifact(art)) continue
          const anchor = art.anchor
          if (!anchor) continue
          for (let i = parsed.length - 1; i >= 0; i--) {
            const m = parsed[i]
            if (m.role === 'ai' && m.content.includes(`<<CHART:${anchor}>>`)) {
              if (!m.attachedArtifacts) m.attachedArtifacts = []
              if (!m.attachedArtifacts.some((a: ArtifactEvent) => a.artifact_id === art.artifact_id)) {
                m.attachedArtifacts.push(art)
              }
              break
            }
          }
        }

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

  // ── 新建会话（纯本地，直接用真实 UUID，无需预先写后端）────────────────────
  // 会话记录在首条消息发送时由后端懒加载创建，彻底消除新建会话时的 DB 等待。
  function newSession(title = '新对话') {
    const sessionId = generateId()
    const now = new Date().toISOString()

    const newSess: SessionInfo = {
      session_id: sessionId, title, created_at: now, updated_at: now,
      message_count: 0, last_message: null, building_id: null,
      is_archived: false, has_pending_action: false,
    }
    sessionList.value.unshift(newSess)
    openTabIds.value.unshift(sessionId)
    currentSessionId.value = sessionId
    // messages.value 和 _msgCache 共享同一数组引用，保证响应式同步
    const msgs: ChatMessage[] = []
    messages.value = msgs
    _msgCache.set(sessionId, msgs)
    _agentStatusBySession.value[sessionId] = null
    pendingWorkOrder.value = null
  }

  // ── 切换会话（缓存命中即刻显示，未命中后台加载；从历史打开时自动加入 Tab） ─
  function switchSession(targetId: string) {
    if (currentSessionId.value === targetId) return

    // 若从历史记录打开，将其加入 openTabIds
    if (!openTabIds.value.includes(targetId)) {
      openTabIds.value.unshift(targetId)
    }

    currentSessionId.value = targetId
    pendingWorkOrder.value = null

    // 缓存命中 → 立即显示
    const cached = _msgCache.get(targetId)
    if (cached !== undefined) {
      messages.value = cached
    } else {
      // 缓存未命中 → 先清空（防止展示上一个会话消息），后台拉取
      const empty: ChatMessage[] = []
      messages.value = empty
      _msgCache.set(targetId, empty)
      _loadMessages(targetId)
    }
  }

  // ── 关闭 Tab（仅从顶栏移除，不删 sessionList，会话保留在历史记录） ─────────
  function removeTab(id: string) {
    openTabIds.value = openTabIds.value.filter(tid => tid !== id)
    _msgCache.delete(id)
    delete _webSearchBySession.value[id]
    delete _loadingBySession.value[id]
    delete _agentStatusBySession.value[id]
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
    delete _loadingBySession.value[id]
    delete _agentStatusBySession.value[id]

    if (currentSessionId.value === id) {
      if (openTabIds.value.length > 0) {
        switchSession(openTabIds.value[0])
      } else if (sessionList.value.length > 0) {
        switchSession(sessionList.value[0].session_id)
      } else {
        newSession()
      }
    }

    // 2. 后台删除（不阻塞；若会话从未发过消息则 DB 中不存在，404 静默忽略）
    apiFetch(`/api/chat/sessions/${id}`, { method: 'DELETE' }).catch(e =>
      console.warn('[chatStore] 删除会话失败（可能是空会话）:', e)
    )
  }

  // ── 内部：追加消息（支持指定目标会话 ID，实现跨 Tab 写入隔离） ──────────────
  function _addMsg(role: MessageRole, content: string, extra?: Partial<ChatMessage>, targetSessionId?: string) {
    const msg: ChatMessage = {
      id: generateId(), role, content, timestamp: new Date(), ...extra,
    }
    if (role === 'artifact' && isHiddenChatArtifact(msg.artifact)) return
    const sid = targetSessionId ?? currentSessionId.value
    if (sid && sid === currentSessionId.value) {
      // ★ 当前会话：直接通过 messages.value（Reactive Proxy）push
      //   Vue 自动感知变化，同时底层 raw 数组（= _msgCache 引用）也自动更新
      messages.value.push(msg)
    } else if (sid) {
      // 非当前会话：写入后台缓存，不触发 UI
      let cache = _msgCache.get(sid)
      if (!cache) { cache = []; _msgCache.set(sid, cache) }
      cache.push(msg)
    } else {
      messages.value.push(msg)
    }
    // artifact 消息额外持久化到 localStorage
    if (role === 'artifact' && sid) {
      _saveArtifactToStorage(sid, msg)
    }
  }

  // ── 发送消息 ───────────────────────────────────────────────────────────────
  async function sendMessage(userText: string) {
    if (!userText.trim()) return
    if (!currentSessionId.value) newSession()

    // 锁定发起会话的 ID，后续所有回调都写入该会话，不受 Tab 切换影响
    let originSessionId = currentSessionId.value!

    // 按会话维度上锁，允许不同 Tab 各自独立请求
    if (_loadingBySession.value[originSessionId]) return
    _loadingBySession.value[originSessionId] = true

    // 先添加用户消息，让 UI 立即显示发送内容
    _addMsg('user', userText, undefined, originSessionId)

    // 首条消息时用用户输入作为临时标题
    {
      const idx = sessionList.value.findIndex(s => s.session_id === originSessionId)
      if (idx !== -1 && sessionList.value[idx].title === '新对话') {
        sessionList.value[idx] = {
          ...sessionList.value[idx],
          title: userText.length > 20 ? userText.slice(0, 20) + '…' : userText,
        }
      }
    }

    // 立即创建 AI 占位消息（在任何异步操作之前，让 UI 立刻显示思考状态）
    const aiMsgId = generateId()
    const thinkingStart = performance.now()
    _addMsg('ai', '', {
      id: aiMsgId, thinkingSteps: [], thinkingFinished: false,
      thinkingStartTime: thinkingStart,
    }, originSessionId)

    // 会话已使用真实 UUID，无需等待预创建，直接进入流式请求
    let textStarted = false
    // 追踪当前正在流式累积的步骤索引（确保 token 追加到同一步骤）
    let _streamStepIdx = -1
    let _streamStepAgent = ''

    /**
     * 查找 AI 气泡：
     *  - 当前会话 → 通过 messages.value（Proxy）查找，返回 Proxy 对象
     *    后续对 m.content / m.thinkingSteps 的修改自动触发 Vue 响应式
     *  - 已切走 → 通过 _msgCache 查找（不需要响应式）
     */
    function findAiMsg(): ChatMessage | undefined {
      if (currentSessionId.value === originSessionId) {
        return messages.value.find(x => x.id === aiMsgId)
      }
      const cache = _msgCache.get(originSessionId as string)
      return cache?.find(x => x.id === aiMsgId)
    }

    const abortCtrl = new AbortController()
    _abortControllers.set(originSessionId, abortCtrl)

    try {
      await sendChatMessage(userText, originSessionId, {
        onThinking(e) {
          // 如果后端传来了动态标签，缓存起来供后续步骤使用
          const label = resolveThinkingLabel(e.agent, e.display_label)
          const m = findAiMsg()
          if (!m) return
          if (!m.thinkingSteps) m.thinkingSteps = []

          const stepLabel = resolveThinkingLabel(e.agent, e.display_label)
          if (e.content) {
            _agentStatusBySession.value[originSessionId] = { name: e.agent, label, status: 'thinking', message: '正在推理...' }
            if (_streamStepIdx >= 0 && _streamStepAgent === e.agent && _streamStepIdx < m.thinkingSteps.length) {
              m.thinkingSteps[_streamStepIdx].streamContent = (m.thinkingSteps[_streamStepIdx].streamContent ?? '') + e.content
              m.thinkingSteps[_streamStepIdx].displayLabel = stepLabel
            } else {
              _streamStepIdx = m.thinkingSteps.length
              _streamStepAgent = e.agent
              m.thinkingSteps.push({
                id: generateId(),
                agent: e.agent,
                message: '正在推理...',
                streamContent: e.content,
                displayLabel: stepLabel,
              })
            }
          } else {
            _streamStepIdx = -1
            _streamStepAgent = ''
            _agentStatusBySession.value[originSessionId] = { name: e.agent, label, status: 'thinking', message: e.message }
            m.thinkingSteps.push({ id: generateId(), agent: e.agent, message: e.message, displayLabel: stepLabel })
          }
        },
        onText(e) {
          const m = findAiMsg()
          if (m) {
            m.content += e.content
            if (!textStarted) {
              textStarted = true
              m.thinkingFinished = true
              m.thinkingDuration = Math.round((performance.now() - thinkingStart) / 1000)
            }
          }
          if (e.is_final) _agentStatusBySession.value[originSessionId] = null
        },
        onArtifact(e) {
          if (isInlineArtifact(e)) {
            const m = findAiMsg()
            if (m) {
              if (!m.attachedArtifacts) m.attachedArtifacts = []
              m.attachedArtifacts.push(e)
            }
          }
          _addMsg('artifact', e.title ?? '生成式组件', { artifact: e }, originSessionId)
          if (isHiddenChatArtifact(e)) return
          if (e.component_type === 'WorkOrderCard' || e.widget === 'WorkOrderCard') {
            pendingWorkOrder.value = e
          }
        },
        onEvidence(e) {
          const m = findAiMsg()
          if (m && e.sources?.length) {
            if (!m.evidenceSources) m.evidenceSources = []
            for (const src of e.sources) {
              const exists = m.evidenceSources.some(
                s => s.source_doc === src.source_doc && s.page === src.page,
              )
              if (!exists) m.evidenceSources.push(src)
            }
          }
        },
        onError(e) {
          _addMsg('error', e.message, undefined, originSessionId)
          _agentStatusBySession.value[originSessionId] = { name: '', label: '错误', status: 'error', message: e.message }
        },
        onDone() {
          _loadingBySession.value[originSessionId] = false
          _agentStatusBySession.value[originSessionId] = null
          const m = findAiMsg()
          if (m) {
            if (!m.thinkingFinished) m.thinkingFinished = true
            if (!m.thinkingDuration) {
              m.thinkingDuration = Math.round((performance.now() - thinkingStart) / 1000)
            }
          }

          // 乐观更新目标会话元数据（用 originSessionId 而非 currentSessionId）
          const idx = sessionList.value.findIndex(s => s.session_id === originSessionId)
          if (idx !== -1) {
            sessionList.value[idx] = {
              ...sessionList.value[idx],
              message_count: sessionList.value[idx].message_count + 1,
              last_message: userText,
              updated_at: new Date().toISOString(),
            }
          }
          // 延迟 600ms 拉一次该会话信息（后端此时已写完标题）
          setTimeout(() => _refreshSession(originSessionId), 600)
        },
        onNetworkError(err) {
          if (abortCtrl.signal.aborted) return
          _addMsg('error', `网络错误：${err.message}`, undefined, originSessionId)
          _loadingBySession.value[originSessionId] = false
        },
      }, webSearchEnabled.value, thinkingMode.value, abortCtrl.signal)
    } catch (err) {
      if (!abortCtrl.signal.aborted) {
        _addMsg('error', `请求失败：${(err as Error).message}`, undefined, originSessionId)
      }
      _loadingBySession.value[originSessionId] = false
    } finally {
      _abortControllers.delete(originSessionId)
    }
  }

  // ── 重新生成（原地替换 AI 回复） ──────────────────────────────────────────
  async function regenerateMessage(aiMsgIndex: number) {
    const originSessionId = currentSessionId.value
    if (!originSessionId) return

    // 找到 AI 消息前面最近的用户消息
    let userText = ''
    for (let i = aiMsgIndex - 1; i >= 0; i--) {
      if (messages.value[i].role === 'user') {
        userText = messages.value[i].content
        break
      }
    }
    if (!userText) return

    if (_loadingBySession.value[originSessionId]) return
    _loadingBySession.value[originSessionId] = true

    // 删除从 AI 消息开始到后续连续的 artifact/error 消息
    let removeEnd = aiMsgIndex + 1
    while (removeEnd < messages.value.length) {
      const r = messages.value[removeEnd].role
      if (r === 'artifact' || r === 'error') removeEnd++
      else break
    }
    messages.value.splice(aiMsgIndex, removeEnd - aiMsgIndex)

    // 同步缓存
    _msgCache.set(originSessionId, messages.value)

    // 创建新的 AI 占位消息
    const aiMsgId = generateId()
    const regenThinkingStart = performance.now()
    _addMsg('ai', '', {
      id: aiMsgId, thinkingSteps: [], thinkingFinished: false,
      thinkingStartTime: regenThinkingStart,
    }, originSessionId)

    let textStarted = false
    let _regenStreamIdx = -1
    let _regenStreamAgent = ''

    function findAiMsg(): ChatMessage | undefined {
      if (currentSessionId.value === originSessionId) {
        return messages.value.find(x => x.id === aiMsgId)
      }
      const cache = _msgCache.get(originSessionId as string)
      return cache?.find(x => x.id === aiMsgId)
    }

    const abortCtrl = new AbortController()
    _abortControllers.set(originSessionId, abortCtrl)

    try {
      await sendChatMessage(userText, originSessionId, {
        onThinking(e) {
          const label = resolveThinkingLabel(e.agent, e.display_label)
          const m = findAiMsg()
          if (!m) return
          if (!m.thinkingSteps) m.thinkingSteps = []
          const stepLabel = resolveThinkingLabel(e.agent, e.display_label)

          if (e.content) {
            _agentStatusBySession.value[originSessionId] = { name: e.agent, label, status: 'thinking', message: '正在推理...' }
            if (_regenStreamIdx >= 0 && _regenStreamAgent === e.agent && _regenStreamIdx < m.thinkingSteps.length) {
              m.thinkingSteps[_regenStreamIdx].streamContent = (m.thinkingSteps[_regenStreamIdx].streamContent ?? '') + e.content
              m.thinkingSteps[_regenStreamIdx].displayLabel = stepLabel
            } else {
              _regenStreamIdx = m.thinkingSteps.length
              _regenStreamAgent = e.agent
              m.thinkingSteps.push({
                id: generateId(),
                agent: e.agent,
                message: '正在推理...',
                streamContent: e.content,
                displayLabel: stepLabel,
              })
            }
          } else {
            _regenStreamIdx = -1
            _regenStreamAgent = ''
            _agentStatusBySession.value[originSessionId] = { name: e.agent, label, status: 'thinking', message: e.message }
            m.thinkingSteps.push({ id: generateId(), agent: e.agent, message: e.message, displayLabel: stepLabel })
          }
        },
        onText(e) {
          const m = findAiMsg()
          if (m) {
            m.content += e.content
            if (!textStarted) {
              textStarted = true
              m.thinkingFinished = true
              m.thinkingDuration = Math.round((performance.now() - regenThinkingStart) / 1000)
            }
          }
          if (e.is_final) _agentStatusBySession.value[originSessionId] = null
        },
        onArtifact(e) {
          if (isInlineArtifact(e)) {
            const m = findAiMsg()
            if (m) {
              if (!m.attachedArtifacts) m.attachedArtifacts = []
              m.attachedArtifacts.push(e)
            }
          }
          _addMsg('artifact', e.title ?? '生成式组件', { artifact: e }, originSessionId)
          if (isHiddenChatArtifact(e)) return
          if (e.component_type === 'WorkOrderCard' || e.widget === 'WorkOrderCard') {
            pendingWorkOrder.value = e
          }
        },
        onError(e) {
          _addMsg('error', e.message, undefined, originSessionId)
          _agentStatusBySession.value[originSessionId] = { name: '', label: '错误', status: 'error', message: e.message }
        },
        onDone() {
          _loadingBySession.value[originSessionId] = false
          _agentStatusBySession.value[originSessionId] = null
          const m = findAiMsg()
          if (m) {
            if (!m.thinkingFinished) m.thinkingFinished = true
            if (!m.thinkingDuration) {
              m.thinkingDuration = Math.round((performance.now() - regenThinkingStart) / 1000)
            }
          }
        },
        onNetworkError(err) {
          if (abortCtrl.signal.aborted) return
          _addMsg('error', `网络错误：${err.message}`, undefined, originSessionId)
          _loadingBySession.value[originSessionId] = false
        },
      }, webSearchEnabled.value, thinkingMode.value, abortCtrl.signal)
    } catch (err) {
      if (!abortCtrl.signal.aborted) {
        _addMsg('error', `请求失败：${(err as Error).message}`, undefined, originSessionId)
      }
      _loadingBySession.value[originSessionId] = false
    } finally {
      _abortControllers.delete(originSessionId)
    }
  }

  // ── 后台刷新指定会话元数据（仅更新标题等，不清消息） ─────────────────────
  async function _refreshSession(sid: string) {
    if (!sid) return
    try {
      const updated = await apiFetch<SessionInfo>(`/api/chat/sessions/${sid}`)
      const idx = sessionList.value.findIndex(s => s.session_id === sid)
      if (idx !== -1) {
        // 防止后端异步持久化未完成时，DB 返回的旧 message_count 覆盖本地乐观更新值
        const localCount = sessionList.value[idx].message_count
        if (updated.message_count < localCount) {
          updated.message_count = localCount
        }
        sessionList.value[idx] = updated
      }
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

  // ── 终止生成 ─────────────────────────────────────────────────────────────
  function stopGeneration() {
    const sid = currentSessionId.value
    if (!sid) return
    const ctrl = _abortControllers.get(sid)
    if (ctrl) {
      ctrl.abort()
      _abortControllers.delete(sid)
    }
    _loadingBySession.value[sid] = false
    _agentStatusBySession.value[sid] = null
    // 标记当前 AI 消息的思考为已完成
    const aiMsg = [...messages.value].reverse().find((m: ChatMessage) => m.role === 'ai')
    if (aiMsg && !aiMsg.thinkingFinished) {
      aiMsg.thinkingFinished = true
      if (!aiMsg.content) aiMsg.content = '（已终止生成）'
    }
  }

  // ── 联网搜索开关（当前会话级别）──────────────────────────────────────────
  function toggleWebSearch() {
    webSearchEnabled.value = !webSearchEnabled.value
  }

  // ── 清除当前会话消息（前端清屏） ──────────────────────────────────────────
  function clearSession() {
    const sid = currentSessionId.value
    const empty: ChatMessage[] = []
    messages.value = empty
    if (sid) {
      _msgCache.set(sid, empty)
      _loadingBySession.value[sid] = false
      _agentStatusBySession.value[sid] = null
    }
    pendingWorkOrder.value = null
  }

  return {
    sessionList, openTabs, sessionListLoading,
    currentSessionId, currentSession,
    messages, isLoading, currentAgentStatus, pendingWorkOrder, hasMessages,
    webSearchEnabled, thinkingMode,
    init, loadSessionList, newSession, switchSession, removeTab, closeSession,
    sendMessage, regenerateMessage, approveOrder, clearSession, renameSession,
    toggleWebSearch, toggleThinkingMode, stopGeneration,
  }
})
