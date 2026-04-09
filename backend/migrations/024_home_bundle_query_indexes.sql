-- Migration 024: 首页首屏与分区查询索引优化

CREATE INDEX IF NOT EXISTS idx_energy_data_building_timestamp_desc
ON energy_data (building_id, "timestamp" DESC);

CREATE INDEX IF NOT EXISTS idx_devices_building_type
ON devices (building_id, device_type);
