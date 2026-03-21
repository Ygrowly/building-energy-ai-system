<template>
  <Teleport to="body">
    <Transition name="modal-fade">
      <div v-if="visible" class="pm-overlay" @click.self="$emit('close')">
        <div class="pm-dialog" :class="'section-' + activeSection">
          <!-- 标题栏 -->
          <div class="pm-header">
            <h2 class="pm-title">{{ SECTION_TITLES[activeSection] }}</h2>
            <button class="pm-close" @click="$emit('close')">
              <Icon icon="mdi:close" width="18" />
            </button>
          </div>

          <!-- 内容区 -->
          <div class="pm-body" :class="{ 'has-sidebar': activeSection === 'settings' }">

            <!-- ═══════════ 设置（Grok 风格：左侧Tab + 右侧内容）═══════════ -->
            <template v-if="activeSection === 'settings'">
              <!-- 左侧竖向Tab -->
              <nav class="settings-sidebar">
                <button
                  v-for="tab in SETTINGS_TABS"
                  :key="tab.id"
                  class="sidebar-tab"
                  :class="{ active: settingsTab === tab.id }"
                  @click="settingsTab = tab.id"
                >
                  <Icon :icon="tab.icon" width="16" />
                  <span>{{ tab.label }}</span>
                </button>
              </nav>

              <!-- 右侧内容 -->
              <div class="settings-content">

                <!-- 个人资料 -->
                <template v-if="settingsTab === 'profile'">
                  <!-- 用户卡片 -->
                  <div class="grok-row user-row">
                    <div class="user-avatar">
                      <span class="avatar-text">{{ avatarInitials }}</span>
                    </div>
                    <div class="grok-row-info">
                      <p class="grok-row-title">{{ user?.username ?? '—' }}</p>
                      <p class="grok-row-sub">{{ user?.email || '未设置邮箱' }}</p>
                    </div>
                    <span class="role-badge" :class="'role-' + (user?.role ?? 'resident')">
                      {{ ROLE_LABELS[user?.role ?? 'resident'] ?? user?.role }}
                    </span>
                  </div>

                  <div class="grok-row">
                    <div class="grok-row-info">
                      <p class="grok-row-title">邮箱</p>
                      <p class="grok-row-sub">{{ profileForm.email || '未设置' }}</p>
                    </div>
                    <button class="btn-action" @click="editingField = editingField === 'email' ? '' : 'email'">
                      {{ editingField === 'email' ? '取消' : '更改' }}
                    </button>
                  </div>
                  <div v-if="editingField === 'email'" class="grok-edit-area">
                    <input v-model="profileForm.email" type="email" class="setting-input" placeholder="请输入邮箱" />
                  </div>

                  <div class="grok-row">
                    <div class="grok-row-info">
                      <p class="grok-row-title">手机号</p>
                      <p class="grok-row-sub">{{ profileForm.phone || '未设置' }}</p>
                    </div>
                    <button class="btn-action" @click="editingField = editingField === 'phone' ? '' : 'phone'">
                      {{ editingField === 'phone' ? '取消' : '更改' }}
                    </button>
                  </div>
                  <div v-if="editingField === 'phone'" class="grok-edit-area">
                    <input v-model="profileForm.phone" type="tel" class="setting-input" placeholder="请输入手机号" />
                  </div>

                  <div class="grok-row">
                    <div class="grok-row-info">
                      <p class="grok-row-title">注册时间</p>
                      <p class="grok-row-sub">{{ formatDate(user?.created_at) }}</p>
                    </div>
                  </div>

                  <p class="grok-id">{{ user?.id }}</p>

                  <div v-if="editingField" class="setting-actions">
                    <button class="btn-primary" @click="saveProfile" :disabled="profileSaving">
                      <Icon :icon="profileSaving ? 'mdi:loading' : 'mdi:content-save-outline'" width="14"
                        :class="{ spin: profileSaving }" />
                      {{ profileSaving ? '保存中...' : '保存' }}
                    </button>
                    <span v-if="profileMsg" class="form-msg" :class="profileMsgType">{{ profileMsg }}</span>
                  </div>
                </template>

                <!-- 账号安全 -->
                <template v-if="settingsTab === 'security'">
                  <div class="grok-row">
                    <div class="grok-row-info">
                      <p class="grok-row-title">账号状态</p>
                      <p class="grok-row-sub">{{ user?.is_active ? '正常使用' : '已停用' }}</p>
                    </div>
                    <span class="status-dot" :class="user?.is_active ? 'ok' : 'warn'"></span>
                  </div>

                  <div class="grok-row">
                    <div class="grok-row-info">
                      <p class="grok-row-title">修改密码</p>
                      <p class="grok-row-sub">定期更换密码以保护账号安全</p>
                    </div>
                    <button class="btn-action" @click="showPwdForm = !showPwdForm">
                      {{ showPwdForm ? '取消' : '更改' }}
                    </button>
                  </div>

                  <div v-if="showPwdForm" class="grok-edit-area pwd-form">
                    <input v-model="pwdForm.old" type="password" class="setting-input"
                      placeholder="当前密码" autocomplete="current-password" />
                    <input v-model="pwdForm.new1" type="password" class="setting-input"
                      placeholder="新密码（至少 8 位）" autocomplete="new-password" />
                    <input v-model="pwdForm.new2" type="password" class="setting-input"
                      placeholder="确认新密码" autocomplete="new-password" />
                    <div class="setting-actions">
                      <button class="btn-primary" @click="changePassword" :disabled="pwdSaving">
                        <Icon :icon="pwdSaving ? 'mdi:loading' : 'mdi:lock-reset'" width="14"
                          :class="{ spin: pwdSaving }" />
                        {{ pwdSaving ? '修改中...' : '确认修改' }}
                      </button>
                      <span v-if="pwdMsg" class="form-msg" :class="pwdMsgType">{{ pwdMsg }}</span>
                    </div>
                  </div>
                </template>

                <!-- 偏好设置 -->
                <template v-if="settingsTab === 'preferences'">
                  <div class="grok-row clickable" @click="setTheme(currentTheme === 'dark' ? 'light' : 'dark')">
                    <div class="grok-row-info">
                      <p class="grok-row-title">外观主题</p>
                      <p class="grok-row-sub">{{ currentTheme === 'dark' ? '深色模式' : '浅色模式' }}</p>
                    </div>
                    <button class="btn-action">更改</button>
                  </div>

                  <div class="grok-row">
                    <div class="grok-row-info">
                      <p class="grok-row-title">默认联网搜索</p>
                      <p class="grok-row-sub">新建会话时自动开启 Web 搜索增强</p>
                    </div>
                    <label class="toggle-switch">
                      <input type="checkbox" v-model="webSearchDefault" @change="saveWebSearchPref" />
                      <span class="toggle-track"></span>
                    </label>
                  </div>

                  <div class="grok-row disabled">
                    <div class="grok-row-info">
                      <p class="grok-row-title">工单状态通知 <span class="coming-soon">即将推出</span></p>
                      <p class="grok-row-sub">审批工单状态更新时接收系统消息</p>
                    </div>
                    <label class="toggle-switch">
                      <input type="checkbox" disabled />
                      <span class="toggle-track"></span>
                    </label>
                  </div>

                  <div class="grok-row disabled">
                    <div class="grok-row-info">
                      <p class="grok-row-title">异常事件推送 <span class="coming-soon">即将推出</span></p>
                      <p class="grok-row-sub">检测到能耗异常时实时推送提醒</p>
                    </div>
                    <label class="toggle-switch">
                      <input type="checkbox" disabled />
                      <span class="toggle-track"></span>
                    </label>
                  </div>
                </template>

              </div>
            </template>

            <!-- ═══════════ 消息中心 ═══════════ -->
            <template v-if="activeSection === 'messages'">
              <!-- 待审批工单 -->
              <div class="msg-block">
                <p class="block-label">
                  <Icon icon="mdi:clipboard-clock-outline" width="14" />
                  待审批工单
                  <span v-if="pendingSessions.length > 0" class="count-badge">{{ pendingSessions.length }}</span>
                </p>
                <div v-if="chatStore.sessionList.length === 0" class="empty-state">
                  <Icon icon="mdi:chat-outline" width="28" class="empty-icon" />
                  <p>暂无 AI 会话</p>
                </div>
                <div v-else-if="pendingSessions.length === 0" class="empty-state ok">
                  <Icon icon="mdi:check-circle-outline" width="28" class="empty-icon" />
                  <p>暂无待审批工单</p>
                </div>
                <div v-else class="msg-list">
                  <div
                    v-for="sess in pendingSessions"
                    :key="sess.session_id"
                    class="msg-item"
                    @click="gotoWorkOrder(sess.session_id)"
                  >
                    <div class="msg-icon"><Icon icon="mdi:wrench-clock" width="16" /></div>
                    <div class="msg-body">
                      <p class="msg-title">{{ sess.title || '未命名会话' }}</p>
                      <p class="msg-sub">{{ formatDate(sess.updated_at) }}</p>
                    </div>
                    <span class="msg-tag pending">待审批</span>
                  </div>
                </div>
              </div>

              <!-- 异常告警 -->
              <div class="msg-block">
                <p class="block-label">
                  <Icon icon="mdi:alert-circle-outline" width="14" />
                  近期异常告警
                  <button class="refresh-btn" @click="loadAnomalies" :disabled="anomalyLoading">
                    <Icon :icon="anomalyLoading ? 'mdi:loading' : 'mdi:refresh'" width="13"
                      :class="{ spin: anomalyLoading }" />
                  </button>
                </p>
                <div v-if="anomalyLoading && anomalies.length === 0" class="empty-state">
                  <Icon icon="mdi:loading" width="24" class="empty-icon spin" />
                  <p>加载中...</p>
                </div>
                <div v-else-if="anomalyError" class="empty-state error">
                  <Icon icon="mdi:alert" width="24" class="empty-icon" />
                  <p>{{ anomalyError }}</p>
                </div>
                <div v-else-if="anomalies.length === 0" class="empty-state ok">
                  <Icon icon="mdi:check-all" width="28" class="empty-icon" />
                  <p>近期无异常告警</p>
                </div>
                <div v-else class="msg-list">
                  <div
                    v-for="anom in anomalies"
                    :key="anom.id ?? anom.detected_at"
                    class="msg-item"
                    :class="'sev-' + (anom.severity ?? 'medium').toLowerCase()"
                  >
                    <div class="msg-icon anom"><Icon icon="mdi:alert-outline" width="16" /></div>
                    <div class="msg-body">
                      <p class="msg-title">{{ anom.anomaly_type ?? '未知异常' }}</p>
                      <p class="msg-sub">
                        楼宇 {{ anom.building_id }} · 设备 {{ anom.device_id ?? '—' }}
                        · {{ formatDate(anom.detected_at) }}
                      </p>
                    </div>
                    <span class="msg-tag" :class="'tag-' + (anom.severity ?? 'medium').toLowerCase()">
                      {{ anom.severity ?? 'medium' }}
                    </span>
                  </div>
                </div>
              </div>
            </template>

            <!-- ═══════════ 帮助中心 ═══════════ -->
            <template v-if="activeSection === 'help'">
              <div class="faq-list">
                <div v-for="faq in FAQ_LIST" :key="faq.q" class="faq-item">
                  <button class="faq-question" @click="faq._open = !faq._open">
                    <Icon :icon="faq._open ? 'mdi:chevron-down' : 'mdi:chevron-right'" width="14" />
                    {{ faq.q }}
                  </button>
                  <div v-if="faq._open" class="faq-answer">{{ faq.a }}</div>
                </div>
              </div>
            </template>

            <!-- ═══════════ 反馈中心 ═══════════ -->
            <template v-if="activeSection === 'feedback'">
              <p class="body-desc">我们非常重视您的反馈，请描述您遇到的问题或功能建议。</p>
              <textarea
                v-model="feedbackText"
                class="feedback-textarea"
                placeholder="请描述您遇到的问题或功能建议..."
                rows="6"
              ></textarea>
              <div class="setting-actions">
                <button class="btn-primary" @click="submitFeedback" :disabled="feedbackSent || !feedbackText.trim()">
                  <Icon :icon="feedbackSent ? 'mdi:check' : 'mdi:send-outline'" width="14" />
                  {{ feedbackSent ? '感谢您的反馈！' : '提交反馈' }}
                </button>
              </div>
            </template>

          </div>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<script setup lang="ts">
