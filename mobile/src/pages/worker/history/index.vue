<template>
  <view class="page">
    <NavBar title="历史记录" bg-color="#0f3d2e" />

    <!-- 统计卡 -->
    <view class="stats-card" v-if="stats.total > 0">
      <view class="stat">
        <text class="stat-n">{{ stats.total }}</text>
        <text class="stat-l">累计工单</text>
      </view>
      <view class="stat-sep" />
      <view class="stat">
        <text class="stat-n green">{{ stats.fixed }}</text>
        <text class="stat-l">已修复</text>
      </view>
      <view class="stat-sep" />
      <view class="stat">
        <text class="stat-n orange">{{ stats.falseAlarm }}</text>
        <text class="stat-l">误报</text>
      </view>
    </view>

    <scroll-view scroll-y class="list-area" @scrolltolower="loadMore">
      <view v-if="loading && !orders.length">
        <view v-for="i in 4" :key="i" class="wo-skeleton" />
      </view>

      <view
        v-for="order in orders"
        :key="order.id"
        class="history-card"
        :class="order.worker_feedback"
        @click="openDetail(order)"
      >
        <view class="hc-header">
          <text class="hc-date">{{ formatDate(order.updated_at) }}</text>
          <view class="feedback-badge" :class="order.worker_feedback">
            {{ feedbackText(order.worker_feedback) }}
          </view>
        </view>

        <text class="hc-building">{{ order.building_name || order.building_id }}</text>
        <text class="hc-type">{{ order.anomaly_type }}</text>
        <text v-if="order.worker_note" class="hc-note">备注：{{ order.worker_note }}</text>
      </view>

      <view v-if="!loading && !orders.length" class="empty-state">
        <text class="empty-icon">📂</text>
        <text>暂无历史记录</text>
      </view>

      <view v-if="noMore && orders.length > 0" class="load-end">没有更多了</view>
    </scroll-view>

    <TabBar :tabs="workerTabs" current="history" theme="worker" />
  </view>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import NavBar from '../../../components/NavBar.vue'
import TabBar, { type TabItem } from '../../../components/TabBar.vue'
import { workOrderApi, type WorkOrder } from '../../../api/workorder'

const workerTabs: TabItem[] = [
  { name: 'pending', label: '待处理', icon: '📥', path: '/pages/worker/pending/index' },
  { name: 'active',  label: '进行中', icon: '🔧', path: '/pages/worker/active/index' },
  { name: 'history', label: '历史',   icon: '📂', path: '/pages/worker/history/index' },
  { name: 'profile', label: '我的',   icon: '👤', path: '/pages/worker/profile/index' },
]

const orders = ref<WorkOrder[]>([])
const loading = ref(false)
const loadingMore = ref(false)
const noMore = ref(false)
const page = ref(1)
const PAGE_SIZE = 15

const stats = computed(() => ({
  total:      orders.value.length,
  fixed:      orders.value.filter(o => o.worker_feedback === 'fixed').length,
  falseAlarm: orders.value.filter(o => o.worker_feedback === 'false_alarm').length,
}))

async function loadData() {
  loading.value = true
  try {
    const res = await workOrderApi.list({
      status: ['completed', 'closed', 'false_alarm'] as any,
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
      status: ['completed', 'closed', 'false_alarm'] as any,
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
    url: `/pages/worker/workorder-detail/index?ticket_id=${order.ticket_id}&readonly=1`,
  })
}

function feedbackText(f?: string) {
  return { fixed: '已修复', false_alarm: '误报', escalated: '已升级' }[f ?? ''] ?? '处理完成'
}

function formatDate(iso: string) {
  const d = new Date(iso)
  return `${d.getFullYear()}-${(d.getMonth()+1).toString().padStart(2,'0')}-${d.getDate().toString().padStart(2,'0')}`
}

onMounted(loadData)
</script>

<style lang="scss" scoped>
.page { background: #f0f5f2; min-height: 100vh; }

.stats-card {
  display: flex;
  align-items: center;
  justify-content: space-around;
  background: linear-gradient(135deg, #0f3d2e, #00b96b);
  padding: 28rpx 32rpx;
}

.stat { display: flex; flex-direction: column; align-items: center; }

.stat-n {
  font-size: 44rpx;
  font-weight: 700;
  color: #fff;

  &.green  { color: #b7eb8f; }
  &.orange { color: #ffd591; }
}

.stat-l { font-size: 22rpx; color: rgba(255,255,255,0.7); margin-top: 4rpx; }

.stat-sep {
  width: 1rpx;
  height: 48rpx;
  background: rgba(255,255,255,0.2);
}

.list-area {
  height: calc(100vh - 300rpx);
  padding: 20rpx 32rpx;
}

.history-card {
  background: #fff;
  border-radius: 16rpx;
  padding: 24rpx;
  margin-bottom: 16rpx;
  border-left: 6rpx solid #e0e0e0;

  &.fixed       { border-left-color: #00b96b; }
  &.false_alarm { border-left-color: #ff4d4f; }
  &.escalated   { border-left-color: #3b6cf4; }
}

.hc-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 12rpx;
}

.hc-date { font-size: 22rpx; color: #aaa; }

.feedback-badge {
  font-size: 22rpx;
  padding: 4rpx 14rpx;
  border-radius: 16rpx;

  &.fixed       { background: #f0fff8; color: #00b96b; }
  &.false_alarm { background: #fff2f0; color: #ff4d4f; }
  &.escalated   { background: #f0f5ff; color: #3b6cf4; }
}

.hc-building {
  display: block;
  font-size: 28rpx;
  font-weight: 700;
  color: #1a1a2e;
  margin-bottom: 4rpx;
}

.hc-type {
  display: block;
  font-size: 24rpx;
  color: #666;
  margin-bottom: 8rpx;
}

.hc-note {
  font-size: 22rpx;
  color: #aaa;
  font-style: italic;
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
  height: 120rpx;
  background: linear-gradient(90deg, #e8f5f0, #d4ede4, #e8f5f0);
  border-radius: 16rpx;
  margin-bottom: 16rpx;
}

.load-end {
  text-align: center;
  font-size: 24rpx;
  color: #ccc;
  padding: 20rpx;
}
</style>
