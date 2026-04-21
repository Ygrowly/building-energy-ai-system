<template>
  <view class="page">
    <scroll-view scroll-y class="page-scroll" :show-scrollbar="false">
      <view class="hero-stage">
        <view class="top-hero" :style="{ paddingTop: `${statusBarHeight + 28}px` }">
          <view class="hero-head hero-head-top">
            <view class="hero-avatar">
              <image v-if="avatarUrl" class="hero-avatar-img" :src="avatarUrl" mode="aspectFill" />
              <text v-else>{{ avatarChar }}</text>
            </view>
            <view class="hero-user">
              <text class="hero-label">当前值班</text>
              <text class="hero-name">{{ userName }}</text>
            </view>
          </view>
        </view>

        <view class="hero-card">
          <view class="portal-grid">
            <view class="portal-main" @click="goToHall">
              <view class="portal-header">
                <text class="portal-title">工单大厅</text>
                <view class="portal-arrow orange">
                  <view class="arrow-icon"></view>
                </view>
              </view>
              <text class="portal-subtitle">待协同、待接管和我的大厅申请都在这里集中处理</text>
              <image
                class="portal-figure-img"
                src="/static/images/worker-hero.png"
                mode="widthFix"
              />
            </view>

            <view class="portal-side">
              <view class="portal-mini portal-blue" @click="goTo('/pages/worker/active/index')">
              <view class="portal-mini-copy">
                <view class="portal-header">
                  <text class="portal-title small">执行列表</text>
                  <view class="portal-arrow blue">
                    <view class="arrow-icon"></view>
                  </view>
                </view>
                  <text class="portal-subtitle">{{ todoSummaryText }}</text>
              </view>
                <image
                  class="portal-mini-figure portal-mini-figure-order"
                  src="/static/images/work-order.png"
                  mode="widthFix"
                />
              </view>
              <view class="portal-mini portal-green" @click="goTo('/pages/worker/history/index')">
                <view class="portal-mini-copy">
                  <view class="portal-header">
                    <text class="portal-title small">消息中心</text>
                    <view class="portal-arrow green">
                      <view class="arrow-icon"></view>
                    </view>
                  </view>
                  <text class="portal-subtitle">您有{{ unreadCount }}条未读消息</text>
                </view>
                <image
                  class="portal-mini-figure portal-mini-figure-message"
                  src="/static/images/message.png"
                  mode="widthFix"
                />
              </view>
            </view>
          </view>
        </view>
      </view>

      <view class="workspace-lower">
        <view class="focus-overview-card">
          <view class="summary-card">
            <view class="summary-item">
              <text class="summary-num" :class="{ loading: isInitialLoading }">{{ displayStat(stats.inProgress) }}</text>
              <text class="summary-label">进行中</text>
            </view>
            <view class="summary-item">
              <text class="summary-num" :class="{ loading: isInitialLoading }">{{ displayStat(stats.pendingStart) }}</text>
              <text class="summary-label">待开始</text>
            </view>
            <view class="summary-item">
              <text class="summary-num" :class="{ loading: isInitialLoading }">{{ displayStat(stats.todayCount) }}</text>
              <text class="summary-label">今日工单</text>
            </view>
            <view class="summary-item">
              <text class="summary-num" :class="{ loading: isInitialLoading }">{{ displayStat(stats.overdueCount) }}</text>
              <text class="summary-label">逾期工单</text>
            </view>
          </view>

          <view class="focus-panel">
            <view class="section-head section-head-compact">
              <text class="section-title">优先处理</text>
              <text class="section-link" @click="goTo('/pages/worker/active/index')">查看我的工单</text>
            </view>

            <view v-if="featuredOrder" class="feature-card" @click="openFeatureOrder">
              <view class="feature-top-row">
                <view class="feature-badges">
                  <text class="feature-tag warn">{{ featureStatusLabel }}</text>
                  <text class="feature-tag plain">{{ featureDateLabel }}</text>
                </view>
                <text class="feature-action">{{ featuredOrder.actionLabel }}</text>
              </view>
              <view v-if="featureAnomalyType" class="feature-type-row">
                <text class="feature-type-value">{{ featureAnomalyType }}</text>
              </view>
              <text
                v-if="featureTitleText"
                class="feature-title"
                :class="{ 'with-type': featureAnomalyType }"
              >{{ featureTitleText }}</text>
              <view class="feature-location-row">
                <view class="feature-location-pin">
                  <view class="feature-location-pin-core"></view>
                </view>
                <text class="feature-location">{{ featureLocationText }}</text>
              </view>
              <view class="feature-meta">
                <view class="feature-meta-row">
                  <text class="feature-meta-label">工单编号</text>
                  <text class="feature-meta-value">{{ featuredOrder.ticketId || '--' }}</text>
                </view>
                <view class="feature-meta-row">
                  <text class="feature-meta-label">工单时间</text>
                  <text class="feature-meta-value">{{ featuredOrder.time || '--' }}</text>
                </view>
              </view>
            </view>

            <view v-else-if="isInitialLoading" class="feature-empty feature-loading">
              <text class="feature-empty-icon loading">…</text>
              <text class="feature-empty-text">工单加载中</text>
            </view>

            <view v-else class="feature-empty">
              <text class="feature-empty-icon">工</text>
              <text class="feature-empty-text">当前没有需要优先跟进的工单</text>
            </view>
          </view>
        </view>

        <view class="section last-section">
          <view class="section-head">
            <text class="section-title">服务提示</text>
            <text class="section-link" @click="goTo('/pages/worker/profile/about')">更多说明</text>
          </view>

          <view class="tips-list">
            <view v-for="tip in tips" :key="tip.title" class="tip-card">
              <text class="tip-title">{{ tip.title }}</text>
              <text class="tip-desc">{{ tip.desc }}</text>
            </view>
          </view>
        </view>
      </view>

      <view class="worker-tabbar-spacer" />
    </scroll-view>

    <TabBar :tabs="WORKER_TABS" current="workspace" theme="worker" />
  </view>
