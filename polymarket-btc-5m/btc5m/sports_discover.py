"""Discover Polymarket sports/esports mainline markets (P7 / P7.1).

Mainline = match winner binary. Props / map / set markets are excluded.
Phase-3/4 plugins own spread trees and live props.
"""
from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

import requests

from btc5m.event_state import MatchPhase, MatchState, infer_phase

log = logging.getLogger("btc5m.sports_discover")

# Prop / non-mainline markers (P7.1: catch game1, Map 1, Set 2, etc.)
_PROP_RE = re.compile(
    r"(?:^|[-_/\s])(?:set|game|map)[-_]?\d"
    r"|first[-_\s]?set"
    r"|(?:set|map|game)\s*\d"
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
    s = f"{slug} {question}"
    return _PROP_RE.search(s) is not None


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


def _mainline_score(event_slug: str, market: dict) -> int:
    """Higher = better match-winner candidate."""
    slug = str(market.get("slug") or "")
    question = str(market.get("question") or "")
    if _is_prop(slug, question):
        return -1
    score = 0
    if slug == event_slug:
        score += 100
    if slug.startswith(event_slug) and slug != event_slug:
        # child market under event — usually prop
        score -= 20
    low_q = question.lower()
    if " vs " in low_q or " vs. " in low_q:
        score += 10
    if any(x in low_q for x in ("winner", "moneyline", "match")):
        score += 5
    return score


def _pick_mainline(event: dict) -> Optional[dict]:
    event_slug = str(event.get("slug") or "")
    markets = event.get("markets") or []
    best: Optional[dict] = None
    best_score = -1
    for market in markets:
        score = _mainline_score(event_slug, market)
        if score < 0:
            continue
        outs = _parse_outcomes(market)
        tokens = _parse_tokens(market)
        if not outs or not tokens:
            continue
        if score > best_score:
            best = market
            best_score = score
    return best


def fetch_mainline_events(
    gamma_host: str,
    series_slug: str,
    *,
    limit: int = 60,
    now: Optional[float] = None,
    include_live: bool = False,
    pre_game_open_sec: float = 6 * 3600,
) -> list[MainlineMarket]:
    """Return tradeable mainline markets for ATP / CS-like series.

    P7.1: order by startTime descending so near-term games are not truncated
    behind a historical LIVE backlog; prefer event-slug match-winner markets.
    """
    now = now if now is not None else time.time()
    r = requests.get(
        f"{gamma_host}/events",
        params={
            "series_slug": series_slug,
            "closed": "false",
            "limit": max(limit, 20),
            "order": "startTime",
            # Newest / furthest-future first — avoids oldest LIVE backlog
            "ascending": "false",
        },
        timeout=10,
    )
    r.raise_for_status()
    out: list[MainlineMarket] = []
    for event in r.json():
        event_slug = str(event.get("slug") or "")
        title = str(event.get("title") or "")
        market = _pick_mainline(event)
        if market is None:
            continue
        outs = _parse_outcomes(market)
        tokens = _parse_tokens(market)
        if not outs or not tokens:
            continue
        start_iso = market.get("eventStartTime") or event.get("startTime")
        if not start_iso:
            continue
        start_ts = _iso_to_unix(str(start_iso))
        # Drop far-past events that Gamma still marks open
        if start_ts < now - 12 * 3600 and not include_live:
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
        slug = str(market.get("slug") or "") or event_slug
        out.append(
            MainlineMarket(
                event_slug=event_slug,
                event_title=title,
                market_slug=slug,
                condition_id=str(market.get("conditionId") or ""),
                question=str(market.get("question") or title),
                home=outs[0],
                away=outs[1],
                home_token=tokens[0],
                away_token=tokens[1],
                start_ts=start_ts,
                tick_size=float(market.get("orderPriceMinTickSize") or 0.01),
                min_size=float(market.get("orderMinSize") or 5),
                state=state,
            )
        )
    # Prefer soonest quoteable, then soonest start
    def _sort_key(m: MainlineMarket) -> tuple:
        quoteable = m.state.may_quote_mainline(
            now=now, pre_game_open_sec=pre_game_open_sec
        )
        return (0 if quoteable else 1, m.start_ts)

    out.sort(key=_sort_key)
    log.info(
        "sports discover %s → %d mainline (include_live=%s)",
        series_slug,
        len(out),
        include_live,
    )
    return out
