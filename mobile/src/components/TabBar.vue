<!--
  自定义底部导航栏
  通过 tabs prop 传入标签配置，current 绑定当前页
-->
<template>
  <view class="tab-bar" :class="theme">
    <view
      v-for="tab in tabs"
      :key="tab.name"
      class="tab-item"
      :class="{ active: current === tab.name }"
      @click="onTab(tab)"
    >
      <text class="tab-icon">{{ tab.icon }}</text>
      <text class="tab-label">{{ tab.label }}</text>
    </view>
  </view>
</template>

<script setup lang="ts">
export interface TabItem {
  name: string
  label: string
  icon: string
  path: string
}

const props = defineProps<{
  tabs: TabItem[]
  current: string
  theme?: 'operator' | 'worker'
}>()

function onTab(tab: TabItem) {
  if (tab.name === props.current) return
  // 自定义 TabBar 不走 uni.switchTab（pages.json 未配置原生 tabBar）
  uni.reLaunch({ url: tab.path })
}
</script>

<style lang="scss" scoped>
.tab-bar {
  position: fixed;
  bottom: 0;
  left: 0;
  right: 0;
  height: calc(120rpx + env(safe-area-inset-bottom, 0px));
  padding-bottom: env(safe-area-inset-bottom, 0px);
  background: #fff;
  display: flex;
  flex-direction: row;
  border-top: 1rpx solid #e8ecf0;
  box-shadow: 0 -4rpx 20rpx rgba(0,0,0,0.06);
  z-index: 999;
}

.tab-item {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 6rpx;
  padding-top: 14rpx;
  cursor: pointer;
}

.tab-icon {
  font-size: 44rpx;
  transition: transform 0.2s;
}

.tab-label {
  font-size: 20rpx;
  color: #999;
  transition: color 0.2s;
}

/* 运维主题激活色 */
.operator .tab-item.active {
  .tab-icon  { transform: scale(1.1); }
  .tab-label { color: #3b6cf4; font-weight: 600; }
}

/* 维修主题激活色 */
.worker .tab-item.active {
  .tab-icon  { transform: scale(1.1); }
  .tab-label { color: #00b96b; font-weight: 600; }
}
</style>
