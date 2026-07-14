"""exec-kernel shadow 对账 loop(V4.0 §6.2/§11.1)—— B 机运行,零下单。
读 dcm_main 引擎声称的持仓(期望)对比 RealVenue 交易所真相(实际),逐腿分类:
  MATCH        期望与实盘一致
  QTY_MISMATCH 数量超容差
  ORPHAN_CLAIM 引擎声称在管,实盘却是平的(引擎侧幻仓/漏平)
  NAKED_EXCHANGE 实盘有仓,引擎无声称(内核不知道的裸仓,最危险)
  UNCHECKABLE  腿在尚无适配器的 venue(gate/bybit/okx/bitget/HL)——诚实标注,不假装对账
发布 dcm:exec:recon + 心跳 dcm:hb:exec-recon(TTL 300)。**只读,绝不下单**。
"""
import asyncio
import json
import os
import sys
import time

import asyncpg
import redis.asyncio as aioredis

sys.path.insert(0, "/home/ec2-user/dexcexmix")
from real_venue import BinanceRealVenue  # noqa: E402

DCM_PG_DSN = os.environ.get("DCM_PG_DSN", "")
REDIS_URL = os.environ.get("DCM_REDIS_URL", "redis://10.0.1.212:6379/0")
INTERVAL = int(os.environ.get("DCM_RECON_INTERVAL_SEC", "120"))
TOL_PCT = float(os.environ.get("DCM_RECON_TOL_PCT", "0.02"))   # 2% 数量容差
SUPPORTED = {"binance"}   # 已有 RealVenue 适配器的 venue


def _canon(sym):
    for s in ("USDT", "USDC", "USD"):
        if sym.endswith(s):
            return sym[:-len(s)]
    return sym


async def reconcile(pool, venue, r) -> dict:
    breaks = []
    matched = unchecked = 0
    expected_binance = {}   # symbol -> {source, exp_qty}

    # C1 basis:binance 期现,永续空腿数量 ~ qty_base
    for row in await pool.fetch(
            "SELECT symbol, qty_base FROM basis_positions WHERE state NOT IN ('CLOSED','FAILED')"):
        expected_binance[row["symbol"]] = {"source": f"C1basis:{row['symbol']}", "exp_qty": float(row["qty_base"] or 0)}

    # C2 dualperp:逐腿,binance 腿可查,其余标 UNCHECKABLE
    for row in await pool.fetch(
            "SELECT symbol, venue_long, venue_short, qty_base FROM dualperp_positions "
            "WHERE state NOT IN ('CLOSED','FAILED')"):
        for side, v in (("long", row["venue_long"]), ("short", row["venue_short"])):
            if v == "binance":
                expected_binance[row["symbol"]] = {"source": f"C2:{row['symbol']}:{side}",
                                                   "exp_qty": float(row["qty_base"] or 0)}
            elif v not in SUPPORTED:
                unchecked += 1
                breaks.append({"type": "UNCHECKABLE", "symbol": row["symbol"], "venue": v,
                               "note": f"{v} 适配器未建,无法对账该腿"})

    # C3 coin:hedge 腿在 binance 主账户(快照)
    try:
        snap = json.loads(await r.get("dcm:engine:coin:positions") or "{}")
        for p in (snap.get("positions") or []):
            if str(p.get("status")) in ("OPEN", "BORROWED_IDLE", "PENDING_REPAY"):
                sym = str(p.get("symbol") or "")
                expected_binance.setdefault(sym, {"source": f"C3coin:{sym}", "exp_qty": None})
    except Exception:  # noqa: BLE001
        pass

    # 实盘全量(binance)
    allp = await venue.all_positions()
    actual = allp.get("positions", {}) if allp.get("ok") else {}

    # 逐期望腿对账
    for sym, exp in expected_binance.items():
        amt = actual.pop(sym, None)
        if amt is None or abs(amt) < 1e-12:
            breaks.append({"type": "ORPHAN_CLAIM", "symbol": sym, "source": exp["source"],
                           "note": "引擎声称在管,binance 实盘却是平的"})
            continue
        eq = exp["exp_qty"]
        if eq is None:
            matched += 1   # C3 无精确期望数量,只确认非平
            continue
        if eq > 0 and abs(abs(amt) - eq) / eq > TOL_PCT:
            breaks.append({"type": "QTY_MISMATCH", "symbol": sym, "source": exp["source"],
                           "expected": eq, "actual": abs(amt),
                           "diff_pct": round(abs(abs(amt) - eq) / eq * 100, 3)})
        else:
            matched += 1

    # 剩余 actual = 实盘有仓但无期望声称 = 裸露实盘(最危险)
    for sym, amt in actual.items():
        breaks.append({"type": "NAKED_EXCHANGE", "symbol": sym, "actual": amt,
                       "note": "binance 实盘有仓但引擎无声称——内核不知道的裸仓"})

    summary = {"ts": int(time.time()), "matched": matched, "unchecked": unchecked,
               "breaks": breaks, "supported_venues": sorted(SUPPORTED)}
    await r.set("dcm:exec:recon", json.dumps(summary, ensure_ascii=False), ex=max(INTERVAL * 3, 600))
    return summary


async def main():
    if not DCM_PG_DSN:
        print("DCM_PG_DSN 未设"); return
    pool = await asyncpg.create_pool(DCM_PG_DSN, min_size=1, max_size=2, command_timeout=10)
    r = aioredis.from_url(REDIS_URL, decode_responses=True)
    venue = BinanceRealVenue()
    once = "--once" in sys.argv
    while True:
        try:
            s = await reconcile(pool, venue, r)
            nb = len(s["breaks"])
            print(f"recon: matched={s['matched']} unchecked={s['unchecked']} breaks={nb} "
                  + (json.dumps([b['type'] for b in s['breaks']]) if nb else "全绿"))
            await r.set("dcm:hb:exec-recon", json.dumps({"ts": int(time.time()), "pid": os.getpid(),
                        "service": "exec-recon", "breaks": nb}), ex=300)
        except Exception as e:  # noqa: BLE001
            print("recon err:", repr(e)[:150])
        if once:
            break
        await asyncio.sleep(INTERVAL)


if __name__ == "__main__":
    asyncio.run(main())
