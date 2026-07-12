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
    """常驻后台任务（API 进程@8200）：坑位摘要变更 → PUBLISH 预打包帧。
    Rust hub(mix-ws-hub@8201) 订阅 mix:ws:frames 纯中继——hub 不算业务，业务留在单一来源。"""
    last = None
    while True:
        try:
            r = ds.rds()
            if r is not None:
                rows = await adapters.position_rows(None)
                digest = [{"id": x["id"], "phase": x["phase"], "pnl": x.get("pnl")} for x in rows]
                if digest != last:
                    await r.publish(FRAMES_CHANNEL, json.dumps(
                        {"channel": "position:updates", "rows": digest,
                         "count": len(digest), "ts": int(time.time())},
                        ensure_ascii=False, default=str))
                    last = digest
        except Exception as e:  # noqa: BLE001
            log.warning("frames publisher: %s", e)
        await asyncio.sleep(10)


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
