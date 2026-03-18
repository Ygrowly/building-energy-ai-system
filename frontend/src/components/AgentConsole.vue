<template>
  <div class="console">
    <!-- ── Cursor 风格顶栏 ─────────────────────────────────────────── -->
    <div class="top-bar">
      <!-- 会话 Tab 列表（可横向滚动） -->
      <div class="tab-list" ref="tabListEl">
        <div
          v-for="sess in store.openTabs"
          :key="sess.session_id"
          class="tab"
          :class="{ active: sess.session_id === store.currentSessionId }"
          @click="store.switchSession(sess.session_id)"
        >
          <span class="tab-title">{{ sess.title }}</span>
          <span class="tab-fade"></span>
          <button
            class="tab-close"
            @click.stop="store.removeTab(sess.session_id)"
            title="关闭"
          >×</button>
        </div>
      </div>

      <!-- 右侧操作按钮组 -->
      <div class="top-actions">
        <!-- 新建对话 -->
        <button class="top-btn" @click="store.newSession()" title="新建对话">
          <Icon icon="mdi:plus" width="16" />
        </button>

        <!-- 历史记录 -->
        <button
          class="top-btn"
          :class="{ active: historyOpen }"
          @click="toggleHistory"
          title="历史记录"
        >
          <Icon icon="mdi:history" width="16" />
        </button>

        <!-- 更多操作 -->
        <div class="dropdown-wrap" ref="moreWrapEl">
          <button
            class="top-btn"
            :class="{ active: moreOpen }"
            @click="moreOpen = !moreOpen"
            title="更多"
          >
            <Icon icon="mdi:dots-horizontal" width="16" />
          </button>
          <Transition name="dropdown">
            <div class="dropdown-menu" v-if="moreOpen">
              <button class="menu-item" @click="onCloseChat">
                <Icon icon="mdi:close" width="14" />
                关闭会话
              </button>
              <div class="menu-divider" />
              <button class="menu-item danger" @click="onClearChat">
                <Icon icon="mdi:trash-can-outline" width="14" />
                清除消息
              </button>
            </div>
          </Transition>
        </div>
      </div>
    </div>

    <!-- ── 历史记录面板（绝对定位下拉） ─────────────────────────────── -->
    <Transition name="dropdown">
      <div class="history-panel" v-if="historyOpen" ref="historyPanelEl">
        <!-- 搜索框 -->
        <div class="history-search">
          <Icon icon="mdi:magnify" width="14" class="search-icon" />
          <input
            v-model="historySearch"
            placeholder="搜索对话..."
            class="search-input"
            @click.stop
          />
        </div>

        <!-- 分组列表 -->
        <div class="history-list">
          <!-- eslint-disable-next-line vue/no-v-for-template-key -->
          <template v-for="group in filteredHistoryGroups" :key="group.label">
            <div class="history-group-label">{{ group.label }}</div>
            <div
              v-for="sess in group.sessions"
              :key="sess.session_id"
              class="history-item"
              :class="{ renaming: renamingId === sess.session_id }"
              @click="renamingId !== sess.session_id && onHistoryClick(sess.session_id)"
            >
              <!-- 普通标题 -->
              <div
                v-if="renamingId !== sess.session_id"
                class="history-item-title"
              >{{ sess.title }}</div>

              <!-- 内联重命名输入框 -->
              <input
                v-else
                class="history-rename-input"
                v-model="renameValue"
                @keydown.enter.prevent="confirmRename"
                @keydown.esc.prevent="cancelRename"
                @blur="confirmRename"
                @click.stop
              />

              <!-- 右侧操作区（重命名时隐藏） -->
              <div v-if="renamingId !== sess.session_id" class="history-item-actions">
                <span class="h-check" :class="{ visible: sess.session_id === store.currentSessionId }">
                  <Icon icon="mdi:check" width="13" />
                </span>
                <button
                  class="h-action"
                  @click.stop="onRename(sess)"
                  title="重命名"
                ><Icon icon="mdi:pencil-outline" width="13" /></button>
                <button
                  class="h-action danger"
                  @click.stop="store.closeSession(sess.session_id)"
                  title="删除会话"
                ><Icon icon="mdi:trash-can-outline" width="13" /></button>
              </div>
            </div>
          </template>
          <div v-if="filteredHistoryGroups.length === 0" class="history-empty">
            未找到相关对话
          </div>
        </div>
      </div>
    </Transition>

    <!-- Agent 状态条 -->
    <Transition name="fade">
      <div class="agent-status-bar" v-if="store.currentAgentStatus">
        <span class="status-dot"></span>
        <span class="status-label">{{ store.currentAgentStatus.label }}</span>
        <span class="status-msg">{{ store.currentAgentStatus.message }}</span>
      </div>
    </Transition>

    <!-- 消息列表 -->
    <div class="messages" ref="messagesEl" @click="closeAllDropdowns">
      <div v-if="!store.hasMessages" class="empty-hint">
        <p class="hint-greeting"><Icon icon="mdi:hand-wave" width="16" class="inline-icon" /> 你好！我是你的建筑能源智能运维助手</p>
        <p class="hint-sub">可以用自然语言提问，支持数据查询、故障诊断与工单生成。</p>
        <div class="hint-examples">
          <p class="hint-group-label"><Icon icon="mdi:chart-bar" width="12" class="inline-icon" /> 数据查询</p>
          <button class="hint-chip" @click="quickSend('教学楼 2016 年 4 月 15 日的用电量是多少？')">
            教学楼 2016-04-15 用电量
          </button>
          <button class="hint-chip" @click="quickSend('对比三栋楼 2016 年 4 月的每日用电趋势')">
            多楼宇趋势对比
          </button>
          <p class="hint-group-label"><Icon icon="mdi:microscope" width="12" class="inline-icon" /> 故障诊断</p>
          <button class="hint-chip" @click="quickSend('办公楼 2016-04-15 凌晨 3 点的能耗有没有问题？帮我处理一下')">
            凌晨异常能耗诊断
          </button>
          <button class="hint-chip" @click="quickSend('计算教学楼 2016 年 4 月的制冷能效比 COP')">
            COP 计算
          </button>
          <p class="hint-group-label"><Icon icon="mdi:file-chart" width="12" class="inline-icon" /> 报表生成</p>
          <button class="hint-chip" @click="quickSend('帮我导出办公楼 2016-04-01 到 2016-05-01 的每日能耗报表')">
            导出能耗报表 CSV
          </button>
        </div>
      </div>

      <!-- eslint-disable-next-line vue/no-v-for-template-key -->
      <template v-for="msg in store.messages" :key="msg.id">
        <!-- 用户消息 -->
        <div class="msg msg-user" v-if="msg.role === 'user'">
          <div class="bubble user-bubble">{{ msg.content }}</div>
        </div>

        <!-- AI 文字回复 -->
        <template v-else-if="msg.role === 'ai'">
          <ThinkingBubble
            v-if="msg.thinkingSteps && msg.thinkingSteps.length > 0"
            :steps="msg.thinkingSteps"
            :is-finished="msg.thinkingFinished ?? false"
          />
          <div
            class="msg msg-ai"
            v-if="msg.content || (msg.thinkingFinished && store.isLoading)"
          >
            <div class="ai-avatar"><Icon icon="mdi:robot" width="14" /></div>
            <div class="ai-content">
              <div class="bubble ai-bubble">
                <span v-if="msg.content" v-html="formatMarkdown(msg.content)"></span>
                <span v-else class="stream-cursor"></span>
              </div>
              <EvidenceLink
                v-if="msg.artifact?.source_info"
                :source-info="toSourceInfo(msg.artifact.source_info)"
              />
            </div>
          </div>
        </template>

        <!-- Artifact：图表 -->
        <DynamicChart
          v-else-if="msg.role === 'artifact' && isChart(msg.artifact)"
          :artifact="msg.artifact"
        />

        <!-- Artifact：工单卡片 -->
        <WorkOrderCard
          v-else-if="msg.role === 'artifact' && isWorkOrder(msg.artifact)"
          :artifact="msg.artifact"
          :is-processing="store.isLoading"
          @approve="store.approveOrder(true)"
          @reject="(reason) => store.approveOrder(false, reason)"
        />

        <!-- Artifact：报表下载卡片 -->
        <ReportDownload
          v-else-if="msg.role === 'artifact' && isReportDownload(msg.artifact)"
          :artifact="msg.artifact"
        />

        <!-- 错误消息 -->
        <div class="msg msg-error" v-else-if="msg.role === 'error'">
          <div class="bubble error-bubble"><Icon icon="mdi:alert" width="14" class="inline-icon" /> {{ msg.content }}</div>
        </div>
      </template>

      <!-- 加载中光标 -->
      <div class="typing-indicator" v-if="store.isLoading">
        <span></span><span></span><span></span>
      </div>
    </div>

    <!-- 输入框 -->
    <div class="input-area">
      <div class="input-box" :class="{ focused: inputFocused, disabled: store.isLoading }">
        <textarea
          v-model="inputText"
          placeholder="输入您的问题，按 Enter 发送..."
          rows="2"
          @keydown.enter.exact.prevent="handleSend"
          @keydown.enter.shift.exact="inputText += '\n'"
          @focus="inputFocused = true"
          @blur="inputFocused = false"
          :disabled="store.isLoading"
        ></textarea>
        <div class="input-toolbar">
          <div class="toolbar-left">
            <button class="tag-btn" title="RAG 知识库">
              <Icon icon="mdi:database-search" width="12" />
              RAG 知识库
            </button>
            <button class="tag-btn" title="MCP 工具">
              <Icon icon="mdi:puzzle-outline" width="12" />
              MCP
            </button>
            <button
              class="tag-btn web-search-btn"
              :class="{ 'web-search-active': store.webSearchEnabled }"
              :title="store.webSearchEnabled ? '关闭联网搜索' : '开启联网搜索（Tavily）'"
              :disabled="store.isLoading"
              @click="store.toggleWebSearch()"
            >
              <Icon
                :icon="store.webSearchEnabled ? 'mdi:web-check' : 'mdi:web'"
                width="12"
              />
              联网搜索
              <span v-if="store.webSearchEnabled" class="web-search-dot"></span>
            </button>
          </div>
          <div class="toolbar-right">
            <button class="tool-btn" title="上传图片" @click="triggerUpload" :disabled="store.isLoading">
              <Icon icon="mdi:image-plus-outline" width="16" />
            </button>
            <input ref="fileInputEl" type="file" accept="image/*" style="display:none" @change="onFileChange" />
            <button class="send-icon-btn" @click="handleSend" :disabled="store.isLoading || !inputText.trim()" title="发送">
              <Icon v-if="store.isLoading" icon="mdi:timer-sand" width="14" />
              <Icon v-else icon="mdi:arrow-up" width="14" />
            </button>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, watch, nextTick, onMounted, onUnmounted } from 'vue'
