"""WebAuthn/Passkey 真实现(V6 §7:高危动作重新认证;平板/手机两步确认第二步)。

依赖 py_webauthn(服务器 venv 安装 webauthn 包);未安装时诚实 501,前端回落 TOTP。
- 凭证表 operator_webauthn_credential(mix_main,auto-DDL);
- 挑战存 Redis 120s 一次性;
- 认证成功→签发 10 分钟 reauth ticket(Redis)——proposal 审批/维护启动可凭 ticket 代替 TOTP。
RP ID 走 env(MIX_WEBAUTHN_RP_ID)——域名重排(管理端迁 mix.hustle2026.xyz)时改配置不改码;
⚠RP 变更后已注册 Passkey 全部作废,须新域重注册(WebAuthn 协议约束),TOTP 过渡不断审批。
"""
import os
import json
import base64
import secrets
import logging

from fastapi import APIRouter, Depends, HTTPException

from ..deps import require_operator
from .. import datasources as ds

log = logging.getLogger("mix.webauthn")
router = APIRouter(tags=["webauthn"])

RP_ID = os.environ.get("MIX_WEBAUTHN_RP_ID", "mix.hustle2026.xyz")
ORIGIN = f"https://{RP_ID}"

_DDL = """CREATE TABLE IF NOT EXISTS operator_webauthn_credential (
    id BIGSERIAL PRIMARY KEY,
    operator TEXT NOT NULL,
    credential_id TEXT NOT NULL UNIQUE,
    public_key TEXT NOT NULL,
    sign_count BIGINT NOT NULL DEFAULT 0,
    device_label TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now())"""


def _wa():
    try:
        import webauthn  # noqa: F401
        return webauthn
    except Exception:  # noqa: BLE001
        raise HTTPException(501, "WebAuthn 依赖未安装(pip install webauthn);请先用 TOTP 二次认证")


async def _pool():
    p = await ds.pg_main()
    if p is None:
        raise HTTPException(503, "mix_main 不可达")
    await p.execute(_DDL)
    return p


