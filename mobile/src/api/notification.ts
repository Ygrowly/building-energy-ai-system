import { get, post, BASE_URL } from './request'

export interface NotificationItem {
  recipient_id: string
  notification_id: string
  category: string
  event_type: string
  title: string
  body: string
  severity: 'info' | 'warning' | 'danger' | 'success' | string
  aggregate_type: string
  aggregate_id: string
  related_ticket_id: string | null
  related_dispatch_id: string | null
  cta_type: string | null
  cta_params: Record<string, any>
  created_at: string | null
  read_at: string | null
  payload: Record<string, any>
  bootstrap?: boolean
}

export interface NotificationListResponse {
  total: number
  page: number
  page_size: number
  notifications: NotificationItem[]
}

export interface NotificationSummary {
  total_unread: number
  categories: Record<string, number>
  event_types: Record<string, number>
}

export interface NotificationRealtimeTicket {
  ticket: string
  expires_in: number
}

export const notificationApi = {
  list(params?: {
    category?: string
    status?: 'all' | 'unread'
    page?: number
    page_size?: number
  }) {
    return get<NotificationListResponse>('/api/notifications', params as Record<string, unknown>)
  },

  summary() {
    return get<NotificationSummary>('/api/notifications/summary')
  },

  markRead(recipientIds: string[]) {
    return post<{ updated: number; recipient_ids: string[] }>('/api/notifications/mark-read', {
      recipient_ids: recipientIds,
    })
  },

  markAllRead(category = 'workorder') {
    return post<{ updated: number }>('/api/notifications/mark-all-read', { category })
  },

  createRealtimeTicket() {
    return post<NotificationRealtimeTicket>('/api/notifications/realtime-ticket')
  },
}

export function buildNotificationRealtimeUrl(ticket: string) {
  let base = BASE_URL
  if (!base && typeof window !== 'undefined' && window.location?.origin) {
    base = window.location.origin
  }
  const normalizedBase = (base || '').replace(/\/$/, '')
  const wsBase = normalizedBase.startsWith('https://')
    ? normalizedBase.replace(/^https:\/\//i, 'wss://')
    : normalizedBase.startsWith('http://')
      ? normalizedBase.replace(/^http:\/\//i, 'ws://')
      : normalizedBase
  return `${wsBase}/api/notifications/ws?ticket=${encodeURIComponent(ticket)}`
}
