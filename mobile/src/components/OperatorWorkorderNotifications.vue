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
        v-for="item in notificationStore.items"
        :key="item.recipient_id"
        class="msg-item clickable"
        :class="[severityClass(item.severity), { unread: !item.read_at }]"
        @click="openNotification(item)"
      >
        <view class="msg-icon workorder" :class="severityClass(item.severity)">
          <text>{{ severityMark(item.severity) }}</text>
        </view>
        <view class="msg-body">
          <text class="msg-title">{{ item.title }}</text>
          <text class="msg-sub">{{ item.body }}</text>
          <view class="msg-meta">
            <text class="msg-tag">{{ eventLabel(item.event_type) }}</text>
            <text v-if="item.related_ticket_id" class="msg-tag ticket">{{ item.related_ticket_id }}</text>
            <text class="msg-time">{{ formatRelativeTime(item.created_at) }}</text>
          </view>
        </view>
        <view v-if="!item.read_at" class="msg-unread"></view>
      </view>
    </view>
  </scroll-view>
</template>

<script setup lang="ts">
import { computed, onMounted } from 'vue'
import { useNotificationStore } from '../stores/notification'
import type { NotificationItem } from '../api/notification'

const props = withDefaults(defineProps<{
  withTabBar?: boolean
}>(), {
  withTabBar: false,
})

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

const listAreaStyle = computed(() => ({
  paddingBottom: props.withTabBar ? 'calc(env(safe-area-inset-bottom, 0px) + 140rpx)' : '32rpx',
}))

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
  background: #fff;
  border-radius: 24rpx;
}

.toolbar-card {
  margin-bottom: 18rpx;
  padding: 24rpx;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 20rpx;
}

.toolbar-copy {
  display: flex;
  flex-direction: column;
  gap: 8rpx;
}

.toolbar-label {
  font-size: 22rpx;
  color: #9ca3af;
}

.toolbar-value {
  font-size: 42rpx;
  color: #111827;
  font-weight: 700;
}

.toolbar-actions {
  display: flex;
  gap: 12rpx;
}

.toolbar-btn {
  padding: 14rpx 22rpx;
  border-radius: 999rpx;

  text {
    font-size: 22rpx;
    font-weight: 700;
  }
}

.toolbar-btn.ghost {
  background: #eef2f7;

  text {
    color: #475569;
  }
}

.toolbar-btn.primary {
  background: linear-gradient(135deg, #3b82f6, #2563eb);

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
}

.empty-check {
  display: block;
  font-size: 44rpx;
  color: #60a5fa;
}

.empty-text {
  display: block;
  margin-top: 10rpx;
  font-size: 26rpx;
  color: #94a3b8;
}

.message-list {
  display: flex;
  flex-direction: column;
  gap: 12rpx;
}

.msg-item {
  position: relative;
  display: flex;
  align-items: flex-start;
  gap: 20rpx;
  padding: 22rpx 24rpx;
}

.msg-item.unread {
  box-shadow: 0 0 0 2rpx rgba(59, 130, 246, 0.12);
}

.msg-icon {
  width: 64rpx;
  height: 64rpx;
  border-radius: 18rpx;
  display: flex;
  align-items: center;
  justify-content: center;

  text {
    font-size: 28rpx;
    color: #fff;
    font-weight: 700;
  }
}

.msg-icon.info {
  background: linear-gradient(135deg, #93c5fd, #3b82f6);
}

.msg-icon.warning {
  background: linear-gradient(135deg, #fdba74, #f59e0b);
}

.msg-icon.danger {
  background: linear-gradient(135deg, #fca5a5, #ef4444);
}

.msg-icon.success {
  background: linear-gradient(135deg, #86efac, #22c55e);
}

.msg-body {
  flex: 1;
  min-width: 0;
}

.msg-title {
  display: block;
  font-size: 28rpx;
  font-weight: 700;
  color: #111827;
}

.msg-sub {
  display: block;
  margin-top: 8rpx;
  font-size: 24rpx;
  line-height: 1.6;
  color: #64748b;
}

.msg-meta {
  display: flex;
  align-items: center;
  gap: 10rpx;
  flex-wrap: wrap;
  margin-top: 12rpx;
}

.msg-tag,
.msg-time {
  font-size: 20rpx;
}

.msg-tag {
  padding: 4rpx 14rpx;
  border-radius: 999rpx;
  background: #eef2ff;
  color: #4f46e5;
}

.msg-tag.ticket {
  background: #e0f2fe;
  color: #0369a1;
}

.msg-time {
  color: #94a3b8;
}

.msg-unread {
  position: absolute;
  top: 28rpx;
  right: 24rpx;
  width: 16rpx;
  height: 16rpx;
  border-radius: 50%;
  background: #ef4444;
}
</style>
