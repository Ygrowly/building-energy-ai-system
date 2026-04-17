<!--
  AI 辅助维修对话组件
  从 workorder-detail 页抽出，独立管理对话状态和 SSE 流
-->
<template>
  <view
    class="ai-chat"
    :class="{
      'input-docked': dockInput,
      'has-floating-step-entry': showFloatingWorkflowEntry,
      'operator-workbench-chat': isOperatorWorkbench,
      'operator-workbench-empty': showOperatorWorkbenchHero,
    }"
  >
    <view v-if="showChatHeader" class="chat-header">
      <text class="chat-title">{{ chatTitle }}</text>
      <text class="chat-hint">{{ chatHint }}</text>
    </view>
    <view v-if="showTopQuickPromptBar" class="quick-prompt-bar">
      <text class="quick-prompt-title">{{ props.order ? '工单追问' : '运营分析快捷问法' }}</text>
      <view class="quick-prompt-list">
        <text
          v-for="prompt in operatorQuickPrompts"
          :key="prompt"
          class="quick-prompt-chip"
          :class="{ disabled: sending }"
          @click="sendPresetMessage(prompt)"
        >{{ prompt }}</text>
      </view>
    </view>
    <view v-if="showOperatorWorkbenchHero" class="operator-hero-shell">
      <view class="operator-hero-visual">
        <view class="operator-hero-icon-shell">
          <DotLottieVue
            class="operator-hero-lottie"
            src="/static/lottie/ai-chat.lottie"
            autoplay
            loop
          />
        </view>
      </view>
      <view class="operator-hero-tabs">
        <text
          v-for="prompt in operatorQuickPrompts"
          :key="prompt"
          class="operator-hero-chip"
          :class="{ disabled: sending }"
          @click="sendPresetMessage(prompt)"
        >{{ prompt }}</text>
      </view>
    </view>

    <!-- 消息列表 -->
    <scroll-view
      v-if="showMessageList"
      scroll-y
      :scroll-top="scrollTop"
      class="chat-messages"
      :scroll-with-animation="true"
    >
      <!-- 欢迎消息 -->
      <view v-if="showWelcomeBubble" class="msg ai-msg">
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
        <view v-else-if="shouldRenderOperatorSummaryCard(msg)" class="analysis-summary-card">
          <view class="analysis-summary-head">
            <text class="analysis-summary-title">结论摘要</text>
            <text class="analysis-summary-mode">运小维 · 只读分析模式</text>
          </view>
          <view v-if="analysisScopeChips(msg).length" class="analysis-summary-chip-list">
            <text
              v-for="chip in analysisScopeChips(msg)"
              :key="chip"
              class="analysis-summary-chip"
            >{{ chip }}</text>
          </view>
          <text
            v-for="(paragraph, paragraphIndex) in splitMessageContent(msg.content)"
            :key="`summary_${idx}_${paragraphIndex}`"
            class="analysis-summary-text"
          >{{ paragraph }}</text>
          <view v-if="analysisSummaryStats(msg).length" class="analysis-summary-grid">
            <view
              v-for="item in analysisSummaryStats(msg)"
              :key="item.label"
              class="analysis-summary-stat"
            >
              <text class="analysis-summary-stat-label">{{ item.label }}</text>
              <text class="analysis-summary-stat-value">{{ item.value }}</text>
            </view>
          </view>
        </view>
        <!-- 正常消息 -->
        <view
          v-else
          class="msg-bubble"
          :id="msg.role === 'ai' ? messageBubbleId(idx) : undefined"
          :class="msg.role"
          @longpress="msg.role === 'ai' && msg.content ? openAiMessageMenu(msg.content, idx) : undefined"
        >
          <text
            v-for="(paragraph, paragraphIndex) in splitMessageContent(msg.content)"
            :key="`${idx}_${paragraphIndex}`"
            class="msg-paragraph"
          >{{ paragraph }}</text>
        </view>
        <view
          v-if="msg.role === 'ai' && shouldRenderMessageExtensions(msg)"
          class="msg-extensions"
        >
          <view v-if="msg.readonly && !shouldRenderOperatorSummaryCard(msg)" class="readonly-tag">
            <text>运小维 · 只读分析模式</text>
          </view>
          <view v-if="msg.blockedActions?.length" class="analysis-card warning-card">
            <text class="analysis-card-title">写动作已拦截</text>
            <text class="analysis-card-copy">当前只提供分析与证据，不直接执行改派、关闭或审批。</text>
          </view>
          <view v-if="msg.chart" class="analysis-card chart-card">
            <view class="analysis-card-head analysis-card-head--stack">
              <view class="analysis-card-title-wrap">
                <text class="analysis-card-title">{{ msg.chart?.title || '运营图表' }}</text>
                <text v-if="msg.chart?.source" class="analysis-card-source">{{ msg.chart.source }}</text>
              </view>
              <view class="chart-toolbar-row">
                <view class="chart-view-switch">
                  <text
                    class="chart-view-chip"
                    :class="{ active: (msg.chartView || 'chart') === 'chart' }"
                    @click="setChartView(idx, 'chart')"
                  >图表</text>
                  <text
                    class="chart-view-chip"
                    :class="{ active: (msg.chartView || 'chart') === 'table' }"
                    @click="setChartView(idx, 'table')"
                  >明细</text>
                </view>
                <text class="chart-collapse-chip" @click="toggleChartCollapse(idx)">{{ msg.chartCollapsed ? '展开' : '收起' }}</text>
              </view>
            </view>
            <view v-if="chartSeriesTabs(msg.chart).length > 1" class="chart-series-tabs">
              <text
                v-for="(seriesItem, seriesIndex) in chartSeriesTabs(msg.chart)"
                :key="seriesItem.key"
                class="chart-series-chip"
                :class="{ active: (msg.selectedSeriesIndex ?? 0) === seriesIndex }"
                @click="selectChartSeries(idx, seriesIndex)"
              >{{ seriesItem.label }}</text>
            </view>
            <view v-if="msg.chartVisual || buildChartTableRows(msg.chart).length" class="chart-visual-shell">
              <template v-if="msg.chartVisual">
                <view class="chart-axis-meta">
                  <text class="chart-axis-meta-item">X轴：{{ chartXAxisUnit(msg) }}</text>
                  <text class="chart-axis-meta-item">Y轴：{{ chartYAxisLabel(msg) }}</text>
                </view>
                <view v-if="activeChartDatum(msg)" class="chart-focus-card">
                  <text class="chart-focus-kicker">点击图表查看数据</text>
                  <view class="chart-focus-main">
                    <text class="chart-focus-label">{{ activeChartDatum(msg)?.label }}</text>
                    <text class="chart-focus-value">{{ activeChartDatum(msg)?.primaryValue }}</text>
                  </view>
                  <text v-if="activeChartDatum(msg)?.secondaryValues" class="chart-focus-sub">{{ activeChartDatum(msg)?.secondaryValues }}</text>
                </view>
              </template>
              <view v-if="msg.chartCollapsed && msg.chartVisual" class="chart-collapsed-tip">图表已收起，点击右上角“展开”查看。</view>
              <scroll-view
                v-else-if="(msg.chartView || 'chart') === 'chart' && msg.chartVisual"
                scroll-x
                class="chart-scroll"
                show-scrollbar="false"
              >
                <view class="chart-visual-canvas" :style="{ width: `${msg.chartVisual.canvasWidth}px` }">
                  <svg
                    class="chart-svg"
                    :viewBox="`0 0 ${msg.chartVisual.canvasWidth} ${msg.chartVisual.canvasHeight}`"
                    preserveAspectRatio="none"
                  >
                    <defs>
                      <linearGradient id="chartBarGradient" x1="0" y1="0" x2="0" y2="1">
                        <stop offset="0%" stop-color="#8cbf7d" />
                        <stop offset="100%" stop-color="#5f9e87" />
                      </linearGradient>
                    </defs>
                    <line
                      v-for="grid in msg.chartVisual?.gridLines || []"
                      :key="`grid_${grid}`"
                      :x1="msg.chartVisual.paddingLeft"
                      :x2="msg.chartVisual.canvasWidth - msg.chartVisual.paddingRight"
                      :y1="grid"
                      :y2="grid"
                      class="chart-grid-line"
                    />
                    <text
                      v-for="tick in msg.chartVisual?.yTicks || []"
                      :key="tick.key"
                      :x="msg.chartVisual.paddingLeft - 8"
                      :y="tick.y + 4"
                      text-anchor="end"
                      class="chart-y-tick"
                    >{{ tick.label }}</text>
                    <line
                      v-if="msg.chartVisual?.zeroY != null"
                      :x1="msg.chartVisual.paddingLeft"
                      :x2="msg.chartVisual.canvasWidth - msg.chartVisual.paddingRight"
                      :y1="msg.chartVisual.zeroY"
                      :y2="msg.chartVisual.zeroY"
                      class="chart-axis-baseline"
                    />
                    <line
                      v-if="msg.chartVisual?.activeGuide"
                      :x1="msg.chartVisual.activeGuide.x"
                      :x2="msg.chartVisual.activeGuide.x"
                      :y1="msg.chartVisual.paddingTop"
                      :y2="msg.chartVisual.canvasHeight - msg.chartVisual.paddingBottom"
                      class="chart-active-guide"
                    />
                    <template v-if="msg.chartVisual?.kind === 'line'">
                      <polyline
                        :points="msg.chartVisual?.fillPoints"
                        class="chart-area"
                      />
                      <polyline
                        :points="msg.chartVisual?.linePoints"
                        class="chart-line"
                      />
                      <circle
                        v-for="point in msg.chartVisual?.points || []"
                        :key="`${point.key}_hit`"
                        :cx="point.x"
                        :cy="point.y"
                        r="12"
                        class="chart-point-hit"
                        @click="selectChartDatum(idx, point.index)"
                      />
                      <circle
                        v-for="point in msg.chartVisual?.points || []"
                        :key="point.key"
                        :cx="point.x"
                        :cy="point.y"
                        :r="point.active ? 6 : 4.5"
                        class="chart-point"
                        :class="{ active: point.active }"
                        @click="selectChartDatum(idx, point.index)"
                      />
                    </template>
                    <template v-else>
                      <rect
                        v-for="bar in msg.chartVisual?.bars || []"
                        :key="bar.key"
                        :x="bar.x"
                        :y="bar.y"
                        :width="bar.width"
                        :height="bar.height"
                        rx="8"
                        fill="url(#chartBarGradient)"
                        class="chart-bar-rect"
                        :class="{ active: bar.active }"
                        @click="selectChartDatum(idx, bar.index)"
                      />
                    </template>
                  </svg>
                  <view
                    class="chart-axis-row"
                    :style="{ width: `${msg.chartVisual.canvasWidth}px` }"
                  >
                    <text
                      v-for="axisItem in msg.chartVisual?.axisLabels || []"
                      :key="axisItem.key"
                      class="chart-axis-label"
                      :style="{ width: `${axisItem.width}px`, left: `${axisItem.left}px` }"
                      @click="selectChartDatum(idx, axisItem.index)"
                    >{{ axisItem.label }}</text>
                  </view>
                </view>
              </scroll-view>
              <view v-else-if="(msg.chartView || 'chart') === 'table' && !msg.chartCollapsed && buildChartTableRows(msg.chart).length" class="chart-table">
                <view
                  v-for="row in buildChartTableRows(msg.chart)"
                  :key="row.label"
                  class="chart-table-row"
                >
                  <text class="chart-table-label">{{ row.label }}</text>
                  <view class="chart-table-values">
                    <view
                      v-for="item in row.values"
                      :key="item.key"
                      class="chart-table-pill"
                    >
                      <text class="chart-table-name">{{ item.label }}</text>
                      <text class="chart-table-value">{{ item.value }}</text>
                    </view>
                  </view>
                </view>
              </view>
              <view v-else-if="(msg.chartView || 'chart') === 'chart'" class="chart-empty-state">
                图表暂未生成可视化，先切换到“明细”查看数据。
              </view>
            </view>
          </view>
          <view v-if="msg.evidenceClaims?.length" class="analysis-card evidence-card">
            <view class="analysis-card-head">
              <text class="analysis-card-title">证据引用</text>
              <text class="analysis-card-toggle" @click="toggleEvidence(idx)">{{ msg.showEvidence ? '收起' : `展开 ${msg.evidenceClaims.length} 条` }}</text>
            </view>
            <view v-if="msg.showEvidence" class="evidence-list">
              <view v-for="claim in msg.evidenceClaims" :key="claim.claim" class="evidence-item">
                <text class="evidence-claim">{{ claim.claim }}</text>
                <text class="evidence-ref">{{ claim.evidence_refs.join(' · ') }}</text>
              </view>
            </view>
          </view>
          <view v-if="msg.experienceItems?.length" class="experience-card-list">
            <view
              v-for="item in msg.experienceItems"
              :key="item.id"
              class="experience-card"
            >
              <view class="experience-card-head">
                <text class="experience-card-title">{{ item.organized_text || item.source_text || '经验记录' }}</text>
                <text v-if="item.score != null" class="experience-card-score">匹配 {{ formatExperienceScore(item.score) }}</text>
              </view>
              <text v-if="item.source_work_order_id" class="experience-card-meta">来源工单：{{ item.source_work_order_id }}</text>
              <text v-if="item.suggested_steps?.length" class="experience-card-copy">建议：{{ item.suggested_steps.join('，') }}</text>
              <text v-if="item.safety_notes?.length" class="experience-card-copy warn">注意：{{ item.safety_notes.join('，') }}</text>
              <text v-if="item.conflict_flags?.length" class="experience-card-copy risk">
                风险：{{ item.conflict_flags.map(flag => flag.message).filter(Boolean).join('，') }}
              </text>
              <view class="experience-card-footer">
                <text class="experience-card-stats">有用 {{ item.helpful_count || 0 }} · 引用 {{ item.usage_count || 0 }}</text>
                <view class="experience-feedback-row">
                  <text
                    class="experience-feedback-btn"
                    :class="{ active: experienceFeedbackState[item.id] === 'helpful', disabled: !!experienceFeedbackLoading[item.id] }"
                    @click="submitExperienceFeedback(item.id, 'helpful')"
                  >有帮助</text>
                  <text
                    class="experience-feedback-btn"
                    :class="{ active: experienceFeedbackState[item.id] === 'unhelpful', disabled: !!experienceFeedbackLoading[item.id] }"
                    @click="submitExperienceFeedback(item.id, 'unhelpful')"
                  >一般</text>
                  <text
                    class="experience-feedback-btn danger"
                    :class="{ active: experienceFeedbackState[item.id] === 'incorrect', disabled: !!experienceFeedbackLoading[item.id] }"
                    @click="submitExperienceFeedback(item.id, 'incorrect')"
                  >不准确</text>
                </view>
              </view>
            </view>
          </view>
          <view v-if="msg.suggestedFollowups?.length" class="analysis-card followup-card">
            <view class="analysis-card-head">
              <text class="analysis-card-title">继续追问</text>
              <text class="analysis-card-copy">点一下直接发送</text>
            </view>
            <view class="followup-chip-list followup-chip-list--embedded">
              <text
                v-for="followup in msg.suggestedFollowups"
                :key="followup"
                class="followup-chip followup-chip--embedded"
                :class="{ disabled: sending }"
                @click="sendPresetMessage(followup)"
              >{{ followup }}</text>
            </view>
          </view>
        </view>
      </view>

      <!-- 娴佸紡杈撳嚭涓?-->
      <view v-if="streamingText" class="msg ai-msg">
        <view class="msg-bubble ai streaming">
          <text>{{ streamingText }}</text>
          <view class="cursor" />
        </view>
      </view>

      <view style="height: 20rpx" />
    </scroll-view>

    <view v-if="isWorkerMode && stepPlan?.guidance_ready && workflowSteps.length && !dockInput" class="step-panel" :class="{ collapsed: !stepPanelExpanded, expanded: stepPanelExpanded }">
      <view class="step-panel-summary" @click="toggleStepPanel">
        <view class="step-panel-summary-copy">
          <view class="step-panel-head">
            <text class="step-panel-tag">维修流程</text>
            <text class="step-panel-index">{{ completedStepCount }}/{{ workflowSteps.length }} 已完成</text>
          </view>
          <text class="step-panel-title">{{ guidanceStep?.title || '现场排查步骤' }}</text>
          <view class="step-panel-pills">
            <text class="step-panel-pill current">第 {{ activeStepIndex + 1 }} 步</text>
            <text class="step-panel-pill">{{ guidanceStep ? stepStatusLabel(guidanceStep.status) : '待处理' }}</text>
          </view>
          <text class="step-panel-text">{{ stepPanelExpanded ? '左右滑动切换不同步骤' : '展开流程卡片查看完整步骤' }}</text>
        </view>
        <view class="step-panel-toggle">
          <text>{{ stepPanelExpanded ? '收起' : '展开' }}</text>
        </view>
      </view>

      <view v-if="stepPanelExpanded" class="step-panel-body">
        <scroll-view
          scroll-x
          class="step-tab-row"
          :show-scrollbar="false"
        >
          <view class="step-tab-track">
            <text
              v-for="(step, index) in workflowSteps"
              :key="`${step.id}-tab`"
              class="step-tab-chip"
              :class="{
                active: index === stepSwiperCurrent,
                current: step.id === currentStep?.id,
                done: step.status === 'completed',
              }"
              @click="jumpToStep(index)"
            >第 {{ index + 1 }} 步</text>
          </view>
        </scroll-view>

        <swiper
          class="step-swiper"
          :current="stepSwiperCurrent"
          :indicator-dots="false"
          :circular="false"
          :duration="260"
          @change="handleStepSwiperChange"
        >
          <swiper-item v-for="(step, index) in workflowSteps" :key="step.id">
            <scroll-view
              scroll-y
              class="step-swiper-scroll"
              :show-scrollbar="false"
            >
              <view class="step-swiper-item">
                <view
                  class="flow-step-card"
                  :class="{ current: step.id === currentStep?.id, done: step.status === 'completed', skipped: step.status === 'skipped', support: step.status === 'needs_support' }"
                >
                  <view class="flow-step-head">
                    <view>
                      <text class="step-panel-tag">{{ step.id === currentStep?.id ? '当前步骤' : stepStatusLabel(step.status) }}</text>
                      <text class="flow-step-title">{{ step.title }}</text>
                    </view>
                    <text class="flow-step-index">第 {{ index + 1 }} 步</text>
                  </view>
                  <text class="step-panel-text">{{ step.instruction }}</text>
                  <text v-if="step.expected_result" class="step-panel-sub">预期：{{ step.expected_result }}</text>
                  <text v-if="step.risk_note" class="step-panel-sub warn">注意：{{ step.risk_note }}</text>
                  <textarea
                    v-model="stepNotes[step.id]"
                    class="step-note-input"
                    maxlength="300"
                    placeholder="记录这一步的现场读数、发现或备注"
                  />
                  <view class="step-actions">
                    <text class="step-btn note" :class="{ disabled: updatingStepId === step.id || !String(stepNotes[step.id] || '').trim() }" @click="saveStepNoteForStep(step)">备注</text>
                    <text class="step-btn done" :class="{ disabled: updatingStepId === step.id }" @click="markStep(step, 'completed')">完成</text>
                    <text class="step-btn skip" :class="{ disabled: updatingStepId === step.id }" @click="markStep(step, 'skipped')">跳过</text>
                    <text class="step-btn support" :class="{ disabled: updatingStepId === step.id }" @click="markStep(step, 'needs_support')">协同</text>
                  </view>
                </view>
              </view>
            </scroll-view>
          </swiper-item>
        </swiper>

        <view class="step-swiper-footer">
          <text class="step-swiper-counter">第 {{ stepSwiperCurrent + 1 }} / {{ workflowSteps.length }} 步</text>
          <view class="step-swiper-dots">
            <view
              v-for="(step, index) in workflowSteps"
              :key="`${step.id}-dot`"
              class="step-swiper-dot"
              :class="{ active: index === stepSwiperCurrent, done: step.status === 'completed' }"
              @click="jumpToStep(index)"
            />
          </view>
        </view>
      </view>
    </view>

    <!-- 经验推荐 -->
    <view v-if="isWorkerMode && experienceRecommendations.length" class="recommend-panel">
      <view class="recommend-panel-head">
        <text class="recommend-panel-title">经验推荐</text>
        <text class="recommend-panel-subtitle">基于当前工单和维修步骤召回的历史经验</text>
      </view>
      <view
        v-for="item in experienceRecommendations"
        :key="item.experience_id"
        class="recommend-card"
      >
        <view class="recommend-card-head">
          <text class="recommend-card-title">{{ item.organized_text || '经验记录' }}</text>
          <text v-if="item.confidence != null" class="recommend-card-score">匹配 {{ formatExperienceScore(item.confidence) }}</text>
        </view>
        <text v-if="item.source_work_order_id" class="recommend-card-meta">来源工单：{{ item.source_work_order_id }}</text>
        <text v-if="item.safety_notes?.length" class="recommend-card-copy warn">注意：{{ item.safety_notes.join('，') }}</text>
        <text v-if="item.conflict_flags?.length" class="recommend-card-copy risk">
          风险：{{ item.conflict_flags.map(flag => flag.message).filter(Boolean).join('，') }}
        </text>
        <view class="recommend-card-footer">
          <text class="recommend-card-stats">已有 {{ item.helpful_count || 0 }} 次正向反馈</text>
          <view class="experience-feedback-row">
            <text
              class="experience-feedback-btn"
              :class="{ active: experienceFeedbackState[item.experience_id] === 'helpful', disabled: !!experienceFeedbackLoading[item.experience_id] }"
              @click="submitExperienceFeedback(item.experience_id, 'helpful')"
            >有帮助</text>
            <text
              class="experience-feedback-btn"
              :class="{ active: experienceFeedbackState[item.experience_id] === 'unhelpful', disabled: !!experienceFeedbackLoading[item.experience_id] }"
              @click="submitExperienceFeedback(item.experience_id, 'unhelpful')"
            >一般</text>
            <text
              class="experience-feedback-btn danger"
              :class="{ active: experienceFeedbackState[item.experience_id] === 'incorrect', disabled: !!experienceFeedbackLoading[item.experience_id] }"
              @click="submitExperienceFeedback(item.experience_id, 'incorrect')"
            >不准确</text>
          </view>
        </view>
      </view>
    </view>
    <view class="chat-input-area">
      <template v-if="isWorkerMode && dockInput">
        <view
          v-if="showFloatingWorkflowEntry"
          class="floating-step-wrap"
        >
          <view v-if="stepPanelExpanded" class="floating-step-popover">
            <view class="floating-step-popover-head">
              <view class="floating-step-popover-copy">
                <text class="floating-step-popover-tag">维修流程</text>
                <text class="floating-step-popover-title">{{ guidanceStep?.title || '现场排查步骤' }}</text>
                <text class="floating-step-popover-sub">{{ completedStepCount }}/{{ workflowSteps.length }} 已完成，左右滑动查看不同步骤</text>
              </view>
              <text class="floating-step-popover-close" @click.stop="toggleStepPanel">收起</text>
            </view>

            <view class="step-panel-body floating">
              <scroll-view
                scroll-x
                class="step-tab-row"
                :show-scrollbar="false"
              >
                <view class="step-tab-track">
                  <text
                    v-for="(step, index) in workflowSteps"
                    :key="`${step.id}-floating-tab`"
                    class="step-tab-chip"
                    :class="{
                      active: index === stepSwiperCurrent,
                      current: step.id === currentStep?.id,
                      done: step.status === 'completed',
                    }"
                    @click="jumpToStep(index)"
                  >第 {{ index + 1 }} 步</text>
                </view>
              </scroll-view>

              <swiper
                class="step-swiper floating"
                :current="stepSwiperCurrent"
                :indicator-dots="false"
                :circular="false"
                :duration="260"
                @change="handleStepSwiperChange"
              >
                <swiper-item v-for="(step, index) in workflowSteps" :key="`${step.id}-floating`">
                  <scroll-view
                    scroll-y
                    class="step-swiper-scroll"
                    :show-scrollbar="false"
                  >
                    <view class="step-swiper-item">
                      <view
                        class="flow-step-card"
                        :class="{ current: step.id === currentStep?.id, done: step.status === 'completed', skipped: step.status === 'skipped', support: step.status === 'needs_support' }"
                      >
                        <view class="flow-step-head">
                          <view>
                            <text class="step-panel-tag">{{ step.id === currentStep?.id ? '当前步骤' : stepStatusLabel(step.status) }}</text>
                            <text class="flow-step-title">{{ step.title }}</text>
                          </view>
                          <text class="flow-step-index">第 {{ index + 1 }} 步</text>
                        </view>
                        <text class="step-panel-text">{{ step.instruction }}</text>
                        <text v-if="step.expected_result" class="step-panel-sub">预期：{{ step.expected_result }}</text>
                        <text v-if="step.risk_note" class="step-panel-sub warn">注意：{{ step.risk_note }}</text>
                        <textarea
                          v-model="stepNotes[step.id]"
                          class="step-note-input"
                          maxlength="300"
                          placeholder="记录这一步的现场读数、发现或备注"
                        />
                        <view class="step-actions">
                          <text class="step-btn note" :class="{ disabled: updatingStepId === step.id || !String(stepNotes[step.id] || '').trim() }" @click="saveStepNoteForStep(step)">备注</text>
                          <text class="step-btn done" :class="{ disabled: updatingStepId === step.id }" @click="markStep(step, 'completed')">完成</text>
                          <text class="step-btn skip" :class="{ disabled: updatingStepId === step.id }" @click="markStep(step, 'skipped')">跳过</text>
                          <text class="step-btn support" :class="{ disabled: updatingStepId === step.id }" @click="markStep(step, 'needs_support')">协同</text>
                        </view>
                      </view>
                    </view>
                  </scroll-view>
                </swiper-item>
              </swiper>

              <view class="step-swiper-footer">
                <text class="step-swiper-counter">第 {{ stepSwiperCurrent + 1 }} / {{ workflowSteps.length }} 步</text>
                <view class="step-swiper-dots">
                  <view
                    v-for="(step, index) in workflowSteps"
                    :key="`${step.id}-floating-dot`"
                    class="step-swiper-dot"
                    :class="{ active: index === stepSwiperCurrent, done: step.status === 'completed' }"
                    @click="jumpToStep(index)"
                  />
                </view>
              </view>
            </view>
          </view>

          <view
            class="floating-step-chip"
            :class="{ active: stepPanelExpanded }"
            @click="toggleStepPanel"
          >
            <view class="floating-step-icon" aria-hidden="true">
              <view class="floating-step-icon-line short" />
              <view class="floating-step-icon-line" />
              <view class="floating-step-icon-line" />
            </view>
            <text class="floating-step-chip-label">维修流程</text>
            <text class="floating-step-chip-badge">第 {{ activeStepIndex + 1 }} 步</text>
          </view>
        </view>

        <view class="worker-input-pill" :class="{ 'voice-mode': voiceInputMode }">
          <view
            class="input-icon-btn camera input-camera-btn"
            :class="{ disabled: mediaBusy }"
            @click="chooseCameraForAnalysis"
          >
            <image class="chat-control-icon camera-icon-img" src="/static/icons/chat-camera.svg" mode="aspectFit" />
          </view>
          <view
            v-if="voiceInputMode"
            class="voice-hold-area"
            :class="{ active: recording, disabled: mediaBusy && !recording }"
            @touchstart.stop.prevent="startVoiceHold"
            @touchend.stop.prevent="stopVoiceHold"
            @touchcancel.stop.prevent="stopVoiceHold"
            @mousedown.stop.prevent="startVoiceHold"
            @mouseup.stop.prevent="stopVoiceHold"
            @mouseleave.stop.prevent="stopVoiceHold"
          >
            <text>{{ recording ? '松开发送' : '按住说话' }}</text>
          </view>
          <textarea
            v-else
            class="chat-input"
            v-model="inputText"
            :placeholder="inputPlaceholder"
            placeholder-style="color: #9ca19a;"
            :disabled="sending"
            :maxlength="500"
            confirm-type="send"
            @confirm="sendMessage"
          />
          <view
            class="input-icon-btn input-mode-toggle"
            :class="{ active: voiceInputMode, disabled: mediaBusy && !recording }"
            @click="toggleVoiceInputMode"
          >
            <image
              v-if="voiceInputMode"
              class="chat-control-icon keyboard-icon-img"
              src="/static/icons/chat-keyboard.svg"
              mode="aspectFit"
            />
            <image
              v-else
              class="chat-control-icon"
              src="/static/icons/chat-voice.svg"
              mode="aspectFit"
            />
          </view>
        </view>
      </template>
      <template v-else>
        <view v-if="isWorkerMode" class="media-tools">
          <text class="media-btn" :class="{ disabled: mediaBusy }" @click="chooseImageForAnalysis()">拍照</text>
          <text class="media-btn" :class="{ active: recording, disabled: mediaBusy }" @click="toggleRecording">{{ recording ? '停止' : '语音' }}</text>
        </view>
        <textarea
          class="chat-input"
          v-model="inputText"
          :placeholder="inputPlaceholder"
          placeholder-style="color: #9ca19a;"
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
      </template>
    </view>
    <view v-if="messageMenuVisible" class="message-menu-mask" @click="closeAiMessageMenu">
      <view class="message-menu" :style="messageMenuStyle" @click.stop>
        <view class="message-menu-item" @click="copyAiMessage">
          <text class="message-menu-icon">复</text>
          <text>复制</text>
        </view>
        <view class="message-menu-item" @click="selectAiMessageText">
          <text class="message-menu-icon">选</text>
          <text>选取文本</text>
        </view>
        <view class="message-menu-item" @click="speakAiMessage">
          <text class="message-menu-icon">读</text>
          <text>朗读</text>
        </view>
      </view>
    </view>

    <view v-if="selectedTextVisible" class="select-text-mask" @click="closeSelectedText">
      <view class="select-text-panel" @click.stop>
        <view class="select-text-head">
          <text class="select-text-title">选取文本</text>
          <text class="select-text-close" @click="closeSelectedText">关闭</text>
        </view>
        <text class="select-text-content" selectable>{{ selectedTextContent }}</text>
      </view>
    </view>
  </view>
