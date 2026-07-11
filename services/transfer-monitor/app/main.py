"""transfer-monitor v1:充提状态监控(蓝图风控面补盲区)。

风控盲区:持仓币一旦被暂停提现,常是下架/脱锚前兆——risk-ledger 现在完全看不见。
本服务纯读币安 capital/config(一次调用返全部币逐网络充提开关),逐币归并"任一网络可充/可提",
发布状态快照 + 检测 开→关 转变;**持仓币被暂停提现即 fatal**(下架/交割/脱锚风险)。

跑在 B 机(key 所在)。纯读,绝无划转/提现动作。币安为主(coin 持仓与现货腿都在币安)。

键契约:
  dcm:coin:transfer_status  HSET {ASSET} -> {dep, wd, ts}(dep/wd=任一网络可充/可提)
  dcm:coin:transfer_events  LPUSH JSON(充提开关转变流,LTRIM 200)
  dcm:hb:transfer-monitor   心跳

持仓集 = dualperp/basis/coin 三引擎快照并集(base 资产);持仓币提现被停 → fatal 告警。
去抖:转变事件按 (asset,field,方向) 冷却;冷启动只登记不告警。
"""
import asyncio
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
log = logging.getLogger("transfer-monitor")

SERVICE = "transfer-monitor"
REDIS_URL = os.environ.get("DCM_REDIS_URL", "redis://10.0.1.212:6379/0")
INTERVAL = int(os.environ.get("DCM_TRANSFER_INTERVAL_SEC", "300"))
EVENT_COOLDOWN = int(os.environ.get("DCM_TRANSFER_EVENT_COOLDOWN_SEC", "1800"))
KEY_STATUS = "dcm:coin:transfer_status"
KEY_EVENTS = "dcm:coin:transfer_events"

BINANCE = {"key": os.environ.get("BINANCE_KEY", ""), "secret": os.environ.get("BINANCE_SECRET", "")}

_prev: dict[str, tuple] = {}          # ASSET -> (dep, wd)
_evt_cooldown: dict[str, float] = {}  # "{ASSET}:{field}:{dir}" -> ts


async def _binance_capital(cli: httpx.AsyncClient) -> dict[str, dict] | None:
    """全币逐网络充提开关。归并:任一网络可充→dep=True;任一网络可提→wd=True。失败 None。"""
    q = urlencode({"timestamp": int(time.time() * 1000), "recvWindow": 5000})
    sig = hmac.new(BINANCE["secret"].encode(), q.encode(), hashlib.sha256).hexdigest()
    try:
        r = (await cli.get(f"https://api.binance.com/sapi/v1/capital/config/getall?{q}&signature={sig}",
                           headers={"X-MBX-APIKEY": BINANCE["key"]})).json()
        if not isinstance(r, list):
            return None
        out = {}
        for x in r:
            nets = x.get("networkList") or []
            out[x["coin"].upper()] = {
                "dep": any(n.get("depositEnable") for n in nets),
                "wd": any(n.get("withdrawEnable") for n in nets),
            }
        return out
    except Exception:
        return None


async def _held_assets(r: aioredis.Redis) -> set[str]:
    """dualperp/basis/coin 三引擎在场持仓的 base 资产。"""
    held: set[str] = set()
    for key in ("dcm:engine:dualperp:positions", "dcm:engine:basis:positions", "dcm:engine:coin:positions"):
        try:
            d = json.loads(await r.get(key) or "{}")
            for p in d.get("positions") or []:
                sym = p.get("symbol") or ""
                if sym.endswith("USDT"):
                    held.add(sym[:-4].upper())
        except Exception:
            continue
    return held


async def monitor_round(r: aioredis.Redis, cli: httpx.AsyncClient, notify: Notifier) -> dict:
    now = int(time.time())
    caps = await _binance_capital(cli)
    if caps is None:
        return {"status": "capital_query_failed"}
    held = await _held_assets(r)
    events = held_alerts = 0
    pipe = r.pipeline()
    for asset, st in caps.items():
        pipe.hset(KEY_STATUS, asset, json.dumps({"dep": st["dep"], "wd": st["wd"], "ts": now}))
    await pipe.execute()
    await r.expire(KEY_STATUS, INTERVAL * 4)

    for asset, st in caps.items():
        prev = _prev.get(asset)
        _prev[asset] = (st["dep"], st["wd"])
        if prev is None:
            continue
        for field, idx, label in (("dep", 0, "充值"), ("wd", 1, "提现")):
            was, now_v = prev[idx], st[field]
            if was == now_v:
                continue
            direction = "off" if (was and not now_v) else "on"
            cdk = f"{asset}:{field}:{direction}"
            if now - _evt_cooldown.get(cdk, 0) < EVENT_COOLDOWN:
                continue
            _evt_cooldown[cdk] = now
            ev = {"asset": asset, "field": field, "direction": direction, "ts": now}
            await r.lpush(KEY_EVENTS, json.dumps(ev, ensure_ascii=False))
            events += 1
            # 持仓币提现被停 = 下架/交割/脱锚前兆 → fatal;其余转变 = warn
            if asset in held and field == "wd" and direction == "off":
                held_alerts += 1
                await asyncio.to_thread(
                    notify.fire, f"held-wd-off:{asset}", f"⚠️持仓币提现暂停 {asset}",
                    f"{asset}(在场持仓)币安提现已关闭——下架/交割/脱锚前兆,立即人工核持仓去留", level="fatal")
            elif direction == "off":
                await asyncio.to_thread(
                    notify.fire, f"{field}-off:{asset}", f"币安{label}暂停 {asset}",
                    f"{asset} 币安{label}关闭(非持仓)——风险信号,观察", level="warn")
    await r.ltrim(KEY_EVENTS, 0, 199)
    return {"coins": len(caps), "held": len(held), "events": events, "held_alerts": held_alerts}


async def main():
    r = aioredis.from_url(REDIS_URL, decode_responses=True)
    notify = Notifier(REDIS_URL, SERVICE, feishu=feishu_from_env())
    hb = Heartbeat(REDIS_URL, SERVICE, interval_sec=60, ttl_sec=max(INTERVAL * 3, 900))
    asyncio.create_task(hb.run_forever())
    log.info(f"transfer-monitor up interval={INTERVAL}s")
    async with httpx.AsyncClient(timeout=20) as cli:
        while True:
            try:
                stats = await monitor_round(r, cli, notify)
                hb.extra = stats
                log.info(f"TRANSFER_OK {stats}")
            except Exception:
                log.exception("transfer-monitor round crashed (continuing)")
            await asyncio.sleep(INTERVAL)


if __name__ == "__main__":
    asyncio.run(main())
