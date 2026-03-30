<template>
  <view class="page">

    <!-- ══ Hero ══ -->
    <view class="hero">

      <!-- 导航栏 -->
      <view class="nav-row">
        <view class="brand">
          <view class="brand-icon">
            <svg viewBox="0 0 28 28" fill="none">
              <rect width="28" height="28" rx="7" fill="#22C55E"/>
              <path d="M16 3L7 16h7l-2 9 10-12h-7V3z" fill="white"/>
            </svg>
          </view>
          <text class="brand-name">建筑能源</text>
        </view>
      </view>

      <!-- 主标题 -->
      <view class="title-block">
        <text class="t-line t-black t-main anim-l1">智慧管理</text>

        <view class="green-wrap anim-l2">
          <text class="t-line t-green t-accent">绿色能源</text>
          <svg class="oval-svg" viewBox="0 0 260 80" fill="none" preserveAspectRatio="none">
            <ellipse cx="130" cy="42" rx="120" ry="32"
              stroke="#22C55E" stroke-width="2.5" stroke-linecap="round"
              stroke-dasharray="7 3" transform="rotate(-2 130 42)" opacity="0.85"/>
            <ellipse cx="132" cy="40" rx="115" ry="28"
              stroke="#4ADE80" stroke-width="1.2" stroke-linecap="round"
              stroke-dasharray="4 6" transform="rotate(2 132 40)" opacity="0.5"/>
          </svg>
        </view>

        <text class="t-line t-black t-dim anim-l3">的未来</text>
        <text class="t-sub anim-l4">面向智能化的能源优化与调度平台</text>
      </view>

      <!-- 按钮 -->
      <view class="cta-btn anim-btn" @click="openLogin">
        <text class="cta-text">立即登录</text>
      </view>

      <!-- 建筑插画 -->
      <view class="illus-wrap">
        <image class="illus-img" src="/static/images/building.png" mode="widthFix"/>
        <view class="illus-fade"/>
        <view class="illus-fade-left"/>
      </view>

    </view>

    <!-- ══ 底部登录抽屉 ══ -->
    <view class="drawer-mask" v-if="showLogin" @click.self="closeLogin"/>

    <view class="drawer" :class="{ 'drawer--open': showLogin }">

      <!-- 拖拽把手 -->
      <view class="handle"/>

      <text class="drawer-title">选择您的身份</text>

      <!-- 运维人员 -->
      <view class="glass-card" :class="{ 'card--op': selectedRole === 'operator' }"
        @click="selectRole('operator')">
        <view class="c-icon op">
          <svg viewBox="0 0 24 24" fill="none">
            <rect x="2" y="3" width="20" height="14" rx="2" stroke="currentColor" stroke-width="1.8"/>
            <path d="M8 21h8M12 17v4" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/>
            <path d="M6 8h4M6 11h6" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/>
            <circle cx="16" cy="9" r="2" stroke="currentColor" stroke-width="1.5"/>
          </svg>
        </view>
        <view class="c-body">
          <text class="c-name">运维人员</text>
          <text class="c-desc">能耗监控 · 工单审阅</text>
        </view>
        <view class="radio" :class="{ 'radio--op': selectedRole === 'operator' }">
          <view class="radio-dot" v-if="selectedRole === 'operator'"/>
        </view>
      </view>

      <!-- 维修人员 -->
      <view class="glass-card" :class="{ 'card--wk': selectedRole === 'worker' }"
        @click="selectRole('worker')">
        <view class="c-icon wk">
          <svg viewBox="0 0 24 24" fill="none">
            <path d="M14.7 6.3a1 1 0 000 1.4l1.6 1.6a1 1 0 001.4 0l3.77-3.77a6 6 0 01-7.94 7.94l-6.91 6.91a2.12 2.12 0 01-3-3l6.91-6.91a6 6 0 017.94-7.94l-3.76 3.76z"
              stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/>
          </svg>
        </view>
        <view class="c-body">
          <text class="c-name">维修人员</text>
          <text class="c-desc">处理工单 · AI辅助维修</text>
        </view>
        <view class="radio" :class="{ 'radio--wk': selectedRole === 'worker' }">
          <view class="radio-dot wk" v-if="selectedRole === 'worker'"/>
        </view>
      </view>

      <!-- 表单（选完角色展开） -->
      <view class="form" v-if="selectedRole">
        <view class="sep"><view class="sep-line"/><text class="sep-txt">账号密码登录</text><view class="sep-line"/></view>

        <view class="field" :class="{ 'field--focus': focusUser }">
          <view class="f-ico">
            <svg viewBox="0 0 20 20" fill="none">
              <circle cx="10" cy="7" r="3" stroke="#9CA3AF" stroke-width="1.5"/>
              <path d="M3 18a7 7 0 0114 0" stroke="#9CA3AF" stroke-width="1.5" stroke-linecap="round"/>
            </svg>
          </view>
          <input class="f-input" v-model="username" placeholder="请输入用户名" placeholder-class="ph"
            :disabled="loading" @focus="focusUser=true" @blur="focusUser=false"/>
        </view>

        <view class="field" :class="{ 'field--focus': focusPwd }">
          <view class="f-ico">
            <svg viewBox="0 0 20 20" fill="none">
              <rect x="3" y="9" width="14" height="9" rx="2" stroke="#9CA3AF" stroke-width="1.5"/>
              <path d="M7 9V6a3 3 0 016 0v3" stroke="#9CA3AF" stroke-width="1.5" stroke-linecap="round"/>
            </svg>
          </view>
          <input class="f-input" v-model="password" placeholder="请输入密码" placeholder-class="ph"
            password :disabled="loading" @confirm="handleLogin"
            @focus="focusPwd=true" @blur="focusPwd=false"/>
        </view>

        <button class="submit" :class="selectedRole === 'worker' ? 'sub--wk' : 'sub--op'"
          :disabled="loading || !username || !password" @click="handleLogin">
          <text v-if="!loading">登 录</text>
          <text v-else>登录中...</text>
        </button>

        <view class="err" v-if="errorMsg">
          <svg viewBox="0 0 16 16" fill="none" style="width:28rpx;height:28rpx;flex-shrink:0">
            <circle cx="8" cy="8" r="7" stroke="#EF4444" stroke-width="1.3"/>
            <path d="M8 5v3M8 10.5h.01" stroke="#EF4444" stroke-width="1.3" stroke-linecap="round"/>
          </svg>
          <text>{{ errorMsg }}</text>
        </view>
      </view>

      <text class="hint">{{ selectedRole ? '输入账号密码完成登录' : '选择身份后即可登录' }}</text>

    </view>

  </view>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { useAuthStore } from '../../stores/auth'

