"""Conservative binary sports strategy; intended for paper simulation only."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from bot.sports_data import SportsDataSource, estimate_probabilities
from bot.sports_markets import SportsMarket


def _cfg(cfg: Any, name: str, default: Any) -> Any:
    return getattr(cfg, name, default)


@dataclass(frozen=True)
class SportsSignal:
    market: SportsMarket
    outcome: str
    token_id: str
    model_probability: float
    market_price: float
    edge: float
    source: str
    reason: str

    @property
    def actionable(self) -> bool:
        return self.edge >= 0.0


def build_signal(cfg_or_market: Any, market_or_source: SportsMarket | SportsDataSource | None = None, source: SportsDataSource | None = None) -> SportsSignal:
    """Build a signal; accepts ``(market, source)`` or ``(cfg, market, source)``."""
    if isinstance(cfg_or_market, SportsMarket):
        market = cfg_or_market
        if market_or_source is not None and not isinstance(market_or_source, SportsMarket):
            source = market_or_source  # type: ignore[assignment]
    else:
        if not isinstance(market_or_source, SportsMarket):
            raise TypeError("build_signal expects a SportsMarket")
        market = market_or_source
    probabilities, source_name = estimate_probabilities(market, source)
    idx = 0 if probabilities[market.outcomes[0]] - market.prices[0] >= probabilities[market.outcomes[1]] - market.prices[1] else 1
    outcome = market.outcomes[idx]
    model = probabilities[outcome]
    price = market.prices[idx]
    edge = model - price
    reason = f"{market.sport}/{market.league or 'unknown'} {market.event_name} | {outcome} model={model:.1%} price={price:.1%} edge={edge:+.1%} source={source_name}"
    return SportsSignal(market, outcome, market.token_ids[idx], model, price, edge, source_name, reason)


def signal_is_allowed(cfg: Any, signal: SportsSignal, *, exposure_usd: float = 0.0) -> tuple[bool, str]:
    if signal.market_price < float(_cfg(cfg, "sports_min_entry_price", 0.05)) or signal.market_price > float(_cfg(cfg, "sports_max_entry_price", 0.95)):
        return False, "price outside configured range"
    if signal.edge < float(_cfg(cfg, "sports_min_edge", 0.05)):
        return False, "edge below minimum"
    max_exposure = float(_cfg(cfg, "sports_max_exposure_usd", 5.0))
    if exposure_usd >= max_exposure:
        return False, "paper exposure cap reached"
    return True, "ok"
