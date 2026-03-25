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
        <div class="anomaly-item" v-for="(a, idx) in anomalies" :key="idx"
             :class="{ 'item-critical': a.severity === 'critical', 'item-warning': a.severity === 'warning' }">
          <div class="anomaly-left">
            <span class="anomaly-priority" :class="a.severity === 'critical' ? 'high' : rulePriority(a.rule)">
              {{ a.severity === 'critical' ? 'CRIT' : (rulePriority(a.rule) === 'high' ? 'HIGH' : 'MED') }}
            </span>
            <div>
              <p class="anomaly-title">{{ a.message }}</p>
              <p class="anomaly-meta">
                {{ formatTime(a.timestamp) }} · {{ buildingName(a.building_type) }}
              </p>
              <!-- notebook v2 丰富信息 -->
              <div class="anomaly-tags" v-if="a.anomaly_phase || a.hvac_diagnosis || (a.symptom_flags && a.symptom_flags.length)">
                <span v-if="a.anomaly_phase" class="tag" :class="'phase-' + a.anomaly_phase">
                  <Icon icon="mdi:waves" width="11" />
                  {{ a.anomaly_phase === 'ramp' ? '上升期' : '全量期' }}
                </span>
                <span v-if="a.hvac_diagnosis" class="tag diag" :title="a.hvac_diagnosis">
                  <Icon icon="mdi:air-conditioner" width="11" />
                  {{ diagLabel(a.hvac_diagnosis) }}
                </span>
                <span v-for="flag in (a.symptom_flags || []).slice(0,3)" :key="flag"
                      class="tag flag">
                  {{ flagLabel(flag) }}
                </span>
              </div>
            </div>
          </div>
          <div class="anomaly-right">
            <span v-if="a.deviation_pct != null" class="anomaly-dev"
                  :class="a.deviation_pct > 30 ? 'dev-high' : 'dev-med'">
              {{ a.deviation_pct > 0 ? '+' : '' }}{{ Number(a.deviation_pct).toFixed(1) }}%
            </span>
            <span v-if="a.actual_value != null" class="anomaly-val">
              {{ Number(a.actual_value).toFixed(2) }} {{ ruleUnit(a.rule) }}
            </span>
            <span v-if="a.expected_value != null" class="anomaly-threshold">
              基线 {{ Number(a.expected_value).toFixed(2) }} {{ ruleUnit(a.rule) }}
            </span>
            <span v-else-if="a.threshold != null" class="anomaly-threshold">
              阈值 {{ Number(a.threshold).toFixed(4) }} {{ ruleUnit(a.rule) }}
            </span>
          </div>
        </div>
      </div>

      <!-- 无数据时的说明 -->
      <div v-if="!loading && anomalies.length === 0 && !fetchError" class="empty-state">
        <p class="empty-icon"><Icon icon="mdi:check-circle" width="32" /></p>
        <p>当前时间窗口内未检测到规则触发异常</p>
        <p class="empty-sub">
          提示：演示数据库的有效数据范围为 {{ dataRangeStore.minDate || '...' }} ~ {{ dataRangeStore.maxDate || '...' }}，
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
import { useDataRangeStore } from '@/stores/dataRangeStore'

const dataRangeStore = useDataRangeStore()

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
  dataRangeStore.fetch()
  fetchAnomalies()
  fetchPendingOrders()
})

// ── 工具函数 ───────────────────────────────────────
function buildingName(type: string): string {
  return buildingStore.getBuildingName(type)
}

// ── notebook v2 辅助函数 ──────────────────────────────
const _DIAG_LABELS: Record<string, string> = {
  'A_low_efficiency': 'A: 主机衰退',
  'B_small_deltaT':   'B: 水力失调',
  'C_unexpected_on':  'C: 非预期开机',
  'other_hvac':       '其他空调故障',
}
function diagLabel(code: string): string {
  return _DIAG_LABELS[code] ?? code
}

const _FLAG_LABELS: Record<string, string> = {
  'flag_water':           '水耗偏高',
  'flag_electricity':     '总电偏高',
  'flag_hvac_energy':     '空调偏高',
  'flag_supply_deviation':'供水偏离',
  'flag_return_deviation':'回水偏离',
}
function flagLabel(flag: string): string {
  return _FLAG_LABELS[flag] ?? flag
}

function rulePriority(rule: string): 'high' | 'medium' {
  return ['night_high_power', 'hvac_overconsumption', 'flag_hvac_energy'].includes(rule) ? 'high' : 'medium'
}

function ruleUnit(rule: string): string {
  if (rule === 'water_leak') return 'L'
  return 'kWh'
}

function formatTime(iso: string): string {
  if (!iso) return '—'
  // energy_data.timestamp 存储的即为使用时刻（本地时间），直接从字符串中提取，不做时区转换
  const m = iso.match(/\d{4}-(\d{2})-(\d{2})T(\d{2}):(\d{2})/)
  if (m) return `${m[1]}/${m[2]} ${m[3]}:${m[4]}`
  return iso.slice(0, 16)
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

.anomaly-priority.high   { background: rgba(248,113,113,0.15); color: var(--danger); }
.anomaly-priority.medium { background: rgba(251,191,36,0.15); color: var(--warning); }

.anomaly-title { font-size: 13px; font-weight: 500; margin-bottom: 2px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.anomaly-meta  { font-size: 11px; color: var(--text-muted); margin-bottom: 4px; }

/* notebook v2 tags */
.anomaly-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  margin-top: 4px;
}
.tag {
  display: inline-flex;
  align-items: center;
  gap: 3px;
  font-size: 10px;
  padding: 2px 6px;
  border-radius: 4px;
  font-weight: 600;
}
.tag.phase-ramp  { background: rgba(251,191,36,0.15);   color: var(--warning); }
.tag.phase-full  { background: rgba(248,113,113,0.12);  color: var(--danger);  }
.tag.diag        { background: rgba(167,139,250,0.12);  color: #a78bfa; }
.tag.flag        { background: rgba(148,163,184,0.1);   color: var(--text-muted); }

/* severity borders */
.item-critical { border-color: rgba(248,113,113,0.3); }
.item-warning  { border-color: rgba(251,191,36,0.2);  }

.anomaly-right { display: flex; flex-direction: column; align-items: flex-end; flex-shrink: 0; margin-left: 12px; }
.anomaly-dev       { font-size: 12px; font-weight: 700; margin-bottom: 2px; }
.anomaly-dev.dev-high { color: var(--danger); }
.anomaly-dev.dev-med  { color: var(--warning); }
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
