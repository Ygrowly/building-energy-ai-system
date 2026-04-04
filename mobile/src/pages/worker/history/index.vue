<template>
  <view class="page">
    <NavBar title="历史记录" bg-color="#0f3d2e" />

    <!-- 统计卡 -->
    <view class="stats-card" v-if="stats.total > 0">
      <view class="stat">
        <text class="stat-n">{{ stats.total }}</text>
        <text class="stat-l">累计工单</text>
      </view>
      <view class="stat-sep" />
      <view class="stat">
        <text class="stat-n green">{{ stats.fixed }}</text>
        <text class="stat-l">已修复</text>
      </view>
      <view class="stat-sep" />
      <view class="stat">
        <text class="stat-n orange">{{ stats.falseAlarm }}</text>
        <text class="stat-l">误报</text>
      </view>
    </view>

    <scroll-view scroll-y class="list-area" @scrolltolower="loadMore">
      <view v-if="loading && !incidents.length">
        <view v-for="i in 4" :key="i" class="wo-skeleton" />
      </view>

      <view
        v-for="incident in incidents"
        :key="incident.id"
        class="history-card"
        :class="incident.current_work_order?.status"
        @click="openDetail(incident)"
      >
        <view class="hc-header">
          <text class="hc-date">{{ formatDate(incident.updated_at) }}</text>
          <view class="feedback-badge" :class="incident.current_work_order?.status">
            {{ WORKER_RESULT_LABEL[incident.current_work_order?.worker_result ?? ''] || '处理完成' }}
          </view>
        </view>

        <text class="hc-building">{{ incident.building_id }}</text>
        <text class="hc-desc">{{ incident.summary_text }}</text>
        <text v-if="incident.current_work_order?.worker_notes" class="hc-note">备注：{{ incident.current_work_order.worker_notes }}</text>
      </view>

      <view v-if="!loading && !incidents.length" class="empty-state">
        <image class="empty-icon" src="/static/icons/tab-history.svg" mode="aspectFit" />
        <text>暂无历史记录</text>
      </view>

      <view v-if="noMore && incidents.length > 0" class="load-end">没有更多了</view>
    </scroll-view>

    <TabBar :tabs="WORKER_TABS" current="history" theme="worker" />
  </view>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import NavBar from '../../../components/NavBar.vue'
import TabBar from '../../../components/TabBar.vue'
import { useRouteGuard } from '../../../utils/route-guard'
import { WORKER_TABS } from '../../../constants/tabs'
import { WORKER_ROLES } from '../../../constants/roles'
import { WORKER_RESULT_LABEL } from '../../../constants/status'
import { formatDate } from '../../../utils/format'
import { incidentApi, type Incident } from '../../../api/incident'
import { getCache, setCache } from '../../../utils/cache'

useRouteGuard(WORKER_ROLES)

const incidents = ref<Incident[]>([])
const loading = ref(false)
const noMore = ref(false)
const page = ref(1)
const PAGE_SIZE = 15

const stats = computed(() => ({
  total:      incidents.value.length,
  fixed:      incidents.value.filter(o => o.current_work_order?.worker_result === 'fixed').length,
  falseAlarm: incidents.value.filter(o => o.current_work_order?.worker_result === 'false_alarm').length,
}))

async function loadData() {
  const cached = getCache<Incident[]>('worker_history')
  if (cached) incidents.value = cached
  loading.value = !cached
  try {
    const res = await incidentApi.list({
      workflow_status: 'completed,closed,false_alarm',
      page: 1,
      page_size: PAGE_SIZE,
    })
    incidents.value = res.incidents
    setCache('worker_history', res.incidents)
    if (res.incidents.length < PAGE_SIZE) noMore.value = true
  } catch { /* handled */ }
  finally { loading.value = false }
}

async function loadMore() {
  if (loading.value || noMore.value) return
  page.value++
  try {
    const res = await incidentApi.list({
      workflow_status: 'completed,closed,false_alarm',
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
    url: `/pages/worker/workorder-detail/index?incident_id=${incident.incident_id}&ticket_id=${ticketId}&readonly=1`,
  })
}

onMounted(loadData)
</script>

<style lang="scss" scoped>
.page { background: #f0f5f2; min-height: 100vh; }

.stats-card {
  display: flex;
  align-items: center;
  justify-content: space-around;
  background: linear-gradient(135deg, #0f3d2e, #00b96b);
  padding: 28rpx 32rpx;
}

.stat { display: flex; flex-direction: column; align-items: center; }

.stat-n {
  font-size: 44rpx;
  font-weight: 700;
  color: #fff;

  &.green  { color: #b7eb8f; }
  &.orange { color: #ffd591; }
}

.stat-l { font-size: 22rpx; color: rgba(255,255,255,0.7); margin-top: 4rpx; }

.stat-sep {
  width: 1rpx;
  height: 48rpx;
  background: rgba(255,255,255,0.2);
}

.list-area {
  height: calc(100vh - 300rpx);
  padding: 20rpx 32rpx;
}

.history-card {
  background: #fff;
  border-radius: 16rpx;
  padding: 24rpx;
  margin-bottom: 16rpx;
  border-left: 6rpx solid #e0e0e0;

  &.completed   { border-left-color: #00b96b; }
  &.false_alarm { border-left-color: #ff4d4f; }
  &.closed      { border-left-color: #3b6cf4; }
}

.hc-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 12rpx;
}

.hc-date { font-size: 22rpx; color: #aaa; }

.feedback-badge {
  font-size: 22rpx;
  padding: 4rpx 14rpx;
  border-radius: 16rpx;

  &.completed   { background: #f0fff8; color: #00b96b; }
  &.false_alarm { background: #fff2f0; color: #ff4d4f; }
  &.closed      { background: #f0f5ff; color: #3b6cf4; }
}

.hc-building {
  display: block;
  font-size: 28rpx;
  font-weight: 700;
  color: #1a1a2e;
  margin-bottom: 4rpx;
}

.hc-desc {
  display: block;
  font-size: 24rpx;
  color: #666;
  margin-bottom: 8rpx;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.hc-note {
  font-size: 22rpx;
  color: #aaa;
  font-style: italic;
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
  height: 120rpx;
  background: linear-gradient(90deg, #e8f5f0, #d4ede4, #e8f5f0);
  border-radius: 16rpx;
  margin-bottom: 16rpx;
}

.load-end {
  text-align: center;
  font-size: 24rpx;
  color: #ccc;
  padding: 20rpx;
}
</style>
