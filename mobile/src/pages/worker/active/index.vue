<template>
  <view class="page">
    <NavBar title="工单" bg-color="#E4EDB8" text-color="#5f7137">
      <template #right>
        <text class="nav-action" @click="loadData">↻</text>
      </template>
    </NavBar>

    <view class="tab-row">
      <view
        v-for="tab in orderTabs"
        :key="tab.value"
        class="tab-item"
        :class="{ active: activeTab === tab.value }"
        @click="activeTab = tab.value"
      >
        <text class="tab-label">{{ tab.label }}</text>
        <text class="tab-count">{{ tab.count }}</text>
      </view>
    </view>

    <scroll-view scroll-y class="list-area">
      <view v-if="loading && !incidents.length">
        <view v-for="index in 3" :key="index" class="skeleton-card" />
      </view>

      <view
        v-for="incident in filteredIncidents"
        :key="incident.id"
        class="workorder-card"
        @click="openDetail(incident, activeTab === 'completed')"
      >
        <view class="card-head">
          <view class="ticket-row">
            <text class="ticket-id">{{ shortTicket(incident.current_work_order?.ticket_id || incident.incident_id) }}</text>
            <text class="copy-btn" @click.stop="copyTicket(incident.current_work_order?.ticket_id || incident.incident_id)">复制</text>
          </view>
          <text class="status-badge" :class="activeTab">{{ statusText(incident) }}</text>
        </view>

        <text class="card-title">{{ incident.summary_text }}</text>
        <view class="location-row">
          <text class="location-text">{{ buildingText(incident) }} / {{ locationText(incident) }}</text>
          <text class="distance-text">{{ dueText(incident) }}</text>
        </view>

        <view class="detail-panel">
          <view class="detail-line">
            <text class="detail-label">工单类型</text>
            <text class="detail-value">{{ typeText(incident) }}</text>
          </view>
          <view class="detail-line">
            <text class="detail-label">处理进度</text>
            <text class="detail-value accent">{{ progressText(incident) }}</text>
          </view>
          <view class="detail-line">
            <text class="detail-label">派单时间</text>
            <text class="detail-value">{{ timeText(incident) }}</text>
          </view>
          <view class="detail-line">
            <text class="detail-label">建议措施</text>
            <text class="detail-value multiline">{{ noteText(incident) }}</text>
          </view>
        </view>

        <view class="action-row">
          <view class="ghost-btn" @click.stop="callContact(incident)">联系TA</view>
          <view class="primary-btn" @click.stop="openDetail(incident, activeTab === 'completed')">
            {{ activeTab === 'completed' ? '查看记录' : activeTab === 'pending_start' ? '立即处理' : '继续处理' }}
          </view>
        </view>
      </view>

      <view v-if="!loading && !filteredIncidents.length" class="empty-card">
        <text class="empty-icon">单</text>
        <text class="empty-title">当前分类暂无工单</text>
        <text class="empty-subtitle">新的派单和状态变更会第一时间同步到这里</text>
      </view>
    </scroll-view>

    <TabBar :tabs="WORKER_TABS" current="workorders" theme="worker" />
  </view>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import NavBar from '../../../components/NavBar.vue'
import TabBar from '../../../components/TabBar.vue'
import { incidentApi, type Incident } from '../../../api/incident'
import { useRouteGuard } from '../../../utils/route-guard'
import { WORKER_ROLES } from '../../../constants/roles'
import { WORKER_TABS } from '../../../constants/tabs'
import { DISPATCH_EXECUTION_STATUS_LABEL } from '../../../constants/status'
import { formatDateTime } from '../../../utils/format'
import { formatBuildingLabel, formatDeviceLabel, formatRuleLabel, formatSystemLabel, sanitizeDisplayText } from '../../../utils/display'
import { getCache, setCache } from '../../../utils/cache'
import {
  getWorkerDashboardStats,
  getWorkerExecutionStatus,
  getWorkerOrderBucket,
  isWorkerOverdueIncident,
} from '../../../utils/worker-ui'

useRouteGuard(WORKER_ROLES)

type OrderTab = 'in_progress' | 'pending_start' | 'completed'

