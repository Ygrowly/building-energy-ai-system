<template>
  <view class="page">
    <NavBar title="工单审阅" bg-color="#111827" />

    <!-- 分组切换 -->
    <view class="tab-shell">
      <view class="tab-switch">
        <view
          v-for="tab in switchTabs"
          :key="tab.value"
          class="switch-item"
          :class="{ active: activeTab === tab.value }"
          @click="onSwitchTab(tab.value)"
        >
          <text class="switch-label">{{ tab.label }}</text>
          <view v-if="tab.count > 0" class="count-dot">{{ tab.count }}</view>
        </view>
      </view>
    </view>

    <scroll-view scroll-y class="list-area" @scrolltolower="loadMore">
      <view class="section-head">
        <view>
          <text class="section-title">{{ activeTabLabel }}</text>
          <text class="section-note">{{ sectionNote }}</text>
        </view>
      </view>

      <view v-if="activeTab === 'dispatched' && sortedIncidents.length" class="summary-strip">
        <view class="summary-pill">
          <text class="summary-value">{{ dispatchStats.total }}</text>
          <text class="summary-label">已派单</text>
        </view>
        <view class="summary-pill danger">
          <text class="summary-value">{{ dispatchStats.overdue }}</text>
          <text class="summary-label">已超时</text>
        </view>
        <view class="summary-pill warning">
          <text class="summary-value">{{ dispatchStats.warning }}</text>
          <text class="summary-label">临期</text>
        </view>
        <view class="summary-pill active">
          <text class="summary-value">{{ dispatchStats.active }}</text>
          <text class="summary-label">持续异常</text>
        </view>
      </view>

      <view v-if="loading && !incidents.length">
        <view v-for="i in 3" :key="i" class="wo-skeleton" />
      </view>

      <view v-for="incident in sortedIncidents" :key="incident.id" class="wo-wrap">
        <IncidentReviewCard
          :incident="incident"
          mode="operator-review"
          :show-quick-actions="activeTab === 'dispatched'"
          @click="openDetail"
          @action="handleCardAction"
        />

        <!-- 审阅操作（根据状态显示不同按钮） -->
        <view v-if="getActions(incident.workflow_status || '').length" class="action-row">
          <button
            v-for="act in getActions(incident.workflow_status || '')"
            :key="act.action"
            class="action-btn"
            :class="act.style"
            :loading="actionLoading === (incident.current_work_order?.ticket_id || incident.id) + '_' + act.action"
            @click.stop="doAdminAction(incident, act.action, act.confirmTitle)"
          >{{ act.label }}</button>
        </view>
      </view>

      <view v-if="!loading && !incidents.length" class="empty-state">
        <image class="empty-icon" src="/static/icons/tab-workorder.svg" mode="aspectFit" />
        <text>{{ emptyText }}</text>
      </view>

      <view v-if="noMore && incidents.length > 0" class="load-end">没有更多了</view>
    </scroll-view>

    <TabBar :tabs="OPERATOR_TABS" current="workorders" theme="operator" />
  </view>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import NavBar from '../../../components/NavBar.vue'
import TabBar from '../../../components/TabBar.vue'
import IncidentReviewCard from '../../../components/IncidentReviewCard.vue'
import { useRouteGuard } from '../../../utils/route-guard'
import { OPERATOR_TABS } from '../../../constants/tabs'
import { OPERATOR_ROLES } from '../../../constants/roles'
import type { AdminAction } from '../../../constants/status'
import { workOrderApi } from '../../../api/workorder'
import { incidentApi, type Incident } from '../../../api/incident'
import { getCache, setCache } from '../../../utils/cache'
import { getDispatchSortScore, getDispatchSummaryStats } from '../../../utils/incident-card'

useRouteGuard(OPERATOR_ROLES)

interface ActionDef { action: AdminAction; label: string; style: string; confirmTitle: string }

// 对齐后端 admin-review 的 action 枚举
function getActions(status: string): ActionDef[] {
  switch (status) {
    case 'auto_approved':
      return [{ action: 'override_reject', label: '覆盖驳回', style: 'danger', confirmTitle: '确认覆盖AI决策，驳回此工单？' }]
    case 'auto_rejected':
      return [{ action: 'override_approve', label: '覆盖批准', style: 'approve', confirmTitle: '确认覆盖AI决策，批准派单？' }]
    case 'completed':
    case 'false_alarm':
      return [{ action: 'confirm', label: '确认关闭', style: 'neutral', confirmTitle: '确认关闭此工单？' }]
    case 'escalated':
      return [{ action: 'close_escalated', label: '关闭升级', style: 'neutral', confirmTitle: '确认关闭此升级工单？' }]
    default:
      return []
  }
}

