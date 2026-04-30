<template>
  <div class="page">
    <!-- ════════════════ 登录模式：左图 + 右表单 ════════════════ -->
    <div v-if="mode === 'login'" class="card card-login">
      <!-- 左侧封面图 -->
      <div class="cover">
        <img src="@/assets/building.jpg" alt="楼宇" class="cover-img" />
        <div class="cover-overlay">
          <div class="cover-brand">
            <div class="cover-icon">
              <Icon icon="mdi:lightning-bolt" width="22" />
            </div>
            <span class="cover-title">楼宇能耗管理系统</span>
          </div>
          <p class="cover-sub">智能化能源监控 · 高效节能管理</p>
        </div>
      </div>

      <!-- 右侧登录表单 -->
      <div class="panel">
        <div class="panel-inner">
          <h2 class="form-title">欢迎回来</h2>
          <p class="form-sub">登录您的账号以继续</p>

          <Transition name="banner">
            <div v-if="registerSuccessMsg" class="banner banner-success">
              <Icon icon="mdi:check-circle-outline" width="15" />
              <span>{{ registerSuccessMsg }}</span>
            </div>
          </Transition>

          <Transition name="banner">
            <div v-if="errorMsg" class="banner banner-error">
              <Icon icon="mdi:alert-circle-outline" width="15" />
              <span>{{ errorMsg }}</span>
            </div>
          </Transition>

          <form class="form" @submit.prevent="handleSubmit" novalidate>
            <!-- 用户名 -->
            <div class="field">
              <label class="label">用户名</label>
              <div class="iw" :class="{ focus: f.username, err: e.username }">
                <Icon icon="mdi:account-outline" width="16" class="ii" />
                <input
                  v-model="username"
                  type="text"
                  placeholder="请输入用户名"
                  autocomplete="username"
                  :disabled="loading"
                  spellcheck="false"
                  @focus="f.username = true"
                  @blur="f.username = false"
                />
              </div>
              <span v-if="e.username" class="ferr">{{ e.username }}</span>
            </div>

            <!-- 密码 -->
            <div class="field">
              <label class="label">密码</label>
              <div class="iw" :class="{ focus: f.password, err: e.password }">
                <Icon icon="mdi:lock-outline" width="16" class="ii" />
                <input
                  v-model="password"
                  :type="showPw ? 'text' : 'password'"
                  placeholder="请输入密码"
                  autocomplete="current-password"
                  :disabled="loading"
                  @focus="f.password = true"
                  @blur="f.password = false"
                />
                <button
                  type="button"
                  class="eye"
                  :disabled="loading"
                  @click="showPw = !showPw"
                  tabindex="-1"
                >
                  <Icon :icon="showPw ? 'mdi:eye-off-outline' : 'mdi:eye-outline'" width="16" />
                </button>
              </div>
              <span v-if="e.password" class="ferr">{{ e.password }}</span>
            </div>

            <button type="submit" class="btn-primary" :disabled="loading" :aria-busy="loading">
              <Icon v-if="loading" icon="mdi:loading" width="16" class="spin" />
              <Icon v-else icon="mdi:login" width="16" />
              {{ loading ? '校验中...' : '登录' }}
            </button>
          </form>

          <div class="test-account">
            <div class="test-account__title">测试账号</div>
            <div class="test-account__row">
              <span class="test-account__role">运维人员账号</span>
              <span class="test-account__value">用户名：test1，密码：test1234</span>
            </div>
            <div class="test-account__row">
              <span class="test-account__role">维修人员账号</span>
              <span class="test-account__value">用户名：test2，密码：test1234</span>
            </div>
          </div>

          <p class="switch-hint">
            还没有账号？
            <button class="link" :disabled="loading" @click="switchMode('register')">立即注册</button>
          </p>
        </div>
      </div>
    </div>

    <!-- ════════════════ 注册模式：全宽表单 ════════════════ -->
    <div v-else class="card card-register">
      <div class="reg-inner">
        <!-- 头部品牌 -->
        <div class="reg-header">
          <div class="reg-brand">
            <div class="reg-icon">
              <Icon icon="mdi:lightning-bolt" width="20" />
            </div>
            <span class="reg-name">楼宇能耗管理系统</span>
          </div>
          <div class="reg-titles">
            <h2 class="form-title">创建账号</h2>
            <p class="form-sub">填写以下信息完成注册</p>
          </div>
        </div>

        <Transition name="banner">
          <div v-if="errorMsg" class="banner banner-error">
            <Icon icon="mdi:alert-circle-outline" width="15" />
            <span>{{ errorMsg }}</span>
          </div>
        </Transition>

        <form class="form reg-form" @submit.prevent="handleSubmit" novalidate>
          <!-- 第一行：用户名 + 邮箱 -->
          <div class="reg-row">
            <div class="field">
              <label class="label">用户名 <span class="required">*</span></label>
              <div class="iw" :class="{ focus: f.username, err: e.username }">
                <Icon icon="mdi:account-outline" width="16" class="ii" />
                <input
                  v-model="username"
                  type="text"
                  placeholder="3~50 字符，字母/数字/下划线"
                  autocomplete="username"
                  spellcheck="false"
                  @focus="f.username = true"
                  @blur="f.username = false; validateUsername()"
                />
              </div>
              <span v-if="e.username" class="ferr">{{ e.username }}</span>
            </div>

            <div class="field">
              <label class="label">邮箱</label>
              <div class="iw" :class="{ focus: f.email, err: e.email }">
                <Icon icon="mdi:email-outline" width="16" class="ii" />
                <input
                  v-model="email"
                  type="email"
                  placeholder="example@company.com"
                  autocomplete="email"
                  @focus="f.email = true"
                  @blur="f.email = false; validateEmail()"
                />
              </div>
              <span v-if="e.email" class="ferr">{{ e.email }}</span>
            </div>
          </div>

          <!-- 第二行：手机号（单独一行） -->
          <div class="field">
            <label class="label">手机号</label>
            <div class="iw" :class="{ focus: f.phone, err: e.phone }">
              <Icon icon="mdi:phone-outline" width="16" class="ii" />
              <input
                v-model="phone"
                type="tel"
                placeholder="请输入手机号"
                autocomplete="tel"
                @focus="f.phone = true"
                @blur="f.phone = false; validatePhone()"
              />
            </div>
            <span v-if="e.phone" class="ferr">{{ e.phone }}</span>
          </div>

          <!-- 第三行：密码 + 确认密码 -->
          <div class="reg-row">
            <div class="field">
              <label class="label">密码 <span class="required">*</span></label>
              <div class="iw" :class="{ focus: f.password, err: e.password }">
                <Icon icon="mdi:lock-outline" width="16" class="ii" />
                <input
                  v-model="password"
                  :type="showPw ? 'text' : 'password'"
                  placeholder="至少 8 位，含字母和数字"
                  autocomplete="new-password"
                  @focus="f.password = true"
                  @blur="f.password = false; validatePassword()"
                />
                <button type="button" class="eye" @click="showPw = !showPw" tabindex="-1">
                  <Icon :icon="showPw ? 'mdi:eye-off-outline' : 'mdi:eye-outline'" width="16" />
                </button>
              </div>
              <span v-if="e.password" class="ferr">{{ e.password }}</span>
            </div>

            <div class="field">
              <label class="label">确认密码 <span class="required">*</span></label>
              <div class="iw" :class="{ focus: f.confirm, err: e.confirm }">
                <Icon icon="mdi:lock-check-outline" width="16" class="ii" />
                <input
                  v-model="confirmPassword"
                  :type="showPw ? 'text' : 'password'"
                  placeholder="再次输入密码"
                  autocomplete="new-password"
                  @focus="f.confirm = true"
                  @blur="f.confirm = false; validateConfirm()"
                />
              </div>
              <span v-if="e.confirm" class="ferr">{{ e.confirm }}</span>
            </div>
          </div>

          <button type="submit" class="btn-primary" :disabled="loading">
            <Icon v-if="loading" icon="mdi:loading" width="16" class="spin" />
            <Icon v-else icon="mdi:account-plus-outline" width="16" />
            {{ loading ? '注册中...' : '创建账号' }}
          </button>
        </form>

        <p class="switch-hint">
          已有账号？
          <button class="link" :disabled="loading" @click="switchMode('login')">去登录</button>
        </p>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { Icon } from '@iconify/vue'
