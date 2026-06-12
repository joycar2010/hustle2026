import asyncio
import logging
import time
from datetime import datetime, timezone
from decimal import Decimal

from app.db.session import SessionLocal
from engine.models import Position, TradeLog
from engine.config_loader import GlobalRulesSnapshot
from engine.spread_feed import SpreadFeed, SpreadSnapshot
from engine.trading.binance_trading import BinanceTradingClient, BinanceAPIError
from engine.trading.quantity_calc import usdt_to_quantity, round_to_step
from engine.notify.feishu_sender import FeishuSender

logger = logging.getLogger(__name__)

TAKER_FEE_RATE = Decimal("0.00075")
FEE_BUFFER = Decimal("1.0015")


async def _get_asset_debt(client: BinanceTradingClient, asset: str) -> tuple[Decimal, Decimal]:
    margin_info = await client.get_margin_account()
    for a in margin_info.get("userAssets", []):
        if a["asset"] == asset:
            borrowed = Decimal(str(a.get("borrowed", "0")))
            interest = Decimal(str(a.get("interest", "0")))
            return borrowed + interest, interest
    return Decimal("0"), Decimal("0")


def _fc_symbol_lock(fc, symbol: str) -> asyncio.Lock:
    """Per-symbol lock attached to the futures client. hedge_via_master 下该 client 被
    全部 worker 共享 —— 同 symbol 的开/平在共享净仓上必须串行,避免 reduceOnly 拒单/过量平仓。
    (子账户自有 client 时各 worker 各一份锁表,无跨账户竞争,加锁无副作用。)"""
    locks = getattr(fc, "_symbol_locks", None)
    if locks is None:
        locks = {}
        fc._symbol_locks = locks
    return locks.setdefault(symbol, asyncio.Lock())


_precheck_warn_ts: dict[str, float] = {}


async def _master_margin_precheck(fc, symbol, qty, spread, notifier, account_note) -> Decimal | None:
    """hedge_via_master: 对冲前查主账户合约可用余额(按该 symbol 当前杠杆估算所需保证金,
    留 10% 缓冲)。带账户级预留(挂在共享 client 上的 in-flight 计数,锁内比较+占用),
    防止多 worker 并发用同一余额各自通过。通过返回预留额(调用方 finally 归还),
    不足或查询异常 → None,调用方把持仓留在 BORROWED_IDLE 等下轮 —— 绝不进入
    「卖出→合约失败→回滚」的空转(主账户欠资是全 worker 共模故障)。"""
    try:
        price = spread.fut_ask if (getattr(spread, "fut_ask", None) and spread.fut_ask > 0) else spread.spot_ask
        pr = await fc.futures_position_risk(symbol)
        lev = Decimal(str((pr or {}).get("leverage") or "20"))
        if lev <= 0:
            lev = Decimal("20")
        need = (qty * price / lev) * Decimal("1.1")

        rlock = getattr(fc, "_reserve_lock", None)
        if rlock is None:
            rlock = asyncio.Lock()
            fc._reserve_lock = rlock
        async with rlock:
            acct = await fc.get_futures_account()
            avail = Decimal(str(acct.get("availableBalance", "0")))
            reserved = getattr(fc, "_margin_reserved", Decimal("0"))
            if avail - reserved >= need:
                fc._margin_reserved = reserved + need
                return need
        now = time.monotonic()
        if now - _precheck_warn_ts.get(symbol, 0) > 300:
            _precheck_warn_ts[symbol] = now
            logger.warning(f"hedge_via_master: master avail insufficient for {symbol} (need≈{need:.4f}); hold BORROWED_IDLE")
            await notifier.notify_error(
                account_note, f"hedge {symbol}",
                f"主账户合约可用余额不足(需≈{need:.2f} USDT),持仓停在待对冲",
            )
        return None
    except Exception as e:
        logger.warning(f"hedge_via_master: precheck failed {symbol}: {e}; hold BORROWED_IDLE")
        return None


def _release_margin_reserve(fc, amount: Decimal):
    if fc is None or amount is None:
        return
    try:
        fc._margin_reserved = max(Decimal("0"), getattr(fc, "_margin_reserved", Decimal("0")) - amount)
    except Exception:
        pass


async def _query_filled_by_client_id(fc, symbol: str, coid: str) -> Decimal:
    """下单响应丢失(超时/5xx「状态未知」)后,按 clientOrderId 复核实际成交量。
    -2013(订单不存在)= 未送达 → 0;查询连续失败按 0 计但留告警日志。"""
    for _ in range(3):
        try:
            o = await fc.futures_get_order_by_client_id(symbol, coid)
            return Decimal(str(o.get("executedQty", "0")))
        except BinanceAPIError as e:
            if e.api_code == -2013:
                return Decimal("0")
        except Exception:
            pass
        await asyncio.sleep(0.5)
    logger.error(f"ambiguous futures order unresolved: {symbol} clientOrderId={coid} — verify manually")
    return Decimal("0")


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


