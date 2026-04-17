-- =============================================================================
-- 迁移 010：升级 anomaly_events 表，支持物理分层诊断方案
-- 执行方式：在 PostgreSQL 客户端/psql中粘贴并运行
-- 执行顺序：在 002_create_anomaly_events.sql 之后执行
-- =============================================================================
-- 变更说明：
--   1. 新增 hvac_root_cause  — HVAC 根因诊断码（第二层诊断层输出）
--   2. 新增 expected_value   — 国标期望值（用于前端展示"实际 vs 期望"差值）
--   3. 新增 deviation_pct    — 相对偏差百分比，前端可直接渲染进度条/热图
-- =============================================================================

-- 1. 新增 hvac_root_cause 列
--    取值：'A_low_efficiency' | 'B_small_deltaT' | 'C_unexpected_on' | 'other_hvac' | NULL
--    仅当 rule_triggered = 'hvac_overconsumption' 时非 NULL
ALTER TABLE anomaly_events
    ADD COLUMN IF NOT EXISTS hvac_root_cause TEXT DEFAULT NULL;

COMMENT ON COLUMN anomaly_events.hvac_root_cause IS
    'HVAC 根因诊断码：
     A_low_efficiency  — 主机效能衰退（供水温度偏离期望 > 1.5℃）
     B_small_deltaT    — 水力失调/大流量小温差（供回水温差 < 3℃）
     C_unexpected_on   — 非预期开机/排程失效（设计负荷率 ≤ 0.05 但空调仍运行）
     other_hvac        — 空调能耗异常但无法归因于以上三类';

-- 2. 新增 expected_value 列（国标期望值，与 actual_value 同量纲）
ALTER TABLE anomaly_events
    ADD COLUMN IF NOT EXISTS expected_value DOUBLE PRECISION DEFAULT NULL;

COMMENT ON COLUMN anomaly_events.expected_value IS
    '基于国标（GB）仿真算法计算的期望值，与 actual_value 同量纲。
     用于前端展示"实际 vs 期望"差值和偏差百分比。';

-- 3. 新增 deviation_pct 列（相对偏差 %，便于前端直接渲染）
ALTER TABLE anomaly_events
    ADD COLUMN IF NOT EXISTS deviation_pct DOUBLE PRECISION DEFAULT NULL;

COMMENT ON COLUMN anomaly_events.deviation_pct IS
    '相对偏差百分比：(actual_value - expected_value) / expected_value × 100。
     正值表示实际超过期望，负值表示实际低于期望（如传感器掉线或异常低值）。';

-- 4. 新增检索索引：按根因诊断类型快速过滤（运维人员关心哪类根因最多）
CREATE INDEX IF NOT EXISTS idx_anomaly_events_hvac_root_cause
    ON anomaly_events (hvac_root_cause)
    WHERE hvac_root_cause IS NOT NULL;

-- 5. 验证
SELECT
    'anomaly_events 升级成功' AS status,
    COUNT(*) AS existing_rows,
    COUNT(hvac_root_cause) AS hvac_diagnosed_rows,
    COUNT(expected_value) AS expected_value_rows
FROM anomaly_events;

