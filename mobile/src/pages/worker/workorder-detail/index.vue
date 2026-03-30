<template>
  <view class="page">
    <NavBar :title="readonly ? '工单详情' : '工单处理'" bg-color="#0f3d2e" :show-back="true" />

    <!-- 加载中 -->
    <view v-if="loading" class="center-loading">
      <text>加载中...</text>
    </view>

    <template v-else-if="order">
      <!-- 工单基本信息 -->
      <view class="info-card">
        <view class="info-header">
          <view class="priority-badge" :class="order.priority">
            {{ PRIORITY_LABEL[order.priority] || order.priority }}
          </view>
          <view class="status-tag" :class="order.status">
            {{ STATUS_LABEL[order.status] || order.status }}
          </view>
        </view>

        <text class="ticket-no">工单 #{{ order.ticket_id.slice(-12) }}</text>
        <text class="building">{{ order.building_id }}</text>

        <view class="info-row">
          <text class="info-label">异常描述</text>
          <text class="info-value">{{ order.issue_description }}</text>
        </view>
        <view class="info-row">
          <text class="info-label">建议措施</text>
          <text class="info-value">{{ order.suggested_action }}</text>
        </view>
        <view class="info-row">
          <text class="info-label">生成时间</text>
          <text class="info-value">{{ formatDateTime(order.created_at) }}</text>
        </view>

        <!-- AI 审批信息 -->
        <view v-if="order.ai_reason" class="ai-block">
          <view class="ai-block-title">
            <text>🤖 AI 审批分析</text>
            <view class="ai-decision-tag" :class="order.ai_decision">
              {{ order.ai_decision === 'approved' ? '批准' : '驳回' }}
            </view>
          </view>
          <text class="ai-reasoning">{{ order.ai_reason }}</text>
        </view>
      </view>

      <!-- AI 辅助维修对话区（非只读模式） -->
      <view v-if="!readonly" class="chat-wrapper">
        <AiChat :order="order" />
      </view>

      <!-- 底部操作区（非只读） -->
      <view v-if="!readonly" class="action-section">
        <text class="action-title">提交维修结果</text>
        <view class="action-buttons">
          <button
            class="feedback-btn fixed"
            :loading="feedbackLoading === 'fixed'"
            @click="submitFeedback('fixed')"
          >
            ✅ 已修复
          </button>
          <button
            class="feedback-btn false-alarm"
            :loading="feedbackLoading === 'false_alarm'"
            @click="submitFeedback('false_alarm')"
          >
            ❌ 误报
          </button>
          <button
            class="feedback-btn escalate"
            :loading="feedbackLoading === 'escalated'"
            @click="submitFeedback('escalated')"
          >
            ⬆️ 升级处理
          </button>
        </view>

        <!-- 备注输入 -->
        <textarea
          class="note-input"
          v-model="workerNote"
          placeholder="维修备注（可选）"
          :maxlength="500"
        />
      </view>

      <!-- 历史反馈（只读时展示） -->
      <view v-if="readonly && order.worker_result" class="feedback-record">
        <text class="feedback-label">维修结果</text>
        <text class="feedback-value" :class="order.worker_result">
          {{ WORKER_RESULT_LABEL[order.worker_result] || order.worker_result }}
        </text>
        <text v-if="order.worker_notes" class="feedback-note">{{ order.worker_notes }}</text>
      </view>

      <view style="height: 40rpx" />
    </template>
  </view>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import NavBar from '../../../components/NavBar.vue'
import AiChat from '../../../components/AiChat.vue'
import { workOrderApi, type WorkOrder } from '../../../api/workorder'
import { STATUS_LABEL, PRIORITY_LABEL, WORKER_RESULT_LABEL, type WorkerResult } from '../../../constants/status'
import { formatDateTime } from '../../../utils/format'

// 路由参数
const pages = getCurrentPages()
const currentPage = pages[pages.length - 1] as any
const ticketId = currentPage?.options?.ticket_id ?? ''
const readonly = currentPage?.options?.readonly === '1'

const order = ref<WorkOrder | null>(null)
const loading = ref(false)
const feedbackLoading = ref<string | null>(null)
const workerNote = ref('')

async function loadOrder() {
  loading.value = true
  try {
    order.value = await workOrderApi.detail(ticketId)
  } catch { uni.navigateBack() }
  finally { loading.value = false }
}

async function submitFeedback(result: WorkerResult) {
  feedbackLoading.value = result
  const labelMap: Record<string, string> = { fixed: '已修复', false_alarm: '误报', escalated: '升级处理' }

  uni.showModal({
    title: `确认提交：${labelMap[result]}`,
    content: result === 'escalated' ? '工单将升级给管理员处理' : `确认将工单标记为「${labelMap[result]}」？`,
    confirmText: '确认',
    success(res) {
      if (!res.confirm) { feedbackLoading.value = null; return }
      doSubmit(result)
    },
    fail() { feedbackLoading.value = null },
  })
}

