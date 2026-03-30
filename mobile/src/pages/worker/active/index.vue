<template>
  <view class="page">
    <NavBar title="进行中" bg-color="#0f3d2e" />

    <scroll-view scroll-y class="list-area" @scrolltolower="loadMore">
      <view v-if="loading && !orders.length">
        <view v-for="i in 2" :key="i" class="wo-skeleton" />
      </view>

      <!-- 进行中工单（已派单，尚未提交反馈） -->
      <view
        v-for="order in orders"
        :key="order.id"
        class="active-card"
        @click="openDetail(order)"
      >
        <view class="active-header">
          <view class="priority-badge" :class="order.priority">
            {{ PRIORITY_LABEL[order.priority] || order.priority }}
          </view>
          <text class="ticket-id">#{{ order.ticket_id.slice(-8) }}</text>
        </view>

        <text class="building-name">{{ order.building_id }}</text>
        <text v-if="order.device_id" class="device-id">{{ order.device_id }}</text>
        <text class="description">{{ order.issue_description }}</text>

        <!-- 进度指示 -->
        <view class="progress-row">
          <view class="progress-dot done" />
          <view class="progress-line" />
          <view class="progress-dot active" />
          <view class="progress-line" />
          <view class="progress-dot" />
        </view>
        <view class="progress-labels">
          <text>已接单</text>
          <text>处理中</text>
          <text>已完成</text>
        </view>

        <view class="open-btn">
          <text>继续处理 →</text>
        </view>
      </view>

      <view v-if="!loading && !orders.length" class="empty-state">
        <text class="empty-icon">🔧</text>
        <text>暂无进行中的工单</text>
        <text class="empty-sub">前往「待处理」接单</text>
      </view>
    </scroll-view>

    <TabBar :tabs="WORKER_TABS" current="active" theme="worker" />
  </view>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import NavBar from '../../../components/NavBar.vue'
import TabBar from '../../../components/TabBar.vue'
import { useRouteGuard } from '../../../utils/route-guard'
import { WORKER_TABS } from '../../../constants/tabs'
import { WORKER_ROLES } from '../../../constants/roles'
import { PRIORITY_LABEL } from '../../../constants/status'
import { workOrderApi, type WorkOrder } from '../../../api/workorder'

useRouteGuard(WORKER_ROLES)

const orders = ref<WorkOrder[]>([])
const loading = ref(false)
const noMore = ref(false)
const page = ref(1)

async function loadData() {
  loading.value = true
  try {
    const res = await workOrderApi.list({
      status: 'dispatched',
      page: 1,
      page_size: 20,
    })
    orders.value = res.work_orders
  } catch { /* handled */ }
  finally { loading.value = false }
}

async function loadMore() {
  if (loading.value || noMore.value) return
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

.list-area {
  height: calc(100vh - 200rpx);
  padding: 24rpx 32rpx;
}

.active-card {
  background: #fff;
  border-radius: 20rpx;
  padding: 28rpx;
  margin-bottom: 24rpx;
  box-shadow: 0 4rpx 20rpx rgba(0,185,107,0.12);
  border-top: 4rpx solid #00b96b;
}

.active-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 16rpx;
}

.priority-badge {
  padding: 6rpx 16rpx;
  border-radius: 20rpx;
  font-size: 22rpx;

  &.high   { background: #fff2f0; color: #ff4d4f; }
  &.medium { background: #fff7e6; color: #fa8c16; }
  &.low    { background: #f6ffed; color: #52c41a; }
}

.ticket-id { font-size: 22rpx; color: #aaa; }

.building-name {
  display: block;
  font-size: 32rpx;
  font-weight: 700;
  color: #1a1a2e;
  margin-bottom: 6rpx;
}

.device-id {
  display: block;
  font-size: 26rpx;
  color: #00b96b;
  margin-bottom: 10rpx;
}

.description {
  display: block;
  font-size: 24rpx;
  color: #999;
  line-height: 1.5;
  margin-bottom: 28rpx;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

/* 进度条 */
.progress-row {
  display: flex;
  align-items: center;
  margin-bottom: 8rpx;
}

.progress-dot {
  width: 20rpx;
  height: 20rpx;
  border-radius: 50%;
  background: #e0e0e0;

  &.done   { background: #00b96b; }
  &.active {
    background: #00b96b;
    box-shadow: 0 0 0 6rpx rgba(0,185,107,0.2);
  }
}

.progress-line {
  flex: 1;
  height: 4rpx;
  background: #e0e0e0;
}

.progress-labels {
  display: flex;
  justify-content: space-between;
  font-size: 20rpx;
  color: #aaa;
  margin-bottom: 20rpx;
}

.open-btn {
  background: #f0fff8;
  border: 2rpx solid #00b96b;
  border-radius: 12rpx;
  padding: 16rpx;
  text-align: center;

  text {
    font-size: 26rpx;
    color: #00b96b;
    font-weight: 600;
  }
}

.empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  padding: 120rpx 0;
  gap: 16rpx;
  color: #aaa;

  .empty-icon { font-size: 80rpx; }
  font-size: 28rpx;
}

.empty-sub {
  font-size: 24rpx;
  color: #ccc;
}

.wo-skeleton {
  height: 280rpx;
  background: linear-gradient(90deg, #e8f5f0, #d4ede4, #e8f5f0);
  border-radius: 20rpx;
  margin-bottom: 24rpx;
}
</style>
