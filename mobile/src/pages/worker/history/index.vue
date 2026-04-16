<template>
  <view class="page">
    <NavBar title="消息" bg-color="#E4EDB8" text-color="#5f7137">
      <template #right>
        <text class="nav-action" @click="loadData">↻</text>
      </template>
    </NavBar>

    <WorkerNotificationFeed />

    <scroll-view v-if="false" scroll-y class="page-scroll">
      <view class="card-grid">
        <view
          v-for="card in messageCards"
          :key="card.key"
          class="entry-card"
          @click="openEntry(card.key)"
        >
          <view class="entry-icon" :style="{ background: card.accent }">
            <text>{{ iconText(card.key) }}</text>
            <view v-if="card.count" class="entry-badge">{{ card.count > 99 ? '99+' : card.count }}</view>
          </view>
          <text class="entry-title">{{ card.label }}</text>
        </view>
      </view>

      <view class="feed-card">
        <view
          v-for="item in messageItems"
          :key="item.id"
          class="feed-item"
          @click="openMessage(item)"
        >
          <view class="feed-avatar" :class="item.category">
            <text>{{ avatarText(item.category) }}</text>
          </view>

          <view class="feed-main">
            <view class="feed-top">
              <text class="feed-title">{{ item.title }}</text>
              <text class="feed-time">{{ item.time }}</text>
            </view>
            <view class="feed-bottom">
              <text class="feed-excerpt">{{ item.excerpt }}</text>
              <view v-if="item.unread" class="feed-unread">{{ item.unread }}</view>
            </view>
          </view>
        </view>
      </view>

      <view class="worker-tabbar-spacer" />
    </scroll-view>

    <TabBar v-if="false" :tabs="WORKER_TABS" current="messages" theme="worker" />
  </view>
</template>

<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { onShow } from '@dcloudio/uni-app'
import NavBar from '../../../components/NavBar.vue'
import TabBar from '../../../components/TabBar.vue'
import WorkerNotificationFeed from '../../../components/WorkerNotificationFeed.vue'
import { incidentApi, type Incident } from '../../../api/incident'
import { useRouteGuard } from '../../../utils/route-guard'
import { WORKER_ROLES } from '../../../constants/roles'
import { WORKER_TABS } from '../../../constants/tabs'
import { getCache, setCache } from '../../../utils/cache'
import { useNotificationStore } from '../../../stores/notification'
import { getWorkerMessageCards, getWorkerMessageItems, type WorkerMessageItem } from '../../../utils/worker-ui'
import { subscribeWorkerOrdersUpdated } from '../../../utils/worker-sync'

useRouteGuard(WORKER_ROLES)

const incidents = ref<Incident[]>([])
const loading = ref(false)
const hasLoadedOnce = ref(false)
const notificationStore = useNotificationStore()
let unsubscribeWorkerSync: (() => void) | null = null

const messageCards = computed(() => getWorkerMessageCards(incidents.value))
const messageItems = computed(() => getWorkerMessageItems(incidents.value))

async function loadData() {
  void notificationStore.refresh({ page_size: 50 })
  const cached = getCache<Incident[]>('worker_messages')
  if (cached) incidents.value = cached
  loading.value = !cached

  try {
    const res = await incidentApi.list({
      workflow_status: 'dispatched,completed,closed,false_alarm,escalated',
      page: 1,
      page_size: 40,
    })
    incidents.value = res.incidents
    setCache('worker_messages', res.incidents)
    hasLoadedOnce.value = true
  } catch {
    if (!incidents.value.length) {
      uni.showToast({ title: '消息加载失败', icon: 'none' })
    }
  } finally {
    loading.value = false
  }
}

function iconText(key: string) {
  if (key === 'customer') return '客'
  if (key === 'notice') return '通'
  return '讯'
}

function avatarText(key: string) {
  if (key === 'customer') return '客'
  if (key === 'notice') return '单'
  return '资'
}

function openEntry(key: string) {
  if (key === 'customer' || key === 'notice') {
    uni.reLaunch({ url: '/pages/worker/active/index' })
    return
  }
  uni.navigateTo({ url: '/pages/worker/profile/notification' })
}

