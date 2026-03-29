<!-- 自定义顶部导航栏（适配刘海屏/动态岛） -->
<template>
  <view class="nav-bar" :style="{ background: bgColor }">
    <view class="status-bar" :style="{ height: statusBarHeight + 'px' }" />
    <view class="nav-content">
      <!-- 左侧：返回按钮或空 -->
      <view class="nav-left" @click="onBack">
        <text v-if="showBack" class="back-icon">‹</text>
        <slot name="left" />
      </view>
      <!-- 标题 -->
      <text class="nav-title">{{ title }}</text>
      <!-- 右侧插槽 -->
      <view class="nav-right">
        <slot name="right" />
      </view>
    </view>
  </view>
  <!-- 占位，防止内容被遮挡 -->
  <view :style="{ height: totalHeight + 'px' }" />
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'

const props = withDefaults(defineProps<{
  title?: string
  bgColor?: string
  showBack?: boolean
}>(), {
  title: '',
  bgColor: '#1a1a2e',
  showBack: false,
})

const statusBarHeight = ref(44)
const navBarHeight = 88 // rpx → 需要转 px，固定 44px 高度

onMounted(() => {
  const info = uni.getSystemInfoSync()
  statusBarHeight.value = info.statusBarHeight ?? 44
})

const totalHeight = computed(() => statusBarHeight.value + 44)

function onBack() {
  if (props.showBack) {
    uni.navigateBack()
  }
}
</script>

<style lang="scss" scoped>
.nav-bar {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  z-index: 100;
}

.status-bar {
  width: 100%;
}

.nav-content {
  height: 88rpx;
  display: flex;
  align-items: center;
  padding: 0 28rpx;
  position: relative;
}

.nav-left {
  width: 80rpx;
  display: flex;
  align-items: center;
}

.back-icon {
  font-size: 52rpx;
  color: #fff;
  font-weight: 300;
  line-height: 1;
}

.nav-title {
  flex: 1;
  text-align: center;
  font-size: 32rpx;
  font-weight: 600;
  color: #fff;
}

.nav-right {
  width: 80rpx;
  display: flex;
  align-items: center;
  justify-content: flex-end;
}
</style>
