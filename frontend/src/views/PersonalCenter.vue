<template>
  <div class="personal-center">
    <!-- 页面头部：用户卡片 -->
    <header class="pc-hero">
      <div class="hero-avatar">
        <Icon icon="mdi:account-circle" width="56" class="avatar-icon" />
      </div>
      <div class="hero-info">
        <div class="hero-name-row">
          <span class="hero-name">{{ user?.username ?? '—' }}</span>
          <span class="role-badge" :class="'role-' + (user?.role ?? 'resident')">
            {{ ROLE_LABELS[user?.role ?? 'resident'] ?? user?.role }}
          </span>
          <span class="status-dot" :class="user?.is_active ? 'active' : 'inactive'"
            :title="user?.is_active ? '账号正常' : '账号已停用'"
          />
        </div>
        <p class="hero-sub">
          <Icon icon="mdi:calendar-outline" width="13" />
          注册于 {{ formatDate(user?.created_at) }}
        </p>
      </div>

      <!-- 消息徽章入口 -->
      <button class="msg-badge-btn" @click="activeTab = 'messages'" title="待处理消息">
        <Icon icon="mdi:bell-outline" width="18" />
        <span v-if="pendingCount > 0" class="msg-dot">{{ pendingCount }}</span>
      </button>
    </header>

    <!-- Tab 导航 -->
    <nav class="pc-tabs">
      <button
        v-for="tab in visibleTabs"
        :key="tab.id"
        class="pc-tab"
        :class="{ active: activeTab === tab.id }"
        @click="activeTab = tab.id"
      >
        <Icon :icon="tab.icon" width="15" />
        <span>{{ tab.label }}</span>
        <span v-if="tab.id === 'messages' && pendingCount > 0" class="tab-badge">
          {{ pendingCount }}
        </span>
      </button>
    </nav>

    <!-- 内容区 -->
    <main class="pc-body">

      <!-- ─────────── 个人资料 ─────────── -->
      <section v-if="activeTab === 'profile'" class="pc-section">
        <h2 class="section-title"><Icon icon="mdi:account-outline" width="16" /> 个人资料</h2>

        <form class="info-form" @submit.prevent="saveProfile">
          <div class="form-row">
            <label>用户名</label>
            <input :value="user?.username" disabled class="form-input disabled" />
          </div>
          <div class="form-row">
            <label>邮箱</label>
            <input v-model="profileForm.email" type="email" class="form-input"
              placeholder="请输入邮箱" autocomplete="email" />
          </div>
          <div class="form-row">
            <label>手机号</label>
            <input v-model="profileForm.phone" type="tel" class="form-input"
              placeholder="请输入手机号" autocomplete="tel" />
          </div>
          <div class="form-row">
            <label>角色</label>
            <div class="role-display">
              <span class="role-badge sm" :class="'role-' + (user?.role ?? 'resident')">
                {{ ROLE_LABELS[user?.role ?? 'resident'] ?? user?.role }}
              </span>
              <span class="role-note">角色由系统管理员分配</span>
            </div>
          </div>

          <div class="form-actions">
            <button type="submit" class="btn-primary" :disabled="profileSaving">
              <Icon :icon="profileSaving ? 'mdi:loading' : 'mdi:content-save-outline'" width="14"
                :class="{ spin: profileSaving }" />
              {{ profileSaving ? '保存中...' : '保存资料' }}
            </button>
            <span v-if="profileMsg" class="form-msg" :class="profileMsgType">{{ profileMsg }}</span>
          </div>
        </form>
      </section>

      <!-- ─────────── 账号与安全 ─────────── -->
      <section v-if="activeTab === 'security'" class="pc-section">
        <h2 class="section-title"><Icon icon="mdi:shield-lock-outline" width="16" /> 账号与安全</h2>

        <!-- 账号状态 -->
        <div class="info-card">
          <div class="info-card-row">
            <span class="ic-label"><Icon icon="mdi:account-check-outline" width="14" /> 账号状态</span>
            <span class="ic-value status-text" :class="user?.is_active ? 'ok' : 'warn'">
              {{ user?.is_active ? '正常使用' : '已停用' }}
            </span>
          </div>
          <div class="info-card-row">
            <span class="ic-label"><Icon icon="mdi:fingerprint" width="14" /> 用户 ID</span>
            <span class="ic-value mono">{{ user?.id?.slice(0, 18) }}…</span>
          </div>
        </div>

        <!-- 修改密码 -->
        <div class="subsection">
          <p class="subsection-title">修改密码</p>
          <form class="info-form" @submit.prevent="changePassword">
            <div class="form-row">
              <label>当前密码</label>
              <input v-model="pwdForm.old" type="password" class="form-input"
                placeholder="请输入当前密码" autocomplete="current-password" />
            </div>
            <div class="form-row">
              <label>新密码</label>
              <input v-model="pwdForm.new1" type="password" class="form-input"
                placeholder="至少 8 位，含字母和数字" autocomplete="new-password" />
            </div>
            <div class="form-row">
              <label>确认新密码</label>
              <input v-model="pwdForm.new2" type="password" class="form-input"
                placeholder="再次输入新密码" autocomplete="new-password" />
            </div>
            <div class="form-actions">
              <button type="submit" class="btn-primary" :disabled="pwdSaving">
                <Icon :icon="pwdSaving ? 'mdi:loading' : 'mdi:lock-reset'" width="14"
                  :class="{ spin: pwdSaving }" />
                {{ pwdSaving ? '修改中...' : '修改密码' }}
              </button>
              <span v-if="pwdMsg" class="form-msg" :class="pwdMsgType">{{ pwdMsg }}</span>
            </div>
          </form>
        </div>

        <!-- 退出登录 -->
        <div class="subsection">
          <p class="subsection-title">退出登录</p>
          <p class="subsection-desc">退出后需重新登录，所有未保存的操作将丢失。</p>
          <button class="btn-danger" @click="handleLogout">
            <Icon icon="mdi:logout" width="14" />
            退出当前账号
          </button>
        </div>
      </section>

      <!-- ─────────── 偏好设置 ─────────── -->
      <section v-if="activeTab === 'preferences'" class="pc-section">
        <h2 class="section-title"><Icon icon="mdi:tune-variant" width="16" /> 偏好设置</h2>

        <!-- 主题 -->
        <div class="pref-group">
          <p class="pref-group-title">外观主题</p>
          <div class="theme-btns">
            <button
              class="theme-opt"
              :class="{ active: currentTheme === 'light' }"
              @click="setTheme('light')"
            >
              <Icon icon="mdi:leaf" width="16" />
              <span>绿色（浅色）</span>
            </button>
            <button
              class="theme-opt"
              :class="{ active: currentTheme === 'dark' }"
              @click="setTheme('dark')"
            >
              <Icon icon="mdi:weather-night" width="16" />
              <span>深色模式</span>
            </button>
          </div>
        </div>

        <!-- AI 偏好 -->
        <div class="pref-group">
          <p class="pref-group-title">AI 对话偏好</p>
          <div class="pref-row">
            <div class="pref-label-block">
              <span class="pref-label">默认开启联网搜索</span>
              <span class="pref-desc">新建会话时自动开启 Web 搜索增强（可在对话中单独切换）</span>
            </div>
            <label class="toggle-switch">
              <input type="checkbox" v-model="webSearchDefault" @change="saveWebSearchPref" />
              <span class="toggle-track"></span>
            </label>
          </div>
        </div>

        <!-- 通知偏好（占位） -->
        <div class="pref-group">
          <p class="pref-group-title">通知偏好 <span class="coming-soon">即将推出</span></p>
          <div class="pref-row disabled">
            <div class="pref-label-block">
              <span class="pref-label">工单状态变更通知</span>
              <span class="pref-desc">审批工单状态更新时接收系统消息</span>
            </div>
            <label class="toggle-switch">
              <input type="checkbox" disabled />
              <span class="toggle-track"></span>
            </label>
          </div>
          <div class="pref-row disabled">
            <div class="pref-label-block">
              <span class="pref-label">异常事件推送</span>
              <span class="pref-desc">检测到能耗异常时实时推送提醒</span>
            </div>
            <label class="toggle-switch">
              <input type="checkbox" disabled />
              <span class="toggle-track"></span>
            </label>
          </div>
        </div>
      </section>

      <!-- ─────────── 消息中心 ─────────── -->
      <section v-if="activeTab === 'messages'" class="pc-section">
        <h2 class="section-title"><Icon icon="mdi:bell-outline" width="16" /> 消息中心</h2>

        <!-- 待处理工单 -->
        <div class="msg-block">
          <p class="msg-block-title">
            <Icon icon="mdi:clipboard-clock-outline" width="14" />
            待审批工单
            <span v-if="pendingSessions.length > 0" class="msg-count">{{ pendingSessions.length }}</span>
          </p>

          <div v-if="chatStore.sessionList.length === 0" class="msg-empty">
            <Icon icon="mdi:chat-outline" width="32" class="empty-icon" />
            <p>暂无 AI 会话，请先在右侧控制台开始对话</p>
          </div>
          <div v-else-if="pendingSessions.length === 0" class="msg-empty">
            <Icon icon="mdi:check-circle-outline" width="32" class="empty-icon ok" />
            <p>暂无待审批工单</p>
          </div>
          <div v-else class="msg-list">
            <div
              v-for="sess in pendingSessions"
              :key="sess.session_id"
              class="msg-item pending-item"
              @click="gotoWorkOrder(sess.session_id)"
            >
              <div class="msg-item-icon">
                <Icon icon="mdi:wrench-clock" width="18" />
              </div>
              <div class="msg-item-body">
                <p class="msg-item-title">{{ sess.title || '未命名会话' }}</p>
                <p class="msg-item-sub">
                  <Icon icon="mdi:calendar-outline" width="12" />
                  {{ formatDate(sess.updated_at) }}
                  <span class="msg-item-tag">待审批</span>
                </p>
              </div>
              <Icon icon="mdi:chevron-right" width="16" class="msg-item-arrow" />
            </div>
          </div>
        </div>

        <!-- 系统通知（异常告警） -->
        <div class="msg-block">
          <p class="msg-block-title">
            <Icon icon="mdi:alert-circle-outline" width="14" />
            近期异常告警
            <button class="refresh-mini" @click="loadAnomalies" :disabled="anomalyLoading">
              <Icon :icon="anomalyLoading ? 'mdi:loading' : 'mdi:refresh'" width="13"
                :class="{ spin: anomalyLoading }" />
            </button>
          </p>

          <div v-if="anomalyLoading && anomalies.length === 0" class="msg-empty">
            <Icon icon="mdi:loading" width="28" class="empty-icon spin" />
            <p>加载中...</p>
          </div>
          <div v-else-if="anomalyError" class="msg-empty error">
            <Icon icon="mdi:alert" width="28" class="empty-icon" />
            <p>{{ anomalyError }}</p>
          </div>
          <div v-else-if="anomalies.length === 0" class="msg-empty">
            <Icon icon="mdi:check-all" width="32" class="empty-icon ok" />
            <p>近期无异常告警</p>
          </div>
          <div v-else class="msg-list">
            <div
              v-for="anom in anomalies"
              :key="anom.id ?? anom.detected_at"
              class="msg-item anom-item"
              :class="'sev-' + (anom.severity ?? 'medium').toLowerCase()"
            >
              <div class="msg-item-icon anom-icon">
                <Icon icon="mdi:alert-outline" width="18" />
              </div>
              <div class="msg-item-body">
                <p class="msg-item-title">{{ anom.anomaly_type ?? '未知异常' }}</p>
                <p class="msg-item-sub">
                  <Icon icon="mdi:office-building-outline" width="12" />
                  楼宇 {{ anom.building_id }} · 设备 {{ anom.device_id ?? '—' }}
                  <span class="msg-item-tag" :class="'tag-' + (anom.severity ?? 'medium').toLowerCase()">
                    {{ anom.severity ?? 'medium' }}
                  </span>
                  · {{ formatDate(anom.detected_at) }}
                </p>
              </div>
            </div>
          </div>
        </div>
      </section>

      <!-- ─────────── 角色与权限 ─────────── -->
      <section v-if="activeTab === 'role' && showRoleTab" class="pc-section">
        <h2 class="section-title"><Icon icon="mdi:account-key-outline" width="16" /> 角色与权限</h2>
        <div class="role-card">
          <div class="role-card-header">
            <span class="role-badge lg" :class="'role-' + (user?.role ?? 'resident')">
              {{ ROLE_LABELS[user?.role ?? 'resident'] ?? user?.role }}
            </span>
            <p class="role-card-desc">{{ ROLE_DESCS[user?.role ?? 'resident'] }}</p>
          </div>
          <div class="role-perms">
            <p class="perms-title">当前角色可访问模块</p>
            <ul class="perms-list">
              <li v-for="perm in ROLE_PERMS[user?.role ?? 'resident']" :key="perm.label">
                <Icon :icon="perm.icon" width="14" class="perm-icon" />
                {{ perm.label }}
              </li>
            </ul>
          </div>
          <p v-if="user?.role !== 'admin'" class="role-note-footer">
            如需变更角色权限，请联系系统管理员。
          </p>
          <p v-else class="role-note-footer ok">
            您拥有系统最高权限。
          </p>
        </div>
      </section>

      <!-- ─────────── 帮助与反馈 ─────────── -->
      <section v-if="activeTab === 'help'" class="pc-section">
        <h2 class="section-title"><Icon icon="mdi:help-circle-outline" width="16" /> 帮助与反馈</h2>

        <div class="help-list">
          <div class="help-item" v-for="faq in FAQ_LIST" :key="faq.q">
            <button
              class="faq-q"
              @click="faq._open = !faq._open"
            >
              <Icon :icon="faq._open ? 'mdi:chevron-down' : 'mdi:chevron-right'" width="14" />
              {{ faq.q }}
            </button>
            <div v-if="faq._open" class="faq-a">{{ faq.a }}</div>
          </div>
        </div>

        <div class="feedback-block">
          <p class="subsection-title">意见反馈</p>
          <textarea
            v-model="feedbackText"
            class="feedback-textarea"
            placeholder="请描述您遇到的问题或功能建议..."
            rows="4"
          ></textarea>
          <button class="btn-primary" @click="submitFeedback" :disabled="feedbackSent">
            <Icon :icon="feedbackSent ? 'mdi:check' : 'mdi:send-outline'" width="14" />
            {{ feedbackSent ? '感谢您的反馈！' : '提交反馈' }}
          </button>
        </div>
      </section>

    </main>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, reactive, watch } from 'vue'
