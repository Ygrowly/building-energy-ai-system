<template>
  <div class="wo-card" :class="statusClass">
    <div class="wo-header">
      <span class="wo-icon"><Icon icon="mdi:tools" width="16" /></span>
      <span class="wo-title">维修工单</span>
      <span class="wo-badge" :class="priorityClass">{{ priority }}</span>
      <span class="wo-status-badge">{{ statusLabel }}</span>
    </div>

    <div class="wo-body">
      <div class="wo-field">
        <span class="wo-label">工单 ID</span>
        <span class="wo-val mono">{{ ticketId }}</span>
      </div>
      <div class="wo-field">
        <span class="wo-label">设备</span>
        <span class="wo-val mono">{{ deviceId }}</span>
      </div>
      <div class="wo-field">
        <span class="wo-label">建筑</span>
        <span class="wo-val">{{ buildingId }}</span>
      </div>
      <div class="wo-field">
        <span class="wo-label">问题描述</span>
        <span class="wo-val">{{ issueDescription }}</span>
      </div>
      <div class="wo-field">
        <span class="wo-label">建议操作</span>
        <span class="wo-val accent">{{ suggestedAction }}</span>
      </div>
    </div>

    <!-- 操作按钮（仅 pending 状态显示） -->
    <div class="wo-actions" v-if="isPending && !readonly">
      <button class="btn-approve" @click="emit('approve')" :disabled="isProcessing">
        <Icon icon="mdi:check-circle" width="14" /> 批准派单
      </button>
      <button class="btn-reject" @click="showRejectInput = !showRejectInput" :disabled="isProcessing">
        <Icon icon="mdi:close-circle" width="14" /> 驳回
      </button>
    </div>

    <div class="reject-input" v-if="showRejectInput && !readonly">
      <input
        v-model="rejectReason"
        placeholder="请输入驳回原因（可选）"
        @keyup.enter="doReject"
      />
      <button @click="doReject">确认驳回</button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue'
import { Icon } from '@iconify/vue'
import type { ArtifactEvent } from '@/api/stream_client'

const props = defineProps<{
  artifact: ArtifactEvent
  isProcessing?: boolean
  readonly?: boolean
}>()

const emit = defineEmits<{
  approve: []
  reject: [reason?: string]
}>()

const payload = computed(() => (props.artifact.data_payload as Record<string, string>) ?? {})
const ticketId = computed(() => payload.value.ticket_id ?? '-')
const deviceId = computed(() => payload.value.device_id ?? '-')
const buildingId = computed(() => payload.value.building_id ?? '-')
const issueDescription = computed(() => payload.value.issue_description ?? '-')
const suggestedAction = computed(() => payload.value.suggested_action ?? '-')
const priority = computed(() => payload.value.priority ?? 'Medium')
const status = computed(() => payload.value.status ?? 'pending_approval')

const isPending = computed(() => status.value === 'pending_approval')
const statusLabel = computed(() => isPending.value ? '待审批' : status.value === 'approved' ? '已批准' : '已驳回')

const statusClass = computed(() => ({
  'status-pending': isPending.value,
  'status-approved': status.value === 'approved',
  'status-rejected': status.value === 'rejected',
}))

const priorityClass = computed(() => ({
  'priority-low': priority.value === 'Low',
  'priority-medium': priority.value === 'Medium',
  'priority-high': priority.value === 'High',
  'priority-critical': priority.value === 'Critical',
}))

const showRejectInput = ref(false)
const rejectReason = ref('')

function doReject() {
  emit('reject', rejectReason.value || undefined)
  showRejectInput.value = false
}
</script>

<style scoped>
.wo-card {
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: 10px;
  margin: 8px 0;
  overflow: hidden;
  transition: box-shadow 0.2s, border-color 0.2s;
  box-shadow: var(--card-shadow);
}
.wo-card:hover {
  box-shadow: var(--card-shadow-hover);
}
.status-pending { border-left: 4px solid var(--warning); }
.status-approved { border-left: 4px solid var(--success); }
.status-rejected { border-left: 4px solid var(--text-muted); }

.wo-header {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 12px 16px;
  background: var(--bg-panel);
}

.wo-icon { display: flex; align-items: center; color: var(--warning); }
.wo-title { font-weight: 700; font-size: 14px; }

.wo-badge {
  font-size: 11px;
  padding: 2px 8px;
  border-radius: 10px;
  font-weight: 600;
}
.priority-low    { background: rgba(74,222,128,0.15); color: var(--success); }
.priority-medium { background: rgba(251,191,36,0.15); color: var(--warning); }
.priority-high   { background: rgba(248,113,113,0.15); color: var(--danger); }
.priority-critical { background: rgba(248,113,113,0.3); color: var(--danger); animation: pulse 1.5s infinite; }

@keyframes pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.6; } }

.wo-status-badge {
  margin-left: auto;
  font-size: 11px;
  color: var(--text-muted);
}

.wo-body { padding: 12px 16px; }

.wo-field {
  display: grid;
  grid-template-columns: 80px 1fr;
  gap: 8px;
  padding: 4px 0;
  font-size: 13px;
  border-bottom: 1px solid var(--border);
}
.wo-field:last-child { border-bottom: none; }
.wo-label { color: var(--text-muted); font-size: 12px; align-self: start; padding-top: 2px; }
.wo-val { color: var(--text-primary); }
.wo-val.mono { font-family: monospace; color: var(--accent); }
.wo-val.accent { color: var(--warning); }

.wo-actions {
  display: flex;
  gap: 8px;
  padding: 12px 16px;
  border-top: 1px solid var(--border);
}

.btn-approve, .btn-reject {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 8px 20px;
  border-radius: 6px;
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
  border: none;
  transition: all 0.2s;
}
.btn-approve { background: var(--success); color: #000; }
.btn-approve:hover { opacity: 0.85; }
.btn-reject { background: var(--bg-hover); color: var(--danger); border: 1px solid var(--danger); }
.btn-reject:hover { background: rgba(248,113,113,0.1); }
.btn-approve:disabled, .btn-reject:disabled { opacity: 0.5; cursor: not-allowed; }

.reject-input {
  display: flex;
  gap: 8px;
  padding: 0 16px 12px;
}
.reject-input input {
  flex: 1;
  background: var(--bg-hover);
  border: 1px solid var(--border);
  border-radius: 4px;
  color: var(--text-primary);
  padding: 6px 10px;
  font-size: 13px;
}
.reject-input button {
  background: var(--bg-hover);
  border: 1px solid var(--border);
  border-radius: 4px;
  color: var(--text-secondary);
  padding: 6px 12px;
  cursor: pointer;
  font-size: 13px;
}
</style>
