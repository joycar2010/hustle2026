"""carry-advisor v1(规则版):双合约期期的选对顾问,decision API 的第一个自动调用方。

逻辑=xv 榜口径:逐币扫五所资金费(已归一日化),最低日化所做多腿 × 最高日化所做空腿,
edge=max-min ≥ 门槛且两腿 L1 皆新鲜 → 候选;按 edge 降序取 top N 铺 shadow 路由。

纪律:
- 一切写入走 decision POST /routes(schema→钳位→乐观锁→审计→热发布),顾问自己不碰表不碰总线;
- 所有权:只创建/更新 updated_by=advisor:carry-v1 的路由;人工路由(smoke/manual)同币冲突时跳过并告日志;
- edge 塌缩(< EXIT 门槛)或腿死 → 置 state=off(shadow 无仓,off 即撤);
- 顾问可整体摘除:停服务=路由冻结=只持有不新增;
- 数据不新鲜不决策:funding ts>30min 或 L1 缺失的腿一律不入候选。
"""
import asyncio
import json
import logging
import os
import time

import httpx
import redis.asyncio as aioredis

from dcm_common import arb_contract

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("carry-advisor")

REDIS_URL = os.environ.get("DCM_REDIS_URL", "redis://10.0.1.212:6379/0")
DECISION_URL = os.environ.get("DCM_DECISION_URL", "http://127.0.0.1:8001")
INTERVAL = int(os.environ.get("DCM_ADV_INTERVAL_SEC", "600"))
MIN_EDGE = float(os.environ.get("DCM_ADV_MIN_EDGE_DAILY_PCT", "0.15"))
EXIT_EDGE = float(os.environ.get("DCM_ADV_EXIT_EDGE_DAILY_PCT", "0.05"))
MAX_ROUTES = int(os.environ.get("DCM_ADV_MAX_ROUTES", "10"))
TARGET_USDT = float(os.environ.get("DCM_ADV_TARGET_NOTIONAL", "200"))
FUNDING_FRESH_SEC = int(os.environ.get("DCM_ADV_FUNDING_FRESH_SEC", "1800"))
# 容量钳位:单腿 ±band 名义 × 安全占比 = 该腿可吃仓;配对取两腿较小;
# 低于最小交易额则该对太薄不铺(xv 命门:高费差长尾容量薄,榜面费差≠可容纳资金)。
DEPTH_SAFETY = float(os.environ.get("DCM_ADV_DEPTH_SAFETY", "0.1"))
MIN_TRADE_USDT = float(os.environ.get("DCM_ADV_MIN_TRADE_USDT", "15"))
DEPTH_FRESH_SEC = int(os.environ.get("DCM_ADV_DEPTH_FRESH_SEC", "300"))
# hyperliquid=第六腿:入榜供 shadow 路由(dualperp 执行器 SUPPORTED 不含 HL,armed 自动拒=安全);
# HL 交易腿(独立签名进程)另期,armed 前勿加入 SUPPORTED
VENUES = ["binance", "okx", "bybit", "gate", "bitget", "hyperliquid"]
ACTOR = "advisor:carry-v1"
# 跨引擎同币仲裁出价(契约权威=dcm_common/arb_contract.py,此处内联保持单文件部署):
# 统一口径 e_daily_pct=%/天;carry 出价=edge−扁平成本(20bps往返/5天摊销)
ARB_KEY_CARRY = "dcm:arb:carry_e"
ARB_STALE_SEC = 900
ARB_FLAT_COST_DAILY_PCT = float(os.environ.get("DCM_ARB_FLAT_COST_DAILY_PCT", "0.04"))
# 退出滞回:有在场真金仓位的路由,连 N 轮不达标才 off(armed 下每次 off=真金往返成本;
# PARTI 40min 开了又关的学费)。无仓路由照旧即时 off(shadow 翻路由零成本)。
EXIT_STRIKES_N = int(os.environ.get("DCM_ADV_EXIT_STRIKES", "3"))
STRIKES_KEY = "dcm:adv:exit_strikes"
# 实收降权(P1,2026-07-13):pnl-recorder 逐仓归因(dualperp_carry_recon)发现某币
# 连续 N 仓实收 net(资金费+盈亏+费)<0 → 冷却期内该币不入候选(有仓在场的不动,只拦新开)。
# 榜面 edge 是预期,实收才是真相——连败=该币执行摩擦/资金费兑现系统性劣于预期。
NEG_STRIKES_KEY = "dcm:carry:neg_strikes"
REALIZED_NEG_N = int(os.environ.get("DCM_ADV_REALIZED_NEG_STRIKES", "2"))
REALIZED_COOLDOWN_H = float(os.environ.get("DCM_ADV_REALIZED_COOLDOWN_H", "24"))


