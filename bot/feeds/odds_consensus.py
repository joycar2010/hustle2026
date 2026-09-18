"""Bookmaker-consensus probabilities for sports markets (The Odds API).

Implements the existing SportsDataSource protocol, so SportsPaperService
gains a genuinely independent probability source: per event, every
bookmaker's two-way moneyline is de-vigged (implied probabilities
normalized) and averaged into a consensus, which is matched to a Polymarket
SportsMarket by start time (+/-45 min) and team-name tokens.  In-play or
finished events are filtered out via the free ESPN scoreboard when
available.  Every successful match is appended to an audit JSONL.

Budget: the free tier is 500 credits/month.  We track the
x-requests-remaining header and stop fetching below a reserve, so a runaway
loop can never exhaust the account.
"""
from __future__ import annotations

import json
import logging
import os
import re
import time
from pathlib import Path
from typing import Mapping, Optional

import requests

log = logging.getLogger("bot.feeds.odds")

ODDS_BASE = "https://api.the-odds-api.com/v4"
ROOT = Path(__file__).resolve().parent.parent.parent
AUDIT_PATH = ROOT / "agents" / "out" / "odds_matches.jsonl"
STATE_PATH = ROOT / "agents" / "out" / "odds_budget.json"

DEFAULT_SPORTS = "americanfootball_nfl,baseball_mlb,basketball_nba,icehockey_nhl"
CACHE_TTL_SEC = 7200.0       # one snapshot per sport per 2h
RESERVE_CREDITS = 50         # stop fetching when remaining falls to this
MATCH_START_TOLERANCE = 45 * 60.0

_token_re = re.compile(r"[a-z0-9]+")


def _tokens(name: str) -> set[str]:
    stop = {"the", "of", "at", "vs", "v", "fc", "sc"}
    return {t for t in _token_re.findall((name or "").lower()) if t not in stop}


def _teams_match(outcome: str, team: str) -> bool:
    a, b = _tokens(outcome), _tokens(team)
    if not a or not b:
        return False
    return a <= b or b <= a or len(a & b) >= 2


