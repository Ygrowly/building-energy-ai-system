<template>
  <view class="page">
    <NavBar title="能耗总览" bg-color="#1a1a2e">
      <template #right>
        <view class="refresh-btn" :class="{ spinning: loading }" @click="loadData">
          <image class="nav-icon" src="/static/icons/refresh.svg" mode="aspectFit" />
        </view>
      </template>
    </NavBar>

    <!-- 顶部：头像 + 天气 -->
    <view class="header">
      <view class="header-left">
        <view class="avatar-circle">
          <text class="avatar-text">{{ (authStore.user?.username || '?')[0] }}</text>
        </view>
        <view class="header-info">
          <text class="header-greeting">{{ greeting }}</text>
          <text class="header-name">{{ authStore.user?.username }}</text>
        </view>
      </view>
      <view v-if="overview && overview.weather && overview.weather.temperature != null" class="weather-chip">
        <image class="chip-icon" src="/static/icons/thermometer.svg" mode="aspectFit" />
        <text class="chip-temp">{{ overview.weather.temperature }}°C</text>
        <text class="chip-sub">{{ overview.weather.humidity }}%</text>
      </view>
    </view>

    <!-- 深色 Banner -->
    <view v-if="overview" class="banner-card">
      <view class="banner-bg">
        <view class="banner-circle c1" />
        <view class="banner-circle c2" />
      </view>
      <view class="banner-left">
        <view class="banner-title-row">
          <image class="banner-leaf" src="/static/icons/leaf.svg" mode="aspectFit" />
          <text class="banner-label">CAMPUS ENERGY</text>
        </view>
        <text class="banner-title">能耗监控面板</text>
        <view class="banner-kpi">
          <text class="banner-kpi-label">{{ currentTab === 'all' ? '总碳排放' : '碳排放' }}</text>
          <text class="banner-kpi-val">{{ formatNum(bannerCarbon) }}kg</text>
        </view>
      </view>
      <view class="banner-chart">
        <view
          v-for="(b, i) in overview.buildings.slice(0, 5)"
          :key="'bb'+i"
          class="banner-bar-col"
          @click="currentTab = b.building_type"
        >
          <view
            class="banner-bar"
            :style="{ height: getBarHeight(b.total_electricity_kwh, 80) + 'rpx' }"
            :class="isBannerBarActive(b.building_type) ? 'bar-highlight' : 'bar-dim'"
          />
          <text class="banner-bar-lbl" :class="isBannerBarActive(b.building_type) ? 'lbl-active' : ''">{{ (b.display_name || '').slice(0, 1) }}</text>
        </view>
      </view>
    </view>

    <!-- ====== 筛选 Tab 栏 ====== -->
    <view v-if="overview" class="filter-bar">
      <scroll-view scroll-x class="filter-scroll" :show-scrollbar="false">
        <view class="filter-inner">
          <view
            class="filter-tab"
            :class="currentTab === 'all' ? 'tab-active' : ''"
            @click="currentTab = 'all'"
          >
            <image class="filter-icon" src="/static/icons/tab-overview.svg" mode="aspectFit" />
            <text class="filter-text">总览</text>
          </view>
          <view
            v-for="b in overview.buildings"
            :key="'ft-'+b.building_type"
            class="filter-tab"
            :class="currentTab === b.building_type ? 'tab-active' : ''"
            @click="currentTab = b.building_type"
          >
            <image class="filter-icon" :src="getBuildingIcon(b.building_type)" mode="aspectFit" />
            <text class="filter-text">{{ (b.display_name || '').replace('楼', '') }}</text>
          </view>
        </view>
      </scroll-view>
    </view>

    <!-- ==================== 总览视图 ==================== -->
    <view v-if="overview && currentTab === 'all'">
      <!-- KPI 双卡片 -->
      <view class="kpi-row">
        <view class="kpi-card">
          <view class="kpi-card-header">
            <text class="kpi-card-title">总用电</text>
            <image class="kpi-arrow" src="/static/icons/arrow-right.svg" mode="aspectFit" />
          </view>
          <view class="kpi-main">
            <text class="kpi-value">{{ formatNum(overview.kpis.total_electricity_kwh) }}</text>
            <text class="kpi-unit">kWh</text>
          </view>
          <view class="kpi-bars">
            <view
              v-for="(b, i) in overview.buildings.slice(0, 6)"
              :key="'ke'+i"
              class="kpi-bar-item"
            >
              <view
                class="kpi-bar"
                :style="{ height: getBarHeight(b.total_electricity_kwh, 56) + 'rpx' }"
                :class="i % 2 === 0 ? 'bar-solid' : 'bar-light'"
              />
            </view>
          </view>
          <view class="kpi-change" :class="changeClass(overview.kpis_change.total_electricity_pct)">
            <text>环比 {{ formatPct(overview.kpis_change.total_electricity_pct) }}</text>
          </view>
        </view>

        <view class="kpi-card">
          <view class="kpi-card-header">
            <text class="kpi-card-title">总用水</text>
            <image class="kpi-arrow" src="/static/icons/arrow-right.svg" mode="aspectFit" />
          </view>
          <view class="kpi-main">
            <text class="kpi-value">{{ formatNum(overview.kpis.total_water_m3) }}</text>
            <text class="kpi-unit">m³</text>
          </view>
          <view class="ring-wrap">
            <view class="ring-outer" :style="{ background: getRingGradient(waterUsagePercent) }">
              <view class="ring-inner">
                <text class="ring-pct">{{ waterUsagePercent }}%</text>
                <text class="ring-sub">用量</text>
              </view>
            </view>
          </view>
          <view class="kpi-change" :class="changeClass(overview.kpis_change.total_water_pct)">
            <text>环比 {{ formatPct(overview.kpis_change.total_water_pct) }}</text>
          </view>
        </view>
      </view>

      <!-- 建筑能耗对比大卡片 -->
      <view class="chart-card">
        <view class="chart-header">
          <view>
            <text class="chart-title">建筑能耗</text>
            <text class="chart-sub">{{ overview.data_date || '最近更新' }}</text>
          </view>
          <image class="chart-arrow" src="/static/icons/arrow-right.svg" mode="aspectFit" />
        </view>
        <view class="chart-main-row">
          <text class="chart-big-num">{{ formatNum(overview.kpis.total_electricity_kwh) }}</text>
          <text class="chart-big-unit">kWh</text>
        </view>
        <view class="chart-bars">
          <view
            v-for="(b, i) in overview.buildings"
            :key="'cb'+i"
            class="chart-bar-group"
            @click="currentTab = b.building_type"
          >
            <view class="chart-bar-wrapper">
              <view
                class="chart-bar"
                :style="{ height: getBarHeight(b.total_electricity_kwh, 150) + 'rpx' }"
                :class="getChartBarClass(i)"
              />
            </view>
            <text class="chart-bar-label">{{ (b.display_name || '').slice(0, 2) }}</text>
          </view>
        </view>
      </view>

      <!-- 暖通 / 异常 -->
      <view class="stats-strip">
        <view class="stat-chip">
          <image class="stat-icon" src="/static/icons/flame.svg" mode="aspectFit" />
          <view class="stat-info">
            <text class="stat-val">{{ formatNum(overview.kpis.total_hac_energy_kwh) }} kWh</text>
            <text class="stat-label">暖通总能耗</text>
          </view>
        </view>
        <view class="stat-chip" :class="overview.kpis.anomaly_count > 0 ? 'chip-warn' : ''">
          <image class="stat-icon" src="/static/icons/alert-triangle.svg" mode="aspectFit" />
          <view class="stat-info">
            <text class="stat-val">{{ overview.kpis.anomaly_count }} 个</text>
            <text class="stat-label">异常</text>
          </view>
        </view>
      </view>

      <!-- 建筑快捷列表 -->
      <view class="section-header">
        <view class="section-dot" />
        <text class="section-title">各建筑概览</text>
      </view>
      <view
        v-for="b in overview.buildings"
        :key="'row-'+b.building_type"
        class="building-row"
        @click="currentTab = b.building_type"
      >
        <view class="brow-left">
          <view class="brow-icon-box" :class="getBuildingBg(b.building_type)">
            <image class="brow-icon" :src="getBuildingIcon(b.building_type)" mode="aspectFit" />
          </view>
          <view class="brow-info">
            <text class="brow-name">{{ b.display_name }}</text>
            <text class="brow-sub">{{ formatNum(b.total_electricity_kwh) }} kWh · {{ formatNum(b.total_water_m3) }} m³</text>
          </view>
        </view>
        <view class="brow-right">
          <view class="brow-badge" :class="b.anomaly_status === 'Anomaly' ? 'badge-red' : 'badge-green'">
            <view class="brow-dot" />
            <text>{{ b.anomaly_status === 'Anomaly' ? '异常' : '正常' }}</text>
          </view>
          <image class="brow-arrow" src="/static/icons/arrow-right.svg" mode="aspectFit" />
        </view>
      </view>
    </view>

    <!-- ==================== 建筑详情视图 ==================== -->
    <view v-if="overview && currentTab !== 'all' && activeBuilding">
      <!-- 建筑头部 -->
      <view class="detail-header">
        <view class="detail-title-row">
          <view class="detail-icon-box" :class="getBuildingBg(activeBuilding.building_type)">
            <image class="detail-icon" :src="getBuildingIcon(activeBuilding.building_type)" mode="aspectFit" />
          </view>
          <view>
            <text class="detail-name">{{ activeBuilding.display_name }}</text>
            <text class="detail-sub">面积 {{ activeBuilding.sqm }}m² · {{ overview.data_date }}</text>
          </view>
        </view>
        <view class="detail-badges">
          <view class="detail-badge" :class="activeBuilding.anomaly_status === 'Anomaly' ? 'dbadge-red' : 'dbadge-green'">
            <view class="detail-dot" />
            <text>{{ activeBuilding.anomaly_status === 'Anomaly' ? '异常' : '正常' }}</text>
          </view>
          <view v-if="activeBuilding.prediction_status !== 'normal'" class="detail-badge dbadge-orange">
            <text>预警 {{ activeBuilding.prediction_warning_count }}</text>
          </view>
        </view>
      </view>

      <!-- 三项 KPI 卡片 -->
      <view class="detail-kpi-row">
        <view class="detail-kpi">
          <view class="dkpi-head">
            <image class="dkpi-icon" src="/static/icons/lightning.svg" mode="aspectFit" />
            <text class="dkpi-label">电耗</text>
          </view>
          <text class="dkpi-value">{{ formatNum(activeBuilding.total_electricity_kwh) }}</text>
          <text class="dkpi-unit">kWh</text>
          <view class="dkpi-bar-track">
            <view class="dkpi-bar-fill fill-green" :style="{ width: getProgressWidth(activeBuilding.total_electricity_kwh, 'electricity') + '%' }" />
          </view>
          <text class="dkpi-change" :class="changeClass(activeBuilding.electricity_change_pct)">
            {{ formatPct(activeBuilding.electricity_change_pct) }}
          </text>
        </view>
        <view class="detail-kpi">
          <view class="dkpi-head">
            <image class="dkpi-icon" src="/static/icons/droplet.svg" mode="aspectFit" />
            <text class="dkpi-label">水耗</text>
          </view>
          <text class="dkpi-value">{{ formatNum(activeBuilding.total_water_m3) }}</text>
          <text class="dkpi-unit">m³</text>
          <view class="dkpi-bar-track">
            <view class="dkpi-bar-fill fill-blue" :style="{ width: getProgressWidth(activeBuilding.total_water_m3, 'water') + '%' }" />
          </view>
          <text class="dkpi-change" :class="changeClass(activeBuilding.water_change_pct)">
            {{ formatPct(activeBuilding.water_change_pct) }}
          </text>
        </view>
        <view class="detail-kpi">
          <view class="dkpi-head">
            <image class="dkpi-icon" src="/static/icons/flame.svg" mode="aspectFit" />
            <text class="dkpi-label">暖通</text>
          </view>
          <text class="dkpi-value">{{ formatNum(activeBuilding.total_hac_energy_kwh) }}</text>
          <text class="dkpi-unit">kWh</text>
          <view class="dkpi-bar-track">
            <view class="dkpi-bar-fill fill-orange" :style="{ width: getProgressWidth(activeBuilding.total_hac_energy_kwh, 'hac') + '%' }" />
          </view>
          <text class="dkpi-change" :class="changeClass(activeBuilding.hac_change_pct)">
            {{ formatPct(activeBuilding.hac_change_pct) }}
          </text>
        </view>
      </view>

      <!-- 能耗对比柱状图 -->
      <view class="detail-compare-card">
        <text class="dc-title">能耗对比</text>
        <text class="dc-sub">该建筑在所有建筑中的电耗排名</text>
        <view class="dc-bars">
          <view
            v-for="(b, i) in overview.buildings"
            :key="'dc'+i"
            class="dc-bar-col"
          >
            <view class="dc-bar-wrap">
              <view
                class="dc-bar"
                :style="{ height: getBarHeight(b.total_electricity_kwh, 120) + 'rpx' }"
                :class="b.building_type === activeBuilding.building_type ? 'dc-bar-active' : 'dc-bar-dim'"
              />
            </view>
            <text
              class="dc-bar-label"
              :class="b.building_type === activeBuilding.building_type ? 'dc-label-active' : ''"
            >{{ (b.display_name || '').slice(0, 2) }}</text>
          </view>
        </view>
      </view>

      <!-- 能耗强度 + 环境温度 -->
      <view class="detail-info-row">
        <view class="info-card">
          <text class="info-label">能耗强度</text>
          <view class="info-main">
            <text class="info-value">{{ activeBuilding.energy_intensity_kwh_per_sqm || '--' }}</text>
            <text class="info-unit">kWh/m²</text>
          </view>
        </view>
        <view class="info-card">
          <text class="info-label">环境温度</text>
          <view class="info-main">
            <text class="info-value">{{ activeBuilding.avg_ambient_temp != null ? activeBuilding.avg_ambient_temp : '--' }}</text>
            <text class="info-unit">°C</text>
          </view>
        </view>
      </view>

      <!-- 最新水耗 -->
      <view class="detail-water-card">
        <view class="dw-row">
          <view class="dw-left">
            <image class="dw-icon" src="/static/icons/droplet.svg" mode="aspectFit" />
            <text class="dw-label">最新水耗</text>
          </view>
          <view class="dw-right">
            <text class="dw-value">{{ formatNum(activeBuilding.latest_water_m3) }}</text>
            <text class="dw-unit">m³</text>
          </view>
        </view>
        <view class="dw-track">
          <view class="dw-fill" :style="{ width: getProgressWidth(activeBuilding.latest_water_m3, 'water') + '%' }" />
        </view>
      </view>
    </view>

    <!-- 骨架屏 -->
    <view v-if="loading && !overview" class="skeleton-area">
      <view class="sk-banner" />
      <view class="sk-row">
        <view class="sk-half" />
        <view class="sk-half" />
      </view>
      <view class="sk-card" />
    </view>

    <view class="safe-bottom" />
    <TabBar :tabs="OPERATOR_TABS" current="overview" theme="operator" />
  </view>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted } from 'vue'
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
const currentTab = ref('all')

