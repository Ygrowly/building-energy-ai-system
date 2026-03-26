<template>
  <Teleport to="body">
    <Transition name="rp-fade">
      <div v-if="reportStore.previewVisible" class="rp-overlay" @click.self="reportStore.closePreview()">
        <div class="rp-modal">
          <!-- 顶部工具栏 -->
          <div class="rp-toolbar">
            <div class="rp-toolbar-left">
              <span class="rp-toolbar-title">
                <Icon icon="mdi:file-chart-outline" width="16" class="rp-toolbar-icon" />
                {{ reportStore.previewPayload?.title ?? '报表预览' }}
              </span>
              <!-- 模式切换 -->
              <div class="rp-mode-toggle">
                <button
                  class="rp-mode-btn"
                  :class="{ active: reportStore.previewMode === 'snapshot' }"
                  @click="reportStore.setPreviewMode('snapshot')"
                >快照</button>
                <button
                  class="rp-mode-btn"
                  :class="{ active: reportStore.previewMode === 'formal' }"
                  @click="reportStore.setPreviewMode('formal')"
                >正式报表</button>
              </div>
            </div>
            <div class="rp-toolbar-right">
              <!-- 导出按钮 -->
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

          <!-- 报表预览区域 -->
          <div class="rp-body" ref="bodyEl">
            <div class="rp-paper" ref="paperEl">
              <ReportRenderer
                v-if="reportStore.previewPayload"
                :payload="reportStore.previewPayload"
                ref="rendererRef"
              />
              <div v-else class="rp-empty">
                <Icon icon="mdi:file-chart-outline" width="40" class="rp-empty-icon" />
                <p>暂无报表数据</p>
              </div>
            </div>
          </div>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { Icon } from '@iconify/vue'
import { useReportStore } from '@/stores/reportStore'
import ReportRenderer from './ReportRenderer.vue'
import { exportToPDF, exportToHTML, buildReportFilename } from '@/utils/reportExportEngine'

const reportStore = useReportStore()
const paperEl = ref<HTMLElement | null>(null)
const exporting = ref(false)

function getFilename(): string {
  const p = reportStore.previewPayload
  return buildReportFilename(p?.title ?? '报表', p?.buildingName)
}

async function onExportPDF() {
  if (!paperEl.value) return
  exporting.value = true
  try {
    await exportToPDF(paperEl.value, getFilename())
  } finally {
    exporting.value = false
  }
}

function onExportHTML() {
  if (!paperEl.value) return
  exportToHTML(paperEl.value, getFilename())
}

function onPrint() {
  window.print()
}
</script>

<style scoped>
/* ── 遮罩 ──────────────────────────────────────────────────── */
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

/* ── 模态容器 ──────────────────────────────────────────────── */
.rp-modal {
  width: 100%;
  max-width: 960px;
  background: #1a1f2e;
  border-radius: 12px;
  border: 1px solid rgba(255,255,255,0.08);
  box-shadow: 0 24px 80px rgba(0,0,0,0.5);
  display: flex;
  flex-direction: column;
  min-height: 400px;
  overflow: hidden;
}

/* ── 顶部工具栏 ────────────────────────────────────────────── */
.rp-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 16px;
  border-bottom: 1px solid rgba(255,255,255,0.08);
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
.rp-toolbar-icon { color: var(--accent, #5b8dee); }
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
.rp-mode-toggle {
  display: flex;
  background: rgba(255,255,255,0.06);
  border-radius: 6px;
  padding: 2px;
  gap: 2px;
  flex-shrink: 0;
}
.rp-mode-btn {
  padding: 4px 12px;
  font-size: 11px;
  font-weight: 500;
  border: none;
  border-radius: 4px;
  background: transparent;
  color: #8c939a;
  cursor: pointer;
  transition: background 0.15s, color 0.15s;
}
.rp-mode-btn.active {
  background: var(--accent, #5b8dee);
  color: #fff;
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
  border: 1px solid rgba(255,255,255,0.12);
  border-radius: 6px;
  background: rgba(255,255,255,0.06);
  color: #c8d0de;
  cursor: pointer;
  transition: background 0.15s, color 0.15s;
}
.rp-action-btn:hover:not(:disabled) {
  background: rgba(255,255,255,0.12);
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
  width: 30px; height: 30px;
  border: none;
  border-radius: 6px;
  background: transparent;
  color: #8c939a;
  cursor: pointer;
  transition: background 0.15s, color 0.15s;
}
.rp-close-btn:hover { background: rgba(255,255,255,0.08); color: #e2e8f0; }

/* ── 报表预览区 ─────────────────────────────────────────────── */
.rp-body {
  flex: 1;
  overflow-y: auto;
  padding: 24px;
  background: #f0f2f7;
}
.rp-paper {
  background: #ffffff;
  border-radius: 4px;
  box-shadow: 0 2px 20px rgba(0,0,0,0.15);
  min-height: 400px;
  overflow: hidden;
}

/* ── 空状态 ────────────────────────────────────────────────── */
.rp-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 80px 20px;
  color: #8c939a;
  gap: 12px;
}
.rp-empty-icon { color: #c8d0de; }

/* ── 动画 ──────────────────────────────────────────────────── */
.rp-fade-enter-active,
.rp-fade-leave-active { transition: opacity 0.2s ease; }
.rp-fade-enter-from,
.rp-fade-leave-to { opacity: 0; }

.spin { animation: spin 1s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }

/* ── 打印时只显示报表内容 ───────────────────────────────────── */
@media print {
  .rp-overlay { position: static; padding: 0; background: none; }
  .rp-modal { box-shadow: none; border: none; border-radius: 0; }
  .rp-toolbar { display: none; }
  .rp-body { padding: 0; background: none; }
  .rp-paper { box-shadow: none; }
}
</style>
