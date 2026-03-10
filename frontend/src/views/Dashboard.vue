<template>
  <div class="dashboard">
    <header class="page-header">
      <h1>🏠 驾驶舱</h1>
      <span class="subtitle">
        实时能耗总览
        <span v-if="dataDate" class="data-date">（数据日期：{{ dataDate }}）</span>
      </span>
    </header>

    <!-- 加载状态 -->
    <div v-if="loading" class="loading-bar">正在加载数据...</div>
    <div v-if="error" class="error-bar">⚠️ {{ error }}</div>

    <!-- KPI 卡片 -->
    <div class="kpi-grid">
      <div class="kpi-card" v-for="kpi in kpis" :key="kpi.label">
        <div class="kpi-icon">{{ kpi.icon }}</div>
        <div class="kpi-body">
          <div class="kpi-value">{{ kpi.value }}</div>
          <div class="kpi-label">{{ kpi.label }}</div>
        </div>
        <div v-if="kpi.trend !== null" class="kpi-trend" :class="kpi.trend > 0 ? 'up' : 'down'">
          {{ kpi.trend > 0 ? '▲' : '▼' }} {{ Math.abs(kpi.trend) }}%
        </div>
        <div v-else class="kpi-trend neutral">—</div>
      </div>
    </div>

    <!-- 建筑状态卡片 -->
    <section class="section">
      <h2 class="section-title">建筑设备状态</h2>
      <div class="building-grid">
        <div
          class="building-card"
          v-for="b in buildingStatus"
          :key="b.building_type"
          :class="b.statusClass"
        >
          <div class="building-header">
            <span class="building-icon">{{ b.icon }}</span>
            <span class="building-name">{{ b.display_name }}</span>
            <span class="status-chip" :class="b.statusClass">{{ b.statusLabel }}</span>
          </div>
          <div class="building-metrics">
            <div class="metric" v-for="m in b.metrics" :key="m.key">
              <span class="metric-label">{{ m.label }}</span>
              <span class="metric-value">{{ m.value }}</span>
            </div>
          </div>
        </div>
      </div>
    </section>

    <!-- 异常告警区块 -->
    <section class="section">
      <div class="section-header">
        <h2 class="section-title">🚨 异常告警</h2>
        <button class="refresh-btn" @click="fetchAnomalies" :disabled="anomalyLoading">
          {{ anomalyLoading ? '刷新中...' : '🔄 刷新' }}
        </button>
      </div>

      <!-- 来自 Overview 的楼宇级异常 -->
      <div v-if="anomalyBuildings.length > 0" class="anomaly-list">
        <div class="anomaly-item" v-for="b in anomalyBuildings" :key="b.building_type">
          <div class="anomaly-left">
            <span class="anomaly-priority high">HIGH</span>
            <div>
              <p class="anomaly-title">{{ b.display_name }} — 运行状态异常 ({{ b.operation_status }})</p>
              <p class="anomaly-meta">数据日期：{{ dataDate }} · 最新用电：{{ (b.total_electricity_kwh ?? 0).toFixed(1) }} kWh</p>
            </div>
          </div>
          <span class="anomaly-status pending">待处理</span>
        </div>
      </div>

      <!-- 来自 /api/anomalies/recent 的规则告警 -->
      <div v-if="recentAnomalies.length > 0" class="anomaly-list" style="margin-top: 8px;">
        <div class="anomaly-item" v-for="(a, idx) in recentAnomalies.slice(0, 10)" :key="idx">
          <div class="anomaly-left">
            <span class="anomaly-priority medium">RULE</span>
            <div>
              <p class="anomaly-title">{{ a.message }}</p>
              <p class="anomaly-meta">{{ formatTime(a.timestamp) }} · 设备 {{ a.meter_device_id }}</p>
            </div>
          </div>
          <span class="anomaly-status" :class="a.operation_status === 'Anomaly' ? 'alert' : 'warn'">
            {{ a.operation_status ?? '—' }}
          </span>
        </div>
      </div>

      <!-- 全部正常 -->
      <div
        v-if="!anomalyLoading && anomalyBuildings.length === 0 && recentAnomalies.length === 0"
        class="no-anomaly"
      >
        ✅ 所有楼宇当前运行正常，暂无告警记录
      </div>

      <div v-if="anomalyError" class="error-bar" style="margin-top: 8px;">
        ⚠️ 告警加载失败：{{ anomalyError }}
      </div>
    </section>

    <!-- 提示用户使用 AI -->
    <div class="ai-hint">
      <span>💡 提示：在右侧控制台询问 AI 进行深度分析，例如「办公楼今天有没有能耗异常？」</span>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, computed } from 'vue'
