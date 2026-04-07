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
          <select v-model="filterHours" @change="fetchAnomalies(true)" class="hours-select">
            <option value="24">最近 24 小时</option>
            <option value="72">最近 3 天</option>
            <option value="168">最近 7 天</option>
          </select>
          <button class="refresh-btn" @click="fetchAnomalies(true)" :disabled="loading">
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

    <!-- 预测预警列表 -->
    <section class="section">
      <div class="section-header">
        <h2 class="section-title"><Icon icon="mdi:crystal-ball" width="16" class="title-icon" /> 预测预警</h2>
        <div class="header-actions">
          <select v-model="predFilterHours" @change="fetchPredictions(true)" class="hours-select">
            <option value="24">最近 24 小时</option>
            <option value="72">最近 3 天</option>
            <option value="168">最近 7 天</option>
          </select>
          <button class="refresh-btn" @click="fetchPredictions(true)" :disabled="predLoading">
            <Icon :icon="predLoading ? 'mdi:loading' : 'mdi:refresh'" width="14" class="btn-icon" />
            {{ predLoading ? '加载中...' : '刷新' }}
          </button>
        </div>
      </div>

      <div v-if="predLoading" class="loading-bar">正在查询预测预警...</div>
      <div v-if="predError" class="error-bar"><Icon icon="mdi:alert" width="14" class="bar-icon" /> {{ predError }}</div>

      <div v-if="!predLoading && predictions.length > 0" class="anomaly-list">
        <div class="anomaly-item item-prediction" v-for="p in predictions" :key="p.id">
          <div class="anomaly-left">
            <span class="anomaly-priority pred-badge"
                  :class="p.risk_level === 'critical' ? 'high' : 'medium'">
              {{ p.risk_level === 'critical' ? 'CRIT' : 'WARN' }}
            </span>
            <div>
              <p class="anomaly-title">
                {{ p.building_name }} · {{ metricLabel(p.metric_name) }} · {{ p.horizon_h }}h 预测
              </p>
              <p class="anomaly-meta">
                预测基准 {{ formatTime(p.as_of_timestamp) }} →
                预计发生 {{ formatTime(p.forecast_for_timestamp) }}
              </p>
              <div class="anomaly-tags">
                <span class="tag pred-tag">
                  <Icon icon="mdi:chart-timeline-variant" width="11" />
                  {{ p.rule_triggered ? ruleLabel(p.rule_triggered) : '偏差预警' }}
                </span>
                <span class="tag flag">{{ p.model_name }}</span>
              </div>
            </div>
          </div>
          <div class="anomaly-right">
            <span v-if="p.deviation_pct != null" class="anomaly-dev"
                  :class="Math.abs(p.deviation_pct) > 30 ? 'dev-high' : 'dev-med'">
              {{ p.deviation_pct > 0 ? '+' : '' }}{{ Number(p.deviation_pct).toFixed(1) }}%
            </span>
            <span class="anomaly-val">
              预测 {{ Number(p.predicted_value).toFixed(2) }} {{ metricUnit(p.metric_name) }}
            </span>
            <span v-if="p.expected_value != null" class="anomaly-threshold">
              基线 {{ Number(p.expected_value).toFixed(2) }} {{ metricUnit(p.metric_name) }}
            </span>
          </div>
        </div>
      </div>

      <div v-if="!predLoading && predictions.length === 0 && !predError" class="empty-state-small">
        暂无预测预警。可通过 /api/admin/run-forecast 手动触发批量预测。
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
          <span class="wo-status pending">{{ workOrderPreviewStatus(wo.status) }}</span>
        </div>
      </div>
      <div v-else-if="!workOrderLoading" class="empty-state-small">
        暂无待审阅或待派工工单。可通过右侧 AI 控制台触发故障诊断生成工单。
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
import { ref, watch, onMounted, onUnmounted } from 'vue'
import { Icon } from '@iconify/vue'
import { RouterLink } from 'vue-router'
import { cachedApiFetch, peekCachedApi } from '@/api/cached'
import { isAbortError, startPerfSpan } from '@/utils/perf'
import { useBuildingStore } from '@/stores/buildingStore'
import { useDataRangeStore } from '@/stores/dataRangeStore'
import { useReportExport } from '@/composables/useReportExport'

const dataRangeStore = useDataRangeStore()

const buildingStore = useBuildingStore()
const { registerSection, setReportMeta } = useReportExport('operations')

