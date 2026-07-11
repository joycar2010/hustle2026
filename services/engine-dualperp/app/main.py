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
from dcm_common.notify import Notifier, feishu_from_env

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
# 净期望 E 闸:E = 持有期费差收益 + 往返价差损益 − 双边手续费 − 冲击成本(全部 bps of notional)
HORIZON_DAYS = Decimal(os.environ.get("DCM_DP_HORIZON_DAYS", "3"))       # 预期持有天数(费差摊销窗)
FEE_BPS_PER_FILL = Decimal(os.environ.get("DCM_DP_FEE_BPS_PER_FILL", "5"))  # 单笔 taker 费(bps)
MIN_E_BPS = Decimal(os.environ.get("DCM_DP_MIN_E_BPS", "3"))             # E≥此才开(enforce)
E_GATE_ENFORCE = os.environ.get("DCM_DP_E_GATE_ENFORCE", "true").lower() == "true"  # false=只shadow记E不拦


class RouteBook:
    """路由本地镜像:**DB 权威现读**起步 + 订阅增量 + 60s 全量轮询兜底。
    两课编码于此:①resume 绝不回放 Redis 旧快照(dcm_main 重建日 Redis 残留 71
    幽灵路由,DB 才 8 行——testgo「恢复回放旧快照」同课);②纯 pubsub 会被网络
    黑洞静默吞掉(testgo userstream 握手 OK 零帧课),轮询兜底保证最迟 60s 收敛。"""

    def __init__(self, r: aioredis.Redis, pool=None):
        self.r = r
        self.pool = pool
        self.routes: dict[str, dict] = {}

    async def load_all(self):
        rows = None
        if self.pool is not None:
            try:
                recs = await self.pool.fetch(
                    "SELECT symbol,engine,venue_long,market_long,venue_short,market_short,"
                    "target_notional_usdt,state,updated_by FROM route_assignments")
                rows = {rec["symbol"]: {k: (str(v) if k == "target_notional_usdt" else v)
                                        for k, v in dict(rec).items()} for rec in recs}
            except Exception as e:
                log.warning(f"route load from DB failed, fallback redis: {e!r}")
        if rows is None:  # DB 不可用才退 Redis 快照(仍好过空书)
            raw = await self.r.hgetall("dcm:route:assignments")
            rows = {}
            for sym, js in raw.items():
                try:
                    rows[sym] = json.loads(js)
                except json.JSONDecodeError:
                    log.warning(f"bad route json for {sym}")
        self.routes = rows
        log.info(f"route book loaded: {len(self.routes)} rows "
                 f"(source={'db' if self.pool is not None else 'redis'})")

    async def refresh_loop(self, interval: int = 60):
        """轮询兑底:pubsub 半开假死时最迟 interval 秒收敛到 DB 真相。"""
        while True:
            await asyncio.sleep(interval)
            try:
                await self.load_all()
            except Exception as e:
                log.warning(f"route refresh failed: {e!r}")

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


async def _depth_side(r: aioredis.Redis, venue: str, symbol: str, side_key: str) -> float:
    """读 depth-sampler 的 ±band 名义(冲击成本估算用);缺失返 0(evaluate 按未知深度保守)。"""
    try:
        raw = await r.get(f"dcm:depth:{venue}:perp:{symbol}")
        return float(json.loads(raw).get(side_key) or 0) if raw else 0.0
    except Exception:
        return 0.0


def _impact_bps(target: Decimal, depth_usdt: float) -> Decimal:
    """冲击成本估算:从 ±25bps 深度 depth_usdt 吃掉 target,线性书近似 ≈ (target/depth)×band。
    深度未知(0)→给保守高惩罚(不确定即当贵),迫使 E 闸对薄/未知深度币谨慎。"""
    band = Decimal("25")
    if depth_usdt <= 0:
        return band  # 深度未知=一个 band 的保守惩罚
    return min(target / Decimal(str(depth_usdt)) * band, band * 4)  # 封顶防极端


