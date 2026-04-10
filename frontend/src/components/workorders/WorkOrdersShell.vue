<template>
  <div class="workorders notranslate" translate="no">
    <header class="page-header">
      <div class="header-copy">
        <h1><Icon icon="mdi:clipboard-list" width="22" class="page-icon" /> {{ workspaceConfig.title }}</h1>
        <span class="subtitle">{{ workspaceConfig.subtitle }}</span>
      </div>
      <div class="workspace-pills" aria-label="工单页面切换">
        <button
          v-for="item in workspaceSwitchItems"
          :key="item.mode"
          class="workspace-pill"
          :class="{ active: workspaceMode === item.mode }"
          @click="$emit('switch-workspace', item.path)"
        >
          <Icon :icon="item.icon" width="14" />
          <span>{{ item.label }}</span>
        </button>
      </div>
    </header>

    <div class="toolbar">
      <div class="tab-group">
        <button
          v-for="tab in tabs"
          :key="tab.value"
          class="tab-btn"
          :class="{ active: activeTab === tab.value }"
          @click="$emit('switch-tab', tab.value)"
        >
          {{ tab.label }}
          <span class="tab-count" v-if="tabCountValue(tab.value) > 0">{{ tabCountValue(tab.value) }}</span>
        </button>
      </div>
      <div class="toolbar-actions">
        <div v-if="activeTab === 'auto_dispatch_review'" class="inline-filter" aria-label="自动派工复核筛选">
          <button
            v-for="item in autoDispatchReviewStatusOptions"
            :key="item.value"
            class="filter-chip"
            :class="{ active: autoDispatchReviewStatus === item.value }"
            @click="$emit('switch-auto-dispatch-review-status', item.value)"
          >
            {{ item.label }}
          </button>
        </div>
        <button
          v-if="activeTab === 'pending_dispatch'"
          class="refresh-btn accent"
          @click="$emit('open-batch-dispatch')"
          :disabled="loading || batchPreviewLoading"
        >
          <Icon :icon="batchPreviewLoading ? 'mdi:loading' : 'mdi:playlist-plus'" width="14" class="btn-icon" />
          {{ batchPreviewLoading ? '生成中...' : '批量推荐' }}
        </button>
        <button class="refresh-btn" @click="$emit('refresh')" :disabled="loading">
          <Icon :icon="loading ? 'mdi:loading' : 'mdi:refresh'" width="14" class="btn-icon" />
          {{ loading ? '刷新中...' : '刷新' }}
        </button>
      </div>
    </div>

    <div class="summary-strip" v-if="activeTab !== 'shared_hall' && activeTab !== 'auto_dispatch_insights' && allOrdersCount > 0">
      <div class="summary-pill">
        <span class="summary-value">{{ allOrdersCount }}</span>
        <span class="summary-label">工单总数</span>
      </div>
      <div class="summary-pill warning">
        <span class="summary-value">{{ tabCountValue('pending_dispatch') }}</span>
        <span class="summary-label">待派工</span>
      </div>
      <div class="summary-pill active">
        <span class="summary-value">{{ tabCountValue('dispatched') }}</span>
        <span class="summary-label">执行中</span>
      </div>
      <div class="summary-pill danger">
        <span class="summary-value">{{ overdueCount }}</span>
        <span class="summary-label">高风险</span>
      </div>
    </div>

    <div class="summary-strip" v-if="activeTab === 'shared_hall' && hallEntriesCount > 0">
      <div class="summary-pill">
        <span class="summary-value">{{ hallEntriesCount }}</span>
        <span class="summary-label">大厅事项</span>
      </div>
      <div class="summary-pill active">
        <span class="summary-value">{{ hallSupportCount }}</span>
        <span class="summary-label">协同事项</span>
      </div>
      <div class="summary-pill warning">
        <span class="summary-value">{{ hallTakeoverCount }}</span>
        <span class="summary-label">待接管</span>
      </div>
      <div class="summary-pill danger">
        <span class="summary-value">{{ hallPendingApplicationCount }}</span>
        <span class="summary-label">待处理申请</span>
      </div>
    </div>

    <div v-if="loading" class="loading-bar">加载工单列表...</div>
    <div v-if="fetchError" class="error-bar"><Icon icon="mdi:alert" width="14" class="bar-icon" /> {{ fetchError }}</div>

    <slot />

    <div v-if="!loading && isCurrentTabEmpty && !fetchError" class="empty-state">
      <p class="empty-icon"><Icon icon="mdi:clipboard-list" width="40" /></p>
      <p>{{ emptyMessage }}</p>
      <p class="empty-sub">系统会根据 AI 审阅、派工和执行推进自动更新这里的状态。</p>
    </div>

    <slot name="overlays" />
  </div>