</template>

<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { onShow } from '@dcloudio/uni-app'
import TabBar from '../../../components/TabBar.vue'
import { incidentApi, type Incident } from '../../../api/incident'
import { workOrderApi, type DispatchHallEntry } from '../../../api/workorder'
import { useRouteGuard } from '../../../utils/route-guard'
import { WORKER_ROLES } from '../../../constants/roles'
import { WORKER_TABS } from '../../../constants/tabs'
import { getCache, setCache } from '../../../utils/cache'
import { useAuthStore } from '../../../stores/auth'
import { useNotificationStore } from '../../../stores/notification'
import { getWorkerDashboardStats, getWorkerFeatureOrder, isWorkerAiReadyIncident } from '../../../utils/worker-ui'
import { subscribeWorkerOrdersUpdated } from '../../../utils/worker-sync'
import { formatBuildingLabel, formatDeviceLabel, formatSystemLabel, formatWorkOrderTitle } from '../../../utils/display'
import { formatDateTime } from '../../../utils/format'
import { getStoredAvatarUrl } from '../../../utils/avatar'

useRouteGuard(WORKER_ROLES)

const authStore = useAuthStore()
const notificationStore = useNotificationStore()
const incidents = ref<Incident[]>([])
const supportEntries = ref<DispatchHallEntry[]>([])
const hallEntries = ref<DispatchHallEntry[]>([])
const loading = ref(false)
const statusBarHeight = ref(20)
const hasLoadedOnce = ref(false)
const avatarUrl = ref('')
let unsubscribeWorkerSync: (() => void) | null = null
const isInitialLoading = computed(() => (
  loading.value
  && !hasLoadedOnce.value
  && !incidents.value.length
  && !supportEntries.value.length
  && !hallEntries.value.length
))

