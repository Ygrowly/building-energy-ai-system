<template>
  <view class="page theme-operator">
    <NavBar title="账号与安全" bg-color="#2f855a" :show-back="true" />

    <!-- 账户状态 -->
    <view class="section">
      <view class="section-title">账户状态</view>
      <view class="status-card">
        <view class="status-dot" :class="{ active: user?.is_active }" />
        <text class="status-text">{{ user?.is_active ? '正常' : '已停用' }}</text>
      </view>
    </view>

    <!-- 修改密码 -->
    <view class="section">
      <view class="section-title">修改密码</view>
      <view class="form-card">
        <input class="form-input" v-model="oldPwd" placeholder="当前密码" password />
        <view class="form-divider" />
        <input class="form-input" v-model="newPwd" placeholder="新密码（至少8位，包含字母和数字）" password />
        <view class="form-divider" />
        <input class="form-input" v-model="confirmPwd" placeholder="确认新密码" password />
      </view>
    </view>

    <view class="btn-wrap">
      <button class="save-btn" :loading="pwdLoading" @click="doChangePwd">确认修改</button>
    </view>
  </view>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue'
import NavBar from '../../../components/NavBar.vue'
import { useAuthStore } from '../../../stores/auth'
import { useRouteGuard } from '../../../utils/route-guard'
import { OPERATOR_ROLES } from '../../../constants/roles'
import { authApi } from '../../../api/auth'

useRouteGuard(OPERATOR_ROLES)

const authStore = useAuthStore()
const user = computed(() => authStore.user)

const oldPwd = ref('')
const newPwd = ref('')
const confirmPwd = ref('')
const pwdLoading = ref(false)

async function doChangePwd() {
  if (!oldPwd.value || !newPwd.value || !confirmPwd.value) {
    return uni.showToast({ title: '请填写完整', icon: 'none' })
  }
  if (newPwd.value.length < 8) {
    return uni.showToast({ title: '新密码至少8位', icon: 'none' })
  }
  if (newPwd.value !== confirmPwd.value) {
    return uni.showToast({ title: '两次密码不一致', icon: 'none' })
  }
  pwdLoading.value = true
  try {
    await authApi.changePassword(oldPwd.value, newPwd.value)
    uni.showToast({ title: '密码已修改', icon: 'success' })
    oldPwd.value = newPwd.value = confirmPwd.value = ''
    setTimeout(() => uni.navigateBack(), 1500)
  } catch { /* handled */ }
  finally { pwdLoading.value = false }
}
</script>

<style lang="scss" scoped>
.page { background: var(--operator-bg, #eef5ef); min-height: 100vh; }

.section {
  margin: 24rpx 32rpx 0;
}

.section-title {
  font-size: 26rpx;
  color: var(--operator-text-secondary, #5b6f62);
  margin-bottom: 16rpx;
  padding-left: 8rpx;
}

.status-card {
  background: var(--operator-card, #fff);
  border-radius: 20rpx;
  padding: 32rpx 28rpx;
  display: flex;
  align-items: center;
  gap: 16rpx;
  border: 1rpx solid var(--operator-border, rgba(203, 225, 208, 0.96));
  box-shadow: var(--operator-shadow, 0 12rpx 34rpx rgba(35, 75, 54, 0.1));
}

.status-dot {
  width: 16rpx;
  height: 16rpx;
  border-radius: 8rpx;
  background: var(--operator-text-muted, #8aa091);

  &.active { background: var(--primary, #2f855a); }
}

.status-text {
  font-size: 28rpx;
  color: var(--operator-text, #163022);
}

.form-card {
  background: var(--operator-card, #fff);
  border-radius: 20rpx;
  overflow: hidden;
  border: 1rpx solid var(--operator-border, rgba(203, 225, 208, 0.96));
  box-shadow: var(--operator-shadow, 0 12rpx 34rpx rgba(35, 75, 54, 0.1));
}

.form-input {
  width: 100%;
  height: 96rpx;
  padding: 0 28rpx;
  font-size: 28rpx;
  color: var(--operator-text, #163022);
  box-sizing: border-box;
}

.form-divider {
  height: 1rpx;
  background: var(--operator-border, rgba(203, 225, 208, 0.96));
  margin: 0 28rpx;
}

.btn-wrap {
  padding: 48rpx 32rpx;
}

.save-btn {
  width: 100%;
  height: 88rpx;
  background: var(--operator-btn, linear-gradient(135deg, #42bf72, #2f855a));
  color: #fff;
  font-size: 30rpx;
  font-weight: 600;
  border-radius: 20rpx;
  border: none;
}
</style>
