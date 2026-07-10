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

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("carry-advisor")

REDIS_URL = os.environ.get("DCM_REDIS_URL", "redis://10.0.1.212:6379/0")
DECISION_URL = os.environ.get("DCM_DECISION_URL", "http://127.0.0.1:8001")
INTERVAL = int(os.environ.get("DCM_ADV_INTERVAL_SEC", "600"))
MIN_EDGE = float(os.environ.get("DCM_ADV_MIN_EDGE_DAILY_PCT", "0.15"))
EXIT_EDGE = float(os.environ.get("DCM_ADV_EXIT_EDGE_DAILY_PCT", "0.05"))
MAX_ROUTES = int(os.environ.get("DCM_ADV_MAX_ROUTES", "10"))
TARGET_USDT = os.environ.get("DCM_ADV_TARGET_NOTIONAL", "200")
FUNDING_FRESH_SEC = int(os.environ.get("DCM_ADV_FUNDING_FRESH_SEC", "1800"))
VENUES = ["binance", "okx", "bybit", "gate", "bitget"]
ACTOR = "advisor:carry-v1"


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


def best_pair(per_venue: dict[str, dict]) -> tuple[str, str, float] | None:
    """返回 (venue_long=最低日化, venue_short=最高日化, edge)。"""
    if len(per_venue) < 2:
        return None
    lo = min(per_venue.items(), key=lambda kv: kv[1]["daily_pct"])
    hi = max(per_venue.items(), key=lambda kv: kv[1]["daily_pct"])
    if lo[0] == hi[0]:
        return None
    return lo[0], hi[0], float(hi[1]["daily_pct"]) - float(lo[1]["daily_pct"])


async def advisor_round(r: aioredis.Redis, cli: httpx.AsyncClient) -> dict:
    funding = await load_funding(r)

    # 候选:edge 达标 + 两腿 L1 新鲜
    candidates: list[dict] = []
    for sym, per_venue in funding.items():
        bp = best_pair(per_venue)
        if bp is None or bp[2] < MIN_EDGE:
            continue
        vl, vs, edge = bp
        if not (await leg_fresh(r, vl, sym) and await leg_fresh(r, vs, sym)):
            continue
        candidates.append({"symbol": sym, "venue_long": vl, "venue_short": vs,
                           "edge": round(edge, 5)})
    candidates.sort(key=lambda c: -c["edge"])
    top = candidates[:MAX_ROUTES]
    top_syms = {c["symbol"] for c in top}

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
        cur = mine.get(sym)
        body = {"symbol": sym, "engine": "dualperp",
                "venue_long": c["venue_long"], "market_long": "perp",
                "venue_short": c["venue_short"], "market_short": "perp",
                "target_notional_usdt": TARGET_USDT, "state": "active",
                "reason": f"carry-v1 edge={c['edge']}%/d", "actor": ACTOR}
        if cur is None:
            resp = await cli.post(f"{DECISION_URL}/routes", json=body)
            if resp.status_code == 200:
                created += 1
                log.info(f"route+ {sym} {c['venue_long']}->long {c['venue_short']}->short edge={c['edge']}%/d")
            else:
                log.warning(f"route create {sym} failed {resp.status_code}: {resp.text[:150]}")
        elif (cur["venue_long"] != c["venue_long"] or cur["venue_short"] != c["venue_short"]
              or cur["state"] != "active"):
            body["version"] = cur["version"]
            resp = await cli.post(f"{DECISION_URL}/routes", json=body)
            if resp.status_code == 200:
                updated += 1
                log.info(f"route~ {sym} -> {c['venue_long']}/{c['venue_short']} edge={c['edge']}%/d")
            else:
                log.warning(f"route update {sym} failed {resp.status_code}: {resp.text[:150]}")

    # 退出:我名下 active 但已不在 top(edge 塌缩/腿死/被挤出)
    for sym, cur in mine.items():
        if cur["state"] != "active" or sym in top_syms:
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

    return {"scanned": len(funding), "candidates": len(candidates),
            "created": created, "updated": updated, "closed": closed, "skipped": skipped,
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
