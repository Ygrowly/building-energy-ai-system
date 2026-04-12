<template>
  <div class="notification-panel">
    <div class="panel-toolbar">
      <div class="toolbar-filters">
        <label class="toolbar-field">
          <span>建筑</span>
          <select v-model="buildingId">
            <option
              v-for="option in BUILDING_OPTIONS"
              :key="option.value"
              :value="option.value"
            >
              {{ option.label }}
            </option>
          </select>
        </label>
        <label class="toolbar-field">
          <span>时间</span>
          <select v-model.number="hours">
            <option
              v-for="option in TIME_OPTIONS"
              :key="option.value"
              :value="option.value"
            >
              {{ option.label }}
            </option>
          </select>
        </label>
      </div>
      <div class="toolbar-actions">
        <button class="ghost-btn" type="button" @click="refresh">
          刷新
        </button>
        <button
          class="primary-btn"
          type="button"
          :disabled="notificationStore.unreadCount === 0"
          @click="markAllRead"
        >
          全部已读
        </button>
      </div>
    </div>

    <div v-if="notificationStore.loading && !notificationStore.items.length" class="empty-state">
      正在加载工单通知
    </div>

    <div v-else-if="!filteredItems.length" class="empty-state">
      {{ notificationStore.items.length ? '当前筛选下暂无通知' : '暂无工单通知' }}
    </div>

    <div v-else class="notification-list">
      <button
        v-for="item in filteredItems"
        :key="item.recipient_id"
        class="notification-item"
        :class="[`severity-${item.severity || 'info'}`, { unread: !item.read_at }]"
        type="button"
        @click="openItem(item)"
      >
        <div class="item-main">
          <div class="item-head">
            <p class="item-title">{{ item.title }}</p>
            <span class="item-time">{{ formatRelativeTime(item.created_at) }}</span>
          </div>
          <p class="item-body">{{ item.body }}</p>
          <div class="item-meta">
            <span class="meta-chip">{{ eventLabel(item.event_type) }}</span>
            <span v-if="extractBuildingId(item)" class="meta-chip meta-building">
              {{ buildingLabel(extractBuildingId(item)) }}
            </span>
            <span v-if="item.related_ticket_id" class="meta-chip meta-ticket">
              {{ item.related_ticket_id }}
            </span>
          </div>
        </div>
        <span v-if="!item.read_at" class="unread-dot"></span>
      </button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ALL_BUILDING_FILTER_OPTIONS, getBuildingLabel } from '@/constants/buildings'
import { useNotificationStore } from '@/stores/notificationCenterStore'
import type { NotificationItem } from '@/api/notifications'

const router = useRouter()
const notificationStore = useNotificationStore()

const BUILDING_OPTIONS = ALL_BUILDING_FILTER_OPTIONS
const TIME_OPTIONS = [
  { value: 0, label: '全部时间' },
  { value: 24, label: '近 24 小时' },
  { value: 168, label: '近 7 天' },
  { value: 720, label: '近 30 天' },
]

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

const buildingId = ref('all')
const hours = ref(0)

const filteredItems = computed(() => notificationStore.items.filter((item) => {
  const itemBuildingId = extractBuildingId(item) || ''
  if (buildingId.value !== 'all' && itemBuildingId !== buildingId.value) {
    return false
  }
  if (hours.value > 0) {
    if (!item.created_at) {
      return false
    }
    const cutoff = Date.now() - hours.value * 3600 * 1000
    if (new Date(item.created_at).getTime() < cutoff) {
      return false
    }
  }
  return true
}))

function extractBuildingId(item: NotificationItem) {
  const value = item.payload?.building_id
  if (typeof value === 'string') return value
  if (typeof value === 'number') return String(value)
  return null
}

function buildingLabel(value?: string | null) {
  return getBuildingLabel(value, '未知楼栋')
}

function eventLabel(eventType: string) {
  return EVENT_LABELS[eventType] || eventType
}

function formatRelativeTime(value?: string | null) {
  if (!value) return '--'
  const target = new Date(value).getTime()
  if (!Number.isFinite(target)) return value
  const diff = Date.now() - target
  if (diff < 60_000) return '刚刚'
  if (diff < 3_600_000) return `${Math.max(1, Math.floor(diff / 60_000))} 分钟前`
  if (diff < 86_400_000) return `${Math.max(1, Math.floor(diff / 3_600_000))} 小时前`
  if (diff < 7 * 86_400_000) return `${Math.max(1, Math.floor(diff / 86_400_000))} 天前`
  return value.slice(0, 16).replace('T', ' ')
}

