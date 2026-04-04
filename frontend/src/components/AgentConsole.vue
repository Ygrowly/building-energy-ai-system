<template>
  <div class="console">
    <!-- ── Cursor 风格顶栏 ─────────────────────────────────────────── -->
    <div class="top-bar">
      <!-- 会话 Tab 列表（可横向滚动） -->
      <div class="tab-list-wrap" @mouseenter="tabHover = true" @mouseleave="tabHover = false">
        <div class="tab-list" ref="tabListEl" @scroll="updateScrollThumb">
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
        <!-- 自定义滚动条（始终占位，hover 才显示滑块） -->
        <div class="custom-scrollbar" v-if="scrollThumb.show" @click="onTrackClick">
          <div
            class="custom-thumb"
            :class="{ visible: tabHover || tabDragging, dragging: tabDragging }"
            :style="{ left: scrollThumb.left + '%', width: scrollThumb.width + '%' }"
            @mousedown.stop="onThumbDown"
          ></div>
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

        <!-- 导出报表 -->
        <button
          class="top-btn"
          :class="{ active: reportMenuOpen || reportGenerating }"
          :title="reportButtonTitle"
          :disabled="reportGenerating || (!isPageReportMode && !store.currentSessionId)"
          :aria-label="reportButtonTitle"
          data-report-trigger="true"
          @click="onReportBtnClick"
        >
          <Icon icon="mdi:file-chart-outline" width="16" />
        </button>

        <Transition name="dropdown">
          <div
            v-if="reportMenuOpen && !isPageReportMode"
            ref="reportWrapEl"
            class="dropdown-menu report-template-floating"
          >
            <div class="report-template-title">选择报表模板</div>
            <button
              v-for="template in conversationReportTemplates"
              :key="template.id"
              class="menu-item report-template-item"
              :disabled="reportGenerating"
              @click="onSelectReportTemplate(template.id)"
            >
              <div class="report-template-copy">
                <div class="report-template-label">
                  <span>{{ template.label }}</span>
                  <span v-if="template.default" class="report-template-badge">默认</span>
                </div>
                <div class="report-template-desc">{{ template.description }}</div>
              </div>
            </button>
          </div>
        </Transition>

        <!-- 更多操作 -->
        <div class="dropdown-wrap" ref="moreWrapEl">
          <button
            class="top-btn"
            :class="{ active: moreOpen }"
            @click="toggleMoreMenu"
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
              <button
                class="menu-item report-export-menu-item"
                :disabled="reportGenerating || !store.currentSessionId"
                @click="onExportConversation()"
              >
                <Icon icon="mdi:file-chart-outline" width="14" />
                <span>{{ reportGenerating ? '生成报表中...' : '导出对话报表' }}</span>
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
        <span class="status-dot" :style="{ background: agentDotColor(store.currentAgentStatus.name) }"></span>
        <span class="status-label" :style="{ color: agentDotColor(store.currentAgentStatus.name) }">{{ store.currentAgentStatus.label }}</span>
        <span class="status-msg">{{ store.currentAgentStatus.message }}</span>
      </div>
    </Transition>

    <!-- 消息列表 -->
    <div class="messages" ref="messagesEl" @click="onMessagesClick">
      <div v-if="!store.hasMessages" class="empty-hint">
        <p class="hint-greeting"><Icon icon="mdi:hand-wave" width="16" class="inline-icon" /> 你好！我是你的建筑能源智能运维助手</p>
        <p class="hint-sub">可以用自然语言提问，支持数据查询、故障诊断与工单生成。</p>
        <div class="hint-examples">
          <p class="hint-group-label"><Icon icon="mdi:chart-bar" width="12" class="inline-icon" /> 数据查询</p>
          <button class="hint-chip" @click="quickSend(`教学楼 ${dataRangeStore.defaultStart} 的用电量是多少？`)">
            教学楼单日用电量
          </button>
          <button class="hint-chip" @click="quickSend(`对比三栋楼 ${dataRangeStore.defaultStart} 到 ${dataRangeStore.defaultEnd} 的每日用电趋势`)">
            多楼宇趋势对比
          </button>
          <p class="hint-group-label"><Icon icon="mdi:microscope" width="12" class="inline-icon" /> 故障诊断</p>
          <button class="hint-chip" @click="quickSend(`办公楼 ${dataRangeStore.defaultStart} 凌晨 3 点的能耗有没有问题？帮我处理一下`)">
            凌晨异常能耗诊断
          </button>
          <button class="hint-chip" @click="quickSend(`计算教学楼 ${dataRangeStore.defaultStart} 到 ${dataRangeStore.defaultEnd} 的制冷能效比 COP`)">
            COP 计算
          </button>
          <p class="hint-group-label"><Icon icon="mdi:file-chart" width="12" class="inline-icon" /> 报表生成</p>
          <button class="hint-chip" @click="quickSend(`帮我导出办公楼 ${dataRangeStore.defaultStart} 到 ${dataRangeStore.defaultEnd} 的每日能耗报表`)">
            导出能耗报表 CSV
          </button>
        </div>
      </div>

      <!-- eslint-disable-next-line vue/no-v-for-template-key -->
      <template v-for="(msg, mIdx) in store.messages" :key="msg.id">
        <!-- 用户消息 -->
        <div class="msg msg-user" v-if="msg.role === 'user'">
          <div class="user-bubble">{{ msg.content }}</div>
        </div>

        <!-- AI 文字回复（支持内嵌图表/卡片） -->
        <template v-else-if="msg.role === 'ai'">
          <ThinkingBubble
            v-if="msg.thinkingSteps && (msg.thinkingSteps.length > 0 || msg.thinkingFinished === false)"
            :steps="msg.thinkingSteps"
            :is-finished="msg.thinkingFinished ?? false"
            :duration="msg.thinkingDuration"
            :start-time="msg.thinkingStartTime"
          />
          <div
            class="msg msg-ai"
            v-if="msg.content || (msg.thinkingFinished && store.isLoading)"
            :data-msg-id="msg.id"
          >
            <div class="ai-content">
              <div class="ai-bubble">
                <!-- 分片渲染：文字段落 / 占位条 / 骨架屏 / 图表 交替显示 -->
                <!-- eslint-disable-next-line vue/no-v-for-template-key -->
                <template v-for="(seg, sIdx) in buildInlineSegments(msg)">
                  <!-- 文字片段 -->
                  <div v-if="seg.type === 'text'" :key="'t'+sIdx" class="md-block" v-html="formatMarkdown(seg.text || '')"></div>

                  <!-- 流式阶段：anchor 已检测到但 artifact 尚未到达 → 骨架屏 -->
                  <div v-else-if="seg.type === 'placeholder'" :key="'p'+sIdx" class="inline-artifact-wrap placeholder-phase">
                    <Transition name="skeleton-in" appear>
                      <ChartSkeleton />
                    </Transition>
                  </div>

                  <!-- 图表：非流式直接渲染 / 流式中 active→骨架屏 / ready→真实图 -->
                  <div
                    v-else-if="seg.type === 'chart'"
                    :key="'c'+sIdx"
                    class="inline-artifact-wrap"
                  >
                    <Transition name="chart-in" mode="out-in">
                      <div
                        v-if="!(store.isLoading && msg.id === lastAiMsgId) || readySet.has(seg.artifactId ?? '')"
                        :key="'real-'+seg.artifactId"
                        class="chart-reveal-inner"
                      >
                        <DynamicChart
                          v-if="seg.artifact && isChart(seg.artifact)"
                          :artifact="ensureArtifact(seg.artifact)"
                          :inline="true"
                          :skip-skeleton="true"
                        />
                        <ValueCard
                          v-else-if="seg.artifact && isValueCard(seg.artifact)"
                          :artifact="ensureArtifact(seg.artifact)"
                          :inline="true"
                        />
                      </div>
                      <div v-else :key="'skel-'+seg.artifactId">
                        <ChartSkeleton />
                      </div>
                    </Transition>
                  </div>
                </template>
                <span
                  v-if="store.isLoading && msg.id === lastAiMsgId"
                  class="stream-cursor"
                ></span>
                <span v-if="!msg.content && !store.isLoading" class="stream-cursor"></span>
              </div>
              <EvidenceLink
                v-if="msg.artifact?.source_info"
                :source-info="toSourceInfo(msg.artifact.source_info)"
              />
              <!-- 知识溯源：引用来源卡片 -->
              <div
                v-if="msg.evidenceSources?.length"
                class="evidence-sources"
              >
                <div class="evidence-header" @click="($event.currentTarget as HTMLElement)?.parentElement?.classList.toggle('open')">
                  <Icon icon="mdi:book-open-page-variant-outline" width="14" />
                  <span>引用来源 ({{ msg.evidenceSources.length }})</span>
                  <Icon icon="mdi:chevron-down" width="14" class="evidence-chevron" />
                </div>
                <div class="evidence-list">
                  <div
                    v-for="(src, sIdx) in msg.evidenceSources"
                    :key="sIdx"
                    class="evidence-item"
                  >
                    <Icon icon="mdi:file-document-outline" width="13" class="evidence-file-icon" />
                    <span class="evidence-doc">{{ src.source_doc }}</span>
                    <span v-if="src.page" class="evidence-page">P.{{ src.page }}</span>
                    <span v-if="src.similarity" class="evidence-score">{{ (src.similarity * 100).toFixed(0) }}%</span>
                  </div>
                </div>
              </div>
              <!-- 互动操作栏 -->
              <div class="msg-actions" v-if="msg.content && !store.isLoading">
                <button
                  class="msg-action-btn"
                  :class="{ copied: copiedMsgId === msg.id }"
                  @click="copyMessage(msg)"
                  :title="copiedMsgId === msg.id ? '已复制' : '复制'"
                >
                  <Icon :icon="copiedMsgId === msg.id ? 'mdi:check' : 'mdi:content-copy'" width="12" />
                </button>
                <button
                  class="msg-action-btn"
                  :class="{ active: msg.liked === true }"
                  @click="toggleLike(msg, true)"
                  title="有帮助"
                >
                  <Icon :icon="msg.liked === true ? 'mdi:thumb-up' : 'mdi:thumb-up-outline'" width="12" />
                </button>
                <button
                  class="msg-action-btn"
                  :class="{ active: msg.liked === false }"
                  @click="toggleLike(msg, false)"
                  title="没帮助"
                >
                  <Icon :icon="msg.liked === false ? 'mdi:thumb-down' : 'mdi:thumb-down-outline'" width="12" />
                </button>
                <button
                  class="msg-action-btn"
                  @click="regenerate(msg)"
                  title="重新生成"
                >
                  <Icon icon="mdi:refresh" width="16" />
                </button>
              </div>
            </div>
          </div>
        </template>

        <!-- 兜底：独立 Artifact（工单/报表，或无 AI 消息时的图表） -->
        <!-- 已内嵌到 AI 气泡中的图表/卡片不再独立渲染 -->

        <!-- Artifact：数值卡片 -->
        <ValueCard
          v-else-if="msg.role === 'artifact' && isValueCard(msg.artifact) && !isArtifactInlined(msg, mIdx)"
          :artifact="ensureArtifact(msg.artifact)"
        />

        <!-- Artifact：图表 -->
        <DynamicChart
          v-else-if="msg.role === 'artifact' && isChart(msg.artifact) && !isArtifactInlined(msg, mIdx)"
          :artifact="ensureArtifact(msg.artifact)"
        />

        <!-- Artifact：工单卡片 -->
        <WorkOrderCard
          v-else-if="msg.role === 'artifact' && isWorkOrder(msg.artifact)"
          :artifact="ensureArtifact(msg.artifact)"
          :is-processing="store.isLoading"
          @approve="store.approveOrder(true)"
          @reject="(reason) => store.approveOrder(false, reason)"
        />

        <!-- Artifact：报表下载卡片（需有有效 download_url） -->
        <ReportDownload
          v-else-if="msg.role === 'artifact' && isReportDownload(msg.artifact) && msg.artifact?.download_url"
          :artifact="ensureArtifact(msg.artifact)"
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
        <!-- 选中元素上下文标签 -->
        <div v-if="pickerStore.selectedElement" class="picked-context">
          <Icon icon="mdi:target" width="14" class="picked-icon" />
          <span class="picked-label">{{ pickerStore.selectedElement.title }}</span>
          <button class="picked-close" @click="pickerStore.clearSelection()">×</button>
        </div>
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
            <button
              class="tool-btn"
              :class="{ active: pickerStore.isPickerActive }"
              @click="pickerStore.togglePicker()"
              title="选择页面元素"
            >
              <Icon icon="mdi:cursor-default-click-outline" width="18" />
            </button>
            <div class="thinking-mode-dropdown" :class="{ disabled: store.isLoading }">
              <button
                class="tag-btn thinking-mode-trigger"
                :class="{ 'thinking-mode-deep': store.thinkingMode === 'deep' }"
                :disabled="store.isLoading"
                @click="showThinkingModeMenu = !showThinkingModeMenu"
              >
                <Icon
                  :icon="store.thinkingMode === 'deep' ? 'mdi:brain' : 'mdi:flash'"
                  width="16"
                />
                {{ store.thinkingMode === 'deep' ? '深度思考' : '快速' }}
                <Icon icon="mdi:chevron-up" width="14" class="dropdown-arrow" :class="{ open: showThinkingModeMenu }" />
              </button>
              <Transition name="dropdown-fade">
                <div v-if="showThinkingModeMenu" class="thinking-mode-menu" @click.stop>
                  <button
                    class="thinking-mode-option"
                    :class="{ active: store.thinkingMode === 'fast' }"
                    @click="store.thinkingMode = 'fast'; showThinkingModeMenu = false"
                  >
                    <Icon icon="mdi:flash" width="16" />
                    <div class="option-info">
                      <span class="option-label">快速</span>
                      <span class="option-desc">响应更快，适合日常查询</span>
                    </div>
                    <Icon v-if="store.thinkingMode === 'fast'" icon="mdi:check" width="16" class="option-check" />
                  </button>
                  <button
                    class="thinking-mode-option"
                    :class="{ active: store.thinkingMode === 'deep' }"
                    @click="store.thinkingMode = 'deep'; showThinkingModeMenu = false"
                  >
                    <Icon icon="mdi:brain" width="16" />
                    <div class="option-info">
                      <span class="option-label">深度思考</span>
                      <span class="option-desc">更精准的分析，适合复杂问题</span>
                    </div>
                    <Icon v-if="store.thinkingMode === 'deep'" icon="mdi:check" width="16" class="option-check" />
                  </button>
                </div>
              </Transition>
            </div>
            <button class="tag-btn" title="MCP 工具">
              <Icon icon="mdi:puzzle-outline" width="18" />
              MCP
            </button>
            <button class="tag-btn" title="RAG 知识库" @click="router.push('/datacenter?tab=knowledge')">
              <Icon icon="mdi:database-search" width="16" />
              RAG 知识库
            </button>
          </div>
          <div class="toolbar-right">
            <button
              class="tool-btn web-search-btn"
              :class="{ 'web-search-active': store.webSearchEnabled }"
              :title="store.webSearchEnabled ? '关闭联网搜索' : '开启联网搜索（Agent 自主决策补充 RAG 不足信息）'"
              :disabled="store.isLoading"
              @click="store.toggleWebSearch()"
            >
              <Icon
                :icon="store.webSearchEnabled ? 'mdi:web-check' : 'mdi:web'"
                width="16"
              />
              <span v-if="store.webSearchEnabled" class="web-search-dot"></span>
            </button>
            <button class="tool-btn" title="上传图片" @click="triggerUpload" :disabled="store.isLoading">
              <Icon icon="mdi:image-plus-outline" width="16" />
            </button>
            <input ref="fileInputEl" type="file" accept="image/*" style="display:none" @change="onFileChange" />
            <button
              v-if="store.isLoading"
              class="send-icon-btn stop-btn"
              @click="store.stopGeneration()"
              title="终止生成"
            >
              <Icon icon="mdi:stop" width="16" />
            </button>
            <button
              v-else
              class="send-icon-btn"
              :class="{ active: inputText.trim() }"
              @click="handleSend"
              :disabled="!inputText.trim()"
              title="发送"
            >
              <Icon icon="mdi:arrow-up" width="16" style="transform: scaleY(1.3)" />
            </button>
          </div>
        </div>
      </div>
    </div>

    <Transition name="fade">
      <div
        v-if="reportGenerating"
        class="report-generating-overlay"
        aria-live="polite"
        aria-busy="true"
      >
        <div class="report-generating-card">
          <Icon icon="mdi:loading" width="28" class="spin report-generating-spinner" />
          <div class="report-generating-title">正在生成报表</div>
          <div class="report-generating-desc">
            {{ activeReportTemplate?.label || 'AI辅助研判会话纪要' }}
          </div>
        </div>
      </div>
    </Transition>

    <Transition name="fade">
      <div v-if="rawDataPreview" class="raw-data-overlay" @click.self="closeRawDataPreview">
        <div class="raw-data-modal">
          <div class="raw-data-header">
            <div>
              <div class="raw-data-title">原始数据快照</div>
              <div class="raw-data-subtitle">
                {{ rawDataMeta }}
              </div>
            </div>
            <button class="raw-data-close" @click="closeRawDataPreview">
              <Icon icon="mdi:close" width="18" />
            </button>
          </div>
          <div class="raw-data-body">
            <div v-if="rawDataRows.length" class="raw-data-table-wrap">
              <table class="raw-data-table">
                <thead>
                  <tr>
                    <th>时间</th>
                    <th>指标</th>
                    <th>数值</th>
                    <th>单位</th>
                  </tr>
                </thead>
                <tbody>
                  <tr v-for="(row, idx) in rawDataRows" :key="idx">
                    <td>{{ row.timestamp }}</td>
                    <td>{{ row.metric }}</td>
                    <td>{{ row.value }}</td>
                    <td>{{ row.unit }}</td>
                  </tr>
                </tbody>
              </table>
            </div>
            <div v-else class="raw-data-empty">
              当前回复没有可展示的原始数据快照。
            </div>
          </div>
        </div>
      </div>
    </Transition>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, computed, watch, nextTick, onMounted, onUnmounted } from 'vue'
