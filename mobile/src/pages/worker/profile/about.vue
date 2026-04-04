<template>
  <view class="page">
    <NavBar title="关于" bg-color="#0f3d2e" :show-back="true" />

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
import { WORKER_ROLES } from '../../../constants/roles'

useRouteGuard(WORKER_ROLES)

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
.page { background: #f0f5f2; min-height: 100vh; }

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
  background: linear-gradient(135deg, #00b96b, #38ef7d);
  display: flex;
  align-items: center;
  justify-content: center;
  margin-bottom: 24rpx;
}

.logo-text {
  font-size: 56rpx;
  color: #fff;
  font-weight: 700;
}

.app-name {
  font-size: 32rpx;
  font-weight: 700;
  color: #1a1a2e;
  margin-bottom: 8rpx;
}

.app-version {
  font-size: 24rpx;
  color: #999;
}

.info-section {
  background: #fff;
  border-radius: 16rpx;
  margin: 0 32rpx;
  overflow: hidden;
}

.info-item {
  display: flex;
  align-items: center;
  padding: 32rpx 28rpx;
}

.info-label {
  flex: 1;
  font-size: 28rpx;
  color: #666;
}

.info-value {
  font-size: 28rpx;
  color: #1a1a2e;
}

.info-divider {
  height: 1rpx;
  background: #f5f5f5;
  margin: 0 28rpx;
}
</style>
