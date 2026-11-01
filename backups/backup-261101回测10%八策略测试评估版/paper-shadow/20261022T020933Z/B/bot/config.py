"""Centralized config loaded from .env. Strategy knobs live here too."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")


@dataclass(frozen=True)
class Config:
    private_key: str
    wallet_address: str
    funder_address: str
    signature_type: int
    chain_id: int
    clob_host: str
    gamma_host: str
    polygon_rpc: str
    api_key: str
    api_secret: str
    api_passphrase: str
    # Polymarket's collateral/position wallet.  In the standard EIP-7702
    # setup this is the same address as funder_address, but keeping it
    # separate prevents balance polling from silently reading the EOA or an
    # old funder when the account has been migrated.
    deposit_wallet_address: str = ""

    series_slug: str = "btc-up-or-down-5m"
    min_entry_price: float = 0.98
    max_entry_price: float = 0.99
    up_min_entry_price: float = 0.98
    up_max_entry_price: float = 0.99
    # Defaults mirror the production conservative BTC profile.  The deployed
    # .env remains authoritative, but keeping the fallback safe prevents a
    # missing override from silently reverting to the old paper profile.
    min_net_edge: float = 0.01
    high_price_edge_threshold: float = 0.0
    high_price_min_net_edge: float = -1.0
    high_price_btc_delta_usd: float = 0.0
    taker_fee_rate: float = 0.07
    btc_delta_filter_enabled: bool = True
    btc_delta_threshold_usd: float = 0.0
    btc_up_min_delta_usd: float = 0.0
    btc_up_max_delta_usd: float = 0.0
    btc_down_min_delta_usd: float = 0.0
    btc_down_max_delta_usd: float = 0.0
    btc_price_symbol: str = "BTCUSDT"
    btc_price_hosts: str = "https://api.binance.com,https://api1.binance.com,https://api.binance.us"
    price_signal_source: str = "rtds"
    rtds_ws_url: str = "wss://ws-live-data.polymarket.com"
    rtds_topic: str = "crypto_prices_twap_thirty"
    rtds_max_age_sec: float = 5.0
    rtds_stale_max_age_sec: float = 12.0
    rtds_beat_max_start_lag_sec: float = 5.0
    rtds_initial_wait_sec: float = 3.0
    rtds_retention_sec: float = 900.0
    chainlink_btc_twap_30s_feed_id: str = ""
    chainlink_eth_twap_30s_feed_id: str = ""
    price_source_guard_enabled: bool = True
    allow_binance_proxy_chainlink_entries: bool = False
    eth_market_enabled: bool = True
    eth_trading_enabled: bool = False
    eth_series_slug: str = "eth-up-or-down-5m"
    eth_price_symbol: str = "ETHUSDT"
    eth_delta_filter_enabled: bool = True
    eth_delta_threshold_usd: float = 0.50
    eth_up_min_delta_usd: float = 0.50
    eth_up_max_delta_usd: float = 0.0
    eth_down_min_delta_usd: float = 0.0
    eth_down_max_delta_usd: float = -0.50
    eth_high_price_delta_usd: float = 0.75
    eth_early_strong_delta_up_min_delta_usd: float = 2.00
    eth_early_strong_delta_down_max_delta_usd: float = -2.00
    eth_strong_delta_up_min_delta_usd: float = 1.50
    eth_strong_delta_down_max_delta_usd: float = -1.50
    eth_late_edge_up_min_delta_usd: float = 0.0
    eth_late_edge_down_max_delta_usd: float = 0.0
    eth_late_edge_confirm_checks: int = 3
    eth_early_strong_delta_risk_fraction: float = 0.01
    eth_strong_delta_risk_fraction: float = 0.015
    eth_order_risk_fraction: float = 0.035
    eth_late_edge_risk_fraction: float = 0.04
    seconds_before_close: int = 90
    min_t_remaining_sec: float = 30.0
    mid_entry_enabled: bool = False
    mid_entry_window_sec: float = 180.0
    mid_entry_min_t_remaining_sec: float = 30.0
    mid_entry_min_price: float = 0.40
    mid_entry_max_price: float = 0.75
    mid_entry_confirm_checks: int = 2
    mid_entry_risk_fraction: float = 0.03
    mid_btc_up_min_delta_usd: float = 15.0
    mid_btc_down_max_delta_usd: float = -15.0
    strong_delta_entry_enabled: bool = False
    strong_delta_entry_window_sec: float = 160.0
    strong_delta_entry_min_t_remaining_sec: float = 120.0
    strong_delta_entry_min_price: float = 0.80
    strong_delta_entry_max_price: float = 0.90
    strong_delta_entry_up_min_delta_usd: float = 0.0
    strong_delta_entry_down_max_delta_usd: float = 0.0
    strong_delta_entry_confirm_checks: int = 4
    strong_delta_entry_risk_fraction: float = 0.035
    early_strong_delta_entry_enabled: bool = False
    early_strong_delta_entry_window_sec: float = 280.0
    early_strong_delta_entry_min_t_remaining_sec: float = 160.0
    early_strong_delta_entry_min_price: float = 0.25
    early_strong_delta_entry_max_price: float = 0.95
    early_strong_delta_entry_up_min_delta_usd: float = 0.0
    early_strong_delta_entry_down_max_delta_usd: float = 0.0
    early_strong_delta_entry_confirm_checks: int = 1
    early_strong_delta_entry_risk_fraction: float = 0.035
    early_strong_delta_entry_hedge_enabled: bool = False
    early_strong_delta_entry_hedge_max_price: float = 0.70
    late_edge_entry_enabled: bool = False
    late_edge_entry_window_sec: float = 60.0
    late_edge_entry_min_t_remaining_sec: float = 10.0
    late_edge_entry_min_price: float = 0.84
    late_edge_entry_max_price: float = 0.90
    late_edge_entry_delta_filter_enabled: bool = True
    late_edge_entry_up_min_delta_usd: float = 0.0
    late_edge_entry_down_max_delta_usd: float = 0.0
    late_edge_entry_confirm_checks: int = 3
    late_edge_entry_mid_confirm_checks: int = 3
    late_edge_entry_late_confirm_checks: int = 2
    late_edge_entry_risk_fraction: float = 0.04
    eth_late_edge_delta_filter_enabled: bool = False
    stable_delta_entry_enabled: bool = False
    stable_delta_entry_window_sec: float = 60.0
    stable_delta_entry_min_t_remaining_sec: float = 20.0
    stable_delta_entry_min_price: float = 0.84
    stable_delta_entry_max_price: float = 0.93
    stable_delta_entry_min_abs_delta_usd: float = 1.0
    stable_delta_entry_max_abs_delta_usd: float = 10.0
    stable_delta_entry_max_delta_move_usd: float = 1.0
    stable_delta_entry_confirm_checks: int = 3
    stable_delta_entry_risk_fraction: float = 0.035
    entry_momentum_filter_enabled: bool = False
    entry_momentum_min_price: float = 0.80
    entry_momentum_max_price: float = 0.93
    entry_momentum_max_ask_move: float = 0.03
    eth_stable_delta_min_abs_usd: float = 0.15
    eth_stable_delta_max_abs_usd: float = 1.00
    eth_stable_delta_max_move_usd: float = 0.30
    eth_stable_delta_trade_enabled: bool = False
    early_entry_enabled: bool = False
    early_entry_seconds_before_close: float = 210.0
    early_entry_min_price: float = 0.95
    early_entry_max_price: float = 1.0
    tail_entry_enabled: bool = False
    tail_entry_window_sec: float = 10.0
    tail_entry_min_t_remaining_sec: float = 0.0
    tail_entry_min_price: float = 0.60
    tail_entry_max_price: float = 1.0
    tail_entry_confirm_checks: int = 1
    tail_entry_risk_fraction: float = 0.03
    strong_normal_reverse_enabled: bool = False
    strong_normal_reverse_held_bid_threshold: float = 0.65
    strong_normal_reverse_min_price: float = 0.01
    strong_normal_reverse_max_price: float = 1.0
    strong_normal_reverse_confirm_checks: int = 1
    strong_normal_reverse_risk_fraction: float = 0.035
    scale_in_after_early_enabled: bool = False
    normal_scale_in_enabled: bool = False
    max_buys_per_market: int = 1
    one_side_per_market: bool = True
    trend_overheat_filter_enabled: bool = False
    trend_overheat_min_streak: int = 3
    trend_overheat_price_floor: float = 0.90
    confirm_checks: int = 2
    order_risk_fraction: float = 0.02
    order_fixed_notional_usd: float = 0.0
    order_balance_reserve_usd: float = 0.10
    paper_equity_usd: float = 100.0
    min_order_notional_usd: float = 1.0
    target_min_orders_per_hour: int = 0
    max_orders_per_hour: int = 20
    max_open_positions: int = 1
    max_daily_loss_fraction: float = 0.05
    max_daily_realized_profit_usd: float = 5.0
    consecutive_loss_kill: int = 0
    order_retry_cooldown_sec: float = 1.0
    max_buy_retries_per_market: int = 0
    retry_min_t_remaining_sec: float = 20.0
    max_retry_price_drift_ticks: int = -1
    fok_price_buffer_ticks: int = 0
    poll_interval_sec: float = 0.25
    market_stale_grace_sec: float = 30.0
    stagnation_window_sec: float = 0.0
    volatility_window_sec: float = 5.0
    max_top_move_ticks: int = 0
    early_reversal_exit_enabled: bool = False
    early_reversal_exit_window_sec: float = 200.0
    early_reversal_exit_min_t_remaining_sec: float = 160.0
    early_reversal_held_bid_threshold: float = 0.45
    early_reversal_confirm_checks: int = 3
    early_reversal_exit_fraction: float = 1.0
    reversal_exit_enabled: bool = True
    reversal_partial_exit_enabled: bool = False
    reversal_partial_exit_window_sec: float = 60.0
    reversal_partial_exit_min_t_remaining_sec: float = 30.0
    reversal_partial_held_bid_threshold: float = 0.0
    reversal_partial_held_bid_drawdown: float = 0.25
    reversal_partial_confirm_checks: int = 2
    reversal_partial_exit_fraction: float = 0.50
    reversal_exit_window_sec: float = 90.0
    reversal_normal_min_t_remaining_sec: float = 0.0
    reversal_exit_min_t_remaining_sec: float = 0.0
    reversal_opposite_bid_threshold: float = 0.55
    reversal_confirm_checks: int = 0
    reversal_held_bid_threshold: float = 0.0
    reversal_held_bid_drawdown: float = 0.20
    reversal_exit_require_btc_reversal: bool = False
    reversal_late_exit_enabled: bool = False
    reversal_late_window_sec: float = 10.0
    reversal_late_held_bid_threshold: float = 0.60
    reversal_late_confirm_checks: int = 1
    reversal_exit_order_fraction: float = 1.0
    sell_fok_slippage_ticks: int = 1
    sell_exit_max_depth_ticks: int = 5
    sell_exit_max_depth_levels: int = 10
    sell_exit_fak_fallback_enabled: bool = True
    sell_exit_reconcile_trades: bool = True
    weather_enabled: bool = True
    weather_live_trading_enabled: bool = False
    weather_cities: str = "nyc,chicago,miami,los_angeles,denver"
    weather_scan_interval_sec: float = 300.0
    weather_market_scan_pages: int = 25
    weather_min_edge: float = 0.08
    weather_min_entry_price: float = 0.05
    weather_max_entry_price: float = 0.70
    weather_max_ensemble_std_f: float = 6.0
    weather_order_risk_fraction: float = 0.02
    weather_max_markets_per_cycle: int = 5
    weather_forecast_cache_ttl_sec: float = 900.0
    weather_max_days_ahead: int = 3
    # Sports scanner is an isolated paper service.  There is intentionally no
    # sports live-trading flag: the sports module rejects live mode outright.
    sports_enabled: bool = False
    sports_market_scan_pages: int = 5
    sports_max_days_ahead: int = 30
    sports_min_edge: float = 0.05
    sports_min_entry_price: float = 0.05
    sports_max_entry_price: float = 0.95
    sports_max_exposure_usd: float = 5.0
    sports_order_size: float = 1.0
    sports_confirm_checks: int = 1
    # Deployment identity and live capability gates.  ``polyauto`` is an
    # isolated paper-first instance; its BTC live switch is explicit and all
    # other asset live paths are permanently disabled by the loader.
    instance_name: str = "main"
    btc_live_enabled: bool = False
    eth_live_allowed: bool = True
    weather_live_allowed: bool = True
    sports_live_allowed: bool = False

    @property
    def effective_min_order_notional_usd(self) -> float:
        return max(self.min_order_notional_usd, 1.0)


def load() -> Config:
    def _bool(name: str, default: bool) -> bool:
        raw = os.environ.get(name)
        if raw is None:
            return default
        return raw.strip().lower() in ("1", "true", "yes", "y", "on")

    def _float(name: str, default: float) -> float:
        return float(os.environ.get(name, default))

    def _int(name: str, default: int) -> int:
        return int(os.environ.get(name, default))

    polyauto_instance = (
        os.environ.get("POLYAUTO_INSTANCE", "").strip().lower() in ("1", "true", "yes", "on", "auto")
        or os.environ.get("INSTANCE_NAME", "").strip().lower() == "polyauto"
    )
    required_credentials = {
        "PRIVATE_KEY": os.environ.get("PRIVATE_KEY", ""),
        "WALLET_ADDRESS": os.environ.get("WALLET_ADDRESS", ""),
        "FUNDER_ADDRESS": os.environ.get("FUNDER_ADDRESS", ""),
        "CLOB_API_KEY": os.environ.get("CLOB_API_KEY", ""),
        "CLOB_API_SECRET": os.environ.get("CLOB_API_SECRET", ""),
        "CLOB_API_PASSPHRASE": os.environ.get("CLOB_API_PASSPHRASE", ""),
    }
    # Paper-only polyauto can run without copied wallet or CLOB secrets.  The
    # guarded live preflight still requires every credential before enabling
    # BTC live.  Preserve the historical fail-fast behaviour for main.
    if not polyauto_instance and os.environ.get("REQUIRE_CREDENTIALS", "").strip().lower() in ("1", "true", "yes", "on"):
        missing = [name for name, value in required_credentials.items() if not value]
        if missing:
            raise KeyError(missing[0])
    # These gates are evaluated before constructing the immutable config so a
    # ETH live is an explicit per-service opt-in in polyauto. Weather remains
    # paper-only in the isolated instance.
    eth_live = _bool("ETH_TRADING_ENABLED", False)
    weather_live = _bool("WEATHER_LIVE_TRADING_ENABLED", False) and not polyauto_instance
    return Config(
        private_key=required_credentials["PRIVATE_KEY"],
        wallet_address=required_credentials["WALLET_ADDRESS"],
        funder_address=required_credentials["FUNDER_ADDRESS"],
        deposit_wallet_address=(
            os.environ.get("DEPOSIT_WALLET_ADDRESS", "").strip()
            or required_credentials["FUNDER_ADDRESS"]
        ),
        signature_type=int(os.environ.get("SIGNATURE_TYPE", "0")),
        chain_id=int(os.environ.get("CHAIN_ID", "137")),
        clob_host=os.environ.get("CLOB_HOST", "https://clob.polymarket.com"),
        gamma_host=os.environ.get("GAMMA_HOST", "https://gamma-api.polymarket.com"),
        polygon_rpc=os.environ.get(
            "POLYGON_RPC_URL", "https://polygon-bor-rpc.publicnode.com"
        ),
        api_key=required_credentials["CLOB_API_KEY"],
        api_secret=required_credentials["CLOB_API_SECRET"],
        api_passphrase=required_credentials["CLOB_API_PASSPHRASE"],
        series_slug=os.environ.get("SERIES_SLUG", "btc-up-or-down-5m"),
        min_entry_price=_float("MIN_ENTRY_PRICE", 0.98),
        max_entry_price=_float("MAX_ENTRY_PRICE", 0.99),
        up_min_entry_price=_float("UP_MIN_ENTRY_PRICE", 0.98),
        up_max_entry_price=_float("UP_MAX_ENTRY_PRICE", 0.99),
        min_net_edge=_float("MIN_NET_EDGE", 0.01),
        high_price_edge_threshold=_float("HIGH_PRICE_EDGE_THRESHOLD", 0.0),
        high_price_min_net_edge=_float("HIGH_PRICE_MIN_NET_EDGE", -1.0),
        high_price_btc_delta_usd=_float("HIGH_PRICE_BTC_DELTA_USD", 0.0),
        taker_fee_rate=_float("TAKER_FEE_RATE", 0.07),
        btc_delta_filter_enabled=_bool("BTC_DELTA_FILTER_ENABLED", True),
        btc_delta_threshold_usd=_float("BTC_DELTA_THRESHOLD_USD", 0.0),
        btc_up_min_delta_usd=_float("BTC_UP_MIN_DELTA_USD", 0.0),
        btc_up_max_delta_usd=_float("BTC_UP_MAX_DELTA_USD", 0.0),
        btc_down_min_delta_usd=_float("BTC_DOWN_MIN_DELTA_USD", 0.0),
        btc_down_max_delta_usd=_float("BTC_DOWN_MAX_DELTA_USD", 0.0),
        btc_price_symbol=os.environ.get("BTC_PRICE_SYMBOL", "BTCUSDT"),
        btc_price_hosts=os.environ.get(
            "BTC_PRICE_HOSTS",
            "https://api.binance.com,https://api1.binance.com,https://api.binance.us",
        ),
        price_signal_source=os.environ.get("PRICE_SIGNAL_SOURCE", "rtds"),
        rtds_ws_url=os.environ.get("RTDS_WS_URL", "wss://ws-live-data.polymarket.com"),
        rtds_topic=os.environ.get("RTDS_TOPIC", "crypto_prices_twap_thirty"),
        rtds_max_age_sec=_float("RTDS_MAX_AGE_SEC", 5.0),
        rtds_stale_max_age_sec=_float("RTDS_STALE_MAX_AGE_SEC", 12.0),
        rtds_beat_max_start_lag_sec=_float("RTDS_BEAT_MAX_START_LAG_SEC", 5.0),
        rtds_initial_wait_sec=_float("RTDS_INITIAL_WAIT_SEC", 3.0),
        rtds_retention_sec=_float("RTDS_RETENTION_SEC", 900.0),
        chainlink_btc_twap_30s_feed_id=os.environ.get("CHAINLINK_BTC_TWAP_30S_FEED_ID", ""),
        chainlink_eth_twap_30s_feed_id=os.environ.get("CHAINLINK_ETH_TWAP_30S_FEED_ID", ""),
        price_source_guard_enabled=_bool("PRICE_SOURCE_GUARD_ENABLED", True),
        allow_binance_proxy_chainlink_entries=_bool("ALLOW_BINANCE_PROXY_CHAINLINK_ENTRIES", False),
        eth_market_enabled=_bool("ETH_MARKET_ENABLED", True),
        eth_trading_enabled=eth_live,
        eth_series_slug=os.environ.get("ETH_SERIES_SLUG", "eth-up-or-down-5m"),
        eth_price_symbol=os.environ.get("ETH_PRICE_SYMBOL", "ETHUSDT"),
        eth_delta_filter_enabled=_bool("ETH_DELTA_FILTER_ENABLED", True),
        eth_delta_threshold_usd=_float("ETH_DELTA_THRESHOLD_USD", 0.50),
        eth_up_min_delta_usd=_float("ETH_UP_MIN_DELTA_USD", 0.50),
        eth_up_max_delta_usd=_float("ETH_UP_MAX_DELTA_USD", 0.0),
        eth_down_min_delta_usd=_float("ETH_DOWN_MIN_DELTA_USD", 0.0),
        eth_down_max_delta_usd=_float("ETH_DOWN_MAX_DELTA_USD", -0.50),
        eth_high_price_delta_usd=_float("ETH_HIGH_PRICE_DELTA_USD", 0.75),
        eth_early_strong_delta_up_min_delta_usd=_float("ETH_EARLY_STRONG_DELTA_UP_MIN_DELTA_USD", 2.00),
        eth_early_strong_delta_down_max_delta_usd=_float("ETH_EARLY_STRONG_DELTA_DOWN_MAX_DELTA_USD", -2.00),
        eth_strong_delta_up_min_delta_usd=_float("ETH_STRONG_DELTA_UP_MIN_DELTA_USD", 1.50),
        eth_strong_delta_down_max_delta_usd=_float("ETH_STRONG_DELTA_DOWN_MAX_DELTA_USD", -1.50),
        eth_late_edge_up_min_delta_usd=_float("ETH_LATE_EDGE_UP_MIN_DELTA_USD", 0.0),
        eth_late_edge_down_max_delta_usd=_float("ETH_LATE_EDGE_DOWN_MAX_DELTA_USD", 0.0),
        eth_late_edge_confirm_checks=_int("ETH_LATE_EDGE_CONFIRM_CHECKS", 3),
        eth_early_strong_delta_risk_fraction=_float("ETH_EARLY_STRONG_DELTA_RISK_FRACTION", 0.01),
        eth_strong_delta_risk_fraction=_float("ETH_STRONG_DELTA_RISK_FRACTION", 0.015),
        eth_order_risk_fraction=_float("ETH_ORDER_RISK_FRACTION", 0.035),
        eth_late_edge_risk_fraction=_float("ETH_LATE_EDGE_RISK_FRACTION", 0.04),
        seconds_before_close=_int("SECONDS_BEFORE_CLOSE", 90),
        min_t_remaining_sec=_float("MIN_T_REMAINING_SEC", 30.0),
        mid_entry_enabled=_bool("MID_ENTRY_ENABLED", False),
        mid_entry_window_sec=_float("MID_ENTRY_WINDOW_SEC", 180.0),
        mid_entry_min_t_remaining_sec=_float("MID_ENTRY_MIN_T_REMAINING_SEC", 30.0),
        mid_entry_min_price=_float("MID_ENTRY_MIN_PRICE", 0.40),
        mid_entry_max_price=_float("MID_ENTRY_MAX_PRICE", 0.75),
        mid_entry_confirm_checks=_int("MID_ENTRY_CONFIRM_CHECKS", 2),
        mid_entry_risk_fraction=_float("MID_ENTRY_RISK_FRACTION", 0.03),
        mid_btc_up_min_delta_usd=_float("MID_BTC_UP_MIN_DELTA_USD", 15.0),
        mid_btc_down_max_delta_usd=_float("MID_BTC_DOWN_MAX_DELTA_USD", -15.0),
        strong_delta_entry_enabled=_bool("STRONG_DELTA_ENTRY_ENABLED", False),
        strong_delta_entry_window_sec=_float("STRONG_DELTA_ENTRY_WINDOW_SEC", 160.0),
        strong_delta_entry_min_t_remaining_sec=_float("STRONG_DELTA_ENTRY_MIN_T_REMAINING_SEC", 120.0),
        strong_delta_entry_min_price=_float("STRONG_DELTA_ENTRY_MIN_PRICE", 0.80),
        strong_delta_entry_max_price=_float("STRONG_DELTA_ENTRY_MAX_PRICE", 0.90),
        strong_delta_entry_up_min_delta_usd=_float("STRONG_DELTA_ENTRY_UP_MIN_DELTA_USD", 0.0),
        strong_delta_entry_down_max_delta_usd=_float("STRONG_DELTA_ENTRY_DOWN_MAX_DELTA_USD", 0.0),
        strong_delta_entry_confirm_checks=_int("STRONG_DELTA_ENTRY_CONFIRM_CHECKS", 4),
        strong_delta_entry_risk_fraction=_float("STRONG_DELTA_ENTRY_RISK_FRACTION", 0.035),
        early_strong_delta_entry_enabled=_bool("EARLY_STRONG_DELTA_ENTRY_ENABLED", False),
        early_strong_delta_entry_window_sec=_float("EARLY_STRONG_DELTA_ENTRY_WINDOW_SEC", 280.0),
        early_strong_delta_entry_min_t_remaining_sec=_float("EARLY_STRONG_DELTA_ENTRY_MIN_T_REMAINING_SEC", 160.0),
        early_strong_delta_entry_min_price=_float("EARLY_STRONG_DELTA_ENTRY_MIN_PRICE", 0.25),
        early_strong_delta_entry_max_price=_float("EARLY_STRONG_DELTA_ENTRY_MAX_PRICE", 0.95),
        early_strong_delta_entry_up_min_delta_usd=_float("EARLY_STRONG_DELTA_ENTRY_UP_MIN_DELTA_USD", 0.0),
        early_strong_delta_entry_down_max_delta_usd=_float("EARLY_STRONG_DELTA_ENTRY_DOWN_MAX_DELTA_USD", 0.0),
        early_strong_delta_entry_confirm_checks=_int("EARLY_STRONG_DELTA_ENTRY_CONFIRM_CHECKS", 1),
        early_strong_delta_entry_risk_fraction=_float("EARLY_STRONG_DELTA_ENTRY_RISK_FRACTION", 0.035),
        early_strong_delta_entry_hedge_enabled=_bool("EARLY_STRONG_DELTA_ENTRY_HEDGE_ENABLED", False),
        early_strong_delta_entry_hedge_max_price=_float("EARLY_STRONG_DELTA_ENTRY_HEDGE_MAX_PRICE", 0.70),
        late_edge_entry_enabled=_bool("LATE_EDGE_ENTRY_ENABLED", False),
        late_edge_entry_window_sec=_float("LATE_EDGE_ENTRY_WINDOW_SEC", 60.0),
        late_edge_entry_min_t_remaining_sec=_float("LATE_EDGE_ENTRY_MIN_T_REMAINING_SEC", 10.0),
        late_edge_entry_min_price=_float("LATE_EDGE_ENTRY_MIN_PRICE", 0.84),
        late_edge_entry_max_price=_float("LATE_EDGE_ENTRY_MAX_PRICE", 0.90),
        late_edge_entry_delta_filter_enabled=_bool("LATE_EDGE_ENTRY_DELTA_FILTER_ENABLED", True),
        late_edge_entry_up_min_delta_usd=_float("LATE_EDGE_ENTRY_UP_MIN_DELTA_USD", 0.0),
        late_edge_entry_down_max_delta_usd=_float("LATE_EDGE_ENTRY_DOWN_MAX_DELTA_USD", 0.0),
        late_edge_entry_confirm_checks=_int("LATE_EDGE_ENTRY_CONFIRM_CHECKS", 3),
        late_edge_entry_mid_confirm_checks=_int("LATE_EDGE_ENTRY_MID_CONFIRM_CHECKS", 3),
        late_edge_entry_late_confirm_checks=_int("LATE_EDGE_ENTRY_LATE_CONFIRM_CHECKS", 2),
        late_edge_entry_risk_fraction=_float("LATE_EDGE_ENTRY_RISK_FRACTION", 0.035),
        eth_late_edge_delta_filter_enabled=_bool("ETH_LATE_EDGE_DELTA_FILTER_ENABLED", False),
        stable_delta_entry_enabled=_bool("STABLE_DELTA_ENTRY_ENABLED", False),
        stable_delta_entry_window_sec=_float("STABLE_DELTA_ENTRY_WINDOW_SEC", 60.0),
        stable_delta_entry_min_t_remaining_sec=_float("STABLE_DELTA_ENTRY_MIN_T_REMAINING_SEC", 20.0),
        stable_delta_entry_min_price=_float("STABLE_DELTA_ENTRY_MIN_PRICE", 0.84),
        stable_delta_entry_max_price=_float("STABLE_DELTA_ENTRY_MAX_PRICE", 0.93),
        stable_delta_entry_min_abs_delta_usd=_float("STABLE_DELTA_ENTRY_MIN_ABS_DELTA_USD", 1.0),
        stable_delta_entry_max_abs_delta_usd=_float("STABLE_DELTA_ENTRY_MAX_ABS_DELTA_USD", 10.0),
        stable_delta_entry_max_delta_move_usd=_float("STABLE_DELTA_ENTRY_MAX_DELTA_MOVE_USD", 1.0),
        stable_delta_entry_confirm_checks=_int("STABLE_DELTA_ENTRY_CONFIRM_CHECKS", 3),
        stable_delta_entry_risk_fraction=_float("STABLE_DELTA_ENTRY_RISK_FRACTION", 0.035),
        entry_momentum_filter_enabled=_bool("ENTRY_MOMENTUM_FILTER_ENABLED", False),
        entry_momentum_min_price=_float("ENTRY_MOMENTUM_MIN_PRICE", 0.80),
        entry_momentum_max_price=_float("ENTRY_MOMENTUM_MAX_PRICE", 0.95),
        entry_momentum_max_ask_move=_float("ENTRY_MOMENTUM_MAX_ASK_MOVE", 0.0),
        eth_stable_delta_min_abs_usd=_float("ETH_STABLE_DELTA_MIN_ABS_USD", 0.15),
        eth_stable_delta_max_abs_usd=_float("ETH_STABLE_DELTA_MAX_ABS_USD", 1.00),
        eth_stable_delta_max_move_usd=_float("ETH_STABLE_DELTA_MAX_MOVE_USD", 0.30),
        eth_stable_delta_trade_enabled=_bool("ETH_STABLE_DELTA_TRADE_ENABLED", False),
        early_entry_enabled=_bool("EARLY_ENTRY_ENABLED", False),
        early_entry_seconds_before_close=_float("EARLY_ENTRY_SECONDS_BEFORE_CLOSE", 210.0),
        early_entry_min_price=_float("EARLY_ENTRY_MIN_PRICE", 0.95),
        early_entry_max_price=_float("EARLY_ENTRY_MAX_PRICE", 1.0),
        tail_entry_enabled=_bool("TAIL_ENTRY_ENABLED", False),
        tail_entry_window_sec=_float("TAIL_ENTRY_WINDOW_SEC", 10.0),
        tail_entry_min_t_remaining_sec=_float("TAIL_ENTRY_MIN_T_REMAINING_SEC", 0.0),
        tail_entry_min_price=_float("TAIL_ENTRY_MIN_PRICE", 0.78),
        tail_entry_max_price=_float("TAIL_ENTRY_MAX_PRICE", 0.99),
        tail_entry_confirm_checks=_int("TAIL_ENTRY_CONFIRM_CHECKS", 1),
        tail_entry_risk_fraction=_float("TAIL_ENTRY_RISK_FRACTION", 0.035),
        strong_normal_reverse_enabled=_bool("STRONG_NORMAL_REVERSE_ENABLED", False),
        strong_normal_reverse_held_bid_threshold=_float("STRONG_NORMAL_REVERSE_HELD_BID_THRESHOLD", 0.65),
        strong_normal_reverse_min_price=_float("STRONG_NORMAL_REVERSE_MIN_PRICE", 0.01),
        strong_normal_reverse_max_price=_float("STRONG_NORMAL_REVERSE_MAX_PRICE", 1.0),
        strong_normal_reverse_confirm_checks=_int("STRONG_NORMAL_REVERSE_CONFIRM_CHECKS", 1),
        strong_normal_reverse_risk_fraction=_float("STRONG_NORMAL_REVERSE_RISK_FRACTION", 0.035),
        scale_in_after_early_enabled=_bool("SCALE_IN_AFTER_EARLY_ENABLED", False),
        normal_scale_in_enabled=_bool("NORMAL_SCALE_IN_ENABLED", False),
        max_buys_per_market=_int("MAX_BUYS_PER_MARKET", 1),
        one_side_per_market=_bool("ONE_SIDE_PER_MARKET", True),
        trend_overheat_filter_enabled=_bool("TREND_OVERHEAT_FILTER_ENABLED", False),
        trend_overheat_min_streak=_int("TREND_OVERHEAT_MIN_STREAK", 3),
        trend_overheat_price_floor=_float("TREND_OVERHEAT_PRICE_FLOOR", 0.90),
        confirm_checks=_int("CONFIRM_CHECKS", 2),
        order_risk_fraction=_float("ORDER_RISK_FRACTION", 0.02),
        order_fixed_notional_usd=_float("ORDER_FIXED_NOTIONAL_USD", 0.0),
        order_balance_reserve_usd=_float("ORDER_BALANCE_RESERVE_USD", 0.10),
        paper_equity_usd=_float("PAPER_EQUITY_USD", 100.0),
        min_order_notional_usd=_float("MIN_ORDER_NOTIONAL_USD", 1.0),
        target_min_orders_per_hour=_int("TARGET_MIN_ORDERS_PER_HOUR", 0),
        max_orders_per_hour=_int("MAX_ORDERS_PER_HOUR", 20),
        max_open_positions=_int("MAX_OPEN_POSITIONS", 1),
        max_daily_loss_fraction=_float("MAX_DAILY_LOSS_FRACTION", 0.05),
        max_daily_realized_profit_usd=_float("MAX_DAILY_REALIZED_PROFIT_USD", 5.0),
        consecutive_loss_kill=_int("CONSECUTIVE_LOSS_KILL", 0),
        order_retry_cooldown_sec=_float("ORDER_RETRY_COOLDOWN_SEC", 1.0),
        max_buy_retries_per_market=_int("MAX_BUY_RETRIES_PER_MARKET", 0),
        retry_min_t_remaining_sec=_float("RETRY_MIN_T_REMAINING_SEC", 20.0),
        max_retry_price_drift_ticks=_int("MAX_RETRY_PRICE_DRIFT_TICKS", -1),
        fok_price_buffer_ticks=_int("FOK_PRICE_BUFFER_TICKS", 0),
        poll_interval_sec=_float("POLL_INTERVAL_SEC", 0.25),
        market_stale_grace_sec=_float("MARKET_STALE_GRACE_SEC", 30.0),
        stagnation_window_sec=_float("STAGNATION_WINDOW_SEC", 0.0),
        volatility_window_sec=_float("VOLATILITY_WINDOW_SEC", 5.0),
        max_top_move_ticks=_int("MAX_TOP_MOVE_TICKS", 0),
        early_reversal_exit_enabled=_bool("EARLY_REVERSAL_EXIT_ENABLED", False),
        early_reversal_exit_window_sec=_float("EARLY_REVERSAL_EXIT_WINDOW_SEC", 200.0),
        early_reversal_exit_min_t_remaining_sec=_float("EARLY_REVERSAL_EXIT_MIN_T_REMAINING_SEC", 160.0),
        early_reversal_held_bid_threshold=_float("EARLY_REVERSAL_HELD_BID_THRESHOLD", 0.45),
        early_reversal_confirm_checks=_int("EARLY_REVERSAL_CONFIRM_CHECKS", 3),
        early_reversal_exit_fraction=_float("EARLY_REVERSAL_EXIT_FRACTION", 1.0),
        reversal_exit_enabled=_bool("REVERSAL_EXIT_ENABLED", True),
        reversal_partial_exit_enabled=_bool("REVERSAL_PARTIAL_EXIT_ENABLED", False),
        reversal_partial_exit_window_sec=_float("REVERSAL_PARTIAL_EXIT_WINDOW_SEC", 60.0),
        reversal_partial_exit_min_t_remaining_sec=_float("REVERSAL_PARTIAL_EXIT_MIN_T_REMAINING_SEC", 30.0),
        reversal_partial_held_bid_threshold=_float("REVERSAL_PARTIAL_HELD_BID_THRESHOLD", 0.0),
        reversal_partial_held_bid_drawdown=_float("REVERSAL_PARTIAL_HELD_BID_DRAWDOWN", 0.25),
        reversal_partial_confirm_checks=_int("REVERSAL_PARTIAL_CONFIRM_CHECKS", 2),
        reversal_partial_exit_fraction=_float("REVERSAL_PARTIAL_EXIT_FRACTION", 0.50),
        reversal_exit_window_sec=_float("REVERSAL_EXIT_WINDOW_SEC", 90.0),
        reversal_normal_min_t_remaining_sec=_float("REVERSAL_NORMAL_MIN_T_REMAINING_SEC", 0.0),
        reversal_exit_min_t_remaining_sec=_float("REVERSAL_EXIT_MIN_T_REMAINING_SEC", 0.0),
        reversal_opposite_bid_threshold=_float("REVERSAL_OPPOSITE_BID_THRESHOLD", 0.55),
        reversal_confirm_checks=_int("REVERSAL_CONFIRM_CHECKS", 0),
        reversal_held_bid_threshold=_float("REVERSAL_HELD_BID_THRESHOLD", 0.0),
        reversal_held_bid_drawdown=_float("REVERSAL_HELD_BID_DRAWDOWN", 0.20),
        reversal_exit_require_btc_reversal=_bool("REVERSAL_EXIT_REQUIRE_BTC_REVERSAL", False),
        reversal_late_exit_enabled=_bool("REVERSAL_LATE_EXIT_ENABLED", False),
        reversal_late_window_sec=_float("REVERSAL_LATE_WINDOW_SEC", 10.0),
        reversal_late_held_bid_threshold=_float("REVERSAL_LATE_HELD_BID_THRESHOLD", 0.60),
        reversal_late_confirm_checks=_int("REVERSAL_LATE_CONFIRM_CHECKS", 1),
        reversal_exit_order_fraction=_float("REVERSAL_EXIT_ORDER_FRACTION", 1.0),
        sell_fok_slippage_ticks=_int("SELL_FOK_SLIPPAGE_TICKS", 1),
        sell_exit_max_depth_ticks=_int("SELL_EXIT_MAX_DEPTH_TICKS", 5),
        sell_exit_max_depth_levels=_int("SELL_EXIT_MAX_DEPTH_LEVELS", 10),
        sell_exit_fak_fallback_enabled=_bool("SELL_EXIT_FAK_FALLBACK_ENABLED", True),
        sell_exit_reconcile_trades=_bool("SELL_EXIT_RECONCILE_TRADES", True),
        weather_enabled=_bool("WEATHER_ENABLED", True),
        weather_live_trading_enabled=weather_live,
        weather_cities=os.environ.get(
            "WEATHER_CITIES",
            "nyc,chicago,miami,los_angeles,denver",
        ),
        weather_scan_interval_sec=_float("WEATHER_SCAN_INTERVAL_SEC", 300.0),
        weather_market_scan_pages=_int("WEATHER_MARKET_SCAN_PAGES", 25),
        weather_min_edge=_float("WEATHER_MIN_EDGE", 0.08),
        weather_min_entry_price=_float("WEATHER_MIN_ENTRY_PRICE", 0.05),
        weather_max_entry_price=_float("WEATHER_MAX_ENTRY_PRICE", 0.70),
        weather_max_ensemble_std_f=_float("WEATHER_MAX_ENSEMBLE_STD_F", 6.0),
        weather_order_risk_fraction=_float("WEATHER_ORDER_RISK_FRACTION", 0.02),
        weather_max_markets_per_cycle=_int("WEATHER_MAX_MARKETS_PER_CYCLE", 5),
        weather_forecast_cache_ttl_sec=_float(
            "WEATHER_FORECAST_CACHE_TTL_SEC", 900.0
        ),
        weather_max_days_ahead=_int("WEATHER_MAX_DAYS_AHEAD", 3),
        sports_enabled=_bool("SPORTS_ENABLED", False),
        sports_market_scan_pages=_int("SPORTS_MARKET_SCAN_PAGES", 5),
        sports_max_days_ahead=_int("SPORTS_MAX_DAYS_AHEAD", 30),
        sports_min_edge=_float("SPORTS_MIN_EDGE", 0.05),
        sports_min_entry_price=_float("SPORTS_MIN_ENTRY_PRICE", 0.05),
        sports_max_entry_price=_float("SPORTS_MAX_ENTRY_PRICE", 0.95),
        sports_max_exposure_usd=_float("SPORTS_MAX_EXPOSURE_USD", 5.0),
        sports_order_size=_float("SPORTS_ORDER_SIZE", 1.0),
        sports_confirm_checks=_int("SPORTS_CONFIRM_CHECKS", 1),
        instance_name=("polyauto" if polyauto_instance else os.environ.get("INSTANCE_NAME", "main").strip() or "main"),
        # Main keeps its historical behaviour (the guarded launcher and
        # preflight remain the authority).  polyauto must opt in explicitly.
        btc_live_enabled=_bool("BTC_LIVE_ENABLED", not polyauto_instance),
        eth_live_allowed=True,
        weather_live_allowed=not polyauto_instance,
        sports_live_allowed=False,
    )
