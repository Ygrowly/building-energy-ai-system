-- =============================================================================
-- Migration 007: 创建物化视图 daily_energy_summary
-- 基于实际 energy_data 列名（air_temp_c / water_m3）
-- ORM 映射见 app/db/models.py DailyEnergySummary
-- =============================================================================

CREATE MATERIALIZED VIEW IF NOT EXISTS daily_energy_summary AS
SELECT
    date_trunc('day', "timestamp")::date AS day,
    building_id,
    SUM(electricity_kwh)  AS total_electricity_kwh,
    AVG(air_temp_c)       AS avg_ambient_temp,
    SUM(water_m3)         AS total_water_m3
FROM energy_data
GROUP BY date_trunc('day', "timestamp")::date, building_id
WITH DATA;

CREATE UNIQUE INDEX IF NOT EXISTS idx_daily_summary_day_building
    ON daily_energy_summary (day, building_id);
