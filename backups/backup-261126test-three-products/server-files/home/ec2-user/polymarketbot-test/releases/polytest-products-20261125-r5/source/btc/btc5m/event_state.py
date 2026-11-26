"""Match / event lifecycle state machine (P7 phase 2).

Used by ATP/CS sports_mm. Crypto up/down windows do not use this module.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional


class MatchPhase(str, Enum):
    SCHEDULED = "scheduled"
    PRE_GAME = "pre_game"  # tradeable for phase-2 MM
    LIVE = "live"  # phase-2: no new risk by default
    SUSPENDED = "suspended"
    FINISHED = "finished"
    SETTLED = "settled"


@dataclass
class MatchState:
    event_slug: str
    home: str
    away: str
    phase: MatchPhase
    start_ts: float
    score_home: Optional[int] = None
    score_away: Optional[int] = None
    # Tennis / CS extensions
    set_home: Optional[int] = None
    set_away: Optional[int] = None
    map_no: Optional[int] = None
    allow_props: bool = False  # phase-4 gate; always False for now

    def may_quote_mainline(self, *, now: float, pre_game_open_sec: float = 6 * 3600) -> bool:
        """Phase-2 policy: only quote mainline in PRE_GAME within open window."""
        if self.phase != MatchPhase.PRE_GAME:
            return False
        if self.start_ts <= 0:
            return False
        # Too early
        if now < self.start_ts - pre_game_open_sec:
            return False
        # Past start → should be LIVE
        if now >= self.start_ts:
            return False
        return True


def infer_phase(*, now: float, start_ts: float, closed: bool = False) -> MatchPhase:
    if closed:
        return MatchPhase.FINISHED
    if start_ts <= 0:
        return MatchPhase.SCHEDULED
    if now < start_ts:
        return MatchPhase.PRE_GAME
    # Without a live feed we cannot confirm LIVE vs FINISHED; treat post-start as LIVE
    # until Gamma marks closed / resolved.
    return MatchPhase.LIVE


def transition(state: MatchState, *, now: float, closed: bool = False) -> MatchState:
    phase = infer_phase(now=now, start_ts=state.start_ts, closed=closed)
    if phase == state.phase:
        return state
    return MatchState(
        event_slug=state.event_slug,
        home=state.home,
        away=state.away,
        phase=phase,
        start_ts=state.start_ts,
        score_home=state.score_home,
        score_away=state.score_away,
        set_home=state.set_home,
        set_away=state.set_away,
        map_no=state.map_no,
        allow_props=False,
    )