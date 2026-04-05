<!--
  自定义底部导航栏
  通过 tabs prop 传入标签配置，current 绑定当前页
  icon 字段现在使用 /static/icons/ 下的 SVG 图标路径
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
      <image
        class="tab-icon"
        :src="current === tab.name ? tab.iconActive || tab.icon : tab.icon"
        mode="aspectFit"
      />
      <text class="tab-label">{{ tab.label }}</text>
    </view>
  </view>
</template>

<script setup lang="ts">
export interface TabItem {
  name: string
  label: string
  icon: string
  iconActive?: string
  path: string
}

const props = defineProps<{
  tabs: TabItem[]
  current: string
  theme?: 'operator' | 'worker'
}>()

function onTab(tab: TabItem) {
  if (tab.name === props.current) return
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
  background: rgba(255,255,255,0.98);
  display: flex;
  flex-direction: row;
  border-top: 1rpx solid rgba(228, 237, 184, 0.88);
  box-shadow: 0 -12rpx 32rpx rgba(181, 196, 118, 0.12);
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
  width: 44rpx;
  height: 44rpx;
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
  .tab-label { color: #73854a; font-weight: 600; }
}
</style>
