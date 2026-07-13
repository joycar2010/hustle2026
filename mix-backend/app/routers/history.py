"""交易历史 —— mix_main.trade_history 持久账（mix 拥有独立留存,不依赖上游保留时长）。
同步进料口（300s 后台任务,幂等 upsert）：
  S2/S1 ← dcm_main dualperp/basis 终态行（mix_ro 只读）
  S3   ← dcm:coin:closed（coin-bridge 终态透传,近7天滚动;历史一旦入 mix 库即永久）
借币主引擎在 coin,本表只是汇入的账本副本——字段口径:
  master=借币/多腿主体所在平台与账户, hedge=对冲腿平台与账户(hedge_via_master 显示真实执行账户)。"""
import json
import asyncio
import logging
import datetime as dt

from fastapi import APIRouter, Query, Depends, HTTPException

from ..deps import require_viewer
from .. import datasources as ds

log = logging.getLogger("mix.history")
router = APIRouter(tags=["history"])

SYNC_INTERVAL = 300


async def _upsert(pool, rows: list[tuple]):
    if not rows:
        return 0
    n = 0
    for r in rows:
        try:
            await pool.execute(
                "INSERT INTO trade_history(source,source_id,strategy_code,symbol,master_venue,"
                "master_account,hedge_venue,hedge_account,qty,notional,state,opened_at,closed_at,raw) "
                "VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14) "
                "ON CONFLICT (source,source_id) DO UPDATE SET state=$11, closed_at=$13, raw=$14", *r)
            n += 1
        except Exception as e:  # noqa: BLE001
            log.warning("upsert %s/%s: %s", r[0], r[1], e)
    return n


async def history_sync_once() -> dict:
    pool = await ds.pg_main()
    if pool is None:
        return {"error": "mix_main 未配置"}
    stats = {}
    # S2 dualperp（终态全量,幂等）
    dp = await ds.fetch(
        "SELECT id, symbol, venue_long, venue_short, account_long, account_short, qty_base, "
        "notional_usdt, state, opened_at, closed_at FROM dualperp_positions "
        "WHERE state IN ('CLOSED','FAILED')")
    stats["S2"] = await _upsert(pool, [(
        "dualperp", r["id"], "S2", r["symbol"],
        r["venue_long"], r["account_long"] or r["venue_long"],
        r["venue_short"], r["account_short"] or r["venue_short"],
        r["qty_base"], r["notional_usdt"], r["state"], r["opened_at"], r["closed_at"], None,
    ) for r in dp])
    # S1 basis（币安单所期现:主=现货腿 对冲=永续空腿）
    bs = await ds.fetch(
        "SELECT id, symbol, qty_base, notional_usdt, state, opened_at, closed_at "
        "FROM basis_positions WHERE state IN ('CLOSED','FAILED')")
    stats["S1"] = await _upsert(pool, [(
        "basis", r["id"], "S1", r["symbol"],
        "binance", "spot(主账户)", "binance", "perp(主账户)",
        r["qty_base"], r["notional_usdt"], r["state"], r["opened_at"], r["closed_at"], None,
    ) for r in bs])
    # S3 coin（桥终态透传;sub 备注名从面板 note 映射）
    closed = await ds.get_json("dcm:coin:closed") or {}
    panel = await ds.get_json("dcm:coin:panel") or {}
    notes = {a.get("account_id"): a.get("note")
             for a in (panel.get("balances") or {}).get("balances") or []}
    rows = []
    for p in closed.get("positions") or []:
        hedge = str(p.get("hedge_account") or "")
        rows.append((
            "coin", int(p["id"]), "S3", p.get("symbol", ""),
            "binance", notes.get(p.get("sub_account_id")) or f"sub:{p.get('sub_account_id')}",
            ("okx" if hedge == "okx" else "binance"),
            ("joycar002" if hedge == "okx" else "主账户(hedge_via_master)"),
            p.get("borrow_qty"), p.get("open_usdt_amount"), p.get("status"),
            dt.datetime.fromtimestamp(int(p["opened_ts"]), dt.timezone.utc) if p.get("opened_ts") else None,
            dt.datetime.fromtimestamp(int(p["closed_ts"]), dt.timezone.utc) if p.get("closed_ts") else None,
            json.dumps(p, ensure_ascii=False, default=str),
        ))
    stats["S3"] = await _upsert(pool, rows)
    return stats


async def history_sync_loop():
    while True:
        try:
            stats = await history_sync_once()
            log.info("HISTORY_SYNC %s", stats)
        except Exception as e:  # noqa: BLE001
            log.warning("history sync: %s", e)
        await asyncio.sleep(SYNC_INTERVAL)


