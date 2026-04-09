<template>
  <view class="page">
    <NavBar title="我的派工画像" bg-color="#E4EDB8" text-color="#5f7137" :show-back="true" />

    <scroll-view scroll-y class="page-scroll">
      <view class="hero-card">
        <view>
          <text class="hero-eyebrow">系统眼中的我</text>
          <text class="hero-title">{{ profile?.user.username || user?.username || '维修人员' }}</text>
          <text class="hero-desc">这里决定调度推荐会如何理解你的班组、技能、负载与当前可接单状态。</text>
        </view>
        <view class="hero-state" :class="{ disabled: !form.dispatch_enabled }">
          <text>{{ form.dispatch_enabled ? '可接单' : '暂停接单' }}</text>
        </view>
      </view>

      <view class="metric-grid">
        <view class="metric-card">
          <text class="metric-value">{{ profile?.active_orders ?? 0 }}</text>
          <text class="metric-label">当前工单</text>
        </view>
        <view class="metric-card">
          <text class="metric-value">{{ profile?.max_active_orders ?? 4 }}</text>
          <text class="metric-label">负载上限</text>
        </view>
        <view class="metric-card">
          <text class="metric-value">{{ capacityText }}</text>
          <text class="metric-label">负载占比</text>
        </view>
      </view>

      <view class="section-card">
        <view class="section-head">
          <text class="section-title">基础画像</text>
          <text class="section-subtitle">由管理员维护，维修端只读</text>
        </view>

        <view class="info-row">
          <text class="info-label">所属班组</text>
          <text class="info-value">{{ profile?.team?.name || '暂未配置' }}</text>
        </view>
        <view class="info-row">
          <text class="info-label">岗位</text>
          <text class="info-value">{{ profile?.job_title || '维修服务工程师' }}</text>
        </view>
        <view class="info-row">
          <text class="info-label">联系方式</text>
          <text class="info-value">{{ profile?.user.phone || profile?.user.email || user?.phone || '暂未填写' }}</text>
        </view>

        <view class="chip-section">
          <text class="chip-title">技能标签</text>
          <view class="chip-row">
            <text
              v-for="skill in profile?.skills || []"
              :key="skill.skill_id || skill.code || skill.name || 'skill'"
              class="skill-chip"
              :class="{ primary: skill.is_primary }"
            >
              {{ skill.name || skill.code }}{{ skill.is_primary ? ' · 主技能' : '' }}
            </text>
            <text v-if="!profile?.skills?.length" class="empty-chip">暂未配置技能</text>
          </view>
        </view>

        <view class="chip-section">
          <text class="chip-title">服务楼宇</text>
          <view class="chip-row">
            <text
              v-for="building in profile?.service_buildings || []"
              :key="building"
              class="building-chip"
            >{{ building }}</text>
            <text v-if="!profile?.service_buildings?.length" class="empty-chip">当前按跨楼宇支援处理</text>
          </view>
        </view>
      </view>

      <view class="section-card">
        <view class="section-head">
          <text class="section-title">当前状态</text>
          <text class="section-subtitle">这些字段会影响后续推荐和半自动派工</text>
        </view>

        <view class="status-options">
          <view
            v-for="option in shiftOptions"
            :key="option.value"
            class="status-option"
            :class="{ active: form.shift_status === option.value }"
            @click="form.shift_status = option.value"
          >
            <text class="status-label">{{ option.label }}</text>
            <text class="status-desc">{{ option.desc }}</text>
          </view>
        </view>

        <view class="switch-row">
          <view>
            <text class="switch-title">今日可接单</text>
            <text class="switch-desc">关闭后调度推荐会降低或避开你</text>
          </view>
          <switch :checked="form.dispatch_enabled" color="#b5c875" @change="onDispatchEnabledChange" />
        </view>

        <view class="switch-row">
          <view>
            <text class="switch-title">可接急单</text>
            <text class="switch-desc">高优先级和超时接管会参考这个开关</text>
          </view>
          <switch :checked="form.accepts_emergency" color="#b5c875" @change="onEmergencyChange" />
        </view>

        <view class="notes-box">
          <text class="notes-title">状态备注</text>
          <textarea
            v-model="form.notes"
            class="notes-input"
            maxlength="1000"
            placeholder="例如：今天在3号楼巡检，优先派附近任务"
          />
        </view>
      </view>

      <view class="hint-card">
        <text class="hint-title">为什么不能直接改班组和技能？</text>
        <text class="hint-text">这些字段会影响调度公平性和自动推荐规则，暂由管理员维护。若发现不准确，可以先在备注里说明。</text>
      </view>

      <button class="save-btn" :loading="saving" :disabled="loading || saving" @click="handleSave">
        保存当前状态
      </button>
    </scroll-view>
  </view>
