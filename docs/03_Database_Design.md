# 03 数据库设计

> 数据库：PostgreSQL（通过 Tailscale 连接到共享开发库）  
> 最后更新：2026-03-24  
> 共 **14 张表**，按层次组织。

---

## 整体架构分层

```
buildings ──────────────────────────────────────────────────┐
    │                                                        │
    ├── devices ──── device_telemetry_hourly                 │
    │                device_status_latest                    │
    │                                                        ▼
    ├── energy_data ──► daily_energy_summary（物化视图）      anomaly_device_attributions
    │       │                                                ▲
    │       ▼                                                │
    ├── kpi_expected_hourly ──► kpi_anomaly_flags ──► anomaly_events
    │
users ── refresh_tokens
      ── chat_sessions
      ── dataset_files
```

| 层次 | 表 | 职责 |
|------|-----|------|
| 物理实体层 | `buildings`、`devices` | 静态元数据，所有数据的外键来源 |
| 时序事实层 | `energy_data`、`daily_energy_summary`、`device_telemetry_hourly`、`device_status_latest` | 高频写入的采集数据与聚合视图 |
| KPI 检测层 | `kpi_expected_hourly`、`kpi_anomaly_flags` | notebook 仿真基线与症状检测中间层 |
| 业务闭环层 | `anomaly_events`、`anomaly_device_attributions` | 最终告警记录与设备归因 |
| 用户认证层 | `users`、`refresh_tokens` | 登录鉴权与 token 管理 |
| AI 对话层 | `chat_sessions` | 多智能体会话上下文持久化 |
| 数据分析层 | `dataset_files` | 用户上传的结构化数据文件管理 |

---

## 一、物理实体层

### `buildings` — 建筑物信息表

建筑物的顶层实体，所有数据的核心外键来源。

| 字段 | 类型 | 可空 | 说明 |
|------|------|------|------|
| `building_id` | TEXT | NOT NULL | 主键，建筑唯一标识（如 `Kassandra_M`） |
| `primary_space_usage` | TEXT | — | 建筑用途：`Education` / `Office` / `Public services` |
| `sqm` | FLOAT | — | 建筑面积（平方米） |
| `timezone` | TEXT | NOT NULL | IANA 时区名（如 `Asia/Shanghai`），用于 UTC 时序数据转本地时间聚合，默认 `UTC` |

**索引：** `idx_buildings_usage`（`primary_space_usage`）

---

### `devices` — 计量设备/传感器表

建筑物下挂载的物理设备，与 `buildings` 为 1:N 关系。每栋楼自动初始化 4 种设备（电表、水表、暖通、环境传感器）。

| 字段 | 类型 | 可空 | 说明 |
|------|------|------|------|
| `device_id` | TEXT | NOT NULL | 主键，设备唯一标识（格式：`{building_id}_{类型缩写}`，如 `Kassandra_M_elec`） |
| `building_id` | TEXT | NOT NULL | 外键 → `buildings.building_id`（CASCADE 删除） |
| `device_type` | TEXT | NOT NULL | 设备类型：`ElectricityMeter` / `WaterMeter` / `HVAC` / `EnvSensor` |

**索引：** `idx_devices_building`（`building_id`）

---

## 二、时序事实层

### `energy_data` — 能耗时序宽表（核心事实表）

每小时采集一次的楼级能耗与环境数据，系统中写入最密集的表。复合主键 `(timestamp, building_id)`。

| 字段 | 类型 | 可空 | 说明 |
|------|------|------|------|
| `timestamp` | TIMESTAMPTZ | NOT NULL | 采集时间戳（UTC），与 `building_id` 构成复合主键 |
| `building_id` | TEXT | NOT NULL | 外键 → `buildings.building_id`（CASCADE 删除） |
| `electricity_kwh` | FLOAT | — | 当小时总电耗（kWh） |
| `water_m3` | FLOAT | — | 当小时用水量（m³） |
| `hac_energy` | FLOAT | — | 暖通空调综合能耗（kWh，Heating/Air-Conditioning） |
| `sim_supply_temp_c` | FLOAT | — | 模拟供水温度（℃） |
| `sim_return_temp_c` | FLOAT | — | 模拟回水温度（℃） |
| `air_temp_c` | FLOAT | — | 室外环境温度（℃） |
| `dew_temp_c` | FLOAT | — | 露点温度（℃） |
| `humidity_rh_pct` | FLOAT | — | 相对湿度（%） |

**索引：** `idx_energy_data_building_timestamp`（`building_id`, `timestamp DESC`）

