"""V6.2 PATCH-01(MIX-V6.2-PATCH-01)M1/M2:canonical 搜索 + 研判上下文 + C2.P 研判案件与人工计划。

挂载前缀 /api/v6(不开第三 API 前缀,M0 契约修正②):
  GET  /instruments/search?q=          canonical 币种搜索(instrument_spec+别名,dbKey 绝不出现在输入框)
  GET  /research/context?symbol=&product=   官方数据事实行(MetricValueEnvelope=dv() 同一权威)+AiCoin 映射
  GET  /research/cases?symbol=         研判案件列表(新表+旧 lab_case 只读映射)
  POST /research/cases                 创建研判(QUICK 四步/FULL 全字段)
  PUT  /research/cases/{id}            草稿更新
  POST /research/cases/{id}/complete   完成研判(summary_text 确定性模板,不依赖 LLM)
  POST /work-items/create-manual-plan  研判→人工计划(dry_run_proposal,C2.P;审批链不变)
  GET  /work-items/plan-preview        计划预览(多腿路线/费/滑点/资金费/退出容量,envelope 化)

铁律:
- 研判只产结论不产订单;人工计划走既有 DRY_RUN→冷却→二次认证链,本模块不新增写入口;
- AiCoin dbKey 只在服务端映射(aicoin_symbol_mapping),映射缺失=AICOIN_MAPPING_MISSING,
  绝不显示成『币种不存在』;
- 指标禁止裸 N/A/无原因 null/0 冒充——一律 dv() 九态带 reason;
- 审批通过(APPROVED)仍是 shadow 终态:真实执行=operator 按 SOP 并入 manager config
  (自动登记 shadow、人工翻 armed 为下批,B机 schema 未接)。
"""
import json
import time
import datetime as dt
import logging

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query

from ..deps import require_viewer, require_operator
from .. import datasources as ds
from ..v6lang import dv

log = logging.getLogger("mix.research")
router = APIRouter(tags=["v62-research"])

VENUES = ("binance", "okx", "bybit", "gate", "bitget", "hyperliquid")

_DDL = """CREATE TABLE IF NOT EXISTS instrument_alias (
    alias TEXT PRIMARY KEY,
    canonical_underlying TEXT NOT NULL,
    note TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now());
CREATE TABLE IF NOT EXISTS aicoin_symbol_mapping (
    canonical_underlying TEXT PRIMARY KEY,
    db_key TEXT NOT NULL,
    display TEXT NOT NULL DEFAULT '',
    source TEXT NOT NULL DEFAULT 'auto',
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now());
CREATE TABLE IF NOT EXISTS c2p_research_decision (
    id BIGSERIAL PRIMARY KEY,
    work_item_id TEXT NOT NULL DEFAULT '',
    proposal_id BIGINT,
    canonical_symbol TEXT NOT NULL,
    product_code TEXT NOT NULL DEFAULT 'C2.P',
    review_mode TEXT NOT NULL DEFAULT 'QUICK' CHECK (review_mode IN ('QUICK','FULL')),
    market_stage TEXT NOT NULL DEFAULT '',
    confidence_level TEXT NOT NULL DEFAULT '',
    evidence_for JSONB NOT NULL DEFAULT '[]'::jsonb,
    evidence_against JSONB NOT NULL DEFAULT '[]'::jsonb,
    risk_flags JSONB NOT NULL DEFAULT '[]'::jsonb,
    decision TEXT NOT NULL DEFAULT 'OBSERVE' CHECK (decision IN ('OBSERVE','PREPARE_PLAN','REJECT')),
    next_watch_trigger TEXT NOT NULL DEFAULT '',
    thesis_invalidation TEXT NOT NULL DEFAULT '',
    recommended_route TEXT NOT NULL DEFAULT '',
    recommended_notional NUMERIC,
    max_holding_time TEXT NOT NULL DEFAULT '',
    review_at TIMESTAMPTZ,
    summary_text TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'DRAFT' CHECK (status IN ('DRAFT','COMPLETED','EXPIRED')),
    created_by TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now());
CREATE INDEX IF NOT EXISTS idx_c2p_research_sym ON c2p_research_decision (canonical_symbol, id DESC)"""

# 别名种子(可经表扩充;大小写不敏感匹配)
_ALIAS_SEED = {
    "BITCOIN": "BTC", "XBT": "BTC", "比特币": "BTC",
    "ETHEREUM": "ETH", "以太坊": "ETH",
    "SOLANA": "SOL", "DOGECOIN": "DOGE", "狗狗币": "DOGE",
    "RIPPLE": "XRP", "CARDANO": "ADA", "LITECOIN": "LTC", "TONCOIN": "TON",
}

_seeded = False


