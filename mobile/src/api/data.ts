import { get } from './request'

export interface BuildingOverview {
  building_id: string
  building_name: string
  building_type: string
  electricity_kwh: number
  water_m3: number
  hac_energy: number
  anomaly_count: number
  last_updated: string
  status: 'normal' | 'warning' | 'critical'
}

export interface OverviewResponse {
  buildings: BuildingOverview[]
  total_electricity_kwh: number
  total_water_m3: number
  total_anomalies: number
  updated_at: string
}

export interface AnomalyEvent {
  id: string
  building_id: string
  building_name?: string
  anomaly_type: string
  severity: 'high' | 'medium' | 'low'
  detected_at: string
  description: string
  status: 'open' | 'work_ordered' | 'resolved'
}

export const dataApi = {
  // 全局总览（手机端专用：只取最新一条能耗数据）
  overview(): Promise<OverviewResponse> {
    return get<OverviewResponse>('/api/overview')
  },

  // 异常事件列表
  anomalies(params?: { page?: number; page_size?: number; severity?: string }): Promise<{
    items: AnomalyEvent[]
    total: number
  }> {
    return get('/api/anomalies/attributions', params as Record<string, unknown>)
  },
}