class OddsConsensusSource:
    name = "odds_consensus"

    def __init__(self, api_key: str, sports: Optional[list[str]] = None):
        self.api_key = api_key
        self.sports = sports or [
            s.strip() for s in os.environ.get("ODDS_API_SPORTS", DEFAULT_SPORTS).split(",") if s.strip()
        ]
        self._cache: dict[str, tuple[float, list[dict]]] = {}
        self._remaining: Optional[float] = self._load_remaining()
        try:
            from bot.feeds.espn_scores import event_state
            self._espn_state = event_state
        except Exception:
            self._espn_state = None

    # -- budget bookkeeping (driven by response headers, not guesses) -------
    def _load_remaining(self) -> Optional[float]:
        try:
            return float(json.loads(STATE_PATH.read_text())["remaining"])
        except Exception:
            return None

    def _save_remaining(self) -> None:
        try:
            STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
            STATE_PATH.write_text(json.dumps(
                {"remaining": self._remaining, "ts": time.time()}))
        except Exception:
            pass

    def _events(self, sport: str) -> list[dict]:
        hit = self._cache.get(sport)
        if hit and time.monotonic() - hit[0] < CACHE_TTL_SEC:
            return hit[1]
        if self._remaining is not None and self._remaining <= RESERVE_CREDITS:
            log.warning("odds api budget reserve reached (%.0f left); serving stale", self._remaining)
            return hit[1] if hit else []
        try:
            r = requests.get(
                f"{ODDS_BASE}/sports/{sport}/odds",
                params={"apiKey": self.api_key, "regions": "us",
                        "markets": "h2h", "oddsFormat": "decimal"},
                timeout=10,
            )
            rem = r.headers.get("x-requests-remaining")
            if rem is not None:
                self._remaining = float(rem)
                self._save_remaining()
            r.raise_for_status()
            events = []
            for ev in r.json() or []:
                cons = self._consensus(ev)
                if cons is None:
                    continue
                events.append({
                    "home": ev.get("home_team") or "",
                    "away": ev.get("away_team") or "",
                    "commence_ts": _iso_ts(ev.get("commence_time")),
                    "sport": sport,
                    "consensus": cons,
                })
            self._cache[sport] = (time.monotonic(), events)
            log.info("odds snapshot %s: %d events (remaining=%s)",
                     sport, len(events), self._remaining)
            return events
        except Exception as exc:
            log.debug("odds fetch %s failed: %s", sport, exc)
            return hit[1] if hit else []

    @staticmethod
    def _consensus(ev: dict) -> Optional[dict[str, float]]:
        """De-vig each bookmaker's two-way h2h, then average across books."""
        home, away = ev.get("home_team"), ev.get("away_team")
        acc: dict[str, list[float]] = {home: [], away: []}
        for book in ev.get("bookmakers") or []:
            for mk in book.get("markets") or []:
                if mk.get("key") != "h2h":
                    continue
                probs = {}
                for oc in mk.get("outcomes") or []:
                    price = float(oc.get("price") or 0)
                    if price > 1.0:
                        probs[oc.get("name")] = 1.0 / price
                if home in probs and away in probs:
                    total = probs[home] + probs[away]
                    if total > 0:
                        acc[home].append(probs[home] / total)
                        acc[away].append(probs[away] / total)
        if len(acc[home]) < 2:      # demand at least two books for "consensus"
            return None
        return {home: sum(acc[home]) / len(acc[home]),
                away: sum(acc[away]) / len(acc[away]),
                "_books": float(len(acc[home]))}

    # -- SportsDataSource protocol ------------------------------------------
    def probabilities(self, market) -> Optional[Mapping[str, float]]:
        start_ts = getattr(market, "event_start_ts", None)
        outcomes = list(getattr(market, "outcomes", ()) or ())
        if not start_ts or len(outcomes) != 2:
            return None
        for sport in self.sports:
            for ev in self._events(sport):
                if ev["commence_ts"] is None or abs(ev["commence_ts"] - start_ts) > MATCH_START_TOLERANCE:
                    continue
                pair = self._pair(outcomes, ev)
                if pair is None:
                    continue
                if self._espn_state is not None and os.environ.get(
                        "ESPN_INPLAY_FILTER", "true").lower() in ("1", "true", "yes", "on"):
                    state = self._espn_state(sport, ev["home"], ev["away"], ev["commence_ts"])
                    if state in ("in", "post"):
                        return None  # never enter in-play/finished on stale odds
                self._audit(market, ev, pair)
                return {outcomes[0]: pair[0], outcomes[1]: pair[1]}
        return None

    def _pair(self, outcomes: list[str], ev: dict) -> Optional[tuple[float, float]]:
        cons = ev["consensus"]
        o0_home = _teams_match(outcomes[0], ev["home"])
        o0_away = _teams_match(outcomes[0], ev["away"])
        o1_home = _teams_match(outcomes[1], ev["home"])
        o1_away = _teams_match(outcomes[1], ev["away"])
        if o0_home and o1_away and not (o0_away or o1_home):
            return cons[ev["home"]], cons[ev["away"]]
        if o0_away and o1_home and not (o0_home or o1_away):
            return cons[ev["away"]], cons[ev["home"]]
        return None

    def _audit(self, market, ev: dict, pair: tuple[float, float]) -> None:
        try:
            AUDIT_PATH.parent.mkdir(parents=True, exist_ok=True)
            with AUDIT_PATH.open("a", encoding="utf-8") as f:
                f.write(json.dumps({
                    "ts": round(time.time(), 3),
                    "pm_event": getattr(market, "event_name", ""),
                    "pm_outcomes": list(getattr(market, "outcomes", ())),
                    "odds_event": f"{ev['away']} @ {ev['home']}",
                    "sport": ev["sport"],
                    "consensus": [round(pair[0], 4), round(pair[1], 4)],
                    "books": ev["consensus"].get("_books"),
                }, ensure_ascii=False) + "\n")
        except Exception:
            pass


def _iso_ts(value) -> Optional[float]:
    try:
        from datetime import datetime, timezone
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp()
    except Exception:
        return None
