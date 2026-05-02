from datetime import datetime, timedelta, timezone

import bcrypt
import jwt
import redis
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.config import settings
from app.db.models_auth import User, UserRole
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
    }
