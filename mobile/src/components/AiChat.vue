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
    <view v-if="isOperatorMode && operatorQuickPrompts.length" class="quick-prompt-bar">
      <text class="quick-prompt-title">经验速查</text>
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
          <view v-if="isWorkerMode && msg.role === 'ai' && msg.content" class="msg-actions">
            <text class="msg-action" @click="speakText(msg.content)">播报</text>
          </view>
        </view>
        <view
          v-if="msg.role === 'ai' && (msg.experienceItems?.length || msg.suggestedFollowups?.length)"
          class="msg-extensions"
        >
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
          <view v-if="msg.suggestedFollowups?.length" class="followup-chip-list">
            <text
              v-for="followup in msg.suggestedFollowups"
              :key="followup"
              class="followup-chip"
              :class="{ disabled: sending }"
              @click="sendPresetMessage(followup)"
            >{{ followup }}</text>
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

    <view v-if="isWorkerMode && stepPlan?.guidance_ready && currentStep" class="step-panel">
      <view class="step-panel-head">
        <text class="step-panel-tag">当前步骤</text>
        <text class="step-panel-index">第 {{ stepIndex(currentStep.id) + 1 }} 步</text>
      </view>
      <text class="step-panel-title">{{ currentStep.title }}</text>
      <text class="step-panel-text">{{ currentStep.instruction }}</text>
      <text v-if="currentStep.expected_result" class="step-panel-sub">预期：{{ currentStep.expected_result }}</text>
      <text v-if="currentStep.risk_note" class="step-panel-sub warn">注意：{{ currentStep.risk_note }}</text>
      <textarea
        v-model="stepNote"
        class="step-note-input"
        maxlength="300"
        auto-height
        placeholder="记录这一步的现场读数、发现或备注"
      />
      <view class="step-actions">
        <text class="step-btn note" :class="{ disabled: updatingStepId || !stepNote.trim() }" @click="saveCurrentStepNote">备注</text>
        <text class="step-btn done" :class="{ disabled: updatingStepId }" @click="markCurrentStep('completed')">完成</text>
        <text class="step-btn skip" :class="{ disabled: updatingStepId }" @click="markCurrentStep('skipped')">跳过</text>
        <text class="step-btn support" :class="{ disabled: updatingStepId }" @click="markCurrentStep('needs_support')">协同</text>
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
      <view v-if="isWorkerMode" class="media-tools">
        <text class="media-btn" :class="{ disabled: mediaBusy }" @click="chooseImageForAnalysis">拍照</text>
        <text class="media-btn" :class="{ active: recording, disabled: mediaBusy }" @click="toggleRecording">{{ recording ? '停止' : '语音' }}</text>
        <text class="media-btn" @click="speakLatestAiMessage">播报</text>
      </view>
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
import { ref, nextTick, computed, onBeforeUnmount, onMounted, watch } from 'vue'
import { workOrderApi, type WorkOrder } from '../api/workorder'
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

interface ChatMsg {
  role: 'user' | 'ai'
  content: string
  thinking?: boolean
  stepId?: string
  answerType?: string
  experienceItems?: MaintenanceExperienceItem[]
  suggestedFollowups?: string[]
}

const emit = defineEmits<{
  (e: 'order-updated', order: WorkOrder): void
}>()

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
const stepPlan = ref<WorkerAiStepPlan | null>(null)
const guidanceLoading = ref(false)
const updatingStepId = ref<string | null>(null)
const mediaBusy = ref(false)
const recording = ref(false)
const stepNote = ref('')
const componentReady = ref(false)
const workflowBootstrapping = ref(false)
const lastWorkflowPromptKey = ref('')
const nextWorkflowPromptOverride = ref<{ key: string; message: string } | null>(null)
const introducedPlanId = ref('')
const lastStepMessageId = ref('')
const experienceFeedbackLoading = ref<Record<string, MaintenanceExperienceFeedbackType | ''>>({})
const experienceFeedbackState = ref<Record<string, MaintenanceExperienceFeedbackType | ''>>({})
let recorderManager: any = null
let h5MediaRecorder: MediaRecorder | null = null
let h5AudioChunks: BlobPart[] = []