async def execute_borrow(
    sub_account_id: int,
    symbol: str,
    spread: SpreadSnapshot,
    rules: GlobalRulesSnapshot,
    client: BinanceTradingClient,
    notifier: FeishuSender,
    account_note: str,
    spread_feed: SpreadFeed = None,
    min_spread: Decimal = None,
    user_id: int = None,
) -> int | None:
    """Phase 1: borrow the coin and hold it idle in the margin account (BORROWED_IDLE).
    Net-flat (owe coin, hold coin) — no directional exposure. Returns position id or None."""
    base_asset = symbol.replace("USDT", "")
    confirm_spread = rules.open_spread if min_spread is None else min_spread
    db = SessionLocal()
    position = Position(
        sub_account_id=sub_account_id,
        symbol=symbol,
        base_asset=base_asset,
        status="PENDING_BORROW",
        user_id=user_id,
    )
    db.add(position)
    db.commit()
    db.refresh(position)
    pos_id = position.id

    try:
        # interest-rate filter
        t0 = time.monotonic()
        interest_rate = await client.get_margin_interest_rate(base_asset)
        latency = int((time.monotonic() - t0) * 1000)
        if interest_rate > rules.interest_filter / 100:
            position.status = "FAILED"
            position.error_message = f"Interest rate {interest_rate} too high"
            db.commit()
            db.close()
            return None
        position.borrow_interest_rate = interest_rate

        # delay + re-confirm spread still above the borrow threshold
        await asyncio.sleep(rules.borrow_delay_sec)
        if spread_feed:
            current = spread_feed.get_symbol(symbol)
            if not current or current.spread_short <= confirm_spread:
                position.status = "FAILED"
                position.error_message = (
                    f"Spread degraded after delay: "
                    f"{current.spread_short if current else 'N/A'}% <= {confirm_spread}%"
                )
                db.commit()
                db.close()
                return None
            spread = current

        # quantity
        lot_info = await client.get_lot_size(symbol, "spot")
        price = spread.spot_ask
        from app.db.models import SymbolRule, AccountSymbolRule, SubAccount
        # 「金额限制」(借币金额上限,USDT)解析: 账户单币 → 单币通用 → 子账户全局
        cap_usdt = None
        asr = db.query(AccountSymbolRule).filter(
            AccountSymbolRule.sub_account_id == sub_account_id,
            AccountSymbolRule.symbol.in_([symbol, base_asset]),
        ).first()
        if asr and asr.max_borrow_amount is not None:
            cap_usdt = asr.max_borrow_amount
        if cap_usdt is None and user_id is not None:
            sr = db.query(SymbolRule).filter(
                SymbolRule.user_id == user_id, SymbolRule.symbol.in_([symbol, base_asset]),
            ).first()
            if sr and sr.max_borrow_amount is not None:
                cap_usdt = sr.max_borrow_amount
        if cap_usdt is None:
            sa = db.query(SubAccount).get(sub_account_id)
            if sa and sa.max_borrow_amount is not None:
                cap_usdt = sa.max_borrow_amount

        if getattr(rules, "borrow_via_otoco", False) and cap_usdt is not None and Decimal(str(cap_usdt)) > 0:
            # OTOCO 借币: 借满「金额限制」∩ maxBorrowable(币捏手上,后续按单笔分批对冲)
            try:
                max_borrowable = await client.get_max_borrowable(base_asset)
            except Exception:
                max_borrowable = Decimal("0")
            cap_qty = Decimal(str(cap_usdt)) / price if price > 0 else Decimal("0")
            target = min(cap_qty, max_borrowable) if max_borrowable > 0 else cap_qty
            qty = round_to_step(target, lot_info["stepSize"])
        else:
            # 单笔金额(order_amount): 单一规则覆盖 → 全局
            eff_amount = rules.order_amount
            if user_id is not None:
                sr2 = db.query(SymbolRule).filter(
                    SymbolRule.user_id == user_id, SymbolRule.symbol.in_([symbol, base_asset]),
                ).first()
                if sr2 and sr2.order_amount is not None:
                    eff_amount = sr2.order_amount
            qty = usdt_to_quantity(eff_amount, price, lot_info["stepSize"], lot_info["minQty"])
        if qty <= 0:
            position.status = "FAILED"
            position.error_message = "Order amount too small for lot size"
            db.commit()
            db.close()
            return None

        # borrow → idle
        # borrow_via_otoco=True 时走 coinmini 同款 IOC OTOCO 借币(MARGIN_BUY/IOC/卖价1.5x,
        # 三单 EXPIRED、币留手上);默认 False 走 borrow-repay,不改变现网行为。
        t0 = time.monotonic()
        if getattr(rules, "borrow_via_otoco", False):
            await client.margin_borrow_otoco(symbol, qty, legs=int(getattr(rules, "otoco_legs", 2) or 2))
        else:
            await client.margin_borrow(base_asset, qty)
        latency = int((time.monotonic() - t0) * 1000)
        position.status = "BORROWED_IDLE"
        position.borrow_qty = qty
        db.commit()
        _log_trade(db, pos_id, sub_account_id, "BORROW", symbol, quantity=qty, status="SUCCESS", latency=latency)
        logger.info(f"Borrowed (idle): {symbol} qty={qty}")
        return pos_id

    except BinanceAPIError as e:
        logger.error(f"Borrow failed: {e}")
        position.status = "FAILED"
        position.error_message = str(e)
        db.commit()
        _log_trade(db, pos_id, sub_account_id, "BORROW", symbol, status="FAILED", error=str(e))
        await notifier.notify_error(account_note, f"borrow {symbol}", str(e))
        return None
    except Exception as e:
        logger.error(f"Borrow failed unexpectedly: {e}", exc_info=True)
        position.status = "FAILED"
        position.error_message = str(e)
        db.commit()
        return None
    finally:
        db.close()


