<template>
  <view class="page theme-operator">
    <NavBar title="个人资料" bg-color="#2f855a" :show-back="true" />

    <view class="form-section">
      <!-- 用户名（只读） -->
      <view class="form-item">
        <text class="form-label">用户名</text>
        <text class="form-value readonly">{{ user?.username }}</text>
      </view>
      <view class="form-divider" />

      <!-- 角色（只读） -->
      <view class="form-item">
        <text class="form-label">角色</text>
        <text class="form-value readonly">{{ roleText }}</text>
      </view>
      <view class="form-divider" />

      <!-- 邮箱 -->
      <view class="form-item">
        <text class="form-label">邮箱</text>
        <input class="form-input" v-model="email" placeholder="请输入邮箱" />
      </view>
      <view class="form-divider" />

      <!-- 手机号 -->
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
import { OPERATOR_ROLES } from '../../../constants/roles'
import { authApi } from '../../../api/auth'

useRouteGuard(OPERATOR_ROLES)

const authStore = useAuthStore()
const user = computed(() => authStore.user)

const roleText = computed(() => {
  const m: Record<string, string> = { admin: '系统管理员', manager: '运维经理' }
  return m[user.value?.role ?? ''] ?? '运维人员'
})

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
.page { background: var(--operator-bg, #eef5ef); min-height: 100vh; }

.form-section {
  background: var(--operator-card, #fff);
  border-radius: 20rpx;
  margin: 24rpx 32rpx 0;
  overflow: hidden;
  border: 1rpx solid var(--operator-border, rgba(203, 225, 208, 0.96));
  box-shadow: var(--operator-shadow, 0 12rpx 34rpx rgba(35, 75, 54, 0.1));
}

.form-item {
  display: flex;
  align-items: center;
  padding: 32rpx 28rpx;
}

.form-label {
  width: 140rpx;
  font-size: 28rpx;
  color: var(--operator-text-secondary, #5b6f62);
  flex-shrink: 0;
}

.form-value {
  flex: 1;
  font-size: 28rpx;
  color: var(--operator-text, #163022);
  text-align: right;

  &.readonly { color: var(--operator-text-muted, #8aa091); }
}

.form-input {
  flex: 1;
  font-size: 28rpx;
  color: var(--operator-text, #163022);
  text-align: right;
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