const chatTitle = computed(() => props.title)
const isWorkerMode = computed(() => props.mode === 'worker' && !!props.order)
const isOperatorMode = computed(() => props.mode === 'operator')
const chatHint = computed(() => props.hint || (
  isWorkerMode.value
    ? '基于当前工单自动提供诊断建议'
    : isOperatorMode.value
      ? (props.order ? '只读查看当前工单进展、维修指导和现场记录' : '可以查询工单、派工和维修进展')
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
    ? '请描述您的现场情况，我将提供针对性的维修指导。'
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
const experienceRecommendations = computed<MaintenanceExperienceRecommendation[]>(() => (
  stepPlan.value?.experience_recommendations || []
))
const operatorQuickPrompts = computed(() => {
  if (!isOperatorMode.value) return []
  const subject = props.order?.ticket_id ? `这张工单 ${props.order.ticket_id}` : '当前这类故障'
  return [
    `${subject} 类似问题历史上大家怎么处理？`,
    `${subject} 最近有哪些相关经验？`,
    `${subject} 哪些经验被引用最多？`,
  ]
})

function getErrorMessage(err: unknown, fallback: string) {
  if (err instanceof Error && err.message) return err.message
  if (typeof err === 'object' && err) {
    const message = (err as any).errMsg || (err as any).message || (err as any).detail
    if (typeof message === 'string' && message.trim()) return message.trim()
  }
  return fallback
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

async function refreshOrderState() {
  if (!props.order?.ticket_id) return null
  try {
    const latest = await workOrderApi.detail(props.order.ticket_id)
    emit('order-updated', latest)
    return latest
  } catch (err) {
    console.warn('[AiChat] 工单刷新失败', err)
    return null
  }
}

function currentWorkflowPrompt(): { key: string; message: string } | null {
  if (!isWorkerMode.value || !props.order) return null
  if (nextWorkflowPromptOverride.value) return nextWorkflowPromptOverride.value
  if (props.hallEntryId) return { key: `support:${props.hallEntryId}`, message: '确认协同' }

  const dispatch = props.order.current_dispatch
  const dispatchStatus = (
    dispatch?.dispatch_status
    || dispatch?.execution_status
    || props.order.execution_status
    || props.order.status
    || ''
  ).toLowerCase()

  if (
    dispatchStatus.includes('processing')
    || dispatchStatus.includes('waiting_support')
    || dispatchStatus.includes('completed')
    || dispatchStatus.includes('closed')
  ) {
    return null
  }
  if (!props.order.accepted_at && !dispatch?.accepted_at && dispatchStatus.includes('assigned')) {
    return { key: 'accept', message: '确认接单' }
  }
  if (!props.order.arrived_at && !dispatch?.arrived_at && (props.order.accepted_at || dispatch?.accepted_at || dispatchStatus.includes('accepted'))) {
    return { key: 'arrive', message: '确认到场' }
  }
  if (!props.order.processing_started_at && !dispatch?.processing_started_at && (props.order.arrived_at || dispatch?.arrived_at || dispatchStatus.includes('arrived'))) {
    return { key: 'start', message: '开始处理' }
  }
  if (!props.order.accepted_at && !dispatch?.accepted_at) {
    return { key: 'accept', message: '确认接单' }
  }
  if (!props.order.arrived_at && !dispatch?.arrived_at) {
    return { key: 'arrive', message: '确认到场' }
  }
  if (!props.order.processing_started_at && !dispatch?.processing_started_at) {
    return { key: 'start', message: '开始处理' }
  }
  return null
}

function shouldUseGuidanceChat() {
  return Boolean(
    props.mode === 'worker'
      && props.order?.ticket_id
      && stepPlan.value?.guidance_ready
      && stepPlan.value?.plan_id
      && currentStep.value,
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

async function loadStepPlan(autoGenerate = true) {
  if (!isWorkerMode.value || !props.order?.ticket_id || guidanceLoading.value) return
  guidanceLoading.value = true
  try {
    stepPlan.value = await workerAiApi.getSteps(props.order.ticket_id, {
      auto_generate: autoGenerate,
      dispatch_id: currentDispatchId(),
    })
    if (!stepPlan.value.guidance_ready) {
      await bootstrapWorkflowPrompt()
    } else {
      introduceStepPlanIfReady()
    }
  } catch (err) {
    messages.value.push({ role: 'ai', content: getErrorMessage(err, '步骤卡片加载失败') })
  } finally {
    guidanceLoading.value = false
  }
}

function stepIndex(stepId: string | undefined): number {
  if (!stepId || !stepPlan.value?.steps?.length) return -1
  return stepPlan.value.steps.findIndex(step => step.id === stepId)
}

function formatPlanOverview(plan: WorkerAiStepPlan): string {
  const lines = plan.steps.map((step, index) => `${index + 1}. ${step.title}`)
  return [
    '我先把整体维修路线说一下：',
    ...lines,
    '',
    '我们按这个顺序一步一步走。你也可以随时说“我想先查别的地方”，我会根据现场情况调整建议。',
  ].join('\n')
}

function formatStepMessage(step: WorkerAiStep): string {
  const index = stepIndex(step.id)
  const total = stepPlan.value?.steps?.length || 0
  const lines = [
    `现在做第 ${index + 1}/${total} 步：${step.title}`,
    step.instruction,
  ]
  if (step.expected_result) lines.push(`预期结果：${step.expected_result}`)
  if (step.risk_note) lines.push(`注意：${step.risk_note}`)
  if (step.requires_photo) lines.push('这一步建议拍照，方便我结合现场图片判断。')
  lines.push('做完后直接告诉我“完成了”。如果看不清、做不了、需要协同，也直接说出来。')
  return lines.join('\n')
}

function introduceStepPlanIfReady() {
  const plan = stepPlan.value
  if (!plan?.guidance_ready || !plan.steps.length || !plan.plan_id) return
  if (introducedPlanId.value !== plan.plan_id) {
    introducedPlanId.value = plan.plan_id
    messages.value.push({ role: 'ai', content: formatPlanOverview(plan) })
  }
  pushCurrentStepMessage()
  scrollToBottom()
}

function pushCurrentStepMessage(force = false) {
  const step = currentStep.value
  if (!step) return
  if (!force && lastStepMessageId.value === step.id) return
  lastStepMessageId.value = step.id
  messages.value.push({ role: 'ai', content: formatStepMessage(step), stepId: step.id })
}

function classifyStepStatusFromText(text: string): WorkerAiStepStatus | null {
  const normalized = text.trim()
  if (!normalized || !currentStep.value || sending.value) return null
  if (/(需要|请求|申请|找|叫).*(协同|支援|电工|水工|班组|师傅)|协同|支援/.test(normalized)) {
    return 'needs_support'
  }
  if (/不确定|不清楚|看不清|看不懂|不会|不知道|没找到|找不到|判断不了|无法判断|做不了|不能做|卡住/.test(normalized)) {
    return 'uncertain'
  }
  if (/跳过|先不做|先不处理|暂时不做|略过/.test(normalized)) {
    return 'skipped'
  }
  if (/完成|完成了|做完|做完了|已完成|处理好了|好了|搞定|检查完|看完了|核对完|确认了/.test(normalized)) {
    return 'completed'
  }
  return null
}

async function bootstrapWorkflowPrompt(force = false) {
  const prompt = currentWorkflowPrompt()
  if (!prompt || workflowBootstrapping.value) return
  if (!force && lastWorkflowPromptKey.value === prompt.key) return
  workflowBootstrapping.value = true
  lastWorkflowPromptKey.value = prompt.key
  try {
    messages.value.push({ role: 'ai', content: '我先带你完成工单前置流程...', thinking: true })
    scrollToBottom()
    await sendAssistantMessage(prompt.message, { silentUserMessage: true, source: 'workflow_bootstrap' })
  } finally {
    workflowBootstrapping.value = false
  }
}

async function updateStep(
  stepId: string,
  status: WorkerAiStepStatus,
  options: { echoUser?: boolean; note?: string | null; noteOnly?: boolean } = {},
) {
  if (!props.order?.ticket_id || !stepPlan.value?.plan_id || updatingStepId.value) return
  updatingStepId.value = stepId
  const oldStep = stepPlan.value.steps.find(step => step.id === stepId)
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
    if (updatedStep) stepNote.value = updatedStep.note || ''
    const actionLabel: Record<WorkerAiStepStatus, string> = {
      completed: '完成',
      skipped: '跳过',
      needs_support: '需要协同',
      uncertain: '不确定',
      pending: '重新打开',
    }[status]
    if (options.noteOnly) {
      if (note) {
        messages.value.push({ role: 'user', content: `备注：${note}` })
      }
      messages.value.push({ role: 'ai', content: response.next_suggestion })
      scrollToBottom()
      return
    }
    if (options.echoUser !== false) {
      messages.value.push({ role: 'user', content: `${actionLabel}：${oldStep?.title || '当前步骤'}` })
    }
    if (status === 'needs_support') {
      messages.value.push({ role: 'ai', content: response.next_suggestion })
    } else if (status === 'uncertain') {
      messages.value.push({
        role: 'ai',
        content: '没关系，这一步先不要硬做。你可以拍一张现场图，或者把你卡住的位置告诉我，我再帮你判断。',
        stepId,
      })
    } else if (currentStep.value) {
      pushCurrentStepMessage(true)
    } else {
      messages.value.push({ role: 'ai', content: '这轮维修步骤已经走完了。请汇总现场记录，再由你确认是否提交处理完成。' })
    }
    scrollToBottom()
  } catch (err) {
    messages.value.push({ role: 'ai', content: getErrorMessage(err, '步骤状态更新失败') })
  } finally {
    updatingStepId.value = null
  }
}

async function markCurrentStep(status: WorkerAiStepStatus) {
  if (!currentStep.value) return
  await updateStep(currentStep.value.id, status, { note: stepNote.value })
}

async function saveCurrentStepNote() {
  if (!currentStep.value) return
  if (!stepNote.value.trim()) {
    uni.showToast({ title: '请先输入备注内容', icon: 'none' })
    return
  }
  await updateStep(currentStep.value.id, currentStep.value.status, {
    echoUser: false,
    note: stepNote.value,
    noteOnly: true,
  })
}

async function handleStepStatusText(text: string): Promise<boolean> {
  const status = classifyStepStatusFromText(text)
  if (!status || !currentStep.value) return false
  messages.value.push({ role: 'user', content: text })
  inputText.value = ''
  isFirstMessage.value = false
  scrollToBottom()
  await updateStep(currentStep.value.id, status, { echoUser: false })
  return true
}

async function sendMessage() {
  const text = inputText.value.trim()
  if (!text || sending.value) return

  if (props.mode === 'worker' && await handleStepStatusText(text)) {
    return
  }

  if (shouldUseGuidanceChat()) {
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
  const step = currentStep.value
  if (!props.order?.ticket_id || !plan?.plan_id || !step) {
    await sendAssistantMessage(text)
    return
  }
  try {
    const response = await workerAiApi.guidanceChat({
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
    })
    sessionId.value = response.session_id
    removePendingThinking()
    messages.value.push({ role: 'ai', content: response.answer, stepId: response.step_id || step.id })
  } catch (err) {
    removePendingThinking()
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
    const response = props.mode === 'operator'
      ? await operatorAiApi.chat({
          message: text,
          session_id: sessionId.value,
          ticket_id: props.order?.ticket_id || null,
          scope: {
            source_component: options.source || 'AiChat',
            work_order_status: props.order?.status || null,
            execution_status: props.order?.current_dispatch?.execution_status || props.order?.execution_status || null,
          },
          include_evidence: true,
        })
      : await workerAiApi.chat({
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
        })
    sessionId.value = response.session_id
    removePendingThinking()
    messages.value.push({
      role: 'ai',
      content: response.answer,
      answerType: 'answer_type' in response ? response.answer_type : undefined,
      experienceItems: props.mode === 'operator' && 'facts' in response
        ? normalizeExperienceItems(response.facts)
        : undefined,
      suggestedFollowups: 'suggested_followups' in response
        ? (response.suggested_followups || [])
        : undefined,
    })
    if (props.mode === 'worker' && response.message_type === 'action_result') {
      const latestOrder = await refreshOrderState()
      if (latestOrder) {
        await nextTick()
      }
      if (response.action_result?.action === 'start') {
        await loadStepPlan(true)
      }
      if (response.action_result?.action === 'accept') {
        nextWorkflowPromptOverride.value = { key: 'arrive', message: '确认到场' }
        lastWorkflowPromptKey.value = ''
        messages.value.push({ role: 'ai', content: '接下来到达现场后，回复“确认”我就帮你提交到场；如果还没到场，可以回复“取消”。' })
        await bootstrapWorkflowPrompt(true)
      } else if (response.action_result?.action === 'arrive') {
        nextWorkflowPromptOverride.value = { key: 'start', message: '开始处理' }
        lastWorkflowPromptKey.value = ''
        messages.value.push({ role: 'ai', content: '是否现在开始处理？回复“确认”后我会提交开始处理，随后生成维修步骤卡片。' })
        await bootstrapWorkflowPrompt(true)
      } else if (response.action_result?.action === 'start') {
        nextWorkflowPromptOverride.value = null
      }
    }
  } catch (err) {
    removePendingThinking()
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

async function chooseImageForAnalysis() {
  if (!isWorkerMode.value || !props.order?.ticket_id || mediaBusy.value) return
  mediaBusy.value = true
  try {
    const chooseResult: any = await new Promise((resolve, reject) => {
      uni.chooseImage({
        count: 1,
        sourceType: ['camera', 'album'],
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
      recording.value = false
      if (!res?.tempFilePath) return
      await transcribeAudioFile(res.tempFilePath)
    })
    recorderManager.onError((err: any) => {
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
    if (process.env.UNI_PLATFORM === 'h5') {
      h5MediaRecorder?.stop()
    } else {
      recorderManager?.stop()
    }
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
    h5AudioChunks = []
    const mimeType = MediaRecorder.isTypeSupported('audio/webm;codecs=opus')
      ? 'audio/webm;codecs=opus'
      : 'audio/webm'
    h5MediaRecorder = new MediaRecorder(stream, { mimeType })
    h5MediaRecorder.ondataavailable = (event) => {
      if (event.data?.size) h5AudioChunks.push(event.data)
    }
    h5MediaRecorder.onstop = async () => {
      recording.value = false
      stream.getTracks().forEach(track => track.stop())
      const blob = new Blob(h5AudioChunks, { type: 'audio/webm' })
      if (blob.size) await transcribeAudioBlob(blob)
      mediaBusy.value = false
    }
    h5MediaRecorder.onerror = () => {
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

async function speakLatestAiMessage() {
  const latest = [...messages.value].reverse().find(msg => msg.role === 'ai' && !msg.thinking && msg.content)
  if (latest) {
    await speakText(latest.content)
    return
  }
  const text = currentStep.value?.instruction || stepPlan.value?.summary || welcomeBody.value
  await speakText(text)
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
  () => currentStep.value?.id,
  () => {
    stepNote.value = currentStep.value?.note || ''
  },
  { immediate: true },
)

watch(
  () => [props.mode, props.order?.ticket_id, props.dispatchId],
  () => {
    if (isWorkerMode.value) void loadStepPlan(true)
  },
)

onMounted(() => {
  nextTick(() => {
    componentReady.value = true
    setupRecorder()
    if (isWorkerMode.value) void loadStepPlan(true)
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

.chat-header {
  padding: 20rpx 24rpx 16rpx;
  border-bottom: 1rpx solid #f0f0f0;
}

.chat-title { display: block; font-size: 28rpx; font-weight: 700; color: #1a1a2e; }
.chat-hint  { font-size: 22rpx; color: #aaa; }

.chat-messages {
  height: 520rpx;
  padding: 16rpx 20rpx;
  box-sizing: border-box;
}

.msg {
  display: flex;
  min-width: 0;
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
  box-sizing: border-box;
  overflow-wrap: anywhere;
  word-break: break-word;

  text {
    display: block;
    margin-bottom: 6rpx;
    white-space: pre-wrap;
    word-break: break-word;
    &:last-child { margin-bottom: 0; }
  }

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

.msg-actions {
  display: flex;
  justify-content: flex-end;
  margin-top: 8rpx;
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

.step-panel-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16rpx;
}

.step-panel-tag,
.step-panel-index {
  font-size: 22rpx;
  color: #6b7d3f;
  font-weight: 700;
}

.step-panel-title {
  display: block;
  margin-top: 12rpx;
  font-size: 28rpx;
  line-height: 1.45;
  color: #273012;
  font-weight: 800;
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

.step-note-input {
  width: 100%;
  min-height: 120rpx;
  margin-top: 16rpx;
  padding: 16rpx 18rpx;
  box-sizing: border-box;
  border-radius: 14rpx;
  background: #ffffff;
  color: #1a1a2e;
  font-size: 24rpx;
  line-height: 1.6;
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

.quick-prompt-bar {
  padding: 18rpx 20rpx 0;
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
  margin-top: 10rpx;
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
</style>
