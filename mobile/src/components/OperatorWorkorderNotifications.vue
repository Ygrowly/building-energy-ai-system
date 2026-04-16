<template>
  <scroll-view scroll-y class="list-area" :style="listAreaStyle">
    <view class="toolbar-card">
      <view class="toolbar-copy">
        <text class="toolbar-label">未读工单通知</text>
        <text class="toolbar-value">{{ notificationStore.unreadCount }}</text>
      </view>
      <view class="toolbar-actions">
        <view class="toolbar-btn ghost" @click="refresh">
          <text>刷新</text>
        </view>
        <view
          class="toolbar-btn primary"
          :class="{ disabled: notificationStore.unreadCount === 0 }"
          @click="markAllRead"
        >
          <text>全部已读</text>
        </view>
      </view>
    </view>

    <view v-if="notificationStore.loading && !notificationStore.items.length" class="empty-block">
      <text class="empty-check">...</text>
      <text class="empty-text">正在加载工单通知</text>
    </view>

    <view v-else-if="!notificationStore.items.length" class="empty-block">
      <text class="empty-check">OK</text>
      <text class="empty-text">暂无工单通知</text>
    </view>

    <view v-else class="message-list">
      <view
        v-for="entry in notificationCards"
        :key="entry.item.recipient_id"
        class="msg-item clickable"
        :class="[entry.view.tone, { unread: !entry.item.read_at }]"
        @click="openNotification(entry.item)"
      >
        <view class="msg-accent" :class="entry.view.tone" />
        <view class="msg-icon" :class="entry.view.tone">
          <text>{{ entry.view.iconText }}</text>
        </view>
        <view class="msg-body">
          <view class="msg-head">
            <text class="msg-event" :class="entry.view.tone">{{ entry.view.eventLabel }}</text>
            <text class="msg-time">{{ formatRelativeTime(entry.item.created_at) }}</text>
          </view>
          <text class="msg-title">{{ entry.view.title }}</text>
          <text class="msg-sub">{{ entry.view.subtitle }}</text>
          <text v-if="entry.view.detail" class="msg-detail">{{ entry.view.detail }}</text>
          <view v-if="entry.view.chips.length" class="msg-chips">
            <text
              v-for="chip in entry.view.chips"
              :key="chip.text"
              class="msg-chip"
              :class="chip.tone"
            >{{ chip.text }}</text>
          </view>
        </view>
        <view v-if="!entry.item.read_at" class="msg-unread" />
      </view>
    </view>
  </scroll-view>
</template>

<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import type { NotificationItem } from '../api/notification'
import { workOrderApi, type WorkOrder } from '../api/workorder'
import { useNotificationStore } from '../stores/notification'
import { buildOperatorNotificationCard } from '../utils/operator-display'

const props = withDefaults(defineProps<{
  withTabBar?: boolean
}>(), {
  withTabBar: false,
})

const notificationStore = useNotificationStore()
const workOrderDetails = ref<Record<string, WorkOrder>>({})
const loadingTicketIds = new Set<string>()

const listAreaStyle = computed(() => ({
  paddingBottom: props.withTabBar ? 'calc(env(safe-area-inset-bottom, 0px) + 140rpx)' : '32rpx',
}))

const notificationTicketIds = computed(() =>
  Array.from(new Set(
    notificationStore.items
      .map((item) => item.related_ticket_id || item.cta_params?.ticket_id || item.payload?.ticket_id)
      .filter((value): value is string => typeof value === 'string' && Boolean(value.trim())),
  )),
)

const notificationCards = computed(() =>
  notificationStore.items.map((item) => ({
    item,
    view: buildOperatorNotificationCard(item, {
      workOrder: workOrderDetails.value[item.related_ticket_id || item.cta_params?.ticket_id || item.payload?.ticket_id || ''] || null,
    }),
  })),
)

function formatRelativeTime(value?: string | null) {
  if (!value) return '--'
  const target = new Date(value).getTime()
  if (!Number.isFinite(target)) return value
  const diff = Date.now() - target
  if (diff < 60_000) return '刚刚'
  if (diff < 3_600_000) return `${Math.max(1, Math.floor(diff / 60_000))}分钟前`
  if (diff < 86_400_000) return `${Math.max(1, Math.floor(diff / 3_600_000))}小时前`
  if (diff < 7 * 86_400_000) return `${Math.max(1, Math.floor(diff / 86_400_000))}天前`
  return value.slice(0, 16).replace('T', ' ')
}

async function refresh() {
  await notificationStore.refresh({ page_size: 50 })
}

