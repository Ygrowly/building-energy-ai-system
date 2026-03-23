-- 迁移 013：notebook 主链路所需新增表
-- 执行前提：001–012 迁移已完成
-- 表职责说明：
--   kpi_expected_hourly         — notebook 仿真的楼级小时期望值（主基线）
--   kpi_anomaly_flags           — notebook 检测的楼级小时细粒度症状 flags
--   device_telemetry_hourly     — 设备级小时遥测事实表
--   device_status_latest        — 设备当前状态快照
--   anomaly_device_attributions — 楼级异常归因到具体设备

-- ===========================================================================
-- 1. kpi_expected_hourly
-- ===========================================================================
CREATE TABLE IF NOT EXISTS public.kpi_expected_hourly (
    timestamp                   TIMESTAMPTZ     NOT NULL,
    building_id                 TEXT            NOT NULL REFERENCES buildings(building_id) ON DELETE CASCADE,

    building_usage              TEXT            NULL,   -- office / teaching / library
    schedule_factor             REAL            NULL,   -- 时间系数 S ∈ [0.08, 1.0]
    hvac_mode                   TEXT            NULL,   -- cooling / heating / transition
    source_version              TEXT            NOT NULL DEFAULT 'notebook_v1',

    water_m3_expected           REAL            NULL,   -- 期望用水量（m³/h）
    electricity_kwh_expected    REAL            NULL,   -- 期望总电耗（kWh/h）
    hac_energy_expected         REAL            NULL,   -- 期望空调能耗（kWh/h）
    sim_supply_temp_c_expected  REAL            NULL,   -- 期望供水温度（℃）
    sim_return_temp_c_expected  REAL            NULL,   -- 期望回水温度（℃）
    humidity_rh_pct_expected    REAL            NULL,   -- 期望湿度（%）

    created_at                  TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    updated_at                  TIMESTAMPTZ     NOT NULL DEFAULT NOW(),

    CONSTRAINT kpi_expected_hourly_pkey PRIMARY KEY (building_id, timestamp)
);

CREATE INDEX IF NOT EXISTS idx_kpi_expected_ts
    ON public.kpi_expected_hourly (timestamp);
