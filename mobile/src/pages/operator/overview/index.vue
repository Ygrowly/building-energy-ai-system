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
      <view v-if="overview" class="weather-chip">
        <view v-if="overview.data_date" class="chip-date-wrap">
          <text class="chip-date-value">{{ overview.data_date }}</text>
        </view>
        <view
          v-if="overview.weather && overview.weather.temperature != null"
          class="chip-weather-wrap"
        >
          <image class="chip-icon" src="/static/icons/thermometer.svg" mode="aspectFit" />
          <text class="chip-temp">{{ formatFixed(overview.weather.temperature, 1) }}°C</text>
          <text class="chip-sub">{{ formatFixed(overview.weather.humidity, 1) }}%</text>
        </view>
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
            <view class="filter-tab-content">
              <image class="filter-icon" src="/static/icons/tab-overview.svg" mode="aspectFit" />
              <text class="filter-text">总览</text>
            </view>
          </view>
          <view
            v-for="b in overview.buildings"
            :key="'ft-'+b.building_type"
            class="filter-tab"
            :class="currentTab === b.building_type ? 'tab-active' : ''"
            @click="currentTab = b.building_type"
          >
            <view class="filter-tab-content">
              <image class="filter-icon" :src="getBuildingIcon(b.building_type)" mode="aspectFit" />
              <text class="filter-text">{{ (b.display_name || '').replace('楼', '') }}</text>
            </view>
          </view>
        </view>
      </scroll-view>
    </view>

    <!-- ==================== 总览视图 ==================== -->
    <view v-if="overview && currentTab === 'all'">
      <!-- 待处理工单（AI驳回） -->
      <view class="wo-section">
        <view class="section-header">
          <view class="section-dot dot-red" />
          <text class="section-title">待处理工单</text>
          <text class="section-count" v-if="rejectedOrders.length">{{ rejectedOrders.length }}条</text>
          <view style="flex:1" />
          <text class="section-link" @click="goWorkOrders">全部</text>
        </view>

        <view
          v-for="wo in rejectedOrders.slice(0, 5)"
          :key="wo.ticket_id"
          class="wo-card"
        >
          <view class="wo-card-top">
            <view
              class="wo-priority"
              :style="{ background: getPriorityColor(wo.priority).bg, color: getPriorityColor(wo.priority).text }"
            >
              {{ getPriorityLabel(wo.priority) }}
            </view>
            <text class="wo-time">{{ formatTimeAgo(wo.created_at) }}</text>
          </view>
          <text class="wo-desc">{{ sanitizeDisplayText(wo.issue_description) }}</text>
          <view class="wo-meta">
            <text class="wo-meta-item">{{ formatBuildingLabel(wo.building_id) }}</text>
            <text v-if="formatDeviceLabel(wo.device_id, wo.building_id)" class="wo-meta-item">{{ formatDeviceLabel(wo.device_id, wo.building_id) }}</text>
          </view>
          <view v-if="wo.ai_reason" class="wo-reason">
            <text class="wo-reason-label">AI驳回理由：</text>
            <text class="wo-reason-text">{{ sanitizeDisplayText(wo.ai_reason) }}</text>
          </view>
          <view class="wo-actions">
            <view class="wo-btn wo-btn-approve" @click="handleOverrideApprove(wo)">
              <text>覆盖批准</text>
            </view>
          </view>
        </view>

        <view v-if="!woLoading && rejectedOrders.length === 0" class="wo-empty">
          <image class="wo-empty-icon" src="/static/icons/check-circle.svg" mode="aspectFit" />
          <text class="wo-empty-text">暂无AI驳回工单</text>
        </view>

        <view v-if="woLoading && rejectedOrders.length === 0" class="wo-skeleton">
          <view class="wo-sk-card" />
          <view class="wo-sk-card" />
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
        <view class="detail-header-main">
          <view class="detail-title-row">
            <view class="detail-icon-box" :class="getBuildingBg(activeBuilding.building_type)">
              <image class="detail-icon" :src="getBuildingIcon(activeBuilding.building_type)" mode="aspectFit" />
            </view>
            <view class="detail-title-copy">
              <text class="detail-name">{{ activeBuilding.display_name }}</text>
              <text class="detail-sub">面积 {{ formatArea(activeBuilding.sqm) }} m²</text>
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
      </view>

      <!-- 三项 KPI 卡片 -->
      <view class="detail-kpi-row">
        <view class="detail-kpi kpi-electric">
          <view class="dkpi-head">
            <view class="dkpi-head-left dkpi-head-stack">
              <view class="dkpi-icon-wrap icon-green">
                <image class="dkpi-icon" src="/static/icons/lightning.svg" mode="aspectFit" />
              </view>
              <text class="dkpi-label">电耗</text>
            </view>
          <view class="dkpi-main dkpi-main-top">
              <text class="dkpi-value">{{ formatNum(activeBuilding.total_electricity_kwh) }}</text>
              <text class="dkpi-unit">kWh</text>
            </view>
          </view>
          <view class="dkpi-change" :class="changeClass(activeBuilding.electricity_change_pct)">
            <image
              v-if="getDeltaIcon(activeBuilding.electricity_change_pct)"
              class="dkpi-change-icon"
              :src="getDeltaIcon(activeBuilding.electricity_change_pct)"
              mode="aspectFit"
            />
            <text>{{ formatDelta(activeBuilding.electricity_change_pct) }}</text>
          </view>
        </view>
        <view class="detail-kpi kpi-water">
          <view class="dkpi-head">
            <view class="dkpi-head-left dkpi-head-stack">
              <view class="dkpi-icon-wrap icon-blue">
                <image class="dkpi-icon" src="/static/icons/droplet.svg" mode="aspectFit" />
              </view>
              <text class="dkpi-label">水耗</text>
            </view>
          <view class="dkpi-main dkpi-main-top">
              <text class="dkpi-value">{{ formatNum(activeBuilding.total_water_m3) }}</text>
              <text class="dkpi-unit">m³</text>
            </view>
          </view>
          <view class="dkpi-change" :class="changeClass(activeBuilding.water_change_pct)">
            <image
              v-if="getDeltaIcon(activeBuilding.water_change_pct)"
              class="dkpi-change-icon"
              :src="getDeltaIcon(activeBuilding.water_change_pct)"
              mode="aspectFit"
            />
            <text>{{ formatDelta(activeBuilding.water_change_pct) }}</text>
          </view>
        </view>
        <view class="detail-kpi kpi-hac">
          <view class="dkpi-head">
            <view class="dkpi-head-left dkpi-head-stack">
              <view class="dkpi-icon-wrap icon-orange">
                <image class="dkpi-icon" src="/static/icons/flame.svg" mode="aspectFit" />
              </view>
              <text class="dkpi-label">暖通</text>
            </view>
          <view class="dkpi-main dkpi-main-top">
              <text class="dkpi-value">{{ formatNum(activeBuilding.total_hac_energy_kwh) }}</text>
              <text class="dkpi-unit">kWh</text>
            </view>
          </view>
          <view class="dkpi-change" :class="changeClass(activeBuilding.hac_change_pct)">
            <image
              v-if="getDeltaIcon(activeBuilding.hac_change_pct)"
              class="dkpi-change-icon"
              :src="getDeltaIcon(activeBuilding.hac_change_pct)"
              mode="aspectFit"
            />
            <text>{{ formatDelta(activeBuilding.hac_change_pct) }}</text>
          </view>
        </view>
      </view>

      <!-- 7×24 热力图 -->
      <view class="heatmap-card">
        <view class="hm-header">
          <text class="hm-title">7×24 用电热力图</text>
          <text class="hm-sub">近14天小时均值</text>
        </view>
        <view v-if="heatmapData.length" class="hm-wrap">
          <view class="hm-main">
            <view class="hm-y-col">
              <text v-for="d in heatmapDays" :key="d" class="hm-y-label">{{ d }}</text>
            </view>
            <view class="hm-cells">
              <view
                v-for="cell in heatmapData"
                :key="`${cell.d}-${cell.h}`"
                class="hm-cell"
                :style="{ background: getHmColor(cell.v) }"
              />
            </view>
          </view>
          <view class="hm-x-row">
            <view class="hm-y-spacer" />
            <view class="hm-x-labels">
              <text
                v-for="h in 24"
                :key="'xh'+h"
                class="hm-x-label"
              >{{ [0, 6, 12, 18].includes(h - 1) ? `${h - 1}` : '' }}</text>
            </view>
          </view>
          <view class="hm-legend">
            <text class="hm-legend-text">低</text>
            <view v-for="c in hmLegendColors" :key="c" class="hm-legend-cell" :style="{ background: c }" />
            <text class="hm-legend-text">高</text>
          </view>
        </view>
        <view v-else class="hm-empty">
          <text class="hm-empty-text">{{ hmLoading ? '加载中...' : '暂无数据' }}</text>
        </view>
      </view>

      <!-- 能耗强度 + 环境温度 -->
      <view class="detail-info-row">
        <view class="info-card">
          <text class="info-label">能耗强度</text>
          <view class="info-main">
            <text class="info-value">{{ formatFixed(activeBuilding.energy_intensity_kwh_per_sqm, 2) }}</text>
            <text class="info-unit">kWh/m²</text>
          </view>
        </view>
        <view class="info-card">
          <text class="info-label">环境温度</text>
          <view class="info-main">
            <text class="info-value">{{ formatFixed(activeBuilding.avg_ambient_temp, 1) }}</text>
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
import { ref, computed, watch, onMounted, onUnmounted } from 'vue'
import NavBar from '../../../components/NavBar.vue'
import TabBar from '../../../components/TabBar.vue'
import { useAuthStore } from '../../../stores/auth'
import { useRouteGuard } from '../../../utils/route-guard'
import { OPERATOR_TABS } from '../../../constants/tabs'
import { OPERATOR_ROLES } from '../../../constants/roles'
import { dataApi, type OverviewResponse, type HourlyPoint, type WeekdayPoint } from '../../../api/data'
import { workOrderApi, type WorkOrder } from '../../../api/workorder'
import { PRIORITY_LABEL, PRIORITY_COLOR } from '../../../constants/status'
import { formatNum, formatPct } from '../../../utils/format'
import { getCache, setCache } from '../../../utils/cache'
import { formatBuildingLabel, formatDeviceLabel, sanitizeDisplayText } from '../../../utils/display'

