from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from typing import List
from ..core.database import get_db
from ..models import RiskAlert
from ..schemas import RiskAlertResponse

router = APIRouter()

@router.get("/", response_model=List[RiskAlertResponse])
def get_risk_alerts(db: Session = Depends(get_db)):
    alerts = db.query(RiskAlert).all()
    return alerts

@router.get("/{alert_id}", response_model=RiskAlertResponse)
def get_risk_alert(alert_id: str, db: Session = Depends(get_db)):
    alert = db.query(RiskAlert).filter(RiskAlert.alert_id == alert_id).first()
    return alert
