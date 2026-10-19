"""Pluggable, read-only sports probability sources for paper mode."""
from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any, Mapping, Protocol

from bot.sports_markets import SportsMarket


class SportsDataSource(Protocol):
    name: str

    def probabilities(self, market: SportsMarket) -> Mapping[str, float] | None:
        """Return outcome -> probability, or None when no model is available."""


@dataclass(frozen=True)
class MarketImpliedSource:
    """Fallback source using normalized CLOB prices (no external requests)."""

    name: str = "market_implied"

    def probabilities(self, market: SportsMarket) -> Mapping[str, float]:
        total = sum(market.prices)
        if total <= 0:
            return {market.outcomes[0]: 0.5, market.outcomes[1]: 0.5}
        return {market.outcomes[0]: market.prices[0] / total, market.outcomes[1]: market.prices[1] / total}


@dataclass(frozen=True)
class StaticSportsDataSource:
    values: Mapping[str, Mapping[str, float]]
    name: str = "static"

    def probabilities(self, market: SportsMarket) -> Mapping[str, float] | None:
        return self.values.get(market.market_key) or self.values.get(market.slug)


def poisson_win_probability(lambda_for: float, lambda_against: float, max_goals: int = 12) -> float:
    """Approximate P(team-for wins), useful for soccer/hockey priors."""
    lf, la = max(float(lambda_for), 0.0), max(float(lambda_against), 0.0)
    p_for = [math.exp(-lf) * lf**k / math.factorial(k) for k in range(max_goals + 1)]
    p_against = [math.exp(-la) * la**k / math.factorial(k) for k in range(max_goals + 1)]
    return max(0.0, min(1.0, sum(p_for[i] * p_against[j] for i in range(max_goals + 1) for j in range(i))))


def estimate_probabilities(market: SportsMarket, source: SportsDataSource | None = None) -> tuple[dict[str, float], str]:
    source = source or MarketImpliedSource()
    values = source.probabilities(market)
    if not values:
        values = MarketImpliedSource().probabilities(market)
        source_name = "market_implied"
    else:
        source_name = getattr(source, "name", source.__class__.__name__)
    raw = [max(0.0, float(values.get(outcome, 0.0))) for outcome in market.outcomes]
    total = sum(raw)
    if total <= 0:
        raw = [0.5, 0.5]
        total = 1.0
    return {market.outcomes[i]: raw[i] / total for i in range(2)}, source_name