</template>

<script setup lang="ts">
import { ref, nextTick, computed, onBeforeUnmount, onMounted, watch, getCurrentInstance } from 'vue'
import { DotLottieVue } from '@lottiefiles/dotlottie-vue'
import type { WorkOrder } from '../api/workorder'
import {
  sendChatMessage,
  buildContextMessage,
  type ThinkingEvent,
  type TextEvent,
} from '../api/chat'
import {
  buildAbsoluteApiUrl,
  operatorAiApi,
  workerAiApi,
  type WorkerAiChatResponse,
  type OperatorAiChatResponse,
  type WorkerAiHistoryMessage,
  type WorkerAiGuidanceChatResponse,
  type WorkerAiStep,
  type WorkerAiStepPlan,
  type WorkerAiStepStatus,
} from '../api/ai-assistant'
import {
  maintenanceExperienceApi,
  type MaintenanceExperienceFeedbackType,
  type MaintenanceExperienceItem,
  type MaintenanceExperienceRecommendation,
} from '../api/maintenance-experience'
import { workerProfileApi } from '../api/workerProfile'
import { getBuildingLabel } from '../constants/buildings'

interface ChatMsg {
  role: 'user' | 'ai'
  content: string
  thinking?: boolean
  stepId?: string
  answerType?: string
  experienceItems?: MaintenanceExperienceItem[]
  suggestedFollowups?: string[]
  chart?: Record<string, any> | null
  chartVisual?: Record<string, any> | null
  chartCollapsed?: boolean
  chartView?: 'chart' | 'table'
  selectedSeriesIndex?: number
  activeChartIndex?: number
  metrics?: Record<string, any> | null
  scope?: Record<string, any> | null
  evidenceClaims?: Array<{ claim: string; evidence_refs: string[] }>
  evidenceRefs?: string[]
  blockedActions?: string[]
  readonly?: boolean
  showEvidence?: boolean
}

interface OperatorFilterOption {
  value: string
  label: string
}

const emit = defineEmits<{
  (e: 'order-updated', order: WorkOrder): void
}>()
const componentInstance = getCurrentInstance()

const props = withDefaults(defineProps<{
  order?: WorkOrder | null
  title?: string
  hint?: string
  mode?: 'general' | 'operator' | 'worker'
  dispatchId?: string | null
  hallEntryId?: string | null
  dockInput?: boolean
}>(), {
  order: null,
  title: 'AI 辅助维修',
  hint: '',
  mode: 'general',
  dispatchId: null,
  hallEntryId: null,
  dockInput: false,
})

const messages = ref<ChatMsg[]>([])
const inputText = ref('')
const sending = ref(false)
const streamingText = ref('')
const sessionId = ref<string | null>(null)
const scrollTop = ref(0)
const isFirstMessage = ref(true)
const stepPlan = ref<WorkerAiStepPlan | null>(null)
const guidanceLoading = ref(false)
const updatingStepId = ref<string | null>(null)
const mediaBusy = ref(false)
const recording = ref(false)
const voiceInputMode = ref(false)
const stepNotes = ref<Record<string, string>>({})
const stepPanelExpanded = ref(false)
const stepSwiperCurrent = ref(0)
const componentReady = ref(false)
const introducedPlanId = ref('')
const activeHistoryKey = ref('')
const historyLoadedKey = ref('')
const messageMenuContent = ref('')
const messageMenuVisible = ref(false)
const messageMenuStyle = ref<Record<string, string>>({})
const selectedTextVisible = ref(false)
const selectedTextContent = ref('')
const experienceFeedbackLoading = ref<Record<string, MaintenanceExperienceFeedbackType | ''>>({})
const experienceFeedbackState = ref<Record<string, MaintenanceExperienceFeedbackType | ''>>({})
const operatorFilterLoading = ref(false)
const operatorDatePreset = ref<'today' | 'week' | 'month' | '7d' | '30d'>('month')
const operatorBuildingId = ref('')
const operatorTeamId = ref('')
const operatorWorkerId = ref('')
const operatorBuildingOptions = ref<OperatorFilterOption[]>([{ value: '', label: '全部楼宇' }])
const operatorTeamOptions = ref<OperatorFilterOption[]>([{ value: '', label: '全部班组' }])
const operatorWorkerOptions = ref<OperatorFilterOption[]>([{ value: '', label: '全部人员' }])
let recorderManager: any = null
let h5MediaRecorder: MediaRecorder | null = null
let h5AudioChunks: BlobPart[] = []
let stepPlanLoadPromise: Promise<void> | null = null
let recordingStopRequested = false

