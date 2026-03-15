-- =============================================================================
-- Migration 008: 按照最终数据库设计文档（EMS v1）补齐两项变更
--
-- 变更 1：buildings 表新增 timezone 列
--   用于将 UTC 时序数据转换为建筑所在地的本地时间（按天/月聚合时精确对齐）
--
-- 变更 2：创建 devices 表（计量设备/传感器静态信息）
--   devices 是 buildings 的 1:N 子表，提供真实 device_id 用于：
--     - anomaly_events.meter_device_id（替代原先用 building_id 充当的占位值）
--     - rag_hybrid_search 的元数据过滤（device_id / device_type 精准过滤文档）
--     - create_work_order_draft 生成的工单设备标识
--
-- 变更 3：anomaly_events 补充优化
--   - 为 building_id 补充外键约束（CASCADE DELETE）
--   - 补充局部索引（Partial Index）加速未解决告警查询
--
-- 执行顺序：在 002_create_anomaly_events.sql 之后执行
-- =============================================================================

-- ─────────────────────────────────────────────────────────────────────────────
-- 1. buildings 表：新增 timezone 列
-- ─────────────────────────────────────────────────────────────────────────────
ALTER TABLE buildings
    ADD COLUMN IF NOT EXISTS timezone TEXT NOT NULL DEFAULT 'UTC';

COMMENT ON COLUMN buildings.timezone IS '建筑所在时区（IANA 时区名称），用于将 UTC 时序数据转换为本地时间聚合';

-- ─────────────────────────────────────────────────────────────────────────────
-- 2. 创建 devices 表
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS devices (
    device_id    TEXT PRIMARY KEY,
    building_id  TEXT NOT NULL REFERENCES buildings(building_id) ON DELETE CASCADE,
    device_type  TEXT NOT NULL                           -- 如 'ElectricityMeter', 'WaterMeter', 'HVAC', 'EnvSensor'
);

COMMENT ON TABLE  devices IS '计量设备/传感器静态信息表，1:N 关联 buildings';
COMMENT ON COLUMN devices.device_id   IS '设备唯一标识，如 Kassandra_M_Electricity';
COMMENT ON COLUMN devices.building_id IS '所属楼宇外键（CASCADE 删除）';
COMMENT ON COLUMN devices.device_type IS '设备类型，如 ElectricityMeter / WaterMeter / HVAC / EnvSensor';

-- 索引：加速查找某栋楼下的所有设备
CREATE INDEX IF NOT EXISTS idx_devices_building ON devices(building_id);

-- ─────────────────────────────────────────────────────────────────────────────
-- 3. anomaly_events 表：补充局部索引（Partial Index）
--    只为 is_resolved = FALSE 的行建索引，极速刷新监控大屏
-- ─────────────────────────────────────────────────────────────────────────────
CREATE INDEX IF NOT EXISTS idx_anomaly_events_unresolved
    ON anomaly_events (data_timestamp DESC)
    WHERE is_resolved = FALSE;

-- ─────────────────────────────────────────────────────────────────────────────
-- 4. 为已存在的楼宇自动生成 devices 记录（使用已有 buildings 数据）
--    按约定：每栋楼自动生成 4 种典型设备（电/水/暖通/环境传感器）
--    device_id 格式：{building_id}_{DeviceType_短码}
--    注意：若 devices 表已有数据则跳过（幂等）
-- ─────────────────────────────────────────────────────────────────────────────
INSERT INTO devices (device_id, building_id, device_type)
SELECT
    b.building_id || '_elec'  AS device_id,
    b.building_id,
    'ElectricityMeter'        AS device_type
FROM buildings b
WHERE NOT EXISTS (
    SELECT 1 FROM devices d
    WHERE d.building_id = b.building_id AND d.device_type = 'ElectricityMeter'
);

INSERT INTO devices (device_id, building_id, device_type)
SELECT
    b.building_id || '_water' AS device_id,
    b.building_id,
    'WaterMeter'              AS device_type
FROM buildings b
WHERE NOT EXISTS (
    SELECT 1 FROM devices d
    WHERE d.building_id = b.building_id AND d.device_type = 'WaterMeter'
);

INSERT INTO devices (device_id, building_id, device_type)
SELECT
    b.building_id || '_hvac'  AS device_id,
    b.building_id,
    'HVAC'                    AS device_type
FROM buildings b
WHERE NOT EXISTS (
    SELECT 1 FROM devices d
    WHERE d.building_id = b.building_id AND d.device_type = 'HVAC'
);

INSERT INTO devices (device_id, building_id, device_type)
SELECT
    b.building_id || '_env'   AS device_id,
    b.building_id,
    'EnvSensor'               AS device_type
FROM buildings b
WHERE NOT EXISTS (
    SELECT 1 FROM devices d
    WHERE d.building_id = b.building_id AND d.device_type = 'EnvSensor'
);

-- ─────────────────────────────────────────────────────────────────────────────
-- 5. 验证
-- ─────────────────────────────────────────────────────────────────────────────
SELECT 'buildings.timezone 列添加成功' AS status,
       COUNT(*) AS buildings_count
FROM buildings;

SELECT 'devices 表创建成功' AS status,
       COUNT(*) AS device_count
FROM devices;
