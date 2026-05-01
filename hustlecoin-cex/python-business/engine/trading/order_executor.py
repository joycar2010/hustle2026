import asyncio
import logging
import time
from datetime import datetime, timezone
from decimal import Decimal

from app.db.session import SessionLocal
from engine.models import Position, TradeLog
from engine.config_loader import GlobalRulesSnapshot
from engine.spread_feed import SpreadSnapshot
from engine.trading.binance_trading import BinanceTradingClient, BinanceAPIError
from engine.trading.quantity_calc import usdt_to_quantity
from engine.notify.feishu_sender import FeishuSender

logger = logging.getLogger(__name__)


def _log_trade(db, position_id: int, sub_account_id: int, action: str, symbol: str,
               side: str = None, quantity: Decimal = None, price: Decimal = None,
               order_id: str = None, status: str = "SUCCESS", error: str = None, latency: int = None):
    db.add(TradeLog(
        position_id=position_id,
        sub_account_id=sub_account_id,
        action=action,
        symbol=symbol,
        side=side,
        quantity=quantity,
        price=price,
        order_id=order_id,
        status=status,
        error_message=error,
        latency_ms=latency,
    ))
    db.commit()


async def execute_open(
    sub_account_id: int,
    symbol: str,
    spread: SpreadSnapshot,
    rules: GlobalRulesSnapshot,
    client: BinanceTradingClient,
    notifier: FeishuSender,
    account_note: str,
):
    base_asset = symbol.replace("USDT", "")
    db = SessionLocal()
    position = Position(
        sub_account_id=sub_account_id,
        symbol=symbol,
        base_asset=base_asset,
        status="PENDING_BORROW",
    )
    db.add(position)
    db.commit()
    db.refresh(position)
    pos_id = position.id

    try:
        # check interest rate
        t0 = time.monotonic()
        interest_rate = await client.get_margin_interest_rate(base_asset)
        latency = int((time.monotonic() - t0) * 1000)
        if interest_rate > rules.interest_filter / 100:
            position.status = "FAILED"
            position.error_message = f"Interest rate {interest_rate} too high"
            db.commit()
            db.close()
            return
        position.borrow_interest_rate = interest_rate

        # delay + re-confirm
        await asyncio.sleep(rules.borrow_delay_sec)

        # calculate quantity
        lot_info = await client.get_lot_size(symbol, "spot")
        qty = usdt_to_quantity(rules.order_amount, spread.spot_ask, lot_info["stepSize"], lot_info["minQty"])
        if qty <= 0:
            position.status = "FAILED"
            position.error_message = "Order amount too small for lot size"
            db.commit()
            db.close()
            return

        # Step 1: borrow
        t0 = time.monotonic()
        await client.margin_borrow(base_asset, qty)
        latency = int((time.monotonic() - t0) * 1000)
        position.status = "BORROWED"
        position.borrow_qty = qty
        db.commit()
        _log_trade(db, pos_id, sub_account_id, "BORROW", symbol, quantity=qty, status="SUCCESS", latency=latency)

        # Step 2: spot sell
        t0 = time.monotonic()
        sell_result = await client.spot_market_sell(symbol, qty)
        latency = int((time.monotonic() - t0) * 1000)
        position.status = "SPOT_SOLD"
        position.spot_sell_qty = Decimal(str(sell_result["executedQty"]))
        position.spot_sell_price = _avg_fill_price(sell_result)
        position.spot_sell_order_id = str(sell_result["orderId"])
        db.commit()
        _log_trade(db, pos_id, sub_account_id, "SPOT_SELL", symbol, "SELL",
                    position.spot_sell_qty, position.spot_sell_price,
                    position.spot_sell_order_id, "SUCCESS", latency=latency)

        # Step 3: futures long
        futures_lot = await client.get_lot_size(symbol, "futures")
        from engine.trading.quantity_calc import round_to_step
        futures_qty = round_to_step(qty, futures_lot["stepSize"])

        t0 = time.monotonic()
        long_result = await client.futures_market_long(symbol, futures_qty)
        latency = int((time.monotonic() - t0) * 1000)
        position.status = "OPEN"
        position.futures_long_qty = Decimal(str(long_result["executedQty"]))
        position.futures_long_price = Decimal(str(long_result.get("avgPrice", "0")))
        position.futures_long_order_id = str(long_result["orderId"])
        position.open_spread = spread.spread_short
        position.open_usdt_amount = position.spot_sell_qty * position.spot_sell_price
        position.opened_at = datetime.now(timezone.utc)
        db.commit()
        _log_trade(db, pos_id, sub_account_id, "FUTURES_LONG", symbol, "BUY",
                    position.futures_long_qty, position.futures_long_price,
                    position.futures_long_order_id, "SUCCESS", latency=latency)

        logger.info(f"Position opened: {symbol} qty={qty} spread={spread.spread_short}%")
        await notifier.notify_position_opened(
            account_note, symbol, spread.spread_short, qty, position.open_usdt_amount,
        )

    except BinanceAPIError as e:
        logger.error(f"Open failed at {position.status}: {e}")
        await _handle_open_failure(db, position, client, e, sub_account_id, symbol, notifier, account_note)
    except Exception as e:
        logger.error(f"Open failed unexpectedly: {e}", exc_info=True)
        position.status = "FAILED"
        position.error_message = str(e)
        db.commit()
        await notifier.notify_error(account_note, f"open {symbol}", str(e))
    finally:
        db.close()