const chatTitle = computed(() => props.title)
const isWorkerMode = computed(() => props.mode === 'worker' && !!props.order)
const isOperatorMode = computed(() => props.mode === 'operator')
const isOperatorWorkbench = computed(() => isOperatorMode.value && !props.order)
const dockInput = computed(() => props.dockInput)
const showOperatorWorkbenchHero = computed(() => Boolean(
  isOperatorWorkbench.value
    && isFirstMessage.value
    && !messages.value.length
    && !sending.value,
))
const showMessageList = computed(() => !showOperatorWorkbenchHero.value)
const showChatHeader = computed(() => !isOperatorWorkbench.value)
const showTopQuickPromptBar = computed(() => Boolean(
  isOperatorMode.value
    && operatorQuickPrompts.value.length
    && !isOperatorWorkbench.value,
))
const showWelcomeBubble = computed(() => !isOperatorWorkbench.value)
const inputPlaceholder = computed(() => (
  isOperatorWorkbench.value
    ? '直接输入问题或点击快捷问法'
    : isWorkerMode.value && dockInput.value
      ? '发消息...'
      : '描述现场情况或提问...'
))
const chatHint = computed(() => props.hint || (
  isWorkerMode.value
    ? '把现场情况发我，我陪你判断下一步'
    : isOperatorMode.value
      ? (props.order ? '只读查看当前工单进展、维修指导和现场记录' : '只读查询工单、班组、楼宇和时间范围运营分析')
      : '可以咨询能耗、工单、派工和现场处置问题'
))
const orderIntro = computed(() => {
  if (!props.order) return ''
  const issue = props.order.issue_description?.slice(0, 60) || '现场情况待补充'
  return `${props.order.building_id} - ${issue}`
})
const welcomeLead = computed(() => props.order ? '您好！我已了解当前工单情况：' : '您好，我是楼宇运维 AI 助手。')
const welcomeBody = computed(() => (
  isWorkerMode.value
    ? '不用一次说全，先告诉我眼前看到什么。'
    : isOperatorMode.value
      ? (
        props.order
          ? '可以直接问我这张工单目前到哪一步、是否超时、维修指导做到哪一步了，或最近有没有图片、语音和协同记录。'
          : '可以直接查询工单进度、派工状态、维修指导记录和风险说明。'
      )
      : '可以直接咨询能耗分析、派工处理、维修流程或现场处置问题。'
))
const currentStep = computed<WorkerAiStep | null>(() => {
  const steps = stepPlan.value?.steps || []
  return steps.find(step => step.status === 'pending' || step.status === 'uncertain')
    || steps.find(step => step.status === 'needs_support')
    || steps.find(step => step.status !== 'completed' && step.status !== 'skipped')
    || null
})
const guidanceStep = computed<WorkerAiStep | null>(() => {
  const steps = stepPlan.value?.steps || []
  return currentStep.value || steps[0] || null
})
const workflowSteps = computed<WorkerAiStep[]>(() => stepPlan.value?.steps || [])
const completedStepCount = computed(() => workflowSteps.value.filter(step => step.status === 'completed').length)
const activeStepIndex = computed(() => {
  const target = guidanceStep.value
  if (!target) return 0
  const index = stepIndex(target.id)
  return index >= 0 ? index : 0
})
const showFloatingWorkflowEntry = computed(() => Boolean(
  isWorkerMode.value
    && dockInput.value
    && stepPlan.value?.guidance_ready
    && workflowSteps.value.length,
))
const experienceRecommendations = computed<MaintenanceExperienceRecommendation[]>(() => (
  stepPlan.value?.experience_recommendations || []
))
const operatorDateOptions = computed<OperatorFilterOption[]>(() => ([
  { value: 'today', label: '今天' },
  { value: 'week', label: '本周' },
  { value: 'month', label: '本月' },
  { value: '7d', label: '近7天' },
  { value: '30d', label: '近30天' },
]))
const operatorQuickPrompts = computed(() => {
  if (!isOperatorMode.value) return []
  if (props.order?.ticket_id) {
    const subject = `这张工单 ${props.order.ticket_id}`
    return [
      `${subject} 完整流程是什么？`,
      `${subject} 为什么超时？`,
      `${subject} 最近有哪些相关经验？`,
    ]
  }
  return [
    '生成本月工单运营总结',
    '对比本周和上周公共楼工单处理效率',
    '这个月谁处理得最多',
    '本周哪个班组超时率最高',
  ]
})
const operatorScopePreview = computed(() => {
  const items = [
    selectedOptionLabel(operatorDateOptions.value, operatorDatePreset.value, '本月'),
    operatorBuildingId.value ? selectedOptionLabel(operatorBuildingOptions.value, operatorBuildingId.value, '全部楼宇') : '',
    operatorTeamId.value ? selectedOptionLabel(operatorTeamOptions.value, operatorTeamId.value, '全部班组') : '',
    operatorWorkerId.value ? selectedOptionLabel(operatorWorkerOptions.value, operatorWorkerId.value, '全部人员') : '',
  ].filter(Boolean)
  return items as string[]
})

function getErrorMessage(err: unknown, fallback: string) {
  if (err instanceof Error && err.message) return err.message
  if (typeof err === 'object' && err) {
    const message = (err as any).errMsg || (err as any).message || (err as any).detail
    if (typeof message === 'string' && message.trim()) return message.trim()
  }
  return fallback
}

function messageBubbleId(index: number) {
  return `ai-message-bubble-${index}`
}

function rpxToPx(value: number) {
  try {
    const info = uni.getSystemInfoSync()
    return (info.windowWidth || 375) * value / 750
  } catch {
    return value / 2
  }
}

function queryRect(selector: string): Promise<any | null> {
  return new Promise((resolve) => {
    const query = componentInstance?.proxy
      ? uni.createSelectorQuery().in(componentInstance.proxy)
      : uni.createSelectorQuery()
    query.select(selector).boundingClientRect((rect: any) => resolve(rect || null)).exec()
  })
}

function buildMessageMenuStyle(rect: { top: number; left: number; width: number; height: number }) {
  const info = uni.getSystemInfoSync()
  const sideGap = rpxToPx(24)
  const menuWidth = Math.min(rpxToPx(580), Math.max(220, (info.windowWidth || 375) - sideGap * 2))
  const menuHeight = rpxToPx(276)
  const anchorGap = rpxToPx(14)
  const dockedReserve = dockInput.value
    ? rpxToPx(showFloatingWorkflowEntry.value && stepPanelExpanded.value ? 860 : showFloatingWorkflowEntry.value ? 340 : 220)
    : rpxToPx(48)
  const maxTop = Math.max(sideGap, (info.windowHeight || 667) - dockedReserve - menuHeight)
  let top = rect.top + rect.height + anchorGap
  if (top > maxTop) {
    top = rect.top - menuHeight - anchorGap
  }
  top = Math.max(sideGap, Math.min(top, (info.windowHeight || 667) - menuHeight - sideGap))

  let left = rect.left
  if (rect.width < menuWidth) {
    left = rect.left + (rect.width - menuWidth) / 2
  }
  left = Math.max(sideGap, Math.min(left, (info.windowWidth || 375) - menuWidth - sideGap))

  return {
    top: `${top}px`,
    left: `${left}px`,
    bottom: 'auto',
  }
}

function pushUniqueAiMessage(content: string) {
  const last = messages.value[messages.value.length - 1]
  if (last?.role === 'ai' && last.content === content) return
  messages.value.push({ role: 'ai', content })
}

function shouldPreferWorkerGeneralChat(text: string) {
  const normalized = String(text || '').trim().toLowerCase()
  if (!normalized) return true
  const pureGreeting = new Set([
    '你好', '您好', 'hi', 'hello', '哈喽', '在吗', '在不在', '喂',
    '好的', '好', '行', '可以', '嗯', '嗯嗯', 'ok',
  ])
  if (pureGreeting.has(normalized)) return true
  if (normalized.length <= 6 && !/[0-9]/.test(normalized) && !/[?？]/.test(normalized)) return true
  if (/(你是谁|你是干嘛的|你能做什么|怎么用|怎么帮我|我是新手|还没开始|不会做)/.test(normalized)) return true
  return false
}

function formatExperienceScore(score: number | null | undefined) {
  if (score == null || Number.isNaN(Number(score))) return '--'
  const normalized = Math.max(0, Math.min(1, Number(score)))
  return `${Math.round(normalized * 100)}%`
}

function normalizeExperienceItems(facts: unknown): MaintenanceExperienceItem[] {
  if (!facts || typeof facts !== 'object') return []
  const rawItems = Array.isArray((facts as any).items) ? (facts as any).items : []
  return rawItems.filter((item: unknown) => !!item && typeof item === 'object') as MaintenanceExperienceItem[]
}

function normalizeEvidenceClaims(
  facts: unknown,
  evidenceRefs: string[] | undefined,
): Array<{ claim: string; evidence_refs: string[] }> {
  if (facts && typeof facts === 'object' && Array.isArray((facts as any).claims)) {
    return (facts as any).claims
      .filter((item: unknown) => !!item && typeof item === 'object')
      .map((item: any) => ({
        claim: String(item.claim || '').trim(),
        evidence_refs: Array.isArray(item.evidence_refs)
          ? item.evidence_refs.map((ref: unknown) => String(ref || '').trim()).filter(Boolean)
          : [],
      }))
      .filter((item: { claim: string }) => !!item.claim)
  }
  return (evidenceRefs || []).length
    ? [{ claim: '本次回答引用了以下证据来源', evidence_refs: evidenceRefs || [] }]
    : []
}

function selectedOptionLabel(options: OperatorFilterOption[], value: string, fallback: string) {
  if (!value) return fallback
  return options.find(item => item.value === value)?.label || fallback
}

function splitMessageContent(text: string) {
  const paragraphs = String(text || '')
    .split(/\n+/)
    .map(item => item.trim())
    .filter(Boolean)
  return paragraphs.length ? paragraphs : ['']
}

function shouldRenderMessageExtensions(msg: ChatMsg) {
  return Boolean(
    msg.readonly
      || msg.chart
      || msg.evidenceClaims?.length
      || msg.blockedActions?.length
      || msg.experienceItems?.length
      || msg.suggestedFollowups?.length,
  )
}

function shouldRenderOperatorSummaryCard(msg: ChatMsg) {
  return Boolean(
    isOperatorMode.value
      && msg.role === 'ai'
      && msg.readonly
      && msg.answerType !== 'greeting'
      && String(msg.content || '').trim(),
  )
}

function normalizeScopeStatusLabels(statusValue: unknown) {
  const labels: Record<string, string> = {
    pending_dispatch: '待派工',
    dispatched: '已派工',
    processing: '处理中',
    waiting_support: '待协同',
    pending_close: '待关闭',
    overdue: '超时',
    closed: '已关闭',
    completed: '已完成',
  }
  const values = Array.isArray(statusValue) ? statusValue : [statusValue]
  return values
    .map(item => String(item || '').trim())
    .filter(Boolean)
    .map(item => labels[item] || item)
}

function analysisScopeChips(msg: ChatMsg) {
  const scope = msg.scope || {}
  const chips = [
    scope.date_label ? String(scope.date_label) : '',
    scope.building_id ? getBuildingLabel(String(scope.building_id), String(scope.building_id)) : '',
    scope.team_name ? String(scope.team_name) : '',
    scope.worker_name ? String(scope.worker_name) : '',
    ...normalizeScopeStatusLabels(scope.status).map(item => `状态 · ${item}`),
  ].filter(Boolean)
  return chips as string[]
}

function formatSummaryValue(value: unknown, unit = '') {
  if (value === null || value === undefined || value === '') return '--'
  if (typeof value === 'number') {
    const normalized = Number.isInteger(value) ? String(value) : value.toFixed(1)
    return `${normalized}${unit}`
  }
  return `${String(value)}${unit}`
}

function analysisSummaryStats(msg: ChatMsg) {
  const summary = (msg.metrics && typeof msg.metrics === 'object' ? msg.metrics.summary : null) as Record<string, any> | null
  if (!summary) return [] as Array<{ label: string; value: string }>
  const items: Array<{ label: string; value: string }> = []
  if (msg.answerType === 'monthly_report' || msg.answerType === 'weekly_report' || msg.answerType === 'daily_report') {
    items.push(
      { label: '新增工单', value: formatSummaryValue(summary.created_count, ' 单') },
      { label: '完成', value: formatSummaryValue(summary.completed_count, ' 单') },
      { label: '超时', value: formatSummaryValue(summary.overdue_count, ' 单') },
      { label: '平均到场', value: formatSummaryValue(summary.avg_arrive_minutes, ' 分钟') },
    )
    if (summary.top_building) items.push({ label: '热点楼宇', value: formatSummaryValue(summary.top_building) })
    if (summary.top_worker) items.push({ label: '高频处理人', value: formatSummaryValue(summary.top_worker) })
    return items.filter(item => item.value !== '--')
  }
  if (msg.answerType === 'comparison_analysis') {
    return [
      { label: '当前新增', value: formatSummaryValue(summary.current_created_count, ' 单') },
      { label: '上期新增', value: formatSummaryValue(summary.previous_created_count, ' 单') },
      { label: '当前超时', value: formatSummaryValue(summary.current_overdue_count, ' 单') },
      { label: '当前到场', value: formatSummaryValue(summary.current_avg_arrive_minutes, ' 分钟') },
    ].filter(item => item.value !== '--')
  }
  if (msg.answerType === 'open_work_order_analysis') {
    return [
      { label: '未完成总量', value: formatSummaryValue(summary.open_total, ' 单') },
      { label: '待派工/已派工', value: formatSummaryValue(summary.pending_dispatch_count, ' 单') },
      { label: '处理中', value: formatSummaryValue(summary.processing_count, ' 单') },
      { label: '待协同', value: formatSummaryValue(summary.waiting_support_count, ' 单') },
      { label: '待关闭', value: formatSummaryValue(summary.pending_close_count, ' 单') },
      { label: '超时', value: formatSummaryValue(summary.overdue_total, ' 单') },
    ].filter(item => item.value !== '--')
  }
  if (msg.answerType === 'worker_performance') {
    return [
      { label: '人员数', value: formatSummaryValue(summary.workers) },
      { label: '派工总量', value: formatSummaryValue(summary.assigned_total, ' 单') },
      { label: '完成总量', value: formatSummaryValue(summary.completed_total, ' 单') },
      { label: '超时总量', value: formatSummaryValue(summary.overdue_total, ' 单') },
    ].filter(item => item.value !== '--')
  }
  if (msg.answerType === 'team_performance') {
    return [
      { label: '班组数', value: formatSummaryValue(summary.teams) },
      { label: '派工总量', value: formatSummaryValue(summary.assigned_total, ' 单') },
      { label: '完成总量', value: formatSummaryValue(summary.completed_total, ' 单') },
      { label: '超时总量', value: formatSummaryValue(summary.overdue_total, ' 单') },
    ].filter(item => item.value !== '--')
  }
  if (msg.answerType === 'building_hotspot') {
    return [
      { label: '楼宇数', value: formatSummaryValue(summary.buildings) },
    ].filter(item => item.value !== '--')
  }
  if (msg.answerType === 'overdue_analysis') {
    return [
      { label: '超时总量', value: formatSummaryValue(summary.overdue_total, ' 单') },
    ].filter(item => item.value !== '--')
  }
  const fallbackEntries = Object.entries(summary)
    .filter(([, value]) => ['number', 'string'].includes(typeof value))
    .slice(0, 4)
    .map(([key, value]) => ({ label: key, value: formatSummaryValue(value) }))
  return fallbackEntries.filter(item => item.value !== '--')
}

function toIsoDate(target: Date) {
  return target.toISOString().slice(0, 10)
}

function resolveOperatorDateScope(preset: 'today' | 'week' | 'month' | '7d' | '30d') {
  const now = new Date()
  const end = new Date(now)
  const start = new Date(now)
  if (preset === 'today') {
    return { date_from: toIsoDate(start), date_to: toIsoDate(end) }
  }
  if (preset === 'week') {
    const day = start.getDay()
    const delta = day === 0 ? 6 : day - 1
    start.setDate(start.getDate() - delta)
    return { date_from: toIsoDate(start), date_to: toIsoDate(end) }
  }
  if (preset === 'month') {
    start.setDate(1)
    return { date_from: toIsoDate(start), date_to: toIsoDate(end) }
  }
  const days = preset === '30d' ? 29 : 6
  start.setDate(start.getDate() - days)
  return { date_from: toIsoDate(start), date_to: toIsoDate(end) }
}

async function loadOperatorFilters() {
  if (!isOperatorWorkbench.value || operatorFilterLoading.value) return
  operatorFilterLoading.value = true
  try {
    const [options, workers] = await Promise.all([
      workerProfileApi.options(),
      workerProfileApi.list(),
    ])
    operatorBuildingOptions.value = [
      { value: '', label: '全部楼宇' },
      ...(options.buildings || []).map(item => ({
        value: item.primary_space_usage || item.building_id,
        label: getBuildingLabel(item.primary_space_usage || item.building_id, item.building_id),
      })),
    ].filter((item, index, list) => list.findIndex(candidate => candidate.value === item.value) === index)
    operatorTeamOptions.value = [
      { value: '', label: '全部班组' },
      ...(options.teams || []).map(item => ({ value: item.id, label: item.name })),
    ]
    operatorWorkerOptions.value = [
      { value: '', label: '全部人员' },
      ...(workers.profiles || []).map(item => ({
        value: item.user.id,
        label: item.user.username,
      })),
    ]
  } catch (err) {
    console.warn('[AiChat] 运营分析筛选项加载失败', err)
  } finally {
    operatorFilterLoading.value = false
  }
}

