"""universe-sync:五所交易宇宙生产化。

每小时拉各所 exchangeInfo(可交易状态)× 24h 成交额(tickers),按成交额地板过滤后
写 dcm:feed:universe:{venue}:{market}(venue 原生符号,排序保证 feed 侧比较稳定)。

纪律:
- 成交额地板(默认 10万U/日)= xv「可交易过滤」口径:切掉死对,防 Gate 现货两千长尾灌进 feed
  触发新鲜度误判;地板放宽须配合 feed 阈值重校准。
- 收缩保护:接口抽风返回小列表时拒绝覆盖(new < 20 或 new < prev*0.5 → SKIP),
  与 coin「universe 空则保留现列表」同一防御哲学。
- 逐所失败隔离:单所异常只丢该所本轮,其余照写;心跳 dcm:hb:universe-sync 带逐所计数,
  -1=拉取失败 -2=收缩保护拒写,风控面/看门狗按此巡检。
"""
import asyncio
import json
import logging
import os
import time

import httpx
import redis.asyncio as aioredis

REDIS_URL = os.environ.get("DCM_REDIS_URL", "redis://127.0.0.1:6379/0")
INTERVAL = int(os.environ.get("DCM_UNIVERSE_INTERVAL_SEC", "3600"))
MIN_QVOL = float(os.environ.get("DCM_UNIVERSE_MIN_QVOL", "100000"))  # 24h 成交额地板(USDT)
MIN_COUNT = 20
SHRINK_FLOOR = 0.5

log = logging.getLogger("universe-sync")


def _f(x, default=0.0):
    try:
        return float(x)
    except (TypeError, ValueError):
        return default


# ---------- 币安 ----------

async def binance(cli: httpx.AsyncClient, market: str) -> list[str]:
    base = "https://api.binance.com/api/v3" if market == "spot" else "https://fapi.binance.com/fapi/v1"
    info = (await cli.get(f"{base}/exchangeInfo")).json()
    ok = set()
    for s in info["symbols"]:
        if s.get("status") != "TRADING" or s.get("quoteAsset") != "USDT":
            continue
        if market == "perp" and s.get("contractType") != "PERPETUAL":
            continue
        ok.add(s["symbol"])
    vols = (await cli.get(f"{base}/ticker/24hr")).json()
    return sorted(t["symbol"].lower() for t in vols
                  if t["symbol"] in ok and _f(t.get("quoteVolume")) >= MIN_QVOL)


# ---------- OKX(SWAP 的 volCcy24h 是币量,×last 得 USDT) ----------

async def okx(cli: httpx.AsyncClient, market: str) -> list[str]:
    inst_type = "SPOT" if market == "spot" else "SWAP"
    info = (await cli.get(f"https://www.okx.com/api/v5/public/instruments?instType={inst_type}")).json()["data"]
    if market == "spot":
        ok = {d["instId"] for d in info if d.get("state") == "live" and d.get("quoteCcy") == "USDT"}
    else:
        ok = {d["instId"] for d in info if d.get("state") == "live" and d["instId"].endswith("-USDT-SWAP")}
    ticks = (await cli.get(f"https://www.okx.com/api/v5/market/tickers?instType={inst_type}")).json()["data"]
    out = []
    for t in ticks:
        if t["instId"] not in ok:
            continue
        qvol = _f(t.get("volCcy24h")) if market == "spot" else _f(t.get("volCcy24h")) * _f(t.get("last"))
        if qvol >= MIN_QVOL:
            out.append(t["instId"])
    return sorted(out)


# ---------- Bybit(instruments 分页;tickers.turnover24h=USDT) ----------

async def bybit(cli: httpx.AsyncClient, market: str) -> list[str]:
    category = "spot" if market == "spot" else "linear"
    ok, cursor = set(), ""
    while True:
        url = f"https://api.bybit.com/v5/market/instruments-info?category={category}&limit=1000"
        if cursor:
            url += f"&cursor={cursor}"
        res = (await cli.get(url)).json()["result"]
        for d in res.get("list", []):
            if d.get("status") != "Trading" or d.get("quoteCoin") != "USDT":
                continue
            if category == "linear" and d.get("contractType") != "LinearPerpetual":
                continue
            ok.add(d["symbol"])
        cursor = res.get("nextPageCursor") or ""
        if not cursor:
            break
    ticks = (await cli.get(f"https://api.bybit.com/v5/market/tickers?category={category}")).json()["result"]["list"]
    return sorted(t["symbol"] for t in ticks
                  if t["symbol"] in ok and _f(t.get("turnover24h")) >= MIN_QVOL)


# ---------- Gate(in_delisting 源头剔除;futures 优先 volume_24h_quote) ----------

