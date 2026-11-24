"""Gamma discovery and parsing for binary sports markets.

The parser is deliberately conservative: a market must have an explicit
sports hint, exactly two outcomes and two CLOB token ids.  It only returns
metadata and never touches the CLOB trading client.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
import logging
import re
from typing import Any, Iterable, Optional

import requests

log = logging.getLogger("bot.sports_markets")

SPORT_KEYWORDS: dict[str, tuple[str, ...]] = {
    "football": ("football", "nfl", "college-football", "soccer"),
    "basketball": ("basketball", "nba", "wnba", "ncaa-basketball"),
    "baseball": ("baseball", "mlb"),
    "hockey": ("hockey", "nhl"),
    "tennis": ("tennis", "atp", "wta"),
    "mma": ("mma", "ufc"),
    "boxing": ("boxing"),
    "golf": ("golf", "pga"),
    "cricket": ("cricket",),
    "rugby": ("rugby",),
    "esports": ("esports", "e-sports"),
}


@dataclass(frozen=True)
class SettlementRules:
    """Normalized settlement metadata shown to paper reviewers."""

    source: str = ""
    oracle: str = ""
    criteria: str = ""
    close_time: Optional[float] = None
    binary: bool = True
    neg_risk: bool = False


@dataclass(frozen=True)
class SportsMarket:
    condition_id: str
    market_id: str
    slug: str
    question: str
    sport: str
    league: str
    event_name: str
    event_start_ts: Optional[float]
    outcomes: tuple[str, str]
    token_ids: tuple[str, str]
    prices: tuple[float, float]
    tick_size: float
    neg_risk: bool
    end_ts: float
    volume: float
    liquidity: float
    settlement: SettlementRules = field(default_factory=SettlementRules)

    @property
    def market_key(self) -> str:
        return self.condition_id or self.market_id or self.slug

    @property
    def yes_token(self) -> str:
        return self.token_ids[0]

    @property
    def no_token(self) -> str:
        return self.token_ids[1]

    @property
    def clob_token_ids(self) -> tuple[str, str]:
        """Compatibility alias matching Gamma's field name."""
        return self.token_ids

    @property
    def settlement_rules(self) -> SettlementRules:
        return self.settlement


def _json_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except (TypeError, json.JSONDecodeError):
            return []
        return parsed if isinstance(parsed, list) else []
    return []


def _bool(value: Any) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _timestamp(value: Any) -> Optional[float]:
    if value in (None, ""):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    try:
        return float(text)
    except ValueError:
        pass
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.timestamp()


def _text(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, (list, tuple, set)):
        return " ".join(_text(item) for item in value)
    if isinstance(value, dict):
        return " ".join(f"{k} {_text(v)}" for k, v in value.items())
    return "" if value is None else str(value)


def _sport_hint(market: dict[str, Any]) -> tuple[str, str]:
    tags = _text(market.get("tags") or market.get("tag") or market.get("category"))
    slug = _text(market.get("slug") or market.get("eventSlug"))
    question = _text(market.get("question"))
    text = " ".join((tags, slug, question)).lower()
    for sport, words in SPORT_KEYWORDS.items():
        if any(re.search(rf"(?<![a-z0-9]){re.escape(word)}(?![a-z0-9])", text) for word in words):
            league = _text(market.get("league") or market.get("leagueName"))
            if not league:
                for candidate in words:
                    if candidate in text and candidate.upper() in {"NFL", "NBA", "MLB", "NHL", "UFC", "ATP", "WTA", "PGA"}:
                        league = candidate.upper()
                        break
            return sport, league
    # Gamma sometimes supplies an explicit sports flag/category without a
    # keyword recognizable by the map.
    category = _text(market.get("sportsCategory") or market.get("sport"))
    if category:
        return category.lower().replace(" ", "-"), _text(market.get("league") or market.get("leagueName"))
    # Some Gamma records expose only a generic ``sports`` tag and put the
    # concrete sport in an event/league field.  Preserve them as ``sports``
    # rather than silently dropping an otherwise valid binary market.
    if re.search(r"(?<![a-z0-9])sports?(?![a-z0-9])", tags.lower()):
        return "sports", _text(market.get("league") or market.get("leagueName"))
    return "", ""


def _event_name(market: dict[str, Any], question: str) -> str:
    value = market.get("eventTitle") or market.get("eventName") or market.get("title")
    if value:
        return str(value)
    # Keep the question as the audit-safe fallback; parsing team names is
    # intentionally avoided because league formats vary widely.
    return question


def parse_settlement_rules(market: dict[str, Any], *, end_ts: Optional[float] = None, neg_risk: Optional[bool] = None) -> SettlementRules:
    source = _text(market.get("resolutionSource") or market.get("resolution_source"))
    oracle = _text(market.get("oracle") or market.get("resolutionMethod"))
    criteria = _text(market.get("rules") or market.get("description") or market.get("resolutionCriteria"))
    close = _timestamp(market.get("endDate") or market.get("endDateIso")) or end_ts
    if neg_risk is None:
        neg_risk = _bool(market.get("negRisk"))
    return SettlementRules(
        source=source,
        oracle=oracle,
        criteria=criteria,
        close_time=close,
        binary=True,
        neg_risk=neg_risk,
    )


