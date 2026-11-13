"""Position sizing and daily loss circuit breaker."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional


@dataclass
class RiskState:
    day_key: str = ""
    realized_pnl_usd: float = 0.0
    open_positions: int = 0
    halted: bool = False
    halt_reason: str = ""

    def roll_day(self) -> None:
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
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
