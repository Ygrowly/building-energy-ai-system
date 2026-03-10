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

    <!-- 提示用户使用 AI -->
    <div class="ai-hint">
      <span>💡 提示：在右侧控制台询问 AI 进行深度分析，例如「办公楼今天有没有能耗异常？」</span>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, computed } from 'vue'

const API_BASE = import.meta.env.VITE_API_BASE ?? 'http://localhost:8000'

// 状态
const loading = ref(true)
const error = ref('')
const overviewData = ref<any>(null)
const dataDate = ref('')

// 获取 Overview 数据
async function fetchOverview() {
  loading.value = true
  error.value = ''
  try {
    const resp = await fetch(`${API_BASE}/api/overview`)
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`)
    overviewData.value = await resp.json()
    dataDate.value = overviewData.value?.data_date ?? ''
  } catch (e: any) {
    error.value = `数据加载失败：${e.message}。请确认后端服务已启动（${API_BASE}）`
  } finally {
    loading.value = false
  }
}

onMounted(fetchOverview)

// KPI 卡片（从真实数据构建）
const kpis = computed(() => {
  if (!overviewData.value) {
    return [
      { icon: '⚡', label: '总用电 (kWh)', value: '—', trend: null },
      { icon: '💧', label: '总用水 (m³)', value: '—', trend: null },
      { icon: '❄️', label: '能耗强度 (kWh/㎡)', value: '—', trend: null },
      { icon: '⚠️', label: '异常楼宇数', value: '—', trend: null },
    ]
  }
  const kpis_ = overviewData.value.kpis
  const buildings = overviewData.value.buildings ?? []

  // 计算加权平均能耗强度
  const totalSqm = buildings.reduce((s: number, b: any) => s + (b.sqm ?? 0), 0)
  const intensity = totalSqm > 0
    ? buildings.reduce((s: number, b: any) => s + (b.total_electricity_kwh ?? 0), 0) / totalSqm
    : 0

  return [
    { icon: '⚡', label: '日总用电 (kWh)', value: kpis_.total_electricity_kwh.toFixed(1), trend: null },
    { icon: '💧', label: '当前用水 (m³)', value: kpis_.total_water_m3.toFixed(1), trend: null },
    { icon: '📐', label: '综合能耗强度 (kWh/㎡)', value: intensity.toFixed(3), trend: null },
    { icon: '⚠️', label: '夜间模式楼宇', value: String(kpis_.anomaly_count), trend: null },
  ]
})

// 建筑状态卡片（从真实数据构建）
const buildingStatus = computed(() => {
  const buildings = overviewData.value?.buildings ?? []
  return buildings.map((b: any) => {
    const isAnomaly = b.operation_status === 'NIGHT_MODE'
    return {
      building_type: b.building_type,
      icon: b.icon,
      display_name: b.display_name,
      statusClass: isAnomaly ? 'anomaly' : 'normal',
      statusLabel: isAnomaly ? '⚠️ 夜间模式' : '✅ 正常',
      metrics: [
        { key: 'e', label: '日用电 (kWh)', value: (b.total_electricity_kwh ?? 0).toFixed(1) },
        { key: 't', label: '平均温度', value: `${(b.avg_ambient_temp ?? 0).toFixed(1)}°C` },
        { key: 'i', label: '能耗强度', value: b.energy_intensity_kwh_per_sqm != null
          ? `${b.energy_intensity_kwh_per_sqm} kWh/㎡` : '—' },
      ],
    }
  })
})
</script>

<style scoped>
.dashboard { padding: 24px; }

.page-header { margin-bottom: 24px; }
.page-header h1 { font-size: 22px; font-weight: 700; margin-bottom: 4px; }
.subtitle { color: var(--text-secondary); font-size: 13px; }
.data-date { color: var(--text-muted); font-size: 12px; margin-left: 6px; }

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
