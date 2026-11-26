"""Probability and value calculations for binary temperature markets."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from bot.config import Config
from bot.weather_data import EnsembleForecast
from bot.weather_markets import WeatherMarket


@dataclass(frozen=True)
class WeatherSignal:
    market: WeatherMarket
    forecast: EnsembleForecast
    model_yes_probability: float
    model_no_probability: float
    market_yes_price: float
    market_no_price: float
    side: str
    token_id: str
    entry_price: float
    edge: float
    confidence: float
    reason: str

    @property
    def actionable(self) -> bool:
        return self.edge > 0.0


def _model_yes_probability(
    market: WeatherMarket,
    forecast: EnsembleForecast,
) -> float:
    if market.kind == "above":
        return forecast.probability_above(market.metric, market.threshold_f)
    if market.kind == "below":
        return forecast.probability_below(market.metric, market.threshold_f)
    if market.upper_threshold_f is None:
        return 0.5
    return forecast.probability_between(
        market.metric,
        market.threshold_f,
        market.upper_threshold_f,
    )


def _metric_stats(
    market: WeatherMarket,
    forecast: EnsembleForecast,
) -> tuple[float, float, tuple[float, ...]]:
    if market.metric == "low":
        return forecast.low_mean, forecast.low_std, forecast.member_lows
    return forecast.high_mean, forecast.high_std, forecast.member_highs


def build_signal(
    cfg: Config,
    market: WeatherMarket,
    forecast: EnsembleForecast,
) -> WeatherSignal:
    model_yes = max(0.02, min(0.98, _model_yes_probability(market, forecast)))
    model_no = 1.0 - model_yes

    yes_edge = model_yes - market.yes_price
    no_edge = model_no - market.no_price
    if yes_edge >= no_edge:
        side = "UP"
        token_id = market.yes_token
        entry_price = market.yes_price
        edge = yes_edge
        model_probability = model_yes
    else:
        side = "DOWN"
        token_id = market.no_token
        entry_price = market.no_price
        edge = no_edge
        model_probability = model_no

    mean, std, members = _metric_stats(market, forecast)
    confidence = max(model_yes, model_no)
    target = (
        f"{market.kind} {market.threshold_f:.1f}F"
        if market.kind != "between"
        else f"{market.threshold_f:.1f}-{(market.upper_threshold_f or 0.0):.1f}F"
    )
    reason = (
        f"{market.city_name} {market.metric} {target} {market.target_date.isoformat()} | "
        f"ensemble={mean:.1f}F+/-{std:.1f}F members={len(members)} | "
        f"model_yes={model_yes:.1%} market_yes={market.yes_price:.1%} | "
        f"trade={side} model={model_probability:.1%} price={entry_price:.1%} "
        f"edge={edge:+.1%} confidence={confidence:.1%}"
    )
    return WeatherSignal(
        market=market,
        forecast=forecast,
        model_yes_probability=model_yes,
        model_no_probability=model_no,
        market_yes_price=market.yes_price,
        market_no_price=market.no_price,
        side=side,
        token_id=token_id,
        entry_price=entry_price,
        edge=edge,
        confidence=confidence,
        reason=reason,
    )


def signal_is_allowed(
    cfg: Config,
    signal: WeatherSignal,
    *,
    entry_price: Optional[float] = None,
    edge: Optional[float] = None,
) -> tuple[bool, str]:
    price = signal.entry_price if entry_price is None else entry_price
    live_edge = signal.edge if edge is None else edge
    _, std, members = _metric_stats(signal.market, signal.forecast)
    if len(members) < 10:
        return False, f"ensemble has only {len(members)} members"
    if std > cfg.weather_max_ensemble_std_f:
        return (
            False,
            f"ensemble std {std:.2f}F > cap {cfg.weather_max_ensemble_std_f:.2f}F",
        )
    if price < cfg.weather_min_entry_price or price > cfg.weather_max_entry_price:
        return (
            False,
            f"entry price {price:.3f} outside "
            f"{cfg.weather_min_entry_price:.3f}-{cfg.weather_max_entry_price:.3f}",
        )
    if live_edge < cfg.weather_min_edge:
        return (
            False,
            f"edge {live_edge:.3f} < min {cfg.weather_min_edge:.3f}",
        )
    return True, "ok"
