<template>
  <view class="page">
    <NavBar title="待处理工单" bg-color="#0f3d2e">
      <template #right>
        <text class="refresh-icon" @click="loadData">↻</text>
      </template>
    </NavBar>

    <!-- 统计横条 -->
    <view class="stat-row">
      <view class="stat-item">
        <text class="stat-num high">{{ counts.high }}</text>
        <text class="stat-label">高优先</text>
      </view>
      <view class="stat-sep" />
      <view class="stat-item">
        <text class="stat-num medium">{{ counts.medium }}</text>
        <text class="stat-label">中优先</text>
      </view>
      <view class="stat-sep" />
      <view class="stat-item">
        <text class="stat-num low">{{ counts.low }}</text>
        <text class="stat-label">低优先</text>
      </view>
    </view>

    <!-- 优先级筛选 -->
    <view class="filter-row">
      <view
        v-for="f in filters"
        :key="f.value"
        class="filter-chip"
        :class="{ active: activeFilter === f.value }"
        @click="activeFilter = f.value"
      >{{ f.label }}</view>
    </view>

    <scroll-view scroll-y class="list-area" @scrolltolower="loadMore">
      <view v-if="loading && !incidents.length">
        <view v-for="i in 3" :key="i" class="wo-skeleton" />
      </view>

      <IncidentReviewCard
        v-for="incident in filteredIncidents"
        :key="incident.id"
        :incident="incident"
        @click="openDetail"
      />

      <view v-if="!loading && !filteredIncidents.length" class="empty-state">
        <image class="empty-icon" src="/static/icons/tab-wrench.svg" mode="aspectFit" />
        <text>暂无待处理工单</text>
      </view>

      <view v-if="noMore && incidents.length > 0" class="load-end">没有更多了</view>
    </scroll-view>

    <TabBar :tabs="WORKER_TABS" current="pending" theme="worker" />
  </view>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import NavBar from '../../../components/NavBar.vue'
import TabBar from '../../../components/TabBar.vue'
import IncidentReviewCard from '../../../components/IncidentReviewCard.vue'
import { useRouteGuard } from '../../../utils/route-guard'
import { WORKER_TABS } from '../../../constants/tabs'
import { WORKER_ROLES } from '../../../constants/roles'
import { incidentApi, type Incident } from '../../../api/incident'
import { getCache, setCache } from '../../../utils/cache'

useRouteGuard(WORKER_ROLES)

const filters = [
  { label: '全部',   value: 'all' },
  { label: '高优先', value: 'high' },
  { label: '中优先', value: 'medium' },
  { label: '低优先', value: 'low' },
]

const activeFilter = ref('all')
const incidents = ref<Incident[]>([])
const loading = ref(false)
const noMore = ref(false)
const page = ref(1)
const PAGE_SIZE = 15

const counts = computed(() => ({
  high:   incidents.value.filter(o => o.priority === 'high').length,
  medium: incidents.value.filter(o => o.priority === 'medium').length,
  low:    incidents.value.filter(o => o.priority === 'low').length,
}))

const filteredIncidents = computed(() => {
  if (activeFilter.value === 'all') return incidents.value
  return incidents.value.filter(o => o.priority === activeFilter.value)
})

async function loadData() {
  const cached = getCache<Incident[]>('worker_pending')
  if (cached) incidents.value = cached
  loading.value = !cached
  page.value = 1
  noMore.value = false
  try {
    const res = await incidentApi.list({
      workflow_status: 'dispatched',
      page: 1,
      page_size: PAGE_SIZE,
    })
    incidents.value = res.incidents
    setCache('worker_pending', res.incidents)
    if (res.incidents.length < PAGE_SIZE) noMore.value = true
  } catch { /* handled */ }
  finally { loading.value = false }
}

async function loadMore() {
  if (loading.value || noMore.value) return
  page.value++
  try {
    const res = await incidentApi.list({
      workflow_status: 'dispatched',
      page: page.value,
      page_size: PAGE_SIZE,
    })
    incidents.value.push(...res.incidents)
    if (res.incidents.length < PAGE_SIZE) noMore.value = true
  } catch { page.value-- }
}

function openDetail(incident: Incident) {
  const ticketId = incident.current_work_order?.ticket_id
  if (!ticketId) return
  uni.navigateTo({
    url: `/pages/worker/workorder-detail/index?incident_id=${incident.incident_id}&ticket_id=${ticketId}`,
  })
}

onMounted(loadData)
</script>

<style lang="scss" scoped>
.page { background: #f0f5f2; min-height: 100vh; }

.refresh-icon { font-size: 40rpx; color: rgba(255,255,255,0.8); }

.stat-row {
  display: flex;
  align-items: center;
  background: linear-gradient(135deg, #0f3d2e, #00b96b);
  padding: 24rpx 32rpx;
  justify-content: space-around;
}

.stat-item {
  display: flex;
  flex-direction: column;
  align-items: center;
}

.stat-num {
  font-size: 44rpx;
  font-weight: 700;
  color: #fff;

  &.high   { color: #ffa39e; }
  &.medium { color: #ffd591; }
  &.low    { color: #b7eb8f; }
}

.stat-label { font-size: 22rpx; color: rgba(255,255,255,0.7); margin-top: 4rpx; }

.stat-sep {
  width: 1rpx;
  height: 48rpx;
  background: rgba(255,255,255,0.2);
}

.filter-row {
  display: flex;
  gap: 16rpx;
  padding: 20rpx 32rpx;
  background: #fff;
  border-bottom: 1rpx solid #e8ecf0;
}

.filter-chip {
  padding: 10rpx 24rpx;
  border-radius: 32rpx;
  background: #f5f5f5;
  font-size: 24rpx;
  color: #666;

  &.active { background: #00b96b; color: #fff; }
}

.list-area {
  height: calc(100vh - 400rpx);
  padding: 20rpx 32rpx;
}

.empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  padding: 120rpx 0;
  gap: 16rpx;
  color: #aaa;
  font-size: 28rpx;

  .empty-icon { width: 88rpx; height: 88rpx; opacity: 0.4; }
}

.wo-skeleton {
  height: 180rpx;
  background: linear-gradient(90deg, #e8f5f0, #d4ede4, #e8f5f0);
  border-radius: 16rpx;
  margin-bottom: 20rpx;
}

.load-end {
  text-align: center;
  font-size: 24rpx;
  color: #ccc;
  padding: 20rpx;
}
</style>
