<template>
  <div class="rr-doc" :class="{ 'rr-formal': payload.mode === 'formal' }">
    <FormalManagementBrief
      v-if="payload.mode === 'formal' && payload.template_id === 'formal-management-brief' && payload.formalMeta"
      :payload="payload"
    />

    <template v-else>
      <div class="rr-header">
        <div class="rr-header-left">
          <div class="rr-header-brand">楼宇能耗智能管理系统</div>
          <h1 class="rr-header-title">{{ payload.title }}</h1>
          <p v-if="payload.subtitle" class="rr-header-subtitle">{{ payload.subtitle }}</p>
        </div>
        <div class="rr-header-meta">
          <span v-if="payload.buildingName" class="rr-meta-chip">{{ payload.buildingName }}</span>
          <span v-if="payload.dateRange" class="rr-meta-chip">
            {{ payload.dateRange.start }} ~ {{ payload.dateRange.end }}
          </span>
          <span class="rr-meta-time">{{ payload.generatedAt }}</span>
        </div>
      </div>

      <template v-for="section in sectionsForRender" :key="section.id">
        <div v-if="section.type === 'kpi'" class="rr-section">
          <h2 class="rr-section-title">{{ section.title }}</h2>
          <p v-if="section.description" class="rr-section-desc">{{ section.description }}</p>
          <div class="rr-kpi-grid">
            <div v-for="kpi in (section.kpis ?? [])" :key="kpi.label" class="rr-kpi-card">
              <div class="rr-kpi-value">
                {{ kpi.value }}<span v-if="kpi.unit" class="rr-kpi-unit"> {{ kpi.unit }}</span>
              </div>
              <div class="rr-kpi-label">{{ kpi.label }}</div>
            </div>
          </div>
        </div>

        <div v-else-if="section.type === 'table' && section.rows?.length" class="rr-section">
          <h2 class="rr-section-title">{{ section.title }}</h2>
          <p v-if="section.description" class="rr-section-desc">{{ section.description }}</p>
          <div class="rr-table-wrap">
            <table class="rr-table">
              <thead>
                <tr>
                  <th
                    v-for="col in (section.columns ?? [])"
                    :key="col.key"
                    :style="{ textAlign: col.align ?? 'left' }"
                  >
                    {{ col.label }}
                  </th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="(row, idx) in (section.rows ?? [])" :key="idx">
                  <td
                    v-for="col in (section.columns ?? [])"
                    :key="col.key"
                    :style="{ textAlign: col.align ?? 'left' }"
                  >
                    {{ formatCell(row[col.key]) }}
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>

        <div v-else-if="section.type === 'cards' && section.cards?.length" class="rr-section">
          <h2 class="rr-section-title">{{ section.title }}</h2>
          <p v-if="section.description" class="rr-section-desc">{{ section.description }}</p>
          <div class="rr-cards-grid">
            <article v-for="card in section.cards" :key="card.title" class="rr-building-card">
              <header class="rr-building-card-head">
                <div class="rr-building-card-title">{{ card.title }}</div>
                <div v-if="card.subtitle" class="rr-building-card-subtitle">{{ card.subtitle }}</div>
              </header>
              <div class="rr-building-card-body">
                <div v-for="metric in card.metrics" :key="`${card.title}-${metric.label}`" class="rr-building-metric">
                  <span class="rr-building-metric-label">{{ metric.label }}</span>
                  <span class="rr-building-metric-value">{{ metric.value }}</span>
                </div>
              </div>
            </article>
          </div>
        </div>

        <div v-else-if="section.type === 'chart-grid'" class="rr-section rr-section-chart-grid">
          <h2 class="rr-section-title">{{ section.title }}</h2>
          <p v-if="section.description" class="rr-section-desc">{{ section.description }}</p>
          <div class="rr-chart-grid">
            <article v-for="chart in section.charts" :key="chart.id" class="rr-chart-card">
              <header class="rr-chart-card-head">
                <h3 class="rr-chart-card-title">{{ chart.title }}</h3>
                <p v-if="chart.description" class="rr-chart-card-desc">{{ chart.description }}</p>
              </header>
              <div class="rr-chart-card-body">
                <img :src="chart.chartImage" :alt="chart.title" class="rr-chart-grid-img" />
              </div>
            </article>
          </div>
        </div>

        <div v-else-if="section.type === 'query-stats-chart-grid'" class="rr-section rr-section-chart-grid">
          <h2 class="rr-section-title">{{ section.title }}</h2>
          <p v-if="section.description" class="rr-section-desc">{{ section.description }}</p>
          <div class="rr-query-chart-grid">
            <article
              v-for="chart in section.charts"
              :key="chart.id"
              :class="['rr-query-chart-card', `rr-query-chart-card--${chart.layout}`]"
            >
              <header class="rr-query-chart-card-head">
                <h3 class="rr-query-chart-card-title">{{ chart.title }}</h3>
                <p v-if="chart.description" class="rr-query-chart-card-desc">{{ chart.description }}</p>
              </header>
              <div class="rr-query-chart-media">
                <img :src="chart.chartImage" :alt="chart.title" class="rr-query-chart-img" />
              </div>
            </article>
          </div>
        </div>

        <div v-else-if="section.type === 'chart' && section.chartImage" class="rr-section">
          <h2 class="rr-section-title">{{ section.title }}</h2>
          <p v-if="section.description" class="rr-section-desc">{{ section.description }}</p>
          <div class="rr-chart-wrap">
            <img :src="section.chartImage" :alt="section.title" class="rr-chart-img" />
          </div>
        </div>

        <div v-else-if="section.type === 'summary' && section.summaryItems?.length" class="rr-section">
          <h2 class="rr-section-title">{{ section.title }}</h2>
          <p v-if="section.description" class="rr-section-desc">{{ section.description }}</p>
          <div class="rr-summary-grid">
            <div v-for="item in (section.summaryItems ?? [])" :key="item.label" class="rr-summary-item">
              <span class="rr-summary-label">{{ item.label }}</span>
              <span class="rr-summary-value">{{ item.value }}</span>
            </div>
          </div>
        </div>

        <div v-else-if="section.type === 'insights' && section.insights?.length" class="rr-section">
          <h2 class="rr-section-title">{{ section.title }}</h2>
          <p v-if="section.description" class="rr-section-desc">{{ section.description }}</p>
          <div class="rr-finding-grid">
            <article v-for="item in section.insights" :key="`${item.tag}-${item.title}`" class="rr-finding-card">
              <div class="rr-finding-badge">{{ item.tag }}</div>
              <div class="rr-finding-content">
                <h3 class="rr-finding-title">{{ item.title }}</h3>
                <p class="rr-finding-text">{{ item.text }}</p>
              </div>
            </article>
          </div>
        </div>

        <div v-else-if="section.id === 'home-insight' && section.type === 'text' && section.content" class="rr-section rr-section-insight">
          <h2 class="rr-section-title">{{ section.title }}</h2>
          <p v-if="section.description" class="rr-section-desc">{{ section.description }}</p>
          <div class="rr-insight-grid">
            <article v-for="block in parseInsightBlocks(section.content)" :key="block.title" class="rr-insight-card">
              <header class="rr-insight-card-head">{{ block.title }}</header>
              <div class="rr-insight-body rr-markdown" v-html="renderMarkdown(block.markdown)"></div>
            </article>
          </div>
        </div>

        <div v-else-if="section.type === 'text' && section.content" class="rr-section">
          <h2 class="rr-section-title">{{ section.title }}</h2>
          <p v-if="section.contentFormat !== 'markdown'" class="rr-text-content rr-text-plain">{{ section.content }}</p>
          <div
            v-else
            class="rr-text-content rr-markdown"
            v-html="renderMarkdown(section.content)"
          ></div>
        </div>

        <div v-else-if="section.type === 'artifact' && section.artifact" class="rr-section">
          <h2 class="rr-section-title">{{ section.title }}</h2>
          <p v-if="section.description" class="rr-section-desc">{{ section.description }}</p>
          <div class="rr-artifact-wrap">
            <DynamicChart
              v-if="isChartArtifact(section.artifact)"
              :artifact="section.artifact"
              :report-mode="true"
            />
            <WorkOrderCard
              v-else-if="isWorkOrderArtifact(section.artifact)"
              :artifact="section.artifact"
              :readonly="true"
            />
            <ReportDownload
              v-else-if="isReportDownloadArtifact(section.artifact)"
              :artifact="section.artifact"
              :readonly="true"
            />
            <pre v-else class="rr-artifact-fallback">{{ JSON.stringify(section.artifact, null, 2) }}</pre>
          </div>
        </div>
      </template>

      <div class="rr-footer">
        <span>楼宇能耗智能管理系统 · 自动生成报表</span>
        <span v-if="payload.mode === 'formal'">内部文件 · 请妥善保管</span>
      </div>
    </template>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import type { ReportPayload, ReportSection } from '@/stores/reportStore'