import { Icon } from '@iconify/vue'
import { useRouter } from 'vue-router'
import { useChatStore } from '@/stores/chatStore'
import { useElementPickerStore } from '@/stores/elementPickerStore'
import type { SessionInfo, ChatMessage } from '@/stores/chatStore'
import ThinkingBubble from '@/generative-ui/ThinkingBubble.vue'
import DynamicChart from '@/generative-ui/DynamicChart.vue'
import WorkOrderCard from '@/generative-ui/WorkOrderCard.vue'
import ReportDownload from '@/generative-ui/ReportDownload.vue'
import ValueCard from '@/generative-ui/ValueCard.vue'
import EvidenceLink from '@/generative-ui/EvidenceLink.vue'
import ChartSkeleton from '@/generative-ui/ChartSkeleton.vue'
import type { ArtifactEvent } from '@/api/stream_client'
import { apiFetch } from '@/api/http'
import { renderMarkdown as sharedRenderMarkdown } from '@/utils/markdown'

import { useDataRangeStore } from '@/stores/dataRangeStore'
import { useReportStore } from '@/stores/reportStore'
import {
  conversationReportTemplates,
  defaultConversationReportTemplate,
} from '@/constants/reportTemplates'

const router = useRouter()
const store = useChatStore()
const pickerStore = useElementPickerStore()
const dataRangeStore = useDataRangeStore()
const reportStore = useReportStore()

