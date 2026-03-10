<template>
  <div class="app-layout">
    <!-- 左侧导航栏 -->
    <nav class="sidebar">
      <div class="sidebar-logo">
        <span class="logo-icon">⚡</span>
        <span class="logo-text">能耗管理</span>
      </div>

      <ul class="nav-list">
        <li v-for="item in navItems" :key="item.path">
          <RouterLink :to="item.path" class="nav-item" :class="{ active: $route.path === item.path }">
            <span class="nav-icon">{{ item.icon }}</span>
            <span class="nav-label">{{ item.label }}</span>
          </RouterLink>
        </li>
      </ul>

      <!-- 建筑选择器 -->
      <div class="building-selector">
        <p class="selector-label">当前建筑</p>
        <button
          v-for="b in buildings"
          :key="b.id"
          class="building-btn"
          :class="{ active: selectedBuilding === b.id }"
          @click="selectedBuilding = b.id"
        >
          <span>{{ b.icon }}</span>
          <span>{{ b.label }}</span>
        </button>
      </div>
    </nav>

    <!-- 中间主工作区 -->
    <main class="canvas">
      <RouterView />
    </main>

    <!-- 右侧 Agent 控制台 -->
    <aside class="agent-panel">
      <AgentConsole />
    </aside>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { RouterView, RouterLink } from 'vue-router'
import AgentConsole from '@/components/AgentConsole.vue'

const selectedBuilding = ref('Office')

const navItems = [
  { path: '/dashboard',  icon: '🏠', label: '驾驶舱' },
  { path: '/analysis',   icon: '📊', label: '能源透视' },
  { path: '/operations', icon: '🔧', label: '智慧运维' },
]

const buildings = [
  { id: 'Education', icon: '🏫', label: '图书馆' },
  { id: 'Office',    icon: '🏢', label: '办公楼' },
  { id: 'Public',    icon: '🏛️', label: '公共区域' },
]
</script>

<style scoped>
.app-layout {
  display: grid;
  grid-template-columns: 180px 1fr 320px;
  height: 100vh;
  overflow: hidden;
}

/* ── 左侧导航 ── */
.sidebar {
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
.logo-icon { font-size: 22px; }
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

.nav-icon { font-size: 16px; }

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

/* ── 中间主区 ── */
.canvas {
  overflow-y: auto;
  background: var(--bg-dark);
}

/* ── 右侧控制台 ── */
.agent-panel {
  border-left: 1px solid var(--border);
  overflow: hidden;
}
</style>