import type { ArtifactEvent } from '@/api/stream_client'
import DynamicChart from '@/generative-ui/DynamicChart.vue'
import WorkOrderCard from '@/generative-ui/WorkOrderCard.vue'
import ReportDownload from '@/generative-ui/ReportDownload.vue'
import FormalManagementBrief from './FormalManagementBrief.vue'
import { renderMarkdown } from '@/utils/markdown'

interface ChartGridSection {
  id: string
  type: 'chart-grid'
  title: string
  description?: string
  charts: ReportSection[]
}

interface QueryStatsChartItem extends ReportSection {
  layout: 'featured' | 'standard' | 'wide'
  chartImage: string
}

interface QueryStatsChartGridSection {
  id: string
  type: 'query-stats-chart-grid'
  title: string
  description?: string
  charts: QueryStatsChartItem[]
}

type RenderSection = ReportSection | ChartGridSection | QueryStatsChartGridSection

const props = defineProps<{ payload: ReportPayload }>()
const homeChartOrder = ['home-chart-radar', 'home-chart-hvac', 'home-chart-compare', 'home-chart-sankey'] as const
const queryStatsChartOrder = ['qs-chart-energy', 'qs-chart-cop', 'qs-chart-device', 'qs-chart-temperature'] as const

const sectionsForRender = computed<RenderSection[]>(() => {
  const sections = props.payload.sections ?? []
  if (isQueryStatsPayload()) return buildQueryStatsSections(sections)
  if (!isHomeOverviewPayload()) return sections

  return buildHomeSections(sections)
})

