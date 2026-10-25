"""Shared market-data freshness configuration.

The Rust publisher historically used ``MAX_STALENESS_MS`` while Python
consumers used ``BINANCE_WS_MAX_AGE_MS``.  Reading both names here keeps old
deployments compatible while making the newer name the single override used by
all Python execution and read-model paths.
"""

from __future__ import annotations

import os


DEFAULT_SPREAD_MAX_AGE_MS = 10_000


def configured_spread_max_age_ms() -> int:
    """Return the configured local-WS freshness fence in milliseconds.

    ``BINANCE_WS_MAX_AGE_MS`` is canonical.  ``MAX_STALENESS_MS`` remains a
    compatibility alias for existing Rust service environments.  Invalid,
    zero, and negative values are ignored so a bad override cannot disable the
    execution freshness gate.
    """

    for name in ("BINANCE_WS_MAX_AGE_MS", "MAX_STALENESS_MS"):
        raw = os.getenv(name)
        if raw is None:
            continue
        try:
            value = int(raw)
        except (TypeError, ValueError, OverflowError):
            continue
        if value > 0:
            return value
    return DEFAULT_SPREAD_MAX_AGE_MS
