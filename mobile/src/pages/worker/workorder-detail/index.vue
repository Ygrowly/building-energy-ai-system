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
            {{ priorityText(order.priority) }}
          </view>
          <view class="status-tag" :class="order.status">
            {{ statusText(order.status) }}
          </view>
        </view>

        <text class="ticket-no">工单 #{{ order.ticket_id.slice(-12) }}</text>
        <text class="building">{{ order.building_name || order.building_id }}</text>

        <view class="info-row">
          <text class="info-label">异常类型</text>
          <text class="info-value">{{ order.anomaly_type }}</text>
        </view>
        <view class="info-row">
          <text class="info-label">异常描述</text>
          <text class="info-value">{{ order.description }}</text>
        </view>
        <view class="info-row">
          <text class="info-label">生成时间</text>
          <text class="info-value">{{ formatDateTime(order.created_at) }}</text>
        </view>

        <!-- AI 审批信息 -->
        <view v-if="order.ai_reasoning" class="ai-block">
          <view class="ai-block-title">
            <text>🤖 AI 审批分析</text>
            <view class="ai-decision-tag" :class="order.ai_decision">
              {{ order.ai_decision === 'approved' ? '批准' : '驳回' }}
            </view>
          </view>
          <text class="ai-reasoning">{{ order.ai_reasoning }}</text>
        </view>
      </view>

      <!-- AI 辅助维修对话区（只读模式不显示） -->
      <view v-if="!readonly" class="chat-section">
        <view class="chat-title-row">
          <text class="chat-title">🤖 AI 辅助维修</text>
          <text class="chat-hint">基于当前工单自动提供诊断建议</text>
        </view>

        <!-- 消息列表 -->
        <scroll-view
          scroll-y
          :scroll-top="scrollTop"
          class="chat-messages"
          :scroll-with-animation="true"
        >
          <!-- 欢迎消息 -->
          <view class="msg ai-msg">
            <view class="msg-bubble ai">
              <text>您好！我已了解当前工单情况：</text>
              <text class="bold-text">{{ order.building_name || order.building_id }} - {{ order.anomaly_type }}</text>
              <text>请描述您的现场情况，我将提供针对性的维修指导。</text>
            </view>
          </view>

          <!-- 对话消息 -->
          <view
            v-for="(msg, idx) in messages"
            :key="idx"
            class="msg"
            :class="msg.role === 'user' ? 'user-msg' : 'ai-msg'"
          >
            <!-- AI 思考中 -->
            <view v-if="msg.role === 'ai' && msg.thinking" class="thinking-indicator">
              <view class="dot" /><view class="dot" /><view class="dot" />
            </view>
            <view class="msg-bubble" :class="msg.role">
              <text>{{ msg.content }}</text>
            </view>
          </view>

          <!-- 流式打字中 -->
          <view v-if="streamingText" class="msg ai-msg">
            <view class="msg-bubble ai streaming">
              <text>{{ streamingText }}</text>
              <view class="cursor" />
            </view>
          </view>

          <view style="height: 20rpx" />
        </scroll-view>

        <!-- 输入区 -->
        <view class="chat-input-area">
          <textarea
            class="chat-input"
            v-model="inputText"
            placeholder="描述现场情况或提问..."
            :disabled="sending"
            auto-height
            :max-height="160"
            @confirm="sendMessage"
          />
          <view
            class="send-btn"
            :class="{ disabled: !inputText.trim() || sending }"
            @click="sendMessage"
          >
            <text v-if="!sending">发送</text>
            <text v-else>...</text>
          </view>
        </view>
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
          :max-height="120"
        />
      </view>

      <!-- 历史反馈（只读时展示） -->
      <view v-if="readonly && order.worker_feedback" class="feedback-record">
        <text class="feedback-label">维修结果</text>
        <text class="feedback-value" :class="order.worker_feedback">
          {{ feedbackText(order.worker_feedback) }}
        </text>
        <text v-if="order.worker_note" class="feedback-note">{{ order.worker_note }}</text>
      </view>

      <view style="height: 40rpx" />
    </template>
  </view>