const userName = computed(() => authStore.user?.username || '维修师傅')
const avatarChar = computed(() => userName.value.slice(0, 1).toUpperCase())
const stats = computed(() => {
  const incidentStats = getWorkerDashboardStats(incidents.value)
  const pendingSupport = supportEntries.value.filter(entry => entry.status === 'assigned').length
  const activeSupport = supportEntries.value.filter(entry => entry.status === 'accepted').length
  return {
    ...incidentStats,
    pendingStart: incidentStats.pendingStart + pendingSupport,
    inProgress: incidentStats.inProgress + activeSupport,
    todayCount: incidentStats.todayCount + supportEntries.value.length,
  }
})
const todoCount = computed(() => stats.value.inProgress + stats.value.pendingStart)
const todoSummaryText = computed(() => (
  isInitialLoading.value
    ? '正在同步正式任务...'
    : `共计${todoCount.value}项正式任务待推进`
))
const featuredOrder = computed(() => {
  const supportTarget = supportEntries.value[0]
  if (supportTarget) {
    const relatedIncident = incidents.value.find(item => item.incident_id === supportTarget.incident_id)
    const workerAiReady = supportTarget.status === 'accepted'
    return {
      ticketId: supportTarget.work_order?.ticket_id || supportTarget.id,
      hallEntryId: supportTarget.id,
      incidentId: supportTarget.incident_id || undefined,
      dispatchId: supportTarget.source_dispatch_id || supportTarget.source_dispatch?.id || undefined,
      anomalyType: relatedIncident ? formatSystemLabel(relatedIncident.rule_triggered) : '',
      title: formatWorkOrderTitle({
        summaryText: supportTarget.support_reason || supportTarget.reason,
        issueDescription: supportTarget.work_order?.issue_description,
        buildingId: supportTarget.work_order?.building_id,
      }) || '协同任务待处理',
      building: formatBuildingLabel(supportTarget.work_order?.building_id),
      location: formatDeviceLabel(supportTarget.work_order?.device_id, supportTarget.work_order?.building_id) || '协同现场待确认',
      time: formatDateTime(supportTarget.assigned_at || supportTarget.created_at),
      timeTag: supportTarget.status === 'assigned' ? '待确认协同' : '协同处理中',
      priorityLabel: '协同任务',
      actionLabel: workerAiReady ? '进入维小修' : '响应协同',
      workerAiReady,
      kind: 'support' as const,
    }
  }
  const incidentTarget = getWorkerFeatureOrder(incidents.value)
  return incidentTarget ? { ...incidentTarget, kind: 'incident' as const } : null
})
const unreadCount = computed(() => notificationStore.unreadCount)
const featureStatusLabel = computed(() => {
  const order = featuredOrder.value
  if (!order) return ''
  if (order.timeTag === '已超时') return '逾期'
  if (order.kind === 'support') return '协同'
  return order.priorityLabel === '普通工单' ? '待处理' : order.priorityLabel
})
const featureDateLabel = computed(() => formatFeatureDateTag(featuredOrder.value?.time))
const featureAnomalyType = computed(() => featuredOrder.value?.anomalyType || '')
const featureTitleText = computed(() => {
  const order = featuredOrder.value
  if (!order) return ''
  const title = (order.title || '').trim()
  const anomalyType = featureAnomalyType.value.trim()
  if (!title) return ''
  return title === anomalyType ? '' : title
})
const featureLocationText = computed(() => {
  const order = featuredOrder.value
  if (!order) return ''
  return buildFeatureLocationText(order.building, order.location)
})

const tips = [
  { title: '到场前确认现场信息', desc: '优先核对建筑、设备与建议措施，减少二次往返。' },
  { title: '处理后及时提交备注', desc: '记录维修动作和异常原因，方便后续复盘与追踪。' },
  { title: '超时工单优先闭环', desc: '带有超时标记的工单会持续推送提醒，建议优先处理。' },
]

