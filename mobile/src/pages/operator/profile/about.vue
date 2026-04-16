<template>
  <view class="page theme-operator">
    <NavBar title="关于" bg-color="#2f855a" :show-back="true" />

    <view class="about-card">
      <view class="app-logo">
        <text class="logo-text">E</text>
      </view>
      <text class="app-name">楼宇能耗管理</text>
      <text class="app-version">v1.0.0</text>
    </view>

    <view class="info-section">
      <view class="info-item">
        <text class="info-label">系统平台</text>
        <text class="info-value">{{ systemInfo }}</text>
      </view>
      <view class="info-divider" />
      <view class="info-item">
        <text class="info-label">开发团队</text>
        <text class="info-value">A08</text>
      </view>
    </view>
  </view>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import NavBar from '../../../components/NavBar.vue'
import { useRouteGuard } from '../../../utils/route-guard'
import { OPERATOR_ROLES } from '../../../constants/roles'

useRouteGuard(OPERATOR_ROLES)

const systemInfo = ref('')

onMounted(() => {
  try {
    const info = uni.getSystemInfoSync()
    systemInfo.value = `${info.platform} ${info.system}`
  } catch {
    systemInfo.value = '未知'
  }
})
</script>

<style lang="scss" scoped>
.page { background: var(--operator-bg, #eef5ef); min-height: 100vh; }

.about-card {
  display: flex;
  flex-direction: column;
  align-items: center;
  padding: 60rpx 32rpx 48rpx;
}

.app-logo {
  width: 120rpx;
  height: 120rpx;
  border-radius: 28rpx;
  background: var(--operator-btn, linear-gradient(135deg, #42bf72, #2f855a));
  display: flex;
  align-items: center;
  justify-content: center;
  margin-bottom: 24rpx;
  box-shadow: 0 14rpx 28rpx rgba(47, 133, 90, 0.22);
}

.logo-text {
  font-size: 56rpx;
  color: #fff;
  font-weight: 700;
}

.app-name {
  font-size: 32rpx;
  font-weight: 700;
  color: var(--operator-text, #163022);
  margin-bottom: 8rpx;
}

.app-version {
  font-size: 24rpx;
  color: var(--operator-text-muted, #8aa091);
}

.info-section {
  background: var(--operator-card, #fff);
  border-radius: 20rpx;
  margin: 0 32rpx;
  overflow: hidden;
  border: 1rpx solid var(--operator-border, rgba(203, 225, 208, 0.96));
  box-shadow: var(--operator-shadow, 0 12rpx 34rpx rgba(35, 75, 54, 0.1));
}

.info-item {
  display: flex;
  align-items: center;
  padding: 32rpx 28rpx;
}

.info-label {
  flex: 1;
  font-size: 28rpx;
  color: var(--operator-text-secondary, #5b6f62);
}

.info-value {
  font-size: 28rpx;
  color: var(--operator-text, #163022);
}

.info-divider {
  height: 1rpx;
  background: var(--operator-border, rgba(203, 225, 208, 0.96));
  margin: 0 28rpx;
}
</style>
