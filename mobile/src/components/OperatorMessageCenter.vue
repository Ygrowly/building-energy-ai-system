<template>
  <view class="message-center" @click="closePickers">
    <view class="capsule-wrap">
      <view class="capsule-bar">
        <view
          class="capsule-btn"
          :class="{ active: msgTab === 'workorder' }"
          @click="switchTab('workorder')"
        >
          <text>待审批工单</text>
          <view v-if="pendingCount > 0" class="capsule-dot ok">{{ pendingCount }}</view>
        </view>
        <view
          class="capsule-btn"
          :class="{ active: msgTab === 'anomaly' }"
          @click="switchTab('anomaly')"
        >
          <text>异常告警</text>
          <view v-if="anomalyCount > 0" class="capsule-dot">{{ anomalyCount > 99 ? '99+' : anomalyCount }}</view>
        </view>
        <view
          class="capsule-btn"
          :class="{ active: msgTab === 'warning' }"
          @click="switchTab('warning')"
        >
          <text>预警通知</text>
          <view v-if="riskHighCount > 0" class="capsule-dot warn">{{ riskHighCount }}</view>
        </view>
      </view>
    </view>

    <view class="filter-bar">
      <view class="filter-fields">
        <view class="filter-pill" :class="{ active: filterBuilding !== 'all', open: showBuildingPicker }" @click.stop="toggleBuildingPicker">
          <view class="pill-inner">
            <text class="pill-label">建筑</text>
            <text class="pill-value">{{ BUILDING_OPTIONS.find(o => o.value === filterBuilding)?.label }}</text>
          </view>
          <text class="pill-arrow">›</text>
          <view v-if="showBuildingPicker" class="dropdown-menu" @click.stop>
            <view
              v-for="opt in BUILDING_OPTIONS"
              :key="opt.value"
              class="dropdown-item"
              :class="{ selected: filterBuilding === opt.value }"
              @click="selectBuilding(opt.value)"
            >
              <text>{{ opt.label }}</text>
              <text v-if="filterBuilding === opt.value" class="dropdown-check">✓</text>
            </view>
          </view>
        </view>
        <view class="filter-pill" :class="{ active: filterHours !== 0, open: showTimePicker }" @click.stop="toggleTimePicker">
          <view class="pill-inner">
            <text class="pill-label">{{ msgTab === 'warning' ? '预测窗口' : '时间范围' }}</text>
            <text class="pill-value">{{ currentTimeOptions.find(o => o.value === filterHours)?.label ?? (msgTab === 'warning' ? '6 小时' : '全部时间') }}</text>
          </view>
          <text class="pill-arrow">›</text>
          <view v-if="showTimePicker" class="dropdown-menu" @click.stop>
            <view
              v-for="opt in currentTimeOptions"
              :key="opt.value"
              class="dropdown-item"
              :class="{ selected: filterHours === opt.value }"
              @click="selectTime(opt.value)"
            >
              <text>{{ opt.label }}</text>
              <text v-if="filterHours === opt.value" class="dropdown-check">✓</text>
            </view>
          </view>
        </view>
      </view>
      <view class="filter-actions">
        <view class="filter-btn apply" :class="{ active: hasActiveFilter }">
          <text>筛选</text>
        </view>
      </view>
    </view>

    <scroll-view v-if="msgTab === 'workorder'" scroll-y class="list-area" :style="listAreaStyle">
      <view class="block-label-row">
        <text class="block-label">待审批工单</text>
        <view v-if="pendingCount > 0" class="count-badge">{{ pendingCount }}</view>
      </view>

      <view v-if="pendingLoading && !pendingIncidents.length">
        <view v-for="i in 3" :key="i" class="msg-item skeleton">
          <view class="sk-line" />
          <view class="sk-line short" />
        </view>
      </view>

      <view v-else-if="!pendingIncidents.length" class="empty-block">
        <text class="empty-check">✓</text>
        <text class="empty-text">暂无待审批工单</text>
      </view>

      <view
        v-for="incident in pendingIncidents"
        :key="incident.id"
        class="msg-item clickable"
        @click="openDetail(incident)"
      >
        <view class="msg-icon workorder">
          <text>🔧</text>
        </view>
        <view class="msg-body">
          <text class="msg-title">{{ formatBuildingLabel(incident.building_id) }}</text>
          <text class="msg-sub">{{ sanitizeDisplayText(incident.summary_text || incident.incident_id) }}</text>
          <text class="msg-time">{{ formatRelativeTime(incident.updated_at) }}</text>
        </view>
        <view class="msg-tag pending">
          <text>待审批</text>
        </view>
        <text class="msg-arrow">›</text>
      </view>
    </scroll-view>

    <scroll-view v-if="msgTab === 'anomaly'" scroll-y class="list-area" :style="listAreaStyle">
      <view class="block-label-row">
        <text class="block-label">已发生异常</text>
        <text class="refresh-btn" @click="loadAnomalies">↻</text>
      </view>

      <view v-if="anomalyLoading && !anomalies.length">
        <view v-for="i in 4" :key="i" class="msg-item skeleton">
          <view class="sk-line" />
          <view class="sk-line short" />
        </view>
      </view>

      <view v-else-if="!filteredAnomalies.length" class="empty-block">
        <text class="empty-check">✓</text>
        <text class="empty-text">{{ hasActiveFilter ? '当前筛选条件下无异常记录' : '近期无异常告警' }}</text>
      </view>

      <view
        v-for="(anom, idx) in filteredAnomalies"
        :key="(anom.data_timestamp || '') + idx"
        class="msg-item"
        :class="'sev-' + deviationSeverity(anom.deviation_pct)"
      >
        <view class="msg-icon anom" :class="deviationSeverity(anom.deviation_pct)">
          <text>{{ RULE_EMOJI[anom.rule_triggered] || '⚠' }}</text>
        </view>
        <view class="msg-body">
          <text class="msg-title">{{ RULE_LABEL[anom.rule_triggered] || anom.rule_triggered }}</text>
          <text class="msg-sub">
            {{ BUILDING_LABEL[anom.building_id] || anom.building_id }}
            <text v-if="anom.deviation_pct != null" :class="'dev-' + deviationSeverity(anom.deviation_pct)"> · {{ anom.deviation_pct > 0 ? '+' : '' }}{{ anom.deviation_pct.toFixed(1) }}%</text>
            · {{ formatRelativeTime(anom.data_timestamp) }}
          </text>
          <text v-if="anom.message" class="msg-detail">{{ anom.message }}</text>
        </view>
        <view class="msg-tag" :class="'tag-' + deviationSeverity(anom.deviation_pct)">
          <text>{{ { high: '严重', medium: '警告', low: '提示' }[deviationSeverity(anom.deviation_pct)] }}</text>
        </view>
      </view>
    </scroll-view>

    <scroll-view v-if="msgTab === 'warning'" scroll-y class="list-area" :style="listAreaStyle">
      <view class="block-label-row">
        <text class="block-label">未来 {{ filterHours }} 小时预测预警</text>
        <text class="refresh-btn" @click="loadPredictions">↻</text>
      </view>

      <view v-if="predictionLoading && !latestPredictions.length">
        <view v-for="i in 3" :key="i" class="prediction-card skeleton">
          <view class="sk-line" />
          <view class="sk-line short" />
        </view>
      </view>

      <view v-else-if="predictionError" class="empty-block">
        <text class="empty-check">!</text>
        <text class="empty-text">{{ predictionError }}</text>
      </view>

      <view v-else-if="!filteredPredictions.length" class="empty-block">
        <text class="empty-check">✓</text>
        <text class="empty-text">{{ filterBuilding !== 'all' ? '该建筑在所选预测窗口内暂无异常预警' : `未来 ${filterHours} 小时暂无异常预警` }}</text>
      </view>

      <view
        v-for="prediction in filteredPredictions"
        :key="prediction.id"
        class="prediction-card"
        :class="'prediction-' + prediction.risk_level"
      >
        <view class="prediction-card-left">
          <view class="prediction-icon" :class="prediction.risk_level">
            <text>{{ prediction.risk_level === 'critical' ? '⚠' : '⚡' }}</text>
          </view>
          <view class="prediction-info">
            <view class="prediction-header">
              <text class="prediction-name">{{ prediction.building_name }}</text>
              <view class="prediction-mode-badge"><text>{{ predictionWindowLabel(prediction.horizon_h) }}</text></view>
            </view>
            <text class="prediction-desc">{{ predictionSummary(prediction) }}</text>
            <text class="prediction-meta">
              预测时刻 {{ formatForecastTime(prediction.forecast_for_timestamp) }}
              <text v-if="prediction.expected_value != null || prediction.predicted_value != null">
                · 预测 {{ formatPredictionValue(prediction.predicted_value, prediction.metric_name) }}
                <text v-if="prediction.expected_value != null"> / 基线 {{ formatPredictionValue(prediction.expected_value, prediction.metric_name) }}</text>
              </text>
            </text>
            <text
              v-if="prediction.deviation_pct != null"
              class="prediction-deviation"
              :class="'dev-' + prediction.risk_level"
            >
              偏差 {{ prediction.deviation_pct > 0 ? '+' : '' }}{{ prediction.deviation_pct }}%
            </text>
          </view>
        </view>
        <view class="prediction-level-tag" :class="prediction.risk_level">
          <text>{{ prediction.risk_level === 'critical' ? '高风险' : '预警' }}</text>
        </view>
      </view>
    </scroll-view>

  </view>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { RULE_LABEL } from '../constants/status'