import { Icon } from '@iconify/vue'
import { useChatStore } from '@/stores/chatStore'
import type { SessionInfo } from '@/stores/chatStore'
import ThinkingBubble from '@/generative-ui/ThinkingBubble.vue'
import DynamicChart from '@/generative-ui/DynamicChart.vue'
import WorkOrderCard from '@/generative-ui/WorkOrderCard.vue'
import ReportDownload from '@/generative-ui/ReportDownload.vue'
import EvidenceLink from '@/generative-ui/EvidenceLink.vue'
import type { ArtifactEvent } from '@/api/stream_client'

const store = useChatStore()
const inputText = ref('')
const inputFocused = ref(false)
const messagesEl = ref<HTMLElement>()
const tabListEl = ref<HTMLElement>()
const fileInputEl = ref<HTMLInputElement>()

function triggerUpload() {
  fileInputEl.value?.click()
}

function onFileChange(e: Event) {
  const file = (e.target as HTMLInputElement).files?.[0]
  if (file) {
    // 预留：可将图片追加到输入或发送
    console.log('selected file:', file.name)
  }
}

// ── 顶栏状态 ──────────────────────────────────────────────────────────────────
const historyOpen = ref(false)
const moreOpen = ref(false)
const historySearch = ref('')
const historyPanelEl = ref<HTMLElement>()
const moreWrapEl = ref<HTMLElement>()