async def execute_hedge(
    position: Position,
    spread: SpreadSnapshot,
    rules: GlobalRulesSnapshot,
    client: BinanceTradingClient,
    notifier: FeishuSender,
    account_note: str,
    futures_client: BinanceTradingClient = None,
):
    """Phase 2: sell the borrowed coin on spot (short) + futures long (hedge).
    BORROWED_IDLE → SPOT_SOLD → OPEN. Full rollback on failure.
    futures_client: hedge_via_master 时传主账户 client(合约腿);None=合约同子账户(原行为)。"""
    fc = futures_client if futures_client is not None else client
    db = SessionLocal()
    # 跨进程互斥(API 手动对冲 vs 引擎自动): DB 级 CAS 认领,只有一方能推进
    claimed = db.query(Position).filter(
        Position.id == position.id, Position.status == "BORROWED_IDLE",
    ).update({"status": "HEDGING"}, synchronize_session=False)
    db.commit()
    if not claimed:
        db.close()
        return
    pos = db.query(Position).get(position.id)
    symbol = pos.symbol
    sub_account_id = pos.sub_account_id
    pos_id = pos.id
    qty = pos.borrow_qty

    # 主账户模式: 卖出前先预检+预留合约保证金,欠资不动现货(回到 BORROWED_IDLE 重试)
    reserved = None
    if futures_client is not None:
        reserved = await _master_margin_precheck(futures_client, symbol, qty, spread, notifier, account_note)
        if reserved is None:
            pos.status = "BORROWED_IDLE"
            db.commit()
            db.close()
            return

    fut_filled = {"qty": Decimal("0")}   # 合约腿已成交量(失败时平残腿用)
    try:
        # Step 1: spot sell (short leg) —— 按「单笔挂单」(order_amount) 分批卖出降低冲击;
        # 合约腿仍按实际卖出总量一次性对冲(回滚逻辑不变)。借量≤单笔时退化为单批=原行为。
        spot_lot = await client.get_lot_size(symbol, "spot")
        order_amt = Decimal(str(getattr(rules, "order_amount", 0) or 0))
        price_ref = spread.spot_ask if (spread.spot_ask and spread.spot_ask > 0) else Decimal("0")
        per_batch = round_to_step(order_amt / price_ref, spot_lot["stepSize"]) if (order_amt > 0 and price_ref > 0) else qty
        if per_batch <= 0:
            per_batch = qty
        total_sold = Decimal("0"); total_value = Decimal("0"); last_oid = ""
        remaining = qty
        first = True
        while remaining > 0:
            b = round_to_step(per_batch if remaining > per_batch else remaining, spot_lot["stepSize"])
            if b <= 0:
                break
            t0 = time.monotonic()
            sell_result = await client.spot_market_sell(symbol, b)
            latency = int((time.monotonic() - t0) * 1000)
            fqty = Decimal(str(sell_result["executedQty"]))
            fprice = _avg_fill_price(sell_result)
            total_sold += fqty
            total_value += fqty * fprice
            last_oid = str(sell_result["orderId"])
            if first:
                pos.status = "SPOT_SOLD"; first = False
            pos.spot_sell_qty = total_sold
            pos.spot_sell_price = (total_value / total_sold) if total_sold > 0 else fprice
            pos.spot_sell_order_id = last_oid
            db.commit()
            _log_trade(db, pos_id, sub_account_id, "SPOT_SELL", symbol, "SELL",
                        fqty, fprice, last_oid, "SUCCESS", latency=latency)
            remaining = round_to_step(qty - total_sold, spot_lot["stepSize"])
        if total_sold <= 0:
            raise BinanceAPIError(0, 0, "spot sell filled 0")
        qty = total_sold  # 合约按实际卖出量对冲

        # Stabilize before hedging (desktop parity)
        stabilize = float(getattr(rules, "stabilize_sec", 0) or 0)
        if stabilize > 0:
            await asyncio.sleep(min(stabilize, 10))

        # Step 2: futures long (hedge) — market (default) or marketable-limit/tiered
        # fc=master(hedge_via_master) 或子账户自身;同 symbol 在共享净仓上串行(per-symbol 锁)
        futures_lot = await fc.get_lot_size(symbol, "futures")
        futures_qty = round_to_step(qty, futures_lot["stepSize"])
        t0 = time.monotonic()
        async with _fc_symbol_lock(fc, symbol):
            if (getattr(rules, "follow_type", "market") or "market") == "limit":
                long_result = await _futures_entry_limit(
                    fc, symbol, futures_qty, rules, futures_lot, db, pos, sub_account_id,
                    fill_tracker=fut_filled,
                )
            else:
                # 带 clientOrderId: 响应丢失(超时/5xx 状态未知)时可复核实际成交量,
                # 保证失败回滚的残腿平仓拿到真实已成交量而非 0
                coid = f"hx{pos_id}t{int(time.time() * 1000) % 10**10}"
                try:
                    long_result = await fc.futures_market_long(symbol, futures_qty,
                                                               new_client_order_id=coid)
                    fut_filled["qty"] = Decimal(str(long_result.get("executedQty", "0")))
                except BinanceAPIError as fe:
                    if fe.api_code == -1007 or fe.http_code >= 500:
                        fut_filled["qty"] = await _query_filled_by_client_id(fc, symbol, coid)
                    raise
        latency = int((time.monotonic() - t0) * 1000)
        pos.status = "OPEN"
        pos.hedge_account = "master" if futures_client is not None else "sub"
        pos.futures_long_qty = Decimal(str(long_result["executedQty"]))
        pos.futures_long_price = Decimal(str(long_result.get("avgPrice", "0")))
        pos.futures_long_order_id = str(long_result["orderId"])
        pos.open_spread = spread.spread_short
        pos.open_usdt_amount = pos.spot_sell_qty * pos.spot_sell_price
        pos.opened_at = datetime.now(timezone.utc)
        db.commit()
        _log_trade(db, pos_id, sub_account_id, "FUTURES_LONG", symbol, "BUY",
                    pos.futures_long_qty, pos.futures_long_price, pos.futures_long_order_id, "SUCCESS", latency=latency)

        logger.info(f"Position opened: {symbol} qty={qty} spread={spread.spread_short}%")
        await notifier.notify_position_opened(
            account_note, symbol, spread.spread_short, qty, pos.open_usdt_amount,
        )

    except BinanceAPIError as e:
        logger.error(f"Hedge failed at {pos.status}: {e}")
        await _handle_hedge_failure(db, pos, client, e, sub_account_id, symbol, notifier, account_note,
                                    futures_client=futures_client, futures_filled=fut_filled["qty"])
    except Exception as e:
        # 非 API 异常同样走回滚(可能已卖出现货/已部分成交合约,只置 FAILED 会裸留敞口)
        logger.error(f"Hedge failed unexpectedly: {e}", exc_info=True)
        await _handle_hedge_failure(db, pos, client, e, sub_account_id, symbol, notifier, account_note,
                                    futures_client=futures_client, futures_filled=fut_filled["qty"])
    finally:
        _release_margin_reserve(futures_client, reserved)
        db.close()


