<template>
  <view class="page">

    <!-- ══ 顶部品牌区 ══ -->
    <view class="top-area">
      <image class="top-bg-img" src="/static/images/bangkok-city.jpg" mode="aspectFill"/>
      <view class="top-brand">
        <text class="top-brand__slogan">智慧能源 · 绿色建筑</text>
      </view>
    </view>

    <!-- ══ 表单卡片 ══ -->
    <view class="card">

      <!-- 注册成功提示 -->
      <view class="banner banner-success" v-if="successMsg">
        <svg viewBox="0 0 20 20" fill="none"><circle cx="10" cy="10" r="9" stroke="#16A34A" stroke-width="1.5"/><path d="M6 10l3 3 5-5" stroke="#16A34A" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/></svg>
        <text>{{ successMsg }}</text>
      </view>

      <!-- 错误提示 -->
      <view class="banner banner-error" v-if="errorMsg">
        <svg viewBox="0 0 20 20" fill="none"><circle cx="10" cy="10" r="9" stroke="#DC2626" stroke-width="1.5"/><path d="M10 6v4M10 13h.01" stroke="#DC2626" stroke-width="1.5" stroke-linecap="round"/></svg>
        <text>{{ errorMsg }}</text>
      </view>

      <!-- ══ 用户画像轮播 ══ -->
      <view class="carousel-wrap" v-if="isLogin"
        @touchstart="onCarouselTouchStart"
        @touchend="onCarouselTouchEnd"
        @mouseenter="pauseCarousel"
        @mouseleave="resumeCarousel">
        <view class="carousel-track">
          <view
            v-for="(card, idx) in personaCards"
            :key="card.key"
            class="carousel-item"
            :class="[
              `carousel-item--${card.key}`,
              { 'carousel-item--active': idx === activeIdx }
            ]"
            :style="getCardStyle(idx)">
            <DotLottieVue class="carousel-item__anim" :class="`carousel-item__anim--${card.key}`"
              :src="card.lottie" autoplay loop />
            <view class="carousel-item__footer">
              <text class="carousel-item__title">{{ card.title }}</text>
              <text class="carousel-item__meta">{{ card.meta }}</text>
            </view>
          </view>
        </view>
        <!-- 指示器 -->
        <view class="carousel-dots">
          <view
            v-for="(_, idx) in personaCards"
            :key="idx"
            class="carousel-dot"
            :class="{ 'carousel-dot--active': idx === activeIdx }"
            @click="goTo(idx)" />
        </view>
      </view>

      <!-- ══ 登录表单 ══ -->
      <view class="form" v-if="isLogin">

        <!-- 用户名 -->
        <view class="field">
          <text class="label">用户名</text>
          <view class="iw" :class="{ 'iw--focus': focus.username, 'iw--err': errors.username }">
            <svg class="ico" viewBox="0 0 20 20" fill="none">
              <circle cx="10" cy="7" r="3.5" stroke="currentColor" stroke-width="1.5"/>
              <path d="M3 19a7 7 0 0114 0" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/>
            </svg>
            <input class="inp" v-model="username" placeholder="请输入用户名" placeholder-class="ph"
              :disabled="loading"
              @focus="focus.username = true; errors.username = ''"
              @blur="focus.username = false; validateUsername()"/>
          </view>
          <text class="ferr" v-if="errors.username">{{ errors.username }}</text>
        </view>

        <!-- 密码 -->
        <view class="field">
          <text class="label">密码</text>
          <view class="iw" :class="{ 'iw--focus': focus.password, 'iw--err': errors.password }">
            <svg class="ico" viewBox="0 0 20 20" fill="none">
              <rect x="3" y="9" width="14" height="9" rx="2.5" stroke="currentColor" stroke-width="1.5"/>
              <path d="M7 9V6a3 3 0 016 0v3" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/>
            </svg>
            <input class="inp" v-model="password" :password="!showPw" placeholder="请输入密码" placeholder-class="ph"
              :disabled="loading" @confirm="handleSubmit"
              @focus="focus.password = true; errors.password = ''"
              @blur="focus.password = false; validatePassword()"/>
            <view class="eye-btn" @click="showPw = !showPw">
              <svg v-if="!showPw" viewBox="0 0 20 20" fill="none">
                <path d="M2 10s3-6 8-6 8 6 8 6-3 6-8 6-8-6-8-6z" stroke="currentColor" stroke-width="1.5"/>
                <circle cx="10" cy="10" r="2.5" stroke="currentColor" stroke-width="1.5"/>
              </svg>
              <svg v-else viewBox="0 0 20 20" fill="none">
                <path d="M3 3l14 14M8.5 8.7A2.5 2.5 0 0013 11.5M5.5 5.8C3.8 7 2.5 9 2.5 10c0 0 3 6 7.5 6a7 7 0 003.7-1.1M17.5 10c-.5-1.3-1.5-2.8-2.7-3.8" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/>
              </svg>
            </view>
          </view>
          <text class="ferr" v-if="errors.password">{{ errors.password }}</text>
        </view>

        <button class="submit-btn" :disabled="loading" @click="handleSubmit">
          <view class="spin" v-if="loading"/>
          <text>{{ loading ? '登录中...' : '登 录' }}</text>
        </button>

      </view>

      <!-- ══ 注册表单 ══ -->
      <view class="form" v-else>

        <!-- 用户名 -->
        <view class="field">
          <text class="label">用户名 <text class="req">*</text></text>
          <view class="iw" :class="{ 'iw--focus': focus.username, 'iw--err': errors.username }">
            <svg class="ico" viewBox="0 0 20 20" fill="none">
              <circle cx="10" cy="7" r="3.5" stroke="currentColor" stroke-width="1.5"/>
              <path d="M3 19a7 7 0 0114 0" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/>
            </svg>
            <input class="inp" v-model="username" placeholder="3~50字符，字母/数字/下划线" placeholder-class="ph"
              :disabled="loading"
              @focus="focus.username = true; errors.username = ''"
              @blur="focus.username = false; validateUsername()"/>
          </view>
          <text class="ferr" v-if="errors.username">{{ errors.username }}</text>
        </view>

        <!-- 邮箱 -->
        <view class="field">
          <text class="label">邮箱</text>
          <view class="iw" :class="{ 'iw--focus': focus.email, 'iw--err': errors.email }">
            <svg class="ico" viewBox="0 0 20 20" fill="none">
              <rect x="2" y="4" width="16" height="12" rx="2" stroke="currentColor" stroke-width="1.5"/>
              <path d="M2 7l8 5 8-5" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/>
            </svg>
            <input class="inp" v-model="email" type="email" placeholder="example@company.com（选填）" placeholder-class="ph"
              :disabled="loading"
              @focus="focus.email = true; errors.email = ''"
              @blur="focus.email = false; validateEmail()"/>
          </view>
          <text class="ferr" v-if="errors.email">{{ errors.email }}</text>
        </view>

        <!-- 手机号 -->
        <view class="field">
          <text class="label">手机号</text>
          <view class="iw" :class="{ 'iw--focus': focus.phone, 'iw--err': errors.phone }">
            <svg class="ico" viewBox="0 0 20 20" fill="none">
              <rect x="5" y="1" width="10" height="18" rx="2.5" stroke="currentColor" stroke-width="1.5"/>
              <circle cx="10" cy="15.5" r="1" fill="currentColor"/>
            </svg>
            <input class="inp" v-model="phone" type="number" placeholder="请输入手机号（选填）" placeholder-class="ph"
              :disabled="loading"
              @focus="focus.phone = true; errors.phone = ''"
              @blur="focus.phone = false; validatePhone()"/>
          </view>
          <text class="ferr" v-if="errors.phone">{{ errors.phone }}</text>
        </view>

        <!-- 密码 -->
        <view class="field">
          <text class="label">密码 <text class="req">*</text></text>
          <view class="iw" :class="{ 'iw--focus': focus.password, 'iw--err': errors.password }">
            <svg class="ico" viewBox="0 0 20 20" fill="none">
              <rect x="3" y="9" width="14" height="9" rx="2.5" stroke="currentColor" stroke-width="1.5"/>
              <path d="M7 9V6a3 3 0 016 0v3" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/>
            </svg>
            <input class="inp" v-model="password" :password="!showPw" placeholder="至少8位，含字母和数字" placeholder-class="ph"
              :disabled="loading"
              @focus="focus.password = true; errors.password = ''"
              @blur="focus.password = false; validatePassword()"/>
            <view class="eye-btn" @click="showPw = !showPw">
              <svg v-if="!showPw" viewBox="0 0 20 20" fill="none">
                <path d="M2 10s3-6 8-6 8 6 8 6-3 6-8 6-8-6-8-6z" stroke="currentColor" stroke-width="1.5"/>
                <circle cx="10" cy="10" r="2.5" stroke="currentColor" stroke-width="1.5"/>
              </svg>
              <svg v-else viewBox="0 0 20 20" fill="none">
                <path d="M3 3l14 14M8.5 8.7A2.5 2.5 0 0013 11.5M5.5 5.8C3.8 7 2.5 9 2.5 10c0 0 3 6 7.5 6a7 7 0 003.7-1.1M17.5 10c-.5-1.3-1.5-2.8-2.7-3.8" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/>
              </svg>
            </view>
          </view>
          <text class="ferr" v-if="errors.password">{{ errors.password }}</text>
        </view>

        <!-- 确认密码 -->
        <view class="field">
          <text class="label">确认密码 <text class="req">*</text></text>
          <view class="iw" :class="{ 'iw--focus': focus.confirm, 'iw--err': errors.confirm }">
            <svg class="ico" viewBox="0 0 20 20" fill="none">
              <rect x="3" y="9" width="14" height="9" rx="2.5" stroke="currentColor" stroke-width="1.5"/>
              <path d="M7 9V6a3 3 0 016 0v3" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/>
              <path d="M8 14l1.5 1.5L13 12" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round"/>
            </svg>
            <input class="inp" v-model="confirmPwd" :password="!showPw" placeholder="再次输入密码" placeholder-class="ph"
              :disabled="loading"
              @focus="focus.confirm = true; errors.confirm = ''"
              @blur="focus.confirm = false; validateConfirm()"/>
          </view>
          <text class="ferr" v-if="errors.confirm">{{ errors.confirm }}</text>
        </view>

        <button class="submit-btn" :disabled="loading" @click="handleSubmit">
          <view class="spin" v-if="loading"/>
          <text>{{ loading ? '注册中...' : '创建账号' }}</text>
        </button>

      </view>

      <!-- 切换提示 -->
      <view class="switch-row">
        <text class="switch-hint">{{ isLogin ? '还没有账号？' : '已有账号？' }}</text>
        <text class="switch-link" @click="switchMode(isLogin ? 'register' : 'login')">
          {{ isLogin ? '立即注册' : '去登录' }}
        </text>
      </view>

    </view>

    <view class="bottom-brand">
      <view class="brand-logo">
        <svg viewBox="0 0 32 32" fill="none">
          <rect width="32" height="32" rx="9" fill="none"/>
          <path d="M18 4L8 18h8l-2 10 12-14h-8V4z" fill="#15803D"/>
        </svg>
      </view>
      <text class="brand-name">建筑能源</text>
    </view>

  </view>