import { useAuthStore } from '@/stores/authStore'

type Mode = 'login' | 'register'

const router = useRouter()
const route  = useRoute()
const authStore = useAuthStore()

const mode            = ref<Mode>('login')
const username        = ref('')
const password        = ref('')
const confirmPassword = ref('')
const email           = ref('')
const phone           = ref('')
const showPw          = ref(false)
const loading              = ref(false)
const errorMsg             = ref('')
const registerSuccessMsg   = ref('')

// focus 状态
const f = reactive({ username: false, password: false, confirm: false, email: false, phone: false })
// 字段错误
const e = reactive({ username: '', password: '', confirm: '', email: '', phone: '' })

function switchMode(m: Mode) {
  mode.value             = m
  errorMsg.value         = ''
  registerSuccessMsg.value = ''
  Object.keys(e).forEach(k => (e as Record<string, string>)[k] = '')
  password.value        = ''
  confirmPassword.value = ''
}

// ── 校验 ─────────────────────────────────────────────────
function validateUsername(): boolean {
  if (!username.value) { e.username = '请输入用户名'; return false }
  if (mode.value === 'register') {
    if (username.value.length < 3) { e.username = '用户名至少 3 个字符'; return false }
    if (!/^\w+$/.test(username.value)) { e.username = '只允许字母、数字和下划线'; return false }
  }
  e.username = ''; return true
}