import { dataApi, type AnomalyItem, type PredictionItem } from '../api/data'
import { incidentApi, type Incident } from '../api/incident'
import { formatRelativeTime, formatServerDateTime } from '../utils/format'
import { getCache, setCache } from '../utils/cache'
import { formatBuildingLabel, sanitizeDisplayText } from '../utils/display'

const props = withDefaults(defineProps<{
  withTabBar?: boolean
}>(), {
  withTabBar: false,
})

const RULE_EMOJI: Record<string, string> = {
  electricity_overload: '⚡',
  water_leak: '💧',
  hvac_overconsumption: '❄',
  A_low_efficiency: '📉',
  B_small_deltaT: '🌊',
  C_unexpected_on: '⏰',
}

const BUILDING_LABEL: Record<string, string> = {
  Office: '办公楼',
  Education: '教学楼',
  'Public services': '公共楼',
  Public: '公共楼',
}

const BUILDING_OPTIONS = [
  { value: 'all', label: '全部建筑' },
  { value: 'Education', label: '教学楼' },
  { value: 'Office', label: '办公楼' },
  { value: 'Public services', label: '公共楼' },
]

const TIME_OPTIONS = [
  { value: 0, label: '全部时间' },
  { value: 24, label: '近 24 小时' },
  { value: 168, label: '近 7 天' },
  { value: 720, label: '近 30 天' },
]

