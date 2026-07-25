"""dcm-io-monitor —— 充提通道状态采集(批二,B机密钥)。
各所 capital-config 端点一次返回全币充提开关,每 5 分钟一所一次签名调用覆盖所有币。
发布 hash dcm:cex:io:{venue}(field=CANON, value={dep,wd,ts});Asset360 只读,C 机零密钥。
口径:任一网络可充=dep OPEN;任一网络可提=wd OPEN;全关=CLOSED。HL(DEX)无此概念,跳过。
"""
import asyncio
import base64
import hashlib
import hmac
import json
import os
import time
from urllib.parse import urlencode

import httpx
import redis.asyncio as aioredis

REDIS_URL = os.environ.get("DCM_REDIS_URL", "redis://10.0.1.95:6379/0")
INTERVAL = int(os.environ.get("DCM_IO_INTERVAL_SEC", "300"))


def _canon(sym: str) -> str:
    s = str(sym or "").upper()
    for suf in ("USDT", "USD"):
        if s.endswith(suf):
            s = s[: -len(suf)]
    return s


# ── 各所签名+拉全币充提配置 → {canon: (dep_open, wd_open)} ────────────
async def _binance(cli):
    k, s = os.environ.get("BINANCE_KEY", ""), os.environ.get("BINANCE_SECRET", "")
    if not k:
        return {}
    ts = str(int(time.time() * 1000))
    qs = f"timestamp={ts}"
    sig = hmac.new(s.encode(), qs.encode(), hashlib.sha256).hexdigest()
    r = await cli.get(f"https://api.binance.com/sapi/v1/capital/config/getall?{qs}&signature={sig}",
                      headers={"X-MBX-APIKEY": k})
    out = {}
    for c in r.json():
        nets = c.get("networkList") or []
        out[str(c.get("coin", "")).upper()] = (
            any(n.get("depositEnable") for n in nets),
            any(n.get("withdrawEnable") for n in nets))
    return out


async def _okx(cli):
    k = os.environ.get("OKX_KEY", "")
    s = os.environ.get("OKX_SECRET", "")
    pw = os.environ.get("OKX_PASSPHRASE", "")
    if not k:
        return {}
    ts = time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime())
    path = "/api/v5/asset/currencies"
    sig = base64.b64encode(hmac.new(s.encode(), (ts + "GET" + path).encode(), hashlib.sha256).digest()).decode()
    r = await cli.get("https://www.okx.com" + path, headers={
        "OK-ACCESS-KEY": k, "OK-ACCESS-SIGN": sig, "OK-ACCESS-TIMESTAMP": ts,
        "OK-ACCESS-PASSPHRASE": pw})
    out = {}
    for c in (r.json().get("data") or []):
        cc = str(c.get("ccy", "")).upper()
        d, w = out.get(cc, (False, False))
        out[cc] = (d or bool(c.get("canDep")), w or bool(c.get("canWd")))
    return out


async def _bybit(cli):
    k, s = os.environ.get("BYBIT_KEY", ""), os.environ.get("BYBIT_SECRET", "")
    if not k:
        return {}
    ts = str(int(time.time() * 1000))
    recv = "10000"
    qs = ""
    sign = hmac.new(s.encode(), (ts + k + recv + qs).encode(), hashlib.sha256).hexdigest()
    r = await cli.get("https://api.bybit.com/v5/asset/coin/query-info",
                      headers={"X-BAPI-API-KEY": k, "X-BAPI-TIMESTAMP": ts,
                               "X-BAPI-RECV-WINDOW": recv, "X-BAPI-SIGN": sign})
    out = {}
    for c in ((r.json().get("result") or {}).get("rows") or []):
        cc = str(c.get("coin", "")).upper()
        chains = c.get("chains") or []
        out[cc] = (any(str(ch.get("chainDeposit")) == "1" for ch in chains),
                   any(str(ch.get("chainWithdraw")) == "1" for ch in chains))
    return out


async def _gate(cli):
    k, s = os.environ.get("GATE_KEY", ""), os.environ.get("GATE_SECRET", "")
    if not k:
        return {}
    ts = str(int(time.time()))
    path = "/api/v4/wallet/currency_chains"   # 需 currency 参数→改用公开 /spot/currencies
    # gate 全币充提:公开 /api/v4/spot/currencies 返回 deposit_disabled/withdraw_disabled
    r = await cli.get("https://api.gateio.ws/api/v4/spot/currencies")
    out = {}
    for c in r.json():
        cc = str(c.get("currency", "")).upper().split("_")[0]
        d, w = out.get(cc, (False, False))
        out[cc] = (d or not c.get("deposit_disabled"), w or not c.get("withdraw_disabled"))
    return out


async def _bitget(cli):
    # bitget 公开 /api/v2/spot/public/coins 返回 chains rechargeable/withdrawable
    r = await cli.get("https://api.bitget.com/api/v2/spot/public/coins")
    out = {}
    for c in (r.json().get("data") or []):
        cc = str(c.get("coin", "")).upper()
        chains = c.get("chains") or []
        out[cc] = (any(str(ch.get("rechargeable")) == "true" for ch in chains),
                   any(str(ch.get("withdrawable")) == "true" for ch in chains))
    return out


_FETCH = {"binance": _binance, "okx": _okx, "bybit": _bybit, "gate": _gate, "bitget": _bitget}


async def poll_venue(cli, r, venue):
    try:
        m = await _FETCH[venue](cli)
        if not m:
            return 0
        pipe = r.pipeline()
        for cc, (dep, wd) in m.items():
            pipe.hset(f"dcm:cex:io:{venue}", cc,
                      json.dumps({"dep": "OPEN" if dep else "CLOSED",
                                  "wd": "OPEN" if wd else "CLOSED", "ts": int(time.time())}))
        pipe.expire(f"dcm:cex:io:{venue}", INTERVAL * 3)
        await pipe.execute()
        return len(m)
    except Exception as e:  # noqa: BLE001
        print(f"io_monitor {venue} err: {str(e)[:80]}", flush=True)
        return 0


async def main():
    r = aioredis.from_url(REDIS_URL, decode_responses=True)
    print(f"io_monitor up interval={INTERVAL}s venues={list(_FETCH)}")
    while True:
        async with httpx.AsyncClient(timeout=20) as cli:
            counts = {}
            for v in _FETCH:
                counts[v] = await poll_venue(cli, r, v)
                await asyncio.sleep(1)   # 逐所错峰
        await r.setex("dcm:hb:io-monitor", INTERVAL * 2,
                      json.dumps({"ts": int(time.time()), "counts": counts}))
        print(f"io_monitor cycle: {counts}", flush=True)
        await asyncio.sleep(INTERVAL)


if __name__ == "__main__":
    asyncio.run(main())
