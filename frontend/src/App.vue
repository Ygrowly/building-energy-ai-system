<template>
  <div class="app-layout">
    <!-- 左侧导航栏 -->
    <nav
      class="sidebar"
      :class="{ expanded: sidebarExpanded, pinned: sidebarPinned }"
      @mouseenter="onSidebarEnter"
      @mouseleave="onSidebarLeave"
    >
      <!-- 顶部 Logo 徽章 -->
      <div class="sidebar-logo">
        <button
          class="logo-badge"
          :class="{ pinned: sidebarPinned }"
          @click="togglePin"
          :title="sidebarPinned ? '已钉住，点击取消固定' : '点击钉住导航栏'"
        >
          <Icon icon="mdi:lightning-bolt" width="18" />
        </button>
        <span class="logo-text">能耗管理</span>
      </div>

      <!-- 导航菜单 -->
      <ul class="nav-list">
        <li v-for="item in navItems" :key="item.path">
          <RouterLink
            :to="item.path"
            class="nav-item"
            :class="{ active: $route.path === item.path }"
            :title="!sidebarExpanded ? item.label : ''"
          >
            <span class="nav-icon"><Icon :icon="item.icon" width="16" /></span>
            <span class="nav-label">{{ item.label }}</span>
          </RouterLink>
        </li>
      </ul>

      <!-- 底部功能区 -->
      <div class="sidebar-bottom">
        <!-- 数据中心 -->
        <RouterLink to="/datacenter" class="bottom-item" :title="!sidebarExpanded ? '数据中心' : ''">
          <span class="bottom-icon"><Icon icon="mdi:database-outline" width="16" /></span>
          <span class="bottom-label">数据中心</span>
        </RouterLink>

        <!-- 主题选择 -->
        <div ref="themeItemRef" class="bottom-item theme-item" :title="!sidebarExpanded ? '主题' : ''" @click.stop="toggleThemePicker">
          <span class="bottom-icon"><Icon icon="mdi:palette-outline" width="16" /></span>
          <span class="bottom-label">主题</span>
        </div>

        <!-- 用户信息 / 退出 -->
        <div class="bottom-item user-item" :title="!sidebarExpanded ? (authStore.user?.username ?? '已登录') : ''">
          <span class="bottom-icon">
            <Icon icon="mdi:account-circle-outline" width="16" />
          </span>
          <span class="bottom-label user-label">
            <span class="user-name">{{ authStore.user?.username ?? '用户' }}</span>
          </span>
          <button
            v-if="sidebarExpanded"
            class="logout-btn"
            title="退出登录"
            @click.stop="handleLogout"
          >
            <Icon icon="mdi:logout" width="14" />
          </button>
        </div>
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

    <!-- 主题弹出面板（Teleport 到 body，避免被 overflow:hidden 裁剪） -->
    <Teleport to="body">
      <Transition name="picker-fade">
        <div
          v-if="showThemePicker"
          class="theme-picker-portal"
          :style="pickerStyle"
          @click.stop
        >
          <p class="picker-title">选择主题</p>
          <button class="picker-opt" :class="{ active: !isDark }" @click="setTheme('light')">
            <Icon icon="mdi:weather-sunny" width="15" />
            <span>浅色</span>
          </button>
          <button class="picker-opt" :class="{ active: isDark }" @click="setTheme('dark')">
            <Icon icon="mdi:weather-night" width="15" />
            <span>深色</span>
          </button>
        </div>
      </Transition>
    </Teleport>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { RouterView, RouterLink, useRouter } from 'vue-router'
import { Icon } from '@iconify/vue'
import AgentConsole from '@/components/AgentConsole.vue'
import { useBuildingStore } from '@/stores/buildingStore'
import { useAuthStore } from '@/stores/authStore'

const buildingStore = useBuildingStore()
const authStore = useAuthStore()
const router = useRouter()

async function handleLogout() {
  await authStore.logout()
  router.push('/login')
}