const WARNING_TIME_OPTIONS = [
  { value: 6, label: '6 小时' },
  { value: 12, label: '12 小时' },
]

const MESSAGE_STATE_KEY = 'operator_message_center_state'
const MESSAGE_STATE_TTL = 24 * 60 * 60 * 1000

const msgTab = ref<'workorder' | 'anomaly' | 'warning'>('workorder')
const filterBuilding = ref('all')
const filterHours = ref(0)
const showBuildingPicker = ref(false)
const showTimePicker = ref(false)

const currentTimeOptions = computed(() =>
  msgTab.value === 'warning' ? WARNING_TIME_OPTIONS : TIME_OPTIONS,
)

const hasActiveFilter = computed(() =>
  filterBuilding.value !== 'all' || filterHours.value !== 0,
)

const listAreaStyle = computed(() => ({
  paddingBottom: props.withTabBar ? 'calc(env(safe-area-inset-bottom, 0px) + 140rpx)' : '32rpx',
}))

function saveViewState() {
  setCache(MESSAGE_STATE_KEY, {
    msgTab: msgTab.value,
    filterBuilding: filterBuilding.value,
    filterHours: filterHours.value,
  })
}

function restoreViewState() {
  const cached = getCache<{
    msgTab?: 'workorder' | 'anomaly' | 'warning'
    filterBuilding?: string
    filterHours?: number
  }>(MESSAGE_STATE_KEY, MESSAGE_STATE_TTL)

  if (!cached) return

  if (cached.msgTab && ['workorder', 'anomaly', 'warning'].includes(cached.msgTab)) {
    msgTab.value = cached.msgTab
  }
  if (cached.filterBuilding && BUILDING_OPTIONS.some((option) => option.value === cached.filterBuilding)) {
    filterBuilding.value = cached.filterBuilding
  }
  if (typeof cached.filterHours === 'number') {
    filterHours.value = cached.filterHours
  }

  if (msgTab.value === 'warning' && ![6, 12].includes(filterHours.value)) {
    filterHours.value = 6
  }
  if (msgTab.value !== 'warning' && [6, 12].includes(filterHours.value)) {
    filterHours.value = 0
  }
}

