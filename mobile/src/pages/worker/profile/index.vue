<template>
  <view class="page">
    <NavBar title="我的" bg-color="#E4EDB8" text-color="#5f7137" />

    <scroll-view scroll-y class="page-scroll">
      <view class="hero-card">
        <view class="hero-top">
          <view class="avatar-wrap" @click="changeAvatar">
            <image v-if="avatarUrl" class="avatar-img" :src="avatarUrl" mode="aspectFill" />
            <view v-else class="avatar-fallback">
              <text>{{ avatarChar }}</text>
            </view>
            <view class="avatar-tag">换</view>
          </view>

          <view class="hero-user">
            <text class="user-name">{{ user?.username || '维修人员' }}</text>
            <text class="user-role">{{ jobTitleText }}</text>
            <text class="user-contact">{{ user?.phone || user?.email || '暂未填写联系方式' }}</text>
          </view>
        </view>

        <view class="hero-stats">
          <view class="stat-item">
            <text class="stat-num">{{ stats.todayCount }}</text>
            <text class="stat-label">今日工单</text>
          </view>
          <view class="stat-item">
            <text class="stat-num">{{ stats.inProgress }}</text>
            <text class="stat-label">进行中</text>
          </view>
          <view class="stat-item">
            <text class="stat-num">{{ stats.completedCount }}</text>
            <text class="stat-label">已完成</text>
          </view>
        </view>
      </view>

      <view class="info-card">
        <view class="info-row">
          <text class="info-label">账号角色</text>
          <text class="info-value">维修端账号</text>
        </view>
        <view class="info-row">
          <text class="info-label">所属班组</text>
          <text class="info-value">{{ teamName }}</text>
        </view>
        <view class="info-row">
          <text class="info-label">当前值班</text>
          <text class="info-value">{{ shiftLabel }}</text>
        </view>
        <view class="info-row">
          <text class="info-label">派工状态</text>
          <text class="info-value">{{ dispatchStatusText }}</text>
        </view>
        <view class="info-row">
          <text class="info-label">消息通知</text>
          <text class="info-value">{{ notificationText }}</text>
        </view>
        <view class="info-row">
          <text class="info-label">账号状态</text>
          <text class="info-value">{{ user?.is_active ? '正常使用中' : '已停用' }}</text>
        </view>
      </view>

      <view v-if="workerProfile" class="profile-card">
        <view class="card-head">
          <text class="card-title">派工画像</text>
          <text class="card-subtitle">调度推荐会综合参考技能、班组和值班状态</text>
        </view>

        <view class="metric-grid">
          <view class="metric-pill">
            <text class="metric-value">{{ workerProfile.max_active_orders }}</text>
            <text class="metric-label">负载上限</text>
          </view>
          <view class="metric-pill">
            <text class="metric-value">{{ workerProfile.skills?.length || 0 }}</text>
            <text class="metric-label">技能数</text>
          </view>
          <view class="metric-pill">
            <text class="metric-value">{{ workerProfile.service_buildings?.length || 0 }}</text>
            <text class="metric-label">覆盖楼宇</text>
          </view>
        </view>

        <view class="chip-section">
          <text class="section-label">技能标签</text>
          <view class="chip-row">
            <text
              v-for="skill in workerProfile.skills"
              :key="skill.code"
              class="skill-chip"
              :class="{ primary: skill.is_primary }"
            >
              {{ skill.name }}{{ skill.is_primary ? ' · 主' : '' }}
            </text>
            <text v-if="!workerProfile.skills?.length" class="empty-chip">暂未配置技能标签</text>
          </view>
        </view>

        <view class="chip-section">
          <text class="section-label">负责楼宇</text>
          <view class="chip-row">
            <text
              v-for="building in workerProfile.service_buildings"
              :key="building"
              class="building-chip"
            >{{ building }}</text>
            <text v-if="!workerProfile.service_buildings?.length" class="empty-chip">当前为跨楼宇支援模式</text>
          </view>
        </view>
      </view>

      <view class="menu-grid">
        <view class="menu-card" @click="goTo('info')">
          <view class="menu-icon coral">资</view>
          <text class="menu-title">个人资料</text>
          <text class="menu-desc">查看和维护基础信息</text>
        </view>
        <view class="menu-card" @click="goTo('dispatchProfile')">
          <view class="menu-icon olive">派</view>
          <text class="menu-title">我的派工画像</text>
          <text class="menu-desc">确认技能范围与当前接单状态</text>
        </view>
        <view class="menu-card" @click="goTo('security')">
          <view class="menu-icon blue">安</view>
          <text class="menu-title">账号安全</text>
          <text class="menu-desc">修改密码与安全设置</text>
        </view>
        <view class="menu-card" @click="goTo('notification')">
          <view class="menu-icon green">消</view>
          <text class="menu-title">消息通知</text>
          <text class="menu-desc">管理工单与告警提醒</text>
        </view>
        <view class="menu-card" @click="goTo('about')">
          <view class="menu-icon orange">关</view>
          <text class="menu-title">关于应用</text>
          <text class="menu-desc">查看版本与使用说明</text>
        </view>
      </view>

      <view class="logout-btn" @click="handleLogout">
        <text>退出登录</text>
      </view>
    </scroll-view>

    <TabBar :tabs="WORKER_TABS" current="profile" theme="worker" />
  </view>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { onShow } from '@dcloudio/uni-app'
