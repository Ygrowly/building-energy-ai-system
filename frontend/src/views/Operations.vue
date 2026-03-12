<template>
  <div class="operations">
    <header class="page-header">
      <h1><Icon icon="mdi:wrench" width="22" class="page-icon" /> 智慧运维</h1>
      <span class="subtitle">故障诊断 · 工单管理 · 可解释性分析</span>
    </header>

    <!-- AI 操作引导 -->
    <div class="hint-card">
      <div class="hint-icon"><Icon icon="mdi:message-text" width="24" /></div>
      <div>
        <p class="hint-title">在右侧控制台输入故障场景，AI 将自动诊断并生成工单</p>
        <p class="hint-examples">
          例如：「办公楼 2016-04-15 凌晨3点的能耗是不是有问题？帮我处理一下」
        </p>
      </div>
    </div>

    <!-- 异常告警列表 -->
    <section class="section">
      <div class="section-header">
        <h2 class="section-title"><Icon icon="mdi:alert-circle" width="16" class="title-icon" /> 近期异常记录</h2>
        <div class="header-actions">
          <select v-model="filterHours" @change="fetchAnomalies" class="hours-select">
            <option value="24">最近 24 小时</option>
            <option value="72">最近 3 天</option>
            <option value="168">最近 7 天</option>
          </select>
          <button class="refresh-btn" @click="fetchAnomalies" :disabled="loading">
            <Icon :icon="loading ? 'mdi:loading' : 'mdi:refresh'" width="14" class="btn-icon" />
            {{ loading ? '加载中...' : '刷新' }}
          </button>
        </div>
      </div>

      <div v-if="loading" class="loading-bar">正在查询异常记录...</div>
      <div v-if="fetchError" class="error-bar"><Icon icon="mdi:alert" width="14" class="bar-icon" /> {{ fetchError }}</div>

      <div v-if="!loading && anomalies.length > 0" class="anomaly-list">
        <div class="anomaly-item" v-for="(a, idx) in anomalies" :key="idx">
          <div class="anomaly-left">
            <span class="anomaly-priority" :class="rulePriority(a.rule)">
              {{ rulePriority(a.rule) === 'high' ? 'HIGH' : 'MED' }}
            </span>
            <div>
              <p class="anomaly-title">{{ a.message }}</p>
              <p class="anomaly-meta">
                {{ formatTime(a.timestamp) }} · 设备 {{ a.meter_device_id }} · {{ buildingName(a.building_type) }}
              </p>
            </div>
          </div>
          <div class="anomaly-right">
            <span class="anomaly-val">{{ a.actual_value.toFixed(1) }} kWh</span>
            <span class="anomaly-threshold">阈值 {{ a.threshold }} kWh</span>
          </div>
        </div>
      </div>

      <!-- 无数据时的说明 -->
      <div v-if="!loading && anomalies.length === 0 && !fetchError" class="empty-state">
        <p class="empty-icon"><Icon icon="mdi:check-circle" width="32" /></p>
        <p>当前时间窗口内未检测到规则触发异常</p>
        <p class="empty-sub">
          提示：演示数据库的有效数据范围为 2016-04-01 ~ 2016-05-02，
          基于当前时间的时间窗口查询将返回空结果，请通过 AI 控制台进行历史异常分析。
        </p>
      </div>
    </section>

    <!-- 工单快速入口 -->
    <section class="section">
      <div class="section-header">
        <h2 class="section-title"><Icon icon="mdi:clipboard-list" width="16" class="title-icon" /> 工单管理</h2>
        <RouterLink to="/workorders" class="view-all-link">查看全部 →</RouterLink>
      </div>
      <div v-if="workOrderLoading" class="loading-bar">加载工单...</div>
      <div v-else-if="pendingOrders.length > 0" class="wo-preview-list">
        <div class="wo-preview-item" v-for="wo in pendingOrders.slice(0, 3)" :key="wo.ticket_id">
          <div class="wo-preview-left">
            <span class="wo-badge" :class="'priority-' + (wo.priority ?? 'medium').toLowerCase()">
              {{ wo.priority ?? 'Medium' }}
            </span>
            <div>
              <p class="wo-title">{{ wo.issue_description ?? wo.ticket_id }}</p>
              <p class="wo-meta">设备 {{ wo.device_id }} · {{ wo.building_id }} · {{ formatTime(wo.created_at) }}</p>
            </div>
          </div>
          <span class="wo-status pending">待审批</span>
        </div>
      </div>
      <div v-else-if="!workOrderLoading" class="empty-state-small">
        暂无待审批工单。可通过右侧 AI 控制台触发故障诊断生成工单。
      </div>
    </section>

    <!-- 可解释性说明 -->
    <section class="section">
      <h2 class="section-title"><Icon icon="mdi:shield-check" width="16" class="title-icon" /> 可解释性说明</h2>
      <div class="explainability-card">
        <p>当 AI 给出诊断结论时，右侧控制台会显示：</p>
        <ul>
          <li><Icon icon="mdi:chart-bar" width="14" class="list-icon" /> <strong>原始数据快照</strong>：触发异常的真实传感器数值</li>
          <li><Icon icon="mdi:book-open-variant" width="14" class="list-icon" /> <strong>知识库依据</strong>：从运维手册中检索到的相关条文</li>
          <li><Icon icon="mdi:trending-up" width="14" class="list-icon" /> <strong>置信度评分</strong>：AI 推理的可信程度</li>
          <li><Icon icon="mdi:tools" width="14" class="list-icon" /> <strong>工单草稿</strong>：需要人工审批才能正式派单（HITL）</li>
        </ul>
      </div>
    </section>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { Icon } from '@iconify/vue'