---

### `daily_energy_summary` — 日能耗聚合视图（物化视图）

由 `energy_data` 按天聚合而来，ORM 只读映射，DDL 见 `migrations/007_create_daily_energy_summary.sql`。

```sql
SELECT date_trunc('day', timestamp)::date AS day,
       building_id,
       SUM(electricity_kwh) AS total_electricity_kwh,
       AVG(air_temp_c)      AS avg_ambient_temp,
       SUM(water_m3)        AS total_water_m3
FROM energy_data GROUP BY day, building_id;
```

| 字段 | 类型 | 说明 |
|------|------|------|
| `day` | DATE | 日期（复合主键之一） |
| `building_id` | TEXT | 所属建筑（复合主键之一） |
| `total_electricity_kwh` | FLOAT | 当日累计电耗（kWh） |
| `avg_ambient_temp` | FLOAT | 当日平均室外温度（℃） |
| `total_water_m3` | FLOAT | 当日累计用水量（m³） |

---

### `device_telemetry_hourly` — 设备级小时遥测表

设备历史运行状态事实表，支持设备级趋势分析与故障回溯。复合主键 `(device_id, timestamp)`。

| 字段 | 类型 | 可空 | 说明 |
|------|------|------|------|
| `device_id` | TEXT | NOT NULL | 外键 → `devices.device_id`（复合主键之一） |
| `timestamp` | TIMESTAMPTZ | NOT NULL | 遥测时间戳（复合主键之一） |
| `building_id` | TEXT | NOT NULL | 外键 → `buildings.building_id` |
| `device_type` | TEXT | NOT NULL | 设备类型 |
| `online_status` | TEXT | — | 在线状态：`online` / `offline` / `unknown` |
| `running_state` | TEXT | — | 运行状态：`running` / `standby` / `fault` / `off` |
| `health_status` | TEXT | — | 健康状态：`normal` / `warning` / `critical` |
| `power_kw` | FLOAT | — | 实时功率（kW） |
| `flow_rate` | FLOAT | — | 流量（适用水泵、冷冻水泵等） |
| `valve_open_pct` | FLOAT | — | 阀门开度百分比（%） |
| `frequency_hz` | FLOAT | — | 运行频率（Hz，适用变频设备） |
| `supply_temp_c` | FLOAT | — | 供水温度（℃） |
| `return_temp_c` | FLOAT | — | 回水温度（℃） |
| `ambient_temp_c` | FLOAT | — | 环境温度（℃） |
| `metric_payload_json` | JSONB | — | 不同设备类型的差异化扩展指标（JSON） |
| `source` | TEXT | — | 数据来源：`simulated` / `real` / `imported` |

**索引：** `idx_device_telemetry_building_ts`、`idx_device_telemetry_device_ts`

---

### `device_status_latest` — 设备最新状态快照表

每台设备只保留一行最新状态（Upsert 写入），前端设备列表页优先查此表，避免扫描全量历史数据。

| 字段 | 类型 | 可空 | 说明 |
|------|------|------|------|
| `device_id` | TEXT | NOT NULL | 主键，外键 → `devices.device_id` |
| `building_id` | TEXT | NOT NULL | 外键 → `buildings.building_id` |
| `device_type` | TEXT | NOT NULL | 设备类型 |
| `last_seen_at` | TIMESTAMPTZ | — | 最后一次上报时间 |
| `online_status` | TEXT | — | 在线状态 |
| `running_state` | TEXT | — | 运行状态 |
| `health_status` | TEXT | — | 健康状态 |
| `latest_power_kw` | FLOAT | — | 最新功率（kW） |
| `latest_flow_rate` | FLOAT | — | 最新流量 |
| `latest_supply_temp_c` | FLOAT | — | 最新供水温度（℃） |
| `latest_return_temp_c` | FLOAT | — | 最新回水温度（℃） |
| `latest_payload_json` | JSONB | — | 最新扩展指标（JSON） |

**索引：** `idx_device_status_building`、`idx_device_status_type`

---

## 三、KPI 检测层（notebook 仿真链路）

### `kpi_expected_hourly` — notebook 仿真基线期望值表

notebook 通过物理仿真模型计算每楼每小时的"正常应该是多少"，作为异常检测的物理参考基线。复合主键 `(building_id, timestamp)`。