/** agent 类型 → 语义配色 */
const _agentColors: Record<string, string> = {
  router:         '#3B82C4',  // 信息蓝
  data_agent:     '#259468',  // 数据绿
  diagnose_agent: '#D4782C',  // 警示橙
  tool:           '#7C5CB8',  // 执行紫
  tools:          '#7C5CB8',  // 执行紫
  agent:          '#8A7B96',  // 思考灰紫
  web_search:     '#3B82C4',  // 信息蓝
}
function agentDotColor(name: string): string {
  return _agentColors[name] ?? '#8A7B96'
}

const inputText = ref('')
const inputFocused = ref(false)
const showThinkingModeMenu = ref(false)
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
const reportWrapEl = ref<HTMLElement>()
const reportMenuOpen = ref(false)
const reportGenerating = ref(false)
const activeReportTemplateId = ref<string | null>(null)
const rawDataPreview = ref<ArtifactEvent | null>(null)

const isPageReportMode = computed(() => reportStore.sections.length > 0)
const activeReportTemplate = computed(() => (
  conversationReportTemplates.find(template => template.id === activeReportTemplateId.value) ?? null
))
const reportButtonTitle = computed(() => {
  if (reportGenerating.value) {
    return activeReportTemplate.value
      ? `生成${activeReportTemplate.value.label}中...`
      : '生成报表中...'
  }
  return isPageReportMode.value ? '导出页面报表' : '导出对话报表'
})

function toggleHistory() {
  historyOpen.value = !historyOpen.value
  if (historyOpen.value) {
    moreOpen.value = false
    reportMenuOpen.value = false
    // 每次打开历史面板时从后端刷新会话列表，保持与数据库同步
    store.loadSessionList()
  }
}

function toggleMoreMenu() {
  moreOpen.value = !moreOpen.value
  if (moreOpen.value) {
    historyOpen.value = false
    reportMenuOpen.value = false
  }
}

function closeAllDropdowns() {
  historyOpen.value = false
  moreOpen.value = false
  reportMenuOpen.value = false
}

function closeRawDataPreview() {
  rawDataPreview.value = null
}

function isRawDataSnapshot(artifact?: ArtifactEvent): boolean {
  if (!artifact) return false
  const t = artifact.component_type ?? artifact.widget ?? ''
  return ['RawDataSnapshot', 'raw-data-snapshot'].includes(t)
}

function findRelatedArtifact(msgId: string, matcher: (artifact?: ArtifactEvent) => boolean): ArtifactEvent | null {
  const start = store.messages.findIndex(m => m.id === msgId)
  if (start === -1) return null
  for (let i = start + 1; i < store.messages.length; i++) {
    const msg = store.messages[i]
    if (msg.role === 'user') break
    if (msg.role === 'artifact' && matcher(msg.artifact)) {
      return msg.artifact ?? null
    }
  }
  return null
}

function onMessagesClick(e: MouseEvent) {
  closeAllDropdowns()
  const target = e.target as HTMLElement | null
  const link = target?.closest('a')
  if (!link) return

  const text = (link.textContent ?? '').trim()
  const href = link.getAttribute('href') ?? ''
  const wantsRawData = text.includes('原始数据') || href.includes('raw-data') || href.includes('原始数据')
  if (!wantsRawData) return

  e.preventDefault()
  const msgEl = link.closest('[data-msg-id]') as HTMLElement | null
  const msgId = msgEl?.dataset.msgId
  if (!msgId) return
  rawDataPreview.value = findRelatedArtifact(msgId, isRawDataSnapshot) ?? {
    type: 'artifact',
    component_type: 'RawDataSnapshot',
    title: '原始数据快照',
    data_payload: { records: [], total_count: 0, preview_count: 0 },
  }
}

// 点击外部关闭
function onDocClick(e: MouseEvent) {
  const target = e.target as Node
  const targetEl = e.target as HTMLElement | null
  if (historyPanelEl.value && !historyPanelEl.value.contains(target)) {
    historyOpen.value = false
  }
  if (moreWrapEl.value && !moreWrapEl.value.contains(target)) {
    moreOpen.value = false
  }
  const clickedReportTrigger = !!targetEl?.closest('[data-report-trigger="true"]')
  if (
    reportWrapEl.value &&
    !reportWrapEl.value.contains(target) &&
    !clickedReportTrigger
  ) {
    reportMenuOpen.value = false
  }
  const dropdownEl = document.querySelector('.thinking-mode-dropdown')
  if (dropdownEl && !dropdownEl.contains(target)) {
    showThinkingModeMenu.value = false
  }
}
/* 自定义滚动条状态 */
const tabHover = ref(false)
const tabDragging = ref(false)
const scrollThumb = ref({ show: false, left: 0, width: 100 })