import { RouterLink } from 'vue-router'
import { apiFetch } from '@/api/http'
import { useBuildingStore } from '@/stores/buildingStore'

const buildingStore = useBuildingStore()

// ── 异常告警 ───────────────────────────────────────
const loading = ref(false)
const fetchError = ref('')
const anomalies = ref<any[]>([])
const filterHours = ref('168')

async function fetchAnomalies() {
  loading.value = true
  fetchError.value = ''
  try {
    const data = await apiFetch<any>(`/api/anomalies/recent?hours=${filterHours.value}`)
    anomalies.value = data?.anomalies ?? []
  } catch (e: any) {
    fetchError.value = e.message
  } finally {
    loading.value = false
  }
}

// ── 工单快速预览 ───────────────────────────────────
const workOrderLoading = ref(false)
const pendingOrders = ref<any[]>([])

async function fetchPendingOrders() {
  workOrderLoading.value = true
  try {
    const data = await apiFetch<any>('/api/work-orders?status=pending_approval')
    pendingOrders.value = data?.work_orders ?? []
  } catch {
    // 静默处理，不影响主界面
  } finally {
    workOrderLoading.value = false
  }
}

onMounted(() => {
  fetchAnomalies()
  fetchPendingOrders()
})

// ── 工具函数 ───────────────────────────────────────
function buildingName(type: string): string {
  return buildingStore.getBuildingName(type)
}

function rulePriority(rule: string): 'high' | 'medium' {
  return rule === 'night_high_power' ? 'high' : 'medium'
}

function formatTime(iso: string): string {
  if (!iso) return '—'
  try {
    return new Date(iso).toLocaleString('zh-CN', {
      month: '2-digit', day: '2-digit',
      hour: '2-digit', minute: '2-digit',
    })
  } catch {
    return iso
  }
}
</script>

<style scoped>
.operations { padding: 24px; }
.page-header { margin-bottom: 24px; }
.page-header h1 { font-size: 22px; font-weight: 700; margin-bottom: 4px; }
.subtitle { color: var(--text-secondary); font-size: 13px; }

.hint-card {
  display: flex;
  gap: 14px;
  align-items: flex-start;
  background: var(--accent-glow);
  border: 1px solid var(--border-accent);
  border-radius: 10px;
  padding: 16px;
  margin-bottom: 24px;
  box-shadow: var(--card-shadow);
}
.hint-icon { display: flex; align-items: flex-start; color: var(--accent); flex-shrink: 0; }
.hint-title { font-weight: 600; font-size: 14px; color: var(--accent); margin-bottom: 4px; }
.hint-examples { font-size: 12px; color: var(--text-secondary); }

.section { margin-bottom: 28px; }

.section-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 12px;
}
.section-title { font-size: 15px; font-weight: 700; color: var(--text-secondary); margin: 0; }

.header-actions { display: flex; align-items: center; gap: 8px; }

.hours-select {
  background: var(--bg-panel);
  border: 1px solid var(--border);
  border-radius: 6px;
  color: var(--text-secondary);
  font-size: 12px;
  padding: 4px 8px;
  cursor: pointer;
}

.refresh-btn {
  background: none;
  border: 1px solid var(--border);
  border-radius: 6px;
  color: var(--text-secondary);
  font-size: 12px;
  padding: 4px 10px;
  cursor: pointer;
  transition: all 0.2s;
}
.refresh-btn:hover { border-color: var(--accent); color: var(--accent); }
.refresh-btn:disabled { opacity: 0.5; cursor: not-allowed; }

.view-all-link {
  font-size: 12px;
  color: var(--accent);
  text-decoration: none;
  transition: opacity 0.2s;
}
.view-all-link:hover { opacity: 0.75; }