const switchTabs = ref([
  { label: '待审阅',     value: 'pending_review', count: 0 },
  { label: 'AI已驳回',   value: 'auto_rejected',  count: 0 },
  { label: '已派单',     value: 'dispatched',     count: 0 },
  { label: '待关闭',     value: 'completed,false_alarm,escalated', count: 0 },
])

const activeTab = ref('dispatched')
const incidents = ref<Incident[]>([])
const loading = ref(false)
const noMore = ref(false)
const actionLoading = ref<string | null>(null)
const page = ref(1)
const PAGE_SIZE = 15

const emptyText = computed(() => {
  const map: Record<string, string> = {
    pending_review: '暂无待审阅事件',
    auto_rejected: '暂无AI已驳回工单',
    dispatched: '暂无已派单工单',
  }
  return map[activeTab.value] ?? '暂无工单'
})

const activeTabLabel = computed(() => {
  return switchTabs.value.find(tab => tab.value === activeTab.value)?.label || '事件列表'
})

const currentTabCount = computed(() => {
  return switchTabs.value.find(tab => tab.value === activeTab.value)?.count || incidents.value.length
})

const sortedIncidents = computed(() => {
  if (activeTab.value !== 'dispatched') return incidents.value
  return [...incidents.value].sort((a, b) => getDispatchSortScore(b) - getDispatchSortScore(a))
})

const dispatchStats = computed(() => getDispatchSummaryStats(sortedIncidents.value))

const sectionNote = computed(() => {
  if (activeTab.value === 'dispatched') {
    return `共 ${currentTabCount.value} 条事件，按超时风险与处理优先级排序`
  }
  return `共 ${currentTabCount.value} 条事件，按最近异常时间倒序展示`
})

async function loadData() {
  const cacheKey = `workorders_${activeTab.value}`
  const cached = getCache<Incident[]>(cacheKey)
  if (cached) incidents.value = cached
  loading.value = !cached
  page.value = 1
  noMore.value = false
  try {
    const res = await incidentApi.list({
      workflow_status: activeTab.value,
      page: 1,
      page_size: PAGE_SIZE,
    })
    incidents.value = res.incidents
    setCache(cacheKey, res.incidents)
    if (res.incidents.length < PAGE_SIZE) noMore.value = true
    await loadCounts()
  } catch { /* handled */ }
  finally { loading.value = false }
}

async function loadCounts() {
  const statuses = ['pending_review', 'auto_rejected', 'dispatched', 'completed,false_alarm,escalated']
  await Promise.allSettled(
    statuses.map(async (s, i) => {
      const res = await incidentApi.list({ workflow_status: s, page: 1, page_size: 1 })
      switchTabs.value[i].count = res.total
    })
  )
}

async function loadMore() {
  if (loading.value || noMore.value) return
  page.value++
  try {
    const res = await incidentApi.list({ workflow_status: activeTab.value, page: page.value, page_size: PAGE_SIZE })
    incidents.value.push(...res.incidents)
    if (res.incidents.length < PAGE_SIZE) noMore.value = true
  } catch { page.value-- }
}

function onSwitchTab(val: string) { activeTab.value = val; loadData() }

function openDetail(incident: Incident) {
  const ticketId = incident.current_work_order?.ticket_id
  if (!ticketId) return
  uni.navigateTo({ url: `/pages/worker/workorder-detail/index?incident_id=${incident.incident_id}&ticket_id=${ticketId}&readonly=1` })
}

function handleCardAction(payload: { type: 'trend' | 'contact' | 'nudge' | 'detail'; incident: Incident }) {
  const { type, incident } = payload
  if (type === 'trend' || type === 'detail') {
    openDetail(incident)
    return
  }

  if (type === 'contact') {
    const phone = incident.current_work_order?.assigned_phone
    if (!phone) {
      uni.showToast({ title: '暂无责任人联系方式', icon: 'none' })
      return
    }
    uni.makePhoneCall({ phoneNumber: phone })
    return
  }

  if (type === 'nudge') {
    const assignee = incident.current_work_order?.assigned_to_name || '责任人'
    uni.showToast({ title: `已催办${assignee}`, icon: 'none' })
  }
}

