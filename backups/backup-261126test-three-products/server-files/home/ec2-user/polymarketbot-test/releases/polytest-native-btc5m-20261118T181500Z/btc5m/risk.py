"""Position sizing and daily loss circuit breaker."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional
from zoneinfo import ZoneInfo


# Dashboard and user-facing daily figures are defined in Beijing time.  Keep
# the risk circuit breaker on the same civil-day boundary so a worker does not
# remain blocked until UTC midnight (08:00 Beijing) after the UI has rolled.
BEIJING_TZ = ZoneInfo("Asia/Shanghai")


def beijing_day_key(now: Optional[datetime] = None) -> str:
    """Return the YYYY-MM-DD key for the Beijing civil day."""
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    return current.astimezone(BEIJING_TZ).date().isoformat()


def beijing_day_start_ts(now: Optional[datetime] = None) -> float:
    """Return the UTC timestamp for Beijing midnight containing ``now``."""
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    local = current.astimezone(BEIJING_TZ)
    start = local.replace(hour=0, minute=0, second=0, microsecond=0)
    return start.astimezone(timezone.utc).timestamp()


@dataclass
class RiskState:
    day_key: str = ""
    realized_pnl_usd: float = 0.0
    open_positions: int = 0
    halted: bool = False
    halt_reason: str = ""

    def roll_day(self) -> None:
        today = beijing_day_key()
        if self.day_key != today:
            self.day_key = today
            self.realized_pnl_usd = 0.0
            self.halted = False
            self.halt_reason = ""


def allowed_to_trade(
    *,
    daily_loss_limit_usd: float,
    max_open_positions: int,
    risk: RiskState,
) -> Optional[str]:
    risk.roll_day()
    if risk.halted:
        return risk.halt_reason or "halted"
    if risk.realized_pnl_usd <= -abs(daily_loss_limit_usd):
        risk.halted = True
        risk.halt_reason = (
            f"daily loss limit hit pnl={risk.realized_pnl_usd:.2f} "
            f"limit=-{abs(daily_loss_limit_usd):.2f}"
        )
        return risk.halt_reason
    if risk.open_positions >= max_open_positions:
        return f"max open positions ({max_open_positions}) reached"
    return None


def note_fill(risk: RiskState, notional_usd: float) -> None:
    risk.open_positions += 1
    # notional tracked only for open count; pnl booked on resolve
    _ = notional_usd


def note_resolution(risk: RiskState, pnl_usd: float) -> None:
    risk.roll_day()
    risk.realized_pnl_usd += pnl_usd
    risk.open_positions = max(risk.open_positions - 1, 0)