</template>

<script setup lang="ts">
import { ref, reactive, computed, onMounted, onUnmounted, watch } from 'vue'
import { DotLottieVue } from '@lottiefiles/dotlottie-vue'
import { useAuthStore } from '../../stores/auth'
import {
  getCachedPersonaByUsername,
  roleToPersona,
  type PersonaKey,
} from '../../utils/login-persona'

type Mode = 'login' | 'register'

const authStore = useAuthStore()

const mode        = ref<Mode>('login')
const username    = ref('')
const password    = ref('')
const confirmPwd  = ref('')
const email       = ref('')
const phone       = ref('')
const showPw      = ref(false)
const loading     = ref(false)
const errorMsg    = ref('')
const successMsg  = ref('')

const isLogin = computed(() => mode.value === 'login')

// ── 轮播可调参数 ────────────────────────────────────────────
const CAROUSEL_INTERVAL = 2800   // 自动轮播间隔 ms
const CAROUSEL_SIDE_SCALE = 0.88 // 两侧卡片缩放
const CAROUSEL_SIDE_OPACITY = 0.65 // 两侧卡片透明度
const CAROUSEL_OFFSET_X = 68     // 两侧偏移百分比

// ── 轮播数据 & 逻辑 ─────────────────────────────────────────
const personaCards: Array<{ key: PersonaKey; title: string; meta: string; lottie: string }> = [
  { key: 'repair', title: '维修人员', meta: '现场处理', lottie: '/static/lottie/free-maintenance-web-animation.lottie' },
  { key: 'ops',    title: '运维人员', meta: '监测调度', lottie: '/static/lottie/free-itay-animation-copy-animation.lottie' },
  { key: 'user',   title: '普通人员', meta: '轻量使用', lottie: '/static/lottie/free-friends-animation.lottie' },
]

