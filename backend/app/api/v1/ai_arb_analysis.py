"""AI 套利分析(testadmin)。

硬约束: 分析数据只来自 (1)rust引擎8090已有的实时点差缓存(WS已收数据,读缓存)
(2)spread_records 历史落库 —— 零新增交易所 WS/REST 请求, 不影响正常交易限额。
LLM 复用 OpenClaw codex_client(熔断降级)。管理员从对冲平台列表(hedging_pairs)
自选平台x产品对; 结果存 ai_arb_analysis 可回看。另含 manual_ledger 跨用户汇总。
"""
import json
import logging
import os
import time as _time_mod
from typing import Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import text

from app.core.database import AsyncSessionLocal
from app.api.v1.auth import get_current_user_id

logger = logging.getLogger(__name__)
router = APIRouter()

RUST_BASE = os.getenv("RUST_ENGINE_URL", "http://127.0.0.1:8090")

ANALYSIS_SYSTEM_PROMPT = (
    "你是跨所对冲套利分析师。给定若干产品对的实时点差、历史点差分布、数据新鲜度, "
    "输出结构化分析。正向点差=A腿卖/B腿买的进场价差, 反向相反; 分析聚焦: "
    "哪些对当前相对历史分布存在异常价差/回归机会、建议开仓阈值区间、"
    "风险(数据陈旧/流动性/资金费)。\n"
    "输出严格JSON(无额外文字):\n"
    '{"summary":"总体判断(<100字)","pairs":[{"pair_code":"...",'
    '"opportunity":"high|medium|low|none","suggested_open_range":[0,0],'
    '"rationale":"<80字","risks":["..."]}],"caveats":["数据层面注意事项"]}'
)


class AnalyzeReq(BaseModel):
    pair_codes: list = Field(..., min_length=1, max_length=17)
    window_h: int = Field(24, ge=1, le=168)


async def _require_admin(db, user_id: str):
    role = (await db.execute(text(
        "SELECT role FROM users WHERE user_id=CAST(:u AS UUID)"), {"u": user_id})).scalar()
    if role not in ("超级管理员", "系统管理员", "管理员", "admin", "super_admin"):
        raise HTTPException(status_code=403, detail="仅管理员可用")


@router.get("/targets")
async def list_targets(user_id: str = Depends(get_current_user_id)):
    """下拉数据源: 对冲平台列表(平台x产品对), 标注哪些有24h历史点差。"""
    async with AsyncSessionLocal() as db:
        await _require_admin(db, user_id)
        rows = (await db.execute(text("""
            SELECT hp.pair_code, pa.platform_name, sa.symbol, pb.platform_name, sb.symbol, hp.is_active,
                   EXISTS(SELECT 1 FROM spread_records sr WHERE sr.symbol=sa.symbol
                          AND sr.timestamp > (now() at time zone 'utc')-interval '24 hours') AS has_history
            FROM hedging_pairs hp
            JOIN platform_symbols sa ON hp.symbol_a_id=sa.id JOIN platforms pa ON sa.platform_id=pa.platform_id
            JOIN platform_symbols sb ON hp.symbol_b_id=sb.id JOIN platforms pb ON sb.platform_id=pb.platform_id
            ORDER BY hp.is_active DESC, hp.pair_code
        """))).all()
    return {"targets": [{
        "pair_code": r[0], "platform_a": r[1], "symbol_a": r[2],
        "platform_b": r[3], "symbol_b": r[4], "is_active": r[5], "has_history": r[6],
    } for r in rows]}


async def _rust_spread(client: httpx.AsyncClient, pair: str) -> Optional[dict]:
    try:
        r = await client.get(f"{RUST_BASE}/api/v1/market/spread", params={"pair": pair})
        if r.status_code == 200:
            return r.json()
    except Exception:
        pass
    return None


