from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.db.models import MasterAccount
from app.db.schemas.master_account import MasterAccountCreate, MasterAccountResponse
from app.db.schemas.sub_account import SubAccountValidation
from app.db.schemas.common import MessageResponse
from app.db.session import get_db
from app.middleware.permissions import get_current_user_id
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
        "api_key": _mask_secret(account.api_key),
        "api_secret_masked": _mask_secret(account.api_secret),
        "is_verified": account.is_verified,
        "created_at": account.created_at,
    }


@router.get("/", response_model=MasterAccountResponse)
def get_master_account(request: Request, db: Session = Depends(get_db)):
    uid = get_current_user_id(request)
    account = db.query(MasterAccount).filter(MasterAccount.user_id == uid).first()
    if not account:
        raise HTTPException(status_code=404, detail="Master account not configured")
    return _to_response(account)


@router.post("/", response_model=MasterAccountResponse, status_code=201)
def upsert_master_account(data: MasterAccountCreate, request: Request, db: Session = Depends(get_db)):
    uid = get_current_user_id(request)
    account = db.query(MasterAccount).filter(MasterAccount.user_id == uid).first()
    if account:
        if data.account_name is not None:
            account.account_name = data.account_name
        account.api_key = data.api_key
        account.api_secret = data.api_secret
        account.is_verified = False
    else:
        account = MasterAccount(
            user_id=uid,
            account_name=data.account_name,
            api_key=data.api_key,
            api_secret=data.api_secret,
        )
        db.add(account)
    db.commit()
    db.refresh(account)
    return _to_response(account)


@router.post("/validate", response_model=SubAccountValidation)
async def validate_master_account(request: Request, db: Session = Depends(get_db)):
    uid = get_current_user_id(request)
    account = db.query(MasterAccount).filter(MasterAccount.user_id == uid).first()
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
async def get_master_balance(request: Request, db: Session = Depends(get_db)):
    """Master account wallet balances — same shape as sub-account balance."""
    uid = get_current_user_id(request)
    account = db.query(MasterAccount).filter(MasterAccount.user_id == uid).first()
    if not account:
        raise HTTPException(status_code=404, detail="Master account not configured")

    if not account.api_key or not account.api_secret:
        raise HTTPException(status_code=400, detail="主账户 API 密钥未配置")

    import asyncio
    from engine.trading.binance_trading import BinanceTradingClient
    try:
        async with BinanceTradingClient(account.api_key, account.api_secret) as client:
            spot, margin, futures, funding, earn = await asyncio.gather(
                client.get_spot_account(),
                client.get_margin_account(),
                client.get_futures_account(),
                client.get_funding_account(),
                client.get_simple_earn_account(),
            )
    except Exception as e:
        # 之前无 try/except,任一子调用失败会直接抛未处理异常 → 500 ExceptionGroup
        msg = str(e)
        hint = "(若提示 API-key/IP/permissions,请检查密钥IP白名单是否含服务器出口IP)" if "-2015" in msg or "IP" in msg else ""
        raise HTTPException(status_code=502, detail=f"主账户余额查询失败: {msg[:100]}{hint}")

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
async def get_master_permissions(request: Request, db: Session = Depends(get_db)):
    uid = get_current_user_id(request)
    account = db.query(MasterAccount).filter(MasterAccount.user_id == uid).first()
    if not account:
        raise HTTPException(status_code=404, detail="Master account not configured")
    if not account.api_key or not account.api_secret:
        raise HTTPException(status_code=400, detail="主账户 API 密钥未配置")
    # 瞬时失败(币安抖动/出口IP偶发不在白名单)重试一次,仍失败给可操作的提示而非裸 msg
    last_err = ""
    for attempt in range(2):
        try:
            return await binance_client.get_api_restrictions(account.api_key, account.api_secret)
        except Exception as e:
            last_err = str(e)
    raise HTTPException(
        status_code=502,
        detail=f"主账户权限查询失败({last_err[:80]});若持续失败请点「验证」重试,并确认密钥 IP 白名单已含服务器出口 IP",
    )