async def _handle_hedge_failure(db, pos, client, error, sub_account_id, symbol, notifier, account_note,
                                futures_client=None, futures_filled: Decimal = Decimal("0")):
    current = pos.status
    if current in ("BORROWED_IDLE", "HEDGING"):
        # spot sell failed — repay borrow
        try:
            await client.margin_repay(pos.base_asset, pos.borrow_qty)
            _log_trade(db, pos.id, sub_account_id, "ROLLBACK_REPAY", symbol,
                        quantity=pos.borrow_qty, status="SUCCESS")
        except Exception as re:
            _log_trade(db, pos.id, sub_account_id, "ROLLBACK_REPAY", symbol, status="FAILED", error=str(re))
        pos.status = "FAILED"
        pos.error_message = f"Spot sell failed: {error}. Borrow rolled back."
        db.commit()
    elif current == "SPOT_SOLD":
        # futures long failed — close any partial futures fill first (master 残腿不平会污染共享净仓),
        # then buy back spot + repay
        if futures_filled and futures_filled > 0:
            fcr = futures_client if futures_client is not None else client
            try:
                async with _fc_symbol_lock(fcr, symbol):
                    await fcr.futures_market_close(symbol, futures_filled)
                _log_trade(db, pos.id, sub_account_id, "ROLLBACK_FUTURES_CLOSE", symbol, "SELL",
                            futures_filled, status="SUCCESS")
            except Exception as re:
                _log_trade(db, pos.id, sub_account_id, "ROLLBACK_FUTURES_CLOSE", symbol,
                            status="FAILED", error=str(re))
        rollback_qty = pos.spot_sell_qty if pos.spot_sell_qty else pos.borrow_qty
        try:
            await client.spot_market_buy_qty(symbol, rollback_qty)
            _log_trade(db, pos.id, sub_account_id, "ROLLBACK_SPOT_BUY", symbol, "BUY", rollback_qty, status="SUCCESS")
        except Exception as re:
            _log_trade(db, pos.id, sub_account_id, "ROLLBACK_SPOT_BUY", symbol, status="FAILED", error=str(re))
        try:
            total_debt, _ = await _get_asset_debt(client, pos.base_asset)
            repay_amount = total_debt if total_debt > 0 else pos.borrow_qty
            await client.margin_repay(pos.base_asset, repay_amount)
            _log_trade(db, pos.id, sub_account_id, "ROLLBACK_REPAY", symbol, quantity=repay_amount, status="SUCCESS")
        except Exception as re:
            _log_trade(db, pos.id, sub_account_id, "ROLLBACK_REPAY", symbol, status="FAILED", error=str(re))
        pos.status = "FAILED"
        pos.error_message = f"Futures long failed: {error}. Rolled back."
        db.commit()
    else:
        pos.status = "FAILED"
        pos.error_message = str(error)
        db.commit()
    await notifier.notify_error(account_note, f"hedge {symbol} (rollback from {current})", str(error))


