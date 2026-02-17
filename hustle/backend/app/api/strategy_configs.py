from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List
from ..core.database import get_db
from ..models import StrategyConfig
from ..schemas import StrategyConfigCreate, StrategyConfigUpdate, StrategyConfigResponse

router = APIRouter()

@router.post("/", response_model=StrategyConfigResponse)
def create_strategy_config(config_in: StrategyConfigCreate, db: Session = Depends(get_db)):
    config = StrategyConfig(
        user_id="00000000-0000-0000-0000-000000000000",  # 暂时使用固定用户ID
        strategy_type=config_in.strategy_type,
        target_spread=config_in.target_spread,
        order_qty=config_in.order_qty,
        retry_times=config_in.retry_times,
        mt5_stuck_threshold=config_in.mt5_stuck_threshold,
        is_enabled=config_in.is_enabled
    )
    db.add(config)
    db.commit()
    db.refresh(config)
    return config

@router.get("/", response_model=List[StrategyConfigResponse])
def get_strategy_configs(db: Session = Depends(get_db)):
    configs = db.query(StrategyConfig).all()
    return configs

@router.get("/{config_id}", response_model=StrategyConfigResponse)
def get_strategy_config(config_id: str, db: Session = Depends(get_db)):
    config = db.query(StrategyConfig).filter(StrategyConfig.config_id == config_id).first()
    if not config:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="策略配置不存在"
        )
    return config

@router.put("/{config_id}", response_model=StrategyConfigResponse)
def update_strategy_config(config_id: str, config_in: StrategyConfigUpdate, db: Session = Depends(get_db)):
    config = db.query(StrategyConfig).filter(StrategyConfig.config_id == config_id).first()
    if not config:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="策略配置不存在"
        )
    
    update_data = config_in.dict(exclude_unset=True)
    for field, value in update_data.items():
        setattr(config, field, value)
    
    db.commit()
    db.refresh(config)
    return config

@router.delete("/{config_id}")
def delete_strategy_config(config_id: str, db: Session = Depends(get_db)):
    config = db.query(StrategyConfig).filter(StrategyConfig.config_id == config_id).first()
    if not config:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="策略配置不存在"
        )
    db.delete(config)
    db.commit()
    return {"message": "策略配置删除成功"}
