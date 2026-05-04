import asyncio
import json
from datetime import datetime, timezone
from decimal import Decimal

import bcrypt
import redis as redis_lib
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy import func as sqlfunc

from app.db.models_auth import User, UserRole
from app.db.models import SubAccount, GlobalRules, MasterAccount
from app.db.models_proxy import AccountProxyBinding, ProxyPool
from app.db.session import get_db
from app.config import settings
from app.middleware.permissions import require_super_admin, require_admin, get_current_user_id
from app.services import binance_client
from engine.models import Position, EngineState, TradeLog

router = APIRouter(prefix="/api/admin", tags=["admin-users"])


class CreateUserRequest(BaseModel):
    username: str
    password: str
    email: str | None = None
    display_name: str | None = None
    role: str = "USER"
    max_sub_accounts: int = 5
    feishu_open_id: str | None = None
    feishu_phone: str | None = None
    feishu_union_id: str | None = None


class UpdateUserRequest(BaseModel):
    email: str | None = None
    display_name: str | None = None
    role: str | None = None
    is_active: bool | None = None
    max_sub_accounts: int | None = None
    feishu_open_id: str | None = None
    feishu_phone: str | None = None
    feishu_union_id: str | None = None


class ResetPasswordRequest(BaseModel):
    new_password: str


class CreateSubAccountRequest(BaseModel):
    note: str
    email: str
    api_key: str
    api_secret: str


class UpdateSubAccountRequest(BaseModel):
    note: str | None = None
    email: str | None = None
    is_enabled: bool | None = None
    api_key: str | None = None
    api_secret: str | None = None


class MasterAccountRequest(BaseModel):
    api_key: str
    api_secret: str


def _hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("ascii")


def _user_to_dict(user: User) -> dict:
    return {
        "id": user.id,
        "username": user.username,
        "email": user.email,
        "display_name": user.display_name,
        "role": user.role.value if isinstance(user.role, UserRole) else user.role,
        "is_active": user.is_active,
        "max_sub_accounts": user.max_sub_accounts,
        "created_at": str(user.created_at) if user.created_at else None,
        "last_login_at": str(user.last_login_at) if user.last_login_at else None,
        "login_ip": user.login_ip,
        "feishu_open_id": getattr(user, "feishu_open_id", None),
        "feishu_phone": getattr(user, "feishu_phone", None),
        "feishu_union_id": getattr(user, "feishu_union_id", None),
    }


def _mask_key(key: str) -> str:
    if not key or len(key) < 8:
        return "***"
    return key[:4] + "..." + key[-4:]


# ─── User CRUD ───

@router.get("/users")
def list_users(request: Request, db: Session = Depends(get_db)):
    require_super_admin(request)
    users = db.query(User).order_by(User.id).all()
    return [_user_to_dict(u) for u in users]


@router.post("/users")
def create_user(req: CreateUserRequest, request: Request, db: Session = Depends(get_db)):
    require_super_admin(request)

    if req.role not in ("SUPER_ADMIN", "ADMIN", "USER"):
        raise HTTPException(status_code=400, detail="Invalid role")

    existing = db.query(User).filter(User.username == req.username).first()
    if existing:
        raise HTTPException(status_code=409, detail="Username already exists")

    user = User(
        username=req.username,
        password_hash=_hash_password(req.password),
        email=req.email,
        display_name=req.display_name,
        role=UserRole(req.role),
        max_sub_accounts=req.max_sub_accounts,
    )
    if req.feishu_open_id is not None:
        user.feishu_open_id = req.feishu_open_id
    if req.feishu_phone is not None:
        user.feishu_phone = req.feishu_phone
    if req.feishu_union_id is not None:
        user.feishu_union_id = req.feishu_union_id

    db.add(user)
    db.flush()

    rules = GlobalRules(user_id=user.id)
    db.add(rules)

    db.commit()
    db.refresh(user)
    return _user_to_dict(user)