function buildOperatorScope(source: string) {
  const dateScope = resolveOperatorDateScope(operatorDatePreset.value)
  return {
    source_component: source,
    ...dateScope,
    building_id: operatorBuildingId.value || undefined,
    team_id: operatorTeamId.value || undefined,
    team_name: operatorTeamId.value ? selectedOptionLabel(operatorTeamOptions.value, operatorTeamId.value, '班组') : undefined,
    worker_id: operatorWorkerId.value || undefined,
    worker_name: operatorWorkerId.value ? selectedOptionLabel(operatorWorkerOptions.value, operatorWorkerId.value, '人员') : undefined,
    work_order_status: props.order?.status || null,
    execution_status: props.order?.current_dispatch?.execution_status || props.order?.execution_status || null,
  }
}

function chartSeriesTabs(chart: Record<string, any> | null | undefined) {
  const series = Array.isArray(chart?.series) ? chart.series : []
  return series.map((entry: any, index: number) => ({
    key: `${entry?.name || 'series'}_${index}`,
    label: String(entry?.name || `系列 ${index + 1}`),
  }))
}

function clampSeriesIndex(chart: Record<string, any> | null | undefined, index: number) {
  const series = Array.isArray(chart?.series) ? chart.series : []
  if (!series.length) return 0
  return Math.max(0, Math.min(index, series.length - 1))
}

function chartSeriesName(chart: Record<string, any> | null | undefined, selectedSeriesIndex = 0) {
  const series = Array.isArray(chart?.series) ? chart.series : []
  if (!series.length) return '数值'
  const seriesIndex = clampSeriesIndex(chart, selectedSeriesIndex)
  return String(series[seriesIndex]?.name || `系列 ${seriesIndex + 1}`)
}

function inferChartNumericUnit(seriesName: string) {
  if (/%|率/i.test(seriesName)) return '%'
  if (/分钟|minutes?/i.test(seriesName)) return '分钟'
  if (/次数|次/i.test(seriesName)) return '次'
  if (/工单|单|数量|count|超时/i.test(seriesName)) return '单'
  return '值'
}

function formatChartNumber(value: unknown, unit = '') {
  const numeric = Number(value)
  if (!Number.isFinite(numeric)) return '--'
  const normalized = Math.abs(numeric) >= 100
    ? Math.round(numeric)
    : Number.isInteger(numeric)
      ? numeric
      : Number(numeric.toFixed(1))
  if (!unit || unit === '值') return String(normalized)
  if (unit === '%') return `${normalized}${unit}`
  return `${normalized}${unit}`
}

function buildChartRows(chart: Record<string, any> | null | undefined, selectedSeriesIndex = 0) {
  if (!chart || typeof chart !== 'object') return []
  const x = Array.isArray(chart.x) ? chart.x.map((item: unknown) => String(item)) : []
  const series = Array.isArray(chart.series) ? chart.series : []
  if (!x.length || !series.length) return []
  const seriesIndex = clampSeriesIndex(chart, selectedSeriesIndex)
  const primarySeries = series[seriesIndex] || series[0]
  const primary = Array.isArray(primarySeries?.data) ? primarySeries.data : []
  const unit = inferChartNumericUnit(String(primarySeries?.name || ''))
  return x.map((label: string, index: number) => {
    const secondaryValues = series
      .filter((_: any, currentIndex: number) => currentIndex !== seriesIndex)
      .map((entry: any) => {
        const entryName = String(entry?.name || '值')
        return `${entryName} ${formatChartNumber(entry?.data?.[index] ?? 0, inferChartNumericUnit(entryName))}`
      })
      .join(' · ')
    const rawValue = primary[index] ?? 0
    return {
      index,
      label,
      rawValue: Number(rawValue || 0),
      primaryValue: `${primarySeries?.name || '值'} ${formatChartNumber(rawValue, unit)}`,
      secondaryValues,
    }
  })
}

function truncateChartAxisLabel(label: string) {
  const value = String(label || '')
  return value.length > 8 ? `${value.slice(0, 8)}...` : value
}

function resolveDefaultSeriesIndex(chart: Record<string, any> | null | undefined) {
  const series = Array.isArray(chart?.series) ? chart.series : []
  if (!series.length) return 0
  let targetIndex = 0
  let targetScore = Number.NEGATIVE_INFINITY
  series.forEach((entry: any, index: number) => {
    const values = Array.isArray(entry?.data) ? entry.data.map((item: unknown) => Number(item || 0)) : []
    if (!values.length) return
    const maxAbs = Math.max(...values.map(item => Math.abs(item)), 0)
    const nonZeroCount = values.filter(item => item !== 0).length
    const uniqueCount = new Set(values.map(item => String(item))).size
    const score = maxAbs * 100 + nonZeroCount * 10 + uniqueCount
    if (score >= targetScore) {
      targetScore = score
      targetIndex = index
    }
  })
  return targetIndex
}

function resolveDefaultActiveChartIndex(chart: Record<string, any> | null | undefined, selectedSeriesIndex = 0) {
  const rows = buildChartRows(chart, selectedSeriesIndex)
  if (!rows.length) return 0
  let targetIndex = 0
  let targetValue = Number.NEGATIVE_INFINITY
  rows.forEach((item, index) => {
    const numeric = Number(item.rawValue || 0)
    if (numeric >= targetValue) {
      targetValue = numeric
      targetIndex = index
    }
  })
  return targetIndex
}

function chartXAxisUnit(msg: ChatMsg) {
  const groupBy = String(msg.scope?.group_by || '')
  if (groupBy === 'day') return '日期'
  if (groupBy === 'period') return '周期'
  if (groupBy === 'status') return '状态'
  if (groupBy === 'team') return '班组'
  if (groupBy === 'building') return '楼宇'
  if (groupBy === 'worker') return '人员'
  if (groupBy === 'experience') return '经验'
  const x = Array.isArray(msg.chart?.x) ? msg.chart.x : []
  if (x.every((item: unknown) => /^\d{4}-\d{2}-\d{2}$/.test(String(item || '')))) return '日期'
  return '维度'
}

function chartYAxisUnit(msg: ChatMsg) {
  return inferChartNumericUnit(chartSeriesName(msg.chart, msg.selectedSeriesIndex ?? 0))
}

function chartYAxisLabel(msg: ChatMsg) {
  const seriesName = chartSeriesName(msg.chart, msg.selectedSeriesIndex ?? 0)
  const unit = chartYAxisUnit(msg)
  if (!unit || unit === '值') return seriesName
  if (seriesName.includes(unit)) return seriesName
  return `${seriesName}（${unit}）`
}

function activeChartDatum(msg: ChatMsg) {
  const rows = buildChartRows(msg.chart, msg.selectedSeriesIndex ?? 0)
  if (!rows.length) return null
  const index = Math.max(0, Math.min(msg.activeChartIndex ?? 0, rows.length - 1))
  return rows[index] || rows[0]
}

function buildChartVisualModel(
  chart: Record<string, any> | null | undefined,
  selectedSeriesIndex = 0,
  activeIndex = 0,
) {
  if (!chart || typeof chart !== 'object') return null
  const rows = buildChartRows(chart, selectedSeriesIndex)
  if (!rows.length) return null
  const values = rows.map(item => Number(item.rawValue || 0))
  const kind = String(chart.type || '').toLowerCase() === 'line' ? 'line' : 'bar'
  const paddingLeft = 36
  const paddingRight = 12
  const paddingTop = 22
  const paddingBottom = 44
  const canvasHeight = 204
  const minStepWidth = kind === 'line'
    ? (rows.length > 6 ? 48 : 64)
    : (rows.length > 6 ? 54 : 76)
  const spanCount = kind === 'line' ? Math.max(rows.length - 1, 1) : rows.length
  const canvasWidth = Math.max(260, paddingLeft + paddingRight + spanCount * minStepWidth)
  const usableWidth = canvasWidth - paddingLeft - paddingRight
  const usableHeight = canvasHeight - paddingTop - paddingBottom
  const slotWidth = kind === 'line'
    ? (rows.length === 1 ? usableWidth : usableWidth / (rows.length - 1))
    : usableWidth / rows.length
  const axisLabelWidth = kind === 'line'
    ? (rows.length === 1 ? usableWidth : Math.min(112, Math.max(72, usableWidth / rows.length)))
    : Math.min(slotWidth, 88)
  const maxValue = Math.max(...values, 0)
  const minValue = Math.min(...values, 0)
  const span = Math.max(maxValue - minValue, 1)
  const zeroY = paddingTop + usableHeight * (1 - ((0 - minValue) / span))
  const safeActiveIndex = Math.max(0, Math.min(activeIndex, rows.length - 1))
  const gridLines = [0, 0.25, 0.5, 0.75, 1].map(step => Number((paddingTop + usableHeight * step).toFixed(2)))
  const yUnit = inferChartNumericUnit(chartSeriesName(chart, selectedSeriesIndex))
  const yTicks = [1, 0.75, 0.5, 0.25, 0].map((step, index) => {
    const value = minValue + span * step
    const y = paddingTop + usableHeight * (1 - step)
    return {
      key: `y_tick_${index}`,
      y: Number(y.toFixed(2)),
      label: formatChartNumber(value, yUnit),
    }
  })
  const axisLabels = rows.map((item, index) => ({
    key: `${item.label}_${index}`,
    index,
    label: truncateChartAxisLabel(item.label),
    width: Number(axisLabelWidth.toFixed(2)),
    left: 0,
  }))
  const clampAxisLeft = (left: number, width: number) => Number(
    Math.max(0, Math.min(left, canvasWidth - width)).toFixed(2),
  )

  if (kind === 'line') {
    const points = values.map((value, index) => {
      const xPosition = rows.length === 1
        ? paddingLeft + usableWidth / 2
        : paddingLeft + (usableWidth * index) / (rows.length - 1)
      const yPosition = paddingTop + usableHeight * (1 - ((value - minValue) / span))
      return {
        key: `${index}_${value}`,
        index,
        x: Number(xPosition.toFixed(2)),
        y: Number(yPosition.toFixed(2)),
        active: index === safeActiveIndex,
      }
    })
    points.forEach((point, index) => {
      axisLabels[index].left = clampAxisLeft(point.x - axisLabelWidth / 2, axisLabels[index].width)
    })
    const linePoints = points.map(point => `${point.x},${point.y}`).join(' ')
    const fillPoints = [
      `${points[0]?.x ?? paddingLeft},${zeroY}`,
      ...points.map(point => `${point.x},${point.y}`),
      `${points[points.length - 1]?.x ?? paddingLeft},${zeroY}`,
    ].join(' ')
    return {
      kind: 'line',
      canvasWidth,
      canvasHeight,
      slotWidth,
      paddingLeft,
      paddingRight,
      paddingTop,
      paddingBottom,
      gridLines,
      yTicks,
      zeroY,
      axisLabels,
      points,
      linePoints,
      fillPoints,
      activeGuide: points[safeActiveIndex] ? { x: points[safeActiveIndex].x } : null,
    }
  }

  const barWidth = Math.max(Math.min(slotWidth * 0.52, 42), 18)
  const bars = values.map((value, index) => {
    const normalized = (value - minValue) / span
    const barHeight = Math.max(Math.abs(value - 0) / span * usableHeight, 4)
    const xPosition = paddingLeft + slotWidth * index + (slotWidth - barWidth) / 2
    const yPosition = value >= 0 ? paddingTop + usableHeight * (1 - normalized) : zeroY
    return {
      key: `${index}_${value}`,
      index,
      x: Number(xPosition.toFixed(2)),
      y: Number(yPosition.toFixed(2)),
      width: Number(barWidth.toFixed(2)),
      height: Number(barHeight.toFixed(2)),
      active: index === safeActiveIndex,
    }
  })
  bars.forEach((bar, index) => {
    axisLabels[index].left = clampAxisLeft(bar.x + bar.width / 2 - axisLabelWidth / 2, axisLabels[index].width)
  })
  return {
    kind: 'bar',
    canvasWidth,
    canvasHeight,
    slotWidth,
    paddingLeft,
    paddingRight,
    paddingTop,
    paddingBottom,
    gridLines,
    yTicks,
    zeroY,
    axisLabels,
    bars,
    activeGuide: bars[safeActiveIndex]
      ? { x: Number((bars[safeActiveIndex].x + bars[safeActiveIndex].width / 2).toFixed(2)) }
      : null,
  }
}

function syncMessageChartVisual(message: ChatMsg | undefined, resetActiveIndex = false) {
  if (!message) return
  const rowCount = buildChartRows(message.chart, message.selectedSeriesIndex ?? 0).length
  if (!rowCount) {
    message.chartVisual = null
    message.activeChartIndex = 0
    return
  }
  if (resetActiveIndex || message.activeChartIndex == null || message.activeChartIndex >= rowCount) {
    message.activeChartIndex = resolveDefaultActiveChartIndex(message.chart, message.selectedSeriesIndex ?? 0)
  }
  message.chartVisual = message.chart
    ? buildChartVisualModel(message.chart, message.selectedSeriesIndex ?? 0, message.activeChartIndex ?? 0)
    : null
}

function initializeChartMessageState(message: ChatMsg | undefined) {
  if (!message?.chart) return
  if (message.selectedSeriesIndex == null) {
    message.selectedSeriesIndex = resolveDefaultSeriesIndex(message.chart)
  } else {
    message.selectedSeriesIndex = clampSeriesIndex(message.chart, message.selectedSeriesIndex)
  }
  if (!message.chartView) {
    message.chartView = 'chart'
  }
  if (typeof message.chartCollapsed !== 'boolean') {
    message.chartCollapsed = false
  }
  syncMessageChartVisual(message, message.activeChartIndex == null)
}

function buildChartTableRows(chart: Record<string, any> | null | undefined) {
  if (!chart || typeof chart !== 'object') return []
  const x = Array.isArray(chart.x) ? chart.x.map((item: unknown) => String(item)) : []
  const series = Array.isArray(chart.series) ? chart.series : []
  if (!x.length || !series.length) return []
  return x.map((label: string, index: number) => ({
    label,
    values: series.map((entry: any, seriesIndex: number) => ({
      key: `${label}_${seriesIndex}`,
      label: String(entry?.name || `系列 ${seriesIndex + 1}`),
      value: String(entry?.data?.[index] ?? 0),
    })),
  }))
}

function selectChartSeries(messageIndex: number, seriesIndex: number) {
  const target = messages.value[messageIndex]
  if (!target?.chart) return
  target.selectedSeriesIndex = clampSeriesIndex(target.chart, seriesIndex)
  syncMessageChartVisual(target, true)
}

function setChartView(messageIndex: number, view: 'chart' | 'table') {
  const target = messages.value[messageIndex]
  if (!target?.chart) return
  target.chartView = view
  if (target.chartCollapsed) target.chartCollapsed = false
}

function toggleChartCollapse(messageIndex: number) {
  const target = messages.value[messageIndex]
  if (!target?.chart) return
  target.chartCollapsed = !target.chartCollapsed
}

function selectChartDatum(messageIndex: number, datumIndex: number) {
  const target = messages.value[messageIndex]
  if (!target?.chart) return
  const rowCount = buildChartRows(target.chart, target.selectedSeriesIndex ?? 0).length
  if (!rowCount) return
  target.activeChartIndex = Math.max(0, Math.min(datumIndex, rowCount - 1))
  syncMessageChartVisual(target)
}

function toggleEvidence(index: number) {
  const target = messages.value[index]
  if (!target || target.role !== 'ai') return
  target.showEvidence = !target.showEvidence
}

function applyExperienceFeedbackToMessages(
  experienceId: string,
  payload: { helpful_count: number; unhelpful_count: number; incorrect_count: number },
) {
  messages.value.forEach((msg) => {
    const target = msg.experienceItems?.find(item => item.id === experienceId)
    if (!target) return
    target.helpful_count = payload.helpful_count
    target.unhelpful_count = payload.unhelpful_count
    target.incorrect_count = payload.incorrect_count
  })
  const recommended = stepPlan.value?.experience_recommendations?.find(item => item.experience_id === experienceId)
  if (recommended) {
    recommended.helpful_count = payload.helpful_count
  }
}

async function submitExperienceFeedback(
  experienceId: string,
  feedback: MaintenanceExperienceFeedbackType,
) {
  if (!experienceId || experienceFeedbackLoading.value[experienceId]) return
  experienceFeedbackLoading.value = {
    ...experienceFeedbackLoading.value,
    [experienceId]: feedback,
  }
  try {
    const response = await maintenanceExperienceApi.feedback(experienceId, {
      feedback,
      work_order_id: props.order?.ticket_id || null,
    })
    applyExperienceFeedbackToMessages(experienceId, response)
    experienceFeedbackState.value = {
      ...experienceFeedbackState.value,
      [experienceId]: response.feedback as MaintenanceExperienceFeedbackType,
    }
    uni.showToast({ title: '经验反馈已记录', icon: 'success' })
  } catch (err) {
    uni.showToast({ title: getErrorMessage(err, '经验反馈失败'), icon: 'none' })
  } finally {
    experienceFeedbackLoading.value = {
      ...experienceFeedbackLoading.value,
      [experienceId]: '',
    }
  }
}

async function sendPresetMessage(text: string) {
  if (sending.value || !text.trim()) return
  inputText.value = text
  await sendMessage()
}

function currentDispatchId() {
  return props.dispatchId || props.order?.current_dispatch?.id || props.order?.dispatch_id || null
}

function currentHistoryKey() {
  if (!isWorkerMode.value || !props.order?.ticket_id) return ''
  return [
    props.order.ticket_id,
    currentDispatchId() || '',
    props.hallEntryId || '',
  ].join(':')
}