| 字段 | 类型 | 可空 | 说明 |
|------|------|------|------|
| `timestamp` | TIMESTAMPTZ | NOT NULL | 时间戳（复合主键之一） |
| `building_id` | TEXT | NOT NULL | 外键 → `buildings.building_id`（复合主键之一） |
| `building_usage` | TEXT | — | 建筑功能类型：`office` / `teaching` / `library` |
| `schedule_factor` | FLOAT | — | 时间系数 S（∈ [0.08, 1.0]），反映不同时段建筑使用强度 |
| `hvac_mode` | TEXT | — | 暖通运行模式：`cooling` / `heating` / `transition` |
| `source_version` | TEXT | NOT NULL | 仿真版本号（默认 `notebook_v1`） |
| `water_m3_expected` | FLOAT | — | 期望用水量（m³/h） |
| `electricity_kwh_expected` | FLOAT | — | 期望总电耗（kWh/h） |
| `hac_energy_expected` | FLOAT | — | 期望空调能耗（kWh/h） |
| `sim_supply_temp_c_expected` | FLOAT | — | 期望供水温度（℃） |
| `sim_return_temp_c_expected` | FLOAT | — | 期望回水温度（℃） |
| `humidity_rh_pct_expected` | FLOAT | — | 期望相对湿度（%） |

**索引：** `idx_kpi_expected_ts`、`idx_kpi_expected_building_ts`

---

### `kpi_anomaly_flags` — notebook 症状检测 flags 表

notebook 检测链路的中间层，记录每楼每小时各维度是否超出阈值，是 `anomaly_events` 的上游数据源。复合主键 `(building_id, timestamp)`。

| 字段 | 类型 | 可空 | 说明 |
|------|------|------|------|
| `timestamp` | TIMESTAMPTZ | NOT NULL | 时间戳（复合主键之一） |
| `building_id` | TEXT | NOT NULL | 外键 → `buildings.building_id`（复合主键之一） |
| `flag_water` | BOOLEAN | NOT NULL | 用水量异常标志（默认 `false`） |
| `flag_electricity` | BOOLEAN | NOT NULL | 用电量异常标志（默认 `false`） |
| `flag_hvac_energy` | BOOLEAN | NOT NULL | 空调能耗异常标志（默认 `false`） |
| `flag_supply_deviation` | BOOLEAN | NOT NULL | 供水温度偏差异常标志（默认 `false`） |
| `flag_return_deviation` | BOOLEAN | NOT NULL | 回水温度偏差异常标志（默认 `false`） |
| `flag_symptom_soft_any` | BOOLEAN | NOT NULL | 软症状联合标志，用于捕获异常 ramp 上升期（默认 `false`） |
| `flag_symptom_union_any` | BOOLEAN | NOT NULL | 所有症状 OR 汇总标志（默认 `false`） |
| `anomaly_phase` | TEXT | — | 异常阶段：`ramp`（上升期）/ `full`（全量期） |
| `hvac_diagnosis` | TEXT | — | 暖通根因诊断：`A_low_efficiency` / `B_small_deltaT` / `C_unexpected_on` / `other_hvac` |
| `detection_mode` | TEXT | NOT NULL | 检测模式（默认 `union`） |
| `source_version` | TEXT | NOT NULL | 检测版本号（默认 `notebook_v1`） |
| `evidence_json` | JSONB | — | 证据详情（偏差值、供回水温差等） |

**索引：** `idx_kpi_flags_ts`、`idx_kpi_flags_building_ts`、`idx_kpi_flags_union_any`（局部）、`idx_kpi_flags_phase`、`idx_kpi_flags_diagnosis`

---

## 四、业务闭环层

### `anomaly_events` — 异常事件持久化表

系统最终输出的告警记录，由 notebook 检测链路或旧版后台扫描器写入。唯一约束 `(data_timestamp, building_id, rule_triggered)` 保证幂等写入。

| 字段 | 类型 | 可空 | 说明 |
|------|------|------|------|
| `id` | TEXT | NOT NULL | 主键（UUID） |
| `detected_at` | TIMESTAMPTZ | NOT NULL | 系统写入异常记录的时间 |
| `data_timestamp` | TIMESTAMPTZ | NOT NULL | 异常对应的原始能耗数据时间戳 |
| `building_id` | TEXT | NOT NULL | 外键 → `buildings.building_id`（CASCADE 删除） |
| `meter_device_id` | TEXT | NOT NULL | 触发告警的设备 ID |
| `rule_triggered` | TEXT | NOT NULL | 触发的规则名称（见下方取值说明） |
| `actual_value` | FLOAT | — | 实际检测值 |
| `threshold_value` | FLOAT | — | 规则阈值 |
| `expected_value` | FLOAT | — | 仿真期望值 |
| `deviation_pct` | FLOAT | — | 偏差百分比（%） |
| `hvac_root_cause` | TEXT | — | 暖通根因描述 |
| `message` | TEXT | — | 人类可读的告警描述文本 |
| `is_resolved` | BOOLEAN | NOT NULL | 是否已处理/关闭（默认 `false`） |
| `anomaly_phase` | TEXT | — | 异常阶段：`ramp`（上升期）/ `full`（全量期） |
| `symptom_flags_json` | JSONB | — | 触发的所有症状 flags（JSON 格式） |
| `event_source` | TEXT | — | 事件来源：`notebook` / `legacy_scanner` / `realtime_fallback`（默认 `notebook`） |
| `severity` | TEXT | — | 严重程度：`warning` / `critical`（默认 `warning`） |

