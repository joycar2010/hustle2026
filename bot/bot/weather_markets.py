"""Discover and parse binary temperature markets from Polymarket Gamma."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
import json
import logging
import re
from typing import Optional

import requests

from bot.config import Config
from bot.weather_data import CITY_CONFIG

log = logging.getLogger("bot.weather_markets")

CITY_ALIASES = {
    "new york city": "nyc",
    "new york": "nyc",
    "nyc": "nyc",
    "chicago": "chicago",
    "miami": "miami",
    "los angeles": "los_angeles",
    "los angeles county": "los_angeles",
    "la": "los_angeles",
    "denver": "denver",
}

MONTHS = {
    "jan": 1,
    "january": 1,
    "feb": 2,
    "february": 2,
    "mar": 3,
    "march": 3,
    "apr": 4,
    "april": 4,
    "may": 5,
    "jun": 6,
    "june": 6,
    "jul": 7,
    "july": 7,
    "aug": 8,
    "august": 8,
    "sep": 9,
    "sept": 9,
    "september": 9,
    "oct": 10,
    "october": 10,
    "nov": 11,
    "november": 11,
    "dec": 12,
    "december": 12,
}


@dataclass(frozen=True)
class WeatherMarket:
    condition_id: str
    market_id: str
    slug: str
    question: str
    city_key: str
    target_date: date
    metric: str
    kind: str
    threshold_f: float
    upper_threshold_f: Optional[float]
    yes_token: str
    no_token: str
    yes_price: float
    no_price: float
    tick_size: float
    neg_risk: bool
    end_ts: float
    volume: float
    liquidity: float

    @property
    def city_name(self) -> str:
        return str(CITY_CONFIG[self.city_key]["name"])

    @property
    def market_key(self) -> str:
        return self.condition_id or self.market_id or self.slug


def _json_list(value) -> list:
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return []
        return parsed if isinstance(parsed, list) else []
    return []


def _extract_date(text: str) -> Optional[date]:
    now = datetime.now(timezone.utc).date()
    month_pattern = "|".join(sorted(MONTHS, key=len, reverse=True))
    match = re.search(
        rf"\b({month_pattern})\s+(\d{{1,2}})(?:\s*,?\s*(\d{{4}}))?\b",
        text.lower(),
    )
    if match:
        month = MONTHS[match.group(1)]
        day = int(match.group(2))
        year = int(match.group(3)) if match.group(3) else now.year
        try:
            candidate = date(year, month, day)
        except ValueError:
            return None
        if not match.group(3) and candidate < now and (now - candidate).days > 30:
            try:
                candidate = date(year + 1, month, day)
            except ValueError:
                return None
        return candidate

    match = re.search(r"\b(\d{1,2})/(\d{1,2})(?:/(\d{4}))?\b", text)
    if not match:
        return None
    month, day = int(match.group(1)), int(match.group(2))
    year = int(match.group(3)) if match.group(3) else now.year
    try:
        candidate = date(year, month, day)
    except ValueError:
        return None
    if not match.group(3) and candidate < now and (now - candidate).days > 30:
        candidate = date(year + 1, month, day)
    return candidate


def _extract_city(text: str) -> Optional[str]:
    text_lower = text.lower()
    for alias, key in sorted(CITY_ALIASES.items(), key=lambda item: -len(item[0])):
        if re.search(rf"\b{re.escape(alias)}\b", text_lower):
            return key
    return None


def _extract_temperature(text: str) -> Optional[float]:
    match = re.search(
        r"(-?\d+(?:\.\d+)?)\s*(?:\u00b0\s*)?(?:f|fahrenheit)\b",
        text.lower(),
    )
    if match:
        return float(match.group(1))
    match = re.search(r"\b(-?\d+(?:\.\d+)?)\s*degrees?\b", text.lower())
    return float(match.group(1)) if match else None


def _extract_range(text: str) -> Optional[tuple[float, float]]:
    match = re.search(
        r"(-?\d+(?:\.\d+)?)\s*(?:\u00b0\s*)?(?:f)?\s*"
        r"(?:-|to|through)\s*"
        r"(-?\d+(?:\.\d+)?)\s*(?:\u00b0\s*)?(?:f|fahrenheit)?\b",
        text.lower(),
    )
    if not match:
        return None
    low, high = float(match.group(1)), float(match.group(2))
    return (low, high) if low < high else (high, low)


def _parse_market_semantics(market: dict) -> Optional[dict]:
    question = str(market.get("question") or "")
    group_item = str(market.get("groupItemTitle") or "")
    text = " ".join(part for part in (question, group_item) if part).strip()
    text_lower = text.lower()
    if not text or not any(
        word in text_lower
        for word in ("temperature", "temp", "degrees", "fahrenheit", "\u00b0f", "high", "low")
    ):
        return None

    city_key = _extract_city(text)
    target_date = _extract_date(text)
    threshold = _extract_temperature(text)
    if not city_key or not target_date or threshold is None:
        return None

    metric = "low" if re.search(r"\blow(?:est)?\b", text_lower) else "high"
    range_values = _extract_range(group_item) or _extract_range(question)
    if range_values:
        low, high = range_values
        return {
            "city_key": city_key,
            "target_date": target_date,
            "metric": metric,
            "kind": "between",
            "threshold_f": low,
            "upper_threshold_f": high + 0.01,
        }

    if re.search(
        r"\b(above|over|exceed|exceeds|more than|at least|higher than)\b",
        text_lower,
    ):
        return {
            "city_key": city_key,
            "target_date": target_date,
            "metric": metric,
            "kind": "above",
            "threshold_f": threshold,
            "upper_threshold_f": None,
        }
    if re.search(
        r"\b(below|under|less than|at most|lower than)\b",
        text_lower,
    ):
        return {
            "city_key": city_key,
            "target_date": target_date,
            "metric": metric,
            "kind": "below",
            "threshold_f": threshold,
            "upper_threshold_f": None,
        }

    # A group item such as "75°F" commonly represents the integer bucket for
    # a multi-market "highest temperature" event.
    if group_item and re.search(r"\d", group_item):
        return {
            "city_key": city_key,
            "target_date": target_date,
            "metric": metric,
            "kind": "between",
            "threshold_f": threshold - 0.5,
            "upper_threshold_f": threshold + 0.5,
        }
    return None


def parse_weather_market(
    cfg: Config,
    market: dict,
) -> Optional[WeatherMarket]:
    semantics = _parse_market_semantics(market)
    if semantics is None:
        return None
    if semantics["city_key"] not in set(
        item.strip().lower() for item in cfg.weather_cities.split(",") if item.strip()
    ):
        return None

    target_date = semantics["target_date"]
    today = datetime.now(timezone.utc).date()
    if target_date < today or (target_date - today).days > cfg.weather_max_days_ahead:
        return None

    outcomes = _json_list(market.get("outcomes"))
    tokens = [str(item) for item in _json_list(market.get("clobTokenIds"))]
    prices = _json_list(market.get("outcomePrices"))
    if len(outcomes) != 2 or len(tokens) != 2 or len(prices) != 2:
        return None
    outcome_map = {
        str(outcome).strip().lower(): (tokens[idx], float(prices[idx]))
        for idx, outcome in enumerate(outcomes)
    }
    if "yes" not in outcome_map or "no" not in outcome_map:
        return None
    yes_token, yes_price = outcome_map["yes"]
    no_token, no_price = outcome_map["no"]
    if not (0.0 < yes_price < 1.0 and 0.0 < no_price < 1.0):
        return None

    end_iso = market.get("endDate") or market.get("endDateIso")
    if not end_iso:
        return None
    condition_id = str(market.get("conditionId") or "")
    if not condition_id:
        return None
    if str(end_iso).endswith("Z"):
        end_iso = str(end_iso)[:-1] + "+00:00"
    try:
        end_ts = datetime.fromisoformat(str(end_iso)).timestamp()
    except ValueError:
        return None

    return WeatherMarket(
        condition_id=condition_id,
        market_id=str(market.get("id") or ""),
        slug=str(market.get("slug") or ""),
        question=str(market.get("question") or market.get("groupItemTitle") or ""),
        city_key=str(semantics["city_key"]),
        target_date=target_date,
        metric=str(semantics["metric"]),
        kind=str(semantics["kind"]),
        threshold_f=float(semantics["threshold_f"]),
        upper_threshold_f=(
            float(semantics["upper_threshold_f"])
            if semantics["upper_threshold_f"] is not None
            else None
        ),
        yes_token=yes_token,
        no_token=no_token,
        yes_price=yes_price,
        no_price=no_price,
        tick_size=float(market.get("orderPriceMinTickSize") or 0.01),
        neg_risk=str(market.get("negRisk", False)).strip().lower()
        in {"1", "true", "yes"},
        end_ts=end_ts,
        volume=float(market.get("volume") or 0.0),
        liquidity=float(market.get("liquidity") or 0.0),
    )


def fetch_weather_markets(cfg: Config) -> list[WeatherMarket]:
    """Page through active Gamma markets and locally filter weather markets."""
    found: dict[str, WeatherMarket] = {}
    pages = max(cfg.weather_market_scan_pages, 1)
    for page in range(pages):
        response = requests.get(
            f"{cfg.gamma_host}/markets",
            params={
                "closed": "false",
                "active": "true",
                "limit": 100,
                "offset": page * 100,
            },
            timeout=10,
        )
        if response.status_code in (404, 422):
            log.debug(
                "gamma market pagination ended at page=%d offset=%d status=%d",
                page,
                page * 100,
                response.status_code,
            )
            break
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, list):
            break
        for raw_market in payload:
            if not isinstance(raw_market, dict):
                continue
            parsed = parse_weather_market(cfg, raw_market)
            if parsed is not None:
                found[parsed.market_key] = parsed
        if len(payload) < 100:
            break

    markets = sorted(
        found.values(),
        key=lambda item: (item.target_date, -item.liquidity, -item.volume),
    )
    log.info("weather market scan found=%d pages=%d", len(markets), pages)
    return markets
