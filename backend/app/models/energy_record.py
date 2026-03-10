"""
能耗记录数据模型
"""
from sqlalchemy import Column, Integer, Float, DateTime, ForeignKey
from app.db.session import Base

class EnergyRecord(Base):
    __tablename__ = "energy_records"
    
    id = Column(Integer, primary_key=True, index=True)
    building_id = Column(Integer, ForeignKey("buildings.id"))
    timestamp = Column(DateTime, nullable=False)
    energy_consumption = Column(Float)  # 能耗值
    temperature = Column(Float)  # 温度
    humidity = Column(Float)  # 湿度