useRouteGuard(OPERATOR_ROLES)

const authStore = useAuthStore()
const overview = ref<OverviewResponse | null>(null)
const loading = ref(false)
const currentTab = ref('all')

const OVERVIEW_CACHE_KEY = 'operator_overview_data'
const OVERVIEW_WORKORDERS_CACHE_KEY = 'operator_overview_rejected_workorders'
const OVERVIEW_STATE_KEY = 'operator_overview_state'
const OVERVIEW_STATE_TTL = 24 * 60 * 60 * 1000

// 工单相关
const rejectedOrders = ref<WorkOrder[]>([])
const woLoading = ref(false)

// 热力图相关
const heatmapData = ref<Array<{ d: number; h: number; v: number }>>([])
const hmMaxVal = ref(1)
const hmLoading = ref(false)
const heatmapDays = ['一', '二', '三', '四', '五', '六', '日']
const hmLegendColors = ['#ebedf0', '#9be9a8', '#40c463', '#30a14e', '#216e39']

function buildHeatmapCells(hourly: HourlyPoint[], weekly: WeekdayPoint[]) {
  const hAvg = Array.from({ length: 24 }, (_, h) => {
    const row = hourly.find(x => x.hour === h)
    return row?.avg_value ?? 0
  })
  const wVals = weekly.map(w => w.avg_value).filter(v => v > 0)
  const wMean = wVals.length ? wVals.reduce((a, b) => a + b, 0) / wVals.length : 1
  const cells: Array<{ d: number; h: number; v: number }> = []
  for (let d = 0; d < 7; d++) {
    const wdProfile = weekly.find(w => w.weekday === d + 1)?.avg_value ?? wMean
    const factor = wMean > 1e-9 ? wdProfile / wMean : 1
    for (let h = 0; h < 24; h++) {
      cells.push({ d, h, v: parseFloat(((hAvg[h] ?? 0) * factor).toFixed(2)) })
    }
  }
  return cells
}

