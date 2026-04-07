<template>
  <div class="hall-list">
    <div class="hall-card" v-for="entry in hallEntries" :key="entry.id">
      <div class="hall-card-head">
        <div class="hall-badge-row">
          <span class="candidate-tag">{{ entry.entry_type === 'support_request' ? '工单大厅协同' : '超时待接管' }}</span>
          <span class="candidate-tag">{{ priorityLabels[entry.work_order?.priority] ?? entry.work_order?.priority ?? '普通工单' }}</span>
        </div>
        <span class="card-meta">{{ formatTimeValue(entry.created_at) }}</span>
      </div>

      <p class="card-title">{{ hallEntryTitleValue(entry) }}</p>
      <p class="card-meta">工单 {{ entry.work_order?.ticket_id || '—' }} · {{ buildingNameValue(entry.work_order?.building_id || '') }} · {{ hallEntryOwnerValue(entry) }}</p>

      <div class="detail-grid hall-detail-grid">
        <div class="detail-row">
          <span class="detail-label">进入原因</span>
          <span class="detail-val wrap">{{ hallEntryReasonValue(entry) }}</span>
        </div>
        <div class="detail-row">
          <span class="detail-label">建议措施</span>
          <span class="detail-val wrap">{{ entry.work_order?.suggested_action || '请先核对现场后再确认是否介入' }}</span>
        </div>
      </div>

      <div class="timeline-block">
        <p class="section-title">待处理申请</p>
        <div v-if="pendingApplications(entry).length" class="candidate-list">
          <div class="candidate-card" v-for="application in pendingApplications(entry)" :key="application.id">
            <div class="candidate-head">
              <div>
                <p class="candidate-name">{{ application.applicant_username || '维修人员' }}</p>
                <p class="candidate-meta">{{ application.application_type === 'takeover' ? '申请接管' : '申请协同' }} · {{ formatTimeValue(application.created_at) }}</p>
              </div>
              <span class="score-pill">待处理</span>
            </div>
            <p class="candidate-note">{{ application.note || '未填写备注' }}</p>
            <div class="action-bar hall-action-bar">
              <button
                class="action-btn primary"
                @click="$emit('approve', entry, application)"
                :disabled="actionLoading === hallActionKeyValue(entry.id, application.id, 'approve')"
              >
                {{ actionLoading === hallActionKeyValue(entry.id, application.id, 'approve') ? '处理中...' : '同意' }}
              </button>
              <button
                class="action-btn danger"
                @click="$emit('reject', entry, application)"
                :disabled="actionLoading === hallActionKeyValue(entry.id, application.id, 'reject')"
              >
                {{ actionLoading === hallActionKeyValue(entry.id, application.id, 'reject') ? '处理中...' : '驳回' }}
              </button>
            </div>
          </div>
        </div>
        <p v-else class="timeline-hint">{{ hallEmptyHintValue(entry) }}</p>
      </div>

      <div class="action-bar">
        <button
          v-if="canSuggestHallTakeoverValue(entry)"
          class="action-btn secondary"
          @click="$emit('suggest', entry)"
          :disabled="actionLoading === hallActionKeyValue(entry.id, '', 'suggest')"
        >
          {{ actionLoading === hallActionKeyValue(entry.id, '', 'suggest') ? '处理中...' : '改派建议' }}
        </button>
        <button
          v-if="canNudgeHallOwnerValue(entry)"
          class="action-btn secondary"
          @click="$emit('nudge', entry)"
          :disabled="actionLoading === hallActionKeyValue(entry.id, '', 'nudge')"
        >
          {{ actionLoading === hallActionKeyValue(entry.id, '', 'nudge') ? '处理中...' : '催办责任人' }}
        </button>
        <button
          class="action-btn danger"
          @click="$emit('close-entry', entry)"
          :disabled="actionLoading === hallActionKeyValue(entry.id, '', 'close')"
        >
          {{ actionLoading === hallActionKeyValue(entry.id, '', 'close') ? '处理中...' : '关闭共享事项' }}
        </button>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { PropType } from 'vue'

