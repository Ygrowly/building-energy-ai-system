<template>
  <div class="experience-workbench">
    <div class="experience-head">
      <div>
        <h2 class="experience-title">
          <Icon icon="mdi:book-open-page-variant-outline" width="18" />
          经验库闭环
        </h2>
        <p class="experience-subtitle">支持运小维经验查询、人工沉淀经验和对经验结果做反馈。</p>
      </div>
      <div class="experience-head-actions">
        <button class="ghost-btn" :disabled="searchLoading" @click="loadRecent">
          {{ searchLoading ? '加载中...' : '加载最近经验' }}
        </button>
      </div>
    </div>

    <div v-if="notice" class="experience-notice" :class="notice.type">{{ notice.message }}</div>

    <div class="experience-grid">
      <section class="experience-panel">
        <div class="panel-head">
          <div>
            <h3>运小维经验查询</h3>
            <p>支持按问题描述、楼宇、设备类型和故障类型组合检索。</p>
          </div>
        </div>

        <div class="quick-query-row">
          <button
            v-for="prompt in quickPrompts"
            :key="prompt"
            class="quick-query-chip"
            :disabled="searchLoading"
            @click="runQuickPrompt(prompt)"
          >
            {{ prompt }}
          </button>
        </div>

        <div class="query-form">
          <input v-model.trim="query" class="field" placeholder="输入经验问题，如：类似空调效率异常怎么处理" />
          <div class="inline-fields">
            <input v-model.trim="buildingId" class="field" placeholder="楼宇 ID" />
            <input v-model.trim="deviceType" class="field" placeholder="设备类型" />
            <input v-model.trim="faultType" class="field" placeholder="故障类型" />
          </div>
          <div class="inline-fields">
            <select v-model="sortBy" class="field select-field">
              <option value="score">按匹配度</option>
              <option value="recent">按最近</option>
              <option value="usage">按引用量</option>
            </select>
            <button class="primary-btn" :disabled="searchLoading" @click="runSearch">
              {{ searchLoading ? '查询中...' : '查询经验' }}
            </button>
          </div>
        </div>

        <div v-if="searchError" class="inline-error">{{ searchError }}</div>
        <div v-else-if="!searchLoading && experiences.length === 0" class="empty-state">
          暂无符合条件的经验记录。
        </div>

        <div v-else class="experience-list">
          <article v-for="item in experiences" :key="item.id" class="experience-card">
            <div class="experience-card-head">
              <div>
                <h4>{{ item.organized_text || item.source_text || '经验记录' }}</h4>
                <p class="experience-meta">
                  来源 {{ item.source_work_order_id || item.source_type || '未知' }}
                  <span v-if="item.score != null"> · 匹配 {{ formatScore(item.score) }}</span>
                  <span v-if="item.vector_index_status"> · 索引 {{ item.vector_index_status }}</span>
                </p>
              </div>
              <span class="experience-status" :class="{ inactive: item.is_active === false }">
                {{ item.is_active === false ? '已停用' : '启用中' }}
              </span>
            </div>

            <div v-if="item.suggested_steps?.length" class="experience-copy">
              建议：{{ item.suggested_steps.join('；') }}
            </div>
            <div v-if="item.safety_notes?.length" class="experience-copy warn">
              注意：{{ item.safety_notes.join('；') }}
            </div>
            <div v-if="item.conflict_flags?.length" class="experience-copy risk">
              风险：{{ item.conflict_flags.map(flag => flag.message).filter(Boolean).join('；') }}
            </div>

            <div class="experience-tags" v-if="item.applicable_conditions?.length">
              <span v-for="condition in item.applicable_conditions" :key="condition" class="tag">{{ condition }}</span>
            </div>

            <div class="experience-card-footer">
              <span class="experience-stats">
                有用 {{ item.helpful_count || 0 }} · 无帮助 {{ item.unhelpful_count || 0 }} · 不准确 {{ item.incorrect_count || 0 }} · 复用 {{ item.usage_count || 0 }}
              </span>
              <div class="feedback-actions">
                <button
                  class="feedback-btn"
                  :class="{ active: feedbackState[item.id] === 'helpful' }"
                  :disabled="feedbackLoading[item.id] === 'helpful'"
                  @click="submitFeedback(item, 'helpful')"
                >
                  有帮助
                </button>
                <button
                  class="feedback-btn"
                  :class="{ active: feedbackState[item.id] === 'unhelpful' }"
                  :disabled="feedbackLoading[item.id] === 'unhelpful'"
                  @click="submitFeedback(item, 'unhelpful')"
                >
                  无帮助
                </button>
                <button
                  class="feedback-btn danger"
                  :class="{ active: feedbackState[item.id] === 'incorrect' }"
                  :disabled="feedbackLoading[item.id] === 'incorrect'"
                  @click="submitFeedback(item, 'incorrect')"
                >
                  不准确
                </button>
              </div>
            </div>
          </article>
        </div>
      </section>

      <section class="experience-panel">
        <div class="panel-head">
          <div>
            <h3>人工新增经验</h3>
            <p>适合运维管理员手动补充运小维和维小修尚未自动沉淀的经验。</p>
          </div>
        </div>

        <div class="create-form">
          <select v-model="form.source_type" class="field select-field">
            <option value="operator_note">运维备注</option>
            <option value="worker_note">维修备注</option>
            <option value="completion_summary">完工总结</option>
            <option value="step_event">步骤事件</option>
          </select>

          <div class="inline-fields">
            <input v-model.trim="form.source_work_order_id" class="field" placeholder="工单 ID（可选）" />
            <input v-model.trim="form.source_dispatch_id" class="field" placeholder="派工 ID（可选）" />
          </div>

          <div class="inline-fields">
            <input v-model.trim="form.building_id" class="field" placeholder="楼宇 ID" />
            <input v-model.trim="form.device_id" class="field" placeholder="设备 ID" />
          </div>

          <div class="inline-fields">
            <input v-model.trim="form.device_type" class="field" placeholder="设备类型" />
            <input v-model.trim="form.fault_type" class="field" placeholder="故障类型" />
          </div>

          <textarea
            v-model.trim="form.source_text"
            class="textarea-field"
            rows="8"
            placeholder="输入经验正文，建议包含：故障现象、判断依据、处理动作、安全注意事项。"
          />

          <div class="submit-row">
            <button class="primary-btn" :disabled="createLoading" @click="submitCreate">
              {{ createLoading ? '提交中...' : '新增经验' }}
            </button>
          </div>
        </div>
      </section>
    </div>
  </div>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { Icon } from '@iconify/vue'
