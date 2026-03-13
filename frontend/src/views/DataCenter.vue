<template>
  <div class="datacenter">
    <!-- 页面标题 -->
    <div class="page-header">
      <div class="page-title">
        <Icon icon="mdi:database" width="22" class="title-icon" />
        <span>数据中心</span>
      </div>
      <p class="page-desc">上传并分析结构化数据，或管理 RAG 知识库文档</p>
    </div>

    <!-- Tab 切换 -->
    <div class="tab-bar">
      <button
        class="tab-btn"
        :class="{ active: activeTab === 'datasets' }"
        @click="activeTab = 'datasets'"
      >
        <Icon icon="mdi:table-large" width="16" />
        数据集
      </button>
      <button
        class="tab-btn"
        :class="{ active: activeTab === 'knowledge' }"
        @click="activeTab = 'knowledge'; loadDocuments()"
      >
        <Icon icon="mdi:book-open-page-variant" width="16" />
        知识库
      </button>
    </div>

    <!-- ═══════════════ 数据集 Tab ═══════════════ -->
    <div v-if="activeTab === 'datasets'" class="tab-content">
      <!-- 上传区 -->
      <div
        class="dropzone"
        :class="{ dragover: isDraggingDataset }"
        @dragover.prevent="isDraggingDataset = true"
        @dragleave.prevent="isDraggingDataset = false"
        @drop.prevent="onDropDataset"
        @click="datasetFileInput?.click()"
      >
        <input
          ref="datasetFileInput"
          type="file"
          accept=".csv,.xlsx,.xls"
          class="file-input"
          @change="onDatasetFileChange"
        />
        <div v-if="!uploadingDataset" class="dropzone-inner">
          <Icon icon="mdi:cloud-upload-outline" width="36" class="upload-icon" />
          <p class="upload-hint">拖拽或点击上传 CSV / Excel 文件</p>
          <p class="upload-sub">支持 .csv .xlsx .xls，最大 50 MB</p>
        </div>
        <div v-else class="dropzone-inner uploading">
          <Icon icon="mdi:loading" width="32" class="spin upload-icon" />
          <p class="upload-hint">正在解析文件，请稍候...</p>
        </div>
      </div>

      <div v-if="datasetError" class="error-bar">
        <Icon icon="mdi:alert-circle-outline" width="14" />
        {{ datasetError }}
      </div>

      <!-- 主区域：列表 + 详情 -->
      <div class="main-area">
        <!-- 左侧：数据集列表 -->
        <div class="list-panel">
          <div class="list-header">
            <span class="list-title">已上传数据集</span>
            <button class="icon-btn" @click="loadDatasets" title="刷新">
              <Icon icon="mdi:refresh" width="15" :class="{ spin: loadingDatasets }" />
            </button>
          </div>

          <div v-if="loadingDatasets" class="list-loading">
            <Icon icon="mdi:loading" width="16" class="spin" /> 加载中...
          </div>
          <div v-else-if="datasets.length === 0" class="list-empty">
            <Icon icon="mdi:tray-remove" width="24" />
            <p>暂无数据集</p>
          </div>
          <div v-else class="dataset-list">
            <div
              v-for="ds in datasets"
              :key="ds.id"
              class="dataset-item"
              :class="{ selected: selectedDataset?.id === ds.id }"
              @click="selectDataset(ds.id)"
            >
              <div class="ds-icon">
                <Icon :icon="ds.file_type === 'csv' ? 'mdi:file-delimited-outline' : 'mdi:microsoft-excel'" width="18" />
              </div>
              <div class="ds-info">
                <p class="ds-name" :title="ds.original_name">{{ ds.original_name }}</p>
                <p class="ds-meta">{{ ds.row_count?.toLocaleString() }} 行 · {{ ds.column_count }} 列</p>
                <p class="ds-time">{{ formatDate(ds.uploaded_at) }}</p>
              </div>
              <button
                class="icon-btn danger"
                title="删除"
                @click.stop="confirmDeleteDataset(ds.id)"
              >
                <Icon icon="mdi:delete-outline" width="15" />
              </button>
            </div>
          </div>
        </div>

        <!-- 右侧：数据集详情 -->
        <div class="detail-panel">
          <div v-if="!selectedDataset && !loadingDetail" class="detail-empty">
            <Icon icon="mdi:cursor-default-click-outline" width="32" />
            <p>选择左侧数据集查看详情</p>
          </div>

          <div v-if="loadingDetail" class="detail-empty">
            <Icon icon="mdi:loading" width="24" class="spin" />
            <p>加载中...</p>
          </div>

          <div v-if="selectedDataset && !loadingDetail" class="detail-content">
            <!-- 数据集标题栏 -->
            <div class="detail-header">
              <div class="detail-title">
                <Icon :icon="selectedDataset.file_type === 'csv' ? 'mdi:file-delimited-outline' : 'mdi:microsoft-excel'" width="18" />
                {{ selectedDataset.original_name }}
              </div>
              <div class="detail-meta-row">
                <span class="meta-badge">{{ selectedDataset.row_count?.toLocaleString() }} 行</span>
                <span class="meta-badge">{{ selectedDataset.column_count }} 列</span>
                <span class="meta-badge">{{ selectedDataset.file_type.toUpperCase() }}</span>
              </div>
              <button
                class="analyze-btn"
                :disabled="analyzing"
                @click="runAIAnalysis"
              >
                <Icon :icon="analyzing ? 'mdi:loading' : 'mdi:brain'" width="16" :class="{ spin: analyzing }" />
                {{ analyzing ? 'AI 分析中...' : 'AI 洞察分析' }}
              </button>
            </div>

            <!-- AI 分析结果 -->
            <div v-if="analysisResult || analyzing" class="analysis-box">
              <div class="analysis-header">
                <Icon icon="mdi:brain" width="14" />
                AI 分析结果
              </div>
              <div class="analysis-content" v-html="renderedAnalysis"></div>
              <div v-if="analyzing" class="analysis-cursor">|</div>
            </div>

            <!-- 列信息 -->
            <div class="section">
              <div class="section-title">
                <Icon icon="mdi:table-column" width="14" />
                列信息
              </div>
              <div class="col-grid">
                <div v-for="col in selectedDataset.columns" :key="col.name" class="col-card">
                  <div class="col-name" :title="col.name">{{ col.name }}</div>
                  <div class="col-dtype">{{ col.dtype }}</div>
                  <div class="col-stats-row">
                    <span class="col-stat">空值 {{ col.null_count }}</span>
                    <span class="col-stat">唯一 {{ col.unique_count }}</span>
                  </div>
                </div>
              </div>
            </div>

            <!-- 数值统计 -->
            <div v-if="Object.keys(selectedDataset.stats).length > 0" class="section">
              <div class="section-title">
                <Icon icon="mdi:chart-box-outline" width="14" />
                数值统计
              </div>
              <div class="stats-table-wrap">
                <table class="stats-table">
                  <thead>
                    <tr>
                      <th>列名</th>
                      <th>最小值</th>
                      <th>最大值</th>
                      <th>均值</th>
                      <th>标准差</th>
                      <th>中位数</th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr v-for="(s, col) in selectedDataset.stats" :key="col">
                      <td class="col-name-cell">{{ col }}</td>
                      <td>{{ formatNum(s.min) }}</td>
                      <td>{{ formatNum(s.max) }}</td>
                      <td>{{ formatNum(s.mean) }}</td>
                      <td>{{ formatNum(s.std) }}</td>
                      <td>{{ formatNum(s.median) }}</td>
                    </tr>
                  </tbody>
                </table>
              </div>
            </div>

            <!-- 样本数据 -->
            <div v-if="selectedDataset.sample_rows.length > 0" class="section">
              <div class="section-title">
                <Icon icon="mdi:table-eye" width="14" />
                样本数据（前 10 行）
              </div>
              <div class="sample-table-wrap">
                <table class="sample-table">
                  <thead>
                    <tr>
                      <th v-for="col in sampleColumns" :key="col">{{ col }}</th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr v-for="(row, i) in selectedDataset.sample_rows" :key="i">
                      <td v-for="col in sampleColumns" :key="col">
                        {{ row[col] ?? '—' }}
                      </td>
                    </tr>
                  </tbody>
                </table>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- ═══════════════ 知识库 Tab ═══════════════ -->
    <div v-if="activeTab === 'knowledge'" class="tab-content">
      <!-- 上传区 -->
      <div
        class="dropzone"
        :class="{ dragover: isDraggingDoc }"
        @dragover.prevent="isDraggingDoc = true"
        @dragleave.prevent="isDraggingDoc = false"
        @drop.prevent="onDropDoc"
        @click="docFileInput?.click()"
      >
        <input
          ref="docFileInput"
          type="file"
          accept=".pdf,.docx,.doc,.txt,.md"
          class="file-input"
          @change="onDocFileChange"
        />
        <div v-if="!uploadingDoc" class="dropzone-inner">
          <Icon icon="mdi:file-upload-outline" width="36" class="upload-icon" />
          <p class="upload-hint">拖拽或点击上传知识库文档</p>
          <p class="upload-sub">支持 .pdf .docx .doc .txt .md，最大 50 MB</p>
        </div>
        <div v-else class="dropzone-inner uploading">
          <Icon icon="mdi:loading" width="32" class="spin upload-icon" />
          <p class="upload-hint">正在上传到 RAGFlow...</p>
        </div>
      </div>

      <div v-if="docError" class="error-bar">
        <Icon icon="mdi:alert-circle-outline" width="14" />
        {{ docError }}
      </div>
      <div v-if="docSuccess" class="success-bar">
        <Icon icon="mdi:check-circle-outline" width="14" />
        {{ docSuccess }}
      </div>

      <!-- 文档列表 -->
      <div class="doc-list-header">
        <span class="list-title">知识库文档</span>
        <button class="icon-btn" @click="loadDocuments" title="刷新">
          <Icon icon="mdi:refresh" width="15" :class="{ spin: loadingDocs }" />
        </button>
      </div>

      <div v-if="loadingDocs" class="list-loading">
        <Icon icon="mdi:loading" width="16" class="spin" /> 加载中...
      </div>
      <div v-else-if="documents.length === 0" class="list-empty">
        <Icon icon="mdi:book-off-outline" width="32" />
        <p>知识库暂无文档</p>
        <p class="sub">上传 PDF/Word 文件后，点击"解析"进行向量化</p>
      </div>
      <div v-else class="doc-table-wrap">
        <table class="doc-table">
          <thead>
            <tr>
              <th>文件名</th>
              <th>大小</th>
              <th>解析状态</th>
              <th>进度</th>
              <th>更新时间</th>
              <th>操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="doc in documents" :key="doc.id">
              <td class="doc-name-cell">
                <Icon :icon="getDocIcon(doc.name)" width="15" class="doc-type-icon" />
                {{ doc.name }}
              </td>
              <td>{{ formatSize(doc.size) }}</td>
              <td>
                <span class="status-badge" :class="getStatusClass(doc.run)">
                  <Icon :icon="getStatusIcon(doc.run)" width="12" />
                  {{ getStatusLabel(doc.run) }}
                </span>
              </td>
              <td>
                <div class="progress-bar-wrap">
                  <div class="progress-bar" :style="{ width: `${(doc.progress ?? 0) * 100}%` }"></div>
                </div>
                <span class="progress-text">{{ Math.round((doc.progress ?? 0) * 100) }}%</span>
              </td>
              <td>{{ formatDate(new Date(doc.update_time).toISOString()) }}</td>
              <td>
                <div class="action-btns">
                  <button
                    class="action-btn parse-btn"
                    :disabled="doc.run === 'running'"
                    title="解析向量化"
                    @click="triggerParse(doc.id)"
                  >
                    <Icon icon="mdi:vector-polyline" width="14" />
                    解析
                  </button>
                  <button
                    class="action-btn delete-btn"
                    title="删除"
                    @click="confirmDeleteDoc(doc.id, doc.name)"
                  >
                    <Icon icon="mdi:delete-outline" width="14" />
                  </button>
                </div>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

    <!-- 删除确认弹窗 -->
    <div v-if="deleteConfirm" class="modal-mask" @click.self="deleteConfirm = null">
      <div class="modal">
        <div class="modal-icon">
          <Icon icon="mdi:alert-outline" width="28" />
        </div>
        <p class="modal-text">{{ deleteConfirm.message }}</p>
        <div class="modal-actions">
          <button class="modal-btn cancel" @click="deleteConfirm = null">取消</button>
          <button class="modal-btn confirm" @click="executeDelete">确认删除</button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { Icon } from '@iconify/vue'
