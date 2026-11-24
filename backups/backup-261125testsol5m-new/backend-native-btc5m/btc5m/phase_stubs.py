"""Phase-3 / Phase-4 scaffolds — explicitly disabled.

NBA/NFL spread trees and Dota props / soccer live are intentionally not
runnable so they cannot interfere with BTC 5m or phase-1/2 paper paths.
"""
from __future__ import annotations


class PhaseNotEnabled(RuntimeError):
    pass


def assert_nba_nfl_ready() -> None:
    raise PhaseNotEnabled(
        "Phase-3 NBA/NFL pre-game MM scaffold only. "
        "Enable after odds_bus + injury feed + spread-tree risk land."
    )


def assert_dota_soccer_live_ready() -> None:
    raise PhaseNotEnabled(
        "Phase-4 Dota props / soccer live deferred — toxic books and jump risk. "
        "Mainline-only esports is phase-2 (CS); Dota props stay off."
    )