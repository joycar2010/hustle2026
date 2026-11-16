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
    # P7 multi-product (defaults preserve BTC 5m)
    product_key: str
    window_sec: int
    market_slug_prefix: str
    split_db_name: str
    maker_db_name: str

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
    signal_require_consensus: bool
    signal_min_venues: int

    # P3 lead / TWAP
    lead_table_enabled: bool
    lead_edge_margin: float
    lead_min_bp: float
    opening_gap_enabled: bool
    opening_gap_window_sec: float
    opening_gap_min_bp: float

    order_shares: float
    max_order_usd: float
    daily_loss_limit_usd: float
    max_open_positions: int
    paper_bankroll_usd: float
    live_trading_enabled: bool

    # late_edge | maker | split_sell
    mode: str

    late_edge_hard_ban_price: float
    late_edge_edge_safety: float
    bucket_calibration_enabled: bool
    bucket_lookback_sec: float
    bucket_min_samples: int
    bucket_wr_buffer: float

    maker_pair_cost_max: float
    maker_pair_profit_min: float
    maker_quote_shares: float
    maker_start_delay_sec: float
    maker_stop_before_end_sec: float
    maker_touch_fill_sec: float
    maker_max_imbalance_shares: float
    maker_allow_crossed_fills: bool
    maker_flatten_residual: bool
    # P5b B1 hardening
    maker_min_bid_price: float
    maker_pair_complete_sec: float
    maker_zero_fill_kill_sec: float
    maker_early_flatten: bool

    # P4/P5a/P6 split-sell
    split_size: float
    split_fair_edge: float
    split_max_lean_shares: float
    split_clip_shares: float
    split_touch_fill_sec: float
    split_stop_before_end_sec: float
    split_merge_before_end_sec: float
    split_rebate_bps: float
    split_min_pair_ask: float
    split_min_ask_price: float
    split_lean_abort_sec: float
    # P6: bilateral fillability + residual closed loop
    split_join_touch: bool
    split_catchup_improve_ticks: int
    split_catchup_min_ask: float
    split_catchup_touch_fill_sec: float
    split_residual_flatten: bool
    split_residual_sla_sec: float

    heartbeat_stale_sec: float
    data_dir: Path


