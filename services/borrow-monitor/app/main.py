"""borrow-monitor v1:借币可借性 + 放币窗口监控(蓝图机会外挂层;点亮 coin 命门"无券"的眼睛)。

命门(coin-arb-inventory-vs-spread):高点差币在币安常无券(-3045),库存何时"放币"全靠盲等。
本服务纯读逐所逐币 max-borrowable,把"能不能借/最大可借"变成可观测流,并检测
**0→可借 的放币事件**(库存补充瞬间)→ 飞书告警 + 事件流,让抢券从盲等变预判。

跑在 B 机(交易所 key 只在 B,与 account-snapshot 同机)。纯读,绝无下单/借币动作。

键契约:
  dcm:borrow:avail   HSET {venue}:{ASSET} -> {amount, ts}(当前可借快照,EX 滚动)
  dcm:borrow:events  LPUSH JSON(放币/断券事件流,LTRIM 200)
  dcm:borrow:watchlist  (可选)其他组件写入的关注币集合(coin 引擎 -3045 命中币等);
                        与 BASE_WATCH 并集;为空则回落 BASE_WATCH
  dcm:hb:borrow-monitor  心跳

放币判定:asset 上一轮 amount≤地板、本轮 > 地板 → 放币(release);反向 → 断券(dry)。
去抖:事件按 (venue,asset,方向) 冷却,避免临界抖动刷屏。冷启动只登记不告警。
venue 覆盖:binance(命门所,实现)+okx(①canary目标,实现);其余所留 spec 位待扩。
"""
import asyncio
import base64
import hashlib
import hmac
import json
import logging
import os
import time
from urllib.parse import urlencode

import httpx
import redis.asyncio as aioredis

from dcm_common.heartbeat import Heartbeat
from dcm_common.notify import Notifier, feishu_from_env

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("borrow-monitor")

SERVICE = "borrow-monitor"
REDIS_URL = os.environ.get("DCM_REDIS_URL", "redis://10.0.1.212:6379/0")
INTERVAL = int(os.environ.get("DCM_BORROW_INTERVAL_SEC", "120"))
# 关注币基础清单(逗号分隔 base 资产);实际关注集 = 此 ∪ dcm:borrow:watchlist ∪ 活跃dualperp路由base
BASE_WATCH = [x.strip().upper() for x in os.environ.get(
    "DCM_BORROW_BASE_WATCH", "").split(",") if x.strip()]
AVAIL_FLOOR = float(os.environ.get("DCM_BORROW_AVAIL_FLOOR", "0"))  # 可借量>此视为有券(地板过滤粉尘额度)
EVENT_COOLDOWN = int(os.environ.get("DCM_BORROW_EVENT_COOLDOWN_SEC", "600"))
KEY_AVAIL = "dcm:borrow:avail"
KEY_EVENTS = "dcm:borrow:events"
KEY_WATCH = "dcm:borrow:watchlist"

BINANCE = {"key": os.environ.get("BINANCE_KEY", ""), "secret": os.environ.get("BINANCE_SECRET", "")}
OKX = {"key": os.environ.get("OKX_KEY", ""), "secret": os.environ.get("OKX_SECRET", ""),
       "passphrase": os.environ.get("OKX_PASSPHRASE", "")}

_prev: dict[str, float] = {}          # "{venue}:{ASSET}" -> 上轮 amount
_evt_cooldown: dict[str, float] = {}  # "{venue}:{ASSET}:{dir}" -> ts


async def _binance_borrowable(cli: httpx.AsyncClient, asset: str) -> float | None:
    """币安全仓 max-borrowable。amount=0 或 -3045(无券)→ 0;鉴权/其他错→ None(不误判放币)。"""
    q = urlencode({"asset": asset, "timestamp": int(time.time() * 1000), "recvWindow": 5000})
    sig = hmac.new(BINANCE["secret"].encode(), q.encode(), hashlib.sha256).hexdigest()
    try:
        r = (await cli.get(f"https://api.binance.com/sapi/v1/margin/maxBorrowable?{q}&signature={sig}",
                           headers={"X-MBX-APIKEY": BINANCE["key"]})).json()
        if isinstance(r, dict) and "amount" in r:
            return float(r.get("amount") or 0)
        # -3045=无券(系统无可借资产);其余错误码返回 None 不误判
        if isinstance(r, dict) and str(r.get("code")) == "-3045":
            return 0.0
        return None
    except Exception:
        return None


