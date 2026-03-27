-- =============================================================================
-- Migration 007: 创建物化视图 daily_energy_summary
-- 基于 energy_data 按天聚合，包含所有前端查询统计页面所需字段
-- ORM 映射见 app/db/models.py DailyEnergySummary
-- =============================================================================

DROP MATERIALIZED VIEW IF EXISTS daily_energy_summary;

CREATE MATERIALIZED VIEW daily_energy_summary AS
SELECT
    date_trunc('day', "timestamp")::date AS day,
    building_id,
    SUM(electricity_kwh)    AS total_electricity_kwh,
    AVG(air_temp_c)         AS avg_ambient_temp,
    SUM(water_m3)           AS total_water_m3,
    SUM(hac_energy)         AS total_hac_energy,
    AVG(sim_supply_temp_c)  AS avg_supply_temp,
    AVG(sim_return_temp_c)  AS avg_return_temp,
    AVG(humidity_rh_pct)    AS avg_humidity,
    AVG(dew_temp_c)         AS avg_dew_temp
FROM energy_data
GROUP BY date_trunc('day', "timestamp")::date, building_id
WITH DATA;

CREATE UNIQUE INDEX IF NOT EXISTS idx_daily_summary_day_building
    ON daily_energy_summary (day, building_id);