const activeIdx = ref(0)
const matchedPersona = ref<PersonaKey | null>(null)
let timer: ReturnType<typeof setInterval> | null = null
let touchStartX = 0

const matchedIdx = computed(() => {
  if (!matchedPersona.value) return -1
  return personaCards.findIndex(card => card.key === matchedPersona.value)
})

const isPersonaLocked = computed(() => isLogin.value && matchedIdx.value >= 0)

function getCardStyle(idx: number) {
  const total = personaCards.length
  // 计算相对位置: -1(左), 0(中), 1(右)
  let offset = idx - activeIdx.value
  if (offset > 1)  offset -= total
  if (offset < -1) offset += total

  const isCenter = offset === 0
  const scale = isCenter ? 1 : CAROUSEL_SIDE_SCALE
  const opacity = isCenter ? 1 : CAROUSEL_SIDE_OPACITY
  const translateX = offset * CAROUSEL_OFFSET_X
  const zIndex = isCenter ? 3 : 1

  return {
    transform: `translateX(${translateX}%) scale(${scale})`,
    opacity,
    zIndex,
  }
}

function goTo(idx: number) {
  if (isPersonaLocked.value) return
  activeIdx.value = idx
  restartTimer()
}

function next() {
  if (isPersonaLocked.value) return
  activeIdx.value = (activeIdx.value + 1) % personaCards.length
}

