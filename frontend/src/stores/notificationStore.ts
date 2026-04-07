/**
 * 通知中心 Store
 * 全局轮询未读异常告警数，驱动侧边栏铃铛角标。
 * 轮询间隔默认 5 分钟，与 anomaly_detector 每小时扫描节奏匹配。
 */
import { defineStore } from 'pinia'
import { ref } from 'vue'
import { cachedApiFetch } from '@/api/cached'
import {
  buildWorkorderNotificationItems,
  type WorkorderNotificationHallEntry,
  type WorkorderNotificationIncident,
} from '@/utils/workorderNotification'

export const useNotificationStore = defineStore('notification', () => {
  const unreadCount = ref(0)
  const sidebarAvatarUrl = ref('')
  let _timer: ReturnType<typeof setInterval> | null = null

  /** 从 localStorage 读取指定用户头像，更新侧边栏显示 */
  function loadAvatar(userId?: string | number) {
    const key = `avatar_${userId ?? 'guest'}`
    sidebarAvatarUrl.value = localStorage.getItem(key) ?? ''
  }

  /** 保存新头像并同步到侧边栏 */
  function saveAvatar(userId: string | number, dataUrl: string) {
    localStorage.setItem(`avatar_${userId}`, dataUrl)
    sidebarAvatarUrl.value = dataUrl
  }

  async function refresh() {
    try {
      const [incidentData, hallData, anomalyData, predictionData] = await Promise.all([
        apiFetch<{ incidents?: WorkorderNotificationIncident[] }>(
          '/api/incidents?workflow_status=pending_review,pending_dispatch,dispatched,completed,false_alarm,escalated&page=1&page_size=100',
        ),
        apiFetch<{ hall_entries?: WorkorderNotificationHallEntry[] }>(
          '/api/dispatch-hall?status=open&entry_type=support_request,takeover_candidate&include_applications=true&page=1&page_size=50',
        ),
        apiFetch<{ total?: number; anomalies?: unknown[] }>('/api/anomalies/recent?hours=168'),
        apiFetch<{ predictions?: Array<{ risk_level?: string | null; as_of_timestamp?: string | null; created_at?: string | null }> }>(
          '/api/predictions/recent?hours=168',
        ),
      ])

      const workorderCount = buildWorkorderNotificationItems(
        incidentData?.incidents ?? [],
        hallData?.hall_entries ?? [],
      ).length
      const anomalyCount = anomalyData?.total ?? anomalyData?.anomalies?.length ?? 0
      const predictionList = predictionData?.predictions ?? []
      const latestPredictionBatchAt = predictionList
        .map((item) => item.as_of_timestamp || item.created_at)
        .filter((value): value is string => Boolean(value))
        .sort((a, b) => new Date(b).getTime() - new Date(a).getTime())[0]
      const warningCount = predictionList.filter((item) =>
        (item.as_of_timestamp || item.created_at) === latestPredictionBatchAt
        && ['warning', 'critical'].includes(item.risk_level || ''),
      ).length

      unreadCount.value = workorderCount + anomalyCount + warningCount
    } catch {
      // 静默失败，不影响主业务
    }
  }

  /** 打开消息中心后调用，清除角标 */
  function clearBadge() {
    unreadCount.value = 0
  }

  /** 应用挂载时启动，interval 单位毫秒，默认 5 分钟 */
  function startPolling(intervalMs = 5 * 60 * 1000) {
    refresh()
    if (_timer) clearInterval(_timer)
    _timer = setInterval(refresh, intervalMs)
  }

  function stopPolling() {
    if (_timer) {
      clearInterval(_timer)
      _timer = null
    }
  }

  /** Home 页铃铛触发打开消息面板，App.vue 监听此标志 */
  const messagesRequested = ref(false)
  function requestOpenMessages() {
    messagesRequested.value = true
  }
  function consumeMessagesRequest() {
    messagesRequested.value = false
  }

  return { unreadCount, sidebarAvatarUrl, loadAvatar, saveAvatar, refresh, clearBadge, startPolling, stopPolling, messagesRequested, requestOpenMessages, consumeMessagesRequest }
})
