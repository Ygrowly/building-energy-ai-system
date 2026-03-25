<template>
  <Transition name="fab-fade">
    <button
      v-if="showFab"
      class="report-fab"
      :class="{ expanded: hovered }"
      @click="reportStore.openPreview()"
      @mouseenter="hovered = true"
      @mouseleave="hovered = false"
      title="生成报表"
    >
      <Icon icon="mdi:file-chart-outline" width="18" class="fab-icon" />
      <span class="fab-label">生成报表</span>
    </button>
  </Transition>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue'
import { useRoute } from 'vue-router'
import { Icon } from '@iconify/vue'
import { useReportStore } from '@/stores/reportStore'

const route = useRoute()
const reportStore = useReportStore()
const hovered = ref(false)

const EXPORTABLE_ROUTES = ['/home', '/querystats', '/operations']
const showFab = computed(() => EXPORTABLE_ROUTES.includes(route.path))
</script>

<style scoped>
.report-fab {
  position: fixed;
  bottom: 24px;
  /* 留出 agent-panel 宽度，默认 320px + 12px 间距 */
  right: calc(var(--agent-panel-width, 320px) + 16px);
  z-index: 500;
  display: flex;
  align-items: center;
  gap: 0;
  overflow: hidden;
  height: 40px;
  padding: 0 12px;
  border: none;
  border-radius: 20px;
  background: var(--accent, #5b8dee);
  color: #fff;
  cursor: pointer;
  box-shadow: 0 4px 16px rgba(91,141,238,0.40);
  transition: all 0.22s cubic-bezier(0.34, 1.56, 0.64, 1);
  white-space: nowrap;
  max-width: 40px;
}
.report-fab:hover,
.report-fab.expanded {
  max-width: 140px;
  padding: 0 16px;
  gap: 7px;
  box-shadow: 0 6px 24px rgba(91,141,238,0.52);
}
.fab-icon { flex-shrink: 0; }
.fab-label {
  font-size: 13px;
  font-weight: 600;
  width: 0;
  opacity: 0;
  overflow: hidden;
  transition: width 0.2s ease, opacity 0.2s ease;
  letter-spacing: 0.02em;
}
.report-fab:hover .fab-label,
.report-fab.expanded .fab-label {
  width: 56px;
  opacity: 1;
}

.fab-fade-enter-active,
.fab-fade-leave-active { transition: opacity 0.2s ease, transform 0.2s ease; }
.fab-fade-enter-from,
.fab-fade-leave-to { opacity: 0; transform: scale(0.85); }
</style>