async def gate(cli: httpx.AsyncClient, market: str) -> list[str]:
    if market == "spot":
        pairs = (await cli.get("https://api.gateio.ws/api/v4/spot/currency_pairs")).json()
        ok = {d["id"] for d in pairs if d.get("trade_status") == "tradable" and d["id"].endswith("_USDT")}
        ticks = (await cli.get("https://api.gateio.ws/api/v4/spot/tickers")).json()
        return sorted(t["currency_pair"] for t in ticks
                      if t["currency_pair"] in ok and _f(t.get("quote_volume")) >= MIN_QVOL)
    contracts = (await cli.get("https://api.gateio.ws/api/v4/futures/usdt/contracts")).json()
    ok = {d["name"] for d in contracts if not d.get("in_delisting") and d["name"].endswith("_USDT")}
    ticks = (await cli.get("https://api.gateio.ws/api/v4/futures/usdt/tickers")).json()
    out = []
    for t in ticks:
        if t.get("contract") not in ok:
            continue
        qvol = _f(t.get("volume_24h_quote")) or _f(t.get("volume_24h_settle"))
        if qvol >= MIN_QVOL:
            out.append(t["contract"])
    return sorted(out)


# ---------- Bitget(v2;usdtVolume) ----------

async def bitget(cli: httpx.AsyncClient, market: str) -> list[str]:
    if market == "spot":
        info = (await cli.get("https://api.bitget.com/api/v2/spot/public/symbols")).json()["data"]
        ok = {d["symbol"] for d in info if d.get("status") == "online" and d.get("quoteCoin") == "USDT"}
        ticks = (await cli.get("https://api.bitget.com/api/v2/spot/market/tickers")).json()["data"]
    else:
        info = (await cli.get("https://api.bitget.com/api/v2/mix/market/contracts?productType=usdt-futures")).json()["data"]
        ok = {d["symbol"] for d in info if d.get("symbolStatus") == "normal" and d.get("quoteCoin") == "USDT"}
        ticks = (await cli.get("https://api.bitget.com/api/v2/mix/market/tickers?productType=usdt-futures")).json()["data"]
    return sorted(t["symbol"] for t in ticks
                  if t["symbol"] in ok and _f(t.get("usdtVolume")) >= MIN_QVOL)


FETCHERS = {
    ("binance", "spot"): lambda c: binance(c, "spot"),
    ("binance", "perp"): lambda c: binance(c, "perp"),
    ("okx", "spot"): lambda c: okx(c, "spot"),
    ("okx", "perp"): lambda c: okx(c, "perp"),
    ("bybit", "spot"): lambda c: bybit(c, "spot"),
    ("bybit", "perp"): lambda c: bybit(c, "perp"),
    ("gate", "spot"): lambda c: gate(c, "spot"),
    ("gate", "perp"): lambda c: gate(c, "perp"),
    ("bitget", "spot"): lambda c: bitget(c, "spot"),
    ("bitget", "perp"): lambda c: bitget(c, "perp"),
}


async def sync_once(r: aioredis.Redis) -> dict:
    counts: dict[str, int] = {}
    async with httpx.AsyncClient(timeout=25) as cli:
        results = await asyncio.gather(*(f(cli) for f in FETCHERS.values()), return_exceptions=True)
    for (venue, market), res in zip(FETCHERS.keys(), results):
        tag = f"{venue}_{market}"
        key = f"dcm:feed:universe:{venue}:{market}"
        if isinstance(res, BaseException):
            log.warning(f"{tag} fetch failed: {res!r}")
            counts[tag] = -1
            continue
        prev_raw = await r.get(key)
        prev = len(json.loads(prev_raw)) if prev_raw else 0
        if len(res) < MIN_COUNT or (prev and len(res) < prev * SHRINK_FLOOR):
            log.warning(f"SYNC_SKIP {tag}: new={len(res)} prev={prev} (收缩保护拒写)")
            counts[tag] = -2
            continue
        await r.set(key, json.dumps(res))
        counts[tag] = len(res)
    return counts


async def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    r = aioredis.from_url(REDIS_URL, decode_responses=True)
    log.info(f"universe-sync up interval={INTERVAL}s min_qvol={MIN_QVOL}")
    while True:
        try:
            counts = await sync_once(r)
            hb = {"service": "universe-sync", "ts": int(time.time()), "pid": os.getpid(),
                  "counts": counts, "min_qvol": MIN_QVOL}
            await r.set("dcm:hb:universe-sync", json.dumps(hb), ex=max(INTERVAL * 2, 7200))
            log.info(f"SYNC_OK {counts}")
        except Exception:
            log.exception("sync loop error")
        await asyncio.sleep(INTERVAL)


if __name__ == "__main__":
    asyncio.run(main())
