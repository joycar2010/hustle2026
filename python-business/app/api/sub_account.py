from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session

from app.db.models import SubAccount
from app.db.schemas.sub_account import (
    SubAccountCreate, SubAccountUpdate, SubAccountKeyUpdate,
    SubAccountResponse, SubAccountValidation, IpWhitelistUpdate,
    SubAccountFundPatch, SubAccountClearRequest,
)
from app.db.schemas.common import MessageResponse
from app.db.models import MasterAccount
from app.db.session import get_db
from app.services import binance_client
from app.middleware.permissions import get_current_user_id, get_effective_user_id

router = APIRouter(prefix="/api/sub-accounts", tags=["sub-accounts"])


@router.post("/check-permissions")
async def check_permissions(data: SubAccountKeyUpdate):
    try:
        result = await binance_client.get_api_restrictions(data.api_key, data.api_secret)
        return result
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/server-ip")
async def get_server_ip():
    import httpx
    async with httpx.AsyncClient(timeout=5) as c:
        resp = await c.get("https://api.ipify.org?format=json")
        return resp.json()


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
        "order_amount": account.order_amount,
        "base_margin_amount": account.base_margin_amount,
        "single_transfer_amount": account.single_transfer_amount,
        "risk_threshold": account.risk_threshold,
        "min_balance": account.min_balance,
        "single_order_amount": account.single_order_amount,
        "max_positions": account.max_positions,
        "max_borrow_amount": account.max_borrow_amount,
        "last_validated_at": account.last_validated_at,
        "created_at": account.created_at,
        "updated_at": account.updated_at,
    }


def _get_account(db: Session, account_id: int, user_id: int) -> SubAccount:
    account = db.query(SubAccount).filter(
        SubAccount.id == account_id,
        SubAccount.user_id == user_id,
    ).first()
    if not account:
        raise HTTPException(status_code=404, detail="Sub-account not found")
    return account


@router.get("/", response_model=list[SubAccountResponse])
def list_sub_accounts(
    request: Request,
    enabled_only: bool = Query(False),
    db: Session = Depends(get_db),
):
    user_id = get_current_user_id(request)
    q = db.query(SubAccount).filter(SubAccount.user_id == user_id)
    if enabled_only:
        q = q.filter(SubAccount.is_enabled == True)
    accounts = q.order_by(SubAccount.id).all()
    return [_to_response(a) for a in accounts]


@router.post("/", response_model=SubAccountResponse, status_code=201)
async def create_sub_account(
    data: SubAccountCreate,
    request: Request,
    validate: bool = Query(False),
    db: Session = Depends(get_db),
):
    user_id = get_current_user_id(request)
    account = SubAccount(
        user_id=user_id,
        note=data.note,
        email=data.email,
        api_key=data.api_key,
        api_secret=data.api_secret,
        margin_enabled=data.margin_enabled,
        futures_enabled=data.futures_enabled,
        spot_enabled=data.spot_enabled,
        bnb_burn_enabled=data.bnb_burn_enabled,
        bnb_interest_enabled=data.bnb_interest_enabled,
    )

    if validate:
        result = await binance_client.validate_api_key(data.api_key, data.api_secret)
        if not result.is_valid:
            raise HTTPException(status_code=400, detail=f"API key validation failed: {result.error}")
        account.last_validated_at = datetime.now(timezone.utc)

    db.add(account)
    db.commit()
    db.refresh(account)
    return _to_response(account)


@router.get("/{account_id}", response_model=SubAccountResponse)
def get_sub_account(account_id: int, request: Request, db: Session = Depends(get_db)):
    user_id = get_current_user_id(request)
    return _to_response(_get_account(db, account_id, user_id))


@router.put("/{account_id}", response_model=SubAccountResponse)
def update_sub_account(account_id: int, data: SubAccountUpdate, request: Request, db: Session = Depends(get_db)):
    user_id = get_current_user_id(request)
    account = _get_account(db, account_id, user_id)
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(account, field, value)
    db.commit()
    db.refresh(account)
    return _to_response(account)


@router.delete("/{account_id}", response_model=MessageResponse)
def delete_sub_account(
    account_id: int,
    request: Request,
    hard: bool = Query(False),
    db: Session = Depends(get_db),
):
    user_id = get_current_user_id(request)
    account = _get_account(db, account_id, user_id)
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
    request: Request,
    validate: bool = Query(False),
    db: Session = Depends(get_db),
):
    user_id = get_current_user_id(request)
    account = _get_account(db, account_id, user_id)

    if validate:
        result = await binance_client.validate_api_key(data.api_key, data.api_secret)
        if not result.is_valid:
            raise HTTPException(status_code=400, detail=f"API key validation failed: {result.error}")
        account.last_validated_at = datetime.now(timezone.utc)

    account.api_key = data.api_key
    account.api_secret = data.api_secret
    db.commit()
    db.refresh(account)
    return _to_response(account)