async def _pool():
    p = await ds.pg_main()
    if p is None:
        raise HTTPException(503, "mix_main 不可达")
    global _seeded
    if not _seeded:
        await p.execute(_DDL)
        for a, u in _ALIAS_SEED.items():
            await p.execute(
                "INSERT INTO instrument_alias(alias, canonical_underlying, note) "
                "VALUES($1,$2,'seed') ON CONFLICT DO NOTHING", a.upper(), u)
        _seeded = True
    return p


def _canon_underlying(symbol: str) -> str:
    s = (symbol or "").strip().upper()
    for suf in ("USDT", "USDC", "USD"):
        if s.endswith(suf) and len(s) > len(suf):
            return s[: -len(suf)]
    return s


# ─────────────────────────── canonical 搜索(§4.1) ───────────────────────────

@router.get("/instruments/search")
async def instruments_search(q: str = Query(..., min_length=1), _who=Depends(require_viewer)):
    """搜币种/交易对/中英文别名——数据源=I1 instrument_spec(六所~2030合约)+别名表。
    AiCoin 可用性只读映射表(不在搜索路径上打外部 API,保持快)。"""
    pool = await _pool()
    kw = q.strip().upper()
    if not kw:
        return {"rows": []}
    # 别名命中(全等优先)→ 归一标的
    hits: list[str] = []
    arow = await pool.fetchrow(
        "SELECT canonical_underlying FROM instrument_alias WHERE alias=$1", kw)
    if arow:
        hits.append(arow["canonical_underlying"])
    # instrument_spec:标的全等 > 标的前缀 > 交易对前缀
    rows = await pool.fetch(
        """SELECT DISTINCT canonical_underlying AS u FROM instrument_spec
           WHERE canonical_underlying = $1
              OR canonical_underlying LIKE $1 || '%'
              OR instrument_id LIKE $1 || '%'
           ORDER BY u LIMIT 24""", kw)
    for r in rows:
        if r["u"] not in hits:
            hits.append(r["u"])
    # 全等置顶,短名优先(BTC 排在 BTCDOM 前)
    hits.sort(key=lambda u: (u != kw, len(u), u))
    hits = hits[:8]
    if not hits:
        return {"rows": []}
    out = []
    specs = await pool.fetch(
        "SELECT canonical_underlying AS u, venue, market_type, quote_asset FROM instrument_spec "
        "WHERE canonical_underlying = ANY($1::text[])", hits)
    amap = {r["alias"]: r["canonical_underlying"] for r in await pool.fetch(
        "SELECT alias, canonical_underlying FROM instrument_alias "
        "WHERE canonical_underlying = ANY($1::text[])", hits)}
    ai_rows = {r["canonical_underlying"]: r["db_key"] for r in await pool.fetch(
        "SELECT canonical_underlying, db_key FROM aicoin_symbol_mapping "
        "WHERE canonical_underlying = ANY($1::text[])", hits)}
    by_u: dict[str, list] = {}
    for r in specs:
        by_u.setdefault(r["u"], []).append(r)
    for u in hits:
        rs = by_u.get(u) or []
        venues = sorted({r["venue"] for r in rs})
        markets = sorted({r["market_type"].upper() for r in rs})
        perp_venues = {r["venue"] for r in rs if r["market_type"] == "perp"}
        prods = []
        if "SPOT" in markets and "PERP" in markets:
            prods.append("C1")
        if len(perp_venues) >= 2:
            prods += ["C2.H", "C2.P"]
        if "FUTURE" in markets:
            prods += ["C4", "C5"]
        out.append({
            "canonicalSymbol": f"{u}USDT", "displayName": f"{u}/USDT",
            "baseAsset": u, "quoteAsset": "USDT",
            "aliases": [a for a, cu in amap.items() if cu == u],
            "venues": venues, "markets": markets,
            "availableProducts": prods,
            # true/false 只对已解析映射说话;未解析=None(前端显示『未探测』,进 context 时懒解析)
            "aicoinAvailable": (True if u in ai_rows else None),
        })
    return {"rows": out}


# ─────────────────────────── AiCoin 映射(服务端懒解析) ───────────────────────

