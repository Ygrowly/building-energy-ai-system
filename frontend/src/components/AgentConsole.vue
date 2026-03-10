<template>
  <div class="console">
    <!-- 顶部工具栏 -->
    <div class="console-toolbar">
      <span class="console-title">🤖 多智能体控制台</span>
      <button class="clear-btn" @click="store.clearSession()" title="清除对话">🗑️</button>
    </div>

    <!-- Agent 状态条 -->
    <Transition name="fade">
      <div class="agent-status-bar" v-if="store.currentAgentStatus">
        <span class="status-dot"></span>
        <span class="status-label">{{ store.currentAgentStatus.label }}</span>
        <span class="status-msg">{{ store.currentAgentStatus.message }}</span>
      </div>
    </Transition>

    <!-- 消息列表 -->
    <div class="messages" ref="messagesEl">
      <div v-if="!store.hasMessages" class="empty-hint">
        <p>👋 你好！我是楼宇能耗管理智能助手。</p>
        <p>你可以问我：</p>
        <ul>
          <li>「图书馆昨天的用电量是多少？」</li>
          <li>「办公楼上周的能效比 COP 怎么样？」</li>
          <li>「凌晨3点的能耗异常是怎么回事？」</li>
        </ul>
      </div>

      <template v-for="msg in store.messages" :key="msg.id">
        <!-- 用户消息 -->
        <div class="msg msg-user" v-if="msg.role === 'user'">
          <div class="bubble user-bubble">{{ msg.content }}</div>
        </div>

        <!-- AI 文字回复 -->
        <div class="msg msg-ai" v-else-if="msg.role === 'ai'">
          <div class="ai-avatar">🤖</div>
          <div class="bubble ai-bubble" v-html="formatMarkdown(msg.content)"></div>
        </div>

        <!-- Thinking 气泡 -->
        <ThinkingBubble
          v-else-if="msg.role === 'thinking'"
          :agent="msg.agent ?? 'router'"
          :message="msg.content"
        />

        <!-- Artifact：图表 -->
        <DynamicChart
          v-else-if="msg.role === 'artifact' && isChart(msg.artifact)"
          :artifact="msg.artifact!"
        />

        <!-- Artifact：工单卡片 -->
        <WorkOrderCard
          v-else-if="msg.role === 'artifact' && isWorkOrder(msg.artifact)"
          :artifact="msg.artifact!"
          :is-processing="store.isLoading"
          @approve="store.approveOrder(true)"
          @reject="(reason) => store.approveOrder(false, reason)"
        />

        <!-- 错误消息 -->
        <div class="msg msg-error" v-else-if="msg.role === 'error'">
          <div class="bubble error-bubble">⚠️ {{ msg.content }}</div>
        </div>
      </template>

      <!-- 加载中光标 -->
      <div class="typing-indicator" v-if="store.isLoading">
        <span></span><span></span><span></span>
      </div>
    </div>

    <!-- 输入框 -->
    <div class="input-area">
      <textarea
        v-model="inputText"
        placeholder="输入您的问题，按 Enter 发送..."
        rows="2"
        @keydown.enter.exact.prevent="handleSend"
        @keydown.enter.shift.exact="inputText += '\n'"
        :disabled="store.isLoading"
      ></textarea>
      <button class="send-btn" @click="handleSend" :disabled="store.isLoading || !inputText.trim()">
        {{ store.isLoading ? '⏳' : '发送' }}
      </button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, watch, nextTick } from 'vue'
import { useChatStore } from '@/stores/chatStore'
import ThinkingBubble from '@/generative-ui/ThinkingBubble.vue'
import DynamicChart from '@/generative-ui/DynamicChart.vue'
import WorkOrderCard from '@/generative-ui/WorkOrderCard.vue'
import type { ArtifactEvent } from '@/api/stream_client'

const store = useChatStore()
const inputText = ref('')
const messagesEl = ref<HTMLElement>()

function handleSend() {
  if (!inputText.value.trim() || store.isLoading) return
  store.sendMessage(inputText.value.trim())
  inputText.value = ''
}

// 自动滚动到底部
watch(() => store.messages.length, async () => {
  await nextTick()
  if (messagesEl.value) {
    messagesEl.value.scrollTop = messagesEl.value.scrollHeight
  }
})

function isChart(artifact?: ArtifactEvent): boolean {
  if (!artifact) return false
  const type = artifact.component_type ?? artifact.widget ?? ''
  return ['LineChart', 'BarChart', 'Gauge'].includes(type)
}

