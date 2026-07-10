"""engine-dualperp v1(shadow):双合约期期配对引擎,B 机执行面首个服务。

v1 = shadow 模式:消费路由权威表(只认 engine=dualperp 且 state=active),
按 feed 实时 L1 计算跨所价差,记录 would_open/would_hold/would_close 决策
到 dualperp_shadow_log——真金 canary 前的战绩账从这里积累(xv-shadow 捕获率闸门口径)。
armed 模式(真下单)在 API key 配置后点亮:state.py 状态机 + venues.py 客户端已就位,
本文件的评估器就是将来 armed 的信号源,shadow/armed 共用同一套决策逻辑。

消费端新鲜度纪律:feed 只发原始双时间戳,stale 判定在这里做(任一腿 recv_ts 超龄=skip_stale,
绝不用 stale 腿算价差——coin 假基差的教训在消费端落地)。

路由感知:启动 HGETALL dcm:route:assignments + 订阅 dcm:route:updates 增量,0 秒热感知。
资金费差:TODO 接 funding 数据源(xv/dd 口径),v1 只有价差腿,detail 里如实标注 funding_missing。
"""
import asyncio
import json
import logging
import os
import socket
import time
from decimal import Decimal

import asyncpg
import httpx
import redis.asyncio as aioredis

from dcm_common.heartbeat import Heartbeat
from dcm_common.notify import FeishuTarget, Notifier

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("engine-dualperp")

SERVICE = "engine-dualperp"
REDIS_URL = os.environ.get("DCM_REDIS_URL", "redis://10.0.1.212:6379/0")
PG_DSN = os.environ.get("DCM_PG_DSN", "")
MODE = os.environ.get("DCM_DP_MODE", "shadow")            # shadow | armed(key 到位前禁用)
EVAL_SEC = int(os.environ.get("DCM_DP_EVAL_SEC", "5"))
STALE_MS = int(os.environ.get("DCM_DP_STALE_MS", "10000"))
SHADOW_LOG_EVERY_SEC = int(os.environ.get("DCM_DP_SHADOW_LOG_SEC", "60"))
# 净期望口径:费差是收益主体,即刻价差是入场成本/红利。
# 开仓 = 费差日化 ≥ MIN_FUNDING 且 入场价差 ≥ -MAX_ENTRY_COST(允许小幅倒贴,由费差摊销);
# 平仓 = 费差日化 ≤ CLOSE_FUNDING(体制消失即撤,基差无锚收敛不保证)。
MIN_FUNDING_DAILY_PCT = Decimal(os.environ.get("DCM_DP_MIN_FUNDING_DAILY_PCT", "0.05"))
CLOSE_FUNDING_DAILY_PCT = Decimal(os.environ.get("DCM_DP_CLOSE_FUNDING_DAILY_PCT", "0"))
MAX_ENTRY_COST_BPS = Decimal(os.environ.get("DCM_DP_MAX_ENTRY_COST_BPS", "10"))
FUNDING_STALE_SEC = int(os.environ.get("DCM_DP_FUNDING_STALE_SEC", "1800"))


class RouteBook:
    """路由本地镜像:HGETALL 起步 + 订阅增量(coin rules:reload 同模式)。"""

    def __init__(self, r: aioredis.Redis):
        self.r = r
        self.routes: dict[str, dict] = {}

    async def load_all(self):
        raw = await self.r.hgetall("dcm:route:assignments")
        self.routes = {}
        for sym, js in raw.items():
            try:
                self.routes[sym] = json.loads(js)
            except json.JSONDecodeError:
                log.warning(f"bad route json for {sym}")
        log.info(f"route book loaded: {len(self.routes)} rows")

    async def watch(self):
        while True:
            try:
                ps = self.r.pubsub()
                await ps.subscribe("dcm:route:updates")
                async for msg in ps.listen():
                    if msg.get("type") != "message":
                        continue
                    sym = msg["data"]
                    js = await self.r.hget("dcm:route:assignments", sym)
                    if js is None:
                        self.routes.pop(sym, None)
                        log.info(f"route removed: {sym}")
                    else:
                        self.routes[sym] = json.loads(js)
                        rt = self.routes[sym]
                        log.info(f"route updated: {sym} engine={rt.get('engine')} "
                                 f"state={rt.get('state')} target={rt.get('target_notional_usdt')}")
            except Exception as e:
                log.warning(f"route watch reconnect: {e!r}")
                await asyncio.sleep(2)

    def active_dualperp(self) -> list[dict]:
        return [r for r in self.routes.values()
                if r.get("engine") == "dualperp" and r.get("state") == "active"]


