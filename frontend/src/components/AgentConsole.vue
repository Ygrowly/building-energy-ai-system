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
        <p class="hint-greeting">👋 你好！我是楼宇能耗管理智能助手。</p>
        <p class="hint-sub">可以用自然语言提问，支持数据查询、故障诊断与工单生成。</p>
        <div class="hint-examples">
          <p class="hint-group-label">📊 数据查询</p>
          <button class="hint-chip" @click="quickSend('教学楼 2016 年 4 月 15 日的用电量是多少？')">
            教学楼 2016-04-15 用电量
          </button>
          <button class="hint-chip" @click="quickSend('对比三栋楼 2016 年 4 月的每日用电趋势')">
            多楼宇趋势对比
          </button>
          <p class="hint-group-label">🔬 故障诊断</p>
          <button class="hint-chip" @click="quickSend('办公楼 2016-04-15 凌晨 3 点的能耗有没有问题？帮我处理一下')">
            凌晨异常能耗诊断
          </button>
          <button class="hint-chip" @click="quickSend('计算教学楼 2016 年 4 月的制冷能效比 COP')">
            COP 计算
          </button>
          <p class="hint-group-label">📥 报表生成</p>
          <button class="hint-chip" @click="quickSend('帮我导出办公楼 2016-04-01 到 2016-05-01 的每日能耗报表')">
            导出能耗报表 CSV
          </button>
        </div>
      </div>

      <template v-for="msg in store.messages" :key="msg.id">
        <!-- 用户消息 -->
        <div class="msg msg-user" v-if="msg.role === 'user'">
          <div class="bubble user-bubble">{{ msg.content }}</div>
        </div>

        <!-- AI 文字回复 + 可选数据血缘 -->
        <div class="msg msg-ai" v-else-if="msg.role === 'ai'">
          <div class="ai-avatar">🤖</div>
          <div class="ai-content">
            <div class="bubble ai-bubble" v-html="formatMarkdown(msg.content)"></div>
            <EvidenceLink
              v-if="msg.artifact?.source_info"
              :source-info="msg.artifact.source_info as Record<string, unknown>"
            />
          </div>
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

        <!-- Artifact：报表下载卡片 -->
        <ReportDownload
          v-else-if="msg.role === 'artifact' && isReportDownload(msg.artifact)"
          :artifact="msg.artifact!"
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
import ReportDownload from '@/generative-ui/ReportDownload.vue'
import EvidenceLink from '@/generative-ui/EvidenceLink.vue'
import type { ArtifactEvent } from '@/api/stream_client'

const store = useChatStore()
const inputText = ref('')
const messagesEl = ref<HTMLElement>()

function handleSend() {
  if (!inputText.value.trim() || store.isLoading) return
  store.sendMessage(inputText.value.trim())
  inputText.value = ''
}

function quickSend(text: string) {
  if (store.isLoading) return
  inputText.value = text
  store.sendMessage(text)
  inputText.value = ''
}

// 自动滚动到底部
watch(() => store.messages.length, async () => {
  await nextTick()
  if (messagesEl.value) {
    messagesEl.value.scrollTop = messagesEl.value.scrollHeight
  }
})

// ── Artifact 类型判断 ──────────────────────────────
function isChart(artifact?: ArtifactEvent): boolean {
  if (!artifact) return false
  const t = artifact.component_type ?? artifact.widget ?? ''
  return ['LineChart', 'BarChart', 'Gauge', 'line-chart', 'bar-chart', 'gauge'].includes(t)
}

function isWorkOrder(artifact?: ArtifactEvent): boolean {
  if (!artifact) return false
  const t = artifact.component_type ?? artifact.widget ?? ''
  return ['WorkOrderCard', 'work-order-card'].includes(t)
}

function isReportDownload(artifact?: ArtifactEvent): boolean {
  if (!artifact) return false
  const t = artifact.component_type ?? artifact.widget ?? ''
  return ['ReportDownload', 'report-download'].includes(t)
}

// ── Markdown 简单渲染 ──────────────────────────────
function formatMarkdown(text: string): string {
  return text
    .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
    .replace(/`([^`]+)`/g, '<code style="background:rgba(108,142,245,0.15);padding:1px 5px;border-radius:3px;font-family:monospace;font-size:0.9em">$1</code>')
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
  margin: auto;
  padding: 24px 16px;
  width: 100%;
}

.hint-greeting { font-size: 14px; font-weight: 600; color: var(--text-primary); margin-bottom: 6px; }
.hint-sub      { font-size: 12px; color: var(--text-secondary); margin-bottom: 16px; }

.hint-examples { display: flex; flex-direction: column; gap: 4px; }

.hint-group-label {
  font-size: 10px;
  font-weight: 700;
  color: var(--text-muted);
  text-transform: uppercase;
  letter-spacing: 0.06em;
  margin-top: 10px;
  margin-bottom: 4px;
}

.hint-chip {
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: 6px;
  color: var(--text-secondary);
  font-size: 12px;
  padding: 7px 12px;
  text-align: left;
  cursor: pointer;
  transition: all 0.2s;
  line-height: 1.4;
}
.hint-chip:hover {
  background: var(--accent-glow);
  border-color: var(--accent);
  color: var(--accent);
}

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

/* AI 气泡 + 数据血缘垂直堆叠 */
.ai-content {
  display: flex;
  flex-direction: column;
  gap: 4px;
  max-width: 85%;
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