import NavBar from '../../../components/NavBar.vue'
import TabBar from '../../../components/TabBar.vue'
import { useAuthStore } from '../../../stores/auth'
import { useRouteGuard } from '../../../utils/route-guard'
import { WORKER_TABS } from '../../../constants/tabs'
import { WORKER_ROLES } from '../../../constants/roles'
import { incidentApi, type Incident } from '../../../api/incident'
import { getWorkerDashboardStats } from '../../../utils/worker-ui'

useRouteGuard(WORKER_ROLES)

const authStore = useAuthStore()
const user = computed(() => authStore.user)
const workerProfile = computed(() => user.value?.worker_profile ?? null)
const avatarChar = computed(() => user.value?.username?.[0]?.toUpperCase() ?? '?')
const avatarUrl = ref('')
const incidents = ref<Incident[]>([])

const stats = computed(() => getWorkerDashboardStats(incidents.value))
const teamName = computed(() => workerProfile.value?.team?.name || '综合运维班')
const shiftLabel = computed(() => {
  const map: Record<string, string> = {
    on_duty: '值班中',
    standby: '待命',
    busy: '忙碌',
    off_duty: '离岗',
  }
  return map[workerProfile.value?.shift_status || ''] || '值班中'
})
const jobTitleText = computed(() => workerProfile.value?.job_title || '维修服务工程师')
const dispatchStatusText = computed(() => {
  if (!workerProfile.value) return '未配置'
  return workerProfile.value.dispatch_enabled ? '可接派工' : '暂停接单'
})
const notificationText = computed(() => '站内通知已开启')

const SUB_PAGES: Record<string, string> = {
  info: '/pages/worker/profile/info',
  dispatchProfile: '/pages/worker/profile/dispatch-profile',
  security: '/pages/worker/profile/security',
  notification: '/pages/worker/profile/notification',
  about: '/pages/worker/profile/about',
}

function loadAvatar() {
  const uid = user.value?.id ?? 'guest'
  avatarUrl.value = uni.getStorageSync(`avatar_${uid}`) || ''
}

async function loadStats() {
  try {
    const res = await incidentApi.list({
      workflow_status: 'dispatched,completed,closed,false_alarm,escalated',
      page: 1,
      page_size: 40,
    })
    incidents.value = res.incidents
  } catch {
    incidents.value = []
  }
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
        canvas.width = 200
        canvas.height = 200
        const ctx = canvas.getContext('2d')
        if (!ctx) return
        ctx.drawImage(img, 0, 0, 200, 200)
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
  const uid = user.value?.id ?? 'guest'
  uni.setStorageSync(`avatar_${uid}`, url)
  avatarUrl.value = url
}

function goTo(page: string) {
  uni.navigateTo({ url: SUB_PAGES[page] })
}

function handleLogout() {
  uni.showModal({
    title: '退出登录',
    content: '确认退出当前账号？',
    confirmText: '退出',
    confirmColor: '#7d9151',
    success(res) {
      if (res.confirm) authStore.logout()
    },
  })
}

onMounted(loadStats)
onShow(() => {
  loadAvatar()
})
</script>