function mapHistoryMessage(message: WorkerAiHistoryMessage): ChatMsg | null {
  const content = String(message.content || '').trim()
  if (!content) return null
  if (isActionFlowHistoryMessage(message, content)) return null
  return {
    role: message.role === 'user' ? 'user' : 'ai',
    content,
  }
}

function isActionFlowHistoryMessage(message: WorkerAiHistoryMessage, content: string) {
  const contentType = message.content_type || ''
  if (contentType === 'tool_result') return true
  if (contentType === 'guidance_observation' || contentType === 'guidance_reply') return false
  if (message.role === 'ai') {
    return [
      '你要执行“',
      '确认后我就替你提交',
      '确认后我会提交',
      '已完成“',
      '无需重复',
      '当前工单已',
      '当前还未',
      '当前派工阶段不支持',
      '我正在等待你确认是否执行上一条动作',
      '请回复“确认”执行',
      '好的，我已取消这次动作',
      '状态机',
      '我在，咱们直接看现场',
      '这张单已经在处理中',
      '我先按你看到的现场来判断',
      '你把现象、读数、报警码或照片发我一个就行',
      '先把一个现象发我就行',
      '先看这个：',
    ].some(fragment => content.includes(fragment))
  }
  return [
    '确认',
    '取消',
    '开始处理',
    '开始维修',
    '开始排查',
    '确认接单',
    '接单',
    '我接了',
    '确认到场',
    '我已到场',
    '已到场',
    '到场了',
  ].includes(content)
}

async function loadWorkerHistory() {
  if (!isWorkerMode.value || !props.order?.ticket_id) return
  const key = currentHistoryKey()
  if (!key) return
  if (activeHistoryKey.value !== key) {
    activeHistoryKey.value = key
    messages.value = []
    sessionId.value = null
    isFirstMessage.value = true
  }
  if (historyLoadedKey.value === key) return
  historyLoadedKey.value = key

  try {
    const response = await workerAiApi.history(props.order.ticket_id, {
      dispatch_id: currentDispatchId(),
      hall_entry_id: props.hallEntryId,
      limit: 80,
    })
    if (response.session_id && !sessionId.value) {
      sessionId.value = response.session_id
    }
    const restored = response.messages
      .map(mapHistoryMessage)
      .filter(Boolean) as ChatMsg[]
    if (restored.length && messages.value.length === 0) {
      messages.value = restored
      isFirstMessage.value = false
      scrollToBottom()
    }
  } catch (err) {
    console.warn('[AiChat] 维小修历史对话加载失败', err)
  }
}

function shouldUseGuidanceChat() {
  return Boolean(
    props.mode === 'worker'
      && props.order?.ticket_id
      && stepPlan.value?.guidance_ready
      && stepPlan.value?.plan_id
      && guidanceStep.value,
  )
}

function scrollToBottom() {
  if (!componentReady.value) return
  nextTick(() => {
    if (!componentReady.value) return
    scrollTop.value = 0
    setTimeout(() => {
      if (componentReady.value) scrollTop.value = Number.MAX_SAFE_INTEGER
    }, 32)
  })
}

async function loadStepPlan(
  autoGenerate = true,
  options: { notifyNotReady?: boolean; notifyError?: boolean } = {},
) {
  if (!isWorkerMode.value || !props.order?.ticket_id) return
  if (stepPlanLoadPromise) return stepPlanLoadPromise
  const notifyNotReady = options.notifyNotReady ?? true
  const notifyError = options.notifyError ?? true
  guidanceLoading.value = true

  stepPlanLoadPromise = (async () => {
    try {
      stepPlan.value = await workerAiApi.getSteps(props.order!.ticket_id, {
        auto_generate: autoGenerate,
        dispatch_id: currentDispatchId(),
      })
      if (!stepPlan.value.guidance_ready) {
        if (notifyNotReady) {
          pushUniqueAiMessage('这张单还没有进入现场处理阶段，请先回到工单详情页完成接单、到场和开始处理。')
        }
      } else {
        introduceStepPlanIfReady()
      }
    } catch (err) {
      if (notifyError) pushUniqueAiMessage(getErrorMessage(err, '步骤卡片加载失败'))
    } finally {
      guidanceLoading.value = false
      stepPlanLoadPromise = null
    }
  })()

  return stepPlanLoadPromise
}

function stepIndex(stepId: string | undefined): number {
  if (!stepId || !stepPlan.value?.steps?.length) return -1
  return stepPlan.value.steps.findIndex(step => step.id === stepId)
}

function stepStatusLabel(status: WorkerAiStepStatus) {
  const labels: Record<WorkerAiStepStatus, string> = {
    pending: '待处理',
    completed: '已完成',
    skipped: '已跳过',
    needs_support: '需协同',
    uncertain: '待确认',
  }
  return labels[status] || '待处理'
}

function toggleStepPanel() {
  const nextExpanded = !stepPanelExpanded.value
  stepPanelExpanded.value = nextExpanded
  if (nextExpanded) {
    stepSwiperCurrent.value = activeStepIndex.value
  }
}

function handleStepSwiperChange(event: any) {
  const next = Number(event?.detail?.current ?? 0)
  stepSwiperCurrent.value = Number.isFinite(next) ? next : 0
}

function jumpToStep(index: number) {
  if (index < 0 || index >= workflowSteps.value.length) return
  stepSwiperCurrent.value = index
}

function syncStepNotesFromPlan() {
  const next = { ...stepNotes.value }
  for (const step of workflowSteps.value) {
    if (next[step.id] === undefined) next[step.id] = step.note || ''
  }
  stepNotes.value = next
}

function introduceStepPlanIfReady() {
  const plan = stepPlan.value
  if (!plan?.guidance_ready || !plan.steps.length || !plan.plan_id) return
  if (introducedPlanId.value !== plan.plan_id) {
    introducedPlanId.value = plan.plan_id
  }
  scrollToBottom()
}

async function updateStep(
  stepId: string,
  status: WorkerAiStepStatus,
  options: { echoUser?: boolean; note?: string | null; noteOnly?: boolean } = {},
) {
  if (!props.order?.ticket_id || !stepPlan.value?.plan_id || updatingStepId.value) return
  updatingStepId.value = stepId
  const note = options.note?.trim() || null
  try {
    const response = await workerAiApi.updateStep(props.order.ticket_id, stepId, {
      plan_id: stepPlan.value.plan_id,
      status,
      note,
      client_version: stepPlan.value.plan_version,
    })
    stepPlan.value = {
      ...stepPlan.value,
      plan_version: response.plan_version,
      steps: response.steps,
    }
    const updatedStep = response.steps.find(step => step.id === stepId)
    if (updatedStep) {
      stepNotes.value = { ...stepNotes.value, [stepId]: updatedStep.note || '' }
    }
    syncStepNotesFromPlan()
    uni.showToast({ title: options.noteOnly ? '备注已保存' : '步骤已更新', icon: 'success' })
  } catch (err) {
    uni.showToast({ title: getErrorMessage(err, '步骤状态更新失败'), icon: 'none' })
  } finally {
    updatingStepId.value = null
  }
}

async function markStep(step: WorkerAiStep, status: WorkerAiStepStatus) {
  await updateStep(step.id, status, { note: stepNotes.value[step.id] || step.note || '' })
}

async function saveStepNoteForStep(step: WorkerAiStep) {
  const note = String(stepNotes.value[step.id] || '').trim()
  if (!note) {
    uni.showToast({ title: '请先输入备注内容', icon: 'none' })
    return
  }
  await updateStep(step.id, step.status, {
    echoUser: false,
    note,
    noteOnly: true,
  })
}

