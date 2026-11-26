"""SOL5M Paper runner facade."""
from __future__ import annotations

import logging
import os

from btc5m.config import load
from btc5m.engine import Engine
from sol5m.profile import SOL5M, assert_paper_env


def paper_config():
    assert_paper_env()
    cfg = load(series=SOL5M.key)
    if cfg.product_key != SOL5M.key or cfg.crypto_asset != SOL5M.crypto_asset:
        raise RuntimeError(f"unexpected SOL profile: {cfg.product_key}/{cfg.crypto_asset}")
    if cfg.live_trading_enabled:
        raise RuntimeError("SOL5M Paper requires LIVE_TRADING_ENABLED=false")
    return cfg


def run(*, once: bool = False) -> None:
    cfg = paper_config()
    logging.getLogger(__name__).info(
        "starting isolated SOL5M Paper db=%s live=false", cfg.data_dir / cfg.late_edge_db_name
    )
    Engine(cfg, live=False).run(once=once)


__all__ = ["paper_config", "run"]

