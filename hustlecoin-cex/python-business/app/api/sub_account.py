import asyncio
import logging
from datetime import datetime, timezone
from enum import Enum

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, field_validator
from sqlalchemy.orm import Session

from app.db.schemas import validators as _V

from app.db.models import SubAccount, MasterAccount
from app.db.models_proxy import AccountProxyBinding, ProxyPool, IpipgoOrder
from app.db.schemas.sub_account import (
    SubAccountCreate, SubAccountUpdate, SubAccountKeyUpdate,
    SubAccountResponse, SubAccountValidation,
)
from app.db.schemas.common import MessageResponse
from app.db.session import get_db
from app.middleware.permissions import get_current_user_id
from app.services import binance_client

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/sub-accounts", tags=["sub-accounts"])


class IpWhitelistUpdate(BaseModel):
    ip_restrict: bool = True
    ip_list: list[str]


class CheckPermBody(BaseModel):
    api_key: str
    api_secret: str


class ClearMode(str, Enum):
    disable_only = "disable_only"
    disable_and_close = "disable_and_close"


class ClearAccountBody(BaseModel):
    mode: ClearMode = ClearMode.disable_only


def _mask_secret(secret: str) -> str:
    if len(secret) <= 4:
        return "****"
    return "****" + secret[-4:]


def _to_response(account: SubAccount) -> dict:
    return {
        "id": account.id,
        "note": account.note,
        "email": account.email,
        "api_key": _mask_secret(account.api_key),
        "api_secret_masked": _mask_secret(account.api_secret),
        "is_enabled": account.is_enabled,
        "margin_enabled": account.margin_enabled,
        "futures_enabled": account.futures_enabled,
        "spot_enabled": account.spot_enabled,
        "bnb_burn_enabled": account.bnb_burn_enabled,
        "bnb_interest_enabled": account.bnb_interest_enabled,
        "last_validated_at": account.last_validated_at,
        "order_amount": str(account.order_amount) if account.order_amount else None,
        "base_margin_amount": str(account.base_margin_amount) if account.base_margin_amount else None,
        "single_transfer_amount": str(account.single_transfer_amount) if account.single_transfer_amount else None,
        "risk_threshold": str(account.risk_threshold) if account.risk_threshold else None,
        "min_balance": str(account.min_balance) if account.min_balance else None,
        "single_order_amount": str(account.single_order_amount) if account.single_order_amount else None,
        "max_positions": account.max_positions,
        "max_borrow_amount": str(account.max_borrow_amount) if account.max_borrow_amount else None,
        "max_order_count": account.max_order_count,
        "borrow_rate_per_sec": str(account.borrow_rate_per_sec) if account.borrow_rate_per_sec else None,
        "created_at": account.created_at,
        "updated_at": account.updated_at,
    }


def _owned_sub(db: Session, account_id: int, request: Request) -> SubAccount:
    """按登录用户取本人子账户;不属于当前用户(或不存在)一律 404。
    收口跨用户越权读/写:coin 端点只有本前端在用,admin 走 /api/admin/users/* 管理他人账户。"""
    uid = get_current_user_id(request)
    acct = db.query(SubAccount).filter(SubAccount.id == account_id, SubAccount.user_id == uid).first()
    if not acct:
        raise HTTPException(status_code=404, detail="Sub-account not found")
    return acct


@router.get("/")
def list_sub_accounts(
    request: Request,
    enabled_only: bool = Query(False),
    db: Session = Depends(get_db),
):
    uid = get_current_user_id(request)
    q = db.query(SubAccount).filter(SubAccount.user_id == uid)
    if enabled_only:
        q = q.filter(SubAccount.is_enabled == True)
    accounts = q.order_by(SubAccount.id).all()
    result = []
    for a in accounts:
        data = _to_response(a)
        binding = db.query(AccountProxyBinding).filter(
            AccountProxyBinding.sub_account_id == a.id,
            AccountProxyBinding.is_active == True,
        ).first()
        proxy_info = None
        if binding:
            proxy = db.query(ProxyPool).filter(ProxyPool.id == binding.proxy_id).first()
            if proxy:
                proxy_info = {"host": proxy.host, "region": proxy.region, "name": proxy.name}
                ipipgo = db.query(IpipgoOrder).filter(
                    IpipgoOrder.ip_address == proxy.host,
                    IpipgoOrder.status == "active",
                ).first()
                if ipipgo:
                    proxy_info["end_date"] = str(ipipgo.end_date) if ipipgo.end_date else None
                    proxy_info["days_left"] = ipipgo.days_left
        data["proxy"] = proxy_info
        result.append(data)
    return result