async def execute_open(
    sub_account_id: int,
    symbol: str,
    spread: SpreadSnapshot,
    rules: GlobalRulesSnapshot,
    client: BinanceTradingClient,
    notifier: FeishuSender,
    account_note: str,
    spread_feed: SpreadFeed = None,
    futures_client: BinanceTradingClient = None,
):
    """Atomic open (borrow + hedge in one shot) — used by manual-open and as a fallback."""
    pos_id = await execute_borrow(
        sub_account_id, symbol, spread, rules, client, notifier, account_note,
        spread_feed=spread_feed, min_spread=rules.open_spread,
    )
    if pos_id is None:
        return
    db = SessionLocal()
    pos = db.query(Position).get(pos_id)
    db.close()
    if pos and pos.status == "BORROWED_IDLE":
        cur = spread_feed.get_symbol(symbol) if spread_feed else None
        await execute_hedge(pos, cur or spread, rules, client, notifier, account_note,
                            futures_client=futures_client)


async def execute_unhedge(
    position: Position,
    spread: SpreadSnapshot,
    client: BinanceTradingClient,
    notifier: FeishuSender,
    account_note: str,
    futures_client: BinanceTradingClient = None,
):
    """Phase 1 of close: close the futures long + buy back the spot, leaving the coin
    in the margin account awaiting repay. OPEN → PENDING_REPAY (net-flat, no exposure).
    合约腿按开仓归属(pos.hedge_account)选 client —— master 开的仓必须用 master 平,
    与全局开关当前值无关;master client 缺失时不动仓位,留 OPEN 等重试。"""
    db = SessionLocal()
    pos = db.query(Position).get(position.id)
    if not pos or pos.status != "OPEN":
        db.close()
        return
    on_master = getattr(pos, "hedge_account", None) == "master"
    if on_master and futures_client is None:
        logger.warning(f"Unhedge {pos.symbol}: hedged on master but master client unavailable; retry later")
        db.close()
        return
    fc = futures_client if on_master else client

    # 跨进程互斥(API 手动平仓 vs 引擎自动): DB 级 CAS 认领 —— master 共享净仓下
    # 双平会误吃其他子账户的对冲腿,留下账面无感知的裸现货空头
    claimed = db.query(Position).filter(
        Position.id == pos.id, Position.status == "OPEN",
    ).update({"status": "CLOSING_FUTURES"}, synchronize_session=False)
    db.commit()
    if not claimed:
        db.close()
        return
    db.refresh(pos)

    try:
        # Step 1: close futures
        t0 = time.monotonic()
        async with _fc_symbol_lock(fc, pos.symbol):
            close_result = await fc.futures_market_close(pos.symbol, pos.futures_long_qty)
        latency = int((time.monotonic() - t0) * 1000)
        pos.futures_close_price = Decimal(str(close_result.get("avgPrice", "0")))
        pos.futures_close_order_id = str(close_result["orderId"])
        pos.status = "FUTURES_CLOSED"
        db.commit()
        _log_trade(db, pos.id, pos.sub_account_id, "FUTURES_CLOSE", pos.symbol, "SELL",
                    pos.futures_long_qty, pos.futures_close_price,
                    pos.futures_close_order_id, "SUCCESS", latency=latency)

        # Step 2: buy back the borrowed coin (cover the short) — keep it for manual repay
        total_debt, _ = await _get_asset_debt(client, pos.base_asset)
        buy_qty = total_debt * FEE_BUFFER if total_debt > 0 else pos.borrow_qty
        spot_lot = await client.get_lot_size(pos.symbol, "spot")
        buy_qty = round_to_step(buy_qty, spot_lot["stepSize"])

        pos.status = "CLOSING_SPOT"
        db.commit()
        t0 = time.monotonic()
        buy_result = await client.spot_market_buy_qty(pos.symbol, buy_qty)
        latency = int((time.monotonic() - t0) * 1000)
        pos.spot_buy_qty = Decimal(str(buy_result["executedQty"]))
        pos.spot_buy_price = _avg_fill_price(buy_result)
        pos.spot_buy_order_id = str(buy_result["orderId"])
        pos.close_spread = spread.spread_short
        pos.status = "PENDING_REPAY"   # coin held; awaiting manual/auto repay
        db.commit()
        _log_trade(db, pos.id, pos.sub_account_id, "SPOT_BUY", pos.symbol, "BUY",
                    pos.spot_buy_qty, pos.spot_buy_price,
                    pos.spot_buy_order_id, "SUCCESS", latency=latency)

        logger.info(f"Unhedged (pending repay): {pos.symbol}")

    except BinanceAPIError as e:
        logger.error(f"Unhedge failed at {pos.status}: {e}")
        pos.error_message = str(e)
        pos.retry_count = (pos.retry_count or 0) + 1
        db.commit()
        _log_trade(db, pos.id, pos.sub_account_id, "CLOSE_ERROR", pos.symbol, status="FAILED", error=str(e))
        await notifier.notify_error(account_note, f"unhedge {pos.symbol}", str(e))
    except Exception as e:
        logger.error(f"Unhedge failed unexpectedly: {e}", exc_info=True)
        pos.error_message = str(e)
        db.commit()
        await notifier.notify_error(account_note, f"unhedge {pos.symbol}", str(e))
    finally:
        db.close()