CREATE INDEX IF NOT EXISTS idx_kpi_expected_building_ts
    ON public.kpi_expected_hourly (building_id, timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_kpi_expected_hvac_mode
    ON public.kpi_expected_hourly (hvac_mode);

COMMENT ON TABLE public.kpi_expected_hourly IS
    'notebook 仿真基线期望值，每楼每小时一行，作为异常检测的物理参考基线';

-- ===========================================================================
-- 2. kpi_anomaly_flags
-- ===========================================================================
CREATE TABLE IF NOT EXISTS public.kpi_anomaly_flags (
    timestamp                   TIMESTAMPTZ     NOT NULL,
    building_id                 TEXT            NOT NULL REFERENCES buildings(building_id) ON DELETE CASCADE,

    -- 满幅度症状 flags
    flag_water                  BOOLEAN         NOT NULL DEFAULT FALSE,
    flag_electricity            BOOLEAN         NOT NULL DEFAULT FALSE,
    flag_hvac_energy            BOOLEAN         NOT NULL DEFAULT FALSE,
    flag_supply_deviation       BOOLEAN         NOT NULL DEFAULT FALSE,
    flag_return_deviation       BOOLEAN         NOT NULL DEFAULT FALSE,

    -- 软症状 / 联合 flags（用于捕获 ramp 阶段）
    flag_symptom_soft_any       BOOLEAN         NOT NULL DEFAULT FALSE,
    flag_symptom_union_any      BOOLEAN         NOT NULL DEFAULT FALSE,

    -- 阶段与根因
    anomaly_phase               TEXT            NULL,   -- ramp / full
    hvac_diagnosis              TEXT            NULL,   -- A_low_efficiency / B_small_deltaT / C_unexpected_on / other_hvac

    -- 元数据
    detection_mode              TEXT            NOT NULL DEFAULT 'union',
    source_version              TEXT            NOT NULL DEFAULT 'notebook_v1',
    evidence_json               JSONB           NULL,   -- 偏差值、供回水温差等证据

    created_at                  TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    updated_at                  TIMESTAMPTZ     NOT NULL DEFAULT NOW(),

    CONSTRAINT kpi_anomaly_flags_pkey PRIMARY KEY (building_id, timestamp)
);

CREATE INDEX IF NOT EXISTS idx_kpi_flags_ts
    ON public.kpi_anomaly_flags (timestamp);
CREATE INDEX IF NOT EXISTS idx_kpi_flags_building_ts
    ON public.kpi_anomaly_flags (building_id, timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_kpi_flags_union_any
    ON public.kpi_anomaly_flags (flag_symptom_union_any)
    WHERE flag_symptom_union_any = TRUE;
CREATE INDEX IF NOT EXISTS idx_kpi_flags_phase
    ON public.kpi_anomaly_flags (anomaly_phase)
    WHERE anomaly_phase IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_kpi_flags_diagnosis
    ON public.kpi_anomaly_flags (hvac_diagnosis)
    WHERE hvac_diagnosis IS NOT NULL;

COMMENT ON TABLE public.kpi_anomaly_flags IS
    'notebook 规则检测每楼每小时的细粒度症状 flags，是 anomaly_events 的上游数据源';

-- ===========================================================================
-- 3. device_telemetry_hourly
-- ===========================================================================
CREATE TABLE IF NOT EXISTS public.device_telemetry_hourly (
    device_id                   TEXT            NOT NULL REFERENCES devices(device_id) ON DELETE CASCADE,
    building_id                 TEXT            NOT NULL REFERENCES buildings(building_id) ON DELETE CASCADE,
    timestamp                   TIMESTAMPTZ     NOT NULL,
    device_type                 TEXT            NOT NULL,

    -- 状态字段
    online_status               TEXT            NULL,   -- online / offline / unknown
    running_state               TEXT            NULL,   -- running / standby / fault / off
    health_status               TEXT            NULL,   -- normal / warning / critical

    -- 通用遥测
    power_kw                    REAL            NULL,
    flow_rate                   REAL            NULL,
    valve_open_pct              REAL            NULL,
    frequency_hz                REAL            NULL,
    supply_temp_c               REAL            NULL,
    return_temp_c               REAL            NULL,
    ambient_temp_c              REAL            NULL,

    -- 扩展字段（不同设备类型的差异指标）
    metric_payload_json         JSONB           NULL,

    source                      TEXT            NULL,   -- simulated / real / imported
    created_at                  TIMESTAMPTZ     NOT NULL DEFAULT NOW(),

    CONSTRAINT device_telemetry_hourly_pkey PRIMARY KEY (device_id, timestamp)
);

CREATE INDEX IF NOT EXISTS idx_device_telemetry_building_ts
    ON public.device_telemetry_hourly (building_id, timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_device_telemetry_device_ts
    ON public.device_telemetry_hourly (device_id, timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_device_telemetry_type_ts
    ON public.device_telemetry_hourly (device_type, timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_device_telemetry_running
    ON public.device_telemetry_hourly (running_state)
    WHERE running_state IS NOT NULL;

COMMENT ON TABLE public.device_telemetry_hourly IS
    '设备级小时遥测事实表，支持设备历史状态查询和趋势分析';

-- ===========================================================================
-- 4. device_status_latest
-- ===========================================================================
CREATE TABLE IF NOT EXISTS public.device_status_latest (
    device_id                   TEXT            NOT NULL REFERENCES devices(device_id) ON DELETE CASCADE,
    building_id                 TEXT            NOT NULL REFERENCES buildings(building_id) ON DELETE CASCADE,
    device_type                 TEXT            NOT NULL,

    last_seen_at                TIMESTAMPTZ     NULL,
    online_status               TEXT            NULL,   -- online / offline / unknown
    running_state               TEXT            NULL,   -- running / standby / fault / off
    health_status               TEXT            NULL,   -- normal / warning / critical

    latest_power_kw             REAL            NULL,
    latest_flow_rate            REAL            NULL,
    latest_supply_temp_c        REAL            NULL,
    latest_return_temp_c        REAL            NULL,

    latest_payload_json         JSONB           NULL,
    updated_at                  TIMESTAMPTZ     NOT NULL DEFAULT NOW(),

    CONSTRAINT device_status_latest_pkey PRIMARY KEY (device_id)
);

CREATE INDEX IF NOT EXISTS idx_device_status_building
    ON public.device_status_latest (building_id);
CREATE INDEX IF NOT EXISTS idx_device_status_type
    ON public.device_status_latest (device_type);
CREATE INDEX IF NOT EXISTS idx_device_status_health
    ON public.device_status_latest (health_status);
CREATE INDEX IF NOT EXISTS idx_device_status_running
    ON public.device_status_latest (running_state);

COMMENT ON TABLE public.device_status_latest IS
    '设备最新状态快照，前端设备列表页和状态卡片优先查此表';

-- ===========================================================================
-- 5. anomaly_device_attributions
-- ===========================================================================
CREATE TABLE IF NOT EXISTS public.anomaly_device_attributions (
    id                          UUID            NOT NULL DEFAULT gen_random_uuid(),
    building_id                 TEXT            NOT NULL REFERENCES buildings(building_id) ON DELETE CASCADE,
    timestamp                   TIMESTAMPTZ     NOT NULL,

    event_id                    TEXT            NULL,   -- 对应 anomaly_events.id（软关联）
    device_id                   TEXT            NOT NULL REFERENCES devices(device_id) ON DELETE CASCADE,
    device_type                 TEXT            NOT NULL,

    attribution_role            TEXT            NULL,   -- primary / secondary / supporting
    attribution_score           REAL            NULL,   -- 0.0 ~ 1.0
    attribution_reason          TEXT            NULL,
    evidence_json               JSONB           NULL,

    created_at                  TIMESTAMPTZ     NOT NULL DEFAULT NOW(),

    CONSTRAINT anomaly_device_attributions_pkey PRIMARY KEY (id),
    CONSTRAINT uq_attribution_event_device UNIQUE (event_id, device_id)
        DEFERRABLE INITIALLY DEFERRED
);

CREATE INDEX IF NOT EXISTS idx_attr_building_ts
    ON public.anomaly_device_attributions (building_id, timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_attr_device_ts
    ON public.anomaly_device_attributions (device_id, timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_attr_event
    ON public.anomaly_device_attributions (event_id)
    WHERE event_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_attr_role
    ON public.anomaly_device_attributions (attribution_role);

COMMENT ON TABLE public.anomaly_device_attributions IS
    '楼级异常事件归因到具体设备，一条楼异常可对应多条设备归因';

-- ===========================================================================
-- 6. 为 anomaly_events 补充 notebook 相关字段（若迁移010已执行则用 IF NOT EXISTS）
-- ===========================================================================
ALTER TABLE public.anomaly_events
    ADD COLUMN IF NOT EXISTS anomaly_phase         TEXT NULL,
    ADD COLUMN IF NOT EXISTS symptom_flags_json    JSONB NULL,
    ADD COLUMN IF NOT EXISTS event_source          TEXT NULL DEFAULT 'notebook',
    ADD COLUMN IF NOT EXISTS severity              TEXT NULL DEFAULT 'warning';

CREATE INDEX IF NOT EXISTS idx_anomaly_events_phase
    ON public.anomaly_events (anomaly_phase)
    WHERE anomaly_phase IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_anomaly_events_severity
    ON public.anomaly_events (severity)
    WHERE severity IS NOT NULL;

COMMENT ON COLUMN public.anomaly_events.anomaly_phase IS
    '异常阶段：ramp（上升期）/ full（全量期）';
COMMENT ON COLUMN public.anomaly_events.symptom_flags_json IS
    '触发的所有症状 flags，JSON 格式';
COMMENT ON COLUMN public.anomaly_events.event_source IS
    '事件来源：notebook / legacy_scanner / realtime_fallback';