function displayStat(value: number) {
  return isInitialLoading.value ? '...' : String(value)
}

function buildFeatureLocationText(building?: string | null, location?: string | null) {
  const buildingText = (building || '').trim()
  const locationText = (location || '').trim()
  if (buildingText && locationText) {
    if (locationText.includes(buildingText)) return locationText
    return `${buildingText} ${locationText}`
  }
  return locationText || buildingText || '现场位置待确认'
}

function formatFeatureDateTag(value?: string | null) {
  if (!value || value === '--') return '时间待定'
  const dateText = value.slice(0, 10)
  return /^\d{4}-\d{2}-\d{2}$/.test(dateText) ? dateText.replace(/-/g, '/') : value
}

function loadAvatar() {
  avatarUrl.value = getStoredAvatarUrl(authStore.user?.id)
}

async function loadData() {
  const cached = getCache<Incident[]>('worker_workspace')
  const supportCached = getCache<DispatchHallEntry[]>('worker_workspace_support')
  const hallCached = getCache<DispatchHallEntry[]>('worker_shared_hall')
  if (cached) incidents.value = cached
  if (supportCached) supportEntries.value = supportCached
  if (hallCached) hallEntries.value = hallCached
  loading.value = !cached && !supportCached && !hallCached

  try {
    const [incidentResult, supportResult, hallResult] = await Promise.allSettled([
      incidentApi.list({
        workflow_status: 'dispatched,completed,closed,false_alarm,escalated',
        page: 1,
        page_size: 40,
      }),
      workOrderApi.listDispatchHallEntries({
        status: 'assigned,accepted',
        entry_type: 'support_request',
        include_applications: true,
        page: 1,
        page_size: 20,
      }),
      workOrderApi.listDispatchHallEntries({
        status: 'open',
        entry_type: 'support_request,takeover_candidate',
        include_applications: true,
        page: 1,
        page_size: 20,
      }),
    ])
    if (incidentResult.status === 'fulfilled') {
      incidents.value = incidentResult.value.incidents
      setCache('worker_workspace', incidentResult.value.incidents)
      hasLoadedOnce.value = true
    }
    if (supportResult.status === 'fulfilled') {
      supportEntries.value = supportResult.value.hall_entries
      setCache('worker_workspace_support', supportResult.value.hall_entries)
      hasLoadedOnce.value = true
    }
    if (hallResult.status === 'fulfilled') {
      hallEntries.value = hallResult.value.hall_entries
      setCache('worker_shared_hall', hallResult.value.hall_entries)
      hasLoadedOnce.value = true
    }
    if (incidentResult.status === 'rejected' && supportResult.status === 'rejected' && hallResult.status === 'rejected') {
      throw new Error('load failed')
    }
  } catch {
    if (!incidents.value.length && !supportEntries.value.length && !hallEntries.value.length) {
      uni.showToast({ title: '工单数据加载失败', icon: 'none' })
    }
  } finally {
    loading.value = false
  }
}

function buildWorkerAiUrl(params: {
  ticketId: string
  incidentId?: string
  dispatchId?: string
  hallEntryId?: string
}) {
  const query = [
    `ticket_id=${encodeURIComponent(params.ticketId)}`,
    params.incidentId ? `incident_id=${encodeURIComponent(params.incidentId)}` : '',
    params.hallEntryId ? `hall_entry_id=${encodeURIComponent(params.hallEntryId)}` : '',
    params.dispatchId ? `dispatch_id=${encodeURIComponent(params.dispatchId)}` : '',
  ].filter(Boolean).join('&')
  return `/pages/worker/ai-workorder/index?${query}`
}

function buildWorkOrderDetailUrl(params: {
  ticketId: string
  incidentId?: string
  dispatchId?: string
  hallEntryId?: string
}) {
  const query = [
    params.hallEntryId ? `hall_entry_id=${encodeURIComponent(params.hallEntryId)}` : '',
    params.incidentId ? `incident_id=${encodeURIComponent(params.incidentId)}` : '',
    `ticket_id=${encodeURIComponent(params.ticketId)}`,
    params.dispatchId ? `dispatch_id=${encodeURIComponent(params.dispatchId)}` : '',
  ].filter(Boolean).join('&')
  return `/pages/worker/workorder-detail/index?${query}`
}