@router.get("/server-ip")
async def get_server_ip():
    try:
        ip = await binance_client.get_server_ip()
        return {"ip": ip}
    except Exception:
        raise HTTPException(status_code=502, detail="获取服务器 IP 失败")


@router.post("/check-permissions")
async def check_permissions(body: CheckPermBody):
    try:
        data = await binance_client.get_api_restrictions(body.api_key, body.api_secret)
        return data
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


@router.post("/", response_model=SubAccountResponse, status_code=201)
async def create_sub_account(
    data: SubAccountCreate,
    request: Request,
    validate: bool = Query(False),
    db: Session = Depends(get_db),
):
    uid = get_current_user_id(request)
    account = SubAccount(
        user_id=uid,
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
    account = _owned_sub(db, account_id, request)
    return _to_response(account)


@router.put("/{account_id}", response_model=SubAccountResponse)
def update_sub_account(account_id: int, data: SubAccountUpdate, request: Request, db: Session = Depends(get_db)):
    account = _owned_sub(db, account_id, request)
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
    account = _owned_sub(db, account_id, request)
    note = account.note
    if hard:
        # 硬删除时一并清掉该账户的 engine_state(sub:N)行,否则残留为永久「超时」
        # 的僵尸 worker(显示却删不掉)。软禁用保留账户,其 worker 行仍有效不清。
        from engine.models import EngineState
        db.query(EngineState).filter(EngineState.scope == f"sub:{account_id}").delete(
            synchronize_session=False
        )
        db.delete(account)
    else:
        account.is_enabled = False
    db.commit()
    action = "deleted" if hard else "disabled"
    return {"message": f"Sub-account {note} {action}"}


@router.put("/{account_id}/keys", response_model=SubAccountResponse)
async def update_keys(
    account_id: int,
    data: SubAccountKeyUpdate,
    request: Request,
    validate: bool = Query(False),
    db: Session = Depends(get_db),
):
    account = _owned_sub(db, account_id, request)

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
    account = _owned_sub(db, account_id, request)

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


@router.get("/{account_id}/permissions")
async def get_sub_account_permissions(account_id: int, request: Request, db: Session = Depends(get_db)):
    account = _owned_sub(db, account_id, request)
    data = await binance_client.get_api_restrictions(account.api_key, account.api_secret)
    return data


@router.post("/{account_id}/toggle", response_model=SubAccountResponse)
def toggle_sub_account(account_id: int, request: Request, db: Session = Depends(get_db)):
    account = _owned_sub(db, account_id, request)
    account.is_enabled = not account.is_enabled
    db.commit()
    db.refresh(account)
    return _to_response(account)


@router.get("/{account_id}/ip-whitelist")
async def get_ip_whitelist(account_id: int, request: Request, db: Session = Depends(get_db)):
    account = _owned_sub(db, account_id, request)
    if not account.is_enabled:
        return {"ipRestrict": None, "ipList": []}
    try:
        restrictions = await binance_client.get_api_restrictions(account.api_key, account.api_secret)
        ip_data = await binance_client.get_ip_restriction(account.api_key, account.api_secret)
        return {
            "ipRestrict": restrictions.get("ipRestrict", False),
            "ipList": ip_data.get("ipList", []),
        }
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e)[:200])


@router.put("/{account_id}/ip-whitelist")
async def update_ip_whitelist(account_id: int, body: IpWhitelistUpdate, request: Request, db: Session = Depends(get_db)):
    account = _owned_sub(db, account_id, request)
    if not body.ip_list:
        raise HTTPException(status_code=400, detail="IP 列表不能为空")
    try:
        result = await binance_client.add_ip_restriction(account.api_key, account.api_secret, body.ip_list)
        return result
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e)[:200])


@router.delete("/{account_id}/ip-whitelist/{ip}")
async def remove_ip_from_whitelist(account_id: int, ip: str, request: Request, db: Session = Depends(get_db)):
    account = _owned_sub(db, account_id, request)
    try:
        result = await binance_client.remove_ip_restriction(account.api_key, account.api_secret, ip)
        return result
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e)[:200])


