from datetime import datetime
from pydantic import BaseModel
from sqlalchemy import Column, Integer, String, DateTime
from sqlalchemy.sql import func

from database import Base

class Inventory(Base):
    __tablename__ = "inventory"
    
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    quantity = Column(Integer, nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    
    
class InventoryBase(BaseModel):
    name: str
    quantity: int
    
class InventoryCreate(InventoryBase):
    pass

class InventoryUpdate(BaseModel):
    quantity: int
    
class InventoryResponse(InventoryBase):
    id: int
    updated_at: datetime
    
    class Config:
        from_attributes = True