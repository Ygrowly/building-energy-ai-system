<!--
  自定义底部导航栏
  通过 tabs prop 传入标签配置，current 绑定当前页
  icon 字段现在使用 /static/icons/ 下的 SVG 图标路径
-->
<template>
  <view class="tab-bar" :class="theme">
    <view class="tab-bar-inner">
      <view class="tab-side">
        <view
          v-for="tab in leftTabs"
          :key="tab.name"
          class="tab-item"
          :class="{ active: current === tab.name }"
          @click="onTab(tab)"
        >
          <image class="tab-icon" :src="tab.icon" mode="aspectFit" />
          <text class="tab-label">{{ tab.label }}</text>
        </view>
      </view>

      <view class="tab-center-spacer" />

      <view class="tab-side">
        <view
          v-for="tab in rightTabs"
          :key="tab.name"
          class="tab-item"
          :class="{ active: current === tab.name }"
          @click="onTab(tab)"
        >
          <image class="tab-icon" :src="tab.icon" mode="aspectFit" />
          <text class="tab-label">{{ tab.label }}</text>
        </view>
      </view>

      <view class="tab-center-button" @click="onCenterAction">
        <DotLottieVue
          v-if="centerLottie"
          :key="centerAnimationKey"
          class="tab-center-lottie"
          :src="centerLottie"
          autoplay
          loop
        />
        <image v-else class="tab-center-icon" :src="centerIcon" mode="aspectFit" />
        <text class="tab-center-label">{{ centerLabel }}</text>
      </view>
    </view>
  </view>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { DotLottieVue } from '@lottiefiles/dotlottie-vue'

export interface TabItem {
  name: string
  label: string
  icon: string
  iconActive?: string
  path: string
}

const props = withDefaults(defineProps<{
  tabs: TabItem[]
  current: string
  theme?: 'operator' | 'worker'
  centerPath?: string
  centerIcon?: string
  centerLottie?: string
  centerLabel?: string
}>(), {
  theme: 'operator',
  centerPath: '/pages/ai/chat/index',
  centerIcon: '/static/icons/tab-ai-chat.svg',
  centerLottie: '/static/lottie/ai-chat.lottie',
  centerLabel: 'AI 对话',
})

const midpoint = computed(() => Math.ceil(props.tabs.length / 2))
const leftTabs = computed(() => props.tabs.slice(0, midpoint.value))
const rightTabs = computed(() => props.tabs.slice(midpoint.value))
const centerAnimationKey = computed(() => `${props.theme}-${props.current}-${props.centerLottie}`)

function onTab(tab: TabItem) {
  if (tab.name === props.current) return
  uni.reLaunch({ url: tab.path })
}

function normalizeRoute(path: string) {
  return path.startsWith('/') ? path : `/${path}`
}

function onCenterAction() {
  const target = props.centerPath
  const pages = getCurrentPages()
  const currentPath = normalizeRoute(pages[pages.length - 1]?.route || '')
  if (currentPath === target) return

  uni.navigateTo({
    url: target,
    fail() {
      uni.redirectTo({ url: target })
    },
  })
}
</script>

<style lang="scss" scoped>
.tab-bar {
  position: fixed;
  bottom: 0;
  left: 0;
  right: 0;
  height: calc(212rpx + env(safe-area-inset-bottom, 0px));
  pointer-events: none;
  z-index: 999;
}

.tab-bar-inner {
  position: absolute;
  left: 0;
  right: 0;
  bottom: 0;
  height: calc(156rpx + env(safe-area-inset-bottom, 0px));
  padding-bottom: env(safe-area-inset-bottom, 0px);
  box-sizing: border-box;
  background: linear-gradient(to bottom, transparent 0 156rpx, rgba(255, 255, 255, 0.94) 156rpx 100%);
  display: flex;
  flex-direction: row;
  align-items: stretch;
  overflow: visible;
  pointer-events: auto;
}

.tab-bar-inner::before {
  content: '';
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  height: 156rpx;
  z-index: 0;
  background: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 750 184' preserveAspectRatio='none'%3E%3Cpath fill='%23fff' fill-opacity='.94' d='M0 184V78C0 50 23 28 54 28H226C286 28 292 88 334 122C358 144 392 144 416 122C458 88 464 28 524 28H696C727 28 750 50 750 78V184Z'/%3E%3C/svg%3E") center bottom / 100% 100% no-repeat;
  filter:
    drop-shadow(0 -16rpx 40rpx rgba(33, 38, 48, 0.10))
    drop-shadow(0 -4rpx 16rpx rgba(33, 38, 48, 0.05));
  pointer-events: none;
}

.tab-side {
  position: relative;
  z-index: 3;
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: row;
}

.tab-center-spacer {
  width: 132rpx;
  flex-shrink: 0;
}

.tab-item {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 8rpx;
  height: 100%;
  padding-top: 16rpx;
  box-sizing: border-box;
  cursor: pointer;
}

.tab-side .tab-item:first-child {
  transform: translateX(18rpx);
}

.tab-side .tab-item:last-child {
  transform: translateX(-18rpx);
}

.tab-icon {
  width: 38rpx;
  height: 38rpx;
  opacity: 0.72;
  transition: transform 0.2s, opacity 0.2s, filter 0.2s;
}

.tab-label {
  font-size: 20rpx;
  line-height: 1;
  color: #9a9aa0;
  white-space: nowrap;
  transition: color 0.2s, font-weight 0.2s;
}

.tab-center-button {
  position: absolute;
  top: -55rpx;
  left: 50%;
  z-index: 6;
  width: 158rpx;
  height: 158rpx;
  margin-left: -79rpx;
  border-radius: 50%;
  background: transparent;
  display: flex;
  align-items: center;
  justify-content: center;
  box-shadow: none;
}

.tab-center-icon {
  width: 44rpx;
  height: 44rpx;
}

.tab-center-lottie {
  width: 100%;
  height: 100%;
  pointer-events: none;
}

.tab-center-lottie :deep(canvas),
.tab-center-lottie :deep(svg) {
  width: 100% !important;
  height: 100% !important;
}

.tab-center-label {
  position: absolute;
  width: 1rpx;
  height: 1rpx;
  overflow: hidden;
  opacity: 0;
}

.tab-item.active {
  .tab-icon {
    opacity: 1;
    filter: brightness(0);
    transform: translateY(-2rpx) scale(1.04);
  }

  .tab-label {
    color: #202024;
    font-weight: 600;
  }
}

.operator .tab-bar-inner {
  &::before {
    filter:
      drop-shadow(0 -16rpx 40rpx rgba(42, 49, 66, 0.11))
      drop-shadow(0 -4rpx 16rpx rgba(42, 49, 66, 0.05));
  }
}

.worker .tab-bar-inner {
  &::before {
    filter:
      drop-shadow(0 -16rpx 40rpx rgba(118, 135, 76, 0.12))
      drop-shadow(0 -4rpx 16rpx rgba(118, 135, 76, 0.06));
  }
}
</style>