<style lang="scss" scoped>
.page {
  min-height: 100vh;
  background:
    radial-gradient(circle at top, rgba(228, 237, 184, 0.72), transparent 38%),
    linear-gradient(180deg, #f8faef 0%, #fffdfb 100%);
}

.page-scroll {
  height: calc(100vh - 132rpx);
  padding: 24rpx 24rpx calc(168rpx + env(safe-area-inset-bottom, 0px));
  box-sizing: border-box;
}

.hero-card,
.info-card,
.profile-card,
.menu-card,
.logout-btn {
  background: rgba(255, 255, 255, 0.97);
  border-radius: 30rpx;
  box-shadow: 0 14rpx 36rpx rgba(181, 196, 118, 0.08);
}

.hero-card {
  padding: 26rpx;
}

.hero-top {
  display: flex;
  align-items: center;
  gap: 22rpx;
}

.avatar-wrap {
  position: relative;
  width: 120rpx;
  height: 120rpx;
  flex-shrink: 0;
}

.avatar-img,
.avatar-fallback {
  width: 120rpx;
  height: 120rpx;
  border-radius: 50%;
}

.avatar-fallback {
  background: linear-gradient(135deg, #d4e29f, #b5c875);
  display: flex;
  align-items: center;
  justify-content: center;

  text {
    color: #fff;
    font-size: 50rpx;
    font-weight: 700;
  }
}

.avatar-tag {
  position: absolute;
  right: -2rpx;
  bottom: -2rpx;
  min-width: 40rpx;
  height: 40rpx;
  padding: 0 10rpx;
  border-radius: 20rpx;
  background: #fff;
  color: #728548;
  font-size: 20rpx;
  display: flex;
  align-items: center;
  justify-content: center;
  box-shadow: 0 6rpx 18rpx rgba(181, 196, 118, 0.18);
}

.hero-user {
  flex: 1;
}

.user-name {
  display: block;
  font-size: 40rpx;
  color: #312925;
  font-weight: 700;
}

.user-role,
.user-contact {
  display: block;
  margin-top: 8rpx;
  font-size: 24rpx;
  color: #8e817b;
}

.hero-stats {
  margin-top: 26rpx;
  padding: 22rpx 18rpx;
  border-radius: 24rpx;
  background: linear-gradient(180deg, #fbfcf6 0%, #f4f8e6 100%);
  display: grid;
  grid-template-columns: repeat(3, 1fr);
}

.stat-item {
  display: flex;
  flex-direction: column;
  align-items: center;
}

.stat-num {
  font-size: 44rpx;
  color: #2d2623;
  font-weight: 700;
}

.stat-label {
  margin-top: 10rpx;
  font-size: 22rpx;
  color: #95867f;
}

.info-card {
  margin-top: 22rpx;
  padding: 8rpx 24rpx;
}

.profile-card {
  margin-top: 22rpx;
  padding: 24rpx;
}

.card-head {
  display: flex;
  flex-direction: column;
  gap: 8rpx;
}

.card-title {
  font-size: 30rpx;
  font-weight: 700;
  color: #302824;
}

.card-subtitle {
  font-size: 22rpx;
  color: #94857e;
}

.metric-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 14rpx;
  margin-top: 20rpx;
}

.metric-pill {
  border-radius: 24rpx;
  padding: 18rpx 12rpx;
  background: linear-gradient(180deg, #fcfdf7 0%, #f4f8e6 100%);
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8rpx;
}

.metric-value {
  font-size: 34rpx;
  font-weight: 700;
  color: #728548;
}

.metric-label {
  font-size: 22rpx;
  color: #8f827c;
}

.chip-section {
  margin-top: 22rpx;
}

.section-label {
  display: block;
  margin-bottom: 12rpx;
  font-size: 24rpx;
  color: #7d7069;
}

.chip-row {
  display: flex;
  flex-wrap: wrap;
  gap: 12rpx;
}

.skill-chip,
.building-chip,
.empty-chip {
  padding: 10rpx 16rpx;
  border-radius: 999rpx;
  font-size: 22rpx;
}

.skill-chip {
  background: #f4f8e6;
  color: #73854a;
}

.skill-chip.primary {
  background: linear-gradient(135deg, #d6e29f, #b5c875);
  color: #fff;
}

.building-chip {
  background: #eff8f3;
  color: #2f8f61;
}

.empty-chip {
  background: #f4f4f4;
  color: #999;
}

.info-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16rpx;
  padding: 22rpx 0;
  border-bottom: 1rpx solid #eef2df;
}

.info-row:last-child {
  border-bottom: none;
}

.info-label {
  font-size: 26rpx;
  color: #8f827c;
}

.info-value {
  font-size: 26rpx;
  color: #332b27;
  text-align: right;
}

.menu-grid {
  margin-top: 22rpx;
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 18rpx;
}

.menu-card {
  padding: 24rpx;
  min-height: 196rpx;
}

.menu-icon {
  width: 72rpx;
  height: 72rpx;
  border-radius: 24rpx;
  display: flex;
  align-items: center;
  justify-content: center;
  color: #fff;
  font-size: 30rpx;
  font-weight: 700;
}

.menu-icon.coral {
  background: linear-gradient(135deg, #d6e29f, #b5c875);
}

.menu-icon.olive {
  background: linear-gradient(135deg, #aabf68, #7d9151);
}

.menu-icon.blue {
  background: linear-gradient(135deg, #81bcff, #5e8cff);
}

.menu-icon.green {
  background: linear-gradient(135deg, #75d8ad, #43b983);
}

.menu-icon.orange {
  background: linear-gradient(135deg, #e4edb8, #c2d58a);
}

.menu-title {
  display: block;
  margin-top: 20rpx;
  font-size: 30rpx;
  color: #302824;
  font-weight: 700;
}

.menu-desc {
  display: block;
  margin-top: 10rpx;
  font-size: 22rpx;
  line-height: 1.6;
  color: #94857e;
}

.logout-btn {
  margin-top: 24rpx;
  height: 92rpx;
  display: flex;
  align-items: center;
  justify-content: center;

  text {
    color: #73854a;
    font-size: 30rpx;
    font-weight: 600;
  }
}
</style>
