import { sanitizeBuildingText } from '@/constants/buildings'

const EMPTY_FALLBACK = '—'

export interface ParsedWorkOrderIssue {
  raw: string
  building: string
  timeRange: string
  prefixTags: string[]
  title: string
  detailTags: string[]
}

function cleanText(value?: string | null) {
  return sanitizeBuildingText(String(value || '')).replace(/\s+/g, ' ').trim()
}

function splitDetailTags(value: string) {
  return value
    .split('，')
    .map(item => cleanText(item))
    .filter(Boolean)
}

export function parseWorkOrderIssue(value?: string | null): ParsedWorkOrderIssue {
  const raw = cleanText(value)
  if (!raw) {
    return {
      raw: '',
      building: '',
      timeRange: '',
      prefixTags: [],
      title: '',
      detailTags: [],
    }
  }

  let rest = raw
  const bracketTags: string[] = []

  while (true) {
    const match = rest.match(/^\[([^\]]+)\]\s*/)
    if (!match) break
    bracketTags.push(cleanText(match[1]))
    rest = rest.slice(match[0].length).trim()
  }

  const building = [...bracketTags].reverse().find(tag => !['预警', '预测'].includes(tag)) || ''
  const prefixTags = bracketTags.filter(tag => tag && tag !== building)

  const timeMatch = rest.match(/^(\d{4}-\d{2}-\d{2}\s\d{2}:\d{2}(?:~\d{4}-\d{2}-\d{2}\s\d{2}:\d{2})?)\s*/)
  const timeRange = timeMatch?.[1] || ''
  if (timeRange) {
    rest = rest.slice(timeMatch![0].length).trim()
  }

  const titleMatch = rest.match(/^(连续\s*\d+\s*次检测到[^，。]+|检测到[^，。]+|预测[^，。]+(?:将|会)?[^，。]*异常[^，。]*)/)
  const title = cleanText(titleMatch?.[1] || splitDetailTags(rest)[0] || rest)

  let tail = rest
  if (titleMatch) {
    tail = rest.slice(titleMatch[0].length).replace(/^[，、\s]+/, '').trim()
  }

  const detailTags = [
    ...prefixTags,
    ...(timeRange ? [timeRange] : []),
    ...splitDetailTags(tail),
  ].filter(Boolean)

  return {
    raw,
    building,
    timeRange,
    prefixTags,
    title,
    detailTags,
  }
}

export function formatWorkOrderIssueTitle(value?: string | null, fallback = EMPTY_FALLBACK) {
  const parsed = parseWorkOrderIssue(value)
  return parsed.title || parsed.raw || fallback
}

export function formatWorkOrderIssueTags(value?: string | null, limit = 4) {
  return parseWorkOrderIssue(value).detailTags.slice(0, limit)
}
