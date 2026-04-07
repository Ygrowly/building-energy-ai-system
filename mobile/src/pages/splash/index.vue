<template>
  <view class="page">

    <!-- Hero -->
    <view class="hero">

      <!-- 顶部品牌 -->
      <view class="nav-row">
        <view class="brand">
          <view class="brand-icon">
            <view class="brand-icon-bolt" />
          </view>
          <text class="brand-name">建筑能源</text>
        </view>
      </view>

      <!-- 主标题 -->
      <view class="title-block">
        <text class="t-line t-black t-main anim-l1">智慧管理</text>

        <view class="green-wrap anim-l2">
          <text class="t-line t-green t-accent">绿色能源</text>
          <view class="oval-ring oval-ring-main" />
          <view class="oval-ring oval-ring-sub" />
        </view>

        <text class="t-line t-black t-dim anim-l3">的未来</text>
        <text class="t-sub anim-l4">面向智能化的能源优化与调度平台</text>
      </view>

      <!-- 建筑插画 -->
      <view class="illus-wrap">
        <image class="illus-img" src="/static/images/building.png" mode="widthFix"/>
        <view class="illus-fade"/>
      </view>

    </view>

    <!-- 底部加载区域 -->
    <view class="loading-bar">
      <!-- 进度条轨道 -->
      <view class="progress-track">
        <view class="progress-fill" :style="{ width: progress + '%' }"/>
      </view>
      <!-- 提示文字 -->
      <text class="loading-hint">{{ hint }}</text>
    </view>

  </view>
</template>

<script setup lang="ts">
import { ref, onMounted, onUnmounted } from 'vue'
import { useAuthStore } from '../../stores/auth'

const authStore = useAuthStore()
const progress  = ref(0)
const hint      = ref('正在初始化...')

const hints = ['正在初始化...', '加载能源数据...', '连接智慧平台...', '准备完成']
let hintIdx = 0
let timer: ReturnType<typeof setInterval> | null = null

onMounted(() => {
  const DURATION = 2600
  const INTERVAL = 30
  const STEPS    = DURATION / INTERVAL
  let step = 0

  timer = setInterval(() => {
    step++
    progress.value = Math.min(100, Math.round(
      (step / STEPS) * 100 * (1 - 0.18 * Math.cos(Math.PI * step / STEPS))
    ))

    const newIdx = Math.min(hints.length - 1, Math.floor((step / STEPS) * hints.length))
    if (newIdx !== hintIdx) {
      hintIdx = newIdx
      hint.value = hints[hintIdx]
    }

    if (step >= STEPS) {
      clearInterval(timer!)
      timer = null
      // 已登录 → 跳首页；未登录 → 跳登录页
      hint.value = '校验登录状态...'
      void authStore.redirectAfterSplash()
    }
  }, INTERVAL)
})

onUnmounted(() => {
  if (timer) clearInterval(timer)
})
</script>

<style lang="scss" scoped>
$green:   #22C55E;
$green-d: #15803D;
$ink:     #0A0A0A;
$font-cn: 'Noto Sans SC', 'PingFang SC', 'Microsoft YaHei', sans-serif;

// ── Keyframes ──────────────────────────────────────────────
@keyframes fadeUp {
  from { opacity: 0; transform: translateY(30rpx); }
  to   { opacity: 1; transform: translateY(0); }
}
@keyframes floatBlob {
  0%,100% { transform: translateY(0) scale(1); }
  50%     { transform: translateY(40rpx) scale(1.08); }
}
@keyframes floatBlob2 {
  0%,100% { transform: translateY(0) scale(1); }
  50%     { transform: translateY(-30rpx) scale(1.05); }
}
@keyframes progressShimmer {
  0%   { background-position: -200% center; }
  100% { background-position: 200% center; }
}
@keyframes hintFade {
  0%   { opacity: 0; transform: translateY(8rpx); }
  15%  { opacity: 1; transform: translateY(0); }
  85%  { opacity: 1; transform: translateY(0); }
  100% { opacity: 0.6; }
}

