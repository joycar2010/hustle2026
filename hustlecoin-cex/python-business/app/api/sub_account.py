from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.db.models import SubAccount
from app.db.schemas.sub_account import (
    SubAccountCreate, SubAccountUpdate, SubAccountKeyUpdate,
    SubAccountResponse, SubAccountValidation,
)
from app.db.schemas.common import MessageResponse
from app.db.session import get_db
from app.services import binance_client

router = APIRouter(prefix="/api/sub-accounts", tags=["sub-accounts"])


def _mask_secret(secret: str) -> str:
    if len(secret) <= 4:
        return "****"
    return "****" + secret[-4:]


def _to_response(account: SubAccount) -> dict:
    return {
        "id": account.id,
        "note": account.note,
        "email": account.email,
        "api_key": account.api_key,
        "api_secret_masked": _mask_secret(account.api_secret),
        "is_enabled": account.is_enabled,
        "margin_enabled": account.margin_enabled,
        "futures_enabled": account.futures_enabled,
        "spot_enabled": account.spot_enabled,
        "bnb_burn_enabled": account.bnb_burn_enabled,
        "bnb_interest_enabled": account.bnb_interest_enabled,
        "proxy_url": account.proxy_url,
        "last_validated_at": account.last_validated_at,
        "created_at": account.created_at,
        "updated_at": account.updated_at,
    }


@router.get("/", response_model=list[SubAccountResponse])
def list_sub_accounts(
    enabled_only: bool = Query(False),
    db: Session = Depends(get_db),
):
    q = db.query(SubAccount)
    if enabled_only:
        q = q.filter(SubAccount.is_enabled == True)
    accounts = q.order_by(SubAccount.id).all()
    return [_to_response(a) for a in accounts]


@router.post("/", response_model=SubAccountResponse, status_code=201)
async def create_sub_account(
    data: SubAccountCreate,
    validate: bool = Query(False),
    db: Session = Depends(get_db),
):
    account = SubAccount(
        note=data.note,
        email=data.email,
        api_key=data.api_key,
        api_secret=data.api_secret,
        margin_enabled=data.margin_enabled,
        futures_enabled=data.futures_enabled,
        spot_enabled=data.spot_enabled,
        bnb_burn_enabled=data.bnb_burn_enabled,
        bnb_interest_enabled=data.bnb_interest_enabled,
        proxy_url=data.proxy_url,
    )

    if validate:
        result = await binance_client.validate_api_key(data.api_key, data.api_secret, proxy_url=data.proxy_url)
        if not result.is_valid:
            raise HTTPException(status_code=400, detail=f"API key validation failed: {result.error}")
        account.last_validated_at = datetime.now(timezone.utc)

    db.add(account)
    db.commit()
    db.refresh(account)
    return _to_response(account)


@router.get("/{account_id}", response_model=SubAccountResponse)
def get_sub_account(account_id: int, db: Session = Depends(get_db)):
    account = db.query(SubAccount).get(account_id)
    if not account:
        raise HTTPException(status_code=404, detail="Sub-account not found")
    return _to_response(account)


@router.put("/{account_id}", response_model=SubAccountResponse)
def update_sub_account(account_id: int, data: SubAccountUpdate, db: Session = Depends(get_db)):
    account = db.query(SubAccount).get(account_id)
    if not account:
        raise HTTPException(status_code=404, detail="Sub-account not found")
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(account, field, value)
    db.commit()
    db.refresh(account)
    return _to_response(account)


@router.delete("/{account_id}", response_model=MessageResponse)
def delete_sub_account(
    account_id: int,
    hard: bool = Query(False),
    db: Session = Depends(get_db),
):
    account = db.query(SubAccount).get(account_id)
    if not account:
        raise HTTPException(status_code=404, detail="Sub-account not found")
    if hard:
        db.delete(account)
    else:
        account.is_enabled = False
    db.commit()
    action = "deleted" if hard else "disabled"
    return {"message": f"Sub-account {account.note} {action}"}


@router.put("/{account_id}/keys", response_model=SubAccountResponse)
async def update_keys(
    account_id: int,
    data: SubAccountKeyUpdate,
    validate: bool = Query(False),
    db: Session = Depends(get_db),
):
    account = db.query(SubAccount).get(account_id)
    if not account:
        raise HTTPException(status_code=404, detail="Sub-account not found")

    if validate:
        result = await binance_client.validate_api_key(data.api_key, data.api_secret, proxy_url=account.proxy_url)
        if not result.is_valid:
            raise HTTPException(status_code=400, detail=f"API key validation failed: {result.error}")
        account.last_validated_at = datetime.now(timezone.utc)

    account.api_key = data.api_key
    account.api_secret = data.api_secret
    db.commit()
    db.refresh(account)
    return _to_response(account)


@router.post("/{account_id}/validate", response_model=SubAccountValidation)
async def validate_sub_account(account_id: int, db: Session = Depends(get_db)):
    account = db.query(SubAccount).get(account_id)
    if not account:
        raise HTTPException(status_code=404, detail="Sub-account not found")

    result = await binance_client.validate_api_key(account.api_key, account.api_secret, proxy_url=account.proxy_url)
    if result.is_valid:
        account.last_validated_at = datetime.now(timezone.utc)
        db.commit()

    return {
        "is_valid": result.is_valid,
        "can_trade": result.can_trade,
        "can_withdraw": result.can_withdraw,
        "permissions": result.permissions or [],
        "error": result.error,
    }


@router.post("/{account_id}/toggle", response_model=SubAccountResponse)
def toggle_sub_account(account_id: int, db: Session = Depends(get_db)):
    account = db.query(SubAccount).get(account_id)
    if not account:
        raise HTTPException(status_code=404, detail="Sub-account not found")
    account.is_enabled = not account.is_enabled
    db.commit()
    db.refresh(account)
    return _to_response(account)