def evaluate(route: dict, long_l1: dict | None, short_l1: dict | None,
             long_fund: dict | None, short_fund: dict | None,
             depth_usdt: float, has_open_position: bool) -> tuple[str, dict]:
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
    long_bid = Decimal(str(long_l1["bid"]))
    short_bid = Decimal(str(short_l1["bid"]))
    short_ask = Decimal(str(short_l1["ask"]))
    if long_ask <= 0 or short_ask <= 0:
        return "skip_stale", detail
    # 入场即刻价差(买多腿ask/卖空腿bid);出场反向价差(卖多腿bid/买空腿ask)
    entry_gap_bps = (short_bid - long_ask) / long_ask * Decimal("10000")
    exit_gap_bps = (long_bid - short_ask) / long_ask * Decimal("10000")
    gap_bps = entry_gap_bps  # 兼容既有字段
    detail["gap_bps"] = str(round(gap_bps, 4))
    detail["exit_gap_bps"] = str(round(exit_gap_bps, 4))
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

    # 净期望 E(bps of notional):费差收益(持有期) + 往返价差损益 − 双边手续费 − 冲击成本
    e_bps = None
    if edge is not None:
        funding_income_bps = edge * HORIZON_DAYS * Decimal("100")   # 日化% × 天数 × 100 = bps
        roundtrip_spread_bps = entry_gap_bps + exit_gap_bps          # 两段价差损益(通常为负=成本)
        fees_bps = FEE_BPS_PER_FILL * Decimal("4")                   # 开2腿+平2腿=4笔 taker
        impact_bps = _impact_bps(Decimal(str(route.get("target_notional_usdt") or "0")), depth_usdt)
        e_bps = funding_income_bps + roundtrip_spread_bps - fees_bps - impact_bps
        detail["e_bps"] = str(round(e_bps, 3))
        detail["e_parts"] = {"funding": str(round(funding_income_bps, 2)),
                             "spread": str(round(roundtrip_spread_bps, 2)),
                             "fees": str(round(fees_bps, 2)), "impact": str(round(impact_bps, 2))}

    target = Decimal(str(route.get("target_notional_usdt") or "0"))
    if has_open_position:
        # 平仓:费差体制消失 或 E 转负(持有已不划算)
        if target == 0 or (edge is not None and edge <= CLOSE_FUNDING_DAILY_PCT):
            return "would_close", detail
        return "would_hold", detail
    if edge is None or e_bps is None:
        return "idle", detail  # 费差/E 不明绝不开仓
    # E 闸:enforce 模式按 E≥门槛开;shadow 模式仅记 E,仍用旧费差+价差阈值(coin E闸 shadow/enforce)
    if E_GATE_ENFORCE:
        open_ok = target > 0 and e_bps >= MIN_E_BPS
    else:
        open_ok = target > 0 and edge >= MIN_FUNDING_DAILY_PCT and gap_bps >= -MAX_ENTRY_COST_BPS
    return ("would_open" if open_ok else "idle"), detail