async def _aicoin_dbkey(pool, underlying: str) -> tuple[str | None, str]:
    """返回 (db_key, reason)。映射表命中→直接用;缺失→现场经 AiCoin coin-search 解析并落表;
    仍无→AICOIN_MAPPING_MISSING(官方行情不受影响,绝不显示成币种不存在)。"""
    row = await pool.fetchrow(
        "SELECT db_key FROM aicoin_symbol_mapping WHERE canonical_underlying=$1", underlying)
    if row:
        return row["db_key"], ""
    try:
        from .aicoin import _client
        ac = await _client()
        if ac is None:
            return None, "AICOIN_NOT_CONFIGURED"
        lst = await ac.search(underlying)
        # AiCoin 真实字段=dbKeys(可逗号多值)/coinShow/coinName(实测 2026-07-16;
        # db_key/dbKey 字段不存在——旧前端找错字段正是"搜索搜不到"的病灶之一)。
        # 优先 coinShow 全等的币 + 币安永续 usdt 对(与官方快照同市场)。
        best = None
        low = underlying.lower()
        for c in lst or []:
            keys = [k.strip() for k in str(c.get("dbKeys") or c.get("db_key") or
                                           c.get("dbKey") or c.get("key") or "").split(",") if k.strip()]
            if not keys:
                continue
            show = str(c.get("coinShow") or c.get("show") or "").upper()
            name = str(c.get("coinName") or c.get("name") or "")
            pick = (next((k for k in keys if k.startswith(f"{low}swapusdt:")), None)
                    or next((k for k in keys if low in k), None)
                    or (keys[0] if show == underlying else None))
            if show == underlying and pick:
                best = (pick, name)
                break
            if best is None and pick:
                best = (pick, name)
        if best:
            await pool.execute(
                "INSERT INTO aicoin_symbol_mapping(canonical_underlying, db_key, display, source) "
                "VALUES($1,$2,$3,'auto') ON CONFLICT (canonical_underlying) DO UPDATE "
                "SET db_key=$2, display=$3, updated_at=now()", underlying, best[0], best[1])
            return best[0], ""
        return None, "AICOIN_MAPPING_MISSING"
    except Exception as e:  # noqa: BLE001
        log.warning("aicoin resolve %s: %s", underlying, e)
        return None, "AICOIN_RESOLVE_ERROR"


# ─────────────────────────── 研判上下文(§4.2/§4.3) ───────────────────────────

_pub_cache: dict = {}   # symbol → (ts, dict) 30s;币安公开端点,无 key 无权重压力
_PUB_TTL = 30


async def _binance_public(symbol: str) -> dict:
    now = time.time()
    c = _pub_cache.get(symbol)
    if c and now - c[0] < _PUB_TTL:
        return c[1]
    out: dict = {}
    async with httpx.AsyncClient(timeout=6) as cli:
        try:
            r = await cli.get("https://fapi.binance.com/fapi/v1/ticker/24hr", params={"symbol": symbol})
            if r.status_code == 200:
                d = r.json()
                out["vol24h_usdt"] = float(d.get("quoteVolume") or 0)
                out["last_price"] = float(d.get("lastPrice") or 0)
        except Exception as e:  # noqa: BLE001
            out["vol_err"] = str(e)[:80]
        try:
            r = await cli.get("https://fapi.binance.com/fapi/v1/openInterest", params={"symbol": symbol})
            if r.status_code == 200:
                d = r.json()
                out["oi_base"] = float(d.get("openInterest") or 0)
        except Exception as e:  # noqa: BLE001
            out["oi_err"] = str(e)[:80]
        try:
            r = await cli.get("https://fapi.binance.com/fapi/v1/depth", params={"symbol": symbol, "limit": 500})
            if r.status_code == 200:
                d = r.json()
                bids, asks = d.get("bids") or [], d.get("asks") or []
                if bids and asks:
                    mid = (float(bids[0][0]) + float(asks[0][0])) / 2
                    lo, hi = mid * (1 - 0.0025), mid * (1 + 0.0025)
                    out["depth_buy_usdt"] = round(sum(float(p) * float(q) for p, q in
                                                      ((float(x[0]), float(x[1])) for x in bids) if p >= lo), 0)
                    out["depth_sell_usdt"] = round(sum(float(p) * float(q) for p, q in
                                                       ((float(x[0]), float(x[1])) for x in asks) if p <= hi), 0)
        except Exception as e:  # noqa: BLE001
            out["depth_err"] = str(e)[:80]
    _pub_cache[symbol] = (now, out)
    return out


async def _venue_rows(symbol: str) -> list[dict]:
    """逐所 L1/资金费(与 /risk/symbol-analysis 同源同口径)。"""
    pol = await ds.get_json("dcm:risk:policy") or {}
    out = []
    for v in VENUES:
        row = {"venue": v, "mode": ((pol.get("venues") or {}).get(v) or {}).get("mode", "N/A"),
               "mid": None, "spread_bps": None, "funding_daily_pct": None,
               "interval_h": None, "fresh": False}
        try:
            raw = await ds.rds().hget(f"dcm:feed:{v}:perp", symbol)
            l1 = json.loads(raw) if raw else None
            if l1:
                b, a = float(l1.get("bid") or 0), float(l1.get("ask") or 0)
                if b > 0 and a > 0:
                    row["mid"] = round((b + a) / 2, 8)
                    row["spread_bps"] = round((a - b) / ((a + b) / 2) * 10000, 2)
                    row["fresh"] = (time.time() * 1000 - float(l1.get("recv_ts") or 0)) < 120000
        except Exception:  # noqa: BLE001
            pass
        try:
            raw = await ds.rds().hget(f"dcm:feed:funding:{v}", symbol)
            f = json.loads(raw) if raw else None
            if f:
                row["funding_daily_pct"] = round(float(f.get("daily_pct") or 0), 4)
                row["interval_h"] = f.get("interval_h")
        except Exception:  # noqa: BLE001
            pass
        out.append(row)
    return out


