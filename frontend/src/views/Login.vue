<template>
  <div class="auth-page">
    <!-- 背景装饰 -->
    <div class="bg-glow bg-glow-1" />
    <div class="bg-glow bg-glow-2" />

    <div class="auth-card">
      <!-- 顶部 Logo -->
      <div class="auth-logo">
        <div class="logo-icon">
          <Icon icon="mdi:lightning-bolt" width="22" />
        </div>
        <div class="logo-text">
          <span class="logo-title">楼宇能耗</span>
          <span class="logo-sub">智能管理系统</span>
        </div>
      </div>

      <!-- 模式切换 Tab -->
      <div class="auth-tabs">
        <button
          class="tab-btn"
          :class="{ active: mode === 'login' }"
          @click="switchMode('login')"
        >
          登录
        </button>
        <button
          class="tab-btn"
          :class="{ active: mode === 'register' }"
          @click="switchMode('register')"
        >
          注册账号
        </button>
        <div class="tab-indicator" :class="{ right: mode === 'register' }" />
      </div>

      <!-- 表单 -->
      <form class="auth-form" @submit.prevent="handleSubmit">
        <!-- 错误提示 -->
        <Transition name="err-fade">
          <div v-if="errorMsg" class="error-banner">
            <Icon icon="mdi:alert-circle-outline" width="15" />
            <span>{{ errorMsg }}</span>
          </div>
        </Transition>

        <!-- 注册成功提示 -->
        <Transition name="err-fade">
          <div v-if="successMsg" class="success-banner">
            <Icon icon="mdi:check-circle-outline" width="15" />
            <span>{{ successMsg }}</span>
          </div>
        </Transition>

        <!-- 用户名 -->
        <div class="field">
          <label class="field-label">用户名</label>
          <div class="input-wrap" :class="{ focused: usernameFocused, error: fieldErrors.username }">
            <Icon icon="mdi:account-outline" width="16" class="input-icon" />
            <input
              v-model="username"
              type="text"
              placeholder="3~50 个字符，字母/数字/下划线"
              autocomplete="username"
              spellcheck="false"
              @focus="usernameFocused = true"
              @blur="usernameFocused = false; validateUsername()"
            />
          </div>
          <span v-if="fieldErrors.username" class="field-error">{{ fieldErrors.username }}</span>
        </div>

        <!-- 密码 -->
        <div class="field">
          <label class="field-label">密码</label>
          <div class="input-wrap" :class="{ focused: passwordFocused, error: fieldErrors.password }">
            <Icon icon="mdi:lock-outline" width="16" class="input-icon" />
            <input
              v-model="password"
              :type="showPassword ? 'text' : 'password'"
              :placeholder="mode === 'register' ? '至少 8 位，包含字母和数字' : '请输入密码'"
              autocomplete="current-password"
              @focus="passwordFocused = true"
              @blur="passwordFocused = false; validatePassword()"
            />
            <button
              type="button"
              class="toggle-pw"
              @click="showPassword = !showPassword"
              tabindex="-1"
            >
              <Icon :icon="showPassword ? 'mdi:eye-off-outline' : 'mdi:eye-outline'" width="16" />
            </button>
          </div>
          <span v-if="fieldErrors.password" class="field-error">{{ fieldErrors.password }}</span>
        </div>

        <!-- 注册模式：确认密码 -->
        <Transition name="field-slide">
          <div v-if="mode === 'register'" class="field">
            <label class="field-label">确认密码</label>
            <div class="input-wrap" :class="{ focused: confirmFocused, error: fieldErrors.confirm }">
              <Icon icon="mdi:lock-check-outline" width="16" class="input-icon" />
              <input
                v-model="confirmPassword"
                :type="showPassword ? 'text' : 'password'"
                placeholder="再次输入密码"
                autocomplete="new-password"
                @focus="confirmFocused = true"
                @blur="confirmFocused = false; validateConfirm()"
              />
            </div>
            <span v-if="fieldErrors.confirm" class="field-error">{{ fieldErrors.confirm }}</span>
          </div>
        </Transition>

        <!-- 提交按钮 -->
        <button type="submit" class="submit-btn" :disabled="loading">
          <Transition name="btn-content" mode="out-in">
            <span v-if="loading" key="loading" class="btn-loading">
              <Icon icon="mdi:loading" width="17" class="spin" />
              {{ mode === 'login' ? '登录中...' : '注册中...' }}
            </span>
            <span v-else key="idle" class="btn-idle">
              <Icon :icon="mode === 'login' ? 'mdi:login' : 'mdi:account-plus-outline'" width="17" />
              {{ mode === 'login' ? '登录' : '创建账号' }}
            </span>
          </Transition>
        </button>
      </form>

      <!-- 底部分割线 + 切换提示 -->
      <div class="auth-footer">
        <span class="footer-hint">
          {{ mode === 'login' ? '还没有账号？' : '已有账号？' }}
          <button class="switch-link" @click="switchMode(mode === 'login' ? 'register' : 'login')">
            {{ mode === 'login' ? '立即注册' : '去登录' }}
          </button>
        </span>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive } from 'vue'
