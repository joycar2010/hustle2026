"""独立用户体系（mix.hustle2026.xyz 用户端）—— mix_main.mix_users + JWT(HS256)。
与操作员体系（dcm operators）分轨：用户端 JWT 只有 VIEWER 级读权限，永远进不了写路径。
契约对齐 mix-user-web auth store：/auth/login → {access_token,user_id,username}；
/users/me；/me/subaccount（banner）。密码 pbkdf2_hmac-sha256(12万轮,逐用户盐)。
"""
import hashlib
import hmac
import secrets
import datetime as dt

from fastapi import APIRouter, HTTPException, Header, Depends
from pydantic import BaseModel

from .. import config
from .. import datasources as ds
from ..deps import require_admin, require_viewer

router = APIRouter(tags=["auth"])

PBKDF2_ITERS = 120_000


def hash_password(password: str, salt: str) -> str:
    return hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), PBKDF2_ITERS).hex()


class LoginBody(BaseModel):
    username: str
    password: str
    totp_code: str | None = None   # 已绑定登录二次认证的账号必填


async def _bearer_user(authorization: str | None = Header(default=None)) -> dict:
    if not (authorization and authorization.lower().startswith("bearer ")):
        raise HTTPException(401, "missing bearer token")
    from ..deps import _jwt_decode
    who = _jwt_decode(authorization[7:].strip())
    if not who:
        raise HTTPException(401, "invalid or expired token")
    return who


@router.post("/auth/login")
async def login(body: LoginBody):
    pool = await ds.pg_main()
    if pool is None or not config.JWT_SECRET:
        raise HTTPException(503, "用户体系未配置（MIX_MAIN_DSN/MIX_JWT_SECRET）")
    rows = await pool.fetch(
        "SELECT id, username, password_hash, salt, role, enabled FROM mix_users WHERE username=$1",
        body.username.strip())
    generic = HTTPException(401, "用户名或密码错误")
    if not rows:
        raise generic
    u = rows[0]
    if not u["enabled"]:
        raise generic
    calc = hash_password(body.password, u["salt"])
    if not hmac.compare_digest(calc, u["password_hash"]):
        raise generic
    # 登录TOTP(用户2026-07-19拍板:二次认证移到登录,会话内不再逐笔输码):
    # 该用户名在 operator_totp 有已确认绑定→登录必须带6位码;JWT标记 sa=1(strong auth)
    strong = False
    try:
        trow = await pool.fetchrow(
            "SELECT secret, confirmed FROM operator_totp WHERE operator=$1", u["username"])
        if trow and trow["confirmed"]:
            code = str(getattr(body, "totp_code", None) or "").strip()
            if not code:
                raise HTTPException(428, "该账号已启用登录二次认证,请输入 Authenticator 6位动态码")
            from .proposal import _totp_verify
            if not _totp_verify(trow["secret"], code):
                raise HTTPException(401, "动态码错误或已过期")
            strong = True
    except HTTPException:
        raise
    except Exception:  # noqa: BLE001
        pass   # totp表不可达=按未绑定放行(绑定是增强不是锁死)
    import jwt
    now = dt.datetime.now(dt.timezone.utc)
    token = jwt.encode({"uid": u["id"], "username": u["username"], "role": u["role"], "sa": strong,
                        "iat": now, "exp": now + dt.timedelta(hours=config.JWT_TTL_HOURS)},
                       config.JWT_SECRET, algorithm="HS256")
    await pool.execute("UPDATE mix_users SET last_login=now() WHERE id=$1", u["id"])
    return {"access_token": token, "token_type": "bearer",
            "user_id": u["id"], "username": u["username"]}


@router.get("/auth/whoami")
async def whoami(who=Depends(require_viewer)):
    """三轨令牌自省（mixadmin 登录门校验用）：operator 令牌/只读令牌/用户 JWT 均可。"""
    from ..deps import is_strong_session
    return {"operator": who.get("operator"), "role": who.get("role"),
            "kind": who.get("kind", "operator"), "uid": who.get("uid"),
            "strong_session": is_strong_session(who)}


@router.get("/users/me")
async def users_me(who=Depends(_bearer_user)):
    return {"user_id": who.get("uid"), "username": who["operator"].removeprefix("user:"),
            "role": "user", "is_subaccount": False, "fund_view_enabled": True}


@router.get("/me/subaccount")
async def me_subaccount_banner(who=Depends(_bearer_user)):
    """用户端 banner 契约（auth store viewCaps 权威源）。自营阶段：主账户全权限。"""
    return {"is_sub": False, "multiplier": 1,
            "view_caps": {"fund_flow": True, "can_trade": True, "can_edit_account": True}}


def new_salt() -> str:
    return secrets.token_hex(16)


class UserCreate(BaseModel):
    username: str
    password: str
    role: str = "user"          # user|owner|admin（owner/admin=全量视角）
    scopes: list[str] = []      # 交易所范围白名单；普通用户零绑定=零数据


@router.post("/auth/users", status_code=201)
async def create_user(body: UserCreate, admin=Depends(require_admin)):
    """开户（SUPER_ADMIN）：建用户+绑定数据范围。默认拒绝：不绑=什么都看不到。"""
    pool = await ds.pg_main()
    if pool is None:
        raise HTTPException(503, "mix_main 未配置")
    # 角色校验对齐 mix_roles 表（含 operator/viewer 等,不再写死三值）
    valid = {r["role_key"] for r in await pool.fetch("SELECT role_key FROM mix_roles")}
    if not valid:
        valid = {"user", "owner", "admin", "operator", "viewer"}
    if body.role not in valid:
        raise HTTPException(400, f"role 必须是 {'/'.join(sorted(valid))} 之一")
    salt = new_salt()
    h = hash_password(body.password, salt)
    try:
        uid = await pool.fetchval(
            "INSERT INTO mix_users(username,password_hash,salt,role) VALUES($1,$2,$3,$4) RETURNING id",
            body.username.strip(), h, salt, body.role)
    except Exception:  # noqa: BLE001
        raise HTTPException(409, "用户名已存在")
    for v in body.scopes:
        await pool.execute(
            "INSERT INTO mix_user_scopes(user_id, venue) VALUES($1,$2) ON CONFLICT DO NOTHING", uid, v)
    return {"id": uid, "username": body.username, "role": body.role, "scopes": body.scopes}
