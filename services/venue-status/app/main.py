"""venue-status-ingest —— 交易所官方状态页进料(V5 遗留项,2026-07-25)。

此前平台健康全靠账户探针反推(账户失败→分类→降级),缺官方主动信源。本服务补进料口:
  binance : GET /sapi/v1/system/status               {"status":0正常|1维护}
  okx     : GET /api/v5/system/status?state=ongoing  进行中维护事件列表
  bybit   : GET api.bybit.com/v5/system/status       官方维护事件列表(state=ongoing判维护)
  gate    : api.gateio.ws /api/v4/spot/time          liveness 弱信号(可达=none,不可达=unknown)
  bitget  : api.bitget.com /api/v2/public/time       liveness 弱信号(同上)
  (bybit/gate/bitget 无 statuspage.io 标准页——2026-07-25 实测域名不存在)
输出:
  dcm:risk:venue_status:{venue} = {"ok","indicator","note","ts"}  (EX=轮距×3)
  dcm:risk:venue_status         = 聚合快照
  心跳 dcm:hb:venue-status
消费:risk-ledger policy.py 把 ongoing 维护/major+ 折成模式下压(独立输入维,与账户探针叠加取严)。
铁律:只读公开端点,零密钥零下单;单所抓取失败=unknown(不臆断不误伤,fail-open 由账户探针兜底)。
"""
import asyncio
import json
import os
import time

import httpx
import redis.asyncio as aioredis

REDIS_URL = os.environ.get("DCM_REDIS_URL", "redis://10.0.1.95:6379/0")
INTERVAL = int(os.environ.get("DCM_VENUE_STATUS_INTERVAL_SEC", "120"))

_LIVENESS = {
    "gate": "https://api.gateio.ws/api/v4/spot/time",
    "bitget": "https://api.bitget.com/api/v2/public/time",
}


async def _bybit(cli):
    """官方维护事件列表:result.list[] 有 ongoing 态即维护中。"""
    try:
        d = (await cli.get("https://api.bybit.com/v5/system/status")).json()
        evs = ((d.get("result") or {}).get("list")) or []
        ongoing = [e for e in evs
                   if str(e.get("state") or "").lower() in ("2", "ongoing", "processing")]
        if ongoing:
            titles = "; ".join(str(e.get("title") or "")[:40] for e in ongoing[:3])
            return {"ok": False, "indicator": "maintenance", "note": f"进行中维护:{titles}"[:120]}
        return {"ok": True, "indicator": "none", "note": ""}
    except Exception as e:  # noqa: BLE001
        return {"ok": None, "indicator": "unknown", "note": f"fetch_fail:{repr(e)[:60]}"}


async def _liveness(cli, venue):
    """API 可达性弱信号:可达=none(不证明无维护);不可达=unknown(不臆断,账户探针兜底)。"""
    try:
        resp = await cli.get(_LIVENESS[venue])
        if resp.status_code == 200:
            return {"ok": True, "indicator": "none", "note": "API可达(liveness弱信号)"}
        return {"ok": None, "indicator": "unknown", "note": f"http {resp.status_code}"}
    except Exception as e:  # noqa: BLE001
        return {"ok": None, "indicator": "unknown", "note": f"fetch_fail:{repr(e)[:60]}"}


async def _binance(cli):
    try:
        d = (await cli.get("https://api.binance.com/sapi/v1/system/status")).json()
        maint = int(d.get("status") or 0) == 1
        return {"ok": not maint, "indicator": "maintenance" if maint else "none",
                "note": str(d.get("msg") or "")[:120]}
    except Exception as e:  # noqa: BLE001
        return {"ok": None, "indicator": "unknown", "note": f"fetch_fail:{repr(e)[:60]}"}


async def _okx(cli):
    try:
        d = (await cli.get("https://www.okx.com/api/v5/system/status?state=ongoing")).json()
        ev = d.get("data") or []
        if ev:
            titles = "; ".join(str(e.get("title") or "")[:40] for e in ev[:3])
            return {"ok": False, "indicator": "maintenance", "note": f"进行中维护:{titles}"[:120]}
        return {"ok": True, "indicator": "none", "note": ""}
    except Exception as e:  # noqa: BLE001
        return {"ok": None, "indicator": "unknown", "note": f"fetch_fail:{repr(e)[:60]}"}


async def collect() -> dict:
    out = {}
    async with httpx.AsyncClient(timeout=15, follow_redirects=True) as cli:
        out["binance"] = await _binance(cli)
        out["okx"] = await _okx(cli)
        out["bybit"] = await _bybit(cli)
        for v in _LIVENESS:
            out[v] = await _liveness(cli, v)
    # hyperliquid 无标准状态页 API:不臆断,标 unknown(账户探针兜底)
    out["hyperliquid"] = {"ok": None, "indicator": "unknown", "note": "无官方状态页API"}
    ts = int(time.time())
    for v in out:
        out[v]["ts"] = ts
    return out


async def main():
    r = aioredis.from_url(REDIS_URL, decode_responses=True)
    print(f"venue-status-ingest up interval={INTERVAL}s venues=binance/okx/bybit/gate/bitget(+HL标unknown)")
    while True:
        try:
            snap = await collect()
            for v, d in snap.items():
                await r.set(f"dcm:risk:venue_status:{v}", json.dumps(d, ensure_ascii=False),
                            ex=INTERVAL * 3)
            await r.set("dcm:risk:venue_status", json.dumps({"ts": int(time.time()), "venues": snap},
                        ensure_ascii=False), ex=INTERVAL * 3)
            await r.set("dcm:hb:venue-status", json.dumps({"ts": int(time.time()), "pid": os.getpid(),
                        "service": "venue-status"}), ex=INTERVAL * 3)
            bad = {v: d["indicator"] for v, d in snap.items()
                   if d.get("ok") is False}
            print("venue-status:", "全绿" if not bad else f"异常{bad}")
        except Exception as e:  # noqa: BLE001
            print("venue-status err:", repr(e)[:150])
        await asyncio.sleep(INTERVAL)


if __name__ == "__main__":
    asyncio.run(main())