@router.post("/{account_id}/validate", response_model=SubAccountValidation)
async def validate_sub_account(account_id: int, request: Request, db: Session = Depends(get_db)):
    user_id = get_current_user_id(request)
    account = _get_account(db, account_id, user_id)

    result = await binance_client.validate_api_key(account.api_key, account.api_secret)
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


@router.patch("/{account_id}/fund-params", response_model=SubAccountResponse)
def patch_fund_params(account_id: int, data: SubAccountFundPatch, request: Request, db: Session = Depends(get_db)):
    user_id = get_current_user_id(request)
    account = _get_account(db, account_id, user_id)

    updates = data.model_dump(exclude_unset=True)
    min_bal = updates.get("min_balance", account.min_balance)
    order_amt = updates.get("single_order_amount", account.single_order_amount)
    if min_bal is not None and order_amt is not None:
        from decimal import Decimal
        if Decimal(str(min_bal)) < Decimal(str(order_amt)) * Decimal("0.3"):
            raise HTTPException(status_code=422, detail="保底额度必须 ≥ 挂单单笔的 30%")

    for field, value in updates.items():
        setattr(account, field, value)
    db.commit()
    db.refresh(account)
    return _to_response(account)


@router.post("/{account_id}/clear")
def clear_account(account_id: int, data: SubAccountClearRequest, request: Request, db: Session = Depends(get_db)):
    from engine.models import Position
    user_id = get_current_user_id(request)
    account = _get_account(db, account_id, user_id)

    account.is_enabled = False

    closed_count = 0
    if data.mode == "disable_and_close":
        positions = db.query(Position).filter(
            Position.sub_account_id == account_id,
            Position.user_id == user_id,
            Position.status == "OPEN",
        ).all()
        for pos in positions:
            pos.status = "FORCE_CLOSE"
            closed_count += 1

    db.commit()
    return {
        "message": f"Account {account.note} disabled" + (f", {closed_count} positions marked for force-close" if closed_count else ""),
        "force_close_count": closed_count,
    }


@router.post("/{account_id}/toggle", response_model=SubAccountResponse)
def toggle_sub_account(account_id: int, request: Request, db: Session = Depends(get_db)):
    user_id = get_current_user_id(request)
    account = _get_account(db, account_id, user_id)
    account.is_enabled = not account.is_enabled
    db.commit()
    db.refresh(account)
    return _to_response(account)


def _get_master_keys(db: Session, user_id: int) -> tuple[str, str]:
    master = db.query(MasterAccount).filter(MasterAccount.user_id == user_id).first()
    if not master:
        raise HTTPException(status_code=400, detail="Master account not configured")
    return master.api_key, master.api_secret


@router.get("/{account_id}/permissions")
async def get_api_permissions(account_id: int, request: Request, db: Session = Depends(get_db)):
    user_id = get_current_user_id(request)
    account = _get_account(db, account_id, user_id)
    try:
        result = await binance_client.get_api_restrictions(account.api_key, account.api_secret)
        return result
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/{account_id}/ip-whitelist")
async def get_ip_whitelist(account_id: int, request: Request, db: Session = Depends(get_db)):
    user_id = get_current_user_id(request)
    account = _get_account(db, account_id, user_id)

    master = db.query(MasterAccount).filter(MasterAccount.user_id == user_id).first()
    if master:
        try:
            result = await binance_client.get_sub_account_ip_restriction(
                master.api_key, master.api_secret, account.email, account.api_key,
            )
            return result
        except Exception:
            pass

    try:
        restrictions = await binance_client.get_api_restrictions(account.api_key, account.api_secret)
        return {
            "ipRestrict": restrictions.get("ipRestrict", False),
            "ipList": [],
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.put("/{account_id}/ip-whitelist")
async def update_ip_whitelist(account_id: int, data: IpWhitelistUpdate, request: Request, db: Session = Depends(get_db)):
    user_id = get_current_user_id(request)
    account = _get_account(db, account_id, user_id)
    master_key, master_secret = _get_master_keys(db, user_id)
    try:
        result = await binance_client.update_sub_account_ip_restriction(
            master_key, master_secret, account.email, account.api_key,
            data.ip_restrict, data.ip_list,
        )
        return result
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/{account_id}/ip-whitelist/{ip_address}")
async def delete_ip_from_whitelist(account_id: int, ip_address: str, request: Request, db: Session = Depends(get_db)):
    user_id = get_current_user_id(request)
    account = _get_account(db, account_id, user_id)
    master_key, master_secret = _get_master_keys(db, user_id)
    try:
        result = await binance_client.delete_sub_account_ip(
            master_key, master_secret, account.email, account.api_key, ip_address,
        )
        return result
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