// ── 主题切换 ──────────────────────────────────────────
const savedTheme = localStorage.getItem('theme') ?? 'dark'
document.documentElement.dataset.theme = savedTheme
const isDark = ref(savedTheme === 'dark')

function setTheme(t: 'dark' | 'light') {
  isDark.value = t === 'dark'
  document.documentElement.dataset.theme = t
  localStorage.setItem('theme', t)
  showThemePicker.value = false
}

// ── 主题选择弹窗 ──────────────────────────────────────
const showThemePicker = ref(false)
const showAbout = ref(false)
const themeItemRef = ref<HTMLElement | null>(null)
const pickerStyle = ref({ top: '0px', left: '0px' })

function toggleThemePicker() {
  if (!showThemePicker.value && themeItemRef.value) {
    const rect = themeItemRef.value.getBoundingClientRect()
    pickerStyle.value = {
      top: `${rect.top - 10}px`,
      left: `${rect.right + 8}px`,
    }
  }
  showThemePicker.value = !showThemePicker.value
  showAbout.value = false
}

// 点击外部关闭弹窗
function onDocClick() {
  showThemePicker.value = false
  showAbout.value = false
}

// ── 导航栏展开逻辑 ────────────────────────────────────
// sidebarPinned: 钉住状态，点击 logo 切换，不受 hover 影响
// sidebarHovered: 鼠标悬停状态
// sidebarExpanded: 只要钉住或悬停，就展开
const sidebarPinned = ref(localStorage.getItem('sidebarPinned') === 'true')
const sidebarHovered = ref(false)
const sidebarExpanded = computed(() => sidebarPinned.value || sidebarHovered.value)

function togglePin() {
  sidebarPinned.value = !sidebarPinned.value
  localStorage.setItem('sidebarPinned', String(sidebarPinned.value))
}

function onSidebarEnter() {
  sidebarHovered.value = true
}

function onSidebarLeave() {
  sidebarHovered.value = false
}

onMounted(() => {
  buildingStore.fetchBuildings()
  document.addEventListener('click', onDocClick)
})

onUnmounted(() => {
  document.removeEventListener('click', onDocClick)
})

// ── 右侧面板宽度拖拽调整 ──────────────────────────
const PANEL_MIN = 240
const PANEL_MAX = 600
const panelWidth = ref(320)
const agentPanelWidth = computed(() => `${panelWidth.value}px`)
const resizing = ref(false)