import { ref, computed, reactive, watch, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { Icon } from '@iconify/vue'
import { useAuthStore } from '@/stores/authStore'
import { useChatStore } from '@/stores/chatStore'
import { apiChangePassword, apiUpdateProfile } from '@/api/auth'
import { apiFetch } from '@/api/http'

const props = defineProps<{
  visible: boolean
  initialSection?: string
}>()
const emit = defineEmits<{ close: [] }>()

const router = useRouter()
const authStore = useAuthStore()
const chatStore = useChatStore()

const user = computed(() => authStore.user)

// ── 当前显示的区块 ──────────────────────────────
const SECTION_TITLES: Record<string, string> = {
  settings: '设置',
  messages: '消息中心',
  help: '帮助中心',
  feedback: '反馈中心',
}

const activeSection = ref(props.initialSection ?? 'settings')

// 每次打开时同步 initialSection
watch(() => props.visible, (v) => {
  if (v && props.initialSection) {
    activeSection.value = props.initialSection
  }
})

// ── 设置子Tab ──────────────────────────────────
const SETTINGS_TABS = [
  { id: 'profile',     label: '个人资料', icon: 'mdi:account-outline' },
  { id: 'security',    label: '账号安全', icon: 'mdi:shield-lock-outline' },
  { id: 'preferences', label: '偏好设置', icon: 'mdi:tune-variant' },
]

const settingsTab = ref('profile')
const editingField = ref('')
const showPwdForm = ref(false)

// ── 角色元数据 ──────────────────────────────────
const ROLE_LABELS: Record<string, string> = {
  resident: '住户',
  ops: '运维人员',
  manager: '运维经理',
  admin: '系统管理员',
}

const avatarInitials = computed(() => {
  const name = user.value?.username ?? ''
  if (!name) return '?'
  return name.slice(0, 2).toUpperCase()
})

// ── 个人资料表单 ──────────────────────────────────
const profileForm = reactive({
  email: user.value?.email ?? '',
  phone: user.value?.phone ?? '',
})

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

// ── 修改密码 ──────────────────────────────────
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
    setTimeout(() => {
      authStore.logout()
      emit('close')
      router.push('/login')
    }, 2000)
  } catch (e: unknown) {
    pwdMsg.value = (e as Error).message ?? '修改失败'
    pwdMsgType.value = 'err'
  } finally {
    pwdSaving.value = false
  }
}

