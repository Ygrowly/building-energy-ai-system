<template>
  <Teleport to="body">
    <Transition name="rp-fade">
      <div v-if="reportStore.previewVisible" class="rp-overlay" @click.self="reportStore.closePreview()">
        <div class="rp-modal">
          <div class="rp-toolbar">
            <div class="rp-toolbar-left">
              <span class="rp-toolbar-title">
                <Icon icon="mdi:file-chart-outline" width="16" class="rp-toolbar-icon" />
                {{ resolvedPayload?.title ?? '报表预览' }}
              </span>
            </div>
            <div class="rp-toolbar-right">
              <button
                v-if="isQueryStatsReport"
                class="rp-action-btn"
                type="button"
                @click="showExportOptions = true"
              >
                <Icon icon="mdi:tune-variant" width="15" />
                导出设置
              </button>
              <button class="rp-action-btn" @click="onPrint" title="打印">
                <Icon icon="mdi:printer-outline" width="15" />
                打印
              </button>
              <button class="rp-action-btn" :disabled="exporting" @click="onExportHTML" title="导出 HTML">
                <Icon icon="mdi:code-tags" width="15" />
                HTML
              </button>
              <button class="rp-action-btn primary" :disabled="exporting" @click="onExportPDF" title="导出 PDF">
                <Icon v-if="!exporting" icon="mdi:file-pdf-box" width="15" />
                <Icon v-else icon="mdi:loading" width="15" class="spin" />
                {{ exporting ? '生成中...' : 'PDF' }}
              </button>
              <button class="rp-close-btn" @click="reportStore.closePreview()" title="关闭">
                <Icon icon="mdi:close" width="18" />
              </button>
            </div>
          </div>

          <div class="rp-body">
            <div class="rp-paper" ref="paperEl">
              <ReportRenderer
                v-if="resolvedPayload"
                :payload="resolvedPayload"
              />
              <div v-else class="rp-empty">
                <Icon icon="mdi:file-chart-outline" width="40" class="rp-empty-icon" />
                <p>暂无报表数据</p>
              </div>
            </div>
          </div>

          <Transition name="rp-options-fade">
            <div v-if="showExportOptions" class="rp-options-backdrop">
              <div class="rp-options-dialog">
                <div class="rp-options-head">
                  <div class="rp-options-title">查询统计导出设置</div>
                  <div class="rp-options-subtitle">决定是否附带能耗数据明细。若包含，明细表会自动移动到报表末尾。</div>
                </div>

                <label class="rp-option-card">
                  <input v-model="includeEnergyDetail" type="checkbox" />
                  <span class="rp-option-check">
                    <Icon v-if="includeEnergyDetail" icon="mdi:check" width="14" />
                  </span>
                  <span class="rp-option-copy">
                    <span class="rp-option-label">包含能耗数据明细</span>
                    <span class="rp-option-desc">取消勾选后，报表将不再展示“能耗数据明细”模块。</span>
                  </span>
                </label>

                <div class="rp-options-actions">
                  <button type="button" class="rp-options-btn ghost" @click="reportStore.closePreview()">
                    取消
                  </button>
                  <button type="button" class="rp-options-btn primary" @click="showExportOptions = false">
                    继续预览
                  </button>
                </div>
              </div>
            </div>
          </Transition>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { Icon } from '@iconify/vue'
import type { ReportPayload, ReportSection } from '@/stores/reportStore'
import { useReportStore } from '@/stores/reportStore'
import ReportRenderer from './ReportRendererV2.vue'
import { exportToPDF, exportToHTML, buildReportFilename } from '@/utils/reportExportEngine'

const QUERY_STATS_DETAIL_SECTION_ID = 'qs-energy-table'

const reportStore = useReportStore()
const paperEl = ref<HTMLElement | null>(null)
const exporting = ref(false)
const showExportOptions = ref(false)
const includeEnergyDetail = ref(true)

