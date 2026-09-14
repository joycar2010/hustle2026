"""裸空/单腿安全网:周期对账币安真实债务,发现「孤儿债务」即告警 + 自动收口。

孤儿债务 = 币安该子账户某币 borrowed+interest 名义价值 > DUST_NOTIONAL,且 DB 里该
(sub_account, symbol) 没有任何非终态 position(非 CLOSED/FAILED)。正常借币/对冲全程都有非
终态 position(PENDING_BORROW→BORROWED_IDLE→HEDGING→SPOT_SOLD→OPEN→PENDING_REPAY→
REPAYING),命中即跳过 —— 这是防误触发的命门,让 0.5s 周期也安全。只有「债务存在但状态机
已丢失追踪」(全 CLOSED/FAILED 却仍欠债)= 孤儿 = 裸空或未追踪借币。

收口统一安全:free≥debt → 直接还币(把持有的币还回);free<debt(币已卖)→ 买回缺口再还。
两路都终于 debt=0。一套机制同时覆盖「裸空收口」+「CLOSED-position 与币安债务对账」两个诉求。

根因背景见 [[coin-hedge-via-master]] / hustle-011 裸空事故(借币后现货被市价卖、合约腿未开)。
"""
import asyncio
import json
import logging
import math
from decimal import Decimal, InvalidOperation

from app.db.session import SessionLocal
from engine.models import Position, TradeLog
from engine.trading.binance_trading import BinanceAPIError

logger = logging.getLogger(__name__)

# 稳定币/手续费币不计债务对账(BNB 借贷利息属正常,不视为裸空)
_STABLE = {"USDT", "BNB", "BUSD", "USDC", "FDUSD", "TUSD"}
_TERMINAL = ("CLOSED", "FAILED")
_BORROW_OUTCOME_UNKNOWN = "BORROW_OUTCOME_UNKNOWN"
DUST_NOTIONAL = Decimal("2.0")   # 债务名义价值 < 2 USDT 不买回；有足额现币仍可直接还清
REPAY_EPSILON = Decimal("0.00000001")

# per-(account:symbol) 连续命中计数(去抖:需连续 2 次=1s 持续才动作,排除借币提交瞬间的微race)
_hit_counts: dict[str, int] = {}


def _proven_terminal_residual(sub_account_id: int, symbol: str) -> Decimal:
    """Return the remaining close residual attributable to terminal rows.

    A zero-debt asset can also be a user's own holding, so an account-wide
    free balance must not be sold merely because a pair was once traded.  We
    only authorize a sweep when completed position rows prove a buy-back
    quantity greater than the recorded repayment.  Prior residual-sale logs
    are deducted so a retry cannot consume unrelated holdings.
    """
    db = SessionLocal()
    try:
        rows = db.query(Position).filter(
            Position.sub_account_id == sub_account_id,
            Position.symbol == symbol,
            Position.status == "CLOSED",
            Position.spot_buy_order_id.isnot(None),
        ).all()
        if not rows:
            return Decimal("0")
        position_ids = [row.id for row in rows if row.id is not None]
        sold_by_position: dict[int, Decimal] = {}
        if position_ids:
            logs = db.query(TradeLog).filter(
                TradeLog.sub_account_id == sub_account_id,
                TradeLog.symbol == symbol,
                TradeLog.action == "SPOT_RESIDUAL_SELL",
                TradeLog.status.in_(("SUCCESS", "PARTIAL", "PARTIALLY_FILLED")),
            ).all()
            for log in logs:
                try:
                    qty = Decimal(str(log.quantity or "0"))
                except (TypeError, ValueError, InvalidOperation):
                    qty = Decimal("0")
                if qty > 0:
                    # Automatic account-level cleanup may not be attributable
                    # to one row, therefore aggregate all prior cleanup logs.
                    key = log.position_id or 0
                    sold_by_position[key] = sold_by_position.get(key, Decimal("0")) + qty
        total = Decimal("0")
        for row in rows:
            # ``isnot(None)`` keeps the query indexable, but legacy rows may
            # contain an empty order id.  An empty id is not close provenance.
            if not str(getattr(row, "spot_buy_order_id", "") or "").strip():
                continue
            # Rows from the old close path could be marked CLOSED before the
            # repayment/PnL commit. Keep them out of asset-level conversion;
            # they require a one-time read-only reconciliation first.
            if getattr(row, "realized_pnl", None) is None or getattr(row, "fee_total", None) is None:
                continue
            try:
                bought = Decimal(str(row.spot_buy_qty or "0"))
                repaid = Decimal(str(row.repay_qty or "0"))
            except (TypeError, ValueError, InvalidOperation):
                continue
            if not bought.is_finite() or not repaid.is_finite():
                continue
            residual = max(Decimal("0"), bought - repaid)
            residual -= sold_by_position.get(row.id, Decimal("0"))
            total += max(Decimal("0"), residual)
        total -= sold_by_position.get(0, Decimal("0"))
        return total
    finally:
        db.close()


