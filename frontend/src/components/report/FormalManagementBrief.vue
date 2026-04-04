<template>
  <div class="minutes-doc">
    <header class="minutes-header">
      <div class="minutes-brand-row">
        <span class="minutes-brand">楼宇能耗智能管理系统</span>
        <span class="minutes-template">{{ payload.template_label ?? 'AI辅助研判会话纪要' }}</span>
      </div>
      <h1 class="minutes-title">{{ payload.title }}</h1>
      <div
        v-if="decisionSummary"
        class="minutes-summary minutes-summary-markdown"
        v-html="renderBlock(`**总结结论：** ${decisionSummary}`)"
      ></div>
      <div class="minutes-status">
        <span class="status-pill" :class="severityClass">{{ severityLabel }}</span>
        <span v-if="currentJudgement" class="status-pill neutral">{{ currentJudgement }}</span>
        <span v-if="conclusionStatus" class="status-pill neutral">{{ conclusionStatus }}</span>
      </div>
    </header>

    <section v-if="overviewItems.length" class="minutes-section">
      <div class="section-title">会话概况</div>
      <div class="overview-grid">
        <div v-for="item in overviewItems" :key="item.label" class="overview-card">
          <div class="overview-label">{{ item.label }}</div>
          <div class="overview-value">{{ item.value }}</div>
        </div>
      </div>
    </section>

    <section v-if="problemStatement" class="minutes-section">
      <div class="section-title">发起问题</div>
      <div class="section-markdown" v-html="renderBlock(problemStatement)"></div>
    </section>

    <section v-if="processSummaryMarkdown" class="minutes-section">
      <div class="section-title">研判过程摘要</div>
      <div class="section-markdown" v-html="renderMarkdown(processSummaryMarkdown)"></div>
    </section>

    <section v-if="conclusionText" class="minutes-section">
      <div class="section-title">会话结论</div>
      <div class="section-markdown section-paragraph-strong" v-html="renderBlock(conclusionText)"></div>
    </section>

    <section class="minutes-section dual-section">
      <div class="dual-card">
        <div class="section-title">关键依据</div>
        <template v-if="evidenceFacts.length || evidenceBasisMarkdown || evidenceExclusionMarkdown">
          <div v-if="evidenceFacts.length" class="summary-list">
            <div v-for="item in evidenceFacts" :key="item.label" class="summary-item">
              <span class="summary-label">{{ item.label }}</span>
              <div class="summary-value summary-markdown" v-html="renderSummaryValue(item.value)"></div>
            </div>
          </div>
          <div v-if="evidenceBasisMarkdown" class="narrative-block">
            <div class="summary-label narrative-label">主要依据</div>
            <div class="section-markdown narrative-markdown" v-html="renderBlock(evidenceBasisMarkdown)"></div>
          </div>
          <div v-if="evidenceExclusionMarkdown" class="narrative-block">
            <div class="summary-label narrative-label">排除项</div>
            <div class="section-markdown narrative-markdown" v-html="renderBlock(evidenceExclusionMarkdown)"></div>
          </div>
        </template>
        <div v-else class="summary-empty">当前无关键依据</div>
      </div>

      <div class="dual-card">
        <div class="section-title">影响评估</div>
        <div v-if="impactFacts.length" class="summary-list">
          <div v-for="item in impactFacts" :key="item.label" class="summary-item">
            <span class="summary-label">{{ item.label }}</span>
            <div class="summary-value summary-markdown" v-html="renderSummaryValue(item.value)"></div>
          </div>
        </div>
        <div v-else class="summary-empty">当前无影响评估</div>
      </div>
    </section>

    <section class="minutes-section">
      <div class="section-title">建议动作</div>
      <div v-if="actionsMarkdown" class="section-markdown" v-html="renderMarkdown(actionsMarkdown)"></div>
      <div v-else class="summary-empty">当前无建议动作</div>
    </section>

    <section class="minutes-section">
      <div class="section-title">待确认事项</div>
      <div v-if="openQuestionsMarkdown" class="section-markdown" v-html="renderMarkdown(openQuestionsMarkdown)"></div>
      <div v-else class="summary-empty">当前无待确认事项</div>
    </section>

    <footer class="minutes-footer">
      <span>楼宇能耗智能管理系统 | 自动生成 | 内部资料</span>
      <span>{{ payload.generatedAt }}</span>
    </footer>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import type { ReportPayload, ReportSection } from '@/stores/reportStore'
