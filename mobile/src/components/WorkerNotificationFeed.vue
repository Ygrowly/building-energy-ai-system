<template>
  <view class="worker-notification-feed">
    <scroll-view scroll-y class="page-scroll">
      <view class="header-card">
        <view class="summary-pill">
          <text class="summary-label">未读工单通知</text>
          <text class="summary-value">{{ notificationStore.unreadCount }}</text>
        </view>
        <view
          class="summary-action"
          :class="{ disabled: notificationStore.unreadCount === 0 }"
          @click="markAllRead"
        >
          <text>全部已读</text>
        </view>
      </view>

      <view v-if="notificationStore.loading && !filteredItems.length" class="empty-card">
        <text class="empty-title">正在加载通知</text>
        <text class="empty-desc">稍后会自动同步最新工单状态</text>
      </view>

      <view v-else-if="!filteredItems.length" class="empty-card">
        <text class="empty-title">暂无工单通知</text>
        <text class="empty-desc">新的派单、协同和催办会出现在这里</text>
      </view>

      <view v-else class="feed-card">
        <view
          v-for="item in filteredItems"
          :key="item.recipient_id"
          class="feed-item"
          :class="[severityClass(item.severity), { unread: !item.read_at }]"
          @click="openNotification(item)"
        >
          <view class="feed-avatar" :class="severityClass(item.severity)">
            <text>{{ severityMark(item.severity) }}</text>
          </view>

          <view class="feed-main">
            <view class="feed-top">
              <text class="feed-title">{{ item.title }}</text>
              <text class="feed-time">{{ formatRelativeTime(item.created_at) }}</text>
            </view>
            <text class="feed-body">{{ item.body }}</text>
            <view class="feed-meta">
              <text class="feed-chip">{{ eventLabel(item.event_type) }}</text>
              <text v-if="item.related_ticket_id" class="feed-chip ticket">{{ item.related_ticket_id }}</text>
            </view>
          </view>

          <view v-if="!item.read_at" class="feed-unread"></view>
        </view>
      </view>

      <view class="worker-tabbar-spacer" />
    </scroll-view>

    <TabBar :tabs="WORKER_TABS" current="messages" theme="worker" />
  </view>
</template>

<script setup lang="ts">
import { computed, onMounted } from 'vue'
import TabBar from './TabBar.vue'
import { WORKER_TABS } from '../constants/tabs'
import { useNotificationStore } from '../stores/notification'
import type { NotificationItem } from '../api/notification'

const notificationStore = useNotificationStore()

const EVENT_LABELS: Record<string, string> = {
  assigned: '已派单',
  auto_assigned: '自动派单',
  accepted: '已接单',
  arrived: '已到场',
  started: '处理中',
  support_requested: '协同请求',
  support_resolved: '协同完成',
  rejected: '已拒单',
  cancelled: '已取消',
  transferred: '已转派',
  reminded: '调度催办',
  timeout_warning: '临近超时',
  timeout_overdue: '已超时',
  support_assigned: '协同指派',
  support_worker_accepted: '协同接单',
  support_worker_rejected: '协同拒单',
  worker_feedback: '维修反馈',
  close: '工单关闭',
  admin_override: '管理员处理',
  dispatch_hall_takeover_open: '接管大厅',
  dispatch_hall_support_open: '协同大厅',
  dispatch_hall_closed: '大厅关闭',
}

const filteredItems = computed(() => notificationStore.items)

function eventLabel(eventType: string) {
  return EVENT_LABELS[eventType] || eventType
}

function severityClass(severity?: string | null) {
  if (severity === 'danger') return 'danger'
  if (severity === 'warning') return 'warning'
  if (severity === 'success') return 'success'
  return 'info'
}

function severityMark(severity?: string | null) {
  if (severity === 'danger') return '急'
  if (severity === 'warning') return '警'
  if (severity === 'success') return '成'
  return '工'
}

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