function isWorkOrder(artifact?: ArtifactEvent): boolean {
  if (!artifact) return false
  const type = artifact.component_type ?? artifact.widget ?? ''
  return type === 'WorkOrderCard'
}

function formatMarkdown(text: string): string {
  return text
    .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
    .replace(/\n/g, '<br/>')
}
</script>

<style scoped>
.console {
  display: flex;
  flex-direction: column;
  height: 100%;
  background: var(--bg-panel);
}

.console-toolbar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 12px 16px;
  border-bottom: 1px solid var(--border);
  flex-shrink: 0;
}

.console-title {
  font-weight: 700;
  font-size: 14px;
  color: var(--text-primary);
}

.clear-btn {
  background: none;
  border: none;
  cursor: pointer;
  font-size: 16px;
  padding: 2px;
  opacity: 0.6;
  transition: opacity 0.2s;
}
.clear-btn:hover { opacity: 1; }

.agent-status-bar {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 16px;
  background: rgba(108,142,245,0.08);
  border-bottom: 1px solid rgba(108,142,245,0.2);
  font-size: 12px;
}

.status-dot {
  width: 8px; height: 8px;
  border-radius: 50%;
  background: var(--thinking-color);
  animation: blink 1s infinite;
}
@keyframes blink { 0%, 100% { opacity: 1; } 50% { opacity: 0.3; } }

.status-label { color: var(--thinking-color); font-weight: 600; }
.status-msg { color: var(--text-secondary); flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }

.messages {
  flex: 1;
  overflow-y: auto;
  padding: 16px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.empty-hint {
  color: var(--text-muted);
  font-size: 13px;
  text-align: center;
  margin: auto;
  padding: 40px 20px;
  line-height: 2;
}
.empty-hint ul { text-align: left; margin-top: 12px; padding-left: 20px; }
.empty-hint li { margin: 6px 0; color: var(--text-secondary); }

.msg { display: flex; align-items: flex-start; gap: 8px; }
.msg-user { justify-content: flex-end; }
.msg-error { justify-content: flex-start; }

.bubble {
  max-width: 85%;
  padding: 10px 14px;
  border-radius: 12px;
  font-size: 13px;
  line-height: 1.6;
}

.user-bubble {
  background: var(--accent);
  color: #fff;
  border-radius: 12px 12px 2px 12px;
}

.ai-avatar {
  width: 28px; height: 28px;
  border-radius: 50%;
  background: var(--bg-card);
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 14px;
  flex-shrink: 0;
}

.ai-bubble {
  background: var(--bg-card);
  color: var(--text-primary);
  border: 1px solid var(--border);
  border-radius: 2px 12px 12px 12px;
}

.error-bubble {
  background: rgba(248,113,113,0.1);
  color: var(--danger);
  border: 1px solid rgba(248,113,113,0.3);
}

.typing-indicator {
  display: flex;
  gap: 4px;
  padding: 8px 14px;
}
.typing-indicator span {
  width: 6px; height: 6px;
  border-radius: 50%;
  background: var(--accent);
  animation: bounce 1.2s infinite;
}
.typing-indicator span:nth-child(2) { animation-delay: 0.2s; }
.typing-indicator span:nth-child(3) { animation-delay: 0.4s; }
@keyframes bounce { 0%, 80%, 100% { transform: translateY(0); } 40% { transform: translateY(-6px); } }

.input-area {
  display: flex;
  gap: 8px;
  padding: 12px 16px;
  border-top: 1px solid var(--border);
  flex-shrink: 0;
}

textarea {
  flex: 1;
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: 8px;
  color: var(--text-primary);
  padding: 8px 12px;
  font-size: 13px;
  resize: none;
  font-family: inherit;
  line-height: 1.5;
  transition: border-color 0.2s;
}
textarea:focus { outline: none; border-color: var(--accent); }
textarea:disabled { opacity: 0.5; }

.send-btn {
  background: var(--accent);
  border: none;
  border-radius: 8px;
  color: #fff;
  padding: 0 18px;
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
  transition: opacity 0.2s;
  align-self: flex-end;
  height: 38px;
}
.send-btn:hover { opacity: 0.85; }
.send-btn:disabled { opacity: 0.4; cursor: not-allowed; }

.fade-enter-active, .fade-leave-active { transition: all 0.3s; }
.fade-enter-from, .fade-leave-to { opacity: 0; transform: translateY(-8px); }
</style>
