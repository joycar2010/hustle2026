"""对冲腿强平(stop-out)检测 + 单腿告警 — 只读监控, 绝不自动下单。

检测在跑用户的 MT5 对冲账号是否被券商强平(成交 comment 含 "[so")，
若有新强平 → 算币安主腿裸露敞口 → publish Redis ws:user_event(type=hedge_stopout)
→ 前端大红阻断弹框。收口由用户在弹框点按钮触发(另见 POST /api/v1/hedge/closeout)。
仅针对强平; 其它单腿情况不在此功能内。
"""
import asyncio
import json
import logging
import os
import time

import httpx

logger = logging.getLogger(__name__)

_SEEN_PREFIX = "hedge_stopout_seen:"
_SEEN_TTL = 7 * 86400
_BRIDGE_HOST = os.getenv("MT5_BRIDGE_HOST", "http://172.31.14.113")
_API_KEY = os.getenv("MT5_API_KEY", os.getenv("MT5_BRIDGE_API_KEY", ""))


async def _rc():
    from app.core.redis_client import redis_client
    return redis_client


async def _running_user_ids(rc):
    raw = getattr(rc, "client", None)
    out = set()
    if raw is None:
        return out
    try:
        async for key in raw.scan_iter(match="strategy_active:*"):
            k = key.decode() if isinstance(key, (bytes, bytearray)) else key
            parts = k.split(":")
            if len(parts) >= 2 and parts[1]:
                out.add(parts[1])
    except Exception as e:
        logger.error("[HedgeStopout] scan running users failed: " + str(e))
    return out


async def _user_mt5_accounts(db, user_id):
    from app.models.account import Account
    from sqlalchemy import select, and_
    from uuid import UUID
    try:
        return (await db.execute(select(Account).where(and_(
            Account.user_id == UUID(user_id), Account.is_mt5_account == True, Account.is_active == True
        )))).scalars().all()
    except Exception:
        return []


async def _account_bridge_ports(db, account_id):
    from app.models.mt5_client import MT5Client
    from sqlalchemy import select, and_
    try:
        rows = (await db.execute(select(MT5Client.bridge_service_port).where(and_(
            MT5Client.account_id == account_id, MT5Client.is_active == True,
            MT5Client.is_system_service == False, MT5Client.bridge_service_port.isnot(None)
        )).order_by(MT5Client.priority))).fetchall()
        return [r[0] for r in rows]
    except Exception:
        return []


async def _pair_for_mt5_account(db, user_id, account_id):
    from sqlalchemy import text
    try:
        r = (await db.execute(text(
            "SELECT pair_code FROM user_pair_accounts WHERE user_id::text=:u AND account_b_id::text=:a LIMIT 1"
        ), {"u": str(user_id), "a": str(account_id)})).first()
        return r[0] if r else None
    except Exception:
        return None


def _binance_naked(user_id, binance_symbol):
    try:
        from app.tasks.broadcast_tasks import position_streamer as ps
        bn = ps._binance_positions.get(user_id) or ps._binance_positions.get("_default", {})
        lng, sht = bn.get(binance_symbol, (0.0, 0.0))
        if lng and float(lng) > 1e-6:
            return ("long", round(float(lng), 4))
        if sht and float(sht) > 1e-6:
            return ("short", round(float(sht), 4))
    except Exception:
        pass
    return ("", 0.0)


async def _publish_alert(rc, uid, pair_code, account_name, so_volume, naked_side, naked_qty, so_comment):
    title = "⚠️ 对冲腿被强平 — 单腿风险!"
    side_cn = "多" if naked_side == "long" else ("空" if naked_side == "short" else naked_side)
    content = (
        "对冲账号【" + str(account_name) + "】(" + str(pair_code) + ") 因保证金不足被券商强平 "
        + str(so_volume) + " 手。\n币安主腿裸露: " + side_cn + " " + str(naked_qty) + " XAU。\n"
        "请核对后在弹框选择【确认收口】(币安 maker 平裸腿)或【取消】另时手动处理。\n强平标记: " + str(so_comment)
    )
    evt = {
        "user_id": str(uid),
        "type": "hedge_stopout",
        "data": {
            "pair_code": pair_code, "account_name": account_name, "so_volume": so_volume,
            "naked_side": naked_side, "naked_qty": naked_qty, "so_comment": so_comment,
            "ts": int(time.time() * 1000),
            "popup_config": {"title": title, "content": content,
                             "sound_file": "/sounds/hello-moto.mp3", "sound_repeat": 5},
        },
    }
    try:
        await rc.publish("ws:user_event", json.dumps(evt, ensure_ascii=False))
        logger.warning("[HedgeStopout] ALERT user=" + str(uid) + " acct=" + str(account_name)
                       + " so_vol=" + str(so_volume) + " naked=" + str(naked_side) + str(naked_qty))
    except Exception as e:
        logger.error("[HedgeStopout] publish failed: " + str(e))


async def _scan_once():
    rc = await _rc()
    raw = getattr(rc, "client", None)
    users = await _running_user_ids(rc)
    if not users:
        return
    from app.core.database import AsyncSessionLocal
    headers = {"X-Api-Key": _API_KEY} if _API_KEY else {}
    async with AsyncSessionLocal() as db:
        from app.services.hedging_pair_service import hedging_pair_service
        for uid in users:
            for a in await _user_mt5_accounts(db, uid):
                ports = await _account_bridge_ports(db, a.account_id)
                if not ports:
                    continue
                new_so_vol = 0.0
                so_comment = ""
                for port in ports:
                    try:
                        async with httpx.AsyncClient(timeout=12) as c:
                            r = await c.get(_BRIDGE_HOST + ":" + str(port) + "/mt5/history/deals",
                                            headers=headers, params={"days": 1})
                            r.raise_for_status()
                            deals = r.json().get("deals", [])
                    except Exception:
                        continue
                    for d in deals:
                        cm = str(d.get("comment", "") or "")
                        if "[so" not in cm.lower():
                            continue
                        tk = d.get("ticket")
                        if not tk:
                            continue
                        seen_key = _SEEN_PREFIX + str(tk)
                        try:
                            if raw is not None and await raw.exists(seen_key):
                                continue
                            if raw is not None:
                                await raw.set(seen_key, "1", ex=_SEEN_TTL)
                        except Exception:
                            pass
                        new_so_vol += float(d.get("volume", 0) or 0)
                        so_comment = cm
                if new_so_vol <= 1e-9:
                    continue
                pair_code = await _pair_for_mt5_account(db, uid, a.account_id) or "XAU"
                try:
                    pair = hedging_pair_service.get_pair(pair_code)
                    binance_symbol = pair.symbol_a.symbol if pair else "XAUUSDT"
                except Exception:
                    binance_symbol = "XAUUSDT"
                naked_side, naked_qty = _binance_naked(uid, binance_symbol)
                await _publish_alert(rc, uid, pair_code, a.account_name, round(new_so_vol, 2),
                                     naked_side, naked_qty, so_comment)


class HedgeStopoutMonitor:
    def __init__(self):
        self.running = False
        self.task = None
        self.interval = 20

    async def start(self):
        if self.running:
            return
        self.running = True
        self.task = asyncio.create_task(self._loop())
        logger.info("[HedgeStopoutMonitor] started (interval=20s)")

    async def stop(self):
        self.running = False
        if self.task:
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass

    async def _loop(self):
        while self.running:
            try:
                await _scan_once()
            except Exception as e:
                logger.error("[HedgeStopoutMonitor] loop error: " + str(e))
            await asyncio.sleep(self.interval)


hedge_stopout_monitor = HedgeStopoutMonitor()