</template>

<script setup lang="ts">
import { computed, reactive, ref } from 'vue'
import { onShow } from '@dcloudio/uni-app'
import NavBar from '../../../components/NavBar.vue'
import { useAuthStore } from '../../../stores/auth'
import { useRouteGuard } from '../../../utils/route-guard'
import { WORKER_ROLES } from '../../../constants/roles'
import { workerProfileApi, type WorkerProfileItem } from '../../../api/workerProfile'

useRouteGuard(WORKER_ROLES)

const authStore = useAuthStore()
const user = computed(() => authStore.user)
const profile = ref<WorkerProfileItem | null>(null)
const loading = ref(false)
const saving = ref(false)

const form = reactive({
  shift_status: 'on_duty',
  dispatch_enabled: true,
  accepts_emergency: true,
  notes: '',
})

const shiftOptions = [
  { value: 'on_duty', label: '值班', desc: '正常接单' },
  { value: 'standby', label: '备勤', desc: '可支援' },
  { value: 'busy', label: '忙碌', desc: '减少派单' },
  { value: 'off_duty', label: '离岗', desc: '不建议派单' },
]

const capacityText = computed(() => {
  const ratio = profile.value?.capacity_ratio
  if (typeof ratio !== 'number') return '0%'
  return `${Math.round(ratio * 100)}%`
})

function fillForm(nextProfile: WorkerProfileItem) {
  form.shift_status = nextProfile.shift_status || 'on_duty'
  form.dispatch_enabled = !!nextProfile.dispatch_enabled
  form.accepts_emergency = !!nextProfile.accepts_emergency
  form.notes = nextProfile.notes || ''
}

function syncAuthProfile(nextProfile: WorkerProfileItem) {
  if (!authStore.user) return
  authStore.user = {
    ...authStore.user,
    worker_profile: {
      user_id: nextProfile.user.id,
      team: nextProfile.team
        ? {
            id: nextProfile.team.id,
            team_code: nextProfile.team.team_code,
            name: nextProfile.team.name,
          }
        : null,
      job_title: nextProfile.job_title,
      shift_status: nextProfile.shift_status,
      dispatch_enabled: nextProfile.dispatch_enabled,
      max_active_orders: nextProfile.max_active_orders,
      accepts_emergency: nextProfile.accepts_emergency,
      service_buildings: [...nextProfile.service_buildings],
      skills: nextProfile.skills.map(item => ({
        code: item.code || '',
        name: item.name || item.code || '未命名技能',
        category: item.category,
        proficiency: item.proficiency,
        is_primary: item.is_primary,
      })),
      notes: nextProfile.notes,
    },
  }
  uni.setStorageSync('user_info', JSON.stringify(authStore.user))
}

async function loadProfile() {
  loading.value = true
  try {
    const res = await workerProfileApi.me()
    profile.value = res
    fillForm(res)
    syncAuthProfile(res)
  } catch {
    // request.ts 已统一提示，这里保持页面不崩。
  } finally {
    loading.value = false
  }
}

function onDispatchEnabledChange(e: any) {
  form.dispatch_enabled = !!e.detail.value
}

function onEmergencyChange(e: any) {
  form.accepts_emergency = !!e.detail.value
}

async function handleSave() {
  saving.value = true
  try {
    const res = await workerProfileApi.updateMe({
      shift_status: form.shift_status,
      dispatch_enabled: form.dispatch_enabled,
      accepts_emergency: form.accepts_emergency,
      notes: form.notes || null,
    })
    profile.value = res
    fillForm(res)
    syncAuthProfile(res)
    uni.showToast({ title: '派工状态已更新', icon: 'success' })
  } catch {
    // request.ts 已统一提示。
  } finally {
    saving.value = false
  }
}

onShow(loadProfile)
</script>