def load(*, series: str | None = None) -> Config:
    mode = os.getenv("MODE", "late_edge").strip().lower() or "late_edge"
    if mode not in {"late_edge", "maker", "split_sell", "sports_mm"}:
        mode = "late_edge"
    series_slug = (series or os.getenv("SERIES_SLUG", "btc-up-or-down-5m")).strip()
    cfg = Config(
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
        series_slug=series_slug,
        product_key=os.getenv("PRODUCT_KEY", "btc5m").strip() or "btc5m",
        window_sec=max(_int("WINDOW_SEC", 300), 60),
        market_slug_prefix=os.getenv("MARKET_SLUG_PREFIX", "btc-updown-5m").strip()
        or "btc-updown-5m",
        split_db_name=os.getenv("SPLIT_DB_NAME", "split_sell_paper.db").strip()
        or "split_sell_paper.db",
        maker_db_name=os.getenv("MAKER_DB_NAME", "maker_paper.db").strip()
        or "maker_paper.db",
        entry_window_sec=_float("ENTRY_WINDOW_SEC", 60.0),
        min_t_remaining_sec=_float("MIN_T_REMAINING_SEC", 15.0),
        min_entry_price=_float("MIN_ENTRY_PRICE", 0.75),
        max_entry_price=_float("MAX_ENTRY_PRICE", 0.88),
        min_net_edge=_float("MIN_NET_EDGE", 0.08),
        taker_fee_rate=_float("TAKER_FEE_RATE", 0.07),
        confirm_checks=max(_int("CONFIRM_CHECKS", 3), 1),
        poll_interval_sec=max(_float("POLL_INTERVAL_SEC", 1.0), 0.2),
        delta_filter_enabled=_bool("DELTA_FILTER_ENABLED", True),
        up_min_delta_usd=_float("UP_MIN_DELTA_USD", 25.0),
        down_max_delta_usd=_float("DOWN_MAX_DELTA_USD", -25.0),
        price_hosts=os.getenv("PRICE_HOSTS", "okx,coinbase,kraken"),
        signal_require_consensus=_bool("SIGNAL_REQUIRE_CONSENSUS", True),
        signal_min_venues=max(_int("SIGNAL_MIN_VENUES", 2), 1),
        lead_table_enabled=_bool("LEAD_TABLE_ENABLED", True),
        lead_edge_margin=_float("LEAD_EDGE_MARGIN", 0.03),
        lead_min_bp=_float("LEAD_MIN_BP", 2.0),
        opening_gap_enabled=_bool("OPENING_GAP_ENABLED", True),
        opening_gap_window_sec=_float("OPENING_GAP_WINDOW_SEC", 60.0),
        opening_gap_min_bp=_float("OPENING_GAP_MIN_BP", 5.0),
        order_shares=max(_float("ORDER_SHARES", 10.0), 5.0),
        max_order_usd=_float("MAX_ORDER_USD", 15.0),
        daily_loss_limit_usd=_float("DAILY_LOSS_LIMIT_USD", 40.0),
        max_open_positions=max(_int("MAX_OPEN_POSITIONS", 1), 1),
        paper_bankroll_usd=_float("PAPER_BANKROLL_USD", 200.0),
        live_trading_enabled=_bool("LIVE_TRADING_ENABLED", False),
        mode=mode,
        late_edge_hard_ban_price=_float("LATE_EDGE_HARD_BAN_PRICE", 0.90),
        late_edge_edge_safety=_float("LATE_EDGE_EDGE_SAFETY", 1.25),
        bucket_calibration_enabled=_bool("BUCKET_CALIBRATION_ENABLED", True),
        bucket_lookback_sec=_float("BUCKET_LOOKBACK_SEC", 7 * 86400.0),
        bucket_min_samples=max(_int("BUCKET_MIN_SAMPLES", 8), 1),
        bucket_wr_buffer=_float("BUCKET_WR_BUFFER", 0.02),
        maker_pair_cost_max=_float("MAKER_PAIR_COST_MAX", 0.96),
        maker_pair_profit_min=_float("MAKER_PAIR_PROFIT_MIN", 0.03),
        maker_quote_shares=max(_float("MAKER_QUOTE_SHARES", 10.0), 5.0),
        maker_start_delay_sec=_float("MAKER_START_DELAY_SEC", 15.0),
        maker_stop_before_end_sec=_float("MAKER_STOP_BEFORE_END_SEC", 60.0),
        maker_touch_fill_sec=_float("MAKER_TOUCH_FILL_SEC", 12.0),
        maker_max_imbalance_shares=_float("MAKER_MAX_IMBALANCE_SHARES", 10.0),
        maker_allow_crossed_fills=_bool("MAKER_ALLOW_CROSSED_FILLS", False),
        maker_flatten_residual=_bool("MAKER_FLATTEN_RESIDUAL", True),
        maker_min_bid_price=_float("MAKER_MIN_BID_PRICE", 0.20),
        maker_pair_complete_sec=_float("MAKER_PAIR_COMPLETE_SEC", 20.0),
        maker_zero_fill_kill_sec=_float("MAKER_ZERO_FILL_KILL_SEC", 90.0),
        maker_early_flatten=_bool("MAKER_EARLY_FLATTEN", True),
        split_size=max(_float("SPLIT_SIZE", 50.0), 5.0),
        split_fair_edge=_float("SPLIT_FAIR_EDGE", 0.01),
        split_max_lean_shares=_float("SPLIT_MAX_LEAN_SHARES", 3.0),
        split_clip_shares=max(_float("SPLIT_CLIP_SHARES", 10.0), 5.0),
        split_touch_fill_sec=_float("SPLIT_TOUCH_FILL_SEC", 5.0),
        split_stop_before_end_sec=_float("SPLIT_STOP_BEFORE_END_SEC", 45.0),
        split_merge_before_end_sec=_float("SPLIT_MERGE_BEFORE_END_SEC", 15.0),
        split_rebate_bps=_float("SPLIT_REBATE_BPS", 42.0),
        # Touch pair on skewed books is ~1.00–1.02; 1.01 keeps edge without blocking fills
        split_min_pair_ask=_float("SPLIT_MIN_PAIR_ASK", 1.01),
        split_min_ask_price=_float("SPLIT_MIN_ASK_PRICE", 0.20),
        split_lean_abort_sec=_float("SPLIT_LEAN_ABORT_SEC", 20.0),
        split_join_touch=_bool("SPLIT_JOIN_TOUCH", True),
        split_catchup_improve_ticks=max(_int("SPLIT_CATCHUP_IMPROVE_TICKS", 1), 0),
        split_catchup_min_ask=_float("SPLIT_CATCHUP_MIN_ASK", 0.15),
        split_catchup_touch_fill_sec=_float("SPLIT_CATCHUP_TOUCH_FILL_SEC", 3.0),
        split_residual_flatten=_bool("SPLIT_RESIDUAL_FLATTEN", True),
        split_residual_sla_sec=_float("SPLIT_RESIDUAL_SLA_SEC", 20.0),
        heartbeat_stale_sec=_float("HEARTBEAT_STALE_SEC", 120.0),
        data_dir=ROOT / "data",
    )
    # Apply product overlays (BTC 5m is identity — no behavioral change)
    from btc5m.products import apply_product

    cfg, _product = apply_product(cfg, series_slug)
    return cfg