const incidents = ref<Incident[]>([])
const loading = ref(false)
const activeTab = ref<OrderTab>('in_progress')

const stats = computed(() => getWorkerDashboardStats(incidents.value))
const orderTabs = computed(() => [
  { label: '进行中', value: 'in_progress' as const, count: stats.value.inProgress },
  { label: '待开始', value: 'pending_start' as const, count: stats.value.pendingStart },
  { label: '已完成', value: 'completed' as const, count: stats.value.completedCount },
])

const filteredIncidents = computed(() => incidents.value.filter(item => getWorkerOrderBucket(item) === activeTab.value))

async function loadData() {
  const cached = getCache<Incident[]>('worker_workorders')
  if (cached) incidents.value = cached
  loading.value = !cached

  try {
    const res = await incidentApi.list({
      workflow_status: 'dispatched,completed,closed,false_alarm,escalated',
      page: 1,
      page_size: 50,
    })
    incidents.value = res.incidents
    setCache('worker_workorders', res.incidents)
  } catch {
    if (!incidents.value.length) {
      uni.showToast({ title: '工单加载失败', icon: 'none' })
    }
  } finally {
    loading.value = false
  }
}

function shortTicket(ticketId: string) {
  return ticketId.slice(-8)
}

function buildingText(incident: Incident) {
  return formatBuildingLabel(incident.building_id)
}

function locationText(incident: Incident) {
  return formatDeviceLabel(incident.device_id, incident.building_id) || formatSystemLabel(incident.rule_triggered)
}

function typeText(incident: Incident) {
  return formatRuleLabel(incident.rule_triggered)
}

function noteText(incident: Incident) {
  return sanitizeDisplayText(incident.current_work_order?.suggested_action) || '请按标准流程排查并补充处理备注'
}

function timeText(incident: Incident) {
  return formatDateTime(incident.current_work_order?.dispatch_at || incident.created_at)
}

function dueText(incident: Incident) {
  if (isWorkerOverdueIncident(incident)) return '已超时'
  const minutes = incident.current_work_order?.sla_minutes_left
  if (minutes !== null && minutes !== undefined) return `剩余${minutes}分钟`
  return activeTab.value === 'completed' ? '已闭环' : '按时'
}

function progressText(incident: Incident) {
  const executionStatus = getWorkerExecutionStatus(incident)
  return DISPATCH_EXECUTION_STATUS_LABEL[executionStatus] || '处理中'
}

function statusText(incident: Incident) {
  const bucket = getWorkerOrderBucket(incident)
  if (bucket === 'completed') return '已完成'
  if (bucket === 'pending_start') return '待开始'
  return '待完成'
}

function copyTicket(ticketId: string) {
  uni.setClipboardData({ data: ticketId, showToast: true })
}

function callContact(incident: Incident) {
  const phone = incident.current_work_order?.assigned_phone
  if (!phone) {
    uni.showToast({ title: '暂无联系电话', icon: 'none' })
    return
  }
  uni.makePhoneCall({ phoneNumber: phone })
}

function openDetail(incident: Incident, readonly = false) {
  const ticketId = incident.current_work_order?.ticket_id
  if (!ticketId) return
  const readonlyQuery = readonly ? '&readonly=1' : ''
  uni.navigateTo({
    url: `/pages/worker/workorder-detail/index?incident_id=${incident.incident_id}&ticket_id=${ticketId}${readonlyQuery}`,
  })
}

onMounted(loadData)
</script>