async function doSubmit(result: WorkerResult) {
  try {
    await workOrderApi.workerFeedback(ticketId, result, workerNote.value || undefined)
    uni.showToast({ title: '已提交', icon: 'success' })
    setTimeout(() => uni.navigateBack(), 1500)
  } catch { /* handled */ }
  finally { feedbackLoading.value = null }
}

onMounted(loadOrder)
</script>

<style lang="scss" scoped>
.page { background: #f0f5f2; min-height: 100vh; }

.center-loading {
  display: flex;
  justify-content: center;
  padding: 80rpx;
  color: #aaa;
  font-size: 28rpx;
}

/* 工单信息卡 */
.info-card {
  background: #fff;
  margin: 20rpx 24rpx;
  border-radius: 20rpx;
  padding: 28rpx;
  box-shadow: 0 2rpx 12rpx rgba(0,0,0,0.06);
}

.info-header {
  display: flex;
  justify-content: space-between;
  margin-bottom: 20rpx;
}

.priority-badge {
  padding: 6rpx 16rpx;
  border-radius: 20rpx;
  font-size: 22rpx;

  &.high   { background: #fff2f0; color: #ff4d4f; }
  &.medium { background: #fff7e6; color: #fa8c16; }
  &.low    { background: #f6ffed; color: #52c41a; }
}

.status-tag {
  padding: 6rpx 16rpx;
  border-radius: 20rpx;
  font-size: 22rpx;

  &.dispatched { background: #e6f7ff; color: #096dd9; }
  &.completed  { background: #f6ffed; color: #389e0d; }
  &.closed     { background: #f5f5f5; color: #8c8c8c; }
  &.false_alarm { background: #f0f0f0; color: #595959; }
  &.escalated  { background: #f0f0ff; color: #722ed1; }
}

.ticket-no {
  display: block;
  font-size: 24rpx;
  color: #aaa;
  margin-bottom: 8rpx;
}

.building {
  display: block;
  font-size: 36rpx;
  font-weight: 700;
  color: #1a1a2e;
  margin-bottom: 20rpx;
}

.info-row {
  display: flex;
  gap: 16rpx;
  margin-bottom: 14rpx;
  align-items: flex-start;
}

.info-label {
  font-size: 24rpx;
  color: #aaa;
  white-space: nowrap;
  flex-shrink: 0;
  padding-top: 2rpx;
}

.info-value {
  font-size: 26rpx;
  color: #333;
  line-height: 1.5;
  flex: 1;
}

.ai-block {
  background: #f8f9ff;
  border-radius: 12rpx;
  padding: 20rpx;
  margin-top: 16rpx;
  border: 1rpx solid #e8effe;
}

.ai-block-title {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 12rpx;

  text { font-size: 26rpx; font-weight: 600; color: #3b6cf4; }
}

.ai-decision-tag {
  padding: 4rpx 14rpx;
  border-radius: 12rpx;
  font-size: 20rpx;

  &.approved { background: #f0fff4; color: #00b96b; }
  &.rejected { background: #fff0f0; color: #ff4d4f; }
}

.ai-reasoning {
  font-size: 24rpx;
  color: #666;
  line-height: 1.6;
}

/* AI 对话区 */
.chat-wrapper {
  margin: 0 24rpx 20rpx;
}

/* 提交反馈区 */
.action-section {
  background: #fff;
  margin: 0 24rpx 20rpx;
  border-radius: 20rpx;
  padding: 28rpx;
  box-shadow: 0 2rpx 12rpx rgba(0,0,0,0.06);
}

.action-title {
  display: block;
  font-size: 28rpx;
  font-weight: 700;
  color: #1a1a2e;
  margin-bottom: 20rpx;
}

.action-buttons {
  display: flex;
  gap: 16rpx;
  margin-bottom: 20rpx;
}

.feedback-btn {
  flex: 1;
  height: 80rpx;
  border-radius: 12rpx;
  font-size: 24rpx;
  font-weight: 600;
  border: none;
  padding: 0;

  &.fixed       { background: #f0fff8; color: #00b96b; border: 2rpx solid #00b96b; }
  &.false-alarm { background: #fff2f0; color: #ff4d4f; border: 2rpx solid #ff4d4f; }
  &.escalate    { background: #f0f5ff; color: #3b6cf4; border: 2rpx solid #3b6cf4; }
}

.note-input {
  width: 100%;
  background: #f5f7fa;
  border-radius: 12rpx;
  padding: 16rpx 20rpx;
  font-size: 26rpx;
  color: #333;
  min-height: 80rpx;
  box-sizing: border-box;
}

/* 历史反馈记录 */
.feedback-record {
  background: #fff;
  margin: 0 24rpx 20rpx;
  border-radius: 20rpx;
  padding: 28rpx;
}

.feedback-label { display: block; font-size: 24rpx; color: #aaa; margin-bottom: 12rpx; }

.feedback-value {
  display: block;
  font-size: 32rpx;
  font-weight: 700;
  margin-bottom: 12rpx;

  &.fixed       { color: #00b96b; }
  &.false_alarm { color: #ff4d4f; }
  &.escalated   { color: #3b6cf4; }
}

.feedback-note {
  font-size: 26rpx;
  color: #666;
  line-height: 1.6;
}
</style>
