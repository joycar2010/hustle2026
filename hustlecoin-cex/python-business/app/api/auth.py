from datetime import datetime, timedelta, timezone

import bcrypt
import httpx
import jwt
import redis
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.config import settings
from app.db.models_auth import User, UserRole
from app.db.models import FeishuConfig
from app.db.schemas.auth import LoginRequest, TokenResponse
from app.db.session import get_db

router = APIRouter(prefix="/api/auth", tags=["auth"])

_rate_limit_redis: redis.Redis | None = None

LOGIN_RATE_LIMIT = 5
LOGIN_RATE_WINDOW = 60


def _get_rate_redis() -> redis.Redis:
    global _rate_limit_redis
    if _rate_limit_redis is None:
        _rate_limit_redis = redis.from_url(settings.redis_url, decode_responses=True)
    return _rate_limit_redis


def _check_login_rate(client_ip: str):
    try:
        r = _get_rate_redis()
        key = f"login_rate:{client_ip}"
        count = r.incr(key)
        if count == 1:
            r.expire(key, LOGIN_RATE_WINDOW)
        if count > LOGIN_RATE_LIMIT:
            raise HTTPException(status_code=429, detail="Too many login attempts, try again later")
    except HTTPException:
        raise
    except Exception:
        pass


def _hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("ascii")


def _verify_password(password: str, hashed: str) -> bool:
    return bcrypt.checkpw(password.encode("utf-8"), hashed.encode("ascii"))


def create_access_token(username: str, user_id: int, role: str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(hours=settings.jwt_expire_hours)
    payload = {
        "sub": username,
        "user_id": user_id,
        "role": role,
        "exp": expire,
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm="HS256")


@router.post("/login", response_model=TokenResponse)
def login(req: LoginRequest, request: Request, db: Session = Depends(get_db)):
    client_ip = request.headers.get("x-forwarded-for", request.client.host if request.client else "unknown").split(",")[0].strip()
    _check_login_rate(client_ip)

    user = db.query(User).filter(
        User.username == req.username,
        User.is_active == True,
    ).first()

    if not user or not _verify_password(req.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid credentials")

    user.last_login_at = datetime.now(timezone.utc)
    user.login_ip = client_ip
    db.commit()

    token = create_access_token(user.username, user.id, user.role.value if isinstance(user.role, UserRole) else user.role)
    return TokenResponse(access_token=token)


@router.post("/refresh", response_model=TokenResponse)
def refresh_token(request: Request):
    auth_header = request.headers.get("authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing token")
    token = auth_header[7:]
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=["HS256"],
                             options={"verify_exp": False})
        username = payload.get("sub")
        user_id = payload.get("user_id")
        role = payload.get("role", "USER")
        if not username or not user_id:
            raise HTTPException(status_code=401, detail="Invalid token")
        exp = payload.get("exp", 0)
        now = datetime.now(timezone.utc).timestamp()
        if now - exp > 7 * 24 * 3600:
            raise HTTPException(status_code=401, detail="Token expired beyond refresh window")
        new_token = create_access_token(username, user_id, role)
        return TokenResponse(access_token=new_token)
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")


@router.post("/init")
def init_admin(req: LoginRequest, db: Session = Depends(get_db)):
    """Create first super admin user. Only works when no users exist."""
    count = db.query(User).count()
    if count > 0:
        raise HTTPException(status_code=403, detail="Admin already initialized")

    user = User(
        username=req.username,
        password_hash=_hash_password(req.password),
        role=UserRole.SUPER_ADMIN,
    )
    db.add(user)
    db.commit()
    return {"message": "Super admin user created"}


@router.get("/me")
def get_me(request: Request, db: Session = Depends(get_db)):
    user_id = getattr(request.state, "user_id", None)
    if not user_id:
        raise HTTPException(status_code=401, detail="Not authenticated")
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return {
        "id": user.id,
        "username": user.username,
        "email": user.email,
        "display_name": user.display_name,
        "role": user.role.value if isinstance(user.role, UserRole) else user.role,
        "is_active": user.is_active,
        "max_sub_accounts": user.max_sub_accounts,
        "last_login_at": str(user.last_login_at) if user.last_login_at else None,
        "feishu_open_id": user.feishu_open_id or "",
        "feishu_phone": user.feishu_phone or "",
        "feishu_union_id": user.feishu_union_id or "",
    }


class ProfileUpdate(BaseModel):
    email: str | None = None
    display_name: str | None = None
    feishu_open_id: str | None = None
    feishu_phone: str | None = None
    feishu_union_id: str | None = None
    password: str | None = None


@router.put("/profile")
def update_profile(req: ProfileUpdate, request: Request, db: Session = Depends(get_db)):
    user_id = getattr(request.state, "user_id", None)
    if not user_id:
        raise HTTPException(status_code=401, detail="Not authenticated")
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    if req.email is not None:
        user.email = req.email
    if req.display_name is not None:
        user.display_name = req.display_name
    if req.feishu_open_id is not None:
        user.feishu_open_id = req.feishu_open_id
    if req.feishu_phone is not None:
        user.feishu_phone = req.feishu_phone
    if req.feishu_union_id is not None:
        user.feishu_union_id = req.feishu_union_id
    if req.password:
        user.password_hash = _hash_password(req.password)

    db.commit()
    return {"message": "Profile updated"}


class FeishuLookupRequest(BaseModel):
    phone: str


@router.post("/feishu-lookup")
async def feishu_lookup(req: FeishuLookupRequest, db: Session = Depends(get_db)):
    fc = db.query(FeishuConfig).filter(FeishuConfig.user_id.is_(None)).first()
    app_id = (fc.app_id if fc and fc.app_id else None) or settings.feishu_app_id
    app_secret = (fc.app_secret if fc and fc.app_secret else None) or settings.feishu_app_secret
    if not app_id or not app_secret:
        raise HTTPException(status_code=400, detail="飞书 App ID/Secret 未配置")

    async with httpx.AsyncClient(timeout=10) as http:
        token_resp = await http.post(
            "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal",
            json={"app_id": app_id, "app_secret": app_secret},
        )
        token_data = token_resp.json()
        if token_data.get("code") != 0:
            raise HTTPException(status_code=502, detail=f"获取飞书token失败: {token_data.get('msg')}")
        tenant_token = token_data["tenant_access_token"]

        lookup_resp = await http.post(
            "https://open.feishu.cn/open-apis/contact/v3/users/batch_get_id",
            headers={"Authorization": f"Bearer {tenant_token}"},
            json={"mobiles": [req.phone]},
            params={"user_id_type": "open_id"},
        )
        lookup_data = lookup_resp.json()
        if lookup_data.get("code") != 0:
            raise HTTPException(status_code=502, detail=f"飞书查询失败: {lookup_data.get('msg')}")

        user_list = lookup_data.get("data", {}).get("user_list", [])
        if not user_list or not user_list[0].get("user_id"):
            raise HTTPException(status_code=404, detail="未找到该手机号对应的飞书用户")

        open_id = user_list[0].get("user_id", "")

    union_id = ""
    async with httpx.AsyncClient(timeout=10) as http:
        user_resp = await http.get(
            f"https://open.feishu.cn/open-apis/contact/v3/users/{open_id}",
            headers={"Authorization": f"Bearer {tenant_token}"},
            params={"user_id_type": "open_id"},
        )
        user_data = user_resp.json()
        if user_data.get("code") == 0:
            union_id = user_data.get("data", {}).get("user", {}).get("union_id", "")

    return {"open_id": open_id, "union_id": union_id}
