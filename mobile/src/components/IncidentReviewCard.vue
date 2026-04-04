<template>
  <view
    v-if="isStatusDrivenCard"
    class="dispatch-card"
    :class="[`priority-${incident.priority || 'medium'}`, `sla-${slaMeta.tone}`]"
    @click="$emit('click', incident)"
  >
    <view class="dispatch-glow" />

    <view class="dispatch-header">
      <view class="header-left">
        <view class="badge" :class="incident.priority">
          {{ PRIORITY_LABEL[incident.priority] || incident.priority }}
        </view>
        <view class="rule-chip">
          {{ ruleLabel }}
        </view>
      </view>
      <view class="header-right">
        <view class="exec-tag" :class="executionStatus" :style="execTagStyle">
          {{ executionLabel }}
        </view>
        <text v-if="headerSlaText" class="sla-text" :class="slaMeta.tone">{{ headerSlaText }}</text>
      </view>
    </view>

    <view class="identity-row">
      <view class="identity-main">
        <text class="location-title">{{ locationPath }}</text>
        <text class="identity-sub">
          事件 {{ incident.incident_id || '--' }}
          <text v-if="incident.current_work_order?.ticket_id">  ·  工单 {{ incident.current_work_order?.ticket_id }}</text>
        </text>
      </view>
    </view>

    <view class="summary-box">
      <text class="summary-line">{{ anomalySummary }}</text>
      <view class="summary-foot">
        <text class="state-dot" :class="{ active: incident.is_active, recovered: !incident.is_active }" />
        <text class="state-text">{{ stateText }}</text>
      </view>
    </view>

    <view class="progress-brief">
      <view class="progress-head">
        <view class="progress-owner">
          <text class="owner-name">{{ assigneeText }}</text>
          <text v-if="teamText" class="owner-team">{{ teamText }}</text>
        </view>
        <text class="progress-meta">{{ progressMetaText }}</text>
      </view>
      <text class="progress-note">{{ progressText }}</text>
    </view>

    <view v-if="showQuickActions" class="action-strip" @click.stop>
      <view class="quick-btn accent" @click="emitAction(primaryActionType)">{{ primaryActionLabel }}</view>
      <view class="quick-btn" @click="emitAction('detail')">详情</view>
    </view>

    <view class="fold-trigger" @click.stop="toggleDetails">
      <text class="fold-label">{{ detailsExpanded ? '收起补充信息' : '展开补充信息' }}</text>
      <text class="fold-arrow">{{ detailsExpanded ? '收起' : '更多' }}</text>
    </view>

    <view v-if="detailsExpanded" class="detail-panel" @click.stop>
      <view class="detail-block">
        <text class="detail-title">时间线</text>
        <text class="detail-line">{{ timeRow || '暂无时间线信息' }}</text>
      </view>
      <view class="detail-block">
        <text class="detail-title">影响</text>
        <text class="detail-line">{{ impactText }}</text>
      </view>
      <view class="detail-block">
        <text class="detail-title">建议</text>
        <text class="detail-line">{{ suggestedActionText }}</text>
      </view>
      <view v-if="aiReasonText" class="detail-block">
        <text class="detail-title">AI 判断</text>
        <text class="detail-line">{{ aiReasonText }}</text>
      </view>
      <view v-if="showQuickActions" class="secondary-actions">
        <view class="quick-btn" @click="emitAction('trend')">趋势</view>
        <view class="quick-btn" @click="emitAction('contact')">联系</view>
      </view>
    </view>
  </view>

  <view
    v-else
    class="incident-card"
    :class="priorityClass"
    @click="$emit('click', incident)"
  >
    <view class="incident-glow" />

    <view class="incident-header">
      <view class="header-left">
        <view class="badge" :class="incident.priority">
          {{ PRIORITY_LABEL[incident.priority] || incident.priority }}
        </view>
        <view class="rule-chip">
          {{ classicRuleLabel }}
        </view>
      </view>
      <view class="status-tag" :class="incident.workflow_status || ''">
        {{ STATUS_LABEL[incident.workflow_status || ''] || incident.workflow_status || '处理中' }}
      </view>
    </view>

    <view class="identity-row">
      <view class="identity-main">
        <text class="building-name">{{ buildingLabel }}</text>
        <text v-if="deviceLabel" class="device-name">{{ deviceLabel }}</text>
      </view>
      <text class="incident-no">事件编号 {{ displayIncidentNo }}</text>
    </view>

    <text v-if="causeLabel" class="cause-text">根因：{{ causeLabel }}</text>
    <text class="summary">{{ summaryText }}</text>

    <view class="metric-grid">
      <view class="metric-card">
        <text class="metric-label">连续次数</text>
        <text class="metric-value">{{ incident.anomaly_count }} 次</text>
      </view>
      <view class="metric-card danger" v-if="incident.peak_deviation_pct !== null">
        <text class="metric-label">峰值偏差</text>
        <text class="metric-value">{{ signedPeak }}</text>
      </view>
      <view class="metric-card" v-if="timeSpan">
        <text class="metric-label">异常时段</text>
        <text class="metric-value">{{ timeSpan }}</text>
      </view>
    </view>

    <view class="time-row-classic">
      <view class="time-block">
        <text class="time-caption">首次发现</text>
        <text class="time-label">{{ formatTime(incident.first_seen_at) }}</text>
      </view>
      <view class="time-block align-right">
        <text class="time-caption">最近异常</text>
        <text class="time-label">{{ formatTime(incident.last_seen_at) }}</text>
      </view>
    </view>

    <view v-if="incident.current_work_order?.ai_reason" class="ai-reason">
      <view class="ai-head">
        <text class="ai-label">AI 分析</text>
        <text class="ai-arrow">查看详情</text>
      </view>
      <text class="ai-text">{{ aiReasonText }}</text>
    </view>
  </view>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import type { Incident } from '../api/incident'
