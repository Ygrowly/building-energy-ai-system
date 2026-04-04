/**
 * 数据查询 API — 精确对齐后端 routes_data.py
 */
import { get } from './request'

// ---- GET /api/overview 响应 ----

export interface BuildingDetail {
  building_type: string
  display_name: string
  icon: string
  total_electricity_kwh: number
  total_water_m3: number
  total_hac_energy_kwh: number
  avg_ambient_temp: number | null
  sqm: number
  energy_intensity_kwh_per_sqm: number | null
  anomaly_status: 'Normal' | 'Anomaly'
  latest_water_m3: number
  electricity_change_pct: number | null
  water_change_pct: number | null
  hac_change_pct: number | null
  carbon_change_pct: number | null
  prediction_warning_count: number
  prediction_status: 'normal' | 'warning' | 'critical'
}

export interface OverviewResponse {
  data_date: string
  kpis: {
    total_electricity_kwh: number
    total_water_m3: number
    total_hac_energy_kwh: number
    total_carbon_kg: number
    anomaly_count: number
    prediction_warning_count: number
  }
  kpis_change: {
    total_electricity_pct: number | null
    total_water_pct: number | null
    total_hac_pct: number | null
    total_carbon_pct: number | null
  }
  weather: {
    temperature: number | null
    humidity: number | null
  }
  buildings: BuildingDetail[]
}

// ---- GET /api/anomalies/recent 响应 ----

export interface AnomalyItem {
  id: string
  detected_at: string | null
  data_timestamp: string | null
  building_id: string
  meter_device_id: string | null
  rule_triggered: string
  actual_value: number | null
  expected_value: number | null
  deviation_pct: number | null
  message: string | null
  is_resolved: boolean
  severity: string | null
  hvac_root_cause: string | null
  anomaly_phase: string | null
  event_source: string | null
}

export interface RecentAnomaliesResponse {
  anomalies: AnomalyItem[]
  total: number
  check_period: {
    start: string | null
    end: string | null
    hours: number
  }
  source: string
  module_status: string
}

// ---- GET /api/buildings/{building_type}/load-profile 响应 ----

export interface HourlyPoint {
  hour: number
  avg_value: number
  sample_count?: number
}

export interface WeekdayPoint {
  weekday: number
  label?: string
  avg_value: number
}

export interface LoadProfileResponse {
  building_type: string
  building_id: string
  metric: string
  days: number
  hourly_profile: HourlyPoint[]
  weekday_profile: WeekdayPoint[]
}

// ---- GET /api/buildings/risk-now 响应 ----

export interface RiskItem {
  building_id: string
  building_name: string
  building_type?: string
  hvac_mode: string
  hvac_mode_label: string
  expected_hac: number
  air_temp: number
  risk_level: 'high' | 'medium' | 'low' | 'normal'
  deviation_pct?: number | null
  risk_desc: string
}

export interface RiskNowResponse {
  risks: RiskItem[]
}

// ---- GET /api/predictions/recent 响应 ----

export interface PredictionItem {
  id: string
  created_at: string | null
  as_of_timestamp: string | null
  forecast_for_timestamp: string | null
  horizon_h: number
  building_id: string
  building_name: string
  building_type?: string
  metric_name: string
  predicted_value: number | null
  expected_value: number | null
  deviation_pct: number | null
  risk_level: 'warning' | 'critical' | 'normal'
  rule_triggered: string | null
  model_name: string | null
  is_confirmed: boolean | null
}

export interface RecentPredictionsResponse {
  predictions: PredictionItem[]
  total: number
  check_period: {
    start: string | null
    end: string | null
    hours: number
  }
  message?: string
}

export const dataApi = {
  /** 全局总览（Dashboard KPI 汇总） */
  overview(date?: string): Promise<OverviewResponse> {
    return get<OverviewResponse>('/api/overview', date ? { date } : undefined)
  },

  /** 近期异常告警 */
  recentAnomalies(params?: {
    hours?: number
    building_type?: string
    only_unresolved?: boolean
  }): Promise<RecentAnomaliesResponse> {
    return get<RecentAnomaliesResponse>('/api/anomalies/recent', params as Record<string, unknown>)
  },

  /** 实时能耗风险评估 */
  riskNow(): Promise<RiskNowResponse> {
    return get<RiskNowResponse>('/api/buildings/risk-now')
  },

  /** 近期预测预警记录 */
  recentPredictions(params?: {
    hours?: number
    building_type?: string
    risk_level?: 'warning' | 'critical'
  }): Promise<RecentPredictionsResponse> {
    return get<RecentPredictionsResponse>('/api/predictions/recent', params as Record<string, unknown>)
  },

  /** 建筑负荷曲线（热力图数据） */
  loadProfile(buildingType: string, metric = 'electricity', days = 14): Promise<LoadProfileResponse> {
    return get<LoadProfileResponse>(
      `/api/buildings/${encodeURIComponent(buildingType)}/load-profile`,
      { metric, days } as Record<string, unknown>,
    )
  },
}
