<template>
  <!-- 登录/注册：全屏独立页，无侧栏、无 Agent 面板 -->
  <div v-if="isStandaloneAuth" class="auth-shell">
    <RouterView />
  </div>

  <div v-else class="app-layout">
    <!-- 左侧导航栏 -->
    <nav
      class="sidebar"
      :class="{ expanded: sidebarExpanded, pinned: sidebarPinned }"
      @mouseenter="onSidebarEnter"
      @mouseleave="onSidebarLeave"
    >
      <!-- 导航菜单（含 Logo） -->
      <ul class="nav-list">
        <!-- Logo 作为第一个列表项，与导航图标共享同一 flex 布局 -->
        <li class="logo-li">
          <button
            class="logo-badge"
            :class="{ pinned: sidebarPinned }"
            @click="togglePin"
            :title="sidebarPinned ? '已钉住，点击取消固定' : '点击钉住导航栏'"
          >
            <Icon icon="mdi:lightning-bolt" width="16" />
          </button>
          <span class="logo-text">能耗管理</span>
        </li>

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
        <!-- 我的 -->
        <button class="bottom-about" title="我的">
          <Icon icon="mdi:account-circle-outline" width="16" />
        </button>
        <!-- 主题选择（仅展开时显示） -->
        <div ref="themeItemRef" class="bottom-theme" title="主题" @click.stop="toggleThemePicker">
          <Icon icon="mdi:palette-outline" width="16" />
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
          <button class="picker-opt" :class="{ active: currentTheme === 'light' }" @click="setTheme('light')">
            <Icon icon="mdi:leaf" width="15" />
            <span>绿色</span>
          </button>
          <button class="picker-opt" :class="{ active: currentTheme === 'dark' }" @click="setTheme('dark')">
            <Icon icon="mdi:weather-night" width="15" />
            <span>深色</span>
          </button>
        </div>
      </Transition>
    </Teleport>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted, watch } from 'vue'
import { RouterView, RouterLink, useRouter, useRoute } from 'vue-router'
import { Icon } from '@iconify/vue'
import AgentConsole from '@/components/AgentConsole.vue'
import { useBuildingStore } from '@/stores/buildingStore'
import { useAuthStore } from '@/stores/authStore'

const buildingStore = useBuildingStore()
const authStore = useAuthStore()
const router = useRouter()
const route = useRoute()

/** 认证页单独全屏，不套主布局（避免侧栏 + 对话面板） */
const isStandaloneAuth = computed(() => route.meta.standaloneAuth === true)

async function handleLogout() {
  await authStore.logout()
  router.push('/login')
}

// ── 主题切换 ──────────────────────────────────────────
const savedTheme = localStorage.getItem('theme') ?? 'dark'
document.documentElement.dataset.theme = savedTheme
const currentTheme = ref(savedTheme)

function setTheme(t: 'dark' | 'light') {
  currentTheme.value = t
  document.documentElement.dataset.theme = t
  localStorage.setItem('theme', t)
  showThemePicker.value = false
}

// ── 主题选择弹窗 ──────────────────────────────────────
const showThemePicker = ref(false)
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
}