import {
  maintenanceExperienceApi,
  type MaintenanceExperienceFeedbackType,
  type MaintenanceExperienceItem,
  type MaintenanceExperienceSourceType,
} from '@/api/maintenanceExperience'

const quickPrompts = [
  '最近有哪些空调效率异常处理经验',
  '类似传感器读数异常通常怎么排查',
  '哪些经验被复用最多',
]

const query = ref('')
const buildingId = ref('')
const deviceType = ref('')
const faultType = ref('')
const sortBy = ref<'score' | 'recent' | 'usage'>('score')
const searchLoading = ref(false)
const searchError = ref('')
const createLoading = ref(false)
const experiences = ref<MaintenanceExperienceItem[]>([])
const notice = ref<{ type: 'success' | 'error' | 'info'; message: string } | null>(null)
const feedbackLoading = reactive<Record<string, string>>({})
const feedbackState = reactive<Record<string, MaintenanceExperienceFeedbackType | ''>>({})

const form = reactive<{
  source_type: MaintenanceExperienceSourceType
  source_text: string
  source_work_order_id: string
  source_dispatch_id: string
  building_id: string
  device_id: string
  device_type: string
  fault_type: string
}>({
  source_type: 'operator_note',
  source_text: '',
  source_work_order_id: '',
  source_dispatch_id: '',
  building_id: '',
  device_id: '',
  device_type: '',
  fault_type: '',
})

function setNotice(message: string, type: 'success' | 'error' | 'info' = 'success') {
  notice.value = { message, type }
}

function formatScore(score: number | null | undefined) {
  if (score == null || Number.isNaN(Number(score))) return '--'
  return `${Math.round(Math.max(0, Math.min(1, Number(score))) * 100)}%`
}