async def load_funding(r: aioredis.Redis) -> dict[str, dict[str, dict]]:
    """symbol -> venue -> funding条目(仅保留新鲜的)。"""
    now = time.time()
    out: dict[str, dict[str, dict]] = {}
    for v in VENUES:
        try:
            raw = await r.hgetall(f"dcm:feed:funding:{v}")
        except Exception as e:
            log.warning(f"funding hash read failed {v}: {e!r}")
            continue
        for sym, js in raw.items():
            try:
                d = json.loads(js)
            except json.JSONDecodeError:
                continue
            if now - float(d.get("ts") or 0) > FUNDING_FRESH_SEC:
                continue
            out.setdefault(sym, {})[v] = d
    return out


async def leg_fresh(r: aioredis.Redis, venue: str, symbol: str) -> bool:
    """两腿 L1 必须存在且 10s 内新鲜(与引擎 stale 口径一致)。"""
    try:
        raw = await r.hget(f"dcm:feed:{venue}:perp", symbol)
        if not raw:
            return False
        l1 = json.loads(raw)
        return time.time() * 1000 - float(l1.get("recv_ts") or 0) <= 10_000
    except Exception:
        return False


async def capacity_cap(r: aioredis.Redis, vl: str, vs: str, symbol: str) -> float | None:
    """配对可容纳名义(USDT):开仓时多腿吃 ask 侧、空腿吃 bid 侧,取两腿较小 × 安全占比。
    深度缺失/陈旧 → None(不钳=不铺,armed 前深度未知的对不给真金入场额度)。"""
    now = time.time()
    caps = []
    for venue, side in ((vl, "ask_usdt"), (vs, "bid_usdt")):
        try:
            raw = await r.get(f"dcm:depth:{venue}:perp:{symbol}")
        except Exception:
            return None
        if not raw:
            return None
        d = json.loads(raw)
        if now - float(d.get("ts") or 0) > DEPTH_FRESH_SEC:
            return None
        caps.append(float(d.get(side) or 0))
    return min(caps) * DEPTH_SAFETY


def best_pair(per_venue: dict[str, dict]) -> tuple[str, str, float] | None:
    """返回 (venue_long=最低日化, venue_short=最高日化, edge)。"""
    if len(per_venue) < 2:
        return None
    lo = min(per_venue.items(), key=lambda kv: kv[1]["daily_pct"])
    hi = max(per_venue.items(), key=lambda kv: kv[1]["daily_pct"])
    if lo[0] == hi[0]:
        return None
    return lo[0], hi[0], float(hi[1]["daily_pct"]) - float(lo[1]["daily_pct"])


async def _open_position_syms(r: aioredis.Redis) -> set[str]:
    """引擎快照里 state=OPEN 的真金持仓币集合(快照缺失/超龄按空集,宁可即时 off 也不凭旧账滞留)。"""
    try:
        raw = await r.get("dcm:engine:dualperp:positions")
        if not raw:
            return set()
        d = json.loads(raw)
        if time.time() - d.get("ts", 0) > 300:
            return set()
        return {p.get("symbol") for p in (d.get("positions") or []) if p.get("symbol")}
    except Exception:
        return set()


