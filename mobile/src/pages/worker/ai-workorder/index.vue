<template>
  <view class="page">
    <NavBar title="维小修" bg-color="#E4EDB8" text-color="#5f7137" :show-back="true" />

    <view v-if="loading" class="loading-box">
      <text>正在读取工单...</text>
    </view>

    <scroll-view v-else scroll-y class="page-scroll">
      <view v-if="order && !isWorkerAiReady" class="not-ready-card">
        <text class="not-ready-title">先完成工单推进</text>
        <text class="not-ready-desc">{{ notReadyText }}</text>
        <view class="not-ready-action" @click="openDetailPage">
          <text>回到工单详情</text>
        </view>
      </view>

      <view v-else-if="order && isWorkerAiReady" class="chat-shell" :class="{ 'with-welcome': showWelcomeCard }">
        <view v-if="showWelcomeCard" class="ai-welcome-card">
          <view class="ai-welcome-copy">
            <text class="ai-welcome-kicker">维小修已接入</text>
            <text class="ai-welcome-title">{{ welcomeTitle }}</text>
            <text class="ai-welcome-desc">不用一次说全，先发一个现象、读数或照片，我陪你判断下一步。</text>
          </view>
          <view class="ai-welcome-visual">
            <DotLottieVue
              class="ai-welcome-lottie"
              src="/static/lottie/ai-chat.lottie"
              autoplay
              loop
            />
          </view>
        </view>
        <AiChat
          :order="order"
          title="维小修"
          hint="把现场情况发我，我陪你判断下一步"
          mode="worker"
          dock-input
          :dispatch-id="dispatchId || order.current_dispatch?.id || order.dispatch_id || null"
          :hall-entry-id="hallEntryId"
          @order-updated="handleOrderUpdated"
        />
      </view>

      <view v-else-if="!order" class="empty-card">
        <text class="empty-title">未找到工单</text>
        <text class="empty-desc">请从我的工单列表进入维小修。</text>
      </view>
    </scroll-view>
  </view>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { DotLottieVue } from '@lottiefiles/dotlottie-vue'
import NavBar from '../../../components/NavBar.vue'
import AiChat from '../../../components/AiChat.vue'
import { workOrderApi, type DispatchHallEntry, type WorkOrder } from '../../../api/workorder'
import { useRouteGuard } from '../../../utils/route-guard'
import { WORKER_ROLES } from '../../../constants/roles'

useRouteGuard(WORKER_ROLES)

const pages = getCurrentPages()
const currentPage = pages[pages.length - 1] as any
const ticketId = currentPage?.options?.ticket_id || ''
const dispatchId = currentPage?.options?.dispatch_id || ''
const hallEntryId = currentPage?.options?.hall_entry_id || ''
const isFreshStartEntry = currentPage?.options?.fresh_start === '1'
const WORKER_AI_READY_STATUSES = new Set(['processing', 'waiting_support', 'supporting'])

const loading = ref(false)
const order = ref<WorkOrder | null>(null)
const hallEntry = ref<DispatchHallEntry | null>(null)

function isWorkerAiReadyStatus(value?: string | null) {
  return WORKER_AI_READY_STATUSES.has(String(value || '').toLowerCase())
}

const hasStartedCurrentDispatch = computed(() => {
  const currentOrder = order.value
  if (!currentOrder) return false
  const dispatch = currentOrder.current_dispatch
  if (dispatch) {
    return Boolean(
      dispatch.processing_started_at
        || isWorkerAiReadyStatus(dispatch.execution_status)
        || isWorkerAiReadyStatus(dispatch.dispatch_status),
    )
  }
  return Boolean(
    currentOrder.processing_started_at
      || isWorkerAiReadyStatus(currentOrder.execution_status),
  )
})
const isWorkerAiReady = computed(() => Boolean(
  order.value
    && (
      hallEntry.value?.status === 'accepted'
      || hasStartedCurrentDispatch.value
    ),
))
const notReadyText = computed(() => {
  if (hallEntryId && hallEntry.value?.status !== 'accepted') {
    return '这条协同任务还没有确认。请先回到工单详情页确认协同，再让维小修接入现场。'
  }
  return '维小修只在开始处理后接入。请先在工单详情页完成接单、到场和开始处理。'
})
const showWelcomeCard = computed(() => Boolean(order.value && isWorkerAiReady.value && isFreshStartEntry))
const welcomeTitle = computed(() => `${timeGreeting()}，我在现场陪你看`)

function timeGreeting() {
  const hour = new Date().getHours()
  if (hour < 6) return '凌晨好'
  if (hour < 12) return '上午好'
  if (hour < 14) return '中午好'
  if (hour < 18) return '下午好'
  return '晚上好'
}