import { renderMarkdown } from '@/utils/markdown'

const props = defineProps<{ payload: ReportPayload }>()

const meta = computed(() => props.payload.formalMeta)
const overviewItems = computed(() => meta.value?.overviewItems ?? [])
const evidenceFacts = computed(() => {
  if (meta.value?.evidenceFacts?.length) {
    return meta.value.evidenceFacts
  }
  return (meta.value?.evidenceHighlights ?? []).filter(item => ['异常时段', '偏离水平'].includes(item.label))
})
const evidenceBasisMarkdown = computed(() => (
  meta.value?.evidenceBasisMarkdown
  || findSummaryValue(meta.value?.evidenceHighlights ?? [], '主要依据')
))
const evidenceExclusionMarkdown = computed(() => (
  meta.value?.evidenceExclusionMarkdown
  || findSummaryValue(meta.value?.evidenceHighlights ?? [], '排除项')
))
const impactFacts = computed(() => (
  meta.value?.impactFacts?.length
    ? meta.value.impactFacts
    : (meta.value?.impactHighlights ?? [])
))
const decisionSummary = computed(() => meta.value?.decisionSummary ?? props.payload.subtitle ?? '')
const currentJudgement = computed(() => meta.value?.currentJudgement ?? '')
const conclusionStatus = computed(() => meta.value?.conclusionStatus ?? '')
const processSummary = computed(() => meta.value?.processSummary ?? [])
const actions = computed(() => meta.value?.actions ?? [])
const openQuestions = computed(() => meta.value?.openQuestions ?? [])

const severityLabelMap: Record<string, string> = {
  critical: '高关注',
  warning: '重点关注',
  attention: '持续关注',
  pending: '待确认',
}

const severityClass = computed(() => `severity-${meta.value?.severity ?? 'pending'}`)
const severityLabel = computed(() => severityLabelMap[meta.value?.severity ?? 'pending'] ?? '待确认')
const problemStatement = computed(() => findSection('conversation-problem-statement')?.content ?? '')
const processSummaryMarkdown = computed(() => (
  findSection('conversation-process-summary')?.content
  || listToMarkdown(processSummary.value)
))
const conclusionText = computed(() => (
  findSection('conversation-conclusion')?.content
  || decisionSummary.value
))
const actionsMarkdown = computed(() => (
  findSection('conversation-recommendations')?.content
  || listToMarkdown(actions.value)
))
const openQuestionsMarkdown = computed(() => (
  findSection('conversation-risks')?.content
  || listToMarkdown(openQuestions.value)
))

function findSection(id: string): ReportSection | undefined {
  return props.payload.sections.find(section => section.id === id)
}

function listToMarkdown(items: string[]): string {
  return items
    .map(item => item.trim())
    .filter(Boolean)
    .map(item => `- ${item}`)
    .join('\n')
}

function renderSummaryValue(value: string): string {
  return renderMarkdown(value || '')
}

function renderBlock(value: string): string {
  return renderMarkdown(value || '')
}

function findSummaryValue(items: { label: string; value: string }[], label: string): string {
  return items.find(item => item.label === label)?.value ?? ''
}
</script>

<style scoped>
.minutes-doc {
  display: flex;
  flex-direction: column;
  gap: 18px;
  color: #182230;
}

.minutes-header,
.minutes-section,
.dual-card {
  border: 1px solid #d9e1ea;
  background: #fff;
}

.minutes-header {
  padding: 22px 24px 20px;
}

.minutes-brand-row {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  align-items: center;
  margin-bottom: 14px;
}

.minutes-brand {
  font-size: 12px;
  font-weight: 700;
  color: #244674;
  letter-spacing: 0.06em;
}

.minutes-template {
  font-size: 12px;
  color: #6b7280;
}

