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


# ---------------- LLM 状态 + 中转站管理 + 每日消费（testauto /infra 模式移植） ----------------
# 权威=mix_main.llm_relays;生效链路=Redis dcm:llm:config(llm-advisor 每轮热读,主备自动降级);
# 熔断态=dcm:llm:breaker(advisor 维护,手动恢复=DEL);用量账=dcm_main.llm_usage_log(0013,mix_ro 读)。

_LLM_HEALTH_KEYS = ("primary_model", "primary_relay", "fallback_model", "circuit_open",
                    "open_until", "recent_failures", "failure_threshold",
                    "consecutive_trips", "current_cooldown_s", "relay", "degraded")


@router.get("/system/llm")
async def llm_status(_who=Depends(require_viewer)):
    d = await ds.get_json("dcm:advisor:llm") or {}
    return {"status": d.get("status", "未配置"), "model": d.get("model"),
            "latency_ms": d.get("latency_ms"), "ts": d.get("ts"),
            "usage": d.get("usage"), "commentary": (d.get("commentary") or "")[:2000],
            **{k: d.get(k) for k in _LLM_HEALTH_KEYS},
            "note": "评审层只读只建议(schema硬校验+越界丢弃);模型/中转站在下方管理区热改,advisor 每轮(15min)生效"}


def _mask_key(k: str) -> str:
    k = str(k or "")
    return (k[:6] + "***" + k[-4:]) if len(k) > 12 else ("***" if k else "")


async def _publish_llm_config(pool):
    """发布全量中转站配置到总线(含明文 key——总线仅内网;UI 响应永远掩码)。"""
    r = ds.rds()
    rows = await pool.fetch("SELECT * FROM llm_relays ORDER BY (role!='primary'), id")
    relays = [{"id": x["id"], "name": x["name"], "base_url": x["base_url"],
               "api_key": x["api_key"], "model": x["model"], "role": x["role"],
               "enabled": x["enabled"]} for x in rows]
    import time as _t
    await r.set("dcm:llm:config", json.dumps({"ts": int(_t.time()), "relays": relays},
                                             ensure_ascii=False))
    return len(relays)


def _relay_row(x) -> dict:
    fetched = json.loads(x["available_models"]) if x["available_models"] else []
    custom = json.loads(x["custom_models"]) if x["custom_models"] else []
    return {"id": x["id"], "name": x["name"], "base_url": x["base_url"],
            "api_key_masked": _mask_key(x["api_key"]), "model": x["model"],
            "role": x["role"], "enabled": x["enabled"],
            # 可选列表 = 中转站 /models 拉取 ∪ 手动加入(未上架模型占位,刷新永不丢)
            "available_models": sorted(set(fetched) | set(custom)),
            "custom_models": custom,
            "price_in_per_m": float(x["price_in_per_m"]), "price_out_per_m": float(x["price_out_per_m"]),
            "note": x["note"]}


@router.get("/system/llm/relays")
async def llm_relays(_who=Depends(require_viewer)):
    pool = await ds.pg_main()
    if pool is None:
        return {"items": []}
    rows = await pool.fetch("SELECT * FROM llm_relays ORDER BY (role!='primary'), id")
    return {"items": [_relay_row(x) for x in rows]}


@router.post("/system/llm/relays", status_code=201)
async def llm_relay_add(body: dict, op=Depends(require_operator)):
    pool = await ds.pg_main()
    name = str(body.get("name") or "").strip()
    base = str(body.get("base_url") or "").strip().rstrip("/")
    key = str(body.get("api_key") or "").strip()
    model = str(body.get("model") or "").strip()
    if not (name and base and key and model):
        raise HTTPException(400, "name/base_url/api_key/model 必填")
    row = await pool.fetchrow(
        "INSERT INTO llm_relays(name,base_url,api_key,model,role,enabled) "
        "VALUES($1,$2,$3,$4,'backup',TRUE) RETURNING *", name, base, key, model)
    n = await _publish_llm_config(pool)
    await proxy.audit(op["operator"], op["role"], "llm.relay.add", name,
                      {"base_url": base, "model": model}, f"published {n}")
    return {"ok": True, "item": _relay_row(row)}


