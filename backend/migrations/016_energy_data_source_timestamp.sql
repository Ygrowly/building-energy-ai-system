-- migration 016:
-- 1. add energy_data.source_timestamp to preserve CSV business time
-- 2. enforce replay idempotency by building_id + source_timestamp

ALTER TABLE public.energy_data
    ADD COLUMN IF NOT EXISTS source_timestamp TIMESTAMPTZ NULL;

CREATE UNIQUE INDEX IF NOT EXISTS uq_energy_data_building_source_timestamp
    ON public.energy_data (building_id, source_timestamp);

CREATE INDEX IF NOT EXISTS idx_energy_data_source_timestamp
    ON public.energy_data (source_timestamp DESC);

COMMENT ON COLUMN public.energy_data.source_timestamp IS
    '原始传感器/CSV 业务时间戳；回放写入时用于幂等键，避免同一 source hour 重复入库';