.minutes-title {
  margin: 0;
  font-size: 28px;
  line-height: 1.3;
  font-weight: 700;
  color: #102033;
}

.minutes-summary {
  margin: 12px 0 0;
  font-size: 15px;
  line-height: 1.8;
  color: #334155;
}

.minutes-summary-markdown :deep(p) {
  margin: 0;
}

.minutes-summary-markdown :deep(strong) {
  color: #102033;
}

.minutes-status {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 14px;
}

.status-pill {
  display: inline-flex;
  align-items: center;
  padding: 5px 10px;
  border-radius: 999px;
  font-size: 12px;
  font-weight: 600;
}

.status-pill.neutral {
  background: #eef2f7;
  color: #475569;
}

.severity-critical {
  background: rgba(220, 38, 38, 0.12);
  color: #b91c1c;
}

.severity-warning {
  background: rgba(245, 158, 11, 0.14);
  color: #b45309;
}

.severity-attention {
  background: rgba(37, 99, 235, 0.12);
  color: #1d4ed8;
}

.severity-pending {
  background: #eef2f7;
  color: #475569;
}

.minutes-section {
  padding: 18px 20px;
  page-break-inside: avoid;
}

.section-title {
  margin-bottom: 12px;
  padding-left: 10px;
  border-left: 3px solid #274c77;
  font-size: 16px;
  font-weight: 700;
  color: #102033;
}

.overview-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 12px;
}

.overview-card {
  border: 1px solid #dfe6ef;
  background: #f8fafc;
  padding: 14px 16px;
  min-height: 88px;
}

.overview-label,
.summary-label {
  display: block;
  font-size: 11px;
  color: #64748b;
  letter-spacing: 0.04em;
  text-transform: uppercase;
}

.overview-value {
  margin-top: 8px;
  font-size: 16px;
  line-height: 1.6;
  font-weight: 600;
  color: #102033;
}

.section-paragraph,
.section-markdown {
  margin: 0;
  font-size: 14px;
  line-height: 1.9;
  color: #334155;
}

.section-paragraph-strong {
  color: #182230;
}

.section-markdown :deep(p),
.section-markdown :deep(ul),
.section-markdown :deep(ol) {
  margin: 0 0 10px;
}

.section-markdown :deep(ul),
.section-markdown :deep(ol) {
  padding-left: 20px;
}

.dual-section {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  align-items: start;
  gap: 14px;
  padding: 0;
  border: none;
  background: transparent;
}

.dual-card {
  padding: 18px 20px;
  page-break-inside: avoid;
}

.summary-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.summary-item {
  display: flex;
  flex-direction: column;
  gap: 6px;
  padding-bottom: 12px;
  border-bottom: 1px solid #e2e8f0;
}

.summary-item:last-child {
  border-bottom: none;
  padding-bottom: 0;
}

.narrative-block {
  margin-top: 14px;
  padding-top: 14px;
  border-top: 1px solid #e2e8f0;
}

.narrative-label {
  margin-bottom: 8px;
}

.narrative-markdown {
  color: #182230;
}

.summary-value {
  font-size: 14px;
  line-height: 1.8;
  color: #182230;
}

.summary-markdown :deep(p),
.summary-markdown :deep(ul),
.summary-markdown :deep(ol) {
  margin: 0;
}

.summary-markdown :deep(strong) {
  font-weight: 700;
  color: #102033;
}

.summary-markdown :deep(ul),
.summary-markdown :deep(ol) {
  padding-left: 20px;
}

.summary-empty {
  font-size: 13px;
  color: #64748b;
}

.minutes-footer {
  display: flex;
  justify-content: space-between;
  gap: 16px;
  padding-top: 10px;
  border-top: 1px solid #d9e1ea;
  color: #94a3b8;
  font-size: 11px;
}

@media (max-width: 900px) {
  .minutes-brand-row,
  .minutes-footer {
    flex-direction: column;
    align-items: flex-start;
  }

  .overview-grid,
  .dual-section {
    grid-template-columns: 1fr;
  }

  .minutes-title {
    font-size: 24px;
  }
}
</style>