**`rule_triggered` 取值：**
- 旧版：`water_leak` / `electricity_overload` / `hvac_overconsumption`
- notebook v2：`flag_water` / `flag_electricity` / `flag_hvac_energy` / `flag_supply_deviation` / `flag_return_deviation`

**索引：** `idx_anomaly_events_data_timestamp`、`idx_anomaly_events_building_ts`、`idx_anomaly_events_unresolved`（局部，`is_resolved=false`）、`idx_anomaly_events_phase`、`idx_anomaly_events_severity`

---

### `anomaly_device_attributions` — 异常事件设备归因表

将楼级异常事件精确归因到具体设备，一条楼级异常可对应多条设备归因记录（1:N 关系）。唯一约束 `(event_id, device_id)`。

| 字段 | 类型 | 可空 | 说明 |
|------|------|------|------|
| `id` | UUID | NOT NULL | 主键 |
| `building_id` | TEXT | NOT NULL | 外键 → `buildings.building_id`（CASCADE 删除） |
| `timestamp` | TIMESTAMPTZ | NOT NULL | 对应异常的时间戳 |
| `event_id` | TEXT | — | 软关联 `anomaly_events.id`（可为空，不做外键约束） |
| `device_id` | TEXT | NOT NULL | 外键 → `devices.device_id`（CASCADE 删除） |
| `device_type` | TEXT | NOT NULL | 设备类型 |
| `attribution_role` | TEXT | — | 归因角色：`primary`（主因）/ `secondary`（次因）/ `supporting`（辅助证据） |
| `attribution_score` | FLOAT | — | 归因置信度分数（0.0 ~ 1.0） |
| `attribution_reason` | TEXT | — | 归因理由文本描述 |
| `evidence_json` | JSONB | — | 归因证据详情（JSON） |

**索引：** `idx_attr_building_ts`、`idx_attr_device_ts`、`idx_attr_event`、`idx_attr_role`

---

## 五、用户认证层

### `users` — 系统用户表

| 字段 | 类型 | 可空 | 说明 |
|------|------|------|------|
| `id` | TEXT | NOT NULL | 主键（UUID） |
| `username` | TEXT(50) | NOT NULL | 登录用户名（唯一索引） |
| `hashed_password` | TEXT | NOT NULL | bcrypt 哈希密码（原始密码从不持久化） |
| `email` | TEXT(254) | — | 邮箱地址（唯一，可为空） |
| `phone` | TEXT(20) | — | 手机号（可为空） |
| `role` | TEXT(20) | NOT NULL | 用户角色：`resident`（住户）/ `ops`（运维人员）/ `manager`（运维经理）/ `admin`（系统管理员），默认 `resident` |
| `is_active` | BOOLEAN | NOT NULL | 账号是否启用（默认 `true`） |
| `created_at` | TIMESTAMPTZ | NOT NULL | 注册时间（自动填充） |

---

### `refresh_tokens` — Refresh Token 持久化表

支持 JWT 主动吊销与 token rotation 机制。每次 `/auth/refresh` 调用时旧 token 标记 `revoked=true`，同时颁发新的 access token + refresh token。

| 字段 | 类型 | 可空 | 说明 |
|------|------|------|------|
| `id` | TEXT | NOT NULL | 主键（UUID） |
| `jti` | TEXT | NOT NULL | JWT ID（JWT 载荷中的唯一标识符，唯一索引，不存储原始 token 字符串） |
| `user_id` | TEXT | NOT NULL | 外键 → `users.id`（CASCADE 删除） |
| `expires_at` | TIMESTAMPTZ | NOT NULL | Token 过期时间 |
| `created_at` | TIMESTAMPTZ | NOT NULL | 颁发时间（自动填充） |
| `revoked` | BOOLEAN | NOT NULL | 是否已吊销（默认 `false`） |

