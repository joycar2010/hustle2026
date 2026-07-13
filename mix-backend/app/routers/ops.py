"""运营端点 —— 官网管理(site_config)/账户别名簿(accounts_registry)/LLM 状态/系统配置(状态+写操作)/操作员管理。
纪律不变：dcm/coin 域的写走代理；mix_main 是 mix 自有域可直写；系统写操作全审计。"""
import os
import ssl
import json
import asyncio
import logging
import datetime as dt

from fastapi import APIRouter, Depends, HTTPException

from ..deps import require_viewer, require_operator, require_admin
from .. import datasources as ds
from .. import proxy

log = logging.getLogger("mix.ops")
router = APIRouter(tags=["ops"])

BACKUP_DIR = "/data/mix/backups"


# ---------------- 官网管理（品牌热配置,Layout loadBrand 消费） ----------------
@router.get("/site/brand")
async def site_brand():
    """开放读（登录门渲染前需要品牌）。仅品牌字段,无敏感内容。"""
    pool = await ds.pg_main()
    if pool is None:
        return {}
    row = await pool.fetchrow("SELECT brand FROM site_config WHERE id=1")
    return json.loads(row["brand"]) if row and row["brand"] else {}


@router.put("/site/brand")
async def site_brand_put(body: dict, admin=Depends(require_admin)):
    pool = await ds.pg_main()
    if pool is None:
        raise HTTPException(503, "mix_main 未配置")
    allowed = {k: str(v)[:300] for k, v in body.items()
               if k in ("title", "loginTitle", "slogan", "logo", "docTitle",
                        "footer", "contact", "icp") and v is not None}
    await pool.execute("UPDATE site_config SET brand=$1, updated_by=$2, updated_at=now() WHERE id=1",
                       json.dumps(allowed, ensure_ascii=False), admin["admin"])
    await proxy.audit(admin["admin"], admin.get("role", ""), "site.brand", "site_config", allowed, "saved")
    return {"saved": True, "brand": allowed}


# ---------------- 账户别名簿 ----------------
@router.get("/accounts/registry")
async def registry_list(_who=Depends(require_viewer)):
    pool = await ds.pg_main()
    if pool is None:
        return []
    return [dict(r) for r in await pool.fetch(
        "SELECT account_key, alias, email, note, machine, enabled FROM accounts_registry")]


@router.put("/accounts/registry")
async def registry_put(body: dict, op=Depends(require_operator)):
    key = str(body.get("account_key") or "").strip()
    if not key:
        raise HTTPException(400, "account_key required")
    pool = await ds.pg_main()
    if pool is None:
        raise HTTPException(503, "mix_main 未配置")
    machine = str(body.get("machine") or "").upper()
    if machine and machine not in ("A", "B", "C"):
        raise HTTPException(400, "machine 必须是 A/B/C 或空")
    await pool.execute(
        "INSERT INTO accounts_registry(account_key, alias, email, note, machine, updated_at) "
        "VALUES($1,$2,$3,$4,$5,now()) ON CONFLICT (account_key) "
        "DO UPDATE SET alias=$2, email=$3, note=$4, machine=$5, updated_at=now()",
        key, str(body.get("alias") or ""), str(body.get("email") or ""), str(body.get("note") or ""), machine)
    await proxy.audit(op["operator"], op["role"], "registry.put", key, body, "saved")
    return {"saved": True}


# ---------------- LLM 状态（dcm llm-advisor 只读真状态） ----------------
@router.get("/system/llm")
async def llm_status(_who=Depends(require_viewer)):
    d = await ds.get_json("dcm:advisor:llm") or {}
    return {"status": d.get("status", "未配置"), "model": d.get("model"),
            "latency_ms": d.get("latency_ms"), "ts": d.get("ts"),
            "usage": d.get("usage"), "commentary": (d.get("commentary") or "")[:2000],
            "note": "评审层只读只建议(治理:schema硬校验+越界丢弃);key/模型改 C 机 llm-advisor env 后重启生效"}


@router.get("/system/llm/history")
async def llm_history(_who=Depends(require_viewer)):
    """建议历史（dcm_main.llm_advice_log 真账,mix_ro 只读）——shadow 对照证据链。"""
    rows = await ds.fetch(
        "SELECT ts, model, latency_ms, tokens, symbol, action, domain, reason "
        "FROM llm_advice_log ORDER BY ts DESC LIMIT 60")
    return [{**dict(r), "ts": r["ts"].strftime("%m-%d %H:%M")} for r in rows]


