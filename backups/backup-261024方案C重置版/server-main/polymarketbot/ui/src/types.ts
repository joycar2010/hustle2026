export interface Wallet {
  eoa: string;
  deposit: string;
  funder?: string;
  balance_pusd: number | null;
  value_usd: number | null;
}

export interface Market {
  condition_id: string;
  market_slug: string;
  up_token: string;
  down_token: string;
  start_ts: number;
  end_ts: number;
  tick_size: number;
  neg_risk: boolean;
  resolution_source?: string;
  t_remaining: number;
  synthetic?: boolean;
}

export interface Book {
  best_bid: number | null;
  bid_size: number;
  best_ask: number | null;
  ask_size: number;
}

export interface BtcSignal {
  ts: number;
  symbol: string;
  source: string;
  source_ts?: number | null;
  age_sec?: number | null;
  feed_id?: string;
  price_to_beat: number;
  current_price: number;
  delta_usd: number;
  signal_side: 'UP' | 'DOWN' | 'FLAT';
  threshold_usd: number;
  up_min_delta_usd: number;
  up_max_delta_usd: number;
  down_min_delta_usd: number;
  down_max_delta_usd: number;
  stale?: boolean;
}

export interface Position {
  conditionId: string;
  title?: string;
  outcome?: string;
  size?: number;
  curPrice?: number;
  realizedPnl?: number;
  redeemable?: boolean;
  [k: string]: unknown;
}

export interface Decision {
  id: number;
  ts: number;
  asset: string | null;
  market_slug: string;
  side: string | null;
  t_remaining: number;
  ask_price: number | null;
  ask_size: number | null;
  action: string;
  reason: string;
  dry_run: number;
}

export interface Order {
  id: number;
  ts: number;
  asset: string | null;
  market_slug: string;
  condition_id: string;
  token_id: string;
  side: string;
  size: number;
  price: number;
  order_id: string | null;
  status: string;
  filled_size: number;
  error: string | null;
  entry_rule: string | null;
  dry_run: number;
  winning_token: string | null;
  resolved_ts: number | null;
  settled: boolean;
  result:
    | 'HIT'
    | 'MISS'
    | 'PENDING'
    | 'FAILED'
    | 'UNCERTAIN'
    | 'EXITED'
    | 'PARTIAL_EXIT'
    | 'EXIT_FAILED'
    | 'EXIT_UNCERTAIN'
    | 'NONE';
}

export interface PnL {
  realized_usd: number;
  wins: number;
  losses: number;
  pending: number;
  period_start_ts: number;
}