async def _handle_open_failure(db, position, client, error, sub_account_id, symbol, notifier, account_note):
    current = position.status

    if current == "BORROWED":
        # spot sell failed — repay borrow
        try:
            await client.margin_repay(position.base_asset, position.borrow_qty)
            _log_trade(db, position.id, sub_account_id, "ROLLBACK_REPAY", symbol,
                        quantity=position.borrow_qty, status="SUCCESS")
        except Exception as re:
            _log_trade(db, position.id, sub_account_id, "ROLLBACK_REPAY", symbol,
                        status="FAILED", error=str(re))
        position.status = "FAILED"
        position.error_message = f"Spot sell failed: {error}. Borrow rolled back."
        db.commit()

    elif current == "SPOT_SOLD":
        # futures long failed — buy back spot + repay
        try:
            await client.spot_market_buy_qty(symbol, position.borrow_qty)
            _log_trade(db, position.id, sub_account_id, "ROLLBACK_SPOT_BUY", symbol,
                        "BUY", position.borrow_qty, status="SUCCESS")
        except Exception as re:
            _log_trade(db, position.id, sub_account_id, "ROLLBACK_SPOT_BUY", symbol,
                        status="FAILED", error=str(re))
        try:
            await client.margin_repay(position.base_asset, position.borrow_qty)
            _log_trade(db, position.id, sub_account_id, "ROLLBACK_REPAY", symbol,
                        quantity=position.borrow_qty, status="SUCCESS")
        except Exception as re:
            _log_trade(db, position.id, sub_account_id, "ROLLBACK_REPAY", symbol,
                        status="FAILED", error=str(re))
        position.status = "FAILED"
        position.error_message = f"Futures long failed: {error}. Rolled back."
        db.commit()

    else:
        position.status = "FAILED"
        position.error_message = str(error)
        db.commit()

    _log_trade(db, position.id, sub_account_id, position.status, symbol,
                status="FAILED", error=str(error))
    await notifier.notify_error(account_note, f"open {symbol} (rollback from {current})", str(error))