const props = defineProps({
  hallEntries: {
    type: Array as PropType<any[]>,
    required: true,
  },
  actionLoading: {
    type: String as PropType<string | null>,
    default: null,
  },
  priorityLabels: {
    type: Object as PropType<Record<string, string>>,
    required: true,
  },
  formatTime: {
    type: Function as PropType<(value?: string | null) => string>,
    required: true,
  },
  buildingName: {
    type: Function as PropType<(id: string) => string>,
    required: true,
  },
  hallPendingApplications: {
    type: Function as PropType<(entry: any) => any[]>,
    required: true,
  },
  hallEntryTitle: {
    type: Function as PropType<(entry: any) => string>,
    required: true,
  },
  hallEntryOwner: {
    type: Function as PropType<(entry: any) => string>,
    required: true,
  },
  hallEntryReason: {
    type: Function as PropType<(entry: any) => string>,
    required: true,
  },
  hallEmptyHint: {
    type: Function as PropType<(entry: any) => string>,
    required: true,
  },
  canSuggestHallTakeover: {
    type: Function as PropType<(entry: any) => boolean>,
    required: true,
  },
  canNudgeHallOwner: {
    type: Function as PropType<(entry: any) => boolean>,
    required: true,
  },
  hallActionKey: {
    type: Function as PropType<(entryId: string, applicationId: string, action: 'approve' | 'reject' | 'close' | 'suggest' | 'nudge') => string>,
    required: true,
  },
})

defineEmits<{
  approve: [entry: any, application: any]
  reject: [entry: any, application: any]
  suggest: [entry: any]
  nudge: [entry: any]
  'close-entry': [entry: any]
}>()

const pendingApplications = (entry: any) => props.hallPendingApplications(entry)
const hallEntryTitleValue = (entry: any) => props.hallEntryTitle(entry)
const hallEntryOwnerValue = (entry: any) => props.hallEntryOwner(entry)
const hallEntryReasonValue = (entry: any) => props.hallEntryReason(entry)
const hallEmptyHintValue = (entry: any) => props.hallEmptyHint(entry)
const canSuggestHallTakeoverValue = (entry: any) => props.canSuggestHallTakeover(entry)
const canNudgeHallOwnerValue = (entry: any) => props.canNudgeHallOwner(entry)
const hallActionKeyValue = (entryId: string, applicationId: string, action: 'approve' | 'reject' | 'close' | 'suggest' | 'nudge') =>
  props.hallActionKey(entryId, applicationId, action)
const buildingNameValue = (id: string) => props.buildingName(id)
const formatTimeValue = (value?: string | null) => props.formatTime(value)
</script>

<style scoped>
.hall-list { display: flex; flex-direction: column; gap: 12px; }
.hall-card { background: var(--bg-panel); border: 1px solid var(--border); border-radius: 12px; padding: 16px; box-shadow: var(--card-shadow); }
.hall-card-head { display: flex; justify-content: space-between; align-items: center; gap: 12px; margin-bottom: 10px; }
.hall-badge-row { display: flex; flex-wrap: wrap; gap: 8px; }
.hall-detail-grid { margin-top: 12px; }
.hall-action-bar { padding: 0; margin-top: 12px; }
.card-title { font-size: 14px; font-weight: 700; margin-bottom: 4px; }
.card-meta { font-size: 12px; color: var(--text-muted); }
.detail-grid { display: flex; flex-direction: column; gap: 0; }
.detail-row { display: grid; grid-template-columns: 100px 1fr; gap: 10px; padding: 7px 0; border-bottom: 1px solid var(--border); font-size: 13px; }
.detail-row:last-child { border-bottom: none; }
.detail-label { color: var(--text-muted); font-size: 12px; }
.detail-val.wrap { white-space: pre-wrap; }
.timeline-block { margin-top: 16px; padding-top: 16px; border-top: 1px solid var(--border); }
.section-title { font-size: 13px; font-weight: 700; margin-bottom: 10px; }
.timeline-hint { font-size: 12px; color: var(--text-muted); margin-bottom: 10px; }
.candidate-list { display: grid; gap: 12px; }
.candidate-card { border: 1px solid var(--border); border-radius: 12px; padding: 14px; background: var(--bg-card); }
.candidate-head { display: flex; justify-content: space-between; gap: 12px; align-items: flex-start; }
.candidate-name { font-size: 14px; font-weight: 700; margin-bottom: 4px; }
.candidate-meta { font-size: 12px; color: var(--text-muted); }
.candidate-note { font-size: 12px; color: var(--text-secondary); margin: 10px 0; }
.candidate-tag, .score-pill { border-radius: 999px; padding: 4px 10px; font-size: 11px; }
.candidate-tag { background: rgba(148, 163, 184, 0.12); color: var(--text-secondary); }
.score-pill { background: rgba(16, 185, 129, 0.1); color: var(--success); }
.action-bar { display: flex; gap: 8px; align-items: center; margin-top: 16px; padding-top: 14px; border-top: 1px solid var(--border); }
.action-btn { border: none; border-radius: 8px; font-size: 13px; font-weight: 600; padding: 8px 16px; cursor: pointer; }
.action-btn.primary { background: var(--accent); color: white; }
.action-btn.secondary { background: rgba(59, 130, 246, 0.12); color: var(--accent); }
.action-btn.danger { background: rgba(248, 113, 113, 0.12); color: var(--danger); }
.action-btn:disabled { opacity: 0.6; cursor: not-allowed; }
</style>
