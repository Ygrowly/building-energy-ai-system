/**
 * 报表状态管理 (Pinia)
 *
 * 负责：
 *  - 各页面注册的报表段落（ReportSection）的增删管理
 *  - 预览弹窗的可见性与当前 payload
 *  - 支持直接传入 payload（用于 AI 对话报表、CSV 解析报表）
 */
import { defineStore } from 'pinia'
import { ref } from 'vue'
import type { ArtifactEvent } from '@/api/stream_client'

// ── 数据模型 ──────────────────────────────────────────────────

export interface KpiItem {
  label: string
  value: string
  unit?: string
  trend?: number | null
}

export interface TableColumn {
  key: string
  label: string
  align?: 'left' | 'right' | 'center'
}

export interface SummaryItem {
  label: string
  value: string
}

export interface ReportCardItem {
  title: string
  subtitle?: string
  metrics: SummaryItem[]
}

export interface FormalReportMeta {
  severity?: string
  confidence?: string
  decisionSummary?: string
  currentJudgement?: string
  conclusionStatus?: string
  overviewItems?: SummaryItem[]
  processSummary?: string[]
  keyMetrics?: SummaryItem[]
  evidenceFacts?: SummaryItem[]
  evidenceBasisMarkdown?: string
  evidenceExclusionMarkdown?: string
  evidenceHighlights?: SummaryItem[]
  impactFacts?: SummaryItem[]
  impactHighlights?: SummaryItem[]
  actions?: string[]
  openQuestions?: string[]
  primaryArtifact?: ArtifactEvent
}

export interface ReportSection {
  id: string
  namespace: string              // 注册方命名空间，用于页面切换时清理
  title: string
  description?: string
  type: 'kpi' | 'table' | 'chart' | 'text' | 'summary' | 'artifact' | 'cards'
  // type=kpi
  kpis?: KpiItem[]
  // type=table
  columns?: TableColumn[]
  rows?: Record<string, any>[]
  // type=chart
  chartImage?: string            // base64 PNG data URL
  // type=summary
  summaryItems?: SummaryItem[]
  // type=cards
  cards?: ReportCardItem[]
  // type=text
  content?: string
  contentFormat?: 'plain' | 'markdown'
  // type=artifact
  artifact?: ArtifactEvent
  order?: number                 // 段落排序（越小越靠前），默认 100
}

export interface ReportPayload {
  title: string
  subtitle?: string
  generatedAt: string
  buildingName?: string
  dateRange?: { start: string; end: string }
  sections: ReportSection[]
  mode: 'snapshot' | 'formal'
  generatedBy?: string
  template_id?: string
  template_label?: string
  formalMeta?: FormalReportMeta
}

// ── Store ─────────────────────────────────────────────────────

export const useReportStore = defineStore('report', () => {
  // 当前注册的所有段落（各页面各子组件写入）
  const sections = ref<ReportSection[]>([])

  // 预览弹窗状态
  const previewVisible = ref(false)
  const previewPayload = ref<ReportPayload | null>(null)
  const previewMode = ref<'snapshot' | 'formal'>('snapshot')

  // 报表元数据（页面设置）
  const reportMeta = ref<Omit<ReportPayload, 'sections' | 'mode' | 'generatedAt'>>({
    title: '楼宇能耗报表',
  })

  // ── 段落管理 ────────────────────────────────────────────────

  function registerSection(section: ReportSection) {
    const idx = sections.value.findIndex(s => s.id === section.id)
    if (idx !== -1) {
      sections.value[idx] = section
    } else {
      sections.value.push(section)
    }
  }

  function removeSection(id: string) {
    sections.value = sections.value.filter(s => s.id !== id)
  }

  function clearSectionsByNamespace(namespace: string) {
    sections.value = sections.value.filter(s => s.namespace !== namespace)
  }

  function clearAllSections() {
    sections.value = []
  }

  // ── 预览控制 ────────────────────────────────────────────────

  function buildPayload(mode: 'snapshot' | 'formal'): ReportPayload {
    const sorted = [...sections.value].sort((a, b) => (a.order ?? 100) - (b.order ?? 100))
    return {
      ...reportMeta.value,
      generatedAt: new Date().toLocaleString('zh-CN'),
      sections: sorted,
      mode,
    }
  }

  function openPreview() {
    previewPayload.value = buildPayload(previewMode.value)
    previewVisible.value = true
  }

  /** 直接传入 payload 打开预览（用于 AI 对话报表、CSV 解析报表） */
  function openPreviewWithPayload(payload: ReportPayload) {
    previewPayload.value = payload
    previewMode.value = payload.mode
    previewVisible.value = true
  }

  function closePreview() {
    previewVisible.value = false
  }

  function setPreviewMode(mode: 'snapshot' | 'formal') {
    previewMode.value = mode
    // 切换模式时重新构建 payload（如果当前是从页面段落构建的）
    if (previewPayload.value && sections.value.length > 0) {
      previewPayload.value = buildPayload(mode)
    } else if (previewPayload.value) {
      previewPayload.value = { ...previewPayload.value, mode }
    }
  }

  function setReportMeta(meta: Partial<typeof reportMeta.value>) {
    reportMeta.value = { ...reportMeta.value, ...meta }
  }

  return {
    sections,
    previewVisible,
    previewPayload,
    previewMode,
    reportMeta,
    registerSection,
    removeSection,
    clearSectionsByNamespace,
    clearAllSections,
    openPreview,
    openPreviewWithPayload,
    closePreview,
    setPreviewMode,
    setReportMeta,
    buildPayload,
  }
})
