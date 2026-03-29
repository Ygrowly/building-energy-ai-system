<template>
  <view class="page">
    <NavBar title="工单审阅" bg-color="#1a1a2e" />

    <!-- 分组切换 -->
    <view class="tab-switch">
      <view
        v-for="tab in switchTabs"
        :key="tab.value"
        class="switch-item"
        :class="{ active: activeTab === tab.value }"
        @click="onSwitchTab(tab.value)"
      >
        <text>{{ tab.label }}</text>
        <view v-if="tab.count" class="count-dot">{{ tab.count }}</view>
      </view>
    </view>

    <!-- 工单列表 -->
    <scroll-view scroll-y class="list-area" @scrolltolower="loadMore">
      <view v-if="loading && !orders.length">
        <view v-for="i in 3" :key="i" class="wo-skeleton" />
      </view>

      <view
        v-for="order in orders"
        :key="order.id"
        class="wo-wrap"
        @click="openDetail(order)"
      >
        <WorkOrderCard :order="order" @click="openDetail" />

        <!-- 审阅操作按钮（仅 ai_approved / ai_rejected 状态显示） -->
        <view
          v-if="order.status === 'ai_approved' || order.status === 'ai_rejected'"
          class="action-row"
        >
          <button
            class="action-btn approve"
            :loading="actionLoading === order.ticket_id + '_approve'"
            @click.stop="doAdminAction(order, 'approve')"
          >批准派单</button>
          <button
            class="action-btn reject"
            :loading="actionLoading === order.ticket_id + '_reject'"
            @click.stop="doAdminAction(order, 'reject')"
          >驳回工单</button>
        </view>

        <!-- AI 推理摘要 -->
        <view v-if="order.ai_reasoning" class="ai-reasoning">
          <text class="ai-reasoning-label">AI 分析：</text>
          <text class="ai-reasoning-text">{{ order.ai_reasoning }}</text>
        </view>
      </view>

      <view v-if="!loading && !orders.length" class="empty-state">
        <text class="empty-icon">📋</text>
        <text>{{ emptyText }}</text>
      </view>

      <view v-if="noMore && orders.length > 0" class="load-end">没有更多了</view>
    </scroll-view>

    <TabBar :tabs="operatorTabs" current="workorders" theme="operator" />
  </view>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import NavBar from '../../../components/NavBar.vue'
import TabBar, { type TabItem } from '../../../components/TabBar.vue'
import WorkOrderCard from '../../../components/WorkOrderCard.vue'
import { workOrderApi, type WorkOrder } from '../../../api/workorder'

const operatorTabs: TabItem[] = [
  { name: 'overview',   label: '总览', icon: '📊', path: '/pages/operator/overview/index' },
  { name: 'alerts',     label: '告警', icon: '🔔', path: '/pages/operator/alerts/index' },
  { name: 'workorders', label: '工单', icon: '📋', path: '/pages/operator/workorders/index' },
  { name: 'profile',    label: '我的', icon: '👤', path: '/pages/operator/profile/index' },
]

// 待审阅 = AI已批准/驳回待运维人员确认，历史 = 已关闭
const switchTabs = ref([
  { label: 'AI已批准', value: 'ai_approved', count: 0 },
  { label: 'AI已驳回', value: 'ai_rejected', count: 0 },
  { label: '已派单',   value: 'dispatched',  count: 0 },
  { label: '已完成',   value: 'closed',      count: 0 },
])

const activeTab = ref('ai_approved')
const orders = ref<WorkOrder[]>([])
const loading = ref(false)
const loadingMore = ref(false)
const noMore = ref(false)
const actionLoading = ref<string | null>(null)
const page = ref(1)
const PAGE_SIZE = 10

const emptyText = computed(() => {
  const map: Record<string, string> = {
    ai_approved: '暂无待确认的AI批准工单',
    ai_rejected: '暂无待复核的AI驳回工单',
    dispatched:  '暂无已派单的工单',
    closed:      '暂无已完成的工单',
  }
  return map[activeTab.value] ?? '暂无工单'
})

async function loadData() {
  loading.value = true
  page.value = 1
  noMore.value = false
  try {
    const res = await workOrderApi.list({
      status: activeTab.value as any,
      page: 1,
      page_size: PAGE_SIZE,
    })
    orders.value = res.items
    if (res.items.length < PAGE_SIZE) noMore.value = true

    // 更新各 tab 角标
    loadCounts()
  } catch { /* handled */ }
  finally { loading.value = false }
}

async function loadCounts() {
  // 并发查各状态数量
  const statuses = ['ai_approved', 'ai_rejected', 'dispatched']
  await Promise.allSettled(
    statuses.map(async (s, i) => {
      const res = await workOrderApi.list({ status: s as any, page: 1, page_size: 1 })
      switchTabs.value[i].count = res.total
    })
  )
}

