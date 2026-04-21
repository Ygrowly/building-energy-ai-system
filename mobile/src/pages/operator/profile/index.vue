<template>
  <view class="page theme-operator">
    <NavBar title="我的" bg-color="#2f855a">
      <template #right>
        <view class="refresh-btn" :class="{ spinning: dashboardLoading }" @click="refreshDashboard">
          <image class="refresh-icon" src="/static/icons/refresh.svg" mode="aspectFit" />
        </view>
      </template>
    </NavBar>

    <scroll-view scroll-y class="page-scroll">
      <view class="profile-card">
        <view class="profile-main">
          <view class="avatar-wrap" @click="changeAvatar">
            <image v-if="avatarUrl" class="avatar-img" :src="avatarUrl" mode="aspectFill" />
            <view v-else class="avatar-fallback">
              <text>{{ avatarChar }}</text>
            </view>
            <view class="avatar-badge">
              <text class="badge-text">换</text>
            </view>
          </view>

          <view class="profile-copy">
            <view class="profile-name-row">
              <text class="username">{{ user?.username || '未命名用户' }}</text>
              <view class="role-badge">
                <text>{{ roleText }}</text>
              </view>
            </view>
            <text class="profile-contact">{{ primaryContact }}</text>
            <text class="profile-note">负责工单审阅、派工协同与异常闭环</text>
          </view>

          <view class="profile-edit" @click="goTo('info')">
            <text>编辑</text>
          </view>
        </view>

        <view class="profile-chip-row">
          <view class="profile-chip dark">
            <text>{{ accountStatusText }}</text>
          </view>
          <view class="profile-chip">
            <text>{{ coverageText }}</text>
          </view>
          <view class="profile-chip">
            <text>{{ anomalySummaryText }}</text>
          </view>
        </view>
      </view>

      <view class="stats-card">
        <view v-for="stat in statCards" :key="stat.label" class="stat-item">
          <text class="stat-value">{{ formatCount(stat.value) }}</text>
          <text class="stat-label">{{ stat.label }}</text>
          <text class="stat-desc">{{ stat.desc }}</text>
        </view>
      </view>

      <view class="section-head">
        <text class="section-title">快捷入口</text>
        <text class="section-note">{{ syncText }}</text>
      </view>

      <view class="quick-grid">
        <view
          v-for="action in quickActions"
          :key="action.key"
          class="quick-card"
          @click="goAction(action.key)"
        >
          <view class="quick-icon-shell" :class="action.tone">
            <image class="quick-icon" :src="action.icon" mode="aspectFit" />
          </view>
          <view class="quick-copy">
            <view class="quick-title-row">
              <text class="quick-title">{{ action.title }}</text>
              <text v-if="action.badge" class="quick-badge">{{ action.badge }}</text>
            </view>
            <text class="quick-desc">{{ action.desc }}</text>
          </view>
          <image class="quick-arrow" src="/static/icons/arrow-right.svg" mode="aspectFit" />
        </view>
      </view>

      <view class="section-head">
        <text class="section-title">平台与账号</text>
        <text class="section-note">保持资料与平台信息同步</text>
      </view>

      <view class="detail-card">
        <view class="detail-row clickable" @click="goTo('info')">
          <view class="detail-copy">
            <text class="detail-label">联系方式</text>
            <text class="detail-hint">手机号 / 邮箱</text>
          </view>
          <view class="detail-meta">
            <text class="detail-value">{{ primaryContact }}</text>
            <image class="detail-arrow" src="/static/icons/arrow-right.svg" mode="aspectFit" />
          </view>
        </view>
        <view class="detail-divider" />
        <view class="detail-row">
          <view class="detail-copy">
            <text class="detail-label">管理范围</text>
            <text class="detail-hint">当前同步的园区运营视图</text>
          </view>
          <view class="detail-meta static">
            <text class="detail-value">{{ coverageText }}</text>
          </view>
        </view>
        <view class="detail-divider" />
        <view class="detail-row clickable" @click="goTo('about')">
          <view class="detail-copy">
            <text class="detail-label">关于平台</text>
            <text class="detail-hint">版本信息与使用说明</text>
          </view>
          <view class="detail-meta">
            <text class="detail-value">查看详情</text>
            <image class="detail-arrow" src="/static/icons/arrow-right.svg" mode="aspectFit" />
          </view>
        </view>
      </view>

      <view class="logout-wrap">
        <view class="logout-btn" @click="handleLogout">
          <image class="logout-icon" src="/static/icons/logout.svg" mode="aspectFit" />
          <text class="logout-text">退出登录</text>
        </view>
      </view>
    </scroll-view>

    <TabBar :tabs="OPERATOR_TABS" current="profile" theme="operator" />
  </view>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import { onShow } from '@dcloudio/uni-app'