async function refresh() {
  await notificationStore.refresh({ page_size: 50 })
}

async function markAllRead() {
  await notificationStore.markAllRead('workorder')
}

async function openItem(item: NotificationItem) {
  if (!item.read_at) {
    await notificationStore.markRead([item.recipient_id])
  }

  if (item.cta_type === 'open_hall_entry') {
    const hallEntryId = item.cta_params?.hall_entry_id
    await router.push({
      path: '/workorders',
      query: {
        active_tab: 'shared_hall',
        hall_entry_id: hallEntryId == null ? undefined : String(hallEntryId),
      },
    })
    return
  }

  if (item.related_ticket_id) {
    await router.push({
      path: '/workorders',
      query: {
        active_tab: 'all',
        focus_ticket: String(item.related_ticket_id),
      },
    })
    return
  }

  await router.push('/workorders')
}

onMounted(() => {
  if (!notificationStore.items.length) {
    void refresh()
  }
})
</script>

<style scoped>
.notification-panel {
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.panel-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
}

.toolbar-filters,
.toolbar-actions {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}

.toolbar-field {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 12px;
  color: #6b7280;
}

.toolbar-field select {
  min-width: 112px;
  border: 1px solid rgba(17, 24, 39, 0.08);
  border-radius: 10px;
  padding: 7px 10px;
  background: #fff;
  color: #111827;
}

.ghost-btn,
.primary-btn {
  border: 0;
  border-radius: 999px;
  padding: 8px 14px;
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
}

.ghost-btn {
  background: rgba(15, 23, 42, 0.06);
  color: #475569;
}

.primary-btn {
  background: #2563eb;
  color: #fff;
}

.primary-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.empty-state {
  border: 1px dashed rgba(100, 116, 139, 0.25);
  border-radius: 14px;
  padding: 28px 16px;
  text-align: center;
  color: #94a3b8;
  background: rgba(248, 250, 252, 0.9);
}

.notification-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.notification-item {
  position: relative;
  display: flex;
  align-items: flex-start;
  gap: 12px;
  width: 100%;
  text-align: left;
  border: 1px solid rgba(15, 23, 42, 0.06);
  border-radius: 14px;
  padding: 14px 16px;
  background: #fff;
  cursor: pointer;
}

.notification-item.unread {
  border-color: rgba(37, 99, 235, 0.18);
  box-shadow: 0 0 0 1px rgba(37, 99, 235, 0.06);
}

.notification-item.severity-warning {
  background: linear-gradient(180deg, rgba(255, 251, 235, 0.85), #fff);
}

.notification-item.severity-danger {
  background: linear-gradient(180deg, rgba(254, 242, 242, 0.9), #fff);
}

.notification-item.severity-success {
  background: linear-gradient(180deg, rgba(240, 253, 244, 0.9), #fff);
}

.item-main {
  flex: 1;
  min-width: 0;
}

.item-head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 12px;
}

.item-title {
  margin: 0;
  font-size: 14px;
  font-weight: 700;
  color: #111827;
}

.item-time {
  flex-shrink: 0;
  font-size: 12px;
  color: #94a3b8;
}

.item-body {
  margin: 6px 0 0;
  color: #475569;
  font-size: 13px;
  line-height: 1.5;
}

.item-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 10px;
}

.meta-chip {
  border-radius: 999px;
  padding: 3px 9px;
  font-size: 11px;
  font-weight: 600;
  background: rgba(15, 23, 42, 0.06);
  color: #475569;
}

.meta-building {
  background: rgba(34, 197, 94, 0.1);
  color: #15803d;
}

.meta-ticket {
  background: rgba(37, 99, 235, 0.1);
  color: #1d4ed8;
}

.unread-dot {
  width: 10px;
  height: 10px;
  margin-top: 6px;
  border-radius: 50%;
  background: #ef4444;
  flex-shrink: 0;
}

:root[data-theme='dark'] .toolbar-field select,
:root[data-theme='dark'] .notification-item {
  background: rgba(255, 255, 255, 0.04);
  border-color: rgba(255, 255, 255, 0.08);
}

:root[data-theme='dark'] .item-title {
  color: #f8fafc;
}

:root[data-theme='dark'] .item-body {
  color: rgba(255, 255, 255, 0.7);
}

:root[data-theme='dark'] .empty-state {
  background: rgba(255, 255, 255, 0.03);
  border-color: rgba(255, 255, 255, 0.1);
}
</style>