async def execute_repay(
    position: Position,
    client: BinanceTradingClient,
    notifier: FeishuSender,
    account_note: str,
):
    """Phase 2 of close: repay the margin debt and finalize PnL. PENDING_REPAY → CLOSED."""
    db = SessionLocal()
    pos = db.query(Position).get(position.id)
    if not pos or pos.status != "PENDING_REPAY":
        db.close()
        return
    # 跨进程互斥: CAS 认领,防手动还币与引擎自动还币双发(双倍 repay 会动用账户其他资产)
    claimed = db.query(Position).filter(
        Position.id == pos.id, Position.status == "PENDING_REPAY",
    ).update({"status": "REPAYING"}, synchronize_session=False)
    db.commit()
    if not claimed:
        db.close()
        return
    db.refresh(pos)

    try:
        total_debt, interest_amount = await _get_asset_debt(client, pos.base_asset)
        repay_amount = total_debt if total_debt > 0 else pos.borrow_qty
        t0 = time.monotonic()
        await client.margin_repay(pos.base_asset, repay_amount)
        latency = int((time.monotonic() - t0) * 1000)
        pos.repay_qty = repay_amount
        pos.repay_interest = interest_amount
        _log_trade(db, pos.id, pos.sub_account_id, "REPAY", pos.symbol,
                    quantity=repay_amount, status="SUCCESS", latency=latency)

        # Finalize PnL (fees + interest)
        spot_pnl = (pos.spot_sell_qty * pos.spot_sell_price) - (pos.spot_buy_qty * pos.spot_buy_price)
        futures_pnl = (pos.futures_close_price - pos.futures_long_price) * pos.futures_long_qty
        spot_sell_notional = pos.spot_sell_qty * pos.spot_sell_price
        spot_buy_notional = pos.spot_buy_qty * pos.spot_buy_price
        futures_open_notional = pos.futures_long_qty * pos.futures_long_price
        futures_close_notional = pos.futures_long_qty * pos.futures_close_price
        total_fee = (spot_sell_notional + spot_buy_notional + futures_open_notional + futures_close_notional) * TAKER_FEE_RATE
        interest_cost = interest_amount * pos.spot_buy_price if interest_amount else Decimal("0")
        pos.fee_total = total_fee + interest_cost
        pos.realized_pnl = spot_pnl + futures_pnl - total_fee - interest_cost
        pos.closed_at = datetime.now(timezone.utc)
        pos.status = "CLOSED"
        db.commit()

        logger.info(f"Position closed (repaid): {pos.symbol} pnl={pos.realized_pnl}")
        await notifier.notify_position_closed(account_note, pos.symbol, pos.realized_pnl, pos.close_spread or Decimal("0"))

    except BinanceAPIError as e:
        logger.error(f"Repay failed: {e}")
        pos.error_message = str(e)
        pos.retry_count = (pos.retry_count or 0) + 1
        db.commit()
        _log_trade(db, pos.id, pos.sub_account_id, "REPAY", pos.symbol, status="FAILED", error=str(e))
        await notifier.notify_error(account_note, f"repay {pos.symbol}", str(e))
    except Exception as e:
        logger.error(f"Repay failed unexpectedly: {e}", exc_info=True)
        pos.error_message = str(e)
        db.commit()
        await notifier.notify_error(account_note, f"repay {pos.symbol}", str(e))
    finally:
        db.close()