async def _collect_stats(db, pair_codes: list, window_h: int) -> list:
    """聚合: 实时点差(rust缓存)+历史分布(spread_records)+新鲜度。零交易所请求。"""
    out = []
    async with httpx.AsyncClient(timeout=5.0) as client:
        for pc in pair_codes:
            meta = (await db.execute(text("""
                SELECT sa.symbol, pa.platform_name, pb.platform_name
                FROM hedging_pairs hp
                JOIN platform_symbols sa ON hp.symbol_a_id=sa.id JOIN platforms pa ON sa.platform_id=pa.platform_id
                JOIN platform_symbols sb ON hp.symbol_b_id=sb.id JOIN platforms pb ON sb.platform_id=pb.platform_id
                WHERE hp.pair_code=:pc
            """), {"pc": pc})).first()
            if not meta:
                continue
            live = await _rust_spread(client, pc)
            hist = (await db.execute(text("""
                SELECT count(*),
                       round(avg(forward_spread)::numeric,3),
                       round((percentile_cont(0.1) WITHIN GROUP (ORDER BY forward_spread))::numeric,3),
                       round((percentile_cont(0.5) WITHIN GROUP (ORDER BY forward_spread))::numeric,3),
                       round((percentile_cont(0.9) WITHIN GROUP (ORDER BY forward_spread))::numeric,3),
                       round(avg(reverse_spread)::numeric,3),
                       round((percentile_cont(0.5) WITHIN GROUP (ORDER BY reverse_spread))::numeric,3)
                FROM spread_records WHERE symbol=:sym
                  AND timestamp > (now() at time zone 'utc') - make_interval(hours=>:h)
            """), {"sym": meta[0], "h": window_h})).first()
            stale_s = None
            if live:
                try:
                    ts = max(live.get("a_quote", {}).get("timestamp", 0),
                             live.get("b_quote", {}).get("timestamp", 0))
                    stale_s = round(_time_mod.time() - ts / 1000, 1) if ts else None
                except Exception:
                    pass
            out.append({
                "pair_code": pc, "platform_a": meta[1], "platform_b": meta[2],
                "live": ({"forward_entry": live.get("forward_entry_spread"),
                          "reverse_entry": live.get("reverse_entry_spread"),
                          "quote_stale_s": stale_s} if live else None),
                "history": ({"n": int(hist[0]), "f_avg": float(hist[1]), "f_p10": float(hist[2]),
                             "f_p50": float(hist[3]), "f_p90": float(hist[4]),
                             "r_avg": float(hist[5]), "r_p50": float(hist[6])}
                            if hist and hist[0] else None),
            })
    return out


@router.post("/analyze")
async def analyze(body: AnalyzeReq, user_id: str = Depends(get_current_user_id)):
    async with AsyncSessionLocal() as db:
        await _require_admin(db, user_id)
        stats = await _collect_stats(db, body.pair_codes, body.window_h)
        if not stats:
            raise HTTPException(status_code=400, detail="无有效产品对")
        from app.services.agent.codex_client import call_decider
        prop, tok, lat = await call_decider(
            ANALYSIS_SYSTEM_PROMPT,
            json.dumps({"window_h": body.window_h, "targets": stats}, ensure_ascii=False),
            db=db)
        if not isinstance(prop, dict) or prop.get("action") == "noop":
            raise HTTPException(status_code=503, detail="LLM 暂不可用(熔断中), 请稍后重试")
        r = await db.execute(text("""
            INSERT INTO ai_arb_analysis(targets, window_h, input_stats, analysis, model, created_by)
            VALUES (CAST(:t AS JSONB), :w, CAST(:i AS JSONB), CAST(:a AS JSONB), :m, CAST(:u AS UUID))
            RETURNING id, created_at
        """), {"t": json.dumps(body.pair_codes), "w": body.window_h,
               "i": json.dumps(stats, ensure_ascii=False),
               "a": json.dumps(prop, ensure_ascii=False),
               "m": os.getenv("OPENCLAW_LLM_MODEL", ""), "u": user_id})
        row = r.first()
        await db.commit()
    return {"id": row[0], "created_at": row[1].isoformat(), "input_stats": stats, "analysis": prop}


@router.get("/history")
async def history(limit: int = 20, user_id: str = Depends(get_current_user_id)):
    async with AsyncSessionLocal() as db:
        await _require_admin(db, user_id)
        rows = (await db.execute(text("""
            SELECT a.id, a.targets, a.window_h, a.analysis, a.created_at, u.username
            FROM ai_arb_analysis a LEFT JOIN users u ON u.user_id=a.created_by
            ORDER BY a.id DESC LIMIT :l
        """), {"l": min(limit, 100)})).all()
    return {"items": [{"id": r[0], "targets": r[1], "window_h": r[2],
                       "analysis": r[3], "created_at": r[4].isoformat(), "by": r[5]} for r in rows]}


