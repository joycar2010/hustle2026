"""Single source of truth for spread threshold direction."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any


AUTO_PUSH_HYSTERESIS_GAP = Decimal("0.05")


def _as_finite_decimal(value: Any) -> Decimal | None:
    """Normalize DB/API numeric values without mixed-type or NaN failures."""
    if value is None:
        return None
    try:
        normalized = Decimal(str(value).strip())
    except (InvalidOperation, TypeError, ValueError):
        return None
    return normalized if normalized.is_finite() else None


def upward_reached(value: Any, threshold: Any) -> bool:
    """An upward gate is reached when value is at least its threshold."""
    value_decimal = _as_finite_decimal(value)
    threshold_decimal = _as_finite_decimal(threshold)
    return (
        value_decimal is not None
        and threshold_decimal is not None
        and value_decimal >= threshold_decimal
    )


def downward_reached(value: Any, threshold: Any) -> bool:
    """A convergence gate is reached when value is at most its threshold."""
    value_decimal = _as_finite_decimal(value)
    threshold_decimal = _as_finite_decimal(threshold)
    return (
        value_decimal is not None
        and threshold_decimal is not None
        and value_decimal <= threshold_decimal
    )


def open_close_conflict(open_threshold: Any, close_threshold: Any) -> bool:
    """Equal or inverted gates can satisfy both open and close transitions."""
    open_decimal = _as_finite_decimal(open_threshold)
    close_decimal = _as_finite_decimal(close_threshold)
    return (
        open_decimal is not None
        and close_decimal is not None
        and open_decimal <= close_decimal
    )


def effective_remove_threshold(
    remove_threshold: Any,
    auto_push_threshold: Any,
) -> Decimal | None:
    """Return an exit line with a real gap below automatic entry.

    Historical rows may contain an inverted pair such as entry ``0.8`` and
    removal ``1.4``.  Equal entry/exit lines still chatter around one market
    tick, so invalid pairs are bounded to at least 0.05 percentage points (or
    half the entry value for very small positive entries) below entry.
    """
    remove_value = _as_finite_decimal(remove_threshold)
    push_value = _as_finite_decimal(auto_push_threshold)
    if remove_value is None:
        return None
    if push_value is None or push_value <= 0 or remove_value < push_value:
        return remove_value
    gap = min(AUTO_PUSH_HYSTERESIS_GAP, push_value / Decimal("2"))
    return push_value - gap


def push_remove_conflict(
    auto_push_threshold: Any,
    remove_threshold: Any,
) -> bool:
    """Whether an enabled automatic entry line lacks a lower exit line."""
    push_value = _as_finite_decimal(auto_push_threshold)
    remove_value = _as_finite_decimal(remove_threshold)
    return (
        push_value is not None
        and push_value > 0
        and remove_value is not None
        and remove_value >= push_value
    )


# Compatibility names used by the deployed canary worker.  Keeping these
# aliases in the shared module lets rolling deployments mix old and new
# workers without changing the threshold direction.
def borrow_reached(value: Any, threshold: Any) -> bool:
    return upward_reached(value, threshold)


def open_reached(value: Any, threshold: Any) -> bool:
    return upward_reached(value, threshold)


def reached_up(value: Any, threshold: Any) -> bool:
    return upward_reached(value, threshold)


def close_reached(value: Any, threshold: Any) -> bool:
    return downward_reached(value, threshold)