function getHmColor(v: number): string {
  const ratio = Math.min(v / hmMaxVal.value, 1)
  const palette = hmLegendColors
  const breaks = [0.1, 0.3, 0.55, 0.75]
  let idx = 0
  for (const br of breaks) if (ratio > br) idx++
  return palette[idx]
}

let prevBuildingType = ''
async function loadHeatmap(buildingType: string) {
  if (!buildingType || buildingType === 'all') { heatmapData.value = []; return }
  if (buildingType === prevBuildingType && heatmapData.value.length) return
  prevBuildingType = buildingType
  const cacheKey = `operator_overview_heatmap_${buildingType}`
  const cached = getCache<{ cells: Array<{ d: number; h: number; v: number }>; max: number }>(cacheKey)
  if (cached) {
    heatmapData.value = cached.cells
    hmMaxVal.value = cached.max
  }
  hmLoading.value = true
  try {
    const res = await dataApi.loadProfile(buildingType)
    const cells = buildHeatmapCells(res.hourly_profile, res.weekday_profile)
    heatmapData.value = cells
    hmMaxVal.value = Math.max(...cells.map(c => c.v), 1)
    setCache(cacheKey, {
      cells,
      max: hmMaxVal.value,
    })
  } catch {
    heatmapData.value = []
  } finally {
    hmLoading.value = false
  }
}