def _has_terminal_residual_provenance(sub_account_id: int, symbol: str) -> bool:
    return _proven_terminal_residual(sub_account_id, symbol) > REPAY_EPSILON


def _has_active_position(sub_account_id: int, symbol: str) -> bool:
    """该 (sub_account, symbol) 是否有非终态 position(状态机仍在追踪)。"""
    db = SessionLocal()
    try:
        return db.query(Position).filter(
            Position.sub_account_id == sub_account_id,
            Position.symbol == symbol,
            Position.status.notin_(_TERMINAL),
        ).count() > 0
    finally:
        db.close()


def _unknown_borrow_positions(
    sub_account_id: int,
    symbol: str | None = None,
) -> list[Position]:
    """Load ambiguous borrow rows before the generic active-position gate."""
    db = SessionLocal()
    try:
        query = db.query(Position).filter(
            Position.sub_account_id == sub_account_id,
            Position.status == _BORROW_OUTCOME_UNKNOWN,
        )
        if symbol is not None:
            query = query.filter(Position.symbol == symbol)
        return query.order_by(Position.id.asc()).all()
    finally:
        db.close()


def _asset_state(ma: dict, asset: str):
    for a in ma.get("userAssets", []):
        if a.get("asset") == asset:
            b = Decimal(str(a.get("borrowed", "0") or 0))
            i = Decimal(str(a.get("interest", "0") or 0))
            f = Decimal(str(a.get("free", "0") or 0))
            return b, i, f
    return Decimal("0"), Decimal("0"), Decimal("0")


async def _repay_available_free(client, asset: str) -> Decimal:
    """Repay only the coin already available in the margin account.

    This path is deliberately independent of market-order filters.  A dust
    debt may be below Binance's minimum order notional, but repaying an
    already-held amount is risk-free and reduces the outstanding liability.
    Re-read the account immediately before submitting and trim on ``-3041``
    because interest/settlement can make the first amount marginally too high.
    """
    latest = await client.get_margin_account()
    borrowed, interest, free = _asset_state(latest, asset)
    amount = min(borrowed + interest, free)
    if amount <= 0:
        return Decimal("0")
    for attempt in range(5):
        try:
            await client.margin_repay(asset, amount)
            return amount
        except BinanceAPIError as exc:
            if getattr(exc, "api_code", None) == -3041 and attempt < 4:
                amount *= Decimal("0.999")
                if amount <= 0:
                    break
                continue
            raise
    return Decimal("0")


