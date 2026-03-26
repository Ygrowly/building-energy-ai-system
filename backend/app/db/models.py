"""
SQLAlchemy ORM 表定义（与 Supabase DDL 严格对齐）。
energy_data / buildings / daily_energy_summary：Data Agent 只读账号（SELECT only）。
anomaly_events：后台检测服务拥有完整读写权限。

数据库四层架构：
  物理实体（buildings/devices） + 时序事实（energy_data） + 业务闭环（anomaly_events）

energy_data 实际列（以 Supabase schema 为准）：
  timestamp, building_id, electricity_kwh, water_m3, hac_energy,
  sim_supply_temp_c, sim_return_temp_c, air_temp_c, dew_temp_c,
  humidity_rh_pct, anomaly_status
"""
import uuid

from sqlalchemy import (
    Boolean,
    Column,
    Date,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy import TIMESTAMP
from sqlalchemy.sql import func
from sqlalchemy.orm import DeclarativeBase, relationship


class Base(DeclarativeBase):
    pass


# ---------------------------------------------------------------------------
# buildings — 资产身份证（关系型，静态元数据）
# DDL 列：building_id, primary_space_usage, sqm, timezone
# ---------------------------------------------------------------------------

class Building(Base):
    """
    建筑物静态信息表（多租户顶层实体）。
    primary_space_usage 对应原 building_type（'Education'/'Office'/'Public services'）。
    """
    __tablename__ = "buildings"

    building_id: str = Column(String, primary_key=True)
    primary_space_usage: str = Column(String)
    sqm: float = Column(Float)

    devices = relationship("Device", back_populates="building", cascade="all, delete-orphan")

    __table_args__ = (
        Index("idx_buildings_usage", "primary_space_usage"),
    )


# ---------------------------------------------------------------------------
# devices — 计量设备/传感器（静态信息，N:1 关联 buildings）
# DDL 列：device_id, building_id, device_type
# ---------------------------------------------------------------------------

class Device(Base):
    """
    设备/传感器静态信息表。
    device_type 如 'ElectricityMeter'/'WaterMeter'/'HVAC'/'EnvSensor'。
    一栋楼可挂载多个不同类型的设备（1:N）。
    """
    __tablename__ = "devices"

    device_id: str = Column(String, primary_key=True)
    building_id: str = Column(
        String,
        ForeignKey("buildings.building_id", ondelete="CASCADE"),
        nullable=False,
    )
    device_type: str = Column(String, nullable=False)

    building = relationship("Building", back_populates="devices")

    __table_args__ = (
        Index("idx_devices_building", "building_id"),
    )


# ---------------------------------------------------------------------------
# energy_data — 核心数据日志（时序宽表）
# 实际 DDL 列（以 Supabase schema 为准）：
#   timestamp, building_id, electricity_kwh, water_m3, hac_energy,
#   sim_supply_temp_c, sim_return_temp_c,
#   air_temp_c, dew_temp_c, humidity_rh_pct, anomaly_status
# ---------------------------------------------------------------------------

class EnergyData(Base):
    """
    能耗时序记录表（写入最密集的"事实表"）。
    复合主键 (timestamp, building_id)。
    直接外键关联 buildings，避免经由 devices 表做深度 JOIN（时序架构优化）。
    hac_energy → 暖通空调综合能耗（Heating/Air-Conditioning）
    """
    __tablename__ = "energy_data"

    timestamp = Column(TIMESTAMP(timezone=True), primary_key=True, nullable=False)
    building_id: str = Column(
        String,
        ForeignKey("buildings.building_id", ondelete="CASCADE"),
        primary_key=True,
        nullable=False,
    )

    electricity_kwh: float = Column(Float)
    water_m3: float = Column(Float)
    hac_energy: float = Column(Float)
    sim_supply_temp_c: float = Column(Float)
    sim_return_temp_c: float = Column(Float)
    air_temp_c: float = Column(Float)
    dew_temp_c: float = Column(Float)
    humidity_rh_pct: float = Column(Float)

    __table_args__ = (
        Index(
            "idx_energy_data_building_timestamp",
            "building_id",
            timestamp.desc(),
        ),
    )


# ---------------------------------------------------------------------------
# daily_energy_summary — 物化视图（只读映射，不做 DDL 管理）
# 视图 DDL 见 migrations/007_create_daily_energy_summary.sql
# ---------------------------------------------------------------------------

class DailyEnergySummary(Base):
    """
    物化视图 daily_energy_summary 的 ORM 映射。
    字段与视图 DDL 严格一一对应：
      SELECT date_trunc('day', timestamp)::date AS day,
             building_id,
             SUM(electricity_kwh) AS total_electricity_kwh,
             AVG(air_temp_c)      AS avg_ambient_temp,
             SUM(water_m3)        AS total_water_m3
      FROM energy_data GROUP BY day, building_id;
    """
    __tablename__ = "daily_energy_summary"

    day = Column(Date, primary_key=True, nullable=False)
    building_id: str = Column(String, primary_key=True, nullable=False)
    total_electricity_kwh: float = Column(Float)
    avg_ambient_temp: float = Column(Float)
    total_water_m3: float = Column(Float)

    __table_args__ = (
        Index(
            "idx_daily_summary_day_building",
            "day",
            "building_id",
            unique=True,
        ),
        {"info": {"is_view": True}},
    )


# ---------------------------------------------------------------------------
# anomaly_events — 异常事件持久化表（后台检测服务写入）
# 实际 DDL 列：id(UUID), detected_at, data_timestamp, building_id,
#              meter_device_id, rule_triggered, actual_value, threshold_value,
#              expected_value, deviation_pct, hvac_root_cause,
#              message, is_resolved
# 迁移历史：002_create_anomaly_events.sql（基础表）
#            010_upgrade_anomaly_events.sql（新增 expected_value/deviation_pct/hvac_root_cause）
# ---------------------------------------------------------------------------

class AnomalyEvent(Base):
    """
    异常事件记录表（业务闭环层）。
    v2：事件由 notebook 检测链路从 kpi_anomaly_flags 汇总写入；
        旧版 anomaly_detector 后台扫描器保留为 legacy fallback。

    rule_triggered 取值：
      water_leak / electricity_overload / hvac_overconsumption（旧）
      flag_water / flag_electricity / flag_hvac_energy /
      flag_supply_deviation / flag_return_deviation（notebook v2）

    event_source：notebook / legacy_scanner / realtime_fallback
    anomaly_phase：ramp / full（notebook 阶段标签）
    """
    __tablename__ = "anomaly_events"

    id: str = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    detected_at = Column(
        TIMESTAMP(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    data_timestamp = Column(TIMESTAMP(timezone=True), nullable=False)
    building_id: str = Column(
        String,
        ForeignKey("buildings.building_id", ondelete="CASCADE"),
        nullable=False,
    )
    meter_device_id: str = Column(String, nullable=False)
    rule_triggered: str = Column(String, nullable=False)
    actual_value: float = Column(Float, nullable=True)
    threshold_value: float = Column(Float, nullable=True)
    expected_value: float = Column(Float, nullable=True)
    deviation_pct: float = Column(Float, nullable=True)
    hvac_root_cause: str = Column(String, nullable=True)
    message: str = Column(String, nullable=True)
    is_resolved: bool = Column(Boolean, nullable=False, default=False)
    # notebook v2 新增字段（迁移 013）
    anomaly_phase: str = Column(String, nullable=True)
    symptom_flags_json: str = Column(Text, nullable=True)
    event_source: str = Column(String, nullable=True, default="notebook")
    severity: str = Column(String, nullable=True, default="warning")

    __table_args__ = (
        UniqueConstraint(
            "data_timestamp", "building_id", "rule_triggered",
            name="uq_anomaly_event",
        ),
        Index("idx_anomaly_events_data_timestamp", "data_timestamp"),
        Index("idx_anomaly_events_building_ts", "building_id", "data_timestamp"),
        Index(
            "idx_anomaly_events_unresolved",
            "data_timestamp",
            postgresql_where=Column("is_resolved") == False,  # noqa: E712
        ),
    )


# ---------------------------------------------------------------------------
# kpi_expected_hourly — notebook 基线期望值表（迁移 013）
# ---------------------------------------------------------------------------

class KpiExpectedHourly(Base):
    """
    每楼每小时的 notebook 仿真基线期望值。
    主键：(building_id, timestamp)，与 energy_data 完全对齐。
    """
    __tablename__ = "kpi_expected_hourly"

    timestamp = Column(TIMESTAMP(timezone=True), primary_key=True, nullable=False)
    building_id: str = Column(
        String,
        ForeignKey("buildings.building_id", ondelete="CASCADE"),
        primary_key=True,
        nullable=False,
    )
    building_usage: str = Column(String, nullable=True)
    schedule_factor: float = Column(Float, nullable=True)
    hvac_mode: str = Column(String, nullable=True)
    source_version: str = Column(String, nullable=False, default="notebook_v1")

    water_m3_expected: float = Column(Float, nullable=True)
    electricity_kwh_expected: float = Column(Float, nullable=True)
    hac_energy_expected: float = Column(Float, nullable=True)
    sim_supply_temp_c_expected: float = Column(Float, nullable=True)
    sim_return_temp_c_expected: float = Column(Float, nullable=True)
    humidity_rh_pct_expected: float = Column(Float, nullable=True)

    __table_args__ = (
        Index("idx_kpi_expected_ts", "timestamp"),
        Index("idx_kpi_expected_building_ts", "building_id", "timestamp"),
    )


# ---------------------------------------------------------------------------
# kpi_anomaly_flags — notebook 检测细粒度 flags 表（迁移 013）
# ---------------------------------------------------------------------------

class KpiAnomalyFlag(Base):
    """每楼每小时的 notebook 症状检测结果。"""
    __tablename__ = "kpi_anomaly_flags"

    timestamp = Column(TIMESTAMP(timezone=True), primary_key=True, nullable=False)
    building_id: str = Column(
        String,
        ForeignKey("buildings.building_id", ondelete="CASCADE"),
        primary_key=True,
        nullable=False,
    )
    flag_water: bool = Column(Boolean, nullable=False, default=False)
    flag_electricity: bool = Column(Boolean, nullable=False, default=False)
    flag_hvac_energy: bool = Column(Boolean, nullable=False, default=False)
    flag_supply_deviation: bool = Column(Boolean, nullable=False, default=False)
    flag_return_deviation: bool = Column(Boolean, nullable=False, default=False)
    flag_symptom_soft_any: bool = Column(Boolean, nullable=False, default=False)
    flag_symptom_union_any: bool = Column(Boolean, nullable=False, default=False)

    anomaly_phase: str = Column(String, nullable=True)
    hvac_diagnosis: str = Column(String, nullable=True)
    detection_mode: str = Column(String, nullable=False, default="union")
    source_version: str = Column(String, nullable=False, default="notebook_v1")
    evidence_json: str = Column(Text, nullable=True)

    __table_args__ = (
        Index("idx_kpi_flags_ts", "timestamp"),
        Index("idx_kpi_flags_building_ts", "building_id", "timestamp"),
    )


# ---------------------------------------------------------------------------
# device_telemetry_hourly — 设备级小时遥测（迁移 013）
# ---------------------------------------------------------------------------

class DeviceTelemetryHourly(Base):
    """设备历史状态事实表，支持运行状态查询与趋势分析。"""
    __tablename__ = "device_telemetry_hourly"

    device_id: str = Column(
        String,
        ForeignKey("devices.device_id", ondelete="CASCADE"),
        primary_key=True,
        nullable=False,
    )
    timestamp = Column(TIMESTAMP(timezone=True), primary_key=True, nullable=False)
    building_id: str = Column(
        String,
        ForeignKey("buildings.building_id", ondelete="CASCADE"),
        nullable=False,
    )
    device_type: str = Column(String, nullable=False)

    online_status: str = Column(String, nullable=True)
    running_state: str = Column(String, nullable=True)
    health_status: str = Column(String, nullable=True)

    power_kw: float = Column(Float, nullable=True)
    flow_rate: float = Column(Float, nullable=True)
    valve_open_pct: float = Column(Float, nullable=True)
    frequency_hz: float = Column(Float, nullable=True)
    supply_temp_c: float = Column(Float, nullable=True)
    return_temp_c: float = Column(Float, nullable=True)
    ambient_temp_c: float = Column(Float, nullable=True)
    metric_payload_json: str = Column(Text, nullable=True)
    source: str = Column(String, nullable=True)

    __table_args__ = (
        Index("idx_device_telemetry_building_ts", "building_id", "timestamp"),
        Index("idx_device_telemetry_device_ts", "device_id", "timestamp"),
    )


# ---------------------------------------------------------------------------
# device_status_latest — 设备当前状态快照（迁移 013）
# ---------------------------------------------------------------------------

class DeviceStatusLatest(Base):
    """设备最新状态快照，前端设备列表页优先查此表。"""
    __tablename__ = "device_status_latest"

    device_id: str = Column(
        String,
        ForeignKey("devices.device_id", ondelete="CASCADE"),
        primary_key=True,
    )
    building_id: str = Column(
        String,
        ForeignKey("buildings.building_id", ondelete="CASCADE"),
        nullable=False,
    )
    device_type: str = Column(String, nullable=False)

    last_seen_at = Column(TIMESTAMP(timezone=True), nullable=True)
    online_status: str = Column(String, nullable=True)
    running_state: str = Column(String, nullable=True)
    health_status: str = Column(String, nullable=True)

    latest_power_kw: float = Column(Float, nullable=True)
    latest_flow_rate: float = Column(Float, nullable=True)
    latest_supply_temp_c: float = Column(Float, nullable=True)
    latest_return_temp_c: float = Column(Float, nullable=True)
    latest_payload_json: str = Column(Text, nullable=True)

    __table_args__ = (
        Index("idx_device_status_building", "building_id"),
        Index("idx_device_status_type", "device_type"),
    )


# ---------------------------------------------------------------------------
# anomaly_device_attributions — 楼级异常归因到设备（迁移 013）
# ---------------------------------------------------------------------------

class AnomalyDeviceAttribution(Base):
    """一条楼级异常事件可对应多条设备归因。"""
    __tablename__ = "anomaly_device_attributions"

    id: str = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    building_id: str = Column(
        String,
        ForeignKey("buildings.building_id", ondelete="CASCADE"),
        nullable=False,
    )
    timestamp = Column(TIMESTAMP(timezone=True), nullable=False)
    event_id: str = Column(String, nullable=True)  # 软关联 anomaly_events.id
    device_id: str = Column(
        String,
        ForeignKey("devices.device_id", ondelete="CASCADE"),
        nullable=False,
    )
    device_type: str = Column(String, nullable=False)

    attribution_role: str = Column(String, nullable=True)   # primary / secondary / supporting
    attribution_score: float = Column(Float, nullable=True)
    attribution_reason: str = Column(String, nullable=True)
    evidence_json: str = Column(Text, nullable=True)

    __table_args__ = (
        Index("idx_attr_building_ts", "building_id", "timestamp"),
        Index("idx_attr_device_ts", "device_id", "timestamp"),
        Index("idx_attr_event", "event_id"),
    )


# ---------------------------------------------------------------------------
# users — 系统用户（登录注册）
# ---------------------------------------------------------------------------

class User(Base):
    """
    系统用户表。
    密码以 bcrypt 哈希形式存储，原始密码从不持久化。
    role 取值：resident（住户）/ ops（运维人员）/ manager（运维经理）/ admin（系统管理员）
    """
    __tablename__ = "users"

    id: str = Column(
        String, primary_key=True, default=lambda: str(uuid.uuid4())
    )
    username: str = Column(String(50), unique=True, nullable=False, index=True)
    hashed_password: str = Column(String, nullable=False)
    email: str = Column(String(254), unique=True, nullable=True)
    phone: str = Column(String(20), nullable=True)
    role: str = Column(String(20), nullable=False, default="resident")
    is_active: bool = Column(Boolean, nullable=False, default=True)
    created_at = Column(
        TIMESTAMP(timezone=True), server_default=func.now(), nullable=False
    )

    refresh_tokens = relationship(
        "RefreshToken", back_populates="user", cascade="all, delete-orphan"
    )


# ---------------------------------------------------------------------------
# refresh_tokens — Refresh Token 存储（支持主动吊销）
# ---------------------------------------------------------------------------

class RefreshToken(Base):
    """
    Refresh Token 持久化表。
    存储 JWT 中的 jti（JWT ID），用于校验和吊销，不存储原始 token 字符串。
    每次 /auth/refresh 调用都执行 token rotation：旧 token 标记 revoked，
    同时颁发新的 access token + refresh token。
    """
    __tablename__ = "refresh_tokens"

    id: str = Column(
        String, primary_key=True, default=lambda: str(uuid.uuid4())
    )
    jti: str = Column(String, unique=True, nullable=False, index=True)
    user_id: str = Column(
        String, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    expires_at = Column(TIMESTAMP(timezone=True), nullable=False)
    created_at = Column(
        TIMESTAMP(timezone=True), server_default=func.now(), nullable=False
    )
    revoked: bool = Column(Boolean, nullable=False, default=False)

    user = relationship("User", back_populates="refresh_tokens")

    __table_args__ = (
        Index("idx_refresh_tokens_user_id", "user_id"),
    )


# ---------------------------------------------------------------------------
# dataset_files — 数据中心上传的 CSV/Excel 数据集（数据分析模块）
# ---------------------------------------------------------------------------

class DatasetFile(Base):
    """
    用户上传的结构化数据文件（CSV / Excel）。
    解析后的统计信息以 JSON 字符串形式存储在 columns_json / stats_json 中，
    原始文件保存在 file_path 指向的本地磁盘路径。
    """
    __tablename__ = "dataset_files"

    id: str = Column(
        String, primary_key=True, default=lambda: str(uuid.uuid4())
    )
    original_name: str = Column(String, nullable=False)
    file_path: str = Column(String, nullable=False)
    file_type: str = Column(String(10), nullable=False)   # csv / xlsx / xls
    row_count: int = Column(Integer, nullable=True)
    column_count: int = Column(Integer, nullable=True)
    columns_json: str = Column(Text, nullable=True)        # JSON: [{name, dtype, null_count}]
    stats_json: str = Column(Text, nullable=True)          # JSON: {col: {min,max,mean,std}}
    uploaded_at = Column(
        TIMESTAMP(timezone=True), server_default=func.now(), nullable=False
    )
    uploader_id: str = Column(
        String, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    __table_args__ = (
        Index("idx_dataset_files_uploader", "uploader_id"),
        Index("idx_dataset_files_uploaded_at", "uploaded_at"),
    )


# ---------------------------------------------------------------------------
# predicted_anomaly_events — ML 模型预测的未来异常预警（迁移 014）
# ---------------------------------------------------------------------------

class PredictedAnomalyEvent(Base):
    """
    ML 模型预测的未来 6h/12h KPI 异常预警。
    与已发生异常 anomaly_events 分离存储，支持事后命中率评估。
    """
    __tablename__ = "predicted_anomaly_events"

    id: str = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    created_at = Column(TIMESTAMP(timezone=True), nullable=False, server_default=func.now())

    as_of_timestamp = Column(TIMESTAMP(timezone=True), nullable=False)
    forecast_for_timestamp = Column(TIMESTAMP(timezone=True), nullable=False)
    horizon_h: int = Column(Integer, nullable=False)

    building_id: str = Column(
        String,
        ForeignKey("buildings.building_id", ondelete="CASCADE"),
        nullable=False,
    )

    metric_name: str = Column(String, nullable=False)
    predicted_value: float = Column(Float, nullable=False)
    expected_value: float = Column(Float, nullable=True)
    deviation_pct: float = Column(Float, nullable=True)

    risk_level: str = Column(String, nullable=False, default="normal")
    rule_triggered: str = Column(String, nullable=True)

    model_name: str = Column(String, nullable=False)
    is_confirmed: bool = Column(Boolean, nullable=True)

    __table_args__ = (
        Index("idx_predicted_anomaly_building_ts", "building_id", "as_of_timestamp"),
    )
