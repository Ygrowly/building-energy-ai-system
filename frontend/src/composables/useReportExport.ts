/**
 * useReportExport composable
 *
 * 各页面（及子组件）通过此 composable 向 reportStore 注册报表段落。
 * 每个调用方传入唯一 namespace，组件卸载时自动清理该命名空间的段落。
 */
import { onUnmounted } from 'vue'
import type * as echarts from 'echarts'
import { useReportStore } from '@/stores/reportStore'
import type { ReportSection, KpiItem, TableColumn, SummaryItem } from '@/stores/reportStore'

export type { ReportSection, KpiItem, TableColumn, SummaryItem }

export function useReportExport(namespace: string) {
  const reportStore = useReportStore()

  // 组件卸载时清理本命名空间的所有段落
  onUnmounted(() => {
    reportStore.clearSectionsByNamespace(namespace)
  })

  /** 注册或更新一个报表段落（相同 id 则覆盖） */
  function registerSection(section: Omit<ReportSection, 'namespace'>) {
    reportStore.registerSection({ ...section, namespace })
  }

  /** 移除指定段落 */
  function removeSection(id: string) {
    reportStore.removeSection(id)
  }

  /**
   * 将 ECharts 实例截图为 base64 并注册为 chart 类型段落
   * @param chartInstance - ECharts 实例
   * @param id - 段落唯一 id
   * @param title - 段落标题
   * @param order - 排序权重
   */
  function captureChart(
    chartInstance: echarts.ECharts | null | undefined,
    id: string,
    title: string,
    order = 100,
  ) {
    if (!chartInstance) return
    try {
      const dataUrl = chartInstance.getDataURL({
        type: 'png',
        pixelRatio: 2,
        backgroundColor: '#ffffff',
      })
      registerSection({
        id,
        title,
        type: 'chart',
        chartImage: dataUrl,
        order,
      })
    } catch {
      // 截图失败时静默跳过（图表可能尚未渲染）
    }
  }

  /** 打开报表预览弹窗（使用当前已注册的所有段落） */
  function openPreview() {
    reportStore.openPreview()
  }

  /** 设置报表元信息（标题、楼宇、日期范围等） */
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
