"""Safety checks for explicit sub-minimum residual conversion.

Binance's ``asset/dust`` endpoint is asset-wide in the spot wallet.  The
caller must therefore prove that the requested margin residual is attributable
to a completed Coin position and that no pre-existing spot balance of the same
asset would be swept along with it.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation


DUST_USDT_THRESHOLD = Decimal("5")
EPSILON = Decimal("0.00000001")
TERMINAL_POSITION_STATUSES = frozenset({"CLOSED", "FAILED", "CANCELLED", "CANCELED"})


def decimal(value: object, default: Decimal = Decimal("0")) -> Decimal:
    try:
        result = Decimal(str(value or "0"))
    except (TypeError, ValueError, InvalidOperation):
        return default
    return result if result.is_finite() else default


def is_terminal_position_status(value: object) -> bool:
    """Return whether a position no longer represents an active workflow."""
    return str(value or "").strip().upper() in TERMINAL_POSITION_STATUSES


def proven_residual_from_position(spot_buy_qty: object, repay_qty: object) -> Decimal:
    """Return the quantity left after the recorded repayment for one row."""
    bought = decimal(spot_buy_qty)
    repaid = decimal(repay_qty)
    if bought <= EPSILON or repaid < 0:
        return Decimal("0")
    return max(Decimal("0"), bought - repaid)


def proven_residual_for_position(position: object) -> Decimal:
    """Return residual only when the row contains close provenance.

    A CLOSED row can also be an accounting row created by a borrow-only or
    manual repayment.  Those rows have no buy-back order and must not be used
    to authorize an asset-wide Binance dust conversion.
    """
    if str(getattr(position, "status", "") or "").strip().upper() != "CLOSED":
        return Decimal("0")
    if not str(getattr(position, "spot_buy_order_id", "") or "").strip():
        return Decimal("0")
    repaid = decimal(getattr(position, "repay_qty", None))
    if repaid <= EPSILON:
        return Decimal("0")
    return proven_residual_from_position(
        getattr(position, "spot_buy_qty", None),
        repaid,
    )


def validate_dust_conversion(
    *,
    free_margin: object,
    proven_quantity: object,
    spot_free: object,
    spot_locked: object,
    price: object,
    min_notional: object = DUST_USDT_THRESHOLD,
) -> tuple[bool, str]:
    """Fail closed unless an exact, isolated residual can be swept safely."""
    free = decimal(free_margin)
    proven = max(Decimal("0"), decimal(proven_quantity))
    spot_total = decimal(spot_free) + decimal(spot_locked)
    px = decimal(price)
    threshold = decimal(min_notional, DUST_USDT_THRESHOLD)
    if free <= EPSILON:
        return False, "杠杆账户没有可兑换的残留"
    if proven <= EPSILON or free > proven + EPSILON:
        return False, "无法证明残留完全来自已结束仓位，未执行资产级兑换"
    if spot_total > EPSILON:
        return False, "现货钱包已有同资产余额，为避免资产级 dust 连带转换，未执行"
    if px <= 0:
        return False, "无法取得实时价格，未执行残留兑换"
    if free * px >= threshold:
        return False, f"残留名义价值不低于 {threshold}U，请使用卖回而非 dust 兑换"
    return True, "ok"