async def leg_l1(r: aioredis.Redis, venue: str, market: str, symbol: str) -> dict | None:
    try:
        raw = await r.hget(f"dcm:feed:{venue}:{market}", symbol)
        return json.loads(raw) if raw else None
    except Exception as e:
        log.warning(f"leg read failed {venue}:{market}:{symbol}: {e!r}")
        return None


async def leg_funding(r: aioredis.Redis, venue: str, symbol: str) -> dict | None:
    try:
        raw = await r.hget(f"dcm:feed:funding:{venue}", symbol)
        return json.loads(raw) if raw else None
    except Exception as e:
        log.warning(f"funding read failed {venue}:{symbol}: {e!r}")
        return None


def evaluate(route: dict, long_l1: dict | None, short_l1: dict | None,
             long_fund: dict | None, short_fund: dict | None,
             has_open_position: bool) -> tuple[str, dict]:
    """shadow/armed 共用的决策核:返回 (decision, detail)。

    收益结构:多腿付/收 long 所资金费,空腿收/付 short 所资金费 →
      funding_edge_daily_pct = short_daily - long_daily(正=按日净收)。
    价差口径:gap_bps = (空腿bid - 多腿ask)/多腿ask,正=开仓即刻价差红利,负=入场成本。
    决策:费差 ≥ 门槛 且 入场成本可接受 → would_open;费差体制消失 → would_close。
    任一腿行情/资金费缺失或超龄 → 不决策(绝不用 stale 数据下判断)。"""
    now = time.time()
    now_ms = int(now * 1000)
    detail: dict = {}
    for name, l1 in (("long", long_l1), ("short", short_l1)):
        if l1 is None:
            detail[f"{name}_leg"] = "missing"
            return "skip_stale", detail
        age = now_ms - int(l1.get("recv_ts") or 0)
        if age > STALE_MS:
            detail[f"{name}_leg_stale_ms"] = age
            return "skip_stale", detail
    long_ask = Decimal(str(long_l1["ask"]))
    short_bid = Decimal(str(short_l1["bid"]))
    if long_ask <= 0:
        return "skip_stale", detail
    gap_bps = (short_bid - long_ask) / long_ask * Decimal("10000")
    detail["gap_bps"] = str(round(gap_bps, 4))
    detail["long_ask"] = str(long_ask)
    detail["short_bid"] = str(short_bid)

    # 资金费差(日化 %):缺失/超龄 → 不决策,如实标注
    edge = None
    for name, f in (("long", long_fund), ("short", short_fund)):
        if f is None:
            detail[f"funding_{name}"] = "missing"
        elif now - float(f.get("ts") or 0) > FUNDING_STALE_SEC:
            detail[f"funding_{name}"] = f"stale({int(now - float(f['ts']))}s)"
        else:
            detail[f"funding_{name}_daily_pct"] = round(float(f["daily_pct"]), 5)
    if ("funding_long_daily_pct" in detail) and ("funding_short_daily_pct" in detail):
        edge = Decimal(str(detail["funding_short_daily_pct"])) \
             - Decimal(str(detail["funding_long_daily_pct"]))
        detail["funding_edge_daily_pct"] = str(round(edge, 5))

    target = Decimal(str(route.get("target_notional_usdt") or "0"))
    if has_open_position:
        if target == 0 or (edge is not None and edge <= CLOSE_FUNDING_DAILY_PCT):
            return "would_close", detail
        return "would_hold", detail
    if edge is None:
        return "idle", detail  # 费差不明绝不开仓
    if target > 0 and edge >= MIN_FUNDING_DAILY_PCT and gap_bps >= -MAX_ENTRY_COST_BPS:
        return "would_open", detail
    return "idle", detail


