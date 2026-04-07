/**
 * 通知中心 Store
 * 全局轮询未读异常告警数，驱动侧边栏铃铛角标。
 * 轮询间隔默认 5 分钟，与 anomaly_detector 每小时扫描节奏匹配。
 */
import { defineStore } from 'pinia'
import { ref } from 'vue'
import { cachedApiFetch } from '@/api/cached'

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
      const data = await cachedApiFetch<{ total?: number }>(
        '/api/anomalies/recent?hours=8760',
        undefined,
        { ttlMs: 60_000 },
      )
      unreadCount.value = data?.total ?? 0
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