const isQueryStatsReport = computed(() => {
  const payload = reportStore.previewPayload
  return payload?.sections?.some(section => section.id.startsWith('qs-')) ?? false
})

const resolvedPayload = computed<ReportPayload | null>(() => {
  const payload = reportStore.previewPayload
  if (!payload) return null
  if (!isQueryStatsReport.value) return payload

  return {
    ...payload,
    sections: buildQueryStatsSections(payload.sections, includeEnergyDetail.value),
  }
})

watch(
  () => reportStore.previewVisible,
  (visible) => {
    includeEnergyDetail.value = true
    showExportOptions.value = visible && isQueryStatsReport.value
  },
  { immediate: true },
)

function buildQueryStatsSections(sections: ReportSection[], includeDetail: boolean) {
  const detailSection = sections.find(section => section.id === QUERY_STATS_DETAIL_SECTION_ID)
  const baseSections = sections.filter(section => section.id !== QUERY_STATS_DETAIL_SECTION_ID)

  if (!includeDetail || !detailSection) return baseSections
  return [...baseSections, { ...detailSection, order: Math.max(detailSection.order ?? 100, 999) }]
}

function getFilename(): string {
  const payload = resolvedPayload.value
  return buildReportFilename(payload?.title ?? '报表', payload?.buildingName)
}

async function onExportPDF() {
  if (!paperEl.value || showExportOptions.value) return
  exporting.value = true
  try {
    await exportToPDF(paperEl.value, getFilename())
  } finally {
    exporting.value = false
  }
}

function onExportHTML() {
  if (!paperEl.value || showExportOptions.value) return
  exportToHTML(paperEl.value, getFilename())
}

function onPrint() {
  if (showExportOptions.value) return
  window.print()
}
</script>

<style scoped>
.rp-overlay {
  position: fixed;
  inset: 0;
  background: rgba(10, 14, 24, 0.72);
  z-index: 2000;
  display: flex;
  align-items: flex-start;
  justify-content: center;
  padding: 20px;
  overflow-y: auto;
  backdrop-filter: blur(3px);
}

.rp-modal {
  position: relative;
  width: 100%;
  max-width: 960px;
  background: #1a1f2e;
  border-radius: 12px;
  border: 1px solid rgba(255, 255, 255, 0.08);
  box-shadow: 0 24px 80px rgba(0, 0, 0, 0.5);
  display: flex;
  flex-direction: column;
  min-height: 400px;
  overflow: hidden;
}

.rp-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 16px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.08);
  background: #141824;
  gap: 12px;
  flex-shrink: 0;
}

.rp-toolbar-left {
  display: flex;
  align-items: center;
  gap: 14px;
  min-width: 0;
}