function onFilterChange() {
  saveViewState()
}

function closePickers() {
  showBuildingPicker.value = false
  showTimePicker.value = false
}

function toggleBuildingPicker() {
  showBuildingPicker.value = !showBuildingPicker.value
  showTimePicker.value = false
}

function toggleTimePicker() {
  showTimePicker.value = !showTimePicker.value
  showBuildingPicker.value = false
}

function selectBuilding(value: string) {
  filterBuilding.value = value
  showBuildingPicker.value = false
  onFilterChange()
}

function selectTime(value: number) {
  filterHours.value = value
  showTimePicker.value = false
  onFilterChange()
}

function switchTab(tab: 'workorder' | 'anomaly' | 'warning') {
  msgTab.value = tab
  if (tab === 'workorder' && !pendingIncidents.value.length) loadPending()
  if (tab === 'anomaly' && !anomalies.value.length) loadAnomalies()
  if (tab === 'warning') {
    if (![6, 12].includes(filterHours.value)) filterHours.value = 6
    if (!predictions.value.length) loadPredictions()
  } else if ([6, 12].includes(filterHours.value)) {
    filterHours.value = 0
  }
  saveViewState()
}

const pendingIncidents = ref<Incident[]>([])
const pendingLoading = ref(false)

const pendingCount = computed(() => pendingIncidents.value.length)

async function loadPending() {
  const cached = getCache<Incident[]>('msg_pending')
  if (cached) pendingIncidents.value = cached
  pendingLoading.value = !cached
  try {
    const res = await incidentApi.list({
      workflow_status: 'pending_review',
      page: 1,
      page_size: 50,
    })
    pendingIncidents.value = res.incidents
    setCache('msg_pending', res.incidents)
  } catch {
    // noop
  } finally {
    pendingLoading.value = false
  }
}

function openDetail(incident: Incident) {
  const ticketId = incident.current_work_order?.ticket_id
  if (!ticketId) return
  uni.navigateTo({
    url: `/pages/worker/workorder-detail/index?incident_id=${incident.incident_id}&ticket_id=${ticketId}&readonly=1`,
  })
}

const anomalies = ref<AnomalyItem[]>([])
const anomalyLoading = ref(false)

const anomalyCount = computed(() => anomalies.value.length)

function deviationSeverity(pct?: number | null): 'high' | 'medium' | 'low' {
  const abs = Math.abs(pct ?? 0)
  if (abs >= 30) return 'high'
  if (abs >= 15) return 'medium'
  return 'low'
}

const filteredAnomalies = computed(() => {
  let list = anomalies.value
  if (filterBuilding.value !== 'all') {
    list = list.filter((a) => a.building_id === filterBuilding.value)
  }
  if (filterHours.value > 0) {
    const cutoff = Date.now() - filterHours.value * 3600 * 1000
    list = list.filter((a) => new Date(a.data_timestamp || '').getTime() >= cutoff)
  }
  return list
})

async function loadAnomalies() {
  const cached = getCache<AnomalyItem[]>('msg_anomalies')
  if (cached) anomalies.value = cached
  anomalyLoading.value = !cached
  try {
    const res = await dataApi.recentAnomalies({ hours: 168 })
    anomalies.value = res.anomalies
    setCache('msg_anomalies', res.anomalies)
  } catch {
    // noop
  } finally {
    anomalyLoading.value = false
  }
}