function toggleHistory() {
  historyOpen.value = !historyOpen.value
  if (historyOpen.value) moreOpen.value = false
}

function closeAllDropdowns() {
  historyOpen.value = false
  moreOpen.value = false
}

// 点击外部关闭
function onDocClick(e: MouseEvent) {
  const target = e.target as Node
  if (historyPanelEl.value && !historyPanelEl.value.contains(target)) {
    // 排除 history 按钮自身（它有自己的 toggle 逻辑）
    historyOpen.value = false
  }
  if (moreWrapEl.value && !moreWrapEl.value.contains(target)) {
    moreOpen.value = false
  }
}
onMounted(() => {
  store.init()
  document.addEventListener('click', onDocClick, true)
})
onUnmounted(() => document.removeEventListener('click', onDocClick, true))

// ── 历史记录分组 ────────────────────────────────────────────────────────────
interface HistoryGroup { label: string; sessions: SessionInfo[] }

function daysBetween(a: Date, b: Date) {
  return Math.floor((b.getTime() - a.getTime()) / 86400000)
}

const filteredHistoryGroups = computed<HistoryGroup[]>(() => {
  const now = new Date()
  const q = historySearch.value.trim().toLowerCase()
  // 过滤：空会话（无消息）不进入历史
  const list = store.sessionList.filter((s: SessionInfo) =>
    s.message_count > 0 && (!q || s.title.toLowerCase().includes(q))
  )

  const groups: HistoryGroup[] = []
  const push = (label: string, sessions: SessionInfo[]) => {
    if (sessions.length) groups.push({ label, sessions })
  }

  const d = (s: SessionInfo) => daysBetween(new Date(s.updated_at), now)
  push('今天',      list.filter((s: SessionInfo) => d(s) === 0))
  push('昨天',      list.filter((s: SessionInfo) => d(s) === 1))
  push('最近 7 天', list.filter((s: SessionInfo) => d(s) >= 2 && d(s) < 7))
  push('更早',      list.filter((s: SessionInfo) => d(s) >= 7))

  return groups
})

