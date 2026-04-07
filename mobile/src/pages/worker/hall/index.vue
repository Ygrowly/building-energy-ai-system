<template>
  <view class="page">
    <NavBar title="工单大厅" bg-color="#E4EDB8" text-color="#5f7137" :show-back="true">
      <template #right>
        <text class="nav-action" @click="loadData">↻</text>
      </template>
    </NavBar>

    <view class="hero-card">
      <text class="hero-title">工单大厅承接可共享响应的任务</text>
      <text class="hero-desc">一期先承接未指派协同和超时待接管任务。正式指派或确认接管后，任务会进入“我的工单”。</text>
      <view class="hero-stats">
        <view class="hero-stat">
          <text class="hero-stat-num">{{ stats.supportCount }}</text>
          <text class="hero-stat-label">待协同</text>
        </view>
        <view class="hero-stat">
          <text class="hero-stat-num">{{ stats.takeoverCount }}</text>
          <text class="hero-stat-label">待接管</text>
        </view>
        <view class="hero-stat">
          <text class="hero-stat-num">{{ stats.appliedCount }}</text>
          <text class="hero-stat-label">我的申请</text>
        </view>
      </view>
    </view>

    <view class="tab-row">
      <view
        v-for="tab in hallTabs"
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
      <view v-if="loading && !filteredEntries.length">
        <view v-for="index in 3" :key="index" class="skeleton-card" />
      </view>

      <view v-for="entry in filteredEntries" :key="entry.id" class="hall-card">
        <view class="card-head">
          <view class="badge-row">
            <text class="type-badge" :class="entry.entry_type === 'support_request' ? 'support' : 'takeover'">
              {{ entryTypeLabel(entry) }}
            </text>
            <text class="priority-badge">{{ priorityText(entry) }}</text>
            <text v-if="applicationBadge(entry)" class="plain-badge">{{ applicationBadge(entry) }}</text>
          </view>
          <text class="time-text">{{ formatDateTime(entry.created_at) }}</text>
        </view>

        <text class="card-title">{{ titleText(entry) }}</text>
        <text class="card-location">{{ buildingText(entry) }} / {{ locationText(entry) }}</text>

        <view class="detail-panel">
          <view class="detail-line">
            <text class="detail-label">当前主责</text>
            <text class="detail-value">{{ ownerText(entry) }}</text>
          </view>
          <view class="detail-line">
            <text class="detail-label">进入原因</text>
            <text class="detail-value multiline">{{ reasonText(entry) }}</text>
          </view>
          <view class="detail-line">
            <text class="detail-label">建议措施</text>
            <text class="detail-value multiline">{{ suggestionText(entry) }}</text>
          </view>
          <view v-if="latestApplicationSummary(entry)" class="detail-line">
            <text class="detail-label">申请状态</text>
            <text class="detail-value multiline">{{ latestApplicationSummary(entry) }}</text>
          </view>
        </view>

        <view class="action-row">
          <view class="ghost-btn" @click.stop="handleSecondaryAction(entry)">{{ secondaryActionLabel(entry) }}</view>
          <view
            class="primary-btn"
            :class="{ disabled: isPrimaryActionDisabled(entry) }"
            @click.stop="handlePrimaryAction(entry)"
          >
            {{ primaryActionLabel(entry) }}
          </view>
        </view>
      </view>

      <view v-if="!loading && !filteredEntries.length" class="empty-card">
        <text class="empty-icon">厅</text>
        <text class="empty-title">当前没有可响应的共享工单</text>
        <text class="empty-subtitle">新的未指派协同和超时待接管任务会同步出现在这里</text>
      </view>
    </scroll-view>
  </view>
</template>

<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { onShow } from '@dcloudio/uni-app'
import NavBar from '../../../components/NavBar.vue'
import { workOrderApi, type DispatchHallApplication, type DispatchHallEntry } from '../../../api/workorder'
import { useRouteGuard } from '../../../utils/route-guard'
import { WORKER_ROLES } from '../../../constants/roles'
import { useAuthStore } from '../../../stores/auth'
import { getCache, setCache } from '../../../utils/cache'
import { emitWorkerOrdersUpdated, subscribeWorkerOrdersUpdated } from '../../../utils/worker-sync'
import { formatDateTime } from '../../../utils/format'
import { formatBuildingLabel, formatDeviceLabel, sanitizeDisplayText } from '../../../utils/display'
import { PRIORITY_LABEL } from '../../../constants/status'

