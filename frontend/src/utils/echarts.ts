import { BarChart, GaugeChart, LineChart, PieChart, RadarChart, SankeyChart } from 'echarts/charts'
import {
  DataZoomComponent,
  GridComponent,
  LegendComponent,
  MarkAreaComponent,
  MarkLineComponent,
  RadarComponent,
  TitleComponent,
  TooltipComponent,
} from 'echarts/components'
import { getInstanceByDom, init, use } from 'echarts/core'
import { CanvasRenderer } from 'echarts/renderers'
import type { ECharts } from 'echarts/core'

use([
  BarChart,
  CanvasRenderer,
  DataZoomComponent,
  GaugeChart,
  GridComponent,
  LegendComponent,
  LineChart,
  MarkAreaComponent,
  MarkLineComponent,
  PieChart,
  RadarChart,
  RadarComponent,
  SankeyChart,
  TitleComponent,
  TooltipComponent,
])

export { getInstanceByDom, init }
export type { ECharts }
export type SeriesOption = Record<string, unknown>