function handleOrderUpdated(nextOrder: WorkOrder) {
  order.value = nextOrder
}

function openDetailPage() {
  if (!order.value?.ticket_id) {
    uni.navigateBack()
    return
  }
  const query = [
    `ticket_id=${order.value.ticket_id}`,
    currentPage?.options?.incident_id ? `incident_id=${currentPage.options.incident_id}` : '',
    hallEntryId ? `hall_entry_id=${hallEntryId}` : '',
    dispatchId ? `dispatch_id=${dispatchId}` : '',
  ].filter(Boolean).join('&')
  uni.redirectTo({ url: `/pages/worker/workorder-detail/index?${query}` })
}

async function loadOrder() {
  if (!ticketId) return
  loading.value = true
  try {
    const [orderDetail, hallDetail] = await Promise.all([
      workOrderApi.detail(ticketId),
      hallEntryId ? workOrderApi.dispatchHallDetail(hallEntryId).catch(() => null) : Promise.resolve(null),
    ])
    order.value = orderDetail
    hallEntry.value = hallDetail
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
  padding: 0 24rpx 0;
  box-sizing: border-box;
}

.empty-card {
  padding: 28rpx;
  border-radius: 28rpx;
  background: #ffffff;
  box-shadow: 0 16rpx 36rpx rgba(167, 191, 99, 0.12);
}

.empty-desc {
  display: block;
  margin-top: 14rpx;
  font-size: 24rpx;
  line-height: 1.6;
  color: #7b8264;
}

.chat-shell {
  margin-top: 0;
}

.ai-welcome-card {
  min-height: 184rpx;
  margin: 22rpx 0 8rpx;
  padding: 26rpx 24rpx 24rpx;
  border-radius: 16rpx;
  background: linear-gradient(135deg, #ffffff 0%, #edf6ec 58%, #f7fbff 100%);
  border: 1rpx solid rgba(190, 207, 137, 0.56);
  box-shadow: 0 16rpx 36rpx rgba(116, 138, 72, 0.11);
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16rpx;
  overflow: hidden;
}

.ai-welcome-copy {
  flex: 1;
  min-width: 0;
}

.ai-welcome-kicker {
  display: block;
  font-size: 22rpx;
  line-height: 1.4;
  color: #6f7f43;
  font-weight: 700;
}

.ai-welcome-title {
  display: block;
  margin-top: 10rpx;
  font-size: 32rpx;
  line-height: 1.25;
  color: #273012;
  font-weight: 900;
}

.ai-welcome-desc {
  display: block;
  margin-top: 10rpx;
  font-size: 24rpx;
  line-height: 1.55;
  color: #596249;
}

.ai-welcome-visual {
  width: 150rpx;
  height: 150rpx;
  flex: 0 0 150rpx;
  display: flex;
  align-items: center;
  justify-content: center;
}

.ai-welcome-lottie {
  width: 150rpx;
  height: 150rpx;
}

.not-ready-card {
  margin-top: 24rpx;
  padding: 28rpx;
  border-radius: 28rpx;
  background: #ffffff;
  box-shadow: 0 16rpx 36rpx rgba(167, 191, 99, 0.10);
}

.not-ready-title {
  display: block;
  font-size: 32rpx;
  color: #273012;
  font-weight: 800;
}

.not-ready-desc {
  display: block;
  margin-top: 14rpx;
  font-size: 25rpx;
  line-height: 1.6;
  color: #6a7448;
}

.not-ready-action {
  height: 76rpx;
  margin-top: 22rpx;
  border-radius: 20rpx;
  background: linear-gradient(135deg, #d6e29f, #b5c875);
  display: flex;
  align-items: center;
  justify-content: center;

  text {
    color: #fff;
    font-size: 26rpx;
    font-weight: 700;
  }
}

:deep(.ai-chat) {
  border-radius: 0;
  box-shadow: none;
  background: transparent;
  overflow: visible;
}

:deep(.chat-header) {
  padding: 22rpx 0 16rpx;
  border-bottom-color: #eef2dc;
}

:deep(.chat-messages) {
  height: auto;
  min-height: 0;
  padding: 16rpx 0;
  overflow: visible;
}

.chat-shell.with-welcome :deep(.chat-messages) {
  height: auto;
  min-height: 0;
}

:deep(.step-panel),
:deep(.recommend-panel) {
  margin-left: 0;
  margin-right: 0;
}

.empty-title {
  display: block;
  font-size: 32rpx;
  color: #273012;
  font-weight: 800;
}
</style>