const greeting = computed(() => {
  const h = new Date().getHours()
  if (h < 6) return '夜深了'
  if (h < 12) return '上午好'
  if (h < 14) return '中午好'
  if (h < 18) return '下午好'
  return '晚上好'
})

const maxBuildingIdx = computed(() => {
  const bs = overview.value?.buildings
  if (!bs || !bs.length) return 0
  let max = 0
  let idx = 0
  bs.slice(0, 5).forEach((b, i) => {
    if (b.total_electricity_kwh > max) { max = b.total_electricity_kwh; idx = i }
  })
  return idx
})

const waterUsagePercent = computed(() => {
  const pct = overview.value?.kpis_change?.total_water_pct
  if (pct == null) return 50
  return Math.min(99, Math.max(1, Math.round(50 + pct)))
})

/** Banner 碳排放：总览显示总量，选中建筑按电耗占比计算 */
const bannerCarbon = computed(() => {
  if (!overview.value) return 0
  const total = overview.value.kpis.total_carbon_kg
  if (currentTab.value === 'all') return total
  const b = overview.value.buildings.find(b => b.building_type === currentTab.value)
  if (!b) return total
  const totalE = overview.value.kpis.total_electricity_kwh || 1
  return Math.round((b.total_electricity_kwh / totalE) * total * 10) / 10
})