# ---------------- 系统配置：状态 + 写操作（备份/快照/SSL） ----------------
def _dir_listing(path: str) -> list[dict]:
    out = []
    try:
        for fn in sorted(os.listdir(path), reverse=True)[:20]:
            p = os.path.join(path, fn)
            out.append({"file": fn, "size_mb": round(os.path.getsize(p) / 1048576, 2),
                        "mtime": dt.datetime.fromtimestamp(os.path.getmtime(p)).strftime("%m-%d %H:%M")})
    except FileNotFoundError:
        pass
    return out


async def _ssl_expiry(host: str = "mixadmin.hustle2026.xyz") -> str:
    def _get():
        try:
            pem = ssl.get_server_certificate((host, 443), timeout=6)
            import subprocess
            r = subprocess.run(["openssl", "x509", "-noout", "-enddate"],
                               input=pem.encode(), capture_output=True, timeout=6)
            return r.stdout.decode().strip().replace("notAfter=", "")
        except Exception as e:  # noqa: BLE001
            return f"读取失败: {e}"
    return await asyncio.to_thread(_get)


@router.get("/system/status")
async def system_status(_who=Depends(require_viewer)):
    pool = await ds.pg_main()
    db = {}
    if pool:
        for name in ("mix_main", "dcm_main"):
            try:
                sz = await pool.fetchval("SELECT pg_size_pretty(pg_database_size($1))", name)
                db[name] = sz
            except Exception:  # noqa: BLE001
                db[name] = "—"
    services = {}
    for svc in ("mix-backend", "mix-ws"):
        services[svc] = "本进程" if svc == "mix-backend" else "见 systemd"
    return {
        "version": {"source_branch": "hustle2026:mix(源码权威,本地推送)",
                    "deployed_at": dt.datetime.fromtimestamp(
                        os.path.getmtime("/data/mix/backend/app/main.py")).strftime("%Y-%m-%d %H:%M")
                    if os.path.exists("/data/mix/backend/app/main.py") else "—"},
        "db": db,
        "ssl": {"cert_expiry": await _ssl_expiry(), "auto_renew": "certbot.timer(系统级)"},
        "backups": _dir_listing(BACKUP_DIR),
    }


async def _run(cmd: list[str], timeout=280) -> tuple[int, str]:
    def _go():
        import subprocess
        r = subprocess.run(cmd, capture_output=True, timeout=timeout)
        return r.returncode, (r.stdout + r.stderr).decode(errors="replace")[-800:]
    return await asyncio.to_thread(_go)


@router.post("/system/backup-db")
async def backup_db(admin=Depends(require_admin)):
    """pg_dump mix_main + dcm_main → /data/mix/backups（gzip）。"""
    os.makedirs(BACKUP_DIR, exist_ok=True)
    from .. import config
    ts = dt.datetime.now().strftime("%Y%m%d_%H%M")
    results = {}
    for name, dsn in (("mix_main", config.MAIN_DSN), ("dcm_main", config.PG_DSN)):
        if not dsn:
            results[name] = "DSN 未配置"
            continue
        out = f"{BACKUP_DIR}/{name}_{ts}.sql.gz"
        # pipefail 必须显式：否则管道退出码=gzip 的,pg_dump 失败会静默产出空备份(比没有备份更危险)
        code, msg = await _run(["bash", "-c", f"set -o pipefail; pg_dump '{dsn}' | gzip > {out}"])
        results[name] = f"ok {round(os.path.getsize(out)/1048576,2)}MB" if code == 0 and os.path.exists(out) \
            else f"fail: {msg[:200]}"
    await proxy.audit(admin["admin"], admin.get("role", ""), "system.backup_db", "pg_dump", {}, str(results))
    return {"results": results}