.rp-toolbar-icon {
  color: var(--accent, #5b8dee);
}

.rp-toolbar-title {
  font-size: 13px;
  font-weight: 600;
  color: #e2e8f0;
  display: flex;
  align-items: center;
  gap: 6px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.rp-toolbar-right {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-shrink: 0;
}

.rp-action-btn {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 6px 12px;
  font-size: 12px;
  font-weight: 500;
  border: 1px solid rgba(255, 255, 255, 0.12);
  border-radius: 6px;
  background: rgba(255, 255, 255, 0.06);
  color: #c8d0de;
  cursor: pointer;
  transition: background 0.15s, color 0.15s;
}

.rp-action-btn:hover:not(:disabled) {
  background: rgba(255, 255, 255, 0.12);
  color: #e2e8f0;
}

.rp-action-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.rp-action-btn.primary {
  background: var(--accent, #5b8dee);
  border-color: var(--accent, #5b8dee);
  color: #fff;
}

.rp-action-btn.primary:hover:not(:disabled) {
  opacity: 0.9;
}

.rp-close-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 30px;
  height: 30px;
  border: none;
  border-radius: 6px;
  background: transparent;
  color: #8c939a;
  cursor: pointer;
  transition: background 0.15s, color 0.15s;
}

.rp-close-btn:hover {
  background: rgba(255, 255, 255, 0.08);
  color: #e2e8f0;
}

.rp-body {
  flex: 1;
  overflow-y: auto;
  padding: 24px;
  background: #f0f2f7;
}

.rp-paper {
  background: #ffffff;
  border-radius: 4px;
  box-shadow: 0 2px 20px rgba(0, 0, 0, 0.15);
  min-height: 400px;
  overflow: hidden;
}

.rp-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 80px 20px;
  color: #8c939a;
  gap: 12px;
}

.rp-empty-icon {
  color: #c8d0de;
}

.rp-options-backdrop {
  position: fixed;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 24px;
  background: rgba(9, 13, 22, 0.48);
  backdrop-filter: blur(4px);
  z-index: 2100;
}

.rp-options-dialog {
  width: min(480px, 100%);
  border-radius: 18px;
  background: linear-gradient(180deg, #ffffff 0%, #f8fafc 100%);
  box-shadow: 0 24px 64px rgba(15, 23, 42, 0.24);
  overflow: hidden;
}

.rp-options-head {
  padding: 22px 24px 14px;
}

.rp-options-title {
  font-size: 18px;
  font-weight: 700;
  color: #0f172a;
}

.rp-options-subtitle {
  margin-top: 8px;
  font-size: 13px;
  line-height: 1.7;
  color: #475569;
}

.rp-option-card {
  display: flex;
  gap: 14px;
  align-items: flex-start;
  margin: 0 24px;
  padding: 18px;
  border-radius: 16px;
  border: 1px solid #dbe5ef;
  background: #fff;
  cursor: pointer;
}

.rp-option-card input {
  display: none;
}

.rp-option-check {
  width: 20px;
  height: 20px;
  border-radius: 6px;
  border: 1.5px solid #c8d4e0;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  color: #fff;
  background: #fff;
  flex-shrink: 0;
  margin-top: 1px;
}

.rp-option-card input:checked + .rp-option-check {
  background: #2563eb;
  border-color: #2563eb;
}

.rp-option-copy {
  display: flex;
  flex-direction: column;
  gap: 5px;
}

.rp-option-label {
  font-size: 15px;
  font-weight: 700;
  color: #0f172a;
}

.rp-option-desc {
  font-size: 12px;
  line-height: 1.7;
  color: #64748b;
}

.rp-options-actions {
  display: flex;
  justify-content: flex-end;
  gap: 10px;
  padding: 18px 24px 24px;
}

.rp-options-btn {
  min-width: 96px;
  height: 38px;
  border-radius: 10px;
  border: 1px solid transparent;
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
}

.rp-options-btn.ghost {
  background: #f8fafc;
  border-color: #dbe5ef;
  color: #334155;
}

.rp-options-btn.primary {
  background: linear-gradient(135deg, #2563eb 0%, #1d4ed8 100%);
  color: #fff;
}

.rp-fade-enter-active,
.rp-fade-leave-active,
.rp-options-fade-enter-active,
.rp-options-fade-leave-active {
  transition: opacity 0.2s ease;
}

.rp-fade-enter-from,
.rp-fade-leave-to,
.rp-options-fade-enter-from,
.rp-options-fade-leave-to {
  opacity: 0;
}

.spin {
  animation: spin 1s linear infinite;
}

@keyframes spin {
  to {
    transform: rotate(360deg);
  }
}

@media print {
  .rp-overlay {
    position: static;
    padding: 0;
    background: none;
  }

  .rp-modal {
    box-shadow: none;
    border: none;
    border-radius: 0;
  }

  .rp-toolbar,
  .rp-options-backdrop {
    display: none;
  }

  .rp-body {
    padding: 0;
    background: none;
  }

  .rp-paper {
    box-shadow: none;
  }
}
</style>