import { useRouter } from 'vue-router'
import { Icon } from '@iconify/vue'
import { useAuthStore } from '@/stores/authStore'
import { useChatStore } from '@/stores/chatStore'
import { apiChangePassword, apiUpdateProfile } from '@/api/auth'
import { apiFetch } from '@/api/http'

const router = useRouter()
const authStore = useAuthStore()
const chatStore = useChatStore()

const user = computed(() => authStore.user)

// ── 角色元数据 ──────────────────────────────────────────────────────
const ROLE_LABELS: Record<string, string> = {
  resident: '住户',
  ops: '运维人员',
  manager: '运维经理',
  admin: '系统管理员',
}

const ROLE_DESCS: Record<string, string> = {
  resident: '普通住户，可查看自身会话记录与系统通知概览。',
  ops: '楼宇运维人员，负责日常设备巡检与工单处理。',
  manager: '运维经理，具备工单审批与数据分析权限。',
  admin: '系统管理员，拥有全部模块访问及用户管理能力。',
}

const ROLE_PERMS: Record<string, { icon: string; label: string }[]> = {
  resident: [
    { icon: 'mdi:view-dashboard', label: '驾驶舱（只读）' },
    { icon: 'mdi:chat-outline', label: 'AI 智能问答' },
    { icon: 'mdi:bell-outline', label: '系统通知概览' },
  ],
  ops: [
    { icon: 'mdi:view-dashboard', label: '驾驶舱' },
    { icon: 'mdi:wrench', label: '智慧运维' },
    { icon: 'mdi:clipboard-list', label: '工单处理' },
    { icon: 'mdi:chat-outline', label: 'AI 智能诊断' },
  ],
  manager: [
    { icon: 'mdi:view-dashboard', label: '驾驶舱' },
    { icon: 'mdi:wrench', label: '智慧运维' },
    { icon: 'mdi:clipboard-list', label: '工单审批与管理' },
    { icon: 'mdi:database-outline', label: '数据中心' },
    { icon: 'mdi:chat-outline', label: 'AI 智能分析' },
  ],
  admin: [
    { icon: 'mdi:view-dashboard', label: '驾驶舱' },
    { icon: 'mdi:wrench', label: '智慧运维' },
    { icon: 'mdi:clipboard-list', label: '工单全权管理' },
    { icon: 'mdi:database-outline', label: '数据中心' },
    { icon: 'mdi:account-key-outline', label: '用户与权限管理' },
    { icon: 'mdi:chat-outline', label: 'AI 全功能' },
  ],
}

