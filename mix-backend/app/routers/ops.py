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


# ================= O1 现金流优化器(V4.0 §3.2/§7.3)+ 执行内核只读(§6) =================
@router.post("/system/o1/evaluate")
async def o1_evaluate(body: dict, _who=Depends(require_viewer)):
    """给定腿集算带符号日现金流(替代 abs(funding))。body={legs:[{venue,symbol,side,notional_usdt,...}]}"""
    from .. import o1
    return await o1.evaluate(body.get("legs") or [])


@router.post("/system/execution/shadow-sync")
async def execution_shadow_sync(op=Depends(require_operator)):
    """手动触发一次影随采纳(读真实持仓→shadow owner/intent/saga+对账)。"""
    from .. import kernel_shadow
    res = await kernel_shadow.shadow_sync()
    await proxy.audit(op["operator"], op["role"], "execution.shadow_sync", "-", {}, str(res)[:120])
    return res


@router.get("/system/execution/state")
async def execution_state(_who=Depends(require_viewer)):
    """执行内核 shadow 态概览(供最终 UI):owner/intent/saga 计数 + 模板映射。表未迁移=空。"""
    from .. import contracts
    pool = await ds.pg_main()
    out = {"owners": 0, "intents_by_status": {}, "sagas_by_state": {},
           "templates": contracts.EXECUTION_TEMPLATES, "armed": False,
           "note": "执行内核当前 SHADOW(不发真单);武装执行待契约稳定+混沌测试后门控"}
    if pool is None:
        return out
    try:
        out["owners"] = int((await pool.fetchrow("SELECT count(*) n FROM resource_ownership"))["n"])
        for r in await pool.fetch("SELECT status, count(*) n FROM position_intent GROUP BY 1"):
            out["intents_by_status"][r["status"]] = int(r["n"])
        for r in await pool.fetch("SELECT state, count(*) n FROM pair_saga GROUP BY 1"):
            out["sagas_by_state"][r["state"]] = int(r["n"])
    except Exception:  # noqa: BLE001
        pass
    return out


# ================= I1 合约矩阵(V4.0 §7.1)=================
# 公开 exchangeInfo(无需 key)拉合约规格入库。首批 Binance(USDT-M linear + COIN-M inverse,
# 含永续/交割);其余 venue 增量补。永续 deliveryDate 哨兵 4133404800000 → expiry=NULL。
_PERP_SENTINEL_MS = 4133404800000  # 币安永续 deliveryDate 占位(≈2100年)


def _bn_filters(sym: dict):
    fl = {f.get("filterType"): f for f in sym.get("filters", [])}
    tick = fl.get("PRICE_FILTER", {}).get("tickSize")
    step = fl.get("LOT_SIZE", {}).get("minQty")
    return (float(tick) if tick else None), (float(step) if step else None)


def _bn_expiry(sym: dict):
    dd = sym.get("deliveryDate")
    if not dd or int(dd) >= _PERP_SENTINEL_MS:
        return None
    import datetime as _dt
    return _dt.datetime.fromtimestamp(int(dd) / 1000, _dt.timezone.utc)