function updateScrollThumb() {
  const el = tabListEl.value
  if (!el) return
  const { scrollWidth, clientWidth, scrollLeft } = el
  if (scrollWidth <= clientWidth) {
    scrollThumb.value.show = false
    return
  }
  scrollThumb.value.show = true
  const rawWidth = (clientWidth / scrollWidth) * 100
  const thumbW = Math.min(rawWidth, 50)
  scrollThumb.value.width = thumbW
  const maxScroll = scrollWidth - clientWidth
  scrollThumb.value.left = maxScroll > 0 ? (scrollLeft / maxScroll) * (100 - thumbW) : 0
}

/* 横向滚轮滚动 tab 列表 */
function onTabWheel(e: WheelEvent) {
  if (!tabListEl.value) return
  e.preventDefault()
  tabListEl.value.scrollLeft += e.deltaY || e.deltaX
}

/* 拖拽自定义滚动条 */
function onThumbDown(e: MouseEvent) {
  e.preventDefault()
  const el = tabListEl.value
  if (!el) return
  const bar = (e.target as HTMLElement).parentElement!
  const barRect = bar.getBoundingClientRect()
  const ratio = el.scrollWidth / barRect.width
  tabDragging.value = true

  function onMove(ev: MouseEvent) {
    const x = ev.clientX - barRect.left
    el!.scrollLeft = x * ratio - el!.clientWidth / 2
  }
  function onUp() {
    tabDragging.value = false
    document.removeEventListener('mousemove', onMove)
    document.removeEventListener('mouseup', onUp)
  }
  document.addEventListener('mousemove', onMove)
  document.addEventListener('mouseup', onUp)
}

/* 点击滚动条轨道跳转 */
function onTrackClick(e: MouseEvent) {
  const el = tabListEl.value
  if (!el) return
  const bar = e.currentTarget as HTMLElement
  const barRect = bar.getBoundingClientRect()
  const x = e.clientX - barRect.left
  const ratio = el.scrollWidth / barRect.width
  el.scrollLeft = x * ratio - el.clientWidth / 2
}

onMounted(() => {
  store.init()
  dataRangeStore.fetch()
  document.addEventListener('click', onDocClick, true)
  tabListEl.value?.addEventListener('wheel', onTabWheel, { passive: false })
  nextTick(updateScrollThumb)
})
onUnmounted(() => {
  document.removeEventListener('click', onDocClick, true)
  tabListEl.value?.removeEventListener('wheel', onTabWheel)
})

/* tab 数量变化时更新滚动条 */
watch(() => store.openTabs.length, () => nextTick(updateScrollThumb))

// ── 最后一条 AI 消息（用于流式光标 + 图表释放定位）────────────────────────────
const lastAiMsg = computed(() => {
  for (let i = store.messages.length - 1; i >= 0; i--) {
    if (store.messages[i].role === 'ai') return store.messages[i]
  }
  return null
})
const lastAiMsgId = computed(() => lastAiMsg.value?.id ?? null)

const rawDataRows = computed(() => {
  const payload = rawDataPreview.value?.data_payload as Record<string, unknown> | undefined
  const rows = payload?.records
  return Array.isArray(rows) ? rows as Array<Record<string, unknown>> : []
})

const rawDataMeta = computed(() => {
  const payload = rawDataPreview.value?.data_payload as Record<string, unknown> | undefined
  if (!payload) return ''
  const building = String(payload.building_id ?? '未知楼宇')
  const total = Number(payload.total_count ?? 0)
  const preview = Number(payload.preview_count ?? rawDataRows.value.length)
  return `${building} · 展示 ${preview}/${total} 条记录`
})

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

function onReportBtnClick() {
  if (reportGenerating.value) return
  if (isPageReportMode.value) {
    reportStore.openPreview()
    return
  }
  historyOpen.value = false
  moreOpen.value = false
  reportMenuOpen.value = !reportMenuOpen.value
}

function onSelectReportTemplate(templateId: string) {
  void onExportConversation(templateId)
}

async function onExportConversation(templateId = defaultConversationReportTemplate.id) {
  moreOpen.value = false
  reportMenuOpen.value = false
  if (reportGenerating.value || !store.currentSessionId) return

  reportGenerating.value = true
  activeReportTemplateId.value = templateId

  try {
    const payload = await apiFetch(`/api/chat/sessions/${store.currentSessionId}/report`, {
      method: 'POST',
      body: JSON.stringify({
        mode: 'formal',
        generation_mode: 'hybrid',
        artifact_policy: 'all',
        include_appendix: false,
        template_id: templateId,
      }),
    })
    reportStore.openPreviewWithPayload(payload as any)
  } catch (error) {
    console.error('[AgentConsole] 导出对话报表失败:', error)
    window.alert((error as Error).message || '导出对话报表失败')
  } finally {
    reportGenerating.value = false
    activeReportTemplateId.value = null
  }
}

// ── 消息互动操作 ──────────────────────────────────────────────────────────────
const copiedMsgId = ref<string | null>(null)

async function copyMessage(msg: ChatMessage) {
  if (!msg.content) return
  try {
    await navigator.clipboard.writeText(msg.content)
    copiedMsgId.value = msg.id
    setTimeout(() => { copiedMsgId.value = null }, 2000)
  } catch {
    // fallback
    const ta = document.createElement('textarea')
    ta.value = msg.content
    document.body.appendChild(ta)
    ta.select()
    document.execCommand('copy')
    document.body.removeChild(ta)
    copiedMsgId.value = msg.id
    setTimeout(() => { copiedMsgId.value = null }, 2000)
  }
}

function toggleLike(msg: ChatMessage, liked: boolean) {
  msg.liked = msg.liked === liked ? null : liked
}

function regenerate(msg: ChatMessage) {
  if (store.isLoading) return
  const idx = store.messages.indexOf(msg)
  if (idx === -1) return
  store.regenerateMessage(idx)
}

// ── 发送消息 ────────────────────────────────────────────────────────────────
function handleSend() {
  if (!inputText.value.trim() || store.isLoading) return
  let text = inputText.value.trim()

  // 附带选中元素的上下文信息
  if (pickerStore.selectedElement) {
    const el = pickerStore.selectedElement
    const ctx = `[关于页面元素「${el.title}」${el.subtitle ? '（' + el.subtitle + '）' : ''}，类型：${el.type}]\n`
    text = ctx + text
    pickerStore.clearSelection()
  }

  store.sendMessage(text)
  inputText.value = ''
}

function quickSend(text: string) {
  if (store.isLoading) return
  store.sendMessage(text)
}

// ── 智能滚动（只在接近底部时自动滚动，防止图表展开时跳位） ────────────────
function _isNearBottom(): boolean {
  const el = messagesEl.value
  if (!el) return true
  return el.scrollHeight - el.scrollTop - el.clientHeight < 120
}

function _scrollToBottom() {
  if (messagesEl.value) messagesEl.value.scrollTop = messagesEl.value.scrollHeight
}

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
    () => {
      const last = store.messages[store.messages.length - 1]
      return last?.attachedArtifacts?.length ?? 0
    },
  ],
  async () => {
    await nextTick()
    if (_isNearBottom()) _scrollToBottom()
  },
)

watch(() => store.currentSessionId, async () => {
  closeRawDataPreview()
  await nextTick()
  _scrollToBottom()
})

// ── Artifact 类型判断 ────────────────────────────────────────────────────────
function ensureArtifact(a: ArtifactEvent | undefined): ArtifactEvent {
  return a!
}

/** 检查独立 artifact 消息是否已被前面的 AI 消息内嵌（避免重复渲染） */
function isArtifactInlined(msg: ChatMessage, msgIdx: number): boolean {
  const artId = msg.artifact?.artifact_id
  if (!artId) return false
  for (let i = msgIdx - 1; i >= 0; i--) {
    const prev = store.messages[i]
    if (prev.role === 'ai' && prev.attachedArtifacts?.some(a => a.artifact_id === artId)) {
      return true
    }
    if (prev.role === 'user') break
  }
  return false
}

