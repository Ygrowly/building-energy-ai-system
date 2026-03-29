<template>
  <view class="login-page">
    <!-- 顶部背景装饰 -->
    <view class="header-bg">
      <view class="header-content">
        <view class="logo-wrap">
          <text class="logo-icon">⚡</text>
        </view>
        <text class="app-title">楼宇能耗管理</text>
        <text class="app-subtitle">Building Energy Management</text>
      </view>
    </view>

    <!-- 登录表单卡片 -->
    <view class="form-card">
      <text class="form-title">账号登录</text>

      <view class="input-group">
        <text class="input-label">用户名</text>
        <input
          class="input-field"
          v-model="username"
          placeholder="请输入用户名"
          placeholder-class="placeholder"
          :disabled="loading"
        />
      </view>

      <view class="input-group">
        <text class="input-label">密码</text>
        <input
          class="input-field"
          v-model="password"
          placeholder="请输入密码"
          placeholder-class="placeholder"
          password
          :disabled="loading"
          @confirm="handleLogin"
        />
      </view>

      <button
        class="login-btn"
        :class="{ loading }"
        :disabled="loading || !username || !password"
        @click="handleLogin"
      >
        <text v-if="!loading">登 录</text>
        <text v-else>登录中...</text>
      </button>

      <view v-if="errorMsg" class="error-msg">
        <text>{{ errorMsg }}</text>
      </view>
    </view>

    <!-- 底部角色说明 -->
    <view class="role-hint">
      <view class="role-item">
        <view class="role-dot operator" />
        <text>运维人员：能耗监控 · 工单审阅</text>
      </view>
      <view class="role-item">
        <view class="role-dot worker" />
        <text>维修人员：处理工单 · AI辅助维修</text>
      </view>
    </view>
  </view>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { useAuthStore } from '../../stores/auth'

const authStore = useAuthStore()
const username = ref('')
const password = ref('')
const loading = ref(false)
const errorMsg = ref('')

async function handleLogin() {
  if (!username.value.trim() || !password.value) return
  errorMsg.value = ''
  loading.value = true
  try {
    await authStore.login(username.value.trim(), password.value)
  } catch (err: any) {
    errorMsg.value = err?.message || '登录失败，请检查用户名和密码'
  } finally {
    loading.value = false
  }
}
</script>

<style lang="scss" scoped>
.login-page {
  min-height: 100vh;
  background: #f5f7fa;
  display: flex;
  flex-direction: column;
}

.header-bg {
  background: linear-gradient(145deg, #1a1a2e 0%, #16213e 60%, #0f3460 100%);
  padding: 100rpx 48rpx 80rpx;
  border-radius: 0 0 48rpx 48rpx;
}

.header-content {
  display: flex;
  flex-direction: column;
  align-items: center;
}

.logo-wrap {
  width: 120rpx;
  height: 120rpx;
  background: rgba(255,255,255,0.12);
  border-radius: 32rpx;
  display: flex;
  align-items: center;
  justify-content: center;
  margin-bottom: 24rpx;
  border: 1rpx solid rgba(255,255,255,0.2);
}

.logo-icon {
  font-size: 64rpx;
}

.app-title {
  font-size: 48rpx;
  font-weight: 700;
  color: #fff;
  margin-bottom: 10rpx;
  letter-spacing: 2rpx;
}

.app-subtitle {
  font-size: 24rpx;
  color: rgba(255,255,255,0.5);
  letter-spacing: 1rpx;
}

.form-card {
  background: #fff;
  border-radius: 24rpx;
  padding: 48rpx 40rpx;
  margin: -32rpx 32rpx 0;
  box-shadow: 0 8rpx 40rpx rgba(0,0,0,0.10);
}

.form-title {
  font-size: 36rpx;
  font-weight: 700;
  color: #1a1a2e;
  margin-bottom: 40rpx;
  display: block;
}

.input-group {
  margin-bottom: 32rpx;
}

.input-label {
  font-size: 26rpx;
  color: #666;
  margin-bottom: 12rpx;
  display: block;
}

.input-field {
  width: 100%;
  height: 88rpx;
  background: #f5f7fa;
  border-radius: 12rpx;
  padding: 0 28rpx;
  font-size: 30rpx;
  color: #1a1a2e;
  border: 2rpx solid transparent;
  box-sizing: border-box;

  &:focus {
    border-color: #3b6cf4;
    background: #fff;
  }
}

.placeholder {
  color: #bbb;
}

.login-btn {
  width: 100%;
  height: 96rpx;
  background: linear-gradient(90deg, #3b6cf4, #5b8cf8);
  border-radius: 48rpx;
  border: none;
  color: #fff;
  font-size: 32rpx;
  font-weight: 600;
  letter-spacing: 4rpx;
  margin-top: 16rpx;
  display: flex;
  align-items: center;
  justify-content: center;

  &[disabled] {
    opacity: 0.5;
    background: linear-gradient(90deg, #3b6cf4, #5b8cf8);
  }

  &.loading {
    opacity: 0.7;
  }
}

.error-msg {
  margin-top: 20rpx;
  padding: 16rpx 20rpx;
  background: #fff2f0;
  border-radius: 8rpx;
  border-left: 4rpx solid #ff4d4f;

  text {
    font-size: 26rpx;
    color: #ff4d4f;
  }
}

.role-hint {
  padding: 40rpx 48rpx;
  display: flex;
  flex-direction: column;
  gap: 16rpx;
}

.role-item {
  display: flex;
  align-items: center;
  gap: 14rpx;

  text {
    font-size: 24rpx;
    color: #999;
  }
}

.role-dot {
  width: 14rpx;
  height: 14rpx;
  border-radius: 50%;

  &.operator { background: #3b6cf4; }
  &.worker   { background: #00b96b; }
}
</style>