@router.put("/users/{user_id}")
def update_user(user_id: int, req: UpdateUserRequest, request: Request, db: Session = Depends(get_db)):
    require_super_admin(request)

    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    if req.email is not None:
        user.email = req.email
    if req.display_name is not None:
        user.display_name = req.display_name
    if req.role is not None:
        if req.role not in ("SUPER_ADMIN", "ADMIN", "USER"):
            raise HTTPException(status_code=400, detail="Invalid role")
        user.role = UserRole(req.role)
    if req.is_active is not None:
        user.is_active = req.is_active
    if req.max_sub_accounts is not None:
        user.max_sub_accounts = req.max_sub_accounts
    if req.feishu_open_id is not None:
        user.feishu_open_id = req.feishu_open_id
    if req.feishu_phone is not None:
        user.feishu_phone = req.feishu_phone
    if req.feishu_union_id is not None:
        user.feishu_union_id = req.feishu_union_id

    db.commit()
    db.refresh(user)
    return _user_to_dict(user)


@router.delete("/users/{user_id}")
def delete_user(user_id: int, request: Request, db: Session = Depends(get_db)):
    require_super_admin(request)
    current_uid = get_current_user_id(request)
    if user_id == current_uid:
        raise HTTPException(status_code=400, detail="Cannot delete yourself")

    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    open_positions = db.query(sqlfunc.count(Position.id)).filter(
        Position.user_id == user_id,
        Position.status == "OPEN",
    ).scalar() or 0
    if open_positions > 0:
        raise HTTPException(status_code=400, detail=f"User has {open_positions} open positions, cannot delete")

    user.is_active = False
    db.commit()
    return {"message": f"User {user.username} disabled"}


@router.post("/users/{user_id}/reset-password")
def reset_password(user_id: int, req: ResetPasswordRequest, request: Request, db: Session = Depends(get_db)):
    require_super_admin(request)

    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    user.password_hash = _hash_password(req.new_password)
    db.commit()
    return {"message": "Password reset successfully"}


@router.get("/users/{user_id}/stats")
def user_stats(user_id: int, request: Request, db: Session = Depends(get_db)):
    require_super_admin(request)

    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    sub_count = db.query(sqlfunc.count(SubAccount.id)).filter(SubAccount.user_id == user_id).scalar() or 0
    position_count = db.query(sqlfunc.count(Position.id)).filter(
        Position.user_id == user_id,
        Position.closed_at.is_(None),
    ).scalar() or 0
    total_positions = db.query(sqlfunc.count(Position.id)).filter(Position.user_id == user_id).scalar() or 0

    return {
        "user": _user_to_dict(user),
        "sub_accounts": sub_count,
        "open_positions": position_count,
        "total_positions": total_positions,
    }


# ─── Master Account ───

@router.get("/users/{user_id}/master-account")
def get_master_account(user_id: int, request: Request, db: Session = Depends(get_db)):
    require_admin(request)
    ma = db.query(MasterAccount).filter(MasterAccount.user_id == user_id).first()
    if not ma:
        return None
    return {
        "id": ma.id,
        "user_id": ma.user_id,
        "api_key_masked": _mask_key(ma.api_key or ""),
        "is_verified": ma.is_verified,
        "created_at": str(ma.created_at) if ma.created_at else None,
    }


@router.post("/users/{user_id}/master-account")
def create_master_account(user_id: int, req: MasterAccountRequest, request: Request, db: Session = Depends(get_db)):
    require_admin(request)
    existing = db.query(MasterAccount).filter(MasterAccount.user_id == user_id).first()
    if existing:
        raise HTTPException(status_code=409, detail="Master account already exists")
    ma = MasterAccount(user_id=user_id, api_key=req.api_key, api_secret=req.api_secret)
    db.add(ma)
    db.commit()
    db.refresh(ma)
    return {"id": ma.id, "message": "Master account created"}


@router.put("/users/{user_id}/master-account")
def update_master_account(user_id: int, req: MasterAccountRequest, request: Request, db: Session = Depends(get_db)):
    require_admin(request)
    ma = db.query(MasterAccount).filter(MasterAccount.user_id == user_id).first()
    if not ma:
        raise HTTPException(status_code=404, detail="Master account not found")
    ma.api_key = req.api_key
    ma.api_secret = req.api_secret
    db.commit()
    return {"message": "Master account updated"}


@router.delete("/users/{user_id}/master-account")
def delete_master_account(user_id: int, request: Request, db: Session = Depends(get_db)):
    require_admin(request)
    ma = db.query(MasterAccount).filter(MasterAccount.user_id == user_id).first()
    if not ma:
        raise HTTPException(status_code=404, detail="Master account not found")
    db.delete(ma)
    db.commit()
    return {"message": "Master account deleted"}


