"""exec-kernel shadow 对账 loop(V4.0 §6.2/§11.1)—— B 机运行,零下单,多所。
读 dcm_main 引擎声称持仓(期望)对比各所 RealVenue 交易所真相(实际),逐腿分类:
  MATCH / QTY_MISMATCH / SIDE_MISMATCH / ORPHAN_CLAIM(声称在管实盘平)/
  NAKED_EXCHANGE(实盘有仓内核不知=最危险)/ UNCHECKABLE(venue 无适配器)
已支持 venue:binance/bybit/gate/bitget(okx/HL 待补)。发布 dcm:exec:recon + 心跳。**只读。**
"""
import asyncio
import json
import os
import sys
import time

import asyncpg
import redis.asyncio as aioredis

sys.path.insert(0, "/home/ec2-user/dexcexmix")
from real_venue import venue_for  # noqa: E402

DCM_PG_DSN = os.environ.get("DCM_PG_DSN", "")
REDIS_URL = os.environ.get("DCM_REDIS_URL", "redis://10.0.1.212:6379/0")
INTERVAL = int(os.environ.get("DCM_RECON_INTERVAL_SEC", "120"))
TOL_PCT = float(os.environ.get("DCM_RECON_TOL_PCT", "0.02"))
SUPPORTED = {"binance", "bybit", "gate", "bitget", "okx", "hyperliquid"}


def _venue_sym(venue, sym):
    """各所符号格式:gate=BASE_USDT / okx=BASE-USDT-SWAP / HL=BASE(币名);其余同 dcm(BASEUSDT)。"""
    if not sym.endswith("USDT"):
        return sym
    base = sym[:-4]
    if venue == "gate":
        return base + "_USDT"
    if venue == "okx":
        return base + "-USDT-SWAP"
    if venue == "hyperliquid":
        return base
    return sym


async def _venue_positions(venue):
    v = venue_for(venue)
    if v is None or not hasattr(v, "all_positions"):
        return None
    r = await v.all_positions()
    return r.get("positions", {}) if r.get("ok") else None


