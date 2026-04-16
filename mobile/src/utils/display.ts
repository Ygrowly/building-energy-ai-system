import { RULE_LABEL } from '../constants/status'
import { getBuildingLabel, sanitizeBuildingText } from '../constants/buildings'

const ROOT_CAUSE_LABEL_MAP: Record<string, string> = {
  A_low_efficiency: '主机效能衰退',
  B_small_deltaT: '水力失调',
  C_unexpected_on: '非预期开机',
  other_hvac: '其他空调故障',
}

const RULE_FALLBACK_LABEL_MAP: Record<string, string> = {
  supply_temp_deviation: '供水温度偏离',
  return_temp_deviation: '回水温度偏离',
  hvac_overconsumption: '空调能耗异常',
  hvac_temperature_deviation: '供水温度偏离',
  supply_water_temperature_deviation: '供水温度偏离',
  return_water_temperature_deviation: '回水温度偏离',
}

const SYSTEM_LABEL_MAP: Record<string, string> = {
  water_leak: '给排水系统',
  flag_water: '给排水系统',
  electricity_overload: '供配电系统',
  flag_electricity: '供配电系统',
  hvac_overconsumption: '空调系统',
  flag_hvac_energy: '空调系统',
  hvac_temperature_deviation: '空调系统',
  supply_water_temperature_deviation: '空调系统',
  return_water_temperature_deviation: '空调系统',
  supply_temp_deviation: '冷站系统',
  flag_supply_deviation: '冷站系统',
  return_temp_deviation: '冷站系统',
  flag_return_deviation: '冷站系统',
}

const TIMELINE_LABEL_MAP: Record<string, string> = {
  merge_evidence: '合并异常证据',
  merge_prediction_evidence: '合并预测证据',
  attach_image: '上传现场图片',
  attach_audio: '上传现场语音',
  generate: '生成维修建议',
  worker_observation: '维修人员现场记录',
  note: '记录备注',
  pending: '待处理',
  completed: '处理完成',
  auto_dispatch_hall_fallback: '自动派工转入工单大厅',
  auto_reassign_shadow_evaluated: '自动重派影子评估',
  auto_dispatch_attempt_skipped: '自动派工尝试跳过',
  auto_dispatch_rollout_skipped: '自动派工灰度跳过',
  auto_dispatch_reviewed: '自动派工复核通过',
  auto_dispatch_needs_reassign: '自动派工需改派',
  auto_reassign_rollout_skipped: '自动重派灰度跳过',
  ai_worker_pending: '维小修等待确认',
  ai_worker_success: '维小修动作已执行',
  ai_worker_failed: '维小修动作执行失败',
}

const TEXT_REPLACEMENTS: Array<[RegExp, string]> = [
  [/\[AUTO_DISPATCH_SMOKE\]\s*/gi, ''],
  [/hvac_temperature_deviation/gi, '供水温度偏离'],
  [/supply_water_temperature_deviation/gi, '供水温度偏离'],
  [/return_water_temperature_deviation/gi, '回水温度偏离'],
  [/HVAC supply water temperature abnormal; suspected air conditioning \/ hvac energy waste\.?/gi, '空调供水温度异常；疑似空调系统能耗浪费。'],
  [/HVAC return water temperature abnormal\.?/gi, '空调回水温度异常。'],
  [/Dispatch HVAC on-duty technician to inspect chilled water supply\/return temperature, air conditioning control, and abnormal energy consumption\.?/gi, '安排暖通值班技师检查冷冻水供回水温度、空调控制以及异常能耗情况。'],
  [/Dispatch HVAC on-duty technician/gi, '安排暖通值班技师'],
  [/chilled water supply\/return temperature/gi, '冷冻水供回水温度'],
  [/air conditioning control/gi, '空调控制'],
  [/abnormal energy consumption/gi, '异常能耗情况'],
  [/suspected air conditioning \/ hvac energy waste/gi, '疑似空调系统能耗浪费'],
  [/\bhvac\b/gi, '暖通空调'],
  [/\belectrical\b/gi, '电气配电'],
  [/\bplumbing\b/gi, '给排水'],
  [/\bcontrols\b/gi, '楼宇自控'],
  [/\binspection\b/gi, '现场巡检'],
  [/A_low_efficiency/g, '主机效能衰退'],
  [/B_small_deltaT/g, '水力失调'],
  [/C_unexpected_on/g, '非预期开机'],
  [/other_hvac/g, '其他空调故障'],
]

export function formatBuildingLabel(value?: string | null): string {
  return getBuildingLabel(value, '未知建筑')
}

export function formatRuleLabel(value?: string | null): string {
  if (!value) return '异常事件'
  return RULE_LABEL[value] || RULE_FALLBACK_LABEL_MAP[value] || sanitizeDisplayText(value)
}

export function formatRootCauseLabel(value?: string | null): string {
  if (!value) return ''
  return ROOT_CAUSE_LABEL_MAP[value] || sanitizeDisplayText(value)
}

export function formatSystemLabel(rule?: string | null): string {
  if (!rule) return '能源系统'
  return SYSTEM_LABEL_MAP[rule] || '能源系统'
}

export function formatDeviceLabel(value?: string | null, buildingId?: string | null): string {
  if (!value) return ''

  const device = value.trim()
  const buildingLabel = formatBuildingLabel(buildingId)
  const deviceAsBuilding = formatBuildingLabel(device)
  if (deviceAsBuilding === buildingLabel) return ''

  if (device.startsWith('EM_AC_')) return `${buildingLabel}空调表`
  if (device.startsWith('EM_ELE_')) return `${buildingLabel}电表`
  if (device.startsWith('EM_WAT_')) return `${buildingLabel}水表`
  if (/_hvac$/i.test(device) || /hvac/i.test(device)) return `${buildingLabel}空调系统`

  return sanitizeDisplayText(device)
}

export function sanitizeDisplayText(value?: string | null): string {
  if (!value) return ''

  let text = sanitizeBuildingText(value)
  TEXT_REPLACEMENTS.forEach(([pattern, replacement]) => {
    text = text.replace(pattern, replacement)
  })

  return text
}

export function formatTimelineLabel(value?: string | null): string {
  if (!value) return ''
  const normalized = value.trim()
  return TIMELINE_LABEL_MAP[normalized] || sanitizeDisplayText(normalized)
}

export function formatWorkOrderTitle(options?: {
  ruleTriggered?: string | null
  summaryText?: string | null
  issueDescription?: string | null
  buildingId?: string | null
}): string {
  const ruleLabel = formatRuleLabel(options?.ruleTriggered)
  if (options?.ruleTriggered && ruleLabel && ruleLabel !== sanitizeDisplayText(options.ruleTriggered)) {
    return ruleLabel
  }

  const buildingLabel = options?.buildingId ? formatBuildingLabel(options.buildingId) : ''
  let text = sanitizeDisplayText(options?.summaryText || options?.issueDescription)
  if (!text) return ruleLabel || '工单待处理'

  text = text
    .replace(/^\[预警\]\s*/g, '')
    .replace(/^\[[^\]]+\]\s*/g, '')
    .replace(/^\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}\s*/g, '')
    .replace(/^预测\s+\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}\s*/g, '')
    .replace(/^(检测到|发现|出现)/, '')
    .trim()

  if (buildingLabel && text.startsWith(`${buildingLabel} `)) {
    text = text.slice(buildingLabel.length).trim()
  }

  const firstClause = text.split(/[，。,；;]/)[0]?.trim() || ''
  return firstClause || ruleLabel || '工单待处理'
}
