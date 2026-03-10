"""
SQLAlchemy ORM 表定义（只读映射，与数据库 DDL 严格对齐）。
Data Agent 数据库账号仅拥有 SELECT 权限，无 INSERT/UPDATE/DELETE。
"""
import enum

from sqlalchemy import (
    Column,
    Enum,
    Float,
    Index,
    String,
    Text,
)
from sqlalchemy import TIMESTAMP
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


# ---------------------------------------------------------------------------
# 枚举类型（与 DB 中 operation_status_enum 一致）
# ---------------------------------------------------------------------------

class OperationStatusEnum(str, enum.Enum):
    Normal = "Normal"
    Anomaly = "Anomaly"


# ---------------------------------------------------------------------------
# buildings — 资产身份证（关系型，静态元数据）
# ---------------------------------------------------------------------------

class Building(Base):
    """
    建筑物静态信息表。
    Data Agent 通过 building_id 或 meter_device_id 做关联查询。
    """
    __tablename__ = "buildings"

    building_id: str = Column(String, primary_key=True)
    building_type: str = Column(String)
    meter_device_id: str = Column(String, unique=True, nullable=False)
    sqm: float = Column(Float)

    __table_args__ = (
        Index("idx_buildings_type", "building_type"),
    )


# ---------------------------------------------------------------------------
# energy_data — 核心数据日志（时序风格，无外键）
# ---------------------------------------------------------------------------

class EnergyData(Base):
    """
    能耗时序记录表。
    复合主键 (building_id, timestamp) 与 DB 实际索引对齐。
    hvac 字段：
      hvac_energy_kwh      → 空调系统总能耗
      hvac_supply_temp_c   → 供水温度（冷冻水送水端）
      hvac_return_temp_c   → 回水温度（冷冻水回水端）
    """
    __tablename__ = "energy_data"

    timestamp = Column(TIMESTAMP(timezone=True), primary_key=True, nullable=False)
    building_id: str = Column(String, primary_key=True, nullable=False)

    electricity_kwh: float = Column(Float)
    water_m3: float = Column(Float)
    hvac_energy_kwh: float = Column(Float)
    hvac_supply_temp_c: float = Column(Float)
    hvac_return_temp_c: float = Column(Float)
    ambient_temp_c: float = Column(Float)
    humidity_rh_pct: float = Column(Float)
    occupancy_density_per_100sqm: float = Column(Float)
    operation_status = Column(
        Enum(OperationStatusEnum, name="operation_status_enum"),
    )

    __table_args__ = (
        Index(
            "idx_energy_data_building_timestamp",
            "building_id",
            timestamp.desc(),
        ),
    )


# ---------------------------------------------------------------------------
# daily_energy_summary — 物化视图（只读映射，不做 DDL 管理）
# ---------------------------------------------------------------------------

class DailyEnergySummary(Base):
    """
    物化视图 daily_energy_summary 的 ORM 映射。
    字段与视图 DDL 严格一一对应：
      SELECT date_trunc('day', timestamp) AS day, building_id,
             SUM(electricity_kwh)              AS total_electricity_kwh,
             AVG(ambient_temp_c)               AS avg_ambient_temp,
             MAX(occupancy_density_per_100sqm) AS max_occupancy
      FROM energy_data GROUP BY day, building_id;
    """
    __tablename__ = "daily_energy_summary"

    day = Column(TIMESTAMP(timezone=True), primary_key=True, nullable=False)
    building_id: str = Column(String, primary_key=True, nullable=False)
    total_electricity_kwh: float = Column(Float)
    avg_ambient_temp: float = Column(Float)
    max_occupancy: float = Column(Float)

    __table_args__ = (
        Index(
            "idx_daily_summary_day_building",
            "day",
            "building_id",
            unique=True,
        ),
        {"info": {"is_view": True}},  # 标记为视图，防止 alembic 生成 CREATE TABLE
    )