def parse_sports_market(cfg_or_market: Any, market: Optional[dict[str, Any]] = None, *, now_ts: Optional[float] = None, max_days_ahead: Optional[int] = None) -> Optional[SportsMarket]:
    """Parse one Gamma record.

    Both ``parse_sports_market(market)`` and the weather-compatible
    ``parse_sports_market(cfg, market)`` forms are accepted.
    """
    cfg = None
    if market is None:
        market = cfg_or_market
    else:
        cfg = cfg_or_market
    if max_days_ahead is None:
        max_days_ahead = int(getattr(cfg, "sports_max_days_ahead", 30)) if cfg is not None else 30
    if not isinstance(market, dict):
        return None
    sport, league = _sport_hint(market)
    if not sport:
        return None
    outcomes = [str(item).strip() for item in _json_list(market.get("outcomes"))]
    tokens = [str(item).strip() for item in _json_list(market.get("clobTokenIds"))]
    prices_raw = _json_list(market.get("outcomePrices"))
    if len(outcomes) != 2 or len(tokens) != 2 or len(prices_raw) != 2 or not all(outcomes + tokens):
        return None
    try:
        prices = tuple(float(item) for item in prices_raw)
    except (TypeError, ValueError):
        return None
    if not all(0.0 < price < 1.0 for price in prices):
        return None
    end_ts = _timestamp(market.get("endDate") or market.get("endDateIso"))
    if end_ts is None:
        return None
    now = float(now_ts if now_ts is not None else datetime.now(timezone.utc).timestamp())
    if end_ts <= now or end_ts > now + max(1, int(max_days_ahead)) * 86400:
        return None
    condition_id = _text(market.get("conditionId"))
    if not condition_id:
        return None
    neg_risk = _bool(market.get("negRisk"))
    question = _text(market.get("question") or market.get("groupItemTitle"))
    event_start = _timestamp(market.get("eventStartTime") or market.get("startDate") or market.get("eventDate"))
    return SportsMarket(
        condition_id=condition_id,
        market_id=_text(market.get("id")),
        slug=_text(market.get("slug")),
        question=question,
        sport=sport,
        league=league,
        event_name=_event_name(market, question),
        event_start_ts=event_start,
        outcomes=(outcomes[0], outcomes[1]),
        token_ids=(tokens[0], tokens[1]),
        prices=(prices[0], prices[1]),
        tick_size=float(market.get("orderPriceMinTickSize") or market.get("tickSize") or 0.01),
        neg_risk=neg_risk,
        end_ts=end_ts,
        volume=float(market.get("volume") or 0.0),
        liquidity=float(market.get("liquidity") or market.get("liquidityNum") or 0.0),
        settlement=parse_settlement_rules(market, end_ts=end_ts, neg_risk=neg_risk),
    )


def fetch_sports_markets(cfg: Any, *, pages: Optional[int] = None, session: Any = requests) -> list[SportsMarket]:
    """Discover active sports markets from Gamma and apply local filters.

    Gamma's general ``/markets`` feed is ordered by liquidity, so a small
    number of pages can miss today's games.  The event endpoint carries the
    canonical ``sports`` tag and embeds its child markets; we inspect that
    feed first and retain the generic market pagination as a compatibility
    fallback for older Gamma deployments.
    """
    found: dict[str, SportsMarket] = {}
    page_count = max(int(pages if pages is not None else getattr(cfg, "sports_market_scan_pages", 5)), 1)

    base = f"{getattr(cfg, 'gamma_host', 'https://gamma-api.polymarket.com').rstrip('/') }"

    # Event records include the sport tag on the parent and often omit it on
    # each child market.  Copy only descriptive metadata into a temporary
    # record so the parser can apply the same strict binary/token/date rules.
    try:
        for page in range(page_count):
            response = session.get(
                f"{base}/events",
                params={
                    "tag_slug": "sports",
                    "closed": "false",
                    "active": "true",
                    "limit": 100,
                    "offset": page * 100,
                },
                timeout=10,
            )
            if response.status_code in (404, 422):
                break
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, list):
                break
            for event in payload:
                if not isinstance(event, dict):
                    continue
                children = event.get("markets")
                if not isinstance(children, list):
                    # Some API versions return a market-shaped event record.
                    children = [event]
                event_tags = event.get("tags") or ["sports"]
                event_league = event.get("league") or event.get("leagueName")
                event_title = event.get("title") or event.get("eventTitle")
                event_start = event.get("startDate") or event.get("eventStartTime")
                for raw in children:
                    if not isinstance(raw, dict):
                        continue
                    enriched = dict(raw)
                    if not enriched.get("tags") and not enriched.get("tag") and not enriched.get("category"):
                        enriched["tags"] = event_tags
                    if event_league and not enriched.get("league") and not enriched.get("leagueName"):
                        enriched["league"] = event_league
                    if event_title and not enriched.get("eventTitle") and not enriched.get("eventName"):
                        enriched["eventTitle"] = event_title
                    if event_start and not enriched.get("eventStartTime"):
                        enriched["eventStartTime"] = event_start
                    parsed = parse_sports_market(
                        enriched,
                        max_days_ahead=int(getattr(cfg, "sports_max_days_ahead", 30)),
                    )
                    if parsed:
                        found[parsed.market_key] = parsed
            if len(payload) < 100:
                break
    except Exception as exc:
        # Do not make a transient event API outage hide the general feed.
        log.debug("sports event discovery failed: %s", exc)

    # Generic market pagination catches records on installations where the
    # event endpoint is unavailable or has incomplete child data.
    for page in range(page_count):
        response = session.get(
            f"{base}/markets",
            params={"closed": "false", "active": "true", "limit": 100, "offset": page * 100},
            timeout=10,
        )
        if response.status_code in (404, 422):
            break
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, list):
            break
        for raw in payload:
            parsed = parse_sports_market(raw, max_days_ahead=int(getattr(cfg, "sports_max_days_ahead", 30)))
            if parsed:
                found[parsed.market_key] = parsed
        if len(payload) < 100:
            break
    return sorted(found.values(), key=lambda item: (-item.liquidity, -item.volume, item.end_ts))
