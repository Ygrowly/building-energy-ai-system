<template>
  <view class="page" :class="{ 'page-operator': isOperatorMode }">
    <NavBar :title="pageTitle" :bg-color="navBgColor" :text-color="navTextColor" :show-back="true">
      <template #right>
        <text class="nav-tag">{{ roleText }}</text>
      </template>
    </NavBar>

    <view class="page-body">
      <AiChat
        :title="pageTitle"
        :hint="chatHint"
        :mode="assistantMode"
      />
    </view>
  </view>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import NavBar from '../../../components/NavBar.vue'
import AiChat from '../../../components/AiChat.vue'
import { useAuthStore } from '../../../stores/auth'
import { ALLOWED_ROLES, ROLE_LABEL, isOperatorRole, type UserRole } from '../../../constants/roles'
import { useRouteGuard } from '../../../utils/route-guard'

useRouteGuard(ALLOWED_ROLES)

const authStore = useAuthStore()
const role = computed(() => authStore.user?.role as UserRole | undefined)
const isOperatorMode = computed(() => Boolean(role.value && isOperatorRole(role.value)))
const roleText = computed(() => {
  return role.value ? ROLE_LABEL[role.value] : 'AI'
})
const assistantMode = computed(() => (isOperatorMode.value ? 'operator' : 'general'))
const pageTitle = computed(() => (isOperatorMode.value ? '运小维' : 'AI 对话'))
const chatHint = computed(() => (
  isOperatorMode.value
    ? '直接输入问题或点击快捷问法'
    : '输入问题即可开始'
))
const navBgColor = computed(() => (isOperatorMode.value ? '#f5faf3' : '#ffffff'))
const navTextColor = computed(() => (isOperatorMode.value ? '#294434' : '#202024'))
</script>

<style lang="scss" scoped>
.page {
  min-height: 100vh;
  background:
    radial-gradient(circle at 12% 8%, rgba(86, 196, 185, 0.18), transparent 32%),
    radial-gradient(circle at 86% 18%, rgba(244, 116, 116, 0.14), transparent 28%),
    linear-gradient(180deg, #f7f9fb 0%, #ffffff 100%);
}

.page-operator {
  background:
    radial-gradient(circle at 18% 0%, rgba(142, 188, 116, 0.16), transparent 30%),
    radial-gradient(circle at 84% 14%, rgba(200, 224, 166, 0.22), transparent 28%),
    linear-gradient(180deg, #f6f9ef 0%, #ffffff 100%);
}

.nav-tag {
  max-width: 120rpx;
  font-size: 20rpx;
  line-height: 1.3;
  color: #626973;
  text-align: right;
}

.page-body {
  height: calc(100vh - 132rpx);
  padding: 24rpx 24rpx calc(24rpx + env(safe-area-inset-bottom, 0px));
  box-sizing: border-box;
}

:deep(.ai-chat) {
  height: 100%;
  display: flex;
  flex-direction: column;
  border-radius: 32rpx;
  box-shadow: 0 22rpx 52rpx rgba(43, 52, 66, 0.08);
  overflow: hidden;
}

:deep(.chat-messages) {
  flex: 1;
  min-height: 0;
  height: auto;
}
</style>
