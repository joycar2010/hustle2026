import asyncio
import json
import logging

import jwt
import redis.asyncio as aioredis
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.config import settings

logger = logging.getLogger(__name__)
router = APIRouter()


class ConnectionManager:
    def __init__(self):
        self.active: list[tuple[WebSocket, int | None]] = []

    async def connect(self, ws: WebSocket, user_id: int | None = None):
        await ws.accept()
        self.active.append((ws, user_id))

    def disconnect(self, ws: WebSocket):
        self.active = [(w, u) for w, u in self.active if w is not ws]

    async def broadcast(self, message: dict):
        dead = []
        for ws, _uid in self.active:
            try:
                await ws.send_json(message)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(ws)


manager = ConnectionManager()


def _verify_token(token: str) -> dict | None:
    try:
        return jwt.decode(token, settings.jwt_secret, algorithms=["HS256"])
    except (jwt.ExpiredSignatureError, jwt.InvalidTokenError):
        return None


@router.websocket("/ws/stream")
async def websocket_stream(ws: WebSocket, token: str = ""):
    payload = _verify_token(token)
    if not payload:
        await ws.close(code=4001, reason="Invalid token")
        return

    ws_user_id = payload.get("user_id")
    await manager.connect(ws, ws_user_id)
    logger.info(f"WebSocket connected: user={payload.get('sub', '?')}, total={len(manager.active)}")

    redis_conn = None
    pubsub = None
    listener_task = None
    flush_task = None
    snapshot_task = None

    # 黑名单(本用户 ∪ 全局系统死币如 HOMEUSDT)∪ 无券币(engine:noinv:*)— WS 利差推送据此排除
    def _load_blacklist():
        from app.db.session import SessionLocal
        from app.db.models import Blacklist
        from sqlalchemy import or_
        syms = set()
        db = SessionLocal()
        try:
            q = db.query(Blacklist.symbol)
            if ws_user_id is not None:
                q = q.filter(or_(Blacklist.user_id == ws_user_id, Blacklist.user_id.is_(None)))
            else:
                q = q.filter(Blacklist.user_id.is_(None))
            syms = {s[0].upper() for s in q.all() if s[0]}
        except Exception:
            pass
        finally:
            db.close()
        # 注:不再把无券币(engine:noinv:*)并入黑名单 —— 否则 dashboard 用户主动推送、等借券的币
        # 开/平点差被挡空白。无券标志改为随每条 spread 附 no_inventory 字段下发,由前端各页自行处理
        # (SpreadsPage 点差榜过滤无券币避免虚高点差占榜;dashboard 正常显示)。
        return syms
    blacklist_syms = await asyncio.to_thread(_load_blacklist)

    # 无券币集(engine:noinv:*):不再用于排除,仅用于给 spread payload 打 no_inventory 标志。
    def _load_noinv():
        s = set()
        try:
            import redis as _r
            from app.config import settings as _s
            rc = _r.from_url(_s.redis_url, decode_responses=True)
            keys = rc.keys("engine:noinv:*")
            rc.close()
            s = {k.split("engine:noinv:", 1)[1].upper() for k in keys}
        except Exception:
            pass
        return s
    noinv_syms = await asyncio.to_thread(_load_noinv)

    # 在交易白名单 engine:universe(现货∩合约 status==TRADING 的 USDT 对,随上/退市动态刷新)。
    # 退市/单腿下架的币不在此集 → 监控不推送。连接时点取一次,连接后由前端 10s 整表刷新纠正。
    # None=集不可用(Redis 异常/空)→ 不启用白名单过滤,避免误清空。
    def _load_universe():
        try:
            import redis as _r
            from app.config import settings as _s
            rc = _r.from_url(_s.redis_url, decode_responses=True)
            raw = rc.get("engine:universe")
            rc.close()
            if not raw:
                return None
            syms = {s.upper() for s in json.loads(raw)}
            return syms or None
        except Exception:
            return None
    universe_syms = await asyncio.to_thread(_load_universe)

    def _excluded(sym: str) -> bool:
        u = sym.upper()
        return u in blacklist_syms or (universe_syms is not None and u not in universe_syms)

    def _tag_noinv(d: dict) -> dict:
        # 给一条 spread dict 附 no_inventory 标志(无券币),前端据此处理(榜单过滤/dashboard 仍显示)
        d["no_inventory"] = d.get("symbol") in noinv_syms
        return d

    try:
        # Send initial spread snapshot(排除黑名单/退市,但无券币照常推送并标 no_inventory)
        try:
            from app.services.spread_reader import spread_reader
            all_spreads = [s for s in spread_reader.get_all() if not _excluded(s.symbol)]
            await ws.send_json({
                "type": "spread_snapshot",
                "data": [_tag_noinv(json.loads(s.model_dump_json())) for s in all_spreads],
            })
        except Exception as e:
            logger.warning(f"Failed to send initial spread snapshot: {e}")
            await ws.send_json({"type": "spread_snapshot", "data": []})

        redis_conn = aioredis.from_url(settings.redis_url, decode_responses=True)

        # Send initial balance snapshot from cache (user-scoped)
        try:
            cached = await redis_conn.get(f"balance:latest:{ws_user_id}") if ws_user_id else None
            if cached:
                await ws.send_json({"type": "balance_update", "data": json.loads(cached)})
        except Exception as e:
            logger.warning(f"Failed to send initial balance snapshot: {e}")

        pubsub = redis_conn.pubsub()
        await pubsub.subscribe("spread:updates", "position:updates", "worker:status", "balance:updates", "notification:broadcast", "ban:updates", "symbol_status:updates", "account_restriction:updates", "market:updates", "pushed:updates")

        batch: dict[str, dict] = {}
        batch_lock = asyncio.Lock()

        async def flush_loop():
            while True:
                await asyncio.sleep(0.2)
                async with batch_lock:
                    if not batch:
                        continue
                    items = list(batch.values())
                    batch.clear()
                try:
                    await ws.send_json({"type": "spread_batch", "data": items})
                except Exception:
                    break

        async def redis_listener():
            async for msg in pubsub.listen():
                if msg["type"] != "message":
                    continue
                channel = msg["channel"]
                data_str = msg["data"]

                if channel == "spread:updates":
                    if _excluded(str(data_str)):
                        continue  # 黑名单/死币/退市(不在 universe)不推送;无券币不再排除(标 no_inventory)
                    raw = await redis_conn.hget("spreads", data_str)
                    if raw:
                        parsed = json.loads(raw)
                        parsed["no_inventory"] = str(data_str) in noinv_syms
                        async with batch_lock:
                            batch[data_str] = parsed

                elif channel == "position:updates":
                    try:
                        parsed = json.loads(data_str)
                        if ws_user_id and parsed.get("user_id") != ws_user_id:
                            continue
                        await ws.send_json({"type": "position_update", "data": parsed})
                    except Exception:
                        pass

                elif channel == "worker:status":
                    try:
                        parsed = json.loads(data_str)
                        if ws_user_id and parsed.get("user_id") not in (None, ws_user_id):
                            continue
                        await ws.send_json({"type": "worker_status", "data": parsed})
                    except Exception:
                        pass

                elif channel == "balance:updates":
                    try:
                        parsed = json.loads(data_str)
                        if ws_user_id and parsed.get("user_id") != ws_user_id:
                            continue
                        await ws.send_json({"type": "balance_update", "data": parsed})
                    except Exception:
                        pass

                elif channel == "ban:updates":
                    try:
                        parsed = json.loads(data_str)
                        if ws_user_id and parsed.get("user_id") != ws_user_id:
                            continue
                        await ws.send_json({"type": "ban_update", "data": parsed})
                    except Exception:
                        pass

                elif channel == "symbol_status:updates":
                    try:
                        parsed = json.loads(data_str)
                        if ws_user_id and parsed.get("user_id") != ws_user_id:
                            continue
                        await ws.send_json({"type": "symbol_status", "data": parsed})
                    except Exception:
                        pass

                elif channel == "account_restriction:updates":
                    try:
                        parsed = json.loads(data_str)
                        if ws_user_id and parsed.get("user_id") != ws_user_id:
                            continue
                        await ws.send_json({"type": "account_restriction", "data": parsed})
                    except Exception:
                        pass

                elif channel == "market:updates":
                    try:
                        parsed = json.loads(data_str)
                        await ws.send_json({"type": "market_data", "data": parsed})
                    except Exception:
                        pass

                elif channel == "pushed:updates":
                    try:
                        parsed = json.loads(data_str)
                        if ws_user_id and parsed.get("user_id") != ws_user_id:
                            continue
                        await ws.send_json({"type": "pushed_update", "data": parsed})
                    except Exception:
                        pass

                elif channel == "notification:broadcast":
                    try:
                        parsed = json.loads(data_str)
                        await ws.send_json({"type": "notification", "data": parsed})
                    except Exception:
                        pass

        async def snapshot_loop():
            # 定期重发全量 spread_snapshot(整表替换):前端增量(spread_batch)改为合并 upsert 后,
            # 退市/停发的死币不再被增量冲掉,靠此周期全量快照纠正;同时补齐任何因增量时序遗漏的币。
            while True:
                await asyncio.sleep(30)
                try:
                    from app.services.spread_reader import spread_reader as _sr
                    snap = [s for s in _sr.get_all() if not _excluded(s.symbol)]
                    await ws.send_json({
                        "type": "spread_snapshot",
                        "data": [_tag_noinv(json.loads(s.model_dump_json())) for s in snap],
                    })
                except Exception:
                    break

        listener_task = asyncio.create_task(redis_listener())
        flush_task = asyncio.create_task(flush_loop())
        snapshot_task = asyncio.create_task(snapshot_loop())

        while True:
            text = await ws.receive_text()
            try:
                msg = json.loads(text)
                if msg.get("type") == "ping":
                    await ws.send_json({"type": "pong"})
            except json.JSONDecodeError:
                pass

    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.warning(f"WebSocket error: {e}")
    finally:
        if listener_task:
            listener_task.cancel()
        if flush_task:
            flush_task.cancel()
        if snapshot_task:
            snapshot_task.cancel()
        if pubsub:
            try:
                await pubsub.unsubscribe()
                await pubsub.aclose()
            except Exception:
                pass
        if redis_conn:
            try:
                await redis_conn.aclose()
            except Exception:
                pass
        manager.disconnect(ws)
        logger.info(f"WebSocket disconnected, remaining={len(manager.active)}")
