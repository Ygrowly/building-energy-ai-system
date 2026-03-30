/**
 * 基于 @chenglou/pretext 的文字适配工具
 *
 * pretext 在不触发 DOM reflow 的情况下精确计算文字尺寸，
 * 适用于动态截断、自适应字号、气泡高度预估等场景。
 */
import { prepare, layout } from '@chenglou/pretext'

/** 默认字体（与 uni.scss 一致） */
const DEFAULT_FONT = "-apple-system, 'PingFang SC', 'Helvetica Neue', sans-serif"

/**
 * 测量文字行数和高度
 */
export function measureText(
  text: string,
  width: number,
  fontSize: number = 14,
  lineHeight: number = 22,
) {
  const prepared = prepare(text, `${fontSize}px ${DEFAULT_FONT}`)
  return layout(prepared, width, lineHeight)
}

/**
 * 判断文字是否超过指定行数
 */
export function isTextOverflow(
  text: string,
  width: number,
  maxLines: number,
  fontSize: number = 14,
  lineHeight: number = 22,
): boolean {
  const { lineCount } = measureText(text, width, fontSize, lineHeight)
  return lineCount > maxLines
}

/**
 * 预估 AI 对话气泡高度（用于 scroll-view 优化）
 */
export function estimateBubbleHeight(
  content: string,
  maxWidth: number,
  fontSize: number = 13,
  lineHeight: number = 20,
  padding: number = 36,
): number {
  const { height } = measureText(content, maxWidth, fontSize, lineHeight)
  return height + padding
}

/**
 * 自适应字号：找到最大字号使文字不超过指定行数
 */
export function autoFitFontSize(
  text: string,
  containerWidth: number,
  maxFontSize: number = 18,
  minFontSize: number = 12,
  maxLines: number = 1,
  lineHeight: number = 24,
): number {
  for (let fs = maxFontSize; fs >= minFontSize; fs -= 1) {
    const prepared = prepare(text, `${fs}px ${DEFAULT_FONT}`)
    const { lineCount } = layout(prepared, containerWidth, lineHeight)
    if (lineCount <= maxLines) return fs
  }
  return minFontSize
}

/**
 * 智能截断文字到指定行数内（返回截断后的文字 + 是否被截断）
 */
export function truncateToLines(
  text: string,
  width: number,
  maxLines: number,
  fontSize: number = 14,
  lineHeight: number = 22,
): { text: string; truncated: boolean } {
  const { lineCount } = measureText(text, width, fontSize, lineHeight)
  if (lineCount <= maxLines) return { text, truncated: false }

  // 二分查找截断点
  let lo = 0, hi = text.length
  while (lo < hi) {
    const mid = Math.ceil((lo + hi) / 2)
    const sub = text.slice(0, mid) + '...'
    const { lineCount: lc } = measureText(sub, width, fontSize, lineHeight)
    if (lc <= maxLines) lo = mid
    else hi = mid - 1
  }
  return { text: text.slice(0, lo) + '...', truncated: true }
}