// ── Tab 定义（按角色显示差异模块）──────────────────────────────────
interface TabDef {
  id: string
  label: string
  icon: string
  roles?: string[]
}

const ALL_TABS: TabDef[] = [
  { id: 'profile', label: '个人资料', icon: 'mdi:account-outline' },
  { id: 'security', label: '账号安全', icon: 'mdi:shield-lock-outline' },
  { id: 'preferences', label: '偏好设置', icon: 'mdi:tune-variant' },
  { id: 'messages', label: '消息中心', icon: 'mdi:bell-outline' },
  { id: 'role', label: '角色权限', icon: 'mdi:account-key-outline', roles: ['manager', 'admin', 'ops'] },
  { id: 'help', label: '帮助反馈', icon: 'mdi:help-circle-outline' },
]

const visibleTabs = computed(() => {
  const role = user.value?.role ?? 'resident'
  return ALL_TABS.filter(t => !t.roles || t.roles.includes(role))
})

const showRoleTab = computed(() => {
  const role = user.value?.role ?? 'resident'
  return ['manager', 'admin', 'ops'].includes(role)
})

const activeTab = ref('profile')

// ── 个人资料表单 ────────────────────────────────────────────────────
const profileForm = reactive({
  email: user.value?.email ?? '',
  phone: user.value?.phone ?? '',
})

