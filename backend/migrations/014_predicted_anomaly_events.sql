-- 迁移 014：预测预警事件表
-- 执行前提：001–013 迁移已完成
-- 职责：存储 ML 模型预测的未来 6h/12h 异常预警，与已发生异常 (anomaly_events) 分离

CREATE TABLE IF NOT EXISTS public.predicted_anomaly_events (
    id                          TEXT            NOT NULL DEFAULT gen_random_uuid()::text,
    created_at                  TIMESTAMPTZ     NOT NULL DEFAULT NOW(),

    -- 时间维度
    as_of_timestamp             TIMESTAMPTZ     NOT NULL,   -- 预测发起时刻（模型输入行对应的时间）
    forecast_for_timestamp      TIMESTAMPTZ     NOT NULL,   -- 预测目标时刻（as_of + horizon）
    horizon_h                   INTEGER         NOT NULL,   -- 预测跨度：6 或 12

    -- 空间维度
    building_id                 TEXT            NOT NULL REFERENCES buildings(building_id) ON DELETE CASCADE,

    -- 预测值与基线对比
    metric_name                 TEXT            NOT NULL,   -- water_l / electricity_kwh / sim_supply_temp_c / sim_return_temp_c / hac_energy
    predicted_value             REAL            NOT NULL,
    expected_value              REAL            NULL,       -- 来自 kpi_expected_hourly，可能为空
    deviation_pct               REAL            NULL,       -- (predicted - expected) / expected * 100

    -- 风险判定
    risk_level                  TEXT            NOT NULL DEFAULT 'normal',  -- normal / warning / critical
    rule_triggered              TEXT            NULL,       -- water_leak / electricity_overload / hvac_overconsumption

    -- 模型元数据
    model_name                  TEXT            NOT NULL,

    -- 回溯评估
    is_confirmed                BOOLEAN         NULL,       -- 事后回填：预测是否命中真实异常

    CONSTRAINT predicted_anomaly_events_pkey PRIMARY KEY (id)
);

CREATE INDEX IF NOT EXISTS idx_predicted_anomaly_as_of
    ON public.predicted_anomaly_events (as_of_timestamp);
CREATE INDEX IF NOT EXISTS idx_predicted_anomaly_forecast_for
    ON public.predicted_anomaly_events (forecast_for_timestamp);
CREATE INDEX IF NOT EXISTS idx_predicted_anomaly_building_ts
    ON public.predicted_anomaly_events (building_id, as_of_timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_predicted_anomaly_risk
    ON public.predicted_anomaly_events (risk_level)
    WHERE risk_level != 'normal';

COMMENT ON TABLE public.predicted_anomaly_events IS
    'ML 模型预测的未来异常预警，与已发生异常 anomaly_events 分离存储，支持事后命中率评估';
