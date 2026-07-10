"""lending-advisor(增强层):币安全币"三率净差"排序 = |资金费| + 理财收益 − 借币利率。

罩在底仓/双合约/coin 之上的收益放大器:每轮拉币安永续资金费(funding-sync 已有)+
杠杆借币利率 + 灵活理财年化,算逐币三率净差日化,排序取 top,发 dcm:lending:ranking 供面板;
内嵌稳定币利率倒挂监控(借稳定币利率 < 理财 → 无风险套利)。只读+排序+告警,不动手。

币安端点:
- 借币利率 /sapi/v1/margin/interestRateHistory 或 crossMarginData(需签名);此处用
  /sapi/v1/margin/crossMarginData(公开的日利率)+ 理财 /sapi/v1/lending/daily/product/list(签名)。
  简化:借币用 nextHourlyInterestRate 折日;理财用 flexible latestAnnualPercentageRate。
数据不可得的币跳过(绝不猜)。
"""
import asyncio
import hashlib
import hmac
import json
import logging
import os
import time
from urllib.parse import urlencode

import asyncpg  # noqa: F401 (预留,当前仅redis)
import httpx
import redis.asyncio as aioredis

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("lending-advisor")

REDIS_URL = os.environ.get("DCM_REDIS_URL", "redis://10.0.1.212:6379/0")
INTERVAL = int(os.environ.get("DCM_LENDING_INTERVAL_SEC", "1800"))
KEY = os.environ.get("BINANCE_KEY", "")
SECRET = os.environ.get("BINANCE_SECRET", "")
TOP_N = int(os.environ.get("DCM_LENDING_TOP_N", "40"))


def _signed(params: dict) -> str:
    params = {**params, "timestamp": int(time.time() * 1000), "recvWindow": 5000}
    q = urlencode(params)
    sig = hmac.new(SECRET.encode(), q.encode(), hashlib.sha256).hexdigest()
    return f"{q}&signature={sig}"


async def fetch_borrow_daily(cli) -> dict[str, float]:
    """逐币杠杆借币日利率(%)。crossMarginData 返回 dailyInterestRate。"""
    try:
        r = (await cli.get(f"https://api.binance.com/sapi/v1/margin/crossMarginData?{_signed({})}",
                           headers={"X-MBX-APIKEY": KEY})).json()
    except Exception as e:
        log.warning("borrow fetch: %r", e)
        return {}
    out = {}
    if isinstance(r, list):
        for x in r:
            try:
                out[x["coin"]] = float(x.get("dailyInterestRate") or 0) * 100
            except (KeyError, TypeError, ValueError):
                pass
    return out


async def fetch_earn_flexible(cli) -> dict[str, float]:
    """逐币灵活理财最新年化(%)→日化。simple-earn flexible list 分页。"""
    out = {}
    try:
        for page in range(1, 4):
            r = (await cli.get(
                f"https://api.binance.com/sapi/v1/simple-earn/flexible/list?{_signed({'size': 100, 'current': page})}",
                headers={"X-MBX-APIKEY": KEY})).json()
            rows = r.get("rows") if isinstance(r, dict) else None
            if not rows:
                break
            for x in rows:
                try:
                    apr = float(x.get("latestAnnualPercentageRate") or 0) * 100
                    out[x["asset"]] = apr / 365.0  # 年化→日化%
                except (KeyError, TypeError, ValueError):
                    pass
    except Exception as e:
        log.warning("earn fetch: %r", e)
    return out


async def main():
    r = aioredis.from_url(REDIS_URL, decode_responses=True)
    log.info("lending-advisor up interval=%ss", INTERVAL)
    while True:
        try:
            async with httpx.AsyncClient(timeout=20) as cli:
                borrow = await fetch_borrow_daily(cli)   # 日利率%
                earn = await fetch_earn_flexible(cli)     # 日化%
            # 资金费日化(绝对值):从 funding-sync 币安哈希
            fmap = await r.hgetall("dcm:feed:funding:binance")
            funding_abs = {}
            for s, js in fmap.items():
                try:
                    base = s[:-4] if s.endswith("USDT") else s
                    funding_abs[base] = abs(float(json.loads(js)["daily_pct"]))
                except Exception:
                    pass
            # 三率净差(日化%)= |资金费| + 理财 − 借币
            rows = []
            for coin in set(borrow) | set(earn) | set(funding_abs):
                b = borrow.get(coin); e = earn.get(coin); f = funding_abs.get(coin, 0.0)
                if b is None and e is None:
                    continue
                net = f + (e or 0) - (b or 0)
                rows.append({"coin": coin, "net_daily_pct": round(net, 5),
                             "funding_abs": round(f, 5), "earn": round(e or 0, 5), "borrow": round(b or 0, 5)})
            rows.sort(key=lambda x: -x["net_daily_pct"])
            # 稳定币利率倒挂:借<理财(无风险)
            inversions = [x for x in rows if x["coin"] in ("USDT", "USDC", "FDUSD", "DAI", "TUSD")
                          and x["earn"] > x["borrow"] > 0]
            await r.set("dcm:lending:ranking", json.dumps(
                {"ts": int(time.time()), "top": rows[:TOP_N], "inversions": inversions,
                 "coins": len(rows)}, ensure_ascii=False), ex=INTERVAL * 3)
            await r.set("dcm:hb:lending-advisor", json.dumps(
                {"service": "lending-advisor", "ts": int(time.time()), "pid": os.getpid(),
                 "coins": len(rows), "inversions": len(inversions)}), ex=max(INTERVAL * 3, 3600))
            log.info("LENDING_OK coins=%d top_net=%s inversions=%d",
                     len(rows), rows[0]["net_daily_pct"] if rows else None, len(inversions))
        except Exception:
            log.exception("lending round crashed (continuing)")
        await asyncio.sleep(INTERVAL)


if __name__ == "__main__":
    asyncio.run(main())
