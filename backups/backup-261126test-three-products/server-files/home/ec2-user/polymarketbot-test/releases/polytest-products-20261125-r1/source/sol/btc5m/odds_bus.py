"""External odds bus — fair probability from sharp books (P7 / P7.1 / P8).

Paper/default provider is a deterministic mock so ATP/CS engines can be
unit-tested without scraping. Wire The Odds API via ODDS_API_KEY.
Sports MM refuses new quotes on mock unless SPORTS_QUOTE_ON_MOCK=1.
"""
from __future__ import annotations

import hashlib
import logging
import os
import re
import time
from dataclasses import dataclass
from typing import Optional, Protocol

import requests

log = logging.getLogger("btc5m.odds_bus")

# Preferred bookmakers for de-vig (sharp → soft)
_BOOK_PREF = (
    "pinnacle",
    "betfair_ex_uk",
    "betfair_ex_eu",
    "lowvig",
    "betonlineag",
    "draftkings",
    "fanduel",
    "betmgm",
    "williamhill_us",
    "bovada",
)

# Default The Odds API sport keys per product
PRODUCT_SPORT_KEYS: dict[str, list[str]] = {
    "nba": ["basketball_nba"],
    "nfl": ["americanfootball_nfl"],
    "atp": ["tennis_atp_finals"],
    "cs": [],  # no CS on The Odds API for this key
    "dota": [],  # no Dota on The Odds API for this key
    "soccer_unl": [
        "soccer_uefa_champs_league",
        "soccer_uefa_europa_league",
        "soccer_uefa_europa_conference_league",
        "soccer_epl",
        "soccer_spain_la_liga",
        "soccer_italy_serie_a",
        "soccer_germany_bundesliga",
        "soccer_france_ligue_one",
        "soccer_usa_mls",
    ],
}


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


