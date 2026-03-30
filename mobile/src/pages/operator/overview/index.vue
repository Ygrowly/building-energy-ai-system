<template>
  <view class="page">
    <NavBar title="能耗总览" bg-color="#1a1a2e">
      <template #right>
        <text class="refresh-btn" @click="loadData">↻</text>
      </template>
    </NavBar>

    <!-- 欢迎行 -->
    <view class="welcome-row">
      <view>
        <text class="welcome-name">{{ authStore.user?.username }}</text>
        <text class="welcome-sub">{{ overview?.data_date || '加载中...' }} · 能耗数据</text>
      </view>
      <view v-if="overview?.weather?.temperature != null" class="weather-badge">
        <text>🌡 {{ overview.weather.temperature }}°C · {{ overview.weather.humidity }}%</text>
      </view>
    </view>

    <!-- 全局 KPI 卡片 -->
    <view v-if="overview" class="kpi-card">
      <view class="kpi-item">
        <text class="kpi-value">{{ formatNum(overview.kpis.total_electricity_kwh) }}</text>
        <text class="kpi-unit">kWh</text>
        <text class="kpi-label">总用电</text>
        <text class="kpi-change" :class="changeClass(overview.kpis_change.total_electricity_pct)">
          {{ formatPct(overview.kpis_change.total_electricity_pct) }}
        </text>
      </view>
      <view class="kpi-sep" />
      <view class="kpi-item">
        <text class="kpi-value">{{ formatNum(overview.kpis.total_water_m3) }}</text>
        <text class="kpi-unit">m³</text>
        <text class="kpi-label">总用水</text>
        <text class="kpi-change" :class="changeClass(overview.kpis_change.total_water_pct)">
          {{ formatPct(overview.kpis_change.total_water_pct) }}
        </text>
      </view>
      <view class="kpi-sep" />
      <view class="kpi-item">
        <text class="kpi-value anomaly" :class="{ warn: overview.kpis.anomaly_count > 0 }">
          {{ overview.kpis.anomaly_count }}
        </text>
        <text class="kpi-unit">个</text>
        <text class="kpi-label">异常</text>
        <text v-if="overview.kpis.prediction_warning_count" class="kpi-pred">
          +{{ overview.kpis.prediction_warning_count }} 预警
        </text>
      </view>
    </view>

    <!-- 骨架屏 -->
    <view v-if="loading && !overview" class="kpi-card skeleton">
      <view class="sk-block" />
    </view>

    <!-- 建筑列表 -->
    <view class="section-title">各建筑详情</view>

    <view
      v-for="b in overview?.buildings"
      :key="b.building_type"
      class="building-card"
      :class="b.anomaly_status === 'Anomaly' ? 'anomaly' : 'normal'"
    >
      <view class="building-header">
        <view class="building-title-row">
          <text class="building-icon">{{ b.icon }}</text>
          <text class="building-name">{{ b.display_name }}</text>
        </view>
        <view class="building-badges">
          <view class="anomaly-badge" :class="b.anomaly_status">
            {{ b.anomaly_status === 'Anomaly' ? '异常' : '正常' }}
          </view>
          <view v-if="b.prediction_status !== 'normal'" class="pred-badge" :class="b.prediction_status">
            预警{{ b.prediction_warning_count }}
          </view>
        </view>
      </view>

      <!-- 三项能耗 -->
      <view class="energy-row">
        <view class="energy-item">
          <text class="energy-val">{{ formatNum(b.total_electricity_kwh) }}</text>
          <text class="energy-unit"> kWh</text>
          <text class="energy-label">电耗</text>
          <text class="energy-change" :class="changeClass(b.electricity_change_pct)">
            {{ formatPct(b.electricity_change_pct) }}
          </text>
        </view>
        <view class="energy-item">
          <text class="energy-val">{{ formatNum(b.total_water_m3) }}</text>
          <text class="energy-unit"> m³</text>
          <text class="energy-label">水耗</text>
          <text class="energy-change" :class="changeClass(b.water_change_pct)">
            {{ formatPct(b.water_change_pct) }}
          </text>
        </view>
        <view class="energy-item">
          <text class="energy-val">{{ formatNum(b.total_hac_energy_kwh) }}</text>
          <text class="energy-unit"> kWh</text>
          <text class="energy-label">暖通</text>
          <text class="energy-change" :class="changeClass(b.hac_change_pct)">
            {{ formatPct(b.hac_change_pct) }}
          </text>
        </view>
      </view>

      <!-- 能耗强度 -->
      <view v-if="b.energy_intensity_kwh_per_sqm" class="intensity-row">
        <text class="intensity-label">能耗强度</text>
        <text class="intensity-value">{{ b.energy_intensity_kwh_per_sqm }} kWh/m²</text>
      </view>
    </view>

    <view class="safe-area-bottom" />
    <TabBar :tabs="OPERATOR_TABS" current="overview" theme="operator" />
  </view>
</template>

<script setup lang="ts">
import { ref, onMounted, onUnmounted } from 'vue'
import NavBar from '../../../components/NavBar.vue'
import TabBar from '../../../components/TabBar.vue'
import { useAuthStore } from '../../../stores/auth'
import { useRouteGuard } from '../../../utils/route-guard'
import { OPERATOR_TABS } from '../../../constants/tabs'
import { OPERATOR_ROLES } from '../../../constants/roles'
import { dataApi, type OverviewResponse } from '../../../api/data'
import { formatNum, formatPct } from '../../../utils/format'