function openFeatureOrder() {
  if (!featuredOrder.value) return
  if (featuredOrder.value.kind === 'support') {
    const target = supportEntries.value.find(item => item.id === featuredOrder.value?.hallEntryId)
    const ticketId = target?.work_order?.ticket_id || featuredOrder.value.ticketId
    const dispatchId = target?.source_dispatch_id || target?.source_dispatch?.id || featuredOrder.value.dispatchId
    const params = {
      ticketId,
      incidentId: target?.incident_id || featuredOrder.value.incidentId,
      dispatchId,
      hallEntryId: featuredOrder.value.hallEntryId,
    }
    uni.navigateTo({
      url: featuredOrder.value.workerAiReady ? buildWorkerAiUrl(params) : buildWorkOrderDetailUrl(params),
    })
    return
  }
  const target = incidents.value.find(item => (item.current_work_order?.ticket_id || item.incident_id) === featuredOrder.value?.ticketId)
  if (!target?.current_work_order?.ticket_id) return
  const dispatchId = target.current_dispatch?.id || featuredOrder.value.dispatchId || target.current_work_order.dispatch_id
  const params = {
    ticketId: target.current_work_order.ticket_id,
    incidentId: target.incident_id,
    dispatchId,
  }
  uni.navigateTo({
    url: isWorkerAiReadyIncident(target) ? buildWorkerAiUrl(params) : buildWorkOrderDetailUrl(params),
  })
}

function goTo(url: string) {
  if (url.includes('/profile/')) {
    uni.navigateTo({ url })
    return
  }
  uni.reLaunch({ url })
}

function goToHall() {
  uni.navigateTo({ url: '/pages/worker/hall/index' })
}

onMounted(() => {
  try {
    const info = uni.getSystemInfoSync()
    statusBarHeight.value = info.statusBarHeight ?? 20
  } catch {
    statusBarHeight.value = 20
  }
  loadAvatar()
  unsubscribeWorkerSync = subscribeWorkerOrdersUpdated(async () => {
    await loadData()
  })
  void loadData()
})

onShow(() => {
  loadAvatar()
  if (!hasLoadedOnce.value) return
  void loadData()
})

onUnmounted(() => {
  unsubscribeWorkerSync?.()
  unsubscribeWorkerSync = null
})
</script>

<style lang="scss" scoped>
.page {
  position: relative;
  min-height: 100vh;
  overflow: hidden;
  background: #fff;
}

.page::before {
  content: '';
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  height: 520rpx;
  background:
    radial-gradient(circle at 18% 28%, rgba(255, 255, 255, 0.4), transparent 20%),
    radial-gradient(circle at 84% 18%, rgba(201, 218, 139, 0.34), transparent 22%),
    linear-gradient(180deg, rgba(228, 237, 184, 0.96) 0%, rgba(241, 246, 217, 0.82) 58%, rgba(247, 250, 239, 0) 100%);
  z-index: 0;
}

.hero-stage {
  position: relative;
  margin: 0 0 18rpx;
  padding: 0;
}

.page-scroll {
  position: relative;
  z-index: 1;
  height: 100vh;
  padding: 0 24rpx;
  box-sizing: border-box;
  scrollbar-width: none;
  -ms-overflow-style: none;
}

.worker-tabbar-spacer {
  height: calc(276rpx + env(safe-area-inset-bottom, 0px));
}

.page-scroll::-webkit-scrollbar {
  display: none;
  width: 0;
  height: 0;
}

.top-hero {
  position: relative;
  z-index: 3;
  margin: 0 0 10rpx;
  padding: 0 4rpx 18rpx;
}

