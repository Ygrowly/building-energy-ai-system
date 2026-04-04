<template>
  <view class="page">
    <NavBar title="个人资料" bg-color="#0f3d2e" :show-back="true" />

    <view class="form-section">
      <view class="form-item">
        <text class="form-label">用户名</text>
        <text class="form-value readonly">{{ user?.username }}</text>
      </view>
      <view class="form-divider" />
      <view class="form-item">
        <text class="form-label">角色</text>
        <text class="form-value readonly">维修人员</text>
      </view>
      <view class="form-divider" />
      <view class="form-item">
        <text class="form-label">邮箱</text>
        <input class="form-input" v-model="email" placeholder="请输入邮箱" />
      </view>
      <view class="form-divider" />
      <view class="form-item">
        <text class="form-label">手机号</text>
        <input class="form-input" v-model="phone" placeholder="请输入手机号" type="number" />
      </view>
    </view>

    <view class="btn-wrap">
      <button class="save-btn" :loading="saving" @click="handleSave">保存</button>
    </view>
  </view>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import NavBar from '../../../components/NavBar.vue'
import { useAuthStore } from '../../../stores/auth'
import { useRouteGuard } from '../../../utils/route-guard'
import { WORKER_ROLES } from '../../../constants/roles'
import { authApi } from '../../../api/auth'

useRouteGuard(WORKER_ROLES)

const authStore = useAuthStore()
const user = computed(() => authStore.user)

const email = ref('')
const phone = ref('')
const saving = ref(false)

onMounted(() => {
  email.value = user.value?.email ?? ''
  phone.value = user.value?.phone ?? ''
})

async function handleSave() {
  saving.value = true
  try {
    const updated = await authApi.updateProfile({
      email: email.value || null,
      phone: phone.value || null,
    })
    authStore.user = updated
    uni.setStorageSync('user_info', JSON.stringify(updated))
    uni.showToast({ title: '保存成功', icon: 'success' })
  } catch { /* handled by request.ts */ }
  finally { saving.value = false }
}
</script>

<style lang="scss" scoped>
.page { background: #f0f5f2; min-height: 100vh; }

.form-section {
  background: #fff;
  border-radius: 16rpx;
  margin: 24rpx 32rpx 0;
  overflow: hidden;
}

.form-item {
  display: flex;
  align-items: center;
  padding: 32rpx 28rpx;
}

.form-label {
  width: 140rpx;
  font-size: 28rpx;
  color: #666;
  flex-shrink: 0;
}

.form-value {
  flex: 1;
  font-size: 28rpx;
  color: #1a1a2e;
  text-align: right;

  &.readonly { color: #999; }
}

.form-input {
  flex: 1;
  font-size: 28rpx;
  color: #1a1a2e;
  text-align: right;
}

.form-divider {
  height: 1rpx;
  background: #f5f5f5;
  margin: 0 28rpx;
}

.btn-wrap {
  padding: 48rpx 32rpx;
}

.save-btn {
  width: 100%;
  height: 88rpx;
  background: #00b96b;
  color: #fff;
  font-size: 30rpx;
  font-weight: 600;
  border-radius: 16rpx;
  border: none;
}
</style>