// 当 user 加载完后同步表单初始值
watch(user, (u) => {
  if (u) {
    profileForm.email = u.email ?? ''
    profileForm.phone = u.phone ?? ''
  }
}, { immediate: true })

const profileSaving = ref(false)
const profileMsg = ref('')
const profileMsgType = ref<'ok' | 'err'>('ok')

async function saveProfile() {
  if (!authStore.accessToken) return
  profileSaving.value = true
  profileMsg.value = ''
  try {
    const updated = await apiUpdateProfile(authStore.accessToken, {
      email: profileForm.email || undefined,
      phone: profileForm.phone || undefined,
    })
    authStore.user = updated
    profileMsg.value = '保存成功'
    profileMsgType.value = 'ok'
  } catch (e: unknown) {
    profileMsg.value = (e as Error).message ?? '保存失败'
    profileMsgType.value = 'err'
  } finally {
    profileSaving.value = false
    setTimeout(() => { profileMsg.value = '' }, 3000)
  }
}

// ── 修改密码 ──────────────────────────────────────────────────────
const pwdForm = reactive({ old: '', new1: '', new2: '' })
const pwdSaving = ref(false)
const pwdMsg = ref('')
const pwdMsgType = ref<'ok' | 'err'>('ok')

async function changePassword() {
  if (!pwdForm.old || !pwdForm.new1 || !pwdForm.new2) {
    pwdMsg.value = '请填写所有密码字段'
    pwdMsgType.value = 'err'
    return
  }
  if (pwdForm.new1 !== pwdForm.new2) {
    pwdMsg.value = '两次新密码不一致'
    pwdMsgType.value = 'err'
    return
  }
  if (!authStore.accessToken) return
  pwdSaving.value = true
  pwdMsg.value = ''
  try {
    await apiChangePassword(authStore.accessToken, pwdForm.old, pwdForm.new1)
    pwdMsg.value = '密码修改成功，请重新登录'
    pwdMsgType.value = 'ok'
    pwdForm.old = ''
    pwdForm.new1 = ''
    pwdForm.new2 = ''
    setTimeout(handleLogout, 2000)
  } catch (e: unknown) {
    pwdMsg.value = (e as Error).message ?? '修改失败'
    pwdMsgType.value = 'err'
  } finally {
    pwdSaving.value = false
  }
}