function validatePassword(): boolean {
  if (!password.value) { e.password = '请输入密码'; return false }
  if (mode.value === 'register') {
    if (password.value.length < 8) { e.password = '密码至少 8 个字符'; return false }
    if (!/[A-Za-z]/.test(password.value)) { e.password = '必须包含至少一个字母'; return false }
    if (!/\d/.test(password.value)) { e.password = '必须包含至少一个数字'; return false }
  }
  e.password = ''; return true
}

function validateConfirm(): boolean {
  if (mode.value !== 'register') return true
  if (!confirmPassword.value) { e.confirm = '请确认密码'; return false }
  if (confirmPassword.value !== password.value) { e.confirm = '两次密码不一致'; return false }
  e.confirm = ''; return true
}

function validateEmail(): boolean {
  if (email.value && !/^[^@]+@[^@]+\.[^@]+$/.test(email.value)) {
    e.email = '邮箱格式不正确'; return false
  }
  e.email = ''; return true
}

function validatePhone(): boolean {
  if (phone.value && !/^[\d\+\-\(\)\s]{5,20}$/.test(phone.value)) {
    e.phone = '手机号格式不正确'; return false
  }
  e.phone = ''; return true
}

// ── 提交 ─────────────────────────────────────────────────
async function handleSubmit() {
  if (loading.value) return

  errorMsg.value = ''
  const ok =
    validateUsername() &&
    validatePassword() &&
    (mode.value === 'login' ? true : validateConfirm() && validateEmail() && validatePhone())
  if (!ok) return

  loading.value = true
  try {
    if (mode.value === 'login') {
      await authStore.login(username.value, password.value)
      const redirect = (route.query.redirect as string) || '/home'
      router.replace(redirect)
    } else {
      // 注册成功：保留用户名，跳回登录页让用户主动点击登录
      const registeredUsername = username.value
      await authStore.register(
        username.value, password.value,
        email.value || undefined, phone.value || undefined,
      )
      // 注册完立即登出内存中的 token，强制用户重新登录
      authStore._clearTokens()
      // 切换到登录模式，回填用户名
      switchMode('login')
      username.value = registeredUsername
      registerSuccessMsg.value = '注册成功！请使用账号密码登录'
    }
  } catch (err: unknown) {
    errorMsg.value = err instanceof Error ? err.message : '操作失败，请稍后重试'
  } finally {
    loading.value = false
  }
}
</script>

<style scoped>
/* ══════════════════════════════════════
   全屏背景
══════════════════════════════════════ */
.page {
  min-height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  background: #f0f2f5;
  padding: 24px;
}

