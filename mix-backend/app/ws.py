"""
P1：内嵌 WS fanout（/ws/stream?token=）。操作员就几个连接，不上独立 hub——
协议不变，将来量级上来只换实现。
频道：
  - marquee            ← Redis PUBLISH dcm:notify:broadcast（dcm 全服务跑马灯）
  - route:updates      ← Redis PUBLISH dcm:route:updates（路由热变更）
  - position:updates   ← 10s 轮询坑位行摘要，变更才推（前端收到即刷新对账）
  - hb                 ← 20s 应用层心跳（客户端看门狗：>60s 静默即重连——半开假死课）
"""
import json
import time
import asyncio
import logging

from fastapi import WebSocket, WebSocketDisconnect

from . import adapters
from . import datasources as ds
from .deps import _resolve_any

log = logging.getLogger("mix.ws")

CHANNELS = ("dcm:notify:broadcast", "dcm:route:updates")
CHANNEL_ALIAS = {"dcm:notify:broadcast": "marquee", "dcm:route:updates": "route:updates"}
FRAMES_CHANNEL = "mix:ws:frames"  # mix-backend 预打包帧 → Rust hub 透传


async def position_frames_publisher():
    """常驻后台任务（API 进程@8200）：坑位全量行 → PUBLISH 预打包帧（1.5s 近实时）。
    Rust hub(mix-ws-hub@8201) 订阅 mix:ws:frames 毫秒级中继——前端直接用帧内 rows 换表,
    不再走 REST 回环（毫秒级坑位刷新;hub 不算业务,业务留单一来源）。
    读缓存 3s TTL 会拖慢刷新,故本任务绕缓存现算（_no_cache）。"""
    last_sig = None
    while True:
        try:
            r = ds.rds()
            if r is not None:
                ds._cache.clear()   # 绕 3s 读缓存,取最新行情/快照
                rows = await adapters.position_rows(None)
                # 变更签名：任何价/费/pnl/相位变动即推（价格几乎每帧变=近实时推）
                sig = json.dumps([[x["id"], x.get("pnl"), x.get("fundingRateRatio"),
                                   [(sr.get("venue"), sr.get("fundingRateRatio"),
                                     (sr.get("values") or [{}])[-1].get("value"))
                                    for sr in (x.get("subRows") or [])]]
                                  for x in rows], default=str, ensure_ascii=False)
                if sig != last_sig:
                    await r.publish(FRAMES_CHANNEL, json.dumps(
                        {"channel": "position:updates", "rows": rows,
                         "count": len(rows), "ts": int(time.time() * 1000)},
                        ensure_ascii=False, default=str))
                    last_sig = sig
        except Exception as e:  # noqa: BLE001
            log.warning("frames publisher: %s", e)
        await asyncio.sleep(1.5)


def _try_json(raw):
    try:
        return json.loads(raw)
    except Exception:  # noqa: BLE001
        return {"text": str(raw)}


async def ws_stream(ws: WebSocket, token: str = ""):
    who = await _resolve_any(token)
    if not who:
        await ws.close(code=4401)
        return
    await ws.accept()
    r = ds.rds()
    send_lock = asyncio.Lock()

    async def send(obj: dict):
        async with send_lock:
            await ws.send_text(json.dumps(obj, ensure_ascii=False, default=str))

    async def pubsub_task():
        if r is None:
            return
        pub = r.pubsub()
        try:
            await pub.subscribe(*CHANNELS)
            async for msg in pub.listen():
                if msg.get("type") != "message":
                    continue
                ch = msg.get("channel")
                await send({"channel": CHANNEL_ALIAS.get(ch, ch),
                            "data": _try_json(msg.get("data")), "ts": int(time.time())})
        finally:
            try:
                await pub.unsubscribe(*CHANNELS)
                await pub.aclose()
            except Exception:  # noqa: BLE001
                pass

    async def snapshot_task():
        last = None
        while True:
            try:
                rows = await adapters.position_rows(None)
                digest = [{"id": x["id"], "phase": x["phase"], "pnl": x.get("pnl")} for x in rows]
                if digest != last:
                    await send({"channel": "position:updates", "rows": digest,
                                "count": len(digest), "ts": int(time.time())})
                    last = digest
            except Exception as e:  # noqa: BLE001
                log.warning("ws snapshot: %s", e)
            await asyncio.sleep(10)

    async def hb_task():
        while True:
            await send({"channel": "hb", "ts": int(time.time())})
            await asyncio.sleep(20)

    tasks = [asyncio.create_task(t()) for t in (pubsub_task, snapshot_task, hb_task)]
    try:
        while True:
            await ws.receive_text()  # 客户端消息即活性；断开抛 WebSocketDisconnect
    except WebSocketDisconnect:
        pass
    except Exception as e:  # noqa: BLE001
        log.info("ws closed: %s", e)
    finally:
        for t in tasks:
            t.cancel()
