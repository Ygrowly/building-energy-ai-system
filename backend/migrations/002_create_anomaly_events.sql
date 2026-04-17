-- =============================================================================
-- 迁移：创建异常事件持久化表 anomaly_events
-- 执行方式：在 PostgreSQL 客户端/psql中粘贴并运行
-- 执行顺序：在 buildings / energy_data / 001_create_chat_sessions 之后执行
-- =============================================================================

-- 1. 创建异常事件表
CREATE TABLE IF NOT EXISTS anomaly_events (
    id               TEXT        PRIMARY KEY,
    detected_at      TIMESTAMPTZ NOT NULL,
    data_timestamp   TIMESTAMPTZ NOT NULL,
    building_id      TEXT        NOT NULL,
    building_type    TEXT        NOT NULL,
    meter_device_id  TEXT        NOT NULL,
    rule_triggered   TEXT        NOT NULL,
    actual_value     DOUBLE PRECISION,
    threshold_value  DOUBLE PRECISION,
    message          TEXT,
    is_resolved      BOOLEAN     NOT NULL DEFAULT FALSE
);

-- 2. 唯一约束：同一小时同一楼宇只写入一条事件（保证幂等扫描）
--    注意：约束已由迁移 015_anomaly_events_unique_per_hour.sql 更新为
--          UNIQUE (data_timestamp, building_id)，去掉了 rule_triggered 列
ALTER TABLE anomaly_events
    DROP CONSTRAINT IF EXISTS uq_anomaly_event;
ALTER TABLE anomaly_events
    ADD CONSTRAINT uq_anomaly_event
    UNIQUE (data_timestamp, building_id, rule_triggered);

-- 3. 索引：按数据发生时间查询（最常用过滤条件）
CREATE INDEX IF NOT EXISTS idx_anomaly_events_data_timestamp
    ON anomaly_events (data_timestamp DESC);

-- 4. 索引：按楼宇 + 时间复合查询
CREATE INDEX IF NOT EXISTS idx_anomaly_events_building_ts
    ON anomaly_events (building_id, data_timestamp DESC);

-- 5. 索引：仅看未解决的告警（Dashboard 常用过滤）
CREATE INDEX IF NOT EXISTS idx_anomaly_events_unresolved
    ON anomaly_events (data_timestamp DESC)
    WHERE is_resolved = FALSE;

-- 6. 授权（将 your_app_user 替换为实际 PostgreSQL 应用账号角色名）
-- 注意：anomaly_events 需要完整读写权限（后台服务需要 INSERT）
-- 执行前先确认账号名：SELECT current_user;
-- GRANT SELECT, INSERT, UPDATE ON anomaly_events TO your_app_user;

-- 7. 验证
SELECT 'anomaly_events 表创建成功' AS status,
       COUNT(*) AS row_count
FROM anomaly_events;