export interface Config {
  min_entry_price: number;
  max_entry_price: number;
  up_min_entry_price: number;
  up_max_entry_price: number;
  min_net_edge: number;
  high_price_edge_threshold: number;
  high_price_min_net_edge: number;
  high_price_btc_delta_usd: number;
  btc_delta_filter_enabled: boolean;
  btc_delta_threshold_usd: number;
  btc_up_min_delta_usd: number;
  btc_up_max_delta_usd: number;
  btc_down_min_delta_usd: number;
  btc_down_max_delta_usd: number;
  btc_price_symbol: string;
  price_signal_source: string;
  rtds_ws_url: string;
  rtds_topic: string;
  rtds_max_age_sec: number;
  rtds_stale_max_age_sec: number;
  chainlink_btc_twap_30s_feed_id: string;
  chainlink_eth_twap_30s_feed_id: string;
  price_source_guard_enabled: boolean;
  allow_binance_proxy_chainlink_entries: boolean;
  eth_market_enabled: boolean;
  eth_trading_enabled: boolean;
  eth_series_slug: string;
  eth_price_symbol: string;
  eth_delta_filter_enabled: boolean;
  eth_delta_threshold_usd: number;
  eth_up_min_delta_usd: number;
  eth_up_max_delta_usd: number;
  eth_down_min_delta_usd: number;
  eth_down_max_delta_usd: number;
  eth_high_price_delta_usd: number;
  eth_early_strong_delta_up_min_delta_usd: number;
  eth_early_strong_delta_down_max_delta_usd: number;
  eth_strong_delta_up_min_delta_usd: number;
  eth_strong_delta_down_max_delta_usd: number;
  eth_late_edge_up_min_delta_usd: number;
  eth_late_edge_down_max_delta_usd: number;
  eth_late_edge_confirm_checks: number;
  eth_early_strong_delta_risk_fraction: number;
  eth_strong_delta_risk_fraction: number;
  eth_order_risk_fraction: number;
  eth_late_edge_risk_fraction: number;
  seconds_before_close: number;
  min_t_remaining_sec: number;
  mid_entry_enabled: boolean;
  mid_entry_window_sec: number;
  mid_entry_min_t_remaining_sec: number;
  mid_entry_min_price: number;
  mid_entry_max_price: number;
  mid_entry_confirm_checks: number;
  mid_entry_risk_fraction: number;
  mid_btc_up_min_delta_usd: number;
  mid_btc_down_max_delta_usd: number;
  strong_delta_entry_enabled: boolean;
  strong_delta_entry_window_sec: number;
  strong_delta_entry_min_t_remaining_sec: number;
  strong_delta_entry_min_price: number;
  strong_delta_entry_max_price: number;
  strong_delta_entry_up_min_delta_usd: number;
  strong_delta_entry_down_max_delta_usd: number;
  strong_delta_entry_confirm_checks: number;
  early_strong_delta_entry_enabled: boolean;
  early_strong_delta_entry_window_sec: number;
  early_strong_delta_entry_min_t_remaining_sec: number;
  early_strong_delta_entry_min_price: number;
  early_strong_delta_entry_max_price: number;
  early_strong_delta_entry_up_min_delta_usd: number;
  early_strong_delta_entry_down_max_delta_usd: number;
  early_strong_delta_entry_confirm_checks: number;
  early_strong_delta_entry_hedge_enabled: boolean;
  early_strong_delta_entry_hedge_max_price: number;
  late_edge_entry_enabled: boolean;
  late_edge_entry_window_sec: number;
  late_edge_entry_min_t_remaining_sec: number;
  late_edge_entry_min_price: number;
  late_edge_entry_max_price: number;
  late_edge_entry_delta_filter_enabled: boolean;
  late_edge_entry_up_min_delta_usd: number;
  late_edge_entry_down_max_delta_usd: number;
  late_edge_entry_confirm_checks: number;
  late_edge_entry_mid_confirm_checks: number;
  late_edge_entry_late_confirm_checks: number;
  late_edge_entry_risk_fraction: number;
  eth_late_edge_delta_filter_enabled: boolean;
  stable_delta_entry_enabled: boolean;
  stable_delta_entry_window_sec: number;
  stable_delta_entry_min_t_remaining_sec: number;
  stable_delta_entry_min_price: number;
  stable_delta_entry_max_price: number;
  stable_delta_entry_min_abs_delta_usd: number;
  stable_delta_entry_max_abs_delta_usd: number;
  stable_delta_entry_max_delta_move_usd: number;
  stable_delta_entry_confirm_checks: number;
  stable_delta_entry_risk_fraction: number;
  entry_momentum_filter_enabled: boolean;
  entry_momentum_min_price: number;
  entry_momentum_max_price: number;
  entry_momentum_max_ask_move: number;
  eth_stable_delta_min_abs_usd: number;
  eth_stable_delta_max_abs_usd: number;
  eth_stable_delta_max_move_usd: number;
  eth_stable_delta_trade_enabled: boolean;
  early_entry_enabled: boolean;
  early_entry_seconds_before_close: number;
  early_entry_min_price: number;
  early_entry_max_price: number;
  tail_entry_enabled: boolean;
  tail_entry_window_sec: number;
  tail_entry_min_t_remaining_sec: number;
  tail_entry_min_price: number;
  tail_entry_max_price: number;
  tail_entry_confirm_checks: number;
  tail_entry_risk_fraction: number;
  strong_normal_reverse_enabled: boolean;
  strong_normal_reverse_held_bid_threshold: number;
  strong_normal_reverse_min_price: number;
  strong_normal_reverse_max_price: number;
  strong_normal_reverse_confirm_checks: number;
  strong_normal_reverse_risk_fraction: number;
  scale_in_after_early_enabled: boolean;
  normal_scale_in_enabled: boolean;
  max_buys_per_market: number;
  one_side_per_market: boolean;
  trend_overheat_filter_enabled: boolean;
  trend_overheat_min_streak: number;
  trend_overheat_price_floor: number;
  order_risk_fraction: number;
  order_fixed_notional_usd: number;
  order_balance_reserve_usd: number;
  min_order_notional_usd: number;
  target_min_orders_per_hour: number;
  max_orders_per_hour: number;
  max_open_positions: number;
  max_daily_loss_fraction: number;
  max_daily_realized_profit_usd: number;
  order_retry_cooldown_sec: number;
  max_buy_retries_per_market: number;
  retry_min_t_remaining_sec: number;
  max_retry_price_drift_ticks: number;
  fok_price_buffer_ticks: number;
  market_stale_grace_sec: number;
  confirm_checks: number;
  stagnation_window_sec: number;
  volatility_window_sec: number;
  max_top_move_ticks: number;
  early_reversal_exit_enabled: boolean;
  early_reversal_exit_window_sec: number;
  early_reversal_exit_min_t_remaining_sec: number;
  early_reversal_held_bid_threshold: number;
  early_reversal_confirm_checks: number;
  early_reversal_exit_fraction: number;
  reversal_exit_enabled: boolean;
  reversal_partial_exit_enabled: boolean;
  reversal_partial_exit_window_sec: number;
  reversal_partial_exit_min_t_remaining_sec: number;
  reversal_partial_held_bid_threshold: number;
  reversal_partial_held_bid_drawdown: number;
  reversal_partial_confirm_checks: number;
  reversal_partial_exit_fraction: number;
  reversal_exit_window_sec: number;
  reversal_normal_min_t_remaining_sec: number;
  reversal_exit_min_t_remaining_sec: number;
  reversal_opposite_bid_threshold: number;
  reversal_confirm_checks: number;
  reversal_held_bid_threshold: number;
  reversal_held_bid_drawdown: number;
  reversal_late_exit_enabled: boolean;
  reversal_late_window_sec: number;
  reversal_late_held_bid_threshold: number;
  reversal_late_confirm_checks: number;
  reversal_exit_order_fraction: number;
  sell_fok_slippage_ticks: number;
  sell_exit_max_depth_ticks: number;
  sell_exit_max_depth_levels: number;
  sell_exit_fak_fallback_enabled: boolean;
  sell_exit_reconcile_trades: boolean;
}

export interface State {
  now: number;
  bot_running: boolean;
  bot_mode: string;       // 'paper' | 'live' | 'stopped' | 'unknown'
  bot_assets?: {
    BTC?: boolean;
    ETH?: boolean;
  };
  risk_state: string;
  wallet: Wallet;
  market: Market | null;
  eth_market: Market | null;
  book_up: Book | null;
  book_down: Book | null;
  eth_book_up: Book | null;
  eth_book_down: Book | null;
  btc_signal: BtcSignal | null;
  eth_signal: BtcSignal | null;
  positions: Position[];
  pnl: PnL;
  config: Config;
  decisions: Decision[];
  orders: Order[];
  errors: Record<string, string>;
}

export interface LlmSettings {
  enabled: boolean;
  advisor_enabled: boolean;
  provider: string;
  base_url: string;
  model: string;
  /** Masked value returned by the server; never a raw API key. */
  api_key: string;
  api_key_configured: boolean;
  timeout_sec: number;
  max_tokens: number;
  temperature: number;
  system_prompt: string;
  requires_restart?: boolean;
}
