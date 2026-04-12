<!--
  AI 辅助维修对话组件
  从 workorder-detail 页抽出，独立管理对话状态和 SSE 流
-->
<template>
  <view class="ai-chat">
    <view class="chat-header">
      <text class="chat-title">{{ chatTitle }}</text>
      <text class="chat-hint">{{ chatHint }}</text>
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
          <text>{{ welcomeLead }}</text>
          <text v-if="orderIntro" class="bold">{{ orderIntro }}</text>
          <text>{{ welcomeBody }}</text>
        </view>
      </view>

      <!-- 对话消息 -->
      <view
        v-for="(msg, idx) in messages"
        :key="idx"
        class="msg"
        :class="msg.role === 'user' ? 'user-msg' : 'ai-msg'"
      >
        <!-- 思考中动画 -->
        <view v-if="msg.role === 'ai' && msg.thinking" class="msg-bubble ai thinking-bubble">
          <view class="dot" /><view class="dot" /><view class="dot" />
          <text v-if="msg.content" class="thinking-text">{{ msg.content }}</text>
        </view>
        <!-- 正常消息 -->
        <view v-else class="msg-bubble" :class="msg.role">
          <text>{{ msg.content }}</text>
        </view>
      </view>

      <!-- 流式输出中 -->
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
        :maxlength="500"
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
</template>

<script setup lang="ts">
import { ref, nextTick, computed } from 'vue'
import type { WorkOrder } from '../api/workorder'
import {
  sendChatMessage,
  buildContextMessage,
  type ThinkingEvent,
  type TextEvent,
} from '../api/chat'
import { operatorAiApi, workerAiApi } from '../api/ai-assistant'

interface ChatMsg {
  role: 'user' | 'ai'
  content: string
  thinking?: boolean
}

const props = withDefaults(defineProps<{
  order?: WorkOrder | null
  title?: string
  hint?: string
  mode?: 'general' | 'operator' | 'worker'
  dispatchId?: string | null
  hallEntryId?: string | null
}>(), {
  order: null,
  title: 'AI 辅助维修',
  hint: '',
  mode: 'general',
  dispatchId: null,
  hallEntryId: null,
})

const messages = ref<ChatMsg[]>([])
const inputText = ref('')
const sending = ref(false)
const streamingText = ref('')
const sessionId = ref<string | null>(null)
const scrollTop = ref(0)
const isFirstMessage = ref(true)

const chatTitle = computed(() => props.title)
const chatHint = computed(() => props.hint || (
  props.order
    ? '基于当前工单自动提供诊断建议'
    : '可以咨询能耗、工单、派工和现场处置问题'
))
const orderIntro = computed(() => {
  if (!props.order) return ''
  const issue = props.order.issue_description?.slice(0, 60) || '现场情况待补充'
  return `${props.order.building_id} - ${issue}`
})
const welcomeLead = computed(() => props.order ? '您好！我已了解当前工单情况：' : '您好，我是楼宇运维 AI 助手。')
const welcomeBody = computed(() => (
  props.order
    ? '请描述您的现场情况，我将提供针对性的维修指导。'
    : '可以直接咨询能耗分析、派工处理、维修流程或现场处置问题。'
))

function scrollToBottom() {
  nextTick(() => { scrollTop.value = 99999 })
}

async function sendMessage() {
  const text = inputText.value.trim()
  if (!text || sending.value) return

  // 首次发送时拼接工单上下文到 message 中
  const actualMessage = props.mode === 'general' && isFirstMessage.value && props.order
    ? buildContextMessage(props.order, text)
    : text

  messages.value.push({ role: 'user', content: text })
  inputText.value = ''
  sending.value = true
  streamingText.value = ''
  isFirstMessage.value = false
  scrollToBottom()

  // 思考占位
  messages.value.push({ role: 'ai', content: '', thinking: true })

  if (props.mode !== 'general') {
    await sendAssistantMessage(actualMessage)
    return
  }

  try {
    const newSessionId = await sendChatMessage(actualMessage, sessionId.value, {
      onThinking(e: ThinkingEvent) {
        const last = messages.value[messages.value.length - 1]
        if (last?.role === 'ai' && last.thinking) {
          last.content = e.message || ''
        }
      },
      onText(e: TextEvent) {
        // 移除 thinking 占位
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
        removePendingThinking()
        messages.value.push({ role: 'ai', content: `提示：${e.message}` })
        sending.value = false
      },
      onDone(e) {
        sessionId.value = e.session_id
        // 如果流还有剩余没 is_final 的内容
        if (streamingText.value) {
          messages.value.push({ role: 'ai', content: streamingText.value })
          streamingText.value = ''
        }
        removePendingThinking()
        sending.value = false
        scrollToBottom()
      },
      onNetworkError() {
        removePendingThinking()
        messages.value.push({ role: 'ai', content: '网络异常，请重试' })
        sending.value = false
      },
    })
    sessionId.value = newSessionId
  } catch {
    sending.value = false
  }
}

async function sendAssistantMessage(text: string) {
  try {
    const response = props.mode === 'operator'
      ? await operatorAiApi.chat({
          message: text,
          session_id: sessionId.value,
          include_evidence: true,
        })
      : await workerAiApi.chat({
          message: text,
          session_id: sessionId.value,
          ticket_id: props.order?.ticket_id || null,
          dispatch_id: props.dispatchId || props.order?.current_dispatch?.id || props.order?.dispatch_id || null,
          hall_entry_id: props.hallEntryId || null,
          client_context: {
            source_component: 'AiChat',
            work_order_status: props.order?.status || null,
            execution_status: props.order?.current_dispatch?.execution_status || props.order?.execution_status || null,
          },
        })
    sessionId.value = response.session_id
    removePendingThinking()
    messages.value.push({ role: 'ai', content: response.answer })
  } catch (err) {
    removePendingThinking()
    messages.value.push({ role: 'ai', content: err instanceof Error ? err.message : '请求失败，请重试' })
  } finally {
    sending.value = false
    scrollToBottom()
  }
}

function removePendingThinking() {
  const last = messages.value[messages.value.length - 1]
  if (last?.role === 'ai' && last.thinking) messages.value.pop()
}
</script>

<style lang="scss" scoped>
.ai-chat {
  background: #fff;
  border-radius: 20rpx;
  overflow: hidden;
  box-shadow: 0 2rpx 12rpx rgba(0,0,0,0.06);
}

.chat-header {
  padding: 20rpx 24rpx 16rpx;
  border-bottom: 1rpx solid #f0f0f0;
}

.chat-title { display: block; font-size: 28rpx; font-weight: 700; color: #1a1a2e; }
.chat-hint  { font-size: 22rpx; color: #aaa; }

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
    background: linear-gradient(135deg, #d6e29f, #b5c875);
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

.bold { font-weight: 700; }

.cursor {
  width: 3rpx;
  height: 28rpx;
  background: #333;
  animation: blink 0.8s infinite;
}

@keyframes blink { 0%,100% { opacity: 1; } 50% { opacity: 0; } }

.thinking-bubble {
  display: flex;
  align-items: center;
  gap: 8rpx;
  flex-wrap: wrap;
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

.thinking-text { font-size: 22rpx; color: #999; width: 100%; margin-top: 8rpx; }

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
  background: linear-gradient(135deg, #d6e29f, #b5c875);
  border-radius: 12rpx;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;

  text { font-size: 26rpx; color: #fff; font-weight: 600; }
  &.disabled { background: #ccc; pointer-events: none; }
}
</style>