@router.put("/system/llm/relays/{rid}")
async def llm_relay_put(rid: int, body: dict, op=Depends(require_operator)):
    pool = await ds.pg_main()
    cur = await pool.fetchrow("SELECT * FROM llm_relays WHERE id=$1", rid)
    if not cur:
        raise HTTPException(404, "中转站不存在")
    key = str(body.get("api_key") or "").strip() or cur["api_key"]   # 空=保留原 key
    custom = body.get("custom_models")
    if not isinstance(custom, list):
        custom = json.loads(cur["custom_models"]) if cur["custom_models"] else []
    custom = sorted({str(m).strip() for m in custom if str(m).strip()})[:40]
    await pool.execute(
        "UPDATE llm_relays SET name=$2, base_url=$3, api_key=$4, model=$5, "
        "price_in_per_m=$6, price_out_per_m=$7, note=$8, custom_models=$9, updated_at=now() WHERE id=$1",
        rid, str(body.get("name") or cur["name"]),
        str(body.get("base_url") or cur["base_url"]).rstrip("/"), key,
        str(body.get("model") or cur["model"]),
        float(body.get("price_in_per_m") if body.get("price_in_per_m") is not None else cur["price_in_per_m"]),
        float(body.get("price_out_per_m") if body.get("price_out_per_m") is not None else cur["price_out_per_m"]),
        str(body.get("note") if body.get("note") is not None else cur["note"]),
        json.dumps(custom))
    n = await _publish_llm_config(pool)
    await proxy.audit(op["operator"], op["role"], "llm.relay.save", cur["name"],
                      {"model": body.get("model")}, f"published {n}")
    return {"ok": True}


@router.delete("/system/llm/relays/{rid}")
async def llm_relay_del(rid: int, op=Depends(require_operator)):
    pool = await ds.pg_main()
    cur = await pool.fetchrow("DELETE FROM llm_relays WHERE id=$1 RETURNING name", rid)
    if not cur:
        raise HTTPException(404, "中转站不存在")
    n = await _publish_llm_config(pool)
    await proxy.audit(op["operator"], op["role"], "llm.relay.del", cur["name"], {}, f"published {n}")
    return {"ok": True}


@router.post("/system/llm/relays/{rid}/set-role")
async def llm_relay_role(rid: int, body: dict, op=Depends(require_operator)):
    """设主站:其余全部降备(主站唯一)。"""
    pool = await ds.pg_main()
    if str(body.get("role")) != "primary":
        raise HTTPException(400, "只支持 role=primary(备用=默认态)")
    async with pool.acquire() as c, c.transaction():
        await c.execute("UPDATE llm_relays SET role='backup', updated_at=now() WHERE role='primary'")
        got = await c.execute("UPDATE llm_relays SET role='primary', enabled=TRUE, updated_at=now() WHERE id=$1", rid)
        if got.endswith("0"):
            raise HTTPException(404, "中转站不存在")
    n = await _publish_llm_config(pool)
    await proxy.audit(op["operator"], op["role"], "llm.relay.primary", str(rid), {}, f"published {n}")
    return {"ok": True}


@router.post("/system/llm/relays/{rid}/toggle")
async def llm_relay_toggle(rid: int, body: dict, op=Depends(require_operator)):
    pool = await ds.pg_main()
    await pool.execute("UPDATE llm_relays SET enabled=$2, updated_at=now() WHERE id=$1",
                       rid, bool(body.get("enabled")))
    n = await _publish_llm_config(pool)
    await proxy.audit(op["operator"], op["role"], "llm.relay.toggle", str(rid),
                      {"enabled": bool(body.get("enabled"))}, f"published {n}")
    return {"ok": True}


@router.post("/system/llm/relays/{rid}/refresh-models")
async def llm_relay_models(rid: int, op=Depends(require_operator)):
    """真调该站 /models 刷新可选模型列表(openai 兼容)。"""
    import httpx
    pool = await ds.pg_main()
    cur = await pool.fetchrow("SELECT * FROM llm_relays WHERE id=$1", rid)
    if not cur:
        raise HTTPException(404, "中转站不存在")
    resp = None
    try:
        async with httpx.AsyncClient(timeout=15) as cli:
            resp = await cli.get(f"{cur['base_url']}/models",
                                 headers={"Authorization": f"Bearer {cur['api_key']}"})
        models = sorted({str(m.get("id")) for m in (resp.json().get("data") or []) if m.get("id")})
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": f"{e!r}"[:200]}
    if not models:
        return {"ok": False, "error": f"http {resp.status_code}: {resp.text[:150]}"}
    await pool.execute("UPDATE llm_relays SET available_models=$2, updated_at=now() WHERE id=$1",
                       rid, json.dumps(models))
    custom = json.loads(cur["custom_models"]) if cur["custom_models"] else []
    return {"ok": True, "count": len(models),
            "available_models": sorted(set(models) | set(custom))}


@router.post("/system/llm/circuit-reset")
async def llm_circuit_reset(op=Depends(require_operator)):
    """手动恢复熔断(advisor 下轮照常调用)。"""
    r = ds.rds()
    await r.delete("dcm:llm:breaker")
    await proxy.audit(op["operator"], op["role"], "llm.circuit.reset", "dcm:llm:breaker", {}, "ok")
    return {"ok": True}