# ─── Sub-Account Management ───

@router.get("/users/{user_id}/sub-accounts")
def get_user_sub_accounts(user_id: int, request: Request, db: Session = Depends(get_db)):
    require_admin(request)

    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    accounts = db.query(SubAccount).filter(SubAccount.user_id == user_id).order_by(SubAccount.id).all()
    result = []
    for sa in accounts:
        binding = db.query(AccountProxyBinding).filter(
            AccountProxyBinding.sub_account_id == sa.id,
            AccountProxyBinding.is_active == True,
        ).first()

        proxy_info = None
        if binding:
            proxy = db.query(ProxyPool).filter(ProxyPool.id == binding.proxy_id).first()
            if proxy:
                proxy_info = {
                    "id": proxy.id,
                    "name": proxy.name,
                    "host": proxy.host,
                    "port": proxy.port,
                    "status": proxy.status,
                }

        pos_count = db.query(sqlfunc.count(Position.id)).filter(
            Position.sub_account_id == sa.id,
            Position.status == "OPEN",
        ).scalar() or 0

        result.append({
            "id": sa.id,
            "note": sa.note,
            "email": sa.email,
            "is_enabled": sa.is_enabled,
            "api_key_masked": _mask_key(sa.api_key or ""),
            "margin_enabled": sa.margin_enabled,
            "futures_enabled": sa.futures_enabled,
            "spot_enabled": sa.spot_enabled,
            "positions_count": pos_count,
            "proxy": proxy_info,
            "last_validated_at": str(sa.last_validated_at) if sa.last_validated_at else None,
            "created_at": str(sa.created_at) if sa.created_at else None,
        })

    return result


@router.post("/users/{user_id}/sub-accounts")
def create_sub_account(user_id: int, req: CreateSubAccountRequest, request: Request, db: Session = Depends(get_db)):
    require_admin(request)

    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    current_count = db.query(sqlfunc.count(SubAccount.id)).filter(SubAccount.user_id == user_id).scalar() or 0
    if current_count >= (user.max_sub_accounts or 5):
        raise HTTPException(status_code=400, detail=f"Max sub-accounts ({user.max_sub_accounts}) reached")

    sa = SubAccount(
        user_id=user_id,
        note=req.note,
        email=req.email,
        api_key=req.api_key,
        api_secret=req.api_secret,
    )
    db.add(sa)
    db.commit()
    db.refresh(sa)

    return {
        "id": sa.id,
        "note": sa.note,
        "email": sa.email,
        "is_enabled": sa.is_enabled,
        "message": "Sub-account created",
    }


@router.put("/users/{user_id}/sub-accounts/{sa_id}")
def update_sub_account(user_id: int, sa_id: int, req: UpdateSubAccountRequest, request: Request, db: Session = Depends(get_db)):
    require_admin(request)

    sa = db.query(SubAccount).filter(SubAccount.id == sa_id, SubAccount.user_id == user_id).first()
    if not sa:
        raise HTTPException(status_code=404, detail="Sub-account not found")

    if req.note is not None:
        sa.note = req.note
    if req.email is not None:
        sa.email = req.email
    if req.is_enabled is not None:
        sa.is_enabled = req.is_enabled
    if req.api_key is not None:
        sa.api_key = req.api_key
    if req.api_secret is not None:
        sa.api_secret = req.api_secret

    db.commit()
    db.refresh(sa)
    return {"message": "Sub-account updated", "id": sa.id}


@router.delete("/users/{user_id}/sub-accounts/{sa_id}")
def delete_sub_account(user_id: int, sa_id: int, request: Request, db: Session = Depends(get_db)):
    require_admin(request)

    sa = db.query(SubAccount).filter(SubAccount.id == sa_id, SubAccount.user_id == user_id).first()
    if not sa:
        raise HTTPException(status_code=404, detail="Sub-account not found")

    open_pos = db.query(sqlfunc.count(Position.id)).filter(
        Position.sub_account_id == sa.id,
        Position.status == "OPEN",
    ).scalar() or 0
    if open_pos > 0:
        raise HTTPException(status_code=400, detail=f"Sub-account has {open_pos} open positions")

    db.query(AccountProxyBinding).filter(AccountProxyBinding.sub_account_id == sa.id).delete()
    db.delete(sa)
    db.commit()
    return {"message": "Sub-account deleted"}


