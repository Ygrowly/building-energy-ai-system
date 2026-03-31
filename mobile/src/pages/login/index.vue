<template>
  <view class="page">

    <!-- ══ 顶部品牌区 ══ -->
    <view class="top-area">
<!-- 背景城市图片 -->
    <image class="top-bg-img" src="/static/images/bangkok-city.jpg" mode="aspectFill"/>

      <view class="brand-wrap">
        <view class="brand-logo">
          <svg viewBox="0 0 32 32" fill="none">
            <rect width="32" height="32" rx="9" fill="rgba(255,255,255,0.22)"/>
            <path d="M18 4L8 18h8l-2 10 12-14h-8V4z" fill="white"/>
          </svg>
        </view>
        <text class="brand-name">建筑能源</text>
      </view>

      <view class="top-text">
        <text class="top-title">{{ isLogin ? '欢迎回来' : '创建账号' }}</text>
        <text class="top-sub">{{ isLogin ? '登录账号以继续使用' : '填写信息完成注册' }}</text>
      </view>
    </view>

    <!-- ══ 表单卡片 ══ -->
    <view class="card">

      <!-- Tab 切换 -->
      <view class="tab-bar">
        <view class="tab" :class="{ active: isLogin }" @click="switchMode('login')">
          <text>登 录</text>
        </view>
        <view class="tab" :class="{ active: !isLogin }" @click="switchMode('register')">
          <text>注 册</text>
        </view>
        <view class="tab-indicator" :class="{ right: !isLogin }"/>
      </view>

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

  </view>
</template>

<script setup lang="ts">
import { ref, reactive, computed } from 'vue'
import { useAuthStore } from '../../stores/auth'

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
  background: #F0FDF4;
  display: flex;
  flex-direction: column;
  font-family: $font-cn;
  overflow: hidden;
}

// ── 顶部品牌区 ───────────────────────────────────────────
.top-area {
  padding: 80rpx 48rpx 80rpx;
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

.top-overlay {
  position: absolute;
  top: 0; left: 0;
  width: 100%; height: 100%;
  z-index: 1;
  background: linear-gradient(
    160deg,
    rgba(10, 74, 32, 0.72) 0%,
    rgba(21, 128, 61, 0.55) 50%,
    rgba(34, 197, 94, 0.38) 100%
  );
}

.brand-wrap {
  display: flex;
  align-items: center;
  gap: 16rpx;
  margin-bottom: 36rpx;
  position: relative;
  z-index: 2;
}

.brand-logo {
  width: 60rpx; height: 60rpx;
  svg { width: 100%; height: 100%; }
}

.brand-name {
  font-size: 30rpx;
  font-weight: 800;
  color: #fff;
  letter-spacing: 4rpx;
  font-family: $font-cn;
}

.top-text {
  position: relative;
  z-index: 2;
}

.top-title {
  display: block;
  font-size: 60rpx;
  font-weight: 900;
  color: #fff;
  letter-spacing: 2rpx;
  line-height: 1.15;
  font-family: $font-cn;
  text-shadow: 0 2rpx 12rpx rgba(0,0,0,0.12);
}

.top-sub {
  display: block;
  font-size: 24rpx;
  color: rgba(255,255,255,0.82);
  margin-top: 10rpx;
  letter-spacing: 1.5rpx;
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

// ── Tab 切换 ─────────────────────────────────────────────
.tab-bar {
  display: flex;
  background: #F1F5F9;
  border-radius: 20rpx;
  padding: 6rpx;
  margin-bottom: 36rpx;
  position: relative;
  height: 80rpx;
}

.tab {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 14rpx;
  position: relative;
  z-index: 1;
  cursor: pointer;
  transition: color 0.22s;

  text {
    font-size: 28rpx;
    font-weight: 600;
    color: $muted;
    letter-spacing: 3rpx;
    font-family: $font-cn;
    transition: color 0.22s;
  }

  &.active text {
    color: $green-d;
  }
}

.tab-indicator {
  position: absolute;
  top: 6rpx;
  left: 6rpx;
  width: calc(50% - 6rpx);
  bottom: 6rpx;
  background: #fff;
  border-radius: 14rpx;
  box-shadow: 0 2rpx 12rpx rgba(0,0,0,0.08);
  transition: transform 0.26s cubic-bezier(0.34,1.56,0.64,1);
  &.right { transform: translateX(100%); }
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
