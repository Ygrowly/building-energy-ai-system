-- =============================================================================
-- 迁移：anomaly_events 唯一约束从 (timestamp, building, rule) 改为 (timestamp, building)
-- 每小时每栋楼只保留一条异常事件（选偏差最大的规则作主规则）
-- =============================================================================

-- 1. 先清空表（避免违反新约束）
TRUNCATE TABLE anomaly_events CASCADE;

-- 2. 删除旧的三列唯一约束
ALTER TABLE anomaly_events
    DROP CONSTRAINT IF EXISTS uq_anomaly_event;

-- 3. 创建新的两列唯一约束
ALTER TABLE anomaly_events
    ADD CONSTRAINT uq_anomaly_event
    UNIQUE (data_timestamp, building_id);