def _b64(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def _unb64(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


@router.post("/webauthn/register/options")
async def register_options(op=Depends(require_operator)):
    wa = _wa()
    from webauthn.helpers.structs import (PublicKeyCredentialDescriptor,
                                          AuthenticatorSelectionCriteria,
                                          UserVerificationRequirement)
    pool = await _pool()
    exclude = [PublicKeyCredentialDescriptor(id=_unb64(r["credential_id"]))
               for r in await pool.fetch(
                   "SELECT credential_id FROM operator_webauthn_credential WHERE operator=$1",
                   op["operator"])]
    opts = wa.generate_registration_options(
        rp_id=RP_ID, rp_name="HustleMix Admin",
        user_name=op["operator"], user_id=op["operator"].encode(),
        exclude_credentials=exclude,
        authenticator_selection=AuthenticatorSelectionCriteria(
            user_verification=UserVerificationRequirement.PREFERRED))
    r = ds.rds()
    await r.set(f"mix:webauthn:reg:{op['operator']}", _b64(opts.challenge), ex=120)
    return json.loads(wa.options_to_json(opts))


@router.post("/webauthn/register/verify")
async def register_verify(body: dict, op=Depends(require_operator)):
    wa = _wa()
    r = ds.rds()
    ch = await r.get(f"mix:webauthn:reg:{op['operator']}")
    if not ch:
        raise HTTPException(400, "挑战过期,重新发起注册")
    try:
        ver = wa.verify_registration_response(
            credential=body.get("credential"), expected_challenge=_unb64(ch),
            expected_origin=ORIGIN, expected_rp_id=RP_ID)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(400, f"注册校验失败:{e}")
    pool = await _pool()
    await pool.execute(
        "INSERT INTO operator_webauthn_credential(operator, credential_id, public_key, sign_count, device_label) "
        "VALUES($1,$2,$3,$4,$5) ON CONFLICT (credential_id) DO NOTHING",
        op["operator"], _b64(ver.credential_id), _b64(ver.credential_public_key),
        int(ver.sign_count), str(body.get("device_label") or "")[:60])
    await r.delete(f"mix:webauthn:reg:{op['operator']}")
    return {"registered": True, "credential_id": _b64(ver.credential_id)}


@router.post("/webauthn/auth/options")
async def auth_options(op=Depends(require_operator)):
    wa = _wa()
    from webauthn.helpers.structs import PublicKeyCredentialDescriptor, UserVerificationRequirement
    pool = await _pool()
    creds = await pool.fetch(
        "SELECT credential_id FROM operator_webauthn_credential WHERE operator=$1", op["operator"])
    if not creds:
        raise HTTPException(404, "尚未注册 Passkey(先在系统配置·二次认证注册)")
    opts = wa.generate_authentication_options(
        rp_id=RP_ID,
        allow_credentials=[PublicKeyCredentialDescriptor(id=_unb64(c["credential_id"])) for c in creds],
        user_verification=UserVerificationRequirement.PREFERRED)
    r = ds.rds()
    await r.set(f"mix:webauthn:auth:{op['operator']}", _b64(opts.challenge), ex=120)
    return json.loads(wa.options_to_json(opts))


@router.post("/webauthn/auth/verify")
async def auth_verify(body: dict, op=Depends(require_operator)):
    """认证成功→10 分钟 reauth ticket(高危动作可凭 ticket 代替 TOTP)。"""
    wa = _wa()
    r = ds.rds()
    ch = await r.get(f"mix:webauthn:auth:{op['operator']}")
    if not ch:
        raise HTTPException(400, "挑战过期,重新发起")
    cred = body.get("credential") or {}
    cid = str(cred.get("id") or "")
    pool = await _pool()
    row = await pool.fetchrow(
        "SELECT public_key, sign_count FROM operator_webauthn_credential "
        "WHERE operator=$1 AND credential_id=$2", op["operator"], cid)
    if not row:
        raise HTTPException(403, "凭证不属于当前操作员")
    try:
        ver = wa.verify_authentication_response(
            credential=cred, expected_challenge=_unb64(ch),
            expected_origin=ORIGIN, expected_rp_id=RP_ID,
            credential_public_key=_unb64(row["public_key"]),
            credential_current_sign_count=int(row["sign_count"]))
    except Exception as e:  # noqa: BLE001
        raise HTTPException(403, f"认证失败:{e}")
    await pool.execute(
        "UPDATE operator_webauthn_credential SET sign_count=$1 WHERE operator=$2 AND credential_id=$3",
        int(ver.new_sign_count), op["operator"], cid)
    ticket = secrets.token_hex(24)
    await r.set(f"mix:reauth:{op['operator']}:{ticket}", "1", ex=600)
    await r.delete(f"mix:webauthn:auth:{op['operator']}")
    return {"ok": True, "reauth_ticket": ticket, "ttl_sec": 600}


@router.get("/webauthn/credentials")
async def credentials_list(op=Depends(require_operator)):
    pool = await _pool()
    rows = await pool.fetch(
        "SELECT id, credential_id, device_label, sign_count, created_at::text "
        "FROM operator_webauthn_credential WHERE operator=$1 ORDER BY id", op["operator"])
    return [dict(r) for r in rows]


@router.delete("/webauthn/credentials/{cid}")
async def credentials_delete(cid: int, op=Depends(require_operator)):
    pool = await _pool()
    n = await pool.execute("DELETE FROM operator_webauthn_credential WHERE id=$1 AND operator=$2",
                           cid, op["operator"])
    return {"deleted": n.endswith("1")}


async def check_reauth_ticket(operator: str, ticket: str) -> bool:
    """供 proposal 审批/维护启动复用:WebAuthn ticket 与 TOTP 二选一。一次性。"""
    if not ticket:
        return False
    r = ds.rds()
    try:
        key = f"mix:reauth:{operator}:{ticket}"
        ok = await r.get(key)
        if ok:
            await r.delete(key)
            return True
    except Exception:  # noqa: BLE001
        pass
    return False