.hero-head-top {
  position: relative;
  z-index: 1;
}

.hero-card {
  position: relative;
  z-index: 3;
  padding: 0;
  background: transparent;
  box-shadow: none;
}

.hero-head {
  display: flex;
  align-items: center;
  gap: 18rpx;
}

.hero-head-top {
  padding: 0 6rpx;
  margin-bottom: 6rpx;
}

.hero-avatar {
  width: 78rpx;
  height: 78rpx;
  border-radius: 50%;
  overflow: hidden;
  background: linear-gradient(135deg, #d4e29f, #b3c86d);
  display: flex;
  align-items: center;
  justify-content: center;

  text {
    color: #fff;
    font-size: 34rpx;
    font-weight: 700;
  }
}

.hero-avatar-img {
  width: 100%;
  height: 100%;
}

.hero-user {
  display: flex;
  flex-direction: column;
}

.hero-label {
  font-size: 22rpx;
  color: #73814f;
}

.hero-name {
  margin-top: 6rpx;
  font-size: 32rpx;
  color: #2d2421;
  font-weight: 700;
}

.portal-grid {
  display: grid;
  grid-template-columns: 0.95fr 1.05fr;
  gap: 18rpx;
}

.portal-main,
.portal-mini {
  position: relative;
  overflow: hidden;
  border-radius: 45rpx;
  background: #fff;
  box-shadow: inset 0 0 0 2rpx rgba(228, 237, 184, 0.92);
}

.portal-main {
  min-height: 450rpx;
  padding: 35rpx 35rpx 0;
  display: flex;
  flex-direction: column;
  background:
    radial-gradient(circle at 14% 92%, rgba(255, 255, 255, 0.98), rgba(255, 255, 255, 0.92) 18%, rgba(255, 255, 255, 0) 42%),
    radial-gradient(circle at 82% 88%, rgba(228, 237, 184, 0.78), transparent 30%),
    linear-gradient(180deg, #fbfdf7 0%, #f3f8e8 58%, #eef5df 100%);
}

.portal-side {
  display: grid;
  gap: 18rpx;
}

.portal-mini {
  min-height: 126rpx;
  padding: 35rpx 35rpx;
}

.portal-mini-copy {
  position: relative;
  z-index: 1;
  width: 100%;
  padding-right: 78rpx;
  box-sizing: border-box;
}

.portal-blue {
  background: linear-gradient(180deg, #fbfdff 0%, #eef6ff 100%);
}

.portal-green {
  background: linear-gradient(180deg, #fafffd 0%, #effcf7 100%);
}

.portal-header {
  position: relative;
  z-index: 1;
  display: flex;
  align-items: center;
  gap: 22rpx;
}

.portal-mini .portal-header {
  justify-content: space-between;
  gap: 12rpx;
}

.portal-title {
  display: block;
  color: #2a2522;
  font-size: 40rpx;
  font-weight: 900;
  letter-spacing: 1rpx;
  font-family: 'PingFang SC', 'Microsoft YaHei', sans-serif;
}

.portal-title.small {
  font-size: 38rpx;
  font-weight: 900;
  font-family: 'PingFang SC', 'Microsoft YaHei', sans-serif;
  flex: 1;
  min-width: 0;
  white-space: nowrap;
}

.portal-arrow {
  width: 35rpx;
  height: 35rpx;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.portal-arrow.orange {
  background: linear-gradient(135deg, #fab82a, #f7b424);
}

.portal-arrow.blue {
  background: linear-gradient(135deg, #5fa8ff, #78cbff);
}

.portal-arrow.green {
  background: linear-gradient(135deg, #59c97a, #3dbd60);
}

.arrow-icon {
  width: 12rpx;
  height: 12rpx;
  border-top: 4rpx solid #fff;
  border-right: 4rpx solid #fff;
  box-sizing: border-box;
  transform: translateX(-1rpx) rotate(45deg);
}

.portal-subtitle {
  position: relative;
  z-index: 1;
  display: block;
  margin-top: 8rpx;
  color: #6d7c49;
  font-size: 24rpx;
  line-height: 1.45;
}

.portal-figure-img {
  position: absolute;
  right: 0;
  bottom: 0;
  width: 95%;
  display: block;
  pointer-events: none;
  transform: translateY(4.2%);
}

.portal-mini-figure {
  position: absolute;
  right: -10rpx;
  bottom: -26rpx;
  display: block;
  pointer-events: none;
  z-index: 0;
}

.portal-mini-figure-order {
  width: 43%;
  min-width: 112rpx;
  max-width: 168rpx;
  right: -24rpx;
  bottom: -28rpx;
  transform: rotate(8deg);
}

.portal-mini-figure-message {
  width: 50%;
  min-width: 132rpx;
  max-width: 196rpx;
  right: -24rpx;
  bottom: -24rpx;
}

.workspace-lower {
  position: relative;
  z-index: 1;
  padding: 0 0 12rpx;
  box-sizing: border-box;
  background: transparent;
}

.workspace-lower .focus-overview-card {
  margin-top: 16rpx;
}

.focus-overview-card {
  margin-top: 22rpx;
  padding: 0 24rpx 26rpx;
  border-radius: 34rpx;
  background: rgba(255, 255, 255, 0.97);
  border: 2rpx solid rgba(228, 237, 184, 0.95);
  box-shadow:
    0 18rpx 42rpx rgba(181, 196, 118, 0.14),
    0 4rpx 12rpx rgba(228, 237, 184, 0.2);
}

.summary-card {
  padding: 28rpx 0 24rpx;
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  border-bottom: 2rpx solid rgba(234, 239, 213, 0.9);
}

.summary-item {
  display: flex;
  flex-direction: column;
  align-items: center;
}

.summary-num {
  font-size: 56rpx;
  line-height: 1;
  color: #2c2624;
  font-weight: 700;
}

.summary-num.loading,
.feature-empty-icon.loading {
  color: #94a06f;
  letter-spacing: 4rpx;
}

.summary-label {
  margin-top: 14rpx;
  font-size: 24rpx;
  color: #8d8e7d;
}

.focus-panel {
  padding-top: 24rpx;
}

.section {
  margin-top: 26rpx;
}

.section-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 18rpx;
  padding: 0 6rpx;
}

.section-head-compact {
  padding: 0;
  margin-bottom: 20rpx;
}

.section-title {
  font-size: 34rpx;
  color: #2b2421;
  font-weight: 700;
}

.section-link {
  font-size: 24rpx;
  color: #8b8c76;
}

.feature-card,
.feature-empty,
.tip-card {
  background: rgba(255, 255, 255, 0.96);
  border-radius: 28rpx;
  box-shadow: 0 12rpx 34rpx rgba(181, 196, 118, 0.08);
}

.feature-card {
  position: relative;
  padding: 28rpx 26rpx 28rpx 32rpx;
  border-radius: 26rpx;
  background: linear-gradient(180deg, #fff8f4 0%, #fffdfc 100%);
  box-shadow: none;
  border: 2rpx solid rgba(255, 154, 122, 0.18);
}

.feature-card::before {
  content: '';
  position: absolute;
  left: 0;
  top: 22rpx;
  bottom: 22rpx;
  width: 10rpx;
  border-radius: 999rpx;
  background: linear-gradient(180deg, #ffae8f 0%, #ff7f5f 100%);
}

.feature-top-row {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 18rpx;
}

.feature-badges {
  display: flex;
  align-items: center;
  gap: 12rpx;
  flex-wrap: wrap;
  min-width: 0;
}

.feature-tag {
  padding: 8rpx 14rpx;
  border-radius: 14rpx;
  font-size: 22rpx;
}

.feature-tag.warn {
  color: #ff7c52;
  background: #fff0ea;
}

.feature-tag.plain {
  color: #c68767;
  background: #fff;
  border: 2rpx solid rgba(255, 166, 134, 0.24);
}

.feature-action {
  flex-shrink: 0;
  padding: 12rpx 22rpx;
  border-radius: 20rpx;
  background: linear-gradient(135deg, #ffa27f, #ff8e67);
  color: #fff;
  font-size: 24rpx;
  line-height: 1;
}

.feature-type-row {
  display: flex;
  align-items: center;
  gap: 12rpx;
  flex-wrap: wrap;
  margin-top: 20rpx;
}

.feature-type-value {
  font-size: 22rpx;
  color: #ff8a64;
  font-weight: 600;
  line-height: 1.35;
}

.feature-title {
  display: -webkit-box;
  margin-top: 20rpx;
  font-size: 34rpx;
  color: #2d2522;
  font-weight: 700;
  line-height: 1.35;
  overflow: hidden;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 2;
}

.feature-title.with-type {
  margin-top: 10rpx;
}

.feature-location-row {
  display: flex;
  align-items: center;
  gap: 14rpx;
  margin-top: 16rpx;
  padding: 14rpx 16rpx;
  border-radius: 18rpx;
  background: linear-gradient(90deg, rgba(255, 145, 108, 0.1) 0%, rgba(255, 145, 108, 0.03) 100%);
}

.feature-location-pin {
  position: relative;
  width: 24rpx;
  height: 24rpx;
  margin-left: 4rpx;
  flex-shrink: 0;
  border: 4rpx solid #ef9f84;
  border-radius: 50% 50% 50% 0;
  box-sizing: border-box;
  transform: rotate(-45deg);
}

.feature-location-pin-core {
  position: absolute;
  top: 5rpx;
  left: 5rpx;
  width: 6rpx;
  height: 6rpx;
  border-radius: 50%;
  background: #ef9f84;
}

.feature-location {
  flex: 1;
  min-width: 0;
  font-size: 24rpx;
  color: #8a7d75;
  line-height: 1.5;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.feature-meta {
  margin-top: 20rpx;
}

.feature-meta-row {
  display: flex;
  align-items: baseline;
  gap: 18rpx;
}

.feature-meta-row + .feature-meta-row {
  margin-top: 12rpx;
}

.feature-meta-label {
  width: 108rpx;
  flex-shrink: 0;
  font-size: 24rpx;
  color: #8d8177;
}

.feature-meta-value {
  flex: 1;
  min-width: 0;
  font-size: 26rpx;
  color: #3d312c;
  font-weight: 600;
  line-height: 1.5;
  word-break: break-all;
}

.feature-empty {
  padding: 60rpx 20rpx;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 18rpx;
  border-radius: 24rpx;
  box-shadow: none;
  background: linear-gradient(180deg, #fffaf6 0%, #fffefe 100%);
  border: 2rpx dashed rgba(255, 162, 127, 0.22);
}

.feature-empty.feature-loading {
  border-style: solid;
  background: linear-gradient(180deg, #f7fbea 0%, #fffefe 100%);
}

.feature-empty-icon {
  width: 92rpx;
  height: 92rpx;
  border-radius: 28rpx;
  background: linear-gradient(135deg, #ffd0bf, #ffb194);
  color: #fff;
  font-size: 40rpx;
  font-weight: 700;
  display: flex;
  align-items: center;
  justify-content: center;
}

.feature-empty-text {
  font-size: 26rpx;
  color: #91827a;
}

.tips-list {
  display: grid;
  gap: 16rpx;
}

.tip-card {
  padding: 22rpx 24rpx;
}

.tip-title {
  display: block;
  font-size: 28rpx;
  color: #2b2522;
  font-weight: 700;
}

.tip-desc {
  display: block;
  margin-top: 10rpx;
  font-size: 23rpx;
  line-height: 1.65;
  color: #79855e;
}

.last-section {
  padding-bottom: 12rpx;
}
</style>
