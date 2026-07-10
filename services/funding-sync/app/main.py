"""funding-sync:五所永续资金费采集,按【结算周期】归一化日化(xv 已验证口径逐行移植)。

口径铁律(xv 学费):资金费必须按结算周期归一日化再比较——币安 fundingInfo 例外表(4h/1h 币)、
Bybit fundingInterval 分钟、Gate funding_interval 秒、Bitget fundInterval 小时、
OKX 无批量端点用 nextFundingTime-fundingTime 推(异常值回退 8h)。不归一 gap 错 2~8 倍。

OKX 特殊:资金费仅逐合约端点 → 每轮轮转扫 OKX_CHUNK 个并缓存,全宇宙 ~6 轮扫完;
缓存条目带自身 ts,消费者按龄判弃(引擎侧 funding_stale 判定)。

键契约:HSET dcm:feed:funding:{venue} <统一符号> {"daily_pct":日化%,"fr":原始费率,
"interval_h":周期小时,"mark":标记价,"ts":写入秒} + 心跳 dcm:hb:funding-sync 逐所计数。
数据面只采集归一不判断。
"""
import asyncio
import json
import logging
import os
import time

import httpx
import redis.asyncio as aioredis

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("funding-sync")

REDIS_URL = os.environ.get("DCM_REDIS_URL", "redis://127.0.0.1:6379/0")
INTERVAL = int(os.environ.get("DCM_FUNDING_INTERVAL_SEC", "240"))
META_REFRESH_SEC = int(os.environ.get("DCM_FUNDING_META_SEC", "3600"))
OKX_CHUNK = int(os.environ.get("DCM_FUNDING_OKX_CHUNK", "60"))
OKX_CONC = 6


