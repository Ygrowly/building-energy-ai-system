<template>
  <App />
</template>

<script setup lang="ts">
import { onLaunch, onShow } from '@dcloudio/uni-app'
import { useAuthStore } from './stores/auth'

const authStore = useAuthStore()

onLaunch(() => {
  // 启动时检查登录态，自动跳转
  authStore.init()
})

onShow(() => {
  // 每次回到前台刷新 token 状态
})
</script>

<style lang="scss">
@import './uni.scss';
</style>
