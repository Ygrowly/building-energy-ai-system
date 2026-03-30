<template>
  <view class="page">
    <NavBar title="我的" bg-color="#0f3d2e" />

    <view class="profile-header">
      <view class="avatar">
        <text>{{ avatarChar }}</text>
      </view>
      <view class="user-info">
        <text class="username">{{ user?.username }}</text>
        <view class="role-badge">
          <text>维修人员</text>
        </view>
      </view>
    </view>

    <view class="menu-section">
      <view class="menu-item" @click="showChangePwd = true">
        <text class="menu-icon">🔑</text>
        <text class="menu-label">修改密码</text>
        <text class="menu-arrow">›</text>
      </view>
      <view class="menu-divider" />
      <view class="menu-item" @click="handleLogout">
        <text class="menu-icon">🚪</text>
        <text class="menu-label logout">退出登录</text>
        <text class="menu-arrow">›</text>
      </view>
    </view>

    <view class="app-info">
      <text>楼宇能耗管理 v1.0.0</text>
    </view>

    <!-- 修改密码弹窗 -->
    <view v-if="showChangePwd" class="modal-mask" @click.self="showChangePwd = false">
      <view class="modal-card">
        <text class="modal-title">修改密码</text>
        <input class="modal-input" v-model="oldPwd" placeholder="当前密码" password />
        <input class="modal-input" v-model="newPwd" placeholder="新密码（至少6位）" password />
        <input class="modal-input" v-model="confirmPwd" placeholder="确认新密码" password />
        <view class="modal-actions">
          <button class="modal-btn cancel" @click="showChangePwd = false">取消</button>
          <button class="modal-btn confirm worker" :loading="pwdLoading" @click="doChangePwd">确认</button>
        </view>
      </view>
    </view>

    <TabBar :tabs="WORKER_TABS" current="profile" theme="worker" />
  </view>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue'
import NavBar from '../../../components/NavBar.vue'
import TabBar from '../../../components/TabBar.vue'
import { useAuthStore } from '../../../stores/auth'
import { useRouteGuard } from '../../../utils/route-guard'
import { WORKER_TABS } from '../../../constants/tabs'
import { WORKER_ROLES } from '../../../constants/roles'
import { authApi } from '../../../api/auth'

useRouteGuard(WORKER_ROLES)

const authStore = useAuthStore()
const user = computed(() => authStore.user)

const avatarChar = computed(() => user.value?.username?.[0]?.toUpperCase() ?? '?')

const showChangePwd = ref(false)
const oldPwd = ref(''), newPwd = ref(''), confirmPwd = ref('')
const pwdLoading = ref(false)

function handleLogout() {
  uni.showModal({
    title: '退出登录',
    content: '确认退出当前账号？',
    confirmText: '退出',
    confirmColor: '#ff4d4f',
    success(res) { if (res.confirm) authStore.logout() },
  })
}

async function doChangePwd() {
  if (!oldPwd.value || !newPwd.value || !confirmPwd.value) {
    return uni.showToast({ title: '请填写完整', icon: 'none' })
  }
  if (newPwd.value.length < 6) return uni.showToast({ title: '新密码至少6位', icon: 'none' })
  if (newPwd.value !== confirmPwd.value) return uni.showToast({ title: '两次密码不一致', icon: 'none' })

  pwdLoading.value = true
  try {
    await authApi.changePassword(oldPwd.value, newPwd.value)
    uni.showToast({ title: '密码已修改', icon: 'success' })
    showChangePwd.value = false
    oldPwd.value = newPwd.value = confirmPwd.value = ''
  } catch { /* handled */ }
  finally { pwdLoading.value = false }
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

.avatar {
  width: 112rpx;
  height: 112rpx;
  border-radius: 56rpx;
  background: linear-gradient(135deg, #00b96b, #38ef7d);
  display: flex;
  align-items: center;
  justify-content: center;

  text { font-size: 48rpx; color: #fff; font-weight: 700; }
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

.menu-icon { font-size: 36rpx; }
.menu-label { flex: 1; font-size: 30rpx; color: #1a1a2e; &.logout { color: #ff4d4f; } }
.menu-arrow { font-size: 36rpx; color: #ccc; }
.menu-divider { height: 1rpx; background: #f5f5f5; margin: 0 28rpx; }

.app-info {
  text-align: center;
  padding: 48rpx;
  font-size: 24rpx;
  color: #ccc;
}

.modal-mask {
  position: fixed;
  inset: 0;
  background: rgba(0,0,0,0.5);
  display: flex;
  align-items: flex-end;
  z-index: 1000;
}

.modal-card {
  background: #fff;
  border-radius: 24rpx 24rpx 0 0;
  padding: 40rpx 32rpx calc(40rpx + env(safe-area-inset-bottom, 0px));
  width: 100%;
}

.modal-title {
  display: block;
  font-size: 34rpx;
  font-weight: 700;
  color: #1a1a2e;
  margin-bottom: 32rpx;
}

.modal-input {
  width: 100%;
  height: 88rpx;
  background: #f5f7fa;
  border-radius: 12rpx;
  padding: 0 24rpx;
  font-size: 28rpx;
  color: #1a1a2e;
  margin-bottom: 20rpx;
  box-sizing: border-box;
}

.modal-actions { display: flex; gap: 20rpx; margin-top: 12rpx; }

.modal-btn {
  flex: 1;
  height: 88rpx;
  border-radius: 12rpx;
  font-size: 28rpx;
  font-weight: 600;
  border: none;

  &.cancel { background: #f5f5f5; color: #666; }
  &.confirm { background: #3b6cf4; color: #fff; }
  &.confirm.worker { background: #00b96b; }
}
</style>