import {
  DISPATCH_EXECUTION_STATUS_COLOR,
  PRIORITY_LABEL,
  STATUS_LABEL,
} from '../constants/status'
import { formatServerDateTime } from '../utils/format'
import {
  buildAnomalySummary,
  buildCardTimeRow,
  buildImpactText,
  buildLocationPath,
  buildProgressText,
  buildRuleLabel,
  buildStateText,
  buildSuggestedActionText,
  resolveExecutionLabel,
  resolveExecutionStatus,
  resolveSlaMeta,
} from '../utils/incident-card'
import {
  formatBuildingLabel,
  formatDeviceLabel,
  formatRootCauseLabel,
  formatRuleLabel,
  sanitizeDisplayText,
} from '../utils/display'

const props = withDefaults(defineProps<{
  incident: Incident
  mode?: 'default' | 'operator-review'
  showQuickActions?: boolean
}>(), {
  mode: 'default',
  showQuickActions: false,
})

const emit = defineEmits<{
  (e: 'click', incident: Incident): void
  (e: 'action', payload: { type: 'trend' | 'contact' | 'nudge' | 'detail'; incident: Incident }): void
}>()

const isStatusDrivenCard = computed(() => props.mode === 'operator-review' && props.incident.workflow_status === 'dispatched')
const priorityClass = computed(() => `priority-${props.incident.priority || 'medium'}`)
const buildingLabel = computed(() => formatBuildingLabel(props.incident.building_id))
const deviceLabel = computed(() => formatDeviceLabel(props.incident.device_id, props.incident.building_id))
const displayIncidentNo = computed(() => props.incident.incident_id || '--')
const classicRuleLabel = computed(() => formatRuleLabel(props.incident.rule_triggered))
const causeLabel = computed(() => formatRootCauseLabel(props.incident.hvac_root_cause))
const summaryText = computed(() => sanitizeDisplayText(props.incident.summary_text))
const aiReasonText = computed(() => sanitizeDisplayText(props.incident.current_work_order?.ai_reason))
const signedPeak = computed(() => {
  const value = props.incident.peak_deviation_pct
  if (value === null || value === undefined) return ''
  return `${value >= 0 ? '+' : ''}${value.toFixed(1)}%`
})
const timeSpan = computed(() => {
  const first = formatTime(props.incident.first_seen_at)
  const last = formatTime(props.incident.last_seen_at)
  if (first === '--' || last === '--') return ''
  return first === last ? first : `${first} - ${last.slice(6)}`
})

