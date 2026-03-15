"""
SQLAlchemy ORM 表定义（与数据库 DDL 严格对齐）。
energy_data / buildings / daily_energy_summary：Data Agent 只读账号（SELECT only）。
anomaly_events：后台检测服务拥有完整读写权限。

数据库四层架构：
  物理实体（buildings/devices） + 时序事实（energy_data） + 业务闭环（anomaly_events）
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
    primary_space_usage 对应原 building_type（'Education'/'Office'/'Public'）。
    timezone 用于将 UTC 时间戳转换为建筑所在地的本地时间（如按天/月聚合时需要）。
    """
    __tablename__ = "buildings"

    building_id: str = Column(String, primary_key=True)
    primary_space_usage: str = Column(String)
    sqm: float = Column(Float)
    timezone: str = Column(String, nullable=True, default="UTC")

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
# 实际 DDL 列：timestamp, building_id, electricity_kwh, water_m3,
#              hotwater_kwh, chilledwater_kwh,
#              sim_supply_temp_c, sim_return_temp_c,
#              air_temp_c, dew_temp_c, humidity_rh_pct, anomaly_status
# ---------------------------------------------------------------------------

class EnergyData(Base):
    """
    能耗时序记录表（写入最密集的"事实表"）。
    复合主键 (timestamp, building_id)。
    直接外键关联 buildings，避免经由 devices 表做深度 JOIN（时序架构优化）。
    冷热水字段：
      chilledwater_kwh  → 冷冻水（空调制冷）能耗
      hotwater_kwh      → 热水能耗
      sim_supply_temp_c → 模拟供水温度（冷冻水送水端）
      sim_return_temp_c → 模拟回水温度（冷冻水回水端）
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
    hotwater_kwh: float = Column(Float)
    chilledwater_kwh: float = Column(Float)
    sim_supply_temp_c: float = Column(Float)
    sim_return_temp_c: float = Column(Float)
    air_temp_c: float = Column(Float)
    dew_temp_c: float = Column(Float)
    humidity_rh_pct: float = Column(Float)
    anomaly_status: str = Column(String)

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
#              meter_device_id, rule_triggered, actual_value,
#              threshold_value, message, is_resolved
# ---------------------------------------------------------------------------

class AnomalyEvent(Base):
    """
    异常事件记录表（业务闭环层）。
    由 anomaly_detector 后台服务扫描 energy_data 后写入，是所有异常展示的唯一来源。

    设计要点：
    - UUID 主键 + 复合唯一约束 (data_timestamp, building_id, rule_triggered) 保证幂等性
    - 外键 CASCADE 保证删楼宇时自动清理相关告警
    - is_resolved 支持运维闭环工作台的处理状态追踪
    - meter_device_id 关联 devices 表，但使用软引用（STRING）避免强 FK 阻碍批量写入

    rule_triggered 取值：
      night_high_power    → 夜间（本地 0-6 点）electricity_kwh > 50
      high_chilled_water  → chilledwater_kwh 超当日均值 3 倍（HVAC 过耗）
      sensor_spike        → electricity_kwh 超当日均值 3 倍
      db_flagged          → energy_data.anomaly_status = 'Anomaly'（存量标注兜底）
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
    message: str = Column(String, nullable=True)
    is_resolved: bool = Column(Boolean, nullable=False, default=False)

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
# users — 系统用户（登录注册）
# ---------------------------------------------------------------------------

class User(Base):
    """
    系统用户表。
    密码以 bcrypt 哈希形式存储，原始密码从不持久化。
    """
    __tablename__ = "users"

    id: str = Column(
        String, primary_key=True, default=lambda: str(uuid.uuid4())
    )
    username: str = Column(String(50), unique=True, nullable=False, index=True)
    hashed_password: str = Column(String, nullable=False)
    email: str = Column(String(254), unique=True, nullable=True)
    phone: str = Column(String(20), nullable=True)
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