const authStore    = useAuthStore()
const showLogin    = ref(false)
const selectedRole = ref<'operator' | 'worker' | null>(null)
const username     = ref('')
const password     = ref('')
const loading      = ref(false)
const errorMsg     = ref('')
const focusUser    = ref(false)
const focusPwd     = ref(false)

function openLogin()  { showLogin.value = true }
function closeLogin() { showLogin.value = false }

function selectRole(role: 'operator' | 'worker') {
  if (selectedRole.value === role) return
  selectedRole.value = role
  username.value = ''
  password.value = ''
  errorMsg.value = ''
}

async function handleLogin() {
  if (!username.value.trim() || !password.value) return
  errorMsg.value = ''
  loading.value = true
  try {
    await authStore.login(username.value.trim(), password.value)
  } catch (err: any) {
    errorMsg.value = err?.message || '登录失败，请检查用户名和密码'
  } finally {
    loading.value = false
  }
}
</script>

<style lang="scss" scoped>
$green:    #22C55E;
$green-d:  #15803D;
$blue:     #3B6CF4;
$ink:      #0A0A0A;
$muted:    #6B7280;

// ── Font stacks ─────────────────────────────────────────────
$font-cn: 'Noto Sans SC', 'PingFang SC', 'Microsoft YaHei', sans-serif;
$font-en: 'Noto Sans SC', -apple-system, sans-serif;

// ── Keyframes ────────────────────────────────────────────────
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

@keyframes particleDrift {
  0%   { transform: translateY(0) translateX(0) scale(1); opacity: 0.6; }
  50%  { transform: translateY(-60rpx) translateX(20rpx) scale(1.3); opacity: 0.9; }
  100% { transform: translateY(-120rpx) translateX(-10rpx) scale(0.8); opacity: 0; }
}

