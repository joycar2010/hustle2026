from pydantic import BaseModel
from datetime import datetime
from typing import Optional
from uuid import UUID

class RiskAlertBase(BaseModel):
    alert_level: str
    alert_message: str
    expire_time: Optional[datetime] = None

class RiskAlertResponse(RiskAlertBase):
    alert_id: UUID
    user_id: UUID
    create_time: datetime

    class Config:
        from_attributes = True