import * as api from '@/api/datacenter'
import type { DatasetSummary, DatasetDetail, RagDocument } from '@/api/datacenter'

// ── 状态 ─────────────────────────────────────────────────────
const activeTab = ref<'datasets' | 'knowledge'>('datasets')

// 数据集状态
const datasetFileInput = ref<HTMLInputElement | null>(null)
const isDraggingDataset = ref(false)
const uploadingDataset = ref(false)
const loadingDatasets = ref(false)
const loadingDetail = ref(false)
const analyzing = ref(false)
const datasetError = ref('')
const datasets = ref<DatasetSummary[]>([])
const selectedDataset = ref<DatasetDetail | null>(null)
const analysisResult = ref('')

// 知识库状态
const docFileInput = ref<HTMLInputElement | null>(null)
const isDraggingDoc = ref(false)
const uploadingDoc = ref(false)
const loadingDocs = ref(false)
const docError = ref('')
const docSuccess = ref('')
const documents = ref<RagDocument[]>([])

// 删除确认
const deleteConfirm = ref<{ message: string; action: () => Promise<void> } | null>(null)

// ── 生命周期 ─────────────────────────────────────────────────
onMounted(() => {
  loadDatasets()
})

// ── 计算属性 ─────────────────────────────────────────────────
const sampleColumns = computed(() =>
  selectedDataset.value?.sample_rows?.[0]
    ? Object.keys(selectedDataset.value.sample_rows[0])
    : [],
)