function isValueCard(artifact?: ArtifactEvent): boolean {
  if (!artifact) return false
  const t = artifact.component_type ?? artifact.widget ?? ''
  return ['ValueCard', 'value-card'].includes(t)
}

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

// ── Markdown 渲染 ─────────────────────────────────────────────
function formatMarkdown(text: string): string {
  return sharedRenderMarkdown(text)
}

// ── 内嵌图表：占位符驱动 + stagger 动画 ──────────────────────────────────────
// LLM 在文本中插入 <<CHART:锚点>> 占位符，前端据此精准插入图表

const CHART_PLACEHOLDER_RE = /<<CHART:([^>]+)>>/g

// ── 图表队列式逐个释放 ──────────────────────────────────────────────────────
// readySet: 图表已就绪 → 渲染真实图表
// activeChartId: 当前正在「骨架屏→真实图」过渡的图表 ID
// 只有 readySet 或 activeChartId 里的图表才会被 buildInlineSegments 输出
const readySet         = reactive(new Set<string>())
const activeChartId    = ref<string | null>(null)
const deferredArtifacts = reactive(new Map<string, string>())
const _chartQueue: string[] = []
let _queueTimer: ReturnType<typeof setTimeout> | null = null

function _processChartQueue() {
  if (activeChartId.value || _chartQueue.length === 0) return
  const id = _chartQueue.shift()!
  activeChartId.value = id
  _queueTimer = setTimeout(async () => {
    readySet.add(id)
    activeChartId.value = null
    await nextTick()
    if (_isNearBottom()) _scrollToBottom()
    _processChartQueue()
  }, 400)
}

watch(() => store.isLoading, (loading) => {
  if (loading) {
    readySet.clear()
    activeChartId.value = null
    deferredArtifacts.clear()
    _chartQueue.length = 0
    if (_queueTimer) { clearTimeout(_queueTimer); _queueTimer = null }
  } else {
    // 流式结束：把剩余 deferred 全部入队
    for (const [id] of deferredArtifacts.entries()) {
      if (!_chartQueue.includes(id)) _chartQueue.push(id)
    }
    deferredArtifacts.clear()
    _processChartQueue()
  }
})

// 流式文本中出现 <<CHART:xx>> → 入队等待逐个释放
watch(
  () => {
    if (!store.isLoading) return null
    return lastAiMsg.value?.content ?? null
  },
  (content) => {
    if (!content) return
    for (const [id, anchor] of deferredArtifacts.entries()) {
      if (anchor && content.includes(`<<CHART:${anchor}>>`)) {
        deferredArtifacts.delete(id)
        _chartQueue.push(id)
      }
    }
    _processChartQueue()
  },
)

// artifact 到达 → 若锚点已在文本中则立即入队，否则 defer
watch(
  () => lastAiMsg.value?.attachedArtifacts?.length ?? 0,
  (newLen, oldLen) => {
    const msg = lastAiMsg.value
    if (!msg) return
    const arts = msg.attachedArtifacts ?? []
    const content = msg.content || ''
    const startIdx = oldLen ?? 0
    for (let i = startIdx; i < newLen; i++) {
      const art = arts[i]
      const id = art?.artifact_id ?? `_art_${i}`
      const anchor = art?.anchor || ''
      if (anchor && content.includes(`<<CHART:${anchor}>>`)) {
        _chartQueue.push(id)
      } else {
        deferredArtifacts.set(id, anchor)
      }
    }
    _processChartQueue()
  },
)


// ── 内嵌图表分片渲染（占位符驱动）─────────────────────────────────────────────
interface InlineSegment {
  type: 'text' | 'chart' | 'placeholder'
  text?: string
  artifact?: ArtifactEvent
  artifactId?: string
  anchor?: string
}

function buildInlineSegments(msg: ChatMessage): InlineSegment[] {
  const artifacts = msg.attachedArtifacts ?? []
  const inlineArtifacts = artifacts.filter((a: ArtifactEvent) => isChart(a) || isValueCard(a))
  const content = msg.content || ''
  const isStreaming = store.isLoading && msg.id === lastAiMsgId.value

  if (!content) return [{ type: 'text', text: '' }]
  if (inlineArtifacts.length === 0 && !isStreaming) {
    return [{ type: 'text', text: content }]
  }

  // 按 anchor 建立图表索引（anchor → artifact）
  const anchorToArt = new Map<string, ArtifactEvent>()
  for (const art of inlineArtifacts) {
    if (art.anchor) anchorToArt.set(art.anchor, art)
  }

  // 按 <<CHART:xxx>> 占位符分割文本
  const segments: InlineSegment[] = []
  const usedAnchors = new Set<string>()
  let lastIndex = 0

  // 逐个匹配占位符
  const regex = new RegExp(CHART_PLACEHOLDER_RE.source, 'g')
  let match: RegExpExecArray | null
  while ((match = regex.exec(content)) !== null) {
    const anchor = match[1]
    const before = content.slice(lastIndex, match.index).trim()

    if (before) {
      segments.push({ type: 'text', text: before })
    }

    const art = anchorToArt.get(anchor)
    if (art) {
      const artId = art.artifact_id ?? `_art_${anchor}`
      usedAnchors.add(anchor)
      // 流式期间：只有轮到的图表（active 或 ready）才渲染，其余跳过
      if (!isStreaming || readySet.has(artId) || activeChartId.value === artId) {
        segments.push({ type: 'chart', artifact: art, artifactId: artId })
      }
    }

    lastIndex = match.index + match[0].length
  }

  // 占位符后面剩余的文本
  const tail = content.slice(lastIndex).trim()
  if (tail) {
    segments.push({ type: 'text', text: tail })
  }

  // 兜底：没有被占位符匹配到的图表追加末尾（流式期间跳过 deferred）
  for (const art of inlineArtifacts) {
    if (art.anchor && usedAnchors.has(art.anchor)) continue
    const artId = art.artifact_id ?? '_art_unmatched'
    if (isStreaming && deferredArtifacts.has(artId)) continue
    segments.push({ type: 'chart', artifact: art, artifactId: artId })
  }

  // 安全兜底：如果文本中完全没有占位符（旧消息/LLM未遵循格式），回退到整块文本+图表追加
  if (segments.length === 0) {
    segments.push({ type: 'text', text: content })
  }

  return segments
}
</script>

<style scoped>
.console {
  display: flex;
  flex-direction: column;
  height: 100%;
  background: var(--bg-card);           /* Cursor 风格：整面板统一底色 */
  /* 原底色 var(--bg-panel)，后续可恢复 */
  border-left: 1px solid var(--border);
  position: relative;
  overflow: hidden;
}

/* ── 顶栏（Cursor 风格：无底部线，圆角浮动 Tab） ────────────────────────── */
.top-bar {
  display: flex;
  align-items: center;
  flex-shrink: 0;
  background: transparent;              /* 继承 .console 底色，统一 */
  min-height: 38px;
}

/* Tab 列表容器 */
.tab-list-wrap {
  display: flex;
  flex-direction: column;
  flex: 1;
  min-width: 0;
  position: relative;
}

/* Tab 列表 */
.tab-list {
  display: flex;
  align-items: center;
  overflow-x: scroll;
  flex: 1;
  padding: 0 4px;
  gap: 2px;
  scrollbar-width: none;           /* Firefox 隐藏原生滚动条 */
}
.tab-list::-webkit-scrollbar { display: none; }  /* Chrome 隐藏原生滚动条 */

/* 自定义滚动条 */
.custom-scrollbar {
  position: absolute;
  bottom: 0;
  left: 4px;
  right: 4px;
  height: 3px;
  cursor: pointer;
  z-index: 10;
}
.custom-thumb {
  position: absolute;
  top: 0;
  height: 100%;
  background: transparent;
  border-radius: 2px;
  cursor: pointer;
  transition: background 0.2s;
}
.custom-thumb.visible {
  background: rgba(0, 0, 0, 0.2);
}
.custom-thumb.visible:hover,
.custom-thumb.dragging {
  background: rgba(0, 0, 0, 0.35);
}

