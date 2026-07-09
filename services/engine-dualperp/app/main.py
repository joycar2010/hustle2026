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
import redis.asyncio as aioredis

from dcm_common.heartbeat import Heartbeat

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("engine-dualperp")

SERVICE = "engine-dualperp"
REDIS_URL = os.environ.get("DCM_REDIS_URL", "redis://10.0.1.212:6379/0")
PG_DSN = os.environ.get("DCM_PG_DSN", "")
MODE = os.environ.get("DCM_DP_MODE", "shadow")            # shadow | armed(key 到位前禁用)
EVAL_SEC = int(os.environ.get("DCM_DP_EVAL_SEC", "5"))
ENTRY_BPS = Decimal(os.environ.get("DCM_DP_ENTRY_BPS", "5"))
EXIT_BPS = Decimal(os.environ.get("DCM_DP_EXIT_BPS", "0"))
STALE_MS = int(os.environ.get("DCM_DP_STALE_MS", "10000"))
SHADOW_LOG_EVERY_SEC = int(os.environ.get("DCM_DP_SHADOW_LOG_SEC", "60"))


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


def evaluate(route: dict, long_l1: dict | None, short_l1: dict | None,
             has_open_position: bool) -> tuple[str, dict]:
    """shadow/armed 共用的决策核:返回 (decision, detail)。
    价差口径:gap = (空腿bid - 多腿ask) / 多腿ask,正值=开仓即刻价差收益(bps)。"""
    now_ms = int(time.time() * 1000)
    detail: dict = {"funding_missing": True}  # TODO: 接资金费差后并入净期望
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
    target = Decimal(str(route.get("target_notional_usdt") or "0"))
    if has_open_position:
        if gap_bps <= EXIT_BPS or target == 0:
            return "would_close", detail
        return "would_hold", detail
    if target > 0 and gap_bps >= ENTRY_BPS:
        return "would_open", detail
    return "idle", detail


async def main():
    assert MODE == "shadow", "armed 模式未启用:API key 配置+canary 验收前禁止"
    r = aioredis.from_url(REDIS_URL, decode_responses=True)
    pool = await asyncpg.create_pool(PG_DSN, min_size=1, max_size=3)
    hb = Heartbeat(REDIS_URL, SERVICE, interval_sec=30, ttl_sec=120)
    book = RouteBook(r)
    await book.load_all()
    asyncio.create_task(book.watch())
    asyncio.create_task(hb.run_forever())
    log.info(f"engine-dualperp up mode={MODE} pid={os.getpid()} host={socket.gethostname()} "
             f"entry={ENTRY_BPS}bps exit={EXIT_BPS}bps eval={EVAL_SEC}s")

    last_logged: dict[str, tuple[str, float]] = {}  # symbol -> (decision, ts) 决策变化或60s才落库
    while True:
        try:
            shadow_status: dict[str, dict] = {}
            for route in book.active_dualperp():
                sym = route["symbol"]
                long_l1 = await leg_l1(r, route["venue_long"], route["market_long"], sym)
                short_l1 = await leg_l1(r, route["venue_short"], route["market_short"], sym)
                decision, detail = evaluate(route, long_l1, short_l1, has_open_position=False)
                shadow_status[sym] = {"decision": decision, **detail}

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

            # 快照契约(risk-ledger/gateway 消费):shadow 期 positions 恒空,armed 后填真仓
            await r.set("dcm:engine:dualperp:positions", json.dumps({
                "ts": int(time.time()), "mode": MODE, "armed": False,
                "active_routes": len(shadow_status), "positions": [],
                "shadow": shadow_status,
            }, ensure_ascii=False), ex=180)
            hb.extra = {"mode": MODE, "active_routes": len(shadow_status)}
        except Exception:
            log.exception("eval round crashed (continuing)")
        await asyncio.sleep(EVAL_SEC)


if __name__ == "__main__":
    asyncio.run(main())