@router.get("/research/context")
async def research_context(symbol: str = Query(...), product: str = Query("C2.P"),
                           _who=Depends(require_viewer)):
    """官方数据事实行(dv() envelope,每行带 source/reason)+逐所表+AiCoin 映射+候选EV。
    指标 schema 按产品(§4.3):C2.P=费差面;C3 借币面在坑位工作台,此处 NOT_APPLICABLE。"""
    pool = await _pool()
    sym = symbol.strip().upper()
    und = _canon_underlying(sym)
    now_iso = dt.datetime.now(dt.timezone.utc).isoformat()
    venues = await _venue_rows(sym)
    fresh = [v for v in venues if v["fresh"] and v["mid"] is not None]
    best = min(fresh, key=lambda v: v["spread_bps"] or 9e9) if fresh else None
    pub = await _binance_public(sym)

    # instrument_spec:cap/floor/结算周期/上市时间(binance 优先,缺则任一所)
    spec = await pool.fetchrow(
        "SELECT venue, funding_interval_h::float8 AS ih, cap::float8 AS cap, floor::float8 AS flr, "
        "raw->>'onboardDate' AS onboard FROM instrument_spec "
        "WHERE canonical_underlying=$1 AND market_type='perp' "
        "ORDER BY (venue!='binance'), venue LIMIT 1", und)
    listed = None
    if spec and spec["onboard"]:
        try:
            listed = dt.datetime.fromtimestamp(int(spec["onboard"]) / 1000, dt.timezone.utc).strftime("%Y-%m")
        except Exception:  # noqa: BLE001
            pass

    fs = [v["funding_daily_pct"] for v in venues if v["funding_daily_pct"] is not None]
    gap = round(max(fs) - min(fs), 4) if len(fs) >= 2 else None

    # 候选EV:opener 榜命中=PRESENT;未命中=WAITING_INPUT(产品/路线/金额定了才算,§4.3)
    ev_env = dv(None, state="WAITING_INPUT", reason="EV_WAITING_PLAN", source="opener")
    try:
        cand = next((c for c in ((await ds.get_json("dcm:exec:opener") or {}).get("candidates") or [])
                     if c.get("symbol") == sym), None)
        if cand:
            ev_env = dv(cand.get("risk_adjusted_e_bps") or cand.get("e_bps"),
                        as_of=now_iso, source="opener")
    except Exception:  # noqa: BLE001
        pass

    metrics = {
        "price": dv(best["mid"] if best else None, as_of=now_iso, source="official_l1",
                    reason=("" if best else "L1_FEED_STALE")),
        "spread_min_bps": dv(best["spread_bps"] if best else None, as_of=now_iso, source="official_l1",
                             reason=("" if best else "L1_FEED_STALE")),
        "vol24h_usdt": dv(pub.get("vol24h_usdt"), as_of=now_iso, source="binance_public",
                          state=(None if pub.get("vol24h_usdt") is not None else "ERROR" if pub.get("vol_err") else "NOT_CONNECTED"),
                          reason=pub.get("vol_err") or ("" if pub.get("vol24h_usdt") is not None else "VOL_SOURCE_NOT_CONNECTED")),
        "oi_usdt": dv(round(pub["oi_base"] * pub["last_price"], 0)
                      if pub.get("oi_base") is not None and pub.get("last_price") else None,
                      as_of=now_iso, source="binance_public",
                      state=(None if pub.get("oi_base") is not None else "ERROR" if pub.get("oi_err") else "NOT_CONNECTED"),
                      reason=pub.get("oi_err") or ("" if pub.get("oi_base") is not None else "OI_SOURCE_NOT_CONNECTED")),
        "depth_buy_25bps": dv(pub.get("depth_buy_usdt"), as_of=now_iso, source="binance_public",
                              reason=pub.get("depth_err") or ""),
        "depth_sell_25bps": dv(pub.get("depth_sell_usdt"), as_of=now_iso, source="binance_public",
                               reason=pub.get("depth_err") or ""),
        "funding_gap_daily_pct": dv(gap, as_of=now_iso, source="funding_feed",
                                    reason=("" if gap is not None else "FUNDING_COVERAGE_LT_2")),
        "funding_coverage": dv(len(fs), as_of=now_iso, source="funding_feed"),
        "funding_interval_h": dv(float(spec["ih"]) if spec and spec["ih"] else None,
                                 source="instrument_spec",
                                 reason=("" if spec and spec["ih"] else "SPEC_FIELD_EMPTY")),
        "funding_cap": dv(spec["cap"] if spec else None, source="instrument_spec",
                          reason=("" if spec and spec["cap"] is not None else "SPEC_FIELD_EMPTY")),
        "funding_floor": dv(spec["flr"] if spec else None, source="instrument_spec",
                            reason=("" if spec and spec["flr"] is not None else "SPEC_FIELD_EMPTY")),
        "listed_since": dv(listed, source="instrument_spec",
                           reason=("" if listed else "ONBOARD_DATE_UNAVAILABLE")),
        "candidate_ev_bps": ev_env,
    }
    if not str(product or "").startswith("C3"):
        # C2.P 不显示借币指标(§4.3):不适用≠没接
        for k in ("max_borrowable", "borrow_rate", "borrow_quota"):
            metrics[k] = dv(None, state="NOT_APPLICABLE", reason="PRODUCT_SCOPE_C3_ONLY")

    db_key, ai_reason = await _aicoin_dbkey(pool, und)
    return {"symbol": sym, "underlying": und, "product": product, "as_of": now_iso,
            "venues": venues, "metrics": metrics,
            "aicoin": {"available": bool(db_key), "db_key": db_key,
                       "reason": ai_reason,
                       "note": ("" if db_key else "官方行情可用,AiCoin 图表尚未匹配")}}


