"""External odds bus — fair probability from sharp books (P7 phase 2).

Paper/default provider is a deterministic mock so ATP/CS engines can be
unit-tested without scraping. Wire a real Pinnacle/OddsAPI adapter later
behind the same FairQuote interface without touching crypto strategies.
"""
from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass
from typing import Optional, Protocol


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

    def edge_vs_ask(self, side: str, ask: float) -> float:
        fair = self.p_home if side.upper() in {"HOME", "A", self.home.upper()} else self.p_away
        return float(fair) - float(ask)


class OddsProvider(Protocol):
    def fair_match(self, event_key: str, home: str, away: str) -> Optional[FairQuote]:
        ...


class MockSharpProvider:
    """Deterministic pseudo-sharp fair probs for paper tests.

    Hash(event_key) → p_home in [0.35, 0.65]; p_away = 1 - p_home.
    """

    def __init__(self, *, source: str = "mock_sharp") -> None:
        self.source = source

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


class OddsBus:
    """Fan-in wrapper; first non-None quote wins (extend to median later)."""

    def __init__(self, providers: Optional[list[OddsProvider]] = None) -> None:
        self.providers = list(providers) if providers else [MockSharpProvider()]

    def fair_match(self, event_key: str, home: str, away: str) -> Optional[FairQuote]:
        for p in self.providers:
            q = p.fair_match(event_key, home, away)
            if q is not None and not q.stale:
                return q
        return None


def deveig_two_way(odds_home: float, odds_away: float) -> tuple[float, float]:
    """Convert decimal odds to no-juice probs."""
    if odds_home <= 1.0 or odds_away <= 1.0:
        raise ValueError("decimal odds must be > 1")
    ih, ia = 1.0 / odds_home, 1.0 / odds_away
    s = ih + ia
    return ih / s, ia / s
