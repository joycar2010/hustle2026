"""Independent sports paper service.

This module intentionally has no live path.  It records decisions and
simulated orders in memory (or through a caller supplied callback) and never
imports the CLOB order placement functions.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import logging
from typing import Any, Callable

from bot.sports_data import MarketImpliedSource, SportsDataSource
from bot.sports_markets import SportsMarket, fetch_sports_markets
from bot.sports_strategy import SportsSignal, build_signal, signal_is_allowed

log = logging.getLogger("bot.sports_paper")


@dataclass(frozen=True)
class PaperDecision:
    timestamp: str
    market_key: str
    slug: str
    action: str
    reason: str
    edge: float
    source: str


@dataclass(frozen=True)
class PaperOrder:
    timestamp: str
    market_key: str
    slug: str
    token_id: str
    outcome: str
    price: float
    size: float
    notional_usd: float
    status: str = "paper_simulated"


class SportsPaperService:
    """Discover, score and simulate sports markets without live side effects."""

    mode = "paper"

    def __init__(self, cfg: Any, *, data_source: SportsDataSource | None = None, market_fetcher: Callable[..., list[SportsMarket]] = fetch_sports_markets):
        self.cfg = cfg
        self.data_source = data_source or MarketImpliedSource()
        self.market_fetcher = market_fetcher
        self.decisions: list[PaperDecision] = []
        self.orders: list[PaperOrder] = []
        self.last_markets: list[SportsMarket] = []
        self._confirmations: dict[str, int] = {}

    def run_once(self) -> dict[str, Any]:
        if not bool(getattr(self.cfg, "sports_enabled", False)):
            return self.snapshot(status="disabled")
        self.last_markets = self.market_fetcher(self.cfg)
        exposure = sum(order.notional_usd for order in self.orders if order.status == "paper_simulated")
        for market in self.last_markets:
            signal = build_signal(market, self.data_source)
            allowed, why = signal_is_allowed(self.cfg, signal, exposure_usd=exposure)
            confirmation_required = max(int(getattr(self.cfg, "sports_confirm_checks", 1)), 1)
            if signal.edge >= 0:
                self._confirmations[market.market_key] = self._confirmations.get(market.market_key, 0) + 1
            else:
                self._confirmations[market.market_key] = 0
            if allowed and self._confirmations[market.market_key] < confirmation_required:
                allowed = False
                why = f"confirmation {self._confirmations[market.market_key]}/{confirmation_required}"
            now = datetime.now(timezone.utc).isoformat()
            self.decisions.append(PaperDecision(now, market.market_key, market.slug, "PAPER_BUY" if allowed else "SKIP_SPORTS", f"{signal.reason}; {why}", signal.edge, signal.source))
            if not allowed:
                continue
            if any(order.market_key == market.market_key for order in self.orders):
                continue
            remaining = max(float(getattr(self.cfg, "sports_max_exposure_usd", 5.0)) - exposure, 0.0)
            size = min(float(getattr(self.cfg, "sports_order_size", 1.0)), remaining / max(signal.market_price, 1e-9))
            if size <= 0:
                continue
            notional = size * signal.market_price
            self.orders.append(PaperOrder(now, market.market_key, market.slug, signal.token_id, signal.outcome, signal.market_price, size, notional))
            exposure += notional
        return self.snapshot(status="ok")

    def snapshot(self, *, status: str = "ok") -> dict[str, Any]:
        return {
            "enabled": bool(getattr(self.cfg, "sports_enabled", False)),
            "mode": self.mode,
            "status": status,
            "markets": [self.market_summary(market) for market in self.last_markets],
            "decisions": [asdict(item) for item in self.decisions[-50:]],
            "orders": [asdict(item) for item in self.orders[-50:]],
            "paper_only": True,
            "live_orders": False,
        }

    @staticmethod
    def market_summary(market: SportsMarket) -> dict[str, Any]:
        return {
            "market_key": market.market_key,
            "slug": market.slug,
            "sport": market.sport,
            "league": market.league,
            "event_name": market.event_name,
            "question": market.question,
            "outcomes": list(market.outcomes),
            "prices": list(market.prices),
            "clob_token_ids": list(market.token_ids),
            "neg_risk": market.neg_risk,
            "tick_size": market.tick_size,
            "volume": market.volume,
            "liquidity": market.liquidity,
            "event_start_ts": market.event_start_ts,
            "end_ts": market.end_ts,
            "settlement": asdict(market.settlement),
        }


def run_cycle(cfg: Any, *, live: bool = False, **_: Any) -> dict[str, Any]:
    """Run one sports cycle; ``live=True`` is rejected as a safety invariant."""
    if live:
        raise ValueError("sports module is paper-only; live orders are not supported")
    return SportsPaperService(cfg).run_once()