async def _populate_binance_instruments(pool) -> dict:
    import httpx
    rows = []
    async with httpx.AsyncClient(timeout=20) as cli:
        # USDT-M(linear):PERPETUAL + 交割 CURRENT_QUARTER/NEXT_QUARTER
        fapi = (await cli.get("https://fapi.binance.com/fapi/v1/exchangeInfo")).json()
        for s in fapi.get("symbols", []):
            ct = s.get("contractType") or ""
            if not ct or s.get("status") != "TRADING":
                continue
            tick, minq = _bn_filters(s)
            mt = "perp" if "PERPETUAL" in ct else "future"
            rows.append(("binance", s["symbol"], s.get("baseAsset", ""), mt, "linear", 1,
                         s.get("quoteAsset", ""), s.get("marginAsset", ""), s.get("marginAsset", ""),
                         ct, _bn_expiry(s), minq, tick, s.get("status", "")))
        # COIN-M(inverse):contractSize=乘数,marginAsset=币本位
        dapi = (await cli.get("https://dapi.binance.com/dapi/v1/exchangeInfo")).json()
        for s in dapi.get("symbols", []):
            ct = s.get("contractType") or ""
            if not ct or s.get("contractStatus", s.get("status")) != "TRADING":
                continue
            tick, minq = _bn_filters(s)
            mt = "perp" if "PERPETUAL" in ct else "future"
            rows.append(("binance", s["symbol"], s.get("baseAsset", ""), mt, "inverse",
                         float(s.get("contractSize") or 1), s.get("quoteAsset", ""),
                         s.get("marginAsset", ""), s.get("marginAsset", ""),
                         ct, _bn_expiry(s), minq, tick, s.get("contractStatus", s.get("status", ""))))
    n = 0
    for r in rows:
        await pool.execute(
            "INSERT INTO instrument_spec(venue,instrument_id,canonical_underlying,market_type,"
            "linear_or_inverse,contract_multiplier,quote_asset,settlement_asset,collateral_asset,"
            "contract_type,expiry,min_qty,tick_size,status,updated_at) "
            "VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,now()) "
            "ON CONFLICT (venue,instrument_id) DO UPDATE SET canonical_underlying=$3,market_type=$4,"
            "linear_or_inverse=$5,contract_multiplier=$6,quote_asset=$7,settlement_asset=$8,"
            "collateral_asset=$9,contract_type=$10,expiry=$11,min_qty=$12,tick_size=$13,status=$14,updated_at=now()",
            *r)
        n += 1
    return {"venue": "binance", "upserted": n}


async def _upsert_instruments(pool, rows) -> int:
    n = 0
    for r in rows:
        await pool.execute(
            "INSERT INTO instrument_spec(venue,instrument_id,canonical_underlying,market_type,"
            "linear_or_inverse,contract_multiplier,quote_asset,settlement_asset,collateral_asset,"
            "contract_type,expiry,min_qty,tick_size,status,updated_at) "
            "VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,now()) "
            "ON CONFLICT (venue,instrument_id) DO UPDATE SET canonical_underlying=$3,market_type=$4,"
            "linear_or_inverse=$5,contract_multiplier=$6,quote_asset=$7,settlement_asset=$8,"
            "collateral_asset=$9,contract_type=$10,expiry=$11,min_qty=$12,tick_size=$13,status=$14,updated_at=now()",
            *r)
        n += 1
    return n


@router.post("/system/instruments/refresh")
async def instruments_refresh(body: dict, op=Depends(require_operator)):
    """拉合约矩阵。venue=binance|bybit|okx|gate|bitget|hyperliquid|all。公开端点无需 key。"""
    pool = await ds.pg_main()
    if pool is None:
        raise HTTPException(503, "mix_main 未配置")
    venue = str(body.get("venue") or "all").lower()
    venues = ["binance", "bybit", "okx", "gate", "bitget", "hyperliquid"] if venue == "all" else [venue]
    from .. import i1_collectors
    res, errs = {}, {}
    for v in venues:
        try:
            if v == "binance":
                res[v] = (await _populate_binance_instruments(pool))["upserted"]
            elif v in i1_collectors._COLLECTORS:
                res[v] = await _upsert_instruments(pool, await i1_collectors.collect(v))
            else:
                errs[v] = "未知 venue"
        except Exception as e:  # noqa: BLE001  (单所失败隔离,不影响其余)
            errs[v] = f"{e!r}"[:150]
    await proxy.audit(op["operator"], op["role"], "instruments.refresh", venue, {"res": res, "errs": errs}, "ok")
    return {"ok": True, "upserted": res, "errors": errs}


@router.get("/meta/instruments")
async def meta_instruments(venue: str = "", underlying: str = "", market_type: str = "",
                           _who=Depends(require_viewer)):
    """合约矩阵查询。可按 venue/underlying/market_type 过滤;futures 带 expiry。"""
    pool = await ds.pg_main()
    if pool is None:
        return {"instruments": [], "count": 0}
    conds, args = [], []
    for col, val in (("venue", venue), ("canonical_underlying", underlying), ("market_type", market_type)):
        if val:
            args.append(val)
            conds.append(f"{col}=${len(args)}")
    where = (" WHERE " + " AND ".join(conds)) if conds else ""
    try:
        rows = await pool.fetch(
            "SELECT venue,instrument_id,canonical_underlying,market_type,linear_or_inverse,"
            "contract_multiplier,quote_asset,settlement_asset,collateral_asset,contract_type,"
            "expiry,min_qty,tick_size,status FROM instrument_spec" + where +
            " ORDER BY canonical_underlying, market_type, expiry NULLS FIRST LIMIT 2000", *args)
    except Exception:  # noqa: BLE001
        return {"instruments": [], "count": 0}
    out = []
    for r in rows:
        d = dict(r)
        for k in ("contract_multiplier", "min_qty", "tick_size"):
            d[k] = float(d[k]) if d[k] is not None else None
        d["expiry"] = d["expiry"].isoformat() if d["expiry"] else None
        out.append(d)
    return {"instruments": out, "count": len(out)}