const activeBuilding = computed(() => {
  if (currentTab.value === 'all' || !overview.value) return null
  return overview.value.buildings.find(b => b.building_type === currentTab.value) || null
})

async function loadData() {
  loading.value = true
  try { overview.value = await dataApi.overview() }
  catch { /* toast handled by request.ts */ }
  finally { loading.value = false }
}

function changeClass(pct: number | null | undefined) {
  if (pct == null) return ''
  return pct > 0 ? 'up' : pct < 0 ? 'down' : ''
}

function getBarHeight(val: number, maxH: number): number {
  const bs = overview.value?.buildings
  if (!bs || !bs.length) return 16
  const max = Math.max(...bs.map(b => b.total_electricity_kwh), 1)
  return Math.max(8, Math.round((val / max) * maxH))
}

function getProgressWidth(val: number, type: string): number {
  const bs = overview.value?.buildings
  if (!bs || !bs.length) return 0
  const getter = (b: typeof bs[0]) => {
    if (type === 'electricity') return b.total_electricity_kwh
    if (type === 'water') return b.total_water_m3
    return b.total_hac_energy_kwh
  }
  const max = Math.max(...bs.map(getter), 1)
  return Math.min(100, Math.round((val / max) * 100))
}

function getRingGradient(percent: number): string {
  const deg = Math.round((percent / 100) * 360)
  return 'conic-gradient(#22c55e 0deg, #4ade80 ' + deg + 'deg, #e8eaf0 ' + deg + 'deg, #e8eaf0 360deg)'
}