function startResize(e: MouseEvent) {
  e.preventDefault()
  resizing.value = true
  const startX = e.clientX
  const startW = panelWidth.value

  function onMove(ev: MouseEvent) {
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
  /* 默认收起：仅显示图标 */
  width: 54px;
  flex-shrink: 0;
  background: var(--bg-panel);
  border-right: 1px solid var(--border);
  display: flex;
  flex-direction: column;
  padding: 0;
  overflow: hidden;
  box-shadow: var(--panel-shadow);
  position: relative;
  z-index: 20;
  transition: width 0.22s cubic-bezier(0.4, 0, 0.2, 1);
}

/* 展开状态 */
.sidebar.expanded {
  width: 176px;
}

/* ── 顶部 Logo 区域 ── */
.sidebar-logo {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 14px 11px 12px;
  flex-shrink: 0;
  overflow: hidden;
  min-width: 0;
}

/* Logo 徽章按钮（仿图片圆角方形图标） */
.logo-badge {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 32px;
  height: 32px;
  flex-shrink: 0;
  background: var(--accent);
  border: none;
  border-radius: 9px;
  color: #fff;
  cursor: pointer;
  transition: all 0.2s;
  box-shadow: 0 2px 8px rgba(96, 165, 250, 0.35);
}
.logo-badge:hover {
  transform: scale(1.06);
  box-shadow: 0 4px 14px rgba(96, 165, 250, 0.5);
}
/* 钉住状态：加一圈高亮轮廓 */
.logo-badge.pinned {
  box-shadow: 0 0 0 2px var(--bg-panel), 0 0 0 4px var(--accent), 0 2px 8px rgba(96, 165, 250, 0.4);
}

.logo-text {
  font-weight: 700;
  font-size: 14px;
  color: var(--text-primary);
  flex: 1;
  letter-spacing: 0.02em;
  white-space: nowrap;
  overflow: hidden;
  opacity: 0;
  transition: opacity 0.18s 0.04s;
  pointer-events: none;
}
.sidebar.expanded .logo-text {
  opacity: 1;
  pointer-events: auto;
}

.theme-toggle {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 26px;
  height: 26px;
  background: var(--bg-hover);
  border: 1px solid var(--border);
  border-radius: 6px;
  color: var(--text-secondary);
  cursor: pointer;
  transition: all 0.2s;
  flex-shrink: 0;
  padding: 0;
  opacity: 0;
  pointer-events: none;
}
.sidebar.expanded .theme-toggle {
  opacity: 1;
  pointer-events: auto;
}
.theme-toggle:hover {
  background: var(--accent-glow);
  border-color: var(--border-accent);
  color: var(--accent);
}

/* ── 导航菜单 ── */
.nav-list {
  list-style: none;
  padding: 10px 7px;
  flex-shrink: 0;
}

.nav-item {
  display: flex;
  align-items: center;
  gap: 9px;
  padding: 9px 8px;
  color: var(--text-secondary);
  text-decoration: none;
  font-size: 13px;
  font-weight: 500;
  border-radius: 8px;
  transition: all 0.2s;
  border-left: 2px solid transparent;
  margin-bottom: 2px;
  white-space: nowrap;
  overflow: hidden;
  /* 收起时居中图标 */
  justify-content: center;
}
.sidebar.expanded .nav-item {
  justify-content: flex-start;
  padding: 9px 12px;
}
.nav-item:hover {
  background: var(--bg-hover);
  color: var(--text-primary);
}
.sidebar.expanded .nav-item:hover {
  border-left-color: var(--border-accent);
}
.nav-item.active {
  background: var(--accent-glow);
  color: var(--accent);
}
.sidebar.expanded .nav-item.active {
  border-left-color: var(--accent);
  box-shadow: inset 0 0 0 1px var(--accent-glow-md);
}
/* 收起时 active 用圆圈边框代替左边框 */
.sidebar:not(.expanded) .nav-item.active {
  border-left-color: transparent;
  box-shadow: 0 0 0 1px var(--border-accent);
}

.nav-icon {
  display: flex;
  align-items: center;
  flex-shrink: 0;
}

.nav-label {
  opacity: 0;
  width: 0;
  overflow: hidden;
  pointer-events: none;
  transition: opacity 0.18s 0.04s;
  white-space: nowrap;
}
.sidebar.expanded .nav-label {
  opacity: 1;
  width: auto;
  pointer-events: auto;
}

/* ── 底部功能区 ── */
.sidebar-bottom {
  margin-top: auto;
  flex-shrink: 0;
  padding: 8px 7px 12px;
  border-top: 1px solid var(--border);
}

/* 底部通用功能项 */
.bottom-item {
  display: flex;
  align-items: center;
  gap: 9px;
  width: 100%;
  padding: 9px 8px;
  background: none;
  border: none;
  border-radius: 8px;
  color: var(--text-secondary);
  font-size: 13px;
  font-weight: 500;
  cursor: pointer;
  text-decoration: none;
  transition: all 0.2s;
  margin-bottom: 2px;
  overflow: hidden;
  white-space: nowrap;
  justify-content: center;
  position: relative;
}
.sidebar.expanded .bottom-item {
  justify-content: flex-start;
  padding: 9px 12px;
}
.bottom-item:hover {
  background: var(--bg-hover);
  color: var(--text-primary);
}

.bottom-icon {
  display: flex;
  align-items: center;
  flex-shrink: 0;
}

.bottom-label {
  opacity: 0;
  width: 0;
  overflow: hidden;
  pointer-events: none;
  transition: opacity 0.18s 0.04s;
  white-space: nowrap;
}
.sidebar.expanded .bottom-label {
  opacity: 1;
  width: auto;
  pointer-events: auto;
}

/* 主题选择项 */
.theme-item {
  user-select: none;
}

/* 用户信息项 */
.user-item {
  cursor: default;
}
.user-label {
  flex: 1;
  min-width: 0;
}
.user-name {
  display: block;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 12px;
  color: var(--text-secondary);
}
.logout-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 22px;
  height: 22px;
  background: none;
  border: 1px solid transparent;
  border-radius: 6px;
  color: var(--text-muted);
  cursor: pointer;
  flex-shrink: 0;
  padding: 0;
  transition: all 0.2s;
}
.logout-btn:hover {
  background: rgba(248, 113, 113, 0.1);
  border-color: rgba(248, 113, 113, 0.3);
  color: var(--danger);
}