async function loadMore() {
  if (loadingMore.value || noMore.value) return
  loadingMore.value = true
  page.value++
  try {
    const res = await workOrderApi.list({
      status: activeTab.value as any,
      page: page.value,
      page_size: PAGE_SIZE,
    })
    orders.value.push(...res.items)
    if (res.items.length < PAGE_SIZE) noMore.value = true
  } catch { page.value-- }
  finally { loadingMore.value = false }
}

function onSwitchTab(val: string) {
  activeTab.value = val
  loadData()
}

function openDetail(order: WorkOrder) {
  uni.navigateTo({
    url: `/pages/worker/workorder-detail/index?ticket_id=${order.ticket_id}&readonly=1`,
  })
}

async function doAdminAction(order: WorkOrder, action: 'approve' | 'reject') {
  const key = order.ticket_id + '_' + action
  actionLoading.value = key

  uni.showModal({
    title: action === 'approve' ? '确认批准派单' : '确认驳回工单',
    content: action === 'approve'
      ? `确认覆盖 AI 决策，批准工单 ${order.ticket_id} 派单？`
      : `确认覆盖 AI 决策，驳回工单 ${order.ticket_id}？`,
    confirmText: action === 'approve' ? '批准' : '驳回',
    confirmColor: action === 'approve' ? '#00b96b' : '#ff4d4f',
    async success(res) {
      if (!res.confirm) { actionLoading.value = null; return }
      try {
        await workOrderApi.adminReview(order.ticket_id, action)
        uni.showToast({ title: action === 'approve' ? '已批准派单' : '已驳回', icon: 'success' })
        // 从列表移除
        orders.value = orders.value.filter(o => o.ticket_id !== order.ticket_id)
      } catch { /* handled */ }
      finally { actionLoading.value = null }
    },
    fail() { actionLoading.value = null },
  })
}

onMounted(loadData)
</script>

<style lang="scss" scoped>
.page { background: #f0f2f8; min-height: 100vh; }

.tab-switch {
  display: flex;
  background: #fff;
  border-bottom: 1rpx solid #e8ecf0;
}

.switch-item {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8rpx;
  height: 88rpx;
  font-size: 26rpx;
  color: #999;
  position: relative;

  &.active {
    color: #3b6cf4;
    font-weight: 600;

    &::after {
      content: '';
      position: absolute;
      bottom: 0;
      left: 20%;
      right: 20%;
      height: 4rpx;
      background: #3b6cf4;
      border-radius: 2rpx;
    }
  }
}

.count-dot {
  background: #ff4d4f;
  color: #fff;
  border-radius: 20rpx;
  font-size: 18rpx;
  padding: 2rpx 10rpx;
  min-width: 30rpx;
  text-align: center;
}

.list-area {
  height: calc(100vh - 280rpx);
  padding: 20rpx 32rpx;
}

.wo-wrap { margin-bottom: 20rpx; }

.action-row {
  display: flex;
  gap: 20rpx;
  margin-top: -6rpx;
  padding: 0 4rpx 20rpx;
}

.action-btn {
  flex: 1;
  height: 72rpx;
  border-radius: 12rpx;
  font-size: 26rpx;
  font-weight: 600;
  border: none;

  &.approve { background: #00b96b; color: #fff; }
  &.reject  { background: #fff2f0; color: #ff4d4f; }
}

.ai-reasoning {
  background: #f8f9ff;
  border-radius: 0 0 16rpx 16rpx;
  padding: 16rpx 24rpx;
  margin-top: -6rpx;
  border: 1rpx solid #e8effe;
  border-top: none;
}

.ai-reasoning-label {
  font-size: 22rpx;
  color: #3b6cf4;
  font-weight: 600;
}

.ai-reasoning-text {
  font-size: 22rpx;
  color: #666;
  line-height: 1.6;
}

.empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  padding: 120rpx 0;
  gap: 16rpx;
  color: #aaa;
  font-size: 28rpx;

  .empty-icon { font-size: 80rpx; }
}

.load-end {
  text-align: center;
  font-size: 24rpx;
  color: #ccc;
  padding: 20rpx;
}

.wo-skeleton {
  height: 180rpx;
  background: linear-gradient(90deg, #f0f0f0, #e8e8e8, #f0f0f0);
  border-radius: 16rpx;
  margin-bottom: 20rpx;
  animation: shimmer 1.5s infinite;
}

@keyframes shimmer {
  0%, 100% { opacity: 1; }
  50%       { opacity: 0.5; }
}
</style>
