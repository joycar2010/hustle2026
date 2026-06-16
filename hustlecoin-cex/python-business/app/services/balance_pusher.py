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
        self._max_borrow_tick = 0
        self._max_borrow_cache: dict[int, dict[str, float]] = {}  # account_id -> {asset: amount}
        self._no_inventory: dict[str, bool] = {}  # asset -> True 表示币安杠杆池无可借库存(-3045)
        self._interest_rate_cache: dict[str, float] = {}  # asset -> daily_interest_rate (global)

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

    async def _btc_price(self) -> float:
        """Read BTCUSDT futures bid from the Redis spreads hash to convert
        margin equity (denominated in BTC by Binance) into USDT."""
        try:
            raw = await self._redis.hget("spreads", "BTCUSDT")
            if raw:
                parsed = json.loads(raw)
                return float(parsed.get("fut_bid") or parsed.get("spot_bid") or 0)
        except Exception:
            pass
        return 0.0

    async def _pushed_assets(self, user_id: int) -> set[str]:
        """Base assets the user is actively monitoring (pushed list), so the
        dashboard shows 现币/借币/最大可借 for monitored coins, not only positioned ones."""
        try:
            raw = await self._redis.get(f"engine:{user_id}:pushed_symbols")
            if raw:
                return {s.replace("USDT", "") for s in json.loads(raw)}
        except Exception:
            pass
        return set()

    async def _fetch_and_push(self):
        self._max_borrow_tick += 1
        fetch_max_borrow = self._max_borrow_tick % 6 == 0
        btc_price = await self._btc_price()
        # Cap maxBorrowable calls per account per cycle to protect the SAPI weight budget.
        MAX_BORROW_PER_CYCLE = 40

        db = SessionLocal()
        try:
            accounts = db.query(SubAccount).filter(SubAccount.is_enabled == True).all()
            if not accounts:
                return

            from engine.trading.binance_trading import BinanceTradingClient
            from engine.models import Position

            # Per-user pushed assets, then per-account target = positioned ∪ pushed.
            pushed_by_user: dict[int, set[str]] = {}
            target_assets: dict[int, set[str]] = {}
            for acc in accounts:
                uid = acc.user_id or 0
                if uid not in pushed_by_user:
                    pushed_by_user[uid] = await self._pushed_assets(uid)
                positions = db.query(Position.symbol).filter(
                    Position.sub_account_id == acc.id, Position.status == "OPEN",
                ).all()
                positioned = {p.symbol.replace("USDT", "") for p in positions}
                target_assets[acc.id] = positioned | pushed_by_user[uid]

            interest_fetched: set[str] = set()

            user_balances: dict[int, list] = {}
            for acc in accounts:
                try:
                    targets = target_assets.get(acc.id, set())
                    async with BinanceTradingClient(acc.api_key, acc.api_secret) as client:
                        margin, futures = await asyncio.gather(
                            client.get_margin_account(),
                            client.get_futures_account(),
                        )

                        if fetch_max_borrow and targets:
                            mb_results = dict(self._max_borrow_cache.get(acc.id, {}))
                            for asset in list(targets)[:MAX_BORROW_PER_CYCLE]:
                                try:
                                    amt = await client.get_max_borrowable(asset)
                                    mb_results[asset] = float(amt)
                                    self._no_inventory[asset] = False
                                except Exception as e:
                                    # -3045 = 币安杠杆池该币无可借库存(真实市场状态,非故障)→ 明确置 0 + 标记池空
                                    if "-3045" in str(e):
                                        mb_results[asset] = 0.0
                                        self._no_inventory[asset] = True
                                    else:
                                        mb_results[asset] = mb_results.get(asset, 0)
                                if asset not in interest_fetched:
                                    try:
                                        rate = await client.get_margin_interest_rate(asset)
                                        self._interest_rate_cache[asset] = float(rate)
                                    except Exception:
                                        pass
                                    interest_fetched.add(asset)
                            self._max_borrow_cache[acc.id] = mb_results

                    margin_free = "0"
                    margin_borrowed = "0"
                    bnb_free = "0"
                    bnb_interest = "0"
                    symbol_margin: dict[str, dict] = {}
                    for a in margin.get("userAssets", []):
                        asset_name = a["asset"]
                        if asset_name == "USDT":
                            margin_free = a.get("free", "0")
                            margin_borrowed = a.get("borrowed", "0")
                        elif asset_name == "BNB":
                            bnb_free = a.get("free", "0")
                            bnb_interest = a.get("interest", "0")
                        if asset_name in targets:
                            sym_key = f"{asset_name}USDT"
                            symbol_margin[sym_key] = {
                                "free": float(a.get("free", "0")),
                                "max_borrowable": self._max_borrow_cache.get(acc.id, {}).get(asset_name, 0),
                                "daily_interest_rate": self._interest_rate_cache.get(asset_name, 0),
                                "no_inventory": self._no_inventory.get(asset_name, False),
                            }

                    # Pushed-but-not-held assets aren't in userAssets — still surface
                    # 最大可借/日息 so monitored coins show data before any position.
                    for asset_name in targets:
                        sym_key = f"{asset_name}USDT"
                        if sym_key not in symbol_margin:
                            symbol_margin[sym_key] = {
                                "free": 0.0,
                                "max_borrowable": self._max_borrow_cache.get(acc.id, {}).get(asset_name, 0),
                                "daily_interest_rate": self._interest_rate_cache.get(asset_name, 0),
                                "no_inventory": self._no_inventory.get(asset_name, False),
                            }

                    spot_free = "0"
                    for a in margin.get("userAssets", []):
                        if a["asset"] == "USDT":
                            spot_free = a.get("free", "0")
                            break

                    # 保证金总权益 (USDT) = 杠杆账户净资产(BTC) × BTC价格
                    margin_net_btc = float(margin.get("totalNetAssetOfBtc", "0") or "0")
                    margin_net_usdt = margin_net_btc * btc_price if btc_price > 0 else 0.0

                    uid = acc.user_id or 0
                    user_balances.setdefault(uid, []).append({
                        "account_id": acc.id,
                        "note": acc.note or f"#{acc.id}",
                        "spot_usdt_free": float(spot_free),
                        "margin_usdt_free": float(margin_free),
                        "margin_usdt_borrowed": float(margin_borrowed),
                        "margin_net_usdt": margin_net_usdt,
                        "margin_level": float(margin.get("marginLevel", "0") or "0"),
                        "futures_total": float(futures.get("totalWalletBalance", "0")),
                        "futures_available": float(futures.get("availableBalance", "0")),
                        "futures_unrealized_pnl": float(futures.get("totalUnrealizedProfit", "0")),
                        "bnb_free": float(bnb_free),
                        "bnb_interest": float(bnb_interest),
                        "symbol_margin": symbol_margin,
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

            # P0: publish IP-wide used weight (this process makes frequent SAPI calls)
            try:
                from engine.metrics import global_weight_snapshot
                ws = global_weight_snapshot()
                if ws["weight_time"] > 0:
                    await self._redis.set("engine:weight:latest", json.dumps(ws), ex=90)
            except Exception:
                pass

        finally:
            db.close()


balance_pusher = BalancePusher()