@router.post("/system/backup-snapshot")
async def backup_snapshot(admin=Depends(require_admin)):
    """部署产物快照（两 dist + backend 源）→ backups/。"""
    os.makedirs(BACKUP_DIR, exist_ok=True)
    ts = dt.datetime.now().strftime("%Y%m%d_%H%M")
    out = f"{BACKUP_DIR}/deploy_snapshot_{ts}.tgz"
    code, msg = await _run(["bash", "-c",
                            f"tar czf {out} -C /data/mix mixadmin-web/dist mix-web/dist backend/app backend/requirements.txt"])
    ok = code == 0 and os.path.exists(out)
    await proxy.audit(admin["admin"], admin.get("role", ""), "system.snapshot", out, {},
                      "ok" if ok else msg[:200])
    if not ok:
        raise HTTPException(500, f"快照失败: {msg[:200]}")
    return {"ok": True, "file": os.path.basename(out),
            "size_mb": round(os.path.getsize(out) / 1048576, 2),
            "note": "源码权威在 GitHub mix 分支(本地推送);此快照=服务器部署态备份"}


@router.post("/system/ssl-renew")
async def ssl_renew(admin=Depends(require_admin)):
    """certbot renew（未到期=no-op,安全;需 sudoers 白名单该命令）。"""
    code, msg = await _run(["sudo", "-n", "/usr/bin/certbot", "renew", "--no-random-sleep-on-renew"])
    await proxy.audit(admin["admin"], admin.get("role", ""), "system.ssl_renew", "certbot", {},
                      f"code={code}")
    return {"code": code, "output": msg[-600:]}


# ---------------- 操作员管理（dcm operators 只读 + mix_users 管理） ----------------
@router.get("/operators/all")
async def operators_all(_who=Depends(require_viewer)):
    ops = await ds.fetch("SELECT name, role, enabled, last_seen FROM operators ORDER BY id")
    pool = await ds.pg_main()
    users, scopes = [], {}
    if pool:
        users = [dict(r) for r in await pool.fetch(
            "SELECT id, username, role, enabled, last_login, created_at FROM mix_users ORDER BY id")]
        for r in await pool.fetch("SELECT user_id, venue FROM mix_user_scopes"):
            scopes.setdefault(r["user_id"], []).append(r["venue"])
    snaps = await ds.keys_values("dcm:account:*")
    equity = {k.rsplit(":", 1)[-1]: (v or {}).get("equity_usdt") for k, v in snaps.items()}
    for u in users:
        u["scopes"] = scopes.get(u["id"], [])
        u["scope_equity"] = round(sum(float(equity.get(v) or 0) for v in u["scopes"]), 2) \
            if u["scopes"] else (round(sum(float(x or 0) for x in equity.values()), 2)
                                 if u["role"] in ("owner", "admin") else 0)
        for k in ("last_login", "created_at"):
            if u.get(k):
                u[k] = u[k].strftime("%m-%d %H:%M")
    return {"operators": [{**dict(o), "last_seen": o["last_seen"].strftime("%m-%d %H:%M")
                           if o["last_seen"] else "—"} for o in ops],
            "users": users,
            "note": "operators=dcm 权威表(只读,增删经 dcm 控制台);users=mix 用户体系(可管理)"}


@router.put("/operators/users/{uid}")
async def user_update(uid: int, body: dict, admin=Depends(require_admin)):
    pool = await ds.pg_main()
    if pool is None:
        raise HTTPException(503, "mix_main 未配置")
    if "enabled" in body:
        await pool.execute("UPDATE mix_users SET enabled=$2 WHERE id=$1", uid, bool(body["enabled"]))
    if body.get("role") in ("user", "operator", "admin", "owner"):
        await pool.execute("UPDATE mix_users SET role=$2 WHERE id=$1", uid, body["role"])
    if body.get("password"):
        from .auth import hash_password, new_salt
        salt = new_salt()
        await pool.execute("UPDATE mix_users SET password_hash=$2, salt=$3 WHERE id=$1",
                           uid, hash_password(str(body["password"]), salt), salt)
    if isinstance(body.get("scopes"), list):
        await pool.execute("DELETE FROM mix_user_scopes WHERE user_id=$1", uid)
        for v in body["scopes"]:
            await pool.execute(
                "INSERT INTO mix_user_scopes(user_id, venue) VALUES($1,$2) ON CONFLICT DO NOTHING",
                uid, str(v))
    await proxy.audit(admin["admin"], admin.get("role", ""), "user.update", f"uid:{uid}",
                      {k: body[k] for k in body if k != "password"}, "saved")
    return {"saved": True}