async def execute_close(
    position: Position,
    spread: SpreadSnapshot,
    client: BinanceTradingClient,
    notifier: FeishuSender,
    account_note: str,
    futures_client: BinanceTradingClient = None,
):
    """Atomic close (unhedge + repay in one shot) — used by manual-close / tail cleanup."""
    await execute_unhedge(position, spread, client, notifier, account_note,
                          futures_client=futures_client)
    db = SessionLocal()
    pos = db.query(Position).get(position.id)
    db.close()
    if pos and pos.status == "PENDING_REPAY":
        await execute_repay(pos, client, notifier, account_note)


async def execute_borrow_only_repay(
    sub_account_id: int,
    symbol: str,
    client: BinanceTradingClient,
    notifier: FeishuSender,
    account_note: str,
    user_id: int = None,
):
    """C6: Repay a borrow-only position (never opened) and record interest in history."""
    base_asset = symbol.replace("USDT", "")
    db = SessionLocal()
    try:
        total_debt, interest_amount = await _get_asset_debt(client, base_asset)
        if total_debt <= 0:
            return

        await client.margin_repay(base_asset, total_debt)

        position = Position(
            sub_account_id=sub_account_id,
            symbol=symbol,
            base_asset=base_asset,
            status="CLOSED",
            user_id=user_id,
            borrow_qty=total_debt - interest_amount,
            repay_qty=total_debt,
            repay_interest=interest_amount,
            cumulative_interest=interest_amount,
            realized_pnl=-interest_amount,
            fee_total=interest_amount,
            opened_at=datetime.now(timezone.utc),
            closed_at=datetime.now(timezone.utc),
            error_message="borrow-only repay (no position opened)",
        )
        db.add(position)
        db.commit()

        _log_trade(db, position.id, sub_account_id, "BORROW_ONLY_REPAY", symbol,
                    quantity=total_debt, status="SUCCESS")

        logger.info(f"Borrow-only repay: {symbol} debt={total_debt} interest={interest_amount}")
        await notifier.send(
            "借币还币记录",
            f"账户: {account_note}\n币种: {symbol}\n借币: {total_debt - interest_amount}\n利息: {interest_amount}",
        )
    except Exception as e:
        logger.error(f"Borrow-only repay failed {symbol}: {e}")
        _log_trade(db, None, sub_account_id, "BORROW_ONLY_REPAY", symbol,
                    status="FAILED", error=str(e))
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


# ─── Limit / tiered futures entry (hedge-safe: always reconciles to full hedge) ───

LIMIT_WAIT_SEC = 2.0       # max wait per limit tranche before fallback
LIMIT_POLL_SEC = 0.3


def _parse_tiers(tier_ratios: str) -> list[tuple[Decimal, Decimal]]:
    """Parse "0.5:30,0.8:30,1.2:40" -> [(offset_pct, qty_pct), ...].
    Returns [] when empty/invalid (caller falls back to a single tranche)."""
    if not tier_ratios or not tier_ratios.strip():
        return []
    out: list[tuple[Decimal, Decimal]] = []
    try:
        for part in tier_ratios.split(","):
            off, q = part.split(":")
            out.append((Decimal(off.strip()), Decimal(q.strip())))
    except Exception:
        return []
    total = sum(q for _, q in out)
    if total <= 0:
        return []
    return out


