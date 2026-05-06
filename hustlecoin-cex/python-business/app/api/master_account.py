from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db.models import MasterAccount
from app.db.schemas.master_account import MasterAccountCreate, MasterAccountResponse
from app.db.schemas.sub_account import SubAccountValidation
from app.db.schemas.common import MessageResponse
from app.db.session import get_db
from app.services import binance_client

router = APIRouter(prefix="/api/master-account", tags=["master-account"])


def _mask_secret(secret: str) -> str:
    if len(secret) <= 4:
        return "****"
    return "****" + secret[-4:]


def _to_response(account: MasterAccount) -> dict:
    return {
        "id": account.id,
        "account_name": account.account_name,
        "api_key": account.api_key,
        "api_secret_masked": _mask_secret(account.api_secret),
        "is_verified": account.is_verified,
        "created_at": account.created_at,
    }


@router.get("/", response_model=MasterAccountResponse)
def get_master_account(db: Session = Depends(get_db)):
    account = db.query(MasterAccount).first()
    if not account:
        raise HTTPException(status_code=404, detail="Master account not configured")
    return _to_response(account)


@router.post("/", response_model=MasterAccountResponse, status_code=201)
def upsert_master_account(data: MasterAccountCreate, db: Session = Depends(get_db)):
    account = db.query(MasterAccount).first()
    if account:
        if data.account_name is not None:
            account.account_name = data.account_name
        account.api_key = data.api_key
        account.api_secret = data.api_secret
        account.is_verified = False
    else:
        account = MasterAccount(
            account_name=data.account_name,
            api_key=data.api_key,
            api_secret=data.api_secret,
        )
        db.add(account)
    db.commit()
    db.refresh(account)
    return _to_response(account)


@router.post("/validate", response_model=SubAccountValidation)
async def validate_master_account(db: Session = Depends(get_db)):
    account = db.query(MasterAccount).first()
    if not account:
        raise HTTPException(status_code=404, detail="Master account not configured")

    result = await binance_client.validate_api_key(account.api_key, account.api_secret)
    if result.is_valid:
        account.is_verified = True
        db.commit()

    return {
        "is_valid": result.is_valid,
        "can_trade": result.can_trade,
        "can_withdraw": result.can_withdraw,
        "permissions": result.permissions or [],
        "error": result.error,
    }


@router.get("/permissions")
async def get_master_permissions(db: Session = Depends(get_db)):
    account = db.query(MasterAccount).first()
    if not account:
        raise HTTPException(status_code=404, detail="Master account not configured")
    try:
        data = await binance_client.get_api_restrictions(account.api_key, account.api_secret)
        return data
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Binance API 错误: {str(e)[:100]}")
