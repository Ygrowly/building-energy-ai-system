<template>
  <view class="page">
    <NavBar title="我的" bg-color="#0f3d2e" />

    <!-- 用户信息头 -->
    <view class="profile-header">
      <view class="avatar-wrap" @click="changeAvatar">
        <image v-if="avatarUrl" class="avatar-img" :src="avatarUrl" mode="aspectFill" />
        <view v-else class="avatar-fallback">
          <text>{{ avatarChar }}</text>
        </view>
        <view class="avatar-badge">
          <text class="badge-text">换</text>
        </view>
      </view>
      <view class="user-info">
        <text class="username">{{ user?.username }}</text>
        <view class="role-badge">
          <text>维修人员</text>
        </view>
      </view>
    </view>

    <!-- 菜单列表 -->
    <view class="menu-section">
      <view class="menu-item" @click="goTo('info')">
        <image class="menu-icon" src="/static/icons/user-outline.svg" mode="aspectFit" />
        <text class="menu-label">个人资料</text>
        <image class="menu-arrow" src="/static/icons/arrow-right.svg" mode="aspectFit" />
      </view>
      <view class="menu-divider" />
      <view class="menu-item" @click="goTo('security')">
        <image class="menu-icon" src="/static/icons/shield-lock.svg" mode="aspectFit" />
        <text class="menu-label">账号与安全</text>
        <image class="menu-arrow" src="/static/icons/arrow-right.svg" mode="aspectFit" />
      </view>
      <view class="menu-divider" />
      <view class="menu-item" @click="goTo('notification')">
        <image class="menu-icon" src="/static/icons/bell-outline.svg" mode="aspectFit" />
        <text class="menu-label">消息通知</text>
        <image class="menu-arrow" src="/static/icons/arrow-right.svg" mode="aspectFit" />
      </view>
      <view class="menu-divider" />
      <view class="menu-item" @click="goTo('about')">
        <image class="menu-icon" src="/static/icons/info-circle.svg" mode="aspectFit" />
        <text class="menu-label">关于</text>
        <image class="menu-arrow" src="/static/icons/arrow-right.svg" mode="aspectFit" />
      </view>
    </view>

    <!-- 退出登录 -->
    <view class="logout-section">
      <view class="logout-btn" @click="handleLogout">
        <image class="menu-icon" src="/static/icons/logout.svg" mode="aspectFit" />
        <text class="logout-text">退出登录</text>
      </view>
    </view>

    <TabBar :tabs="WORKER_TABS" current="profile" theme="worker" />
  </view>
</template>

<script setup lang="ts">
import NavBar from '../../../components/NavBar.vue'
import TabBar from '../../../components/TabBar.vue'
import { useAuthStore } from '../../../stores/auth'
import { useRouteGuard } from '../../../utils/route-guard'
import { WORKER_TABS } from '../../../constants/tabs'
import { WORKER_ROLES } from '../../../constants/roles'
import { ref, computed } from 'vue'
import { onShow } from '@dcloudio/uni-app'

useRouteGuard(WORKER_ROLES)

const authStore = useAuthStore()
const user = computed(() => authStore.user)

const avatarChar = computed(() => user.value?.username?.[0]?.toUpperCase() ?? '?')

// 头像：本地存储
const avatarUrl = ref('')

function loadAvatar() {
  const uid = user.value?.id ?? 'guest'
  avatarUrl.value = uni.getStorageSync(`avatar_${uid}`) || ''
}

onShow(() => { loadAvatar() })

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
        const ctx = canvas.getContext('2d')!
        ctx.drawImage(img, 0, 0, size, size)
        const dataUrl = canvas.toDataURL('image/jpeg', 0.8)
        saveAvatar(dataUrl)
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

const SUB_PAGES: Record<string, string> = {
  info: '/pages/worker/profile/info',
  security: '/pages/worker/profile/security',
  notification: '/pages/worker/profile/notification',
  about: '/pages/worker/profile/about',
}

function goTo(page: string) {
  uni.navigateTo({ url: SUB_PAGES[page] })
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
</script>

<style lang="scss" scoped>
.page { background: #f0f5f2; min-height: 100vh; }

.profile-header {
  display: flex;
  align-items: center;
  gap: 28rpx;
  padding: 40rpx 32rpx;
  background: #fff;
  margin-bottom: 24rpx;
}

.avatar-wrap {
  position: relative;
  width: 112rpx;
  height: 112rpx;
  flex-shrink: 0;
}

.avatar-img {
  width: 112rpx;
  height: 112rpx;
  border-radius: 56rpx;
}

.avatar-fallback {
  width: 112rpx;
  height: 112rpx;
  border-radius: 56rpx;
  background: linear-gradient(135deg, #00b96b, #38ef7d);
  display: flex;
  align-items: center;
  justify-content: center;

  text { font-size: 48rpx; color: #fff; font-weight: 700; }
}

.avatar-badge {
  position: absolute;
  right: -4rpx;
  bottom: -4rpx;
  width: 36rpx;
  height: 36rpx;
  border-radius: 18rpx;
  background: #00b96b;
  border: 3rpx solid #fff;
  display: flex;
  align-items: center;
  justify-content: center;
}

.badge-text {
  font-size: 18rpx;
  color: #fff;
  font-weight: 600;
}

.username {
  display: block;
  font-size: 36rpx;
  font-weight: 700;
  color: #1a1a2e;
  margin-bottom: 10rpx;
}

.role-badge {
  background: #e6f7f1;
  border-radius: 16rpx;
  padding: 6rpx 16rpx;
  display: inline-flex;

  text { font-size: 22rpx; color: #00b96b; font-weight: 500; }
}

.menu-section {
  background: #fff;
  border-radius: 16rpx;
  margin: 0 32rpx;
  overflow: hidden;
}

.menu-item {
  display: flex;
  align-items: center;
  gap: 20rpx;
  padding: 32rpx 28rpx;
}

.menu-icon {
  width: 40rpx;
  height: 40rpx;
}

.menu-label {
  flex: 1;
  font-size: 30rpx;
  color: #1a1a2e;
}

.menu-arrow {
  width: 32rpx;
  height: 32rpx;
}

.menu-divider {
  height: 1rpx;
  background: #f5f5f5;
  margin: 0 28rpx;
}

.logout-section {
  margin: 40rpx 32rpx;
}

.logout-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 12rpx;
  background: #fff;
  border-radius: 16rpx;
  padding: 28rpx 0;
}

.logout-text {
  font-size: 30rpx;
  color: #ff4d4f;
  font-weight: 600;
}
</style>