async def execute_close(
    position: Position,
    spread: SpreadSnapshot,
    client: BinanceTradingClient,
    notifier: FeishuSender,
    account_note: str,
):
    db = SessionLocal()
    pos = db.query(Position).get(position.id)
    if not pos or pos.status != "OPEN":
        db.close()
        return

    try:
        # Step 1: close futures
        pos.status = "CLOSING_FUTURES"
        db.commit()
        t0 = time.monotonic()
        close_result = await client.futures_market_close(pos.symbol, pos.futures_long_qty)
        latency = int((time.monotonic() - t0) * 1000)
        pos.futures_close_price = Decimal(str(close_result.get("avgPrice", "0")))
        pos.futures_close_order_id = str(close_result["orderId"])
        pos.status = "FUTURES_CLOSED"
        db.commit()
        _log_trade(db, pos.id, pos.sub_account_id, "FUTURES_CLOSE", pos.symbol, "SELL",
                    pos.futures_long_qty, pos.futures_close_price,
                    pos.futures_close_order_id, "SUCCESS", latency=latency)

        # Step 2: spot buy
        pos.status = "CLOSING_SPOT"
        db.commit()
        t0 = time.monotonic()
        buy_result = await client.spot_market_buy_qty(pos.symbol, pos.borrow_qty)
        latency = int((time.monotonic() - t0) * 1000)
        pos.spot_buy_qty = Decimal(str(buy_result["executedQty"]))
        pos.spot_buy_price = _avg_fill_price(buy_result)
        pos.spot_buy_order_id = str(buy_result["orderId"])
        pos.status = "SPOT_BOUGHT"
        db.commit()
        _log_trade(db, pos.id, pos.sub_account_id, "SPOT_BUY", pos.symbol, "BUY",
                    pos.spot_buy_qty, pos.spot_buy_price,
                    pos.spot_buy_order_id, "SUCCESS", latency=latency)

        # Step 3: repay
        pos.status = "REPAYING"
        db.commit()
        t0 = time.monotonic()
        await client.margin_repay(pos.base_asset, pos.borrow_qty)
        latency = int((time.monotonic() - t0) * 1000)
        pos.repay_qty = pos.borrow_qty
        _log_trade(db, pos.id, pos.sub_account_id, "REPAY", pos.symbol,
                    quantity=pos.borrow_qty, status="SUCCESS", latency=latency)

        # Calculate PnL
        spot_pnl = (pos.spot_sell_qty * pos.spot_sell_price) - (pos.spot_buy_qty * pos.spot_buy_price)
        futures_pnl = (pos.futures_close_price - pos.futures_long_price) * pos.futures_long_qty
        pos.realized_pnl = spot_pnl + futures_pnl
        pos.close_spread = spread.spread_short
        pos.closed_at = datetime.now(timezone.utc)
        pos.status = "CLOSED"
        db.commit()

        logger.info(f"Position closed: {pos.symbol} pnl={pos.realized_pnl}")
        await notifier.notify_position_closed(account_note, pos.symbol, pos.realized_pnl, spread.spread_short)

    except BinanceAPIError as e:
        logger.error(f"Close failed at {pos.status}: {e}")
        pos.error_message = str(e)
        pos.retry_count += 1
        db.commit()
        _log_trade(db, pos.id, pos.sub_account_id, "CLOSE_ERROR", pos.symbol,
                    status="FAILED", error=str(e))
        await notifier.notify_error(account_note, f"close {pos.symbol}", str(e))
    except Exception as e:
        logger.error(f"Close failed unexpectedly: {e}", exc_info=True)
        pos.error_message = str(e)
        db.commit()
        await notifier.notify_error(account_note, f"close {pos.symbol}", str(e))
    finally:
        db.close()


def _avg_fill_price(order_result: dict) -> Decimal:
    fills = order_result.get("fills", [])
    if not fills:
        return Decimal(str(order_result.get("price", "0")))
    total_qty = sum(Decimal(f["qty"]) for f in fills)
    if total_qty == 0:
        return Decimal("0")
    weighted = sum(Decimal(f["price"]) * Decimal(f["qty"]) for f in fills)
    return weighted / total_qty