/* 弹出动画（scoped 内的 Transition name 仍然有效） */
.picker-fade-enter-active,
.picker-fade-leave-active {
  transition: opacity 0.15s, transform 0.15s;
}
.picker-fade-enter-from,
.picker-fade-leave-to {
  opacity: 0;
  transform: translateX(-6px);
}

@keyframes spin {
  to { transform: rotate(360deg); }
}
.spin {
  animation: spin 1s linear infinite;
}

/* ── 中间主区 ── */
.canvas {
  flex: 1;
  min-width: 0;
  overflow-y: auto;
  background: var(--bg-dark);
  transition: background 0.25s;
}

/* ── 拖拽分隔条 ── */
.resize-handle {
  width: 4px;
  flex-shrink: 0;
  cursor: col-resize;
  background: var(--border);
  position: relative;
  transition: background 0.2s;
  z-index: 10;
}
.resize-handle:hover,
.resize-handle.resizing {
  background: var(--accent);
  box-shadow: 0 0 8px var(--accent-glow-md);
}
.resize-handle::before {
  content: '';
  position: absolute;
  inset: 0 -4px;
}

/* ── 右侧控制台 ── */
.agent-panel {
  flex-shrink: 0;
  width: v-bind(agentPanelWidth);
  border-left: none;
  overflow: hidden;
}
</style>

<!-- 全局样式：Teleport 渲染到 body，scoped 不可达，需用非 scoped 块 -->
<style>
.theme-picker-portal {
  position: fixed;
  width: 140px;
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: 10px;
  padding: 8px;
  box-shadow: var(--card-shadow);
  z-index: 9999;
}

.theme-picker-portal .picker-title {
  font-size: 10px;
  color: var(--text-muted);
  text-transform: uppercase;
  letter-spacing: 0.08em;
  font-weight: 600;
  margin-bottom: 6px;
  padding: 0 4px;
}

.theme-picker-portal .picker-opt {
  display: flex;
  align-items: center;
  gap: 8px;
  width: 100%;
  padding: 7px 8px;
  background: none;
  border: 1px solid transparent;
  border-radius: 7px;
  color: var(--text-secondary);
  font-size: 13px;
  cursor: pointer;
  transition: all 0.2s;
  margin-bottom: 2px;
}
.theme-picker-portal .picker-opt:hover {
  background: var(--bg-hover);
  color: var(--text-primary);
}
.theme-picker-portal .picker-opt.active {
  background: var(--accent-glow);
  border-color: var(--border-accent);
  color: var(--accent);
}

/* Teleport Transition 类名需要全局定义 */
.picker-fade-enter-active,
.picker-fade-leave-active {
  transition: opacity 0.15s, transform 0.15s;
}
.picker-fade-enter-from,
.picker-fade-leave-to {
  opacity: 0;
  transform: translateX(-6px);
}
</style>