// ── 异常告警 ───────────────────────────────────────
const loading = ref(false)
const fetchError = ref('')
const anomalies = ref<any[]>([])
const filterHours = ref('168')
const OPERATIONS_BUNDLE_PATH = '/api/operations/bundle'
const OPERATIONS_CACHE_TTL = 15_000
let operationsLoadController: AbortController | null = null

function applyAnomaliesData(data: any) {
  anomalies.value = data?.anomalies ?? []
}

// ── 预测预警 ───────────────────────────────────────
const predLoading = ref(false)
const predError = ref('')
const predictions = ref<any[]>([])
const predFilterHours = ref('168')

function applyPredictionsData(data: any) {
  predictions.value = data?.predictions ?? []
}

const _METRIC_LABELS: Record<string, string> = {
  water_l: '水耗 (L)',
  electricity_kwh: '电耗 (kWh)',
  sim_supply_temp_c: '供水温度 (℃)',
  sim_return_temp_c: '回水温度 (℃)',
  hac_energy: '空调能耗 (kWh)',
}
function metricLabel(name: string): string {
  return _METRIC_LABELS[name] ?? name
}
function metricUnit(name: string): string {
  if (name.includes('temp')) return '℃'
  if (name === 'water_l') return 'L'
  return 'kWh'
}

// ── 工单快速预览 ───────────────────────────────────
const workOrderLoading = ref(false)
const pendingOrders = ref<any[]>([])

function applyPendingOrdersData(data: any) {
  pendingOrders.value = data?.work_orders ?? []
}

function getOperationsBundlePath() {
  return `${OPERATIONS_BUNDLE_PATH}?anomaly_hours=${filterHours.value}&prediction_hours=${predFilterHours.value}`
}

function applyOperationsBundle(data: any) {
  applyAnomaliesData(data?.anomalies)
  applyPredictionsData(data?.predictions)
  applyPendingOrdersData(data?.pending_work_orders)
}

function setBundleLoading(next: boolean) {
  loading.value = next
  predLoading.value = next
  workOrderLoading.value = next
}

async function fetchOperationsBundle(force = false) {
  operationsLoadController?.abort()
  const controller = new AbortController()
  operationsLoadController = controller
  const finish = startPerfSpan('operations.bundle.load', {
    force,
    anomalyHours: filterHours.value,
    predictionHours: predFilterHours.value,
  })
  setBundleLoading(true)
  fetchError.value = ''
  predError.value = ''
  try {
    const data = await cachedApiFetch<any>(getOperationsBundlePath(), undefined, {
      force,
      signal: controller.signal,
      ttlMs: OPERATIONS_CACHE_TTL,
    })
    if (operationsLoadController !== controller || controller.signal.aborted) return
    applyOperationsBundle(data)
    finish('ok')
  } catch (e: any) {
    if (isAbortError(e)) {
      finish('abort')
      return
    }
    const message = e?.message ?? '运维数据加载失败'
    if (operationsLoadController === controller) {
      fetchError.value = message
      predError.value = message
    }
    finish('error', { message })
  } finally {
    if (operationsLoadController === controller) {
      setBundleLoading(false)
    }
  }
}

async function fetchAnomalies(force = false) {
  await fetchOperationsBundle(force)
}

async function fetchPredictions(force = false) {
  await fetchOperationsBundle(force)
}

function hydrateOperationsCache() {
  const snapshot = peekCachedApi<any>(getOperationsBundlePath(), { ttlMs: OPERATIONS_CACHE_TTL })
  if (snapshot.data) {
    applyOperationsBundle(snapshot.data)
  }
  return {
    bundleFresh: snapshot.isFresh,
  }
}

const initialOperationsCache = hydrateOperationsCache()
setBundleLoading(!initialOperationsCache.bundleFresh)

onMounted(() => {
  void dataRangeStore.fetch()
  if (!initialOperationsCache.bundleFresh) {
    void fetchOperationsBundle(true)
  }
})

onUnmounted(() => {
  operationsLoadController?.abort()
  operationsLoadController = null
})