function truncate(text: string, max: number) {
  return text.length > max ? text.slice(0, max) + '…' : text
}

function formatSessionTime(iso: string) {
  return new Date(iso).toLocaleString('zh-CN', {
    month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit',
  })
}

function onHistoryClick(id: string) {
  store.switchSession(id)
  historyOpen.value = false
}

// ── 内联重命名 ────────────────────────────────────────────────────────────
const renamingId = ref<string | null>(null)
const renameValue = ref('')
let _renameOriginal = ''

// renamingId 变化后仅聚焦一次，不用 :ref 避免每次重渲都触发
watch(renamingId, async (id) => {
  if (!id) return
  await nextTick()
  const input = document.querySelector<HTMLInputElement>('.history-rename-input')
  if (input) {
    input.focus()
    const len = input.value.length
    input.setSelectionRange(len, len)
  }
})

function onRename(sess: SessionInfo) {
  renamingId.value = sess.session_id
  renameValue.value = sess.title
  _renameOriginal = sess.title
}

async function confirmRename() {
  if (!renamingId.value) return
  const id = renamingId.value
  const newTitle = renameValue.value.trim()
  renamingId.value = null
  if (newTitle && newTitle !== _renameOriginal) {
    await store.renameSession(id, newTitle)
  }
}

function cancelRename() {
  renamingId.value = null
}

// ── 顶栏菜单操作 ────────────────────────────────────────────────────────────
function onCloseChat() {
  moreOpen.value = false
  if (store.currentSessionId) store.closeSession(store.currentSessionId)
}

function onClearChat() {
  moreOpen.value = false
  store.clearSession()
}

// ── 发送消息 ────────────────────────────────────────────────────────────────
function handleSend() {
  if (!inputText.value.trim() || store.isLoading) return
  store.sendMessage(inputText.value.trim())
  inputText.value = ''
}

function quickSend(text: string) {
  if (store.isLoading) return
  store.sendMessage(text)
}

// ── 自动滚动 ────────────────────────────────────────────────────────────────
watch(
  [
    () => store.messages.length,
    () => {
      const last = store.messages[store.messages.length - 1]
      return last?.thinkingSteps?.length ?? 0
    },
    () => {
      const last = store.messages[store.messages.length - 1]
      return last?.content?.length ?? 0
    },
  ],
  async () => {
    await nextTick()
    if (messagesEl.value) messagesEl.value.scrollTop = messagesEl.value.scrollHeight
  },
)

