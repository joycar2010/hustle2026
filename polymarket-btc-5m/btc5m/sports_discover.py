"""Discover Polymarket sports/esports mainline markets (P7 phase 2).

Mainline = match winner binary (first market on the event that is not a
set/map/prop). Props and spread trees are intentionally excluded here;
phase-3/4 plugins will own those.
"""
from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

import requests

from btc5m.event_state import MatchPhase, MatchState, infer_phase

log = logging.getLogger("btc5m.sports_discover")

# Slug / question fragments that indicate non-mainline markets
_PROP_MARKERS = (
    "set-",
    "set_",
    "first-set",
    "game-",
    "map-",
    "total",
    "spread",
    "o/u",
    "handicap",
    "roshan",
    "barracks",
    "kill",
    "pistol",
    "daytime",
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
    s = f"{slug} {question}".lower()
    return any(m in s for m in _PROP_MARKERS)


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


def fetch_mainline_events(
    gamma_host: str,
    series_slug: str,
    *,
    limit: int = 30,
    now: Optional[float] = None,
    include_live: bool = False,
) -> list[MainlineMarket]:
    """Return tradeable mainline markets for ATP / CS-like series."""
    now = now if now is not None else time.time()
    r = requests.get(
        f"{gamma_host}/events",
        params={
            "series_slug": series_slug,
            "closed": "false",
            "limit": limit,
            "order": "startTime",
            "ascending": "true",
        },
        timeout=10,
    )
    r.raise_for_status()
    out: list[MainlineMarket] = []
    for event in r.json():
        event_slug = str(event.get("slug") or "")
        title = str(event.get("title") or "")
        markets = event.get("markets") or []
        main = None
        for market in markets:
            slug = str(market.get("slug") or "")
            question = str(market.get("question") or "")
            if _is_prop(slug, question):
                continue
            outs = _parse_outcomes(market)
            tokens = _parse_tokens(market)
            if not outs or not tokens:
                continue
            start_iso = market.get("eventStartTime") or event.get("startTime")
            if not start_iso:
                continue
            start_ts = _iso_to_unix(start_iso)
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
    log.info(
        "sports discover %s → %d mainline (include_live=%s)",
        series_slug,
        len(out),
        include_live,
    )
    return out