useRouteGuard(WORKER_ROLES)

type HallTab = 'support_request' | 'takeover_candidate' | 'applied'

const authStore = useAuthStore()
const entries = ref<DispatchHallEntry[]>([])
const loading = ref(false)
const activeTab = ref<HallTab>('support_request')
const applyingEntryId = ref('')
const withdrawingApplicationId = ref('')
const hasLoadedOnce = ref(false)
let unsubscribeWorkerSync: (() => void) | null = null

const currentUserId = computed(() => authStore.user?.id || '')
const stats = computed(() => ({
  supportCount: entries.value.filter(item => item.entry_type === 'support_request').length,
  takeoverCount: entries.value.filter(item => item.entry_type === 'takeover_candidate').length,
  appliedCount: entries.value.filter(item => !!latestMyApplication(item)).length,
}))
const hallTabs = computed(() => [
  { label: '待协同', value: 'support_request' as const, count: stats.value.supportCount },
  { label: '待接管', value: 'takeover_candidate' as const, count: stats.value.takeoverCount },
  { label: '我的申请', value: 'applied' as const, count: stats.value.appliedCount },
])
const filteredEntries = computed(() => {
  if (activeTab.value === 'applied') {
    return entries.value.filter(item => !!latestMyApplication(item))
  }
  return entries.value.filter(item => item.entry_type === activeTab.value)
})

function getMyApplications(entry: DispatchHallEntry): DispatchHallApplication[] {
  if (!currentUserId.value) return []
  return entry.applications.filter(item => item.applicant_user_id === currentUserId.value)
}

function hasPendingApplication(entry: DispatchHallEntry) {
  return getMyApplications(entry).some(item => item.status === 'pending')
}

function latestMyApplication(entry: DispatchHallEntry) {
  return [...getMyApplications(entry)].sort((a, b) => {
    const aTime = a.updated_at || a.created_at || ''
    const bTime = b.updated_at || b.created_at || ''
    return bTime.localeCompare(aTime)
  })[0] || null
}

function entryTypeLabel(entry: DispatchHallEntry) {
  return entry.entry_type === 'support_request' ? '共享协同' : '待接管'
}

function priorityText(entry: DispatchHallEntry) {
  return PRIORITY_LABEL[entry.work_order?.priority || ''] || '普通工单'
}

function applicationBadge(entry: DispatchHallEntry) {
  const latest = latestMyApplication(entry)
  if (!latest) return ''
  if (latest.status === 'pending') return '已提交申请'
  if (latest.status === 'rejected') return '可重新申请'
  if (latest.status === 'approved') return '已被选中'
  if (latest.status === 'withdrawn') return '已撤回'
  return ''
}

function latestApplicationSummary(entry: DispatchHallEntry) {
  const latest = latestMyApplication(entry)
  if (!latest) return ''
  const statusMap: Record<string, string> = {
    pending: '等待管理员确认',
    approved: '申请已通过，请到“我的工单”继续处理',
    rejected: '申请已驳回',
    withdrawn: '你已主动撤回申请',
  }
  const summary = statusMap[latest.status] || `当前状态 ${latest.status}`
  return latest.handle_note ? `${summary}；${latest.handle_note}` : summary
}

function titleText(entry: DispatchHallEntry) {
  return sanitizeDisplayText(
    entry.support_reason
    || entry.reason
    || entry.work_order?.issue_description,
  ) || '共享工单待处理'
}

function buildingText(entry: DispatchHallEntry) {
  return formatBuildingLabel(entry.work_order?.building_id)
}

function locationText(entry: DispatchHallEntry) {
  return formatDeviceLabel(entry.work_order?.device_id, entry.work_order?.building_id) || '现场待确认'
}