# ================= catalog v2 产品目录(V4.0 §3,读) =================
@router.get("/meta/products")
async def meta_products(_who=Depends(require_viewer)):
    """产品/能力目录:C1-C6/O1/I1/R1/D1-D4 + 旧 S 码 alias。前端策略标签/规则中心可消费。
    表未迁移=空(前端回落旧 STRATEGY_META,老行为不变)。"""
    pool = await ds.pg_main()
    if pool is None:
        return {"products": [], "by_scode": {}}
    try:
        rows = await pool.fetch(
            "SELECT product_id, name, kind, parent_id, economic_structure, stage, priority, "
            "book_eligibility, deploy_domain, alias_scode, note, sort_order "
            "FROM product_catalog ORDER BY sort_order, product_id")
    except Exception:  # noqa: BLE001  (表未迁移)
        return {"products": [], "by_scode": {}}
    prods = [dict(r) for r in rows]
    by_scode = {r["alias_scode"]: r["product_id"] for r in prods if r["alias_scode"]}
    return {"products": prods, "by_scode": by_scode}


# ================= 投资份额账本 / NAV 管道(V4.0 §11-12,操作员侧) =================
# CORE_POOL NAV 权威源 = risk-ledger 的 reconciled 跨所权益(实盘对账后的真值)。
# 纪律:share_event append-only(表层已无 UPDATE/DELETE 权);NAV 快照不覆盖;发行份额须
# 关联 external_flow + 选定 FINALIZED NAV;所有份额操作全审计。

async def _pool_nav_source() -> dict:
    """读 CORE_POOL 的 reconciled 权益(dcm:risk:status.reconcile.total_equity_usdt)。
    当前 HOUSE_RND 未从 CORE 分账,先取全量并如实标注(§2.2 分账为后续 Phase)。"""
    risk = await ds.get_json("dcm:risk:status") or {}
    rec = risk.get("reconcile") or {}
    return {"total_equity_usdt": rec.get("total_equity_usdt"),
            "configured": bool(rec.get("configured")),
            "note": "含 HOUSE_RND(未分账);CORE/HOUSE 物理隔离为后续 Phase"}


@router.get("/system/nav/current")
async def nav_current(_who=Depends(require_viewer)):
    """当前池净值源 + 最近快照 + 总 Units(操作员发行份额前的对账视图)。"""
    pool = await ds.pg_main()
    src = await _pool_nav_source()
    snap = units = None
    if pool is not None:
        r = await pool.fetchrow("SELECT id, nav_status, pool_nav, total_units, nav_per_unit, as_of "
                                "FROM pool_nav_snapshot ORDER BY as_of DESC LIMIT 1")
        snap = dict(r) if r else None
        u = await pool.fetchrow("SELECT coalesce(sum(units),0) tu FROM share_event")
        units = float(u["tu"]) if u else 0.0
    if snap and snap.get("as_of"):
        snap["as_of"] = snap["as_of"].isoformat()
        for k in ("pool_nav", "total_units", "nav_per_unit"):
            snap[k] = float(snap[k]) if snap[k] is not None else None
    return {"source": src, "latest_snapshot": snap, "issued_units": units}