async def _poll_fill(client: BinanceTradingClient, symbol: str, order_id: str,
                     timeout: float) -> tuple[Decimal, Decimal]:
    """Poll a futures order until FILLED or timeout. Returns (executedQty, avgPrice)."""
    waited = 0.0
    eq, ap = Decimal("0"), Decimal("0")
    while waited < timeout:
        try:
            o = await client.futures_get_order(symbol, order_id)
            eq = Decimal(str(o.get("executedQty", "0")))
            ap = Decimal(str(o.get("avgPrice", "0")))
            if o.get("status") in ("FILLED", "CANCELED", "EXPIRED", "REJECTED"):
                break
        except Exception:
            pass
        await asyncio.sleep(LIMIT_POLL_SEC)
        waited += LIMIT_POLL_SEC
    return eq, ap


async def _futures_entry_limit(client: BinanceTradingClient, symbol: str, total_qty: Decimal,
                               rules, futures_lot: dict, db, pos, sub_account_id,
                               fill_tracker: dict = None) -> dict:
    """Marketable-limit (+ optional tiered) futures long, capping slippage but
    ALWAYS reconciling any unfilled remainder with a market order so the spot leg
    is never left unhedged. Returns a dict shaped like a market-order result."""
    step = futures_lot["stepSize"]
    min_qty = Decimal(str(futures_lot.get("minQty", "0")))
    slippage = (rules.slippage_pct or Decimal("0.1")) / Decimal("100")

    # fresh ask for accurate limit pricing
    try:
        book = await client.futures_book_ticker(symbol)
        ask = Decimal(str(book.get("askPrice") or book.get("a") or "0"))
    except Exception:
        ask = Decimal("0")
    tick = await client.get_futures_tick_size(symbol)

    tiers = _parse_tiers(rules.tier_ratios)
    if not tiers:
        tiers = [(rules.slippage_pct or Decimal("0.1"), Decimal("100"))]

    fills: list[tuple[Decimal, Decimal]] = []
    filled = Decimal("0")

    if ask > 0:
        for offset_pct, qty_pct in tiers:
            qty_i = round_to_step(total_qty * qty_pct / Decimal("100"), step)
            if qty_i <= 0:
                continue
            # marketable limit: ask uplifted by max(offset, slippage cap)
            uplift = max(offset_pct / Decimal("100"), slippage)
            price = round_to_step(ask * (Decimal("1") + uplift), tick)
            try:
                res = await client.futures_limit_long(symbol, qty_i, price)
                oid = str(res["orderId"])
                eq, ap = await _poll_fill(client, symbol, oid, LIMIT_WAIT_SEC)
                if eq < qty_i:
                    try:
                        cres = await client.futures_cancel_order(symbol, oid)
                        eq = Decimal(str(cres.get("executedQty") or eq))
                        ap = Decimal(str(cres.get("avgPrice") or ap))
                    except Exception:
                        pass
                    # 最后一次轮询与撤单生效之间可能有新成交 —— 以订单终态为准,
                    # 否则 filled 低估 → 市价兜底超买 + 回滚平不净(master 共仓残腿)
                    for _ in range(3):
                        try:
                            o = await client.futures_get_order(symbol, oid)
                            eq = Decimal(str(o.get("executedQty", "0")))
                            ap = Decimal(str(o.get("avgPrice", "0")))
                            break
                        except Exception:
                            await asyncio.sleep(0.3)
                if eq > 0:
                    fills.append((eq, ap)); filled += eq
                    if fill_tracker is not None:
                        fill_tracker["qty"] = filled
                    _log_trade(db, pos.id, sub_account_id, "FUTURES_LIMIT_FILL", symbol, "BUY",
                                eq, ap, oid, "SUCCESS")
            except Exception as e:
                logger.warning(f"Limit tranche failed {symbol} {qty_i}@{price}: {e}")

    # Reconcile to full hedge with a market order (safety invariant).
    remaining = round_to_step(total_qty - filled, step)
    last_id = None
    if remaining >= min_qty and remaining > 0:
        mres = await client.futures_market_long(symbol, remaining)
        meq = Decimal(str(mres.get("executedQty", "0")))
        map_ = Decimal(str(mres.get("avgPrice", "0")))
        last_id = str(mres.get("orderId", ""))
        if meq > 0:
            fills.append((meq, map_)); filled += meq
            if fill_tracker is not None:
                fill_tracker["qty"] = filled
            _log_trade(db, pos.id, sub_account_id, "FUTURES_MARKET_FALLBACK", symbol, "BUY",
                        meq, map_, last_id, "SUCCESS")

    avg = (sum(q * p for q, p in fills) / filled) if filled > 0 else Decimal("0")
    return {
        "executedQty": str(filled),
        "avgPrice": str(avg),
        "orderId": last_id or (str(int(pos.id)) if not fills else "limit"),
    }