const executionStatus = computed(() => resolveExecutionStatus(props.incident))
const executionLabel = computed(() => resolveExecutionLabel(props.incident))
const execTagStyle = computed(() => {
  const color = DISPATCH_EXECUTION_STATUS_COLOR[executionStatus.value] || DISPATCH_EXECUTION_STATUS_COLOR.pending_accept
  return {
    background: color.bg,
    color: color.text,
    borderColor: color.border,
  }
})
const slaMeta = computed(() => resolveSlaMeta(props.incident))
const locationPath = computed(() => buildLocationPath(props.incident))
const anomalySummary = computed(() => buildAnomalySummary(props.incident))
const stateText = computed(() => buildStateText(props.incident))
const timeRow = computed(() => buildCardTimeRow(props.incident))
const progressText = computed(() => buildProgressText(props.incident))
const impactText = computed(() => buildImpactText(props.incident))
const suggestedActionText = computed(() => buildSuggestedActionText(props.incident))
const ruleLabel = computed(() => buildRuleLabel(props.incident))
const assigneeText = computed(() => props.incident.current_work_order?.assigned_to_name || '待分配责任人')
const teamText = computed(() => props.incident.current_work_order?.assigned_team_name || '')
const detailsExpanded = ref(false)
const primaryActionType = computed<'trend' | 'nudge'>(() => {
  return executionStatus.value === 'overdue' || executionStatus.value === 'pending_accept' ? 'nudge' : 'trend'
})
const primaryActionLabel = computed(() => primaryActionType.value === 'nudge' ? '催办' : '趋势')
const headerSlaText = computed(() => {
  if (slaMeta.value.tone === 'overdue') {
    return `${Math.abs(slaMeta.value.minutesLeft || 0)} 分钟`
  }
  if (slaMeta.value.tone === 'warning' && slaMeta.value.minutesLeft !== null) {
    return `${slaMeta.value.minutesLeft} 分钟后超时`
  }
  return ''
})
const progressMetaText = computed(() => {
  if (executionStatus.value === 'overdue') return '优先跟进'
  if (executionStatus.value === 'pending_accept') return '等待接单'
  if (executionStatus.value === 'waiting_support') return '等待协同'
  return '处理中'
})

function emitAction(type: 'trend' | 'contact' | 'nudge' | 'detail') {
  emit('action', { type, incident: props.incident })
}

function toggleDetails() {
  detailsExpanded.value = !detailsExpanded.value
}

function formatTime(value: string | null): string {
  if (!value) return '--'
  const normalized = formatServerDateTime(value)
  return normalized.slice(5, 16)
}

</script>

<style lang="scss" scoped>
.dispatch-card,
.incident-card {
  position: relative;
  overflow: hidden;
  border-radius: 28rpx;
  border: 1rpx solid rgba(218, 225, 238, 0.9);
  box-shadow: 0 14rpx 36rpx rgba(12, 24, 42, 0.08);
}

.dispatch-card {
  background:
    linear-gradient(180deg, rgba(255,255,255,0.99), rgba(246,249,255,0.98)),
    #fff;
  padding: 28rpx;
  margin-bottom: 22rpx;

  &.sla-warning {
    border-color: #ffd8a8;
    box-shadow: 0 16rpx 34rpx rgba(245, 158, 11, 0.12);
  }

  &.sla-overdue {
    border-color: #ffd4cf;
    box-shadow: 0 16rpx 38rpx rgba(229, 72, 77, 0.14);
  }

  &.priority-high .dispatch-glow {
    background: radial-gradient(circle, rgba(255, 107, 107, 0.16) 0%, rgba(255,255,255,0) 68%);
  }

  &.priority-medium .dispatch-glow {
    background: radial-gradient(circle, rgba(245, 158, 11, 0.16) 0%, rgba(255,255,255,0) 68%);
  }

  &.priority-low .dispatch-glow {
    background: radial-gradient(circle, rgba(34, 197, 94, 0.16) 0%, rgba(255,255,255,0) 68%);
  }
}

