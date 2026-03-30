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
      >{{ f.label }}</view>

      <view class="filter-chip toggle" :class="{ active: onlyUnresolved }" @click="onlyUnresolved = !onlyUnresolved; loadData()">
        仅未解决
      </view>
    </view>

    <scroll-view scroll-y class="list-area" @scrolltolower="loadMore">
      <view v-if="loading && !items.length">
        <view v-for="i in 4" :key="i" class="alert-card skeleton"><view class="sk-line" /><view class="sk-line short" /></view>
      </view>

      <view
        v-for="item in filteredItems"
        :key="item.id"
        class="alert-card"
        :class="item.severity || 'medium'"
      >
        <view class="alert-header">
          <view class="severity-badge" :class="item.severity || 'medium'">
            {{ item.severity || '中' }}
          </view>
          <text class="alert-time">{{ formatRelativeTime(item.data_timestamp) }}</text>
        </view>
        <text class="alert-building">{{ item.building_id }}</text>
        <text class="alert-rule">{{ RULE_LABEL[item.rule_triggered] || item.rule_triggered }}</text>
        <text v-if="item.deviation_pct" class="alert-deviation">偏离 {{ item.deviation_pct.toFixed(1) }}%</text>
        <text v-if="item.message" class="alert-msg">{{ item.message }}</text>
        <view class="alert-status-row">
          <view class="alert-status-dot" :class="item.is_resolved ? 'resolved' : 'open'" />
          <text class="alert-status-text">{{ item.is_resolved ? '已解决' : '未解决' }}</text>
        </view>
      </view>

      <view v-if="!loading && !filteredItems.length" class="empty-state">
        <text class="empty-icon">✅</text>
        <text>暂无异常告警</text>
      </view>
    </scroll-view>

    <TabBar :tabs="OPERATOR_TABS" current="alerts" theme="operator" />
  </view>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import NavBar from '../../../components/NavBar.vue'
import TabBar from '../../../components/TabBar.vue'
import { useRouteGuard } from '../../../utils/route-guard'
import { OPERATOR_TABS } from '../../../constants/tabs'
import { OPERATOR_ROLES } from '../../../constants/roles'
import { RULE_LABEL } from '../../../constants/status'
import { dataApi, type AnomalyItem } from '../../../api/data'
import { formatRelativeTime } from '../../../utils/format'

useRouteGuard(OPERATOR_ROLES)

const filters = [
  { label: '全部', value: 'all' },
  { label: '高', value: 'high' },
  { label: '中', value: 'medium' },
  { label: '低', value: 'low' },
]

const activeFilter = ref('all')
const onlyUnresolved = ref(true)
const items = ref<AnomalyItem[]>([])
const loading = ref(false)

const filteredItems = computed(() => {
  if (activeFilter.value === 'all') return items.value
  return items.value.filter(i => i.severity === activeFilter.value)
})

async function loadData() {
  loading.value = true
  try {
    const res = await dataApi.recentAnomalies({
      hours: 168,
      only_unresolved: onlyUnresolved.value,
    })
    items.value = res.anomalies
  } catch { /* handled */ }
  finally { loading.value = false }
}

async function loadMore() {
  // 后端 /anomalies/recent 无分页，一次返回全部（最多 200）
}

onMounted(loadData)
</script>

<style lang="scss" scoped>
.page { background: #f0f2f8; min-height: 100vh; }

.filter-row {
  display: flex; gap: 16rpx; padding: 24rpx 32rpx; overflow-x: auto; flex-wrap: wrap;
}
.filter-chip {
  padding: 12rpx 28rpx; border-radius: 32rpx; background: #fff;
  font-size: 26rpx; color: #666; white-space: nowrap; border: 2rpx solid transparent;
  &.active { background: #3b6cf4; color: #fff; }
  &.toggle { border: 2rpx solid #d9d9d9; &.active { border-color: #3b6cf4; background: #e8effe; color: #3b6cf4; } }
}

.list-area { height: calc(100vh - 280rpx); padding: 0 32rpx; }

.alert-card {
  background: #fff; border-radius: 16rpx; padding: 28rpx; margin-bottom: 20rpx;
  border-left: 6rpx solid #e8ecf0;
  &.high   { border-left-color: #ff4d4f; }
  &.medium { border-left-color: #fa8c16; }
  &.low    { border-left-color: #52c41a; }
}
.alert-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 12rpx; }
.severity-badge {
  font-size: 22rpx; padding: 4rpx 14rpx; border-radius: 20rpx;
  &.high   { background: #fff2f0; color: #ff4d4f; }
  &.medium { background: #fff7e6; color: #fa8c16; }
  &.low    { background: #f6ffed; color: #52c41a; }
}
.alert-time { font-size: 22rpx; color: #aaa; }
.alert-building { display: block; font-size: 30rpx; font-weight: 700; color: #1a1a2e; margin-bottom: 4rpx; }
.alert-rule { display: block; font-size: 26rpx; color: #666; margin-bottom: 4rpx; }
.alert-deviation { display: block; font-size: 24rpx; color: #fa8c16; font-weight: 600; margin-bottom: 6rpx; }
.alert-msg { display: block; font-size: 24rpx; color: #999; line-height: 1.5; margin-bottom: 14rpx; }
.alert-status-row { display: flex; align-items: center; gap: 10rpx; }
.alert-status-dot {
  width: 12rpx; height: 12rpx; border-radius: 50%;
  &.open     { background: #fa8c16; }
  &.resolved { background: #52c41a; }
}
.alert-status-text { font-size: 22rpx; color: #aaa; }

.empty-state {
  display: flex; flex-direction: column; align-items: center; padding: 120rpx 0;
  color: #aaa; font-size: 28rpx; gap: 16rpx;
  .empty-icon { font-size: 80rpx; }
}

.skeleton { animation: shimmer 1.5s infinite; }
.sk-line { height: 28rpx; background: #f0f0f0; border-radius: 6rpx; margin-bottom: 16rpx; &.short { width: 60%; } }
@keyframes shimmer { 0%,100% { opacity: 1; } 50% { opacity: 0.5; } }
</style>
