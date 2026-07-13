"""
鉴权依赖 —— 复用 dcm_main.operators 表（sha256 令牌，VIEWER < OPERATOR < SUPER_ADMIN），
不发明第三套身份体系。另支持 MIX_READONLY_TOKEN（.env）作为 VIEWER 级只读令牌。
读端点 require_viewer；写端点 require_operator/require_admin（P0 写路径未接线，过鉴权后 501）。
"""
import hashlib
from fastapi import Header, HTTPException, Query

from . import config
from . import datasources as ds

_ROLE_RANK = {"VIEWER": 0, "OPERATOR": 1, "SUPER_ADMIN": 2}


async def _resolve(token: str | None) -> dict | None:
    if not token:
        return None
    if config.READONLY_TOKEN and token == config.READONLY_TOKEN:
        return {"operator": "readonly-token", "role": "VIEWER"}
    h = hashlib.sha256(token.encode()).hexdigest()
    rows = await ds.fetch(
        "SELECT name, role FROM operators WHERE token_hash = $1 AND enabled", h)
    if rows:
        return {"operator": rows[0]["name"], "role": rows[0]["role"]}
    return None


def _jwt_decode(token: str | None) -> dict | None:
    """mix 用户端 JWT（HS256，独立用户体系）→ VIEWER 级身份。"""
    if not token or not config.JWT_SECRET:
        return None
    try:
        import jwt
        p = jwt.decode(token, config.JWT_SECRET, algorithms=["HS256"])
        return {"operator": f"user:{p.get('username')}", "role": "VIEWER",
                "uid": p.get("uid"), "urole": p.get("role", "user"), "kind": "mix_user"}
    except Exception:  # noqa: BLE001
        return None


async def _resolve_any(token: str | None) -> dict | None:
    """operator/只读令牌 → 否则试 mix 用户 JWT。"""
    return await _resolve(token) or _jwt_decode(token)


async def require_viewer(
    x_op_token: str | None = Header(default=None),
    authorization: str | None = Header(default=None),
    token: str = Query(default=""),
) -> dict:
    """读端点门槛：X-Op-Token（operator/只读令牌）或 Authorization: Bearer（mix 用户 JWT）。"""
    bearer = None
    if authorization and authorization.lower().startswith("bearer "):
        bearer = authorization[7:].strip()
    who = await _resolve_any(x_op_token or token or bearer)
    if not who:
        raise HTTPException(401, "缺少或无效访问令牌：X-Op-Token 或 Authorization: Bearer")
    return who


async def require_operator(x_op_token: str | None = Header(default=None)) -> dict:
    who = await _resolve(x_op_token)
    if not who:
        raise HTTPException(401, "missing operator token")
    if _ROLE_RANK.get(who["role"], 0) < _ROLE_RANK["OPERATOR"]:
        raise HTTPException(403, f"需要 OPERATOR 权限（当前 {who['role']}）")
    return {**who, "token": x_op_token}   # token 供写代理透传(gateway 审计留操作者身份)


async def require_admin(x_op_token: str | None = Header(default=None)) -> dict:
    who = await _resolve(x_op_token)
    if not who:
        raise HTTPException(401, "missing admin token")
    if _ROLE_RANK.get(who["role"], 0) < _ROLE_RANK["SUPER_ADMIN"]:
        raise HTTPException(403, f"需要 SUPER_ADMIN 权限（当前 {who['role']}）")
    return {"admin": who["operator"], **who}


async def require_wall_token(token: str = Query(default="")) -> str:
    """三分屏墙 /wall/* 免登录只读令牌（VIEWER 级）。"""
    who = await _resolve(token)
    if not who:
        raise HTTPException(403, "wall token required")
    return token


def enforce_view(view: str = Query(...)) -> str:
    """merged/self 口径必须显式 —— 历史事故：默认 merged 泄漏到交易面板。"""
    if view not in ("merged", "self"):
        raise HTTPException(400, "view must be merged|self（口径必须显式，无默认）")
    return view


def not_wired(what: str):
    """P0 写路径诚实拒绝：绝不假 202。写操作 P2 按代理制接入引擎权威 API。"""
    raise HTTPException(501, f"{what}：写路径尚未接线（P2 代理到引擎权威 API），本次操作未执行")
