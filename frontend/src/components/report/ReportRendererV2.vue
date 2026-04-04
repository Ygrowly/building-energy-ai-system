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

      <template v-for="section in payload.sections" :key="section.id">
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
import type { ReportPayload } from '@/stores/reportStore'
import type { ArtifactEvent } from '@/api/stream_client'
import DynamicChart from '@/generative-ui/DynamicChart.vue'
import WorkOrderCard from '@/generative-ui/WorkOrderCard.vue'
import ReportDownload from '@/generative-ui/ReportDownload.vue'
import FormalManagementBrief from './FormalManagementBrief.vue'
import { renderMarkdown } from '@/utils/markdown'

defineProps<{ payload: ReportPayload }>()

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

.rr-chart-img {
  display: block;
  width: 100%;
  height: auto;
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
}
</style>
