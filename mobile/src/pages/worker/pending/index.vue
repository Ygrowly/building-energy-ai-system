<template>
  <view class="page">
    <scroll-view scroll-y class="page-scroll" :show-scrollbar="false">
      <view class="hero-stage">
        <view class="top-hero" :style="{ paddingTop: `${statusBarHeight + 28}px` }">
          <view class="hero-head hero-head-top">
            <view class="hero-avatar">
              <text>{{ avatarChar }}</text>
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
              <view class="portal-metrics">
                <view class="portal-metric">
                  <text class="portal-metric-num">{{ hallStats.supportCount }}</text>
                  <text class="portal-metric-label">待协同</text>
                </view>
                <view class="portal-metric">
                  <text class="portal-metric-num">{{ hallStats.takeoverCount }}</text>
                  <text class="portal-metric-label">待接管</text>
                </view>
                <view class="portal-metric">
                  <text class="portal-metric-num">{{ hallStats.appliedCount }}</text>
                  <text class="portal-metric-label">我的申请</text>
                </view>
              </view>
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
                  <text class="portal-subtitle">共计{{ todoCount }}项正式任务待推进</text>
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
              <text class="summary-num">{{ stats.inProgress }}</text>
              <text class="summary-label">进行中</text>
            </view>
            <view class="summary-item">
              <text class="summary-num">{{ stats.pendingStart }}</text>
              <text class="summary-label">待开始</text>
            </view>
            <view class="summary-item">
              <text class="summary-num">{{ stats.todayCount }}</text>
              <text class="summary-label">今日工单</text>
            </view>
            <view class="summary-item">
              <text class="summary-num">{{ stats.overdueCount }}</text>
              <text class="summary-label">逾期工单</text>
            </view>
          </view>

          <view class="focus-panel">
            <view class="section-head section-head-compact">
              <text class="section-title">优先处理</text>
              <text class="section-link" @click="goTo('/pages/worker/active/index')">查看我的工单</text>
            </view>

            <view v-if="featuredOrder" class="feature-card" @click="openFeatureOrder">
              <view class="feature-tag-row">
                <text class="feature-tag warn">{{ featuredOrder.priorityLabel }}</text>
                <text class="feature-tag plain">{{ featuredOrder.timeTag }}</text>
                <text class="feature-action">{{ featuredOrder.actionLabel }}</text>
              </view>
              <text class="feature-title">{{ featuredOrder.title }}</text>
              <text class="feature-location">{{ featuredOrder.building }} · {{ featuredOrder.location }}</text>
              <view class="feature-meta">
                <text>工单编号 {{ shortTicket(featuredOrder.ticketId) }}</text>
                <text>派单时间 {{ featuredOrder.time }}</text>
              </view>
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
import { getWorkerDashboardStats, getWorkerFeatureOrder, getWorkerMessageCards } from '../../../utils/worker-ui'
import { subscribeWorkerOrdersUpdated } from '../../../utils/worker-sync'
import { sanitizeDisplayText, formatBuildingLabel, formatDeviceLabel } from '../../../utils/display'
import { formatDateTime } from '../../../utils/format'

useRouteGuard(WORKER_ROLES)

const authStore = useAuthStore()
const incidents = ref<Incident[]>([])
const supportEntries = ref<DispatchHallEntry[]>([])
const hallEntries = ref<DispatchHallEntry[]>([])
const loading = ref(false)
const statusBarHeight = ref(20)
const hasLoadedOnce = ref(false)
let unsubscribeWorkerSync: (() => void) | null = null

const userName = computed(() => authStore.user?.username || '维修师傅')
const avatarChar = computed(() => userName.value.slice(0, 1).toUpperCase())
const currentUserId = computed(() => authStore.user?.id || '')
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
const hallStats = computed(() => {
  const entries = hallEntries.value
  const appliedCount = entries.filter(entry => hasPendingApplication(entry)).length
  return {
    supportCount: entries.filter(entry => entry.entry_type === 'support_request').length,
    takeoverCount: entries.filter(entry => entry.entry_type === 'takeover_candidate').length,
    appliedCount,
  }
})
const featuredOrder = computed(() => {
  const supportTarget = supportEntries.value[0]
  if (supportTarget) {
    return {
      ticketId: supportTarget.work_order?.ticket_id || supportTarget.id,
      hallEntryId: supportTarget.id,
      incidentId: supportTarget.incident_id || undefined,
      title: sanitizeDisplayText(supportTarget.support_reason || supportTarget.reason || supportTarget.work_order?.issue_description) || '协同任务待处理',
      building: formatBuildingLabel(supportTarget.work_order?.building_id),
      location: formatDeviceLabel(supportTarget.work_order?.device_id, supportTarget.work_order?.building_id) || '协同现场待确认',
      time: formatDateTime(supportTarget.assigned_at || supportTarget.created_at),
      timeTag: supportTarget.status === 'assigned' ? '待确认协同' : '协同处理中',
      priorityLabel: '协同任务',
      actionLabel: supportTarget.status === 'assigned' ? '响应协同' : '查看协同',
      kind: 'support' as const,
    }
  }
  const incidentTarget = getWorkerFeatureOrder(incidents.value)
  return incidentTarget ? { ...incidentTarget, kind: 'incident' as const } : null
})
const messageCards = computed(() => getWorkerMessageCards(incidents.value))
const unreadCount = computed(() => messageCards.value
  .filter(card => card.key !== 'bulletin')
  .reduce((sum, card) => sum + card.count, 0))