# ─────────────────────────── 研判案件(§4.4) ───────────────────────────

_DECISION_CN = {"OBSERVE": "继续观察", "PREPARE_PLAN": "准备人工计划", "REJECT": "不参与"}


def _summary(sym: str, body: dict) -> str:
    """确定性模板(不依赖 LLM 才能保存);生成后允许编辑。"""
    ef = body.get("evidence_for") or []
    rf = body.get("risk_flags") or []
    return (f"{sym} {body.get('market_stage') or '?'}"
            f";依据={'/'.join(ef) if ef else '无'}"
            f";风险={'/'.join(rf) if rf else '无'}"
            f";结论={_DECISION_CN.get(str(body.get('decision') or 'OBSERVE'), '?')}")


def _case_row(r) -> dict:
    d = dict(r)
    for k in ("evidence_for", "evidence_against", "risk_flags"):
        if isinstance(d.get(k), str):
            try:
                d[k] = json.loads(d[k])
            except Exception:  # noqa: BLE001
                d[k] = []
    for k in ("created_at", "updated_at", "review_at"):
        if d.get(k) is not None:
            d[k] = str(d[k])
    if d.get("recommended_notional") is not None:
        d["recommended_notional"] = float(d["recommended_notional"])
    d["source"] = "v62"
    return d


@router.get("/research/cases")
async def research_cases(symbol: str = "", limit: int = Query(20, le=100),
                         _who=Depends(require_viewer)):
    """新研判案件+旧 lab_case 只读映射(§11:旧数据经 adapter 只读,不迁移不删除)。"""
    pool = await _pool()
    if symbol:
        rows = await pool.fetch(
            "SELECT * FROM c2p_research_decision WHERE canonical_symbol=$1 ORDER BY id DESC LIMIT $2",
            symbol.strip().upper(), limit)
    else:
        rows = await pool.fetch("SELECT * FROM c2p_research_decision ORDER BY id DESC LIMIT $1", limit)
    out = [_case_row(r) for r in rows]
    try:   # 旧案件只读映射(展示同一张历史表)
        q = ("SELECT id, symbol, operator, action, stage, product, evidence_for, evidence_against, "
             "invalidation, review_by, aicoin_price, official_price, outcome, created_at::text "
             "FROM lab_case " + ("WHERE symbol=$1 " if symbol else "") + "ORDER BY id DESC LIMIT 20")
        lrows = await (pool.fetch(q, symbol.strip().upper()) if symbol else pool.fetch(q))
        for r in lrows:
            out.append({"id": f"legacy-{r['id']}", "source": "legacy",
                        "canonical_symbol": r["symbol"], "product_code": r["product"] or "",
                        "review_mode": "FULL", "market_stage": r["stage"] or "",
                        "evidence_for": [r["evidence_for"]] if r["evidence_for"] else [],
                        "evidence_against": [r["evidence_against"]] if r["evidence_against"] else [],
                        "risk_flags": [], "decision": ("REJECT" if r["action"] == "REJECT" else "OBSERVE"),
                        "thesis_invalidation": r["invalidation"] or "",
                        "summary_text": f"[旧案件] {r['action']} {r['stage'] or ''}",
                        "status": "COMPLETED", "created_by": r["operator"],
                        "created_at": r["created_at"], "outcome": r["outcome"] or ""})
    except Exception:  # noqa: BLE001
        pass
    return {"rows": out}