// ── 退出登录 ──────────────────────────────────────────────────────
async function handleLogout() {
  await authStore.logout()
  router.push('/login')
}

// ── 主题偏好 ──────────────────────────────────────────────────────
const currentTheme = ref(localStorage.getItem('theme') ?? 'dark')

function setTheme(t: 'dark' | 'light') {
  currentTheme.value = t
  document.documentElement.dataset.theme = t
  localStorage.setItem('theme', t)
}

// ── Web Search 偏好 ──────────────────────────────────────────────
const WEB_SEARCH_PREF_KEY = 'chat_web_search_default'
const webSearchDefault = ref(localStorage.getItem(WEB_SEARCH_PREF_KEY) === 'true')

function saveWebSearchPref() {
  localStorage.setItem(WEB_SEARCH_PREF_KEY, String(webSearchDefault.value))
}

// ── 消息中心：待审批会话 ─────────────────────────────────────────
const pendingSessions = computed(() =>
  chatStore.sessionList.filter(s => s.has_pending_action)
)
const pendingCount = computed(() => pendingSessions.value.length)

function gotoWorkOrder(sessionId: string) {
  chatStore.switchSession(sessionId)
  router.push('/workorders')
}

// ── 消息中心：异常告警 ──────────────────────────────────────────
interface AnomalyItem {
  id?: string
  detected_at: string
  anomaly_type?: string
  severity?: string
  device_id?: string
  building_id?: string | number
}

const anomalies = ref<AnomalyItem[]>([])
const anomalyLoading = ref(false)
const anomalyError = ref('')

async function loadAnomalies() {
  anomalyLoading.value = true
  anomalyError.value = ''
  try {
    const data = await apiFetch<AnomalyItem[]>('/api/anomalies/recent?hours=168&limit=20')
    anomalies.value = data
  } catch (e: unknown) {
    anomalyError.value = (e as Error).message ?? '加载失败'
  } finally {
    anomalyLoading.value = false
  }
}

// ── FAQ ────────────────────────────────────────────────────────
interface FaqItem { q: string; a: string; _open: boolean }

const FAQ_LIST = reactive<FaqItem[]>([
  {
    q: '如何发起 AI 诊断工单？',
    a: '在右侧 AI 控制台向 AI 描述问题（如"3号楼空调能耗偏高"），AI 将自动分析并生成工单，您可在"工单管理"页面审批执行。',
    _open: false,
  },
  {
    q: '如何上传数据进行分析？',
    a: '进入"数据中心"页面，点击"上传数据集"按钮，支持 CSV / Excel 格式。上传后可在 AI 对话中引用该数据集进行问答分析。',
    _open: false,
  },
  {
    q: '主题颜色如何切换？',
    a: '在"偏好设置"中选择"绿色"或"深色"主题，也可通过左侧导航栏底部的调色板图标快速切换。',
    _open: false,
  },
  {
    q: '联网搜索有什么用？',
    a: '开启后，AI 在回答问题时会主动搜索互联网获取最新资料，适合查询行业规范、政策法规等外部知识。可在 AI 控制台底部单独切换。',
    _open: false,
  },
  {
    q: '如何联系技术支持？',
    a: '请发送邮件至 support@yourcompany.com 或通过系统管理员反馈渠道联系，我们将在 1 个工作日内响应。',
    _open: false,
  },
])

// ── 反馈 ──────────────────────────────────────────────────────
const feedbackText = ref('')
const feedbackSent = ref(false)

function submitFeedback() {
  if (!feedbackText.value.trim()) return
  feedbackSent.value = true
  // MVP 阶段：本地提示，不发请求
  setTimeout(() => {
    feedbackText.value = ''
    feedbackSent.value = false
  }, 3000)
}

// ── 工具函数 ──────────────────────────────────────────────────
function formatDate(dateStr?: string | null): string {
  if (!dateStr) return '—'
  try {
    return new Date(dateStr).toLocaleDateString('zh-CN', {
      year: 'numeric', month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit',
    })
  } catch {
    return dateStr
  }
}

// ── 初始化 ────────────────────────────────────────────────────
onMounted(() => {
  if (chatStore.sessionList.length === 0) chatStore.loadSessionList()
  loadAnomalies()
})
</script>

<style scoped>
/* ── 整体布局 ── */
.personal-center {
  min-height: 100%;
  padding: 24px 28px 40px;
  color: var(--text-primary);
  max-width: 860px;
  margin: 0 auto;
  box-sizing: border-box;
}

/* ── Hero 头部卡片 ── */
.pc-hero {
  display: flex;
  align-items: center;
  gap: 16px;
  background: var(--bg-panel);
  border: 1px solid var(--border);
  border-radius: 14px;
  padding: 20px 22px;
  margin-bottom: 20px;
  box-shadow: var(--card-shadow);
}

