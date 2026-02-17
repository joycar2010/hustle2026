from pydantic import BaseModel
from datetime import datetime
from typing import Optional
from uuid import UUID

class OrderRecordBase(BaseModel):
    symbol: str
    order_side: str
    order_type: str
    price: float
    qty: float
    filled_qty: float = 0
    status: str
    platform_order_id: Optional[str] = None

class OrderRecordCreate(OrderRecordBase):
    account_id: UUID

class OrderRecordResponse(OrderRecordBase):
    order_id: UUID
    account_id: UUID
    create_time: datetime
    update_time: datetime

    class Config:
        from_attributes = True