<style lang="scss" scoped>
.page {
  min-height: 100vh;
  background:
    radial-gradient(circle at top left, rgba(228, 237, 184, 0.78), transparent 36%),
    linear-gradient(180deg, #f8faef 0%, #fffdfb 100%);
}

.page-scroll {
  height: 100vh;
  padding: 24rpx 24rpx calc(56rpx + env(safe-area-inset-bottom, 0px));
  box-sizing: border-box;
}

.hero-card,
.metric-card,
.section-card,
.hint-card {
  background: rgba(255, 255, 255, 0.97);
  border-radius: 30rpx;
  box-shadow: 0 14rpx 36rpx rgba(181, 196, 118, 0.08);
}

.hero-card {
  padding: 28rpx;
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 24rpx;
}

.hero-eyebrow,
.hero-desc {
  display: block;
  color: #8f827c;
  font-size: 23rpx;
}

.hero-title {
  display: block;
  margin-top: 10rpx;
  color: #302824;
  font-size: 42rpx;
  font-weight: 800;
}

.hero-desc {
  margin-top: 12rpx;
  line-height: 1.7;
}

.hero-state {
  flex-shrink: 0;
  padding: 12rpx 18rpx;
  border-radius: 999rpx;
  background: #eff8f3;

  text {
    color: #2f8f61;
    font-size: 24rpx;
    font-weight: 700;
  }

  &.disabled {
    background: #fff0ec;

    text {
      color: #d66d4f;
    }
  }
}

.metric-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 16rpx;
  margin-top: 20rpx;
}

.metric-card {
  padding: 22rpx 10rpx;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8rpx;
}

.metric-value {
  color: #728548;
  font-size: 38rpx;
  font-weight: 800;
}

.metric-label {
  color: #91847d;
  font-size: 22rpx;
}

.section-card,
.hint-card {
  margin-top: 22rpx;
  padding: 26rpx;
}

.section-head {
  margin-bottom: 18rpx;
}

.section-title,
.hint-title {
  display: block;
  color: #302824;
  font-size: 31rpx;
  font-weight: 800;
}

.section-subtitle,
.hint-text {
  display: block;
  margin-top: 8rpx;
  color: #94857e;
  font-size: 23rpx;
  line-height: 1.7;
}

.info-row {
  display: flex;
  justify-content: space-between;
  gap: 20rpx;
  padding: 20rpx 0;
  border-bottom: 1rpx solid #eef2df;
}

.info-row:last-of-type {
  border-bottom: none;
}

.info-label {
  color: #8f827c;
  font-size: 25rpx;
}

.info-value {
  flex: 1;
  color: #332b27;
  font-size: 25rpx;
  text-align: right;
}

.chip-section {
  margin-top: 22rpx;
}

.chip-title {
  display: block;
  margin-bottom: 12rpx;
  color: #7d7069;
  font-size: 24rpx;
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

.status-options {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 14rpx;
}

.status-option {
  padding: 20rpx;
  border-radius: 24rpx;
  background: #f7f8f2;
  border: 2rpx solid transparent;
}

.status-option.active {
  border-color: #b5c875;
  background: #f4f8e6;
}

.status-label,
.status-desc,
.switch-title,
.switch-desc,
.notes-title {
  display: block;
}

.status-label,
.switch-title,
.notes-title {
  color: #302824;
  font-size: 27rpx;
  font-weight: 700;
}

.status-desc,
.switch-desc {
  margin-top: 8rpx;
  color: #95867f;
  font-size: 22rpx;
}

.switch-row {
  margin-top: 18rpx;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 24rpx;
  padding: 22rpx 0;
  border-top: 1rpx solid #eef2df;
}

.notes-box {
  margin-top: 18rpx;
}

.notes-input {
  margin-top: 14rpx;
  width: 100%;
  min-height: 160rpx;
  padding: 20rpx;
  border-radius: 22rpx;
  background: #f8faf1;
  color: #332b27;
  font-size: 25rpx;
  line-height: 1.6;
  box-sizing: border-box;
}

.save-btn {
  margin: 28rpx 0 10rpx;
  height: 92rpx;
  border: none;
  border-radius: 999rpx;
  background: linear-gradient(135deg, #d6e29f, #b5c875);
  color: #fff;
  font-size: 30rpx;
  font-weight: 800;
}
</style>