async function runSearch() {
  searchLoading.value = true
  searchError.value = ''
  try {
    const response = await maintenanceExperienceApi.search({
      query: query.value || null,
      building_id: buildingId.value || null,
      device_type: deviceType.value || null,
      fault_type: faultType.value || null,
      sort_by: sortBy.value,
      limit: 8,
    })
    experiences.value = response.items || []
    setNotice(`已返回 ${response.total} 条经验记录`, 'info')
  } catch (error) {
    searchError.value = error instanceof Error ? error.message : '经验查询失败'
    setNotice(searchError.value, 'error')
  } finally {
    searchLoading.value = false
  }
}

async function runQuickPrompt(prompt: string) {
  query.value = prompt
  await runSearch()
}

async function loadRecent() {
  sortBy.value = 'recent'
  await runSearch()
}

async function submitCreate() {
  if (!form.source_text.trim()) {
    setNotice('请先输入经验正文', 'error')
    return
  }
  createLoading.value = true
  try {
    const response = await maintenanceExperienceApi.create({
      source_type: form.source_type,
      source_text: form.source_text.trim(),
      source_work_order_id: form.source_work_order_id || null,
      source_dispatch_id: form.source_dispatch_id || null,
      building_id: form.building_id || null,
      device_id: form.device_id || null,
      device_type: form.device_type || null,
      fault_type: form.fault_type || null,
    })
    form.source_text = ''
    setNotice(response.status === 'existing' ? '经验已存在，未重复入库' : '经验已新增并进入索引', 'success')
    await loadRecent()
  } catch (error) {
    setNotice(error instanceof Error ? error.message : '新增经验失败', 'error')
  } finally {
    createLoading.value = false
  }
}

async function submitFeedback(item: MaintenanceExperienceItem, feedback: MaintenanceExperienceFeedbackType) {
  if (!item.id) return
  feedbackLoading[item.id] = feedback
  try {
    const response = await maintenanceExperienceApi.feedback(item.id, {
      feedback,
      work_order_id: item.source_work_order_id || null,
    })
    item.helpful_count = response.helpful_count
    item.unhelpful_count = response.unhelpful_count
    item.incorrect_count = response.incorrect_count
    feedbackState[item.id] = feedback
    setNotice('经验反馈已记录', 'success')
  } catch (error) {
    setNotice(error instanceof Error ? error.message : '经验反馈失败', 'error')
  } finally {
    feedbackLoading[item.id] = ''
  }
}

onMounted(() => {
  void loadRecent()
})
</script>

<style scoped>
.experience-workbench {
  display: grid;
  gap: 16px;
}

.experience-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
}

.experience-title {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  margin: 0;
  font-size: 15px;
  font-weight: 700;
  color: var(--text-primary);
}

.experience-subtitle {
  margin: 6px 0 0;
  font-size: 12px;
  color: var(--text-muted);
}

.experience-head-actions {
  flex-shrink: 0;
}

.experience-notice {
  padding: 10px 12px;
  border-radius: 10px;
  font-size: 12px;
}

.experience-notice.success {
  background: rgba(34, 197, 94, 0.1);
  border: 1px solid rgba(34, 197, 94, 0.18);
  color: #166534;
}

.experience-notice.error {
  background: rgba(248, 113, 113, 0.08);
  border: 1px solid rgba(248, 113, 113, 0.18);
  color: var(--danger);
}

.experience-notice.info {
  background: rgba(59, 130, 246, 0.08);
  border: 1px solid rgba(59, 130, 246, 0.16);
  color: var(--accent);
}

.experience-grid {
  display: grid;
  grid-template-columns: minmax(0, 1.2fr) minmax(320px, 0.8fr);
  gap: 16px;
}

.experience-panel {
  padding: 16px;
  border-radius: 14px;
  background: var(--bg-panel);
  border: 1px solid var(--border);
  box-shadow: var(--card-shadow);
}

.panel-head h3 {
  margin: 0;
  font-size: 14px;
  font-weight: 700;
  color: var(--text-primary);
}

.panel-head p {
  margin: 6px 0 0;
  font-size: 12px;
  color: var(--text-muted);
}