.incident-card {
  background:
    linear-gradient(180deg, rgba(255,255,255,0.98), rgba(249,250,255,0.98)),
    #fff;
  padding: 28rpx;
  margin-bottom: 22rpx;

  &.priority-high .incident-glow {
    background: radial-gradient(circle, rgba(255, 107, 107, 0.18) 0%, rgba(255,255,255,0) 68%);
  }

  &.priority-medium .incident-glow {
    background: radial-gradient(circle, rgba(245, 158, 11, 0.18) 0%, rgba(255,255,255,0) 68%);
  }

  &.priority-low .incident-glow {
    background: radial-gradient(circle, rgba(34, 197, 94, 0.18) 0%, rgba(255,255,255,0) 68%);
  }
}

.dispatch-glow,
.incident-glow {
  position: absolute;
  top: -26rpx;
  right: -38rpx;
  width: 180rpx;
  height: 180rpx;
  border-radius: 50%;
  pointer-events: none;
}

.dispatch-header,
.incident-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 14rpx;
  margin-bottom: 18rpx;
}

.header-left {
  display: flex;
  align-items: center;
  gap: 10rpx;
  flex-wrap: wrap;
}

.header-right {
  display: flex;
  flex-direction: row;
  align-items: center;
  gap: 8rpx;
  flex-shrink: 0;
}