/* ══════════════════════════════════════
   共用卡片
══════════════════════════════════════ */
.card {
  background: #ffffff;
  border-radius: 20px;
  box-shadow:
    0 4px 6px rgba(0,0,0,0.04),
    0 12px 40px rgba(0,0,0,0.10),
    0 0 0 1px rgba(0,0,0,0.04);
  overflow: hidden;
}

/* ══════════════════════════════════════
   登录卡：左图 + 右表单
══════════════════════════════════════ */
.card-login {
  display: flex;
  width: 900px;
  max-width: 100%;
  min-height: 540px;
}

/* 左侧封面图 */
.cover {
  width: 65%;
  flex-shrink: 0;
  position: relative;
  overflow: hidden;
}
.cover-img {
  width: 100%;
  height: 100%;
  object-fit: cover;
  display: block;
}
.cover-overlay {
  position: absolute;
  inset: 0;
  background: linear-gradient(
    160deg,
    rgba(10, 20, 50, 0.45) 0%,
    rgba(15, 30, 80, 0.62) 100%
  );
  display: flex;
  flex-direction: column;
  justify-content: flex-end;
  padding: 36px 32px;
}
.cover-brand {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 10px;
}
.cover-icon {
  width: 38px;
  height: 38px;
  background: #3b7cf4;
  border-radius: 10px;
  display: flex;
  align-items: center;
  justify-content: center;
  color: #fff;
  flex-shrink: 0;
  box-shadow: 0 4px 14px rgba(59,124,244,0.45);
}
.cover-title {
  font-size: 18px;
  font-weight: 700;
  color: #fff;
  letter-spacing: 0.03em;
  text-shadow: 0 1px 4px rgba(0,0,0,0.3);
}
.cover-sub {
  font-size: 12px;
  color: rgba(255,255,255,0.7);
  letter-spacing: 0.04em;
}

/* 右侧表单区 */
.panel {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 48px 44px;
}
.panel-inner {
  width: 100%;
  max-width: 320px;
}

/* ══════════════════════════════════════
   注册卡：全宽
══════════════════════════════════════ */
.card-register {
  width: 760px;
  max-width: 100%;
}
.reg-inner {
  padding: 44px 48px;
}
.reg-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  margin-bottom: 28px;
  flex-wrap: wrap;
  gap: 12px;
}
.reg-brand {
  display: flex;
  align-items: center;
  gap: 10px;
}
.reg-icon {
  width: 36px;
  height: 36px;
  background: #3b7cf4;
  border-radius: 9px;
  display: flex;
  align-items: center;
  justify-content: center;
  color: #fff;
  flex-shrink: 0;
  box-shadow: 0 3px 10px rgba(59,124,244,0.35);
}
.reg-name {
  font-size: 14px;
  font-weight: 700;
  color: #1a202c;
  letter-spacing: 0.02em;
}
.reg-titles {
  text-align: right;
}
.reg-form {
  gap: 18px;
}
.reg-row {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 16px;
}