import NavBar from '../../../components/NavBar.vue'
import TabBar from '../../../components/TabBar.vue'
import { dataApi, type OverviewResponse } from '../../../api/data'
import { incidentApi, type Incident } from '../../../api/incident'
import { workOrderApi, type DispatchHallEntry } from '../../../api/workorder'
import { useAuthStore } from '../../../stores/auth'
import { useRouteGuard } from '../../../utils/route-guard'
import { OPERATOR_TABS } from '../../../constants/tabs'
import { OPERATOR_ROLES } from '../../../constants/roles'
import { buildOperatorWorkorderMessageItems } from '../../../utils/operator-message'
import { getCache, setCache } from '../../../utils/cache'
import { getStoredAvatarUrl, setStoredAvatarUrl } from '../../../utils/avatar'

useRouteGuard(OPERATOR_ROLES)

const authStore = useAuthStore()
const user = computed(() => authStore.user)

const overview = ref<OverviewResponse | null>(null)
const incidents = ref<Incident[]>([])
const hallEntries = ref<DispatchHallEntry[]>([])
const dashboardLoading = ref(false)

const avatarUrl = ref('')
const avatarChar = computed(() => user.value?.username?.[0]?.toUpperCase() ?? '?')
const roleText = computed(() => {
  const roleMap: Record<string, string> = {
    admin: '系统管理员',
    manager: '运维经理',
  }
  return roleMap[user.value?.role ?? ''] ?? '运维人员'
})
const primaryContact = computed(() => user.value?.phone || user.value?.email || '未设置手机号或邮箱')
const accountStatusText = computed(() => (user.value?.is_active ? '账号正常' : '账号停用'))
const buildingCount = computed(() => overview.value?.buildings.length ?? 0)
const anomalyCount = computed(() => overview.value?.kpis.anomaly_count ?? 0)
const predictionCount = computed(() => overview.value?.kpis.prediction_warning_count ?? 0)
const coverageText = computed(() => (
  buildingCount.value > 0 ? `管理 ${buildingCount.value} 栋建筑` : '管理范围待同步'
))
const anomalySummaryText = computed(() => (
  anomalyCount.value > 0 ? `异常 ${formatCount(anomalyCount.value)} 条` : '当前无新增异常'
))
const syncText = computed(() => {
  if (dashboardLoading.value && !overview.value) return '数据同步中'
  return overview.value?.data_date ? `数据更新至 ${overview.value.data_date}` : '暂无同步数据'
})

const workorderItems = computed(() =>
  buildOperatorWorkorderMessageItems(incidents.value, hallEntries.value),
)
const pendingCount = computed(() => workorderItems.value.filter(item => (
  ['pending_review', 'pending_dispatch', 'hall_application', 'pending_close'].includes(item.category)
)).length)
const riskCount = computed(() => workorderItems.value.filter(item => (
  ['warning', 'overdue', 'waiting_support', 'takeover_recommendation'].includes(item.category)
)).length)
const reminderCount = computed(() => workorderItems.value.length + predictionCount.value)

const statCards = computed(() => [
  {
    label: '待处理',
    value: pendingCount.value,
    desc: '审批 / 派工 / 复核',
  },
  {
    label: '风险工单',
    value: riskCount.value,
    desc: '临期 / 超时 / 协同',
  },
  {
    label: '预测预警',
    value: predictionCount.value,
    desc: '模型识别的重点提醒',
  },
])