import { apiFetch } from '@/api/http'

// ── 状态 ─────────────────────────────────────────────
const loading = ref(true)
const error = ref('')
const overviewData = ref<any>(null)
const dataDate = ref('')

const anomalyLoading = ref(false)
const anomalyError = ref('')
const recentAnomalies = ref<any[]>([])

// ── 获取 Overview 数据 ───────────────────────────────
async function fetchOverview() {
  loading.value = true
  error.value = ''
  try {
    const data = await apiFetch<any>('/api/overview')
    overviewData.value = data
    dataDate.value = data?.data_date ?? ''
  } catch (e: any) {
    error.value = `数据加载失败：${e.message}`
  } finally {
    loading.value = false
  }
}

// ── 获取近期规则告警 ─────────────────────────────────
// 注意：数据库有效期 2016-04-01~2016-05-02，时间窗查询通常为空，故优雅降级。
async function fetchAnomalies() {
  anomalyLoading.value = true
  anomalyError.value = ''
  try {
    const data = await apiFetch<any>('/api/anomalies/recent?hours=168')
    recentAnomalies.value = data?.anomalies ?? []
  } catch (e: any) {
    anomalyError.value = e.message
  } finally {
    anomalyLoading.value = false
  }
}

onMounted(() => {
  fetchOverview()
  fetchAnomalies()
})

// ── KPI 卡片 ─────────────────────────────────────────
const kpis = computed(() => {
  if (!overviewData.value) {
    return [
      { icon: '⚡', label: '日总用电 (kWh)', value: '—', trend: null },
      { icon: '💧', label: '当前用水 (m³)', value: '—', trend: null },
      { icon: '📐', label: '综合能耗强度 (kWh/㎡)', value: '—', trend: null },
      { icon: '⚠️', label: '异常楼宇数', value: '—', trend: null },
    ]
  }
  const k = overviewData.value.kpis
  const buildings: any[] = overviewData.value.buildings ?? []
  const totalSqm = buildings.reduce((s: number, b: any) => s + (b.sqm ?? 0), 0)
  const intensity = totalSqm > 0
    ? buildings.reduce((s: number, b: any) => s + (b.total_electricity_kwh ?? 0), 0) / totalSqm
    : 0

  return [
    { icon: '⚡', label: '日总用电 (kWh)', value: Number(k.total_electricity_kwh).toFixed(1), trend: null },
    { icon: '💧', label: '当前用水 (m³)', value: Number(k.total_water_m3).toFixed(1), trend: null },
    { icon: '📐', label: '综合能耗强度 (kWh/㎡)', value: intensity.toFixed(3), trend: null },
    { icon: '🚨', label: '异常楼宇数', value: String(k.anomaly_count), trend: null },
  ]
})

// ── 建筑状态卡片 ─────────────────────────────────────
const buildingStatus = computed(() => {
  const buildings: any[] = overviewData.value?.buildings ?? []
  return buildings.map((b: any) => {
    const isAbnormal = b.operation_status !== 'Normal'
    return {
      building_type: b.building_type,
      icon: b.icon,
      display_name: b.display_name,
      statusClass: isAbnormal ? 'anomaly' : 'normal',
      statusLabel: isAbnormal ? `⚠️ ${b.operation_status}` : '✅ 正常',
      metrics: [
        { key: 'e', label: '日用电 (kWh)', value: (b.total_electricity_kwh ?? 0).toFixed(1) },
        { key: 't', label: '平均温度', value: `${(b.avg_ambient_temp ?? 0).toFixed(1)}°C` },
        { key: 'i', label: '能耗强度', value: b.energy_intensity_kwh_per_sqm != null
          ? `${b.energy_intensity_kwh_per_sqm} kWh/㎡` : '—' },
      ],
    }
  })
})

// ── 楼宇级异常（从 overview 中过滤非 Normal 状态） ───
const anomalyBuildings = computed(() => {
  const buildings: any[] = overviewData.value?.buildings ?? []
  return buildings.filter((b: any) => b.operation_status && b.operation_status !== 'Normal')
})

// ── 工具函数 ─────────────────────────────────────────
function formatTime(iso: string): string {
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
.dashboard { padding: 24px; }

.page-header { margin-bottom: 24px; }
.page-header h1 { font-size: 22px; font-weight: 700; margin-bottom: 4px; }
.subtitle { color: var(--text-secondary); font-size: 13px; }
.data-date { color: var(--text-muted); font-size: 12px; margin-left: 6px; }

.section-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 12px;
}
.section-header .section-title { margin-bottom: 0; }

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