class FundingSync:
    def __init__(self):
        self.bn_interval_h: dict[str, float] = {}
        self.bn_tradable: set[str] = set()
        self.bb_interval_h: dict[str, float] = {}
        self.bb_tradable: set[str] = set()
        self.bg_interval_h: dict[str, float] = {}
        self.okx_insts: list[str] = []
        self.okx_cursor = 0
        self.okx_cache: dict[str, dict] = {}  # 统一符号 -> 完整条目(带自身 ts)
        self._meta_at = 0.0

    # ── 元数据(结算周期/可交易状态,低频) ──
    async def refresh_meta(self, cli: httpx.AsyncClient):
        try:
            r = await cli.get("https://fapi.binance.com/fapi/v1/fundingInfo")
            self.bn_interval_h = {x["symbol"]: float(x.get("fundingIntervalHours") or 8)
                                  for x in r.json() if isinstance(x, dict) and x.get("symbol")}
        except Exception as e:
            log.warning("bn fundingInfo: %r", e)
        try:
            r = await cli.get("https://fapi.binance.com/fapi/v1/exchangeInfo")
            tr = {x["symbol"] for x in r.json().get("symbols", [])
                  if x.get("status") == "TRADING" and x.get("contractType") == "PERPETUAL"
                  and x.get("symbol", "").endswith("USDT")}
            if tr:
                self.bn_tradable = tr
        except Exception as e:
            log.warning("bn exchangeInfo: %r", e)
        try:
            out: dict[str, float] = {}
            tradable: set[str] = set()
            cursor = ""
            for _ in range(6):
                params = {"category": "linear", "limit": "1000"}
                if cursor:
                    params["cursor"] = cursor
                r = await cli.get("https://api.bybit.com/v5/market/instruments-info", params=params)
                res = r.json().get("result", {})
                for it in res.get("list", []):
                    s = it.get("symbol", "")
                    if s.endswith("USDT"):
                        out[s] = float(it.get("fundingInterval") or 480) / 60.0
                        if it.get("status") == "Trading":
                            tradable.add(s)
                cursor = res.get("nextPageCursor") or ""
                if not cursor:
                    break
            if out:
                self.bb_interval_h = out
            if tradable:
                self.bb_tradable = tradable
        except Exception as e:
            log.warning("bb instruments: %r", e)
        try:
            r = await cli.get("https://api.bitget.com/api/v2/mix/market/contracts",
                              params={"productType": "USDT-FUTURES"})
            self.bg_interval_h = {x["symbol"]: float(x.get("fundInterval") or 8)
                                  for x in r.json().get("data", [])
                                  if x.get("symbol", "").endswith("USDT")
                                  and x.get("symbolStatus") in (None, "normal")}
        except Exception as e:
            log.warning("bg contracts: %r", e)
        try:
            r = await cli.get("https://www.okx.com/api/v5/public/instruments",
                              params={"instType": "SWAP"})
            self.okx_insts = [x.get("instId", "") for x in r.json().get("data", [])
                              if x.get("instId", "").endswith("-USDT-SWAP") and x.get("state") == "live"]
        except Exception as e:
            log.warning("okx instruments: %r", e)
        self._meta_at = time.monotonic()
        log.info("meta: bn_exc=%d bn_tr=%d bb=%d bg=%d okx=%d",
                 len(self.bn_interval_h), len(self.bn_tradable),
                 len(self.bb_interval_h), len(self.bg_interval_h), len(self.okx_insts))

    @staticmethod
    def entry(fr: float, hours: float, mark: float, now: int) -> str:
        return json.dumps({"fr": fr, "interval_h": hours,
                           "daily_pct": fr * (24.0 / hours) * 100.0,
                           "mark": mark, "ts": now})

    async def fetch_bn(self, cli, now) -> dict[str, str]:
        r = await cli.get("https://fapi.binance.com/fapi/v1/premiumIndex")
        out = {}
        for t in r.json():
            s = t.get("symbol", "")
            if not s.endswith("USDT") or "_" in s:
                continue
            if self.bn_tradable and s not in self.bn_tradable:
                continue
            try:
                fr, mark = float(t.get("lastFundingRate") or 0), float(t.get("markPrice") or 0)
            except (TypeError, ValueError):
                continue
            if mark > 0:
                out[s] = self.entry(fr, self.bn_interval_h.get(s, 8.0), mark, now)
        return out

    async def fetch_bb(self, cli, now) -> dict[str, str]:
        r = await cli.get("https://api.bybit.com/v5/market/tickers", params={"category": "linear"})
        out = {}
        for t in r.json().get("result", {}).get("list", []):
            s = t.get("symbol", "")
            if not s.endswith("USDT"):
                continue
            if self.bb_tradable and s not in self.bb_tradable:
                continue
            try:
                fr, mark = float(t.get("fundingRate") or 0), float(t.get("markPrice") or 0)
            except (TypeError, ValueError):
                continue
            if mark > 0:
                out[s] = self.entry(fr, self.bb_interval_h.get(s, 8.0), mark, now)
        return out

    async def fetch_gate(self, cli, now) -> dict[str, str]:
        r = await cli.get("https://api.gateio.ws/api/v4/futures/usdt/contracts")
        out = {}
        for t in r.json():
            name = t.get("name", "")
            if not name.endswith("_USDT") or t.get("in_delisting"):
                continue
            try:
                fr = float(t.get("funding_rate") or 0)
                mark = float(t.get("mark_price") or 0)
                itv = float(t.get("funding_interval") or 28800)
            except (TypeError, ValueError):
                continue
            if mark > 0 and itv > 0:
                out[name.replace("_USDT", "USDT")] = self.entry(fr, itv / 3600.0, mark, now)
        return out

    async def fetch_bg(self, cli, now) -> dict[str, str]:
        r = await cli.get("https://api.bitget.com/api/v2/mix/market/tickers",
                          params={"productType": "USDT-FUTURES"})
        out = {}
        for t in r.json().get("data", []):
            s = t.get("symbol", "")
            if not s.endswith("USDT") or s not in self.bg_interval_h:
                continue
            try:
                fr, mark = float(t.get("fundingRate") or 0), float(t.get("markPrice") or 0)
            except (TypeError, ValueError):
                continue
            if mark > 0:
                out[s] = self.entry(fr, self.bg_interval_h.get(s, 8.0), mark, now)
        return out

    async def fetch_hl(self, cli, now) -> dict[str, str]:
        """Hyperliquid:metaAndAssetCtxs 批量返回全宇宙;funding=每小时费率(interval 1h)。
        统一符号=coin 名+USDT(与 feed hl_normalize 同源;kPEPE 类 k 前缀原样保留)。"""
        r = await cli.post("https://api.hyperliquid.xyz/info",
                           json={"type": "metaAndAssetCtxs"})
        meta, ctxs = r.json()
        out = {}
        for u, c in zip(meta.get("universe", []), ctxs):
            if u.get("isDelisted"):
                continue
            try:
                fr, mark = float(c.get("funding") or 0), float(c.get("markPx") or 0)
            except (TypeError, ValueError):
                continue
            if mark > 0:
                sym = u["name"].upper().replace("-", "").replace("_", "") + "USDT"
                out[sym] = self.entry(fr, 1.0, mark, now)
        return out

    async def okx_sweep(self, cli, now):
        """逐合约轮转扫:每轮 OKX_CHUNK 个,interval=nextFundingTime-fundingTime 推,异常回退 8h。"""
        if not self.okx_insts:
            return
        n = len(self.okx_insts)
        chunk = [self.okx_insts[(self.okx_cursor + i) % n] for i in range(min(OKX_CHUNK, n))]
        self.okx_cursor = (self.okx_cursor + len(chunk)) % n
        sem = asyncio.Semaphore(OKX_CONC)

        async def one(inst):
            async with sem:
                try:
                    r = await cli.get("https://www.okx.com/api/v5/public/funding-rate",
                                      params={"instId": inst})
                    d = r.json().get("data", [{}])[0]
                    fr = float(d.get("fundingRate") or 0)
                    ft, nft = float(d.get("fundingTime") or 0), float(d.get("nextFundingTime") or 0)
                    hours = (nft - ft) / 3600000.0 if nft > ft > 0 else 8.0
                    if hours <= 0 or hours > 24:
                        hours = 8.0
                    sym = inst.replace("-USDT-SWAP", "USDT")
                    self.okx_cache[sym] = {"fr": fr, "interval_h": hours,
                                           "daily_pct": fr * (24.0 / hours) * 100.0,
                                           "mark": 0.0, "ts": now}
                except Exception:
                    pass
        await asyncio.gather(*[one(i) for i in chunk])