// ── 报表集成 ───────────────────────────────────────
watch(anomalies, (data) => {
  if (!data?.length) return
  setReportMeta({ title: '智慧运维报表' })
  registerSection({
    id: 'ops-anomalies',
    title: `近期异常告警（最近 ${filterHours.value} 小时）`,
    type: 'table',
    order: 10,
    columns: [
      { key: 'ts', label: '时间' },
      { key: 'building', label: '楼宇' },
      { key: 'message', label: '告警内容' },
      { key: 'severity', label: '严重度' },
      { key: 'deviation', label: '偏差', align: 'right' },
    ],
    rows: data.map((a: any) => ({
      ts: a.timestamp ? new Date(a.timestamp).toLocaleString('zh-CN') : '—',
      building: buildingStore.getBuildingName(a.building_type),
      message: a.message ?? '—',
      severity: a.severity === 'critical' ? 'CRITICAL' : 'WARNING',
      deviation: a.deviation_pct != null ? `${a.deviation_pct > 0 ? '+' : ''}${Number(a.deviation_pct).toFixed(1)}%` : '—',
    })),
  })
})

watch(predictions, (data) => {
  if (!data?.length) return
  registerSection({
    id: 'ops-predictions',
    title: `预测预警（最近 ${predFilterHours.value} 小时）`,
    type: 'table',
    order: 20,
    columns: [
      { key: 'building', label: '楼宇' },
      { key: 'metric', label: '指标' },
      { key: 'horizon', label: '预测时窗' },
      { key: 'risk', label: '风险等级' },
      { key: 'predicted', label: '预测值', align: 'right' },
      { key: 'expected', label: '基线值', align: 'right' },
      { key: 'deviation', label: '偏差', align: 'right' },
    ],
    rows: data.map((p: any) => ({
      building: p.building_name ?? buildingStore.getBuildingName(p.building_type),
      metric: metricLabel(p.metric_name),
      horizon: `${p.horizon_h}h`,
      risk: p.risk_level === 'critical' ? 'CRITICAL' : 'WARNING',
      predicted: p.predicted_value != null ? Number(p.predicted_value).toFixed(2) : '—',
      expected: p.expected_value != null ? Number(p.expected_value).toFixed(2) : '—',
      deviation: p.deviation_pct != null ? `${p.deviation_pct > 0 ? '+' : ''}${Number(p.deviation_pct).toFixed(1)}%` : '—',
    })),
  })
})

// ── 工具函数 ───────────────────────────────────────
function buildingName(type: string): string {
  return buildingStore.getBuildingName(type)
}

function workOrderPreviewStatus(status: string): string {
  const map: Record<string, string> = {
    pending_review: '待AI审阅',
    pending_dispatch: '待派工',
  }
  return map[status] || '处理中'
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

const _RULE_LABELS: Record<string, string> = {
  'water_leak': '水耗异常',
  'electricity_overload': '电耗超标',
  'hvac_overconsumption': '空调过耗',
  'supply_temp_deviation': '供水温度偏离',
  'return_temp_deviation': '回水温度偏离',
  'night_high_power': '夜间高耗',
  'db_flagged': '标注异常',
  'flag_water': '水耗偏高',
  'flag_electricity': '总电耗偏高',
  'flag_hvac_energy': '空调能耗偏高',
  'flag_supply_deviation': '供水温度偏离',
  'flag_return_deviation': '回水温度偏离',
}
function ruleLabel(rule: string): string {
  return _RULE_LABELS[rule] ?? rule
}

const _FLAG_LABELS: Record<string, string> = {
  'flag_water':           '水耗偏高',
  'flag_electricity':     '总电偏高',
  'flag_hvac_energy':     '空调偏高',
  'flag_supply_deviation':'供水温度偏离',
  'flag_return_deviation':'回水温度偏离',
}
function flagLabel(flag: string): string {
  return _FLAG_LABELS[flag] ?? ruleLabel(flag)
}

function rulePriority(rule: string): 'high' | 'medium' {
  return ['night_high_power', 'hvac_overconsumption', 'flag_hvac_energy'].includes(rule) ? 'high' : 'medium'
}

function ruleUnit(rule: string): string {
  if (rule === 'water_leak') return 'L'
  if (['supply_temp_deviation', 'return_temp_deviation', 'flag_supply_deviation', 'flag_return_deviation'].includes(rule)) return '℃'
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

/* 预测预警 */
.item-prediction { border-left: 3px solid rgba(147, 130, 255, 0.5); }
.pred-badge { background: rgba(147,130,255,0.15); color: #9382ff; }
.pred-badge.high { background: rgba(248,113,113,0.15); color: var(--danger); }
.pred-tag { background: rgba(147,130,255,0.12); color: #9382ff; }

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