function ownerText(entry: DispatchHallEntry) {
  return entry.source_dispatch?.assigned_to_name || '主责任人待确认'
}

function reasonText(entry: DispatchHallEntry) {
  if (entry.entry_type === 'takeover_candidate') {
    const detail = sanitizeDisplayText(entry.reason || entry.work_order?.dispatch_blocked_reason || '')
    const overdueText = entry.overdue_level ? `当前级别 ${entry.overdue_level}` : ''
    return detail || overdueText || '当前派工已超时，进入共享接管池'
  }
  return sanitizeDisplayText(entry.support_reason || entry.reason || '') || '主责任人正在请求协同支援'
}

function suggestionText(entry: DispatchHallEntry) {
  return sanitizeDisplayText(entry.work_order?.suggested_action) || '请先核对现场情况，再决定是否申请介入'
}

function primaryActionLabel(entry: DispatchHallEntry) {
  if (isWithdrawing(entry)) return '撤回中...'
  if (isApplying(entry.id)) return '提交中...'
  if (activeTab.value === 'applied' && hasPendingApplication(entry)) return '撤回申请'
  const latest = latestMyApplication(entry)
  if (latest?.status === 'rejected') {
    return entry.entry_type === 'support_request' ? '重新申请协同' : '重新申请接管'
  }
  if (latest?.status === 'withdrawn') {
    return entry.entry_type === 'support_request' ? '重新申请协同' : '重新申请接管'
  }
  if (latest?.status === 'approved') return '查看我的工单'
  if (hasPendingApplication(entry)) {
    return entry.entry_type === 'support_request' ? '已申请协同' : '已申请接管'
  }
  return entry.entry_type === 'support_request' ? '申请协同' : '申请接管'
}

function isApplying(entryId: string) {
  return applyingEntryId.value === entryId
}

function isWithdrawing(entry: DispatchHallEntry) {
  const latest = latestMyApplication(entry)
  return !!latest && withdrawingApplicationId.value === latest.id
}

function isPrimaryActionDisabled(entry: DispatchHallEntry) {
  const latest = latestMyApplication(entry)
  if (isApplying(entry.id) || isWithdrawing(entry)) return true
  if (activeTab.value === 'applied' && latest?.status === 'approved') return false
  return hasPendingApplication(entry) && activeTab.value !== 'applied'
}

function secondaryActionLabel(entry: DispatchHallEntry) {
  const latest = latestMyApplication(entry)
  if (activeTab.value === 'applied' && latest?.handle_note) return '查看说明'
  return '联系主责'
}

async function loadData() {
  const cached = getCache<DispatchHallEntry[]>('worker_shared_hall')
  if (cached) entries.value = cached
  loading.value = !cached

  try {
    const res = await workOrderApi.listDispatchHallEntries({
      status: 'open',
      entry_type: 'support_request,takeover_candidate',
      include_applications: true,
      page: 1,
      page_size: 50,
    })
    entries.value = res.hall_entries
    setCache('worker_shared_hall', res.hall_entries)
    hasLoadedOnce.value = true
  } catch {
    if (!entries.value.length) {
      uni.showToast({ title: '共享工单加载失败', icon: 'none' })
    }
  } finally {
    loading.value = false
  }
}

async function submitApplication(entry: DispatchHallEntry) {
  if (isApplying(entry.id) || hasPendingApplication(entry)) return
  applyingEntryId.value = entry.id
  try {
    if (entry.entry_type === 'support_request') {
      await workOrderApi.applyDispatchHallSupport(entry.id)
    } else {
      await workOrderApi.applyDispatchHallTakeover(entry.id)
    }
    emitWorkerOrdersUpdated({
      reason: `dispatch_hall_apply:${entry.entry_type}`,
      ticketId: entry.work_order?.ticket_id,
      incidentId: entry.incident_id || undefined,
    })
    await loadData()
    uni.showToast({ title: entry.entry_type === 'support_request' ? '已提交协同申请' : '已提交接管申请', icon: 'none' })
  } catch (error: any) {
    uni.showToast({ title: error?.message || '申请失败，请稍后重试', icon: 'none' })
  } finally {
    applyingEntryId.value = ''
  }
}