# ─── Sync Permissions ───


@router.post("/users/{user_id}/sub-accounts/sync-permissions")
async def sync_user_sub_account_permissions(user_id: int, request: Request, db: Session = Depends(get_db)):
    require_admin(request)

    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    accounts = db.query(SubAccount).filter(
        SubAccount.user_id == user_id,
        SubAccount.is_enabled == True,
    ).all()

    if not accounts:
        return {"synced": 0, "failed": 0, "results": []}

    results = []
    synced = 0
    failed = 0

    for sa in accounts:
        try:
            restrictions = await binance_client.get_api_restrictions(sa.api_key, sa.api_secret)
            sa.spot_enabled = bool(restrictions.get("enableSpotAndMarginTrading", False))
            sa.margin_enabled = bool(restrictions.get("enableMargin", False))
            sa.futures_enabled = bool(restrictions.get("enableFutures", False))
            sa.last_validated_at = datetime.now(timezone.utc)
            results.append({
                "id": sa.id, "note": sa.note, "status": "ok",
                "spot": sa.spot_enabled, "margin": sa.margin_enabled, "futures": sa.futures_enabled,
            })
            synced += 1
        except Exception as e:
            results.append({"id": sa.id, "note": sa.note, "status": "error", "error": str(e)[:100]})
            failed += 1
        await asyncio.sleep(0.3)

    db.commit()
    return {"synced": synced, "failed": failed, "results": results}


# ─── Engine Control ───

@router.get("/engine/users")
def list_engine_users(request: Request, db: Session = Depends(get_db)):
    require_admin(request)

    users = db.query(User).filter(User.is_active == True).all()
    result = []
    for u in users:
        es = db.query(EngineState).filter(
            EngineState.user_id == u.id,
            EngineState.scope == "global",
        ).first()

        worker_states = db.query(EngineState).filter(
            EngineState.user_id == u.id,
            EngineState.scope != "global",
        ).all()

        user_open = db.query(sqlfunc.count(Position.id)).filter(
            Position.user_id == u.id,
            Position.status == "OPEN",
        ).scalar() or 0

        user_pnl = db.query(sqlfunc.coalesce(sqlfunc.sum(Position.realized_pnl), 0)).filter(
            Position.user_id == u.id,
            Position.status == "CLOSED",
        ).scalar()

        last_trade = db.query(TradeLog.created_at).filter(
            TradeLog.user_id == u.id,
        ).order_by(TradeLog.created_at.desc()).first()

        result.append({
            "user_id": u.id,
            "username": u.username,
            "status": es.status if es else "STOPPED",
            "worker_count": len(worker_states),
            "open_positions": user_open,
            "total_pnl": str(Decimal(str(user_pnl))),
            "last_trade_at": str(last_trade[0]) if last_trade else None,
        })

    return result


@router.post("/engine/users/{user_id}/start")
def start_user_engine(user_id: int, request: Request, db: Session = Depends(get_db)):
    require_admin(request)

    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    sub_accounts = db.query(SubAccount).filter(
        SubAccount.user_id == user_id,
        SubAccount.is_enabled == True,
    ).all()
    if not sub_accounts:
        raise HTTPException(status_code=400, detail="User has no enabled sub-accounts")

    try:
        r = redis_lib.from_url(settings.redis_url, socket_connect_timeout=2)
        r.rpush("engine:admin_commands", json.dumps({
            "action": "start_user",
            "user_id": user_id,
        }))
    except Exception:
        pass

    return {"message": f"Engine start signal sent for user {user.username}"}


@router.post("/engine/users/{user_id}/stop")
def stop_user_engine(user_id: int, request: Request, db: Session = Depends(get_db)):
    require_admin(request)

    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    try:
        r = redis_lib.from_url(settings.redis_url, socket_connect_timeout=2)
        r.rpush("engine:admin_commands", json.dumps({
            "action": "stop_user",
            "user_id": user_id,
        }))
    except Exception:
        pass

    return {"message": f"Engine stop signal sent for user {user.username}"}