// ── 主题偏好 ──────────────────────────────────
const currentTheme = ref(localStorage.getItem('theme') ?? 'dark')

function setTheme(t: 'dark' | 'light') {
  currentTheme.value = t
  document.documentElement.dataset.theme = t
  localStorage.setItem('theme', t)
}

// ── Web Search 偏好 ──────────────────────────────
const WEB_SEARCH_PREF_KEY = 'chat_web_search_default'
const webSearchDefault = ref(localStorage.getItem(WEB_SEARCH_PREF_KEY) === 'true')

function saveWebSearchPref() {
  localStorage.setItem(WEB_SEARCH_PREF_KEY, String(webSearchDefault.value))
}

// ── 消息中心 ──────────────────────────────────
const pendingSessions = computed(() =>
  chatStore.sessionList.filter(s => s.has_pending_action)
)

function gotoWorkOrder(sessionId: string) {
  chatStore.switchSession(sessionId)
  emit('close')
  router.push('/workorders')
}

// ── 异常告警 ──────────────────────────────────
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

// ── FAQ ──────────────────────────────────
interface FaqItem { q: string; a: string; _open: boolean }

const FAQ_LIST = reactive<FaqItem[]>([
  { q: '如何发起 AI 诊断工单？', a: '在右侧 AI 控制台向 AI 描述问题（如"3号楼空调能耗偏高"），AI 将自动分析并生成工单，您可在"工单管理"页面审批执行。', _open: false },
  { q: '如何上传数据进行分析？', a: '进入"数据中心"页面，点击"上传数据集"按钮，支持 CSV / Excel 格式。上传后可在 AI 对话中引用该数据集进行问答分析。', _open: false },
  { q: '主题颜色如何切换？', a: '在"设置 → 偏好设置"中切换"深色"或"浅色"主题，也可通过左侧导航栏底部的调色板图标快速切换。', _open: false },
  { q: '联网搜索有什么用？', a: '开启后，AI 在回答问题时会主动搜索互联网获取最新资料，适合查询行业规范、政策法规等外部知识。可在 AI 控制台底部单独切换。', _open: false },
  { q: '如何联系技术支持？', a: '请发送邮件至 support@yourcompany.com 或通过"反馈中心"提交问题，我们将在 1 个工作日内响应。', _open: false },
])

