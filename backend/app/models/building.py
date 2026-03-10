"""
建筑数据模型
"""
from sqlalchemy import Column, Integer, String, Float, DateTime
from app.db.session import Base

class Building(Base):
    __tablename__ = "buildings"
    
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    address = Column(String)
    area = Column(Float)  # 建筑面积
    created_at = Column(DateTime)