/* ══════════════════════════════════════
   通用表单元素
══════════════════════════════════════ */
.form-title {
  font-size: 22px;
  font-weight: 700;
  color: #1a202c;
  margin: 0 0 4px;
  letter-spacing: -0.01em;
}
.form-sub {
  font-size: 13px;
  color: #718096;
  margin: 0 0 24px;
}
.form {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

/* Banner */
.banner {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 14px;
  border-radius: 8px;
  font-size: 13px;
  margin-bottom: 4px;
}
.banner-error {
  background: #fff5f5;
  border: 1px solid #feb2b2;
  color: #c53030;
}
.banner-success {
  background: #f0fff4;
  border: 1px solid #9ae6b4;
  color: #276749;
}
.banner-enter-active,
.banner-leave-active { transition: opacity 0.2s, transform 0.2s; }
.banner-enter-from,
.banner-leave-to { opacity: 0; transform: translateY(-6px); }

/* Field */
.field {
  display: flex;
  flex-direction: column;
  gap: 5px;
}
.label {
  font-size: 12.5px;
  font-weight: 600;
  color: #4a5568;
  letter-spacing: 0.02em;
}
.required {
  color: #e53e3e;
  margin-left: 2px;
}

/* Input wrap */
.iw {
  display: flex;
  align-items: center;
  gap: 8px;
  background: #f7fafc;
  border: 1.5px solid #e2e8f0;
  border-radius: 10px;
  padding: 10px 14px;
  transition: all 0.18s;
}
.iw.focus {
  border-color: #3b7cf4;
  background: #fff;
  box-shadow: 0 0 0 3px rgba(59,124,244,0.12);
}
.iw.err {
  border-color: #fc8181;
  box-shadow: 0 0 0 3px rgba(252,129,129,0.12);
  background: #fff;
}
.ii {
  color: #a0aec0;
  flex-shrink: 0;
  transition: color 0.18s;
}
.iw.focus .ii { color: #3b7cf4; }
.iw input {
  flex: 1;
  background: none;
  border: none;
  outline: none;
  font-size: 13.5px;
  color: #2d3748;
  font-family: inherit;
  min-width: 0;
}
.iw input::placeholder { color: #b9c4d4; }
.eye {
  background: none;
  border: none;
  padding: 0;
  color: #a0aec0;
  cursor: pointer;
  display: flex;
  align-items: center;
  flex-shrink: 0;
  transition: color 0.18s;
}
.eye:hover { color: #4a5568; }
.eye:disabled {
  cursor: not-allowed;
  opacity: 0.6;
}
.ferr {
  font-size: 11.5px;
  color: #e53e3e;
  padding-left: 2px;
}

.test-account {
  display: flex;
  flex-direction: column;
  gap: 8px;
  margin-top: 14px;
  padding: 12px 14px;
  background: #eef6ff;
  border: 1px solid #bfdbfe;
  border-radius: 10px;
}
.test-account__title {
  font-size: 13px;
  font-weight: 700;
  color: #1d4ed8;
}
.test-account__row {
  display: flex;
  flex-direction: column;
  gap: 3px;
}
.test-account__role {
  font-size: 12.5px;
  font-weight: 700;
  color: #2d3748;
}
.test-account__value {
  font-size: 12px;
  font-weight: 700;
  color: #1e40af;
}

/* 提交按钮 */
.btn-primary {
  width: 100%;
  padding: 12px;
  background: #3b7cf4;
  border: none;
  border-radius: 10px;
  color: #fff;
  font-size: 14px;
  font-weight: 600;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  transition: all 0.18s;
  margin-top: 4px;
  letter-spacing: 0.02em;
  box-shadow: 0 4px 16px rgba(59,124,244,0.28);
}
.btn-primary:hover:not(:disabled) {
  background: #2b6de3;
  transform: translateY(-1px);
  box-shadow: 0 6px 24px rgba(59,124,244,0.38);
}
.btn-primary:active:not(:disabled) { transform: translateY(0); }
.btn-primary:disabled {
  opacity: 0.6;
  cursor: not-allowed;
  pointer-events: none;
}

/* 切换提示 */
.switch-hint {
  margin-top: 20px;
  text-align: center;
  font-size: 13px;
  color: #718096;
}
.link {
  background: none;
  border: none;
  color: #3b7cf4;
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
  padding: 0;
  margin-left: 4px;
  transition: opacity 0.18s;
}
.link:hover { opacity: 0.75; text-decoration: underline; }
.link:disabled {
  opacity: 0.45;
  cursor: not-allowed;
  text-decoration: none;
}

/* loading spin */
@keyframes spin { to { transform: rotate(360deg); } }
.spin { animation: spin 0.8s linear infinite; }

/* ── 响应式 ── */
@media (max-width: 700px) {
  .card-login { flex-direction: column; width: 100%; }
  .cover { width: 100%; height: 200px; }
  .panel { padding: 32px 24px; }
  .card-register { width: 100%; }
  .reg-inner { padding: 32px 24px; }
  .reg-row { grid-template-columns: 1fr; }
  .reg-header { flex-direction: column; }
  .reg-titles { text-align: left; }
}
</style>
