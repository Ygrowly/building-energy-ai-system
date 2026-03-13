-- =============================================================================
-- Migration 005: buildings 表补充 meter_device_id（与 ORM 一致）
-- 若库中 buildings 无此列，会导致 /api/buildings 及关联查询 500。
-- =============================================================================

ALTER TABLE buildings ADD COLUMN IF NOT EXISTS meter_device_id VARCHAR(64);

-- 为已有行生成唯一占位 ID（按 building_id 保证唯一）
UPDATE buildings
SET meter_device_id = 'M-DEV-' || building_id
WHERE meter_device_id IS NULL;

ALTER TABLE buildings ALTER COLUMN meter_device_id SET NOT NULL;

CREATE UNIQUE INDEX IF NOT EXISTS uq_buildings_meter_device_id ON buildings (meter_device_id);

COMMENT ON COLUMN buildings.meter_device_id IS '仪表设备 ID，如 M-OFF-001';
