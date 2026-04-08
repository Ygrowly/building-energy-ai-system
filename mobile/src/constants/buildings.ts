export const BUILDING_TYPE_ORDER = ['Education', 'Office', 'Public services'] as const
export type BuildingType = typeof BUILDING_TYPE_ORDER[number]
export type BuildingFilterValue = BuildingType | 'all'

export const BUILDING_TYPE_LABELS: Record<BuildingType, string> = {
  Education: '教学楼',
  Office: '办公楼',
  'Public services': '公共楼',
}

export const ALL_BUILDING_FILTER_OPTIONS: Array<{ value: BuildingFilterValue; label: string }> = [
  { value: 'all', label: '全部建筑' },
  ...BUILDING_TYPE_ORDER.map((value) => ({
    value,
    label: BUILDING_TYPE_LABELS[value],
  })),
]

const BUILDING_ALIASES: Record<string, BuildingType> = {
  Education: 'Education',
  Office: 'Office',
  'Public services': 'Public services',
  Public: 'Public services',
  Fox_education_Louie: 'Education',
  Fox_office_Alice: 'Office',
  Fox_public_Henry: 'Public services',
  教学楼: 'Education',
  办公楼: 'Office',
  公共楼: 'Public services',
  公共服务楼: 'Public services',
  图书馆: 'Public services',
  'Louie 教学楼': 'Education',
  'Alice 办公楼': 'Office',
  'Henry 公共服务楼': 'Public services',
}

const NORMALIZED_BUILDING_ALIASES = Object.fromEntries(
  Object.entries(BUILDING_ALIASES).map(([alias, buildingType]) => [
    normalizeBuildingAlias(alias),
    buildingType,
  ]),
) as Record<string, BuildingType>

const BUILDING_TEXT_REPLACEMENTS: Array<[RegExp, string]> = [
  [/\bEducation\b/gi, BUILDING_TYPE_LABELS.Education],
  [/\bOffice\b/gi, BUILDING_TYPE_LABELS.Office],
  [/\bPublic services\b/gi, BUILDING_TYPE_LABELS['Public services']],
  [/\bPublic\b/gi, BUILDING_TYPE_LABELS['Public services']],
  [/Fox_education_Louie/gi, BUILDING_TYPE_LABELS.Education],
  [/Fox_office_Alice/gi, BUILDING_TYPE_LABELS.Office],
  [/Fox_public_Henry/gi, BUILDING_TYPE_LABELS['Public services']],
  [/教学楼/gi, BUILDING_TYPE_LABELS.Education],
  [/办公楼/gi, BUILDING_TYPE_LABELS.Office],
  [/公共服务楼/gi, BUILDING_TYPE_LABELS['Public services']],
  [/公共楼/gi, BUILDING_TYPE_LABELS['Public services']],
  [/图书馆/gi, BUILDING_TYPE_LABELS['Public services']],
  [/Louie\s*教学楼/gi, BUILDING_TYPE_LABELS.Education],
  [/Alice\s*办公楼/gi, BUILDING_TYPE_LABELS.Office],
  [/Henry\s*公共(?:服务)?楼/gi, BUILDING_TYPE_LABELS['Public services']],
]

function normalizeBuildingAlias(value: string) {
  return value.trim().replace(/\s+/g, ' ').toLowerCase()
}

export function normalizeBuildingType(value?: string | null): BuildingType | undefined {
  const raw = String(value || '').trim()
  if (!raw) return undefined
  return NORMALIZED_BUILDING_ALIASES[normalizeBuildingAlias(raw)]
}

export function getBuildingLabel(value?: string | null, fallback = '未知建筑') {
  const buildingType = normalizeBuildingType(value)
  if (buildingType) return BUILDING_TYPE_LABELS[buildingType]

  const raw = String(value || '').trim()
  return raw || fallback
}

export function sanitizeBuildingText(value?: string | null) {
  const raw = String(value || '')
  const directLabel = normalizeBuildingType(raw)
  let text = directLabel ? BUILDING_TYPE_LABELS[directLabel] : raw
  BUILDING_TEXT_REPLACEMENTS.forEach(([pattern, replacement]) => {
    text = text.replace(pattern, replacement)
  })
  return text
}