const tips = [
  { title: '到场前确认现场信息', desc: '优先核对建筑、设备与建议措施，减少二次往返。' },
  { title: '处理后及时提交备注', desc: '记录维修动作和异常原因，方便后续复盘与追踪。' },
  { title: '超时工单优先闭环', desc: '带有超时标记的工单会持续推送提醒，建议优先处理。' },
]

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

function hasPendingApplication(entry: DispatchHallEntry) {
  if (!currentUserId.value) return false
  return entry.applications.some(item => item.applicant_user_id === currentUserId.value && item.status === 'pending')
}

function shortTicket(ticketId: string) {
  return ticketId.slice(-8)
}

function openFeatureOrder() {
  if (!featuredOrder.value) return
  if (featuredOrder.value.kind === 'support') {
    uni.navigateTo({
      url: `/pages/worker/workorder-detail/index?hall_entry_id=${featuredOrder.value.hallEntryId}&incident_id=${featuredOrder.value.incidentId || ''}&ticket_id=${featuredOrder.value.ticketId}`,
    })
    return
  }
  const target = incidents.value.find(item => (item.current_work_order?.ticket_id || item.incident_id) === featuredOrder.value?.ticketId)
  if (!target?.current_work_order?.ticket_id) return
  uni.navigateTo({
    url: `/pages/worker/workorder-detail/index?incident_id=${target.incident_id}&ticket_id=${target.current_work_order.ticket_id}`,
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
  unsubscribeWorkerSync = subscribeWorkerOrdersUpdated(async () => {
    await loadData()
  })
  void loadData()
})

onShow(() => {
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
  padding: 0 24rpx calc(168rpx + env(safe-area-inset-bottom, 0px));
  box-sizing: border-box;
  scrollbar-width: none;
  -ms-overflow-style: none;
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
  font-family: 'RuiZiZhenYan', sans-serif;
}

.portal-title.small {
  font-size: 38rpx;
  font-weight: 900;
  font-family: 'RuiZiZhenYan', sans-serif;
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

.portal-metrics {
  position: relative;
  z-index: 1;
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 12rpx;
  margin-top: 22rpx;
  padding-right: 20rpx;
}

.portal-metric {
  padding: 16rpx 10rpx;
  border-radius: 22rpx;
  background: rgba(255, 255, 255, 0.82);
  box-shadow: inset 0 0 0 2rpx rgba(228, 237, 184, 0.6);
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8rpx;
}

.portal-metric-num {
  font-size: 34rpx;
  line-height: 1;
  color: #31411f;
  font-weight: 800;
}

.portal-metric-label {
  font-size: 20rpx;
  color: #73814f;
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
  padding: 24rpx 24rpx 24rpx 30rpx;
  border-radius: 24rpx;
  background: linear-gradient(180deg, #fff8f4 0%, #fffdfb 100%);
  box-shadow: none;
  border: 2rpx solid rgba(255, 154, 122, 0.18);
}

.feature-card::before {
  content: '';
  position: absolute;
  left: 0;
  top: 24rpx;
  bottom: 24rpx;
  width: 8rpx;
  border-radius: 999rpx;
  background: linear-gradient(180deg, #ffae8f 0%, #ff7f5f 100%);
}

.feature-tag-row {
  display: flex;
  align-items: center;
  gap: 16rpx;
}

.feature-tag {
  padding: 8rpx 16rpx;
  border-radius: 16rpx;
  font-size: 22rpx;
}

.feature-tag.warn {
  color: #ff845e;
  background: #fff0ea;
}

.feature-tag.plain {
  color: #e08f6d;
  background: #fff7f2;
}

.feature-action {
  margin-left: auto;
  padding: 10rpx 18rpx;
  border-radius: 18rpx;
  background: linear-gradient(135deg, #ffa27f, #ff8e67);
  color: #fff;
  font-size: 24rpx;
}

.feature-title {
  display: block;
  margin-top: 18rpx;
  font-size: 36rpx;
  color: #2d2522;
  font-weight: 700;
}

.feature-location {
  display: block;
  margin-top: 14rpx;
  font-size: 24rpx;
  color: #8a7d75;
}

.feature-meta {
  margin-top: 18rpx;
  padding: 18rpx 20rpx;
  border-radius: 20rpx;
  background: linear-gradient(180deg, rgba(255, 145, 108, 0.08) 0%, rgba(255, 145, 108, 0.02) 100%);

  text {
    display: block;
    font-size: 24rpx;
    color: #5f5652;
    line-height: 1.7;
  }
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
