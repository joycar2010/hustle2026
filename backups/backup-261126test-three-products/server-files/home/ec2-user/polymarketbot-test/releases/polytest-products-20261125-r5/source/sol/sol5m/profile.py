"""SOL5M release profile and safe environment defaults."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import os


@dataclass(frozen=True)
class Sol5mProfile:
    key: str = "sol5m"
    series_slug: str = "sol-up-or-down-5m"
    market_slug_prefix: str = "sol-updown-5m"
    crypto_asset: str = "sol"
    window_sec: int = 300
    late_edge_db_name: str = "paper_sol5m.db"
    live_db_name: str = "live_sol5m.db"
    mode: str = "late_edge"
    live_trading_enabled: bool = False
    description: str = "SOL Up/Down 5m isolated Paper profile"


SOL5M = Sol5mProfile()


def env_defaults(*, data_dir: Path | None = None) -> dict[str, str]:
    """Return a complete, conservative SOL environment overlay.

    Values are strings so callers can pass them directly to ``subprocess`` or
    merge them into an ``.env`` file.  Live execution is deliberately disabled
    in both Paper and production templates until an operator edits the file.
    """
    root = Path(data_dir or Path(__file__).resolve().parents[1])
    return {
        "PRODUCT_KEY": SOL5M.key,
        "SERIES_SLUG": SOL5M.series_slug,
        "MARKET_SLUG_PREFIX": SOL5M.market_slug_prefix,
        "WINDOW_SEC": str(SOL5M.window_sec),
        "CRYPTO_ASSET": SOL5M.crypto_asset,
        "MODE": SOL5M.mode,
        "LATE_EDGE_DB_NAME": SOL5M.late_edge_db_name,
        "LIVE_DB_NAME": SOL5M.live_db_name,
        "LIVE": "false",
        "LIVE_TRADING_ENABLED": "false",
        "SOL5M_DATA_DIR": str(root / "data"),
    }


def assert_paper_env(env: dict[str, str] | None = None) -> None:
    """Fail closed if a supposedly Paper process inherits live permission."""
    values = env or os.environ
    live = str(values.get("LIVE_TRADING_ENABLED", "false")).strip().lower()
    flag = str(values.get("LIVE", "false")).strip().lower()
    if live in {"1", "true", "yes", "on"} or flag in {"1", "true", "yes", "on"}:
        raise RuntimeError("SOL5M Paper refuses LIVE/LIVE_TRADING_ENABLED=true")