async function doAdminAction(incident: Incident, action: AdminAction, confirmTitle: string) {
  const ticketId = incident.current_work_order?.ticket_id
  if (!ticketId) return
  const key = ticketId + '_' + action
  actionLoading.value = key

  uni.showModal({
    title: '操作确认',
    content: confirmTitle,
    confirmColor: action.includes('reject') ? '#ff4d4f' : '#3b6cf4',
    async success(res) {
      if (!res.confirm) { actionLoading.value = null; return }
      try {
        await workOrderApi.adminReview(ticketId, action)
        uni.showToast({ title: '操作成功', icon: 'success' })
        incidents.value = incidents.value.filter(item => item.id !== incident.id)
        await loadCounts()
      } catch { /* handled */ }
      finally { actionLoading.value = null }
    },
    fail() { actionLoading.value = null },
  })
}

onMounted(loadData)
</script>

<style lang="scss" scoped>
.page {
  min-height: 100vh;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  background:
    radial-gradient(circle at top right, rgba(74, 222, 128, 0.1), transparent 24%),
    #eef2f8;
}

.tab-shell {
  margin: 20rpx 24rpx 6rpx;
  position: relative;
  z-index: 1;
}

.tab-switch {
  display: flex;
  background: #fff;
  border: 1rpx solid rgba(225,231,240,0.9);
  border-radius: 24rpx;
  padding: 8rpx;
  box-shadow: 0 10rpx 30rpx rgba(20, 32, 58, 0.08);
}

.switch-item {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8rpx;
  height: 76rpx;
  color: #7d8797;
  position: relative;
  border-radius: 18rpx;
  &.active {
    color: #1d4ed8;
    font-weight: 700;
    background: linear-gradient(135deg, #eef4ff, #ffffff);
    box-shadow: inset 0 0 0 1rpx rgba(97, 139, 255, 0.18);
  }
}

.switch-label {
  font-size: 24rpx;
}

.count-dot {
  background: linear-gradient(135deg, #ff5d73, #ff7a5c);
  color: #fff;
  border-radius: 999rpx;
  font-size: 18rpx;
  padding: 3rpx 10rpx;
  min-width: 34rpx;
  text-align: center;
  box-shadow: 0 6rpx 16rpx rgba(255, 93, 115, 0.28);
}

.list-area {
  flex: 1;
  min-height: 0;
  height: auto;
  box-sizing: border-box;
  padding: 22rpx 24rpx calc(env(safe-area-inset-bottom, 0px) + 140rpx);
}

.section-head {
  padding: 10rpx 6rpx 18rpx;
}

.section-title {
  display: block;
  font-size: 28rpx;
  font-weight: 800;
  color: #1b2433;
  margin-bottom: 6rpx;
}

.section-note {
  display: block;
  font-size: 22rpx;
  color: #7d8797;
}

.summary-strip {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 12rpx;
  margin: 0 0 18rpx;
}

.summary-pill {
  background: #ffffff;
  border: 1rpx solid rgba(226, 232, 240, 0.95);
  border-radius: 20rpx;
  padding: 18rpx 14rpx;
  display: flex;
  flex-direction: column;
  gap: 6rpx;
  box-shadow: 0 10rpx 24rpx rgba(15, 23, 42, 0.05);

  &.danger {
    background: #fff4f3;
    border-color: #ffd8d3;
  }

  &.warning {
    background: #fff7e8;
    border-color: #ffe0b2;
  }

  &.active {
    background: #eefcf7;
    border-color: #d6f2e6;
  }
}

.summary-value {
  font-size: 30rpx;
  line-height: 1;
  font-weight: 800;
  color: #1f2937;
}

.summary-label {
  font-size: 20rpx;
  color: #6b7280;
}

.wo-wrap { margin-bottom: 8rpx; }

.action-row {
  display: flex;
  gap: 16rpx;
  margin-top: -4rpx;
  padding: 0 6rpx 16rpx;
}

.action-btn {
  flex: 1;
  height: 72rpx;
  border-radius: 16rpx;
  font-size: 24rpx;
  font-weight: 700;
  border: none;
  box-shadow: 0 10rpx 22rpx rgba(16, 24, 40, 0.06);
  &.approve { background: linear-gradient(135deg, #12b76a, #16c47f); color: #fff; }
  &.danger  { background: #fff2f0; color: #ff4d4f; }
  &.neutral { background: #eef4ff; color: #2f6df6; }
}

.empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  padding: 140rpx 0;
  gap: 16rpx;
  color: #97a2b4;
  font-size: 28rpx;
  .empty-icon { width: 88rpx; height: 88rpx; opacity: 0.42; }
}

.load-end { text-align: center; font-size: 24rpx; color: #a5afbf; padding: 20rpx; }

.wo-skeleton {
  height: 252rpx;
  background: linear-gradient(90deg, #f6f8fb, #eef2f7, #f6f8fb);
  border-radius: 28rpx;
  margin-bottom: 20rpx;
}

@media (max-width: 430px) {
  .summary-strip {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}
</style>