async def run_naked_short_guard(client, redis, sub_account_id, user_id, notifier,
                                account_note, *, auto_remediate=True,
                                cleanup_residuals=True):
    """对账本子账户币安真实债务,孤儿债务即告警 + (可选)自动收口。每周期由 worker 调一次。"""
    ma = await client.get_margin_account()

    # A completed close can leave free margin coin after debt reaches zero.
    # The naked-debt loop below intentionally ignores debt=0, so those rows
    # used to remain visible forever.  Sweep only quantities proven by closed
    # buy-back rows; arbitrary user-held inventory is never touched.
    if auto_remediate and cleanup_residuals:
        await _cleanup_terminal_residuals(
            client, redis, sub_account_id, ma, notifier, account_note,
        )

    # Unknown submissions must remain visible even when Binance reports zero
    # principal or omits the asset from userAssets. Query Position first; a
    # debt-driven loop alone cannot observe either case.
    unknown_rows = await asyncio.to_thread(
        _unknown_borrow_positions, sub_account_id
    )
    unknown_by_symbol: dict[str, list[Position]] = {}
    for row in unknown_rows:
        symbol = str(row.symbol or "").upper()
        if symbol:
            unknown_by_symbol.setdefault(symbol, []).append(row)

    margin_assets = {
        str(item.get("asset") or "").upper(): item
        for item in ma.get("userAssets", [])
        if item.get("asset")
    }
    for symbol, rows in unknown_by_symbol.items():
        asset = str(rows[0].base_asset or "").upper()
        if not asset and symbol.endswith("USDT"):
            asset = symbol[:-4]
        snapshot = margin_assets.get(asset, {})
        borrowed = Decimal(str(snapshot.get("borrowed", "0") or 0))
        free = Decimal(str(snapshot.get("free", "0") or 0))
        key = f"{sub_account_id}:{symbol}"
        _hit_counts.pop(key, None)
        wait_key = f"engine:borrowunknown:{sub_account_id}:{symbol}"
        try:
            already_alerted = await redis.get(wait_key)
            if not already_alerted:
                await redis.set(wait_key, "1", ex=300)
                details = "; ".join(
                    f"position={row.id}: {row.error_message or 'no detail'}"
                    for row in rows
                )
                logger.error(
                    "BORROW OUTCOME UNKNOWN acct%s %s principal=%s free=%s; %s",
                    sub_account_id, symbol, borrowed, free, details,
                )
                await notifier.notify_error(
                    account_note,
                    f"借币待核对 {symbol}",
                    f"Binance本金={borrowed} {asset}, 可用={free}; {details}; "
                    "已阻断该账户该币继续借币，未自动操作账户总债",
                )
        except Exception:
            logger.debug("unknown borrow alert failed", exc_info=True)

    for a in ma.get("userAssets", []):
        asset = a.get("asset")
        if not asset or asset in _STABLE:
            continue
        borrowed = Decimal(str(a.get("borrowed", "0") or 0))
        interest = Decimal(str(a.get("interest", "0") or 0))
        free = Decimal(str(a.get("free", "0") or 0))
        debt = borrowed + interest
        if debt <= 0:
            continue
        symbol = f"{asset}USDT"
        key = f"{sub_account_id}:{symbol}"

        # 命门:有非终态 position → 状态机在管(含正常对冲中间窗口),跳过 + 清去抖计数
        if await asyncio.to_thread(_has_active_position, sub_account_id, symbol):
            _hit_counts.pop(key, None)
            continue

        # 孤儿候选:取 Rust Binance WS 现价算名义价值(只对孤儿取价,正常态不打)
        price_error = None
        try:
            price = await client.ws_spot_price(symbol, "bid")
        except Exception as exc:
            price = Decimal("0")
            price_error = str(exc) or exc.__class__.__name__
        if price <= 0:
            # Never buy back with an absent/stale quote. Keep the debt visible
            # and retry on the next cycle; rate-limit the operator alert so a
            # low-liquidity WS outage cannot flood notifications.
            _hit_counts.pop(key, None)
            wait_key = f"engine:nakedfix:pricewait:{sub_account_id}:{symbol}"
            try:
                already_alerted = await redis.get(wait_key)
                if not already_alerted:
                    await redis.set(wait_key, "1", ex=300)
                    detail = price_error or "WS bid price unavailable"
                    logger.error(
                        "NAKED SHORT pending price: acct%s %s debt=%s; "
                        "remediation withheld until fresh WS quote (%s)",
                        sub_account_id, symbol, debt, detail,
                    )
                    try:
                        await notifier.notify_error(
                            account_note,
                            f"孤儿债务收口等待实时行情 {symbol}",
                            f"借币债务约 {debt} {asset}, WS 实时买回价暂不可用: {detail}; 未下单,行情恢复后自动重试",
                        )
                    except Exception:
                        logger.debug("naked price-wait notification failed", exc_info=True)
            except Exception:
                logger.debug("naked price-wait cooldown failed", exc_info=True)
            continue
        if debt * price < DUST_NOTIONAL:
            # A dust-sized debt is still safe to settle when the margin
            # account already holds enough of the asset.  The old blanket
            # skip left these rows visible forever even though a direct
            # repay carries no market-order risk.  A shortfall remains
            # untouched because buying it would violate the exchange's
            # minimum-notional rule; emit one throttled diagnostic instead.
            _hit_counts.pop(key, None)
            dust_key = f"engine:nakedfix:dust:{sub_account_id}:{symbol}"
            try:
                if not await redis.get(dust_key):
                    await redis.set(dust_key, "1", ex=300)
                    if not auto_remediate:
                        await notifier.notify_error(
                            account_note,
                            f"微额残债待人工处理 {symbol}",
                            f"Binance 残债 {debt} {asset} 名义约 {debt * price:.4f}U，"
                            "自动收口已关闭，未发起任何还币或买单",
                        )
                    elif free >= debt:
                        await _remediate(
                            client, symbol, asset, debt, free, price, ma,
                            sub_account_id, notifier, account_note,
                        )
                    elif free > 0 and auto_remediate:
                        # The market-buy portion is intentionally impossible
                        # for a dust shortfall, but any coin already held can
                        # still be repaid safely.  Do that partial reduction
                        # instead of leaving the full historical debt forever.
                        repaid = await _repay_available_free(client, asset)
                        if repaid > 0:
                            await notifier.notify_error(
                                account_note,
                                f"微额残债部分收口 {symbol}",
                                f"已用账户现有 {repaid} {asset} 偿还；"
                                "剩余缺口低于 Binance 最小下单额，未发起买单，残债继续可见",
                            )
                    else:
                        await notifier.notify_error(
                            account_note,
                            f"微额残债待人工处理 {symbol}",
                            f"Binance 残债 {debt} {asset} 名义约 {debt * price:.4f}U，"
                            "可用币不足且低于最小下单额，未发起买单",
                        )
            except Exception:
                logger.debug("dust debt reconciliation failed", exc_info=True)
            continue

        # 去抖:需连续 2 次命中才动作
        _hit_counts[key] = _hit_counts.get(key, 0) + 1
        if _hit_counts[key] < 2:
            continue

        # Redis 冷却:收口/告警后 5min 内不重复(防结算期反复触发)
        cd_key = f"engine:nakedfix:{sub_account_id}:{symbol}"
        try:
            if await redis.get(cd_key):
                continue
        except Exception:
            pass
        _hit_counts.pop(key, None)

        # 主账户合约持仓量(仅作告警上下文,不参与判定)
        fut_qty = None
        try:
            raw = await redis.get(f"balance:latest:{user_id}")
            if raw:
                fut_qty = (json.loads(raw).get("master_futures_positions") or {}).get(symbol)
        except Exception:
            pass

        logger.warning(
            f"NAKED SHORT (orphan debt) acct{sub_account_id} {symbol}: "
            f"borrowed={borrowed} interest={interest} free={free} fut={fut_qty} notional≈{debt*price:.2f}U"
        )
        try:
            await notifier.notify_naked_short(account_note, symbol, debt, free, fut_qty)
        except Exception as e:
            logger.warning(f"notify_naked_short failed: {e}")

        # 占冷却(无论是否自动收口,都防 5min 内刷屏/重复动作)
        try:
            await redis.set(cd_key, "1", ex=300)
        except Exception:
            pass

        if not auto_remediate:
            continue

        try:
            await _remediate(client, symbol, asset, debt, free, price, ma,
                             sub_account_id, notifier, account_note)
        except Exception as e:
            logger.error(f"naked short remediate failed acct{sub_account_id} {symbol}: {e}")
            try:
                await notifier.notify_error(account_note, f"裸空收口失败 {symbol}", str(e))
            except Exception:
                pass


