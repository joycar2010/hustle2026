import asyncio
import json
import logging
from typing import Optional

import redis.asyncio as aioredis

from app.config import settings
from app.db.session import SessionLocal
from app.db.models import SubAccount

logger = logging.getLogger(__name__)

BALANCE_INTERVAL = 10  # seconds


class BalancePusher:
    def __init__(self):
        self._redis: Optional[aioredis.Redis] = None
        self._running = False

    async def start(self):
        self._redis = aioredis.from_url(settings.redis_url, decode_responses=True)
        self._running = True
        asyncio.create_task(self._loop())
        logger.info("BalancePusher started")

    async def stop(self):
        self._running = False

    async def _loop(self):
        while self._running:
            try:
                await self._fetch_and_push()
            except Exception as e:
                logger.warning(f"BalancePusher error: {e}")
            await asyncio.sleep(BALANCE_INTERVAL)

    async def _fetch_and_push(self):
        db = SessionLocal()
        try:
            accounts = db.query(SubAccount).filter(SubAccount.is_enabled == True).all()
            if not accounts:
                return

            from engine.trading.binance_trading import BinanceTradingClient
            from engine.models import Position

            user_balances: dict[int, list] = {}
            for acc in accounts:
                try:
                    async with BinanceTradingClient(acc.api_key, acc.api_secret) as client:
                        margin, futures = await asyncio.gather(
                            client.get_margin_account(),
                            client.get_futures_account(),
                        )

                    margin_free = "0"
                    margin_borrowed = "0"
                    bnb_free = "0"
                    bnb_interest = "0"
                    for a in margin.get("userAssets", []):
                        if a["asset"] == "USDT":
                            margin_free = a.get("free", "0")
                            margin_borrowed = a.get("borrowed", "0")
                        elif a["asset"] == "BNB":
                            bnb_free = a.get("free", "0")
                            bnb_interest = a.get("interest", "0")

                    spot_free = "0"
                    for a in margin.get("userAssets", []):
                        if a["asset"] == "USDT":
                            spot_free = a.get("free", "0")
                            break

                    uid = acc.user_id or 0
                    user_balances.setdefault(uid, []).append({
                        "account_id": acc.id,
                        "note": acc.note or f"#{acc.id}",
                        "spot_usdt_free": float(spot_free),
                        "margin_usdt_free": float(margin_free),
                        "margin_usdt_borrowed": float(margin_borrowed),
                        "margin_level": float(margin.get("marginLevel", "0") or "0"),
                        "futures_total": float(futures.get("totalWalletBalance", "0")),
                        "futures_available": float(futures.get("availableBalance", "0")),
                        "futures_unrealized_pnl": float(futures.get("totalUnrealizedProfit", "0")),
                        "bnb_free": float(bnb_free),
                        "bnb_interest": float(bnb_interest),
                    })
                except Exception as e:
                    logger.debug(f"Balance fetch failed for account {acc.id}: {e}")

            for uid, balances in user_balances.items():
                position_count = db.query(Position).filter(
                    Position.status == "OPEN", Position.user_id == uid,
                ).count()
                total_contracts = db.query(Position).filter(
                    Position.user_id == uid,
                ).count()

                payload = {
                    "user_id": uid,
                    "balances": balances,
                    "position_count": position_count,
                    "total_contracts": total_contracts,
                }

                await self._redis.publish("balance:updates", json.dumps(payload))
                await self._redis.set(f"balance:latest:{uid}", json.dumps(payload), ex=30)

        finally:
            db.close()


balance_pusher = BalancePusher()
