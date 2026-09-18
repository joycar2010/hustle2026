"""Weather ensemble data used by the Polymarket weather strategy.

The forecast is intentionally kept separate from market parsing and order
execution. This makes it possible to backtest the probability model without
touching the wallet or CLOB code.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timezone
import logging
import statistics
import threading
import time
from typing import Optional

import requests

from bot.config import Config

log = logging.getLogger("bot.weather_data")


CITY_CONFIG: dict[str, dict[str, object]] = {
    "nyc": {
        "name": "New York City",
        "lat": 40.7128,
        "lon": -74.0060,
        "station": "KNYC",
    },
    "chicago": {
        "name": "Chicago",
        "lat": 41.8781,
        "lon": -87.6298,
        "station": "KORD",
    },
    "miami": {
        "name": "Miami",
        "lat": 25.7617,
        "lon": -80.1918,
        "station": "KMIA",
    },
    "los_angeles": {
        "name": "Los Angeles",
        "lat": 34.0522,
        "lon": -118.2437,
        "station": "KLAX",
    },
    "denver": {
        "name": "Denver",
        "lat": 39.7392,
        "lon": -104.9903,
        "station": "KDEN",
    },
}


@dataclass(frozen=True)
class EnsembleForecast:
    city_key: str
    target_date: date
    member_highs: tuple[float, ...]
    member_lows: tuple[float, ...]
    fetched_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )

    @property
    def high_mean(self) -> float:
        return statistics.mean(self.member_highs)

    @property
    def high_std(self) -> float:
        return statistics.stdev(self.member_highs) if len(self.member_highs) > 1 else 0.0

    @property
    def low_mean(self) -> float:
        return statistics.mean(self.member_lows)

    @property
    def low_std(self) -> float:
        return statistics.stdev(self.member_lows) if len(self.member_lows) > 1 else 0.0

    @property
    def member_count(self) -> int:
        return max(len(self.member_highs), len(self.member_lows))

    def values(self, metric: str) -> tuple[float, ...]:
        if metric == "low":
            return self.member_lows
        return self.member_highs

    def probability_above(self, metric: str, threshold_f: float) -> float:
        values = self.values(metric)
        if not values:
            return 0.5
        return sum(value > threshold_f for value in values) / len(values)

    def probability_below(self, metric: str, threshold_f: float) -> float:
        values = self.values(metric)
        if not values:
            return 0.5
        return sum(value < threshold_f for value in values) / len(values)

    def probability_between(
        self,
        metric: str,
        low_f: float,
        high_f: float,
    ) -> float:
        values = self.values(metric)
        if not values:
            return 0.5
        return sum(low_f <= value < high_f for value in values) / len(values)


_CACHE: dict[tuple[str, date], tuple[float, EnsembleForecast]] = {}
_CACHE_LOCK = threading.Lock()


def _cached(
    key: tuple[str, date],
    ttl_sec: float,
) -> Optional[EnsembleForecast]:
    with _CACHE_LOCK:
        item = _CACHE.get(key)
    if item is None:
        return None
    cached_at, forecast = item
    if time.time() - cached_at > max(ttl_sec, 0.0):
        return None
    return forecast


def _parse_members(
    daily: dict,
    prefix: str,
) -> tuple[float, ...]:
    values: list[float] = []
    for key, raw_values in daily.items():
        if not key.startswith(prefix) or not isinstance(raw_values, list):
            continue
        if not raw_values or raw_values[0] is None:
            continue
        try:
            values.append(float(raw_values[0]))
        except (TypeError, ValueError):
            continue
    return tuple(values)


def fetch_ensemble_forecast(
    cfg: Config,
    city_key: str,
    target_date: date,
) -> EnsembleForecast:
    """Fetch one daily GFS ensemble forecast from Open-Meteo.

    Open-Meteo returns a control forecast plus member columns. We keep the
    raw member distribution rather than collapsing it to a single point
    estimate, because the trading decision needs a bucket probability.
    """
    if city_key not in CITY_CONFIG:
        raise ValueError(f"unknown weather city: {city_key}")

    key = (city_key, target_date)
    cached = _cached(key, cfg.weather_forecast_cache_ttl_sec)
    if cached is not None:
        return cached

    city = CITY_CONFIG[city_key]
    params = {
        "latitude": city["lat"],
        "longitude": city["lon"],
        "daily": "temperature_2m_max,temperature_2m_min",
        "temperature_unit": "fahrenheit",
        "start_date": target_date.isoformat(),
        "end_date": target_date.isoformat(),
        "models": "gfs_seamless",
    }
    response = requests.get(
        "https://ensemble-api.open-meteo.com/v1/ensemble",
        params=params,
        timeout=20,
    )
    response.raise_for_status()
    daily = response.json().get("daily") or {}
    highs = _parse_members(daily, "temperature_2m_max")
    lows = _parse_members(daily, "temperature_2m_min")
    if not highs and not lows:
        raise RuntimeError(
            f"Open-Meteo returned no ensemble members for {city_key} {target_date}"
        )

    forecast = EnsembleForecast(
        city_key=city_key,
        target_date=target_date,
        member_highs=highs,
        member_lows=lows,
    )
    with _CACHE_LOCK:
        _CACHE[key] = (time.time(), forecast)
    log.info(
        "weather forecast city=%s date=%s high=%.1f+/-%.1f low=%.1f+/-%.1f members=%d",
        city_key,
        target_date,
        forecast.high_mean if highs else float("nan"),
        forecast.high_std if highs else float("nan"),
        forecast.low_mean if lows else float("nan"),
        forecast.low_std if lows else float("nan"),
        forecast.member_count,
    )
    return forecast


def configured_city_keys(cfg: Config) -> list[str]:
    """Return validated city keys from WEATHER_CITIES."""
    keys = [item.strip().lower() for item in cfg.weather_cities.split(",") if item.strip()]
    unknown = [key for key in keys if key not in CITY_CONFIG]
    if unknown:
        raise ValueError(
            f"unknown WEATHER_CITIES={','.join(unknown)}; "
            f"supported={','.join(sorted(CITY_CONFIG))}"
        )
    return list(dict.fromkeys(keys))