const quickActions = computed(() => [
  {
    key: 'info',
    title: '个人资料',
    desc: '维护头像、手机号与邮箱',
    icon: '/static/icons/user-outline.svg',
    tone: 'tone-green',
    badge: '',
  },
  {
    key: 'notification',
    title: '消息中心',
    desc: reminderCount.value > 0 ? `${formatCount(reminderCount.value)} 项提醒待查看` : '集中查看告警与动态',
    icon: '/static/icons/bell-outline.svg',
    tone: 'tone-mint',
    badge: reminderCount.value > 0 ? formatCount(reminderCount.value) : '',
  },
  {
    key: 'workorders',
    title: '工单审阅',
    desc: riskCount.value > 0 ? `${formatCount(riskCount.value)} 项风险待跟进` : '查看派工、协同与复核',
    icon: '/static/icons/tab-workorder.svg',
    tone: 'tone-sage',
    badge: riskCount.value > 0 ? formatCount(riskCount.value) : '',
  },
  {
    key: 'security',
    title: '账号安全',
    desc: '修改密码并检查账号状态',
    icon: '/static/icons/shield-lock.svg',
    tone: 'tone-olive',
    badge: '',
  },
])

const CACHE_KEYS = {
  overview: 'operator_profile_overview',
  incidents: 'operator_profile_incidents',
  hallEntries: 'operator_profile_hall_entries',
}

function formatCount(value: number) {
  return value > 99 ? '99+' : `${value}`
}

function restoreDashboardCache() {
  overview.value = getCache<OverviewResponse>(CACHE_KEYS.overview) || overview.value
  incidents.value = getCache<Incident[]>(CACHE_KEYS.incidents) || incidents.value
  hallEntries.value = getCache<DispatchHallEntry[]>(CACHE_KEYS.hallEntries) || hallEntries.value
}

function loadAvatar() {
  avatarUrl.value = getStoredAvatarUrl(user.value?.id)
}

async function loadDashboard(showFeedback = false) {
  dashboardLoading.value = true
  let successCount = 0

  try {
    const [overviewRes, incidentRes, hallRes] = await Promise.allSettled([
      dataApi.overview(),
      incidentApi.list({
        workflow_status: 'pending_review,pending_dispatch,dispatched,completed,false_alarm,escalated',
        page: 1,
        page_size: 80,
      }),
      workOrderApi.listDispatchHallEntries({
        status: 'open',
        entry_type: 'support_request,takeover_candidate',
        include_applications: true,
        page: 1,
        page_size: 50,
      }),
    ])

    if (overviewRes.status === 'fulfilled') {
      overview.value = overviewRes.value
      setCache(CACHE_KEYS.overview, overviewRes.value)
      successCount += 1
    }

    if (incidentRes.status === 'fulfilled') {
      incidents.value = incidentRes.value.incidents
      setCache(CACHE_KEYS.incidents, incidentRes.value.incidents)
      successCount += 1
    }

    if (hallRes.status === 'fulfilled') {
      hallEntries.value = hallRes.value.hall_entries
      setCache(CACHE_KEYS.hallEntries, hallRes.value.hall_entries)
      successCount += 1
    }

    if (showFeedback) {
      uni.showToast({
        title: successCount > 0 ? '已刷新' : '刷新失败',
        icon: successCount > 0 ? 'success' : 'none',
      })
    }
  } finally {
    dashboardLoading.value = false
  }
}

function refreshDashboard() {
  if (dashboardLoading.value) return
  void loadDashboard(true)
}

function changeAvatar() {
  uni.chooseImage({
    count: 1,
    sizeType: ['compressed'],
    sourceType: ['album', 'camera'],
    success(res) {
      const tempPath = res.tempFilePaths[0]
      // #ifdef H5
      const canvas = document.createElement('canvas')
      const img = new Image()
      img.onload = () => {
        const size = 200
        canvas.width = size
        canvas.height = size
        const ctx = canvas.getContext('2d')
        if (!ctx) return
        ctx.drawImage(img, 0, 0, size, size)
        saveAvatar(canvas.toDataURL('image/jpeg', 0.82))
      }
      img.src = tempPath
      // #endif
      // #ifndef H5
      saveAvatar(tempPath)
      // #endif
    },
  })
}

