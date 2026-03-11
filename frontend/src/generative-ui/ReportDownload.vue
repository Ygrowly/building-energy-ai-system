<template>
  <div class="rd-card">
    <div class="rd-header">
      <span class="rd-icon"><Icon icon="mdi:file-download" width="18" /></span>
      <div class="rd-title-block">
        <span class="rd-title">{{ title }}</span>
        <span class="rd-subtitle">CSV 报表 · AI 自动生成</span>
      </div>
      <span class="rd-badge">报表就绪</span>
    </div>

    <!-- 报表信息 -->
    <div class="rd-body">
      <div class="rd-row" v-if="parsedParams.building_type">
        <span class="rd-label">楼宇</span>
        <span class="rd-val">{{ buildingStore.getBuildingName(parsedParams.building_type) }}</span>
      </div>
      <div class="rd-row" v-if="parsedParams.report_type">
        <span class="rd-label">报表类型</span>
        <span class="rd-val">{{ REPORT_TYPE_LABELS[parsedParams.report_type] ?? parsedParams.report_type }}</span>
      </div>
      <div class="rd-row" v-if="parsedParams.start_date">
        <span class="rd-label">数据范围</span>
        <span class="rd-val">{{ parsedParams.start_date }} ~ {{ parsedParams.end_date }}</span>
      </div>
      <div class="rd-row">
        <span class="rd-label">下载路径</span>
        <span class="rd-val mono">{{ shortUrl }}</span>
      </div>
    </div>

    <!-- 操作 -->
    <div class="rd-footer">
      <button class="btn-download" @click="triggerDownload" :disabled="downloading">
        <Icon v-if="!downloading" icon="mdi:download" width="14" />
        {{ downloading ? '下载中...' : '立即下载 CSV' }}
      </button>
      <span class="dl-hint" v-if="downloaded"><Icon icon="mdi:check-circle" width="14" /> 已开始下载</span>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue'
import { Icon } from '@iconify/vue'
import type { ArtifactEvent } from '@/api/stream_client'
import { useBuildingStore } from '@/stores/buildingStore'

const props = defineProps<{ artifact: ArtifactEvent }>()
const buildingStore = useBuildingStore()

const downloading = ref(false)
const downloaded = ref(false)

// 报表类型为后端 API 固定枚举值，静态映射合理
const REPORT_TYPE_LABELS: Record<string, string> = {
  daily_summary: '每日汇总',
  energy_detail: '原始明细',
}

const title = computed(() => props.artifact.title ?? '能耗报表')

// 解析 download_url 中的 query 参数，提取报表元信息
const parsedParams = computed<Record<string, string>>(() => {
  const url = props.artifact.download_url ?? ''
  const queryStart = url.indexOf('?')
  if (queryStart === -1) return {}
  try {
    const params = new URLSearchParams(url.slice(queryStart + 1))
    return Object.fromEntries(params.entries())
  } catch {
    return {}
  }
})

// 截短显示路径（去掉 API_BASE）
const shortUrl = computed(() => {
  const url = props.artifact.download_url ?? ''
  const idx = url.indexOf('/api/')
  return idx !== -1 ? url.slice(idx) : url
})

// 完整下载 URL（需加上 origin 保证跨 Vite proxy 场景可下载）
const fullUrl = computed(() => {
  const url = props.artifact.download_url ?? ''
  if (url.startsWith('http')) return url
  // 开发时走 Vite proxy，直接拼 localhost:8000
  const API_BASE = (import.meta.env.VITE_API_BASE as string | undefined) ?? ''
  return `${API_BASE}${url}`
})

function triggerDownload() {
  if (!props.artifact.download_url) return
  downloading.value = true
  try {
    const a = document.createElement('a')
    a.href = fullUrl.value
    // 从 URL 推断文件名
    const bt = parsedParams.value.building_type ?? 'report'
    const rt = parsedParams.value.report_type ?? 'export'
    const sd = parsedParams.value.start_date ?? ''
    const ed = parsedParams.value.end_date ?? ''
    a.download = `${bt}_${rt}_${sd}_${ed}.csv`
    document.body.appendChild(a)
    a.click()
    document.body.removeChild(a)
    downloaded.value = true
    setTimeout(() => { downloaded.value = false }, 3000)
  } finally {
    downloading.value = false
  }
}
</script>

<style scoped>
.rd-card {
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-left: 4px solid var(--success);
  border-radius: 10px;
  margin: 8px 0;
  overflow: hidden;
}

.rd-header {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 12px 16px;
  background: var(--bg-panel);
  border-bottom: 1px solid var(--border);
}

.rd-icon { display: flex; align-items: center; color: var(--success); }

.rd-title-block { flex: 1; min-width: 0; }
.rd-title    { display: block; font-size: 13px; font-weight: 700; color: var(--text-primary); }
.rd-subtitle { display: block; font-size: 11px; color: var(--text-muted); margin-top: 2px; }

.rd-badge {
  font-size: 11px;
  font-weight: 600;
  background: rgba(74,222,128,0.15);
  color: var(--success);
  padding: 3px 10px;
  border-radius: 10px;
  flex-shrink: 0;
}

.rd-body { padding: 10px 16px; }

.rd-row {
  display: grid;
  grid-template-columns: 70px 1fr;
  gap: 8px;
  padding: 4px 0;
  font-size: 12px;
  border-bottom: 1px solid var(--border);
}
.rd-row:last-child { border-bottom: none; }

.rd-label { color: var(--text-muted); align-self: center; }
.rd-val   { color: var(--text-primary); word-break: break-all; }
.rd-val.mono { font-family: monospace; color: var(--accent); font-size: 11px; }

.rd-footer {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 10px 16px;
  border-top: 1px solid var(--border);
  background: var(--bg-panel);
}

.btn-download {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  background: var(--success);
  border: none;
  border-radius: 6px;
  color: #000;
  font-size: 13px;
  font-weight: 600;
  padding: 8px 20px;
  cursor: pointer;
  transition: opacity 0.2s;
}
.btn-download:hover    { opacity: 0.85; }
.btn-download:disabled { opacity: 0.5; cursor: not-allowed; }

.dl-hint {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: 12px;
  color: var(--success);
  animation: fadein 0.3s ease;
}

@keyframes fadein {
  from { opacity: 0; transform: translateX(-6px); }
  to   { opacity: 1; transform: translateX(0); }
}
</style>