async function withdrawApplication(entry: DispatchHallEntry) {
  const latest = latestMyApplication(entry)
  if (!latest || latest.status !== 'pending' || isWithdrawing(entry)) return
  withdrawingApplicationId.value = latest.id
  try {
    await workOrderApi.withdrawDispatchHallApplication(latest.id)
    emitWorkerOrdersUpdated({
      reason: `dispatch_hall_withdraw:${entry.entry_type}`,
      ticketId: entry.work_order?.ticket_id,
      incidentId: entry.incident_id || undefined,
    })
    await loadData()
    uni.showToast({ title: '已撤回申请', icon: 'none' })
  } catch (error: any) {
    uni.showToast({ title: error?.message || '撤回失败，请稍后重试', icon: 'none' })
  } finally {
    withdrawingApplicationId.value = ''
  }
}

function goToMyOrders() {
  uni.switchTab({ url: '/pages/worker/active/index' })
}

function handlePrimaryAction(entry: DispatchHallEntry) {
  const latest = latestMyApplication(entry)
  if (activeTab.value === 'applied' && latest?.status === 'pending') {
    void withdrawApplication(entry)
    return
  }
  if (activeTab.value === 'applied' && latest?.status === 'approved') {
    goToMyOrders()
    return
  }
  void submitApplication(entry)
}

function handleSecondaryAction(entry: DispatchHallEntry) {
  const latest = latestMyApplication(entry)
  if (activeTab.value === 'applied' && latest?.handle_note) {
    uni.showModal({
      title: '处理说明',
      content: latest.handle_note,
      showCancel: false,
      confirmText: '知道了',
    })
    return
  }
  callOwner(entry)
}

function callOwner(entry: DispatchHallEntry) {
  const phone = entry.source_dispatch?.assigned_phone
  if (!phone) {
    uni.showToast({ title: '暂无联系电话', icon: 'none' })
    return
  }
  uni.makePhoneCall({ phoneNumber: phone })
}