_QUICK_REQUIRED = ("market_stage", "decision")
_FULL_REQUIRED = ("market_stage", "confidence_level", "decision", "thesis_invalidation", "review_at")


def _validate_case(body: dict):
    mode = str(body.get("review_mode") or "QUICK")
    req = _FULL_REQUIRED if mode == "FULL" else _QUICK_REQUIRED
    missing = [f for f in req if not str(body.get(f) or "").strip()]
    if missing:
        raise HTTPException(400, f"研判必填缺失({mode}):{','.join(missing)}")
    if mode == "QUICK" and not (body.get("evidence_for") or body.get("risk_flags")):
        raise HTTPException(400, "快速研判至少勾选一项主要依据或主要风险")
    if str(body.get("decision")) not in _DECISION_CN:
        raise HTTPException(400, "decision 必须为 OBSERVE/PREPARE_PLAN/REJECT")


@router.post("/research/cases")
async def research_case_create(body: dict, who=Depends(require_viewer)):
    """创建研判(viewer 可记录——研判是证据不是订单);complete=true 直接完成。"""
    pool = await _pool()
    sym = str(body.get("symbol") or body.get("canonical_symbol") or "").strip().upper()
    if not sym:
        raise HTTPException(400, "symbol 必填")
    _validate_case(body)
    summary = str(body.get("summary_text") or "").strip() or _summary(sym, body)
    review_at = None
    if str(body.get("review_at") or "").strip():
        try:
            review_at = dt.datetime.fromisoformat(str(body["review_at"]).replace("Z", "+00:00"))
        except Exception:  # noqa: BLE001
            raise HTTPException(400, "review_at 需 ISO 时间(如 2026-07-17T09:00:00+08:00)")
    status = "COMPLETED" if body.get("complete") else "DRAFT"
    row = await pool.fetchrow(
        """INSERT INTO c2p_research_decision(canonical_symbol, product_code, review_mode, market_stage,
           confidence_level, evidence_for, evidence_against, risk_flags, decision, next_watch_trigger,
           thesis_invalidation, recommended_route, recommended_notional, max_holding_time, review_at,
           summary_text, status, created_by)
           VALUES($1,$2,$3,$4,$5,$6::jsonb,$7::jsonb,$8::jsonb,$9,$10,$11,$12,$13,$14,$15,$16,$17,$18)
           RETURNING id""",
        sym, str(body.get("product_code") or "C2.P"), str(body.get("review_mode") or "QUICK"),
        str(body.get("market_stage") or ""), str(body.get("confidence_level") or ""),
        json.dumps(body.get("evidence_for") or [], ensure_ascii=False),
        json.dumps(body.get("evidence_against") or [], ensure_ascii=False),
        json.dumps(body.get("risk_flags") or [], ensure_ascii=False),
        str(body.get("decision") or "OBSERVE"), str(body.get("next_watch_trigger") or ""),
        str(body.get("thesis_invalidation") or ""), str(body.get("recommended_route") or ""),
        (float(body["recommended_notional"]) if body.get("recommended_notional") not in (None, "") else None),
        str(body.get("max_holding_time") or ""), review_at, summary, status,
        str(who.get("operator") or who.get("username") or "viewer"))
    return {"ok": True, "id": row["id"], "status": status, "summary_text": summary,
            "note": "研判只产结论不产订单" + (";结论=准备计划→可生成人工计划(DRY_RUN)" if
                                            body.get("decision") == "PREPARE_PLAN" else "")}


@router.put("/research/cases/{cid}")
async def research_case_update(cid: int, body: dict, who=Depends(require_viewer)):
    pool = await _pool()
    row = await pool.fetchrow("SELECT status FROM c2p_research_decision WHERE id=$1", cid)
    if not row:
        raise HTTPException(404, "案件不存在")
    if row["status"] != "DRAFT":
        raise HTTPException(409, "只能修改草稿;已完成案件只追加新案件(证据不可覆盖)")
    _validate_case(body)
    await pool.execute(
        """UPDATE c2p_research_decision SET market_stage=$2, confidence_level=$3, evidence_for=$4::jsonb,
           evidence_against=$5::jsonb, risk_flags=$6::jsonb, decision=$7, next_watch_trigger=$8,
           thesis_invalidation=$9, recommended_route=$10, recommended_notional=$11, max_holding_time=$12,
           summary_text=$13, updated_at=now() WHERE id=$1""",
        cid, str(body.get("market_stage") or ""), str(body.get("confidence_level") or ""),
        json.dumps(body.get("evidence_for") or [], ensure_ascii=False),
        json.dumps(body.get("evidence_against") or [], ensure_ascii=False),
        json.dumps(body.get("risk_flags") or [], ensure_ascii=False),
        str(body.get("decision") or "OBSERVE"), str(body.get("next_watch_trigger") or ""),
        str(body.get("thesis_invalidation") or ""), str(body.get("recommended_route") or ""),
        (float(body["recommended_notional"]) if body.get("recommended_notional") not in (None, "") else None),
        str(body.get("max_holding_time") or ""),
        str(body.get("summary_text") or "").strip() or _summary(str(body.get("symbol") or ""), body))
    return {"ok": True, "id": cid}