.hero-avatar {
  flex-shrink: 0;
  color: var(--accent);
  display: flex;
  align-items: center;
}

.avatar-icon {
  opacity: 0.9;
}

.hero-info {
  flex: 1;
  min-width: 0;
}

.hero-name-row {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
  margin-bottom: 4px;
}

.hero-name {
  font-size: 18px;
  font-weight: 700;
  color: var(--text-primary);
}

.hero-sub {
  display: flex;
  align-items: center;
  gap: 5px;
  font-size: 12px;
  color: var(--text-muted);
  margin: 0;
}

/* ── 角色标签 ── */
.role-badge {
  font-size: 11px;
  font-weight: 600;
  padding: 2px 9px;
  border-radius: 20px;
  letter-spacing: 0.03em;
}
.role-badge.sm { font-size: 11px; padding: 2px 8px; }
.role-badge.lg { font-size: 14px; padding: 5px 14px; }

.role-resident  { background: rgba(var(--accent-rgb, 80,200,120), 0.15); color: var(--accent); }
.role-ops       { background: rgba(var(--info-rgb, 56,189,248), 0.15);   color: #38bdf8; }
.role-manager   { background: rgba(var(--warn-rgb, 251,191,36), 0.15);   color: #fbbf24; }
.role-admin     { background: rgba(var(--danger-rgb,239,68,68), 0.15);   color: #ef4444; }

/* ── 账号状态点 ── */
.status-dot {
  width: 8px; height: 8px;
  border-radius: 50%;
  flex-shrink: 0;
}
.status-dot.active  { background: var(--accent); box-shadow: 0 0 6px var(--accent-glow-md); }
.status-dot.inactive { background: var(--text-muted); }

/* ── 消息徽章按钮 ── */
.msg-badge-btn {
  margin-left: auto;
  flex-shrink: 0;
  position: relative;
  background: var(--bg-hover);
  border: 1px solid var(--border);
  border-radius: 10px;
  color: var(--text-secondary);
  cursor: pointer;
  padding: 8px 10px;
  display: flex;
  align-items: center;
  gap: 5px;
  transition: all 0.2s;
}
.msg-badge-btn:hover {
  border-color: var(--border-accent);
  color: var(--accent);
  background: var(--accent-glow);
}
.msg-dot {
  position: absolute;
  top: 4px; right: 4px;
  background: #ef4444;
  color: #fff;
  font-size: 10px;
  font-weight: 700;
  width: 16px; height: 16px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
}

/* ── Tab 导航 ── */
.pc-tabs {
  display: flex;
  align-items: center;
  gap: 4px;
  background: var(--bg-panel);
  border: 1px solid var(--border);
  border-radius: 12px;
  padding: 6px 8px;
  margin-bottom: 18px;
  flex-wrap: wrap;
}

.pc-tab {
  position: relative;
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 7px 14px;
  background: none;
  border: none;
  border-radius: 8px;
  color: var(--text-secondary);
  font-size: 13px;
  cursor: pointer;
  transition: all 0.2s;
  white-space: nowrap;
}
.pc-tab:hover { background: var(--bg-hover); color: var(--text-primary); }
.pc-tab.active {
  background: var(--accent-glow);
  color: var(--accent);
  font-weight: 600;
}

.tab-badge {
  background: #ef4444;
  color: #fff;
  font-size: 10px;
  font-weight: 700;
  min-width: 16px;
  height: 16px;
  border-radius: 20px;
  padding: 0 4px;
  display: flex;
  align-items: center;
  justify-content: center;
}

/* ── 内容区 ── */
.pc-body { min-height: 400px; }

.pc-section {
  background: var(--bg-panel);
  border: 1px solid var(--border);
  border-radius: 14px;
  padding: 24px;
  box-shadow: var(--card-shadow);
}

.section-title {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 15px;
  font-weight: 700;
  color: var(--text-primary);
  margin: 0 0 20px;
  padding-bottom: 12px;
  border-bottom: 1px solid var(--border);
}

/* ── 表单 ── */
.info-form { display: flex; flex-direction: column; gap: 14px; }

.form-row {
  display: flex;
  align-items: center;
  gap: 16px;
}

.form-row label {
  width: 84px;
  flex-shrink: 0;
  font-size: 13px;
  color: var(--text-secondary);
  text-align: right;
}

.form-input {
  flex: 1;
  padding: 8px 12px;
  background: var(--bg-dark);
  border: 1px solid var(--border);
  border-radius: 8px;
  color: var(--text-primary);
  font-size: 13px;
  outline: none;
  transition: border-color 0.2s;
}
.form-input:focus { border-color: var(--accent); }
.form-input.disabled {
  opacity: 0.55;
  cursor: not-allowed;
}

.role-display {
  flex: 1;
  display: flex;
  align-items: center;
  gap: 10px;
}
.role-note {
  font-size: 11px;
  color: var(--text-muted);
}

.form-actions {
  display: flex;
  align-items: center;
  gap: 14px;
  padding-left: 100px;
  margin-top: 4px;
}

.form-msg {
  font-size: 12px;
  font-weight: 500;
}
.form-msg.ok  { color: var(--accent); }
.form-msg.err { color: #ef4444; }

/* ── 按钮 ── */
.btn-primary {
  display: flex;
  align-items: center;
  gap: 7px;
  padding: 8px 18px;
  background: var(--accent);
  color: #fff;
  border: none;
  border-radius: 8px;
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
  transition: opacity 0.2s;
}
.btn-primary:hover:not(:disabled) { opacity: 0.88; }
.btn-primary:disabled { opacity: 0.5; cursor: not-allowed; }

.btn-danger {
  display: flex;
  align-items: center;
  gap: 7px;
  padding: 8px 18px;
  background: rgba(239, 68, 68, 0.12);
  color: #ef4444;
  border: 1px solid rgba(239, 68, 68, 0.3);
  border-radius: 8px;
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.2s;
}
.btn-danger:hover { background: rgba(239, 68, 68, 0.2); }

/* ── 信息卡 ── */
.info-card {
  background: var(--bg-dark);
  border: 1px solid var(--border);
  border-radius: 10px;
  padding: 14px 18px;
  margin-bottom: 20px;
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.info-card-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}
.ic-label {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  color: var(--text-muted);
}
.ic-value {
  font-size: 13px;
  color: var(--text-primary);
}
.ic-value.mono { font-family: 'JetBrains Mono', monospace; font-size: 12px; color: var(--text-secondary); }
.status-text.ok { color: var(--accent); }
.status-text.warn { color: #ef4444; }

/* ── 子区块 ── */
.subsection { margin-top: 22px; }
.subsection-title {
  font-size: 13px;
  font-weight: 600;
  color: var(--text-primary);
  margin: 0 0 12px;
}
.subsection-desc {
  font-size: 12px;
  color: var(--text-muted);
  margin: 0 0 12px;
}

/* ── 偏好设置 ── */
.pref-group { margin-bottom: 24px; }
.pref-group-title {
  font-size: 12px;
  font-weight: 600;
  color: var(--text-muted);
  text-transform: uppercase;
  letter-spacing: 0.08em;
  margin: 0 0 12px;
  display: flex;
  align-items: center;
  gap: 8px;
}
.coming-soon {
  font-size: 10px;
  font-weight: 500;
  text-transform: none;
  letter-spacing: 0;
  background: rgba(var(--warn-rgb, 251,191,36), 0.15);
  color: #fbbf24;
  padding: 1px 7px;
  border-radius: 20px;
}

.theme-btns {
  display: flex;
  gap: 10px;
  flex-wrap: wrap;
}
.theme-opt {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 18px;
  background: var(--bg-dark);
  border: 1px solid var(--border);
  border-radius: 10px;
  color: var(--text-secondary);
  font-size: 13px;
  cursor: pointer;
  transition: all 0.2s;
}
.theme-opt:hover { border-color: var(--border-accent); color: var(--text-primary); }
.theme-opt.active {
  border-color: var(--accent);
  background: var(--accent-glow);
  color: var(--accent);
  font-weight: 600;
}

.pref-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 12px 16px;
  background: var(--bg-dark);
  border: 1px solid var(--border);
  border-radius: 10px;
  margin-bottom: 8px;
}
.pref-row.disabled { opacity: 0.45; pointer-events: none; }
.pref-label-block { display: flex; flex-direction: column; gap: 3px; }
.pref-label { font-size: 13px; color: var(--text-primary); font-weight: 500; }
.pref-desc { font-size: 11px; color: var(--text-muted); }

/* Toggle Switch */
.toggle-switch {
  position: relative;
  display: inline-block;
  width: 40px;
  height: 22px;
  flex-shrink: 0;
  cursor: pointer;
}
.toggle-switch input { opacity: 0; width: 0; height: 0; }
.toggle-track {
  position: absolute;
  inset: 0;
  background: var(--border);
  border-radius: 22px;
  transition: background 0.25s;
}
.toggle-track::before {
  content: '';
  position: absolute;
  width: 16px; height: 16px;
  left: 3px; bottom: 3px;
  background: #fff;
  border-radius: 50%;
  transition: transform 0.25s;
}
.toggle-switch input:checked + .toggle-track { background: var(--accent); }
.toggle-switch input:checked + .toggle-track::before { transform: translateX(18px); }

/* ── 消息中心 ── */
.msg-block { margin-bottom: 24px; }
.msg-block:last-child { margin-bottom: 0; }

.msg-block-title {
  display: flex;
  align-items: center;
  gap: 7px;
  font-size: 13px;
  font-weight: 600;
  color: var(--text-secondary);
  margin: 0 0 10px;
  text-transform: uppercase;
  letter-spacing: 0.06em;
}
.msg-count {
  background: var(--accent);
  color: #fff;
  font-size: 10px;
  min-width: 16px;
  height: 16px;
  border-radius: 20px;
  padding: 0 4px;
  display: flex;
  align-items: center;
  justify-content: center;
}
.refresh-mini {
  margin-left: auto;
  background: none;
  border: none;
  color: var(--text-muted);
  cursor: pointer;
  padding: 2px 4px;
  border-radius: 6px;
  display: flex;
  align-items: center;
  transition: color 0.2s;
}
.refresh-mini:hover { color: var(--text-primary); }
.refresh-mini:disabled { opacity: 0.4; cursor: not-allowed; }

.msg-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
  padding: 28px 20px;
  background: var(--bg-dark);
  border: 1px solid var(--border);
  border-radius: 10px;
  color: var(--text-muted);
  font-size: 13px;
  text-align: center;
}
.msg-empty.error { color: #ef4444; }
.empty-icon { opacity: 0.4; }
.empty-icon.ok { opacity: 0.8; color: var(--accent); }

.msg-list { display: flex; flex-direction: column; gap: 8px; }

.msg-item {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 12px 14px;
  background: var(--bg-dark);
  border: 1px solid var(--border);
  border-radius: 10px;
  transition: all 0.18s;
}

.pending-item {
  cursor: pointer;
}
.pending-item:hover {
  border-color: var(--border-accent);
  background: var(--accent-glow);
}

.msg-item-icon {
  flex-shrink: 0;
  width: 36px;
  height: 36px;
  border-radius: 8px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--accent-glow);
  color: var(--accent);
}
.anom-icon {
  background: rgba(239,68,68,0.12);
  color: #ef4444;
}
.sev-high .anom-icon { background: rgba(239,68,68,0.18); color: #ef4444; }
.sev-medium .anom-icon { background: rgba(251,191,36,0.15); color: #fbbf24; }
.sev-low .anom-icon { background: rgba(80,200,120,0.12); color: var(--accent); }

.msg-item-body { flex: 1; min-width: 0; }
.msg-item-title {
  font-size: 13px;
  font-weight: 600;
  color: var(--text-primary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  margin: 0 0 3px;
}
.msg-item-sub {
  display: flex;
  align-items: center;
  gap: 5px;
  font-size: 11px;
  color: var(--text-muted);
  flex-wrap: wrap;
  margin: 0;
}
.msg-item-tag {
  background: var(--accent-glow);
  color: var(--accent);
  padding: 1px 6px;
  border-radius: 20px;
  font-size: 10px;
  font-weight: 600;
}
.msg-item-tag.tag-high   { background: rgba(239,68,68,0.12); color: #ef4444; }
.msg-item-tag.tag-medium { background: rgba(251,191,36,0.12); color: #fbbf24; }
.msg-item-tag.tag-low    { background: rgba(80,200,120,0.12); color: var(--accent); }
.msg-item-arrow { color: var(--text-muted); flex-shrink: 0; }

/* ── 角色权限 ── */
.role-card {
  background: var(--bg-dark);
  border: 1px solid var(--border);
  border-radius: 12px;
  padding: 20px;
}
.role-card-header {
  display: flex;
  align-items: center;
  gap: 14px;
  margin-bottom: 20px;
  flex-wrap: wrap;
}
.role-card-desc {
  font-size: 13px;
  color: var(--text-secondary);
  margin: 0;
}
.role-perms { margin-bottom: 16px; }
.perms-title {
  font-size: 12px;
  font-weight: 600;
  color: var(--text-muted);
  text-transform: uppercase;
  letter-spacing: 0.07em;
  margin: 0 0 10px;
}
.perms-list {
  list-style: none;
  padding: 0;
  margin: 0;
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.perms-list li {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 13px;
  color: var(--text-primary);
}
.perm-icon { color: var(--accent); flex-shrink: 0; }
.role-note-footer {
  font-size: 12px;
  color: var(--text-muted);
  margin: 0;
  padding-top: 14px;
  border-top: 1px solid var(--border);
}
.role-note-footer.ok { color: var(--accent); }

/* ── 帮助 ── */
.help-list { margin-bottom: 24px; display: flex; flex-direction: column; gap: 6px; }
.help-item {}
.faq-q {
  display: flex;
  align-items: center;
  gap: 8px;
  width: 100%;
  padding: 11px 14px;
  background: var(--bg-dark);
  border: 1px solid var(--border);
  border-radius: 8px;
  color: var(--text-primary);
  font-size: 13px;
  font-weight: 500;
  cursor: pointer;
  text-align: left;
  transition: all 0.18s;
}
.faq-q:hover { border-color: var(--border-accent); }
.faq-a {
  padding: 12px 16px;
  font-size: 13px;
  color: var(--text-secondary);
  line-height: 1.7;
  background: var(--bg-dark);
  border: 1px solid var(--border);
  border-top: none;
  border-radius: 0 0 8px 8px;
  margin-top: -4px;
}

.feedback-block {
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.feedback-textarea {
  width: 100%;
  padding: 10px 14px;
  background: var(--bg-dark);
  border: 1px solid var(--border);
  border-radius: 10px;
  color: var(--text-primary);
  font-size: 13px;
  resize: vertical;
  outline: none;
  transition: border-color 0.2s;
  box-sizing: border-box;
  font-family: inherit;
}
.feedback-textarea:focus { border-color: var(--accent); }

/* ── 动画 ── */
@keyframes spin { to { transform: rotate(360deg); } }
.spin { animation: spin 0.8s linear infinite; }
</style>
