"""External odds bus — fair probability from sharp books (P7 / P7.1).

Paper/default provider is a deterministic mock so ATP/CS engines can be
unit-tested without scraping. Wire a real OddsAPI / Pinnacle adapter via
ODDS_API_KEY. Sports MM refuses new quotes on mock unless
SPORTS_QUOTE_ON_MOCK=1.
"""
from __future__ import annotations

import hashlib
import logging
import os
import time
from dataclasses import dataclass
from typing import Optional, Protocol

log = logging.getLogger("btc5m.odds_bus")


@dataclass(frozen=True)
class FairQuote:
    event_key: str
    home: str
    away: str
    p_home: float  # fair win prob home/team A (no juice)
    p_away: float
    source: str
    ts: float
    max_age_sec: float = 120.0

    @property
    def stale(self) -> bool:
        return (time.time() - self.ts) > self.max_age_sec

    @property
    def is_mock(self) -> bool:
        return self.source.startswith("mock")

    def edge_vs_ask(self, side: str, ask: float) -> float:
        fair = self.p_home if side.upper() in {"HOME", "A", self.home.upper()} else self.p_away
        return float(fair) - float(ask)


class OddsProvider(Protocol):
    name: str

    def fair_match(self, event_key: str, home: str, away: str) -> Optional[FairQuote]:
        ...


class MockSharpProvider:
    """Deterministic pseudo-sharp fair probs for paper tests.

    Hash(event_key) → p_home in [0.35, 0.65]; p_away = 1 - p_home.
    """

    name = "mock_sharp"

    def __init__(self, *, source: str = "mock_sharp") -> None:
        self.source = source
        self.name = source

    def fair_match(self, event_key: str, home: str, away: str) -> Optional[FairQuote]:
        digest = hashlib.sha256(event_key.encode()).hexdigest()
        raw = int(digest[:8], 16) / 0xFFFFFFFF
        p_home = 0.35 + 0.30 * raw
        p_away = 1.0 - p_home
        return FairQuote(
            event_key=event_key,
            home=home,
            away=away,
            p_home=p_home,
            p_away=p_away,
            source=self.source,
            ts=time.time(),
        )


class OddsApiProvider:
    """Optional The Odds API adapter (soccer/tennis/cs when key present).

    Without a successful HTTP quote this provider returns None so the bus
    can fall through. Keeps crypto engines untouched.
    """

    name = "odds_api"

    def __init__(self, api_key: str, *, sport_keys: Optional[list[str]] = None) -> None:
        self.api_key = api_key.strip()
        self.sport_keys = sport_keys or []
        self._cache: dict[str, FairQuote] = {}

    def fair_match(self, event_key: str, home: str, away: str) -> Optional[FairQuote]:
        if not self.api_key:
            return None
        cached = self._cache.get(event_key)
        if cached is not None and not cached.stale:
            return cached
        # Network fetch is intentionally deferred until sport_keys + team
        # matching are configured per product. Returning None forces mock
        # fall-through only when explicitly allowed by OddsBus policy.
        log.debug(
            "odds_api: no mapped quote yet for %s (%s vs %s)", event_key, home, away
        )
        return None


class OddsBus:
    """Fan-in wrapper; first non-None quote wins (extend to median later)."""

    def __init__(self, providers: Optional[list[OddsProvider]] = None) -> None:
        self.providers = list(providers) if providers else [MockSharpProvider()]

    @property
    def primary_source(self) -> str:
        if not self.providers:
            return "none"
        return getattr(self.providers[0], "name", type(self.providers[0]).__name__)

    @property
    def using_mock(self) -> bool:
        return all(
            str(getattr(p, "name", "")).startswith("mock") for p in self.providers
        )

    def fair_match(self, event_key: str, home: str, away: str) -> Optional[FairQuote]:
        for p in self.providers:
            q = p.fair_match(event_key, home, away)
            if q is not None and not q.stale:
                return q
        return None


def build_odds_bus_from_env() -> OddsBus:
    """Use the configured external provider, or an explicit mock Paper bus.

    When a key is present we do not silently fall back to pseudo odds.  That
    keeps a failed/stale external feed from being mistaken for tradable edge.
    """
    key = os.getenv("ODDS_API_KEY", "").strip()
    if key:
        return OddsBus([OddsApiProvider(key)])
    return OddsBus([MockSharpProvider()])


def deveig_two_way(odds_home: float, odds_away: float) -> tuple[float, float]:
    """Convert decimal odds to no-juice probs."""
    if odds_home <= 1.0 or odds_away <= 1.0:
        raise ValueError("decimal odds must be > 1")
    ih, ia = 1.0 / odds_home, 1.0 / odds_away
    s = ih + ia
    return ih / s, ia / s