.badge {
  padding: 8rpx 18rpx;
  border-radius: 999rpx;
  font-size: 22rpx;
  font-weight: 700;

  &.high { background: #fff2f0; color: #ff4d4f; }
  &.medium { background: #fff7e6; color: #fa8c16; }
  &.low { background: #f6ffed; color: #52c41a; }
}

.rule-chip {
  padding: 8rpx 16rpx;
  border-radius: 999rpx;
  font-size: 21rpx;
  color: #5f6b7a;
  background: #f4f7fb;
  border: 1rpx solid #e4eaf3;
}

.exec-tag {
  padding: 8rpx 16rpx;
  border-radius: 999rpx;
  font-size: 22rpx;
  font-weight: 700;
  border: 1rpx solid transparent;
}

.sla-text {
  font-size: 21rpx;
  font-weight: 600;
  color: #7d8797;
  white-space: nowrap;

  &.warning {
    color: #d97706;
  }

  &.overdue {
    color: #e5484d;
  }
}

.identity-row {
  display: flex;
  justify-content: space-between;
  gap: 18rpx;
  margin-bottom: 16rpx;
}

.identity-main {
  flex: 1;
  min-width: 0;
}

.location-title,
.building-name {
  display: block;
  font-size: 33rpx;
  font-weight: 800;
  color: #122033;
  line-height: 1.28;
}

.identity-sub,
.device-name,
.incident-no {
  display: block;
  margin-top: 8rpx;
  font-size: 22rpx;
  color: #7b8698;
  line-height: 1.5;
}

.device-name {
  color: #22a06b;
}

.summary-box,
.ai-reason,
.progress-brief,
.detail-panel {
  background: #f8faff;
  border: 1rpx solid #e7edf7;
  border-radius: 22rpx;
  padding: 18rpx 20rpx;
}

.summary-box {
  margin-bottom: 16rpx;
}

.summary-line,
.progress-note,
.insight-line,
.summary {
  display: block;
  font-size: 24rpx;
  color: #415164;
  line-height: 1.7;
}

.summary-foot {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 10rpx;
  margin-top: 12rpx;
}

.state-text,
.time-caption,
.metric-label,
.ai-arrow,
.time-label,
.time-value,
.owner-team {
  font-size: 20rpx;
  color: #7d8797;
}

.progress-brief,
.detail-panel,
.ai-reason {
  margin-bottom: 16rpx;
}

.progress-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12rpx;
  margin-bottom: 10rpx;
}

.progress-owner {
  display: flex;
  align-items: center;
  gap: 10rpx;
  flex-wrap: wrap;
}

.owner-name {
  font-size: 26rpx;
  font-weight: 700;
  color: #1b2a41;
}

.progress-meta {
  font-size: 20rpx;
  color: #7d8797;
  flex-shrink: 0;
}

.state-dot {
  width: 12rpx;
  height: 12rpx;
  border-radius: 50%;
  background: #9aa5b5;

  &.active {
    background: #e5484d;
  }

  &.recovered {
    background: #12b76a;
  }
}

.time-row-classic {
  display: flex;
  gap: 14rpx;
  margin-top: 14rpx;
}

.time-item,
.time-block {
  flex: 1;
  min-width: 0;
}

.time-value {
  display: block;
  margin-top: 6rpx;
  font-size: 22rpx;
  color: #314256;
  font-weight: 600;
}

.action-strip {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12rpx;
  margin-top: 6rpx;
}

.fold-trigger {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 10rpx 6rpx 2rpx;
  color: #6b7b91;
  font-size: 22rpx;
}

.fold-label {
  font-size: 22rpx;
  color: #53657d;
}

.fold-arrow {
  font-size: 20rpx;
  color: #8ea0b8;
}

.detail-block + .detail-block {
  margin-top: 14rpx;
}

.detail-title {
  display: block;
  font-size: 20rpx;
  color: #8a97aa;
  margin-bottom: 6rpx;
}

.detail-line {
  display: block;
  font-size: 22rpx;
  color: #46576d;
  line-height: 1.6;
}

.secondary-actions {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12rpx;
  margin-top: 16rpx;
}

.quick-btn {
  height: 72rpx;
  border-radius: 18rpx;
  background: #f4f7fb;
  border: 1rpx solid #e4eaf3;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 23rpx;
  font-weight: 700;
  color: #506074;

  &.accent {
    background: #eef4ff;
    color: #2f6df6;
    border-color: #d7e5ff;
  }
}

.status-tag {
  padding: 8rpx 16rpx;
  border-radius: 999rpx;
  font-size: 22rpx;
  font-weight: 600;
  flex-shrink: 0;

  &.pending_review { background: #fffbe6; color: #d48806; }
  &.auto_approved { background: #e6f7ff; color: #096dd9; }
  &.auto_rejected { background: #fff2f0; color: #ff4d4f; }
  &.dispatched { background: #e6f7ff; color: #096dd9; }
  &.completed { background: #f6ffed; color: #389e0d; }
  &.closed { background: #f5f5f5; color: #8c8c8c; }
  &.false_alarm { background: #f0f0f0; color: #595959; }
  &.escalated { background: #f0f0ff; color: #722ed1; }
  &.admin_override_approved { background: #e6f7ff; color: #096dd9; }
  &.admin_override_rejected { background: #fff2f0; color: #ff4d4f; }
}

.cause-text {
  display: block;
  font-size: 22rpx;
  color: #65758b;
  margin-bottom: 12rpx;
}

.metric-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 12rpx;
  margin-bottom: 18rpx;
}

.metric-card {
  background: #f7f9fc;
  border-radius: 20rpx;
  padding: 16rpx 18rpx;
  border: 1rpx solid #edf1f7;
  min-height: 90rpx;

  &.danger {
    background: #fff4f3;
    border-color: #ffd8d3;
  }
}

.metric-value {
  display: block;
  margin-top: 6rpx;
  font-size: 25rpx;
  font-weight: 700;
  color: #1b2a41;
}

.align-right {
  text-align: right;
}

.ai-reason {
  background: linear-gradient(135deg, #f7f9ff, #eef4ff);
  border-color: #dce8ff;
}

.ai-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 8rpx;
}

.ai-text {
  font-size: 22rpx;
  color: #5f6b7a;
  line-height: 1.6;
}

@media (max-width: 430px) {
  .dispatch-header,
  .incident-header,
  .summary-foot,
  .time-row-classic {
    align-items: flex-start;
  }

  .align-right {
    align-items: flex-start;
    text-align: left;
  }

  .metric-grid {
    grid-template-columns: 1fr;
  }

  .action-strip {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}
</style>
