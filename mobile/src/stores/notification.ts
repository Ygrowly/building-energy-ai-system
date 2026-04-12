import { computed, ref } from 'vue'
import { defineStore } from 'pinia'
import { useAuthStore } from './auth'
import {
  buildNotificationRealtimeUrl,
  notificationApi,
  type NotificationItem,
  type NotificationSummary,
} from '../api/notification'

const ELIGIBLE_ROLES = new Set(['ops', 'manager', 'admin'])
const DEFAULT_INTERVAL_MS = 60_000

function sortItems(items: NotificationItem[]) {
  return [...items].sort((a, b) => {
    const aRead = a.read_at ? 1 : 0
    const bRead = b.read_at ? 1 : 0
    if (aRead !== bRead) return aRead - bRead
    return new Date(b.created_at || 0).getTime() - new Date(a.created_at || 0).getTime()
  })
}

export const useNotificationStore = defineStore('mobile-notification-center', () => {
  const authStore = useAuthStore()

  const unreadCount = ref(0)
  const items = ref<NotificationItem[]>([])
  const total = ref(0)
  const loading = ref(false)
  const connected = ref(false)
  const summary = ref<NotificationSummary>({
    total_unread: 0,
    categories: {},
    event_types: {},
  })

  const isEligibleUser = computed(() => (
    authStore.isLoggedIn
    && Boolean(authStore.user?.role)
    && ELIGIBLE_ROLES.has(authStore.user?.role as string)
  ))

  let socketTask: UniApp.SocketTask | null = null
  let refreshTimer: ReturnType<typeof setInterval> | null = null
  let reconnectTimer: ReturnType<typeof setTimeout> | null = null
  let reconnectAttempt = 0
  let started = false

  function resetState() {
    items.value = []
    total.value = 0
    loading.value = false
    applySummary({ total_unread: 0, categories: {}, event_types: {} })
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
      disconnectRealtime()
      resetState()
      return
    }
    applySummary(await notificationApi.summary())
  }

  async function refresh(options: {
    status?: 'all' | 'unread'
    page?: number
    page_size?: number
  } = {}) {
    if (!isEligibleUser.value) {
      disconnectRealtime()
      resetState()
      return
    }

    loading.value = true
    try {
      const response = await notificationApi.list({
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
    await notificationApi.markRead(ids)
    const readAt = new Date().toISOString()
    for (const id of ids) applyRead(id, readAt)
    await refreshSummary()
  }

  async function markAllRead(category = 'workorder') {
    if (!isEligibleUser.value) return
    await notificationApi.markAllRead(category)
    const readAt = new Date().toISOString()
    items.value = items.value.map((item) => ({ ...item, read_at: item.read_at || readAt }))
    await refreshSummary()
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
    if (socketTask) {
      try {
        socketTask.close({})
      } catch {
        // noop
      }
      socketTask = null
    }
  }

  function handleSocketMessage(message: string) {
    if (!isEligibleUser.value) {
      disconnectRealtime()
      return
    }
    let payload: { type?: string; data?: any } = {}
    try {
      payload = JSON.parse(message)
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
    if (payload.type === 'notification.read' && payload.data?.recipient_id) {
      applyRead(payload.data.recipient_id, payload.data.read_at)
    }
  }

  function scheduleReconnect() {
    if (!started || !isEligibleUser.value || reconnectTimer) return
    const delay = Math.min(30_000, 1_000 * Math.max(1, 2 ** reconnectAttempt))
    reconnectAttempt += 1
    reconnectTimer = setTimeout(() => {
      reconnectTimer = null
      void connectRealtime()
    }, delay)
  }

  async function connectRealtime() {
    if (!isEligibleUser.value) {
      disconnectRealtime()
      return
    }
    if (socketTask) return
    try {
      const ticket = await notificationApi.createRealtimeTicket()
      socketTask = uni.connectSocket({
        url: buildNotificationRealtimeUrl(ticket.ticket),
        complete: () => {},
      })
      socketTask.onOpen(() => {
        connected.value = true
        reconnectAttempt = 0
      })
      socketTask.onMessage((event) => {
        if (typeof event.data === 'string') {
          handleSocketMessage(event.data)
        }
      })
      socketTask.onClose(() => {
        socketTask = null
        connected.value = false
        scheduleReconnect()
      })
      socketTask.onError(() => {
        connected.value = false
        try {
          socketTask?.close({})
        } catch {
          // noop
        }
      })
    } catch {
      connected.value = false
      scheduleReconnect()
    }
  }

  function start(intervalMs = DEFAULT_INTERVAL_MS) {
    started = true
    if (refreshTimer) {
      clearInterval(refreshTimer)
      refreshTimer = null
    }
    if (!isEligibleUser.value) {
      disconnectRealtime()
      resetState()
      return
    }
    void refresh()
    void connectRealtime()
    refreshTimer = setInterval(() => {
      if (!connected.value) {
        void refresh()
        void connectRealtime()
        return
      }
      void refreshSummary()
    }, intervalMs)
  }

  function stop(clearState = false) {
    started = false
    if (refreshTimer) {
      clearInterval(refreshTimer)
      refreshTimer = null
    }
    disconnectRealtime()
    if (clearState) {
      resetState()
    }
  }

  return {
    connected,
    items,
    loading,
    summary,
    total,
    unreadCount,
    markAllRead,
    markRead,
    refresh,
    refreshSummary,
    start,
    stop,
  }
})
