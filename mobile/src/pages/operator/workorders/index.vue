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
        <view v-if="tab.count > 0" class="count-dot">{{ tab.count }}</view>
      </view>
    </view>

    <scroll-view scroll-y class="list-area" @scrolltolower="loadMore">
      <view v-if="loading && !orders.length">
        <view v-for="i in 3" :key="i" class="wo-skeleton" />
      </view>

      <view v-for="order in orders" :key="order.id" class="wo-wrap">
        <WorkOrderCard :order="order" @click="openDetail" />

        <!-- 审阅操作（根据状态显示不同按钮） -->
        <view v-if="getActions(order.status).length" class="action-row">
          <button
            v-for="act in getActions(order.status)"
            :key="act.action"
            class="action-btn"
            :class="act.style"
            :loading="actionLoading === order.ticket_id + '_' + act.action"
            @click.stop="doAdminAction(order, act.action, act.confirmTitle)"
          >{{ act.label }}</button>
        </view>

        <!-- AI 推理摘要 -->
        <view v-if="order.ai_reason" class="ai-reasoning">
          <text class="ai-label">AI 分析：</text>
          <text class="ai-text">{{ order.ai_reason }}</text>
        </view>
      </view>

      <view v-if="!loading && !orders.length" class="empty-state">
        <text class="empty-icon">📋</text>
        <text>{{ emptyText }}</text>
      </view>

      <view v-if="noMore && orders.length > 0" class="load-end">没有更多了</view>
    </scroll-view>

    <TabBar :tabs="OPERATOR_TABS" current="workorders" theme="operator" />
  </view>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import NavBar from '../../../components/NavBar.vue'
import TabBar from '../../../components/TabBar.vue'
import WorkOrderCard from '../../../components/WorkOrderCard.vue'
import { useRouteGuard } from '../../../utils/route-guard'
import { OPERATOR_TABS } from '../../../constants/tabs'
import { OPERATOR_ROLES } from '../../../constants/roles'
import { STATUS_LABEL, type AdminAction } from '../../../constants/status'
import { workOrderApi, type WorkOrder } from '../../../api/workorder'

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
  { label: 'AI已批准',   value: 'auto_approved',  count: 0 },
  { label: 'AI已驳回',   value: 'auto_rejected',  count: 0 },
  { label: '已派单',     value: 'dispatched',     count: 0 },
  { label: '待关闭',     value: 'completed,false_alarm,escalated', count: 0 },
])

const activeTab = ref('auto_approved')
const orders = ref<WorkOrder[]>([])
const loading = ref(false)
const noMore = ref(false)
const actionLoading = ref<string | null>(null)
const page = ref(1)
const PAGE_SIZE = 15

const emptyText = computed(() => {
  const map: Record<string, string> = {
    auto_approved: '暂无AI已批准工单',
    auto_rejected: '暂无AI已驳回工单',
    dispatched: '暂无已派单工单',
  }
  return map[activeTab.value] ?? '暂无工单'
})

async function loadData() {
  loading.value = true
  page.value = 1
  noMore.value = false
  try {
    const res = await workOrderApi.list({
      status: activeTab.value,
      page: 1,
      page_size: PAGE_SIZE,
    })
    orders.value = res.work_orders
    if (res.work_orders.length < PAGE_SIZE) noMore.value = true
    loadCounts()
  } catch { /* handled */ }
  finally { loading.value = false }
}

async function loadCounts() {
  const statuses = ['auto_approved', 'auto_rejected', 'dispatched']
  await Promise.allSettled(
    statuses.map(async (s, i) => {
      const res = await workOrderApi.list({ status: s, page: 1, page_size: 1 })
      switchTabs.value[i].count = res.total
    })
  )
}

async function loadMore() {
  if (loading.value || noMore.value) return
  page.value++
  try {
    const res = await workOrderApi.list({ status: activeTab.value, page: page.value, page_size: PAGE_SIZE })
    orders.value.push(...res.work_orders)
    if (res.work_orders.length < PAGE_SIZE) noMore.value = true
  } catch { page.value-- }
}

function onSwitchTab(val: string) { activeTab.value = val; loadData() }

function openDetail(order: WorkOrder) {
  uni.navigateTo({ url: `/pages/worker/workorder-detail/index?ticket_id=${order.ticket_id}&readonly=1` })
}

async function doAdminAction(order: WorkOrder, action: AdminAction, confirmTitle: string) {
  const key = order.ticket_id + '_' + action
  actionLoading.value = key

  uni.showModal({
    title: '操作确认',
    content: confirmTitle,
    confirmColor: action.includes('reject') ? '#ff4d4f' : '#3b6cf4',
    async success(res) {
      if (!res.confirm) { actionLoading.value = null; return }
      try {
        await workOrderApi.adminReview(order.ticket_id, action)
        uni.showToast({ title: '操作成功', icon: 'success' })
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

.tab-switch { display: flex; background: #fff; border-bottom: 1rpx solid #e8ecf0; }
.switch-item {
  flex: 1; display: flex; align-items: center; justify-content: center; gap: 8rpx;
  height: 88rpx; font-size: 24rpx; color: #999; position: relative;
  &.active {
    color: #3b6cf4; font-weight: 600;
    &::after { content: ''; position: absolute; bottom: 0; left: 20%; right: 20%; height: 4rpx; background: #3b6cf4; border-radius: 2rpx; }
  }
}
.count-dot { background: #ff4d4f; color: #fff; border-radius: 20rpx; font-size: 18rpx; padding: 2rpx 10rpx; min-width: 30rpx; text-align: center; }

.list-area { height: calc(100vh - 280rpx); padding: 20rpx 32rpx; }

.wo-wrap { margin-bottom: 8rpx; }

.action-row { display: flex; gap: 20rpx; margin-top: -6rpx; padding: 0 4rpx 16rpx; }
.action-btn {
  flex: 1; height: 72rpx; border-radius: 12rpx; font-size: 26rpx; font-weight: 600; border: none;
  &.approve { background: #00b96b; color: #fff; }
  &.danger  { background: #fff2f0; color: #ff4d4f; }
  &.neutral { background: #f0f5ff; color: #3b6cf4; }
}

.ai-reasoning {
  background: #f8f9ff; border-radius: 0 0 16rpx 16rpx; padding: 16rpx 24rpx;
  margin-top: -6rpx; border: 1rpx solid #e8effe; border-top: none;
}
.ai-label { font-size: 22rpx; color: #3b6cf4; font-weight: 600; }
.ai-text  { font-size: 22rpx; color: #666; line-height: 1.6; }

.empty-state { display: flex; flex-direction: column; align-items: center; padding: 120rpx 0; gap: 16rpx; color: #aaa; font-size: 28rpx; .empty-icon { font-size: 80rpx; } }
.load-end { text-align: center; font-size: 24rpx; color: #ccc; padding: 20rpx; }
.wo-skeleton { height: 180rpx; background: linear-gradient(90deg, #f0f0f0, #e8e8e8, #f0f0f0); border-radius: 16rpx; margin-bottom: 20rpx; }
</style>