function saveAvatar(url: string) {
  setStoredAvatarUrl(user.value?.id, url)
  avatarUrl.value = url
}

const SUB_PAGES = {
  info: '/pages/operator/profile/info',
  security: '/pages/operator/profile/security',
  notification: '/pages/operator/profile/notification',
  about: '/pages/operator/profile/about',
} as const

type SubPageKey = keyof typeof SUB_PAGES
type ActionKey = SubPageKey | 'workorders'

function goTo(page: SubPageKey) {
  uni.navigateTo({ url: SUB_PAGES[page] })
}

function goAction(action: ActionKey) {
  if (action === 'workorders') {
    uni.reLaunch({ url: '/pages/operator/workorders/index' })
    return
  }
  goTo(action)
}

function handleLogout() {
  uni.showModal({
    title: '退出登录',
    content: '确认退出当前账号？',
    confirmText: '退出',
    confirmColor: '#ff4d4f',
    success(res) {
      if (res.confirm) authStore.logout()
    },
  })
}

onShow(() => {
  loadAvatar()
  restoreDashboardCache()
  void loadDashboard()
})
</script>

<style lang="scss" scoped>
.page {
  min-height: 100vh;
  background:
    radial-gradient(circle at top, rgba(34, 197, 94, 0.12), transparent 34%),
    linear-gradient(180deg, #f5f7fa 0%, #eef4f0 100%);
}

.page-scroll {
  height: calc(100vh - 132rpx);
  padding: 24rpx 0 calc(176rpx + env(safe-area-inset-bottom, 0px));
  box-sizing: border-box;
}

.refresh-btn {
  width: 56rpx;
  height: 56rpx;
  border-radius: 28rpx;
  background: rgba(34, 197, 94, 0.1);
  border: 1rpx solid rgba(74, 222, 128, 0.2);
  display: flex;
  align-items: center;
  justify-content: center;

  &.spinning .refresh-icon {
    transform: rotate(180deg);
  }
}

.refresh-icon {
  width: 30rpx;
  height: 30rpx;
  transition: transform 0.4s ease;
}

.profile-card,
.stats-card,
.quick-card,
.detail-card,
.logout-btn {
  background: rgba(255, 255, 255, 0.97);
  box-shadow: 0 18rpx 44rpx rgba(22, 34, 78, 0.08);
}

.profile-card {
  margin: 0 24rpx;
  padding: 28rpx;
  border-radius: 30rpx;
}

.profile-main {
  display: flex;
  align-items: center;
}

.avatar-wrap {
  position: relative;
  width: 116rpx;
  height: 116rpx;
  flex-shrink: 0;
}

.avatar-img,
.avatar-fallback {
  width: 116rpx;
  height: 116rpx;
  border-radius: 58rpx;
}

.avatar-fallback {
  display: flex;
  align-items: center;
  justify-content: center;
  background: linear-gradient(135deg, #22c55e, #16a34a);

  text {
    color: #fff;
    font-size: 50rpx;
    font-weight: 700;
  }
}

.avatar-badge {
  position: absolute;
  right: -2rpx;
  bottom: -2rpx;
  min-width: 40rpx;
  height: 40rpx;
  padding: 0 10rpx;
  border-radius: 20rpx;
  border: 4rpx solid #fff;
  background: #3b6cf4;
  display: flex;
  align-items: center;
  justify-content: center;
}

.badge-text {
  font-size: 18rpx;
  color: #fff;
  font-weight: 600;
}

.profile-copy {
  flex: 1;
  min-width: 0;
  margin-left: 22rpx;
}

.profile-name-row {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 12rpx;
}

.username {
  font-size: 38rpx;
  font-weight: 700;
  color: #16224e;
}

.role-badge {
  padding: 8rpx 18rpx;
  border-radius: 999rpx;
  background: #f0fdf4;

  text {
    font-size: 22rpx;
    color: #16a34a;
    font-weight: 600;
  }
}

.profile-contact,
.profile-note {
  display: block;
}

.profile-contact {
  margin-top: 12rpx;
  font-size: 24rpx;
  color: #59688e;
}

.profile-note {
  margin-top: 8rpx;
  font-size: 22rpx;
  color: #8a96b2;
}

.profile-edit {
  flex-shrink: 0;
  padding: 14rpx 18rpx;
  border-radius: 22rpx;
  background: #f0fdf4;

  text {
    font-size: 22rpx;
    color: #16a34a;
    font-weight: 600;
  }
}

.profile-chip-row {
  display: flex;
  flex-wrap: wrap;
  gap: 14rpx;
  margin-top: 26rpx;
}

.profile-chip {
  padding: 10rpx 18rpx;
  border-radius: 999rpx;
  background: #f4f7fd;

  text {
    font-size: 22rpx;
    color: #5a6789;
  }

  &.dark {
    background: linear-gradient(135deg, #22c55e, #16a34a);

    text {
      color: #fff;
    }
  }
}

.stats-card {
  display: flex;
  margin: 24rpx;
  border-radius: 30rpx;
  overflow: hidden;
}

.stat-item {
  flex: 1;
  padding: 28rpx 20rpx 24rpx;
  text-align: center;
  position: relative;

  & + .stat-item::before {
    content: '';
    position: absolute;
    left: 0;
    top: 28rpx;
    bottom: 28rpx;
    width: 1rpx;
    background: rgba(22, 34, 78, 0.08);
  }
}

.stat-value,
.stat-label,
.stat-desc {
  display: block;
}

.stat-value {
  font-size: 42rpx;
  line-height: 1.1;
  font-weight: 700;
  color: #166534;
}

.stat-label {
  margin-top: 12rpx;
  font-size: 24rpx;
  color: #445272;
  font-weight: 600;
}

.stat-desc {
  margin-top: 8rpx;
  font-size: 20rpx;
  line-height: 1.5;
  color: #92a0bc;
}

.section-head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  margin: 20rpx 24rpx 20rpx ;
}

.section-title {
  font-size: 28rpx;
  font-weight: 700;
  color: #16224e;
}

.section-note {
  font-size: 22rpx;
  color: #8d9ab4;
}

.quick-grid {
  display: flex;
  flex-wrap: wrap;
  gap: 18rpx;
  margin: 0 24rpx;
}

.quick-card {
  width: calc(50% - 9rpx);
  min-height: 194rpx;
  padding: 22rpx;
  border-radius: 28rpx;
  box-sizing: border-box;
  position: relative;
}

.quick-icon-shell {
  width: 72rpx;
  height: 72rpx;
  border-radius: 22rpx;
  display: flex;
  align-items: center;
  justify-content: center;

  &.tone-green {
    background: linear-gradient(135deg, rgba(34, 197, 94, 0.18), rgba(134, 239, 172, 0.32));
  }

  &.tone-mint {
    background: linear-gradient(135deg, rgba(16, 185, 129, 0.18), rgba(167, 243, 208, 0.34));
  }

  &.tone-sage {
    background: linear-gradient(135deg, rgba(132, 204, 22, 0.18), rgba(217, 249, 157, 0.34));
  }

  &.tone-olive {
    background: linear-gradient(135deg, rgba(101, 163, 13, 0.18), rgba(190, 242, 100, 0.3));
  }
}

.quick-icon {
  width: 34rpx;
  height: 34rpx;
}

.quick-copy {
  margin-top: 18rpx;
}

.quick-title-row {
  display: flex;
  align-items: center;
  gap: 10rpx;
}

.quick-title {
  flex: 1;
  font-size: 28rpx;
  color: #16224e;
  font-weight: 700;
}

.quick-badge {
  min-width: 34rpx;
  padding: 4rpx 10rpx;
  border-radius: 999rpx;
  background: #f0fdf4;
  font-size: 20rpx;
  color: #16a34a;
  font-weight: 600;
  text-align: center;
}

.quick-desc {
  display: block;
  margin-top: 12rpx;
  padding-right: 36rpx;
  font-size: 22rpx;
  line-height: 1.6;
  color: #8b97b2;
}

.quick-arrow {
  position: absolute;
  right: 22rpx;
  bottom: 22rpx;
  width: 28rpx;
  height: 28rpx;
  opacity: 0.45;
}

.detail-card {
  margin: 0 24rpx;
  padding: 0 24rpx;
  border-radius: 28rpx;
}

.detail-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 18rpx;
  padding: 26rpx 0;

  &.clickable:active {
    opacity: 0.92;
  }
}

.detail-divider {
  height: 1rpx;
  background: rgba(22, 34, 78, 0.08);
}

.detail-copy,
.detail-meta {
  display: flex;
  flex-direction: column;
}

.detail-copy {
  min-width: 0;
}

.detail-label {
  font-size: 26rpx;
  color: #16224e;
  font-weight: 600;
}

.detail-hint {
  margin-top: 8rpx;
  font-size: 22rpx;
  color: #8b97b2;
}

.detail-meta {
  align-items: flex-end;
  gap: 8rpx;
}

.detail-meta.static {
  justify-content: center;
}

.detail-value {
  font-size: 24rpx;
  line-height: 1.5;
  color: #59688e;
  text-align: right;
}

.detail-arrow {
  width: 24rpx;
  height: 24rpx;
  opacity: 0.45;
}

.logout-wrap {
  margin: 30rpx 24rpx 0;
}

.logout-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 16rpx;
  height: 96rpx;
  border-radius: 28rpx;
  border: 1rpx solid rgba(255, 77, 79, 0.18);
  background: rgba(255, 255, 255, 0.98);
}