@router.get("/ledger-summary")
async def ledger_summary(user_id: str = Depends(get_current_user_id)):
    """手工对账跨用户汇总: 每主账户预设/最新/累计/笔数/起止日+全站合计。"""
    async with AsyncSessionLocal() as db:
        await _require_admin(db, user_id)
        rows = (await db.execute(text("""
            WITH per_user AS (
                SELECT ml.user_id,
                       (array_agg(ml.total_amount ORDER BY ml.entry_date ASC))[1]  AS baseline,
                       (array_agg(ml.total_amount ORDER BY ml.entry_date DESC))[1] AS latest,
                       min(ml.entry_date) AS first_date,
                       max(ml.entry_date) AS last_date,
                       count(*) AS n
                FROM manual_ledger ml GROUP BY ml.user_id)
            SELECT u.username, p.baseline, p.latest, p.latest - p.baseline AS cumulative,
                   p.first_date, p.last_date, p.n
            FROM per_user p JOIN users u ON u.user_id = p.user_id
            ORDER BY u.username
        """))).all()
    items = [{
        "username": r[0], "baseline": float(r[1]), "latest": float(r[2]),
        "cumulative_pnl": round(float(r[3]), 2),
        "first_date": r[4].isoformat(), "last_date": r[5].isoformat(), "entry_count": int(r[6]),
    } for r in rows]
    return {"items": items, "total": {
        "baseline": round(sum(i["baseline"] for i in items), 2),
        "latest": round(sum(i["latest"] for i in items), 2),
        "cumulative_pnl": round(sum(i["cumulative_pnl"] for i in items), 2),
        "users": len(items),
    }}


@router.get("/ledger-detail")
async def ledger_detail(username: str, user_id: str = Depends(get_current_user_id)):
    """明细钻取: admin 查指定用户的逐日手工记账 + 系统日收益对账差值。"""
    async with AsyncSessionLocal() as db:
        await _require_admin(db, user_id)
        tgt = (await db.execute(text(
            "SELECT user_id FROM users WHERE username=:un"), {"un": username})).scalar()
        if not tgt:
            raise HTTPException(status_code=404, detail="用户不存在")
        rows = (await db.execute(text("""
            SELECT entry_date, total_amount, daily_pnl, is_baseline, note, updated_at
            FROM manual_ledger WHERE user_id=CAST(:u AS UUID) ORDER BY entry_date DESC
        """), {"u": str(tgt)})).all()
        # 系统日收益(北京日): binance income(非TRANSFER)+mt5平仓
        dates = [r[0] for r in rows]
        sys_map = {}
        if dates:
            srows = (await db.execute(text("""
                WITH aids AS (SELECT account_id FROM accounts WHERE user_id=CAST(:u AS UUID)),
                b AS (SELECT (to_timestamp(income_time_ms/1000)+interval '8 hours')::date d, sum(income) v
                      FROM binance_income WHERE account_id IN (SELECT account_id FROM aids)
                        AND income_type<>'TRANSFER' GROUP BY 1),
                m AS (SELECT (deal_time_utc+interval '8 hours')::date d, sum(profit+swap+commission) v
                      FROM mt5_deals WHERE account_id IN (SELECT account_id FROM aids)
                        AND entry=1 AND symbol<>'' GROUP BY 1)
                SELECT COALESCE(b.d,m.d) d, COALESCE(b.v,0)+COALESCE(m.v,0) v
                FROM b FULL OUTER JOIN m ON b.d=m.d
                WHERE COALESCE(b.d,m.d)=ANY(CAST(:ds AS date[]))
            """), {"u": str(tgt), "ds": dates})).all()
            sys_map = {r[0].isoformat(): float(r[1]) for r in srows}
    entries = []
    for r in rows:
        dk = r[0].isoformat(); sysv = sys_map.get(dk); manual = float(r[2])
        entries.append({
            "entry_date": dk, "total_amount": float(r[1]), "daily_pnl": manual,
            "is_baseline": bool(r[3]), "note": r[4],
            "sys_pnl": (round(sysv, 2) if sysv is not None else None),
            "diff": (round(manual - sysv, 2) if (sysv is not None and not r[3]) else None),
        })
    return {"username": username, "entries": entries}