// ── Page ───────────────────────────────────────────────────
.page {
  min-height: 100vh;
  background:
    radial-gradient(ellipse 55% 42% at 100% 0%,   #bbf7d0 0%, transparent 68%),
    radial-gradient(ellipse 55% 42% at 0%   100%, #bbf7d0 0%, transparent 68%),
    #ffffff;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  font-family: $font-cn;
  position: relative;
}

// ── Hero ───────────────────────────────────────────────────
.hero {
  flex: 1;
  padding: 0 44rpx;
  display: flex;
  flex-direction: column;
  position: relative;

  &::before {
    content: '';
    position: absolute;
    width: 500rpx; height: 500rpx;
    background: #22c55e;
    filter: blur(100px);
    opacity: 0.13;
    top: -120rpx; right: -120rpx;
    border-radius: 50%;
    animation: floatBlob 7s ease-in-out infinite;
    pointer-events: none;
  }
  &::after {
    content: '';
    position: absolute;
    width: 380rpx; height: 380rpx;
    background: #4ade80;
    filter: blur(90px);
    opacity: 0.10;
    bottom: 200rpx; left: -80rpx;
    border-radius: 50%;
    animation: floatBlob2 9s ease-in-out infinite;
    pointer-events: none;
  }
}

// Nav
.nav-row {
  display: flex;
  align-items: center;
  padding-top: 64rpx;
  margin-bottom: 52rpx;
}
.brand      { display: flex; align-items: center; gap: 14rpx; }
.brand-icon {
  width: 48rpx;
  height: 48rpx;
  border-radius: 14rpx;
  background: linear-gradient(135deg, #16a34a, #4ade80);
  position: relative;
  box-shadow: 0 10rpx 24rpx rgba(34, 197, 94, 0.24);
}
.brand-icon-bolt {
  position: absolute;
  top: 8rpx;
  left: 16rpx;
  width: 0;
  height: 0;
  border-left: 8rpx solid transparent;
  border-right: 3rpx solid transparent;
  border-top: 0 solid transparent;
  border-bottom: 18rpx solid #fff;
  transform: skewX(-18deg);

  &::after {
    content: '';
    position: absolute;
    top: 10rpx;
    left: -6rpx;
    width: 0;
    height: 0;
    border-left: 4rpx solid transparent;
    border-right: 9rpx solid transparent;
    border-top: 18rpx solid #fff;
    border-bottom: 0 solid transparent;
  }
}
.brand-name { font-size: 28rpx; font-weight: 800; color: #0A2312; letter-spacing: 3rpx; font-family: $font-cn; }

// 入场动画
.anim-l1 { animation: fadeUp 0.8s ease forwards; opacity: 0; }
.anim-l2 { animation: fadeUp 0.8s ease 0.15s forwards; opacity: 0; }
.anim-l3 { animation: fadeUp 0.8s ease 0.28s forwards; opacity: 0; }
.anim-l4 { animation: fadeUp 0.8s ease 0.40s forwards; opacity: 0; }

// Title
.title-block { margin-bottom: 44rpx; position: relative; z-index: 1; }

.t-line {
  display: block;
  font-weight: 900;
  line-height: 1.12;
  font-family: $font-cn;
  &.t-main   { font-size: 84rpx; color: $ink; letter-spacing: 2rpx; }
  &.t-accent {
    font-size: 92rpx; letter-spacing: 4rpx;
    position: relative; z-index: 1;
    color: #16a34a;
    text-shadow: 0 6rpx 20rpx rgba(34, 197, 94, 0.14);
  }
  &.t-dim  { font-size: 76rpx; color: rgba(10,10,10,0.75); letter-spacing: 2rpx; font-weight: 800; }
  &.t-black { color: $ink; font-size: 84rpx; letter-spacing: 2rpx; }
  &.t-green { color: $green; position: relative; z-index: 1; }
}

.green-wrap {
  position: relative;
  display: inline-block;
  margin: 2rpx 0;
}

.oval-ring {
  position: absolute;
  top: -14rpx; left: -18rpx;
  width: calc(100% + 36rpx);
  height: calc(100% + 28rpx);
  pointer-events: none;
  z-index: 0;
  border-radius: 999rpx;
}

.oval-ring-main {
  border: 3rpx dashed rgba(34, 197, 94, 0.85);
  transform: rotate(-2deg);
}

.oval-ring-sub {
  top: -8rpx;
  left: -10rpx;
  width: calc(100% + 20rpx);
  height: calc(100% + 16rpx);
  border: 2rpx dashed rgba(74, 222, 128, 0.4);
  transform: rotate(2deg);
}

.t-sub {
  display: block;
  font-size: 21rpx;
  color: #8BB89A;
  letter-spacing: 2.5rpx;
  margin-top: 22rpx;
  font-weight: 500;
  font-family: $font-cn;
}

// 插画
.illus-wrap {
  position: relative;
  margin: 0 -44rpx;
  flex: 1;
  overflow: hidden;
}
.illus-img {
  width: 110%;
  display: block;
}
.illus-fade {
  position: absolute;
  bottom: 0; left: 0; right: 0;
  height: 160rpx;
  background: linear-gradient(to bottom, transparent, rgba(255,255,255,0.9));
  pointer-events: none;
}

// ── 底部加载区域 ────────────────────────────────────────────
.loading-bar {
  padding: 0 52rpx 72rpx;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 20rpx;
  background: transparent;
}

.progress-track {
  width: 100%;
  height: 6rpx;
  background: rgba(34, 197, 94, 0.15);
  border-radius: 3rpx;
  overflow: hidden;
}

.progress-fill {
  height: 100%;
  border-radius: 3rpx;
  background: linear-gradient(90deg, #15803D 0%, #22C55E 50%, #4ADE80 100%);
  background-size: 200% 100%;
  animation: progressShimmer 1.4s linear infinite;
  transition: width 0.03s linear;
}

.loading-hint {
  font-size: 22rpx;
  color: #8BB89A;
  letter-spacing: 2rpx;
  font-family: $font-cn;
  animation: hintFade 0.4s ease forwards;
}
</style>
