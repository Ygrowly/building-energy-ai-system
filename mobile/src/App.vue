<template>
  <App />
</template>

<script setup lang="ts">
import { computed, watch } from 'vue'
import { onHide, onLaunch, onShow } from '@dcloudio/uni-app'
import { useAuthStore } from './stores/auth'
import { useNotificationStore } from './stores/notification'

const authStore = useAuthStore()
const notificationStore = useNotificationStore()
const isEligibleNotificationUser = computed(() => (
  authStore.isLoggedIn
  && ['ops', 'manager', 'admin'].includes(authStore.user?.role || '')
))

function syncNotificationLifecycle() {
  notificationStore.stop(true)
  if (isEligibleNotificationUser.value) {
    notificationStore.start()
  }
}

onLaunch(() => {
  // 启动时检查登录态，自动跳转
  authStore.init()
  syncNotificationLifecycle()
})

onShow(() => {
  if (isEligibleNotificationUser.value) {
    notificationStore.start()
  }
  // 每次回到前台刷新 token 状态
})
onHide(() => {
  notificationStore.stop()
})

watch(
  () => [authStore.isLoggedIn, authStore.user?.id, authStore.user?.role] as const,
  (next, prev) => {
    if (!prev) return
    if (next[0] === prev[0] && next[1] === prev[1] && next[2] === prev[2]) return
    syncNotificationLifecycle()
  },
)
</script>

<style lang="scss">
@import './uni.scss';
</style>