function startTimer() {
  if (!isLogin.value || isPersonaLocked.value) return
  if (timer) return
  timer = setInterval(next, CAROUSEL_INTERVAL)
}

function stopTimer() {
  if (timer) { clearInterval(timer); timer = null }
}

function restartTimer() {
  stopTimer()
  startTimer()
}

function pauseCarousel() { stopTimer() }
function resumeCarousel() {
  if (!isPersonaLocked.value) startTimer()
}

function onCarouselTouchStart(e: TouchEvent) {
  if (isPersonaLocked.value) return
  stopTimer()
  touchStartX = e.touches[0].clientX
}

function onCarouselTouchEnd(e: TouchEvent) {
  if (isPersonaLocked.value) return
  const dx = e.changedTouches[0].clientX - touchStartX
  if (Math.abs(dx) > 30) {
    const total = personaCards.length
    if (dx < 0) {
      // 左滑 → 下一张
      activeIdx.value = (activeIdx.value + 1) % total
    } else {
      // 右滑 → 上一张
      activeIdx.value = (activeIdx.value - 1 + total) % total
    }
  }
  startTimer()
}

function syncMatchedPersona() {
  if (!isLogin.value) {
    matchedPersona.value = null
    return
  }

  const matched = getCachedPersonaByUsername(username.value)
  matchedPersona.value = matched?.persona ?? null
}

function syncCarouselMode() {
  if (!isLogin.value) {
    stopTimer()
    return
  }

  if (matchedIdx.value >= 0) {
    activeIdx.value = matchedIdx.value
    stopTimer()
    return
  }

  startTimer()
}

watch(username, () => {
  syncMatchedPersona()
  syncCarouselMode()
}, { immediate: true })

watch(mode, () => {
  syncMatchedPersona()
  syncCarouselMode()
})

watch(matchedIdx, () => {
  syncCarouselMode()
})

onMounted(() => syncCarouselMode())
onUnmounted(() => stopTimer())

const focus  = reactive({ username: false, password: false, confirm: false, email: false, phone: false })
const errors = reactive({ username: '', password: '', confirm: '', email: '', phone: '' })

function switchMode(m: Mode) {
  mode.value   = m
  errorMsg.value  = ''
  successMsg.value = ''
  password.value  = ''
  confirmPwd.value = ''
  showPw.value = false
  Object.keys(errors).forEach(k => ((errors as Record<string, string>)[k] = ''))
}

// ── 校验 ──────────────────────────────────────────────
function validateUsername(): boolean {
  if (!username.value.trim()) { errors.username = '请输入用户名'; return false }
  if (!isLogin.value) {
    if (username.value.length < 3) { errors.username = '用户名至少 3 个字符'; return false }
    if (!/^\w+$/.test(username.value)) { errors.username = '只允许字母、数字和下划线'; return false }
  }
  errors.username = ''; return true
}