// 点击外部关闭弹窗
function onDocClick() {
  showThemePicker.value = false
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

// 进入主布局时再拉楼宇（纯登录首屏不请求，登录后进仪表盘会触发）
watch(
  () => route.meta.standaloneAuth,
  (standalone) => {
    if (standalone !== true) buildingStore.fetchBuildings()
  },
  { immediate: true },
)

onMounted(() => {
  document.addEventListener('click', onDocClick)
})

onUnmounted(() => {
  document.removeEventListener('click', onDocClick)
})

// ── 右侧面板宽度拖拽调整 ──────────────────────────
const PANEL_MIN = 240
const PANEL_MAX = 1000
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
  { path: '/home',       icon: 'mdi:home',            label: '首页' },
  { path: '/dashboard',  icon: 'mdi:view-dashboard',  label: '驾驶舱' },
  { path: '/operations', icon: 'mdi:wrench',           label: '智慧运维' },
  { path: '/workorders', icon: 'mdi:clipboard-list',   label: '工单管理' },
  { path: '/datacenter', icon: 'mdi:database-outline', label: '数据中心' },
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
/* 登录/注册全屏壳层 */
.auth-shell {
  min-height: 100vh;
  height: 100%;
  width: 100%;
  overflow: auto;
  background: var(--bg-dark);
  display: block;
}

.app-layout {
  display: flex;
  height: 100vh;
  overflow: hidden;
  padding: 0 0 0 14px;
  gap: 0;
  box-sizing: border-box;
}

/* ── 左侧导航 ── */
.sidebar {
  /* 默认收起：仅显示图标 */
  width: 60px;
  flex-shrink: 0;
  background: var(--bg-panel);
  border-right: none;
  border-radius: 16px;
  display: flex;
  flex-direction: column;
  padding: 0;
  margin: 8px 0;
  overflow: visible;
  box-shadow: none;
  position: relative;
  z-index: 20;
  transition: width 0.22s cubic-bezier(0.4, 0, 0.2, 1);
}

/* 展开状态 */
.sidebar.expanded {
  width: 176px;
}

/* ── Logo 列表项（与导航项共享 nav-list 布局） ── */
.logo-li {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  width: 36px;
  flex-shrink: 0;
  gap: 6px;
  overflow: visible;
  margin-bottom: 20px;
}
.sidebar.expanded .logo-li {
  width: 100%;
}

/* Logo 徽章按钮 */
.logo-badge {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 32px;
  height: 32px;
  flex-shrink: 0;
  background: var(--accent);
  border: none;
  border-radius: 50%;
  color: #fff;
  cursor: pointer;
  transition: all 0.2s;
  box-shadow: 0 2px 8px var(--accent-glow-md);
}
.logo-badge:hover {
  transform: scale(1.06);
  box-shadow: 0 4px 14px var(--accent-glow-md);
}
/* 钉住状态：加一圈高亮轮廓 */
.logo-badge.pinned {
  box-shadow: 0 0 0 2px var(--bg-panel), 0 0 0 3px var(--accent), 0 2px 8px var(--accent-glow-md);
}

.logo-text {
  font-weight: 700;
  font-size: 13px;
  color: var(--text-primary);
  letter-spacing: 0.04em;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  text-align: center;
  max-width: 0;
  height: 0;
  opacity: 0;
  transition: max-width 0.22s cubic-bezier(0.4, 0, 0.2, 1), opacity 0.18s, height 0.18s;
}
.sidebar.expanded .logo-text {
  max-width: 140px;
  height: auto;
  opacity: 1;
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
  padding: 24px 9px 6px;
  flex-shrink: 0;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 4px;
}

.nav-list li {
  display: flex;
  width: 36px;
  flex-shrink: 0;
}
.sidebar.expanded .nav-list li {
  width: 100%;
}

.nav-item {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 36px;
  height: 36px;
  padding: 0;
  color: #fff;
  text-decoration: none;
  font-size: 11px;
  font-weight: 500;
  border-radius: 50%;
  transition: background 0.2s, color 0.2s, border-radius 0.2s;
  border-left: none;
  white-space: nowrap;
  overflow: hidden;
  flex-shrink: 0;
}
.sidebar.expanded .nav-item {
  width: 100%;
  border-radius: 10px;
  justify-content: flex-start;
  padding: 9px 12px;
  gap: 9px;
}
.nav-item:hover {
  background: var(--bg-hover);
  color: var(--text-primary);
}
.nav-item.active {
  background: var(--accent-glow);
  color: var(--accent);
  border-radius: 50%;
}
.sidebar.expanded .nav-item.active {
  box-shadow: inset 0 0 0 1px var(--accent-glow-md);
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
  padding: 6px 9px 12px;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 4px;
}
.sidebar.expanded .sidebar-bottom {
  justify-content: space-between;
}

/* 关于我的 */
.bottom-about {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 36px;
  height: 36px;
  padding: 0;
  background: none;
  border: none;
  border-radius: 50%;
  color: #fff;
  font-size: 13px;
  font-weight: 500;
  cursor: pointer;
  transition: color 0.2s;
  overflow: hidden;
  white-space: nowrap;
  flex-shrink: 0;
}
.sidebar.expanded .bottom-about {
  width: auto;
  border-radius: 10px;
  justify-content: flex-start;
  padding: 9px 12px;
  gap: 9px;
}
.bottom-about:hover {
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

/* 主题图标（收起时隐藏，展开时显示） */
.bottom-theme {
  display: none;
  align-items: center;
  justify-content: center;
  width: 36px;
  height: 36px;
  padding: 0;
  background: none;
  border: none;
  border-radius: 50%;
  color: #fff;
  cursor: pointer;
  transition: color 0.2s;
  flex-shrink: 0;
  user-select: none;
}
.sidebar.expanded .bottom-theme {
  display: flex;
}
.bottom-theme:hover {
  color: var(--text-primary);
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
  background: transparent;
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