function openMessage(item: WorkerMessageItem) {
  if (item.ticketId && item.incidentId) {
    const readonlyQuery = item.readonly ? '&readonly=1' : ''
    uni.navigateTo({
      url: `/pages/worker/workorder-detail/index?incident_id=${item.incidentId}&ticket_id=${item.ticketId}${readonlyQuery}`,
    })
    return
  }
  uni.reLaunch({ url: '/pages/worker/active/index' })
}

onMounted(() => {
  unsubscribeWorkerSync = subscribeWorkerOrdersUpdated(async () => {
    await loadData()
  })
  void loadData()
})

onShow(() => {
  if (!hasLoadedOnce.value) return
  void loadData()
})

onUnmounted(() => {
  unsubscribeWorkerSync?.()
  unsubscribeWorkerSync = null
})
</script>

<style lang="scss" scoped>
.page {
  min-height: 100vh;
  background:
    radial-gradient(circle at top, rgba(174, 203, 150, 0.20), transparent 35%),
    linear-gradient(180deg, #f2fbe9 0%, #fbfdf8 100%);
}

.nav-action {
  font-size: 36rpx;
  color: #5f7137;
}

.page-scroll {
  height: calc(100vh - 132rpx);
  padding: 24rpx 24rpx 0;
  box-sizing: border-box;
}

.worker-tabbar-spacer {
  height: calc(276rpx + env(safe-area-inset-bottom, 0px));
}

.card-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 18rpx;
}

.entry-card,
.feed-card {
  background: rgba(255, 255, 255, 0.97);
  border-radius: 30rpx;
  box-shadow: 0 14rpx 36rpx rgba(181, 196, 118, 0.08);
}

.entry-card {
  min-height: 190rpx;
  padding: 24rpx 18rpx;
}

.entry-icon {
  position: relative;
  width: 92rpx;
  height: 92rpx;
  border-radius: 28rpx;
  display: flex;
  align-items: center;
  justify-content: center;

  text {
    font-size: 34rpx;
    color: #fff;
    font-weight: 700;
  }
}

.entry-badge {
  position: absolute;
  top: -10rpx;
  right: -10rpx;
  min-width: 34rpx;
  height: 34rpx;
  padding: 0 8rpx;
  border-radius: 17rpx;
  background: #ff4d4f;
  color: #fff;
  font-size: 18rpx;
  display: flex;
  align-items: center;
  justify-content: center;
  border: 4rpx solid #fff;
}

.entry-title {
  display: block;
  margin-top: 24rpx;
  font-size: 30rpx;
  color: #302825;
  font-weight: 700;
}

.feed-card {
  margin-top: 22rpx;
  padding: 10rpx 24rpx;
}

.feed-item {
  display: flex;
  gap: 18rpx;
  padding: 24rpx 0;
  border-bottom: 1rpx solid #e8eddf;
}

.feed-item:last-child {
  border-bottom: none;
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

.feed-avatar.customer {
  background: linear-gradient(135deg, #ff7b92, #ff5d7d);
}

.feed-avatar.notice {
  background: linear-gradient(135deg, #d6e29f, #b5c875);
}

.feed-avatar.bulletin {
  background: linear-gradient(135deg, #72b8ff, #4d93ff);
}

.feed-main {
  flex: 1;
  min-width: 0;
}

.feed-top,
.feed-bottom {
  display: flex;
  align-items: center;
}

.feed-top {
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

.feed-bottom {
  margin-top: 10rpx;
  gap: 12rpx;
}

.feed-excerpt {
  flex: 1;
  font-size: 24rpx;
  line-height: 1.6;
  color: #8f817b;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.feed-unread {
  min-width: 34rpx;
  height: 34rpx;
  padding: 0 8rpx;
  border-radius: 17rpx;
  background: #ff3b30;
  color: #fff;
  font-size: 18rpx;
  display: flex;
  align-items: center;
  justify-content: center;
}
</style>