// 切换会话时也滚动到底部
watch(() => store.currentSessionId, async () => {
  await nextTick()
  if (messagesEl.value) messagesEl.value.scrollTop = messagesEl.value.scrollHeight
})

// ── Artifact 类型判断 ────────────────────────────────────────────────────────
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

function toSourceInfo(v: unknown): Record<string, unknown> {
  return v as Record<string, unknown>
}

// ── Markdown 渲染 ────────────────────────────────────────────────────────────
function formatMarkdown(text: string): string {
  return text
    .replace(/^---+$/gm, '<hr style="border:none;border-top:1px solid var(--border);margin:6px 0"/>')
    .replace(/^### (.+)$/gm,
      '<span style="display:block;font-size:12px;font-weight:700;color:var(--accent);margin:6px 0 2px">$1</span>')
    .replace(/^## (.+)$/gm,
      '<span style="display:block;font-size:13px;font-weight:700;color:var(--text-primary);margin:7px 0 3px;border-bottom:1px solid var(--border);padding-bottom:2px">$1</span>')
    .replace(/^# (.+)$/gm,
      '<span style="display:block;font-size:14px;font-weight:700;color:var(--text-primary);margin:8px 0 3px">$1</span>')
    .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
    .replace(/(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)/g, '<em>$1</em>')
    .replace(/`([^`]+)`/g,
      '<code style="background:rgba(108,142,245,0.15);padding:1px 5px;border-radius:3px;font-family:monospace;font-size:0.9em">$1</code>')
    .replace(/^[ \t]*[-*] (.+)$/gm,
      '<span style="display:block;padding-left:14px;margin:1px 0;position:relative"><span style="position:absolute;left:4px;color:var(--accent)">•</span>$1</span>')
    .replace(/^[ \t]*(\d+)\. (.+)$/gm,
      '<span style="display:block;padding-left:20px;margin:1px 0;position:relative"><span style="position:absolute;left:4px;color:var(--text-secondary)">$1.</span>$2</span>')
    .replace(/\n{2,}/g, '<br/>')
    .replace(/\n/g, '<br/>')
}
</script>

<style scoped>
.console {
  display: flex;
  flex-direction: column;
  height: 100%;
  background: var(--bg-panel);
  border-left: 1px solid var(--border);
  position: relative;
  overflow: hidden;
}

/* ── 顶栏（Cursor 风格：无底部线，圆角浮动 Tab） ────────────────────────── */
.top-bar {
  display: flex;
  align-items: center;   /* 垂直居中，为圆角 pill 效果留出上下空间 */
  flex-shrink: 0;
  background: var(--bg-panel);
  min-height: 38px;
  /* 无底部分隔线 */
}

/* Tab 列表 */
.tab-list {
  display: flex;
  align-items: center;
  overflow-x: auto;
  flex: 1;
  scrollbar-width: none;
  padding: 0 4px;
  gap: 2px;
}
.tab-list::-webkit-scrollbar { display: none; }

.tab {
  display: flex;
  align-items: center;
  gap: 0;
  /* 内容自适应宽度，最大 160px */
  width: fit-content;
  min-width: 0;
  max-width: 160px;
  height: 24px;
  padding: 0 10px;
  cursor: pointer;
  color: var(--text-secondary);
  font-size: 12px;
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', system-ui, sans-serif;
  font-weight: 400;
  letter-spacing: 0.01em;
  white-space: nowrap;
  border-radius: 6px;   /* 四周圆角 */
  transition: background 0.12s, color 0.12s;
  position: relative;
  flex-shrink: 0;
  overflow: hidden;
}
.tab:hover {
  background: rgba(255,255,255,0.06);
  color: var(--text-primary);
}
.tab.active {
  background: rgba(255,255,255,0.1);
  color: var(--text-primary);
  font-weight: 500;
}

/* light 主题下选中 Tab */
html[data-theme="light"] .tab:hover {
  background: rgba(0,0,0,0.05);
}
html[data-theme="light"] .tab.active {
  background: rgba(0,0,0,0.08);
}

.tab-title {
  /* 自适应宽度，不超过 max-width */
  overflow: hidden;
  white-space: nowrap;
  /* 不用 text-overflow ellipsis，由渐变遮罩处理视觉截断 */
}

/* 渐变遮罩：hover 时从透明→tab背景色，覆盖标题末尾 */
.tab-fade {
  position: absolute;
  right: 0;
  top: 0;
  bottom: 0;
  width: 0;
  opacity: 0;
  pointer-events: none;
  transition: opacity 0.15s, width 0.15s;
}
/* 暗色主题：hover 渐变深色遮罩 */
.tab:hover .tab-fade {
  opacity: 1;
  width: 40px;
  background: linear-gradient(to right, transparent, #15161e);
}
.tab.active .tab-fade {
  /* active 状态常驻渐变，等待 hover */
  background: linear-gradient(to right, transparent, #1a1b24);
}
.tab.active:hover .tab-fade {
  opacity: 1;
  width: 40px;
  background: linear-gradient(to right, transparent, #1a1b24);
}

/* 亮色主题 */
html[data-theme="light"] .tab:hover .tab-fade {
  background: linear-gradient(to right, transparent, #eef0f4);
}
html[data-theme="light"] .tab.active .tab-fade {
  background: linear-gradient(to right, transparent, #e4e7ed);
}
html[data-theme="light"] .tab.active:hover .tab-fade {
  background: linear-gradient(to right, transparent, #e4e7ed);
}

/* 叉号：绝对定位，默认隐藏，hover 时出现在渐变上层 */
.tab-close {
  position: absolute;
  right: 0;
  top: 50%;
  transform: translateY(-50%);
  background: none;
  border: none;
  cursor: pointer;
  color: var(--text-secondary);
  font-size: 18px;
  line-height: 1;
  padding: 0;
  border-radius: 4px;
  display: flex;
  align-items: center;
  justify-content: center;
  width: 26px;
  height: 26px;
  opacity: 0;
  z-index: 1;
  transition: opacity 0.15s, color 0.12s;
}
/* 只在 hover 时显示，active 不自动显示 */
.tab:hover .tab-close { opacity: 0.7; }
.tab-close:hover { opacity: 1 !important; color: var(--text-primary); }

/* 右侧操作按钮（无左侧边框） */
.top-actions {
  display: flex;
  align-items: center;
  padding: 0 6px;
  gap: 1px;
  flex-shrink: 0;
  /* 无 border-left */
}

.top-btn {
  background: none;
  border: none;
  cursor: pointer;
  color: var(--text-secondary);
  display: flex;
  align-items: center;
  justify-content: center;
  width: 26px;
  height: 26px;
  border-radius: 4px;
  transition: color 0.12s;
  opacity: 0.7;
}
.top-btn:hover { color: var(--text-primary); opacity: 1; }
.top-btn.active { color: var(--accent); opacity: 1; }

/* 下拉菜单 */
.dropdown-wrap { position: relative; }

.dropdown-menu {
  position: absolute;
  top: calc(100% + 4px);
  right: 0;
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 4px;
  min-width: 150px;
  box-shadow: 0 8px 24px rgba(0,0,0,0.15);
  z-index: 200;
}

.menu-item {
  display: flex;
  align-items: center;
  gap: 8px;
  width: 100%;
  background: none;
  border: none;
  cursor: pointer;
  padding: 7px 10px;
  border-radius: 5px;
  font-size: 13px;
  color: var(--text-secondary);
  text-align: left;
  transition: background 0.15s, color 0.15s;
}
.menu-item:hover { background: var(--bg-hover); color: var(--text-primary); }
.menu-item.danger:hover { background: rgba(248,113,113,0.08); color: var(--danger, #f87171); }

.menu-divider { height: 1px; background: var(--border); margin: 4px 0; }

/* ── 历史记录面板 ─────────────────────────────────────────────────────────── */
.history-panel {
  position: absolute;
  top: 42px;
  right: 0;
  width: 280px;
  max-height: 420px;
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: 8px;
  box-shadow: 0 8px 28px rgba(0,0,0,0.18);
  z-index: 200;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.history-search {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 12px;
  flex-shrink: 0;
  /* 无分割线 */
}

.search-icon { color: var(--text-muted); flex-shrink: 0; }

.search-input {
  flex: 1;
  background: none;
  border: none;
  outline: none;
  font-size: 13px;
  color: var(--text-primary);
}
.search-input::placeholder { color: var(--text-muted); }

.history-list {
  overflow-y: auto;
  flex: 1;
  padding: 4px 0;
}

.history-group-label {
  font-size: 11px;
  font-weight: 600;
  color: var(--text-muted);
  text-transform: uppercase;
  letter-spacing: 0.06em;
  padding: 8px 12px 4px;
}

.history-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 6px;
  padding: 6px 8px;
  cursor: pointer;
  border-radius: 5px;
  margin: 0 4px;
  transition: background 0.15s;
}
.history-item:hover { background: rgba(108,142,245,0.08); }
/* 无持久选中背景，仅用打勾区分当前会话 */

.history-item-title {
  flex: 1;
  font-size: 13px;
  color: var(--text-primary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

/* 内联重命名输入框 */
.history-rename-input {
  flex: 1;
  font-size: 13px;
  color: var(--text-primary);
  background: var(--bg-card);
  border: 1px solid var(--accent);
  border-radius: 4px;
  padding: 1px 6px;
  outline: none;
  min-width: 0;
  font-family: inherit;
}

.history-item.renaming {
  background: rgba(108,142,245,0.06);
}

/* 右侧操作区 */
.history-item-actions {
  display: flex;
  align-items: center;
  gap: 1px;
  flex-shrink: 0;
}

/* 打勾：右侧，仅当前会话显示，hover 时与操作按钮并列 */
.h-check {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 20px;
  height: 20px;
  flex-shrink: 0;
  color: var(--accent);
  opacity: 0;
  transition: opacity 0.12s;
}
.h-check.visible { opacity: 1; }

/* 操作按钮：默认隐藏，hover 时出现 */
.h-action {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 20px;
  height: 20px;
  background: none;
  border: none;
  cursor: pointer;
  color: var(--text-muted);
  border-radius: 3px;
  opacity: 0;
  transition: opacity 0.12s, color 0.12s, background 0.12s;
}
.history-item:hover .h-action { opacity: 1; }
.h-action:hover { color: var(--text-primary); background: rgba(255,255,255,0.08); }
.h-action.danger:hover { color: var(--danger, #f87171); background: rgba(248,113,113,0.1); }

.history-empty {
  padding: 24px 12px;
  text-align: center;
  font-size: 13px;
  color: var(--text-muted);
}

/* ── Agent 状态条 ────────────────────────────────────────────────────────── */
.agent-status-bar {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 16px;
  background: var(--accent-glow);
  border-bottom: 1px solid var(--border-accent);
  font-size: 12px;
  flex-shrink: 0;
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

/* ── 消息区 ─────────────────────────────────────────────────────────────── */
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
  display: flex;
  align-items: center;
  gap: 4px;
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
  box-shadow: var(--card-shadow);
}
.hint-chip:hover {
  background: var(--accent-glow);
  border-color: var(--border-accent);
  color: var(--accent);
  box-shadow: var(--card-shadow-hover);
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

.msg-ai .bubble {
  max-width: 100%;
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
  color: var(--accent);
  flex-shrink: 0;
}

.ai-content {
  display: flex;
  flex-direction: column;
  gap: 4px;
  width: 90%;
  min-width: 0;
}

.ai-bubble {
  background: var(--bg-card);
  color: var(--text-primary);
  border: 1px solid var(--border);
  border-radius: 2px 12px 12px 12px;
  max-width: 100%;
}

.error-bubble {
  background: rgba(248,113,113,0.1);
  color: var(--danger);
  border: 1px solid rgba(248,113,113,0.3);
}

.stream-cursor {
  display: inline-block;
  width: 2px;
  height: 14px;
  background: var(--accent);
  vertical-align: middle;
  border-radius: 1px;
  animation: blink-cursor 0.9s infinite;
}
@keyframes blink-cursor { 0%, 100% { opacity: 1; } 50% { opacity: 0; } }

.typing-indicator { display: flex; gap: 4px; padding: 8px 14px; }
.typing-indicator span {
  width: 6px; height: 6px;
  border-radius: 50%;
  background: var(--accent);
  animation: bounce 1.2s infinite;
}
.typing-indicator span:nth-child(2) { animation-delay: 0.2s; }
.typing-indicator span:nth-child(3) { animation-delay: 0.4s; }
@keyframes bounce { 0%, 80%, 100% { transform: translateY(0); } 40% { transform: translateY(-6px); } }

/* ── 输入框 ─────────────────────────────────────────────────────────────── */
.input-area {
  padding: 0 12px 16px;
  flex-shrink: 0;
}

.input-box {
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: 10px;
  display: flex;
  flex-direction: column;
  transition: border-color 0.2s, box-shadow 0.2s;
}
.input-box.focused {
  border-color: var(--accent);
  box-shadow: 0 0 0 2px rgba(108, 142, 245, 0.12);
}
.input-box.disabled { opacity: 0.55; }

textarea {
  flex: 1;
  background: transparent;
  border: none;
  color: var(--text-primary);
  padding: 9px 12px 5px;
  font-size: 13px;
  resize: none;
  font-family: inherit;
  line-height: 1.5;
  outline: none;
  min-height: 48px;
}
textarea::placeholder { color: var(--text-muted); }

/* ── 工具栏 ─────────────────────────────────────────────── */
.input-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 5px 8px 6px;
}

.toolbar-left {
  display: flex;
  align-items: center;
  gap: 4px;
}

.tag-btn {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  background: none;
  border: 1px solid var(--border);
  border-radius: 5px;
  color: var(--text-muted);
  font-size: 11px;
  font-family: inherit;
  padding: 2px 7px;
  cursor: pointer;
  transition: color 0.15s, border-color 0.15s, background 0.15s;
  white-space: nowrap;
}
.tag-btn:hover {
  color: var(--text-primary);
  border-color: var(--accent);
  background: rgba(108, 142, 245, 0.06);
}

.web-search-btn {
  position: relative;
}

.web-search-active {
  color: var(--accent);
  border-color: var(--accent);
  background: rgba(108, 142, 245, 0.1);
}

.web-search-active:hover {
  background: rgba(108, 142, 245, 0.16);
}

.web-search-dot {
  display: inline-block;
  width: 5px;
  height: 5px;
  border-radius: 50%;
  background: #22c55e;
  margin-left: 2px;
  vertical-align: middle;
  flex-shrink: 0;
  animation: pulse-dot 2s ease-in-out infinite;
}

@keyframes pulse-dot {
  0%, 100% { opacity: 1; transform: scale(1); }
  50% { opacity: 0.6; transform: scale(0.8); }
}

.toolbar-right {
  display: flex;
  align-items: center;
  gap: 4px;
}

.tool-btn {
  width: 28px;
  height: 28px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: none;
  border: none;
  cursor: pointer;
  color: var(--text-muted);
  border-radius: 5px;
  transition: color 0.15s, background 0.15s;
}
.tool-btn:hover { color: var(--text-primary); background: rgba(108, 142, 245, 0.08); }
.tool-btn:disabled { opacity: 0.4; cursor: not-allowed; }

.send-icon-btn {
  width: 28px;
  height: 28px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--accent);
  border: none;
  border-radius: 50%;
  color: #fff;
  cursor: pointer;
  transition: opacity 0.15s;
  flex-shrink: 0;
}
.send-icon-btn:hover { opacity: 0.85; }
.send-icon-btn:disabled { opacity: 0.35; cursor: not-allowed; }

/* ── 通用过渡动画 ───────────────────────────────────────────────────────── */
.fade-enter-active, .fade-leave-active { transition: all 0.3s; }
.fade-enter-from, .fade-leave-to { opacity: 0; transform: translateY(-8px); }

.dropdown-enter-active, .dropdown-leave-active { transition: all 0.18s ease; }
.dropdown-enter-from, .dropdown-leave-to { opacity: 0; transform: translateY(-6px) scale(0.97); }

.inline-icon { vertical-align: middle; margin-right: 4px; }
</style>