</template>

<script setup lang="ts">
import { ref, onMounted, nextTick } from 'vue'
import NavBar from '../../../components/NavBar.vue'
import { workOrderApi, type WorkOrder, type WorkerFeedback } from '../../../api/workorder'
import { sendChatMessage, buildWorkOrderContext, type TextEvent, type ThinkingEvent } from '../../../api/chat'

interface ChatMsg {
  role: 'user' | 'ai'
  content: string
  thinking?: boolean
}

// 路由参数
const pages = getCurrentPages()
const currentPage = pages[pages.length - 1] as any
const ticketId  = currentPage?.options?.ticket_id ?? ''
const readonly  = currentPage?.options?.readonly === '1'

const order = ref<WorkOrder | null>(null)
const loading = ref(false)
const messages = ref<ChatMsg[]>([])
const inputText = ref('')
const sending = ref(false)
const streamingText = ref('')
const sessionId = ref<string | null>(null)
const scrollTop = ref(0)
const feedbackLoading = ref<string | null>(null)
const workerNote = ref('')

async function loadOrder() {
  loading.value = true
  try {
    order.value = await workOrderApi.get(ticketId)
  } catch { uni.navigateBack() }
  finally { loading.value = false }
}

async function sendMessage() {
  const text = inputText.value.trim()
  if (!text || sending.value || !order.value) return

  messages.value.push({ role: 'user', content: text })
  inputText.value = ''
  sending.value = true
  streamingText.value = ''
  scrollToBottom()

  // 首次发送时注入工单上下文
  const context = messages.value.length === 1
    ? buildWorkOrderContext(order.value)
    : undefined

  // 添加 AI 思考占位
  messages.value.push({ role: 'ai', content: '', thinking: true })

  try {
    const newSessionId = await sendChatMessage(text, sessionId.value, {
      onThinking(e: ThinkingEvent) {
        // 更新最后一条AI消息的thinking状态
        const last = messages.value[messages.value.length - 1]
        if (last?.role === 'ai') last.content = e.message || ''
      },
      onText(e: TextEvent) {
        // 移除thinking占位，开始流式显示
        const last = messages.value[messages.value.length - 1]
        if (last?.role === 'ai' && last.thinking) {
          messages.value.pop()
        }
        streamingText.value += e.content
        if (e.is_final) {
          messages.value.push({ role: 'ai', content: streamingText.value })
          streamingText.value = ''
        }
        scrollToBottom()
      },
      onError(e) {
        const last = messages.value[messages.value.length - 1]
        if (last?.role === 'ai' && last.thinking) messages.value.pop()
        messages.value.push({ role: 'ai', content: `⚠️ ${e.message}` })
      },
      onDone(e) {
        sessionId.value = e.session_id
        sending.value = false
        scrollToBottom()
      },
      onNetworkError() {
        const last = messages.value[messages.value.length - 1]
        if (last?.role === 'ai' && last.thinking) messages.value.pop()
        messages.value.push({ role: 'ai', content: '⚠️ 网络异常，请重试' })
        sending.value = false
      },
    }, context)
    sessionId.value = newSessionId
  } catch {
    sending.value = false
  }
}

async function submitFeedback(fb: WorkerFeedback) {
  feedbackLoading.value = fb
  const labelMap = { fixed: '已修复', false_alarm: '误报', escalated: '升级处理' }

  uni.showModal({
    title: `确认提交：${labelMap[fb]}`,
    content: fb === 'escalated' ? '工单将升级给管理员处理' : `确认将工单标记为「${labelMap[fb]}」？`,
    confirmText: '确认',
    async success(res) {
      if (!res.confirm) { feedbackLoading.value = null; return }
      try {
        await workOrderApi.workerFeedback(ticketId, fb, workerNote.value || undefined)
        uni.showToast({ title: '已提交', icon: 'success' })
        setTimeout(() => uni.navigateBack(), 1500)
      } catch { /* handled */ }
      finally { feedbackLoading.value = null }
    },
    fail() { feedbackLoading.value = null },
  })
}

function scrollToBottom() {
  nextTick(() => { scrollTop.value = 99999 })
}