@router.post("/research/cases/{cid}/complete")
async def research_case_complete(cid: int, body: dict | None = None, who=Depends(require_viewer)):
    """complete 只生成/固化研究结论(§5)——不生成订单,不改交易状态。"""
    pool = await _pool()
    row = await pool.fetchrow("SELECT * FROM c2p_research_decision WHERE id=$1", cid)
    if not row:
        raise HTTPException(404, "案件不存在")
    summary = str((body or {}).get("summary_text") or "").strip() or row["summary_text"] or \
        _summary(row["canonical_symbol"], _case_row(row))
    await pool.execute(
        "UPDATE c2p_research_decision SET status='COMPLETED', summary_text=$2, updated_at=now() WHERE id=$1",
        cid, summary)
    return {"ok": True, "id": cid, "status": "COMPLETED", "summary_text": summary}


# ─────────────────────────── 人工计划(§5,C2.P) ───────────────────────────

# 人工计划可选产品(泛产品化批次):计划产品=研判案件的 product_code,不再写死 C2.P。
# 全部产品同一纪律:研判先行→DRY_RUN→冷却→二次认证→shadow 终态,无产品能绕。
_PLAN_PRODUCTS = {"C1", "C2.H", "C2.C", "C2.P", "C3.S", "C3.R", "C4", "C5", "C6", "O1"}


@router.post("/work-items/create-manual-plan")
async def create_manual_plan(body: dict, op=Depends(require_operator)):
    """研判→人工计划:走既有 dry_run_proposal 权威(冷却+二次认证链不变,不建第二写入口)。
    research_case_id 必填且结论必须=PREPARE_PLAN——证据先行,计划挂研判;产品取研判案件。"""
    from .maintenance import block_new_risk
    await block_new_risk()
    pool = await _pool()
    rcid = body.get("research_case_id")
    if not rcid:
        raise HTTPException(400, "research_case_id 必填(人工计划必须挂研判案件——证据先行)")
    case = await pool.fetchrow("SELECT * FROM c2p_research_decision WHERE id=$1", int(rcid))
    if not case:
        raise HTTPException(404, "研判案件不存在")
    if case["status"] != "COMPLETED" or case["decision"] != "PREPARE_PLAN":
        raise HTTPException(409, f"研判未完成或结论非『准备计划』(status={case['status']},decision={case['decision']})")
    if case["proposal_id"]:
        raise HTTPException(409, f"该研判已生成计划(proposal #{case['proposal_id']}),一案一计划")
    product = str(case["product_code"] or "C2.P")
    if product not in _PLAN_PRODUCTS:
        raise HTTPException(400, f"产品 {product} 不在人工计划白名单({'/'.join(sorted(_PLAN_PRODUCTS))})")
    sym = case["canonical_symbol"] + ("" if case["canonical_symbol"].endswith("USDT") else "USDT")
    notional = float(body.get("notional") or case["recommended_notional"] or 0)
    if notional <= 0:
        raise HTTPException(400, "notional 必填(>0)")
    vl = str(body.get("venue_long") or "").strip()
    vs = str(body.get("venue_short") or "").strip()
    pol = await ds.get_json("dcm:risk:policy") or {}
    econ = {"origin": "manual_research", "research_case_id": int(rcid),
            "research_summary": case["summary_text"],
            "thesis_invalidation": case["thesis_invalidation"],
            "policy_version": pol.get("policy_version"), "policy_epoch": pol.get("policy_epoch"),
            "snapped_at": int(time.time())}
    from .proposal import _PROP_DDL, COOLDOWN_SEC
    await pool.execute(_PROP_DDL)
    row = await pool.fetchrow(
        "INSERT INTO dry_run_proposal(symbol, product, venue_long, venue_short, target_notional, "
        "econ_snapshot, state, cooldown_until, created_by, note) "
        "VALUES($1,$2,$3,$4,$5,$6::jsonb,'COOLDOWN', now() + ($7||' seconds')::interval, $8, $9) RETURNING id",
        sym, product, vl, vs, notional, json.dumps(econ, ensure_ascii=False), str(COOLDOWN_SEC),
        str(op.get("operator") or "op"), f"{product}人工计划·研判#{rcid}")
    await pool.execute(
        "UPDATE c2p_research_decision SET proposal_id=$2, updated_at=now() WHERE id=$1", int(rcid), row["id"])
    return {"ok": True, "proposal_id": row["id"], "product": product, "state": "COOLDOWN",
            "cooldown_sec": COOLDOWN_SEC,
            "note": (f"{product} 人工计划已进 DRY_RUN 冷却+二次认证链;批准后仍为 shadow 终态——"
                     "真实执行按 SOP 放行(C2系并入 exec-manager shadow→人工翻 armed;C3系执行权威在 coin)")}


