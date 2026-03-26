<template>
  <div class="datacenter">
    <!-- 全局 Toast 通知 -->
    <Transition name="toast">
      <div v-if="toast" :class="['global-toast', `toast-${toast.type}`]">
        <Icon :icon="toast.type === 'success' ? 'mdi:check-circle-outline' : toast.type === 'error' ? 'mdi:alert-circle-outline' : 'mdi:information-outline'" width="18" />
        <span>{{ toast.msg }}</span>
      </div>
    </Transition>

    <!-- 页面标题 + Tab 切换 -->
    <div class="page-header">
      <div class="page-header-left">
        <div class="page-title">
          <Icon icon="mdi:database" width="22" class="title-icon" />
          <span>数据中心</span>
        </div>
        <p class="page-desc">上传并分析结构化数据，或管理 RAG 知识库文档</p>
      </div>
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

        <!-- 右侧：数据集详情 + CRUD -->
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
              <div class="detail-title-row">
                <div class="detail-title">
                  <Icon :icon="selectedDataset.file_type === 'csv' ? 'mdi:file-delimited-outline' : 'mdi:microsoft-excel'" width="18" />
                  {{ selectedDataset.original_name }}
                </div>
                <div class="detail-actions">
                  <!-- 导入按钮 -->
                  <button
                    class="import-btn"
                    :disabled="importing"
                    @click="runImport"
                    :title="importMeta ? `已导入 ${importMeta.imported_rows} 条，点击重新导入` : '导入到 energy_data 表'"
                  >
                    <Icon :icon="importing ? 'mdi:loading' : (importMeta ? 'mdi:database-check' : 'mdi:database-import')" width="15" :class="{ spin: importing }" />
                    {{ importing ? '导入中...' : (importMeta ? '重新导入' : '导入到 energy_data') }}
                  </button>
                  <!-- AI 分析按钮 -->
                  <button
                    class="analyze-btn"
                    :disabled="analyzing"
                    @click="runAIAnalysis"
                  >
                    <Icon :icon="analyzing ? 'mdi:loading' : 'mdi:brain'" width="15" :class="{ spin: analyzing }" />
                    {{ analyzing ? 'AI 分析中...' : 'AI 洞察' }}
                  </button>
                </div>
              </div>
              <div class="detail-meta-row">
                <span class="meta-badge">{{ selectedDataset.row_count?.toLocaleString() }} 行</span>
                <span class="meta-badge">{{ selectedDataset.column_count }} 列</span>
                <span class="meta-badge">{{ selectedDataset.file_type.toUpperCase() }}</span>
                <span v-if="importMeta" class="meta-badge imported-badge">
                  <Icon icon="mdi:check-circle" width="11" />
                  已导入 {{ importMeta.imported_rows.toLocaleString() }} 条
                </span>
              </div>
            </div>

            <!-- 导入进度条 -->
            <div v-if="importing" class="import-progress-wrap">
              <div class="import-progress-header">
                <Icon icon="mdi:database-import" width="14" />
                <span>{{ importProgressMsg }}</span>
                <span v-if="importTotal > 0" class="import-count">
                  {{ importProcessed.toLocaleString() }} / {{ importTotal.toLocaleString() }} 行
                </span>
              </div>
              <div class="import-progress-track">
                <div class="import-progress-bar" :style="{ width: `${importProgress * 100}%` }"></div>
              </div>
              <div class="import-progress-pct">{{ Math.round(importProgress * 100) }}%</div>
            </div>

            <!-- 导入错误提示 -->
            <div v-if="importError" class="error-bar">
              <Icon icon="mdi:alert-circle-outline" width="14" />
              {{ importError }}
            </div>
            <div v-if="importSuccess && !importing" class="success-bar">
              <Icon icon="mdi:check-circle-outline" width="14" />
              {{ importSuccess }}
            </div>

            <!-- 导入后的 CRUD 区（可折叠） -->
            <div v-if="importMeta" class="crud-section">
              <!-- CRUD 标题栏（带折叠） -->
              <div class="crud-header" @click="showCrud = !showCrud" style="cursor:pointer">
                <div class="crud-title">
                  <Icon
                    :icon="showCrud ? 'mdi:chevron-down' : 'mdi:chevron-right'"
                    width="16"
                    class="crud-toggle-icon"
                  />
                  <Icon icon="mdi:table-edit" width="15" />
                  energy_data 数据管理
                  <span class="crud-total">共 {{ energyDataTotal.toLocaleString() }} 条</span>
                </div>
                <div class="crud-actions" @click.stop>
                  <button class="crud-btn add-btn" @click="openAddModal">
                    <Icon icon="mdi:plus" width="14" />
                    新增行
                  </button>
                  <button class="crud-btn refresh-btn" @click="loadEnergyData" :disabled="loadingEnergyData">
                    <Icon icon="mdi:refresh" width="14" :class="{ spin: loadingEnergyData }" />
                    刷新
                  </button>
                  <button class="crud-btn" @click="showCrud = !showCrud" :title="showCrud ? '折叠' : '展开'">
                    <Icon :icon="showCrud ? 'mdi:chevron-up' : 'mdi:chevron-down'" width="15" />
                  </button>
                </div>
              </div>

              <!-- 折叠内容 -->
              <div v-if="showCrud">
              <!-- 加载状态 -->
              <div v-if="loadingEnergyData" class="crud-loading">
                <Icon icon="mdi:loading" width="18" class="spin" /> 加载数据...
              </div>

              <!-- 数据表格 -->
              <div v-else class="crud-table-wrap">
                <table class="crud-table">
                  <thead>
                    <tr>
                      <th class="col-ts">时间戳</th>
                      <th class="col-bid">楼宇ID</th>
                      <th class="col-num">电耗(kWh)</th>
                      <th class="col-num">水耗(m³)</th>
                      <th class="col-num">空调(kWh)</th>
                      <th class="col-num">供水℃</th>
                      <th class="col-num">回水℃</th>
                      <th class="col-num">室外℃</th>
                      <th class="col-num">湿度%</th>
                      <th class="col-actions">操作</th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr v-if="energyDataRecords.length === 0">
                      <td colspan="10" class="empty-row">暂无数据</td>
                    </tr>
                    <tr
                      v-for="row in energyDataRecords"
                      :key="`${row.timestamp}-${row.building_id}`"
                      class="data-row"
                    >
                      <td class="col-ts ts-cell" :title="row.timestamp">{{ formatTsShort(row.timestamp) }}</td>
                      <td class="col-bid"><span class="bid-badge">{{ row.building_id }}</span></td>
                      <td class="col-num">{{ formatNum(row.electricity_kwh) }}</td>
                      <td class="col-num">{{ formatNum(row.water_m3) }}</td>
                      <td class="col-num">{{ formatNum(row.hac_energy) }}</td>
                      <td class="col-num">{{ formatNum(row.sim_supply_temp_c) }}</td>
                      <td class="col-num">{{ formatNum(row.sim_return_temp_c) }}</td>
                      <td class="col-num">{{ formatNum(row.air_temp_c) }}</td>
                      <td class="col-num">{{ formatNum(row.humidity_rh_pct) }}</td>
                      <td class="col-actions">
                        <button class="row-btn edit-row" @click="openEditModal(row)" title="编辑">
                          <Icon icon="mdi:pencil-outline" width="13" />
                        </button>
                        <button class="row-btn del-row" @click="confirmDeleteRow(row)" title="删除">
                          <Icon icon="mdi:delete-outline" width="13" />
                        </button>
                      </td>
                    </tr>
                  </tbody>
                </table>
              </div>

              <!-- 分页 -->
              <div v-if="energyDataTotal > 0" class="pagination">
                <button class="page-btn" :disabled="energyPage <= 1" @click="changePage(energyPage - 1)">
                  <Icon icon="mdi:chevron-left" width="15" />
                </button>
                <span class="page-info">{{ energyPage }} / {{ totalPages }}</span>
                <button class="page-btn" :disabled="energyPage >= totalPages" @click="changePage(energyPage + 1)">
                  <Icon icon="mdi:chevron-right" width="15" />
                </button>
                <span class="page-size-info">每页 {{ energyPageSize }} 条</span>
              </div>
              </div><!-- end v-if="showCrud" -->
            </div><!-- end crud-section -->

            <!-- AI 分析结果 -->
            <div v-if="analysisResult || analyzing" class="analysis-box">
              <div class="analysis-header">
                <Icon icon="mdi:brain" width="14" />
                AI 分析结果
              </div>
              <div class="analysis-content" v-html="renderedAnalysis"></div>
              <div v-if="analyzing" class="analysis-cursor">|</div>
            </div>

            <!-- 数据预览区（折叠） -->
            <div class="preview-section">
              <button class="preview-toggle" @click="showPreview = !showPreview">
                <Icon :icon="showPreview ? 'mdi:chevron-up' : 'mdi:chevron-down'" width="15" />
                数据预览
                <span class="preview-sub">列信息 · 统计 · 样本</span>
              </button>

              <div v-if="showPreview">
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
                          <th>列名</th><th>最小值</th><th>最大值</th><th>均值</th><th>标准差</th><th>中位数</th>
                        </tr>
                      </thead>
                      <tbody>
                        <tr v-for="(s, col) in previewStats" :key="col">
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
                        <tr><th v-for="col in sampleColumns" :key="col">{{ col }}</th></tr>
                      </thead>
                      <tbody>
                        <tr v-for="(row, i) in selectedDataset.sample_rows" :key="i">
                          <td v-for="col in sampleColumns" :key="col">{{ row[col] ?? '—' }}</td>
                        </tr>
                      </tbody>
                    </table>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- ═══════════════ 编辑/新增弹窗 ═══════════════ -->
    <div v-if="showEditModal || showAddModal" class="modal-mask" @click.self="closeDataModal">
      <div class="data-modal">
        <div class="data-modal-header">
          <Icon :icon="showAddModal ? 'mdi:plus-circle-outline' : 'mdi:pencil-circle-outline'" width="18" />
          <span>{{ showAddModal ? '新增 energy_data 记录' : '编辑记录' }}</span>
          <button class="modal-close" @click="closeDataModal">
            <Icon icon="mdi:close" width="16" />
          </button>
        </div>
        <div class="data-modal-body">
          <div class="form-row">
            <label>时间戳 *</label>
            <input v-model="editForm.timestamp" type="text" placeholder="2024-01-01T00:00:00+00:00" :disabled="showEditModal" />
          </div>
          <div class="form-row">
            <label>楼宇 ID *</label>
            <input v-model="editForm.building_id" type="text" placeholder="如 Kassandra_M" :disabled="showEditModal" />
          </div>
          <div class="form-grid">
            <div class="form-field">
              <label>电耗 (kWh)</label>
              <input v-model.number="editForm.electricity_kwh" type="number" step="any" placeholder="—" />
            </div>
            <div class="form-field">
              <label>水耗 (m³)</label>
              <input v-model.number="editForm.water_m3" type="number" step="any" placeholder="—" />
            </div>
            <div class="form-field">
              <label>空调能耗 (kWh)</label>
              <input v-model.number="editForm.hac_energy" type="number" step="any" placeholder="—" />
            </div>
            <div class="form-field">
              <label>供水温度 (℃)</label>
              <input v-model.number="editForm.sim_supply_temp_c" type="number" step="any" placeholder="—" />
            </div>
            <div class="form-field">
              <label>回水温度 (℃)</label>
              <input v-model.number="editForm.sim_return_temp_c" type="number" step="any" placeholder="—" />
            </div>
            <div class="form-field">
              <label>室外温度 (℃)</label>
              <input v-model.number="editForm.air_temp_c" type="number" step="any" placeholder="—" />
            </div>
            <div class="form-field">
              <label>露点温度 (℃)</label>
              <input v-model.number="editForm.dew_temp_c" type="number" step="any" placeholder="—" />
            </div>
            <div class="form-field">
              <label>相对湿度 (%)</label>
              <input v-model.number="editForm.humidity_rh_pct" type="number" step="any" placeholder="—" />
            </div>
          </div>
        </div>
        <div class="data-modal-footer">
          <button class="modal-btn cancel" @click="closeDataModal">取消</button>
          <button class="modal-btn confirm" @click="submitDataModal" :disabled="savingRow">
            <Icon :icon="savingRow ? 'mdi:loading' : 'mdi:check'" width="14" :class="{ spin: savingRow }" />
            {{ savingRow ? '保存中...' : '保存' }}
          </button>
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
                    :disabled="getRunKey(doc.run) === 'running' || parsingByDoc[doc.id]"
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
        <!-- 若有 energy_data 导入记录，提示同步删除 -->
        <div v-if="deleteConfirm.hasImport" class="delete-energy-opt">
          <label class="opt-label">
            <input type="checkbox" v-model="deleteConfirm.deleteEnergyData" />
            <span>同时删除已导入到 energy_data 的 <strong>{{ deleteConfirm.importedRows?.toLocaleString() }}</strong> 条记录</span>
          </label>
          <p class="opt-hint">取消勾选则仅删除数据集文件，energy_data 数据保留</p>
        </div>
        <div class="modal-actions">
          <button class="modal-btn cancel" @click="deleteConfirm = null">取消</button>
          <button class="modal-btn confirm" @click="executeDelete">确认删除</button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, watch } from 'vue'