async def main():
    r = aioredis.from_url(REDIS_URL, decode_responses=True)
    fs = FundingSync()
    log.info("funding-sync up interval=%ss okx_chunk=%d", INTERVAL, OKX_CHUNK)
    async with httpx.AsyncClient(timeout=20) as cli:
        await fs.refresh_meta(cli)
        while True:
            try:
                now = int(time.time())
                if time.monotonic() - fs._meta_at > META_REFRESH_SEC:
                    await fs.refresh_meta(cli)
                results = await asyncio.gather(
                    fs.fetch_bn(cli, now), fs.fetch_bb(cli, now),
                    fs.fetch_gate(cli, now), fs.fetch_bg(cli, now),
                    fs.fetch_hl(cli, now),
                    fs.okx_sweep(cli, now), return_exceptions=True)
                venue_maps = {"binance": results[0], "bybit": results[1],
                              "gate": results[2], "bitget": results[3],
                              "hyperliquid": results[4]}
                counts = {}
                for venue, m in venue_maps.items():
                    if isinstance(m, BaseException):
                        log.warning("%s funding fetch failed: %r", venue, m)
                        counts[venue] = -1
                        continue
                    if m:
                        await r.hset(f"dcm:feed:funding:{venue}", mapping=m)
                    counts[venue] = len(m)
                if fs.okx_cache:
                    await r.hset("dcm:feed:funding:okx",
                                 mapping={s: json.dumps(v) for s, v in fs.okx_cache.items()})
                counts["okx"] = len(fs.okx_cache)
                await r.set("dcm:hb:funding-sync", json.dumps(
                    {"service": "funding-sync", "ts": now, "pid": os.getpid(),
                     "counts": counts}), ex=max(INTERVAL * 3, 900))
                log.info("FUNDING_OK %s", counts)
            except Exception:
                log.exception("funding round crashed (continuing)")
            await asyncio.sleep(INTERVAL)


if __name__ == "__main__":
    asyncio.run(main())