function buildHomeSections(sections: ReportSection[]): RenderSection[] {
  const chartMap = new Map(sections.map(section => [section.id, section]))
  const homeCharts = homeChartOrder
    .map(id => chartMap.get(id))
    .filter((section): section is ReportSection => !!section && section.type === 'chart' && !!section.chartImage)

  if (homeCharts.length < 2) return sections

  const consumed = new Set(homeCharts.map(section => section.id))
  const output: RenderSection[] = []
  let inserted = false

  for (const section of sections) {
    if (consumed.has(section.id)) {
      if (!inserted) {
        output.push({
          id: 'home-chart-grid',
          type: 'chart-grid',
          title: '核心图表',
          description: '按概览对比、HVAC 运行、能耗结构、异常根因四个维度压缩展示首页核心图表。',
          charts: homeCharts,
        })
        inserted = true
      }
      continue
    }
    output.push(section)
  }

  return output
}

function buildQueryStatsSections(sections: ReportSection[]): RenderSection[] {
  const chartMap = new Map(sections.map(section => [section.id, section]))
  const queryCharts = queryStatsChartOrder
    .map(id => chartMap.get(id))
    .filter((section): section is ReportSection => !!section && section.type === 'chart' && !!section.chartImage)
    .map((section): QueryStatsChartItem => ({
      ...section,
      chartImage: section.chartImage!,
      layout: resolveQueryStatsChartLayout(section.id),
    }))

  if (queryCharts.length < 2) return sections

  const consumed = new Set(queryCharts.map(section => section.id))
  const output: RenderSection[] = []
  let inserted = false

  for (const section of sections) {
    if (consumed.has(section.id)) {
      if (!inserted) {
        output.push({
          id: 'query-stats-chart-grid',
          type: 'query-stats-chart-grid',
          title: '核心分析图表',
          description: '能耗总览与 COP 并排展示，环境与温度固定放在最后，仅保留固定组件间距。',
          charts: queryCharts,
        })
        inserted = true
      }
      continue
    }
    output.push(section)
  }

  return output
}