import { useRoute } from 'vue-router'
import { Icon } from '@iconify/vue'
import * as api from '@/api/datacenter'
import type { DatasetSummary, DatasetDetail, RagDocument, EnergyDataRecord, ImportResult } from '@/api/datacenter'
import { useReportExport } from '@/composables/useReportExport'

// ── 状态 ─────────────────────────────────────────────────────
const route = useRoute()
const initialTab = route.query.tab === 'knowledge' ? 'knowledge' : 'datasets'
const activeTab = ref<'datasets' | 'knowledge'>(initialTab)
const { registerSection, setReportMeta } = useReportExport('datacenter')

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

// 导入状态
const importing = ref(false)
const importError = ref('')
const importSuccess = ref('')
const importMeta = ref<ImportResult | null>(null)
const importProgress = ref(0)       // 0-1
const importProgressMsg = ref('')   // 进度描述文字
const importProcessed = ref(0)      // 已处理行数
const importTotal = ref(0)          // 总行数

// energy_data CRUD 状态
const loadingEnergyData = ref(false)
const energyDataRecords = ref<EnergyDataRecord[]>([])
const energyDataTotal = ref(0)
const energyPage = ref(1)
const energyPageSize = 50
const showCrud = ref(true)          // CRUD 区域折叠控制

// 编辑/新增弹窗
const showEditModal = ref(false)
const showAddModal = ref(false)
const savingRow = ref(false)
const editForm = ref<EnergyDataRecord>({
  timestamp: '',
  building_id: '',
  electricity_kwh: null,
  water_m3: null,
  hac_energy: null,
  sim_supply_temp_c: null,
  sim_return_temp_c: null,
  air_temp_c: null,
  dew_temp_c: null,
  humidity_rh_pct: null,
})

