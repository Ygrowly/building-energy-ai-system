<template>
  <div class="app-layout">
    <!-- 左侧导航栏 -->
    <nav class="sidebar">
      <div class="sidebar-logo">
        <span class="logo-icon"><Icon icon="mdi:lightning-bolt" width="22" /></span>
        <span class="logo-text">能耗管理</span>
      </div>

      <ul class="nav-list">
        <li v-for="item in navItems" :key="item.path">
          <RouterLink :to="item.path" class="nav-item" :class="{ active: $route.path === item.path }">
            <span class="nav-icon"><Icon :icon="item.icon" width="16" /></span>
            <span class="nav-label">{{ item.label }}</span>
          </RouterLink>
        </li>
      </ul>

      <!-- 建筑选择器（动态从 API 加载） -->
      <div class="building-selector">
        <p class="selector-label">当前建筑</p>
        <div v-if="buildingStore.loading" class="selector-loading">加载中...</div>
        <template v-else>
          <button
            v-for="b in buildingStore.buildings"
            :key="b.building_type"
            class="building-btn"
            :class="{ active: buildingStore.selectedType === b.building_type }"
            @click="buildingStore.select(b.building_type)"
          >
            <Icon :icon="getBuildingIcon(b.building_type)" width="14" />
            <span>{{ b.display_name }}</span>
          </button>
          <p v-if="buildingStore.error" class="selector-error">{{ buildingStore.error }}</p>
        </template>
      </div>
    </nav>

    <!-- 中间主工作区 -->
    <main class="canvas">
      <RouterView />
    </main>

    <!-- 可拖拽分隔条 -->
    <div
      class="resize-handle"
      @mousedown="startResize"
      :class="{ resizing }"
      title="拖拽调整宽度"
    ></div>

    <!-- 右侧 Agent 控制台 -->
    <aside class="agent-panel">
      <AgentConsole />
    </aside>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { RouterView, RouterLink } from 'vue-router'
import { Icon } from '@iconify/vue'
import AgentConsole from '@/components/AgentConsole.vue'
import { useBuildingStore } from '@/stores/buildingStore'

const buildingStore = useBuildingStore()

onMounted(() => {
  buildingStore.fetchBuildings()
})

// ── 右侧面板宽度拖拽调整 ──────────────────────────
const PANEL_MIN = 240
const PANEL_MAX = 600
const panelWidth = ref(320)
const resizing = ref(false)

function startResize(e: MouseEvent) {
  e.preventDefault()
  resizing.value = true
  const startX = e.clientX
  const startW = panelWidth.value

  function onMove(ev: MouseEvent) {
    // 向左拖 → delta 为正 → 面板变宽
    const delta = startX - ev.clientX
    panelWidth.value = Math.max(PANEL_MIN, Math.min(PANEL_MAX, startW + delta))
  }

  function onUp() {
    resizing.value = false
    document.removeEventListener('mousemove', onMove)
    document.removeEventListener('mouseup', onUp)
    document.body.style.cursor = ''
    document.body.style.userSelect = ''
  }

  document.body.style.cursor = 'col-resize'
  document.body.style.userSelect = 'none'
  document.addEventListener('mousemove', onMove)
  document.addEventListener('mouseup', onUp)
}

const navItems = [
  { path: '/dashboard',  icon: 'mdi:view-dashboard', label: '驾驶舱' },
  { path: '/operations', icon: 'mdi:wrench',          label: '智慧运维' },
  { path: '/workorders', icon: 'mdi:clipboard-list',  label: '工单管理' },
]

const BUILDING_ICONS: Record<string, string> = {
  Office:    'mdi:office-building',
  Teaching:  'mdi:school',
  Lab:       'mdi:flask',
  Library:   'mdi:library',
  Dormitory: 'mdi:bed',
  Gym:       'mdi:dumbbell',
}

function getBuildingIcon(type: string): string {
  return BUILDING_ICONS[type] ?? 'mdi:office-building-outline'
}
</script>

<style scoped>
.app-layout {
  display: flex;
  height: 100vh;
  overflow: hidden;
}

/* ── 左侧导航 ── */
.sidebar {
  width: 180px;
  flex-shrink: 0;
  background: var(--bg-panel);
  border-right: 1px solid var(--border);
  display: flex;
  flex-direction: column;
  padding: 0;
  overflow-y: auto;
}

.sidebar-logo {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 20px 16px 16px;
  border-bottom: 1px solid var(--border);
}
.logo-icon { display: flex; align-items: center; }
.logo-text { font-weight: 700; font-size: 14px; color: var(--text-primary); }

.nav-list {
  list-style: none;
  padding: 12px 0;
}

.nav-item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 16px;
  color: var(--text-secondary);
  text-decoration: none;
  font-size: 13px;
  font-weight: 500;
  border-radius: 0;
  transition: all 0.2s;
  border-left: 3px solid transparent;
}
.nav-item:hover { background: var(--bg-hover); color: var(--text-primary); }
.nav-item.active { background: var(--accent-glow); color: var(--accent); border-left-color: var(--accent); }

.nav-icon { display: flex; align-items: center; }

.building-selector {
  padding: 16px;
  border-top: 1px solid var(--border);
  margin-top: auto;
}
.selector-label {
  font-size: 11px;
  color: var(--text-muted);
  margin-bottom: 8px;
  text-transform: uppercase;
  letter-spacing: 0.05em;
}
.building-btn {
  display: flex;
  align-items: center;
  gap: 8px;
  width: 100%;
  padding: 8px 10px;
  background: none;
  border: 1px solid transparent;
  border-radius: 6px;
  color: var(--text-secondary);
  font-size: 13px;
  cursor: pointer;
  text-align: left;
  transition: all 0.2s;
  margin-bottom: 4px;
}
.building-btn:hover { background: var(--bg-hover); }
.building-btn.active { background: var(--accent-glow); border-color: var(--accent); color: var(--accent); }

.selector-loading {
  font-size: 12px;
  color: var(--text-muted);
  padding: 8px 0;
}

.selector-error {
  font-size: 11px;
  color: var(--danger);
  margin-top: 6px;
  line-height: 1.4;
}

/* ── 中间主区 ── */
.canvas {
  flex: 1;
  min-width: 0;
  overflow-y: auto;
  background: var(--bg-dark);
}

/* ── 拖拽分隔条 ── */
.resize-handle {
  width: 4px;
  flex-shrink: 0;
  cursor: col-resize;
  background: var(--border);
  position: relative;
  transition: background 0.15s;
  z-index: 10;
}
.resize-handle:hover,
.resize-handle.resizing {
  background: var(--accent);
}
/* 扩大可点击区域，用伪元素在两侧各扩展 4px */
.resize-handle::before {
  content: '';
  position: absolute;
  inset: 0 -4px;
}

/* ── 右侧控制台 ── */
.agent-panel {
  flex-shrink: 0;
  width: v-bind(panelWidth + 'px');
  border-left: none;
  overflow: hidden;
}
</style>