.anomaly-list { display: flex; flex-direction: column; gap: 8px; }

.anomaly-item {
  display: flex;
  justify-content: space-between;
  align-items: center;
  background: var(--bg-panel);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 12px 16px;
}

.anomaly-left { display: flex; align-items: center; gap: 12px; }

.anomaly-priority {
  font-size: 11px;
  font-weight: 600;
  padding: 3px 8px;
  border-radius: 4px;
  flex-shrink: 0;
}
.anomaly-priority.high { background: rgba(248,113,113,0.15); color: var(--danger); }
.anomaly-priority.medium { background: rgba(251,191,36,0.15); color: var(--warning); }

.anomaly-title { font-size: 13px; font-weight: 500; margin-bottom: 2px; }
.anomaly-meta { font-size: 11px; color: var(--text-muted); }

.anomaly-status {
  font-size: 12px;
  padding: 3px 10px;
  border-radius: 10px;
  flex-shrink: 0;
}
.anomaly-status.pending { background: rgba(251,191,36,0.15); color: var(--warning); }
.anomaly-status.alert   { background: rgba(248,113,113,0.15); color: var(--danger); }
.anomaly-status.warn    { background: rgba(251,191,36,0.15); color: var(--warning); }

.no-anomaly {
  background: rgba(74,222,128,0.08);
  border: 1px solid rgba(74,222,128,0.25);
  border-radius: 8px;
  padding: 12px 16px;
  color: var(--success);
  font-size: 13px;
}

.loading-bar {
  background: rgba(108,142,245,0.1);
  border: 1px solid rgba(108,142,245,0.3);
  border-radius: 8px;
  padding: 10px 16px;
  color: var(--accent);
  font-size: 13px;
  margin-bottom: 16px;
}

.error-bar {
  background: rgba(248,113,113,0.1);
  border: 1px solid rgba(248,113,113,0.3);
  border-radius: 8px;
  padding: 10px 16px;
  color: var(--danger);
  font-size: 13px;
  margin-bottom: 16px;
}

.kpi-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 12px;
  margin-bottom: 28px;
}

.kpi-card {
  background: var(--bg-panel);
  border: 1px solid var(--border);
  border-radius: 10px;
  padding: 16px;
  display: flex;
  align-items: center;
  gap: 12px;
}

.kpi-icon { font-size: 28px; }
.kpi-body { flex: 1; }
.kpi-value { font-size: 22px; font-weight: 700; color: var(--text-primary); }
.kpi-label { font-size: 11px; color: var(--text-muted); margin-top: 2px; }
.kpi-trend { font-size: 12px; font-weight: 600; }
.kpi-trend.up { color: var(--danger); }
.kpi-trend.down { color: var(--success); }
.kpi-trend.neutral { color: var(--text-muted); }

.section { margin-bottom: 28px; }
.section-title { font-size: 15px; font-weight: 700; margin-bottom: 12px; color: var(--text-secondary); }

.building-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 12px; }

.building-card {
  background: var(--bg-panel);
  border: 1px solid var(--border);
  border-radius: 10px;
  overflow: hidden;
  transition: border-color 0.2s;
}
.building-card.anomaly { border-color: rgba(248,113,113,0.5); }

.building-header {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 14px 16px;
  background: var(--bg-card);
  border-bottom: 1px solid var(--border);
}
.building-icon { font-size: 18px; }
.building-name { font-weight: 600; font-size: 13px; flex: 1; }

.status-chip {
  font-size: 11px;
  padding: 2px 8px;
  border-radius: 10px;
  font-weight: 600;
}
.status-chip.normal { background: rgba(74,222,128,0.15); color: var(--success); }
.status-chip.anomaly { background: rgba(248,113,113,0.15); color: var(--danger); }

.building-metrics { padding: 12px 16px; display: flex; flex-direction: column; gap: 8px; }

.metric {
  display: flex;
  justify-content: space-between;
  font-size: 13px;
}
.metric-label { color: var(--text-muted); }
.metric-value { color: var(--text-primary); font-weight: 500; }

.ai-hint {
  background: var(--accent-glow);
  border: 1px solid rgba(108,142,245,0.3);
  border-radius: 8px;
  padding: 12px 16px;
  color: var(--accent);
  font-size: 13px;
}
</style>