/** Banner 柱状图是否高亮：总览时全亮，选中建筑时只亮对应的 */
function isBannerBarActive(buildingType: string): boolean {
  if (currentTab.value === 'all') return true
  return currentTab.value === buildingType
}

function getChartBarClass(index: number): string {
  if (index === maxBuildingIdx.value) return 'bar-active'
  return index % 2 === 0 ? 'bar-normal' : 'bar-normal-light'
}

function getBuildingIcon(type: string): string {
  const map: Record<string, string> = {
    teaching: '/static/icons/building-school.svg',
    office: '/static/icons/building-office.svg',
    public: '/static/icons/building-public.svg',
    dormitory: '/static/icons/building-dorm.svg',
    library: '/static/icons/building-library.svg',
  }
  return map[type] || '/static/icons/building-default.svg'
}

function getBuildingBg(type: string): string {
  const map: Record<string, string> = {
    teaching: 'bg-blue', office: 'bg-purple', public: 'bg-teal',
    dormitory: 'bg-orange', library: 'bg-indigo',
  }
  return map[type] || 'bg-gray'
}

let timer: ReturnType<typeof setInterval>
onMounted(() => { loadData(); timer = setInterval(loadData, 60000) })
onUnmounted(() => clearInterval(timer))
</script>

<style lang="scss" scoped>
.page { background: #f5f7fa; min-height: 100vh; padding-bottom: 20rpx; }

/* Header */
.header {
  display: flex; align-items: center; justify-content: space-between;
  padding: 24rpx 32rpx 16rpx;
}
.header-left { display: flex; align-items: center; gap: 16rpx; }
.avatar-circle {
  width: 64rpx; height: 64rpx; border-radius: 50%;
  background: linear-gradient(135deg, #22c55e, #16a34a);
  display: flex; align-items: center; justify-content: center;
}
.avatar-text { font-size: 28rpx; font-weight: 700; color: #fff; }
.header-greeting { display: block; font-size: 22rpx; color: #94a3b8; }
.header-name { display: block; font-size: 32rpx; font-weight: 700; color: #1e293b; margin-top: 2rpx; }

.weather-chip {
  display: flex; align-items: center; gap: 8rpx;
  background: #fff; border-radius: 40rpx; padding: 14rpx 24rpx;
  box-shadow: 0 2rpx 16rpx rgba(0,0,0,0.05);
}
.chip-icon { width: 28rpx; height: 28rpx; }
.chip-temp { font-size: 28rpx; font-weight: 600; color: #1e293b; }
.chip-sub { font-size: 22rpx; color: #94a3b8; }

.refresh-btn {
  width: 48rpx; height: 48rpx;
  display: flex; align-items: center; justify-content: center;
}
.refresh-btn.spinning { animation: spin 1s linear infinite; }
.nav-icon { width: 38rpx; height: 38rpx; }
@keyframes spin { from { transform: rotate(0deg); } to { transform: rotate(360deg); } }

/* Banner */
.banner-card {
  margin: 8rpx 32rpx 20rpx; background: #1a1a2e;
  border-radius: 24rpx; padding: 32rpx;
  position: relative; overflow: hidden;
  display: flex; justify-content: space-between; align-items: flex-end;
}
.banner-bg { position: absolute; top: 0; left: 0; right: 0; bottom: 0; overflow: hidden; }
.banner-circle {
  position: absolute; border-radius: 50%;
}
.banner-circle.c1 { width: 240rpx; height: 240rpx; background: rgba(34,197,94,0.12); top: -80rpx; right: -40rpx; }
.banner-circle.c2 { width: 160rpx; height: 160rpx; background: rgba(59,130,246,0.08); bottom: -60rpx; left: 20%; }
.banner-left { position: relative; z-index: 1; flex: 1; }
.banner-title-row { display: flex; align-items: center; gap: 10rpx; margin-bottom: 8rpx; }
.banner-leaf { width: 28rpx; height: 28rpx; }
.banner-label { font-size: 18rpx; color: rgba(255,255,255,0.4); letter-spacing: 2rpx; font-weight: 500; }
.banner-title { font-size: 32rpx; font-weight: 700; color: #fff; margin-bottom: 16rpx; }
.banner-kpi { display: flex; align-items: baseline; gap: 8rpx; }
.banner-kpi-label { font-size: 22rpx; color: rgba(255,255,255,0.5); }
.banner-kpi-val { font-size: 28rpx; font-weight: 600; color: #4ade80; }

.banner-chart {
  display: flex; align-items: flex-end; gap: 10rpx;
  position: relative; z-index: 1; height: 90rpx; padding-bottom: 24rpx;
}
.banner-bar-col { display: flex; flex-direction: column; align-items: center; gap: 6rpx; }
.banner-bar {
  width: 18rpx; border-radius: 6rpx 6rpx 0 0; min-height: 8rpx;
  transition: height 0.6s ease;
}
.banner-bar.bar-highlight { background: #4ade80; transition: background 0.3s ease; }
.banner-bar.bar-dim { background: rgba(255,255,255,0.12); transition: background 0.3s ease; }
.banner-bar-lbl { font-size: 16rpx; color: rgba(255,255,255,0.35); transition: color 0.3s ease; }
.banner-bar-lbl.lbl-active { color: rgba(255,255,255,0.85); font-weight: 600; }

/* 筛选 Tab */
.filter-bar {
  margin: 0 32rpx 24rpx; background: #fff;
  border-radius: 20rpx; padding: 8rpx;
  box-shadow: 0 2rpx 16rpx rgba(0,0,0,0.04);
}
.filter-scroll { white-space: nowrap; }
.filter-inner { display: flex; gap: 0; }
.filter-tab {
  display: flex; flex-direction: column; align-items: center; gap: 6rpx;
  padding: 16rpx 24rpx; border-radius: 16rpx;
  flex-shrink: 0; min-width: 100rpx;
  transition: all 0.25s ease;
}
.filter-tab.tab-active { background: #22c55e; }
.filter-tab.tab-active .filter-text { color: #fff; font-weight: 600; }
.filter-tab.tab-active .filter-icon { opacity: 1; }
.filter-icon { width: 36rpx; height: 36rpx; opacity: 0.5; }
.filter-text { font-size: 22rpx; color: #94a3b8; white-space: nowrap; }

/* KPI 双卡片 */
.kpi-row { display: flex; gap: 20rpx; padding: 0 32rpx; margin-bottom: 24rpx; }
.kpi-card {
  flex: 1; background: #fff; border-radius: 20rpx;
  padding: 24rpx; box-shadow: 0 4rpx 24rpx rgba(0,0,0,0.04);
}
.kpi-card-header { display: flex; align-items: center; justify-content: space-between; margin-bottom: 14rpx; }
.kpi-card-title { font-size: 24rpx; color: #94a3b8; font-weight: 500; }
.kpi-arrow { width: 24rpx; height: 24rpx; opacity: 0.35; }
.kpi-main { display: flex; align-items: baseline; gap: 6rpx; margin-bottom: 16rpx; }
.kpi-value { font-size: 48rpx; font-weight: 700; color: #1e293b; line-height: 1; }
.kpi-unit { font-size: 22rpx; color: #94a3b8; }

.kpi-bars { display: flex; align-items: flex-end; gap: 8rpx; height: 60rpx; margin-bottom: 14rpx; }
.kpi-bar-item { flex: 1; display: flex; align-items: flex-end; }
.kpi-bar {
  width: 100%; border-radius: 4rpx 4rpx 0 0; min-height: 6rpx; transition: height 0.6s ease;
}
.kpi-bar.bar-solid { background: #22c55e; }
.kpi-bar.bar-light { background: #bbf7d0; }

.ring-wrap { display: flex; justify-content: center; margin-bottom: 14rpx; }
.ring-outer {
  width: 110rpx; height: 110rpx; border-radius: 50%;
  display: flex; align-items: center; justify-content: center;
}
.ring-inner {
  width: 76rpx; height: 76rpx; border-radius: 50%;
  background: #fff; display: flex; flex-direction: column;
  align-items: center; justify-content: center;
}
.ring-pct { font-size: 22rpx; font-weight: 700; color: #22c55e; line-height: 1.2; }
.ring-sub { font-size: 16rpx; color: #94a3b8; }
.kpi-change { font-size: 20rpx; color: #94a3b8; text-align: center; }
.kpi-change.up { color: #ef4444; }
.kpi-change.down { color: #22c55e; }

/* 大卡片柱状图 */
.chart-card {
  margin: 0 32rpx 24rpx; background: #fff;
  border-radius: 24rpx; padding: 28rpx;
  box-shadow: 0 4rpx 24rpx rgba(0,0,0,0.04);
}
.chart-header { display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 16rpx; }
.chart-title { font-size: 30rpx; font-weight: 700; color: #1e293b; display: block; }
.chart-sub { font-size: 22rpx; color: #94a3b8; display: block; margin-top: 4rpx; }
.chart-arrow { width: 28rpx; height: 28rpx; opacity: 0.35; }
.chart-main-row { display: flex; align-items: baseline; gap: 8rpx; margin-bottom: 24rpx; }
.chart-big-num { font-size: 56rpx; font-weight: 700; color: #1e293b; line-height: 1; }
.chart-big-unit { font-size: 24rpx; color: #94a3b8; }

.chart-bars { display: flex; align-items: flex-end; gap: 0; height: 160rpx; padding-bottom: 8rpx; }
.chart-bar-group { flex: 1; display: flex; flex-direction: column; align-items: center; gap: 8rpx; }
.chart-bar-wrapper {
  width: 100%; display: flex; justify-content: center; align-items: flex-end; height: 150rpx;
}
.chart-bar {
  width: 60%; border-radius: 6rpx 6rpx 0 0; min-height: 8rpx; transition: height 0.6s ease;
}
.chart-bar.bar-active { background: linear-gradient(180deg, #4ade80, #22c55e); }
.chart-bar.bar-normal { background: #d1fae5; }
.chart-bar.bar-normal-light { background: #e8eaf0; }
.chart-bar-label { font-size: 20rpx; color: #94a3b8; }

/* 暖通/异常 */
.stats-strip { display: flex; gap: 16rpx; padding: 0 32rpx; margin-bottom: 28rpx; }
.stat-chip {
  flex: 1; display: flex; align-items: center; gap: 14rpx;
  background: #fff; border-radius: 16rpx; padding: 20rpx;
  box-shadow: 0 2rpx 12rpx rgba(0,0,0,0.04);
}
.stat-chip.chip-warn { border: 1rpx solid #fecaca; background: #fef2f2; }
.stat-icon { width: 36rpx; height: 36rpx; }
.stat-val { font-size: 26rpx; font-weight: 700; color: #1e293b; display: block; }
.stat-label { font-size: 20rpx; color: #94a3b8; display: block; margin-top: 2rpx; }

/* Section */
.section-header { display: flex; align-items: center; gap: 12rpx; padding: 4rpx 32rpx 20rpx; }
.section-dot { width: 10rpx; height: 10rpx; border-radius: 50%; background: #22c55e; }
.section-title { font-size: 28rpx; font-weight: 600; color: #1e293b; }

/* 建筑行 */
.building-row {
  display: flex; align-items: center; justify-content: space-between;
  margin: 0 32rpx 16rpx; background: #fff; border-radius: 16rpx;
  padding: 24rpx; box-shadow: 0 2rpx 12rpx rgba(0,0,0,0.04);
}
.brow-left { display: flex; align-items: center; gap: 16rpx; }
.brow-icon-box {
  width: 48rpx; height: 48rpx; border-radius: 12rpx;
  display: flex; align-items: center; justify-content: center;
}
.brow-icon-box.bg-blue { background: #eff6ff; }
.brow-icon-box.bg-purple { background: #f5f3ff; }
.brow-icon-box.bg-teal { background: #f0fdfa; }
.brow-icon-box.bg-orange { background: #fff7ed; }
.brow-icon-box.bg-indigo { background: #eef2ff; }
.brow-icon-box.bg-gray { background: #f3f4f6; }
.brow-icon { width: 24rpx; height: 24rpx; }
.brow-name { display: block; font-size: 28rpx; font-weight: 600; color: #1e293b; }
.brow-sub { display: block; font-size: 22rpx; color: #94a3b8; margin-top: 4rpx; }

.brow-right { display: flex; align-items: center; gap: 12rpx; }
.brow-badge {
  display: flex; align-items: center; gap: 6rpx;
  padding: 6rpx 16rpx; border-radius: 20rpx; font-size: 22rpx; font-weight: 500;
}
.brow-badge.badge-green { background: #f0fdf4; color: #16a34a; }
.brow-badge.badge-green .brow-dot { background: #22c55e; }
.brow-badge.badge-red { background: #fef2f2; color: #dc2626; }
.brow-badge.badge-red .brow-dot { background: #ef4444; }
.brow-dot { width: 10rpx; height: 10rpx; border-radius: 50%; }
.brow-arrow { width: 24rpx; height: 24rpx; opacity: 0.3; }

/* ====== 建筑详情视图 ====== */
.detail-header {
  margin: 0 32rpx 20rpx; background: #fff;
  border-radius: 20rpx; padding: 28rpx;
  box-shadow: 0 4rpx 20rpx rgba(0,0,0,0.04);
}
.detail-title-row { display: flex; align-items: center; gap: 16rpx; margin-bottom: 16rpx; }
.detail-icon-box {
  width: 60rpx; height: 60rpx; border-radius: 16rpx;
  display: flex; align-items: center; justify-content: center;
}
.detail-icon-box.bg-blue { background: #eff6ff; }
.detail-icon-box.bg-purple { background: #f5f3ff; }
.detail-icon-box.bg-teal { background: #f0fdfa; }
.detail-icon-box.bg-orange { background: #fff7ed; }
.detail-icon-box.bg-indigo { background: #eef2ff; }
.detail-icon-box.bg-gray { background: #f3f4f6; }
.detail-icon { width: 32rpx; height: 32rpx; }
.detail-name { display: block; font-size: 34rpx; font-weight: 700; color: #1e293b; }
.detail-sub { display: block; font-size: 22rpx; color: #94a3b8; margin-top: 4rpx; }

.detail-badges { display: flex; gap: 12rpx; }
.detail-badge {
  display: flex; align-items: center; gap: 6rpx;
  padding: 8rpx 20rpx; border-radius: 24rpx; font-size: 22rpx; font-weight: 500;
}
.detail-badge.dbadge-green { background: #f0fdf4; color: #16a34a; }
.detail-badge.dbadge-green .detail-dot { background: #22c55e; }
.detail-badge.dbadge-red { background: #fef2f2; color: #dc2626; }
.detail-badge.dbadge-red .detail-dot { background: #ef4444; }
.detail-badge.dbadge-orange { background: #fffbeb; color: #d97706; }
.detail-dot { width: 10rpx; height: 10rpx; border-radius: 50%; }

/* 三项 KPI */
.detail-kpi-row { display: flex; gap: 16rpx; padding: 0 32rpx; margin-bottom: 20rpx; }
.detail-kpi {
  flex: 1; background: #fff; border-radius: 18rpx;
  padding: 22rpx 16rpx; box-shadow: 0 2rpx 16rpx rgba(0,0,0,0.04);
  display: flex; flex-direction: column;
}
.dkpi-head { display: flex; align-items: center; gap: 8rpx; margin-bottom: 12rpx; }
.dkpi-icon { width: 24rpx; height: 24rpx; opacity: 0.6; }
.dkpi-label { font-size: 22rpx; color: #94a3b8; }
.dkpi-value { font-size: 32rpx; font-weight: 700; color: #1e293b; line-height: 1.1; }
.dkpi-unit { font-size: 18rpx; color: #94a3b8; margin-bottom: 12rpx; }

.dkpi-bar-track {
  width: 100%; height: 8rpx; background: #e8eaf0; border-radius: 4rpx;
  overflow: hidden; margin-bottom: 8rpx;
}
.dkpi-bar-fill { height: 100%; border-radius: 4rpx; transition: width 0.6s ease; }
.dkpi-bar-fill.fill-green { background: #22c55e; }
.dkpi-bar-fill.fill-blue { background: #3b82f6; }
.dkpi-bar-fill.fill-orange { background: #f97316; }
.dkpi-change { font-size: 20rpx; color: #94a3b8; }
.dkpi-change.up { color: #ef4444; }
.dkpi-change.down { color: #22c55e; }

/* 能耗对比 */
.detail-compare-card {
  margin: 0 32rpx 20rpx; background: #fff;
  border-radius: 24rpx; padding: 28rpx;
  box-shadow: 0 4rpx 20rpx rgba(0,0,0,0.04);
}
.dc-title { display: block; font-size: 28rpx; font-weight: 700; color: #1e293b; }
.dc-sub { display: block; font-size: 22rpx; color: #94a3b8; margin: 4rpx 0 24rpx; }

.dc-bars { display: flex; align-items: flex-end; height: 140rpx; gap: 0; }
.dc-bar-col { flex: 1; display: flex; flex-direction: column; align-items: center; gap: 8rpx; }
.dc-bar-wrap {
  width: 100%; display: flex; justify-content: center; align-items: flex-end; height: 120rpx;
}
.dc-bar { width: 50%; border-radius: 6rpx 6rpx 0 0; min-height: 8rpx; transition: height 0.6s ease; }
.dc-bar.dc-bar-active { background: linear-gradient(180deg, #4ade80, #22c55e); }
.dc-bar.dc-bar-dim { background: #e8eaf0; }
.dc-bar-label { font-size: 20rpx; color: #94a3b8; }
.dc-bar-label.dc-label-active { color: #22c55e; font-weight: 600; }

/* 强度+温度 */
.detail-info-row { display: flex; gap: 16rpx; padding: 0 32rpx; margin-bottom: 20rpx; }
.info-card {
  flex: 1; background: #fff; border-radius: 18rpx; padding: 24rpx;
  box-shadow: 0 2rpx 16rpx rgba(0,0,0,0.04);
}
.info-label { display: block; font-size: 22rpx; color: #94a3b8; margin-bottom: 12rpx; }
.info-main { display: flex; align-items: baseline; gap: 6rpx; }
.info-value { font-size: 40rpx; font-weight: 700; color: #1e293b; }
.info-unit { font-size: 22rpx; color: #94a3b8; }

/* 最新水耗 */
.detail-water-card {
  margin: 0 32rpx 24rpx; background: #fff;
  border-radius: 18rpx; padding: 24rpx;
  box-shadow: 0 2rpx 16rpx rgba(0,0,0,0.04);
}
.dw-row { display: flex; align-items: center; justify-content: space-between; margin-bottom: 16rpx; }
.dw-left { display: flex; align-items: center; gap: 12rpx; }
.dw-icon { width: 28rpx; height: 28rpx; }
.dw-label { font-size: 24rpx; color: #94a3b8; }
.dw-right { display: flex; align-items: baseline; gap: 4rpx; }
.dw-value { font-size: 36rpx; font-weight: 700; color: #1e293b; }
.dw-unit { font-size: 20rpx; color: #94a3b8; }
.dw-track {
  width: 100%; height: 10rpx; background: #e8eaf0; border-radius: 5rpx; overflow: hidden;
}
.dw-fill {
  height: 100%; border-radius: 5rpx;
  background: linear-gradient(90deg, #38bdf8, #3b82f6);
  transition: width 0.6s ease;
}

/* 骨架屏 */
.skeleton-area { padding: 0 32rpx; }
.sk-banner {
  height: 180rpx; border-radius: 24rpx; margin-bottom: 24rpx;
  background: linear-gradient(90deg, #eee 25%, #f5f5f5 50%, #eee 75%);
  background-size: 200% 100%; animation: shimmer 1.5s infinite;
}
.sk-row { display: flex; gap: 20rpx; margin-bottom: 24rpx; }
.sk-half {
  flex: 1; height: 220rpx; border-radius: 20rpx;
  background: linear-gradient(90deg, #eee 25%, #f5f5f5 50%, #eee 75%);
  background-size: 200% 100%; animation: shimmer 1.5s infinite;
}
.sk-card {
  height: 280rpx; border-radius: 24rpx;
  background: linear-gradient(90deg, #eee 25%, #f5f5f5 50%, #eee 75%);
  background-size: 200% 100%; animation: shimmer 1.5s infinite;
}
@keyframes shimmer { 0% { background-position: 200% 0; } 100% { background-position: -200% 0; } }

.safe-bottom { height: calc(env(safe-area-inset-bottom, 0px) + 140rpx); }
</style>
