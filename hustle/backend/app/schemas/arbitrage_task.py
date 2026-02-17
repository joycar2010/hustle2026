from pydantic import BaseModel
from datetime import datetime
from typing import Optional
from uuid import UUID

class ArbitrageTaskBase(BaseModel):
    strategy_type: str
    open_spread: float
    close_spread: Optional[float] = None
    status: str
    open_time: datetime
    close_time: Optional[datetime] = None
    profit: Optional[float] = None

class ArbitrageTaskCreate(ArbitrageTaskBase):
    pass

class ArbitrageTaskResponse(ArbitrageTaskBase):
    task_id: UUID
    user_id: UUID

    class Config:
        from_attributes = True