async def _okx_borrowable(cli: httpx.AsyncClient, asset: str) -> float | None:
    """OKX 全仓 max-loan(ccy 维度)。availLoan/maxLoan 取可借;缺/错→ None。"""
    ts = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()) + ".000Z"
    path = f"/api/v5/account/max-loan?mgnMode=cross&ccy={asset}"
    pre = ts + "GET" + path
    sign = base64.b64encode(hmac.new(OKX["secret"].encode(), pre.encode(), hashlib.sha256).digest()).decode()
    try:
        r = (await cli.get(f"https://www.okx.com{path}", headers={
            "OK-ACCESS-KEY": OKX["key"], "OK-ACCESS-SIGN": sign, "OK-ACCESS-TIMESTAMP": ts,
            "OK-ACCESS-PASSPHRASE": OKX["passphrase"]})).json()
        if str(r.get("code")) == "0" and r.get("data"):
            row = r["data"][0]
            return float(row.get("availLoan") or row.get("maxLoan") or 0)
        return None
    except Exception:
        return None


# 币安=命门所(coin 引擎在此借、在此撞 -3045),始终启用;
# OKX 现货杠杆借币链路依赖账户保证金模式,待 ① 多venue借币建立后经 DCM_BORROW_OKX=true 点亮
_VENUES = {"binance": _binance_borrowable}
if OKX["key"] and os.environ.get("DCM_BORROW_OKX", "").lower() == "true":
    _VENUES["okx"] = _okx_borrowable


async def _watch_assets(r: aioredis.Redis) -> list[str]:
    assets = set(BASE_WATCH)
    try:
        assets |= set(a.upper() for a in await r.smembers(KEY_WATCH))
    except Exception:
        pass
    # 活跃 dualperp 路由的 base(高资金费币,也是 coin 借币的天然关注对象)
    try:
        for js in (await r.hgetall("dcm:route:assignments")).values():
            rt = json.loads(js)
            if rt.get("state") == "active" and rt.get("symbol", "").endswith("USDT"):
                assets.add(rt["symbol"][:-4])
    except Exception:
        pass
    return sorted(assets)


async def monitor_round(r: aioredis.Redis, cli: httpx.AsyncClient, notify: Notifier) -> dict:
    now = int(time.time())
    assets = await _watch_assets(r)
    checked = releases = dries = 0
    for asset in assets:
        for venue, fn in _VENUES.items():
            amt = await fn(cli, asset)
            if amt is None:
                continue  # 查询失败:不更新、不判事件(绝不把鉴权错误误判成断券)
            checked += 1
            key = f"{venue}:{asset}"
            await r.hset(KEY_AVAIL, key, json.dumps({"amount": amt, "ts": now}))
            prev = _prev.get(key)
            _prev[key] = amt
            if prev is None:
                continue  # 冷启动只登记不告警
            direction = None
            if prev <= AVAIL_FLOOR < amt:
                direction = "release"   # 放币:无券→有券
            elif prev > AVAIL_FLOOR >= amt:
                direction = "dry"       # 断券:有券→无券
            if not direction:
                continue
            cdk = f"{key}:{direction}"
            if now - _evt_cooldown.get(cdk, 0) < EVENT_COOLDOWN:
                continue
            _evt_cooldown[cdk] = now
            ev = {"venue": venue, "asset": asset, "direction": direction,
                  "amount": round(amt, 4), "prev": round(prev, 4), "ts": now}
            await r.lpush(KEY_EVENTS, json.dumps(ev, ensure_ascii=False))
            if direction == "release":
                releases += 1
                await asyncio.to_thread(
                    notify.fire, f"release:{key}", f"放币 {venue} {asset}",
                    f"{venue} {asset} 库存放出,最大可借 {round(amt,2)}(此前无券)——抢券窗口", level="warn")
            else:
                dries += 1
    await r.ltrim(KEY_EVENTS, 0, 199)
    await r.expire(KEY_AVAIL, INTERVAL * 4)
    return {"assets": len(assets), "checked": checked, "releases": releases, "dries": dries,
            "venues": list(_VENUES)}


async def main():
    r = aioredis.from_url(REDIS_URL, decode_responses=True)
    notify = Notifier(REDIS_URL, SERVICE, feishu=feishu_from_env())
    hb = Heartbeat(REDIS_URL, SERVICE, interval_sec=60, ttl_sec=max(INTERVAL * 3, 600))
    asyncio.create_task(hb.run_forever())
    log.info(f"borrow-monitor up interval={INTERVAL}s venues={list(_VENUES)} base_watch={len(BASE_WATCH)}")
    async with httpx.AsyncClient(timeout=15) as cli:
        while True:
            try:
                stats = await monitor_round(r, cli, notify)
                hb.extra = stats
                log.info(f"BORROW_OK {stats}")
            except Exception:
                log.exception("borrow-monitor round crashed (continuing)")
            await asyncio.sleep(INTERVAL)


if __name__ == "__main__":
    asyncio.run(main())