import { useRouter } from 'vue-router'
import { Icon } from '@iconify/vue'
import { useAuthStore } from '@/stores/authStore'

type Mode = 'login' | 'register'

const router = useRouter()
const authStore = useAuthStore()

const mode = ref<Mode>('login')
const username = ref('')
const password = ref('')
const confirmPassword = ref('')
const showPassword = ref(false)
const loading = ref(false)
const errorMsg = ref('')
const successMsg = ref('')

const usernameFocused = ref(false)
const passwordFocused = ref(false)
const confirmFocused = ref(false)

const fieldErrors = reactive({ username: '', password: '', confirm: '' })

function switchMode(m: Mode) {
  mode.value = m
  errorMsg.value = ''
  successMsg.value = ''
  fieldErrors.username = ''
  fieldErrors.password = ''
  fieldErrors.confirm = ''
  password.value = ''
  confirmPassword.value = ''
}

// ── 字段校验 ─────────────────────────────────────────────
function validateUsername(): boolean {
  if (!username.value) {
    fieldErrors.username = '请输入用户名'
    return false
  }
  if (mode.value === 'register') {
    if (username.value.length < 3) {
      fieldErrors.username = '用户名至少 3 个字符'
      return false
    }
    if (!/^\w+$/.test(username.value)) {
      fieldErrors.username = '只允许字母、数字和下划线'
      return false
    }
  }
  fieldErrors.username = ''
  return true
}

function validatePassword(): boolean {
  if (!password.value) {
    fieldErrors.password = '请输入密码'
    return false
  }
  if (mode.value === 'register') {
    if (password.value.length < 8) {
      fieldErrors.password = '密码至少 8 个字符'
      return false
    }
    if (!/[A-Za-z]/.test(password.value)) {
      fieldErrors.password = '密码必须包含至少一个字母'
      return false
    }
    if (!/\d/.test(password.value)) {
      fieldErrors.password = '密码必须包含至少一个数字'
      return false
    }
  }
  fieldErrors.password = ''
  return true
}

function validateConfirm(): boolean {
  if (mode.value !== 'register') return true
  if (!confirmPassword.value) {
    fieldErrors.confirm = '请确认密码'
    return false
  }
  if (confirmPassword.value !== password.value) {
    fieldErrors.confirm = '两次输入的密码不一致'
    return false
  }
  fieldErrors.confirm = ''
  return true
}

// ── 提交 ─────────────────────────────────────────────────
async function handleSubmit() {
  errorMsg.value = ''
  successMsg.value = ''

  const usernameOk = validateUsername()
  const passwordOk = validatePassword()
  const confirmOk = validateConfirm()
  if (!usernameOk || !passwordOk || !confirmOk) return

  loading.value = true
  try {
    if (mode.value === 'login') {
      await authStore.login(username.value, password.value)
    } else {
      await authStore.register(username.value, password.value)
    }
    router.replace('/dashboard')
  } catch (err: unknown) {
    const msg = err instanceof Error ? err.message : '操作失败，请稍后重试'
    errorMsg.value = msg
  } finally {
    loading.value = false
  }
}
</script>

<style scoped>
/* ── 全屏背景 ── */
.auth-page {
  min-height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--bg-dark);
  padding: 20px;
  position: relative;
  overflow: hidden;
}

/* 背景光晕装饰 */
.bg-glow {
  position: absolute;
  border-radius: 50%;
  filter: blur(80px);
  pointer-events: none;
}
.bg-glow-1 {
  width: 480px;
  height: 480px;
  background: radial-gradient(circle, rgba(96, 165, 250, 0.08) 0%, transparent 70%);
  top: -100px;
  left: -100px;
}
.bg-glow-2 {
  width: 360px;
  height: 360px;
  background: radial-gradient(circle, rgba(34, 211, 238, 0.06) 0%, transparent 70%);
  bottom: -80px;
  right: -60px;
}

/* ── 卡片 ── */
.auth-card {
  width: 100%;
  max-width: 400px;
  background: var(--bg-panel);
  border: 1px solid var(--border);
  border-radius: 16px;
  padding: 32px;
  box-shadow: var(--panel-shadow), 0 0 0 1px rgba(96, 165, 250, 0.04);
  position: relative;
  z-index: 1;
}

/* ── Logo ── */
.auth-logo {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 28px;
}
.logo-icon {
  width: 40px;
  height: 40px;
  background: var(--accent);
  border-radius: 12px;
  display: flex;
  align-items: center;
  justify-content: center;
  color: #fff;
  flex-shrink: 0;
  box-shadow: 0 4px 16px rgba(96, 165, 250, 0.35);
}
.logo-text {
  display: flex;
  flex-direction: column;
  gap: 1px;
}
.logo-title {
  font-size: 15px;
  font-weight: 700;
  color: var(--text-primary);
  letter-spacing: 0.02em;
}
.logo-sub {
  font-size: 11px;
  color: var(--text-secondary);
  letter-spacing: 0.03em;
}

