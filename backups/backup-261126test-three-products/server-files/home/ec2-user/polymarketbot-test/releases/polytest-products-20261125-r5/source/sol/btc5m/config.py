"""Load configuration from environment / .env."""
from __future__ import annotations

import os
import math
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
    # P7/P8 multi-product (defaults preserve BTC 5m)
    product_key: str
    window_sec: int
    market_slug_prefix: str
    split_db_name: str
    maker_db_name: str
    late_edge_db_name: str
    crypto_asset: str  # btc | eth | sol
    odds_sport_keys: str  # comma-separated The Odds API sport keys

    entry_window_sec: float
    min_t_remaining_sec: float
    min_entry_price: float
    max_entry_price: float
    # P1: gap phase tighter than late; high-ask edge / confirm
    opening_gap_max_entry_price: float
    high_ask_threshold: float
    min_net_edge: float
    min_net_edge_high: float
    taker_fee_rate: float
    confirm_checks: int
    confirm_checks_high: int
    poll_interval_sec: float

    delta_filter_enabled: bool
    up_min_delta_usd: float
    down_max_delta_usd: float
    price_hosts: str
    signal_require_consensus: bool
    signal_min_venues: int

    # P3 lead / TWAP (+ P1/P2 asymmetric)
    lead_table_enabled: bool
    lead_edge_margin: float
    lead_edge_margin_down: float  # DOWN uses max(margin, this)
    lead_min_bp: float
    up_lead_min_bp: float
    down_lead_min_bp: float
    opening_gap_enabled: bool
    opening_gap_window_sec: float
    opening_gap_min_bp: float

    order_shares: float
    max_order_usd: float
    # P2: size ∝ (1-ask)/(1-ref) so a high ask cannot erase many cheap wins
    size_scale_enabled: bool
    size_scale_ref_ask: float
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

    # P7.1 sports MM (does not affect BTC 5m defaults)
    sports_min_edge: float
    sports_daily_loss_limit_usd: float
    sports_pre_game_open_sec: float
    sports_quote_on_mock: bool
    sports_discover_limit: int
    odds_api_key: str

    data_dir: Path

    # Paper-only adverse-fill and maker queue controls retained from the
    # current integrity release.  These defaults keep existing ledgers safe.
    paper_slippage_ticks: float = 0.0
    paper_slippage_pct: float = 0.0
    allow_spot_resolution_fallback: bool = False
    maker_queue_factor: float = 0.25
    maker_max_capital_usd: float = 30.0
    maker_trade_api_host: str = "https://data-api.polymarket.com/v2"
    maker_trade_poll_sec: float = 1.0
    maker_trade_freshness_sec: float = 10.0


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
        late_edge_db_name=os.getenv("LATE_EDGE_DB_NAME", "paper.db").strip()
        or "paper.db",
        crypto_asset=os.getenv("CRYPTO_ASSET", "btc").strip().lower() or "btc",
        odds_sport_keys=os.getenv("ODDS_SPORT_KEYS", "").strip(),
        entry_window_sec=_float("ENTRY_WINDOW_SEC", 60.0),
        min_t_remaining_sec=_float("MIN_T_REMAINING_SEC", 15.0),
        min_entry_price=_float("MIN_ENTRY_PRICE", 0.75),
        # P0 A: cut toxic [0.80,0.85) band (live WR≪breakeven)
        max_entry_price=_float("MAX_ENTRY_PRICE", 0.79),
        opening_gap_max_entry_price=_float("OPENING_GAP_MAX_ENTRY_PRICE", 0.78),
        high_ask_threshold=_float("HIGH_ASK_THRESHOLD", 0.80),
        min_net_edge=_float("MIN_NET_EDGE", 0.08),
        min_net_edge_high=_float("MIN_NET_EDGE_HIGH", 0.12),
        taker_fee_rate=_float("TAKER_FEE_RATE", 0.07),
        confirm_checks=max(_int("CONFIRM_CHECKS", 3), 1),
        confirm_checks_high=max(_int("CONFIRM_CHECKS_HIGH", 5), 1),
        poll_interval_sec=max(_float("POLL_INTERVAL_SEC", 1.0), 0.2),
        delta_filter_enabled=_bool("DELTA_FILTER_ENABLED", True),
        # P1 asymmetric Δ: slightly easier UP, stricter DOWN
        up_min_delta_usd=_float("UP_MIN_DELTA_USD", 20.0),
        down_max_delta_usd=_float("DOWN_MAX_DELTA_USD", -30.0),
        price_hosts=os.getenv("PRICE_HOSTS", "okx,coinbase,kraken"),
        signal_require_consensus=_bool("SIGNAL_REQUIRE_CONSENSUS", True),
        signal_min_venues=max(_int("SIGNAL_MIN_VENUES", 2), 1),
        lead_table_enabled=_bool("LEAD_TABLE_ENABLED", True),
        lead_edge_margin=_float("LEAD_EDGE_MARGIN", 0.05),
        lead_edge_margin_down=_float("LEAD_EDGE_MARGIN_DOWN", 0.07),
        lead_min_bp=_float("LEAD_MIN_BP", 2.0),
        up_lead_min_bp=_float("UP_LEAD_MIN_BP", 1.5),
        down_lead_min_bp=_float("DOWN_LEAD_MIN_BP", 3.0),
        opening_gap_enabled=_bool("OPENING_GAP_ENABLED", True),
        opening_gap_window_sec=_float("OPENING_GAP_WINDOW_SEC", 60.0),
        opening_gap_min_bp=_float("OPENING_GAP_MIN_BP", 5.0),
        order_shares=max(_float("ORDER_SHARES", 10.0), 5.0),
        max_order_usd=_float("MAX_ORDER_USD", 15.0),
        size_scale_enabled=_bool("SIZE_SCALE_ENABLED", True),
        size_scale_ref_ask=_float("SIZE_SCALE_REF_ASK", 0.75),
        daily_loss_limit_usd=_float("DAILY_LOSS_LIMIT_USD", 40.0),
        max_open_positions=max(_int("MAX_OPEN_POSITIONS", 1), 1),
        paper_bankroll_usd=_float("PAPER_BANKROLL_USD", 200.0),
        live_trading_enabled=_bool("LIVE_TRADING_ENABLED", False),
        mode=mode,
        late_edge_hard_ban_price=_float("LATE_EDGE_HARD_BAN_PRICE", 0.90),
        late_edge_edge_safety=_float("LATE_EDGE_EDGE_SAFETY", 1.5),
        bucket_calibration_enabled=_bool("BUCKET_CALIBRATION_ENABLED", True),
        bucket_lookback_sec=_float("BUCKET_LOOKBACK_SEC", 7 * 86400.0),
        # Faster fuse so a toxic band bans before the 8th loser
        bucket_min_samples=max(_int("BUCKET_MIN_SAMPLES", 5), 1),
        bucket_wr_buffer=_float("BUCKET_WR_BUFFER", 0.03),
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
        sports_min_edge=_float("SPORTS_MIN_EDGE", 0.04),
        sports_daily_loss_limit_usd=_float("SPORTS_DAILY_LOSS_LIMIT_USD", 25.0),
        sports_pre_game_open_sec=_float("SPORTS_PRE_GAME_OPEN_SEC", 6 * 3600.0),
        # Default off: mock fair probs are not tradable edge
        sports_quote_on_mock=_bool("SPORTS_QUOTE_ON_MOCK", False),
        sports_discover_limit=max(_int("SPORTS_DISCOVER_LIMIT", 60), 20),
        odds_api_key=os.getenv("ODDS_API_KEY", "").strip(),
        data_dir=ROOT / "data",
        paper_slippage_ticks=max(_float("PAPER_SLIPPAGE_TICKS", 0.0), 0.0),
        paper_slippage_pct=max(_float("PAPER_SLIPPAGE_PCT", 0.0), 0.0),
        allow_spot_resolution_fallback=False,
        maker_queue_factor=max(_float("MAKER_QUEUE_FACTOR", 0.25), 0.0),
        maker_max_capital_usd=max(_float("MAKER_MAX_CAPITAL_USD", 30.0), 0.0),
        maker_trade_api_host=os.getenv("MAKER_TRADE_API_HOST", "https://data-api.polymarket.com/v2").rstrip("/"),
        maker_trade_poll_sec=max(_float("MAKER_TRADE_POLL_SEC", 1.0), 0.5),
        maker_trade_freshness_sec=max(_float("MAKER_TRADE_FRESHNESS_SEC", 10.0), 1.0),
    )
    # Apply product overlays (BTC 5m is identity — no behavioral change)
    from btc5m.products import apply_product

    cfg, _product = apply_product(cfg, series_slug)
    if cfg.mode == "split_sell":
        validate_split_parameters(cfg)
    return cfg


def validate_split_parameters(cfg: Config) -> None:
    clip, lean, size = cfg.split_clip_shares, cfg.split_max_lean_shares, cfg.split_size
    if not all(math.isfinite(x) for x in (clip, lean, size)):
        raise ValueError("split size, clip and lean must be finite")
    if clip < 5 or lean < clip or size < clip:
        raise ValueError("split requires 5 <= clip <= max_lean and clip <= mint size")
