"""账户簿 + API 凭证托管（浏览器端加密专场,用户拍板方案一）。

密钥纪律铁律：
  - 明文 key/secret 永不进 mix-backend 内存,永不进 DB——前端用 B 机公钥 sealed box 加密后才提交;
  - 服务端只存密文(ciphertext)+掩码(key_mask);私钥只在 B 机 ~/dexcexmix/.mix_cred_key(600);
  - B 机 cred-agent(systemd,60s 轮询)拉密文→本机解密→写 account-snapshot/引擎 .env→验证回写 active;
  - 网页只显示掩码;删除=state=revoked,agent 下发吊销;全程 admin_audit。
IP 代理出口(proxy_url)随凭证存,agent 落到该账户的交易客户端 httpx proxies(直连=空)。"""
import time

from fastapi import APIRouter, Depends, HTTPException

from ..deps import require_operator, require_admin, require_viewer
from .. import datasources as ds
from .. import proxy as _proxy

router = APIRouter(tags=["credentials"])

# B 机 sealed box 公钥(私钥只在 B 机;换机=重生成+更新此处并重录密文)
CRED_PUBKEY = "JHd3LodOmDV1537xn4OSxsLbCAjiG4Kg6nl0zgAJPmc="


@router.get("/credentials/pubkey")
async def cred_pubkey(_who=Depends(require_operator)):
    """前端 libsodium sealed box 加密用公钥(明文永不离开浏览器)。"""
    return {"pubkey": CRED_PUBKEY, "algo": "nacl.sealedbox(curve25519)",
            "note": "明文=key\\nsecret\\npassphrase;前端加密后提交 ciphertext"}


@router.get("/credentials")
async def cred_list(_who=Depends(require_viewer)):
    pool = await ds.pg_main()
    if pool is None:
        return []
    return [dict(r) for r in await pool.fetch(
        "SELECT account_key, venue, label, key_mask, proxy_url, state, applied_detail, updated_at "
        "FROM api_credentials ORDER BY account_key")]


@router.put("/credentials")
async def cred_put(body: dict, admin=Depends(require_admin)):
    """录入/更新密文(SUPER_ADMIN)。ciphertext 由前端 sealed box 生成,后端不解密只落库。"""
    key = str(body.get("account_key") or "").strip()
    ct = str(body.get("ciphertext") or "")
    if not key or not ct:
        raise HTTPException(400, "account_key 与 ciphertext 必填(密文=前端加密)")
    if len(ct) > 4000 or "\n" in body.get("plaintext_leak", ""):
        raise HTTPException(400, "非法密文")
    pool = await ds.pg_main()
    if pool is None:
        raise HTTPException(503, "mix_main 未配置")
    await pool.execute(
        "INSERT INTO api_credentials(account_key,venue,label,key_mask,ciphertext,proxy_url,state,created_by,updated_at) "
        "VALUES($1,$2,$3,$4,$5,$6,'pending',$7,now()) ON CONFLICT (account_key) DO UPDATE SET "
        "venue=$2, label=$3, key_mask=$4, ciphertext=$5, proxy_url=$6, state='pending', updated_at=now()",
        key, str(body.get("venue") or "")[:40], str(body.get("label") or "")[:80],
        str(body.get("key_mask") or "")[:40], ct, str(body.get("proxy_url") or "")[:200], admin["admin"])
    await _proxy.audit(admin["admin"], admin.get("role", ""), "credential.put", key,
                       {"venue": body.get("venue"), "mask": body.get("key_mask"),
                        "proxy": bool(body.get("proxy_url"))}, "pending(待 B 机 agent 生效)")
    return {"saved": True, "state": "pending",
            "note": "密文已落库(明文从未经过服务端);B 机 cred-agent 60s 内解密下发并验证回写 active"}


