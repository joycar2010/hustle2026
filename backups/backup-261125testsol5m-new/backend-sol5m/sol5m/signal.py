"""SOL price signal facade with an explicit asset assertion."""
from __future__ import annotations

from dataclasses import replace

from btc5m.config import Config
from btc5m.markets import LiveMarket
from btc5m.signal import BtcSignal, fetch_asset_signal
from sol5m.profile import SOL5M


def fetch_sol_signal(cfg: Config, market: LiveMarket) -> BtcSignal:
    """Fetch the multi-venue SOL signal, never silently falling back to BTC."""
    if getattr(cfg, "crypto_asset", "sol") != SOL5M.crypto_asset:
        cfg = replace(cfg, crypto_asset=SOL5M.crypto_asset)
    return fetch_asset_signal(cfg, market)


__all__ = ["BtcSignal", "fetch_sol_signal"]