<style lang="scss" scoped>
.page {
  min-height: 100vh;
  background:
    radial-gradient(circle at top, rgba(174, 203, 150, 0.22), transparent 36%),
    linear-gradient(180deg, #f5f8ef 0%, #fbfdf8 100%);
}

.nav-action {
  font-size: 36rpx;
  color: #5f7137;
}

.tab-row {
  display: flex;
  padding: 12rpx 24rpx 0;
  background: #f7faef;
}

.tab-item {
  flex: 1;
  padding: 18rpx 0 22rpx;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 6rpx;
  color: #2c2724;
  position: relative;
}

.tab-item.active::after {
  content: '';
  position: absolute;
  left: 28%;
  right: 28%;
  bottom: 0;
  height: 8rpx;
  border-radius: 999rpx;
  background: linear-gradient(90deg, #E4EDB8, #b7cc76);
}

.tab-label {
  font-size: 34rpx;
  font-weight: 700;
}

.tab-count {
  font-size: 22rpx;
  color: #808873;
}

.list-area {
  height: calc(100vh - 290rpx);
  padding: 22rpx 24rpx calc(168rpx + env(safe-area-inset-bottom, 0px));
  box-sizing: border-box;
}

.workorder-card,
.empty-card,
.skeleton-card {
  background: rgba(255, 255, 255, 0.98);
  border-radius: 30rpx;
  box-shadow: 0 14rpx 36rpx rgba(181, 196, 118, 0.08);
}

.workorder-card {
  padding: 26rpx;
  margin-bottom: 20rpx;
}

.card-head,
.ticket-row,
.location-row,
.detail-line,
.action-row {
  display: flex;
  align-items: center;
}

.card-head,
.location-row,
.detail-line {
  justify-content: space-between;
}

.ticket-row {
  gap: 12rpx;
}

.ticket-id {
  font-size: 25rpx;
  color: #8a7e79;
}

.copy-btn {
  font-size: 22rpx;
  color: #b5aba7;
}

.status-badge {
  padding: 8rpx 18rpx;
  border-radius: 18rpx;
  font-size: 22rpx;
}

.status-badge.in_progress {
  color: #73854a;
  background: #f2f6df;
}

.status-badge.pending_start {
  color: #f6a726;
  background: #fff7e7;
}

.status-badge.completed {
  color: #67a381;
  background: #edf8f1;
}

.card-title {
  display: block;
  margin-top: 22rpx;
  font-size: 40rpx;
  line-height: 1.3;
  color: #2c2522;
  font-weight: 700;
}

.location-row {
  margin-top: 18rpx;
}

.location-text,
.distance-text {
  font-size: 24rpx;
}

.location-text {
  color: #8b7a74;
  flex: 1;
  padding-right: 12rpx;
}

.distance-text {
  color: #73854a;
}

.detail-panel {
  margin-top: 20rpx;
  padding: 18rpx 20rpx;
  border-radius: 22rpx;
  background: linear-gradient(180deg, #f8faef 0%, #f2f6e2 100%);
}

.detail-line {
  gap: 18rpx;
  padding: 10rpx 0;
}

.detail-label {
  width: 118rpx;
  font-size: 24rpx;
  color: #818976;
  flex-shrink: 0;
}

.detail-value {
  flex: 1;
  text-align: left;
  font-size: 25rpx;
  line-height: 1.55;
  color: #403834;
}

.detail-value.accent {
  color: #73854a;
}

.detail-value.multiline {
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.action-row {
  gap: 16rpx;
  margin-top: 24rpx;
}

.ghost-btn,
.primary-btn {
  flex: 1;
  height: 82rpx;
  border-radius: 22rpx;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 28rpx;
  font-weight: 600;
}

.ghost-btn {
  color: #73854a;
  border: 2rpx solid rgba(201, 218, 139, 0.88);
  background: #fff;
}

.primary-btn {
  color: #fff;
  background: linear-gradient(135deg, #d6e29f, #b5c875);
}

.empty-card {
  padding: 90rpx 26rpx;
  display: flex;
  flex-direction: column;
  align-items: center;
}

.empty-icon {
  width: 94rpx;
  height: 94rpx;
  border-radius: 26rpx;
  background: linear-gradient(135deg, #E4EDB8, #c2d58a);
  color: #fff;
  font-size: 38rpx;
  font-weight: 700;
  display: flex;
  align-items: center;
  justify-content: center;
}

.empty-title {
  margin-top: 20rpx;
  font-size: 30rpx;
  font-weight: 700;
  color: #2f2825;
}

.empty-subtitle {
  margin-top: 10rpx;
  font-size: 24rpx;
  line-height: 1.6;
  color: #818976;
  text-align: center;
}

.skeleton-card {
  height: 340rpx;
  margin-bottom: 20rpx;
  background: linear-gradient(90deg, rgba(245, 248, 231, 0.94), rgba(228, 237, 184, 1), rgba(245, 248, 231, 0.94));
}
</style>