async def _cleanup_terminal_residuals(
    client,
    redis,
    sub_account_id: int,
    margin_account: dict,
    notifier,
    account_note: str,
    symbols: set[str] | None = None,
) -> int:
    """Automatically sell proven zero-debt close residuals.

    The account-level margin ``free`` field is safe to inspect but unsafe to
    blindly sell.  Require all of these gates before submitting a market
    order: Binance confirms zero debt, no non-terminal position exists, a
    CLOSED row proves buy-back quantity above repayment, and free balance does
    not exceed the proven remainder (which would indicate unrelated user
    holdings).  A short Redis claim suppresses concurrent/manual races.
    """
    from engine.trading.order_executor import sell_residual_spot

    cleaned = 0
    for raw in margin_account.get("userAssets", []):
        asset = str(raw.get("asset") or "").upper()
        if not asset or asset in _STABLE:
            continue
        try:
            debt = Decimal(str(raw.get("borrowed", "0") or 0)) + Decimal(
                str(raw.get("interest", "0") or 0)
            )
            free = Decimal(str(raw.get("free", "0") or 0))
        except (TypeError, ValueError, InvalidOperation):
            continue
        if debt > REPAY_EPSILON or free <= REPAY_EPSILON:
            continue
        symbol = f"{asset}USDT"
        # A post-close trigger may scope the pass to the position that just
        # reached CLOSED.  Keep the periodic naked-debt sweep account-wide,
        # while allowing the close path to avoid touching an unrelated asset.
        if symbols is not None and symbol not in symbols:
            continue
        # A newly borrowed/open symbol must never be sold by the residual
        # maintenance path, even if the debt snapshot is briefly stale.
        if await asyncio.to_thread(_has_active_position, sub_account_id, symbol):
            continue
        proven = await asyncio.to_thread(
            _proven_terminal_residual, sub_account_id, symbol,
        )
        # We cannot decompose one account-level free balance into "position
        # residual" and a user's own deposit.  Require the observed amount to
        # match the proven remainder (exchange rounding tolerance); both a
        # larger balance and a short balance remain for explicit review.
        if proven <= REPAY_EPSILON or abs(free - proven) > max(
            REPAY_EPSILON, proven * Decimal("0.000001")
        ):
            continue
        claim_key = f"engine:residual-cleanup:{sub_account_id}:{symbol}"
        if redis is not None:
            try:
                claimed = await redis.set(claim_key, "1", ex=60, nx=True)
            except TypeError:
                # Minimal test doubles and older Redis clients may not expose
                # NX.  The worker loop is single-threaded, so proceed safely.
                claimed = True
            except Exception:
                claimed = True
            if claimed is False:
                continue
        try:
            # Re-read immediately before the write.  A borrow/open request can
            # change the account after the initial snapshot; never sell on a
            # stale zero-debt observation.
            reader = getattr(client, "get_margin_account", None)
            latest = await reader() if callable(reader) else margin_account
            latest_row = next(
                (item for item in latest.get("userAssets", [])
                 if str(item.get("asset") or "").upper() == asset),
                None,
            )
            if latest_row is None:
                continue
            latest_debt = Decimal(str(latest_row.get("borrowed", "0") or 0)) + Decimal(
                str(latest_row.get("interest", "0") or 0)
            )
            latest_free = Decimal(str(latest_row.get("free", "0") or 0))
            if latest_debt > REPAY_EPSILON or abs(latest_free - proven) > max(
                REPAY_EPSILON, proven * Decimal("0.000001")
            ):
                continue
            sold, note = await sell_residual_spot(
                client, symbol, asset, proven,
            )
            if sold > REPAY_EPSILON:
                cleaned += 1
                db = SessionLocal()
                try:
                    # Account-level cleanup is intentionally not assigned to
                    # one position; provenance is tracked by symbol/account.
                    from engine.trading.order_executor import _log_trade
                    _log_trade(
                        db, None, sub_account_id, "SPOT_RESIDUAL_SELL", symbol,
                        side="SELL", quantity=sold, status="SUCCESS",
                    )
                    db.commit()
                finally:
                    db.close()
                logger.info(
                    "Automatic terminal residual cleanup %s acct%s qty=%s",
                    symbol, sub_account_id, sold,
                )
            elif note:
                # A residual below Binance's spot market minimum cannot be
                # sold.  It may be converted through the dust endpoint, but
                # only after proving the margin quantity is the complete
                # terminal-position remainder and the spot wallet has no same
                # asset balance.  This prevents sweeping normal holdings.
                converted = await _convert_proven_dust_residual(
                    client, symbol, asset, proven, redis, sub_account_id,
                )
                if not converted:
                    logger.info(
                        "Automatic terminal residual cleanup deferred %s acct%s: %s",
                        symbol, sub_account_id, note,
                    )
        except Exception as exc:
            logger.warning(
                "Automatic terminal residual cleanup failed %s acct%s: %s",
                symbol, sub_account_id, exc,
            )
    return cleaned


