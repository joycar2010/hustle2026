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


# ---------------- 官网 CMS 内容区块（用户端登录框/品牌头可配,site_blocks 表） ----------------
_BLOCK_KEYS = ("user_login", "user_brand")


@router.get("/site/config")
async def site_config():
    """开放读——用户端登录页/品牌头渲染前需要(仅品牌与文案区块,无敏感内容)。"""
    pool = await ds.pg_main()
    if pool is None:
        return {"brand": {}, "blocks": {}}
    row = await pool.fetchrow("SELECT brand FROM site_config WHERE id=1")
    blocks: dict = {}
    try:
        for r in await pool.fetch("SELECT block_key, content FROM site_blocks"):
            blocks[r["block_key"]] = json.loads(r["content"]) if r["content"] else {}
    except Exception:  # 表未迁移=空区块,前端回落硬编码默认,老行为不变
        blocks = {}
    return {"brand": json.loads(row["brand"]) if row and row["brand"] else {}, "blocks": blocks}


@router.put("/site/blocks/{key}")
async def site_block_put(key: str, body: dict, admin=Depends(require_admin)):
    if key not in _BLOCK_KEYS:
        raise HTTPException(400, f"未知区块 {key}(可用:{','.join(_BLOCK_KEYS)})")
    pool = await ds.pg_main()
    if pool is None:
        raise HTTPException(503, "mix_main 未配置")
    content: dict = {}
    for k, v in (body or {}).items():
        if v is None:
            continue
        s = str(v)
        # logo 为 data URL 放宽到 280KB(与品牌 logo 同口径),其余文案 300 字
        content[str(k)[:40]] = s[:280000] if k in ("logo", "logoUrl") else s[:300]
    await pool.execute(
        "INSERT INTO site_blocks(block_key, content, updated_by, updated_at) VALUES($1,$2,$3,now()) "
        "ON CONFLICT (block_key) DO UPDATE SET content=$2, updated_by=$3, updated_at=now()",
        key, json.dumps(content, ensure_ascii=False), admin["admin"])
    await proxy.audit(admin["admin"], admin.get("role", ""), "site.block", key,
                      {"keys": list(content)}, "saved")
    return {"saved": True, "block": key}


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


async def _agents_row(pool) -> dict:
    """AI 智能体接入配置(单行权威;表未迁移=全开默认,老行为不变)。"""
    try:
        ag = await pool.fetchrow(
            "SELECT advisor_enabled, ops_chat_enabled, chat_scope FROM llm_agent_settings WHERE id=1")
        if ag:
            return {"advisor_enabled": bool(ag["advisor_enabled"]),
                    "ops_chat_enabled": bool(ag["ops_chat_enabled"]),
                    "chat_scope": str(ag["chat_scope"] or "site")}
    except Exception:  # noqa: BLE001
        pass
    return {"advisor_enabled": True, "ops_chat_enabled": True, "chat_scope": "site"}


