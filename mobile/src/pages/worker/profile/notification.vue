<template>
  <view class="page">
    <NavBar title="消息通知" bg-color="#0f3d2e" :show-back="true" />

    <view class="section">
      <view class="section-title">推送设置</view>
      <view class="card">
        <view class="switch-item">
          <view class="switch-info">
            <text class="switch-label">工单状态通知</text>
            <text class="switch-desc">工单分配、状态变更时推送通知</text>
          </view>
          <switch :checked="workorderNotify" color="#00b96b" @change="onWorkorderChange" />
        </view>
        <view class="card-divider" />
        <view class="switch-item">
          <view class="switch-info">
            <text class="switch-label">异常告警通知</text>
            <text class="switch-desc">设备能耗异常时推送告警通知</text>
          </view>
          <switch :checked="alertNotify" color="#00b96b" @change="onAlertChange" />
        </view>
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

const STORAGE_KEY = 'notify_prefs'

const workorderNotify = ref(true)
const alertNotify = ref(true)

onMounted(() => {
  try {
    const raw = uni.getStorageSync(STORAGE_KEY)
    if (raw) {
      const prefs = typeof raw === 'string' ? JSON.parse(raw) : raw
      workorderNotify.value = prefs.workorder ?? true
      alertNotify.value = prefs.alert ?? true
    }
  } catch { /* use defaults */ }
})

function savePrefs() {
  uni.setStorageSync(STORAGE_KEY, JSON.stringify({
    workorder: workorderNotify.value,
    alert: alertNotify.value,
  }))
}

function onWorkorderChange(e: any) {
  workorderNotify.value = e.detail.value
  savePrefs()
}

function onAlertChange(e: any) {
  alertNotify.value = e.detail.value
  savePrefs()
}
</script>

<style lang="scss" scoped>
.page { background: #f0f5f2; min-height: 100vh; }

.section {
  margin: 24rpx 32rpx 0;
}

.section-title {
  font-size: 26rpx;
  color: #999;
  margin-bottom: 16rpx;
  padding-left: 8rpx;
}

.card {
  background: #fff;
  border-radius: 16rpx;
  overflow: hidden;
}

.switch-item {
  display: flex;
  align-items: center;
  padding: 28rpx;
  gap: 20rpx;
}

.switch-info {
  flex: 1;
}

.switch-label {
  display: block;
  font-size: 28rpx;
  color: #1a1a2e;
  margin-bottom: 6rpx;
}

.switch-desc {
  display: block;
  font-size: 22rpx;
  color: #999;
}

.card-divider {
  height: 1rpx;
  background: #f5f5f5;
  margin: 0 28rpx;
}
</style>