async def _trade_economics(trades: list[dict]) -> None:
    """逐笔经济学归因：income_records(交易所已入账账单)按 币种+持有窗 归到每笔。
    口径=落袋(FUNDING/FEE/PNL/返佣=OTHER中REBATE),不含浮盈;S3(coin账本在coin库)给 None 如实标注。
    窗口=开仓-5min ~ 平仓+30min(资金费结算/平仓账单落账延迟缓冲)。"""
    wins = [t for t in trades if t["source"] in ("dualperp", "basis") and t["opened_at"] and t["closed_at"]]
    if not wins:
        return
    syms = sorted({t["symbol"] for t in wins})
    lo = min(t["opened_at"] for t in wins) - dt.timedelta(minutes=5)
    hi = max(t["closed_at"] for t in wins) + dt.timedelta(minutes=30)
    rows = await ds.fetch(
        "SELECT symbol, itype, amount, ts, "
        "(coalesce(raw->>'incomeType','') ILIKE '%REBATE%') AS is_rebate "
        "FROM income_records WHERE symbol = ANY($1::text[]) AND ts BETWEEN $2 AND $3 "
        "AND itype <> 'TRANSFER'", syms, lo, hi)
    by_sym: dict[str, list] = {}
    for r in rows:
        by_sym.setdefault(r["symbol"], []).append(r)
    for t in wins:
        f = fee = pnl = reb = 0.0
        for r in by_sym.get(t["symbol"], []):
            if not (t["opened_at"] - dt.timedelta(minutes=5) <= r["ts"]
                    <= t["closed_at"] + dt.timedelta(minutes=30)):
                continue
            amt = float(r["amount"])
            if r["itype"] == "FUNDING":
                f += amt
            elif r["itype"] == "FEE":
                fee += amt
            elif r["itype"] == "PNL":
                pnl += amt
            elif r["is_rebate"]:
                reb += amt
        t["funding"] = round(f, 4)
        t["fee"] = round(fee, 4)
        t["rebate"] = round(reb, 4)
        t["pnl"] = round(pnl, 4)
        t["profit"] = round(f + fee + pnl + reb, 4)


def _parse_ts(v: str):
    try:
        return dt.datetime.fromisoformat(v.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None


@router.get("/history")
async def get_history(
    range: str = Query(default="30d"),
    strategy: str = Query(default=""),
    start: str = Query(default=""),
    end: str = Query(default=""),
    limit: int = Query(default=200, le=1000),
    _who=Depends(require_viewer),
):
    pool = await ds.pg_main()
    if pool is None:
        raise HTTPException(503, "mix_main 未配置")
    args: list = []
    ts_s, ts_e = _parse_ts(start), _parse_ts(end)
    if ts_s and ts_e:
        cond = "WHERE closed_at BETWEEN $1 AND $2"
        args = [ts_s, ts_e]
    else:
        days = {"7d": 7, "30d": 30, "90d": 90, "all": 3650}.get(range, 30)
        cond = "WHERE closed_at > now() - make_interval(days => $1)"
        args = [days]
    if strategy:
        cond += f" AND strategy_code = ${len(args) + 1}"
        args.append(strategy)
    rows = await pool.fetch(
        f"SELECT source, source_id, strategy_code, symbol, master_venue, master_account, "
        f"hedge_venue, hedge_account, qty, notional, state, opened_at, closed_at "
        f"FROM trade_history {cond} ORDER BY closed_at DESC NULLS LAST LIMIT {int(limit)}", *args)
    trades = []
    for r in rows:
        hold_h = None
        if r["opened_at"] and r["closed_at"]:
            hold_h = round((r["closed_at"] - r["opened_at"]).total_seconds() / 3600, 1)
        trades.append({**dict(r),
                       "qty": float(r["qty"]) if r["qty"] is not None else None,
                       "notional": float(r["notional"]) if r["notional"] is not None else None,
                       "hold_hours": hold_h,
                       "funding": None, "fee": None, "rebate": None, "pnl": None, "profit": None})
    await _trade_economics(trades)
    stats = {"count": len(trades),
             "notional": round(sum(t["notional"] or 0 for t in trades), 2),
             "funding": round(sum(t["funding"] or 0 for t in trades), 4),
             "fee": round(sum(t["fee"] or 0 for t in trades), 4),
             "rebate": round(sum(t["rebate"] or 0 for t in trades), 4),
             "profit": round(sum(t["profit"] or 0 for t in trades), 4),
             "note": "口径=落袋账单(S1/S2);S3 账本在 coin 库暂标 —"}
    for t in trades:
        t["opened_at"] = t["opened_at"].isoformat() if t["opened_at"] else None
        t["closed_at"] = t["closed_at"].isoformat() if t["closed_at"] else None
    return {"rows": trades, "stats": stats}