async function sendMessage() {
  const text = inputText.value.trim()
  if (!text || sending.value) return
  const preferWorkerGeneralChat = shouldPreferWorkerGeneralChat(text)

  if (shouldUseGuidanceChat() && !preferWorkerGeneralChat) {
    messages.value.push({ role: 'user', content: text })
    inputText.value = ''
    sending.value = true
    streamingText.value = ''
    isFirstMessage.value = false
    scrollToBottom()
    messages.value.push({ role: 'ai', content: '我在结合当前步骤和现场描述判断...', thinking: true })
    await sendGuidanceMessage(text)
    return
  }

  if (props.mode === 'worker') {
    messages.value.push({ role: 'user', content: text })
    inputText.value = ''
    sending.value = true
    streamingText.value = ''
    isFirstMessage.value = false
    messages.value.push({ role: 'ai', content: '我看一下这张单和你刚说的现场情况。', thinking: true })
    scrollToBottom()
    await loadStepPlan(true, { notifyNotReady: false, notifyError: false })
    if (shouldUseGuidanceChat() && !preferWorkerGeneralChat) {
      const last = messages.value[messages.value.length - 1]
      if (last?.role === 'ai' && last.thinking) {
        last.content = '我在结合当前步骤和现场描述判断...'
      }
      await sendGuidanceMessage(text)
      return
    }
    await sendAssistantMessage(text, { source: 'AiChat.worker' })
    return
  }

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

async function sendGuidanceMessage(text: string) {
  const plan = stepPlan.value
  const step = guidanceStep.value
  if (!props.order?.ticket_id || !plan?.plan_id || !step) {
    removePendingThinking()
    messages.value.push({ role: 'ai', content: '我还没拿到这张单的维修指导上下文。请稍等一下再发，或者返回工单详情重新进入维小修。' })
    sending.value = false
    scrollToBottom()
    return
  }
  try {
    let finalized = false
    const payload = {
      message: text,
      session_id: sessionId.value,
      ticket_id: props.order.ticket_id,
      dispatch_id: currentDispatchId(),
      plan_id: plan.plan_id,
      step_id: step.id,
      client_context: {
        source_component: 'AiChat.guidance',
        step_title: step.title,
        step_status: step.status,
        work_order_status: props.order.status || null,
        execution_status: props.order.current_dispatch?.execution_status || props.order.execution_status || null,
      },
    }
    const nextSessionId = await workerAiApi.guidanceChatStream(payload, {
      onThinking(event) {
        const last = messages.value[messages.value.length - 1]
        if (last?.role === 'ai' && last.thinking) {
          last.content = event.message || '我在结合当前步骤和现场描述判断...'
        }
      },
      onText(event) {
        appendStreamingChunk(event.content)
      },
      onResult(event) {
        const response = event.payload as WorkerAiGuidanceChatResponse
        sessionId.value = response.session_id
        finalizeStreamingMessage({
          role: 'ai',
          content: response.answer,
          stepId: response.step_id || step.id,
        }, response.answer)
        finalized = true
      },
      onError(event) {
        removePendingThinking()
        streamingText.value = ''
        messages.value.push({ role: 'ai', content: event.message || '维修指导请求失败，请重试' })
        sending.value = false
        scrollToBottom()
      },
      onDone(event) {
        sessionId.value = event.session_id || sessionId.value
        if (!finalized && streamingText.value.trim()) {
          finalizeStreamingMessage({
            role: 'ai',
            content: '',
            stepId: step.id,
          })
          finalized = true
        }
        sending.value = false
        scrollToBottom()
      },
      onNetworkError(err) {
        removePendingThinking()
        streamingText.value = ''
        messages.value.push({ role: 'ai', content: err.message || '网络异常，请重试' })
        sending.value = false
        scrollToBottom()
      },
    })
    if (nextSessionId) sessionId.value = nextSessionId
  } catch (err) {
    removePendingThinking()
    streamingText.value = ''
    messages.value.push({ role: 'ai', content: err instanceof Error ? err.message : '维修指导请求失败，请重试' })
  } finally {
    sending.value = false
    scrollToBottom()
  }
}

async function sendAssistantMessage(
  text: string,
  options: { silentUserMessage?: boolean; source?: string } = {},
) {
  try {
    let finalized = false
    const nextSessionId = props.mode === 'worker'
      ? await workerAiApi.chatStream({
          message: text,
          session_id: sessionId.value,
          ticket_id: props.order?.ticket_id || null,
          dispatch_id: props.dispatchId || props.order?.current_dispatch?.id || props.order?.dispatch_id || null,
          hall_entry_id: props.hallEntryId || null,
          client_context: {
            source_component: options.source || 'AiChat',
            work_order_status: props.order?.status || null,
            execution_status: props.order?.current_dispatch?.execution_status || props.order?.execution_status || null,
          },
        }, {
          onThinking(event) {
            const last = messages.value[messages.value.length - 1]
            if (last?.role === 'ai' && last.thinking) {
              last.content = event.message || '我在看这张单和你刚说的情况...'
            }
          },
          onText(event) {
            appendStreamingChunk(event.content)
          },
          onResult(event) {
            const response = event.payload as WorkerAiChatResponse
            sessionId.value = response.session_id
            finalizeStreamingMessage({
              role: 'ai',
              content: response.answer,
            }, response.answer)
            finalized = true
          },
          onError(event) {
            removePendingThinking()
            streamingText.value = ''
            messages.value.push({ role: 'ai', content: event.message || '请求失败，请重试' })
            sending.value = false
            scrollToBottom()
          },
          onDone(event) {
            sessionId.value = event.session_id || sessionId.value
            if (!finalized && streamingText.value.trim()) {
              finalizeStreamingMessage({ role: 'ai', content: '' })
              finalized = true
            }
            sending.value = false
            scrollToBottom()
          },
          onNetworkError(err) {
            removePendingThinking()
            streamingText.value = ''
            messages.value.push({ role: 'ai', content: err.message || '网络异常，请重试' })
            sending.value = false
            scrollToBottom()
          },
        })
      : await operatorAiApi.chatStream({
          message: text,
          session_id: sessionId.value,
          ticket_id: props.order?.ticket_id || null,
          scope: props.order
            ? {
                source_component: options.source || 'AiChat',
                work_order_status: props.order?.status || null,
                execution_status: props.order?.current_dispatch?.execution_status || props.order?.execution_status || null,
              }
            : buildOperatorScope(options.source || 'AiChat'),
          include_evidence: true,
          include_chart: true,
        }, {
      onThinking(event) {
        const last = messages.value[messages.value.length - 1]
        if (last?.role === 'ai' && last.thinking) {
          last.content = event.message || '我在整理分析结论...'
        }
      },
      onText(event) {
        appendStreamingChunk(event.content)
      },
      onResult(event) {
        const response = event.payload as OperatorAiChatResponse
        sessionId.value = response.session_id
        finalizeStreamingMessage(buildOperatorAiMessage(response), response.answer)
        finalized = true
      },
      onError(event) {
        removePendingThinking()
        streamingText.value = ''
        messages.value.push({ role: 'ai', content: event.message || '请求失败，请重试' })
        sending.value = false
        scrollToBottom()
      },
      onDone(event) {
        sessionId.value = event.session_id || sessionId.value
        if (!finalized && streamingText.value.trim()) {
          finalizeStreamingMessage({ role: 'ai', content: '' })
          finalized = true
        }
        sending.value = false
        scrollToBottom()
      },
      onNetworkError(err) {
        removePendingThinking()
        streamingText.value = ''
        messages.value.push({ role: 'ai', content: err.message || '网络异常，请重试' })
        sending.value = false
        scrollToBottom()
      },
    })
    if (nextSessionId) sessionId.value = nextSessionId
  } catch (err) {
    removePendingThinking()
    streamingText.value = ''
    messages.value.push({ role: 'ai', content: getErrorMessage(err, '请求失败，请重试') })
  } finally {
    sending.value = false
    scrollToBottom()
  }
}

function removePendingThinking() {
  const last = messages.value[messages.value.length - 1]
  if (last?.role === 'ai' && last.thinking) messages.value.pop()
}

function appendStreamingChunk(content: string) {
  if (!content) return
  removePendingThinking()
  streamingText.value += content
  scrollToBottom()
}

function finalizeStreamingMessage(message: ChatMsg | null, fallbackContent = '') {
  removePendingThinking()
  const content = String(streamingText.value || fallbackContent || '').trim()
  streamingText.value = ''
  if (message && content) {
    const nextMessage: ChatMsg = {
      ...message,
      content,
    }
    initializeChartMessageState(nextMessage)
    messages.value.push(nextMessage)
  } else if (content) {
    messages.value.push({ role: 'ai', content })
  }
  scrollToBottom()
}

function buildOperatorAiMessage(response: OperatorAiChatResponse, fallbackContent = ''): ChatMsg {
  return {
    role: 'ai',
    content: fallbackContent || response.answer,
    answerType: response.answer_type,
    experienceItems: normalizeExperienceItems(response.facts),
    suggestedFollowups: response.suggested_followups || [],
    chart: response.chart || null,
    metrics: response.metrics || null,
    scope: response.facts && typeof response.facts === 'object' && !Array.isArray(response.facts)
      ? ((response.facts as Record<string, any>).scope || null)
      : null,
    evidenceClaims: normalizeEvidenceClaims(response.facts, response.evidence_refs || []),
    evidenceRefs: response.evidence_refs || [],
    blockedActions: response.blocked_actions || [],
    readonly: !!response.readonly,
    showEvidence: false,
  }
}

async function chooseCameraForAnalysis() {
  await chooseImageForAnalysis(['camera'])
}

async function chooseImageForAnalysis(sourceType: Array<'camera' | 'album'> = ['camera', 'album']) {
  if (!isWorkerMode.value || !props.order?.ticket_id || mediaBusy.value) return
  mediaBusy.value = true
  try {
    const chooseResult: any = await new Promise((resolve, reject) => {
      uni.chooseImage({
        count: 1,
        sourceType,
        success: resolve,
        fail: reject,
      })
    })
    const filePath = chooseResult?.tempFilePaths?.[0]
    if (!filePath) return
    messages.value.push({ role: 'user', content: '已上传现场图片，请帮我判断下一步。' })
    messages.value.push({ role: 'ai', content: '正在分析现场图片...', thinking: true })
    scrollToBottom()
    const response = await workerAiApi.analyzeImage({
      ticket_id: props.order.ticket_id,
      dispatch_id: currentDispatchId(),
      step_id: currentStep.value?.id || null,
      prompt: currentStep.value?.instruction || null,
      filePath,
    })
    removePendingThinking()
    const analysis = response.analysis
    const observations = analysis.observations?.length ? `\n观察：${analysis.observations.join('；')}` : ''
    const uncertainties = analysis.uncertainties?.length ? `\n不确定：${analysis.uncertainties.join('；')}` : ''
    messages.value.push({
      role: 'ai',
      content: `${analysis.summary}${observations}${uncertainties}\n${response.suggested_next_message || ''}`.trim(),
    })
  } catch (err) {
    removePendingThinking()
    const message = err instanceof Error ? err.message : '图片分析失败'
    if (!/cancel/i.test(message)) {
      messages.value.push({ role: 'ai', content: message })
    }
  } finally {
    mediaBusy.value = false
    scrollToBottom()
  }
}

function stopRecording() {
  if (!recording.value || recordingStopRequested) return
  recordingStopRequested = true
  try {
    if (process.env.UNI_PLATFORM === 'h5') {
      if (h5MediaRecorder && h5MediaRecorder.state !== 'inactive') {
        h5MediaRecorder.stop()
      }
    } else {
      recorderManager?.stop()
    }
  } catch {
    recordingStopRequested = false
    recording.value = false
    mediaBusy.value = false
  }
}

function toggleVoiceInputMode() {
  if (mediaBusy.value && !recording.value) return
  if (recording.value) stopRecording()
  voiceInputMode.value = !voiceInputMode.value
}

function startVoiceHold() {
  if (!voiceInputMode.value || recording.value || mediaBusy.value) return
  toggleRecording()
}

function stopVoiceHold() {
  if (!voiceInputMode.value) return
  stopRecording()
}

function setupRecorder() {
  if (process.env.UNI_PLATFORM === 'h5') {
    recorderManager = null
    return
  }
  if (typeof uni.getRecorderManager !== 'function') {
    recorderManager = null
    return
  }
  try {
    recorderManager = uni.getRecorderManager()
    recorderManager.onStop(async (res: any) => {
      recordingStopRequested = false
      recording.value = false
      if (!res?.tempFilePath) return
      await transcribeAudioFile(res.tempFilePath)
    })
    recorderManager.onError((err: any) => {
      recordingStopRequested = false
      recording.value = false
      mediaBusy.value = false
      messages.value.push({ role: 'ai', content: err?.errMsg || '录音失败，请改用文字输入。' })
    })
  } catch {
    recorderManager = null
  }
}

function toggleRecording() {
  if (!isWorkerMode.value) return
  if (recording.value) {
    stopRecording()
    return
  }
  if (mediaBusy.value) return
  if (process.env.UNI_PLATFORM === 'h5') {
    void startH5Recording()
    return
  }
  if (!recorderManager) {
    uni.showToast({ title: '当前端不支持录音，请用文字输入', icon: 'none' })
    return
  }
  try {
    recordingStopRequested = false
    recording.value = true
    mediaBusy.value = true
    recorderManager.start({
      duration: 60000,
      sampleRate: 16000,
      numberOfChannels: 1,
      encodeBitRate: 48000,
      format: 'mp3',
    })
  } catch {
    recording.value = false
    mediaBusy.value = false
    uni.showToast({ title: '录音启动失败', icon: 'none' })
  }
}

async function startH5Recording() {
  if (
    typeof navigator === 'undefined'
    || !navigator.mediaDevices?.getUserMedia
    || typeof MediaRecorder === 'undefined'
  ) {
    uni.showToast({ title: '当前浏览器不支持录音，请用文字输入', icon: 'none' })
    return
  }
  try {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
    recordingStopRequested = false
    h5AudioChunks = []
    const mimeType = MediaRecorder.isTypeSupported('audio/webm;codecs=opus')
      ? 'audio/webm;codecs=opus'
      : 'audio/webm'
    h5MediaRecorder = new MediaRecorder(stream, { mimeType })
    h5MediaRecorder.ondataavailable = (event) => {
      if (event.data?.size) h5AudioChunks.push(event.data)
    }
    h5MediaRecorder.onstop = async () => {
      recordingStopRequested = false
      recording.value = false
      stream.getTracks().forEach(track => track.stop())
      const blob = new Blob(h5AudioChunks, { type: 'audio/webm' })
      if (blob.size) await transcribeAudioBlob(blob)
      mediaBusy.value = false
    }
    h5MediaRecorder.onerror = () => {
      recordingStopRequested = false
      recording.value = false
      mediaBusy.value = false
      stream.getTracks().forEach(track => track.stop())
      uni.showToast({ title: '录音失败，请改用文字输入', icon: 'none' })
    }
    recording.value = true
    mediaBusy.value = true
    h5MediaRecorder.start()
  } catch {
    recording.value = false
    mediaBusy.value = false
    uni.showToast({ title: '未获得麦克风权限', icon: 'none' })
  }
}

async function transcribeAudioFile(filePath: string) {
  if (!props.order?.ticket_id) return
  try {
    messages.value.push({ role: 'user', content: '已发送语音。' })
    messages.value.push({ role: 'ai', content: '正在识别语音...', thinking: true })
    scrollToBottom()
    const response = await workerAiApi.transcribeAudio({
      ticket_id: props.order.ticket_id,
      dispatch_id: currentDispatchId(),
      step_id: currentStep.value?.id || null,
      filePath,
    })
    removePendingThinking()
    if (!response.transcript) {
      messages.value.push({ role: 'ai', content: '这段语音暂时没有识别出文字，请再说一遍或改用文字输入。' })
      return
    }
    inputText.value = response.transcript
    await sendMessage()
  } catch (err) {
    removePendingThinking()
    messages.value.push({ role: 'ai', content: err instanceof Error ? err.message : '语音识别失败' })
  } finally {
    mediaBusy.value = false
    scrollToBottom()
  }
}

async function transcribeAudioBlob(blob: Blob) {
  if (!props.order?.ticket_id) return
  try {
    messages.value.push({ role: 'user', content: '已发送语音。' })
    messages.value.push({ role: 'ai', content: '正在识别语音...', thinking: true })
    scrollToBottom()
    const response = await workerAiApi.transcribeAudioBlob({
      ticket_id: props.order.ticket_id,
      dispatch_id: currentDispatchId(),
      step_id: currentStep.value?.id || null,
      blob,
      fileName: 'voice.webm',
    })
    removePendingThinking()
    if (!response.transcript) {
      messages.value.push({ role: 'ai', content: '这段语音暂时没有识别出文字，请再说一遍或改用文字输入。' })
      return
    }
    inputText.value = response.transcript
    await sendMessage()
  } catch (err) {
    removePendingThinking()
    messages.value.push({ role: 'ai', content: err instanceof Error ? err.message : '语音识别失败' })
  } finally {
    mediaBusy.value = false
    scrollToBottom()
  }
}

async function openAiMessageMenu(content: string, index: number) {
  const text = content.trim()
  if (!text) return
  messageMenuContent.value = text
  const rect = await queryRect(`#${messageBubbleId(index)}`)
  messageMenuStyle.value = rect ? buildMessageMenuStyle(rect) : {}
  messageMenuVisible.value = true
}

function closeAiMessageMenu() {
  messageMenuVisible.value = false
  messageMenuStyle.value = {}
}

function copyAiMessage() {
  const content = messageMenuContent.value
  closeAiMessageMenu()
  if (!content) return
  uni.setClipboardData({
    data: content,
    success() {
      uni.showToast({ title: '已复制', icon: 'success' })
    },
  })
}

function selectAiMessageText() {
  selectedTextContent.value = messageMenuContent.value
  closeAiMessageMenu()
  selectedTextVisible.value = true
}

function closeSelectedText() {
  selectedTextVisible.value = false
}

async function speakAiMessage() {
  const content = messageMenuContent.value
  closeAiMessageMenu()
  await speakText(content)
}

async function speakText(text: string) {
  const content = text.trim()
  if (!content) return
  try {
    const response = await workerAiApi.tts({ text: content })
    if (response.audio_url) {
      const audio = uni.createInnerAudioContext()
      audio.src = buildAbsoluteApiUrl(response.audio_url)
      audio.play()
      return
    }
    const win = typeof window !== 'undefined' ? window : undefined
    if (win?.speechSynthesis && typeof SpeechSynthesisUtterance !== 'undefined') {
      const utterance = new SpeechSynthesisUtterance(response.text || content)
      utterance.lang = 'zh-CN'
      utterance.rate = 1
      win.speechSynthesis.cancel()
      win.speechSynthesis.speak(utterance)
      return
    }
    uni.showToast({ title: '当前端不支持本机播报', icon: 'none' })
  } catch (err) {
    uni.showToast({ title: err instanceof Error ? err.message : '播报失败', icon: 'none' })
  }
}

watch(
  () => stepPlan.value?.steps,
  () => {
    syncStepNotesFromPlan()
  },
  { immediate: true, deep: true },
)

watch(
  () => [guidanceStep.value?.id, workflowSteps.value.length],
  () => {
    stepSwiperCurrent.value = activeStepIndex.value
  },
  { immediate: true },
)

watch(
  () => [props.mode, props.order?.ticket_id, props.dispatchId, props.hallEntryId],
  () => {
    if (isWorkerMode.value) {
      void loadWorkerHistory()
      void loadStepPlan(true, { notifyNotReady: false, notifyError: false })
    }
    if (isOperatorWorkbench.value) void loadOperatorFilters()
  },
)

onMounted(() => {
  nextTick(() => {
    componentReady.value = true
    setupRecorder()
    if (isWorkerMode.value) {
      void loadWorkerHistory()
      void loadStepPlan(true, { notifyNotReady: false, notifyError: false })
    }
    if (isOperatorWorkbench.value) void loadOperatorFilters()
  })
})

onBeforeUnmount(() => {
  componentReady.value = false
  if (recording.value && recorderManager) {
    recorderManager.stop()
  }
  if (recording.value && h5MediaRecorder) {
    h5MediaRecorder.ondataavailable = null
    h5MediaRecorder.onstop = null
    try {
      h5MediaRecorder.stop()
    } catch {}
  }
})
</script>

<style lang="scss" scoped>
.ai-chat {
  background: #fff;
  border-radius: 20rpx;
  overflow: hidden;
  box-shadow: 0 2rpx 12rpx rgba(0,0,0,0.06);
}

.operator-workbench-chat {
  background:
    radial-gradient(circle at 50% 16%, rgba(197, 220, 137, 0.2), transparent 28%),
    linear-gradient(180deg, #fbfdf7 0%, #ffffff 100%);
}

.chat-header {
  padding: 20rpx 24rpx 16rpx;
  border-bottom: 1rpx solid #f0f0f0;
}

.chat-title { display: block; font-size: 28rpx; font-weight: 700; color: #1a1a2e; }
.chat-hint  { font-size: 22rpx; color: #aaa; }

.chat-messages {
  height: 520rpx;
  padding: 18rpx 20rpx 12rpx;
  box-sizing: border-box;
  background:
    linear-gradient(180deg, rgba(246, 249, 251, 0.72) 0%, rgba(255, 255, 255, 0) 120rpx),
    #fff;
}

.operator-hero-shell {
  flex: 1;
  min-height: 0;
  padding: 56rpx 34rpx 24rpx;
  box-sizing: border-box;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 42rpx;
}

.operator-hero-visual {
  width: 260rpx;
  height: 260rpx;
  display: flex;
  align-items: center;
  justify-content: center;
}

.operator-hero-icon-shell {
  width: 196rpx;
  height: 196rpx;
  border-radius: 999rpx;
  display: flex;
  align-items: center;
  justify-content: center;
  overflow: hidden;
  background: radial-gradient(circle, rgba(248, 252, 232, 0.98) 0%, rgba(233, 244, 193, 0.94) 72%, rgba(216, 232, 156, 0.92) 100%);
  box-shadow:
    0 24rpx 54rpx rgba(155, 176, 90, 0.16),
    inset 0 1rpx 0 rgba(255, 255, 255, 0.9);
}

.operator-hero-lottie {
  width: 164rpx;
  height: 164rpx;
  pointer-events: none;
}

.operator-hero-lottie :deep(canvas),
.operator-hero-lottie :deep(svg) {
  width: 100% !important;
  height: 100% !important;
  display: block;
}

.operator-hero-tabs {
  width: 100%;
  display: flex;
  flex-wrap: wrap;
  justify-content: center;
  gap: 14rpx;
}

.operator-hero-chip {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-height: 54rpx;
  padding: 0 22rpx;
  border-radius: 999rpx;
  background: rgba(246, 248, 232, 0.96);
  border: 1rpx solid #dde6b8;
  color: #65743a;
  font-size: 22rpx;
  font-weight: 700;
  box-shadow: 0 10rpx 22rpx rgba(152, 172, 88, 0.08);
}

.operator-hero-chip.disabled {
  opacity: 0.45;
}

.msg {
  display: flex;
  flex-direction: column;
  min-width: 0;
  margin-bottom: 24rpx;
  width: 100%;
  &.user-msg { align-items: flex-end; }
  &.ai-msg   { align-items: flex-start; }
}

.msg-bubble {
  max-width: calc(100% - 84rpx);
  padding: 20rpx 22rpx;
  border-radius: 24rpx;
  font-size: 26rpx;
  line-height: 1.72;
  box-sizing: border-box;
  overflow-wrap: anywhere;
  word-break: break-word;
  box-shadow: 0 10rpx 28rpx rgba(45, 57, 72, 0.06);
  border: 1rpx solid transparent;

  text {
    display: block;
    margin-bottom: 0;
    white-space: pre-wrap;
    word-break: break-word;
  }

  &.user {
    background: linear-gradient(135deg, #d6e29f, #b5c875);
    color: #fff;
    border-bottom-right-radius: 8rpx;
  }

  &.ai {
    background: linear-gradient(180deg, #ffffff 0%, #f7f9fb 100%);
    border-color: #e6ebef;
    color: #2b3740;
    border-bottom-left-radius: 8rpx;
  }

  &.streaming {
    display: flex;
    align-items: flex-end;
    gap: 8rpx;
  }
}

.msg-paragraph + .msg-paragraph {
  margin-top: 12rpx;
}

.analysis-summary-card {
  width: 100%;
  max-width: 100%;
  min-width: 0;
  padding: 18rpx 18rpx 16rpx;
  border-radius: 24rpx;
  background: linear-gradient(180deg, #ffffff 0%, #f7fafc 100%);
  border: 1rpx solid #e4ecf1;
  box-shadow: 0 12rpx 30rpx rgba(40, 55, 71, 0.07);
  box-sizing: border-box;
}

.analysis-summary-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 14rpx;
  flex-wrap: wrap;
}

.analysis-summary-title {
  flex: 1;
  min-width: 0;
  display: block;
  font-size: 24rpx;
  line-height: 1.45;
  color: #22333c;
  font-weight: 800;
  word-break: break-word;
}

.analysis-summary-mode {
  flex-shrink: 0;
  max-width: 100%;
  padding: 6rpx 14rpx;
  border-radius: 999rpx;
  background: #eef6e6;
  color: #4c6a43;
  font-size: 18rpx;
  font-weight: 700;
  box-sizing: border-box;
}

.analysis-summary-chip-list {
  display: flex;
  flex-wrap: wrap;
  gap: 8rpx;
  margin-top: 12rpx;
}

.analysis-summary-chip {
  display: inline-flex;
  align-items: center;
  min-height: 38rpx;
  padding: 0 12rpx;
  border-radius: 999rpx;
  background: #f1f5f8;
  color: #60727d;
  font-size: 18rpx;
  font-weight: 700;
}

.analysis-summary-text {
  display: block;
  margin-top: 14rpx;
  font-size: 23rpx;
  line-height: 1.68;
  color: #30424d;
}

.analysis-summary-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10rpx;
  margin-top: 16rpx;
}

.analysis-summary-stat {
  min-width: 0;
  padding: 14rpx 14rpx 12rpx;
  border-radius: 16rpx;
  background: linear-gradient(180deg, #fbfdfd 0%, #f3f7f8 100%);
  border: 1rpx solid #e4ecef;
}

.analysis-summary-stat-label {
  display: block;
  font-size: 18rpx;
  color: #82929b;
}

.analysis-summary-stat-value {
  display: block;
  margin-top: 8rpx;
  font-size: 24rpx;
  line-height: 1.35;
  color: #22343d;
  font-weight: 800;
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

.msg-actions {
  display: flex;
  justify-content: flex-end;
  margin-top: 12rpx;
}

.msg-action {
  font-size: 22rpx;
  color: #6b7d3f;
  font-weight: 700;
}

.step-panel {
  margin: 0 20rpx 16rpx;
  padding: 20rpx;
  border-radius: 18rpx;
  background: linear-gradient(180deg, #fbfcf5 0%, #f4f8e5 100%);
  border: 1rpx solid #dfe8b8;
}

.step-panel.collapsed {
  margin-bottom: 14rpx;
}

.step-panel-summary,
.step-panel-head,
.flow-step-head,
.step-swiper-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16rpx;
}

.step-panel-summary {
  min-height: 110rpx;
  padding: 22rpx 22rpx 20rpx;
}

.step-panel-summary-copy {
  flex: 1;
  min-width: 0;
}

.step-panel-tag,
.step-panel-index {
  font-size: 22rpx;
  color: #6b7d3f;
  font-weight: 800;
}

.step-panel-toggle {
  width: 96rpx;
  height: 58rpx;
  border-radius: 999rpx;
  background: rgba(255, 255, 255, 0.92);
  display: flex;
  align-items: center;
  justify-content: center;
  color: #6b7d3f;
  font-size: 22rpx;
  font-weight: 800;
  flex-shrink: 0;
  box-shadow: inset 0 0 0 1rpx rgba(214, 226, 159, 0.9);
}

.step-panel-title {
  display: block;
  margin-top: 12rpx;
  font-size: 30rpx;
  line-height: 1.4;
  color: #273012;
  font-weight: 900;
}

.step-panel-pills {
  display: flex;
  flex-wrap: wrap;
  gap: 12rpx;
  margin-top: 14rpx;
}

.step-panel-pill {
  min-height: 48rpx;
  padding: 0 18rpx;
  border-radius: 999rpx;
  background: rgba(255, 255, 255, 0.76);
  display: inline-flex;
  align-items: center;
  justify-content: center;
  font-size: 22rpx;
  color: #647440;
  font-weight: 700;
}

.step-panel-pill.current {
  background: #dce8aa;
  color: #415118;
}

.step-panel-text,
.step-panel-sub {
  display: block;
  margin-top: 10rpx;
  font-size: 23rpx;
  line-height: 1.6;
  color: #565f3d;
}

.step-panel-sub.warn {
  color: #9b5c2a;
}

.step-panel-body {
  padding: 0 18rpx 18rpx;
  border-top: 1rpx solid rgba(216, 226, 175, 0.78);
}

.step-tab-row {
  width: 100%;
  margin-top: 18rpx;
  white-space: nowrap;
}

.step-tab-track {
  display: flex;
  gap: 12rpx;
  width: max-content;
  padding-right: 8rpx;
}

.step-tab-chip {
  min-width: 120rpx;
  height: 56rpx;
  padding: 0 18rpx;
  border-radius: 999rpx;
  background: rgba(255, 255, 255, 0.8);
  color: #657349;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  font-size: 22rpx;
  font-weight: 700;
  border: 1rpx solid transparent;
  box-sizing: border-box;
}

.step-tab-chip.active {
  background: #ffffff;
  border-color: #c9d88c;
  color: #273012;
}

.step-tab-chip.current {
  box-shadow: inset 0 0 0 1rpx rgba(206, 220, 146, 0.95);
}

.step-tab-chip.done {
  background: #edf5d3;
  color: #536228;
}

.step-swiper {
  height: 760rpx;
  margin-top: 18rpx;
}

.step-swiper-scroll {
  height: 100%;
}

.step-swiper-item {
  min-height: 100%;
  padding: 2rpx;
  box-sizing: border-box;
}

.flow-step-card {
  width: 100%;
  height: 100%;
  min-height: 100%;
  padding: 22rpx;
  border-radius: 22rpx;
  border: 1rpx solid #dfe8b8;
  background: #ffffff;
  box-sizing: border-box;
  white-space: normal;
  box-shadow: 0 10rpx 24rpx rgba(118, 133, 69, 0.08);

  &.current {
    border-color: #c7d982;
    background: linear-gradient(180deg, #fffef7 0%, #ffffff 100%);
  }

  &.done {
    background: #f4f9e8;
  }

  &.skipped {
    background: #faf7ed;
  }

  &.support {
    background: #fff6ee;
  }
}

.flow-step-head {
  align-items: flex-start;
}

.flow-step-title {
  display: block;
  margin-top: 8rpx;
  font-size: 30rpx;
  line-height: 1.35;
  color: #273012;
  font-weight: 900;
}

.flow-step-index {
  flex-shrink: 0;
  min-width: 96rpx;
  height: 46rpx;
  padding: 0 16rpx;
  border-radius: 999rpx;
  background: #f1f5de;
  color: #6b7d3f;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 22rpx;
  font-weight: 800;
}

.step-note-input {
  width: 100%;
  height: 120rpx;
  min-height: 120rpx;
  margin-top: 16rpx;
  padding: 16rpx 18rpx;
  box-sizing: border-box;
  border-radius: 14rpx;
  border: 1rpx solid #edf1db;
  background: #fbfcf8;
  color: #1a1a2e;
  font-size: 24rpx;
  line-height: 1.6;
}

.step-swiper-footer {
  margin-top: 18rpx;
}

.step-swiper-counter {
  color: #687644;
  font-size: 22rpx;
  font-weight: 700;
}

.step-swiper-dots {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  flex-wrap: wrap;
  gap: 10rpx;
}

.step-swiper-dot {
  width: 12rpx;
  height: 12rpx;
  border-radius: 999rpx;
  background: rgba(107, 125, 63, 0.24);
}

.step-swiper-dot.active {
  width: 34rpx;
  background: #7a9043;
}

.step-swiper-dot.done {
  background: rgba(122, 144, 67, 0.52);
}

.step-swiper-dot.active.done {
  background: #7a9043;
}

.guide-panel {
  padding: 18rpx 20rpx 8rpx;
  border-top: 1rpx solid #f0f0f0;
  background: #fbfcf5;
}

.guide-head,
.step-card-head,
.step-actions,
.media-tools {
  display: flex;
  align-items: center;
}

.guide-head,
.step-card-head {
  justify-content: space-between;
  gap: 16rpx;
}

.guide-title {
  display: block;
  font-size: 26rpx;
  color: #273012;
  font-weight: 800;
}

.guide-subtitle {
  display: block;
  margin-top: 4rpx;
  font-size: 21rpx;
  line-height: 1.4;
  color: #7b8264;
}

.guide-refresh {
  flex-shrink: 0;
  font-size: 22rpx;
  color: #6b7d3f;
  font-weight: 700;
}

.guide-empty {
  min-height: 92rpx;
  display: flex;
  align-items: center;
  padding: 12rpx 0 4rpx;
  color: #7b8264;
  font-size: 24rpx;
  line-height: 1.5;
}

.step-card {
  margin-top: 14rpx;
  padding: 18rpx;
  border: 1rpx solid #dfe8b8;
  border-radius: 12rpx;
  background: #ffffff;
}

.step-tag,
.step-count {
  font-size: 21rpx;
  color: #6b7d3f;
  font-weight: 700;
}

.step-title {
  display: block;
  margin-top: 12rpx;
  font-size: 28rpx;
  color: #273012;
  font-weight: 800;
}

.step-copy,
.step-meta,
.step-risk {
  display: block;
  margin-top: 8rpx;
  font-size: 23rpx;
  line-height: 1.55;
  color: #565f3d;
}

.step-risk {
  color: #9b5c2a;
}

.step-actions {
  gap: 12rpx;
  margin-top: 14rpx;
  flex-wrap: wrap;
}

.step-btn {
  min-width: 96rpx;
  height: 52rpx;
  padding: 0 18rpx;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 999rpx;
  font-size: 22rpx;
  font-weight: 700;
  color: #273012;
  background: #eef4ce;

  &.done {
    background: #d6e29f;
  }

  &.skip {
    background: #f2ecd0;
    color: #7a6534;
  }

  &.support {
    background: #f6d4b6;
    color: #8a4a22;
  }

  &.note {
    background: #e6efe8;
    color: #42624d;
  }

  &.disabled {
    opacity: 0.45;
  }
}

.step-action {
  min-width: 92rpx;
  height: 48rpx;
  padding: 0 14rpx;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 8rpx;
  border: 1rpx solid #dfe8b8;
  color: #5f7137;
  font-size: 22rpx;
  background: #fbfcf5;

  &.primary {
    background: #d6e29f;
    border-color: #d6e29f;
    color: #273012;
    font-weight: 800;
  }
}

.chat-input-area {
  display: flex;
  align-items: flex-end;
  gap: 16rpx;
  padding: 16rpx 20rpx;
  border-top: 1rpx solid #f0f0f0;
  background: #fff;
  width: 100%;
  box-sizing: border-box;
}

.operator-workbench-empty .chat-input-area {
  padding-top: 8rpx;
  border-top: 0;
  background: linear-gradient(180deg, rgba(255, 255, 255, 0.12) 0%, #ffffff 100%);
}

.media-tools {
  flex-direction: column;
  gap: 8rpx;
  flex-shrink: 0;
}

.media-btn {
  width: 76rpx;
  height: 38rpx;
  border-radius: 8rpx;
  background: #eef4ce;
  color: #5f7137;
  font-size: 20rpx;
  font-weight: 700;
  display: flex;
  align-items: center;
  justify-content: center;

  &.active {
    background: #e87070;
    color: #fff;
  }

  &.disabled {
    opacity: 0.55;
  }
}

.chat-input {
  flex: 1;
  width: 0;
  min-width: 0;
  background: #f5f7fa;
  border-radius: 12rpx;
  padding: 16rpx 20rpx;
  box-sizing: border-box;
  font-size: 26rpx;
  color: #1a1a2e;
  min-height: 72rpx;
}

.send-btn {
  width: 100rpx;
  min-width: 100rpx;
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

.worker-voice-btn,
.input-icon-btn {
  flex-shrink: 0;
  display: flex;
  align-items: center;
  justify-content: center;
}

.worker-voice-btn {
  width: 68rpx;
  height: 68rpx;
  border-radius: 50%;
  background: #f5f7f1;
  box-shadow: inset 0 0 0 1rpx rgba(39, 48, 18, 0.035);
  transition: transform 0.16s ease, background-color 0.16s ease;

  &.active {
    background: #2a2f25;
    transform: scale(0.96);

    .chat-control-icon {
      filter: brightness(0) invert(1);
    }
  }

  &.disabled {
    opacity: 0.55;
  }
}

.input-icon-btn {
  width: 68rpx;
  height: 68rpx;
  border-radius: 50%;
  background: #f5f7f1;
  box-shadow: inset 0 0 0 1rpx rgba(39, 48, 18, 0.035);
  transition: transform 0.16s ease, background-color 0.16s ease;

  &:active {
    transform: scale(0.94);
    background: #eef2df;
  }

  &.disabled {
    opacity: 0.45;
  }
}

.chat-control-icon {
  width: 48rpx;
  height: 48rpx;
  display: block;
}

.floating-step-wrap {
  width: 100%;
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 16rpx;
  pointer-events: auto;
}

.floating-step-chip {
  min-width: 220rpx;
  max-width: calc(100% - 120rpx);
  height: 76rpx;
  padding: 0 26rpx 0 22rpx;
  border-radius: 999rpx;
  background: rgba(255, 255, 255, 0.96);
  box-shadow: 0 12rpx 30rpx rgba(36, 40, 28, 0.09);
  display: inline-flex;
  align-items: center;
  gap: 14rpx;
  box-sizing: border-box;
}

.floating-step-chip.active {
  background: #f7fbeb;
  box-shadow: 0 16rpx 34rpx rgba(91, 108, 43, 0.14);
}

.floating-step-icon {
  width: 34rpx;
  height: 34rpx;
  border-radius: 12rpx;
  background: #f1f5df;
  display: flex;
  flex-direction: column;
  justify-content: center;
  gap: 4rpx;
  padding: 0 7rpx;
  box-sizing: border-box;
  flex-shrink: 0;
}

.floating-step-icon-line {
  height: 3rpx;
  border-radius: 999rpx;
  background: #5f7137;
}

.floating-step-icon-line.short {
  width: 60%;
}

.floating-step-chip-label {
  font-size: 28rpx;
  line-height: 1;
  color: #273012;
  font-weight: 800;
  white-space: nowrap;
}

.floating-step-chip-badge {
  max-width: 164rpx;
  height: 42rpx;
  padding: 0 14rpx;
  border-radius: 999rpx;
  background: #edf4cf;
  color: #61713e;
  font-size: 21rpx;
  font-weight: 700;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  white-space: nowrap;
  flex-shrink: 0;
}

.floating-step-popover {
  width: 100%;
  border-radius: 28rpx;
  background: linear-gradient(180deg, #fcfdf7 0%, #f3f8e3 100%);
  border: 1rpx solid #dce5b4;
  box-shadow: 0 24rpx 56rpx rgba(90, 107, 46, 0.18);
  overflow: hidden;
}

.floating-step-popover-head {
  padding: 24rpx 24rpx 18rpx;
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 18rpx;
}

.floating-step-popover-copy {
  flex: 1;
  min-width: 0;
}

.floating-step-popover-tag {
  display: block;
  font-size: 22rpx;
  color: #6b7d3f;
  font-weight: 800;
}

.floating-step-popover-title {
  display: block;
  margin-top: 10rpx;
  font-size: 30rpx;
  line-height: 1.38;
  color: #273012;
  font-weight: 900;
}

.floating-step-popover-sub {
  display: block;
  margin-top: 10rpx;
  font-size: 22rpx;
  line-height: 1.55;
  color: #677345;
}

.floating-step-popover-close {
  min-width: 88rpx;
  height: 56rpx;
  padding: 0 18rpx;
  border-radius: 999rpx;
  background: rgba(255, 255, 255, 0.94);
  color: #6b7d3f;
  font-size: 22rpx;
  font-weight: 800;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  box-shadow: inset 0 0 0 1rpx rgba(214, 226, 159, 0.9);
}

.camera-icon-img {
  width: 52rpx;
  height: 52rpx;
}

.keyboard-icon-img {
  width: 50rpx;
  height: 50rpx;
}

.ai-chat.input-docked {
  padding-bottom: calc(214rpx + env(safe-area-inset-bottom, 0px));
}

.ai-chat.input-docked.has-floating-step-entry {
  padding-bottom: calc(310rpx + env(safe-area-inset-bottom, 0px));
}

.ai-chat.input-docked .chat-messages {
  padding: 18rpx 0 10rpx;
}

.ai-chat.input-docked .msg {
  margin-bottom: 22rpx;
}

.ai-chat.input-docked .msg-bubble {
  padding: 20rpx 24rpx;
  border-radius: 18rpx;
  font-size: 27rpx;
  line-height: 1.68;
}

.ai-chat.input-docked .msg-bubble.ai {
  max-width: calc(100% - 24rpx);
  background: #f6f6f6;
  border-bottom-left-radius: 8rpx;
}

.ai-chat.input-docked .msg-bubble.user {
  max-width: 72%;
  border-bottom-right-radius: 8rpx;
}

.ai-chat.input-docked .chat-input-area {
  position: fixed;
  left: 24rpx;
  right: 24rpx;
  bottom: calc(46rpx + env(safe-area-inset-bottom, 0px));
  z-index: 120;
  width: auto;
  min-height: auto;
  padding: 0;
  border: 0;
  border-radius: 0;
  background: transparent;
  box-shadow: none;
  pointer-events: none;
  box-sizing: border-box;
  max-width: calc(100vw - 48rpx);
  overflow: visible;
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 16rpx;
}

.worker-input-pill {
  width: 100%;
  min-width: 0;
  height: 104rpx;
  padding: 10rpx 14rpx;
  border: 1rpx solid rgba(39, 48, 18, 0.04);
  border-radius: 999rpx;
  background: #ffffff;
  box-shadow: 0 14rpx 40rpx rgba(34, 38, 27, 0.10);
  display: flex;
  align-items: center;
  gap: 18rpx;
  box-sizing: border-box;
  pointer-events: auto;
}

.step-panel-body.floating {
  padding-top: 0;
  border-top: 0;
}

.step-swiper.floating {
  height: min(840rpx, 56vh);
}

.input-camera-btn,
.input-mode-toggle {
  width: 82rpx;
  height: 82rpx;
}

.input-camera-btn {
  background: transparent;
  box-shadow: none;
}

.input-mode-toggle,
.input-mode-toggle.active {
  background: transparent;
  box-shadow: none;
}

.voice-hold-area {
  flex: 1;
  min-width: 0;
  height: 82rpx;
  min-height: 82rpx;
  border-radius: 999rpx;
  display: flex;
  align-items: center;
  justify-content: center;
  color: #1f241d;
  font-size: 28rpx;
  font-weight: 800;
  letter-spacing: 0;
  background: transparent;
  transition: background-color 0.16s ease, transform 0.16s ease;

  &.active {
    background: #eef4ce;
    transform: scale(0.99);
  }

  &.disabled {
    opacity: 0.45;
  }
}

.camera-standalone {
  display: none !important;
}

.ai-chat.input-docked .media-tools {
  flex-direction: row;
  gap: 8rpx;
}

.ai-chat.input-docked .media-btn {
  width: 58rpx;
  height: 52rpx;
  border-radius: 16rpx;
  font-size: 18rpx;
}

.ai-chat.input-docked .chat-input {
  height: 82rpx;
  min-height: 82rpx;
  max-height: 82rpx;
  padding: 21rpx 6rpx;
  border-radius: 0;
  background: transparent;
  font-size: 26rpx;
  color: #23261f;
  line-height: 40rpx;
  overflow: hidden;
}

.ai-chat.input-docked .send-btn {
  width: 96rpx;
  min-width: 96rpx;
  height: 66rpx;
  border-radius: 999rpx;
  background: #b7ca74;
  box-shadow: 0 8rpx 20rpx rgba(115, 133, 57, 0.16);
}

.message-menu-mask,
.select-text-mask {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  z-index: 220;
  background: rgba(23, 27, 17, 0.08);
}

.message-menu {
  position: fixed;
  width: min(580rpx, calc(100vw - 96rpx));
  max-width: calc(100vw - 96rpx);
  left: 48rpx;
  bottom: calc(180rpx + env(safe-area-inset-bottom, 0px));
  border-radius: 18rpx;
  overflow: hidden;
  background: rgba(255, 255, 255, 0.98);
  box-shadow: 0 24rpx 64rpx rgba(39, 48, 18, 0.18);
}

.message-menu-item {
  height: 88rpx;
  padding: 0 32rpx;
  display: flex;
  align-items: center;
  gap: 22rpx;
  border-bottom: 1rpx solid #eef0e8;
  color: #273012;
  font-size: 28rpx;
  font-weight: 700;

  &:last-child {
    border-bottom: 0;
  }
}

.message-menu-icon {
  width: 42rpx;
  color: #5f7137;
  font-size: 24rpx;
  font-weight: 900;
}

.select-text-mask {
  display: flex;
  align-items: flex-end;
  padding: 0 24rpx calc(26rpx + env(safe-area-inset-bottom, 0px));
  box-sizing: border-box;
}

.select-text-panel {
  width: 100%;
  max-height: 62vh;
  padding: 24rpx;
  border-radius: 24rpx;
  background: #ffffff;
  box-shadow: 0 24rpx 64rpx rgba(39, 48, 18, 0.18);
  box-sizing: border-box;
}

.select-text-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 18rpx;
}

.select-text-title {
  font-size: 28rpx;
  color: #273012;
  font-weight: 800;
}

.select-text-close {
  font-size: 24rpx;
  color: #6b7d3f;
  font-weight: 700;
}

.select-text-content {
  display: block;
  max-height: 48vh;
  overflow-y: auto;
  font-size: 27rpx;
  line-height: 1.7;
  color: #2f3327;
  white-space: pre-wrap;
  word-break: break-word;
  user-select: text;
  -webkit-user-select: text;
}

.quick-prompt-bar {
  padding: 18rpx 20rpx 2rpx;
}

.quick-prompt-title {
  display: block;
  font-size: 22rpx;
  color: #7a6c4d;
  font-weight: 700;
}

.quick-prompt-list,
.followup-chip-list,
.experience-feedback-row {
  display: flex;
  flex-wrap: wrap;
  gap: 10rpx;
}

.quick-prompt-list,
.followup-chip-list {
  margin-top: 12rpx;
}

.quick-prompt-chip,
.followup-chip,
.experience-feedback-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-height: 50rpx;
  padding: 0 18rpx;
  border-radius: 999rpx;
  font-size: 21rpx;
  font-weight: 700;
}

.quick-prompt-chip,
.followup-chip {
  background: #f6f1df;
  color: #7a6440;
}

.quick-prompt-chip.disabled,
.followup-chip.disabled,
.experience-feedback-btn.disabled {
  opacity: 0.45;
}

.msg-extensions {
  width: 100%;
  max-width: 100%;
  min-width: 0;
  margin-top: 12rpx;
  display: grid;
  gap: 12rpx;
  box-sizing: border-box;
}

.experience-card-list {
  display: grid;
  gap: 12rpx;
}

.experience-card,
.recommend-card {
  padding: 16rpx 18rpx;
  border-radius: 18rpx;
  background: #fffaf0;
  border: 1rpx solid #efe1b4;
}

.recommend-panel {
  margin: 0 20rpx 16rpx;
  padding: 20rpx;
  border-radius: 18rpx;
  background: linear-gradient(180deg, #fffaf0 0%, #fff6e8 100%);
  border: 1rpx solid #f0ddb3;
}

.recommend-panel-head,
.experience-card-head,
.recommend-card-head,
.experience-card-footer,
.recommend-card-footer {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16rpx;
}

.recommend-panel-title,
.experience-card-title,
.recommend-card-title {
  flex: 1;
  font-size: 25rpx;
  line-height: 1.55;
  color: #3d2f16;
  font-weight: 800;
}

.recommend-panel-subtitle,
.experience-card-meta,
.recommend-card-meta,
.experience-card-stats,
.recommend-card-stats {
  display: block;
  margin-top: 8rpx;
  font-size: 21rpx;
  line-height: 1.6;
  color: #8a7650;
}

.experience-card-copy,
.recommend-card-copy {
  display: block;
  margin-top: 10rpx;
  font-size: 22rpx;
  line-height: 1.6;
  color: #5d4d30;
}

.experience-card-copy.warn,
.recommend-card-copy.warn {
  color: #9b6b2c;
}

.experience-card-copy.risk,
.recommend-card-copy.risk {
  color: #b45042;
}

.experience-card-score,
.recommend-card-score {
  flex-shrink: 0;
  font-size: 20rpx;
  color: #8a6a2a;
  font-weight: 700;
}

.experience-card-footer,
.recommend-card-footer {
  margin-top: 12rpx;
  align-items: center;
}

.experience-feedback-btn {
  background: #f6efe0;
  color: #7a6440;
}

.experience-feedback-btn.active {
  background: #e3f3df;
  color: #2f7a3b;
}

.experience-feedback-btn.danger.active {
  background: #ffe5df;
  color: #b45042;
}

.operator-filter-panel {
  margin: 18rpx 20rpx 4rpx;
  padding: 16rpx;
  border-radius: 22rpx;
  background: linear-gradient(180deg, #f6fbf1 0%, #edf6ea 100%);
  border: 1rpx solid #d6e7cf;
  box-shadow: inset 0 1rpx 0 rgba(255, 255, 255, 0.7);
}

.operator-filter-head {
  display: flex;
  flex-direction: column;
  gap: 4rpx;
}

.operator-filter-title {
  font-size: 23rpx;
  font-weight: 800;
  color: #2f4a32;
}

.operator-filter-sub {
  font-size: 20rpx;
  line-height: 1.45;
  color: #68806c;
}

.operator-filter-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10rpx;
  margin-top: 12rpx;
}

.operator-picker {
  min-width: 0;
}

.operator-picker-box {
  min-height: 72rpx;
  padding: 14rpx 16rpx;
  border-radius: 16rpx;
  background: rgba(255, 255, 255, 0.82);
  border: 1rpx solid #d9e4d4;
  box-shadow: 0 8rpx 18rpx rgba(68, 102, 73, 0.05);
}

.operator-picker-meta {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12rpx;
}

.operator-picker-label {
  display: block;
  font-size: 19rpx;
  color: #7b8c78;
}

.operator-picker-action {
  flex-shrink: 0;
  font-size: 18rpx;
  color: #86a07f;
  font-weight: 700;
}

.operator-picker-value {
  display: block;
  margin-top: 6rpx;
  font-size: 23rpx;
  line-height: 1.32;
  color: #27412b;
  font-weight: 700;
}

.operator-scope-preview {
  display: flex;
  flex-wrap: wrap;
  gap: 8rpx;
  margin-top: 12rpx;
}

.operator-scope-chip {
  display: inline-flex;
  align-items: center;
  min-height: 40rpx;
  padding: 0 14rpx;
  border-radius: 999rpx;
  background: rgba(255, 255, 255, 0.76);
  color: #4d6650;
  font-size: 19rpx;
  font-weight: 700;
  border: 1rpx solid rgba(214, 231, 207, 0.92);
}

.readonly-tag {
  display: inline-flex;
  align-items: center;
  min-height: 44rpx;
  padding: 0 16rpx;
  border-radius: 999rpx;
  background: #eef6e6;
  color: #4c6a43;
  font-size: 20rpx;
  font-weight: 700;
}

.analysis-card {
  width: 100%;
  max-width: 100%;
  min-width: 0;
  padding: 16rpx 18rpx;
  border-radius: 20rpx;
  background: linear-gradient(180deg, #fbfdff 0%, #f6f9fc 100%);
  border: 1rpx solid #e2e8ef;
  box-shadow: 0 10rpx 26rpx rgba(38, 52, 67, 0.05);
  box-sizing: border-box;
}

.warning-card {
  background: #fff6ef;
  border-color: #f3d8bf;
}

.chart-card {
  background: linear-gradient(180deg, #fbfdff 0%, #f2f7fb 100%);
}

.evidence-card {
  background: linear-gradient(180deg, #ffffff 0%, #fafcfd 100%);
}

.followup-card {
  background: linear-gradient(180deg, #fffdfa 0%, #fcf7ee 100%);
}

.analysis-card-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16rpx;
  flex-wrap: wrap;
}

.analysis-card-head--stack {
  display: flex;
  flex-direction: column;
  align-items: stretch;
  gap: 12rpx;
}

.analysis-card-title-wrap {
  width: 100%;
  min-width: 0;
}

.analysis-card-title {
  display: block;
  font-size: 24rpx;
  line-height: 1.5;
  color: #23323b;
  font-weight: 800;
  word-break: break-word;
}

.analysis-card-source {
  display: inline-block;
  margin-top: 8rpx;
  padding: 4rpx 12rpx;
  border-radius: 999rpx;
  background: #eef3f7;
  color: #6a7882;
  font-size: 19rpx;
  line-height: 1.4;
  max-width: 100%;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  box-sizing: border-box;
}

.analysis-card-toggle,
.analysis-card-copy {
  display: block;
  max-width: 100%;
  margin-top: 8rpx;
  font-size: 21rpx;
  line-height: 1.55;
  color: #6a7882;
  word-break: break-word;
}

.analysis-card-toggle {
  margin-top: 0;
  flex-shrink: 0;
  color: #627a88;
  font-weight: 700;
}

.analysis-card-head .analysis-card-copy {
  margin-top: 0;
  flex-shrink: 0;
}

.chart-toolbar-row {
  display: flex;
  align-items: center;
  width: 100%;
  gap: 10rpx;
  flex-wrap: wrap;
  justify-content: space-between;
}

.chart-view-switch {
  display: inline-flex;
  align-items: center;
  gap: 8rpx;
  padding: 6rpx;
  border-radius: 999rpx;
  background: #edf3ef;
}

.chart-view-chip,
.chart-series-chip,
.chart-collapse-chip {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-height: 42rpx;
  padding: 0 16rpx;
  border-radius: 999rpx;
  font-size: 20rpx;
  font-weight: 700;
}

.chart-view-chip {
  color: #6c7f72;
}

.chart-view-chip.active {
  background: #ffffff;
  color: #365a42;
  box-shadow: 0 4rpx 12rpx rgba(54, 90, 66, 0.1);
}

.chart-collapse-chip {
  background: #f3f7fa;
  color: #60717d;
  border: 1rpx solid #dfe8ef;
}

.chart-series-tabs {
  display: flex;
  flex-wrap: wrap;
  gap: 10rpx;
  margin-top: 14rpx;
}

.chart-series-chip {
  background: #eef3f7;
  color: #667786;
}

.chart-series-chip.active {
  background: #dfeee0;
  color: #315942;
}

.chart-visual-shell {
  width: 100%;
  max-width: 100%;
  min-width: 0;
  margin-top: 16rpx;
  padding: 14rpx;
  border-radius: 18rpx;
  background: rgba(255, 255, 255, 0.94);
  border: 1rpx solid #e4ebf1;
  box-sizing: border-box;
}

.chart-axis-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 10rpx;
}

.chart-axis-meta-item {
  display: inline-flex;
  align-items: center;
  min-height: 38rpx;
  padding: 0 12rpx;
  border-radius: 999rpx;
  background: #f5f8fb;
  color: #6c7b86;
  font-size: 18rpx;
  font-weight: 700;
}

.chart-focus-card {
  margin-top: 12rpx;
  padding: 14rpx 16rpx;
  border-radius: 16rpx;
  background: linear-gradient(135deg, #f7fbff 0%, #eef6f2 100%);
  border: 1rpx solid #dbe8de;
}

.chart-focus-kicker {
  display: block;
  font-size: 18rpx;
  color: #7b8c98;
}

.chart-focus-main {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: 16rpx;
  margin-top: 8rpx;
}

.chart-focus-label {
  flex: 1;
  min-width: 0;
  font-size: 24rpx;
  color: #273640;
  font-weight: 700;
}

.chart-focus-value {
  flex-shrink: 0;
  font-size: 24rpx;
  color: #365a42;
  font-weight: 800;
}

.chart-focus-sub {
  display: block;
  margin-top: 8rpx;
  font-size: 19rpx;
  line-height: 1.5;
  color: #6d7b85;
}

.chart-collapsed-tip {
  margin-top: 12rpx;
  padding: 18rpx 16rpx;
  border-radius: 16rpx;
  background: #f7fafc;
  border: 1rpx dashed #d8e2ea;
  color: #71808b;
  font-size: 20rpx;
  text-align: center;
}

.chart-empty-state {
  margin-top: 14rpx;
  padding: 18rpx 16rpx;
  border-radius: 16rpx;
  background: #f7fafc;
  border: 1rpx dashed #d8e2ea;
  color: #71808b;
  font-size: 20rpx;
  text-align: center;
}

.chart-scroll {
  width: 100%;
  max-width: 100%;
  margin-top: 14rpx;
  white-space: nowrap;
  box-sizing: border-box;
}

.chart-visual-canvas {
  display: block;
  margin: 0 auto;
}

.chart-svg {
  width: 100%;
  height: 300rpx;
  display: block;
}

.chart-grid-line {
  stroke: #e6edf2;
  stroke-width: 1;
}

.chart-y-tick {
  fill: #90a0ac;
  font-size: 10px;
}

.chart-axis-baseline {
  stroke: #ccd8df;
  stroke-width: 1.2;
}

.chart-active-guide {
  stroke: rgba(95, 158, 135, 0.35);
  stroke-width: 1.2;
  stroke-dasharray: 4 4;
}

.chart-line {
  fill: none;
  stroke: #5f9e87;
  stroke-width: 4;
  stroke-linecap: round;
  stroke-linejoin: round;
}

.chart-area {
  fill: rgba(140, 191, 125, 0.18);
  stroke: none;
}

.chart-point-hit {
  fill: transparent;
  stroke: transparent;
}

.chart-point {
  fill: #ffffff;
  stroke: #5f9e87;
  stroke-width: 3;
  transition: all 0.2s ease;
}

.chart-point.active {
  fill: #dff0df;
  stroke: #2f7c59;
  stroke-width: 4;
}

.chart-bar-rect {
  fill: url(#chartBarGradient);
  opacity: 0.72;
  transition: opacity 0.2s ease, transform 0.2s ease;
}

.chart-bar-rect.active {
  opacity: 1;
}

.chart-axis-row {
  position: relative;
  height: 42rpx;
  margin-top: 10rpx;
}

.chart-axis-label {
  position: absolute;
  top: 0;
  min-width: 0;
  text-align: center;
  font-size: 18rpx;
  line-height: 1.45;
  color: #7d8a94;
}

.chart-row-list,
.evidence-list {
  display: grid;
  gap: 12rpx;
  margin-top: 16rpx;
}

.chart-row {
  padding: 14rpx 16rpx;
  border-radius: 16rpx;
  background: rgba(255, 255, 255, 0.86);
  border: 1rpx solid #e4ebf1;
}

.chart-row-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16rpx;
}

.chart-row-label {
  font-size: 22rpx;
  color: #2b3c46;
  font-weight: 700;
}

.chart-row-values {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  gap: 4rpx;
}

.chart-row-main {
  text-align: right;
  font-size: 20rpx;
  line-height: 1.5;
  color: #506670;
  font-weight: 700;
}

.chart-row-sub {
  text-align: right;
  font-size: 18rpx;
  line-height: 1.5;
  color: #8a98a3;
}

.chart-row-track {
  height: 12rpx;
  margin-top: 10rpx;
  border-radius: 999rpx;
  background: #e7eef4;
  overflow: hidden;
}

.chart-row-fill {
  height: 100%;
  border-radius: 999rpx;
  background: linear-gradient(90deg, #8cbf7d 0%, #5f9e87 100%);
}

.chart-table {
  display: grid;
  gap: 10rpx;
  margin-top: 16rpx;
}

.chart-table-row {
  padding: 14rpx 16rpx;
  border-radius: 16rpx;
  background: rgba(255, 255, 255, 0.92);
  border: 1rpx solid #e5edf2;
}

.chart-table-label {
  display: block;
  font-size: 22rpx;
  color: #283942;
  font-weight: 800;
}

.chart-table-values {
  display: flex;
  flex-wrap: wrap;
  gap: 10rpx;
  margin-top: 12rpx;
}

.chart-table-pill {
  min-width: 132rpx;
  padding: 10rpx 12rpx;
  border-radius: 14rpx;
  background: #f4f7fa;
}

.chart-table-name {
  display: block;
  font-size: 18rpx;
  color: #82909a;
}

.chart-table-value {
  display: block;
  margin-top: 6rpx;
  font-size: 21rpx;
  color: #31444f;
  font-weight: 700;
}

.evidence-item {
  padding: 14rpx;
  border-radius: 14rpx;
  background: #ffffff;
  border: 1rpx solid #ebf0f4;
}

.evidence-claim {
  display: block;
  font-size: 22rpx;
  line-height: 1.55;
  color: #27343c;
  font-weight: 700;
}

.evidence-ref {
  display: block;
  margin-top: 8rpx;
  font-size: 20rpx;
  line-height: 1.5;
  color: #788690;
}

.followup-chip-list--embedded {
  display: flex;
  flex-wrap: wrap;
  gap: 12rpx;
  min-width: 0;
  width: 100%;
  box-sizing: border-box;
}

.followup-chip--embedded {
  flex: 0 1 auto;
  max-width: 100%;
  white-space: normal;
  line-height: 1.4;
  padding-top: 10rpx;
  padding-bottom: 10rpx;
  text-align: center;
}
</style>