// ── 反馈 ──────────────────────────────────
const feedbackText = ref('')
const feedbackSent = ref(false)

function submitFeedback() {
  if (!feedbackText.value.trim()) return
  feedbackSent.value = true
  setTimeout(() => {
    feedbackText.value = ''
    feedbackSent.value = false
  }, 3000)
}

// ── 工具函数 ──────────────────────────────────
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

// ── 初始化 ──────────────────────────────────
onMounted(() => {
  if (chatStore.sessionList.length === 0) chatStore.loadSessionList()
  loadAnomalies()
})
</script>

<style scoped>
/* ── 遮罩层 ── */
.pm-overlay {
  position: fixed;
  inset: 0;
  z-index: 9000;
  background: rgba(0, 0, 0, 0.3);
  backdrop-filter: blur(6px);
  display: flex;
  align-items: center;
  justify-content: center;
}

/* ── 弹窗主体 ── */
.pm-dialog {
  width: 640px;
  max-width: 92vw;
  max-height: 80vh;
  background: #ffffff;
  border: 1px solid rgba(0, 0, 0, 0.06);
  border-radius: 18px;
  box-shadow:
    0 4px 6px -1px rgba(0, 0, 0, 0.04),
    0 16px 40px -8px rgba(0, 0, 0, 0.12);
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

:deep([data-theme="dark"]) .pm-dialog,
:root[data-theme="dark"] .pm-dialog {
  background: #1a2420;
  border-color: rgba(255, 255, 255, 0.06);
  box-shadow:
    0 4px 6px -1px rgba(0, 0, 0, 0.15),
    0 16px 40px -8px rgba(0, 0, 0, 0.4);
}

/* ── 顶部标题栏 ── */
.pm-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 20px 24px 16px;
  border-bottom: 1px solid rgba(0, 0, 0, 0.06);
  flex-shrink: 0;
}