useRouteGuard(OPERATOR_ROLES)

const authStore = useAuthStore()
const overview = ref<OverviewResponse | null>(null)
const loading = ref(false)

async function loadData() {
  loading.value = true
  try { overview.value = await dataApi.overview() }
  catch { /* toast handled by request.ts */ }
  finally { loading.value = false }
}

function changeClass(pct: number | null | undefined) {
  if (pct === null || pct === undefined) return ''
  return pct > 0 ? 'up' : pct < 0 ? 'down' : ''
}

let timer: ReturnType<typeof setInterval>
onMounted(() => { loadData(); timer = setInterval(loadData, 60000) })
onUnmounted(() => clearInterval(timer))
</script>

<style lang="scss" scoped>
.page { background: #f0f2f8; min-height: 100vh; }

.welcome-row {
  display: flex; align-items: center; justify-content: space-between;
  padding: 32rpx 32rpx 16rpx;
}
.welcome-name { display: block; font-size: 34rpx; font-weight: 700; color: #1a1a2e; }
.welcome-sub  { font-size: 24rpx; color: #999; margin-top: 4rpx; display: block; }
.weather-badge {
  background: #fff; border-radius: 20rpx; padding: 10rpx 20rpx;
  box-shadow: 0 2rpx 8rpx rgba(0,0,0,0.08); font-size: 22rpx; color: #666;
}
.refresh-btn { font-size: 40rpx; color: rgba(255,255,255,0.8); }

/* KPI 卡片 */
.kpi-card {
  margin: 0 32rpx 24rpx; background: linear-gradient(135deg, #1a1a2e, #3b6cf4);
  border-radius: 20rpx; padding: 32rpx; display: flex; align-items: center;
  justify-content: space-around; box-shadow: 0 8rpx 32rpx rgba(59,108,244,0.3);
  &.skeleton { height: 140rpx; }
}
.kpi-item { display: flex; flex-direction: column; align-items: center; }
.kpi-value { font-size: 42rpx; font-weight: 700; color: #fff; &.anomaly.warn { color: #ff7875; } }
.kpi-unit  { font-size: 20rpx; color: rgba(255,255,255,0.6); }
.kpi-label { font-size: 22rpx; color: rgba(255,255,255,0.7); margin-top: 6rpx; }
.kpi-change { font-size: 20rpx; margin-top: 4rpx; &.up { color: #ffa39e; } &.down { color: #b7eb8f; } }
.kpi-pred { font-size: 18rpx; color: #ffd591; margin-top: 2rpx; }
.kpi-sep  { width: 1rpx; height: 60rpx; background: rgba(255,255,255,0.2); }

/* 建筑卡片 */
.section-title {
  padding: 8rpx 32rpx 16rpx; font-size: 26rpx; font-weight: 600; color: #666;
}
.building-card {
  margin: 0 32rpx 20rpx; background: #fff; border-radius: 20rpx; padding: 28rpx;
  box-shadow: 0 2rpx 12rpx rgba(0,0,0,0.06); border-left: 6rpx solid #52c41a;
  &.anomaly { border-left-color: #ff4d4f; }
}
.building-header { display: flex; align-items: center; justify-content: space-between; margin-bottom: 20rpx; }
.building-title-row { display: flex; align-items: center; gap: 10rpx; }
.building-icon { font-size: 36rpx; }
.building-name { font-size: 32rpx; font-weight: 700; color: #1a1a2e; }
.building-badges { display: flex; gap: 8rpx; }
.anomaly-badge {
  font-size: 22rpx; padding: 4rpx 14rpx; border-radius: 16rpx;
  &.Normal  { background: #f6ffed; color: #52c41a; }
  &.Anomaly { background: #fff2f0; color: #ff4d4f; }
}
.pred-badge {
  font-size: 22rpx; padding: 4rpx 14rpx; border-radius: 16rpx;
  &.warning  { background: #fff7e6; color: #fa8c16; }
  &.critical { background: #fff2f0; color: #ff4d4f; }
}

.energy-row { display: flex; justify-content: space-between; margin-bottom: 16rpx; }
.energy-item { display: flex; flex-direction: column; align-items: center; flex: 1; }
.energy-val  { font-size: 30rpx; font-weight: 700; color: #1a1a2e; }
.energy-unit { font-size: 20rpx; color: #999; }
.energy-label { font-size: 22rpx; color: #aaa; margin-top: 4rpx; }
.energy-change { font-size: 20rpx; margin-top: 2rpx; color: #aaa; &.up { color: #ff4d4f; } &.down { color: #52c41a; } }

.intensity-row {
  display: flex; justify-content: space-between; padding-top: 12rpx;
  border-top: 1rpx solid #f0f0f0;
}
.intensity-label { font-size: 22rpx; color: #aaa; }
.intensity-value { font-size: 22rpx; color: #666; font-weight: 600; }

.safe-area-bottom { height: calc(env(safe-area-inset-bottom, 0px) + 140rpx); }
.sk-block { height: 80rpx; background: rgba(255,255,255,0.2); border-radius: 8rpx; }
</style>