async def _convert_proven_dust_residual(
    client, symbol: str, asset: str, proven: Decimal, redis, sub_account_id: int,
) -> bool:
    """Convert a sub-minimum margin remainder only with wallet isolation.

    Binance's dust API is asset-wide for the wallet it receives.  Therefore a
    margin remainder is eligible only when the corresponding spot wallet is
    empty and the live margin balance still equals the proven quantity.
    """
    try:
        latest = await client.get_margin_account()
        row = next((x for x in latest.get("userAssets", [])
                    if str(x.get("asset") or "").upper() == asset), None)
        if row is None:
            return False
        debt = Decimal(str(row.get("borrowed", "0") or 0)) + Decimal(
            str(row.get("interest", "0") or 0)
        )
        free = Decimal(str(row.get("free", "0") or 0))
        if debt > REPAY_EPSILON or abs(free - proven) > max(
            REPAY_EPSILON, proven * Decimal("0.000001")
        ):
            return False
        # Recheck ownership immediately before moving funds.  A new borrow or
        # open may have been persisted after the outer reconciliation snapshot.
        if await asyncio.to_thread(_has_active_position, sub_account_id, symbol):
            return False
        spot = await client.get_spot_account()
        spot_row = next((x for x in spot.get("balances", [])
                         if str(x.get("asset") or "").upper() == asset), None)
        if spot_row and (
            Decimal(str(spot_row.get("free", "0") or 0))
            + Decimal(str(spot_row.get("locked", "0") or 0))
        ) > REPAY_EPSILON:
            return False
        price = await client.ws_spot_price(symbol, "bid")
        if Decimal(str(price)) <= 0 or free * Decimal(str(price)) >= Decimal("5"):
            return False
        from engine.fund.residual_conversion import convert_margin_residual_to_bnb
        result = await convert_margin_residual_to_bnb(client, asset, free)
        conversion = result.get("conversion") or {}
        db = SessionLocal()
        try:
            from engine.trading.order_executor import _log_trade
            _log_trade(
                db, None, sub_account_id, "DUST_CONVERSION", symbol,
                side="CONVERT", quantity=free, status="SUCCESS",
            )
            db.commit()
        finally:
            db.close()
        logger.info(
            "Automatic dust conversion %s acct%s qty=%s tx=%s",
            symbol, sub_account_id, free,
            conversion.get("tranId") or conversion.get("transId"),
        )
        return True
    except Exception as exc:
        logger.warning("Automatic dust conversion deferred %s acct%s: %s", symbol, sub_account_id, exc)
        return False