function formatCell(v: unknown): string {
  if (v == null || v === '') return '--'
  const n = Number(v)
  if (!Number.isNaN(n) && typeof v !== 'boolean' && String(v).trim() !== '') {
    return n % 1 === 0 ? String(n) : n.toFixed(2)
  }
  return String(v)
}

function isChartArtifact(artifact?: ArtifactEvent): boolean {
  if (!artifact) return false
  const type = artifact.component_type ?? artifact.widget ?? ''
  return ['LineChart', 'BarChart', 'Gauge', 'line-chart', 'bar-chart', 'gauge'].includes(type)
}

function isWorkOrderArtifact(artifact?: ArtifactEvent): boolean {
  if (!artifact) return false
  const type = artifact.component_type ?? artifact.widget ?? ''
  return ['WorkOrderCard', 'work-order-card'].includes(type)
}

function isReportDownloadArtifact(artifact?: ArtifactEvent): boolean {
  if (!artifact) return false
  const type = artifact.component_type ?? artifact.widget ?? ''
  return ['ReportDownload', 'report-download'].includes(type)
}

function isHomeOverviewPayload(): boolean {
  return props.payload.title.includes('首页')
}

function isQueryStatsPayload(): boolean {
  return props.payload.sections.some(section => section.id.startsWith('qs-'))
    || props.payload.title.includes('查询统计')
}

function resolveQueryStatsChartLayout(sectionId: string): QueryStatsChartItem['layout'] {
  if (sectionId === 'qs-chart-device') return 'wide'
  if (sectionId === 'qs-chart-temperature') return 'wide'
  return 'standard'
}

function parseInsightBlocks(content?: string): Array<{ title: string; markdown: string }> {
  if (!content) return []

  const blocks: Array<{ title: string; lines: string[] }> = []
  let current: { title: string; lines: string[] } | null = null

  for (const rawLine of content.split('\n')) {
    const trimmed = rawLine.trim()
    if (trimmed.startsWith('### ')) {
      current = { title: trimmed.slice(4).trim(), lines: [] }
      blocks.push(current)
      continue
    }
    if (!current) {
      current = { title: '洞察摘要', lines: [] }
      blocks.push(current)
    }
    current.lines.push(rawLine)
  }

  return blocks
    .map(block => ({
      title: block.title,
      markdown: block.lines.join('\n').trim(),
    }))
    .filter(block => !!block.markdown)
}
</script>

<style scoped>
.rr-doc {
  background: #ffffff;
  color: #1a1f2e;
  font-family: 'PingFang SC', 'Microsoft YaHei', 'Noto Sans SC', sans-serif;
  font-size: 13px;
  line-height: 1.6;
  padding: 28px 36px 24px;
  min-width: 600px;
}

.rr-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  padding-bottom: 16px;
  margin-bottom: 24px;
  border-bottom: 2px solid #1a3a6b;
  gap: 16px;
}

.rr-header-brand {
  font-size: 11px;
  color: #1a3a6b;
  font-weight: 600;
  letter-spacing: 0.06em;
  text-transform: uppercase;
  margin-bottom: 4px;
}

.rr-header-title {
  font-size: 20px;
  font-weight: 700;
  color: #0d1b2a;
  margin: 0;
}

.rr-header-subtitle {
  font-size: 12px;
  color: #5a6478;
  margin-top: 4px;
}

.rr-header-meta {
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  gap: 4px;
}

.rr-meta-chip {
  background: #eef2fa;
  color: #1a3a6b;
  font-size: 11px;
  font-weight: 600;
  padding: 3px 10px;
  border-radius: 20px;
}

.rr-meta-time {
  font-size: 11px;
  color: #8c939a;
}

.rr-section {
  margin-bottom: 28px;
  page-break-inside: avoid;
}

.rr-section-title {
  font-size: 14px;
  font-weight: 700;
  color: #0d1b2a;
  border-left: 3px solid #1a3a6b;
  padding-left: 10px;
  margin-bottom: 12px;
}

.rr-section-desc {
  font-size: 13px;
  color: #475569;
  margin-bottom: 14px;
  line-height: 1.7;
}

.rr-kpi-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(140px, 1fr));
  gap: 12px;
}

.rr-kpi-card,
.rr-summary-item {
  border: 1px solid #e2e8f0;
  border-radius: 12px;
  padding: 14px 16px;
  background: #f8fafc;
}