@router.get("/work-items/plan-preview")
async def plan_preview(symbol: str = Query(...), notional: float = Query(0),
                       venue_long: str = "", venue_short: str = "",
                       research_case_id: int | None = None, _who=Depends(require_viewer)):
    """计划预览(§5):路线/费/滑点/资金费/退出容量/最坏退出/失效条件——全 envelope,只读不落库。"""
    pool = await _pool()
    sym = symbol.strip().upper()
    now_iso = dt.datetime.now(dt.timezone.utc).isoformat()
    venues = await _venue_rows(sym)
    fmap = {v["venue"]: v["funding_daily_pct"] for v in venues if v["funding_daily_pct"] is not None}
    # 路线:显式传入优先;否则按费差自动建议(空腿=费率最高所,多腿=最低所)
    if not (venue_long and venue_short) and len(fmap) >= 2:
        venue_short = max(fmap, key=fmap.get)
        venue_long = min(fmap, key=fmap.get)
    gap = (round(fmap[venue_short] - fmap[venue_long], 4)
           if venue_long in fmap and venue_short in fmap else None)
    sp = {v["venue"]: v["spread_bps"] for v in venues if v["spread_bps"] is not None}
    leg_spread = (sp.get(venue_long), sp.get(venue_short))
    has_n = notional and notional > 0
    fees = round(notional * 0.0005 * 4, 2) if has_n else None      # 4×taker 开平往返(估)
    slip = (round(notional * (leg_spread[0] + leg_spread[1]) / 2 / 10000, 2)
            if has_n and None not in leg_spread else None)
    fund_d = round(notional * (gap or 0) / 100, 2) if has_n and gap is not None else None
    pub = await _binance_public(sym)
    worst = (round((fees or 0) + 2 * (slip or 0), 2) if has_n and fees is not None else None)
    inval = ""
    if research_case_id:
        c = await pool.fetchrow(
            "SELECT thesis_invalidation FROM c2p_research_decision WHERE id=$1", research_case_id)
        inval = (c["thesis_invalidation"] if c else "") or ""
    wi = lambda v, **kw: dv(v, as_of=now_iso, **kw)   # noqa: E731
    need = "WAITING_INPUT"
    return {"symbol": sym, "as_of": now_iso,
            "route": {"venue_long": venue_long or None, "venue_short": venue_short or None,
                      "template": "DERIVATIVE_LONG_DERIVATIVE_SHORT",
                      "source": "funding_feed 自动建议(可改)" if gap is not None else "费差覆盖不足"},
            "preview": {
                "notional_usdt": wi(notional if has_n else None,
                                    state=None if has_n else need, reason="" if has_n else "输入金额后计算"),
                "funding_gap_daily_pct": wi(gap, source="funding_feed",
                                            reason="" if gap is not None else "FUNDING_COVERAGE_LT_2"),
                "expected_funding_daily_usdt": wi(fund_d, state=None if fund_d is not None else need,
                                                  reason="" if fund_d is not None else "需金额+费差"),
                "est_fees_usdt": wi(fees, state=None if fees is not None else need,
                                    reason="" if fees is not None else "输入金额后计算(4×taker)"),
                "est_slippage_usdt": wi(slip, state=None if slip is not None else
                                        (need if not has_n else "NOT_CONNECTED"),
                                        reason="" if slip is not None else "两腿L1点差缺失或金额未定"),
                "exit_capacity_25bps_usdt": wi(pub.get("depth_buy_usdt"), source="binance_public",
                                               reason=pub.get("depth_err") or ""),
                "worst_exit_cost_usdt": wi(worst, state=None if worst is not None else need,
                                           reason="" if worst is not None else "输入金额后计算"),
            },
            "thesis_invalidation": inval or "(未挂研判案件)",
            "risk_note": "预览为估算,审批时以经济快照为准;批准后仍 shadow,不直接下单"}
