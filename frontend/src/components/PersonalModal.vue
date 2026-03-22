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
                  <!-- 个人信息头部 -->
                  <div class="profile-header">
                    <div
                      class="profile-avatar-wrap"
                      @click="triggerAvatarUpload"
                      title="点击更换头像"
                    >
                      <img v-if="avatarUrl" :src="avatarUrl" class="profile-avatar-img" alt="头像" />
                      <div v-else class="profile-avatar-placeholder">
                        <span class="avatar-initials">{{ avatarInitials }}</span>
                      </div>
                      <div class="avatar-overlay">
                        <Icon icon="mdi:camera-outline" width="16" />
                        <span>更换</span>
                      </div>
                    </div>
                    <div class="profile-header-info">
                      <div class="profile-name-row">
                        <p class="profile-username">{{ user?.username ?? '—' }}</p>
                        <span class="role-badge" :class="'role-' + (user?.role ?? 'resident')">
                          {{ ROLE_LABELS[user?.role ?? 'resident'] ?? user?.role }}
                        </span>
                      </div>
                      <p class="profile-email-hint">{{ user?.email || '未设置邮箱' }}</p>
                    </div>
                    <input
                      ref="avatarInputRef"
                      type="file"
                      accept="image/*"
                      class="avatar-file-input"
                      @change="onAvatarChange"
                    />
                  </div>
                  <div class="profile-section-divider"></div>

                  <!-- 用户名 -->
                  <div class="grok-row">
                    <div class="grok-row-info">
                      <p class="grok-row-title">用户名</p>
                      <p class="grok-row-sub">{{ profileForm.username || '未设置' }}</p>
                    </div>
                    <div class="row-btns">
                      <button v-if="editingField === 'username'" class="btn-primary sm" @click="saveProfile" :disabled="profileSaving">
                        <Icon :icon="profileSaving ? 'mdi:loading' : 'mdi:check'" width="13" :class="{ spin: profileSaving }" />
                        {{ profileSaving ? '保存中...' : '保存' }}
                      </button>
                      <button class="btn-action" @click="editingField = editingField === 'username' ? '' : 'username'">
                        {{ editingField === 'username' ? '取消' : '更改' }}
                      </button>
                    </div>
                  </div>
                  <div v-if="editingField === 'username'" class="grok-edit-area">
                    <input v-model="profileForm.username" type="text" class="setting-input" placeholder="请输入用户名（2-50位，支持中英文）" />
                    <span v-if="profileMsg && editingField === 'username'" class="form-msg" :class="profileMsgType">{{ profileMsg }}</span>
                  </div>

                  <!-- 邮箱 -->
                  <div class="grok-row">
                    <div class="grok-row-info">
                      <p class="grok-row-title">邮箱</p>
                      <p class="grok-row-sub">{{ profileForm.email || '未设置' }}</p>
                    </div>
                    <div class="row-btns">
                      <button v-if="editingField === 'email'" class="btn-primary sm" @click="saveProfile" :disabled="profileSaving">
                        <Icon :icon="profileSaving ? 'mdi:loading' : 'mdi:check'" width="13" :class="{ spin: profileSaving }" />
                        {{ profileSaving ? '保存中...' : '保存' }}
                      </button>
                      <button class="btn-action" @click="editingField = editingField === 'email' ? '' : 'email'">
                        {{ editingField === 'email' ? '取消' : '更改' }}
                      </button>
                    </div>
                  </div>
                  <div v-if="editingField === 'email'" class="grok-edit-area">
                    <input v-model="profileForm.email" type="email" class="setting-input" placeholder="请输入邮箱" />
                    <span v-if="profileMsg && editingField === 'email'" class="form-msg" :class="profileMsgType">{{ profileMsg }}</span>
                  </div>

                  <!-- 手机号 -->
                  <div class="grok-row">
                    <div class="grok-row-info">
                      <p class="grok-row-title">手机号</p>
                      <p class="grok-row-sub">{{ profileForm.phone || '未设置' }}</p>
                    </div>
                    <div class="row-btns">
                      <button v-if="editingField === 'phone'" class="btn-primary sm" @click="saveProfile" :disabled="profileSaving">
                        <Icon :icon="profileSaving ? 'mdi:loading' : 'mdi:check'" width="13" :class="{ spin: profileSaving }" />
                        {{ profileSaving ? '保存中...' : '保存' }}
                      </button>
                      <button class="btn-action" @click="editingField = editingField === 'phone' ? '' : 'phone'">
                        {{ editingField === 'phone' ? '取消' : '更改' }}
                      </button>
                    </div>
                  </div>
                  <div v-if="editingField === 'phone'" class="grok-edit-area">
                    <input v-model="profileForm.phone" type="tel" class="setting-input" placeholder="请输入手机号" />
                    <span v-if="profileMsg && editingField === 'phone'" class="form-msg" :class="profileMsgType">{{ profileMsg }}</span>
                  </div>

                  <!-- 注册时间（只读） -->
                  <div class="grok-row">
                    <div class="grok-row-info">
                      <p class="grok-row-title">注册时间</p>
                      <p class="grok-row-sub">{{ formatDate(user?.created_at) }}</p>
                    </div>
                  </div>

                  <p class="grok-id">{{ user?.id }}</p>
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

              <!-- ── 胶囊切换 ── -->
              <div class="msg-capsule-wrap">
                <div class="msg-capsule">
                  <button
                    class="capsule-btn"
                    :class="{ active: msgTab === 'workorder' }"
                    @click="switchMsgTab('workorder')"
                  >
                    <Icon icon="mdi:clipboard-clock-outline" width="13" />
                    待审批工单
                    <span v-if="pendingSessions.length > 0" class="capsule-dot ok">{{ pendingSessions.length }}</span>
                  </button>
                  <button
                    class="capsule-btn"
                    :class="{ active: msgTab === 'anomaly' }"
                    @click="switchMsgTab('anomaly')"
                  >
                    <Icon icon="mdi:bell-ring-outline" width="13" />
                    异常告警
                    <span v-if="anomalies.length > 0" class="capsule-dot">{{ anomalies.length > 99 ? '99+' : anomalies.length }}</span>
                  </button>
                  <button
                    class="capsule-btn"
                    :class="{ active: msgTab === 'warning' }"
                    @click="switchMsgTab('warning')"
                  >
                    <Icon icon="mdi:lightning-bolt-outline" width="13" />
                    预警通知
                    <span v-if="riskHighCount > 0" class="capsule-dot warn">{{ riskHighCount }}</span>
                  </button>
                </div>
              </div>

              <!-- ── 筛选栏 ── -->
              <div class="msg-filter-bar">
                <div class="filter-group">
                  <span class="filter-label">
                    <Icon icon="mdi:office-building-outline" width="11" />
                    建筑
                  </span>
                  <div class="filter-value-row">
                    <select v-model="filterBuilding" class="filter-select">
                      <option v-for="opt in BUILDING_OPTIONS" :key="opt.value" :value="opt.value">{{ opt.label }}</option>
                    </select>
                    <Icon icon="mdi:chevron-down" width="13" class="filter-chevron" />
                  </div>
                </div>

                <div class="filter-divider"></div>

                <div class="filter-group">
                  <span class="filter-label">
                    <Icon icon="mdi:clock-time-four-outline" width="11" />
                    时间范围
                  </span>
                  <div class="filter-value-row">
                    <select v-model.number="filterHours" class="filter-select">
                      <option v-for="opt in TIME_OPTIONS" :key="opt.value" :value="opt.value">{{ opt.label }}</option>
                    </select>
                    <Icon icon="mdi:chevron-down" width="13" class="filter-chevron" />
                  </div>
                </div>

                <button
                  class="filter-action-btn"
                  :class="hasActiveFilter ? 'filter-action-reset' : 'filter-action-apply'"
                  @click="hasActiveFilter ? resetFilters() : undefined"
                >
                  <Icon :icon="hasActiveFilter ? 'mdi:close' : 'mdi:filter-outline'" width="14" />
                  {{ hasActiveFilter ? '重置' : '筛选' }}
                </button>
              </div>

              <!-- ── Tab: 待审批工单 ── -->
              <div v-if="msgTab === 'workorder'" class="msg-tab-content">
                <div class="msg-block">
                  <p class="block-label">
                    <Icon icon="mdi:clipboard-clock-outline" width="13" />
                    待审批工单
                    <span v-if="pendingSessions.length > 0" class="count-badge">{{ pendingSessions.length }}</span>
                  </p>
                  <div v-if="pendingSessions.length === 0" class="empty-state ok">
                    <Icon icon="mdi:check-circle-outline" width="26" class="empty-icon" />
                    <p>暂无待审批工单</p>
                  </div>
                  <div v-else class="msg-list">
                    <div
                      v-for="sess in pendingSessions"
                      :key="sess.session_id"
                      class="msg-item clickable"
                      @click="gotoWorkOrder(sess.session_id)"
                    >
                      <div class="msg-icon workorder">
                        <Icon icon="mdi:wrench-clock" width="15" />
                      </div>
                      <div class="msg-body">
                        <p class="msg-title">{{ sess.title || '未命名会话' }}</p>
                        <p class="msg-sub">{{ formatDate(sess.updated_at) }}</p>
                      </div>
                      <span class="msg-tag pending">待审批</span>
                      <Icon icon="mdi:chevron-right" width="14" class="msg-chevron" />
                    </div>
                  </div>
                </div>
              </div>

              <!-- ── Tab: 异常告警 ── -->
              <div v-if="msgTab === 'anomaly'" class="msg-tab-content">
                <div class="msg-block">
                  <p class="block-label">
                    <Icon icon="mdi:alert-circle-outline" width="13" />
                    已发生异常
                    <button class="refresh-btn" @click="loadAnomalies" :disabled="anomalyLoading" title="刷新">
                      <Icon :icon="anomalyLoading ? 'mdi:loading' : 'mdi:refresh'" width="12" :class="{ spin: anomalyLoading }" />
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
                  <div v-else-if="filteredAnomalies.length === 0" class="empty-state ok">
                    <Icon icon="mdi:check-all" width="26" class="empty-icon" />
                    <p>{{ hasActiveFilter ? '当前筛选条件下无异常记录' : '近期无异常告警' }}</p>
                  </div>
                  <div v-else class="msg-list">
                    <div
                      v-for="(anom, idx) in filteredAnomalies"
                      :key="anom.timestamp + idx"
                      class="msg-item"
                      :class="'sev-' + deviationSeverity(anom.deviation_pct)"
                    >
                      <div class="msg-icon anom">
                        <Icon :icon="ruleIcon(anom.rule)" width="15" />
                      </div>
                      <div class="msg-body">
                        <p class="msg-title">{{ ruleLabel(anom.rule) }}</p>
                        <p class="msg-sub">
                          {{ buildingLabel(anom.building_type) }}
                          <template v-if="anom.deviation_pct != null">
                            · <span :class="'dev-' + deviationSeverity(anom.deviation_pct)">{{ anom.deviation_pct > 0 ? '+' : '' }}{{ anom.deviation_pct.toFixed(1) }}%</span>
                          </template>
                          · {{ formatDate(anom.timestamp) }}
                        </p>
                        <p v-if="anom.message" class="msg-detail">{{ anom.message }}</p>
                      </div>
                      <span class="msg-tag" :class="'tag-' + deviationSeverity(anom.deviation_pct)">
                        {{ { high: '严重', medium: '警告', low: '提示' }[deviationSeverity(anom.deviation_pct)] }}
                      </span>
                    </div>
                  </div>
                </div>
              </div>

              <!-- ── Tab: 预警通知 ── -->
              <div v-if="msgTab === 'warning'" class="msg-tab-content">
                <div class="msg-block">
                  <p class="block-label">
                    <Icon icon="mdi:lightning-bolt-outline" width="13" />
                    实时能耗风险评估
                    <button class="refresh-btn" @click="loadRisks" :disabled="riskLoading" title="刷新">
                      <Icon :icon="riskLoading ? 'mdi:loading' : 'mdi:refresh'" width="12" :class="{ spin: riskLoading }" />
                    </button>
                    <span class="block-label-hint">基于当前天气实时计算</span>
                  </p>
                  <div v-if="riskLoading && risks.length === 0" class="empty-state">
                    <Icon icon="mdi:loading" width="24" class="empty-icon spin" />
                    <p>正在评估中...</p>
                  </div>
                  <div v-else-if="riskError" class="empty-state error">
                    <Icon icon="mdi:alert" width="24" class="empty-icon" />
                    <p>{{ riskError }}</p>
                  </div>
                  <div v-else-if="filteredRisks.length === 0" class="empty-state ok">
                    <Icon icon="mdi:check-circle-outline" width="26" class="empty-icon" />
                    <p>{{ hasActiveFilter ? '该建筑运行正常' : '所有楼宇运行正常' }}</p>
                  </div>
                  <div v-else class="msg-list">
                    <div
                      v-for="risk in filteredRisks"
                      :key="risk.building_id"
                      class="risk-card"
                      :class="'risk-' + risk.risk_level"
                    >
                      <div class="risk-card-left">
                        <div class="risk-icon">
                          <Icon :icon="risk.risk_level === 'high' ? 'mdi:alert' : risk.risk_level === 'medium' ? 'mdi:alert-circle-outline' : risk.risk_level === 'low' ? 'mdi:information-outline' : 'mdi:check-circle-outline'" width="16" />
                        </div>
                        <div class="risk-info">
                          <div class="risk-header">
                            <span class="risk-name">{{ risk.building_name }}</span>
                            <span class="risk-mode-badge">{{ risk.hvac_mode_label }}</span>
                          </div>
                          <p class="risk-desc">{{ risk.risk_desc }}</p>
                          <p class="risk-meta">
                            室外 {{ Number(risk.air_temp).toFixed(1) }}℃ · 期望 {{ risk.expected_hac }} kWh
                            <template v-if="risk.deviation_pct != null">
                              · 偏差 <span :class="'dev-' + risk.risk_level">{{ risk.deviation_pct > 0 ? '+' : '' }}{{ risk.deviation_pct }}%</span>
                            </template>
                          </p>
                        </div>
                      </div>
                      <span class="risk-level-badge" :class="'rlv-' + risk.risk_level">
                        {{ { high: '高风险', medium: '警告', low: '偏高', normal: '正常' }[risk.risk_level] }}
                      </span>
                    </div>
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

