import { apiFetch } from '@/api/http'

const API_BASE = (import.meta.env.VITE_API_BASE as string | undefined) ?? ''

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
  cta_params: Record<string, unknown>
  created_at: string | null
  read_at: string | null
  payload: Record<string, unknown>
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

export function listNotifications(params?: {
  category?: string
  status?: 'all' | 'unread'
  page?: number
  page_size?: number
}) {
  const search = new URLSearchParams()
  if (params?.category) search.set('category', params.category)
  if (params?.status) search.set('status', params.status)
  if (params?.page) search.set('page', String(params.page))
  if (params?.page_size) search.set('page_size', String(params.page_size))
  const qs = search.toString()
  return apiFetch<NotificationListResponse>(`/api/notifications${qs ? `?${qs}` : ''}`)
}

export function getNotificationSummary() {
  return apiFetch<NotificationSummary>('/api/notifications/summary')
}

export function markNotificationsRead(recipientIds: string[]) {
  return apiFetch<{ updated: number; recipient_ids: string[] }>('/api/notifications/mark-read', {
    method: 'POST',
    body: JSON.stringify({ recipient_ids: recipientIds }),
  })
}

export function markAllNotificationsRead(category = 'workorder') {
  return apiFetch<{ updated: number }>('/api/notifications/mark-all-read', {
    method: 'POST',
    body: JSON.stringify({ category }),
  })
}

export function createNotificationRealtimeTicket() {
  return apiFetch<NotificationRealtimeTicket>('/api/notifications/realtime-ticket', {
    method: 'POST',
  })
}

export function buildNotificationRealtimeUrl(ticket: string): string {
  const baseUrl = API_BASE ? new URL(API_BASE, window.location.origin) : new URL(window.location.origin)
  baseUrl.protocol = baseUrl.protocol === 'https:' ? 'wss:' : 'ws:'
  const basePath = baseUrl.pathname.replace(/\/$/, '')
  baseUrl.pathname = `${basePath}/api/notifications/ws`
  baseUrl.search = ''
  baseUrl.searchParams.set('ticket', ticket)
  return baseUrl.toString()
}
