/**
 * useReportExport composable
 *
 * Pages/components register report sections through this composable.
 * Page-level callers can also mark the current active report scope so
 * cached keep-alive pages do not leak sections into each other.
 */
import { onActivated, onDeactivated, onUnmounted } from 'vue'
import type * as echarts from '@/utils/echarts'
import { useReportStore } from '@/stores/reportStore'
import type { ReportSection, KpiItem, TableColumn, SummaryItem, ReportInsightItem } from '@/stores/reportStore'

export type { ReportSection, KpiItem, TableColumn, SummaryItem, ReportInsightItem }

interface UseReportExportOptions {
  activateScopePrefixes?: string[]
}

interface ChartCapturePadding {
  top?: number
  right?: number
  bottom?: number
  left?: number
}

interface ChartCaptureOptions {
  padding?: ChartCapturePadding
}

export function useReportExport(namespace: string, options: UseReportExportOptions = {}) {
  const reportStore = useReportStore()
  const scopePrefixes = options.activateScopePrefixes ?? []

  const activateScope = () => {
    if (!scopePrefixes.length) return
    reportStore.setActiveNamespacePrefixes(scopePrefixes)
  }

  const deactivateScope = () => {
    if (!scopePrefixes.length) return
    reportStore.clearActiveNamespacePrefixes(scopePrefixes)
  }

  onActivated(activateScope)
  onDeactivated(deactivateScope)

  onUnmounted(() => {
    deactivateScope()
    reportStore.clearSectionsByNamespace(namespace)
  })

  function registerSection(section: Omit<ReportSection, 'namespace'>) {
    reportStore.registerSection({ ...section, namespace })
  }

  function removeSection(id: string) {
    reportStore.removeSection(id)
  }

  function buildChartDataUrl(chartInstance: echarts.ECharts, options: ChartCaptureOptions = {}) {
    const pixelRatio = 2
    const padding = options.padding ?? {}
    const top = Math.max(0, padding.top ?? 0)
    const right = Math.max(0, padding.right ?? 0)
    const bottom = Math.max(0, padding.bottom ?? 0)
    const left = Math.max(0, padding.left ?? 0)
    const hasPadding = top > 0 || right > 0 || bottom > 0 || left > 0

    if (hasPadding) {
      try {
        const renderedCanvas = (chartInstance as any).getRenderedCanvas?.({
          pixelRatio,
          backgroundColor: '#ffffff',
        }) as HTMLCanvasElement | undefined

        if (renderedCanvas) {
          const scaledTop = top * pixelRatio
          const scaledRight = right * pixelRatio
          const scaledBottom = bottom * pixelRatio
          const scaledLeft = left * pixelRatio

          const outputCanvas = document.createElement('canvas')
          outputCanvas.width = renderedCanvas.width + scaledLeft + scaledRight
          outputCanvas.height = renderedCanvas.height + scaledTop + scaledBottom

          const context = outputCanvas.getContext('2d')
          if (context) {
            context.fillStyle = '#ffffff'
            context.fillRect(0, 0, outputCanvas.width, outputCanvas.height)
            context.drawImage(renderedCanvas, scaledLeft, scaledTop)
            return outputCanvas.toDataURL('image/png')
          }
        }
      } catch {
        // Fall back to ECharts native export below.
      }
    }

    return chartInstance.getDataURL({
      type: 'png',
      pixelRatio,
      backgroundColor: '#ffffff',
    })
  }

  function captureChart(
    chartInstance: echarts.ECharts | null | undefined,
    id: string,
    title: string,
    order = 100,
    options: ChartCaptureOptions = {},
  ) {
    if (!chartInstance) return
    try {
      const dataUrl = buildChartDataUrl(chartInstance, options)
      registerSection({
        id,
        title,
        type: 'chart',
        chartImage: dataUrl,
        order,
      })
    } catch {
      // Ignore chart capture failures when the chart is not ready yet.
    }
  }

  function openPreview() {
    reportStore.openPreview()
  }

  function setReportMeta(meta: Parameters<typeof reportStore.setReportMeta>[0]) {
    reportStore.setReportMeta(meta)
  }

  return {
    registerSection,
    removeSection,
    captureChart,
    openPreview,
    setReportMeta,
  }
}
