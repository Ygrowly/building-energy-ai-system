/**
 * 报表导出引擎
 *
 * 提供两种导出方式：
 *  1. exportToPDF  — 使用 html2pdf.js 将报表 DOM 转为 PDF 文件下载
 *  2. exportToHTML — 将报表 DOM 序列化为独立 HTML 文件下载（含内联样式）
 */

/**
 * 导出为 PDF
 * @param element - 报表容器 DOM 元素（ReportRenderer 的根元素）
 * @param filename - 文件名（不含扩展名）
 */
export async function exportToPDF(element: HTMLElement, filename: string): Promise<void> {
  const { default: html2pdf } = await import('html2pdf.js')
  const options = {
    margin: [8, 8, 8, 8],
    filename: `${filename}.pdf`,
    image: { type: 'jpeg', quality: 0.95 },
    html2canvas: {
      scale: 2,
      useCORS: true,
      allowTaint: true,
      backgroundColor: '#ffffff',
    },
    jsPDF: { unit: 'mm', format: 'a4', orientation: 'portrait' },
    pagebreak: { mode: ['avoid-all', 'css', 'legacy'] },
  }
  await html2pdf()
    .set(options as any)
    .from(element)
    .save()
}

/**
 * 导出为独立 HTML 文件
 * 将报表的 outerHTML 包装为完整 HTML 文档后下载。
 * 图表 base64 已嵌入 DOM，无需额外处理。
 */
export function exportToHTML(element: HTMLElement, filename: string): void {
  // 提取当前报表的所有 scoped 样式（含 <style scoped>）
  const styleSheets = Array.from(document.styleSheets)
  let cssText = ''
  for (const sheet of styleSheets) {
    try {
      const rules = Array.from(sheet.cssRules || [])
      cssText += rules.map(r => r.cssText).join('\n')
    } catch {
      // 跨域样式表跳过
    }
  }

  const htmlContent = `<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>${filename}</title>
  <style>
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body { background: #f5f5f5; display: flex; justify-content: center; padding: 24px; font-family: 'PingFang SC', 'Microsoft YaHei', sans-serif; }
    .report-html-wrap { width: 100%; max-width: 900px; }
    ${cssText}
  </style>
</head>
<body>
  <div class="report-html-wrap">
    ${element.outerHTML}
  </div>
</body>
</html>`

  const blob = new Blob([htmlContent], { type: 'text/html;charset=utf-8;' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `${filename}.html`
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
  URL.revokeObjectURL(url)
}

/**
 * 生成报表文件名
 */
export function buildReportFilename(title: string, buildingName?: string): string {
  const date = new Date().toLocaleDateString('zh-CN').replace(/\//g, '-')
  const parts = [buildingName, title, date].filter(Boolean)
  return parts.join('_').replace(/\s+/g, '')
}

/**
 * 将 CSV 文本解析为二维数组
 */
export function parseCSV(csvText: string): string[][] {
  return csvText
    .split('\n')
    .filter(line => line.trim())
    .map(line =>
      line.split(',').map(cell => cell.trim().replace(/^"|"$/g, '')),
    )
}
