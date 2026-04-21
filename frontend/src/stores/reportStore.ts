/**
 * Report store (Pinia)
 *
 * Responsibilities:
 * - manage sections registered by each page/component
 * - manage preview dialog state
 * - build page-report payloads from the active page scope
 * - accept direct payloads for conversation / server-generated reports
 */
import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import type { ArtifactEvent } from '@/api/stream_client'

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

export interface ReportInsightItem {
  tag: string
  title: string
  text: string
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
  namespace: string
  title: string
  description?: string
  type: 'kpi' | 'table' | 'chart' | 'text' | 'summary' | 'artifact' | 'cards' | 'insights'
  kpis?: KpiItem[]
  columns?: TableColumn[]
  rows?: Record<string, any>[]
  chartImage?: string
  summaryItems?: SummaryItem[]
  insights?: ReportInsightItem[]
  cards?: ReportCardItem[]
  content?: string
  contentFormat?: 'plain' | 'markdown'
  artifact?: ArtifactEvent
  order?: number
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

function isSamePrefixList(left: string[], right: string[]) {
  if (left.length !== right.length) return false
  return left.every((item, index) => item === right[index])
}

export const useReportStore = defineStore('report', () => {
  const sections = ref<ReportSection[]>([])
  const activeNamespacePrefixes = ref<string[]>([])

  const previewVisible = ref(false)
  const previewPayload = ref<ReportPayload | null>(null)
  const previewMode = ref<'snapshot' | 'formal'>('snapshot')
  const previewSource = ref<'sections' | 'payload'>('sections')

  const reportMeta = ref<Omit<ReportPayload, 'sections' | 'mode' | 'generatedAt'>>({
    title: '楼宇能耗报表',
  })

  const matchesActiveScope = (section: ReportSection) => {
    if (!activeNamespacePrefixes.value.length) return true
    return activeNamespacePrefixes.value.some(prefix => section.namespace.startsWith(prefix))
  }

  const activeSections = computed(() => sections.value.filter(matchesActiveScope))
  const hasActiveSections = computed(() => activeSections.value.length > 0)

  function registerSection(section: ReportSection) {
    const index = sections.value.findIndex(item => item.id === section.id)
    if (index !== -1) {
      sections.value[index] = section
      return
    }
    sections.value.push(section)
  }

  function removeSection(id: string) {
    sections.value = sections.value.filter(section => section.id !== id)
  }

  function clearSectionsByNamespace(namespace: string) {
    sections.value = sections.value.filter(section => section.namespace !== namespace)
  }

  function clearAllSections() {
    sections.value = []
  }

  function setActiveNamespacePrefixes(prefixes: string[]) {
    activeNamespacePrefixes.value = [...prefixes]
  }

  function clearActiveNamespacePrefixes(prefixes?: string[]) {
    if (!prefixes || isSamePrefixList(activeNamespacePrefixes.value, prefixes)) {
      activeNamespacePrefixes.value = []
    }
  }

  function buildPayload(mode: 'snapshot' | 'formal'): ReportPayload {
    const sortedSections = [...activeSections.value]
      .sort((left, right) => (left.order ?? 100) - (right.order ?? 100))

    return {
      ...reportMeta.value,
      generatedAt: new Date().toLocaleString('zh-CN'),
      sections: sortedSections,
      mode,
    }
  }

  function openPreview() {
    previewMode.value = 'snapshot'
    previewSource.value = 'sections'
    previewPayload.value = buildPayload('snapshot')
    previewVisible.value = true
  }

  function openPreviewWithPayload(payload: ReportPayload) {
    previewSource.value = 'payload'
    previewPayload.value = payload
    previewMode.value = payload.mode
    previewVisible.value = true
  }

  function closePreview() {
    previewVisible.value = false
  }

  function setPreviewMode(mode: 'snapshot' | 'formal') {
    previewMode.value = mode
    if (!previewPayload.value) return

    if (previewSource.value === 'sections') {
      previewPayload.value = buildPayload(mode)
      return
    }

    previewPayload.value = { ...previewPayload.value, mode }
  }

  function setReportMeta(meta: Partial<typeof reportMeta.value>) {
    reportMeta.value = { ...reportMeta.value, ...meta }
  }

  return {
    sections,
    activeSections,
    activeNamespacePrefixes,
    hasActiveSections,
    previewVisible,
    previewPayload,
    previewMode,
    previewSource,
    reportMeta,
    registerSection,
    removeSection,
    clearSectionsByNamespace,
    clearAllSections,
    setActiveNamespacePrefixes,
    clearActiveNamespacePrefixes,
    openPreview,
    openPreviewWithPayload,
    closePreview,
    setPreviewMode,
    setReportMeta,
    buildPayload,
  }
})