// 预览折叠
const showPreview = ref(false)

// ── Toast 通知 ────────────────────────────────────────────────
const toast = ref<{ msg: string; type: 'success' | 'error' | 'info' } | null>(null)
let toastTimer: ReturnType<typeof setTimeout> | null = null

function showToast(msg: string, type: 'success' | 'error' | 'info' = 'success', duration = 3000) {
  if (toastTimer) clearTimeout(toastTimer)
  toast.value = { msg, type }
  toastTimer = setTimeout(() => { toast.value = null }, duration)
}

// 知识库状态
const docFileInput = ref<HTMLInputElement | null>(null)
const isDraggingDoc = ref(false)
const uploadingDoc = ref(false)
const loadingDocs = ref(false)
const docError = ref('')
const docSuccess = ref('')
const documents = ref<RagDocument[]>([])
const parsingByDoc = ref<Record<string, boolean>>({})

// 轮询任务取消：每次触发解析都会生成一个 jobId；删除文档时把 jobId 标记失效，轮询下一轮立刻退出。
const pollJobIdByDoc = ref<Record<string, number>>({})
let pollJobCounter = 0

// 删除确认
interface DeleteConfirmState {
  message: string
  action: () => Promise<void>
  hasImport?: boolean       // 是否有已导入的 energy_data 数据
  importedRows?: number     // 已导入行数
  deleteEnergyData?: boolean // 是否同步删除 energy_data
}
const deleteConfirm = ref<DeleteConfirmState | null>(null)

// ── 生命周期 ─────────────────────────────────────────────────
onMounted(() => {
  loadDatasets()
  if (initialTab === 'knowledge') loadDocuments()
})