</template>

<script setup lang="ts">
import { Icon } from '@iconify/vue'
import { PropType } from 'vue'
import type { WorkOrderTabKey, WorkOrderWorkspaceMode } from '@/constants/workOrders'

defineEmits<{
  'switch-workspace': [path: string]
  'switch-tab': [tab: WorkOrderTabKey]
  'switch-auto-dispatch-review-status': [status: 'pending' | 'reviewed' | 'needs_reassign' | 'all']
  'open-batch-dispatch': []
  refresh: []
}>()

const autoDispatchReviewStatusOptions = [
  { label: '待复核', value: 'pending' },
  { label: '已复核', value: 'reviewed' },
  { label: '需改派', value: 'needs_reassign' },
  { label: '全部', value: 'all' },
] as const

const props = defineProps({
  workspaceConfig: {
    type: Object as PropType<{ title: string; subtitle: string }>,
    required: true,
  },
  workspaceSwitchItems: {
    type: Array as PropType<Array<{ mode: WorkOrderWorkspaceMode; label: string; icon: string; path: string }>>,
    required: true,
  },
  workspaceMode: {
    type: String as PropType<WorkOrderWorkspaceMode>,
    required: true,
  },
  tabs: {
    type: Array as PropType<Array<{ value: WorkOrderTabKey; label: string }>>,
    required: true,
  },
  activeTab: {
    type: String as PropType<WorkOrderTabKey>,
    required: true,
  },
  autoDispatchReviewStatus: {
    type: String as PropType<'pending' | 'reviewed' | 'needs_reassign' | 'all'>,
    default: 'pending',
  },
  loading: {
    type: Boolean,
    required: true,
  },
  batchPreviewLoading: {
    type: Boolean,
    required: true,
  },
  allOrdersCount: {
    type: Number,
    required: true,
  },
  hallEntriesCount: {
    type: Number,
    required: true,
  },
  overdueCount: {
    type: Number,
    required: true,
  },
  hallSupportCount: {
    type: Number,
    required: true,
  },
  hallTakeoverCount: {
    type: Number,
    required: true,
  },
  hallPendingApplicationCount: {
    type: Number,
    required: true,
  },
  fetchError: {
    type: String,
    required: true,
  },
  isCurrentTabEmpty: {
    type: Boolean,
    required: true,
  },
  emptyMessage: {
    type: String,
    required: true,
  },
  tabCount: {
    type: Function as PropType<(tab: WorkOrderTabKey) => number>,
    required: true,
  },
})

const tabCountValue = (tab: WorkOrderTabKey) => props.tabCount(tab)
</script>

