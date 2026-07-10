"""engine-basis(shadow):币安期现底仓 carry 评估器(收益地板层)。

结构:币安现货多 + 永续空,收正资金费(+可质押现货腿转理财=双份收益,shadow 期先只算资金费)。
单所双腿(同账户),无跨所保证金对称问题,容量最大零转账风险——蓝图第 1 层。

shadow 自驱:扫币安 funding 哈希取正资金费币,读现货+永续 L1 算净期望 E:
  E = 资金费收益(日化%×HORIZON×100) − 往返价差(买现货ask+卖永续bid, 平仓反向) − 双边手续费
funding 正 且 E≥门槛 → would_open;记 basis_shadow_log + 发 dcm:engine:basis:positions。
armed:BasisExecutor(armed.py)双门闸(DCM_BASIS_MODE=armed 且 ∈ARM_SYMBOLS);
执行器有 key 即常驻构造(reconcile 认领持仓防重启双开),下单按 mode 门控,持仓管理不分 mode。
"""
import asyncio
import json
import logging
import os
import socket
import sys
import time
from decimal import Decimal

import asyncpg
import httpx
import redis.asyncio as aioredis

from dcm_common.heartbeat import Heartbeat

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from armed import ARM_SYMBOLS, MODE, BasisExecutor  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("engine-basis")

REDIS_URL = os.environ.get("DCM_REDIS_URL", "redis://10.0.1.212:6379/0")
PG_DSN = os.environ.get("DCM_PG_DSN", "")
EVAL_SEC = int(os.environ.get("DCM_BASIS_EVAL_SEC", "10"))
HORIZON_DAYS = Decimal(os.environ.get("DCM_BASIS_HORIZON_DAYS", "5"))     # 底仓持有更久
FEE_BPS_PER_FILL = Decimal(os.environ.get("DCM_BASIS_FEE_BPS", "4"))       # 现货+合约 maker 化更低
MIN_E_BPS = Decimal(os.environ.get("DCM_BASIS_MIN_E_BPS", "5"))
MIN_FUNDING_DAILY = Decimal(os.environ.get("DCM_BASIS_MIN_FUNDING", "0.01"))
STALE_MS = int(os.environ.get("DCM_BASIS_STALE_MS", "10000"))
TOP_N = int(os.environ.get("DCM_BASIS_TOP_N", "30"))
LOG_EVERY_SEC = 60


async def l1(r, market, sym):
    raw = await r.hget(f"dcm:feed:binance:{market}", sym)
    return json.loads(raw) if raw else None


def evaluate(spot, perp, fund_daily: Decimal):
    """现货多+永续空:funding 正=永续空收。返回 (decision, detail)。"""
    now_ms = int(time.time() * 1000)
    for x in (spot, perp):
        if x is None or now_ms - int(x.get("recv_ts") or 0) > STALE_MS:
            return "skip_stale", {}
    spot_ask = Decimal(str(spot["ask"])); spot_bid = Decimal(str(spot["bid"]))
    perp_bid = Decimal(str(perp["bid"])); perp_ask = Decimal(str(perp["ask"]))
    if spot_ask <= 0:
        return "skip_stale", {}
    # 入场:买现货@ask 卖永续@bid;出场:卖现货@bid 买永续@ask
    entry_gap = (perp_bid - spot_ask) / spot_ask * Decimal("10000")
    exit_gap = (spot_bid - perp_ask) / spot_ask * Decimal("10000")
    funding_bps = fund_daily * HORIZON_DAYS * Decimal("100")
    fees_bps = FEE_BPS_PER_FILL * Decimal("4")
    e_bps = funding_bps + entry_gap + exit_gap - fees_bps
    detail = {"e_bps": str(round(e_bps, 2)), "funding_daily": str(round(fund_daily, 5)),
              "entry_gap": str(round(entry_gap, 2)), "exit_gap": str(round(exit_gap, 2)),
              "funding_bps": str(round(funding_bps, 1))}
    if fund_daily >= MIN_FUNDING_DAILY and e_bps >= MIN_E_BPS:
        return "would_open", detail
    return "idle", detail