// ── 头像上传（本地 localStorage 存储）──────────────────────────
const avatarInputRef = ref<HTMLInputElement | null>(null)

const avatarUrl = ref<string>(
  localStorage.getItem(`avatar_${user.value?.id ?? 'guest'}`) ?? ''
)

// 用户 id 加载后同步头像
watch(user, (u) => {
  if (u?.id) {
    avatarUrl.value = localStorage.getItem(`avatar_${u.id}`) ?? ''
  }
}, { immediate: true })

function triggerAvatarUpload() {
  avatarInputRef.value?.click()
}

function onAvatarChange(e: Event) {
  const file = (e.target as HTMLInputElement).files?.[0]
  if (!file) return
  const reader = new FileReader()
  reader.onload = async (ev) => {
    const dataUrl = ev.target?.result as string
    avatarUrl.value = dataUrl
    const { useNotificationStore } = await import('@/stores/notificationStore')
    useNotificationStore().saveAvatar(user.value?.id ?? 'guest', dataUrl)
  }
  reader.readAsDataURL(file)
  if (avatarInputRef.value) avatarInputRef.value.value = ''
}

// ── 个人资料表单 ──────────────────────────────────
const editingField = ref('')

const profileForm = reactive({
  username: user.value?.username ?? '',
  email:    user.value?.email    ?? '',
  phone:    user.value?.phone    ?? '',
})