const predictions = ref<PredictionItem[]>([])
const predictionLoading = ref(false)
const predictionError = ref('')

const latestPredictionBatchAt = computed(() => {
  const timestamps = predictions.value
    .map((item) => item.as_of_timestamp || item.created_at)
    .filter((value): value is string => Boolean(value))
    .sort((a, b) => new Date(b).getTime() - new Date(a).getTime())
  return timestamps[0] ?? null
})

const latestPredictions = computed(() =>
  predictions.value.filter((item) => (item.as_of_timestamp || item.created_at) === latestPredictionBatchAt.value),
)

const riskHighCount = computed(() =>
  latestPredictions.value.filter((item) => item.risk_level === 'warning' || item.risk_level === 'critical').length,
)

const filteredPredictions = computed(() =>
  filterBuilding.value === 'all'
    ? latestPredictions.value.filter((item) => item.horizon_h === filterHours.value)
    : latestPredictions.value.filter((item) => item.horizon_h === filterHours.value && item.building_type === filterBuilding.value),
)

async function loadPredictions() {
  const cached = getCache<PredictionItem[]>('msg_predictions')
  if (cached) predictions.value = cached
  predictionLoading.value = !cached
  predictionError.value = ''
  try {
    const res = await dataApi.recentPredictions({ hours: 168 })
    predictions.value = (res.predictions || [])
      .filter((item) => item.risk_level === 'warning' || item.risk_level === 'critical')
      .sort((a, b) => {
        const levelOrder = { critical: 0, warning: 1 }
        const levelDiff = levelOrder[a.risk_level as keyof typeof levelOrder] - levelOrder[b.risk_level as keyof typeof levelOrder]
        if (levelDiff !== 0) return levelDiff
        return Math.abs(b.deviation_pct || 0) - Math.abs(a.deviation_pct || 0)
      })
    setCache('msg_predictions', predictions.value)
    if (!predictions.value.length && res.message) {
      predictionError.value = res.message
    }
  } catch (error) {
    predictionError.value = error instanceof Error ? error.message : '预测预警加载失败'
  } finally {
    predictionLoading.value = false
  }
}

function predictionWindowLabel(horizon: number) {
  return `${horizon}h`
}

function metricLabel(metricName: string) {
  const labels: Record<string, string> = {
    electricity_kwh: '用电量',
    water_l: '水耗',
    hac_energy: '空调能耗',
    sim_supply_temp_c: '供水温度',
    sim_return_temp_c: '回水温度',
  }
  return labels[metricName] || metricName
}

function metricUnit(metricName: string) {
  const units: Record<string, string> = {
    electricity_kwh: 'kWh',
    water_l: 'L',
    hac_energy: 'kWh',
    sim_supply_temp_c: '℃',
    sim_return_temp_c: '℃',
  }
  return units[metricName] || ''
}

function formatPredictionValue(value: number | null, metricName: string) {
  if (value == null || Number.isNaN(value)) return '--'
  const unit = metricUnit(metricName)
  return `${value.toFixed(2)}${unit ? ` ${unit}` : ''}`
}

function formatForecastTime(iso: string | null) {
  return formatServerDateTime(iso)
}

function predictionSummary(item: PredictionItem) {
  const metric = RULE_LABEL[item.rule_triggered || ''] || metricLabel(item.metric_name)
  const prefix = item.risk_level === 'critical' ? '预计显著异常' : '预计偏离基线'
  return `${metric} ${prefix}`
}

onMounted(() => {
  restoreViewState()
  loadPending()
  if (msgTab.value === 'anomaly') loadAnomalies()
  loadPredictions()
})
</script>

<style lang="scss" scoped>
.message-center {
  min-height: 0;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  background: #f0f2f8;
  width: 100%;
  box-sizing: border-box;
}