const renderedAnalysis = computed(() => {
  if (!analysisResult.value) return ''
  return markdownToHtml(analysisResult.value)
})

// ── 数据集操作 ────────────────────────────────────────────────
async function loadDatasets() {
  loadingDatasets.value = true
  try {
    datasets.value = await api.listDatasets()
  } catch (e) {
    datasetError.value = (e as Error).message
  } finally {
    loadingDatasets.value = false
  }
}

async function selectDataset(id: string) {
  if (selectedDataset.value?.id === id) return
  loadingDetail.value = true
  analysisResult.value = ''
  try {
    selectedDataset.value = await api.getDataset(id)
  } catch (e) {
    datasetError.value = (e as Error).message
  } finally {
    loadingDetail.value = false
  }
}

async function onDatasetFileChange(e: Event) {
  const file = (e.target as HTMLInputElement).files?.[0]
  if (file) await uploadDatasetFile(file)
  ;(e.target as HTMLInputElement).value = ''
}

async function onDropDataset(e: DragEvent) {
  isDraggingDataset.value = false
  const file = e.dataTransfer?.files[0]
  if (file) await uploadDatasetFile(file)
}

async function uploadDatasetFile(file: File) {
  datasetError.value = ''
  uploadingDataset.value = true
  try {
    const result = await api.uploadDataset(file)
    datasets.value.unshift({
      id: result.id,
      original_name: result.original_name,
      file_type: result.file_type,
      row_count: result.row_count,
      column_count: result.column_count,
      uploaded_at: result.uploaded_at,
    })
    selectedDataset.value = result
    analysisResult.value = ''
  } catch (e) {
    datasetError.value = (e as Error).message
  } finally {
    uploadingDataset.value = false
  }
}

