<template>
  <view class="page">
    <NavBar title="异常告警" bg-color="#1a1a2e" />

    <!-- 筛选栏 -->
    <view class="filter-row">
      <view
        v-for="f in filters"
        :key="f.value"
        class="filter-chip"
        :class="{ active: activeFilter === f.value }"
        @click="activeFilter = f.value; loadData()"
      >
        {{ f.label }}
      </view>
    </view>

    <!-- 列表 -->
    <scroll-view scroll-y class="list-area" @scrolltolower="loadMore">
      <view v-if="loading && !items.length">
        <view v-for="i in 4" :key="i" class="alert-card skeleton">
          <view class="sk-line" />
          <view class="sk-line short" />
        </view>
      </view>

      <view
        v-for="item in items"
        :key="item.id"
        class="alert-card"
        :class="item.severity"
      >
        <view class="alert-header">
          <view class="severity-badge" :class="item.severity">
            {{ severityText(item.severity) }}
          </view>
          <text class="alert-time">{{ formatTime(item.detected_at) }}</text>
        </view>
        <text class="alert-building">{{ item.building_name || item.building_id }}</text>
        <text class="alert-type">{{ item.anomaly_type }}</text>
        <text class="alert-desc">{{ item.description }}</text>
        <view class="alert-status-row">
          <view class="alert-status-dot" :class="item.status" />
          <text class="alert-status-text">{{ anomalyStatusText(item.status) }}</text>
        </view>
      </view>

      <view v-if="!loading && !items.length" class="empty-state">
        <text class="empty-icon">✅</text>
        <text>暂无{{ activeFilter !== 'all' ? severityText(activeFilter) : '' }}异常</text>
      </view>

      <view v-if="loadingMore" class="loading-more">加载中...</view>
      <view v-if="noMore && items.length > 0" class="loading-more">没有更多了</view>
    </scroll-view>

    <TabBar :tabs="operatorTabs" current="alerts" theme="operator" />
  </view>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import NavBar from '../../../components/NavBar.vue'
import TabBar, { type TabItem } from '../../../components/TabBar.vue'
import { dataApi, type AnomalyEvent } from '../../../api/data'

const operatorTabs: TabItem[] = [
  { name: 'overview',   label: '总览', icon: '📊', path: '/pages/operator/overview/index' },
  { name: 'alerts',     label: '告警', icon: '🔔', path: '/pages/operator/alerts/index' },
  { name: 'workorders', label: '工单', icon: '📋', path: '/pages/operator/workorders/index' },
  { name: 'profile',    label: '我的', icon: '👤', path: '/pages/operator/profile/index' },
]

const filters = [
  { label: '全部', value: 'all' },
  { label: '高', value: 'high' },
  { label: '中', value: 'medium' },
  { label: '低', value: 'low' },
]

const activeFilter = ref('all')
const items = ref<AnomalyEvent[]>([])
const loading = ref(false)
const loadingMore = ref(false)
const noMore = ref(false)
const page = ref(1)
const PAGE_SIZE = 15

async function loadData() {
  loading.value = true
  page.value = 1
  noMore.value = false
  try {
    const params = {
      page: 1,
      page_size: PAGE_SIZE,
      ...(activeFilter.value !== 'all' ? { severity: activeFilter.value } : {}),
    }
    const res = await dataApi.anomalies(params)
    items.value = res.items
    if (res.items.length < PAGE_SIZE) noMore.value = true
  } catch { /* handled */ }
  finally { loading.value = false }
}

async function loadMore() {
  if (loadingMore.value || noMore.value) return
  loadingMore.value = true
  page.value++
  try {
    const res = await dataApi.anomalies({
      page: page.value,
      page_size: PAGE_SIZE,
      ...(activeFilter.value !== 'all' ? { severity: activeFilter.value } : {}),
    })
    items.value.push(...res.items)
    if (res.items.length < PAGE_SIZE) noMore.value = true
  } catch { page.value-- }
  finally { loadingMore.value = false }
}

function severityText(s: string) {
  return { high: '高优先', medium: '中优先', low: '低优先' }[s] ?? s
}
function anomalyStatusText(s: string) {
  return { open: '未处理', work_ordered: '已建工单', resolved: '已解决' }[s] ?? s
}
function formatTime(iso: string) {
  const d = new Date(iso)
  const diff = (Date.now() - d.getTime()) / 1000
  if (diff < 3600) return `${Math.floor(diff / 60)}分钟前`
  if (diff < 86400) return `${Math.floor(diff / 3600)}小时前`
  return `${d.getMonth() + 1}/${d.getDate()}`
}

onMounted(loadData)
</script>

<style lang="scss" scoped>
.page { background: #f0f2f8; min-height: 100vh; }

.filter-row {
  display: flex;
  gap: 16rpx;
  padding: 24rpx 32rpx;
  overflow-x: auto;

  &::-webkit-scrollbar { display: none; }
}

.filter-chip {
  padding: 12rpx 28rpx;
  border-radius: 32rpx;
  background: #fff;
  font-size: 26rpx;
  color: #666;
  white-space: nowrap;
  border: 2rpx solid transparent;

  &.active {
    background: #3b6cf4;
    color: #fff;
    border-color: #3b6cf4;
  }
}

.list-area {
  height: calc(100vh - 280rpx);
  padding: 0 32rpx;
}

.alert-card {
  background: #fff;
  border-radius: 16rpx;
  padding: 28rpx;
  margin-bottom: 20rpx;
  border-left: 6rpx solid #e8ecf0;

  &.high   { border-left-color: #ff4d4f; }
  &.medium { border-left-color: #fa8c16; }
  &.low    { border-left-color: #52c41a; }
}

.alert-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 12rpx;
}

.severity-badge {
  font-size: 22rpx;
  padding: 4rpx 14rpx;
  border-radius: 20rpx;

  &.high   { background: #fff2f0; color: #ff4d4f; }
  &.medium { background: #fff7e6; color: #fa8c16; }
  &.low    { background: #f6ffed; color: #52c41a; }
}

.alert-time { font-size: 22rpx; color: #aaa; }

.alert-building {
  display: block;
  font-size: 30rpx;
  font-weight: 700;
  color: #1a1a2e;
  margin-bottom: 4rpx;
}

.alert-type {
  display: block;
  font-size: 26rpx;
  color: #666;
  margin-bottom: 8rpx;
}

.alert-desc {
  display: block;
  font-size: 24rpx;
  color: #999;
  line-height: 1.5;
  margin-bottom: 14rpx;
}

.alert-status-row {
  display: flex;
  align-items: center;
  gap: 10rpx;
}

.alert-status-dot {
  width: 12rpx;
  height: 12rpx;
  border-radius: 50%;

  &.open         { background: #fa8c16; }
  &.work_ordered { background: #3b6cf4; }
  &.resolved     { background: #52c41a; }
}

.alert-status-text { font-size: 22rpx; color: #aaa; }

.empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  padding: 120rpx 0;
  color: #aaa;
  font-size: 28rpx;
  gap: 16rpx;

  .empty-icon { font-size: 80rpx; }
}

.loading-more {
  text-align: center;
  font-size: 24rpx;
  color: #ccc;
  padding: 20rpx;
}

.sk-line {
  height: 28rpx;
  background: #f0f0f0;
  border-radius: 6rpx;
  margin-bottom: 16rpx;

  &.short { width: 60%; }
}

.skeleton {
  animation: shimmer 1.5s infinite;
}

@keyframes shimmer {
  0%, 100% { opacity: 1; }
  50%       { opacity: 0.5; }
}
</style>