.pm-title {
  font-size: 18px;
  font-weight: 700;
  color: #111827;
  margin: 0;
  letter-spacing: -0.01em;
}

.pm-close {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 32px;
  height: 32px;
  background: none;
  border: none;
  border-radius: 8px;
  color: #9ca3af;
  cursor: pointer;
  transition: background 0.15s ease, color 0.15s ease;
}
.pm-close:hover {
  background: #f3f4f6;
  color: #374151;
}

/* ── 内容区 ── */
.pm-body {
  flex: 1;
  min-height: 0;
  padding: 20px 24px 24px;
  overflow-y: auto;
}
.pm-body.has-sidebar {
  display: flex;
  padding: 0;
  overflow: hidden;
}

/* ── 设置左侧Tab栏（Grok 风格） ── */
.settings-sidebar {
  width: 150px;
  flex-shrink: 0;
  padding: 16px 10px;
  border-right: 1px solid rgba(0, 0, 0, 0.05);
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.sidebar-tab {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 14px;
  background: none;
  border: none;
  border-radius: 10px;
  color: #6b7280;
  font-size: 13px;
  font-weight: 500;
  cursor: pointer;
  transition: background 0.15s ease, color 0.15s ease;
  text-align: left;
  white-space: nowrap;
}
.sidebar-tab:hover {
  background: #f3f4f6;
  color: #374151;
}
.sidebar-tab.active {
  background: rgba(80, 200, 120, 0.08);
  color: #50c878;
  font-weight: 600;
}

/* ── 设置右侧内容 ── */
.settings-content {
  flex: 1;
  min-width: 0;
  padding: 20px 24px;
  overflow-y: auto;
}

/* ── Grok 风格行 ── */
.grok-row {
  display: flex;
  align-items: center;
  gap: 14px;
  padding: 16px 0;
  border-bottom: 1px solid rgba(0, 0, 0, 0.04);
}
.grok-row:last-child { border-bottom: none; }
.grok-row.clickable {
  cursor: pointer;
  border-radius: 10px;
  padding: 16px 14px;
  margin: 0 -14px;
  border-bottom: none;
  transition: background 0.15s ease;
}
.grok-row.clickable:hover { background: #f9fafb; }
.grok-row.disabled { opacity: 0.4; pointer-events: none; }
.grok-row.user-row { padding-top: 4px; }

.grok-row-info { flex: 1; min-width: 0; }
.grok-row-title {
  font-size: 13.5px;
  font-weight: 500;
  color: #111827;
  margin: 0 0 2px;
  display: flex;
  align-items: center;
  gap: 8px;
}
.grok-row-sub {
  font-size: 12px;
  color: #9ca3af;
  margin: 0;
}

/* 用户 ID（底部灰色小字） */
.grok-id {
  padding: 14px 0 0;
  font-size: 11px;
  font-family: 'JetBrains Mono', monospace;
  color: #d1d5db;
  margin: 0;
  text-align: center;
}

/* 展开编辑区 */
.grok-edit-area {
  padding: 0 0 12px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.grok-edit-area.pwd-form {
  gap: 10px;
}

/* 状态圆点 */
.status-dot {
  width: 10px; height: 10px;
  border-radius: 50%;
  flex-shrink: 0;
}
.status-dot.ok { background: #34d399; box-shadow: 0 0 6px rgba(52, 211, 153, 0.4); }
.status-dot.warn { background: #ef4444; box-shadow: 0 0 6px rgba(239, 68, 68, 0.3); }

/* ── 用户头像 ── */
.user-avatar {
  width: 42px;
  height: 42px;
  border-radius: 10px;
  background: linear-gradient(135deg, #6ee7a0, #50c878);
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.avatar-text {
  color: #fff;
  font-size: 15px;
  font-weight: 700;
  letter-spacing: 0.02em;
}

/* ── 角色标签 ── */
.role-badge {
  font-size: 11px; font-weight: 600; padding: 3px 10px;
  border-radius: 20px; letter-spacing: 0.03em; flex-shrink: 0;
}
.role-resident  { background: rgba(80, 200, 120, 0.1); color: #34d399; }
.role-ops       { background: rgba(56, 189, 248, 0.1); color: #38bdf8; }
.role-manager   { background: rgba(251, 191, 36, 0.1); color: #f59e0b; }
.role-admin     { background: rgba(239, 68, 68, 0.1);  color: #ef4444; }

/* ── 表单输入 ── */
.setting-input {
  width: 100%; padding: 8px 12px;
  background: #f9fafb; border: 1px solid rgba(0, 0, 0, 0.08);
  border-radius: 10px; color: #111827; font-size: 13px;
  outline: none; transition: border-color 0.2s ease, box-shadow 0.2s ease;
  box-sizing: border-box;
}
.setting-input:focus {
  border-color: #50c878;
  box-shadow: 0 0 0 3px rgba(80, 200, 120, 0.1);
}

.setting-actions { display: flex; align-items: center; gap: 14px; padding-top: 14px; }

.coming-soon {
  font-size: 10px; font-weight: 500;
  background: rgba(251, 191, 36, 0.1); color: #f59e0b;
  padding: 1px 8px; border-radius: 20px;
}

/* ── 按钮 ── */
.btn-primary {
  display: flex; align-items: center; gap: 7px; padding: 8px 20px;
  background: #50c878; color: #fff; border: none; border-radius: 10px;
  font-size: 13px; font-weight: 600; cursor: pointer;
  transition: background 0.15s ease, transform 0.1s ease;
}
.btn-primary:hover:not(:disabled) { background: #45b86c; }
.btn-primary:active:not(:disabled) { transform: scale(0.98); }
.btn-primary:disabled { opacity: 0.5; cursor: not-allowed; }

.btn-action {
  padding: 6px 16px; background: #f3f4f6;
  border: 1px solid rgba(0, 0, 0, 0.06); border-radius: 20px;
  color: #374151; font-size: 12px; font-weight: 500;
  cursor: pointer; transition: background 0.15s ease; flex-shrink: 0;
}
.btn-action:hover { background: #e5e7eb; }

.form-msg { font-size: 12px; font-weight: 500; }
.form-msg.ok  { color: #34d399; }
.form-msg.err { color: #ef4444; }

/* ── Toggle Switch ── */
.toggle-switch { position: relative; display: inline-block; width: 42px; height: 24px; flex-shrink: 0; cursor: pointer; }
.toggle-switch input { opacity: 0; width: 0; height: 0; }
.toggle-track {
  position: absolute; inset: 0; background: #d1d5db;
  border-radius: 24px; transition: background 0.25s ease;
}
.toggle-track::before {
  content: ''; position: absolute; width: 18px; height: 18px;
  left: 3px; bottom: 3px; background: #fff; border-radius: 50%;
  transition: transform 0.25s ease;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.1);
}
.toggle-switch input:checked + .toggle-track { background: #50c878; }
.toggle-switch input:checked + .toggle-track::before { transform: translateX(18px); }

/* ── 消息中心 ── */
.body-desc { font-size: 13px; color: #9ca3af; margin: 0 0 16px; line-height: 1.65; }
.msg-block { margin-bottom: 22px; }
.msg-block:last-child { margin-bottom: 0; }
.block-label {
  display: flex; align-items: center; gap: 7px;
  font-size: 11px; font-weight: 600; color: #9ca3af;
  text-transform: uppercase; letter-spacing: 0.08em; margin: 0 0 10px;
}
.count-badge {
  background: #50c878; color: #fff; font-size: 10px;
  min-width: 17px; height: 17px; border-radius: 20px; padding: 0 5px;
  display: flex; align-items: center; justify-content: center;
}
.refresh-btn {
  margin-left: auto; background: none; border: none; color: #9ca3af;
  cursor: pointer; padding: 2px 4px; border-radius: 6px; display: flex;
  align-items: center; transition: color 0.15s ease;
}
.refresh-btn:hover { color: #374151; }
.refresh-btn:disabled { opacity: 0.4; cursor: not-allowed; }

.empty-state {
  display: flex; flex-direction: column; align-items: center; gap: 8px;
  padding: 28px 16px; background: #f9fafb;
  border: 1px solid rgba(0, 0, 0, 0.04); border-radius: 12px;
  color: #9ca3af; font-size: 13px; text-align: center;
}
.empty-state.error { color: #ef4444; }
.empty-state.ok .empty-icon { color: #34d399; opacity: 0.8; }
.empty-icon { opacity: 0.35; }

.msg-list { display: flex; flex-direction: column; gap: 6px; }
.msg-item {
  display: flex; align-items: center; gap: 12px; padding: 12px 14px;
  background: #f9fafb; border: 1px solid rgba(0, 0, 0, 0.04);
  border-radius: 12px; cursor: pointer;
  transition: background 0.15s ease, border-color 0.15s ease;
}
.msg-item:hover {
  border-color: rgba(80, 200, 120, 0.2);
  background: rgba(80, 200, 120, 0.04);
}

.msg-icon {
  flex-shrink: 0; width: 34px; height: 34px; border-radius: 10px;
  display: flex; align-items: center; justify-content: center;
  background: rgba(80, 200, 120, 0.08); color: #50c878;
}
.msg-icon.anom { background: rgba(239, 68, 68, 0.06); color: #ef4444; }
.sev-high .msg-icon.anom   { background: rgba(239, 68, 68, 0.1); color: #ef4444; }
.sev-medium .msg-icon.anom { background: rgba(251, 191, 36, 0.08); color: #f59e0b; }
.sev-low .msg-icon.anom    { background: rgba(80, 200, 120, 0.08); color: #34d399; }

.msg-body { flex: 1; min-width: 0; }
.msg-title {
  font-size: 13px; font-weight: 600; color: #111827; margin: 0 0 3px;
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
}
.msg-sub { font-size: 11px; color: #9ca3af; margin: 0; }
.msg-tag { font-size: 10px; font-weight: 600; padding: 2px 8px; border-radius: 20px; flex-shrink: 0; }
.msg-tag.pending { background: rgba(80, 200, 120, 0.08); color: #34d399; }
.msg-tag.tag-high   { background: rgba(239, 68, 68, 0.08); color: #ef4444; }
.msg-tag.tag-medium { background: rgba(251, 191, 36, 0.08); color: #f59e0b; }
.msg-tag.tag-low    { background: rgba(80, 200, 120, 0.08); color: #34d399; }

/* ── FAQ ── */
.faq-list { display: flex; flex-direction: column; gap: 6px; }
.faq-question {
  display: flex; align-items: center; gap: 8px; width: 100%; padding: 12px 16px;
  background: #f9fafb; border: 1px solid rgba(0, 0, 0, 0.04);
  border-radius: 10px; color: #374151; font-size: 13px;
  font-weight: 500; cursor: pointer; text-align: left;
  transition: background 0.15s ease, border-color 0.15s ease;
}
.faq-question:hover { background: #f3f4f6; border-color: rgba(0, 0, 0, 0.08); }
.faq-answer {
  padding: 14px 18px; font-size: 13px; color: #6b7280; line-height: 1.7;
  background: #f9fafb; border: 1px solid rgba(0, 0, 0, 0.04);
  border-top: none; border-radius: 0 0 10px 10px; margin-top: -4px;
}

/* ── 反馈 ── */
.feedback-textarea {
  width: 100%; padding: 14px 16px;
  background: #f9fafb; border: 1px solid rgba(0, 0, 0, 0.06);
  border-radius: 12px; color: #111827; font-size: 13px;
  resize: vertical; outline: none;
  transition: border-color 0.2s ease, box-shadow 0.2s ease;
  box-sizing: border-box; font-family: inherit; line-height: 1.65;
}
.feedback-textarea:focus {
  border-color: #50c878;
  box-shadow: 0 0 0 3px rgba(80, 200, 120, 0.1);
}

/* ── 深色模式适配 ── */
:root[data-theme="dark"] .pm-title { color: #f3f4f6; }
:root[data-theme="dark"] .pm-header { border-color: rgba(255,255,255,0.06); }
:root[data-theme="dark"] .pm-close { color: rgba(255,255,255,0.4); }
:root[data-theme="dark"] .pm-close:hover { background: rgba(255,255,255,0.06); color: #f3f4f6; }

/* 设置侧边栏 */
:root[data-theme="dark"] .settings-sidebar { border-color: rgba(255,255,255,0.06); }
:root[data-theme="dark"] .sidebar-tab { color: rgba(255,255,255,0.4); }
:root[data-theme="dark"] .sidebar-tab:hover { background: rgba(255,255,255,0.06); color: rgba(255,255,255,0.8); }
:root[data-theme="dark"] .sidebar-tab.active { background: rgba(80,200,120,0.1); color: #6ee7a0; }

/* Grok 风格行 */
:root[data-theme="dark"] .grok-row { border-color: rgba(255,255,255,0.04); }
:root[data-theme="dark"] .grok-row.clickable:hover { background: rgba(255,255,255,0.04); }
:root[data-theme="dark"] .grok-row-title { color: rgba(255,255,255,0.88); }
:root[data-theme="dark"] .grok-row-sub { color: rgba(255,255,255,0.4); }
:root[data-theme="dark"] .grok-id { color: rgba(255,255,255,0.2); }

/* 表单 */
:root[data-theme="dark"] .setting-input { background: rgba(255,255,255,0.04); border-color: rgba(255,255,255,0.08); color: #f3f4f6; }
:root[data-theme="dark"] .setting-input:focus { border-color: #50c878; box-shadow: 0 0 0 3px rgba(80,200,120,0.15); }
:root[data-theme="dark"] .btn-action { background: rgba(255,255,255,0.06); border-color: rgba(255,255,255,0.08); color: rgba(255,255,255,0.8); }
:root[data-theme="dark"] .btn-action:hover { background: rgba(255,255,255,0.1); }
:root[data-theme="dark"] .toggle-track { background: rgba(255,255,255,0.15); }
:root[data-theme="dark"] .body-desc { color: rgba(255,255,255,0.4); }

/* 消息中心 */
:root[data-theme="dark"] .empty-state { background: rgba(255,255,255,0.03); border-color: rgba(255,255,255,0.04); }
:root[data-theme="dark"] .msg-item { background: rgba(255,255,255,0.03); border-color: rgba(255,255,255,0.04); }
:root[data-theme="dark"] .msg-item:hover { background: rgba(80,200,120,0.06); border-color: rgba(80,200,120,0.15); }
:root[data-theme="dark"] .msg-title { color: #f3f4f6; }
:root[data-theme="dark"] .block-label { color: rgba(255,255,255,0.35); }

/* FAQ */
:root[data-theme="dark"] .faq-question { background: rgba(255,255,255,0.03); border-color: rgba(255,255,255,0.04); color: rgba(255,255,255,0.8); }
:root[data-theme="dark"] .faq-question:hover { background: rgba(255,255,255,0.06); border-color: rgba(255,255,255,0.08); }
:root[data-theme="dark"] .faq-answer { background: rgba(255,255,255,0.03); border-color: rgba(255,255,255,0.04); color: rgba(255,255,255,0.5); }

/* 反馈 */
:root[data-theme="dark"] .feedback-textarea { background: rgba(255,255,255,0.04); border-color: rgba(255,255,255,0.06); color: #f3f4f6; }
:root[data-theme="dark"] .feedback-textarea:focus { border-color: #50c878; box-shadow: 0 0 0 3px rgba(80,200,120,0.15); }

/* ── 弹窗动画 ── */
.modal-fade-enter-active { transition: opacity 0.2s ease; }
.modal-fade-enter-active .pm-dialog { transition: transform 0.2s cubic-bezier(0.16, 1, 0.3, 1), opacity 0.2s ease; }
.modal-fade-leave-active { transition: opacity 0.15s ease; }
.modal-fade-leave-active .pm-dialog { transition: transform 0.15s ease, opacity 0.15s ease; }
.modal-fade-enter-from { opacity: 0; }
.modal-fade-enter-from .pm-dialog { transform: scale(0.96) translateY(8px); opacity: 0; }
.modal-fade-leave-to { opacity: 0; }
.modal-fade-leave-to .pm-dialog { transform: scale(0.96); opacity: 0; }

@keyframes spin { to { transform: rotate(360deg); } }
.spin { animation: spin 0.8s linear infinite; }

/* ── prefers-reduced-motion ── */
@media (prefers-reduced-motion: reduce) {
  .modal-fade-enter-active,
  .modal-fade-leave-active,
  .modal-fade-enter-active .pm-dialog,
  .modal-fade-leave-active .pm-dialog {
    transition: none;
  }
}
</style>