function confirmDeleteDataset(id: string) {
  const ds = datasets.value.find(d => d.id === id)
  deleteConfirm.value = {
    message: `确认删除数据集「${ds?.original_name}」？此操作不可恢复。`,
    action: async () => {
      await api.deleteDataset(id)
      datasets.value = datasets.value.filter(d => d.id !== id)
      if (selectedDataset.value?.id === id) {
        selectedDataset.value = null
        analysisResult.value = ''
      }
    },
  }
}

async function runAIAnalysis() {
  if (!selectedDataset.value || analyzing.value) return
  analysisResult.value = ''
  analyzing.value = true
  await api.analyzeDataset(
    selectedDataset.value.id,
    (chunk) => { analysisResult.value += chunk },
    () => { analyzing.value = false },
    (err) => { datasetError.value = err; analyzing.value = false },
  )
}

// ── 知识库操作 ────────────────────────────────────────────────
async function loadDocuments() {
  loadingDocs.value = true
  docError.value = ''
  try {
    const res = await api.listDocuments()
    documents.value = res?.data?.docs ?? []
  } catch (e) {
    docError.value = (e as Error).message
  } finally {
    loadingDocs.value = false
  }
}

async function onDocFileChange(e: Event) {
  const file = (e.target as HTMLInputElement).files?.[0]
  if (file) await uploadDocFile(file)
  ;(e.target as HTMLInputElement).value = ''
}