def _norm_team(name: str) -> str:
    s = (name or "").lower()
    s = re.sub(r"[^a-z0-9\s]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    # Drop common suffixes that differ across books / Polymarket
    for tok in (
        " fc",
        " cf",
        " sc",
        " afc",
        " club",
        " united",
        " city",
        " town",
        " team",
    ):
        if s.endswith(tok) and len(s) > len(tok) + 2:
            s = s[: -len(tok)].strip()
    return s


def _token_set(name: str) -> set[str]:
    return {t for t in _norm_team(name).split() if len(t) > 1}


def _teams_match(a: str, b: str) -> bool:
    na, nb = _norm_team(a), _norm_team(b)
    if not na or not nb:
        return False
    if na == nb:
        return True
    if na in nb or nb in na:
        return True
    ta, tb = _token_set(a), _token_set(b)
    if not ta or not tb:
        return False
    # Jaccard on tokens; require overlap of key tokens
    inter = ta & tb
    if not inter:
        return False
    union = ta | tb
    return (len(inter) / len(union)) >= 0.5 or inter == ta or inter == tb


def deveig_two_way(odds_home: float, odds_away: float) -> tuple[float, float]:
    """Convert decimal odds to no-juice probs."""
    if odds_home <= 1.0 or odds_away <= 1.0:
        raise ValueError("decimal odds must be > 1")
    ih, ia = 1.0 / odds_home, 1.0 / odds_away
    s = ih + ia
    return ih / s, ia / s


class OddsApiProvider:
    """The Odds API adapter (NBA/NFL/soccer/tennis when key + sport_keys present)."""

    name = "odds_api"
    _BASE = "https://api.the-odds-api.com/v4"

    def __init__(
        self,
        api_key: str,
        *,
        sport_keys: Optional[list[str]] = None,
        cache_ttl_sec: float = 60.0,
        timeout_sec: float = 8.0,
    ) -> None:
        self.api_key = api_key.strip()
        self.sport_keys = [s.strip() for s in (sport_keys or []) if s and s.strip()]
        self.cache_ttl_sec = cache_ttl_sec
        self.timeout_sec = timeout_sec
        self._event_cache: dict[str, tuple[float, list[dict]]] = {}
        self._quote_cache: dict[str, FairQuote] = {}

    def fair_match(self, event_key: str, home: str, away: str) -> Optional[FairQuote]:
        if not self.api_key or not self.sport_keys:
            return None
        cached = self._quote_cache.get(event_key)
        if cached is not None and not cached.stale:
            return cached
        # Also key by normalized teams so re-discover reuses quotes
        team_key = f"{_norm_team(home)}|{_norm_team(away)}"
        cached_t = self._quote_cache.get(team_key)
        if cached_t is not None and not cached_t.stale:
            self._quote_cache[event_key] = cached_t
            return cached_t

        for sport in self.sport_keys:
            events = self._events_for_sport(sport)
            q = self._match_event(events, event_key, home, away, sport)
            if q is not None:
                self._quote_cache[event_key] = q
                self._quote_cache[team_key] = q
                return q
        log.debug(
            "odds_api: no match for %s (%s vs %s) sports=%s",
            event_key,
            home,
            away,
            self.sport_keys,
        )
        return None

    def _events_for_sport(self, sport: str) -> list[dict]:
        now = time.time()
        hit = self._event_cache.get(sport)
        if hit and now - hit[0] <= self.cache_ttl_sec:
            return hit[1]
        url = f"{self._BASE}/sports/{sport}/odds"
        try:
            r = requests.get(
                url,
                params={
                    "apiKey": self.api_key,
                    "regions": "us,uk,eu",
                    "markets": "h2h",
                    "oddsFormat": "decimal",
                },
                timeout=self.timeout_sec,
            )
            if r.status_code == 401:
                log.warning("odds_api: unauthorized (check ODDS_API_KEY)")
                self._event_cache[sport] = (now, [])
                return []
            if r.status_code == 404:
                log.debug("odds_api: sport %s not found", sport)
                self._event_cache[sport] = (now, [])
                return []
            r.raise_for_status()
            data = r.json()
            events = data if isinstance(data, list) else []
            self._event_cache[sport] = (now, events)
            remaining = r.headers.get("x-requests-remaining")
            if remaining is not None:
                log.debug("odds_api: requests remaining=%s sport=%s", remaining, sport)
            return events
        except Exception as exc:  # noqa: BLE001
            log.warning("odds_api fetch failed sport=%s: %s", sport, exc)
            return hit[1] if hit else []

    def _match_event(
        self,
        events: list[dict],
        event_key: str,
        home: str,
        away: str,
        sport: str,
    ) -> Optional[FairQuote]:
        for ev in events:
            eh = str(ev.get("home_team") or "")
            ea = str(ev.get("away_team") or "")
            # Polymarket titles are often "Away vs. Home" or abbreviations —
            # try both orientations.
            oriented: Optional[tuple[str, str, bool]] = None
            if _teams_match(home, eh) and _teams_match(away, ea):
                oriented = (eh, ea, False)  # poly home ↔ odds home
            elif _teams_match(home, ea) and _teams_match(away, eh):
                oriented = (eh, ea, True)  # poly home ↔ odds away
            if oriented is None:
                continue
            odds_home_name, odds_away_name, swapped = oriented
            dec = self._best_h2h_decimals(ev, odds_home_name, odds_away_name)
            if dec is None:
                continue
            oh, oa = dec
            try:
                p_odds_home, p_odds_away = deveig_two_way(oh, oa)
            except ValueError:
                continue
            if swapped:
                p_home, p_away = p_odds_away, p_odds_home
            else:
                p_home, p_away = p_odds_home, p_odds_away
            return FairQuote(
                event_key=event_key,
                home=home,
                away=away,
                p_home=p_home,
                p_away=p_away,
                source=f"odds_api/{sport}",
                ts=time.time(),
                max_age_sec=max(self.cache_ttl_sec * 2, 120.0),
            )
        return None

    def _best_h2h_decimals(
        self, ev: dict, home_name: str, away_name: str
    ) -> Optional[tuple[float, float]]:
        books = list(ev.get("bookmakers") or [])
        if not books:
            return None

        def rank(b: dict) -> int:
            key = str(b.get("key") or "")
            try:
                return _BOOK_PREF.index(key)
            except ValueError:
                return len(_BOOK_PREF) + 1

        books.sort(key=rank)
        for book in books:
            for market in book.get("markets") or []:
                if str(market.get("key") or "") != "h2h":
                    continue
                outcomes = market.get("outcomes") or []
                by_name = {
                    str(o.get("name") or ""): float(o.get("price") or 0)
                    for o in outcomes
                }
                if home_name in by_name and away_name in by_name:
                    oh, oa = by_name[home_name], by_name[away_name]
                    if oh > 1.0 and oa > 1.0:
                        return oh, oa
                # Fuzzy outcome names
                oh = oa = None
                for name, px in by_name.items():
                    if oh is None and _teams_match(name, home_name):
                        oh = px
                    elif oa is None and _teams_match(name, away_name):
                        oa = px
                if oh and oa and oh > 1.0 and oa > 1.0:
                    return oh, oa
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


def sport_keys_for_product(product_key: str, override: str = "") -> list[str]:
    if override.strip():
        return [s.strip() for s in override.split(",") if s.strip()]
    return list(PRODUCT_SPORT_KEYS.get((product_key or "").strip().lower(), []))


def build_odds_bus(
    *,
    api_key: str = "",
    product_key: str = "",
    sport_keys_override: str = "",
) -> OddsBus:
    """Prefer OddsAPI when key is set; skip mock fallthrough so quotes stay real."""
    key = (api_key or os.getenv("ODDS_API_KEY", "")).strip()
    providers: list[OddsProvider] = []
    if key:
        keys = sport_keys_for_product(product_key, sport_keys_override)
        providers.append(OddsApiProvider(key, sport_keys=keys))
        # No MockSharp append: avoid silent mock edge when a real key is present.
        return OddsBus(providers)
    providers.append(MockSharpProvider())
    return OddsBus(providers)


def build_odds_bus_from_env(product_key: str = "") -> OddsBus:
    """Prefer OddsAPI when ODDS_API_KEY is set; else mock-only bus."""
    return build_odds_bus(
        api_key=os.getenv("ODDS_API_KEY", "").strip(),
        product_key=product_key or os.getenv("PRODUCT_KEY", "").strip(),
        sport_keys_override=os.getenv("ODDS_SPORT_KEYS", "").strip(),
    )