async function markAllRead() {
  if (notificationStore.unreadCount === 0) return
  await notificationStore.markAllRead('workorder')
}

async function hydrateWorkOrders() {
  const missingIds = notificationTicketIds.value.filter((ticketId) => !workOrderDetails.value[ticketId] && !loadingTicketIds.has(ticketId))
  if (!missingIds.length) return

  missingIds.forEach((ticketId) => loadingTicketIds.add(ticketId))
  const results = await Promise.allSettled(
    missingIds.map(async (ticketId) => ({
      ticketId,
      detail: await workOrderApi.detail(ticketId),
    })),
  )

  const nextMap = { ...workOrderDetails.value }
  results.forEach((result, index) => {
    const ticketId = missingIds[index]
    loadingTicketIds.delete(ticketId)
    if (result.status === 'fulfilled') {
      nextMap[result.value.ticketId] = result.value.detail
    }
  })
  workOrderDetails.value = nextMap
}

async function openNotification(item: NotificationItem) {
  if (!item.read_at) {
    await notificationStore.markRead([item.recipient_id])
  }

  const hallEntryId = item.cta_params?.hall_entry_id
  const ticketId = item.related_ticket_id || item.cta_params?.ticket_id || item.payload?.ticket_id
  const incidentId = item.cta_params?.incident_id || item.payload?.incident_id

  if (item.cta_type === 'open_hall_entry' && hallEntryId && ticketId) {
    uni.navigateTo({
      url: `/pages/worker/workorder-detail/index?hall_entry_id=${encodeURIComponent(String(hallEntryId))}&incident_id=${encodeURIComponent(String(incidentId || ''))}&ticket_id=${encodeURIComponent(String(ticketId))}&readonly=1`,
    })
    return
  }

  if (item.cta_type === 'open_hall_entry' && hallEntryId) {
    uni.navigateTo({
      url: `/pages/operator/workorders/index?active_tab=shared_hall&hall_entry_id=${encodeURIComponent(String(hallEntryId))}`,
    })
    return
  }

  if (ticketId) {
    uni.navigateTo({
      url: `/pages/worker/workorder-detail/index?incident_id=${encodeURIComponent(String(incidentId || ''))}&ticket_id=${encodeURIComponent(String(ticketId))}&readonly=1`,
    })
    return
  }

  uni.navigateTo({ url: '/pages/operator/workorders/index' })
}

onMounted(() => {
  void refresh()
})

watch(notificationTicketIds, () => {
  void hydrateWorkOrders()
}, { immediate: true })
</script>

<style lang="scss" scoped>
.list-area {
  flex: 1;
  min-height: 0;
  padding: 12rpx 32rpx 32rpx;
  box-sizing: border-box;
}