onMounted(() => {
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
  min-height: 100vh;
  background:
    radial-gradient(circle at top, rgba(174, 203, 150, 0.2), transparent 36%),
    linear-gradient(180deg, #f5f8ef 0%, #fbfdf8 100%);
}

.nav-action {
  font-size: 36rpx;
  color: #5f7137;
}

.hero-card {
  margin: 0 24rpx;
  padding: 28rpx 28rpx 30rpx;
  border-radius: 30rpx;
  background: linear-gradient(180deg, rgba(232, 241, 207, 0.96) 0%, rgba(255, 255, 255, 0.98) 100%);
  border: 2rpx solid rgba(183, 204, 118, 0.24);
  box-shadow: 0 18rpx 42rpx rgba(181, 196, 118, 0.12);
}

.hero-title {
  display: block;
  font-size: 34rpx;
  color: #31411f;
  font-weight: 700;
}

.hero-desc {
  display: block;
  margin-top: 12rpx;
  font-size: 24rpx;
  line-height: 1.65;
  color: #69784f;
}

.hero-stats {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 14rpx;
  margin-top: 24rpx;
}

.hero-stat {
  padding: 18rpx 12rpx;
  border-radius: 22rpx;
  background: rgba(255, 255, 255, 0.84);
  display: flex;
  flex-direction: column;
  align-items: center;
}

.hero-stat-num {
  font-size: 46rpx;
  line-height: 1;
  color: #31411f;
  font-weight: 700;
}

.hero-stat-label {
  margin-top: 10rpx;
  font-size: 22rpx;
  color: #73814f;
}

.tab-row {
  display: flex;
  padding: 18rpx 24rpx 0;
}

.tab-item {
  flex: 1;
  padding: 18rpx 0 22rpx;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 6rpx;
  position: relative;
}

.tab-item.active::after {
  content: '';
  position: absolute;
  left: 24%;
  right: 24%;
  bottom: 0;
  height: 8rpx;
  border-radius: 999rpx;
  background: linear-gradient(90deg, #E4EDB8, #b7cc76);
}

.tab-label {
  font-size: 30rpx;
  color: #2d2522;
  font-weight: 700;
}

.tab-count {
  font-size: 22rpx;
  color: #808873;
}

.list-area {
  height: calc(100vh - 480rpx);
  padding: 24rpx 24rpx calc(80rpx + env(safe-area-inset-bottom, 0px));
  box-sizing: border-box;
}

.hall-card,
.empty-card,
.skeleton-card {
  background: rgba(255, 255, 255, 0.98);
  border-radius: 30rpx;
  box-shadow: 0 14rpx 36rpx rgba(181, 196, 118, 0.08);
}

.hall-card {
  padding: 26rpx;
  margin-bottom: 20rpx;
}

.card-head,
.badge-row,
.detail-line,
.action-row {
  display: flex;
  align-items: center;
}

.card-head {
  justify-content: space-between;
  gap: 12rpx;
}

.badge-row {
  gap: 10rpx;
  flex-wrap: wrap;
}

.type-badge,
.priority-badge,
.plain-badge {
  padding: 8rpx 16rpx;
  border-radius: 999rpx;
  font-size: 22rpx;
}

.type-badge.support {
  color: #486533;
  background: rgba(183, 204, 118, 0.18);
}

.type-badge.takeover {
  color: #d36444;
  background: rgba(255, 170, 140, 0.18);
}

.priority-badge {
  color: #745640;
  background: rgba(255, 233, 215, 0.96);
}

.plain-badge {
  color: #5f7137;
  background: rgba(228, 237, 184, 0.78);
}

.time-text {
  flex-shrink: 0;
  font-size: 22rpx;
  color: #8a8f7f;
}

.card-title {
  display: block;
  margin-top: 18rpx;
  font-size: 34rpx;
  line-height: 1.4;
  color: #2d2522;
  font-weight: 700;
}

.card-location {
  display: block;
  margin-top: 12rpx;
  font-size: 24rpx;
  color: #7c7f72;
}

.detail-panel {
  margin-top: 18rpx;
  padding: 18rpx 20rpx;
  border-radius: 24rpx;
  background: linear-gradient(180deg, rgba(246, 249, 238, 0.96) 0%, rgba(255, 255, 255, 0.92) 100%);
}

.detail-line {
  align-items: flex-start;
  gap: 16rpx;
  margin-top: 12rpx;
}

.detail-line:first-child {
  margin-top: 0;
}

.detail-label {
  width: 120rpx;
  flex-shrink: 0;
  font-size: 24rpx;
  color: #8c8d7a;
}

.detail-value {
  flex: 1;
  font-size: 24rpx;
  line-height: 1.6;
  color: #2f2925;
}

.detail-value.multiline {
  white-space: pre-wrap;
}

.action-row {
  gap: 16rpx;
  margin-top: 20rpx;
}

.ghost-btn,
.primary-btn {
  flex: 1;
  height: 76rpx;
  border-radius: 999rpx;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 26rpx;
  font-weight: 700;
}

.ghost-btn {
  color: #6f7a57;
  background: #f4f7ea;
}

.primary-btn {
  color: #fff;
  background: linear-gradient(135deg, #b9cf7d, #8eab45);
}

.primary-btn.disabled {
  opacity: 0.6;
}

.empty-card {
  padding: 64rpx 24rpx;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 16rpx;
}

.empty-icon {
  width: 92rpx;
  height: 92rpx;
  border-radius: 28rpx;
  background: linear-gradient(135deg, #d8e6a7, #b7cc76);
  color: #fff;
  font-size: 40rpx;
  font-weight: 700;
  display: flex;
  align-items: center;
  justify-content: center;
}

.empty-title {
  font-size: 30rpx;
  color: #2f2925;
  font-weight: 700;
}

.empty-subtitle {
  font-size: 24rpx;
  line-height: 1.6;
  color: #7c7f72;
  text-align: center;
}

.skeleton-card {
  height: 320rpx;
  margin-bottom: 20rpx;
  background: linear-gradient(90deg, rgba(245, 248, 239, 0.9) 0%, rgba(255, 255, 255, 0.98) 45%, rgba(245, 248, 239, 0.9) 100%);
}
</style>