watch(user, (u) => {
  if (u) {
    profileForm.username = u.username ?? ''
    profileForm.email    = u.email    ?? ''
    profileForm.phone    = u.phone    ?? ''
  }
}, { immediate: true })

const profileSaving  = ref(false)
const profileMsg     = ref('')
const profileMsgType = ref<'ok' | 'err'>('ok')

function cancelEdit() {
  const u = user.value
  if (u) {
    profileForm.username = u.username ?? ''
    profileForm.email    = u.email    ?? ''
    profileForm.phone    = u.phone    ?? ''
  }
  editingField.value = ''
}

async function saveProfile() {
  if (!authStore.accessToken) return
  profileSaving.value = true
  profileMsg.value = ''
  try {
    const payload: { username?: string; email?: string; phone?: string } = {}
    if (editingField.value === 'username') payload.username = profileForm.username || undefined
    if (editingField.value === 'email')    payload.email    = profileForm.email    || undefined
    if (editingField.value === 'phone')    payload.phone    = profileForm.phone    || undefined

    const updated = await apiUpdateProfile(authStore.accessToken, payload)
    authStore.user = updated
    editingField.value = ''
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
const msgTab = ref<'workorder' | 'anomaly' | 'warning'>('workorder')

// ── 筛选状态 ──────────────────────────────────
const filterBuilding = ref<string>('all')
const filterHours    = ref<number>(0)

const BUILDING_OPTIONS = [
  { value: 'all',       label: '全部建筑' },
  { value: 'Education', label: '教学楼' },
  { value: 'Office',    label: '办公楼' },
  { value: 'Public',    label: '图书馆' },
]
const TIME_OPTIONS = [
  { value: 0,    label: '全部时间' },
  { value: 24,   label: '近 24 小时' },
  { value: 168,  label: '近 7 天' },
  { value: 720,  label: '近 30 天' },
]

const hasActiveFilter = computed(
  () => filterBuilding.value !== 'all' || filterHours.value !== 0
)

function resetFilters() {
  filterBuilding.value = 'all'
  filterHours.value    = 0
}

const filteredAnomalies = computed(() => {
  let list = anomalies.value
  if (filterBuilding.value !== 'all')
    list = list.filter(a => a.building_type === filterBuilding.value)
  if (filterHours.value > 0) {
    const cutoff = Date.now() - filterHours.value * 3600 * 1000
    list = list.filter(a => new Date(a.timestamp).getTime() >= cutoff)
  }
  return list
})

const filteredRisks = computed(() =>
  filterBuilding.value === 'all'
    ? risks.value
    : risks.value.filter(r => r.building_type === filterBuilding.value)
)

const pendingSessions = computed(() =>
  chatStore.sessionList.filter(s => s.has_pending_action)
)

function switchMsgTab(tab: 'workorder' | 'anomaly' | 'warning') {
  msgTab.value = tab
  if (tab === 'warning' && risks.value.length === 0) loadRisks()
}

function gotoWorkOrder(sessionId: string) {
  chatStore.switchSession(sessionId)
  emit('close')
  router.push('/workorders')
}

// ── 异常告警 ──────────────────────────────────
interface AnomalyItem {
  timestamp: string
  building_id?: string | number
  building_type?: string
  meter_device_id?: string
  rule?: string
  message?: string
  actual_value?: number
  expected_value?: number
  deviation_pct?: number
}

const RULE_LABELS: Record<string, string> = {
  electricity_overload:  '电耗超标',
  water_leak:            '水耗异常',
  hvac_overconsumption:  '空调能耗超标',
  A_low_efficiency:      '主机效能衰退',
  B_small_deltaT:        '水力失调（大流量小温差）',
  C_unexpected_on:       '非预期开机',
}

const RULE_ICONS: Record<string, string> = {
  electricity_overload:  'mdi:lightning-bolt',
  water_leak:            'mdi:water-alert',
  hvac_overconsumption:  'mdi:air-conditioner',
  A_low_efficiency:      'mdi:gauge-low',
  B_small_deltaT:        'mdi:waves-arrow-right',
  C_unexpected_on:       'mdi:clock-alert-outline',
}

function ruleLabel(rule?: string) {
  return RULE_LABELS[rule ?? ''] ?? rule ?? '未知异常'
}

function ruleIcon(rule?: string) {
  return RULE_ICONS[rule ?? ''] ?? 'mdi:alert-outline'
}

function deviationSeverity(pct?: number): 'high' | 'medium' | 'low' {
  const abs = Math.abs(pct ?? 0)
  if (abs >= 30) return 'high'
  if (abs >= 15) return 'medium'
  return 'low'
}

function buildingLabel(type?: string) {
  const map: Record<string, string> = {
    Office: '办公楼', Education: '教学楼',
    'Public services': '图书馆', Public: '图书馆',
  }
  return map[type ?? ''] ?? type ?? '—'
}

const anomalies = ref<AnomalyItem[]>([])
const anomalyLoading = ref(false)
const anomalyError = ref('')

async function loadAnomalies() {
  anomalyLoading.value = true
  anomalyError.value = ''
  try {
    const data = await apiFetch<{ anomalies: AnomalyItem[] }>('/api/anomalies/recent?hours=168')
    anomalies.value = data?.anomalies ?? []
    // 刷新后清除角标
    const { useNotificationStore } = await import('@/stores/notificationStore')
    useNotificationStore().clearBadge()
  } catch (e: unknown) {
    anomalyError.value = (e as Error).message ?? '加载失败'
  } finally {
    anomalyLoading.value = false
  }
}

// ── 预警通知 ──────────────────────────────────
interface RiskItem {
  building_id: string
  building_name: string
  building_type?: string
  hvac_mode: string
  hvac_mode_label: string
  expected_hac: number
  air_temp: number
  risk_level: 'high' | 'medium' | 'low' | 'normal'
  deviation_pct?: number | null
  risk_desc: string
}

const risks        = ref<RiskItem[]>([])
const riskLoading  = ref(false)
const riskError    = ref('')
const riskHighCount = computed(() =>
  risks.value.filter(r => r.risk_level === 'high' || r.risk_level === 'medium').length
)

async function loadRisks() {
  riskLoading.value = true
  riskError.value = ''
  try {
    const data = await apiFetch<{ risks: RiskItem[] }>('/api/buildings/risk-now')
    risks.value = data?.risks ?? []
  } catch (e: unknown) {
    riskError.value = (e as Error).message ?? '加载失败'
  } finally {
    riskLoading.value = false
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
  max-width: 94vw;
  height: 520px;
  max-height: 94vh;
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

.pm-dialog.section-messages { width: 720px; height: 680px; }

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

/* ── 个人信息头部 ── */
.profile-header {
  display: flex;
  align-items: center;
  gap: 18px;
  padding: 4px 0 20px;
}

.profile-avatar-wrap {
  position: relative;
  width: 64px;
  height: 64px;
  border-radius: 50%;
  flex-shrink: 0;
  cursor: pointer;
  overflow: hidden;
}

.profile-avatar-img {
  width: 100%;
  height: 100%;
  object-fit: cover;
  border-radius: 50%;
  display: block;
}

.profile-avatar-placeholder {
  width: 100%;
  height: 100%;
  border-radius: 50%;
  background: linear-gradient(135deg, #6ee7a0, #50c878);
  display: flex;
  align-items: center;
  justify-content: center;
}

.avatar-initials {
  color: #fff;
  font-size: 20px;
  font-weight: 700;
  letter-spacing: 0.02em;
  user-select: none;
}

.avatar-overlay {
  position: absolute;
  inset: 0;
  border-radius: 50%;
  background: rgba(0, 0, 0, 0.45);
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 2px;
  color: #fff;
  font-size: 10px;
  font-weight: 500;
  opacity: 0;
  transition: opacity 0.18s ease;
}

.profile-avatar-wrap:hover .avatar-overlay {
  opacity: 1;
}

.avatar-file-input {
  display: none;
}

.profile-header-info {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.profile-name-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
}

.profile-username {
  font-size: 17px;
  font-weight: 700;
  color: #111827;
  margin: 0;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.profile-email-hint {
  font-size: 12px;
  color: #9ca3af;
  margin: 0;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.profile-section-divider {
  height: 1px;
  background: rgba(0, 0, 0, 0.06);
  margin: 0 0 4px;
}

/* 旧版小头像兼容保留 */
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

.row-btns {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-shrink: 0;
}
.btn-primary.sm {
  padding: 5px 12px;
  font-size: 12px;
  height: auto;
  display: flex;
  align-items: center;
  gap: 4px;
}

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

/* 胶囊切换 */
.msg-capsule-wrap {
  display: flex; justify-content: flex-start; margin-bottom: 18px;
}
.msg-capsule {
  display: inline-flex; align-items: center; gap: 2px;
  background: #f3f4f6; border-radius: 100px; padding: 3px;
}
.capsule-btn {
  display: inline-flex; align-items: center; gap: 5px;
  padding: 6px 13px; border-radius: 100px; border: none;
  font-size: 12px; font-weight: 500; cursor: pointer;
  color: #6b7280; background: transparent;
  transition: background 0.18s ease, color 0.18s ease, box-shadow 0.18s ease;
  position: relative; white-space: nowrap;
}
.capsule-btn:hover { color: #374151; }
.capsule-btn.active {
  background: #fff; color: #111827; font-weight: 600;
  box-shadow: 0 1px 4px rgba(0,0,0,0.1), 0 0 0 1px rgba(0,0,0,0.04);
}
.capsule-dot {
  display: inline-flex; align-items: center; justify-content: center;
  min-width: 16px; height: 16px; border-radius: 20px; padding: 0 4px;
  font-size: 10px; font-weight: 700; line-height: 1;
  background: #ef4444; color: #fff;
}
.capsule-dot.warn { background: #f59e0b; }
.capsule-dot.ok   { background: #50c878; }

/* ── 筛选栏 ── */
.msg-filter-bar {
  display: flex; align-items: stretch;
  background: #fff;
  border: 1px solid rgba(0, 0, 0, 0.08);
  border-radius: 12px;
  box-shadow: 0 1px 4px rgba(0, 0, 0, 0.05);
  overflow: hidden;
  margin-bottom: 16px;
}
.filter-group {
  flex: 1; display: flex; flex-direction: column;
  padding: 9px 14px; cursor: pointer; position: relative;
  transition: background 0.15s ease;
}
.filter-group:hover { background: rgba(0, 0, 0, 0.02); }
.filter-label {
  display: flex; align-items: center; gap: 4px;
  font-size: 10px; font-weight: 600; color: #9ca3af;
  text-transform: uppercase; letter-spacing: 0.07em;
  margin-bottom: 4px; pointer-events: none;
}
.filter-value-row {
  display: flex; align-items: center; gap: 4px;
}
.filter-select {
  flex: 1; border: none; background: transparent; outline: none;
  font-size: 13px; font-weight: 500; color: #111827;
  appearance: none; -webkit-appearance: none;
  cursor: pointer; font-family: inherit;
  padding: 0;
}
.filter-chevron { color: #c4c9d4; flex-shrink: 0; pointer-events: none; }
.filter-divider {
  width: 1px; background: rgba(0, 0, 0, 0.07);
  margin: 8px 0; flex-shrink: 0;
}
.filter-action-btn {
  display: flex; align-items: center; justify-content: center; gap: 6px;
  padding: 0 20px; border: none; cursor: pointer;
  font-size: 13px; font-weight: 600; font-family: inherit;
  flex-shrink: 0; white-space: nowrap;
  transition: background 0.15s ease, color 0.15s ease;
}
.filter-action-apply {
  background: #50c878; color: #fff;
}
.filter-action-apply:hover { background: #45b86e; }
.filter-action-reset {
  background: rgba(239, 68, 68, 0.08); color: #dc2626;
}
.filter-action-reset:hover { background: rgba(239, 68, 68, 0.14); }

.msg-tab-content { animation: tabFadeIn 0.18s ease; }
@keyframes tabFadeIn {
  from { opacity: 0; transform: translateY(4px); }
  to   { opacity: 1; transform: translateY(0); }
}

.msg-block { margin-bottom: 20px; }
.msg-block:last-child { margin-bottom: 0; }
.block-label {
  display: flex; align-items: center; gap: 7px;
  font-size: 11px; font-weight: 600; color: #9ca3af;
  text-transform: uppercase; letter-spacing: 0.08em; margin: 0 0 10px;
}
.block-label-hint {
  font-size: 10px; font-weight: 400; color: #c4c9d4;
  text-transform: none; letter-spacing: 0;
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
  display: flex; align-items: center; gap: 11px; padding: 11px 13px;
  background: #f9fafb; border: 1px solid rgba(0, 0, 0, 0.04);
  border-radius: 12px;
  transition: background 0.15s ease, border-color 0.15s ease;
}
.msg-item.clickable { cursor: pointer; }
.msg-item.clickable:hover {
  border-color: rgba(80, 200, 120, 0.25);
  background: rgba(80, 200, 120, 0.04);
}

.msg-icon {
  flex-shrink: 0; width: 32px; height: 32px; border-radius: 9px;
  display: flex; align-items: center; justify-content: center;
}
.msg-icon.workorder { background: rgba(80, 200, 120, 0.1); color: #50c878; }
.msg-icon.anom      { background: rgba(239, 68, 68, 0.08); color: #ef4444; }
.sev-high .msg-icon.anom   { background: rgba(239, 68, 68, 0.1); color: #ef4444; }
.sev-medium .msg-icon.anom { background: rgba(251, 191, 36, 0.08); color: #f59e0b; }
.sev-low .msg-icon.anom    { background: rgba(80, 200, 120, 0.08); color: #34d399; }

.msg-body { flex: 1; min-width: 0; }
.msg-title {
  font-size: 13px; font-weight: 600; color: #111827; margin: 0 0 3px;
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
}
.msg-sub { font-size: 11px; color: #9ca3af; margin: 0; }
.msg-detail { font-size: 11px; color: #6b7280; margin: 3px 0 0; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.msg-chevron { color: #d1d5db; flex-shrink: 0; }
.msg-tag { font-size: 10px; font-weight: 600; padding: 2px 8px; border-radius: 20px; flex-shrink: 0; }
.msg-tag.pending { background: rgba(80, 200, 120, 0.1); color: #16a34a; }
.msg-tag.tag-high   { background: rgba(239, 68, 68, 0.1); color: #dc2626; }
.msg-tag.tag-medium { background: rgba(251, 191, 36, 0.1); color: #d97706; }
.msg-tag.tag-low    { background: rgba(80, 200, 120, 0.1); color: #16a34a; }

/* 偏差高亮 */
.dev-high   { color: #dc2626; font-weight: 600; }
.dev-medium { color: #d97706; font-weight: 600; }
.dev-low    { color: #16a34a; font-weight: 600; }

/* ── 预警风险卡片 ── */
.risk-card {
  display: flex; align-items: center; gap: 10px; padding: 13px 14px;
  background: #f9fafb; border: 1px solid rgba(0, 0, 0, 0.05);
  border-radius: 13px; margin-bottom: 7px;
  transition: border-color 0.15s ease, background 0.15s ease;
}
.risk-card:last-child { margin-bottom: 0; }
.risk-card.risk-high   { border-left: 3px solid #ef4444; background: rgba(239,68,68,0.02); }
.risk-card.risk-medium { border-left: 3px solid #f59e0b; background: rgba(245,158,11,0.02); }
.risk-card.risk-low    { border-left: 3px solid #34d399; background: rgba(52,211,153,0.02); }
.risk-card.risk-normal { border-left: 3px solid #d1fae5; }

.risk-card-left { display: flex; align-items: flex-start; gap: 10px; flex: 1; min-width: 0; }
.risk-icon {
  flex-shrink: 0; width: 32px; height: 32px; border-radius: 9px;
  display: flex; align-items: center; justify-content: center; margin-top: 1px;
}
.risk-high .risk-icon   { background: rgba(239,68,68,0.1); color: #ef4444; }
.risk-medium .risk-icon { background: rgba(245,158,11,0.1); color: #f59e0b; }
.risk-low .risk-icon    { background: rgba(52,211,153,0.1); color: #34d399; }
.risk-normal .risk-icon { background: rgba(52,211,153,0.08); color: #34d399; }

.risk-info { flex: 1; min-width: 0; }
.risk-header { display: flex; align-items: center; gap: 7px; margin-bottom: 3px; }
.risk-name { font-size: 13px; font-weight: 600; color: #111827; }
.risk-mode-badge {
  font-size: 10px; font-weight: 500; padding: 1px 7px; border-radius: 10px;
  background: rgba(80,200,120,0.1); color: #16a34a;
}
.risk-desc { font-size: 12px; color: #374151; margin: 0 0 3px; }
.risk-meta { font-size: 11px; color: #9ca3af; margin: 0; }

.risk-level-badge {
  flex-shrink: 0; font-size: 10px; font-weight: 700; padding: 3px 10px;
  border-radius: 20px; align-self: center;
}
.rlv-high   { background: rgba(239,68,68,0.1); color: #dc2626; }
.rlv-medium { background: rgba(245,158,11,0.1); color: #d97706; }
.rlv-low    { background: rgba(52,211,153,0.1); color: #059669; }
.rlv-normal { background: rgba(52,211,153,0.08); color: #16a34a; }

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

/* 个人信息头部深色 */
:root[data-theme="dark"] .profile-username { color: rgba(255,255,255,0.9); }
:root[data-theme="dark"] .profile-email-hint { color: rgba(255,255,255,0.35); }
:root[data-theme="dark"] .profile-section-divider { background: rgba(255,255,255,0.06); }

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

/* 消息中心 深色 */
:root[data-theme="dark"] .msg-filter-bar { background: rgba(255,255,255,0.04); border-color: rgba(255,255,255,0.08); box-shadow: none; }
:root[data-theme="dark"] .filter-group:hover { background: rgba(255,255,255,0.04); }
:root[data-theme="dark"] .filter-label { color: rgba(255,255,255,0.3); }
:root[data-theme="dark"] .filter-select { color: rgba(255,255,255,0.85); }
:root[data-theme="dark"] .filter-chevron { color: rgba(255,255,255,0.2); }
:root[data-theme="dark"] .filter-divider { background: rgba(255,255,255,0.08); }
:root[data-theme="dark"] .filter-select option { background: #1a2420; color: #f3f4f6; }

:root[data-theme="dark"] .msg-capsule { background: rgba(255,255,255,0.06); }
:root[data-theme="dark"] .capsule-btn { color: rgba(255,255,255,0.4); }
:root[data-theme="dark"] .capsule-btn:hover { color: rgba(255,255,255,0.75); }
:root[data-theme="dark"] .capsule-btn.active { background: rgba(255,255,255,0.09); color: #f3f4f6; box-shadow: 0 1px 4px rgba(0,0,0,0.3), 0 0 0 1px rgba(255,255,255,0.07); }

:root[data-theme="dark"] .empty-state { background: rgba(255,255,255,0.03); border-color: rgba(255,255,255,0.04); }
:root[data-theme="dark"] .msg-item { background: rgba(255,255,255,0.03); border-color: rgba(255,255,255,0.04); }
:root[data-theme="dark"] .msg-item.clickable:hover { background: rgba(80,200,120,0.06); border-color: rgba(80,200,120,0.15); }
:root[data-theme="dark"] .msg-title { color: #f3f4f6; }
:root[data-theme="dark"] .block-label { color: rgba(255,255,255,0.35); }
:root[data-theme="dark"] .block-label-hint { color: rgba(255,255,255,0.2); }
:root[data-theme="dark"] .msg-chevron { color: rgba(255,255,255,0.15); }

:root[data-theme="dark"] .risk-card { background: rgba(255,255,255,0.03); border-color: rgba(255,255,255,0.04); }
:root[data-theme="dark"] .risk-card.risk-high   { background: rgba(239,68,68,0.04); }
:root[data-theme="dark"] .risk-card.risk-medium { background: rgba(245,158,11,0.04); }
:root[data-theme="dark"] .risk-card.risk-low    { background: rgba(52,211,153,0.03); }
:root[data-theme="dark"] .risk-name { color: rgba(255,255,255,0.9); }
:root[data-theme="dark"] .risk-desc { color: rgba(255,255,255,0.6); }
:root[data-theme="dark"] .risk-meta { color: rgba(255,255,255,0.3); }
:root[data-theme="dark"] .risk-mode-badge { background: rgba(80,200,120,0.12); color: #6ee7a0; }

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