function validatePassword(): boolean {
  if (!password.value) { errors.password = '请输入密码'; return false }
  if (!isLogin.value) {
    if (password.value.length < 8) { errors.password = '密码至少 8 个字符'; return false }
    if (!/[A-Za-z]/.test(password.value)) { errors.password = '必须包含至少一个字母'; return false }
    if (!/\d/.test(password.value)) { errors.password = '必须包含至少一个数字'; return false }
  }
  errors.password = ''; return true
}

function validateConfirm(): boolean {
  if (!isLogin.value) {
    if (!confirmPwd.value) { errors.confirm = '请确认密码'; return false }
    if (confirmPwd.value !== password.value) { errors.confirm = '两次密码不一致'; return false }
  }
  errors.confirm = ''; return true
}

function validateEmail(): boolean {
  if (email.value && !/^[^@]+@[^@]+\.[^@]+$/.test(email.value)) {
    errors.email = '邮箱格式不正确'; return false
  }
  errors.email = ''; return true
}

function validatePhone(): boolean {
  if (phone.value && !/^[\d]{5,20}$/.test(phone.value)) {
    errors.phone = '手机号格式不正确'; return false
  }
  errors.phone = ''; return true
}

// ── 提交 ──────────────────────────────────────────────
async function handleSubmit() {
  errorMsg.value  = ''
  successMsg.value = ''
  const ok = isLogin.value
    ? validateUsername() && validatePassword()
    : validateUsername() && validatePassword() && validateConfirm() && validateEmail() && validatePhone()
  if (!ok) return

  loading.value = true
  try {
    if (isLogin.value) {
      await authStore.login(username.value.trim(), password.value)
      const realRole = authStore.user?.role
      if (realRole) {
        matchedPersona.value = roleToPersona(realRole)
        syncCarouselMode()
      }
    } else {
      const uname = username.value.trim()
      await authStore.register(
        uname,
        password.value,
        email.value || undefined,
        phone.value || undefined,
      )
      switchMode('login')
      username.value = uname
      successMsg.value = '注册成功！请使用账号密码登录'
    }
  } catch (err: unknown) {
    errorMsg.value = err instanceof Error ? err.message : '操作失败，请稍后重试'
  } finally {
    loading.value = false
  }
}
</script>

<style lang="scss" scoped>
$green:    #22C55E;
$green-d:  #15803D;
$green-dk: #0A4A20;
$ink:      #0F172A;
$muted:    #64748B;
$border:   #E2E8F0;
$red:      #DC2626;
$font-cn:  'Noto Sans SC', 'PingFang SC', 'Microsoft YaHei', sans-serif;

// ── 旋转动画 ─────────────────────────────────────────────
@keyframes spin {
  to { transform: rotate(360deg); }
}
@keyframes fadeSlideUp {
  from { opacity: 0; transform: translateY(20rpx); }
  to   { opacity: 1; transform: translateY(0); }
}

// ── Page ─────────────────────────────────────────────────
.page {
  min-height: 100vh;
  background: #fff;
  display: flex;
  flex-direction: column;
  font-family: $font-cn;
  overflow: hidden;
}

// ── 顶部品牌区 ───────────────────────────────────────────
.top-area {
  height: 360rpx;
  position: relative;
  overflow: hidden;
  flex-shrink: 0;
}

.top-bg-img {
  position: absolute;
  top: 0; left: 0;
  width: 100%; height: 100%;
  z-index: 0;
}

.top-brand {
  position: absolute;
  bottom: 36rpx;
  left: 0; right: 0;
  z-index: 2;
  display: flex;
  flex-direction: column;
  align-items: center;
}

.top-brand__slogan {
  font-size: 32rpx;
  font-weight: 700;
  line-height: 1.35;
  color: #ffffff;
  letter-spacing: 4rpx;
  text-shadow: 0 2rpx 10rpx rgba(0,0,0,0.35);
}

.bottom-brand {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 16rpx;
  padding: 24rpx 0 36rpx;
  flex-shrink: 0;
  background: #fff;
}

.brand-logo {
  width: 60rpx; height: 60rpx;
  svg { width: 100%; height: 100%; }
}