.rr-kpi-value {
  font-size: 22px;
  font-weight: 700;
  color: #0f172a;
}

.rr-kpi-unit,
.rr-kpi-label,
.rr-summary-label {
  color: #64748b;
  font-size: 12px;
}

.rr-kpi-label {
  margin-top: 8px;
}

.rr-table-wrap,
.rr-chart-wrap,
.rr-artifact-wrap {
  border: 1px solid #e2e8f0;
  border-radius: 12px;
  overflow: hidden;
  background: #fff;
}

.rr-table {
  width: 100%;
  border-collapse: collapse;
}

.rr-table th,
.rr-table td {
  padding: 10px 12px;
  border-bottom: 1px solid #e2e8f0;
  font-size: 12px;
}

.rr-table th {
  background: #f8fafc;
  color: #334155;
  font-weight: 600;
}

.rr-table tr:last-child td {
  border-bottom: none;
}

.rr-cards-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
  gap: 14px;
}

.rr-building-card {
  border: 1px solid #d8e1ec;
  border-radius: 16px;
  overflow: hidden;
  background:
    linear-gradient(180deg, rgba(245, 248, 252, 0.95) 0%, rgba(255, 255, 255, 1) 100%);
  box-shadow: 0 12px 28px rgba(15, 23, 42, 0.06);
}

.rr-building-card-head {
  padding: 16px 18px 12px;
  background: linear-gradient(135deg, #eef4fb 0%, #f8fafc 100%);
  border-bottom: 1px solid #e4ebf3;
}

.rr-building-card-title {
  font-size: 16px;
  font-weight: 700;
  color: #0f2742;
}

.rr-building-card-subtitle {
  margin-top: 4px;
  font-size: 11px;
  color: #64748b;
}

.rr-building-card-body {
  padding: 14px 18px 16px;
  display: grid;
  gap: 10px;
}

.rr-building-metric {
  display: flex;
  justify-content: space-between;
  align-items: baseline;
  gap: 12px;
  padding-bottom: 8px;
  border-bottom: 1px dashed #e2e8f0;
}

.rr-building-metric:last-child {
  padding-bottom: 0;
  border-bottom: none;
}

.rr-building-metric-label {
  font-size: 12px;
  color: #64748b;
}

.rr-building-metric-value {
  font-size: 14px;
  font-weight: 700;
  color: #0f172a;
}

.rr-chart-img {
  display: block;
  width: 100%;
  height: auto;
}

.rr-section-chart-grid {
  margin-bottom: 30px;
}

.rr-chart-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 16px;
}

.rr-query-chart-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 16px;
}