async function onDropDoc(e: DragEvent) {
  isDraggingDoc.value = false
  const file = e.dataTransfer?.files[0]
  if (file) await uploadDocFile(file)
}

async function uploadDocFile(file: File) {
  docError.value = ''
  docSuccess.value = ''
  uploadingDoc.value = true
  try {
    await api.uploadDocument(file)
    docSuccess.value = `「${file.name}」已上传，点击"解析"按钮进行向量化`
    await loadDocuments()
  } catch (e) {
    docError.value = (e as Error).message
  } finally {
    uploadingDoc.value = false
  }
}

async function triggerParse(docId: string) {
  docError.value = ''
  try {
    await api.parseDocument(docId)
    docSuccess.value = '已提交解析任务，稍后刷新查看进度'
    setTimeout(() => loadDocuments(), 2000)
  } catch (e) {
    docError.value = (e as Error).message
  }
}

function confirmDeleteDoc(docId: string, name: string) {
  deleteConfirm.value = {
    message: `确认从知识库删除文档「${name}」？`,
    action: async () => {
      await api.deleteDocument(docId)
      documents.value = documents.value.filter(d => d.id !== docId)
      docSuccess.value = '文档已删除'
    },
  }
}

async function executeDelete() {
  if (!deleteConfirm.value) return
  try {
    await deleteConfirm.value.action()
  } catch (e) {
    datasetError.value = (e as Error).message
    docError.value = (e as Error).message
  } finally {
    deleteConfirm.value = null
  }
}

// ── 工具函数 ─────────────────────────────────────────────────
function formatDate(iso: string): string {
  return new Date(iso).toLocaleString('zh-CN', {
    month: '2-digit', day: '2-digit',
    hour: '2-digit', minute: '2-digit',
  })
}