.brand-name {
  font-size: 30rpx;
  font-weight: 800;
  color: $green-dk;
  letter-spacing: 4rpx;
  font-family: $font-cn;
}

// ── 卡片 ─────────────────────────────────────────────────
.card {
  flex: 1;
  background: #fff;
  border-radius: 44rpx 44rpx 0 0;
  margin-top: -32rpx;
  padding: 40rpx 44rpx 60rpx;
  box-shadow: 0 -8rpx 40rpx rgba(0,80,0,0.07);
  overflow-y: auto;
  animation: fadeSlideUp 0.4s ease both;
}

// ── Banner ───────────────────────────────────────────────
.banner {
  display: flex;
  align-items: flex-start;
  gap: 14rpx;
  padding: 20rpx 22rpx;
  border-radius: 16rpx;
  margin-bottom: 22rpx;
  animation: fadeSlideUp 0.25s ease both;

  svg { width: 36rpx; height: 36rpx; flex-shrink: 0; margin-top: 2rpx; }

  text {
    font-size: 24rpx;
    line-height: 1.5;
    font-family: $font-cn;
    flex: 1;
  }

  &-success {
    background: #F0FDF4;
    border: 1.5rpx solid #BBF7D0;
    text { color: #15803D; }
  }
  &-error {
    background: #FEF2F2;
    border: 1.5rpx solid #FECACA;
    text { color: $red; }
  }
}

// ── 轮播区 ──────────────────────────────────────────────
.carousel-wrap {
  margin: -10rpx -10rpx 28rpx;
  padding: 20rpx 0 12rpx;
  overflow: hidden;
  animation: fadeSlideUp 0.35s ease both;
}

.carousel-track {
  position: relative;
  height: 330rpx;
  display: flex;
  align-items: center;
  justify-content: center;
}

.carousel-item {
  position: absolute;
  width: 54%;
  padding: 24rpx 20rpx 22rpx;
  border-radius: 24rpx;
  border: none;
  background: #ffffff;
  display: flex;
  flex-direction: column;
  align-items: center;
  box-shadow: 0 4rpx 16rpx rgba(18, 60, 37, 0.06);
  transition: transform 0.8s cubic-bezier(0.4, 0, 0.2, 1),
              opacity 0.8s cubic-bezier(0.4, 0, 0.2, 1),
              box-shadow 0.8s cubic-bezier(0.4, 0, 0.2, 1);
  will-change: transform, opacity;

  &--active {
    box-shadow: 0 16rpx 48rpx rgba(18, 80, 40, 0.15),
                0 4rpx 12rpx rgba(18, 60, 37, 0.08);
  }

  &--repair {
    background: linear-gradient(160deg, #ffffff 0%, #eef8f1 50%, #e2f3e8 100%);
  }
  &--ops {
    background: linear-gradient(160deg, #ffffff 0%, #eaf6f0 50%, #ddf1e6 100%);
  }
  &--user {
    background: linear-gradient(160deg, #ffffff 0%, #f0f9f3 50%, #e5f5eb 100%);
  }
}

.carousel-item__anim {
  width: 100%;
  height: 185rpx;
  margin-bottom: 16rpx;
  border-radius: 16rpx;
  background: radial-gradient(ellipse 80% 70% at 50% 45%,
    rgba(34, 197, 94, 0.10) 0%,
    rgba(34, 197, 94, 0.03) 55%,
    transparent 100%);

  &--repair {
    filter: saturate(1.08);
    transform: translateX(-42rpx) scale(1.3);
    transform-origin: center center;
  }
  &--ops {
    filter: hue-rotate(8deg) saturate(1.1);
    transform: translateY(20rpx) scale(1.22);
    transform-origin: center center;
  }
  &--user   { filter: hue-rotate(-6deg) saturate(0.96); }
}

.carousel-item__footer {
  width: 100%;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12rpx;
  padding: 0 4rpx;
}

.carousel-item__title {
  font-size: 28rpx;
  font-weight: 700;
  color: #163827;
  line-height: 1.3;
  letter-spacing: 1rpx;
  flex: 1;
}

.carousel-item__meta {
  flex-shrink: 0;
  padding: 8rpx 18rpx;
  border-radius: 999rpx;
  background: linear-gradient(135deg, #e8f5ec 0%, #d4eddb 100%);
  color: #1a6b3a;
  font-size: 20rpx;
  font-weight: 600;
  line-height: 1;
  letter-spacing: 1rpx;
}

// ── 指示器 ──────────────────────────────────────────────
.carousel-dots {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 14rpx;
  margin-top: 20rpx;
}

.carousel-dot {
  width: 12rpx;
  height: 12rpx;
  border-radius: 50%;
  background: #c8dccf;
  transition: all 0.4s cubic-bezier(0.4, 0, 0.2, 1);

  &--active {
    width: 36rpx;
    border-radius: 6rpx;
    background: linear-gradient(90deg, $green-d 0%, $green 100%);
    box-shadow: 0 2rpx 8rpx rgba(21, 128, 61, 0.3);
  }
}

// ── 表单 ─────────────────────────────────────────────────
.form {
  display: flex;
  flex-direction: column;
  gap: 22rpx;
  animation: fadeSlideUp 0.3s ease both;
}

.field {
  display: flex;
  flex-direction: column;
  gap: 10rpx;
}

.label {
  font-size: 24rpx;
  font-weight: 600;
  color: #334155;
  letter-spacing: 1rpx;
  font-family: $font-cn;
}

.req {
  color: $red;
  margin-left: 4rpx;
  font-weight: 700;
}

// Input wrap
.iw {
  display: flex;
  align-items: center;
  gap: 16rpx;
  height: 96rpx;
  background: #F8FAFC;
  border: 2rpx solid $border;
  border-radius: 18rpx;
  padding: 0 24rpx;
  transition: border-color 0.18s, box-shadow 0.18s, background 0.18s;

  &--focus {
    border-color: $green;
    background: #fff;
    box-shadow: 0 0 0 6rpx rgba(34,197,94,0.10);
  }

  &--err {
    border-color: $red;
    background: #fff;
    box-shadow: 0 0 0 6rpx rgba(220,38,38,0.08);
  }
}

.ico {
  width: 36rpx; height: 36rpx;
  flex-shrink: 0;
  color: #94A3B8;
  transition: color 0.18s;

  .iw--focus & { color: $green-d; }
  .iw--err &   { color: $red; }
}

.inp {
  flex: 1;
  height: 100%;
  background: transparent;
  border: none;
  outline: none;
  font-size: 28rpx;
  color: $ink;
  font-family: $font-cn;
  font-weight: 400;
  min-width: 0;
}

.ph { color: #CBD5E1; }

.eye-btn {
  width: 44rpx; height: 44rpx;
  display: flex; align-items: center; justify-content: center;
  color: #94A3B8;
  cursor: pointer;
  flex-shrink: 0;
  svg { width: 36rpx; height: 36rpx; }
}

.ferr {
  font-size: 22rpx;
  color: $red;
  padding-left: 6rpx;
  font-family: $font-cn;
}

// ── 提交按钮 ─────────────────────────────────────────────
.submit-btn {
  width: 100%;
  height: 100rpx;
  border-radius: 50rpx;
  border: none;
  background: linear-gradient(90deg, $green-d 0%, $green 100%);
  color: #fff;
  font-size: 30rpx;
  font-weight: 700;
  letter-spacing: 6rpx;
  font-family: $font-cn;
  margin-top: 8rpx;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 16rpx;
  box-shadow: 0 8rpx 28rpx rgba(21,128,61,0.32);
  cursor: pointer;
  transition: opacity 0.18s, transform 0.12s;

  &:active:not([disabled]) {
    opacity: 0.88;
    transform: scale(0.98);
  }

  &[disabled] {
    opacity: 0.5;
    box-shadow: none;
    cursor: not-allowed;
  }
}

.spin {
  width: 36rpx; height: 36rpx;
  border: 4rpx solid rgba(255,255,255,0.35);
  border-top-color: #fff;
  border-radius: 50%;
  animation: spin 0.7s linear infinite;
  flex-shrink: 0;
}

// ── 切换行 ───────────────────────────────────────────────
.switch-row {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8rpx;
  margin-top: 36rpx;
}

.switch-hint {
  font-size: 24rpx;
  color: $muted;
  font-family: $font-cn;
}

.switch-link {
  font-size: 24rpx;
  font-weight: 700;
  color: $green-d;
  font-family: $font-cn;
  cursor: pointer;
  text-decoration: underline;
  text-underline-offset: 4rpx;
}
</style>
