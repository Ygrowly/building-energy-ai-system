<template>
  <view class="page">
    <NavBar title="待处理工单" bg-color="#0f3d2e">
      <template #right>
        <text class="refresh-icon" @click="loadData">↻</text>
      </template>
    </NavBar>

    <!-- 统计横条 -->
    <view class="stat-row">
      <view class="stat-item">
        <text class="stat-num high">{{ counts.high }}</text>
        <text class="stat-label">高优先</text>
      </view>
      <view class="stat-sep" />
      <view class="stat-item">
        <text class="stat-num medium">{{ counts.medium }}</text>
        <text class="stat-label">中优先</text>
      </view>
      <view class="stat-sep" />
      <view class="stat-item">
        <text class="stat-num low">{{ counts.low }}</text>
        <text class="stat-label">低优先</text>
      </view>
    </view>

    <!-- 优先级筛选 -->
    <view class="filter-row">
      <view
        v-for="f in filters"
        :key="f.value"
        class="filter-chip"
        :class="{ active: activeFilter === f.value }"
        @click="activeFilter = f.value"
      >{{ f.label }}</view>
    </view>

    <scroll-view scroll-y class="list-area" @scrolltolower="loadMore">
      <view v-if="loading && !orders.length">
        <view v-for="i in 3" :key="i" class="wo-skeleton" />
      </view>

      <WorkOrderCard
        v-for="order in filteredOrders"
        :key="order.id"
        :order="order"
        @click="openDetail"
      />

      <view v-if="!loading && !filteredOrders.length" class="empty-state">
        <text class="empty-icon">🎉</text>
        <text>暂无待处理工单</text>
      </view>

      <view v-if="noMore && orders.length > 0" class="load-end">没有更多了</view>
    </scroll-view>

    <TabBar :tabs="workerTabs" current="pending" theme="worker" />
  </view>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import NavBar from '../../../components/NavBar.vue'
import TabBar, { type TabItem } from '../../../components/TabBar.vue'
import WorkOrderCard from '../../../components/WorkOrderCard.vue'
import { workOrderApi, type WorkOrder } from '../../../api/workorder'

const workerTabs: TabItem[] = [
  { name: 'pending', label: '待处理', icon: '📥', path: '/pages/worker/pending/index' },
  { name: 'active',  label: '进行中', icon: '🔧', path: '/pages/worker/active/index' },
  { name: 'history', label: '历史',   icon: '📂', path: '/pages/worker/history/index' },
  { name: 'profile', label: '我的',   icon: '👤', path: '/pages/worker/profile/index' },
]

const filters = [
  { label: '全部',   value: 'all' },
  { label: '高优先', value: 'high' },
  { label: '中优先', value: 'medium' },
  { label: '低优先', value: 'low' },
]

const activeFilter = ref('all')
const orders = ref<WorkOrder[]>([])
const loading = ref(false)
const loadingMore = ref(false)
const noMore = ref(false)
const page = ref(1)
const PAGE_SIZE = 15

const counts = computed(() => ({
  high:   orders.value.filter(o => o.priority === 'high').length,
  medium: orders.value.filter(o => o.priority === 'medium').length,
  low:    orders.value.filter(o => o.priority === 'low').length,
}))

const filteredOrders = computed(() => {
  if (activeFilter.value === 'all') return orders.value
  return orders.value.filter(o => o.priority === activeFilter.value)
})

async function loadData() {
  loading.value = true
  page.value = 1
  noMore.value = false
  try {
    const res = await workOrderApi.list({
      status: 'dispatched',
      assigned_to_me: true,
      page: 1,
      page_size: PAGE_SIZE,
    })
    orders.value = res.items
    if (res.items.length < PAGE_SIZE) noMore.value = true
  } catch { /* handled */ }
  finally { loading.value = false }
}

async function loadMore() {
  if (loadingMore.value || noMore.value) return
  loadingMore.value = true
  page.value++
  try {
    const res = await workOrderApi.list({
      status: 'dispatched',
      assigned_to_me: true,
      page: page.value,
      page_size: PAGE_SIZE,
    })
    orders.value.push(...res.items)
    if (res.items.length < PAGE_SIZE) noMore.value = true
  } catch { page.value-- }
  finally { loadingMore.value = false }
}

function openDetail(order: WorkOrder) {
  uni.navigateTo({
    url: `/pages/worker/workorder-detail/index?ticket_id=${order.ticket_id}`,
  })
}

onMounted(loadData)
</script>

<style lang="scss" scoped>
.page { background: #f0f5f2; min-height: 100vh; }

.refresh-icon { font-size: 40rpx; color: rgba(255,255,255,0.8); }

.stat-row {
  display: flex;
  align-items: center;
  background: linear-gradient(135deg, #0f3d2e, #00b96b);
  padding: 24rpx 32rpx;
  justify-content: space-around;
}

.stat-item {
  display: flex;
  flex-direction: column;
  align-items: center;
}

.stat-num {
  font-size: 44rpx;
  font-weight: 700;
  color: #fff;

  &.high   { color: #ffa39e; }
  &.medium { color: #ffd591; }
  &.low    { color: #b7eb8f; }
}

.stat-label { font-size: 22rpx; color: rgba(255,255,255,0.7); margin-top: 4rpx; }

.stat-sep {
  width: 1rpx;
  height: 48rpx;
  background: rgba(255,255,255,0.2);
}

.filter-row {
  display: flex;
  gap: 16rpx;
  padding: 20rpx 32rpx;
  background: #fff;
  border-bottom: 1rpx solid #e8ecf0;
}

.filter-chip {
  padding: 10rpx 24rpx;
  border-radius: 32rpx;
  background: #f5f5f5;
  font-size: 24rpx;
  color: #666;

  &.active { background: #00b96b; color: #fff; }
}

.list-area {
  height: calc(100vh - 400rpx);
  padding: 20rpx 32rpx;
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

.wo-skeleton {
  height: 180rpx;
  background: linear-gradient(90deg, #e8f5f0, #d4ede4, #e8f5f0);
  border-radius: 16rpx;
  margin-bottom: 20rpx;
}

.load-end {
  text-align: center;
  font-size: 24rpx;
  color: #ccc;
  padding: 20rpx;
}
</style>
