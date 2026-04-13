export type WorkOrderTabKey =
  | 'all'
  | 'pending_review'
  | 'auto_dispatch_review'
  | 'pending_dispatch'
  | 'auto_dispatch_insights'
  | 'auto_rejected'
  | 'dispatched'
  | 'pending_close'
  | 'closed'
  | 'shared_hall'

export type WorkOrderWorkspaceMode = 'all' | 'review' | 'dispatch' | 'tracking'

export interface WorkOrderTab {
  label: string
  value: WorkOrderTabKey
}

export interface WorkOrderWorkspaceConfig {
  title: string
  subtitle: string
  defaultTab: WorkOrderTabKey
  tabs: WorkOrderTab[]
}

const TAB_MAP: Record<WorkOrderTabKey, WorkOrderTab> = {
  all: { label: '全部', value: 'all' },
  pending_review: { label: '待AI审阅', value: 'pending_review' },
  auto_dispatch_review: { label: '自动派工复核', value: 'auto_dispatch_review' },
  pending_dispatch: { label: '待派工', value: 'pending_dispatch' },
  auto_dispatch_insights: { label: '派工洞察', value: 'auto_dispatch_insights' },
  auto_rejected: { label: 'AI已驳回', value: 'auto_rejected' },
  dispatched: { label: '执行中', value: 'dispatched' },
  pending_close: { label: '待关闭', value: 'pending_close' },
  closed: { label: '已关闭', value: 'closed' },
  shared_hall: { label: '工单大厅', value: 'shared_hall' },
}

export const WORK_ORDER_TABS: WorkOrderTab[] = [
  TAB_MAP.all,
  TAB_MAP.pending_review,
  TAB_MAP.pending_dispatch,
  TAB_MAP.auto_rejected,
  TAB_MAP.dispatched,
  TAB_MAP.pending_close,
  TAB_MAP.closed,
  TAB_MAP.shared_hall,
]

export const WORK_ORDER_WORKSPACE_CONFIG: Record<WorkOrderWorkspaceMode, WorkOrderWorkspaceConfig> = {
  all: {
    title: '工单管理',
    subtitle: 'AI 审阅 · 派工中心 · 执行跟踪',
    defaultTab: 'pending_dispatch',
    tabs: WORK_ORDER_TABS,
  },
  review: {
    title: '工单审阅',
    subtitle: 'AI 审阅与自动派工结果复核',
    defaultTab: 'pending_review',
    tabs: [TAB_MAP.pending_review, TAB_MAP.auto_dispatch_review, TAB_MAP.auto_rejected],
  },
  dispatch: {
    title: '派工中心',
    subtitle: '待派工、批量派工与工单大厅申请处理',
    defaultTab: 'pending_dispatch',
    tabs: [TAB_MAP.pending_dispatch, TAB_MAP.shared_hall, TAB_MAP.auto_dispatch_insights],
  },
  tracking: {
    title: '执行跟踪',
    subtitle: '已派单、待关闭与已关闭工单的执行闭环',
    defaultTab: 'dispatched',
    tabs: [TAB_MAP.dispatched, TAB_MAP.pending_close, TAB_MAP.closed],
  },
}

export const STATUS_LABELS: Record<string, string> = {
  pending_review: '待AI审阅',
  pending_dispatch: '待派工',
  auto_rejected: 'AI已驳回',
  dispatched: '已派单',
  completed: '已修复',
  false_alarm: '误报',
  escalated: '已升级',
  auto_approved: 'AI已批准',
  admin_override_approved: '管理员批准',
  admin_override_rejected: '管理员驳回',
  closed: '已关闭',
}

export const EXECUTION_LABELS: Record<string, string> = {
  pending_dispatch: '待派工',
  pending_accept: '待接单',
  accepted: '已接单',
  arrived: '已到场',
  processing: '处理中',
  waiting_support: '待协同',
  overdue: '已超时',
}

export const PRIORITY_LABELS: Record<string, string> = {
  high: '高优先',
  medium: '中优先',
  low: '低优先',
}

export const WORK_ORDER_EMPTY_MESSAGES: Record<WorkOrderTabKey, string> = {
  all: '暂无工单记录',
  pending_review: '暂无待AI审阅工单',
  auto_dispatch_review: '暂无待复核的自动派工单',
  pending_dispatch: '暂无待派工工单',
  auto_dispatch_insights: '暂无自动派工洞察数据',
  auto_rejected: '暂无 AI 驳回工单',
  dispatched: '暂无执行中的工单',
  pending_close: '暂无待关闭工单',
  closed: '暂无已关闭工单',
  shared_hall: '暂无待处理的工单大厅事项',
}
