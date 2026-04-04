/** 工单状态（严格对齐后端 VALID_TRANSITIONS） */
export type WorkOrderStatus =
  | 'pending_review'
  | 'auto_approved'
  | 'auto_rejected'
  | 'dispatched'
  | 'completed'
  | 'false_alarm'
  | 'escalated'
  | 'admin_override_approved'
  | 'admin_override_rejected'
  | 'closed'

export const STATUS_LABEL: Record<string, string> = {
  pending_review:          '待AI审批',
  auto_approved:           'AI已批准',
  auto_rejected:           'AI已驳回',
  dispatched:              '已派单',
  completed:               '已修复',
  false_alarm:             '误报',
  escalated:               '已升级',
  admin_override_approved: '管理员批准',
  admin_override_rejected: '管理员驳回',
  closed:                  '已关闭',
}

export const STATUS_COLOR: Record<string, string> = {
  pending_review:          '#d48806',
  auto_approved:           '#096dd9',
  auto_rejected:           '#ff4d4f',
  dispatched:              '#1890ff',
  completed:               '#389e0d',
  false_alarm:             '#595959',
  escalated:               '#722ed1',
  admin_override_approved: '#096dd9',
  admin_override_rejected: '#ff4d4f',
  closed:                  '#8c8c8c',
}

export type DispatchExecutionStatus =
  | 'pending_accept'
  | 'accepted'
  | 'arrived'
  | 'processing'
  | 'waiting_support'
  | 'overdue'

export const DISPATCH_EXECUTION_STATUS_LABEL: Record<string, string> = {
  pending_accept: '待接单',
  accepted: '已接单',
  arrived: '已到场',
  processing: '处理中',
  waiting_support: '待协同',
  overdue: '已超时',
}

export const DISPATCH_EXECUTION_STATUS_COLOR: Record<string, { bg: string; text: string; border: string }> = {
  pending_accept: { bg: '#eef4ff', text: '#2f6df6', border: '#dbe7ff' },
  accepted: { bg: '#ebf8ff', text: '#0c7abf', border: '#cfeeff' },
  arrived: { bg: '#ecfbf3', text: '#0f9f6e', border: '#cdeedd' },
  processing: { bg: '#eefcf7', text: '#0f9f6e', border: '#d6f2e6' },
  waiting_support: { bg: '#f3f0ff', text: '#6f42d8', border: '#e4ddff' },
  overdue: { bg: '#fff1f0', text: '#e5484d', border: '#ffd8d3' },
}

export const SLA_STATUS_LABEL: Record<string, string> = {
  normal: '正常',
  warning: '临期',
  overdue: '超时',
}

export type Priority = 'high' | 'medium' | 'low'

export const PRIORITY_LABEL: Record<string, string> = {
  high: '高优先',
  medium: '中优先',
  low: '低优先',
}

export const PRIORITY_COLOR: Record<string, { bg: string; text: string }> = {
  high:   { bg: '#fff2f0', text: '#ff4d4f' },
  medium: { bg: '#fff7e6', text: '#fa8c16' },
  low:    { bg: '#f6ffed', text: '#52c41a' },
}

/** 维修反馈枚举（对齐后端 worker-feedback body.result） */
export type WorkerResult = 'fixed' | 'false_alarm' | 'escalated' | 'needs_parts'

export const WORKER_RESULT_LABEL: Record<string, string> = {
  fixed:       '已修复',
  false_alarm: '误报',
  escalated:   '升级处理',
  needs_parts: '需要配件',
}

/** 管理员审阅 action 枚举（对齐后端 admin-review body.action） */
export type AdminAction = 'confirm' | 'override_approve' | 'override_reject' | 'close_escalated'

export const ADMIN_ACTION_LABEL: Record<string, string> = {
  confirm:          '确认关闭',
  override_approve: '覆盖批准',
  override_reject:  '覆盖驳回',
  close_escalated:  '关闭升级',
}

/** 异常规则中文映射 */
export const RULE_LABEL: Record<string, string> = {
  water_leak:            '水耗异常',
  electricity_overload:  '电耗超标',
  hvac_overconsumption:  '空调过耗',
  db_flagged:            '标注异常',
  night_high_power:      '夜间高耗',
  flag_water:            '水耗偏高',
  flag_electricity:      '总电耗偏高',
  flag_hvac_energy:      '空调能耗偏高',
  flag_supply_deviation: '供水温度偏离',
  flag_return_deviation: '回水温度偏离',
}
