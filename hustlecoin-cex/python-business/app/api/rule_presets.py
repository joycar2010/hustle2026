import logging
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db.models import RulePreset, SymbolRule
from app.db.session import get_db
from app.middleware.permissions import get_current_user_id

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/rule-presets", tags=["rule-presets"])

PRESET_FIELDS = {
    "open_spread", "close_spread", "order_amount", "remove_spread",
    "close_funding_ratio", "repay_funding_ratio", "repay_spread",
    "max_daily_interest_rate", "max_borrow_amount",
}


class PresetCreate(BaseModel):
    name: str
    open_spread: float | None = None
    close_spread: float | None = None
    order_amount: float | None = None
    remove_spread: float | None = None
    close_funding_ratio: float | None = None
    repay_funding_ratio: float | None = None
    repay_spread: float | None = None
    max_daily_interest_rate: float | None = None
    max_borrow_amount: float | None = None


def _to_response(p: RulePreset) -> dict:
    return {
        "id": p.id,
        "name": p.name,
        "open_spread": str(p.open_spread) if p.open_spread is not None else None,
        "close_spread": str(p.close_spread) if p.close_spread is not None else None,
        "order_amount": str(p.order_amount) if p.order_amount is not None else None,
        "remove_spread": str(p.remove_spread) if p.remove_spread is not None else None,
        "close_funding_ratio": str(p.close_funding_ratio) if p.close_funding_ratio is not None else None,
        "repay_funding_ratio": str(p.repay_funding_ratio) if p.repay_funding_ratio is not None else None,
        "repay_spread": str(p.repay_spread) if p.repay_spread is not None else None,
        "max_daily_interest_rate": str(p.max_daily_interest_rate) if p.max_daily_interest_rate is not None else None,
        "max_borrow_amount": str(p.max_borrow_amount) if p.max_borrow_amount is not None else None,
        "created_at": p.created_at,
    }


@router.get("/")
def list_presets(request: Request, db: Session = Depends(get_db)):
    user_id = get_current_user_id(request)
    presets = db.query(RulePreset).filter(RulePreset.user_id == user_id).order_by(RulePreset.id).all()
    return [_to_response(p) for p in presets]


@router.post("/", status_code=201)
def create_preset(data: PresetCreate, request: Request, db: Session = Depends(get_db)):
    user_id = get_current_user_id(request)
    preset = RulePreset(user_id=user_id, name=data.name)
    for field in PRESET_FIELDS:
        value = getattr(data, field, None)
        if value is not None:
            setattr(preset, field, value)
    db.add(preset)
    db.commit()
    db.refresh(preset)
    return _to_response(preset)


@router.put("/{preset_id}")
def update_preset(preset_id: int, data: PresetCreate, request: Request, db: Session = Depends(get_db)):
    user_id = get_current_user_id(request)
    preset = db.query(RulePreset).filter(
        RulePreset.id == preset_id, RulePreset.user_id == user_id,
    ).first()
    if not preset:
        raise HTTPException(status_code=404, detail="Preset not found")
    preset.name = data.name
    for field in PRESET_FIELDS:
        value = getattr(data, field, None)
        setattr(preset, field, value)
    db.commit()
    db.refresh(preset)
    return _to_response(preset)


@router.delete("/{preset_id}")
def delete_preset(preset_id: int, request: Request, db: Session = Depends(get_db)):
    user_id = get_current_user_id(request)
    preset = db.query(RulePreset).filter(
        RulePreset.id == preset_id, RulePreset.user_id == user_id,
    ).first()
    if not preset:
        raise HTTPException(status_code=404, detail="Preset not found")
    db.delete(preset)
    db.commit()
    return {"message": f"Preset '{preset.name}' deleted"}


@router.post("/{preset_id}/apply/{symbol}")
def apply_preset(preset_id: int, symbol: str, request: Request, db: Session = Depends(get_db)):
    user_id = get_current_user_id(request)
    preset = db.query(RulePreset).filter(
        RulePreset.id == preset_id, RulePreset.user_id == user_id,
    ).first()
    if not preset:
        raise HTTPException(status_code=404, detail="Preset not found")

    sym = symbol.upper().strip()
    if sym and not sym.endswith("USDT"):   # 补全 USDT 后缀,杜绝裸键规则(与 symbol_rules._norm_symbol 同口径)
        sym += "USDT"
    rule = db.query(SymbolRule).filter(
        SymbolRule.user_id == user_id, SymbolRule.symbol == sym,
    ).first()
    if not rule:
        rule = SymbolRule(user_id=user_id, symbol=sym, source="preset")
        db.add(rule)

    for field in PRESET_FIELDS:
        value = getattr(preset, field, None)
        if value is not None:
            setattr(rule, field, value)
    rule.source = "preset"
    db.commit()
    return {"message": f"Preset '{preset.name}' applied to {sym}"}