.capsule-wrap {
  padding: 20rpx 32rpx 14rpx;
  display: flex;
  overflow-x: auto;
  overflow-y: hidden;
  -webkit-overflow-scrolling: touch;
}
.capsule-bar {
  display: inline-flex;
  align-items: center;
  gap: 6rpx;
  min-width: max-content;
  padding: 8rpx;
  background: linear-gradient(180deg, #f8fafc 0%, #eef2f7 100%);
  border: 1rpx solid rgba(148, 163, 184, 0.18);
  border-radius: 100rpx;
  box-shadow: 0 8rpx 20rpx rgba(15, 23, 42, 0.08);
}
.capsule-btn {
  display: flex;
  align-items: center;
  gap: 8rpx;
  padding: 16rpx 28rpx;
  border-radius: 100rpx;
  font-size: 26rpx;
  color: #6b7280;
  white-space: nowrap;
  transition: background 0.2s ease, color 0.2s ease, box-shadow 0.2s ease;
}
.capsule-btn.active {
  background: #fff;
  color: #111827;
  font-weight: 600;
  box-shadow: 0 2rpx 8rpx rgba(0, 0, 0, 0.1), 0 0 0 1rpx rgba(0, 0, 0, 0.04);
}
.capsule-dot {
  min-width: 32rpx;
  height: 32rpx;
  border-radius: 32rpx;
  padding: 0 8rpx;
  font-size: 20rpx;
  font-weight: 700;
  display: flex;
  align-items: center;
  justify-content: center;
  background: #ef4444;
  color: #fff;
}
.capsule-dot.warn { background: #f59e0b; }
.capsule-dot.ok { background: #50c878; }

.filter-bar {
  display: flex;
  align-items: stretch;
  gap: 16rpx;
  padding: 20rpx 32rpx;
  flex-wrap: nowrap;
  box-sizing: border-box;
}
.filter-fields {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
  flex: 1 1 auto;
  gap: 16rpx;
  min-width: 0;
}
.filter-pill {
  display: flex;
  align-items: center;
  padding: 16rpx 20rpx;
  background: #fff;
  border: 2rpx solid #e5e7eb;
  border-radius: 20rpx;
  min-width: 0;
  box-sizing: border-box;
  position: relative;
  z-index: 2;
  min-height: 92rpx;
}
.filter-pill.active {
  border-color: #50c878;
  background: #f0fdf4;
}
.filter-pill.open {
  border-color: #50c878;
  box-shadow: 0 0 0 4rpx rgba(80, 200, 120, 0.12);
}
.pill-inner {
  flex: 1;
  min-width: 0;
}
.pill-label {
  display: block;
  font-size: 20rpx;
  font-weight: 600;
  color: #9ca3af;
  margin-bottom: 2rpx;
}
.filter-pill.active .pill-label { color: #16a34a; }
.pill-value {
  display: block;
  font-size: 26rpx;
  font-weight: 500;
  color: #111827;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.filter-pill.active .pill-value { color: #15803d; }
.pill-arrow {
  font-size: 28rpx;
  color: #d1d5db;
  flex-shrink: 0;
  transform: rotate(90deg);
  transition: transform 0.2s ease, color 0.2s ease;
}
.filter-pill.open .pill-arrow {
  transform: rotate(270deg);
  color: #50c878;
}

.dropdown-menu {
  position: absolute;
  top: calc(100% + 10rpx);
  left: 0;
  right: 0;
  background: #fff;
  border: 2rpx solid #e5e7eb;
  border-radius: 20rpx;
  box-shadow: 0 16rpx 40rpx rgba(15, 23, 42, 0.12);
  overflow: hidden;
  z-index: 20;
}

.dropdown-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16rpx;
  padding: 24rpx 22rpx;
  font-size: 26rpx;
  color: #374151;
  background: #fff;
}

.dropdown-item + .dropdown-item {
  border-top: 1rpx solid #edf2f7;
}

.dropdown-item.selected {
  background: #f0fdf4;
  color: #16a34a;
  font-weight: 600;
}

.dropdown-check {
  color: #22c55e;
  font-weight: 700;
  flex-shrink: 0;
}

.filter-actions {
  display: flex;
  flex-direction: column;
  gap: 12rpx;
  flex-shrink: 0;
  width: 128rpx;
  justify-content: stretch;
}
.filter-btn {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 16rpx 24rpx;
  border-radius: 18rpx;
  font-size: 24rpx;
  font-weight: 600;
  box-sizing: border-box;
  min-height: 0;
}
.filter-btn.apply {
  background: #50c878;
  color: #fff;
  box-shadow: 0 4rpx 16rpx rgba(80, 200, 120, 0.3);
}
.filter-btn.apply.active { background: #22c55e; }
.list-area {
  flex: 1;
  min-height: 0;
  padding: 12rpx 32rpx 32rpx;
  box-sizing: border-box;
}

.block-label-row {
  display: flex;
  align-items: center;
  gap: 12rpx;
  margin-bottom: 20rpx;
}
.block-label {
  font-size: 22rpx;
  font-weight: 600;
  color: #9ca3af;
  letter-spacing: 0.04em;
}
.count-badge {
  background: #50c878;
  color: #fff;
  font-size: 20rpx;
  min-width: 34rpx;
  height: 34rpx;
  border-radius: 34rpx;
  padding: 0 10rpx;
  display: flex;
  align-items: center;
  justify-content: center;
}
.refresh-btn {
  margin-left: auto;
  font-size: 36rpx;
  color: #9ca3af;
  padding: 4rpx 8rpx;
}

.empty-block {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 12rpx;
  padding: 56rpx 32rpx;
  background: #f9fafb;
  border: 2rpx solid rgba(0, 0, 0, 0.04);
  border-radius: 24rpx;
}
.empty-check {
  font-size: 52rpx;
  color: #34d399;
  opacity: 0.8;
}
.empty-text {
  font-size: 26rpx;
  color: #9ca3af;
}

.msg-item {
  display: flex;
  align-items: center;
  gap: 20rpx;
  padding: 22rpx 24rpx;
  background: #f9fafb;
  border: 2rpx solid rgba(0, 0, 0, 0.04);
  border-radius: 24rpx;
  margin-bottom: 12rpx;
  box-sizing: border-box;
  width: 100%;
}
.msg-item.clickable:active {
  background: rgba(80, 200, 120, 0.06);
  border-color: rgba(80, 200, 120, 0.2);
}
.msg-icon {
  flex-shrink: 0;
  width: 64rpx;
  height: 64rpx;
  border-radius: 18rpx;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 30rpx;
}
.msg-icon.workorder { background: rgba(80, 200, 120, 0.1); }
.msg-icon.anom { background: rgba(239, 68, 68, 0.08); }
.msg-icon.anom.high { background: rgba(239, 68, 68, 0.1); }
.msg-icon.anom.medium { background: rgba(251, 191, 36, 0.08); }
.msg-icon.anom.low { background: rgba(80, 200, 120, 0.08); }

.msg-body {
  flex: 1;
  min-width: 0;
}
.msg-title {
  display: block;
  font-size: 26rpx;
  font-weight: 600;
  color: #111827;
  margin-bottom: 4rpx;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.msg-sub {
  display: block;
  font-size: 22rpx;
  color: #9ca3af;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.msg-time {
  display: block;
  font-size: 20rpx;
  color: #c4c9d4;
  margin-top: 4rpx;
}
.msg-detail {
  display: block;
  font-size: 22rpx;
  color: #6b7280;
  margin-top: 6rpx;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.msg-arrow {
  font-size: 32rpx;
  color: #d1d5db;
  flex-shrink: 0;
}
.msg-tag {
  flex-shrink: 0;
  font-size: 20rpx;
  font-weight: 600;
  padding: 4rpx 16rpx;
  border-radius: 32rpx;
  white-space: nowrap;
}
.msg-tag.pending { background: rgba(80, 200, 120, 0.1); color: #16a34a; }
.msg-tag.tag-high { background: rgba(239, 68, 68, 0.1); color: #dc2626; }
.msg-tag.tag-medium { background: rgba(251, 191, 36, 0.1); color: #d97706; }
.msg-tag.tag-low { background: rgba(80, 200, 120, 0.1); color: #16a34a; }

.dev-high { color: #dc2626; font-weight: 600; }
.dev-medium { color: #d97706; font-weight: 600; }
.dev-low { color: #16a34a; font-weight: 600; }
.dev-critical { color: #dc2626; font-weight: 700; }
.dev-warning { color: #d97706; font-weight: 700; }

.prediction-card {
  display: flex;
  align-items: center;
  gap: 16rpx;
  padding: 24rpx 26rpx;
  background: #f9fafb;
  border: 2rpx solid rgba(0, 0, 0, 0.05);
  border-radius: 24rpx;
  margin-bottom: 14rpx;
  box-sizing: border-box;
  width: 100%;
}
.prediction-card.prediction-critical { border-left: 6rpx solid #ef4444; background: rgba(239, 68, 68, 0.02); }
.prediction-card.prediction-warning { border-left: 6rpx solid #f59e0b; background: rgba(245, 158, 11, 0.02); }

.prediction-card-left {
  display: flex;
  align-items: flex-start;
  gap: 16rpx;
  flex: 1;
  min-width: 0;
}
.prediction-icon {
  flex-shrink: 0;
  width: 64rpx;
  height: 64rpx;
  border-radius: 18rpx;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 28rpx;
}
.prediction-icon.critical { background: rgba(239, 68, 68, 0.1); }
.prediction-icon.warning { background: rgba(245, 158, 11, 0.1); }

.prediction-info {
  flex: 1;
  min-width: 0;
}
.prediction-header {
  display: flex;
  align-items: center;
  gap: 12rpx;
  margin-bottom: 6rpx;
}
.prediction-name { font-size: 26rpx; font-weight: 600; color: #111827; }
.prediction-mode-badge {
  font-size: 20rpx;
  font-weight: 500;
  padding: 2rpx 14rpx;
  border-radius: 20rpx;
  background: rgba(59, 108, 244, 0.1);
  color: #3b6cf4;
}
.prediction-desc {
  font-size: 24rpx;
  color: #374151;
  margin-bottom: 6rpx;
  overflow: hidden;
  text-overflow: ellipsis;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
}
.prediction-meta {
  font-size: 22rpx;
  color: #9ca3af;
  line-height: 1.5;
}
.prediction-deviation {
  display: block;
  margin-top: 6rpx;
  font-size: 22rpx;
}
.prediction-level-tag {
  flex-shrink: 0;
  font-size: 20rpx;
  font-weight: 700;
  padding: 6rpx 20rpx;
  border-radius: 32rpx;
  white-space: nowrap;
}
.prediction-level-tag.critical { background: rgba(239, 68, 68, 0.1); color: #dc2626; }
.prediction-level-tag.warning { background: rgba(245, 158, 11, 0.1); color: #d97706; }

@media screen and (max-width: 430px) {
  .capsule-btn {
    padding: 16rpx 24rpx;
    font-size: 24rpx;
  }

  .filter-bar {
    gap: 12rpx;
    padding: 18rpx 24rpx;
  }

  .filter-fields {
    width: auto;
    grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
    gap: 12rpx;
  }

  .filter-pill {
    width: auto;
    min-height: 84rpx;
    padding: 14rpx 16rpx;
  }

  .dropdown-menu {
    top: calc(100% + 8rpx);
  }

  .filter-actions {
    width: 120rpx;
  }

  .filter-btn {
    text-align: center;
    padding: 14rpx 16rpx;
    font-size: 22rpx;
  }

  .msg-item {
    align-items: flex-start;
    flex-wrap: wrap;
  }

  .msg-body {
    min-width: 0;
    width: calc(100% - 84rpx);
  }

  .msg-tag {
    margin-left: 84rpx;
  }

  .msg-arrow {
    margin-left: auto;
    margin-top: 6rpx;
  }

  .prediction-card {
    align-items: flex-start;
    flex-wrap: wrap;
  }

  .prediction-card-left {
    width: 100%;
  }

  .prediction-level-tag {
    margin-left: 80rpx;
  }
}

.skeleton { animation: shimmer 1.5s infinite; }
.sk-line {
  height: 28rpx;
  background: #f0f0f0;
  border-radius: 6rpx;
  margin-bottom: 16rpx;
}
.sk-line.short { width: 60%; }

@keyframes shimmer {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.5; }
}
</style>