.loading-bar {
  background: var(--accent-glow);
  border: 1px solid var(--border-accent);
  border-radius: 8px;
  padding: 10px 16px;
  color: var(--accent);
  font-size: 13px;
  margin-bottom: 8px;
}
.error-bar {
  background: rgba(248,113,113,0.08);
  border: 1px solid rgba(248,113,113,0.22);
  border-radius: 8px;
  padding: 10px 16px;
  color: var(--danger);
  font-size: 13px;
  margin-bottom: 8px;
}

/* 异常列表 */
.anomaly-list { display: flex; flex-direction: column; gap: 8px; }

.anomaly-item {
  display: flex;
  justify-content: space-between;
  align-items: center;
  background: var(--bg-panel);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 12px 16px;
  box-shadow: var(--card-shadow);
  transition: box-shadow 0.2s, border-color 0.2s;
}
.anomaly-item:hover {
  box-shadow: var(--card-shadow-hover);
  border-color: var(--border-accent);
}

.anomaly-left { display: flex; align-items: center; gap: 12px; flex: 1; min-width: 0; }

.anomaly-priority {
  font-size: 11px;
  font-weight: 600;
  padding: 3px 8px;
  border-radius: 4px;
  flex-shrink: 0;
}
.anomaly-priority.high   { background: rgba(248,113,113,0.15); color: var(--danger); }
.anomaly-priority.medium { background: rgba(251,191,36,0.15); color: var(--warning); }

.anomaly-title { font-size: 13px; font-weight: 500; margin-bottom: 2px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.anomaly-meta  { font-size: 11px; color: var(--text-muted); }

.anomaly-right { display: flex; flex-direction: column; align-items: flex-end; flex-shrink: 0; margin-left: 12px; }
.anomaly-val       { font-size: 14px; font-weight: 700; color: var(--danger); }
.anomaly-threshold { font-size: 11px; color: var(--text-muted); }

/* 空状态 */
.empty-state {
  background: var(--bg-panel);
  border: 2px dashed var(--border);
  border-radius: 10px;
  padding: 28px 20px;
  text-align: center;
  color: var(--text-secondary);
  font-size: 13px;
}
.empty-state .empty-icon { display: flex; justify-content: center; color: var(--success); margin-bottom: 8px; }
.empty-sub { font-size: 12px; color: var(--text-muted); margin-top: 8px; line-height: 1.7; max-width: 440px; margin-left: auto; margin-right: auto; }

.empty-state-small {
  font-size: 13px;
  color: var(--text-muted);
  padding: 14px 16px;
  background: var(--bg-panel);
  border: 1px solid var(--border);
  border-radius: 8px;
}

/* 工单预览 */
.wo-preview-list { display: flex; flex-direction: column; gap: 8px; }

.wo-preview-item {
  display: flex;
  justify-content: space-between;
  align-items: center;
  background: var(--bg-panel);
  border: 1px solid var(--border);
  border-left: 3px solid var(--warning);
  border-radius: 8px;
  padding: 12px 16px;
}

.wo-preview-left { display: flex; align-items: center; gap: 12px; flex: 1; min-width: 0; }

.wo-badge {
  font-size: 11px;
  font-weight: 600;
  padding: 3px 8px;
  border-radius: 4px;
  flex-shrink: 0;
}
.priority-low      { background: rgba(74,222,128,0.15);  color: var(--success); }
.priority-medium   { background: rgba(251,191,36,0.15);  color: var(--warning); }
.priority-high     { background: rgba(248,113,113,0.15); color: var(--danger); }
.priority-critical { background: rgba(248,113,113,0.25); color: var(--danger); }

.wo-title { font-size: 13px; font-weight: 500; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; margin-bottom: 2px; }
.wo-meta  { font-size: 11px; color: var(--text-muted); }

.wo-status { font-size: 12px; padding: 3px 10px; border-radius: 10px; flex-shrink: 0; }
.wo-status.pending { background: rgba(251,191,36,0.15); color: var(--warning); }

/* 可解释性 */
.explainability-card {
  background: var(--bg-panel);
  border: 1px solid var(--border);
  border-radius: 10px;
  padding: 16px 20px;
  font-size: 13px;
  color: var(--text-secondary);
  line-height: 2;
  box-shadow: var(--card-shadow);
}
.explainability-card ul { list-style: none; margin-top: 8px; padding: 0; }
.explainability-card li { display: flex; align-items: center; gap: 8px; }
.explainability-card strong { color: var(--text-primary); }

.page-icon  { vertical-align: middle; margin-right: 6px; }
.title-icon { vertical-align: middle; margin-right: 4px; }
.bar-icon   { vertical-align: middle; flex-shrink: 0; }
.btn-icon   { vertical-align: middle; }
.list-icon  { flex-shrink: 0; color: var(--accent); }

.refresh-btn {
  display: inline-flex;
  align-items: center;
  gap: 4px;
}
</style>
