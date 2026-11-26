"""Discover Polymarket sports/esports mainline markets (P7 phase 2).

Mainline = match winner binary (first market on the event that is not a
set/map/prop). Props and spread trees are intentionally excluded here;
phase-3/4 plugins will own those.
"""
from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

import requests

from btc5m.event_state import MatchPhase, MatchState, infer_phase

log = logging.getLogger("btc5m.sports_discover")

# Slug / question fragments that indicate non-mainline markets
_PROP_RE = re.compile(
    r"(?:^|[-_/\s])(?:set|game|map)[-_]?\d"
    r"|first[-_\s]?set"
    r"|\btotal\b|\bspread\b|o/u|\bhandicap\b"
    r"|\broshan\b|\bbarracks\b|\bkill\b|\bpistol\b|\bdaytime\b"
    r"|player[-_\s]?prop|anytime\s+goal|completed\s+match",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class MainlineMarket:
    event_slug: str
    event_title: str
    market_slug: str
    condition_id: str
    question: str
    home: str
    away: str
    home_token: str
    away_token: str
    start_ts: float
    tick_size: float
    min_size: float
    state: MatchState


def _iso_to_unix(value: str) -> float:
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    return datetime.fromisoformat(value).timestamp()


def _is_prop(slug: str, question: str) -> bool:
    return _PROP_RE.search(f"{slug} {question}") is not None


def _mainline_score(event_slug: str, market: dict) -> int:
    """Rank match-winner candidates above child map/set/game markets."""
    slug = str(market.get("slug") or "")
    question = str(market.get("question") or "")
    if _is_prop(slug, question):
        return -1
    score = 0
    if slug == event_slug:
        score += 100
    elif slug.startswith(event_slug):
        score -= 20
    low_q = question.lower()
    if " vs " in low_q or " vs. " in low_q:
        score += 10
    if any(x in low_q for x in ("winner", "moneyline", "match")):
        score += 5
    return score


def _parse_outcomes(market: dict) -> Optional[tuple[str, str]]:
    raw = market.get("outcomes")
    if raw is None:
        return None
    outs = json.loads(raw) if isinstance(raw, str) else raw
    if not isinstance(outs, list) or len(outs) != 2:
        return None
    return str(outs[0]), str(outs[1])


def _parse_tokens(market: dict) -> Optional[tuple[str, str]]:
    raw = market.get("clobTokenIds")
    if not raw:
        return None
    tokens = json.loads(raw) if isinstance(raw, str) else raw
    if not isinstance(tokens, list) or len(tokens) != 2:
        return None
    return str(tokens[0]), str(tokens[1])


def _flag(value: object, *, default: bool = True) -> bool:
    """Parse Gamma boolean fields without treating ``"false"`` as true."""
    if value is None:
        return default
    if isinstance(value, str):
        return value.strip().lower() not in {"", "0", "false", "no", "off"}
    return bool(value)


def fetch_mainline_events(
    gamma_host: str,
    series_slug: str,
    *,
    limit: int = 100,
    now: Optional[float] = None,
    include_live: bool = False,
    pre_game_open_sec: float = 6 * 3600.0,
) -> list[MainlineMarket]:
    """Return tradeable mainline markets for ATP / CS-like series."""
    now = now if now is not None else time.time()
    r = requests.get(
        f"{gamma_host}/events",
        params={
            "series_slug": series_slug,
            "closed": "false",
            "limit": max(int(limit), 100),
            "order": "startTime",
            "ascending": "false",
            # The API uses this hint to avoid returning months of historical
            # events before the local phase/closed filters run.  The local
            # check below remains authoritative for API compatibility.
            "start_time_min": datetime.fromtimestamp(
                now, tz=timezone.utc
            ).isoformat().replace("+00:00", "Z"),
        },
        timeout=10,
    )
    r.raise_for_status()
    out: list[MainlineMarket] = []
    for event in r.json():
        if _flag(event.get("closed"), default=False):
            continue
        event_slug = str(event.get("slug") or "")
        title = str(event.get("title") or "")
        markets = sorted(
            event.get("markets") or [],
            key=lambda market: _mainline_score(event_slug, market),
            reverse=True,
        )
        main = None
        for market in markets:
            slug = str(market.get("slug") or "")
            question = str(market.get("question") or "")
            if _is_prop(slug, question):
                continue
            if _flag(market.get("closed"), default=False):
                continue
            if not _flag(market.get("acceptingOrders"), default=True):
                continue
            if not _flag(market.get("enableOrderBook"), default=True):
                continue
            outs = _parse_outcomes(market)
            tokens = _parse_tokens(market)
            if not outs or not tokens:
                continue
            start_iso = market.get("eventStartTime") or event.get("startTime")
            if not start_iso:
                continue
            start_ts = _iso_to_unix(start_iso)
            # Only future mainline markets are candidates in this phase. This
            # prevents a stale ascending response from consuming the entire
            # result page with already-started events.
            if start_ts <= now:
                continue
            phase = infer_phase(now=now, start_ts=start_ts, closed=False)
            if phase == MatchPhase.LIVE and not include_live:
                continue
            if phase not in {MatchPhase.PRE_GAME, MatchPhase.LIVE}:
                continue
            state = MatchState(
                event_slug=event_slug,
                home=outs[0],
                away=outs[1],
                phase=phase,
                start_ts=start_ts,
                allow_props=False,
            )
            main = MainlineMarket(
                event_slug=event_slug,
                event_title=title,
                market_slug=slug or event_slug,
                condition_id=str(market.get("conditionId") or ""),
                question=question or title,
                home=outs[0],
                away=outs[1],
                home_token=tokens[0],
                away_token=tokens[1],
                start_ts=start_ts,
                tick_size=float(market.get("orderPriceMinTickSize") or 0.01),
                min_size=float(market.get("orderMinSize") or 5),
                state=state,
            )
            break
        if main is not None:
            out.append(main)
    # The strategy itself applies the six-hour pre-game gate. Sorting here
    # keeps the soonest quoteable events first without dropping future events.
    out.sort(
        key=lambda m: (
            0 if m.state.may_quote_mainline(now=now, pre_game_open_sec=pre_game_open_sec) else 1,
            m.start_ts,
        )
    )
    log.info(
        "sports discover %s → %d mainline (include_live=%s)",
        series_slug,
        len(out),
        include_live,
    )
    return out
