<template>
  <view class="page">
    <NavBar title="维小修" bg-color="#E4EDB8" text-color="#5f7137" :show-back="true" />

    <view v-if="loading" class="loading-box">
      <text>正在读取工单...</text>
    </view>

    <scroll-view v-else scroll-y class="page-scroll">
      <view v-if="order" class="order-brief">
        <view class="brief-head">
          <text class="assistant-name">维小修</text>
          <text class="brief-status">{{ order.current_dispatch?.dispatch_status || order.execution_status || order.status }}</text>
        </view>
        <text class="brief-title">{{ order.issue_description }}</text>
        <text class="brief-meta">{{ order.ticket_id }} · {{ order.building_id }}</text>
        <text class="brief-copy">你可以直接说“确认接单”“我已到场”“开始处理”“请求协同”或“处理完成”。关键动作我会先向你确认，再提交到后端状态机。</text>
      </view>

      <view v-if="order" class="chat-shell">
        <AiChat
          :order="order"
          title="维小修"
          hint="对话式推进工单，状态变更仍走后端状态机"
          mode="worker"
          :dispatch-id="dispatchId || order.current_dispatch?.id || order.dispatch_id || null"
          :hall-entry-id="hallEntryId"
          @order-updated="handleOrderUpdated"
        />
      </view>

      <view v-else class="empty-card">
        <text class="empty-title">未找到工单</text>
        <text class="empty-desc">请从我的工单列表进入维小修。</text>
      </view>
    </scroll-view>
  </view>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import NavBar from '../../../components/NavBar.vue'
import AiChat from '../../../components/AiChat.vue'
import { workOrderApi, type WorkOrder } from '../../../api/workorder'
import { useRouteGuard } from '../../../utils/route-guard'
import { WORKER_ROLES } from '../../../constants/roles'

useRouteGuard(WORKER_ROLES)

const pages = getCurrentPages()
const currentPage = pages[pages.length - 1] as any
const ticketId = currentPage?.options?.ticket_id || ''
const dispatchId = currentPage?.options?.dispatch_id || ''
const hallEntryId = currentPage?.options?.hall_entry_id || ''

const loading = ref(false)
const order = ref<WorkOrder | null>(null)

function handleOrderUpdated(nextOrder: WorkOrder) {
  order.value = nextOrder
}

async function loadOrder() {
  if (!ticketId) return
  loading.value = true
  try {
    order.value = await workOrderApi.detail(ticketId)
  } catch {
    uni.showToast({ title: '工单加载失败', icon: 'none' })
  } finally {
    loading.value = false
  }
}

onMounted(() => {
  void loadOrder()
})
</script>

<style lang="scss" scoped>
.page {
  min-height: 100vh;
  background: linear-gradient(180deg, #f5f8e8 0%, #fbfcf5 48%, #ffffff 100%);
}

.loading-box {
  padding: 160rpx 0;
  text-align: center;
  color: #6a7448;
  font-size: 28rpx;
}

.page-scroll {
  height: calc(100vh - 132rpx);
  padding: 24rpx 24rpx 52rpx;
  box-sizing: border-box;
}

.order-brief,
.empty-card {
  padding: 28rpx;
  border-radius: 28rpx;
  background: #ffffff;
  box-shadow: 0 16rpx 36rpx rgba(167, 191, 99, 0.12);
}

.brief-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16rpx;
}

.assistant-name {
  font-size: 28rpx;
  color: #5f7137;
  font-weight: 800;
}

.brief-status {
  padding: 8rpx 14rpx;
  border-radius: 16rpx;
  color: #5f7137;
  background: #eef4ce;
  font-size: 22rpx;
}

.brief-title {
  display: block;
  margin-top: 20rpx;
  font-size: 36rpx;
  line-height: 1.35;
  font-weight: 800;
  color: #273012;
}

.brief-meta,
.brief-copy,
.empty-desc {
  display: block;
  margin-top: 14rpx;
  font-size: 24rpx;
  line-height: 1.6;
  color: #7b8264;
}

.chat-shell {
  margin-top: 24rpx;
}

:deep(.ai-chat) {
  border-radius: 28rpx;
  box-shadow: 0 16rpx 36rpx rgba(167, 191, 99, 0.10);
}

:deep(.chat-messages) {
  height: calc(100vh - 650rpx);
  min-height: 520rpx;
}

.empty-title {
  display: block;
  font-size: 32rpx;
  color: #273012;
  font-weight: 800;
}
</style>