async def _publish_llm_config(pool):
    """发布全量中转站配置+智能体开关到总线(含明文 key——总线仅内网;UI 响应永远掩码)。
    llm-advisor/运维助手每轮热读同一键,开关零新增通道热生效。"""
    r = ds.rds()
    rows = await pool.fetch("SELECT * FROM llm_relays ORDER BY (role!='primary'), id")
    relays = [{"id": x["id"], "name": x["name"], "base_url": x["base_url"],
               "api_key": x["api_key"], "model": x["model"], "role": x["role"],
               "enabled": x["enabled"]} for x in rows]
    import time as _t
    await r.set("dcm:llm:config", json.dumps(
        {"ts": int(_t.time()), "relays": relays, "agents": await _agents_row(pool)},
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
    # 缺哪个字段就明说哪个(原来只笼统报"必填",前端难定位)
    missing = [lbl for lbl, v in (("名称", name), ("地址", base), ("API Key", key), ("模型", model)) if not v]
    if missing:
        raise HTTPException(400, f"以下字段必填:{'、'.join(missing)}")
    # 一步原子创建带账号 role(主/备),消除"先建备用再移主站"两步中途失败=行留错账号的窗口
    role = str(body.get("role") or "backup")
    if role not in ("primary", "backup"):
        role = "backup"
    row = await pool.fetchrow(
        "INSERT INTO llm_relays(name,base_url,api_key,model,role,enabled) "
        "VALUES($1,$2,$3,$4,$5,TRUE) RETURNING *", name, base, key, model, role)
    n = await _publish_llm_config(pool)
    await proxy.audit(op["operator"], op["role"], "llm.relay.add", name,
                      {"base_url": base, "model": model, "role": role}, f"published {n}")
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
    """移动地址到「主账号」或「备用账号」——不再强制主站唯一,每个账号可挂多个地址
    (调用不同模型);失效转移=所有启用主账号地址优先,再所有启用备用地址。"""
    pool = await ds.pg_main()
    role = str(body.get("role") or "")
    if role not in ("primary", "backup"):
        raise HTTPException(400, "role 必须是 primary(主账号) 或 backup(备用账号)")
    got = await pool.execute("UPDATE llm_relays SET role=$2, updated_at=now() WHERE id=$1", rid, role)
    if got.endswith("0"):
        raise HTTPException(404, "中转站不存在")
    n = await _publish_llm_config(pool)
    await proxy.audit(op["operator"], op["role"], "llm.relay.move", str(rid), {"role": role}, f"published {n}")
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


@router.post("/system/llm/probe-models")
async def llm_probe_models(body: dict, op=Depends(require_operator)):
    """无状态探测:直接用传入的 base_url+api_key 拉 /models(不需先存库)——
    解决添加新地址时「要先填模型才能存、但想先拉模型来挑」的鸡生蛋问题。
    地址缺 /v1 时自动补齐重试(OpenAI 兼容站几乎都在 /v1 下),返回真正生效的 base_url。"""
    import httpx
    raw = str(body.get("base_url") or "").strip().rstrip("/")
    key = str(body.get("api_key") or "").strip()
    if not raw or not key:
        raise HTTPException(400, "base_url 和 api_key 必填")
    # 候选地址:原样优先;若结尾不是已知版本段(/v1 /v1beta 等),追加 /v1 兜底
    import re
    candidates = [raw]
    if not re.search(r"/v\d[a-z]*$", raw):
        candidates.append(raw + "/v1")

    async def _try(base):
        async with httpx.AsyncClient(timeout=15) as cli:
            r = await cli.get(f"{base}/models", headers={"Authorization": f"Bearer {key}"})
        if r.status_code != 200:
            return None, f"http {r.status_code}: {r.text[:120]}"
        data = r.json()  # 非 JSON(HTML 落地页)会抛,交给外层按候选换下一个
        models = sorted({str(m.get("id")) for m in (data.get("data") or []) if m.get("id")})
        return models, None

    last_err = ""
    for base in candidates:
        try:
            models, err = await _try(base)
        except Exception as e:  # noqa: BLE001  (非JSON/连接错→换候选)
            last_err = f"{e!r}"[:120]
            continue
        if models is not None:
            return {"ok": True, "count": len(models), "models": models,
                    "effective_base_url": base,
                    "note": ("已自动补全为 " + base) if base != raw else ""}
        last_err = err
    hint = "" if raw.endswith("/v1") else "(试过原地址与 /v1 均失败,请确认地址正确)"
    return {"ok": False, "error": f"探测失败{hint}:{last_err}"[:200]}


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


@router.post("/system/llm/relays/{rid}/test-model")
async def llm_relay_test_model(rid: int, body: dict, op=Depends(require_operator)):
    """真调该站指定模型一次(chat/completions 最小请求),返回延迟/回复/错误——
    「加入列表≠可用」,上架与价格配置只有真调才知道。"""
    import time
    import httpx
    pool = await ds.pg_main()
    cur = await pool.fetchrow("SELECT * FROM llm_relays WHERE id=$1", rid)
    if not cur:
        raise HTTPException(404, "中转站不存在")
    model = str(body.get("model") or cur["model"]).strip()
    if not model:
        raise HTTPException(400, "model 必填")
    t0 = time.time()
    try:
        async with httpx.AsyncClient(timeout=30) as cli:
            resp = await cli.post(
                f"{cur['base_url']}/chat/completions",
                json={"model": model, "messages": [{"role": "user", "content": "回复两个字:OK"}],
                      "max_tokens": 200},
                headers={"Authorization": f"Bearer {cur['api_key']}"})
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "model": model, "latency_ms": int((time.time() - t0) * 1000),
                "error": repr(e)[:200]}
    lat = int((time.time() - t0) * 1000)
    if resp.status_code != 200:
        return {"ok": False, "model": model, "latency_ms": lat,
                "error": f"http {resp.status_code}: {resp.text[:200]}"}
    try:
        data = resp.json()
        reply = data["choices"][0]["message"]["content"]
        return {"ok": True, "model": model, "latency_ms": lat,
                "reply": str(reply)[:80], "usage": data.get("usage") or {}}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "model": model, "latency_ms": lat, "error": f"bad shape {e!r}"[:200]}


@router.get("/system/llm/agents")
async def llm_agents_get(_who=Depends(require_viewer)):
    pool = await ds.pg_main()
    if pool is None:
        raise HTTPException(503, "mix_main 未配置")
    return await _agents_row(pool)


@router.put("/system/llm/agents")
async def llm_agents_put(body: dict, op=Depends(require_operator)):
    """AI 智能体接入开关+运维助手回答范围:写单行权威表→重发布 dcm:llm:config 热生效
    (llm-advisor 每轮 15min 读;运维助手每次对话读=即时)。"""
    pool = await ds.pg_main()
    if pool is None:
        raise HTTPException(503, "mix_main 未配置")
    cur = await _agents_row(pool)
    adv = bool(body.get("advisor_enabled")) if body.get("advisor_enabled") is not None else cur["advisor_enabled"]
    chat = bool(body.get("ops_chat_enabled")) if body.get("ops_chat_enabled") is not None else cur["ops_chat_enabled"]
    scope = str(body.get("chat_scope") or cur["chat_scope"])
    if scope not in ("site", "open"):
        raise HTTPException(400, "chat_scope 必须是 site(限本站) 或 open(无限制)")
    try:
        await pool.execute(
            "INSERT INTO llm_agent_settings(id, advisor_enabled, ops_chat_enabled, chat_scope, updated_by, updated_at) "
            "VALUES(1,$1,$2,$3,$4,now()) ON CONFLICT (id) DO UPDATE SET advisor_enabled=$1, "
            "ops_chat_enabled=$2, chat_scope=$3, updated_by=$4, updated_at=now()",
            adv, chat, scope, op["operator"])
    except Exception as e:  # noqa: BLE001
        raise HTTPException(503, f"llm_agent_settings 表未迁移或写失败:{e}")
    await _publish_llm_config(pool)
    await proxy.audit(op["operator"], op["role"], "llm.agents", "llm_agent_settings",
                      {"advisor": adv, "ops_chat": chat, "scope": scope}, "published")
    return {"ok": True, "agents": {"advisor_enabled": adv, "ops_chat_enabled": chat, "chat_scope": scope}}


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
