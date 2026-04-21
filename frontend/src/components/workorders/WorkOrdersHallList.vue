<template>
  <div class="hall-list">
    <div class="hall-card" v-for="entry in hallEntries" :key="entry.id">
      <div class="hall-card-head">
        <div class="hall-badge-row">
          <span class="candidate-tag">{{ entry.entry_type === 'support_request' ? '工单大厅协同' : '超时待接管' }}</span>
          <span class="candidate-tag">{{ priorityLabels[entry.work_order?.priority] ?? entry.work_order?.priority ?? '普通工单' }}</span>
          <span v-if="entry.application_stats" class="candidate-tag urgent">
            申请 {{ entry.application_stats.total || 0 }} · 待处理 {{ entry.application_stats.pending || 0 }}
          </span>
          <span v-if="entry.risk_score" class="candidate-tag risk">风险 {{ entry.risk_score }}</span>
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
          <span class="detail-label">异常情况</span>
          <span class="detail-val wrap">{{ hallEntryIssueValue(entry) }}</span>
        </div>
        <div class="detail-row">
          <span class="detail-label">可见范围</span>
          <span class="detail-val wrap">{{ visibilityText(entry) }}</span>
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
        <div v-else>
          <p class="timeline-hint">{{ hallEmptyHintValue(entry) }}</p>
          <div v-if="latestApplication(entry)" class="latest-application">
            <span>{{ applicationStatusLabel(latestApplication(entry)?.status) }}</span>
            <strong>{{ latestApplication(entry)?.applicant_username || '维修人员' }}</strong>
            <p>{{ latestApplication(entry)?.handle_note || latestApplication(entry)?.note || '暂无处理说明' }}</p>
          </div>
        </div>
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
  hallEntryIssue: {
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
const hallEntryIssueValue = (entry: any) => props.hallEntryIssue(entry)
const hallEmptyHintValue = (entry: any) => props.hallEmptyHint(entry)
const canSuggestHallTakeoverValue = (entry: any) => props.canSuggestHallTakeover(entry)
const canNudgeHallOwnerValue = (entry: any) => props.canNudgeHallOwner(entry)
const hallActionKeyValue = (entryId: string, applicationId: string, action: 'approve' | 'reject' | 'close' | 'suggest' | 'nudge') =>
  props.hallActionKey(entryId, applicationId, action)
const buildingNameValue = (id: string) => props.buildingName(id)
const formatTimeValue = (value?: string | null) => props.formatTime(value)

function latestApplication(entry: any) {
  return entry.latest_application || [...(entry.applications || [])].sort((a: any, b: any) => {
    const aTime = a.updated_at || a.created_at || ''
    const bTime = b.updated_at || b.created_at || ''
    return bTime.localeCompare(aTime)
  })[0] || null
}

function applicationStatusLabel(status?: string) {
  const map: Record<string, string> = {
    approved: '已同意',
    rejected: '已驳回',
    withdrawn: '已撤回',
    pending: '待处理',
  }
  return map[status || ''] || '申请动态'
}

function visibilityText(entry: any) {
  const parts: string[] = []
  if (entry.target_team_ids?.length) parts.push(`目标班组 ${entry.target_team_ids.length} 个`)
  if (entry.target_skill_tags?.length) parts.push(`技能 ${entry.target_skill_tags.join(' / ')}`)
  if (entry.target_user_ids?.length) parts.push(`推荐人员 ${entry.target_user_ids.length} 人`)
  return parts.length ? parts.join(' · ') : '所有可见维修人员'
}
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
.candidate-tag.urgent { color: #b45309; background: rgba(245, 158, 11, 0.12); }
.candidate-tag.risk { color: #b91c1c; background: rgba(248, 113, 113, 0.12); }
.score-pill { background: rgba(16, 185, 129, 0.1); color: var(--success); }
.latest-application { border: 1px dashed var(--border); border-radius: 10px; padding: 10px 12px; background: rgba(148, 163, 184, 0.08); font-size: 12px; color: var(--text-secondary); }
.latest-application span { display: inline-block; margin-right: 8px; color: var(--accent); font-weight: 700; }
.latest-application strong { color: var(--text-primary); }
.latest-application p { margin-top: 6px; }
.action-bar { display: flex; gap: 8px; align-items: center; margin-top: 16px; padding-top: 14px; border-top: 1px solid var(--border); }
.action-btn { border: none; border-radius: 8px; font-size: 13px; font-weight: 600; padding: 8px 16px; cursor: pointer; }
.action-btn.primary { background: var(--accent); color: white; }
.action-btn.secondary { background: rgba(59, 130, 246, 0.12); color: var(--accent); }
.action-btn.danger { background: rgba(248, 113, 113, 0.12); color: var(--danger); }
.action-btn:disabled { opacity: 0.6; cursor: not-allowed; }
</style>