async def _exit_allowed(r: aioredis.Redis, sym: str, open_syms: set[str], reason: str) -> bool:
    """滞回裁决:无仓即放行;有仓则累计 strike,满 EXIT_STRIKES_N 轮才放行 off。"""
    if sym not in open_syms:
        await r.hdel(STRIKES_KEY, sym)
        return True
    strikes = await r.hincrby(STRIKES_KEY, sym, 1)
    if strikes < EXIT_STRIKES_N:
        log.info(f"route- {sym} 滞回持有 ({reason}; strike {strikes}/{EXIT_STRIKES_N})")
        return False
    await r.hdel(STRIKES_KEY, sym)
    return True


async def _coin_held_symbols(r: aioredis.Redis) -> set[str]:
    """coin 引擎在场(非终态)币的统一符号——跨引擎路由互斥:dualperp 不碰 coin 已持有的币。"""
    try:
        snap = json.loads(await r.get("dcm:engine:coin:positions") or "{}")
        return {p.get("symbol") for p in snap.get("positions", []) or [] if p.get("symbol")}
    except Exception:
        return set()


async def advisor_round(r: aioredis.Redis, cli: httpx.AsyncClient) -> dict:
    funding = await load_funding(r)
    coin_held = await _coin_held_symbols(r)  # 路由互斥:排除 coin 引擎在管的币(在管=现任,无条件让)
    open_pos = await _open_position_syms(r)  # 真金在场币:off 须过滞回
    # E 仲裁:coin 引擎的逐币出价(事件驱动,无出价=无意愿)。coin 出价按滞回规则
    # 胜出的币让给借币引擎——路由互斥从"先到先得"升级为"期望值裁决"。
    coin_bids = arb_contract.parse_bids(await r.hgetall(arb_contract.KEY_COIN_E))

    # 实收连败降权名单(pnl-recorder 维护;有真金仓在场的币不拦——只拦新开,存量按退出滞回走)
    neg_block: set[str] = set()
    try:
        now0 = time.time()
        for sym, raw in (await r.hgetall(NEG_STRIKES_KEY) or {}).items():
            try:
                d = json.loads(raw)
                import datetime as _dt
                last = _dt.datetime.fromisoformat(d.get("last_close")).timestamp()
                if (int(d.get("strikes", 0)) >= REALIZED_NEG_N
                        and now0 - last < REALIZED_COOLDOWN_H * 3600
                        and sym not in open_pos):
                    neg_block.add(sym)
            except Exception:  # noqa: BLE001
                continue
        if neg_block:
            log.info("REALIZED_NEG block=%s (连续%d仓实收<0,冷却%.0fh)",
                     sorted(neg_block), REALIZED_NEG_N, REALIZED_COOLDOWN_H)
    except Exception:  # noqa: BLE001
        pass  # 降权名单读失败不阻断铺路(fail-open:少一层过滤,不误杀)

    # 候选:edge 达标 + 两腿 L1 新鲜 + 非 coin 已持有(跨引擎互斥) + 非实收连败冷却
    candidates: list[dict] = []
    yielded: list[dict] = []
    for sym, per_venue in funding.items():
        if sym in coin_held or sym in neg_block:
            continue
        bp = best_pair(per_venue)
        if bp is None or bp[2] < MIN_EDGE:
            continue
        vl, vs, edge = bp
        if not (await leg_fresh(r, vl, sym) and await leg_fresh(r, vs, sym)):
            continue
        my_e = arb_contract.carry_daily_net_pct(edge, ARB_FLAT_COST_DAILY_PCT)
        cb = coin_bids.get(sym)
        if cb is not None and arb_contract.challenger_wins(cb["e_daily_pct"], my_e):
            yielded.append({"sym": sym, "coin_e": cb["e_daily_pct"], "carry_e": round(my_e, 5)})
            continue  # coin 期望值显著更高:让币,不入候选(coin 侧黑名单随路由消失自动解除)
        candidates.append({"symbol": sym, "venue_long": vl, "venue_short": vs,
                           "edge": round(edge, 5)})
    candidates.sort(key=lambda c: -c["edge"])
    top = candidates[:MAX_ROUTES]
    top_syms = {c["symbol"] for c in top}
    if top_syms:
        await r.hdel(STRIKES_KEY, *top_syms)  # 重新达标即清零(滞回=连续不达标才 off)

    # watchlist:让 depth-sampler 先采本轮候选两腿深度,本轮不足者下轮即可钳位铺路
    watch = []
    for c in top:
        watch.append([c["venue_long"], c["symbol"]])
        watch.append([c["venue_short"], c["symbol"]])
    await r.set("dcm:depth:watchlist", json.dumps(watch), ex=max(INTERVAL * 3, 1800))

    # 仲裁契约:发布 carry 出价(候选全量,不止 top——仲裁面要看到所有 carry 有意愿的币),
    # 并清理超龄字段。失败不影响铺路主流程。
    try:
        now = int(time.time())
        pipe = r.pipeline()
        for c in candidates:
            pipe.hset(ARB_KEY_CARRY, c["symbol"], json.dumps({
                "v": 1, "src": "carry", "sym": c["symbol"],
                "e_daily_pct": round(c["edge"] - ARB_FLAT_COST_DAILY_PCT, 5),
                "raw": {"edge_daily_pct": c["edge"],
                        "venues": f"{c['venue_long']}/{c['venue_short']}"},
                "ts": now}, ensure_ascii=False))
        await pipe.execute()
        existing = await r.hgetall(ARB_KEY_CARRY)
        drop = []
        for sym, s in existing.items():
            try:
                if now - json.loads(s).get("ts", 0) > ARB_STALE_SEC:
                    drop.append(sym)
            except Exception:
                drop.append(sym)
        if drop:
            await r.hdel(ARB_KEY_CARRY, *drop)
    except Exception:
        log.warning("arb carry bid publish failed", exc_info=True)

    # 现有路由(经 decision API 读,不直连表)
    routes = (await cli.get(f"{DECISION_URL}/routes")).json()["routes"]
    mine = {rt["symbol"]: rt for rt in routes if rt["updated_by"] == ACTOR}
    others = {rt["symbol"]: rt for rt in routes if rt["updated_by"] != ACTOR}

    created = updated = closed = skipped = 0
    # 上新/换腿
    for c in top:
        sym = c["symbol"]
        if sym in others and others[sym].get("state") in ("proposed", "active"):
            skipped += 1  # 人工/他引擎路由在场,顾问不抢(路由互斥礼让)
            continue
        # 容量钳位:target = min(配置目标, 两腿深度较小 × 安全占比);太薄则不铺(下方 off)
        cap = await capacity_cap(r, c["venue_long"], c["venue_short"], sym)
        target = min(TARGET_USDT, cap) if cap is not None else 0.0
        c["cap"] = None if cap is None else round(cap, 1)
        c["target"] = round(target, 1)
        if target < MIN_TRADE_USDT:
            # 深度不足/未知:若我名下已有该对则撤(有真金仓须过滞回),否则跳过不铺
            if sym in mine and mine[sym]["state"] == "active" \
                    and await _exit_allowed(r, sym, open_pos, "容量不足"):
                cur = mine[sym]
                await cli.post(f"{DECISION_URL}/routes", json={
                    "symbol": sym, "engine": "dualperp",
                    "venue_long": cur["venue_long"], "market_long": "perp",
                    "venue_short": cur["venue_short"], "market_short": "perp",
                    "target_notional_usdt": "0", "state": "off",
                    "reason": f"carry-v1 容量不足 cap={c['cap']}", "actor": ACTOR,
                    "version": cur["version"]})
            skipped += 1
            continue
        cur = mine.get(sym)
        body = {"symbol": sym, "engine": "dualperp",
                "venue_long": c["venue_long"], "market_long": "perp",
                "venue_short": c["venue_short"], "market_short": "perp",
                "target_notional_usdt": str(target), "state": "active",
                "reason": f"carry-v1 edge={c['edge']}%/d cap={c['cap']}", "actor": ACTOR}
        if cur is None:
            resp = await cli.post(f"{DECISION_URL}/routes", json=body)
            if resp.status_code == 200:
                created += 1
                log.info(f"route+ {sym} {c['venue_long']}->long {c['venue_short']}->short edge={c['edge']}%/d")
            else:
                log.warning(f"route create {sym} failed {resp.status_code}: {resp.text[:150]}")
        elif (cur["venue_long"] != c["venue_long"] or cur["venue_short"] != c["venue_short"]
              or cur["state"] != "active"
              # 容量跟随:书变薄/变厚使 target 实质变化也更新(armed 下书缩必须实时缩仓)
              or abs(float(cur["target_notional_usdt"]) - target) > max(1.0, target * 0.05)):
            body["version"] = cur["version"]
            resp = await cli.post(f"{DECISION_URL}/routes", json=body)
            if resp.status_code == 200:
                updated += 1
                log.info(f"route~ {sym} -> {c['venue_long']}/{c['venue_short']} edge={c['edge']}%/d")
            else:
                log.warning(f"route update {sym} failed {resp.status_code}: {resp.text[:150]}")

    # 退出:我名下 active 但已不在 top(edge 塌缩/腿死/被挤出);有真金仓须连 N 轮不达标
    for sym, cur in mine.items():
        if cur["state"] != "active" or sym in top_syms:
            continue
        if not await _exit_allowed(r, sym, open_pos, "edge塌缩/挤出"):
            continue
        body = {"symbol": sym, "engine": "dualperp",
                "venue_long": cur["venue_long"], "market_long": "perp",
                "venue_short": cur["venue_short"], "market_short": "perp",
                "target_notional_usdt": "0", "state": "off",
                "reason": "carry-v1 edge塌缩/腿死,撤出", "actor": ACTOR,
                "version": cur["version"]}
        resp = await cli.post(f"{DECISION_URL}/routes", json=body)
        if resp.status_code == 200:
            closed += 1
            log.info(f"route- {sym} (不再达标)")
        else:
            log.warning(f"route off {sym} failed {resp.status_code}: {resp.text[:150]}")

    # 仲裁观测面:本轮裁决快照(胜负与双方出价),15min 过期
    try:
        await r.set("dcm:arb:verdicts", json.dumps(
            {"ts": int(time.time()), "yielded_to_coin": yielded}, ensure_ascii=False), ex=900)
    except Exception:
        pass
    if yielded:
        log.info(f"arb 让币 {len(yielded)}: " + ", ".join(
            f"{y['sym']}(coin {y['coin_e']} vs carry {y['carry_e']})" for y in yielded[:5]))

    return {"scanned": len(funding), "candidates": len(candidates),
            "created": created, "updated": updated, "closed": closed, "skipped": skipped,
            "arb_yielded": len(yielded),
            "top": [(c["symbol"], c["edge"]) for c in top[:5]]}


async def main():
    r = aioredis.from_url(REDIS_URL, decode_responses=True)
    log.info(f"carry-advisor up interval={INTERVAL}s min_edge={MIN_EDGE}%/d "
             f"exit={EXIT_EDGE}%/d max_routes={MAX_ROUTES} target={TARGET_USDT}U actor={ACTOR}")
    async with httpx.AsyncClient(timeout=15) as cli:
        while True:
            try:
                stats = await advisor_round(r, cli)
                await r.set("dcm:hb:carry-advisor", json.dumps(
                    {"service": "carry-advisor", "ts": int(time.time()),
                     "pid": os.getpid(), **stats}, ensure_ascii=False),
                    ex=max(INTERVAL * 3, 1800))
                log.info(f"ADVISOR_OK {stats}")
            except Exception:
                log.exception("advisor round crashed (continuing)")
            await asyncio.sleep(INTERVAL)


if __name__ == "__main__":
    asyncio.run(main())