@router.get("/system/llm/usage-daily")
async def llm_usage_daily(days: int = 14, _who=Depends(require_viewer)):
    """每日消费明细(dcm_main.llm_usage_log 真账):逐日 调用/tokens/延迟/失败 + 按中转站单价折算成本。"""
    days = max(1, min(days, 90))
    pool = await ds.pg_main()
    prices = {}
    if pool is not None:
        for x in await pool.fetch("SELECT name, price_in_per_m, price_out_per_m FROM llm_relays"):
            prices[x["name"]] = (float(x["price_in_per_m"]), float(x["price_out_per_m"]))
    rows = await ds.fetch(
        "SELECT ts::date d, relay, model, count(*) calls, count(*) FILTER (WHERE NOT ok) fails, "
        "sum(tokens_in) tin, sum(tokens_out) tout, avg(latency_ms)::int lat "
        "FROM llm_usage_log WHERE ts > now() - ($1 || ' days')::interval "
        "GROUP BY 1,2,3 ORDER BY 1 DESC, 4 DESC", str(days))
    out = []
    for x in rows:
        pin, pout = prices.get(x["relay"], (0.5, 1.5))
        tin, tout = int(x["tin"] or 0), int(x["tout"] or 0)
        out.append({"date": str(x["d"]), "relay": x["relay"], "model": x["model"],
                    "calls": int(x["calls"]), "fails": int(x["fails"]),
                    "tokens_in": tin, "tokens_out": tout,
                    "avg_latency_ms": int(x["lat"] or 0),
                    "cost_usd": round(tin / 1e6 * pin + tout / 1e6 * pout, 4)})
    return {"days": days, "rows": out,
            "note": "成本=tokens×中转站单价(默认in $0.5/M,out $1.5/M,可在中转站条目改)"}


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


# ---------------- 角色权限矩阵（mix_roles：自定义角色→可见模块） ----------------
@router.get("/operators/roles")
async def roles_list(_who=Depends(require_viewer)):
    pool = await ds.pg_main()
    if pool is None:
        return []
    import json as _json
    return [{**dict(r), "modules": _json.loads(r["modules"]) if isinstance(r["modules"], str) else r["modules"]}
            for r in await pool.fetch("SELECT role_key, name, modules, is_builtin FROM mix_roles ORDER BY role_key")]


@router.put("/operators/roles")
async def role_put(body: dict, admin=Depends(require_admin)):
    import json as _json
    rk = str(body.get("role_key") or "").strip()
    if not rk:
        raise HTTPException(400, "role_key required")
    pool = await ds.pg_main()
    if pool is None:
        raise HTTPException(503, "mix_main 未配置")
    await pool.execute(
        "INSERT INTO mix_roles(role_key,name,modules,updated_by,updated_at) VALUES($1,$2,$3,$4,now()) "
        "ON CONFLICT (role_key) DO UPDATE SET name=$2, modules=$3, updated_by=$4, updated_at=now() "
        "WHERE mix_roles.is_builtin=false OR mix_roles.role_key=$1",
        rk, str(body.get("name") or "")[:40], _json.dumps(body.get("modules") or []), admin["admin"])
    await proxy.audit(admin["admin"], admin.get("role", ""), "role.put", rk, body, "saved")
    return {"saved": True}


@router.delete("/operators/roles/{role_key}")
async def role_del(role_key: str, admin=Depends(require_admin)):
    pool = await ds.pg_main()
    if pool is None:
        raise HTTPException(503, "mix_main 未配置")
    n = await pool.execute("DELETE FROM mix_roles WHERE role_key=$1 AND is_builtin=false", role_key)
    if n.endswith("0"):
        raise HTTPException(400, "内置角色不可删")
    await proxy.audit(admin["admin"], admin.get("role", ""), "role.del", role_key, {}, "deleted")
    return {"deleted": True}


@router.get("/operators/audit")
async def operators_audit(_who=Depends(require_viewer)):
    """操作员行为日志（admin_audit 全量,最近 80 条）。"""
    rows = await ds.fetch(
        "SELECT ts, operator, role, action, target, result FROM admin_audit ORDER BY ts DESC LIMIT 80")
    return [{"at": r["ts"].strftime("%m-%d %H:%M:%S"), "operator": r["operator"], "role": r["role"],
             "action": r["action"], "target": r["target"], "result": str(r["result"])[:120]} for r in rows]


@router.put("/operators/users/{uid}")
async def user_update(uid: int, body: dict, admin=Depends(require_admin)):
    pool = await ds.pg_main()
    if pool is None:
        raise HTTPException(503, "mix_main 未配置")
    if "enabled" in body:
        await pool.execute("UPDATE mix_users SET enabled=$2 WHERE id=$1", uid, bool(body["enabled"]))
    if body.get("role") in ("user", "operator", "admin", "owner", "viewer"):
        await pool.execute("UPDATE mix_users SET role=$2 WHERE id=$1", uid, body["role"])
    if "ip_whitelist" in body:
        await pool.execute("UPDATE mix_users SET ip_whitelist=$2 WHERE id=$1",
                           uid, str(body["ip_whitelist"] or "")[:400])
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
