<template>
  <view class="page">
    <NavBar title="能耗总览" bg-color="#1a1a2e">
      <template #right>
        <text class="refresh-btn" @click="loadData">↻</text>
      </template>
    </NavBar>

    <!-- 用户欢迎 -->
    <view class="welcome-row">
      <view>
        <text class="welcome-name">{{ authStore.user?.username }}</text>
        <text class="welcome-sub">今日能耗实时数据</text>
      </view>
      <view class="time-badge">
        <text>{{ currentTime }}</text>
      </view>
    </view>

    <!-- 全局汇总卡 -->
    <view class="summary-card" v-if="overview">
      <view class="summary-item">
        <text class="summary-value">{{ formatNum(overview.total_electricity_kwh) }}</text>
        <text class="summary-unit">kWh</text>
        <text class="summary-label">总用电量</text>
      </view>
      <view class="summary-divider" />
      <view class="summary-item">
        <text class="summary-value">{{ formatNum(overview.total_water_m3) }}</text>
        <text class="summary-unit">m³</text>
        <text class="summary-label">总用水量</text>
      </view>
      <view class="summary-divider" />
      <view class="summary-item">
        <text class="summary-value anomaly" :class="{ has: overview.total_anomalies > 0 }">
          {{ overview.total_anomalies }}
        </text>
        <text class="summary-unit">个</text>
        <text class="summary-label">当前异常</text>
      </view>
    </view>

    <!-- 骨架屏 -->
    <view v-if="loading && !overview" class="summary-card skeleton">
      <view class="skeleton-block" />
    </view>

    <!-- 建筑列表 -->
    <view class="section-title">各建筑实时能耗</view>

    <view v-if="loading && !overview">
      <view v-for="i in 3" :key="i" class="building-card skeleton">
        <view class="skeleton-block tall" />
      </view>
    </view>

    <view
      v-for="b in overview?.buildings"
      :key="b.building_id"
      class="building-card"
      :class="b.status"
    >
      <!-- 建筑名 + 状态 -->
      <view class="building-header">
        <view class="building-title-row">
          <view class="status-dot" :class="b.status" />
          <text class="building-name">{{ b.building_name }}</text>
        </view>
        <view class="building-status-tag" :class="b.status">
          {{ statusText(b.status) }}
        </view>
      </view>

      <!-- 三项能耗数据 -->
      <view class="energy-row">
        <view class="energy-item">
          <text class="energy-icon">⚡</text>
          <view>
            <text class="energy-value">{{ formatNum(b.electricity_kwh) }}</text>
            <text class="energy-unit"> kWh</text>
            <text class="energy-label">电耗</text>
          </view>
        </view>
        <view class="energy-item">
          <text class="energy-icon">💧</text>
          <view>
            <text class="energy-value">{{ formatNum(b.water_m3) }}</text>
            <text class="energy-unit"> m³</text>
            <text class="energy-label">水耗</text>
          </view>
        </view>
        <view class="energy-item">
          <text class="energy-icon">❄️</text>
          <view>
            <text class="energy-value">{{ formatNum(b.hac_energy) }}</text>
            <text class="energy-unit"> kWh</text>
            <text class="energy-label">暖通</text>
          </view>
        </view>
      </view>

      <!-- 异常数 -->
      <view v-if="b.anomaly_count > 0" class="anomaly-hint">
        <text>⚠️ {{ b.anomaly_count }} 个异常待处理</text>
      </view>

      <text class="update-time">更新于 {{ formatTime(b.last_updated) }}</text>
    </view>

    <!-- 底部占位 -->
    <view class="safe-area-bottom" />
    <TabBar :tabs="operatorTabs" current="overview" theme="operator" />
  </view>
</template>

<script setup lang="ts">
import { ref, onMounted, onUnmounted } from 'vue'
import NavBar from '../../../components/NavBar.vue'
import TabBar, { type TabItem } from '../../../components/TabBar.vue'
import { useAuthStore } from '../../../stores/auth'
import { dataApi, type OverviewResponse } from '../../../api/data'

const authStore = useAuthStore()
const overview = ref<OverviewResponse | null>(null)
const loading = ref(false)
const currentTime = ref('')

const operatorTabs: TabItem[] = [
  { name: 'overview',   label: '总览',   icon: '📊', path: '/pages/operator/overview/index' },
  { name: 'alerts',     label: '告警',   icon: '🔔', path: '/pages/operator/alerts/index' },
  { name: 'workorders', label: '工单',   icon: '📋', path: '/pages/operator/workorders/index' },
  { name: 'profile',    label: '我的',   icon: '👤', path: '/pages/operator/profile/index' },
]

async function loadData() {
  loading.value = true
  try {
    overview.value = await dataApi.overview()
  } catch { /* toast already shown by request.ts */ }
  finally { loading.value = false }
}

function updateTime() {
  const now = new Date()
  currentTime.value = `${now.getHours().toString().padStart(2,'0')}:${now.getMinutes().toString().padStart(2,'0')}`
}

function formatNum(n: number): string {
  if (n === undefined || n === null) return '--'
  if (n >= 10000) return (n / 10000).toFixed(1) + '万'
  return n.toFixed(1)
}

