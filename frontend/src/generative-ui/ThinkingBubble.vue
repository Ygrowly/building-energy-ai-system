<template>
  <div class="thinking-bubble" :class="{ collapsed }">
    <div class="thinking-header" @click="collapsed = !collapsed">
      <span class="agent-icon">{{ agentIcon }}</span>
      <span class="agent-label">{{ agentLabel }}</span>
      <span class="thinking-dot" v-if="!collapsed">
        <span></span><span></span><span></span>
      </span>
      <span class="thinking-text" v-if="!collapsed">{{ message }}</span>
      <button class="collapse-btn">{{ collapsed ? '▶' : '▼' }}</button>
    </div>
    <div class="thinking-body" v-if="!collapsed">
      <p>{{ message }}</p>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue'

const props = defineProps<{
  agent: string
  message: string
}>()

const collapsed = ref(false)

const agentIcon = computed(() => {
  const icons: Record<string, string> = {
    router: '🔀',
    data_agent: '📊',
    diagnose_agent: '🔬',
    tool: '⚙️',
  }
  return icons[props.agent] ?? '🤖'
})

const agentLabel = computed(() => {
  const labels: Record<string, string> = {
    router: '路由前台',
    data_agent: '数据分析师',
    diagnose_agent: '故障诊断专家',
    tool: '工具调用',
  }
  return labels[props.agent] ?? props.agent
})
</script>

<style scoped>
.thinking-bubble {
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-left: 3px solid var(--thinking-color);
  border-radius: 8px;
  margin: 6px 0;
  overflow: hidden;
  transition: all 0.2s;
  font-size: 12px;
}

.thinking-header {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 12px;
  cursor: pointer;
  user-select: none;
  color: var(--thinking-color);
}

.agent-icon { font-size: 14px; }
.agent-label { font-weight: 600; }

.thinking-dot {
  display: flex;
  gap: 3px;
  margin-left: 4px;
}
.thinking-dot span {
  width: 4px;
  height: 4px;
  border-radius: 50%;
  background: var(--thinking-color);
  animation: bounce 1.2s infinite;
}
.thinking-dot span:nth-child(2) { animation-delay: 0.2s; }
.thinking-dot span:nth-child(3) { animation-delay: 0.4s; }

@keyframes bounce {
  0%, 80%, 100% { transform: translateY(0); opacity: 0.5; }
  40% { transform: translateY(-4px); opacity: 1; }
}

.thinking-text {
  color: var(--text-secondary);
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.collapse-btn {
  background: none;
  border: none;
  color: var(--text-muted);
  cursor: pointer;
  font-size: 10px;
  padding: 0;
  margin-left: auto;
}

.thinking-body {
  padding: 0 12px 10px;
  color: var(--text-secondary);
  border-top: 1px solid var(--border);
  padding-top: 8px;
}

.collapsed .thinking-body { display: none; }
</style>