@router.post("/system/nav/snapshot")
async def nav_snapshot(body: dict, op=Depends(require_operator)):
    """写一条池净值快照。status=ESTIMATED(盘中可修订)/FINALIZED(日度定版不覆盖)。
    total_units 取当前已发行 units;nav_per_unit=pool_nav/total_units(units=0 时首日种 1.0)。"""
    pool = await ds.pg_main()
    if pool is None:
        raise HTTPException(503, "mix_main 未配置")
    status = str(body.get("nav_status") or "ESTIMATED")
    if status not in ("ESTIMATED", "CALCULATED", "RECONCILED", "FINALIZED", "PUBLISHED"):
        raise HTTPException(400, "nav_status 非法")
    src = await _pool_nav_source()
    pool_nav = body.get("pool_nav")
    if pool_nav is None:
        pool_nav = src["total_equity_usdt"]
    if pool_nav is None:
        raise HTTPException(409, "无法取得池净值(risk-ledger 未对账),请显式传 pool_nav")
    pool_nav = float(pool_nav)
    u = await pool.fetchrow("SELECT coalesce(sum(units),0) tu FROM share_event")
    total_units = float(u["tu"]) if u else 0.0
    # units=0(首日尚未发行)→ nav_per_unit 种 1.0,便于首发按实缴金额=Units
    nav_per_unit = (pool_nav / total_units) if total_units > 1e-9 else 1.0
    import datetime as _dt
    as_of = _dt.datetime.now(_dt.timezone.utc)
    row = await pool.fetchrow(
        "INSERT INTO pool_nav_snapshot(nav_status,pool_nav,total_units,nav_per_unit,net_flow,as_of,source) "
        "VALUES($1,$2,$3,$4,$5,$6,$7) RETURNING id",
        status, pool_nav, total_units, nav_per_unit, float(body.get("net_flow") or 0), as_of,
        str(body.get("source") or src["note"]))
    await proxy.audit(op["operator"], op["role"], "nav.snapshot", str(row["id"]),
                      {"status": status, "pool_nav": pool_nav, "nav_per_unit": nav_per_unit}, "written")
    return {"ok": True, "nav_id": row["id"], "pool_nav": pool_nav,
            "total_units": total_units, "nav_per_unit": nav_per_unit, "nav_status": status}


@router.get("/system/share/accounts")
async def share_accounts(_who=Depends(require_viewer)):
    pool = await ds.pg_main()
    if pool is None:
        return []
    rows = await pool.fetch(
        "SELECT sa.investor_id, sa.display_name, sa.is_house, sa.status, sa.login_user_id, "
        "coalesce(sum(se.units),0) AS units "
        "FROM share_account sa LEFT JOIN share_event se ON se.investor_id=sa.investor_id "
        "GROUP BY sa.investor_id ORDER BY sa.investor_id")
    return [{"investor_id": r["investor_id"], "name": r["display_name"], "is_house": r["is_house"],
             "status": r["status"], "login_user_id": r["login_user_id"], "units": float(r["units"])} for r in rows]


@router.post("/system/share/accounts")
async def share_account_create(body: dict, op=Depends(require_operator)):
    """建份额账户(不发份额)。login_user_id 绑定 mix_users 用于门户登录。"""
    pool = await ds.pg_main()
    if pool is None:
        raise HTTPException(503, "mix_main 未配置")
    name = str(body.get("display_name") or "").strip()
    if not name:
        raise HTTPException(400, "display_name 必填")
    row = await pool.fetchrow(
        "INSERT INTO share_account(login_user_id, display_name, is_house, note) VALUES($1,$2,$3,$4) "
        "RETURNING investor_id", body.get("login_user_id"), name,
        bool(body.get("is_house")), str(body.get("note") or ""))
    await proxy.audit(op["operator"], op["role"], "share.account.create", str(row["investor_id"]), {"name": name}, "ok")
    return {"ok": True, "investor_id": row["investor_id"]}


@router.post("/system/share/issue/dry-run")
async def share_issue_dryrun(body: dict, op=Depends(require_operator)):
    """发行 dry-run(§12.3):给定 investor + 实缴 USDT + 选定 NAV,算 Units,不落库。"""
    pool = await ds.pg_main()
    if pool is None:
        raise HTTPException(503, "mix_main 未配置")
    nav_id = body.get("nav_id")
    nav = await pool.fetchrow(
        "SELECT id, nav_per_unit, nav_status FROM pool_nav_snapshot WHERE id=$1", nav_id) if nav_id else \
        await pool.fetchrow("SELECT id, nav_per_unit, nav_status FROM pool_nav_snapshot "
                            "WHERE nav_status='FINALIZED' ORDER BY as_of DESC LIMIT 1")
    if not nav:
        raise HTTPException(409, "无可用 NAV 快照(先 POST /system/nav/snapshot,发行须用 FINALIZED)")
    npu = float(nav["nav_per_unit"])
    amt = float(body.get("amount_usdt") or 0)
    if amt <= 0:
        raise HTTPException(400, "amount_usdt 必须为正")
    units = amt / npu if npu > 1e-9 else 0.0
    return {"nav_id": nav["id"], "nav_status": nav["nav_status"], "nav_per_unit": npu,
            "amount_usdt": amt, "units": round(units, 10),
            "warn": None if nav["nav_status"] == "FINALIZED" else "该 NAV 非 FINALIZED,正式发行须用 FINALIZED"}


