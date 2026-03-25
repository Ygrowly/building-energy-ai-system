<template>
  <div class="rr-doc" :class="{ 'rr-formal': payload.mode === 'formal' }">
    <!-- 封面（正式模式） -->
    <div v-if="payload.mode === 'formal'" class="rr-cover">
      <div class="rr-cover-logo">
        <div class="rr-cover-logo-icon">E</div>
        <span class="rr-cover-logo-text">楼宇能耗智能管理系统</span>
      </div>
      <div class="rr-cover-main">
        <h1 class="rr-cover-title">{{ payload.title }}</h1>
        <p v-if="payload.subtitle" class="rr-cover-subtitle">{{ payload.subtitle }}</p>
      </div>
      <div class="rr-cover-meta">
        <div class="rr-cover-meta-item" v-if="payload.buildingName">
          <span class="rr-cover-meta-label">楼宇</span>
          <span class="rr-cover-meta-val">{{ payload.buildingName }}</span>
        </div>
        <div class="rr-cover-meta-item" v-if="payload.dateRange">
          <span class="rr-cover-meta-label">数据范围</span>
          <span class="rr-cover-meta-val">{{ payload.dateRange.start }} ~ {{ payload.dateRange.end }}</span>
        </div>
        <div class="rr-cover-meta-item">
          <span class="rr-cover-meta-label">生成时间</span>
          <span class="rr-cover-meta-val">{{ payload.generatedAt }}</span>
        </div>
        <div class="rr-cover-meta-item" v-if="payload.generatedBy">
          <span class="rr-cover-meta-label">生成人</span>
          <span class="rr-cover-meta-val">{{ payload.generatedBy }}</span>
        </div>
      </div>
      <div class="rr-cover-divider"></div>
    </div>

    <!-- 快照模式页眉 -->
    <div v-else class="rr-header">
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
        <span class="rr-meta-time">生成于 {{ payload.generatedAt }}</span>
      </div>
    </div>

    <!-- 内容段落 -->
    <template v-for="section in payload.sections" :key="section.id">
      <!-- KPI 卡片组 -->
      <div v-if="section.type === 'kpi'" class="rr-section">
        <h2 class="rr-section-title">{{ section.title }}</h2>
        <p v-if="section.description" class="rr-section-desc">{{ section.description }}</p>
        <div class="rr-kpi-grid">
          <div
            v-for="kpi in (section.kpis ?? [])"
            :key="kpi.label"
            class="rr-kpi-card"
          >
            <div class="rr-kpi-value">{{ kpi.value }}<span v-if="kpi.unit" class="rr-kpi-unit"> {{ kpi.unit }}</span></div>
            <div class="rr-kpi-label">{{ kpi.label }}</div>
            <div
              v-if="kpi.trend != null"
              class="rr-kpi-trend"
              :class="kpi.trend >= 0 ? 'up' : 'down'"
            >{{ kpi.trend >= 0 ? '▲' : '▼' }} {{ Math.abs(kpi.trend).toFixed(1) }}%</div>
          </div>
        </div>
      </div>

      <!-- 数据表格 -->
      <div v-else-if="section.type === 'table' && section.rows && section.rows.length" class="rr-section">
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
                >{{ col.label }}</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="(row, idx) in (section.rows ?? [])" :key="idx">
                <td
                  v-for="col in (section.columns ?? [])"
                  :key="col.key"
                  :style="{ textAlign: col.align ?? 'left' }"
                >{{ formatCell(row[col.key]) }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>

      <!-- 图表截图 -->
      <div v-else-if="section.type === 'chart' && section.chartImage" class="rr-section">
        <h2 class="rr-section-title">{{ section.title }}</h2>
        <p v-if="section.description" class="rr-section-desc">{{ section.description }}</p>
        <div class="rr-chart-wrap">
          <img :src="section.chartImage" :alt="section.title" class="rr-chart-img" />
        </div>
      </div>

      <!-- 统计摘要 -->
      <div v-else-if="section.type === 'summary' && section.summaryItems?.length" class="rr-section">
        <h2 class="rr-section-title">{{ section.title }}</h2>
        <p v-if="section.description" class="rr-section-desc">{{ section.description }}</p>
        <div class="rr-summary-grid">
          <div
            v-for="item in (section.summaryItems ?? [])"
            :key="item.label"
            class="rr-summary-item"
          >
            <span class="rr-summary-label">{{ item.label }}</span>
            <span class="rr-summary-value">{{ item.value }}</span>
          </div>
        </div>
      </div>

      <!-- 说明文本 -->
      <div v-else-if="section.type === 'text' && section.content" class="rr-section">
        <h2 class="rr-section-title">{{ section.title }}</h2>
        <p class="rr-text-content">{{ section.content }}</p>
      </div>
    </template>

    <!-- 页脚 -->
    <div class="rr-footer">
      <span>楼宇能耗智能管理系统 · 自动生成报表</span>
      <span v-if="payload.mode === 'formal'" class="rr-footer-page">内部文件 · 请妥善保管</span>
    </div>
  </div>
</template>

<script setup lang="ts">
import type { ReportPayload } from '@/stores/reportStore'

const props = defineProps<{ payload: ReportPayload }>()

function formatCell(v: any): string {
  if (v == null || v === '') return '—'
  const n = Number(v)
  if (!isNaN(n) && typeof v !== 'boolean' && String(v).trim() !== '') {
    return n % 1 === 0 ? String(n) : n.toFixed(2)
  }
  return String(v)
}
</script>

<style scoped>
/* ── 整体文档 ───────────────────────────────────────────────── */
.rr-doc {
  background: #ffffff;
  color: #1a1f2e;
  font-family: 'PingFang SC', 'Microsoft YaHei', 'Noto Sans SC', sans-serif;
  font-size: 13px;
  line-height: 1.6;
  padding: 32px 40px 24px;
  min-width: 600px;
}

/* ── 封面（正式模式） ──────────────────────────────────────── */
.rr-cover {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  min-height: 280px;
  padding: 40px 0 32px;
  margin-bottom: 32px;
  border-bottom: 2px solid #1a3a6b;
}

.rr-cover-logo {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 32px;
}
.rr-cover-logo-icon {
  width: 36px; height: 36px;
  background: #1a3a6b;
  color: #fff;
  border-radius: 8px;
  display: flex; align-items: center; justify-content: center;
  font-weight: 700; font-size: 18px;
}
.rr-cover-logo-text {
  font-size: 15px;
  font-weight: 600;
  color: #1a3a6b;
  letter-spacing: 0.05em;
}
.rr-cover-main { text-align: center; margin-bottom: 28px; }
.rr-cover-title {
  font-size: 26px;
  font-weight: 700;
  color: #0d1b2a;
  letter-spacing: 0.04em;
  margin-bottom: 6px;
}
.rr-cover-subtitle { color: #5a6478; font-size: 14px; }

.rr-cover-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 20px;
  justify-content: center;
}
.rr-cover-meta-item { display: flex; flex-direction: column; align-items: center; gap: 2px; }
.rr-cover-meta-label { font-size: 11px; color: #8c939a; text-transform: uppercase; letter-spacing: 0.06em; }
.rr-cover-meta-val { font-size: 13px; font-weight: 600; color: #1a1f2e; }
.rr-cover-divider { display: none; }

/* ── 快照页眉 ──────────────────────────────────────────────── */
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
  letter-spacing: 0.02em;
}
.rr-header-subtitle { font-size: 12px; color: #5a6478; margin-top: 2px; }
.rr-header-meta {
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  gap: 4px;
  flex-shrink: 0;
}
.rr-meta-chip {
  background: #eef2fa;
  color: #1a3a6b;
  font-size: 11px;
  font-weight: 600;
  padding: 3px 10px;
  border-radius: 20px;
}
.rr-meta-time { font-size: 11px; color: #8c939a; }

/* ── 段落通用 ──────────────────────────────────────────────── */
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
  font-size: 12px;
  color: #5a6478;
  margin-bottom: 10px;
}

/* ── KPI 卡片 ──────────────────────────────────────────────── */
.rr-kpi-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(140px, 1fr));
  gap: 12px;
}
.rr-kpi-card {
  background: #f7f9fc;
  border: 1px solid #e4eaf5;
  border-radius: 8px;
  padding: 14px 16px;
  text-align: center;
}
.rr-kpi-value {
  font-size: 22px;
  font-weight: 700;
  color: #1a3a6b;
  line-height: 1.2;
}
.rr-kpi-unit { font-size: 12px; font-weight: 400; color: #8c939a; }
.rr-kpi-label { font-size: 11px; color: #5a6478; margin-top: 4px; }
.rr-kpi-trend { font-size: 11px; font-weight: 600; margin-top: 4px; }
.rr-kpi-trend.up { color: #e05555; }
.rr-kpi-trend.down { color: #22aa6b; }

/* ── 表格 ──────────────────────────────────────────────────── */
.rr-table-wrap { overflow-x: auto; }
.rr-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 12px;
}
.rr-table thead th {
  background: #1a3a6b;
  color: #ffffff;
  padding: 8px 12px;
  font-weight: 600;
  font-size: 11px;
  letter-spacing: 0.03em;
  white-space: nowrap;
}
.rr-table tbody tr:nth-child(even) { background: #f7f9fc; }
.rr-table tbody td {
  padding: 7px 12px;
  border-bottom: 1px solid #eaedf2;
  color: #2d3239;
  white-space: nowrap;
}
.rr-table tbody tr:last-child td { border-bottom: none; }

/* ── 图表 ──────────────────────────────────────────────────── */
.rr-chart-wrap {
  border: 1px solid #eaedf2;
  border-radius: 6px;
  overflow: hidden;
  background: #fafbfc;
  padding: 8px;
}
.rr-chart-img {
  width: 100%;
  height: auto;
  display: block;
}

/* ── 统计摘要 ──────────────────────────────────────────────── */
.rr-summary-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
  gap: 8px;
}
.rr-summary-item {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 8px 12px;
  background: #f7f9fc;
  border-radius: 6px;
  border: 1px solid #eaedf2;
}
.rr-summary-label { font-size: 12px; color: #5a6478; }
.rr-summary-value { font-size: 13px; font-weight: 600; color: #1a3a6b; }

/* ── 说明文本 ──────────────────────────────────────────────── */
.rr-text-content {
  font-size: 12px;
  color: #3d4451;
  line-height: 1.8;
  background: #f7f9fc;
  border-left: 3px solid #c8d5ee;
  padding: 10px 14px;
  border-radius: 0 6px 6px 0;
}

/* ── 页脚 ──────────────────────────────────────────────────── */
.rr-footer {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-top: 32px;
  padding-top: 12px;
  border-top: 1px solid #eaedf2;
  font-size: 11px;
  color: #a0a8b8;
}

/* ── 打印优化 ──────────────────────────────────────────────── */
@media print {
  .rr-doc { padding: 0; }
  .rr-section { page-break-inside: avoid; }
  .rr-cover { page-break-after: always; }
  .rr-table-wrap { overflow: visible; }
}
</style>