.toolbar-card,
.empty-block,
.msg-item {
  background: var(--operator-card, #ffffff);
  border-radius: 28rpx;
}

.toolbar-card {
  margin-bottom: 18rpx;
  padding: 24rpx;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 20rpx;
  border: 1rpx solid var(--operator-border, rgba(203, 225, 208, 0.96));
  box-shadow: var(--operator-shadow, 0 12rpx 34rpx rgba(35, 75, 54, 0.1));
}

.toolbar-copy {
  display: flex;
  flex-direction: column;
  gap: 8rpx;
}

.toolbar-label {
  font-size: 22rpx;
  color: var(--operator-text-muted, #8aa091);
}

.toolbar-value {
  font-size: 42rpx;
  color: var(--operator-text, #163022);
  font-weight: 700;
}

.toolbar-actions {
  display: flex;
  gap: 12rpx;
}

.toolbar-btn {
  padding: 14rpx 24rpx;
  border-radius: 999rpx;

  text {
    font-size: 22rpx;
    font-weight: 700;
  }
}

.toolbar-btn.ghost {
  background: var(--operator-card-soft, #f4fbf5);

  text {
    color: var(--operator-text-secondary, #5b6f62);
  }
}

.toolbar-btn.primary {
  background: var(--operator-btn, linear-gradient(135deg, #42bf72, #2f855a));

  text {
    color: #fff;
  }
}

.toolbar-btn.disabled {
  opacity: 0.45;
}

.empty-block {
  padding: 56rpx 32rpx;
  text-align: center;
  border: 1rpx solid var(--operator-border, rgba(203, 225, 208, 0.96));
  background: var(--operator-bg-soft, #f7fbf7);
}

.empty-check {
  display: block;
  font-size: 44rpx;
  color: var(--primary, #2f855a);
}

.empty-text {
  display: block;
  margin-top: 10rpx;
  font-size: 26rpx;
  color: var(--operator-text-muted, #8aa091);
}

.message-list {
  display: flex;
  flex-direction: column;
  gap: 14rpx;
}

.msg-item {
  position: relative;
  display: flex;
  align-items: flex-start;
  gap: 18rpx;
  padding: 24rpx 24rpx 24rpx 28rpx;
  border: 1rpx solid var(--operator-border, rgba(203, 225, 208, 0.96));
  box-shadow: 0 10rpx 24rpx rgba(35, 75, 54, 0.06);
  overflow: hidden;
}

.msg-item.unread {
  box-shadow:
    0 0 0 2rpx rgba(66, 191, 114, 0.18),
    0 12rpx 28rpx rgba(35, 75, 54, 0.08);
}

.msg-accent {
  position: absolute;
  left: 0;
  top: 20rpx;
  bottom: 20rpx;
  width: 10rpx;
  border-radius: 999rpx;
}

.msg-accent.info,
.msg-icon.info,
.msg-event.info,
.msg-chip.accent {
  color: #2f855a;
}

.msg-accent.info {
  background: linear-gradient(180deg, #5bca85, #2f855a);
}

.msg-accent.warning {
  background: linear-gradient(180deg, #f7b955, #e58e11);
}

.msg-accent.danger {
  background: linear-gradient(180deg, #ef6d6d, #dc2626);
}

.msg-accent.success {
  background: linear-gradient(180deg, #73d69a, #2f9e62);
}

.msg-icon {
  position: relative;
  width: 68rpx;
  height: 68rpx;
  border-radius: 22rpx;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;

  text {
    font-size: 28rpx;
    color: #fff;
    font-weight: 700;
  }
}

.msg-icon.info {
  background: linear-gradient(135deg, #7fd7a0, #2f855a);
}

.msg-icon.warning {
  background: linear-gradient(135deg, #fdc877, #e58e11);
}

.msg-icon.danger {
  background: linear-gradient(135deg, #f49b9b, #dc2626);
}

.msg-icon.success {
  background: linear-gradient(135deg, #8ee3af, #2f9e62);
}

.msg-body {
  flex: 1;
  min-width: 0;
}

.msg-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12rpx;
}

.msg-event {
  display: inline-flex;
  align-items: center;
  padding: 6rpx 16rpx;
  border-radius: 999rpx;
  font-size: 20rpx;
  font-weight: 700;
}

.msg-event.info {
  background: var(--operator-chip-bg, #ebf8ef);
}

.msg-event.warning {
  background: rgba(245, 158, 11, 0.12);
  color: #d97706;
}

.msg-event.danger {
  background: rgba(239, 68, 68, 0.12);
  color: #dc2626;
}

.msg-event.success {
  background: rgba(34, 197, 94, 0.12);
  color: #15803d;
}

.msg-time {
  flex-shrink: 0;
  font-size: 20rpx;
  color: var(--operator-text-muted, #8aa091);
}

.msg-title {
  display: block;
  margin-top: 12rpx;
  font-size: 28rpx;
  font-weight: 800;
  line-height: 1.4;
  color: var(--operator-text, #163022);
}

.msg-sub {
  display: block;
  margin-top: 8rpx;
  font-size: 24rpx;
  line-height: 1.65;
  color: var(--operator-text-secondary, #5b6f62);
}

.msg-detail {
  display: block;
  margin-top: 10rpx;
  font-size: 22rpx;
  line-height: 1.6;
  color: var(--operator-text-muted, #8aa091);
}

.msg-chips {
  display: flex;
  flex-wrap: wrap;
  gap: 10rpx;
  margin-top: 14rpx;
}

.msg-chip {
  padding: 6rpx 14rpx;
  border-radius: 999rpx;
  font-size: 20rpx;
  line-height: 1.4;
}

.msg-chip.neutral {
  background: #f3f8f3;
  color: var(--operator-text-secondary, #5b6f62);
}

.msg-chip.accent {
  background: var(--operator-chip-bg, #ebf8ef);
}

.msg-chip.warning {
  background: rgba(245, 158, 11, 0.12);
  color: #d97706;
}

.msg-chip.danger {
  background: rgba(239, 68, 68, 0.12);
  color: #dc2626;
}

.msg-chip.success {
  background: rgba(34, 197, 94, 0.12);
  color: #15803d;
}

.msg-unread {
  position: absolute;
  top: 24rpx;
  right: 24rpx;
  width: 16rpx;
  height: 16rpx;
  border-radius: 50%;
  background: #ef4444;
}
</style>