.logout-icon {
  width: 36rpx;
  height: 36rpx;
}

.logout-text {
  font-size: 30rpx;
  color: #ff4d4f;
  font-weight: 600;
}

.theme-operator.page {
  background:
    radial-gradient(circle at top, rgba(66, 191, 114, 0.18), transparent 34%),
    linear-gradient(180deg, var(--operator-bg-soft, #f7fbf7) 0%, var(--operator-bg, #eef5ef) 100%);
}

.theme-operator .refresh-btn {
  background: rgba(66, 191, 114, 0.12);
  border: 1rpx solid rgba(66, 191, 114, 0.18);
}

.theme-operator .profile-card,
.theme-operator .stats-card,
.theme-operator .quick-card,
.theme-operator .detail-card,
.theme-operator .logout-btn {
  background: var(--operator-card, #ffffff);
  border: 1rpx solid var(--operator-border, rgba(203, 225, 208, 0.96));
  box-shadow: var(--operator-shadow, 0 12rpx 34rpx rgba(35, 75, 54, 0.1));
}

.theme-operator .profile-card {
  background:
    linear-gradient(135deg, rgba(255, 255, 255, 0.98), rgba(244, 251, 245, 0.96));
}

.theme-operator .avatar-badge,
.theme-operator .profile-chip.dark {
  background: var(--operator-btn, linear-gradient(135deg, #42bf72, #2f855a));
}

.theme-operator .username,
.theme-operator .section-title,
.theme-operator .quick-title,
.theme-operator .detail-label {
  color: var(--operator-text, #163022);
}

.theme-operator .profile-contact,
.theme-operator .detail-value,
.theme-operator .detail-hint,
.theme-operator .quick-desc,
.theme-operator .section-note,
.theme-operator .profile-note {
  color: var(--operator-text-secondary, #5b6f62);
}

.theme-operator .role-badge,
.theme-operator .profile-edit,
.theme-operator .profile-chip,
.theme-operator .quick-badge {
  background: var(--operator-chip-bg, #ebf8ef);
}

.theme-operator .role-badge text,
.theme-operator .profile-edit text,
.theme-operator .quick-badge,
.theme-operator .stat-value {
  color: var(--primary, #2f855a);
}

.theme-operator .profile-chip text,
.theme-operator .stat-label {
  color: var(--operator-text, #163022);
}

.theme-operator .stat-desc {
  color: var(--operator-text-muted, #8aa091);
}

.theme-operator .stat-item + .stat-item::before,
.theme-operator .detail-divider {
  background: var(--operator-border, rgba(203, 225, 208, 0.96));
}

.theme-operator .quick-arrow,
.theme-operator .detail-arrow {
  opacity: 0.32;
}
</style>