async def main():
    assert MODE in ("shadow", "armed"), f"未知 MODE={MODE}"
    r = aioredis.from_url(REDIS_URL, decode_responses=True)
    pool = await asyncpg.create_pool(PG_DSN, min_size=1, max_size=3)
    hb = Heartbeat(REDIS_URL, SERVICE, interval_sec=30, ttl_sec=120)
    book = RouteBook(r)
    await book.load_all()
    asyncio.create_task(book.watch())
    asyncio.create_task(hb.run_forever())

    # armed 执行器:仅 MODE=armed 时构造;下单再受 per-symbol 白名单二次门闸
    executor = None
    trade_cli = None
    if MODE == "armed":
        from app.armed import ArmedExecutor, ARM_SYMBOLS
        cfg = {"binance": {"key": os.environ.get("BINANCE_KEY", ""), "secret": os.environ.get("BINANCE_SECRET", "")},
               "bybit": {"key": os.environ.get("BYBIT_KEY", ""), "secret": os.environ.get("BYBIT_SECRET", "")}}
        notifier = Notifier(REDIS_URL, "engine-dualperp",
                            feishu=FeishuTarget(webhook_url=os.environ.get("DCM_FEISHU_WEBHOOK", "")),
                            throttle_interval_sec=300, throttle_max_count=2)
        trade_cli = httpx.AsyncClient(timeout=15)
        executor = ArmedExecutor(r, pool, notifier, cfg)
        await executor.reconcile_startup(trade_cli)
        log.warning("ARMED MODE — arm_symbols=%s (空=仍不下单)", sorted(ARM_SYMBOLS))

    log.info(f"engine-dualperp up mode={MODE} pid={os.getpid()} host={socket.gethostname()} "
             f"min_funding={MIN_FUNDING_DAILY_PCT}%/d max_entry_cost={MAX_ENTRY_COST_BPS}bps eval={EVAL_SEC}s")

    last_logged: dict[str, tuple[str, float]] = {}  # symbol -> (decision, ts) 决策变化或60s才落库
    while True:
        try:
            shadow_status: dict[str, dict] = {}
            for route in book.active_dualperp():
                sym = route["symbol"]
                long_l1 = await leg_l1(r, route["venue_long"], route["market_long"], sym)
                short_l1 = await leg_l1(r, route["venue_short"], route["market_short"], sym)
                long_fund = await leg_funding(r, route["venue_long"], sym)
                short_fund = await leg_funding(r, route["venue_short"], sym)
                has_pos = bool(executor and sym in executor.open_syms)
                decision, detail = evaluate(route, long_l1, short_l1,
                                            long_fund, short_fund, has_open_position=has_pos)
                shadow_status[sym] = {"decision": decision, **detail}

                # armed 执行:仅白名单币且不在途;shadow 决策即执行信号,同一决策核
                if executor and executor.armed_for(sym) and sym not in executor.inflight:
                    target = Decimal(str(route.get("target_notional_usdt") or "0"))
                    if decision == "would_open" and not has_pos:
                        asyncio.create_task(executor.open_pair(trade_cli, route, target, long_l1, short_l1))
                    elif decision == "would_close" and has_pos:
                        asyncio.create_task(executor.close_pair(trade_cli, sym))

                prev = last_logged.get(sym)
                if prev is None or prev[0] != decision or time.time() - prev[1] >= SHADOW_LOG_EVERY_SEC:
                    await pool.execute(
                        "INSERT INTO dualperp_shadow_log"
                        "(symbol, venue_long, venue_short, gap_bps, long_ask, short_bid, decision, detail) "
                        "VALUES ($1,$2,$3,$4,$5,$6,$7,$8)",
                        sym, route["venue_long"], route["venue_short"],
                        Decimal(detail["gap_bps"]) if "gap_bps" in detail else None,
                        Decimal(detail["long_ask"]) if "long_ask" in detail else None,
                        Decimal(detail["short_bid"]) if "short_bid" in detail else None,
                        decision, json.dumps(detail, ensure_ascii=False))
                    last_logged[sym] = (decision, time.time())
                    log.info(f"shadow[{sym}] {decision} {detail.get('gap_bps', '-')}bps")

            # 快照契约(risk-ledger/gateway 消费)
            open_positions = []
            if executor and executor.open_syms:
                rows = await pool.fetch(
                    "SELECT symbol,venue_long,venue_short,qty_base,notional_usdt,long_order_id,"
                    "short_order_id,opened_at FROM dualperp_positions WHERE state='OPEN'")
                open_positions = [dict(r) for r in rows]
            await r.set("dcm:engine:dualperp:positions", json.dumps({
                "ts": int(time.time()), "mode": MODE,
                "armed_symbols": sorted(executor.open_syms) if executor else [],
                "active_routes": len(shadow_status), "positions": open_positions,
                "shadow": shadow_status,
            }, ensure_ascii=False, default=str), ex=180)
            hb.extra = {"mode": MODE, "active_routes": len(shadow_status),
                        "open_positions": len(open_positions)}
        except Exception:
            log.exception("eval round crashed (continuing)")
        await asyncio.sleep(EVAL_SEC)


if __name__ == "__main__":
    asyncio.run(main())