<style scoped>
.workorders { padding: 24px; }
.page-header {
  margin-bottom: 20px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 18px;
  padding: 14px 16px;
  border: 1px solid rgba(245, 158, 11, 0.24);
  border-radius: 18px;
  background:
    linear-gradient(135deg, rgba(255, 251, 235, 0.84), rgba(240, 253, 244, 0.7)),
    var(--bg-panel);
  box-shadow: 0 12px 30px rgba(15, 23, 42, 0.06);
}
.header-copy { min-width: 0; }
.page-header h1 { font-size: 22px; font-weight: 700; margin-bottom: 4px; display: flex; align-items: center; gap: 8px; }
.subtitle { color: var(--text-secondary); font-size: 13px; }
.workspace-pills {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  flex-shrink: 0;
  padding: 4px;
  border: 1px solid rgba(245, 158, 11, 0.26);
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.68);
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.8);
}
.workspace-pill {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  border: none;
  border-radius: 999px;
  padding: 8px 13px;
  background: transparent;
  color: #7c6f4b;
  font-size: 12px;
  font-weight: 700;
  white-space: nowrap;
  cursor: pointer;
  transition: all 0.18s ease;
}
.workspace-pill:hover {
  color: #166534;
  background: rgba(22, 163, 74, 0.08);
}
.workspace-pill.active {
  color: #065f46;
  background: linear-gradient(135deg, rgba(34, 197, 94, 0.18), rgba(250, 204, 21, 0.16));
  box-shadow: 0 6px 16px rgba(22, 163, 74, 0.12);
}
.toolbar { display: flex; justify-content: space-between; align-items: center; gap: 16px; margin-bottom: 16px; }
.toolbar-actions { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; justify-content: flex-end; }
.tab-group { display: flex; flex-wrap: wrap; gap: 6px; }
.tab-btn, .refresh-btn, .link-btn { background: none; border: 1px solid var(--border); border-radius: 8px; color: var(--text-secondary); font-size: 13px; padding: 8px 14px; cursor: pointer; transition: all 0.2s; }
.tab-btn { display: flex; align-items: center; gap: 6px; }
.tab-btn.active { background: var(--accent-glow); border-color: var(--border-accent); color: var(--accent); font-weight: 600; }
.inline-filter { display: inline-flex; align-items: center; gap: 6px; flex-wrap: wrap; }
.filter-chip { border: 1px solid var(--border); border-radius: 8px; background: var(--bg-panel); color: var(--text-secondary); font-size: 12px; font-weight: 600; padding: 7px 10px; cursor: pointer; }
.filter-chip.active { background: rgba(34, 197, 94, 0.12); border-color: rgba(34, 197, 94, 0.28); color: #166534; }
.refresh-btn.accent { background: var(--accent); border-color: var(--accent); color: white; }
.refresh-btn.inline { padding: 7px 12px; }
.refresh-btn.warn { border-color: rgba(245, 158, 11, 0.24); color: #b45309; background: rgba(245, 158, 11, 0.08); }
.tab-count { background: rgba(59, 130, 246, 0.12); color: var(--accent); border-radius: 999px; padding: 1px 8px; font-size: 11px; }
.summary-strip { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 12px; margin-bottom: 16px; }
.summary-pill { background: var(--bg-panel); border: 1px solid var(--border); border-radius: 12px; padding: 14px 16px; display: flex; flex-direction: column; gap: 4px; }
.summary-pill.warning { border-color: rgba(59, 130, 246, 0.22); }
.summary-pill.active { border-color: rgba(16, 185, 129, 0.22); }
.summary-pill.danger { border-color: rgba(248, 113, 113, 0.22); }
.summary-value { font-size: 22px; font-weight: 700; color: var(--text-primary); }
.summary-label { font-size: 12px; color: var(--text-muted); }
.loading-bar, .error-bar { border-radius: 10px; padding: 12px 16px; font-size: 13px; margin-bottom: 12px; }
.loading-bar { background: var(--accent-glow); border: 1px solid var(--border-accent); color: var(--accent); }
.error-bar { background: rgba(248,113,113,0.08); border: 1px solid rgba(248,113,113,0.24); color: var(--danger); }
.empty-state { display: flex; flex-direction: column; align-items: center; gap: 8px; padding: 100px 0; color: var(--text-muted); }
.empty-sub { font-size: 12px; }

@media (max-width: 1100px) {
  .page-header { align-items: flex-start; flex-direction: column; }
  .workspace-pills { width: 100%; overflow-x: auto; }
}
</style>
