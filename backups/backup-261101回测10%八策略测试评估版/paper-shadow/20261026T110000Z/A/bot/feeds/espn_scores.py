"""ESPN public scoreboard (unofficial, keyless) -- game-state lookups.

Used only as an in-play filter for the odds-consensus source: pre-game
events pass, live/finished events are skipped so stale odds can never open a
paper entry mid-game.  Endpoints are the JSON feeds behind espn.com; they
carry no SLA, so every failure degrades to "state unknown" (no filtering).
"""
from __future__ import annotations

import logging
import time
from typing import Optional

import requests

log = logging.getLogger("bot.feeds.espn")

BASE = "https://site.api.espn.com/apis/site/v2/sports"
LEAGUE_PATH = {
    "americanfootball_nfl": "football/nfl",
    "baseball_mlb": "baseball/mlb",
    "basketball_nba": "basketball/nba",
    "icehockey_nhl": "hockey/nhl",
}
_cache: dict[tuple[str, str], tuple[float, list[dict]]] = {}
_CACHE_TTL = 60.0


def _scoreboard(sport_key: str, yyyymmdd: str) -> list[dict]:
    path = LEAGUE_PATH.get(sport_key)
    if path is None:
        return []
    key = (sport_key, yyyymmdd)
    hit = _cache.get(key)
    if hit and time.monotonic() - hit[0] < _CACHE_TTL:
        return hit[1]
    try:
        r = requests.get(f"{BASE}/{path}/scoreboard",
                         params={"dates": yyyymmdd}, timeout=6)
        r.raise_for_status()
        events = (r.json() or {}).get("events") or []
    except Exception as exc:
        log.debug("espn scoreboard %s %s failed: %s", sport_key, yyyymmdd, exc)
        events = hit[1] if hit else []
    _cache[key] = (time.monotonic(), events)
    return events


def event_state(sport_key: str, home: str, away: str,
                commence_ts: Optional[float]) -> Optional[str]:
    """'pre' | 'in' | 'post' for the matching game, or None when unknown."""
    if not commence_ts:
        return None
    yyyymmdd = time.strftime("%Y%m%d", time.gmtime(commence_ts))
    home_l, away_l = (home or "").lower(), (away or "").lower()
    for ev in _scoreboard(sport_key, yyyymmdd):
        name = str(ev.get("name") or "").lower()
        if not name:
            continue
        home_hit = any(tok in name for tok in home_l.split() if len(tok) > 3)
        away_hit = any(tok in name for tok in away_l.split() if len(tok) > 3)
        if home_hit and away_hit:
            try:
                return str(ev["status"]["type"]["state"])
            except Exception:
                return None
    return None