@router.post("/system/share/issue")
async def share_issue(body: dict, op=Depends(require_operator)):
    """正式发行/赎回份额 —— append-only share_event。发行须:①FINALIZED NAV ②关联 external_flow
    ③idempotency_key 防重放。event_type=ISSUE(units+)/REDEEM(units-)/ADJUST。"""
    pool = await ds.pg_main()
    if pool is None:
        raise HTTPException(503, "mix_main 未配置")
    inv = body.get("investor_id")
    etype = str(body.get("event_type") or "ISSUE")
    if etype not in ("ISSUE", "REDEEM", "TRANSFER", "ADJUST"):
        raise HTTPException(400, "event_type 非法")
    units = body.get("units")
    if units is None:
        raise HTTPException(400, "units 必填(发行+/赎回-,前端由 dry-run 得到)")
    units = float(units)
    flow = str(body.get("external_flow_id") or "").strip()
    if etype in ("ISSUE", "REDEEM") and not flow:
        raise HTTPException(400, "发行/赎回必须关联 external_flow_id(真实入金/出金流水)")
    idem = str(body.get("idempotency_key") or "").strip() or None
    nav_id = body.get("effective_nav_id")
    try:
        row = await pool.fetchrow(
            "INSERT INTO share_event(investor_id,event_type,units,effective_nav_id,external_flow_id,"
            "idempotency_key,approved_by,note) VALUES($1,$2,$3,$4,$5,$6,$7,$8) RETURNING id",
            inv, etype, units, nav_id, flow, idem, op["operator"], str(body.get("note") or ""))
    except Exception as e:  # noqa: BLE001  (唯一 idem 冲突=重放,幂等拒绝)
        if "idempotency" in str(e).lower() or "unique" in str(e).lower():
            raise HTTPException(409, "该资金流已发行过份额(idempotency_key 重复)")
        raise HTTPException(400, f"发行失败:{e}")
    await proxy.audit(op["operator"], op["role"], f"share.{etype.lower()}", str(inv),
                      {"units": units, "flow": flow, "nav_id": nav_id}, f"event {row['id']}")
    return {"ok": True, "event_id": row["id"]}


@router.post("/system/share/project")
async def share_project(body: dict, op=Depends(require_operator)):
    """按某 NAV 快照重算全体投资者投影(§12.2 公式)。可重算=先删该 nav_id 旧投影再生成。"""
    pool = await ds.pg_main()
    if pool is None:
        raise HTTPException(503, "mix_main 未配置")
    nav_id = body.get("nav_id")
    nav = await pool.fetchrow("SELECT id,pool_nav,total_units,nav_per_unit,as_of FROM pool_nav_snapshot WHERE id=$1", nav_id)
    if not nav:
        raise HTTPException(404, "nav 快照不存在")
    npu = float(nav["nav_per_unit"])
    # 组合收益率:与上一快照比(NAV_t - NAV_(t-1) - net_flow)/NAV_(t-1);首个快照为 None
    prev = await pool.fetchrow("SELECT pool_nav FROM pool_nav_snapshot WHERE as_of < $1 ORDER BY as_of DESC LIMIT 1", nav["as_of"])
    net_flow_row = await pool.fetchrow("SELECT net_flow FROM pool_nav_snapshot WHERE id=$1", nav_id)
    pool_ret = None
    if prev and float(prev["pool_nav"]) > 1e-9:
        pool_ret = (float(nav["pool_nav"]) - float(prev["pool_nav"]) - float(net_flow_row["net_flow"] or 0)) / float(prev["pool_nav"])
    # 逐投资者:units = 截至该快照时点的累计份额
    accts = await pool.fetch(
        "SELECT sa.investor_id, coalesce(sum(se.units),0) units FROM share_account sa "
        "LEFT JOIN share_event se ON se.investor_id=sa.investor_id AND se.approved_at<=$1 "
        "GROUP BY sa.investor_id", nav["as_of"])
    await pool.execute("DELETE FROM investor_projection WHERE nav_id=$1", nav_id)
    n = 0
    for a in accts:
        units = float(a["units"])
        await pool.execute(
            "INSERT INTO investor_projection(investor_id,nav_id,units,nav_per_unit,investor_equity,pool_return_pct,as_of) "
            "VALUES($1,$2,$3,$4,$5,$6,$7)",
            a["investor_id"], nav_id, units, npu, round(units * npu, 8), pool_ret, nav["as_of"])
        n += 1
    await proxy.audit(op["operator"], op["role"], "share.project", str(nav_id), {"investors": n}, "ok")
    return {"ok": True, "projected": n, "nav_per_unit": npu, "pool_return_pct": pool_ret}


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
    # 未传的字段不覆盖(前端别名弹框不传 machine→防清空 A/B/C 标记):仅当 body 含该键才更新。
    await pool.execute(
        "INSERT INTO accounts_registry(account_key, alias, email, note, machine, updated_at) "
        "VALUES($1,$2,$3,$4,$5,now()) ON CONFLICT (account_key) DO UPDATE SET "
        "alias=CASE WHEN $6 THEN $2 ELSE accounts_registry.alias END, "
        "email=CASE WHEN $7 THEN $3 ELSE accounts_registry.email END, "
        "note=CASE WHEN $8 THEN $4 ELSE accounts_registry.note END, "
        "machine=CASE WHEN $9 THEN $5 ELSE accounts_registry.machine END, updated_at=now()",
        key, str(body.get("alias") or ""), str(body.get("email") or ""), str(body.get("note") or ""), machine,
        "alias" in body, "email" in body, "note" in body, bool(machine))
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


