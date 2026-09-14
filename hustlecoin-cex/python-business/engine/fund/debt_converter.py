"""残留负债清理(全仓负债转换间隔 debt_convert_interval_sec)。

清掉子账户里「无对应持仓的小额非 USDT 币种欠款」——即开/平/还过程中残留的尾单债
(如外部平仓/部分成交后欠一点点币)。每个 base 资产:
  · 仅当该 base **无任何进行中持仓**(排除尾单=合法持仓债)才处理;
  · 若 margin 已持有该币 free ≥ 欠款 → 直接 margin_repay(纯还债,无交易,零风险);
  · 否则缺口很小(名义 < 阈值)时,用现有 USDT 现货买回缺口再还(限小额);USDT 不足则跳过。

安全:只清小额、只清无持仓、不自动借 USDT;所有异常吞掉(不崩 worker)。
价格取 spread_feed(spot_ask);无行情的币跳过(无法估值/买回,留人工)。
"""
from __future__ import annotations

import logging
from decimal import Decimal, InvalidOperation

from app.db.session import SessionLocal
from engine.models import Position

logger = logging.getLogger(__name__)

# A debt conversion pass is allowed to touch only balances that have no
# lifecycle owner. Every status other than these two explicit terminal states
# remains protected, including OPEN, PENDING_REPAY, and unresolved/transition
# states from an interrupted borrow or hedge.
_TERMINAL_POSITION_STATUSES = ("CLOSED", "FAILED")
_SKIP_ASSETS = {"USDT", "BNB"}
_MAX_DUST_USDT = Decimal("50")   # 单币残留债清理名义上限(超过视为非尾单,不自动清)


async def _spot_min_notional(client, symbol: str) -> Decimal | None:
    """Read the exchange minimum for a market buy without guessing an order.

    Binance has exposed this constraint as both ``NOTIONAL`` and the older
    ``MIN_NOTIONAL`` filter.  A missing/invalid value is treated as unknown so
    the residual cleaner fails closed instead of submitting a request that is
    likely to be rejected with ``-1013``.
    """
    getter = getattr(client, "_get_spot_filters", None)
    if not callable(getter):
        return None
    try:
        filters = await getter(symbol)
    except Exception:
        return None
    if not isinstance(filters, dict):
        return None
    raw = filters.get("min_notional")
    if raw is None:
        # Accept the exchange spelling when a lightweight client forwards the
        # raw filter map without normalizing it first.
        raw = filters.get("minNotional")
    if raw is None:
        for name in ("NOTIONAL", "MIN_NOTIONAL"):
            entry = filters.get(name)
            if isinstance(entry, dict):
                entry = entry.get("minNotional")
            if entry is not None:
                raw = entry
                break
    try:
        value = Decimal(str(raw))
    except (TypeError, ValueError, InvalidOperation):
        return None
    return value if value.is_finite() and value > 0 else None


def _bases_with_active_position(sub_id: int) -> set[str]:
    db = SessionLocal()
    try:
        rows = db.query(Position.base_asset).filter(
            Position.sub_account_id == sub_id,
            # Any non-terminal row, including an unresolved borrow submission,
            # owns the asset. Debt conversion must never alter account-level
            # principal while that ownership is unresolved.
            Position.status.notin_(_TERMINAL_POSITION_STATUSES),
        ).distinct().all()
        return {r[0] for r in rows if r[0]}
    finally:
        db.close()


async def run_debt_convert(client, sub_id, spread_feed, notifier, account_note) -> None:
    try:
        mi = await client.get_margin_account()
    except Exception as e:
        logger.debug(f"debt_convert {account_note}: get_margin_account failed: {e}")
        return
    busy = await _safe_bases(sub_id)

    for a in mi.get("userAssets", []):
        asset = a.get("asset")
        if asset in _SKIP_ASSETS:
            continue
        borrowed = Decimal(str(a.get("borrowed", "0"))) + Decimal(str(a.get("interest", "0")))
        if borrowed <= 0:
            continue
        if asset in busy:
            continue  # 有进行中持仓 = 合法借币债,不动

        symbol = f"{asset}USDT"
        sp = spread_feed.get_symbol(symbol) if spread_feed else None
        price = Decimal(str(sp.spot_ask)) if (sp and getattr(sp, "spot_ask", 0)) else None
        if price is None or price <= 0:
            continue  # 无行情,无法估值/买回 → 留人工

        notional = borrowed * price
        if notional > _MAX_DUST_USDT:
            continue  # 超小额上限,不自动清(防误清大额债)

        free_coin = Decimal(str(a.get("free", "0")))
        try:
            if free_coin >= borrowed:
                # 已持有足额 → 直接还(纯还债,无交易)
                await client.margin_repay(asset, borrowed)
                await notifier.send("残留负债清理",
                                    f"账户: {account_note}\n{asset} 残留欠款 {borrowed} 已用持有币直接还清",
                                    throttle_key=f"debtconv:{account_note}:{asset}")
                logger.info(f"debt_convert {account_note}: repaid {asset} {borrowed} from held balance")
                continue
            # 缺口小额 → 用现有 USDT 买回缺口再还
            shortfall = borrowed - free_coin
            usdt_free = next((Decimal(str(x.get("free", "0"))) for x in mi.get("userAssets", [])
                              if x.get("asset") == "USDT"), Decimal("0"))
            if shortfall * price > usdt_free:
                # Repay the portion already in the account even when there
                # is not enough USDT to buy the remaining gap.  This reduces
                # debt without creating a rejected market order.
                if free_coin > 0:
                    try:
                        await client.margin_repay(asset, free_coin)
                    except Exception as exc:
                        logger.debug(
                            "debt_convert %s: free-balance repay with low USDT failed: %s",
                            account_note, exc,
                        )
                continue  # USDT 不足,不自动借,跳过(留人工/下轮)
            min_notional = await _spot_min_notional(client, symbol)
            if min_notional is None or shortfall * price < min_notional:
                # Do not repeat a market order that Binance will reject.  Any
                # coin already available can still be repaid safely; only the
                # unbuyable tail remains visible for a later/manual cleanup.
                if free_coin > 0:
                    try:
                        await client.margin_repay(asset, free_coin)
                    except Exception as exc:
                        logger.debug(
                            "debt_convert %s: partial free-balance repay failed: %s",
                            account_note, exc,
                        )
                detail = (
                    f"{asset} 缺口名义约 {shortfall * price:.4f}U，"
                    f"Binance 最小下单额未知或为 {min_notional or '未知'}U；未发起买单，剩余债务待人工处理"
                )
                try:
                    await notifier.send(
                        "残留负债等待最小下单额",
                        f"账户: {account_note}\n{detail}",
                        throttle_key=f"debtconv:minnotional:{account_note}:{asset}",
                    )
                except Exception:
                    pass
                continue
            await client.spot_market_buy_qty(symbol, shortfall)
            await client.margin_repay(asset, borrowed)
            await notifier.send("残留负债清理",
                                f"账户: {account_note}\n{asset} 残留欠款 {borrowed}(名义≈{notional:.2f}U)买回补足并还清",
                                throttle_key=f"debtconv:{account_note}:{asset}")
            logger.info(f"debt_convert {account_note}: bought {shortfall} {asset} + repaid {borrowed}")
        except Exception as e:
            logger.debug(f"debt_convert {account_note}: clear {asset} failed: {e}")


async def _safe_bases(sub_id: int):
    import asyncio
    return await asyncio.to_thread(_bases_with_active_position, sub_id)
