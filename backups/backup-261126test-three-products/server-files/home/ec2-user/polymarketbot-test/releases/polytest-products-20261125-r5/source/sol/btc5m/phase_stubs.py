"""Phase-3 / Phase-4 readiness gates.

NBA/NFL moneyline and Dota/Soccer mainline paper are enabled (P8).
Spread trees, props, and live quoting remain deferred — discover keeps
include_live=False and prop filters on.
"""
from __future__ import annotations

import logging

log = logging.getLogger("btc5m.phase_stubs")


class PhaseNotEnabled(RuntimeError):
    pass


def assert_nba_nfl_ready() -> None:
    """Paper moneyline sports_mm is enabled; spread-tree risk still deferred."""
    log.info(
        "NBA/NFL paper sports_mm enabled (moneyline mainline + OddsAPI). "
        "Spread tree / injury feed still deferred."
    )


def assert_dota_soccer_live_ready() -> None:
    """Mainline-only paper; live and props stay filtered out."""
    log.info(
        "Dota/Soccer paper sports_mm enabled (mainline-only). "
        "Live/props quoting remains gated (include_live=False, prop filter)."
    )