**索引：** `idx_refresh_tokens_user_id`（`user_id`）

---

## 六、AI 对话层

### `chat_sessions` — 对话会话表

多智能体控制台的会话管理，存储 AI 对话的完整上下文（LangChain AgentState 序列化）。`updated_at` 由数据库触发器自动维护。

| 字段 | 类型 | 可空 | 说明 |
|------|------|------|------|
| `id` | TEXT | NOT NULL | 主键，会话唯一标识 |
| `title` | TEXT | NOT NULL | 对话标题（默认"新对话"） |
| `created_at` | TIMESTAMPTZ | NOT NULL | 创建时间 |
| `updated_at` | TIMESTAMPTZ | NOT NULL | 最后更新时间（触发器自动维护） |
| `message_count` | INTEGER | NOT NULL | 会话消息总条数（默认 0） |
| `last_message` | TEXT | — | 最后一条消息的文本预览 |
| `building_id` | TEXT | — | 会话关联的建筑（可为空） |
| `is_archived` | BOOLEAN | NOT NULL | 是否已归档（默认 `false`） |
| `messages_json` | TEXT | — | LangChain `messages_to_dict()` 序列化的完整消息历史（JSON 字符串） |
| `extra_state_json` | TEXT | — | 其余 AgentState 字段的 JSON 序列化（工具调用状态等） |
| `user_id` | TEXT | — | 外键 → `users.id`，会话所属用户（可为空，兼容匿名会话） |

**索引：** `idx_chat_sessions_updated_at`（活跃会话，局部）、`idx_chat_sessions_archived`

---

## 七、数据分析层

### `dataset_files` — 用户上传数据集表

数据中心模块，管理用户上传的 CSV/Excel 结构化文件，解析后的统计信息以 JSON 形式存储。

| 字段 | 类型 | 可空 | 说明 |
|------|------|------|------|
| `id` | TEXT | NOT NULL | 主键（UUID） |
| `original_name` | TEXT | NOT NULL | 原始文件名 |
| `file_path` | TEXT | NOT NULL | 服务器本地磁盘存储路径 |
| `file_type` | TEXT(10) | NOT NULL | 文件格式：`csv` / `xlsx` / `xls` |
| `row_count` | INTEGER | — | 数据行数（解析后填充） |
| `column_count` | INTEGER | — | 数据列数 |
| `columns_json` | TEXT | — | 列信息 JSON：`[{name, dtype, null_count}, ...]` |
| `stats_json` | TEXT | — | 列统计 JSON：`{col: {min, max, mean, std}, ...}` |
| `uploaded_at` | TIMESTAMPTZ | NOT NULL | 上传时间（自动填充） |
| `uploader_id` | TEXT | — | 外键 → `users.id`（用户删除后置 NULL） |

**索引：** `idx_dataset_files_uploader`（`uploader_id`）、`idx_dataset_files_uploaded_at`（`uploaded_at`）

---

## 迁移历史

| 迁移文件 | 内容 |
|----------|------|
| `001_create_chat_sessions.sql` | 创建 `chat_sessions` 表及自动更新触发器 |
| `002_create_anomaly_events.sql` | 创建 `anomaly_events` 基础表及唯一约束 |
| `003_create_users.sql` | 创建 `users` 表 |
| `004_create_datasets.sql` | 创建 `dataset_files` 表 |
| `005_buildings_meter_device_id.sql` | `buildings` 补充 `meter_device_id` 列（已被 008 设备表方案替代） |
| `006_users_add_contact.sql` | `users` 补充 `email` / `phone` 字段 |
| `007_create_daily_energy_summary.sql` | 创建 `daily_energy_summary` 物化视图 |
| `008_add_timezone_and_devices.sql` | `buildings` 新增 `timezone`；创建 `devices` 表；自动生成每楼 4 种设备记录 |
| `009_add_chat_sessions_user_id.sql` | `chat_sessions` 新增 `user_id` 字段 |
| `010_upgrade_anomaly_events.sql` | `anomaly_events` 新增 `expected_value` / `deviation_pct` / `hvac_root_cause` |
| `011_deduplicate_energy_data.sql` | `energy_data` 数据去重处理 |
| `012_add_user_role.sql` | `users` 新增 `role` 字段 |
| `013_notebook_kpi_tables.sql` | 创建 `kpi_expected_hourly`、`kpi_anomaly_flags`、`device_telemetry_hourly`、`device_status_latest`、`anomaly_device_attributions`；`anomaly_events` 新增 notebook v2 字段 |