async def reconcile(pool, r) -> dict:
    # 期望:{venue: {venue_sym: {source, exp_qty, exp_sign}}}
    expected = {v: {} for v in SUPPORTED}
    unchecked = []

    def add(venue, sym, source, qty, sign):
        if venue in SUPPORTED:
            expected[venue][_venue_sym(venue, sym)] = {"source": source, "exp_qty": qty, "exp_sign": sign}
        else:
            unchecked.append({"type": "UNCHECKABLE", "symbol": sym, "venue": venue,
                              "note": f"{venue} 适配器未建"})

    # C1 basis:binance 永续空腿(-qty_base);现货腿是余额非持仓,暂不在此对账
    for row in await pool.fetch(
            "SELECT symbol, qty_base FROM basis_positions WHERE state NOT IN ('CLOSED','FAILED')"):
        add("binance", row["symbol"], f"C1:{row['symbol']}:perp_short", float(row["qty_base"] or 0), -1)

    # C2 dualperp:多腿 +qty / 空腿 -qty
    for row in await pool.fetch(
            "SELECT symbol, venue_long, venue_short, qty_base FROM dualperp_positions "
            "WHERE state NOT IN ('CLOSED','FAILED')"):
        q = float(row["qty_base"] or 0)
        add(row["venue_long"], row["symbol"], f"C2:{row['symbol']}:long", q, +1)
        add(row["venue_short"], row["symbol"], f"C2:{row['symbol']}:short", q, -1)

    # C3 coin:binance 主账户对冲腿(快照,无精确数量→只确认非平)
    try:
        snap = json.loads(await r.get("dcm:engine:coin:positions") or "{}")
        for p in (snap.get("positions") or []):
            if str(p.get("status")) in ("OPEN", "BORROWED_IDLE", "PENDING_REPAY"):
                expected["binance"].setdefault(str(p.get("symbol") or ""),
                                               {"source": f"C3:{p.get('symbol')}", "exp_qty": None, "exp_sign": 0})
    except Exception:  # noqa: BLE001
        pass

    # exec-manager 接管仓(引擎退役后 manager=owner-of-record,无引擎 DB 行):
    # 读 dcm:exec:manager 发布态(20s刷新EX300;manager 死→键消失→接管仓如实转 NAKED 告警,fail-loud)。
    # pairs 腿的 symbol 已是 venue 格式(manager 存的就是 venue_sym 结果),直接入 expected。
    try:
        mgr = json.loads(await r.get("dcm:exec:manager") or "{}")
        for s in (mgr.get("symbols") or []):   # C1 形态:binance 永续腿
            amt = float(s.get("perp_amt") or 0)
            if abs(amt) > 1e-12:
                expected["binance"][str(s.get("symbol") or "")] = {
                    "source": f"MGR:{s.get('symbol')}:perp", "exp_qty": abs(amt),
                    "exp_sign": 1 if amt > 0 else -1}
        for p in (mgr.get("pairs") or []):     # C2 形态:跨所双永续腿
            for lg in (p.get("legs") or []):
                amt = float(lg.get("amt") or 0)
                v = lg.get("venue")
                if abs(amt) > 1e-12 and v in SUPPORTED:
                    expected[v][str(lg.get("symbol") or "")] = {
                        "source": f"MGR:{p.get('pair')}:{v}", "exp_qty": abs(amt),
                        "exp_sign": 1 if amt > 0 else -1}
    except Exception:  # noqa: BLE001
        pass

    breaks = list(unchecked)
    matched = 0
    for venue in SUPPORTED:
        if not expected[venue]:
            continue
        actual = await _venue_positions(venue)
        if actual is None:
            for sym, e in expected[venue].items():
                breaks.append({"type": "VENUE_READ_FAIL", "venue": venue, "symbol": sym, "source": e["source"]})
            continue
        actual = dict(actual)
        for sym, e in expected[venue].items():
            amt = actual.pop(sym, None)
            if amt is None or abs(amt) < 1e-12:
                breaks.append({"type": "ORPHAN_CLAIM", "venue": venue, "symbol": sym, "source": e["source"],
                               "note": "引擎声称在管,实盘平"})
                continue
            if e["exp_sign"] and (amt > 0) != (e["exp_sign"] > 0):
                breaks.append({"type": "SIDE_MISMATCH", "venue": venue, "symbol": sym, "source": e["source"],
                               "actual_sign": "+" if amt > 0 else "-"})
                continue
            eq = e["exp_qty"]
            if eq is None:
                matched += 1
                continue
            if eq > 0 and abs(abs(amt) - eq) / eq > TOL_PCT:
                breaks.append({"type": "QTY_MISMATCH", "venue": venue, "symbol": sym, "source": e["source"],
                               "expected": eq, "actual": abs(amt), "diff_pct": round(abs(abs(amt) - eq) / eq * 100, 3)})
            else:
                matched += 1
        # 该所剩余实盘 = 裸露仓(内核不知)
        for sym, amt in actual.items():
            breaks.append({"type": "NAKED_EXCHANGE", "venue": venue, "symbol": sym, "actual": amt,
                           "note": "实盘有仓但引擎无声称"})

    summary = {"ts": int(time.time()), "matched": matched, "supported_venues": sorted(SUPPORTED),
               "breaks": breaks, "break_types": sorted({b["type"] for b in breaks})}
    await r.set("dcm:exec:recon", json.dumps(summary, ensure_ascii=False), ex=max(INTERVAL * 3, 600))
    return summary


async def main():
    if not DCM_PG_DSN:
        print("DCM_PG_DSN 未设"); return
    pool = await asyncpg.create_pool(DCM_PG_DSN, min_size=1, max_size=2, command_timeout=10)
    r = aioredis.from_url(REDIS_URL, decode_responses=True)
    once = "--once" in sys.argv
    while True:
        try:
            s = await reconcile(pool, r)
            nb = len(s["breaks"])
            print(f"recon: matched={s['matched']} breaks={nb} " + (json.dumps(s["break_types"]) if nb else "全绿"))
            await r.set("dcm:hb:exec-recon", json.dumps({"ts": int(time.time()), "pid": os.getpid(),
                        "service": "exec-recon", "breaks": nb}), ex=300)
        except Exception as e:  # noqa: BLE001
            print("recon err:", repr(e)[:150])
        if once:
            break
        await asyncio.sleep(INTERVAL)


if __name__ == "__main__":
    asyncio.run(main())
