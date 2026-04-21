<template>
  <App />
</template>

<script setup lang="ts">
import { computed, onUnmounted, watch } from 'vue'
import { onHide, onLaunch, onShow } from '@dcloudio/uni-app'
import { useAuthStore } from './stores/auth'
import { useNotificationStore } from './stores/notification'
import { registerAuthResetHandler } from './utils/auth-session'

const authStore = useAuthStore()
const notificationStore = useNotificationStore()
const isEligibleNotificationUser = computed(() => (
  authStore.sessionReady
  && authStore.isLoggedIn
  && ['ops', 'manager', 'admin'].includes(authStore.user?.role || '')
))

function syncNotificationLifecycle() {
  notificationStore.stop(true)
  if (isEligibleNotificationUser.value) {
    notificationStore.start()
  }
}

const unregisterAuthResetHandler = registerAuthResetHandler(() => {
  notificationStore.stop(true)
  authStore._clearTokens()
})

onLaunch(() => {
  // 启动时检查登录态，自动跳转
  authStore.init()
  syncNotificationLifecycle()
})

onShow(() => {
  syncNotificationLifecycle()
})
onHide(() => {
  notificationStore.stop()
})

onUnmounted(() => {
  unregisterAuthResetHandler()
})

watch(
  () => [authStore.sessionReady, authStore.isLoggedIn, authStore.user?.id, authStore.user?.role] as const,
  (next, prev) => {
    if (!prev) return
    if (next[0] === prev[0] && next[1] === prev[1] && next[2] === prev[2] && next[3] === prev[3]) return
    syncNotificationLifecycle()
  },
)
</script>

<style lang="scss">
@import './uni.scss';
</style>