async def run_terminal_residual_scan(
    client,
    redis,
    sub_account_id: int,
    notifier,
    account_note: str,
    symbols: set[str] | None = None,
) -> int:
    """Run the account-level residual cleanup on its deliberate cadence.

    The naked-short guard runs at sub-second cadence so it can stop an orphan
    borrow quickly.  Dust conversion is an asset-wide Binance operation and
    therefore must not run from that hot loop.  This entry point performs one
    fresh balance read and invokes the same provenance gates at the scheduled
    (30 minute) cadence used by the worker.  It never sweeps arbitrary wallet
    balances and returns the number of market residuals cleaned.
    """
    try:
        margin_account = await client.get_margin_account()
    except Exception as exc:
        logger.debug("terminal residual scan balance read failed %s: %s", account_note, exc)
        return 0
    return await _cleanup_terminal_residuals(
        client, redis, sub_account_id, margin_account, notifier, account_note,
        symbols=symbols,
    )


async def _remediate(client, symbol, asset, debt, free, price, ma,
                     sub_account_id, notifier, account_note):
    """收口:free<debt 时用 USDT 买回缺口(NO_SIDE_EFFECT)→ 还币。USDT 不足则只告警人工干预。"""
    _, _, usdt_free = (Decimal("0"), Decimal("0"),
                       Decimal(str(next((x.get("free", "0") for x in ma.get("userAssets", [])
                                         if x.get("asset") == "USDT"), "0") or 0)))
    need = max(Decimal("0"), debt - free)
    buy_block_reason = None
    if need > 0:
        flt = await client._get_spot_filters(symbol)
        if not isinstance(flt, dict):
            flt = {}
        try:
            step = Decimal(str(flt.get("step") or 0))
        except (TypeError, ValueError, InvalidOperation):
            step = Decimal("0")
        raw_min_notional = flt.get("min_notional")
        if not raw_min_notional:
            for filter_name in ("NOTIONAL", "MIN_NOTIONAL"):
                nested = flt.get(filter_name)
                if isinstance(nested, dict) and nested.get("minNotional") is not None:
                    raw_min_notional = nested.get("minNotional")
                    break
        try:
            min_notional = Decimal(str(raw_min_notional or 0))
        except (TypeError, ValueError, InvalidOperation):
            min_notional = Decimal("0")
        if (
            not step.is_finite()
            or step <= 0
            or not min_notional.is_finite()
            or min_notional <= 0
        ):
            buy_block_reason = "Binance 最小名义额或数量精度不可用"
        else:
            buy_qty = (Decimal(math.ceil(need / step)) + 2) * step   # 取整 + 2 档缓冲(覆盖利息累积/精度)
            buy_notional = buy_qty * price
            cost = buy_notional * Decimal("1.01")
            if buy_notional < min_notional:
                buy_block_reason = (
                    f"缺口买回名义约 {buy_notional:.4f}U，低于 Binance 最小下单额 "
                    f"{min_notional}U"
                )
            elif cost > usdt_free:
                buy_block_reason = (
                    f"买回约需 {cost:.2f}U，可用 USDT 仅 {usdt_free:.2f}"
                )

        if buy_block_reason:
            logger.warning(f"naked short remediate acct{sub_account_id} {symbol}: 买回受阻 "
                           f"({buy_block_reason}),先偿还可用现币并保留剩余债务")
            try:
                await notifier.notify_error(
                    account_note, f"裸空收口需人工干预 {symbol}",
                    f"需买回 {need} {asset}(≈{(need*price):.4f}U)；{buy_block_reason}；"
                    "未发送无效买单，将先偿还账户已有可用币，剩余债务继续保留并重试",
                )
            except Exception:
                logger.debug("naked buy-block notification failed", exc_info=True)
        else:
            await client.spot_market_buy_qty(symbol, buy_qty, is_margin=True)
            await asyncio.sleep(4)   # 容忍杠杆户秒级读-写结算延迟(买回后 free 不会立即可见)

    # 还币:重读权威债务+free,按 min 全额还,-3041 退避重试
    ma2 = await client.get_margin_account()
    b2, i2, f2 = _asset_state(ma2, asset)
    repay = min(b2 + i2, f2)
    if repay > 0:
        for attempt in range(5):
            try:
                await client.margin_repay(asset, repay)
                break
            except BinanceAPIError as e:
                if getattr(e, "api_code", None) == -3041 and attempt < 4:
                    repay *= Decimal("0.999")
                    continue
                raise
    await asyncio.sleep(3)
    ma3 = await client.get_margin_account()
    b3, i3, _ = _asset_state(ma3, asset)
    final_debt = b3 + i3
    logger.info(f"naked short remediated acct{sub_account_id} {symbol}: debt {debt} -> {final_debt}")
    if final_debt > REPAY_EPSILON:
        if not buy_block_reason:
            await notifier.notify_error(
                account_note,
                f"裸空收口仍有残债 {symbol}",
                f"Binance 权威残债 {final_debt} {asset}，未标记为已收口，将继续对账",
            )
        return False
    try:
        await notifier.notify_naked_short(account_note, symbol, final_debt, Decimal("0"), None, remediated=True)
    except Exception:
        pass
    return True
