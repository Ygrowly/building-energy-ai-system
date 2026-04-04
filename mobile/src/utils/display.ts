import { RULE_LABEL } from '../constants/status'

const BUILDING_LABEL_MAP: Record<string, string> = {
  fox_office_alice: '办公楼',
  fox_education_louie: '教学楼',
  fox_public_henry: '公共服务楼',
  office: '办公楼',
  education: '教学楼',
  public: '公共服务楼',
  'public services': '公共服务楼',
}

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
}

const SYSTEM_LABEL_MAP: Record<string, string> = {
  water_leak: '给排水系统',
  flag_water: '给排水系统',
  electricity_overload: '供配电系统',
  flag_electricity: '供配电系统',
  hvac_overconsumption: '空调系统',
  flag_hvac_energy: '空调系统',
  supply_temp_deviation: '冷站系统',
  flag_supply_deviation: '冷站系统',
  return_temp_deviation: '冷站系统',
  flag_return_deviation: '冷站系统',
}

const TEXT_REPLACEMENTS: Array<[RegExp, string]> = [
  [/Fox_office_Alice/gi, '办公楼'],
  [/Fox_education_Louie/gi, '教学楼'],
  [/Fox_public_Henry/gi, '公共服务楼'],
  [/Alice\s*办公楼/gi, '办公楼'],
  [/Louie\s*教学楼/gi, '教学楼'],
  [/Henry\s*公共服务楼/gi, '公共服务楼'],
  [/A_low_efficiency/g, '主机效能衰退'],
  [/B_small_deltaT/g, '水力失调'],
  [/C_unexpected_on/g, '非预期开机'],
  [/other_hvac/g, '其他空调故障'],
]

function normalizeValue(value: string) {
  return value.trim().replace(/\s+/g, ' ').toLowerCase()
}

export function formatBuildingLabel(value?: string | null): string {
  if (!value) return '未知建筑'
  const normalized = normalizeValue(value)
  return BUILDING_LABEL_MAP[normalized] || sanitizeDisplayText(value)
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

  let text = value
  TEXT_REPLACEMENTS.forEach(([pattern, replacement]) => {
    text = text.replace(pattern, replacement)
  })

  return text
}