.quick-query-row,
.inline-fields,
.feedback-actions,
.submit-row,
.experience-head-actions {
  display: flex;
  gap: 10px;
  flex-wrap: wrap;
}

.quick-query-row {
  margin-top: 14px;
}

.quick-query-chip,
.feedback-btn,
.ghost-btn,
.primary-btn {
  border: 1px solid var(--border);
  border-radius: 999px;
  background: transparent;
  color: var(--text-secondary);
  font-size: 12px;
  font-weight: 600;
  padding: 8px 14px;
  cursor: pointer;
  transition: all 0.18s ease;
}

.quick-query-chip:hover,
.ghost-btn:hover,
.feedback-btn:hover {
  border-color: rgba(59, 130, 246, 0.28);
  color: var(--accent);
  background: rgba(59, 130, 246, 0.06);
}

.primary-btn {
  border-color: rgba(34, 197, 94, 0.2);
  background: linear-gradient(135deg, rgba(34, 197, 94, 0.16), rgba(132, 204, 22, 0.12));
  color: #166534;
}

.primary-btn:hover {
  border-color: rgba(34, 197, 94, 0.28);
  background: linear-gradient(135deg, rgba(34, 197, 94, 0.22), rgba(132, 204, 22, 0.18));
}

.feedback-btn.active {
  background: rgba(34, 197, 94, 0.12);
  border-color: rgba(34, 197, 94, 0.24);
  color: #166534;
}

.feedback-btn.danger.active {
  background: rgba(248, 113, 113, 0.1);
  border-color: rgba(248, 113, 113, 0.2);
  color: var(--danger);
}

.query-form,
.create-form,
.experience-list {
  display: grid;
  gap: 12px;
  margin-top: 14px;
}

.field,
.textarea-field {
  width: 100%;
  box-sizing: border-box;
  border-radius: 10px;
  border: 1px solid var(--border);
  background: rgba(255, 255, 255, 0.84);
  color: var(--text-primary);
  font-size: 13px;
  padding: 10px 12px;
}

.textarea-field {
  resize: vertical;
  min-height: 180px;
  line-height: 1.6;
}

.select-field {
  appearance: none;
}

.inline-fields > * {
  flex: 1;
  min-width: 140px;
}

.inline-error,
.empty-state {
  margin-top: 14px;
  padding: 14px;
  border-radius: 10px;
  font-size: 12px;
}

.inline-error {
  background: rgba(248, 113, 113, 0.08);
  border: 1px solid rgba(248, 113, 113, 0.18);
  color: var(--danger);
}

.empty-state {
  background: rgba(148, 163, 184, 0.08);
  border: 1px dashed rgba(148, 163, 184, 0.24);
  color: var(--text-muted);
}

.experience-card {
  padding: 14px;
  border-radius: 12px;
  border: 1px solid var(--border);
  background: linear-gradient(180deg, rgba(255, 251, 235, 0.64), rgba(255, 255, 255, 0.94));
}

.experience-card-head,
.experience-card-footer {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
}

.experience-card h4 {
  margin: 0;
  font-size: 13px;
  line-height: 1.6;
  color: var(--text-primary);
}

.experience-meta,
.experience-stats {
  margin: 6px 0 0;
  font-size: 12px;
  color: var(--text-muted);
}

.experience-status {
  flex-shrink: 0;
  border-radius: 999px;
  background: rgba(34, 197, 94, 0.12);
  color: #166534;
  font-size: 11px;
  font-weight: 700;
  padding: 6px 10px;
}

.experience-status.inactive {
  background: rgba(248, 113, 113, 0.1);
  color: var(--danger);
}

.experience-copy {
  margin-top: 10px;
  font-size: 12px;
  line-height: 1.7;
  color: var(--text-secondary);
}

.experience-copy.warn {
  color: #9a6700;
}

.experience-copy.risk {
  color: var(--danger);
}

.experience-tags {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
  margin-top: 10px;
}

.tag {
  border-radius: 999px;
  background: rgba(59, 130, 246, 0.08);
  color: var(--accent);
  font-size: 11px;
  padding: 5px 10px;
}

@media (max-width: 1100px) {
  .experience-grid {
    grid-template-columns: 1fr;
  }
}
</style>