async function openNotification(item: NotificationItem) {
  if (!item.read_at) {
    await notificationStore.markRead([item.recipient_id])
  }

  const hallEntryId = item.cta_params?.hall_entry_id
  const incidentId = item.cta_params?.incident_id
  const ticketId = item.cta_params?.ticket_id

  if (hallEntryId && ticketId) {
    uni.navigateTo({
      url: `/pages/worker/workorder-detail/index?hall_entry_id=${encodeURIComponent(String(hallEntryId))}&incident_id=${encodeURIComponent(String(incidentId || ''))}&ticket_id=${encodeURIComponent(String(ticketId))}`,
    })
    return
  }

  if (incidentId && ticketId) {
    uni.navigateTo({
      url: `/pages/worker/workorder-detail/index?incident_id=${encodeURIComponent(String(incidentId))}&ticket_id=${encodeURIComponent(String(ticketId))}`,
    })
    return
  }

  uni.reLaunch({ url: '/pages/worker/active/index' })
}

onMounted(() => {
  void refresh()
})

</script>

<style lang="scss" scoped>
.worker-notification-feed {
  min-height: 0;
}

.page-scroll {
  height: calc(100vh - 132rpx);
  padding: 24rpx 24rpx 0;
  box-sizing: border-box;
}

.worker-tabbar-spacer {
  height: calc(276rpx + env(safe-area-inset-bottom, 0px));
}

.header-card,
.feed-card,
.empty-card {
  background: rgba(255, 255, 255, 0.97);
  border-radius: 30rpx;
  box-shadow: 0 14rpx 36rpx rgba(181, 196, 118, 0.08);
}

.header-card {
  padding: 24rpx;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 20rpx;
}

.summary-pill {
  display: flex;
  flex-direction: column;
  gap: 8rpx;
}

.summary-label {
  font-size: 24rpx;
  color: #8d8e7d;
}

.summary-value {
  font-size: 46rpx;
  line-height: 1;
  color: #2d2623;
  font-weight: 700;
}

.summary-action {
  padding: 14rpx 24rpx;
  border-radius: 999rpx;
  background: linear-gradient(135deg, #d6e29f, #b5c875);

  text {
    color: #fff;
    font-size: 24rpx;
    font-weight: 700;
  }
}

.summary-action.disabled {
  opacity: 0.45;
}

.empty-card {
  margin-top: 22rpx;
  padding: 48rpx 32rpx;
  text-align: center;
}

.empty-title {
  display: block;
  font-size: 30rpx;
  color: #302825;
  font-weight: 700;
}

.empty-desc {
  display: block;
  margin-top: 12rpx;
  font-size: 24rpx;
  line-height: 1.6;
  color: #8f817b;
}

.feed-card {
  margin-top: 22rpx;
  padding: 10rpx 24rpx;
}

.feed-item {
  position: relative;
  display: flex;
  gap: 18rpx;
  padding: 24rpx 0;
  border-bottom: 1rpx solid #e8eddf;
}

.feed-item:last-child {
  border-bottom: none;
}

.feed-item.unread {
  background: linear-gradient(90deg, rgba(214, 226, 159, 0.12), transparent 48%);
}

.feed-avatar {
  width: 74rpx;
  height: 74rpx;
  border-radius: 50%;
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

.feed-avatar.info {
  background: linear-gradient(135deg, #d6e29f, #b5c875);
}

.feed-avatar.warning {
  background: linear-gradient(135deg, #ffc36a, #f59e0b);
}

.feed-avatar.danger {
  background: linear-gradient(135deg, #ff9b8b, #ef4444);
}

.feed-avatar.success {
  background: linear-gradient(135deg, #75d8ad, #34c759);
}

.feed-main {
  flex: 1;
  min-width: 0;
}

.feed-top {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 14rpx;
}

.feed-title {
  flex: 1;
  font-size: 30rpx;
  color: #312925;
  font-weight: 700;
}

.feed-time {
  font-size: 22rpx;
  color: #aaa09c;
}

.feed-body {
  display: block;
  margin-top: 10rpx;
  font-size: 24rpx;
  line-height: 1.6;
  color: #8f817b;
}

.feed-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 10rpx;
  margin-top: 12rpx;
}

.feed-chip {
  padding: 6rpx 16rpx;
  border-radius: 999rpx;
  background: #f4f8e6;
  color: #73854a;
  font-size: 20rpx;
  font-weight: 600;
}

.feed-chip.ticket {
  background: #eef4ff;
  color: #4d6cff;
}

.feed-unread {
  position: absolute;
  top: 32rpx;
  right: 0;
  width: 18rpx;
  height: 18rpx;
  border-radius: 50%;
  background: #ef4444;
  box-shadow: 0 0 0 6rpx rgba(239, 68, 68, 0.08);
}
</style>