.tab {
  display: flex;
  align-items: center;
  gap: 0;
  /* 内容自适应宽度，最大 160px */
  width: fit-content;
  min-width: 48px;
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
  color: var(--text-primary);
}
.tab.active {
  background: rgba(255,255,255,0.1);
  color: var(--text-primary);
  font-weight: 500;
}

/* light 主题下选中 Tab */
html[data-theme="light"] .tab:hover {
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

/* 渐变遮罩：已移除，仅保留关闭按钮覆盖 */
.tab-fade {
  display: none;
}

/* 叉号：绝对定位，默认隐藏，hover 时带底色覆盖标题尾部（Cursor 风格） */
.tab-close {
  position: absolute;
  right: 0;
  top: 0;
  bottom: 0;
  margin: auto 0;
  background: var(--bg-card);
  border: none;
  cursor: pointer;
  color: var(--text-secondary);
  font-size: 14px;
  line-height: 16px;
  padding: 0 2px;
  border-radius: 0 6px 6px 0;
  display: flex;
  align-items: center;
  justify-content: center;
  width: 16px;
  height: 100%;
  opacity: 0;
  z-index: 1;
  transition: opacity 0.15s, color 0.12s;
}
/* 只在 hover 时显示，active 不自动显示 */
.tab:hover .tab-close { opacity: 1; }
.tab-close:hover { color: var(--text-primary); }

/* 选中 Tab 的关闭按钮底色要与选中 Tab 背景一致（覆盖区不能露出 bg-card） */
.tab.active .tab-close {
  /* dark 主题：bg-card #101118 + rgba(255,255,255,0.1) ≈ #282930 */
  background: #282930;
}
html[data-theme="light"] .tab.active .tab-close {
  /* light 主题：bg-card #f5f5f5 + rgba(0,0,0,0.08) ≈ #e2e2e2 */
  background: #e2e2e2;
}

/* 右侧操作按钮（无左侧边框） */
.top-actions {
  display: flex;
  align-items: center;
  padding: 0 6px;
  gap: 1px;
  flex-shrink: 0;
  position: relative;
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
.top-btn:disabled {
  cursor: not-allowed;
  opacity: 0.5;
}
.top-btn:disabled:hover {
  color: var(--text-secondary);
  opacity: 0.5;
}

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
.menu-item:disabled {
  cursor: not-allowed;
  opacity: 0.55;
}
.menu-item:disabled:hover {
  background: none;
  color: var(--text-secondary);
}
.menu-item.danger:hover { background: rgba(248,113,113,0.08); color: var(--danger, #f87171); }

.menu-divider { height: 1px; background: var(--border); margin: 4px 0; }

.report-template-floating {
  top: calc(100% + 4px);
  right: 34px;
  min-width: 260px;
  max-width: 320px;
}

.report-template-title {
  padding: 8px 10px 6px;
  font-size: 11px;
  font-weight: 600;
  color: var(--text-muted);
  text-transform: uppercase;
  letter-spacing: 0.06em;
}

.report-template-item {
  align-items: flex-start;
}

.report-template-copy {
  display: flex;
  flex-direction: column;
  gap: 4px;
  min-width: 0;
}

.report-template-label {
  display: flex;
  align-items: center;
  gap: 6px;
  color: var(--text-primary);
  font-weight: 600;
}

.report-template-badge {
  display: inline-flex;
  align-items: center;
  padding: 1px 6px;
  border-radius: 999px;
  background: rgba(108,142,245,0.12);
  color: var(--accent);
  font-size: 11px;
  font-weight: 600;
}

.report-template-desc {
  font-size: 12px;
  line-height: 1.5;
  color: var(--text-muted);
}

.report-export-menu-item > span {
  flex: 1;
}

.report-generating-overlay {
  position: absolute;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  background: rgba(10, 14, 24, 0.42);
  backdrop-filter: blur(2px);
  z-index: 240;
}

.report-generating-card {
  min-width: 220px;
  max-width: 320px;
  padding: 22px 24px;
  border: 1px solid var(--border);
  border-radius: 14px;
  background: var(--bg-card);
  box-shadow: 0 18px 40px rgba(0, 0, 0, 0.22);
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 10px;
  text-align: center;
}

.report-generating-spinner {
  color: var(--accent);
}

.report-generating-title {
  font-size: 15px;
  font-weight: 600;
  color: var(--text-primary);
}

.report-generating-desc {
  font-size: 12px;
  line-height: 1.6;
  color: var(--text-muted);
}

.spin {
  animation: spin 0.9s linear infinite;
}

@keyframes spin {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}

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
  /* 颜色由 inline style 动态设置 */
  animation: status-breathe 1.6s ease-in-out infinite;
}
@keyframes status-breathe {
  0%, 100% { transform: scale(1);   opacity: 0.7; }
  50%      { transform: scale(1.4); opacity: 1; }
}

.status-label { font-weight: 600; /* 颜色由 inline style 动态设置 */ }
.status-msg { color: var(--text-secondary); flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }

/* ── 消息区 ─────────────────────────────────────────────────────────────── */
.messages {
  flex: 1;
  overflow-y: auto;
  padding: 12px 12px;
  display: flex;
  flex-direction: column;
  gap: 8px;
  background: transparent;              /* 继承 .console 底色，统一 */
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
  background: var(--bg-panel);
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
.msg-user { justify-content: flex-start; width: 100%; }
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
  /* Cursor 风格：与输入框同底色 */
  background: var(--bg-panel);
  color: var(--text-primary);
  border: 1px solid var(--border);
  border-radius: 10px;
  font-size: 13px;
  font-weight: 400;
  line-height: 1.6;
  padding: 10px 14px;
  max-width: 100%;
  width: 100%;
  word-break: break-word;
}

/* .ai-avatar 已移除，不再显示大模型图标 */

.ai-content {
  display: flex;
  flex-direction: column;
  gap: 0;
  width: 100%;
  min-width: 0;
}

.ai-bubble {
  background: transparent;
  color: var(--text-primary);
  border: none;
  border-radius: 0;
  max-width: 100%;
  padding: 10px 14px 6px;
  font-size: 13.5px;
  line-height: 1.85;
  letter-spacing: 0.015em;
  word-break: break-word;
}

/* ── Markdown 排版样式（marked 原生 HTML 标签） ───────────────────────────── */

/* 标题 */
.ai-bubble :deep(h1) {
  font-size: 15.5px;
  font-weight: 700;
  color: var(--text-primary);
  margin: 14px 0 6px;
  letter-spacing: 0.01em;
  line-height: 1.4;
}
.ai-bubble :deep(h2) {
  font-size: 14px;
  font-weight: 700;
  color: var(--text-primary);
  margin: 12px 0 5px;
  padding-bottom: 4px;
  border-bottom: 1px solid var(--border);
  letter-spacing: 0.01em;
  line-height: 1.4;
}
.ai-bubble :deep(h3) {
  font-size: 12.5px;
  font-weight: 700;
  color: var(--accent);
  margin: 10px 0 4px;
  line-height: 1.4;
}
.ai-bubble :deep(h4) {
  font-size: 12px;
  font-weight: 700;
  color: var(--text-primary);
  margin: 8px 0 3px;
  line-height: 1.4;
}
.ai-bubble :deep(h5),
.ai-bubble :deep(h6) {
  font-size: 11.5px;
  font-weight: 600;
  color: var(--text-secondary);
  margin: 6px 0 2px;
  line-height: 1.4;
}

/* markdown 块容器（替代原来的 span） */
.ai-bubble .md-block {
  display: block;
  min-width: 0;
}

/* 段落 */
.ai-bubble :deep(p) {
  margin: 4px 0;
  line-height: 1.7;
}
.ai-bubble :deep(p:first-child) {
  margin-top: 0;
}

/* 分隔线 */
.ai-bubble :deep(hr) {
  border: none;
  border-top: 1px solid var(--border);
  margin: 10px 0;
  opacity: 0.6;
}

/* 粗体 / 斜体 */
.ai-bubble :deep(strong) {
  font-weight: 700;
  color: var(--text-primary);
}
.ai-bubble :deep(em) {
  font-style: italic;
}

/* 行内代码 */
.ai-bubble :deep(:not(pre) > code) {
  background: rgba(108, 142, 245, 0.12);
  color: var(--accent);
  padding: 1px 6px;
  border-radius: 4px;
  font-family: 'JetBrains Mono', 'Fira Code', 'Cascadia Code', Consolas, monospace;
  font-size: 0.88em;
  letter-spacing: 0;
  border: 1px solid rgba(108, 142, 245, 0.18);
}

/* 代码块 */
.ai-bubble :deep(pre) {
  background: rgba(0, 0, 0, 0.06);
  border-radius: 6px;
  padding: 10px 12px;
  margin: 6px 0;
  overflow-x: auto;
}
.ai-bubble :deep(pre code) {
  background: none;
  border: none;
  padding: 0;
  font-family: 'JetBrains Mono', 'Fira Code', 'Cascadia Code', Consolas, monospace;
  font-size: 12px;
  line-height: 1.6;
  white-space: pre-wrap;
  word-break: break-word;
  color: var(--text-primary);
}

/* 无序列表 */
.ai-bubble :deep(ul) {
  margin: 4px 0;
  padding-left: 0;
  list-style: none;
}
.ai-bubble :deep(ul li) {
  padding: 1px 0 1px 16px;
  line-height: 1.7;
  position: relative;
}
.ai-bubble :deep(ul li::before) {
  content: '•';
  position: absolute;
  left: 4px;
  color: var(--accent);
}
.ai-bubble :deep(ul ul) {
  margin: 0;
  padding-left: 14px;
}
.ai-bubble :deep(ul ul li::before) {
  content: '–';
  color: var(--text-muted);
}

/* 有序列表 */
.ai-bubble :deep(ol) {
  margin: 4px 0;
  padding-left: 0;
  list-style: none;
  counter-reset: md-ol;
}
.ai-bubble :deep(ol li) {
  padding: 1px 0 1px 24px;
  line-height: 1.7;
  position: relative;
  counter-increment: md-ol;
}
.ai-bubble :deep(ol li::before) {
  content: counter(md-ol) ".";
  position: absolute;
  left: 2px;
  color: var(--text-secondary);
  font-size: 0.9em;
  font-weight: 600;
  font-variant-numeric: tabular-nums;
}

/* 引用块 */
.ai-bubble :deep(blockquote) {
  border-left: 3px solid var(--accent);
  padding: 4px 10px 4px 12px;
  margin: 6px 0;
  color: var(--text-secondary);
  font-style: italic;
  background: rgba(108, 142, 245, 0.05);
  border-radius: 0 4px 4px 0;
  line-height: 1.7;
}
.ai-bubble :deep(blockquote p) {
  margin: 0;
}

/* ── 表格 ── */
.ai-bubble :deep(table) {
  width: 100%;
  border-collapse: collapse;
  font-size: 12px;
  line-height: 1.5;
  margin: 8px 0;
  border-radius: 6px;
  overflow: hidden;
  border: 1px solid var(--border, rgba(128,128,128,0.2));
  display: block;
  overflow-x: auto;
}
.ai-bubble :deep(thead) {
  background: rgba(108, 142, 245, 0.08);
}
.ai-bubble :deep(th) {
  font-weight: 600;
  text-align: left;
  padding: 7px 12px;
  border-bottom: 1.5px solid var(--border, rgba(128,128,128,0.25));
  color: var(--text-primary);
  white-space: nowrap;
}
.ai-bubble :deep(td) {
  padding: 5px 12px;
  border-bottom: 1px solid var(--border, rgba(128,128,128,0.12));
  color: var(--text-secondary);
}
.ai-bubble :deep(tbody tr:last-child td) {
  border-bottom: none;
}
.ai-bubble :deep(tbody tr:hover) {
  background: rgba(108, 142, 245, 0.04);
}
.ai-bubble :deep(td strong) {
  color: var(--text-primary);
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

/* ── 内嵌图表三阶段动画系统 ──────────────────────────────────────────── */

/* 容器：所有内嵌 artifact（占位/骨架/真实图表）统一容器 */
.inline-artifact-wrap {
  margin: 12px 0;
  width: 100%;
  display: grid;
  grid-template-rows: 1fr;
  transition: grid-template-rows 0.5s cubic-bezier(0.22, 1, 0.36, 1);
  overflow: hidden;
}
.inline-artifact-wrap > * {
  min-height: 0;
  overflow: hidden;
}

/* 占位/骨架屏淡入 */
.placeholder-phase {
  animation: placeholderFadeIn 0.4s ease-out both;
}

@keyframes placeholderFadeIn {
  from { opacity: 0; grid-template-rows: 0fr; }
  to   { opacity: 1; grid-template-rows: 1fr; }
}

/* ── 骨架屏入场（从占位条高度展开到骨架屏高度） ─────────────── */
.skeleton-in-enter-active {
  animation: skeletonExpand 0.5s cubic-bezier(0.22, 1, 0.36, 1) both;
}

@keyframes skeletonExpand {
  from { opacity: 0; max-height: 46px; transform: scaleY(0.3); transform-origin: top; }
  to   { opacity: 1; max-height: 300px; transform: scaleY(1); transform-origin: top; }
}

/* ── 真实图表入场（从骨架屏交叉溶解） ────────────────────────── */
.chart-in-enter-active {
  animation: chartReveal 0.5s cubic-bezier(0.22, 1, 0.36, 1) both;
}

@keyframes chartReveal {
  from { opacity: 0; transform: translateY(6px); }
  to   { opacity: 1; transform: translateY(0); }
}

/* 就绪阶段入场后的微光扫过 */
.ready-phase {
  position: relative;
}
.ready-phase::after {
  content: '';
  position: absolute;
  inset: 0;
  background: linear-gradient(
    90deg,
    transparent 0%,
    rgba(108, 142, 245, 0.08) 45%,
    rgba(108, 142, 245, 0.12) 50%,
    rgba(108, 142, 245, 0.08) 55%,
    transparent 100%
  );
  background-size: 200% 100%;
  animation: readyShine 0.8s ease-out 0.1s both;
  pointer-events: none;
  border-radius: 10px;
  z-index: 5;
}

@keyframes readyShine {
  0%   { background-position: -200% 0; opacity: 1; }
  100% { background-position: 200% 0; opacity: 0; }
}

@media (prefers-reduced-motion: reduce) {
  .inline-artifact-wrap,
  .ready-phase::after {
    animation: none !important;
    transition: none !important;
  }
}

/* ── 知识溯源：引用来源 ────────────────────────────────────────────────── */
.evidence-sources {
  margin-top: 10px;
  border: 1px solid var(--border);
  border-radius: 8px;
  overflow: hidden;
  font-size: 12px;
}

.evidence-header {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 8px 12px;
  cursor: pointer;
  color: var(--text-secondary);
  font-weight: 600;
  background: var(--bg-hover);
  transition: background 0.15s;
  user-select: none;
}
.evidence-header:hover {
  background: var(--bg-panel);
}

.evidence-chevron {
  margin-left: auto;
  transition: transform 0.2s;
}
.evidence-sources.open .evidence-chevron {
  transform: rotate(180deg);
}

.evidence-list {
  max-height: 0;
  overflow: hidden;
  transition: max-height 0.25s ease;
}
.evidence-sources.open .evidence-list {
  max-height: 300px;
  overflow-y: auto;
}

.evidence-item {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 6px 12px;
  border-top: 1px solid var(--border);
  color: var(--text-secondary);
  line-height: 1.4;
}
.evidence-item:hover {
  background: var(--bg-hover);
}

.evidence-file-icon {
  color: var(--text-muted);
  flex-shrink: 0;
}

.evidence-doc {
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: var(--text-primary);
  font-weight: 500;
}

.evidence-page {
  color: var(--text-muted);
  font-size: 11px;
  flex-shrink: 0;
}

.evidence-score {
  color: var(--accent);
  font-size: 11px;
  font-weight: 600;
  flex-shrink: 0;
  background: var(--accent-glow);
  padding: 1px 5px;
  border-radius: 3px;
}

/* ── 消息互动操作栏 ──────────────────────────────────────────────────────── */
.msg-actions {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 0px;
  padding: 0 14px 2px;
  margin-top: -6px;
  opacity: 0;
  transition: opacity 0.2s;
}
.msg.msg-ai:hover .msg-actions {
  opacity: 1;
}
.msg-action-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 22px;
  height: 22px;
  border: none;
  border-radius: 4px;
  background: transparent;
  color: var(--text-muted);
  cursor: pointer;
  transition: background 0.15s, color 0.15s;
  font-size: 0;
}
.msg-action-btn:hover {
  background: var(--bg-hover, rgba(0,0,0,0.06));
  color: var(--text-primary);
}
.msg-action-btn.active {
  color: var(--accent);
}
.msg-action-btn.copied {
  color: var(--success, #22c55e);
}

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
  padding: 0 12px 12px;
  flex-shrink: 0;
}

.input-box {
  background: var(--bg-panel);          /* 比面板深一级，Cursor 风格输入区 */
  border: 1px solid var(--border);
  border-radius: 12px;
  display: flex;
  flex-direction: column;
  transition: border-color 0.2s, box-shadow 0.2s;
}
.input-box.focused {
  border-color: var(--border);          /* 聚焦时不高亮边框，保持 Cursor 简洁风 */
  box-shadow: none;
}
.input-box.disabled { opacity: 0.55; }

/* 选中元素上下文标签 */
.picked-context {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 6px 10px;
  margin: 6px 8px 0;
  background: var(--accent-glow, rgba(96, 165, 250, 0.1));
  border: 1px solid var(--border-accent, rgba(96, 165, 250, 0.3));
  border-radius: 8px;
  font-size: 12px;
  color: var(--accent, #60a5fa);
}
.picked-icon { flex-shrink: 0; }
.picked-label {
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-weight: 600;
}
.picked-close {
  flex-shrink: 0;
  width: 18px;
  height: 18px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: none;
  border: none;
  border-radius: 4px;
  color: var(--accent, #60a5fa);
  font-size: 14px;
  cursor: pointer;
  transition: background 0.15s;
}
.picked-close:hover {
  background: rgba(96, 165, 250, 0.2);
}

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
  gap: 2px;
}

.tag-btn {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  background: none;
  border: none;
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
  background: rgba(108, 142, 245, 0.06);
}
.tag-btn.active {
  color: var(--accent);
  background: var(--accent-glow, rgba(96, 165, 250, 0.1));
}

/* ── 思考模式下拉 ── */
.thinking-mode-dropdown {
  position: relative;
}
.thinking-mode-dropdown.disabled {
  pointer-events: none;
  opacity: 0.5;
}
.thinking-mode-trigger {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  height: 28px;
  padding: 0 7px;
  font-size: 11px;
  cursor: pointer;
  user-select: none;
}
.thinking-mode-trigger .dropdown-arrow {
  transition: transform 0.2s ease;
}
.thinking-mode-trigger .dropdown-arrow.open {
  transform: rotate(180deg);
}
.thinking-mode-deep {
  color: var(--accent);
  border-color: var(--accent);
  background: rgba(108, 142, 245, 0.1);
}
.thinking-mode-deep:hover {
  background: rgba(108, 142, 245, 0.16);
}

.thinking-mode-menu {
  position: absolute;
  bottom: calc(100% + 2px);
  left: 0;
  min-width: 220px;
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: 10px;
  box-shadow: 0 -4px 16px rgba(0, 0, 0, 0.1);
  padding: 4px;
  z-index: 100;
}
.thinking-mode-option {
  display: flex;
  align-items: center;
  gap: 10px;
  width: 100%;
  padding: 8px 10px;
  border: none;
  background: transparent;
  border-radius: 8px;
  cursor: pointer;
  color: var(--text-primary);
  font-size: 13px;
  text-align: left;
  transition: background 0.15s;
}
.thinking-mode-option:hover {
  background: var(--hover-bg, rgba(0, 0, 0, 0.04));
}
.thinking-mode-option.active {
  background: rgba(108, 142, 245, 0.08);
}
.option-info {
  display: flex;
  flex-direction: column;
  flex: 1;
  min-width: 0;
}
.option-label {
  font-weight: 600;
  font-size: 13px;
  line-height: 1.3;
}
.option-desc {
  font-size: 11px;
  color: var(--text-secondary);
  line-height: 1.3;
  margin-top: 1px;
}
.option-check {
  color: var(--accent);
  flex-shrink: 0;
}

/* dropdown transition */
.dropdown-fade-enter-active,
.dropdown-fade-leave-active {
  transition: opacity 0.15s ease, transform 0.15s ease;
}
.dropdown-fade-enter-from,
.dropdown-fade-leave-to {
  opacity: 0;
  transform: translateY(4px);
}

.web-search-btn {
  position: relative;
  width: auto;
  height: auto;
  padding: 0;
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
  position: absolute;
  top: 2px;
  right: 2px;
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: #22c55e;
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
  gap: 0;
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
  width: 22px;
  height: 22px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: none;
  border: none;
  border-radius: 50%;
  color: #999;
  cursor: default;
  transition: background 0.2s, color 0.2s, opacity 0.15s;
  flex-shrink: 0;
  margin-left: 2px;
}
.send-icon-btn.active {
  background: var(--accent);
  color: #fff;
  cursor: pointer;
}
.send-icon-btn.active:hover { opacity: 0.85; }
.send-icon-btn:disabled { opacity: 0.6; cursor: not-allowed; }
.send-icon-btn.stop-btn {
  background: #e53e3e;
  color: #fff;
  cursor: pointer;
  animation: stop-pulse 1.5s ease-in-out infinite;
}
.send-icon-btn.stop-btn:hover {
  background: #c53030;
}
@keyframes stop-pulse {
  0%, 100% { box-shadow: 0 0 0 0 rgba(229, 62, 62, 0.4); }
  50% { box-shadow: 0 0 0 4px rgba(229, 62, 62, 0); }
}

.raw-data-overlay {
  position: absolute;
  inset: 0;
  background: rgba(15, 23, 42, 0.48);
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 20px;
  z-index: 40;
}

.raw-data-modal {
  width: min(820px, 100%);
  max-height: min(78vh, 760px);
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: 14px;
  box-shadow: 0 24px 80px rgba(15, 23, 42, 0.22);
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.raw-data-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  padding: 16px 18px 12px;
  border-bottom: 1px solid var(--border);
}

.raw-data-title {
  font-size: 16px;
  font-weight: 700;
  color: var(--text-primary);
}

.raw-data-subtitle {
  margin-top: 4px;
  font-size: 12px;
  color: var(--text-secondary);
}

.raw-data-close {
  width: 30px;
  height: 30px;
  border: none;
  border-radius: 8px;
  background: transparent;
  color: var(--text-muted);
  cursor: pointer;
}

.raw-data-close:hover {
  background: var(--bg-hover);
  color: var(--text-primary);
}

.raw-data-body {
  padding: 14px 18px 18px;
  overflow: auto;
}

.raw-data-table-wrap {
  border: 1px solid var(--border);
  border-radius: 10px;
  overflow: auto;
}

.raw-data-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 12px;
}

.raw-data-table th,
.raw-data-table td {
  padding: 10px 12px;
  text-align: left;
  border-bottom: 1px solid var(--border);
  vertical-align: top;
}

.raw-data-table th {
  position: sticky;
  top: 0;
  background: var(--bg-panel);
  color: var(--text-secondary);
  font-weight: 600;
}

.raw-data-table td {
  color: var(--text-primary);
  word-break: break-word;
}

.raw-data-table tr:last-child td {
  border-bottom: none;
}

.raw-data-empty {
  padding: 20px 8px;
  text-align: center;
  color: var(--text-secondary);
}

/* ── 通用过渡动画 ───────────────────────────────────────────────────────── */
.fade-enter-active, .fade-leave-active { transition: all 0.3s; }
.fade-enter-from, .fade-leave-to { opacity: 0; transform: translateY(-8px); }

.dropdown-enter-active, .dropdown-leave-active { transition: all 0.18s ease; }
.dropdown-enter-from, .dropdown-leave-to { opacity: 0; transform: translateY(-6px) scale(0.97); }

.inline-icon { vertical-align: middle; margin-right: 4px; }
</style>