function priorityText(p: string) {
  return { high: '高优先', medium: '中优先', low: '低优先' }[p] ?? p
}

function statusText(s: string) {
  return {
    new: '待审批', pending_ai_review: 'AI审批中', ai_approved: 'AI批准',
    ai_rejected: 'AI驳回', dispatched: '已派单', completed: '已完成',
    closed: '已关闭', false_alarm: '误报', escalated: '已升级',
  }[s] ?? s
}

function feedbackText(f: string) {
  return { fixed: '已修复 ✅', false_alarm: '误报 ❌', escalated: '已升级 ⬆️' }[f] ?? f
}

function formatDateTime(iso: string): string {
  const d = new Date(iso)
  return `${d.getFullYear()}-${d.getMonth()+1}-${d.getDate()} ${d.getHours().toString().padStart(2,'0')}:${d.getMinutes().toString().padStart(2,'0')}`
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
.chat-section {
  background: #fff;
  margin: 0 24rpx 20rpx;
  border-radius: 20rpx;
  overflow: hidden;
  box-shadow: 0 2rpx 12rpx rgba(0,0,0,0.06);
}

.chat-title-row {
  padding: 20rpx 24rpx 16rpx;
  border-bottom: 1rpx solid #f0f0f0;
}

.chat-title {
  display: block;
  font-size: 28rpx;
  font-weight: 700;
  color: #1a1a2e;
}

.chat-hint {
  font-size: 22rpx;
  color: #aaa;
}

.chat-messages {
  height: 520rpx;
  padding: 16rpx 20rpx;
}

.msg {
  display: flex;
  margin-bottom: 20rpx;

  &.user-msg { justify-content: flex-end; }
  &.ai-msg   { justify-content: flex-start; }
}

.msg-bubble {
  max-width: 75%;
  padding: 18rpx 22rpx;
  border-radius: 20rpx;
  font-size: 26rpx;
  line-height: 1.6;

  text { display: block; margin-bottom: 6rpx; &:last-child { margin-bottom: 0; } }

  &.user {
    background: #00b96b;
    color: #fff;
    border-bottom-right-radius: 4rpx;
  }

  &.ai {
    background: #f5f5f5;
    color: #333;
    border-bottom-left-radius: 4rpx;
  }

  &.streaming {
    display: flex;
    align-items: flex-end;
    gap: 8rpx;
  }
}

.bold-text { font-weight: 700; }

.cursor {
  width: 3rpx;
  height: 28rpx;
  background: #333;
  animation: blink 0.8s infinite;
}

@keyframes blink { 0%,100% { opacity: 1; } 50% { opacity: 0; } }

.thinking-indicator {
  display: flex;
  align-items: center;
  gap: 8rpx;
  padding: 16rpx 20rpx;
  background: #f5f5f5;
  border-radius: 20rpx;
  border-bottom-left-radius: 4rpx;
  max-width: 75%;
}

.dot {
  width: 12rpx;
  height: 12rpx;
  border-radius: 50%;
  background: #aaa;
  animation: bounce 1s infinite;

  &:nth-child(2) { animation-delay: 0.2s; }
  &:nth-child(3) { animation-delay: 0.4s; }
}

@keyframes bounce {
  0%,80%,100% { transform: translateY(0); }
  40%         { transform: translateY(-8rpx); }
}

.chat-input-area {
  display: flex;
  align-items: flex-end;
  gap: 16rpx;
  padding: 16rpx 20rpx;
  border-top: 1rpx solid #f0f0f0;
  background: #fff;
}

.chat-input {
  flex: 1;
  background: #f5f7fa;
  border-radius: 12rpx;
  padding: 16rpx 20rpx;
  font-size: 26rpx;
  color: #1a1a2e;
  min-height: 72rpx;
}

.send-btn {
  width: 100rpx;
  height: 72rpx;
  background: #00b96b;
  border-radius: 12rpx;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;

  text { font-size: 26rpx; color: #fff; font-weight: 600; }

  &.disabled {
    background: #ccc;
    pointer-events: none;
  }
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
