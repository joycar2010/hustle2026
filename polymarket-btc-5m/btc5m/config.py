"""Load configuration from environment / .env."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")


def _bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _float(name: str, default: float) -> float:
    raw = os.getenv(name)
    return float(raw) if raw not in (None, "") else default


def _int(name: str, default: int) -> int:
    raw = os.getenv(name)
    return int(raw) if raw not in (None, "") else default


@dataclass(frozen=True)
class Config:
    private_key: str
    funder_address: str
    signature_type: int
    chain_id: int
    api_key: str
    api_secret: str
    api_passphrase: str

    clob_host: str
    gamma_host: str
    polygon_rpc: str
    series_slug: str

    entry_window_sec: float
    min_t_remaining_sec: float
    min_entry_price: float
    max_entry_price: float
    min_net_edge: float
    taker_fee_rate: float
    confirm_checks: int
    poll_interval_sec: float

    delta_filter_enabled: bool
    up_min_delta_usd: float
    down_max_delta_usd: float
    price_hosts: str

    order_shares: float
    max_order_usd: float
    daily_loss_limit_usd: float
    max_open_positions: int
    paper_bankroll_usd: float
    live_trading_enabled: bool

    # late_edge | maker
    mode: str

    # Maker bilateral MM (paper)
    maker_pair_cost_max: float
    maker_quote_shares: float
    maker_start_delay_sec: float
    maker_stop_before_end_sec: float
    maker_touch_fill_sec: float
    maker_max_imbalance_shares: float

    data_dir: Path


def load() -> Config:
    mode = os.getenv("MODE", "late_edge").strip().lower() or "late_edge"
    if mode not in {"late_edge", "maker"}:
        mode = "late_edge"
    return Config(
        private_key=os.getenv("PRIVATE_KEY", "").strip(),
        funder_address=os.getenv("FUNDER_ADDRESS", "").strip(),
        signature_type=_int("SIGNATURE_TYPE", 3),
        chain_id=_int("CHAIN_ID", 137),
        api_key=os.getenv("API_KEY", "").strip(),
        api_secret=os.getenv("API_SECRET", "").strip(),
        api_passphrase=os.getenv("API_PASSPHRASE", "").strip(),
        clob_host=os.getenv("CLOB_HOST", "https://clob.polymarket.com").rstrip("/"),
        gamma_host=os.getenv("GAMMA_HOST", "https://gamma-api.polymarket.com").rstrip("/"),
        polygon_rpc=os.getenv("POLYGON_RPC", "https://polygon-rpc.com").rstrip("/"),
        series_slug=os.getenv("SERIES_SLUG", "btc-up-or-down-5m"),
        entry_window_sec=_float("ENTRY_WINDOW_SEC", 60.0),
        min_t_remaining_sec=_float("MIN_T_REMAINING_SEC", 12.0),
        min_entry_price=_float("MIN_ENTRY_PRICE", 0.75),
        max_entry_price=_float("MAX_ENTRY_PRICE", 0.95),
        min_net_edge=_float("MIN_NET_EDGE", 0.02),
        taker_fee_rate=_float("TAKER_FEE_RATE", 0.07),
        confirm_checks=max(_int("CONFIRM_CHECKS", 2), 1),
        poll_interval_sec=max(_float("POLL_INTERVAL_SEC", 1.0), 0.2),
        delta_filter_enabled=_bool("DELTA_FILTER_ENABLED", True),
        up_min_delta_usd=_float("UP_MIN_DELTA_USD", 15.0),
        down_max_delta_usd=_float("DOWN_MAX_DELTA_USD", -15.0),
        price_hosts=os.getenv("PRICE_HOSTS", "okx,coinbase,kraken"),
        order_shares=max(_float("ORDER_SHARES", 10.0), 5.0),
        max_order_usd=_float("MAX_ORDER_USD", 15.0),
        daily_loss_limit_usd=_float("DAILY_LOSS_LIMIT_USD", 40.0),
        max_open_positions=max(_int("MAX_OPEN_POSITIONS", 1), 1),
        paper_bankroll_usd=_float("PAPER_BANKROLL_USD", 200.0),
        live_trading_enabled=_bool("LIVE_TRADING_ENABLED", False),
        mode=mode,
        maker_pair_cost_max=_float("MAKER_PAIR_COST_MAX", 0.98),
        maker_quote_shares=max(_float("MAKER_QUOTE_SHARES", 10.0), 5.0),
        maker_start_delay_sec=_float("MAKER_START_DELAY_SEC", 15.0),
        maker_stop_before_end_sec=_float("MAKER_STOP_BEFORE_END_SEC", 45.0),
        maker_touch_fill_sec=_float("MAKER_TOUCH_FILL_SEC", 8.0),
        maker_max_imbalance_shares=_float("MAKER_MAX_IMBALANCE_SHARES", 20.0),
        data_dir=ROOT / "data",
    )