async def main():
    from livecfg import CFG
    r = aioredis.from_url(REDIS_URL, decode_responses=True)
    pool = await asyncpg.create_pool(PG_DSN, min_size=1, max_size=3)
    await CFG.load(pool)                        # DB 配置优先(engine_config),env 兜底
    hb = Heartbeat(REDIS_URL, SERVICE, interval_sec=30, ttl_sec=120)
    book = RouteBook(r, pool=pool)
    await book.load_all()
    asyncio.create_task(book.watch())
    asyncio.create_task(book.refresh_loop())
    asyncio.create_task(hb.run_forever())
    asyncio.create_task(CFG.watch(r, pool))     # 订阅 dcm:config:updates 热重载(armed 可热切换)
    asyncio.create_task(CFG.poll(pool))         # 30s 轮询兜底(pubsub 黑洞时开关仍可达)

    # 执行器常驻构造(有 key 即建;shadow 只是不被调用)——mode 热切 armed 时立即可用,
    # reconcile_startup 保证任何时刻构造/切换都先认领实盘持仓(防双开)
    executor = None
    trade_cli = None
    cfg = {
        "binance": {"key": os.environ.get("BINANCE_KEY", ""), "secret": os.environ.get("BINANCE_SECRET", "")},
        "bybit": {"key": os.environ.get("BYBIT_KEY", ""), "secret": os.environ.get("BYBIT_SECRET", "")},
        "okx": {"key": os.environ.get("OKX_KEY", ""), "secret": os.environ.get("OKX_SECRET", ""),
                "passphrase": os.environ.get("OKX_PASSPHRASE", "")},
        "gate": {"key": os.environ.get("GATE_KEY", ""), "secret": os.environ.get("GATE_SECRET", "")},
        "bitget": {"key": os.environ.get("BITGET_KEY", ""), "secret": os.environ.get("BITGET_SECRET", ""),
                   "passphrase": os.environ.get("BITGET_PASSPHRASE", "")},
    }
    if any(c.get("key") for c in cfg.values()):
        from armed import ArmedExecutor
        notifier = Notifier(REDIS_URL, "engine-dualperp", feishu=feishu_from_env(),
                            throttle_interval_sec=300, throttle_max_count=2)
        trade_cli = httpx.AsyncClient(timeout=15)
        executor = ArmedExecutor(r, pool, notifier, cfg)
        await executor.reconcile_startup(trade_cli)

    log.info(f"engine-dualperp up mode={CFG.mode} arm={sorted(CFG.arm_symbols)} pid={os.getpid()} "
             f"host={socket.gethostname()} eval={EVAL_SEC}s (热配置:engine_config)")

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
                # 冲击成本用两腿吃单侧较薄深度(多腿吃ask/空腿吃bid)
                dl = await _depth_side(r, route["venue_long"], sym, "ask_usdt")
                ds = await _depth_side(r, route["venue_short"], sym, "bid_usdt")
                depth_usdt = min(dl, ds) if (dl > 0 and ds > 0) else max(dl, ds)
                has_pos = bool(executor and sym in executor.open_syms)
                decision, detail = evaluate(route, long_l1, short_l1,
                                            long_fund, short_fund, depth_usdt, has_open_position=has_pos)
                shadow_status[sym] = {"decision": decision, **detail}

                # armed 开仓:mode=armed 且白名单币且不在途(新开仓受 mode 门控)
                if executor and CFG.mode == "armed" and executor.armed_for(sym) and sym not in executor.inflight:
                    target = Decimal(str(route.get("target_notional_usdt") or "0"))
                    if decision == "would_open" and not has_pos:
                        asyncio.create_task(executor.open_pair(trade_cli, route, target, long_l1, short_l1))
                    elif decision == "would_close" and has_pos:
                        asyncio.create_task(executor.close_pair(trade_cli, sym))

                # shadow 落库(决策变化或60s)——必须在 for route 循环内,每个活跃路由都记,
                # 且与 armed 无关(shadow 模式 executor=None 也要记战绩)
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
                    log.info(f"shadow[{sym}] {decision} {detail.get('gap_bps', '-')}bps E={detail.get('e_bps','-')}")

            # 平仓触发(路由消失/off/draining)+ 持仓管理(基差止损/收敛):独立于 for route 扫持仓集,
            # 否则置 off 的仓位会被孤立(引擎不再管、实盘仍开着)——close/manage 不能只挂在 active 路由上
            # 持仓管理无论 mode:只要实盘有仓就管(基差止损/收敛/路由off平仓),即便切回 shadow
            if executor:
                for sym in list(executor.open_syms):
                    if sym in executor.inflight:
                        continue
                    rt = book.routes.get(sym)
                    if rt is None or rt.get("state") in ("off", "draining"):
                        log.info("close trigger: %s route %s -> close_pair", sym,
                                 "missing" if rt is None else rt.get("state"))
                        asyncio.create_task(executor.close_pair(trade_cli, sym))
                    else:
                        asyncio.create_task(executor.manage_open(trade_cli, sym))

            # 快照契约(risk-ledger/gateway 消费)
            open_positions = []
            if executor and executor.open_syms:
                rows = await pool.fetch(
                    "SELECT symbol,venue_long,venue_short,qty_base,notional_usdt,long_order_id,"
                    "short_order_id,opened_at FROM dualperp_positions WHERE state='OPEN'")
                open_positions = [dict(r) for r in rows]
            await r.set("dcm:engine:dualperp:positions", json.dumps({
                "ts": int(time.time()), "mode": CFG.mode,
                "armed_symbols": sorted(executor.open_syms) if executor else [],
                "active_routes": len(shadow_status), "positions": open_positions,
                "shadow": shadow_status,
            }, ensure_ascii=False, default=str), ex=180)
            hb.extra = {"mode": CFG.mode, "active_routes": len(shadow_status),
                        "open_positions": len(open_positions)}
        except Exception:
            log.exception("eval round crashed (continuing)")
        await asyncio.sleep(EVAL_SEC)


if __name__ == "__main__":
    asyncio.run(main())