function formatTime(iso: string): string {
  const d = new Date(iso)
  const diff = (Date.now() - d.getTime()) / 1000
  if (diff < 60) return '刚刚'
  if (diff < 3600) return `${Math.floor(diff / 60)}分钟前`
  return `${d.getHours()}:${String(d.getMinutes()).padStart(2,'0')}`
}

function statusText(s: string): string {
  return { normal: '正常', warning: '预警', critical: '告警' }[s] ?? s
}

let timer: ReturnType<typeof setInterval>
onMounted(() => {
  updateTime()
  loadData()
  timer = setInterval(() => {
    updateTime()
    loadData()
  }, 60000) // 每分钟刷新
})
onUnmounted(() => clearInterval(timer))
</script>

<style lang="scss" scoped>
.page {
  background: #f0f2f8;
  min-height: 100vh;
}

.welcome-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 32rpx 32rpx 16rpx;
}

.welcome-name {
  display: block;
  font-size: 34rpx;
  font-weight: 700;
  color: #1a1a2e;
}

.welcome-sub {
  font-size: 24rpx;
  color: #999;
  margin-top: 4rpx;
  display: block;
}

.time-badge {
  background: #fff;
  border-radius: 20rpx;
  padding: 10rpx 20rpx;
  box-shadow: 0 2rpx 8rpx rgba(0,0,0,0.08);
  font-size: 24rpx;
  color: #666;
}

.refresh-btn {
  font-size: 40rpx;
  color: rgba(255,255,255,0.8);
}

/* 汇总卡 */
.summary-card {
  margin: 0 32rpx 24rpx;
  background: linear-gradient(135deg, #1a1a2e, #3b6cf4);
  border-radius: 20rpx;
  padding: 32rpx;
  display: flex;
  align-items: center;
  justify-content: space-around;
  box-shadow: 0 8rpx 32rpx rgba(59,108,244,0.3);

  &.skeleton {
    height: 120rpx;
  }
}

.summary-item {
  display: flex;
  flex-direction: column;
  align-items: center;
}

.summary-value {
  font-size: 42rpx;
  font-weight: 700;
  color: #fff;

  &.anomaly.has { color: #ff7875; }
}

.summary-unit {
  font-size: 20rpx;
  color: rgba(255,255,255,0.6);
  margin-top: 2rpx;
}

.summary-label {
  font-size: 22rpx;
  color: rgba(255,255,255,0.7);
  margin-top: 6rpx;
}

.summary-divider {
  width: 1rpx;
  height: 60rpx;
  background: rgba(255,255,255,0.2);
}

/* 建筑卡 */
.section-title {
  padding: 8rpx 32rpx 16rpx;
  font-size: 26rpx;
  font-weight: 600;
  color: #666;
  text-transform: uppercase;
  letter-spacing: 1rpx;
}

.building-card {
  margin: 0 32rpx 20rpx;
  background: #fff;
  border-radius: 20rpx;
  padding: 28rpx;
  box-shadow: 0 2rpx 12rpx rgba(0,0,0,0.06);
  border-left: 6rpx solid #e8ecf0;

  &.warning  { border-left-color: #fa8c16; }
  &.critical { border-left-color: #ff4d4f; }
  &.normal   { border-left-color: #52c41a; }
}

.building-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 20rpx;
}

.building-title-row {
  display: flex;
  align-items: center;
  gap: 12rpx;
}

.status-dot {
  width: 16rpx;
  height: 16rpx;
  border-radius: 50%;

  &.normal   { background: #52c41a; }
  &.warning  { background: #fa8c16; }
  &.critical { background: #ff4d4f; box-shadow: 0 0 8rpx rgba(255,77,79,0.6); }
}

.building-name {
  font-size: 32rpx;
  font-weight: 700;
  color: #1a1a2e;
}

.building-status-tag {
  font-size: 22rpx;
  padding: 6rpx 16rpx;
  border-radius: 16rpx;

  &.normal   { background: #f6ffed; color: #52c41a; }
  &.warning  { background: #fff7e6; color: #fa8c16; }
  &.critical { background: #fff2f0; color: #ff4d4f; }
}

.energy-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 16rpx;
}

.energy-item {
  display: flex;
  align-items: center;
  gap: 12rpx;
}

.energy-icon {
  font-size: 36rpx;
}

.energy-value {
  font-size: 32rpx;
  font-weight: 700;
  color: #1a1a2e;
}

.energy-unit {
  font-size: 22rpx;
  color: #999;
}

.energy-label {
  display: block;
  font-size: 22rpx;
  color: #aaa;
  margin-top: 2rpx;
}

.anomaly-hint {
  background: #fff7e6;
  border-radius: 8rpx;
  padding: 10rpx 16rpx;
  margin-bottom: 12rpx;
  font-size: 24rpx;
  color: #fa8c16;
}

.update-time {
  font-size: 22rpx;
  color: #bbb;
}

/* 骨架屏 */
.skeleton-block {
  background: linear-gradient(90deg, rgba(255,255,255,0.1), rgba(255,255,255,0.3), rgba(255,255,255,0.1));
  border-radius: 8rpx;
  height: 60rpx;
  animation: shimmer 1.5s infinite;

  &.tall { height: 180rpx; background: linear-gradient(90deg, #f0f0f0, #e0e0e0, #f0f0f0); }
}

@keyframes shimmer {
  0%   { background-position: -200% 0; }
  100% { background-position: 200% 0; }
}
</style>