async def main():
    r = aioredis.from_url(REDIS_URL, decode_responses=True)
    pool = await asyncpg.create_pool(PG_DSN, min_size=1, max_size=2)
    hb = Heartbeat(REDIS_URL, "engine-basis", interval_sec=30, ttl_sec=120)
    asyncio.create_task(hb.run_forever())
    # 执行器:有 key 即常驻构造(reconcile 认领),下单按 MODE+ARM_SYMBOLS 双门闸
    key, secret = os.environ.get("BINANCE_KEY", ""), os.environ.get("BINANCE_SECRET", "")
    executor = None
    cli = httpx.AsyncClient(timeout=20)  # 共享 client(反复新建会阻塞事件循环,testgo 学费)
    if key and secret:
        executor = BasisExecutor(r, pool, {"key": key, "secret": secret})
        await executor.reconcile_startup(cli)
    log.info("engine-basis up mode=%s arm=%s pid=%s host=%s min_E=%sbps horizon=%sd",
             MODE, sorted(ARM_SYMBOLS), os.getpid(), socket.gethostname(), MIN_E_BPS, HORIZON_DAYS)
    last_log: dict[str, tuple[str, float]] = {}
    while True:
        try:
            fmap = await r.hgetall("dcm:feed:funding:binance")
            cand = []
            for sym, js in fmap.items():
                try:
                    fd = Decimal(str(json.loads(js)["daily_pct"]))
                except Exception:
                    continue
                if fd >= MIN_FUNDING_DAILY:
                    cand.append((sym, fd))
            cand.sort(key=lambda x: -x[1])
            shadow = {}
            # 评估集 = top 候选 ∪ 在场持仓(持仓管理不能因跌出榜而失明)
            eval_syms = {s for s, _ in cand[:TOP_N]}
            if executor:
                eval_syms |= executor.open_syms
            fd_map = {s: fd for s, fd in cand}
            for sym in sorted(eval_syms):
                fd = fd_map.get(sym)
                if fd is None:
                    try:
                        fd = Decimal(str(json.loads(fmap.get(sym) or "{}").get("daily_pct", "0")))
                    except Exception:
                        fd = Decimal("0")
                sp = await l1(r, "spot", sym); pp = await l1(r, "perp", sym)
                decision, detail = evaluate(sp, pp, fd)
                if executor and sp and pp:
                    if decision == "would_open" and executor.armed_for(sym) \
                            and sym not in executor.open_syms:
                        await executor.open_pair(cli, sym, sp, pp, detail["e_bps"], fd)
                    await executor.manage(cli, sym, sp, pp, fd)
                if not detail:
                    continue
                shadow[sym] = {"decision": decision, **detail}
                prev = last_log.get(sym)
                if prev is None or prev[0] != decision or time.time() - prev[1] >= LOG_EVERY_SEC:
                    await pool.execute(
                        "INSERT INTO basis_shadow_log(symbol,funding_daily,e_bps,decision,detail) "
                        "VALUES($1,$2,$3,$4,$5)",
                        sym, fd, Decimal(detail["e_bps"]), decision, json.dumps(detail))
                    last_log[sym] = (decision, time.time())
            pos_rows = await pool.fetch(
                "SELECT symbol,qty_base,notional_usdt,state,open_e_bps,funding_daily,"
                "EXTRACT(EPOCH FROM opened_at)::bigint AS opened_ts FROM basis_positions "
                "WHERE state NOT IN ('CLOSED','FAILED') ORDER BY id")
            await r.set("dcm:engine:basis:positions", json.dumps(
                {"ts": int(time.time()), "mode": MODE,
                 "positions": [dict(x) for x in pos_rows],
                 "candidates": len(cand), "shadow": shadow}, ensure_ascii=False, default=str), ex=180)
            hb.extra = {"mode": MODE, "candidates": len(cand),
                        "positions": len(pos_rows), "would_open":
                        sum(1 for v in shadow.values() if v["decision"] == "would_open")}
        except Exception:
            log.exception("basis eval crashed (continuing)")
        await asyncio.sleep(EVAL_SEC)


if __name__ == "__main__":
    asyncio.run(main())