def _base_candidates(raw: str) -> list:
    """地址候选:原样优先;结尾非 /v数字 版本段则追加 /v1 兜底(OpenAI 兼容站几乎都在 /v1)。"""
    import re
    raw = str(raw or "").strip().rstrip("/")
    out = [raw]
    if raw and not re.search(r"/v\d[a-z]*$", raw):
        out.append(raw + "/v1")
    return out


@router.post("/system/llm/probe-models")
async def llm_probe_models(body: dict, op=Depends(require_operator)):
    """无状态探测:直接用传入的 base_url+api_key 拉 /models(不需先存库)——
    解决添加新地址时「要先填模型才能存、但想先拉模型来挑」的鸡生蛋问题。
    地址缺 /v1 时自动补齐重试,返回真正生效的 base_url。"""
    import httpx
    raw = str(body.get("base_url") or "").strip().rstrip("/")
    key = str(body.get("api_key") or "").strip()
    if not raw or not key:
        raise HTTPException(400, "base_url 和 api_key 必填")

    async def _try(base):
        async with httpx.AsyncClient(timeout=15) as cli:
            r = await cli.get(f"{base}/models", headers={"Authorization": f"Bearer {key}"})
        if r.status_code != 200:
            return None, f"http {r.status_code}: {r.text[:120]}"
        data = r.json()  # 非 JSON(HTML 落地页)会抛,交给外层换候选
        return sorted({str(m.get("id")) for m in (data.get("data") or []) if m.get("id")}), None

    last_err = ""
    for base in _base_candidates(raw):
        try:
            models, err = await _try(base)
        except Exception as e:  # noqa: BLE001
            last_err = f"{e!r}"[:120]
            continue
        if models is not None:
            return {"ok": True, "count": len(models), "models": models,
                    "effective_base_url": base,
                    "note": ("已自动补全为 " + base) if base != raw else ""}
        last_err = err
    hint = "" if raw.endswith("/v1") else "(试过原地址与 /v1 均失败,请确认地址正确)"
    return {"ok": False, "error": f"探测失败{hint}:{last_err}"[:200]}


async def _heal_base_url(pool, rid, cur_base, working_base, op):
    """测试/刷新时发现库里地址缺 /v1、而补全版能用→自愈:把库里地址纠正为能用的那个+重发布。
    避免坏地址留库致 ai.py 生产真调也失败。"""
    if working_base == cur_base:
        return False
    await pool.execute("UPDATE llm_relays SET base_url=$2, updated_at=now() WHERE id=$1", rid, working_base)
    await _publish_llm_config(pool)
    await proxy.audit(op["operator"], op["role"], "llm.relay.heal_base", str(rid),
                      {"from": cur_base, "to": working_base}, "auto-fixed /v1")
    return True