// ── 报表集成 ─────────────────────────────────────────────────
watch(selectedDataset, (ds) => {
  if (!ds) return
  setReportMeta({ title: `数据中心 — ${ds.original_name}` })

  registerSection({
    id: 'dc-dataset-info',
    title: '数据集信息',
    type: 'kpi',
    kpis: [
      { label: '文件名', value: ds.original_name },
      { label: '行数', value: ds.row_count?.toLocaleString() ?? '—' },
      { label: '列数', value: String(ds.column_count ?? '—') },
      { label: '文件类型', value: ds.file_type.toUpperCase() },
    ],
    order: 10,
  })

  const statsObj = ds.stats as Record<string, any>
  const statEntries = Object.entries(statsObj).filter(([k]) => !k.startsWith('_'))
  if (statEntries.length > 0) {
    registerSection({
      id: 'dc-stats',
      title: '数值统计',
      type: 'table',
      columns: [
        { key: 'col', label: '列名', align: 'left' },
        { key: 'min', label: '最小值', align: 'right' },
        { key: 'max', label: '最大值', align: 'right' },
        { key: 'mean', label: '均值', align: 'right' },
        { key: 'std', label: '标准差', align: 'right' },
        { key: 'median', label: '中位数', align: 'right' },
      ],
      rows: statEntries.map(([col, s]: [string, any]) => ({
        col,
        min: formatNum(s.min),
        max: formatNum(s.max),
        mean: formatNum(s.mean),
        std: formatNum(s.std),
        median: formatNum(s.median),
      })),
      order: 20,
    })
  }
})

watch(energyDataRecords, (records) => {
  if (!records.length) return
  registerSection({
    id: 'dc-energy-data',
    title: 'energy_data 数据',
    type: 'table',
    columns: [
      { key: 'timestamp', label: '时间戳', align: 'left' },
      { key: 'building_id', label: '楼宇ID', align: 'left' },
      { key: 'electricity_kwh', label: '电耗(kWh)', align: 'right' },
      { key: 'water_m3', label: '水耗(m³)', align: 'right' },
      { key: 'hac_energy', label: '空调(kWh)', align: 'right' },
      { key: 'air_temp_c', label: '室外℃', align: 'right' },
      { key: 'humidity_rh_pct', label: '湿度%', align: 'right' },
    ],
    rows: records.map(r => ({
      timestamp: formatTsShort(r.timestamp),
      building_id: r.building_id,
      electricity_kwh: formatNum(r.electricity_kwh),
      water_m3: formatNum(r.water_m3),
      hac_energy: formatNum(r.hac_energy),
      air_temp_c: formatNum(r.air_temp_c),
      humidity_rh_pct: formatNum(r.humidity_rh_pct),
    })),
    order: 30,
  })
})