function formatNum(val: number | null | undefined): string {
  if (val == null) return '—'
  return Number(val).toLocaleString('zh-CN', { maximumFractionDigits: 4 })
}

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`
}

function getDocIcon(name: string): string {
  const ext = name.split('.').pop()?.toLowerCase()
  if (ext === 'pdf') return 'mdi:file-pdf-box'
  if (ext === 'docx' || ext === 'doc') return 'mdi:file-word-box'
  if (ext === 'txt') return 'mdi:file-document-outline'
  return 'mdi:file-outline'
}

function getStatusClass(run: string): string {
  const map: Record<string, string> = {
    unstart: 'status-idle',
    running: 'status-running',
    done: 'status-done',
    fail: 'status-fail',
    CANCEL: 'status-cancel',
  }
  return map[run] ?? 'status-idle'
}

function getStatusIcon(run: string): string {
  const map: Record<string, string> = {
    unstart: 'mdi:clock-outline',
    running: 'mdi:loading',
    done: 'mdi:check-circle-outline',
    fail: 'mdi:alert-circle-outline',
    CANCEL: 'mdi:cancel',
  }
  return map[run] ?? 'mdi:clock-outline'
}

function getStatusLabel(run: string): string {
  const map: Record<string, string> = {
    unstart: '待解析',
    running: '解析中',
    done: '已完成',
    fail: '解析失败',
    CANCEL: '已取消',
  }
  return map[run] ?? run
}

/** 极简 Markdown → HTML 转换（仅支持标题、加粗、换行、有序/无序列表）。 */
function markdownToHtml(md: string): string {
  return md
    .replace(/^### (.+)$/gm, '<h4>$1</h4>')
    .replace(/^## (.+)$/gm, '<h3>$1</h3>')
    .replace(/^# (.+)$/gm, '<h2>$1</h2>')
    .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
    .replace(/^- (.+)$/gm, '<li>$1</li>')
    .replace(/^\d+\. (.+)$/gm, '<li>$1</li>')
    .replace(/\n\n/g, '<br/><br/>')
    .replace(/\n/g, '<br/>')
}
</script>

<style scoped>
.datacenter {
  height: 100%;
  overflow-y: auto;
  padding: 24px;
  display: flex;
  flex-direction: column;
  gap: 20px;
}

/* ── 页面标题 ── */
.page-header { display: flex; flex-direction: column; gap: 4px; }
.page-title {
  display: flex;
  align-items: center;
  gap: 10px;
  font-size: 18px;
  font-weight: 600;
  color: var(--text-primary);
}
.title-icon { color: var(--accent); }
.page-desc { font-size: 12px; color: var(--text-secondary); margin-left: 32px; }

/* ── Tab 切换 ── */
.tab-bar {
  display: flex;
  gap: 4px;
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: 10px;
  padding: 4px;
  width: fit-content;
}
.tab-btn {
  display: flex;
  align-items: center;
  gap: 7px;
  padding: 7px 18px;
  border-radius: 7px;
  border: none;
  background: transparent;
  color: var(--text-secondary);
  font-size: 13px;
  cursor: pointer;
  transition: all 0.18s;
}
.tab-btn:hover { color: var(--text-primary); background: var(--bg-hover); }
.tab-btn.active { background: var(--accent); color: #fff; font-weight: 500; }

/* ── Tab 内容区 ── */
.tab-content { display: flex; flex-direction: column; gap: 16px; }

/* ── 上传区 ── */
.dropzone {
  border: 2px dashed var(--border);
  border-radius: 12px;
  padding: 32px 24px;
  text-align: center;
  cursor: pointer;
  transition: all 0.2s;
  background: var(--bg-card);
  position: relative;
}
.dropzone:hover, .dropzone.dragover {
  border-color: var(--accent);
  background: var(--accent-glow);
}
.file-input { display: none; }
.dropzone-inner { display: flex; flex-direction: column; align-items: center; gap: 8px; }
.dropzone-inner.uploading { opacity: 0.7; }
.upload-icon { color: var(--accent); }
.upload-hint { font-size: 14px; color: var(--text-primary); font-weight: 500; }
.upload-sub { font-size: 12px; color: var(--text-muted); }

/* ── 消息栏 ── */
.error-bar, .success-bar {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 14px;
  border-radius: 8px;
  font-size: 13px;
}
.error-bar { background: rgba(248,113,113,0.1); color: var(--danger); border: 1px solid rgba(248,113,113,0.2); }
.success-bar { background: rgba(74,222,128,0.08); color: var(--success); border: 1px solid rgba(74,222,128,0.18); }

/* ── 主区域：列表+详情 ── */
.main-area {
  display: grid;
  grid-template-columns: 280px 1fr;
  gap: 16px;
  min-height: 420px;
}

/* ── 列表面板 ── */
.list-panel {
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: 12px;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}
.list-header, .doc-list-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 14px;
  border-bottom: 1px solid var(--border);
}
.list-title { font-size: 13px; font-weight: 600; color: var(--text-primary); }
.list-loading, .list-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 10px;
  padding: 32px;
  color: var(--text-muted);
  font-size: 13px;
}
.dataset-list { overflow-y: auto; flex: 1; }
.dataset-item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 14px;
  cursor: pointer;
  border-bottom: 1px solid var(--border);
  transition: background 0.15s;
}
.dataset-item:hover { background: var(--bg-hover); }
.dataset-item.selected { background: var(--accent-glow); border-left: 2px solid var(--accent); }
.ds-icon { color: var(--accent); flex-shrink: 0; }
.ds-info { flex: 1; min-width: 0; }
.ds-name { font-size: 13px; color: var(--text-primary); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.ds-meta { font-size: 11px; color: var(--text-secondary); margin-top: 2px; }
.ds-time { font-size: 11px; color: var(--text-muted); }

/* ── 图标按钮 ── */
.icon-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 28px;
  height: 28px;
  border-radius: 6px;
  border: none;
  background: transparent;
  color: var(--text-secondary);
  cursor: pointer;
  transition: all 0.15s;
  flex-shrink: 0;
}
.icon-btn:hover { background: var(--bg-hover); color: var(--text-primary); }
.icon-btn.danger:hover { background: rgba(248,113,113,0.1); color: var(--danger); }

/* ── 详情面板 ── */
.detail-panel {
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: 12px;
  overflow-y: auto;
}
.detail-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  height: 100%;
  gap: 12px;
  color: var(--text-muted);
  font-size: 13px;
  padding: 48px;
}
.detail-content { padding: 20px; display: flex; flex-direction: column; gap: 20px; }
.detail-header { display: flex; flex-direction: column; gap: 10px; }
.detail-title {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 15px;
  font-weight: 600;
  color: var(--text-primary);
}
.detail-meta-row { display: flex; gap: 8px; }
.meta-badge {
  padding: 3px 10px;
  border-radius: 20px;
  background: var(--bg-hover);
  border: 1px solid var(--border);
  font-size: 11px;
  color: var(--text-secondary);
}

/* ── AI 分析按钮 ── */
.analyze-btn {
  display: flex;
  align-items: center;
  gap: 7px;
  padding: 8px 18px;
  border-radius: 8px;
  border: 1px solid var(--accent);
  background: var(--accent-glow);
  color: var(--accent);
  font-size: 13px;
  cursor: pointer;
  width: fit-content;
  transition: all 0.18s;
}
.analyze-btn:hover:not(:disabled) { background: var(--accent); color: #fff; }
.analyze-btn:disabled { opacity: 0.6; cursor: not-allowed; }

/* ── AI 分析结果框 ── */
.analysis-box {
  background: var(--bg-panel);
  border: 1px solid var(--border-accent);
  border-radius: 10px;
  overflow: hidden;
}
.analysis-header {
  display: flex;
  align-items: center;
  gap: 7px;
  padding: 10px 14px;
  border-bottom: 1px solid var(--border);
  font-size: 12px;
  color: var(--accent);
  font-weight: 600;
  background: var(--accent-glow);
}
.analysis-content {
  padding: 14px 16px;
  font-size: 13px;
  color: var(--text-primary);
  line-height: 1.8;
}
.analysis-content :deep(h2) { font-size: 15px; color: var(--text-primary); margin: 12px 0 6px; }
.analysis-content :deep(h3) { font-size: 14px; color: var(--accent); margin: 10px 0 4px; }
.analysis-content :deep(h4) { font-size: 13px; color: var(--text-primary); margin: 8px 0 4px; }
.analysis-content :deep(strong) { color: var(--accent-2); }
.analysis-content :deep(li) { margin-left: 16px; list-style: disc; margin-bottom: 3px; }
.analysis-cursor {
  display: inline-block;
  width: 2px;
  height: 14px;
  background: var(--accent);
  animation: blink 0.8s step-end infinite;
  margin-left: 2px;
  vertical-align: text-bottom;
}
@keyframes blink { 50% { opacity: 0; } }

/* ── Section ── */
.section { display: flex; flex-direction: column; gap: 10px; }
.section-title {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  font-weight: 600;
  color: var(--text-secondary);
  text-transform: uppercase;
  letter-spacing: 0.5px;
}

/* ── 列信息网格 ── */
.col-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(160px, 1fr));
  gap: 8px;
}
.col-card {
  background: var(--bg-panel);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 10px 12px;
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.col-name {
  font-size: 12px;
  font-weight: 600;
  color: var(--text-primary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.col-dtype {
  font-size: 11px;
  color: var(--accent);
  background: var(--accent-glow);
  padding: 1px 6px;
  border-radius: 4px;
  width: fit-content;
}
.col-stats-row { display: flex; gap: 8px; }
.col-stat { font-size: 11px; color: var(--text-muted); }

/* ── 统计表格 ── */
.stats-table-wrap, .sample-table-wrap {
  overflow-x: auto;
  border-radius: 8px;
  border: 1px solid var(--border);
}
.stats-table, .sample-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 12px;
}
.stats-table th, .sample-table th {
  padding: 8px 12px;
  background: var(--bg-panel);
  color: var(--text-secondary);
  font-weight: 600;
  text-align: left;
  white-space: nowrap;
  border-bottom: 1px solid var(--border);
}
.stats-table td, .sample-table td {
  padding: 7px 12px;
  color: var(--text-primary);
  border-bottom: 1px solid var(--border);
  white-space: nowrap;
}
.stats-table tr:last-child td, .sample-table tr:last-child td { border-bottom: none; }
.stats-table tr:hover td, .sample-table tr:hover td { background: var(--bg-hover); }
.col-name-cell { color: var(--accent); font-weight: 500; }

/* ── 文档列表 ── */
.doc-list-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.doc-table-wrap {
  border: 1px solid var(--border);
  border-radius: 12px;
  overflow: hidden;
}
.doc-table { width: 100%; border-collapse: collapse; font-size: 13px; }
.doc-table th {
  padding: 10px 14px;
  background: var(--bg-card);
  color: var(--text-secondary);
  font-weight: 600;
  text-align: left;
  border-bottom: 1px solid var(--border);
  white-space: nowrap;
}
.doc-table td {
  padding: 10px 14px;
  color: var(--text-primary);
  border-bottom: 1px solid var(--border);
  vertical-align: middle;
}
.doc-table tr:last-child td { border-bottom: none; }
.doc-table tr:hover td { background: var(--bg-hover); }
.doc-name-cell {
  display: flex;
  align-items: center;
  gap: 8px;
  max-width: 240px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.doc-type-icon { color: var(--accent); flex-shrink: 0; }

/* ── 状态徽章 ── */
.status-badge {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 3px 9px;
  border-radius: 20px;
  font-size: 11px;
  font-weight: 500;
}
.status-idle { background: rgba(107,122,154,0.12); color: var(--text-secondary); }
.status-running { background: rgba(96,165,250,0.12); color: var(--accent); }
.status-done { background: rgba(74,222,128,0.1); color: var(--success); }
.status-fail { background: rgba(248,113,113,0.1); color: var(--danger); }
.status-cancel { background: rgba(251,191,36,0.1); color: var(--warning); }

/* ── 进度条 ── */
.progress-bar-wrap {
  height: 4px;
  background: var(--bg-hover);
  border-radius: 2px;
  overflow: hidden;
  width: 80px;
  display: inline-block;
  vertical-align: middle;
  margin-right: 6px;
}
.progress-bar { height: 100%; background: var(--accent); border-radius: 2px; transition: width 0.4s; }
.progress-text { font-size: 11px; color: var(--text-secondary); vertical-align: middle; }

/* ── 操作按钮 ── */
.action-btns { display: flex; align-items: center; gap: 6px; }
.action-btn {
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 5px 10px;
  border-radius: 6px;
  border: none;
  font-size: 12px;
  cursor: pointer;
  transition: all 0.15s;
}
.parse-btn {
  background: var(--accent-glow);
  color: var(--accent);
  border: 1px solid var(--border-accent);
}
.parse-btn:hover:not(:disabled) { background: var(--accent); color: #fff; }
.parse-btn:disabled { opacity: 0.5; cursor: not-allowed; }
.delete-btn {
  background: transparent;
  color: var(--text-muted);
  border: 1px solid var(--border);
  width: 28px;
  height: 28px;
  padding: 0;
  justify-content: center;
}
.delete-btn:hover { background: rgba(248,113,113,0.1); color: var(--danger); border-color: rgba(248,113,113,0.3); }

/* ── 删除确认弹窗 ── */
.modal-mask {
  position: fixed;
  inset: 0;
  background: rgba(0,0,0,0.55);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 1000;
}
.modal {
  background: var(--bg-panel);
  border: 1px solid var(--border);
  border-radius: 14px;
  padding: 28px 32px;
  width: 360px;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 14px;
  box-shadow: var(--panel-shadow);
}
.modal-icon { color: var(--warning); }
.modal-text { font-size: 14px; color: var(--text-primary); text-align: center; line-height: 1.6; }
.modal-actions { display: flex; gap: 10px; width: 100%; }
.modal-btn {
  flex: 1;
  padding: 9px;
  border-radius: 8px;
  border: 1px solid var(--border);
  font-size: 13px;
  cursor: pointer;
  transition: all 0.15s;
}
.modal-btn.cancel { background: var(--bg-hover); color: var(--text-primary); }
.modal-btn.cancel:hover { background: var(--bg-card); }
.modal-btn.confirm { background: var(--danger); color: #fff; border-color: var(--danger); }
.modal-btn.confirm:hover { opacity: 0.85; }

/* ── 动画 ── */
.spin { animation: spin 1s linear infinite; }
@keyframes spin { from { transform: rotate(0deg); } to { transform: rotate(360deg); } }
</style>