// ── Page ────────────────────────────────────────────────────
.page {
  min-height: 100vh;
  // 纯白底 + 右上角/左下角双角光晕
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

// ── Hero ────────────────────────────────────────────────────
.hero {
  flex: 1;
  padding: 0 44rpx;
  display: flex;
  flex-direction: column;
  position: relative;

  // 右上角光斑
  &::before {
    content: '';
    position: absolute;
    width: 500rpx;
    height: 500rpx;
    background: #22c55e;
    filter: blur(100px);
    opacity: 0.13;
    top: -120rpx;
    right: -120rpx;
    border-radius: 50%;
    animation: floatBlob 7s ease-in-out infinite;
    pointer-events: none;
  }

  // 左下角光斑
  &::after {
    content: '';
    position: absolute;
    width: 380rpx;
    height: 380rpx;
    background: #4ade80;
    filter: blur(90px);
    opacity: 0.10;
    bottom: 200rpx;
    left: -80rpx;
    border-radius: 50%;
    animation: floatBlob2 9s ease-in-out infinite;
    pointer-events: none;
  }
}

// Nav
.nav-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding-top: 64rpx;
  margin-bottom: 52rpx;
}
.brand       { display: flex; align-items: center; gap: 14rpx; }
.brand-icon  { width: 48rpx; height: 48rpx; svg { width: 100%; height: 100%; } }
.brand-name  { font-size: 28rpx; font-weight: 800; color: #0A2312; letter-spacing: 3rpx; font-family: $font-cn; }

// ── 入场动画 ─────────────────────────────────────────────────
.anim-l1 { animation: fadeUp 0.8s ease forwards; opacity: 0; }
.anim-l2 { animation: fadeUp 0.8s ease 0.15s forwards; opacity: 0; }
.anim-l3 { animation: fadeUp 0.8s ease 0.28s forwards; opacity: 0; }
.anim-l4 { animation: fadeUp 0.8s ease 0.40s forwards; opacity: 0; }
.anim-btn { animation: fadeUp 0.8s ease 0.55s forwards; opacity: 0; }

// Title
.title-block { margin-bottom: 44rpx; position: relative; z-index: 1; }

.t-line {
  display: block;
  font-weight: 900;
  line-height: 1.12;
  font-family: $font-cn;

  // 第1行：智慧管理 — 大、黑、收紧字距
  &.t-main {
    font-size: 84rpx;
    color: $ink;
    letter-spacing: 2rpx;
  }

  // 第2行：绿色能源 — 更大、渐变、拉开字距强调
  &.t-accent {
    font-size: 92rpx;
    letter-spacing: 4rpx;
    position: relative;
    z-index: 1;
    // 渐变文字 #22c55e → #4ade80（绿→青绿）
    background: linear-gradient(90deg, #16a34a 0%, #22c55e 40%, #4ade80 100%);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    background-clip: text;
  }

  // 第3行：的未来 — 略小、略弱
  &.t-dim {
    font-size: 76rpx;
    color: rgba(10,10,10,0.75);
    letter-spacing: 2rpx;
    font-weight: 800;
  }

  // 兼容旧 class（不破坏其他地方）
  &.t-black { color: $ink; font-size: 84rpx; letter-spacing: 2rpx; }
  &.t-green { color: $green; position: relative; z-index: 1; }
}

.green-wrap {
  position: relative;
  display: inline-block;
  margin: 2rpx 0;
}

.oval-svg {
  position: absolute;
  top: -14rpx;
  left: -18rpx;
  width: calc(100% + 36rpx);
  height: calc(100% + 28rpx);
  pointer-events: none;
  z-index: 0;
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

// CTA 按钮 — Solmate GET START 风格
.cta-btn {
  display: inline-flex;
  align-items: center;
  justify-content: flex-start;
  align-self: flex-start;
  height: 78rpx;
  padding: 0 120rpx 0 44rpx;
  background: linear-gradient(90deg, #15803D 0%, #ffffff 100%);
  border: none;
  border-radius: 8rpx;
  cursor: pointer;
  margin-bottom: 36rpx;
  position: relative;
  z-index: 1;
  transition: all 0.25s ease;

  &:active {
    background: linear-gradient(90deg, #166534 0%, #e5e5e5 100%);
  }
}

.cta-text {
  font-size: 26rpx;
  font-weight: 600;
  color: #FFFFFF;
  letter-spacing: 2rpx;
  font-family: $font-cn;
}


// 建筑插画
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

// 左下角遮罩：盖住图片，让底层绿色渐变透出
.illus-fade-left {
  position: absolute;
  bottom: 0; left: 0;
  width: 260rpx;
  height: 340rpx;
  background: linear-gradient(
    135deg,
    rgba(187, 247, 208, 0.95) 0%,
    rgba(240, 253, 244, 0.7) 50%,
    transparent 100%
  );
  pointer-events: none;
}

// ── Drawer mask ─────────────────────────────────────────────
.drawer-mask {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.18);
  z-index: 100;
  -webkit-backdrop-filter: blur(2px);
  backdrop-filter: blur(2px);
}

// ── Drawer ──────────────────────────────────────────────────
.drawer {
  position: fixed;
  left: 0; right: 0; bottom: 0;
  z-index: 101;
  background: rgba(255, 255, 255, 0.82);
  -webkit-backdrop-filter: blur(28px);
  backdrop-filter: blur(28px);
  border-radius: 40rpx 40rpx 0 0;
  border-top: 1.5rpx solid rgba(255, 255, 255, 0.7);
  box-shadow: 0 -8rpx 48rpx rgba(0, 80, 0, 0.08);
  padding: 20rpx 36rpx 60rpx;
  transform: translateY(100%);
  transition: transform 0.32s cubic-bezier(0.32, 0.72, 0, 1);

  &--open { transform: translateY(0); }
}

.handle {
  width: 72rpx;
  height: 8rpx;
  border-radius: 4rpx;
  background: #D1D5DB;
  margin: 0 auto 36rpx;
}

.drawer-title {
  display: block;
  font-size: 28rpx;
  font-weight: 700;
  color: $ink;
  margin-bottom: 22rpx;
}

// ── Glass cards ─────────────────────────────────────────────
.glass-card {
  display: flex;
  align-items: center;
  gap: 22rpx;
  background: rgba(255, 255, 255, 0.55);
  border: 2rpx solid rgba(255, 255, 255, 0.6);
  border-radius: 22rpx;
  padding: 24rpx 26rpx;
  margin-bottom: 14rpx;
  box-shadow: 0 4rpx 24rpx rgba(34, 80, 34, 0.05);
  cursor: pointer;

  &.card--op { border-color: rgba(59,108,244,0.45); background: rgba(238,242,255,0.65); }
  &.card--wk { border-color: rgba(34,197,94,0.45);  background: rgba(240,253,244,0.65); }
}

.c-icon {
  width: 76rpx; height: 76rpx;
  border-radius: 18rpx;
  display: flex; align-items: center; justify-content: center;
  flex-shrink: 0;
  svg { width: 38rpx; height: 38rpx; }
  &.op { background: rgba(219,234,254,0.9); color: $blue; }
  &.wk { background: rgba(220,252,231,0.9); color: $green-d; }
}

.c-body   { flex: 1; display: flex; flex-direction: column; gap: 6rpx; }
.c-name   { font-size: 30rpx; font-weight: 700; color: $ink; font-family: $font-cn; }
.c-desc   { font-size: 22rpx; color: $muted; font-family: $font-cn; font-weight: 400; }

.radio {
  width: 38rpx; height: 38rpx;
  border-radius: 50%;
  border: 2rpx solid #D1D5DB;
  display: flex; align-items: center; justify-content: center;
  flex-shrink: 0;
  &--op { border-color: $blue; background: rgba(59,108,244,0.08); }
  &--wk { border-color: $green; background: rgba(34,197,94,0.08); }
}

.radio-dot {
  width: 16rpx; height: 16rpx;
  border-radius: 50%;
  background: $blue;
  &.wk { background: $green; }
}

// ── Form ────────────────────────────────────────────────────
.form { animation: up .22s ease; }
@keyframes up {
  from { opacity: 0; transform: translateY(10rpx); }
  to   { opacity: 1; transform: translateY(0); }
}

.sep   { display: flex; align-items: center; gap: 14rpx; margin: 14rpx 0 18rpx; }
.sep-line { flex: 1; height: 1rpx; background: rgba(0,0,0,0.08); }
.sep-txt  { font-size: 22rpx; color: $muted; white-space: nowrap; }

.field {
  display: flex; align-items: center;
  height: 92rpx;
  background: rgba(255,255,255,0.65);
  border: 2rpx solid rgba(220,220,220,0.6);
  border-radius: 14rpx;
  padding: 0 22rpx;
  margin-bottom: 14rpx;
  transition: border-color .2s, box-shadow .2s;

  &--focus {
    border-color: rgba(34,197,94,0.5);
    box-shadow: 0 0 0 4rpx rgba(34,197,94,0.08);
    background: rgba(255,255,255,0.9);
  }
}

.f-ico    { width: 32rpx; height: 32rpx; margin-right: 16rpx; flex-shrink: 0; svg { width: 100%; height: 100%; } }
.f-input  { flex: 1; font-size: 28rpx; color: $ink; background: transparent; border: none; height: 100%; font-family: $font-cn; font-weight: 400; }
.ph       { color: #D1D5DB; }

.submit {
  width: 100%; height: 96rpx;
  border-radius: 48rpx; border: none;
  color: #fff; font-size: 30rpx; font-weight: 700; letter-spacing: 6rpx;
  font-family: $font-cn;
  margin-top: 6rpx; cursor: pointer;
  &.sub--op { background: linear-gradient(90deg,$blue,#6B9AF8); box-shadow: 0 8rpx 24rpx rgba(59,108,244,.28); }
  &.sub--wk { background: linear-gradient(90deg,$green-d,$green);  box-shadow: 0 8rpx 24rpx rgba(34,197,94,.28); }
  &[disabled] { opacity: .4; box-shadow: none; }
}

.err {
  display: flex; align-items: center; gap: 10rpx;
  margin-top: 16rpx; padding: 16rpx 18rpx;
  background: rgba(254,226,226,0.75); border-left: 4rpx solid #EF4444; border-radius: 10rpx;
  text { font-size: 24rpx; color: #DC2626; flex: 1; }
}

// ── Hint ────────────────────────────────────────────────────
.hint {
  display: block; text-align: center;
  font-size: 22rpx; color: #C4D4C8;
  margin-top: 22rpx; letter-spacing: 1rpx;
}
</style>
