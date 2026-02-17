from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from typing import List
from ..core.database import get_db
from ..models import ArbitrageTask
from ..schemas import ArbitrageTaskCreate, ArbitrageTaskResponse

router = APIRouter()

@router.post("/", response_model=ArbitrageTaskResponse)
def create_arbitrage_task(task_in: ArbitrageTaskCreate, db: Session = Depends(get_db)):
    task = ArbitrageTask(
        user_id="00000000-0000-0000-0000-000000000000",  # 暂时使用固定用户ID
        strategy_type=task_in.strategy_type,
        open_spread=task_in.open_spread,
        close_spread=task_in.close_spread,
        status=task_in.status,
        open_time=task_in.open_time,
        close_time=task_in.close_time,
        profit=task_in.profit
    )
    db.add(task)
    db.commit()
    db.refresh(task)
    return task

@router.get("/", response_model=List[ArbitrageTaskResponse])
def get_arbitrage_tasks(db: Session = Depends(get_db)):
    tasks = db.query(ArbitrageTask).all()
    return tasks

@router.get("/{task_id}", response_model=ArbitrageTaskResponse)
def get_arbitrage_task(task_id: str, db: Session = Depends(get_db)):
    task = db.query(ArbitrageTask).filter(ArbitrageTask.task_id == task_id).first()
    return task