@router.post("/system/llm/relays/{rid}/refresh-models")
async def llm_relay_models(rid: int, op=Depends(require_operator)):
    """真调该站 /models 刷新可选模型列表(openai 兼容);地址缺 /v1 自动补并自愈库里地址。"""
    import httpx
    pool = await ds.pg_main()
    cur = await pool.fetchrow("SELECT * FROM llm_relays WHERE id=$1", rid)
    if not cur:
        raise HTTPException(404, "中转站不存在")

    async def _try(base):
        async with httpx.AsyncClient(timeout=15) as cli:
            r = await cli.get(f"{base}/models", headers={"Authorization": f"Bearer {cur['api_key']}"})
        if r.status_code != 200:
            return None, f"http {r.status_code}: {r.text[:120]}"
        data = r.json()
        return sorted({str(m.get("id")) for m in (data.get("data") or []) if m.get("id")}), None

    last_err = ""
    for base in _base_candidates(cur["base_url"]):
        try:
            models, err = await _try(base)
        except Exception as e:  # noqa: BLE001
            last_err = f"{e!r}"[:120]
            continue
        if models is not None:
            healed = await _heal_base_url(pool, rid, cur["base_url"], base, op)
            await pool.execute("UPDATE llm_relays SET available_models=$2, updated_at=now() WHERE id=$1",
                               rid, json.dumps(models))
            custom = json.loads(cur["custom_models"]) if cur["custom_models"] else []
            return {"ok": True, "count": len(models),
                    "available_models": sorted(set(models) | set(custom)),
                    "note": (f"地址已自愈为 {base}") if healed else ""}
        last_err = err
    return {"ok": False, "error": f"拉取失败:{last_err}"[:200]}


@router.post("/system/llm/relays/{rid}/test-model")
async def llm_relay_test_model(rid: int, body: dict, op=Depends(require_operator)):
    """真调该站指定模型一次(chat/completions 最小请求),返回延迟/回复/错误。
    地址缺 /v1 自动补并自愈库里地址;非 JSON 响应如实回显首段(HTML 落地页一眼看出)。"""
    import time
    import httpx
    pool = await ds.pg_main()
    cur = await pool.fetchrow("SELECT * FROM llm_relays WHERE id=$1", rid)
    if not cur:
        raise HTTPException(404, "中转站不存在")
    model = str(body.get("model") or cur["model"]).strip()
    if not model:
        raise HTTPException(400, "model 必填")

    async def _try(base):
        async with httpx.AsyncClient(timeout=30) as cli:
            r = await cli.post(
                f"{base}/chat/completions",
                json={"model": model, "messages": [{"role": "user", "content": "回复两个字:OK"}],
                      "max_tokens": 200},
                headers={"Authorization": f"Bearer {cur['api_key']}"})
        # 非 200:确定的服务端错(如 401/404/价格未配),不试下一个候选,直接回报
        if r.status_code != 200:
            return {"fatal": True, "err": f"http {r.status_code}: {r.text[:180]}"}
        try:
            data = r.json()
        except Exception:  # noqa: BLE001  (非 JSON=可能地址缺 /v1 命中落地页,换候选)
            return {"nonjson": True, "err": f"200 但非 JSON(疑似地址缺 /v1 命中网页):{r.text[:120]}"}
        return {"reply": str(data["choices"][0]["message"]["content"])[:80], "usage": data.get("usage") or {}}

    t0 = time.time()
    last_err = ""
    for base in _base_candidates(cur["base_url"]):
        try:
            res = await _try(base)
        except Exception as e:  # noqa: BLE001
            last_err = repr(e)[:180]
            continue
        lat = int((time.time() - t0) * 1000)
        if res.get("fatal"):
            return {"ok": False, "model": model, "latency_ms": lat, "error": res["err"]}
        if res.get("nonjson"):
            last_err = res["err"]
            continue   # 换 /v1 候选再试
        healed = await _heal_base_url(pool, rid, cur["base_url"], base, op)
        return {"ok": True, "model": model, "latency_ms": lat,
                "reply": res["reply"], "usage": res["usage"],
                "note": (f"地址已自愈为 {base}") if healed else ""}
    lat = int((time.time() - t0) * 1000)
    return {"ok": False, "model": model, "latency_ms": lat, "error": last_err}


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