const greeting = computed(() => {
  const h = new Date().getHours()
  if (h < 6) return '夜深了'
  if (h < 12) return '上午好'
  if (h < 14) return '中午好'
  if (h < 18) return '下午好'
  return '晚上好'
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

watch(currentTab, (tab) => {
  setCache(OVERVIEW_STATE_KEY, { currentTab: tab })
  loadHeatmap(tab)
})

async function loadWorkOrders() {
  const cached = getCache<WorkOrder[]>(OVERVIEW_WORKORDERS_CACHE_KEY)
  if (cached) rejectedOrders.value = cached
  woLoading.value = !cached
  try {
    const res = await workOrderApi.list({ status: 'auto_rejected', page: 1, page_size: 5 })
    rejectedOrders.value = res.work_orders
    setCache(OVERVIEW_WORKORDERS_CACHE_KEY, res.work_orders)
  } catch { /* toast handled by request.ts */ }
  finally { woLoading.value = false }
}

async function handleOverrideApprove(wo: WorkOrder) {
  try {
    await workOrderApi.adminReview(wo.ticket_id, 'override_approve')
    uni.showToast({ title: '已批准', icon: 'success' })
    rejectedOrders.value = rejectedOrders.value.filter(o => o.ticket_id !== wo.ticket_id)
  } catch { /* toast handled by request.ts */ }
}

function goWorkOrders() {
  uni.switchTab({ url: '/pages/operator/workorders/index' })
}

function getPriorityColor(p: string) {
  return PRIORITY_COLOR[p] || { bg: '#f0f0f0', text: '#999' }
}

function getPriorityLabel(p: string) {
  return PRIORITY_LABEL[p] || p
}

function formatTimeAgo(dateStr: string): string {
  const diff = Date.now() - new Date(dateStr).getTime()
  const mins = Math.floor(diff / 60000)
  if (mins < 1) return '刚刚'
  if (mins < 60) return `${mins}分钟前`
  const hours = Math.floor(mins / 60)
  if (hours < 24) return `${hours}小时前`
  const days = Math.floor(hours / 24)
  return `${days}天前`
}

async function loadData() {
  const cached = getCache<OverviewResponse>(OVERVIEW_CACHE_KEY)
  if (cached) overview.value = cached
  loading.value = !cached
  try {
    overview.value = await dataApi.overview()
    setCache(OVERVIEW_CACHE_KEY, overview.value)
  }
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

/** Banner 柱状图是否高亮：总览时全亮，选中建筑时只亮对应的 */
function isBannerBarActive(buildingType: string): boolean {
  if (currentTab.value === 'all') return true
  return currentTab.value === buildingType
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

function getDeltaIcon(value: number | null | undefined): string {
  if (value == null || Number.isNaN(value) || value === 0) return ''
  return value > 0 ? '/static/icons/arrow-up.svg' : '/static/icons/arrow-down.svg'
}

function formatDelta(value: number | null | undefined): string {
  if (value == null || Number.isNaN(value)) return '--'
  return formatPct(value)
}

function formatArea(area: number | null | undefined): string {
  if (area == null || Number.isNaN(area)) return '--'
  if (area >= 1000) return area.toFixed(1)
  if (area >= 100) return area.toFixed(2)
  return area.toFixed(2)
}

function formatFixed(value: number | null | undefined, digits = 1): string {
  if (value == null || Number.isNaN(value)) return '--'
  return value.toFixed(digits)
}

let timer: ReturnType<typeof setInterval>
onMounted(() => {
  const cachedState = getCache<{ currentTab?: string }>(OVERVIEW_STATE_KEY, OVERVIEW_STATE_TTL)
  if (cachedState?.currentTab) currentTab.value = cachedState.currentTab
  loadData()
  loadWorkOrders()
  timer = setInterval(() => { loadData(); loadWorkOrders() }, 60000)
})
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
.header-info { display: flex; align-items: baseline; gap: 10rpx; }
.avatar-circle {
  width: 64rpx; height: 64rpx; border-radius: 50%;
  background: linear-gradient(135deg, #22c55e, #16a34a);
  display: flex; align-items: center; justify-content: center;
}
.avatar-text { font-size: 28rpx; font-weight: 700; color: #fff; }
.header-greeting { font-size: 22rpx; color: #94a3b8; }
.header-name { font-size: 32rpx; font-weight: 700; color: #1e293b; }

.weather-chip {
  display: flex; align-items: center; gap: 8rpx;
  background: #fff; border-radius: 40rpx; padding: 14rpx 24rpx;
  box-shadow: 0 2rpx 16rpx rgba(0,0,0,0.05);
}
.chip-date-wrap {
  display: inline-flex; align-items: center; gap: 8rpx;
  padding-right: 14rpx; margin-right: 6rpx;
  border-right: 1rpx solid #e2e8f0;
}
.chip-date-value { font-size: 22rpx; color: #475569; font-weight: 600; }
.chip-weather-wrap { display: inline-flex; align-items: center; gap: 8rpx; }
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
  border-radius: 26rpx; padding: 10rpx;
  box-shadow: 0 10rpx 28rpx rgba(15, 23, 42, 0.06);
}
.filter-scroll { white-space: nowrap; }
.filter-inner { display: flex; gap: 10rpx; }
.filter-tab {
  display: flex; align-items: center; justify-content: center;
  padding: 0 6rpx; border-radius: 999rpx;
  flex-shrink: 0;
  background: transparent;
  transition: all 0.25s ease;
}
.filter-tab-content {
  display: inline-flex; align-items: center; gap: 10rpx;
  min-height: 64rpx; padding: 0 22rpx;
  border-radius: 999rpx;
  background: #f8fafc;
  transition: all 0.25s ease;
}
.filter-tab.tab-active .filter-tab-content {
  background: linear-gradient(135deg, #22c55e 0%, #16a34a 100%);
  box-shadow: 0 8rpx 18rpx rgba(34, 197, 94, 0.24);
}
.filter-tab.tab-active .filter-text { color: #fff; font-weight: 600; }
.filter-tab.tab-active .filter-icon {
  opacity: 1;
  filter: brightness(0) invert(1);
}
.filter-icon { width: 28rpx; height: 28rpx; opacity: 0.72; }
.filter-text {
  font-size: 24rpx; color: #64748b; white-space: nowrap;
  line-height: 1;
}

/* KPI 双卡片 */
/* Section */
.section-header { display: flex; align-items: center; gap: 12rpx; padding: 4rpx 32rpx 20rpx; }
.section-dot { width: 10rpx; height: 10rpx; border-radius: 50%; background: #22c55e; }
.section-dot.dot-red { background: #ef4444; }
.section-title { font-size: 28rpx; font-weight: 600; color: #1e293b; }
.section-count { font-size: 22rpx; color: #94a3b8; }
.section-link { font-size: 24rpx; color: #3b82f6; font-weight: 500; }

/* 待处理工单 */
.wo-section { margin-bottom: 24rpx; }
.wo-card {
  margin: 0 32rpx 16rpx; background: #fff; border-radius: 16rpx;
  padding: 24rpx; box-shadow: 0 2rpx 12rpx rgba(0,0,0,0.04);
  border-left: 6rpx solid #ff4d4f;
}
.wo-card-top { display: flex; align-items: center; justify-content: space-between; margin-bottom: 12rpx; }
.wo-priority {
  font-size: 20rpx; font-weight: 600; padding: 4rpx 14rpx;
  border-radius: 8rpx; line-height: 1.4;
}
.wo-time { font-size: 22rpx; color: #94a3b8; }
.wo-desc {
  font-size: 28rpx; font-weight: 500; color: #1e293b;
  margin-bottom: 10rpx; line-height: 1.5;
  overflow: hidden; text-overflow: ellipsis;
  display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical;
}
.wo-meta { display: flex; gap: 16rpx; margin-bottom: 12rpx; }
.wo-meta-item {
  font-size: 22rpx; color: #64748b; background: #f1f5f9;
  padding: 4rpx 12rpx; border-radius: 6rpx;
}
.wo-reason {
  background: #fef2f2; border-radius: 10rpx; padding: 14rpx 16rpx;
  margin-bottom: 16rpx;
}
.wo-reason-label { font-size: 22rpx; color: #ef4444; font-weight: 600; }
.wo-reason-text { font-size: 22rpx; color: #7f1d1d; line-height: 1.5; }
.wo-actions { display: flex; justify-content: flex-end; }
.wo-btn {
  font-size: 24rpx; font-weight: 500; padding: 10rpx 28rpx;
  border-radius: 10rpx; line-height: 1.4;
}
.wo-btn-approve { background: #22c55e; color: #fff; }

.wo-empty {
  display: flex; flex-direction: column; align-items: center;
  padding: 60rpx 0; gap: 16rpx;
}
.wo-empty-icon { width: 64rpx; height: 64rpx; opacity: 0.4; }
.wo-empty-text { font-size: 26rpx; color: #94a3b8; }

.wo-skeleton { padding: 0 32rpx; }
.wo-sk-card {
  height: 200rpx; background: #e2e8f0; border-radius: 16rpx;
  margin-bottom: 16rpx; animation: pulse 1.5s ease-in-out infinite;
}
@keyframes pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.5; } }

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
  border-radius: 24rpx; padding: 28rpx;
  box-shadow: 0 10rpx 28rpx rgba(15, 23, 42, 0.06);
}
.detail-header-main {
  display: flex; align-items: flex-start; justify-content: space-between; gap: 16rpx;
}
.detail-title-row { display: flex; align-items: center; gap: 16rpx; flex: 1; min-width: 0; }
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
.detail-title-copy { flex: 1; min-width: 0; }
.detail-name { display: block; font-size: 34rpx; font-weight: 700; color: #1e293b; }
.detail-sub { display: block; font-size: 22rpx; color: #94a3b8; margin-top: 6rpx; }

.detail-badges {
  display: flex; flex-direction: column; align-items: flex-end; gap: 10rpx;
  flex-shrink: 0;
}
.detail-badge {
  display: flex; align-items: center; gap: 6rpx;
  padding: 8rpx 20rpx; border-radius: 24rpx; font-size: 22rpx; font-weight: 600;
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
  padding: 18rpx 18rpx 20rpx; box-shadow: 0 6rpx 20rpx rgba(15, 23, 42, 0.05);
  display: flex; flex-direction: column;
}
.dkpi-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 8rpx; margin-bottom: 18rpx; }
.dkpi-head-left { display: flex; align-items: center; gap: 8rpx; min-width: 0; }
.dkpi-head-stack { flex-direction: column; align-items: flex-start; gap: 14rpx; }
.dkpi-icon-wrap {
  width: 44rpx; height: 44rpx; border-radius: 14rpx;
  display: flex; align-items: center; justify-content: center;
  flex-shrink: 0;
}
.dkpi-icon-wrap.icon-green { background: #ecfdf3; }
.dkpi-icon-wrap.icon-blue { background: #eff6ff; }
.dkpi-icon-wrap.icon-orange { background: #fff7ed; }
.dkpi-icon { width: 22rpx; height: 22rpx; opacity: 0.95; }
.dkpi-label { font-size: 22rpx; color: #64748b; font-weight: 600; }
.dkpi-main { display: flex; align-items: baseline; gap: 6rpx; margin-bottom: 6rpx; }
.dkpi-main-top { margin-bottom: 0; justify-content: flex-end; text-align: right; flex-shrink: 0; }
.dkpi-value { font-size: 40rpx; font-weight: 700; color: #0f172a; line-height: 1.05; }
.dkpi-unit { font-size: 20rpx; color: #94a3b8; }
.dkpi-change {
  display: flex; align-items: baseline; justify-content: flex-end; gap: 6rpx;
  font-size: 18rpx; color: #94a3b8; margin-top: auto;
  line-height: 1;
}
.dkpi-change-icon {
  width: 16rpx; height: 16rpx;
  position: relative; top: 1rpx;
}
.dkpi-change.up { color: #ef4444; }
.dkpi-change.down { color: #22c55e; }

/* 热力图 */
.heatmap-card {
  margin: 0 32rpx 20rpx; background: #fff;
  border-radius: 24rpx; padding: 28rpx;
  box-shadow: 0 4rpx 20rpx rgba(0,0,0,0.04);
}
.hm-header { margin-bottom: 20rpx; }
.hm-title { display: block; font-size: 28rpx; font-weight: 700; color: #1e293b; }
.hm-sub { display: block; font-size: 22rpx; color: #94a3b8; margin-top: 4rpx; }

.hm-wrap { display: flex; flex-direction: column; gap: 10rpx; }
.hm-main { display: flex; align-items: stretch; gap: 12rpx; }
.hm-y-col {
  display: flex; flex-direction: column; justify-content: space-around;
  width: 40rpx; flex-shrink: 0;
}
.hm-y-label {
  font-size: 18rpx; color: #94a3b8; text-align: right;
  flex: 1; display: flex; align-items: center; justify-content: flex-end;
}
.hm-cells {
  flex: 1; display: grid;
  grid-template-columns: repeat(24, 1fr); gap: 3rpx;
}
.hm-cell {
  aspect-ratio: 1; border-radius: 4rpx;
  min-width: 0; min-height: 0;
}
.hm-x-row { display: flex; align-items: center; gap: 12rpx; }
.hm-y-spacer { width: 40rpx; flex-shrink: 0; }
.hm-x-labels {
  flex: 1; display: grid;
  grid-template-columns: repeat(24, 1fr); gap: 3rpx;
}
.hm-x-label { font-size: 16rpx; color: #94a3b8; text-align: center; }
.hm-legend {
  display: flex; align-items: center; gap: 6rpx;
  justify-content: flex-end; margin-top: 4rpx;
}
.hm-legend-text { font-size: 18rpx; color: #94a3b8; }
.hm-legend-cell { width: 20rpx; height: 20rpx; border-radius: 4rpx; }

.hm-empty {
  display: flex; justify-content: center; padding: 40rpx 0;
}
.hm-empty-text { font-size: 24rpx; color: #94a3b8; }

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
