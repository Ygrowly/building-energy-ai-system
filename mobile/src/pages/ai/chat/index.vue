<template>
  <view class="page">
    <NavBar title="AI 对话" bg-color="#ffffff" text-color="#202024" :show-back="true">
      <template #right>
        <text class="nav-tag">{{ roleText }}</text>
      </template>
    </NavBar>

    <scroll-view scroll-y class="page-scroll">
      <view class="intro">
        <text class="intro-kicker">AI Assistant</text>
        <text class="intro-title">{{ assistantMode === 'operator' ? '今天想分析什么？' : '今天想查什么？' }}</text>
        <text class="intro-copy">{{ assistantMode === 'operator' ? '可按时间、楼宇、班组、人员做只读运营分析。' : '能耗、派工、维修流程都可以直接问。' }}</text>
      </view>

      <AiChat
        title="AI 对话"
        hint="输入问题即可开始"
        :mode="assistantMode"
      />
    </scroll-view>
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
const roleText = computed(() => {
  const role = authStore.user?.role as UserRole | undefined
  return role ? ROLE_LABEL[role] : 'AI'
})
const assistantMode = computed(() => {
  const role = authStore.user?.role as UserRole | undefined
  return role && isOperatorRole(role) ? 'operator' : 'general'
})
</script>

<style lang="scss" scoped>
.page {
  min-height: 100vh;
  background:
    radial-gradient(circle at 12% 8%, rgba(86, 196, 185, 0.18), transparent 32%),
    radial-gradient(circle at 86% 18%, rgba(244, 116, 116, 0.14), transparent 28%),
    linear-gradient(180deg, #f7f9fb 0%, #ffffff 100%);
}

.nav-tag {
  max-width: 88rpx;
  font-size: 20rpx;
  line-height: 1.2;
  color: #626973;
  text-align: right;
}

.page-scroll {
  height: calc(100vh - 132rpx);
  padding: 28rpx 24rpx calc(56rpx + env(safe-area-inset-bottom, 0px));
  box-sizing: border-box;
}

.intro {
  padding: 16rpx 4rpx 28rpx;
}

.intro-kicker {
  display: block;
  font-size: 22rpx;
  color: #6f7682;
  letter-spacing: 0;
  margin-bottom: 12rpx;
}

.intro-title {
  display: block;
  font-size: 44rpx;
  line-height: 1.18;
  font-weight: 800;
  color: #202024;
}

.intro-copy {
  display: block;
  margin-top: 14rpx;
  font-size: 26rpx;
  line-height: 1.55;
  color: #747b86;
}

:deep(.ai-chat) {
  border-radius: 28rpx;
  box-shadow: 0 18rpx 42rpx rgba(43, 52, 66, 0.08);
}

:deep(.chat-messages) {
  height: calc(100vh - 560rpx);
  min-height: 480rpx;
}
</style>
