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


@router.get("/balance")
async def get_master_balance(db: Session = Depends(get_db)):
    """Master account wallet balances — same shape as sub-account balance."""
    account = db.query(MasterAccount).first()
    if not account:
        raise HTTPException(status_code=404, detail="Master account not configured")

    import asyncio
    from engine.trading.binance_trading import BinanceTradingClient
    async with BinanceTradingClient(account.api_key, account.api_secret) as client:
        spot, margin, futures, funding, earn = await asyncio.gather(
            client.get_spot_account(),
            client.get_margin_account(),
            client.get_futures_account(),
            client.get_funding_account(),
            client.get_simple_earn_account(),
        )

    spot_free, spot_locked = "0", "0"
    for a in spot.get("balances", []):
        if a["asset"] == "USDT":
            spot_free = a.get("free", "0")
            spot_locked = a.get("locked", "0")
            break

    funding_usdt = "0"
    for a in (funding if isinstance(funding, list) else []):
        if a.get("asset") == "USDT":
            funding_usdt = a.get("free", "0")
            break

    earn_total = earn.get("totalAmountInUSDT", "0") if isinstance(earn, dict) else "0"

    margin_free, margin_borrowed = "0", "0"
    for a in margin.get("userAssets", []):
        if a["asset"] == "USDT":
            margin_free = a.get("free", "0")
            margin_borrowed = a.get("borrowed", "0")
            break

    return {
        "spot_usdt_free": spot_free,
        "spot_usdt_locked": spot_locked,
        "funding_usdt": funding_usdt,
        "earn_total": earn_total,
        "margin_level": margin.get("marginLevel", "0"),
        "margin_usdt_free": margin_free,
        "margin_usdt_borrowed": margin_borrowed,
        "futures_total_balance": futures.get("totalWalletBalance", "0"),
        "futures_available": futures.get("availableBalance", "0"),
        "futures_unrealized_pnl": futures.get("totalUnrealizedProfit", "0"),
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