watch(analysisResult, (text) => {
  if (!text) return
  registerSection({
    id: 'dc-ai-analysis',
    title: 'AI 分析结果',
    type: 'text',
    content: text,
    order: 40,
  })
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

const totalPages = computed(() => Math.max(1, Math.ceil(energyDataTotal.value / energyPageSize)))

// 过滤掉 _import 元信息键，只显示真实统计列
const previewStats = computed(() => {
  const s = selectedDataset.value?.stats ?? {}
  return Object.fromEntries(Object.entries(s).filter(([k]) => !k.startsWith('_')))
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
  importError.value = ''
  importSuccess.value = ''
  importMeta.value = null
  energyDataRecords.value = []
  energyDataTotal.value = 0
  energyPage.value = 1
  showPreview.value = false
  try {
    selectedDataset.value = await api.getDataset(id)
    // 检查是否已有导入记录（存储在 stats._import）
    const stats = selectedDataset.value.stats as Record<string, unknown>
    const prevImport = stats['_import'] as ImportResult | undefined
    if (prevImport?.imported_rows) {
      importMeta.value = prevImport
      await loadEnergyData()
    }
  } catch (e) {
    datasetError.value = (e as Error).message
  } finally {
    loadingDetail.value = false
  }
}

// ── 导入操作（SSE 流式） ─────────────────────────────────────
async function runImport() {
  if (!selectedDataset.value || importing.value) return
  importError.value = ''
  importSuccess.value = ''
  importProgress.value = 0
  importProgressMsg.value = '准备中...'
  importProcessed.value = 0
  importTotal.value = 0
  importing.value = true

  const stageLabel: Record<string, string> = {
    parsing:    '解析文件...',
    validating: '校验楼宇 ID...',
    preparing:  '预处理数据...',
    importing:  '批量写入数据库...',
  }

  await api.importDatasetToEnergyData(
    selectedDataset.value.id,
    (e) => {
      importProgress.value = e.progress
      importProgressMsg.value = e.msg ?? stageLabel[e.stage] ?? e.stage
      if (e.imported !== undefined) importProcessed.value = e.imported
      if (e.total    !== undefined) importTotal.value    = e.total
    },
    async (result) => {
      importMeta.value = result
      importProgress.value = 1
      importProgressMsg.value = '导入完成'
      importSuccess.value = `导入完成：成功 ${result.imported_rows.toLocaleString()} 条，失败 ${result.failed_rows} 条`
      if (result.invalid_building_ids?.length > 0) {
        importError.value = `以下楼宇 ID 不存在于 buildings 表，对应行已跳过：${result.invalid_building_ids.join(', ')}`
      }
      importing.value = false
      if (result.imported_rows > 0) {
        showCrud.value = true
        energyPage.value = 1
        await loadEnergyData()
      }
    },
    (err) => {
      importError.value = err
      importProgressMsg.value = '导入失败'
      importing.value = false
    },
  )
}

// ── energy_data CRUD ─────────────────────────────────────────
async function loadEnergyData() {
  if (!importMeta.value?.building_ids?.length) return
  loadingEnergyData.value = true
  try {
    const res = await api.listEnergyData(
      importMeta.value.building_ids,
      importMeta.value.min_ts!,
      importMeta.value.max_ts!,
      energyPage.value,
      energyPageSize,
    )
    energyDataRecords.value = res.records
    energyDataTotal.value = res.total
  } catch (e) {
    importError.value = (e as Error).message
  } finally {
    loadingEnergyData.value = false
  }
}

async function changePage(p: number) {
  energyPage.value = p
  await loadEnergyData()
}

function openAddModal() {
  editForm.value = {
    timestamp: new Date().toISOString(),
    building_id: importMeta.value?.building_ids?.[0] ?? '',
    electricity_kwh: null,
    water_m3: null,
    hac_energy: null,
    sim_supply_temp_c: null,
    sim_return_temp_c: null,
    air_temp_c: null,
    dew_temp_c: null,
    humidity_rh_pct: null,
  }
  showAddModal.value = true
}

function openEditModal(row: EnergyDataRecord) {
  editForm.value = { ...row }
  showEditModal.value = true
}

function closeDataModal() {
  showEditModal.value = false
  showAddModal.value = false
}

async function submitDataModal() {
  savingRow.value = true
  try {
    if (showAddModal.value) {
      await api.createEnergyDataRow(editForm.value)
      importSuccess.value = '记录已新增'
    } else {
      await api.updateEnergyDataRow(editForm.value)
      importSuccess.value = '记录已更新'
    }
    closeDataModal()
    await loadEnergyData()
  } catch (e) {
    importError.value = (e as Error).message
  } finally {
    savingRow.value = false
  }
}

function confirmDeleteRow(row: EnergyDataRecord) {
  deleteConfirm.value = {
    message: `确认删除 ${formatTsShort(row.timestamp)}（${row.building_id}）的记录？`,
    action: async () => {
      await api.deleteEnergyDataRow(row.timestamp, row.building_id)
      showToast('记录已删除')
      await loadEnergyData()
    },
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

  // 尝试从当前选中的数据集或 importMeta 中读取已导入行数（仅用于显示提示）
  // 不用于决定是否删除——始终由后端判断
  let importedRows = 0
  let hasImport = false
  if (selectedDataset.value?.id === id) {
    const imp = (selectedDataset.value.stats as Record<string, unknown>)?.['_import'] as { imported_rows?: number } | undefined
    importedRows = imp?.imported_rows ?? 0
    hasImport = importedRows > 0
  } else if (importMeta.value?.imported_rows) {
    // 当前 importMeta 可能属于同一个已选中但未展示统计的数据集
    importedRows = importMeta.value.imported_rows
    hasImport = true
  }

  deleteConfirm.value = {
    message: `确认删除数据集「${ds?.original_name}」？此操作不可恢复。`,
    hasImport,
    importedRows,
    deleteEnergyData: true,   // ★ 始终默认为 true，让后端自行判断
    action: async () => {
      const doDeleteEnergy = deleteConfirm.value?.deleteEnergyData ?? true
      const res = await api.deleteDataset(id, doDeleteEnergy)
      datasets.value = datasets.value.filter(d => d.id !== id)
      if (selectedDataset.value?.id === id) {
        selectedDataset.value = null
        analysisResult.value = ''
        importMeta.value = null
        energyDataRecords.value = []
        energyDataTotal.value = 0
      }
      showToast(res?.message ?? '数据集已删除')
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
    const uploadRes = await api.uploadDocument(file)
    const docId = extractDocIdFromUpload(uploadRes, file.name)
    if (docId) {
      docSuccess.value = `「${file.name}」已上传，正在后台解析...`
      // 不阻塞上传 UI：上传完成后直接后台触发轮询直到 Done/失败
      void triggerParse(docId, { auto: true })
    } else {
      docSuccess.value = `「${file.name}」已上传，需点击"解析"按钮进行向量化`
    }

    // 上传成功后不阻塞等待列表刷新；列表刷新只为更新表格展示
    void loadDocuments()
  } catch (e) {
    docError.value = (e as Error).message
  } finally {
    uploadingDoc.value = false
  }
}

async function triggerParse(docId: string, opts?: { auto?: boolean }) {
  if (parsingByDoc.value[docId]) return
  parsingByDoc.value[docId] = true
  pollJobCounter += 1
  const jobId = pollJobCounter
  pollJobIdByDoc.value[docId] = jobId
  docError.value = ''
  try {
    // 乐观更新：让用户立刻看到“解析中”，并禁用重复点击
    const idx = documents.value.findIndex(d => d.id === docId)
    if (idx !== -1) {
      documents.value[idx] = {
        ...documents.value[idx],
        run: 'running',
        progress: Math.max(documents.value[idx].progress ?? 0, 0.01),
      }
    }

    await api.parseDocument(docId)
    // 删除发生在 parseDocument 之后：避免继续轮询导致页面反复刷新
    if (pollJobIdByDoc.value[docId] !== jobId) return
    docSuccess.value = opts?.auto ? '已提交解析任务，正在后台解析...' : '已提交解析任务，正在后台解析...'
    await pollDocStatus(docId, jobId)
  } catch (e) {
    docError.value = (e as Error).message
    await loadDocuments()
  } finally {
    parsingByDoc.value[docId] = false
  }
}

function confirmDeleteDoc(docId: string, name: string) {
  deleteConfirm.value = {
    message: `确认从知识库删除文档「${name}」？`,
    action: async () => {
      // 立刻取消该文档的轮询，避免删除后页面持续刷新（轮询里会触发 loadDocuments）
      pollJobIdByDoc.value[docId] = -1
      await api.deleteDocument(docId)
      documents.value = documents.value.filter(d => d.id !== docId)
      showToast('文档已删除')
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

function formatTsShort(iso: string): string {
  if (!iso) return '—'
  try {
    const d = new Date(iso)
    return `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}-${String(d.getDate()).padStart(2,'0')} ${String(d.getHours()).padStart(2,'0')}:00`
  } catch {
    return iso.slice(0, 16)
  }
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
  const key = getRunKey(run)
  const map: Record<string, string> = {
    unstart: 'status-idle',
    running: 'status-running',
    done: 'status-done',
    fail: 'status-fail',
    CANCEL: 'status-cancel',
  }
  return map[key] ?? 'status-idle'
}

function getStatusIcon(run: string): string {
  const key = getRunKey(run)
  const map: Record<string, string> = {
    unstart: 'mdi:clock-outline',
    running: 'mdi:loading',
    done: 'mdi:check-circle-outline',
    fail: 'mdi:alert-circle-outline',
    CANCEL: 'mdi:cancel',
  }
  return map[key] ?? 'mdi:clock-outline'
}

function getStatusLabel(run: string): string {
  const key = getRunKey(run)
  const map: Record<string, string> = {
    unstart: '待解析',
    running: '解析中',
    done: '已完成',
    fail: '解析失败',
    CANCEL: '已取消',
  }
  return map[key] ?? run
}

function getRunKey(run: string): 'unstart' | 'running' | 'done' | 'fail' | 'CANCEL' {
  const r = (run ?? '').toString().trim()
  const upper = r.toUpperCase()
  if (upper === 'CANCEL') return 'CANCEL'
  const lower = r.toLowerCase()
  if (lower === 'unstart' || lower === 'running' || lower === 'done' || lower === 'fail') return lower as any
  return 'unstart'
}

function isFinalRunKey(key: string): boolean {
  return key === 'done' || key === 'fail' || key === 'CANCEL'
}

function extractDocIdFromUpload(uploadRes: api.RagUploadResponse | unknown, fileName?: string): string | null {
  const findId = (obj: any, visited: WeakSet<object>): string | null => {
    if (!obj || typeof obj !== 'object') return null
    if (visited.has(obj)) return null
    visited.add(obj)

    if (typeof obj.id === 'string') {
      if (!fileName) return obj.id
      if (typeof obj.name === 'string' && obj.name === fileName) return obj.id
    }

    // 递归扫描：兼容 RAGFlow 返回的 data/data.docs 等形态
    for (const v of Object.values(obj)) {
      const got = findId(v, visited)
      if (got) return got
    }
    return null
  }

  const root = uploadRes as any
  // 先尝试常见形态 data:[{id,...}] / data:{id,...}
  const data = root?.data ?? root
  if (Array.isArray(data)) return data?.[0]?.id ?? null
  if (data && typeof data === 'object' && typeof data.id === 'string') return data.id

  return findId(data, new WeakSet()) ?? (typeof root?.id === 'string' ? root.id : null)
}

function sleep(ms: number): Promise<void> {
  return new Promise(resolve => setTimeout(resolve, ms))
}

async function pollDocStatus(docId: string, jobId: number) {
  const intervalMs = 2000
  const timeoutMs = 900000 // 15 分钟轮询：RAGFlow 解析有时会较慢，避免“卡在中间态后需手动刷新”
  const startedAt = Date.now()
  let errorCount = 0
  const maxErrorCount = 10
  let lastListRefreshAt = 0
  const listRefreshIntervalMs = 15000
  let finalRunKey: string = 'unstart'
  let finalProgress: number | null = null

  while (Date.now() - startedAt < timeoutMs) {
    // 删除后标记失效：立刻退出，避免持续触发 loadDocuments
    if (pollJobIdByDoc.value[docId] !== jobId) return

    let status: api.RagDocumentStatus
    try {
      status = await api.getDocumentStatus(docId)
      errorCount = 0
    } catch (e) {
      errorCount++
      // 解析过程中偶发网络/网关问题不应终止轮询
      if (errorCount >= maxErrorCount) break
      await sleep(Math.min(10000, intervalMs * errorCount))
      continue
    }

    const runKey = getRunKey(status.run ?? '')
    finalRunKey = runKey
    finalProgress = status.progress ?? null

    const idx = documents.value.findIndex(d => d.id === docId)
    if (idx !== -1) {
      documents.value[idx] = {
        ...documents.value[idx],
        run: runKey,
        progress: status.progress ?? documents.value[idx].progress,
        update_time: status.update_time ?? documents.value[idx].update_time,
      }
    } else {
      // 如果当前列表还没包含该 doc，避免“删除后轮询不断触发刷新”
      const now = Date.now()
      if (now - lastListRefreshAt >= listRefreshIntervalMs) {
        if (pollJobIdByDoc.value[docId] !== jobId) return
        lastListRefreshAt = now
        await loadDocuments()
      }
    }

    if (isFinalRunKey(runKey)) break
    await sleep(intervalMs)
  }

  if (pollJobIdByDoc.value[docId] !== jobId) return

  // 轮询结束时更新顶部提示文案，避免用户看到“正在后台解析..”但已解析完成
  const doc = documents.value.find(d => d.id === docId)
  const docName = doc?.name ?? docId
  if (finalRunKey === 'done') {
    docSuccess.value = `「${docName}」已解析完成`
  } else if (finalRunKey === 'fail') {
    docError.value = `「${docName}」解析失败`
  } else if (finalRunKey === 'CANCEL') {
    docSuccess.value = `「${docName}」解析已取消`
  }

  await loadDocuments()
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
/* ── Light 主题下覆盖深绿变量，改为浅色卡片风格 ── */
html[data-theme="light"] .datacenter {
  --bg-panel:       #f5f5f5;
  --bg-card:        #ffffff;
  --bg-hover:       #f0f4f2;
  --border:         #d9dce0;
  --text-primary:   #1a1a1a;
  --text-secondary: #5f6368;
  --text-muted:     #9aa0a6;
  --accent-glow:    rgba(34,197,94,0.10);
  --border-accent:  rgba(34,197,94,0.25);
}

.datacenter {
  height: 100%;
  overflow-y: auto;
  padding: 24px;
  display: flex;
  flex-direction: column;
  gap: 20px;
}

/* ── 页面标题 ── */
.page-header {
  display: flex;
  flex-direction: row;
  align-items: center;
  justify-content: space-between;
}
.page-header-left { display: flex; flex-direction: column; gap: 4px; }
.page-title {
  display: flex;
  align-items: center;
  gap: 10px;
  font-size: 18px;
  font-weight: 600;
  color: #1a1a1a;
}
.title-icon { color: var(--accent); }
.page-desc { font-size: 12px; color: #555; margin-left: 32px; }

/* ── Tab 切换 ── */
.tab-bar {
  display: flex;
  gap: 4px;
  background: #f0f0f0;
  border: 1px solid #ddd;
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
  color: #555;
  font-size: 13px;
  cursor: pointer;
  transition: all 0.18s;
}
.tab-btn:hover { color: #000; background: #e0e0e0; }
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
.detail-title-row { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
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

/* ── 详情操作按钮组 ── */
.detail-actions { display: flex; gap: 8px; align-items: center; }

/* ── 导入按钮 ── */
.import-btn {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 7px 14px;
  border-radius: 8px;
  border: 1px solid #3b82f6;
  background: rgba(59,130,246,0.08);
  color: #3b82f6;
  font-size: 13px;
  cursor: pointer;
  transition: all 0.18s;
}
.import-btn:hover:not(:disabled) { background: #3b82f6; color: #fff; }
.import-btn:disabled { opacity: 0.6; cursor: not-allowed; }

/* ── AI 分析按钮 ── */
.analyze-btn {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 7px 14px;
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

/* ── 已导入徽章 ── */
.imported-badge {
  background: rgba(34,197,94,0.12) !important;
  color: #22c55e !important;
  border-color: rgba(34,197,94,0.3) !important;
  display: inline-flex;
  align-items: center;
  gap: 4px;
}

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
  display: flex;
  gap: 8px;
  overflow-x: auto;
  padding-bottom: 6px;
}
.col-card {
  background: var(--bg-panel);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 10px 12px;
  display: flex;
  flex-direction: column;
  gap: 4px;
  min-width: 140px;
  max-width: 180px;
  flex-shrink: 0;
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
  font-size: 12px;
  font-weight: 600;
}
.status-idle { background: rgba(107,122,154,0.12); color: var(--text-secondary); }
.status-running { background: rgba(96,165,250,0.12); color: var(--accent); }
.status-done { background: rgba(34,197,94,0.22); color: #22c55e; border: 1px solid rgba(34,197,94,0.35); }
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

/* ── 导入进度条 ── */
.import-progress-wrap {
  border: 1px solid var(--border-accent);
  border-radius: 10px;
  background: var(--accent-glow);
  padding: 12px 14px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.import-progress-header {
  display: flex;
  align-items: center;
  gap: 7px;
  font-size: 12px;
  color: var(--accent);
  font-weight: 500;
}
.import-count {
  margin-left: auto;
  font-size: 11px;
  color: var(--text-secondary);
  font-weight: 400;
  font-variant-numeric: tabular-nums;
}
.import-progress-track {
  height: 6px;
  background: var(--border);
  border-radius: 3px;
  overflow: hidden;
}
.import-progress-bar {
  height: 100%;
  background: var(--accent);
  border-radius: 3px;
  transition: width 0.3s ease;
}
.import-progress-pct {
  font-size: 11px;
  color: var(--accent);
  text-align: right;
  font-variant-numeric: tabular-nums;
  font-weight: 600;
}

/* ── 预览折叠区 ── */
.preview-section {
  border: 1px solid var(--border);
  border-radius: 10px;
  overflow: hidden;
}
.preview-toggle {
  width: 100%;
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 14px;
  background: var(--bg-panel);
  border: none;
  cursor: pointer;
  font-size: 13px;
  font-weight: 600;
  color: var(--text-secondary);
  transition: background 0.15s;
  text-align: left;
}
.preview-toggle:hover { background: var(--bg-hover); color: var(--text-primary); }
.preview-sub {
  font-size: 11px;
  font-weight: 400;
  color: var(--text-muted);
  margin-left: 4px;
}
.preview-section .section { padding: 14px 14px 0; }
.preview-section .col-grid { padding: 0 14px; }
.preview-section .stats-table-wrap,
.preview-section .sample-table-wrap { margin: 0 14px 14px; }

/* ── CRUD 区域 ── */
.crud-section {
  border: 1px solid var(--border);
  border-radius: 10px;
  overflow: hidden;
  background: var(--bg-card);
}
.crud-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 10px 14px;
  border-bottom: 1px solid var(--border);
  background: var(--bg-panel);
}
.crud-toggle-icon {
  color: var(--text-muted);
  transition: color 0.15s;
  flex-shrink: 0;
}
.crud-header:hover .crud-toggle-icon { color: var(--accent); }
.crud-title {
  display: flex;
  align-items: center;
  gap: 7px;
  font-size: 13px;
  font-weight: 600;
  color: var(--text-primary);
}
.crud-total {
  font-size: 11px;
  font-weight: 400;
  color: var(--text-muted);
  margin-left: 4px;
}
.crud-actions { display: flex; gap: 6px; }
.crud-btn {
  display: flex;
  align-items: center;
  gap: 5px;
  padding: 5px 12px;
  border-radius: 6px;
  border: 1px solid var(--border);
  font-size: 12px;
  cursor: pointer;
  transition: all 0.15s;
  background: var(--bg-card);
  color: var(--text-secondary);
}
.crud-btn:hover:not(:disabled) { background: var(--bg-hover); color: var(--text-primary); }
.crud-btn:disabled { opacity: 0.5; cursor: not-allowed; }
.add-btn { color: var(--accent); border-color: var(--border-accent); background: var(--accent-glow); }
.add-btn:hover:not(:disabled) { background: var(--accent); color: #fff; }

.crud-loading {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 20px;
  color: var(--text-muted);
  font-size: 13px;
  justify-content: center;
}

/* ── CRUD 数据表格 ── */
.crud-table-wrap { overflow-x: auto; }
.crud-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 12px;
  min-width: 900px;
}
.crud-table th {
  padding: 8px 10px;
  background: var(--bg-panel);
  color: var(--text-secondary);
  font-weight: 600;
  text-align: left;
  border-bottom: 1px solid var(--border);
  white-space: nowrap;
  position: sticky;
  top: 0;
  z-index: 1;
}
.crud-table td {
  padding: 7px 10px;
  color: var(--text-primary);
  border-bottom: 1px solid var(--border);
  white-space: nowrap;
}
.crud-table tr:last-child td { border-bottom: none; }
.crud-table tr.data-row:hover td { background: var(--bg-hover); }

.col-ts { min-width: 130px; }
.col-bid { min-width: 110px; }
.col-num { min-width: 80px; text-align: right; }
.col-num td { text-align: right; font-variant-numeric: tabular-nums; }
.col-actions { min-width: 70px; text-align: center; }

.ts-cell { color: var(--text-secondary); font-size: 11px; }
.bid-badge {
  display: inline-block;
  padding: 2px 7px;
  border-radius: 4px;
  background: var(--accent-glow);
  color: var(--accent);
  font-size: 11px;
  font-weight: 500;
  max-width: 100px;
  overflow: hidden;
  text-overflow: ellipsis;
}

.empty-row { text-align: center; padding: 24px; color: var(--text-muted); }

.row-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 26px;
  height: 26px;
  border-radius: 5px;
  border: none;
  background: transparent;
  cursor: pointer;
  transition: all 0.15s;
  color: var(--text-muted);
}
.row-btn + .row-btn { margin-left: 3px; }
.edit-row:hover { background: var(--accent-glow); color: var(--accent); }
.del-row:hover { background: rgba(248,113,113,0.1); color: var(--danger); }

/* ── 分页 ── */
.pagination {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 10px 14px;
  border-top: 1px solid var(--border);
  background: var(--bg-panel);
}
.page-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 28px;
  height: 28px;
  border-radius: 6px;
  border: 1px solid var(--border);
  background: var(--bg-card);
  cursor: pointer;
  color: var(--text-secondary);
  transition: all 0.15s;
}
.page-btn:hover:not(:disabled) { background: var(--bg-hover); color: var(--text-primary); }
.page-btn:disabled { opacity: 0.4; cursor: not-allowed; }
.page-info { font-size: 12px; color: var(--text-secondary); min-width: 60px; text-align: center; }
.page-size-info { font-size: 11px; color: var(--text-muted); margin-left: 4px; }

/* ── 编辑/新增弹窗 ── */
.data-modal {
  background: var(--bg-panel);
  border: 1px solid var(--border);
  border-radius: 14px;
  width: 560px;
  max-width: 95vw;
  max-height: 85vh;
  overflow-y: auto;
  box-shadow: var(--panel-shadow);
}
.data-modal-header {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 16px 20px;
  border-bottom: 1px solid var(--border);
  font-size: 14px;
  font-weight: 600;
  color: var(--text-primary);
}
.modal-close {
  margin-left: auto;
  width: 28px;
  height: 28px;
  display: flex;
  align-items: center;
  justify-content: center;
  border: none;
  background: transparent;
  cursor: pointer;
  border-radius: 6px;
  color: var(--text-muted);
  transition: all 0.15s;
}
.modal-close:hover { background: var(--bg-hover); color: var(--danger); }
.data-modal-body { padding: 16px 20px; display: flex; flex-direction: column; gap: 12px; }
.form-row {
  display: flex;
  align-items: center;
  gap: 10px;
}
.form-row label {
  width: 80px;
  font-size: 12px;
  color: var(--text-secondary);
  flex-shrink: 0;
}
.form-row input {
  flex: 1;
  padding: 7px 10px;
  border-radius: 7px;
  border: 1px solid var(--border);
  background: var(--bg-card);
  color: var(--text-primary);
  font-size: 13px;
  outline: none;
  transition: border 0.15s;
}
.form-row input:focus { border-color: var(--accent); }
.form-row input:disabled { opacity: 0.6; cursor: not-allowed; }
.form-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 10px;
}
.form-field label {
  display: block;
  font-size: 11px;
  color: var(--text-secondary);
  margin-bottom: 4px;
}
.form-field input {
  width: 100%;
  padding: 7px 10px;
  border-radius: 7px;
  border: 1px solid var(--border);
  background: var(--bg-card);
  color: var(--text-primary);
  font-size: 13px;
  outline: none;
  box-sizing: border-box;
  transition: border 0.15s;
}
.form-field input:focus { border-color: var(--accent); }
.data-modal-footer {
  display: flex;
  gap: 10px;
  padding: 14px 20px;
  border-top: 1px solid var(--border);
  justify-content: flex-end;
}

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

/* ── 删除选项（同步清除 energy_data） ── */
.delete-energy-opt {
  width: 100%;
  background: rgba(248,113,113,0.07);
  border: 1px solid rgba(248,113,113,0.2);
  border-radius: 8px;
  padding: 10px 12px;
  display: flex;
  flex-direction: column;
  gap: 5px;
}
.opt-label {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  font-size: 13px;
  color: var(--text-primary);
  cursor: pointer;
}
.opt-label input[type="checkbox"] {
  margin-top: 2px;
  accent-color: var(--danger);
  flex-shrink: 0;
}
.opt-hint {
  font-size: 11px;
  color: var(--text-muted);
  margin-left: 20px;
}

/* ── 动画 ── */
.spin { animation: spin 1s linear infinite; }
@keyframes spin { from { transform: rotate(0deg); } to { transform: rotate(360deg); } }

/* ── 全局 Toast ── */
.global-toast {
  position: fixed;
  top: 32px;
  left: 50%;
  transform: translateX(-50%);
  z-index: 9999;
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 20px;
  border-radius: 8px;
  font-size: 14px;
  font-weight: 500;
  box-shadow: 0 4px 16px rgba(0,0,0,.18);
  white-space: nowrap;
  pointer-events: none;
}
.toast-success { background: #18a058; color: #fff; }
.toast-error   { background: #d03050; color: #fff; }
.toast-info    { background: #2080f0; color: #fff; }

.toast-enter-active, .toast-leave-active { transition: opacity .3s, transform .3s; }
.toast-enter-from, .toast-leave-to       { opacity: 0; transform: translateX(-50%) translateY(-12px); }
</style>