/* ── 模式 Tab ── */
.auth-tabs {
  display: flex;
  position: relative;
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: 10px;
  padding: 3px;
  margin-bottom: 24px;
}
.tab-btn {
  flex: 1;
  padding: 8px 0;
  background: none;
  border: none;
  border-radius: 8px;
  font-size: 13px;
  font-weight: 500;
  color: var(--text-secondary);
  cursor: pointer;
  position: relative;
  z-index: 1;
  transition: color 0.2s;
}
.tab-btn.active {
  color: var(--accent);
}
.tab-indicator {
  position: absolute;
  top: 3px;
  left: 3px;
  width: calc(50% - 3px);
  bottom: 3px;
  background: var(--bg-hover);
  border: 1px solid var(--border-accent);
  border-radius: 8px;
  transition: transform 0.22s cubic-bezier(0.4, 0, 0.2, 1);
  box-shadow: 0 1px 4px rgba(0, 0, 0, 0.3);
}
.tab-indicator.right {
  transform: translateX(100%);
}

/* ── 表单 ── */
.auth-form {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

/* 错误 / 成功 Banner */
.error-banner,
.success-banner {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 12px;
  border-radius: 8px;
  font-size: 13px;
}
.error-banner {
  background: rgba(248, 113, 113, 0.1);
  border: 1px solid rgba(248, 113, 113, 0.25);
  color: var(--danger);
}
.success-banner {
  background: rgba(74, 222, 128, 0.1);
  border: 1px solid rgba(74, 222, 128, 0.25);
  color: var(--success);
}

/* 字段 */
.field {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.field-label {
  font-size: 12px;
  font-weight: 500;
  color: var(--text-secondary);
  letter-spacing: 0.03em;
}
.input-wrap {
  display: flex;
  align-items: center;
  gap: 8px;
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: 9px;
  padding: 10px 12px;
  transition: all 0.2s;
}
.input-wrap.focused {
  border-color: var(--accent);
  background: var(--bg-hover);
  box-shadow: 0 0 0 3px var(--accent-glow);
}
.input-wrap.error {
  border-color: var(--danger);
  box-shadow: 0 0 0 3px rgba(248, 113, 113, 0.1);
}
.input-icon {
  color: var(--text-muted);
  flex-shrink: 0;
  transition: color 0.2s;
}
.input-wrap.focused .input-icon {
  color: var(--accent);
}
.input-wrap input {
  flex: 1;
  background: none;
  border: none;
  outline: none;
  font-size: 13px;
  color: var(--text-primary);
  font-family: inherit;
}
.input-wrap input::placeholder {
  color: var(--text-muted);
}
.toggle-pw {
  background: none;
  border: none;
  padding: 0;
  color: var(--text-muted);
  cursor: pointer;
  display: flex;
  align-items: center;
  transition: color 0.2s;
  flex-shrink: 0;
}
.toggle-pw:hover {
  color: var(--text-secondary);
}
.field-error {
  font-size: 11px;
  color: var(--danger);
  padding-left: 2px;
}

/* 提交按钮 */
.submit-btn {
  width: 100%;
  padding: 12px;
  background: var(--accent);
  border: none;
  border-radius: 9px;
  color: #fff;
  font-size: 14px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.2s;
  margin-top: 4px;
  letter-spacing: 0.02em;
  box-shadow: 0 4px 16px rgba(96, 165, 250, 0.25);
}
.submit-btn:hover:not(:disabled) {
  filter: brightness(1.1);
  transform: translateY(-1px);
  box-shadow: 0 6px 24px rgba(96, 165, 250, 0.35);
}
.submit-btn:active:not(:disabled) {
  transform: translateY(0);
}
.submit-btn:disabled {
  opacity: 0.65;
  cursor: not-allowed;
}
.btn-loading,
.btn-idle {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 7px;
}

/* ── 底部 ── */
.auth-footer {
  margin-top: 20px;
  text-align: center;
}
.footer-hint {
  font-size: 12px;
  color: var(--text-secondary);
}
.switch-link {
  background: none;
  border: none;
  color: var(--accent);
  font-size: 12px;
  font-weight: 500;
  cursor: pointer;
  padding: 0;
  margin-left: 4px;
  transition: opacity 0.2s;
}
.switch-link:hover {
  opacity: 0.8;
  text-decoration: underline;
}

/* ── 动画 ── */
.err-fade-enter-active,
.err-fade-leave-active {
  transition: opacity 0.2s, transform 0.2s;
}
.err-fade-enter-from,
.err-fade-leave-to {
  opacity: 0;
  transform: translateY(-6px);
}

.field-slide-enter-active,
.field-slide-leave-active {
  transition: opacity 0.22s, transform 0.22s, max-height 0.22s;
  max-height: 80px;
  overflow: hidden;
}
.field-slide-enter-from,
.field-slide-leave-to {
  opacity: 0;
  transform: translateY(-4px);
  max-height: 0;
}

.btn-content-enter-active,
.btn-content-leave-active {
  transition: opacity 0.15s;
}
.btn-content-enter-from,
.btn-content-leave-to {
  opacity: 0;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}
.spin {
  animation: spin 0.8s linear infinite;
}
</style>