class FundParamsUpdate(BaseModel):
    order_amount: float | None = None
    base_margin_amount: float | None = None
    single_transfer_amount: float | None = None
    risk_threshold: float | None = None
    min_balance: float | None = None
    single_order_amount: float | None = None
    max_positions: int | None = None
    max_borrow_amount: float | None = None
    max_order_count: int | None = None
    borrow_rate_per_sec: float | None = None

    @field_validator("order_amount", "base_margin_amount", "single_transfer_amount",
                     "min_balance", "single_order_amount", "max_borrow_amount")
    @classmethod
    def _v_amount(cls, v, info):
        return _V.rng(v, 0, 1_000_000_000_000, info.field_name)

    @field_validator("risk_threshold")
    @classmethod
    def _v_risk(cls, v, info):
        return _V.rng(v, 0, 1000, info.field_name)

    @field_validator("borrow_rate_per_sec")
    @classmethod
    def _v_rate(cls, v, info):
        return _V.rng(v, 0, 2, info.field_name)

    @field_validator("max_positions", "max_order_count")
    @classmethod
    def _v_count(cls, v, info):
        return _V.rng(v, 0, 100000, info.field_name)


FUND_PARAM_FIELDS = {
    "order_amount", "base_margin_amount", "single_transfer_amount",
    "risk_threshold", "min_balance", "single_order_amount",
    "max_positions", "max_borrow_amount", "max_order_count",
    "borrow_rate_per_sec",
}


@router.patch("/{account_id}/fund-params")
def patch_fund_params(account_id: int, data: FundParamsUpdate, request: Request, db: Session = Depends(get_db)):
    from decimal import Decimal
    import json
    import math

    account = _owned_sub(db, account_id, request)

    update_data = data.model_dump(exclude_unset=True)
    diffs: dict = {}
    for field, value in update_data.items():
        if field in FUND_PARAM_FIELDS:
            old = getattr(account, field, None)
            if str(old) != str(value):
                diffs[f"acct{account_id}.{field}"] = [None if old is None else str(old),
                                                      None if value is None else str(value)]
            setattr(account, field, value)

    # E1: auto-enforce min_balance >= 30% of single_order_amount
    if "single_order_amount" in update_data and account.single_order_amount:
        min_required = Decimal(str(math.ceil(float(account.single_order_amount) * 0.3)))
        current_min = Decimal(str(account.min_balance or 0))
        if current_min < min_required:
            account.min_balance = min_required

    db.commit()
    db.refresh(account)
    if diffs:
        try:
            request.state.audit_details = json.dumps(diffs, ensure_ascii=False)[:3900]
        except Exception:
            pass
    return {
        "id": account.id,
        "note": account.note,
        "order_amount": str(account.order_amount) if account.order_amount else None,
        "base_margin_amount": str(account.base_margin_amount) if account.base_margin_amount else None,
        "single_transfer_amount": str(account.single_transfer_amount) if account.single_transfer_amount else None,
        "risk_threshold": str(account.risk_threshold) if account.risk_threshold else None,
        "min_balance": str(account.min_balance) if account.min_balance else None,
        "single_order_amount": str(account.single_order_amount) if account.single_order_amount else None,
        "max_positions": account.max_positions,
        "max_borrow_amount": str(account.max_borrow_amount) if account.max_borrow_amount else None,
        "max_order_count": account.max_order_count,
        "borrow_rate_per_sec": str(account.borrow_rate_per_sec) if account.borrow_rate_per_sec else None,
    }


@router.post("/{account_id}/clear")
async def clear_sub_account(account_id: int, body: ClearAccountBody, request: Request, db: Session = Depends(get_db)):
    import json
    import redis
    from app.config import settings
    from engine.models import Position

    account = _owned_sub(db, account_id, request)

    account.is_enabled = False
    db.commit()

    if body.mode == ClearMode.disable_and_close:
        open_count = db.query(Position).filter(
            Position.sub_account_id == account_id,
            Position.status == "OPEN",
        ).count()

        user_id = account.user_id
        r = redis.from_url(settings.redis_url, decode_responses=True)
        r.rpush(
            f"engine:{user_id}:commands",
            json.dumps({"action": "clear_account", "account_id": account_id}),
        )
        r.close()

        return {
            "message": f"账户 {account.note} 已禁用，{open_count} 个持仓正在平仓中",
            "open_positions": open_count,
        }

    return {"message": f"账户 {account.note} 已禁用"}