.rr-chart-card {
  border: 1px solid #dbe5ef;
  border-radius: 16px;
  overflow: hidden;
  background: linear-gradient(180deg, #f8fbff 0%, #ffffff 100%);
  box-shadow: 0 10px 24px rgba(15, 23, 42, 0.05);
}

.rr-chart-card-head {
  padding: 14px 16px 10px;
  border-bottom: 1px solid #e6edf5;
  background: linear-gradient(135deg, rgba(238, 244, 251, 0.95) 0%, rgba(248, 250, 252, 0.98) 100%);
}

.rr-chart-card-title {
  margin: 0;
  font-size: 14px;
  font-weight: 700;
  color: #12263f;
}

.rr-chart-card-desc {
  margin: 6px 0 0;
  font-size: 11px;
  line-height: 1.6;
  color: #64748b;
}

.rr-chart-card-body {
  padding: 10px 12px 12px;
  background: #fff;
}

.rr-chart-grid-img {
  display: block;
  width: 100%;
  border-radius: 12px;
  background: #fff;
}

.rr-query-chart-card {
  border: 1px solid #dbe5ef;
  border-radius: 16px;
  overflow: hidden;
  background: linear-gradient(180deg, #fbfdff 0%, #ffffff 100%);
  box-shadow: 0 12px 28px rgba(15, 23, 42, 0.05);
}

.rr-query-chart-card--wide {
  grid-column: 1 / -1;
}

.rr-query-chart-card-head {
  padding: 14px 16px 10px;
  border-bottom: 1px solid #e6edf5;
  background: linear-gradient(135deg, rgba(239, 246, 255, 0.96) 0%, rgba(248, 250, 252, 0.98) 100%);
}

.rr-query-chart-card-title {
  margin: 0;
  font-size: 14px;
  font-weight: 700;
  color: #0f2742;
}

.rr-query-chart-card-desc {
  margin: 6px 0 0;
  font-size: 11px;
  line-height: 1.6;
  color: #64748b;
}

.rr-query-chart-media {
  padding: 10px 10px 12px;
  background: #fff;
}

.rr-query-chart-img {
  display: block;
  width: 100%;
  height: auto;
  border-radius: 0 0 10px 10px;
  background: #fff;
}

.rr-summary-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
  gap: 12px;
}

.rr-summary-item {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.rr-finding-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 14px;
}

.rr-finding-card {
  display: flex;
  gap: 12px;
  align-items: flex-start;
  padding: 16px 18px;
  border-radius: 16px;
  border: 1px solid #dbe6f0;
  background: linear-gradient(180deg, #fbfdff 0%, #f8fbff 100%);
  box-shadow: 0 10px 22px rgba(15, 23, 42, 0.05);
}

.rr-finding-badge {
  min-width: 48px;
  height: 24px;
  padding: 0 8px;
  border-radius: 999px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  background: #e8f0ff;
  color: #1d4ed8;
  font-size: 12px;
  font-weight: 700;
  flex-shrink: 0;
}

.rr-finding-content {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.rr-finding-title {
  margin: 0;
  font-size: 14px;
  font-weight: 700;
  color: #102a43;
}

.rr-finding-text {
  margin: 0;
  font-size: 12px;
  line-height: 1.8;
  color: #475569;
}

.rr-summary-value {
  font-size: 18px;
  font-weight: 700;
  color: #0f172a;
}

.rr-text-content {
  color: #334155;
  font-size: 13px;
  line-height: 1.8;
}

.rr-section-insight {
  margin-top: 6px;
}

.rr-insight-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 14px;
}

.rr-insight-card {
  border: 1px solid #dbe6f0;
  border-radius: 16px;
  background: linear-gradient(180deg, #f8fbff 0%, #ffffff 100%);
  box-shadow: 0 10px 22px rgba(15, 23, 42, 0.05);
  overflow: hidden;
}

.rr-insight-card-head {
  padding: 14px 16px 12px;
  font-size: 13px;
  font-weight: 700;
  color: #102a43;
  border-bottom: 1px solid #e6edf5;
  background: linear-gradient(135deg, #eff6ff 0%, #f8fafc 100%);
}

.rr-insight-body {
  padding: 14px 18px 16px;
}

.rr-insight-body :deep(p),
.rr-insight-body :deep(ul),
.rr-insight-body :deep(ol) {
  margin: 0 0 10px;
}

.rr-insight-body :deep(ul),
.rr-insight-body :deep(ol) {
  padding-left: 20px;
}

.rr-insight-body :deep(li),
.rr-insight-body :deep(p) {
  color: #334155;
  font-size: 12px;
  line-height: 1.8;
}

.rr-insight-body :deep(strong) {
  color: #0f172a;
}

.rr-markdown :deep(p),
.rr-markdown :deep(ul),
.rr-markdown :deep(ol) {
  margin: 0 0 10px;
}

.rr-markdown :deep(ul),
.rr-markdown :deep(ol) {
  padding-left: 20px;
}

.rr-artifact-fallback {
  margin: 0;
  padding: 14px;
  white-space: pre-wrap;
  font-size: 11px;
  color: #334155;
}

.rr-footer {
  display: flex;
  justify-content: space-between;
  gap: 16px;
  padding-top: 12px;
  border-top: 1px solid #e2e8f0;
  color: #94a3b8;
  font-size: 11px;
}

@media (max-width: 900px) {
  .rr-doc {
    padding: 20px;
    min-width: 0;
  }

  .rr-header,
  .rr-footer {
    flex-direction: column;
  }

  .rr-header-meta {
    align-items: flex-start;
  }

  .rr-chart-grid,
  .rr-query-chart-grid,
  .rr-finding-grid,
  .rr-insight-grid {
    grid-template-columns: 1fr;
  }
}
</style>
