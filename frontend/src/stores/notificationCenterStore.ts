import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import { useAuthStore } from '@/stores/authStore'
import {
  buildNotificationRealtimeUrl,
  createNotificationRealtimeTicket,
  getNotificationSummary,
  listNotifications,
  markAllNotificationsRead,
  markNotificationsRead,
  type NotificationItem,
  type NotificationSummary,
} from '@/api/notifications'

const DEFAULT_INTERVAL_MS = 60_000
const ELIGIBLE_ROLES = new Set(['ops', 'manager', 'admin'])

function isEligibleRole(role?: string | null) {
  return Boolean(role && ELIGIBLE_ROLES.has(role))
}

function normalizeUrl(url: string) {
  if (/^wss?:\/\//i.test(url)) return url
  if (url.startsWith('//')) {
    return `${window.location.protocol === 'https:' ? 'wss:' : 'ws:'}${url}`
  }
  if (url.startsWith('/')) {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    return `${protocol}//${window.location.host}${url}`
  }
  return url
}

function sortItems(items: NotificationItem[]) {
  return [...items].sort((a, b) => {
    const aRead = a.read_at ? 1 : 0
    const bRead = b.read_at ? 1 : 0
    if (aRead !== bRead) return aRead - bRead
    return new Date(b.created_at || 0).getTime() - new Date(a.created_at || 0).getTime()
  })
}

export const useNotificationStore = defineStore('notification-center', () => {
  const authStore = useAuthStore()

  const unreadCount = ref(0)
  const sidebarAvatarUrl = ref('')
  const items = ref<NotificationItem[]>([])
  const total = ref(0)
  const loading = ref(false)
  const connected = ref(false)
  const summary = ref<NotificationSummary>({
    total_unread: 0,
    categories: {},
    event_types: {},
  })
  const messagesRequested = ref(false)

  let refreshTimer: ReturnType<typeof setInterval> | null = null
  let socket: WebSocket | null = null
  let reconnectTimer: ReturnType<typeof setTimeout> | null = null
  let reconnectAttempt = 0
  let pollingStarted = false

  const isEligibleUser = computed(() => (
    authStore.isLoggedIn
    && isEligibleRole(authStore.user?.role)
  ))

  function loadAvatar(userId?: string | number) {
    const key = `avatar_${userId ?? 'guest'}`
    sidebarAvatarUrl.value = localStorage.getItem(key) ?? ''
  }

  function saveAvatar(userId: string | number, dataUrl: string) {
    localStorage.setItem(`avatar_${userId}`, dataUrl)
    sidebarAvatarUrl.value = dataUrl
  }

  function consumeMessagesRequest() {
    messagesRequested.value = false
  }

  function requestOpenMessages() {
    messagesRequested.value = true
  }

  function applySummary(nextSummary: NotificationSummary) {
    summary.value = nextSummary
    unreadCount.value = nextSummary.total_unread ?? 0
  }

  function upsertItem(nextItem: NotificationItem) {
    const next = [...items.value]
    const index = next.findIndex((item) => item.recipient_id === nextItem.recipient_id)
    if (index >= 0) {
      next[index] = { ...next[index], ...nextItem }
    } else {
      next.unshift(nextItem)
      total.value += 1
    }
    items.value = sortItems(next)
  }

  function applyRead(recipientId: string, readAt?: string | null) {
    items.value = sortItems(items.value.map((item) => (
      item.recipient_id === recipientId
        ? { ...item, read_at: readAt || new Date().toISOString() }
        : item
    )))
  }

  async function refreshSummary() {
    if (!isEligibleUser.value) {
      applySummary({ total_unread: 0, categories: {}, event_types: {} })
      return
    }
    applySummary(await getNotificationSummary())
  }

  async function refresh(options: {
    status?: 'all' | 'unread'
    page?: number
    page_size?: number
  } = {}) {
    if (!isEligibleUser.value) {
      items.value = []
      total.value = 0
      applySummary({ total_unread: 0, categories: {}, event_types: {} })
      return
    }

    loading.value = true
    try {
      const response = await listNotifications({
        category: 'workorder',
        status: options.status ?? 'all',
        page: options.page ?? 1,
        page_size: options.page_size ?? 50,
      })
      items.value = sortItems(response.notifications ?? [])
      total.value = response.total ?? items.value.length
      await refreshSummary()
    } finally {
      loading.value = false
    }
  }

  async function markRead(recipientIds: string[]) {
    const ids = recipientIds.filter(Boolean)
    if (!ids.length || !isEligibleUser.value) return
    await markNotificationsRead(ids)
    const readAt = new Date().toISOString()
    for (const id of ids) applyRead(id, readAt)
    await refreshSummary()
  }

  async function markAllRead(category = 'workorder') {
    if (!isEligibleUser.value) return
    await markAllNotificationsRead(category)
    const readAt = new Date().toISOString()
    items.value = items.value.map((item) => ({ ...item, read_at: item.read_at || readAt }))
    await refreshSummary()
  }

  function clearBadge() {
    if (!isEligibleUser.value) {
      unreadCount.value = 0
    }
  }

  function handleSocketMessage(raw: string) {
    let payload: { type?: string; data?: unknown } = {}
    try {
      payload = JSON.parse(raw) as { type?: string; data?: unknown }
    } catch {
      return
    }

    if (payload.type === 'notification.summary' && payload.data) {
      applySummary(payload.data as NotificationSummary)
      return
    }
    if (payload.type === 'notification.created' && payload.data) {
      upsertItem(payload.data as NotificationItem)
      return
    }
    if (payload.type === 'notification.read' && payload.data && typeof payload.data === 'object') {
      const data = payload.data as { recipient_id?: string; read_at?: string | null }
      if (data.recipient_id) applyRead(data.recipient_id, data.read_at)
    }
  }

  function clearReconnectTimer() {
    if (reconnectTimer) {
      clearTimeout(reconnectTimer)
      reconnectTimer = null
    }
  }

  function disconnectRealtime() {
    clearReconnectTimer()
    connected.value = false
    reconnectAttempt = 0
    if (socket) {
      try {
        socket.close()
      } catch {
        // noop
      }
      socket = null
    }
  }

  function scheduleReconnect() {
    if (!pollingStarted || !isEligibleUser.value || reconnectTimer) return
    const delay = Math.min(30_000, 1_000 * Math.max(1, 2 ** reconnectAttempt))
    reconnectAttempt += 1
    reconnectTimer = setTimeout(() => {
      reconnectTimer = null
      void connectRealtime()
    }, delay)
  }

  async function connectRealtime() {
    if (!isEligibleUser.value || socket) return
    try {
      const ticket = await createNotificationRealtimeTicket()
      const url = normalizeUrl(buildNotificationRealtimeUrl(ticket.ticket))
      const nextSocket = new WebSocket(url)
      socket = nextSocket

      nextSocket.onopen = () => {
        connected.value = true
        reconnectAttempt = 0
      }

      nextSocket.onmessage = (event) => {
        if (typeof event.data === 'string') {
          handleSocketMessage(event.data)
        }
      }

      nextSocket.onclose = () => {
        if (socket === nextSocket) {
          socket = null
        }
        connected.value = false
        scheduleReconnect()
      }

      nextSocket.onerror = () => {
        nextSocket.close()
      }
    } catch {
      connected.value = false
      scheduleReconnect()
    }
  }

  function startPolling(intervalMs = DEFAULT_INTERVAL_MS) {
    pollingStarted = true
    void refresh()
    void connectRealtime()
    if (refreshTimer) clearInterval(refreshTimer)
    refreshTimer = setInterval(() => {
      if (!connected.value) {
        void refresh()
        void connectRealtime()
        return
      }
      void refreshSummary()
    }, intervalMs)
  }

  function stopPolling() {
    pollingStarted = false
    if (refreshTimer) {
      clearInterval(refreshTimer)
      refreshTimer = null
    }
    disconnectRealtime()
  }

  return {
    connected,
    items,
    loading,
    messagesRequested,
    sidebarAvatarUrl,
    summary,
    total,
    unreadCount,
    clearBadge,
    consumeMessagesRequest,
    loadAvatar,
    markAllRead,
    markRead,
    refresh,
    refreshSummary,
    requestOpenMessages,
    saveAvatar,
    startPolling,
    stopPolling,
  }
})