@router.put("/credentials/{account_key}/proxy")
async def cred_proxy(account_key: str, body: dict, admin=Depends(require_admin)):
    """单独改 IP 代理出口(不动密文)。空=直连。"""
    pool = await ds.pg_main()
    if pool is None:
        raise HTTPException(503, "mix_main 未配置")
    n = await pool.execute("UPDATE api_credentials SET proxy_url=$2, state='pending', updated_at=now() "
                           "WHERE account_key=$1", account_key, str(body.get("proxy_url") or "")[:200])
    if n.endswith("0"):
        raise HTTPException(404, "该账户无凭证记录(先设置 API)")
    await _proxy.audit(admin["admin"], admin.get("role", ""), "credential.proxy", account_key,
                       {"proxy": bool(body.get("proxy_url"))}, "pending")
    return {"saved": True, "note": "代理已更新,agent 下发到该账户交易客户端"}


@router.delete("/credentials/{account_key}")
async def cred_del(account_key: str, admin=Depends(require_admin)):
    pool = await ds.pg_main()
    if pool is None:
        raise HTTPException(503, "mix_main 未配置")
    await pool.execute("UPDATE api_credentials SET state='revoked', updated_at=now() WHERE account_key=$1",
                       account_key)
    await _proxy.audit(admin["admin"], admin.get("role", ""), "credential.revoke", account_key, {}, "revoked")
    return {"revoked": True, "note": "已置吊销;B 机 agent 下轮从 .env 清除该账户 key"}


# ---------------- 账户簿(主/子模型) ----------------
@router.get("/accounts/registry-tree")
async def registry_tree(_who=Depends(require_viewer)):
    """主/子账户簿:master 行 + 挂在其下的 sub 行;含凭证状态。"""
    pool = await ds.pg_main()
    if pool is None:
        return []
    rows = [dict(r) for r in await pool.fetch(
        "SELECT account_key, alias, email, note, machine, enabled, account_type, parent_key FROM accounts_registry")]
    creds = {}
    for c in await pool.fetch("SELECT account_key, key_mask, state, proxy_url FROM api_credentials"):
        creds[c["account_key"]] = dict(c)
    for r in rows:
        r["credential"] = creds.get(r["account_key"])
    masters = [r for r in rows if r["account_type"] == "master"]
    subs = [r for r in rows if r["account_type"] == "sub"]
    for m in masters:
        m["children"] = [s for s in subs if s["parent_key"] == m["account_key"]]
    # 孤儿子账户(parent 未建主行)：按 venue 归到虚拟主行
    orphan = [s for s in subs if not any(s["parent_key"] == m["account_key"] for m in masters)]
    return {"masters": masters, "orphans": orphan}


@router.post("/accounts/registry-full")
async def registry_full(body: dict, op=Depends(require_operator)):
    """新建账户(主/子)+可选别名/邮箱;API Key 走独立 credentials(浏览器加密),此处只落账户簿元数据。"""
    key = str(body.get("account_key") or "").strip()
    if not key:
        raise HTTPException(400, "account_key required")
    atype = body.get("account_type") if body.get("account_type") in ("master", "sub") else "master"
    pool = await ds.pg_main()
    if pool is None:
        raise HTTPException(503, "mix_main 未配置")
    await pool.execute(
        "INSERT INTO accounts_registry(account_key,alias,email,note,machine,account_type,parent_key,updated_at) "
        "VALUES($1,$2,$3,$4,$5,$6,$7,now()) ON CONFLICT (account_key) DO UPDATE SET "
        "alias=$2, email=$3, note=$4, machine=$5, account_type=$6, parent_key=$7, updated_at=now()",
        key, str(body.get("alias") or "")[:80], str(body.get("email") or "")[:120],
        str(body.get("note") or "")[:200], str(body.get("machine") or "").upper()[:1],
        atype, str(body.get("parent_key") or "")[:80] if atype == "sub" else "")
    await _proxy.audit(op["operator"], op["role"], "account.create", key,
                       {"type": atype, "parent": body.get("parent_key")}, "saved")
    return {"saved": True, "hint": "如需交易能力,右键「设置 API…」录入密钥(浏览器端加密)"}
