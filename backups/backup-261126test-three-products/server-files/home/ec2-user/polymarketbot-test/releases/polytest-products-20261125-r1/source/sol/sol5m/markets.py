"""SOL-specific market discovery facade.

The parser and Gamma transport are shared with the proven engine, while this
facade fixes the SOL series/prefix/window so a caller cannot accidentally query
the BTC live lane.
"""
from __future__ import annotations

from typing import Optional

from btc5m.markets import LiveMarket
from btc5m.markets import fetch_market_by_slug as _fetch_market_by_slug
from btc5m.markets import fetch_live_market as _fetch_live_market
from sol5m.profile import SOL5M


def fetch_market_by_slug(gamma_host: str, slug: str) -> Optional[LiveMarket]:
    return _fetch_market_by_slug(gamma_host, slug)


def fetch_live_market(gamma_host: str) -> Optional[LiveMarket]:
    return _fetch_live_market(
        gamma_host,
        SOL5M.series_slug,
        window_sec=SOL5M.window_sec,
        slug_prefix=SOL5M.market_slug_prefix,
    )

