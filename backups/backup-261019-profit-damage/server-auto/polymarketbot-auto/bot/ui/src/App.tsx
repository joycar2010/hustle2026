import { useEffect, useRef, useState } from 'react';
import type { CSSProperties, ReactNode } from 'react';
import { fetchState } from './api';
import type { Book, Decision, Order, Position, State } from './types';
import { fmtDur, fmtNum, fmtPct, fmtPx, fmtTime, fmtUsd } from './format';

const POLL_MS = 500;

export default function App() {
  const [state, setState] = useState<State | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [now, setNow] = useState<number>(Date.now() / 1000);
  const [flash, setFlash] = useState<boolean>(false);
  const [lastFlashAt, setLastFlashAt] = useState<number>(0);
  const lastSeenOrderId = useRef<number>(-1);

  useEffect(() => {
    let cancelled = false;
    const tick = async () => {
      try {
        const s = await fetchState();
        if (cancelled) return;
        setState(s);
        setErr(null);
        const newest = s.orders.length ? s.orders[0].id : -1;
        if (lastSeenOrderId.current < 0) {
          lastSeenOrderId.current = newest;
        } else if (newest > lastSeenOrderId.current) {
          const o = s.orders[0];
          if (o && o.dry_run === 0 && (o.status === 'matched' || o.status === 'filled')) {
            setFlash(false);
            setTimeout(() => {
              setFlash(true);
              setLastFlashAt(Date.now());
            }, 0);
            setTimeout(() => setFlash(false), 5000);
          }
          lastSeenOrderId.current = newest;
        }
      } catch (e) {
        if (!cancelled) setErr(String(e));
      }
    };
    tick();
    const id = setInterval(tick, POLL_MS);
    return () => { cancelled = true; clearInterval(id); };
  }, []);

  useEffect(() => {
    const id = setInterval(() => setNow(Date.now() / 1000), 200);
    return () => clearInterval(id);
  }, []);

  const viewportWidth = useViewportWidth();
  const compactLayout = viewportWidth < 1180;

  const m = state?.market;
  const tRem = m ? Math.max(0, m.end_ts - now) : null;
  const ethM = state?.eth_market;
  const ethTRem = ethM ? Math.max(0, ethM.end_ts - now) : null;
  const totalEquity =
    (state?.wallet.balance_pusd ?? 0) + (state?.wallet.value_usd ?? 0);
  const pnl = state?.pnl;
  const winRate =
    pnl && pnl.wins + pnl.losses > 0
      ? (pnl.wins / (pnl.wins + pnl.losses)) * 100
      : null;
  const hourlyCap = state?.config.max_orders_per_hour ?? 0;
  const ordersPerHourLabel =
    hourlyCap > 0
      ? `${state?.config.target_min_orders_per_hour ?? '?'}-${hourlyCap} / h`
      : 'off';
  const earlyEntryLabel =
    state?.config.early_entry_enabled
      ? `${state.config.seconds_before_close}-${state.config.early_entry_seconds_before_close}s >= ${fmtPx(state.config.early_entry_min_price)}`
      : 'off';
  const tailEntryLabel =
    state?.config.tail_entry_enabled
      ? `${state.config.tail_entry_window_sec}-${state.config.tail_entry_min_t_remaining_sec}s > ${fmtPx(state.config.tail_entry_min_price)} ${state.config.tail_entry_confirm_checks}x ${fmtPct(state.config.tail_entry_risk_fraction * 100)}`
      : 'off';
  const midEntryLabel =
    state?.config.mid_entry_enabled
      ? `${state.config.mid_entry_window_sec}-${state.config.mid_entry_min_t_remaining_sec}s ${fmtPx(state.config.mid_entry_min_price)}-${fmtPx(state.config.mid_entry_max_price)} ${state.config.mid_entry_confirm_checks}x ${fmtPct(state.config.mid_entry_risk_fraction * 100)} UP>${state.config.mid_btc_up_min_delta_usd} DOWN<${state.config.mid_btc_down_max_delta_usd}`
      : 'off';
  const strongDeltaEntryLabel =
    state?.config.strong_delta_entry_enabled
      ? `${state.config.strong_delta_entry_window_sec}-${state.config.strong_delta_entry_min_t_remaining_sec}s >${fmtPx(state.config.strong_delta_entry_min_price)} UP>=${fmtUsd(state.config.strong_delta_entry_up_min_delta_usd)} DOWN<=${fmtUsd(state.config.strong_delta_entry_down_max_delta_usd)} ${state.config.strong_delta_entry_confirm_checks}x`
      : 'off';
  const earlyStrongDeltaEntryLabel =
    state?.config.early_strong_delta_entry_enabled
      ? `${state.config.early_strong_delta_entry_window_sec}-${state.config.early_strong_delta_entry_min_t_remaining_sec}s >${fmtPx(state.config.early_strong_delta_entry_min_price)} <${fmtPx(state.config.early_strong_delta_entry_max_price)} ${state.config.early_strong_delta_entry_hedge_enabled ? 'price-only always-hedge' : `UP>=${fmtUsd(state.config.early_strong_delta_entry_up_min_delta_usd)} DOWN<=${fmtUsd(state.config.early_strong_delta_entry_down_max_delta_usd)}`} ${state.config.early_strong_delta_entry_confirm_checks}x${state.config.early_strong_delta_entry_hedge_enabled ? ' hedge' : ''}`
      : 'off';
  const lateEdgeConfirmLabel = state
    ? state.config.late_edge_entry_window_sec <= 60
      ? `${state.config.late_edge_entry_window_sec}-30s ${state.config.late_edge_entry_mid_confirm_checks}x; 30-${state.config.late_edge_entry_min_t_remaining_sec}s ${state.config.late_edge_entry_late_confirm_checks}x`
      : `${state.config.late_edge_entry_window_sec}-60s ${state.config.late_edge_entry_confirm_checks}x; 60-30s ${state.config.late_edge_entry_mid_confirm_checks}x; 30-${state.config.late_edge_entry_min_t_remaining_sec}s ${state.config.late_edge_entry_late_confirm_checks}x`
    : '';
  const lateEdgeEntryLabel =
    state?.config.late_edge_entry_enabled
      ? state.config.late_edge_entry_delta_filter_enabled
        ? `${state.config.late_edge_entry_window_sec}-${state.config.late_edge_entry_min_t_remaining_sec}s ${fmtPx(state.config.late_edge_entry_min_price)}-${fmtPx(state.config.late_edge_entry_max_price)} UP>=${fmtUsd(state.config.late_edge_entry_up_min_delta_usd)} DOWN<=${fmtUsd(state.config.late_edge_entry_down_max_delta_usd)} ${lateEdgeConfirmLabel} ${fmtPct(state.config.late_edge_entry_risk_fraction * 100)}`
        : `${state.config.late_edge_entry_window_sec}-${state.config.late_edge_entry_min_t_remaining_sec}s ${fmtPx(state.config.late_edge_entry_min_price)}-${fmtPx(state.config.late_edge_entry_max_price)} price-only ${lateEdgeConfirmLabel} ${fmtPct(state.config.late_edge_entry_risk_fraction * 100)}`
      : 'off';
  const stableDeltaEntryLabel =
    state?.config.stable_delta_entry_enabled
      ? `${state.config.stable_delta_entry_window_sec}-${state.config.stable_delta_entry_min_t_remaining_sec}s ${fmtPx(state.config.stable_delta_entry_min_price)}-${fmtPx(state.config.stable_delta_entry_max_price)} abs=${fmtMoneyCompact(state.config.stable_delta_entry_min_abs_delta_usd)}-${fmtMoneyCompact(state.config.stable_delta_entry_max_abs_delta_usd)} move<${fmtMoneyCompact(state.config.stable_delta_entry_max_delta_move_usd)} ${state.config.stable_delta_entry_confirm_checks}x ${fmtPct(state.config.stable_delta_entry_risk_fraction * 100)}`
      : 'off';
  const entryMomentumLabel =
    state?.config.entry_momentum_filter_enabled
      ? state.config.entry_momentum_max_ask_move > 0
        ? `${fmtPx(state.config.entry_momentum_min_price)}-${fmtPx(state.config.entry_momentum_max_price)} final>=prev-1t move<${fmtPx(state.config.entry_momentum_max_ask_move)}`
        : 'all non-tail final>=prev-1t'
      : 'off';
  const trendOverheatLabel =
    state?.config.trend_overheat_filter_enabled
      ? `${state.config.trend_overheat_min_streak}x same-dir price>=${fmtPx(state.config.trend_overheat_price_floor)} skip`
      : 'off';
  const highEdgeLabel =
    state?.config.high_price_edge_threshold !== undefined && state.config.high_price_edge_threshold > 0
      ? `> ${fmtPx(state.config.min_net_edge)}; >=${fmtPx(state.config.high_price_edge_threshold)} BTC abs>=${fmtMoneyCompact(state.config.high_price_btc_delta_usd)} ETH abs>=${fmtMoneyCompact(state.config.eth_high_price_delta_usd)}`
      : `> ${fmtPx(state?.config.min_net_edge)}`;
  const btcSignal = state?.btc_signal ?? null;
  const ethSignal = state?.eth_signal ?? null;
  const btcFilterLabel = state?.config.btc_delta_filter_enabled
    ? `${state.config.btc_price_symbol} UP>=${fmtMoneyCompact(state.config.btc_up_min_delta_usd)} DOWN<=${fmtMoneyCompact(state.config.btc_down_max_delta_usd)} ${state.config.confirm_checks}x`
    : 'off';
  const scaleInLabel =
    state?.config.scale_in_after_early_enabled
      ? [
          `early${state.config.early_strong_delta_entry_hedge_enabled ? ' hedge' : ''}`,
          state.config.strong_delta_entry_enabled ? 'strong' : '',
          state.config.normal_scale_in_enabled ? `${state.config.seconds_before_close}-${state.config.min_t_remaining_sec}s` : '',
          state.config.late_edge_entry_enabled ? `${state.config.late_edge_entry_window_sec}-${state.config.late_edge_entry_min_t_remaining_sec}s` : '',
          state.config.tail_entry_enabled ? 'tail' : '',
        ]
          .filter(Boolean)
          .join(' + ') + `; max ${state.config.max_buys_per_market}; per-slot side`
      : 'off';
  const strongNormalReverseLabel =
    state?.config.strong_normal_reverse_enabled
      ? `strong->normal held<=${fmtPx(state.config.strong_normal_reverse_held_bid_threshold)} reverse ${state.config.strong_normal_reverse_confirm_checks}x ${fmtPct(state.config.strong_normal_reverse_risk_fraction * 100)}`
      : 'off';
  const btcDeltaLabel = btcSignal
    ? `${btcSignal.delta_usd >= 0 ? '+' : ''}${fmtUsd(btcSignal.delta_usd)} ${btcSignal.signal_side}${btcSignal.stale ? ' STALE' : ''}`
    : '--';
  const btcPriceLabel = btcSignal
    ? `${fmtUsd(btcSignal.current_price)} / ${fmtUsd(btcSignal.price_to_beat)}`
    : '--';
  const btcPriceKey = btcSignal?.source?.includes('rtds') ? 'BTC TWAP PX / BEAT' : 'BTC PX / BEAT';
  const ethDeltaLabel = ethSignal
    ? `${ethSignal.delta_usd >= 0 ? '+' : ''}${fmtUsd(ethSignal.delta_usd)} ${ethSignal.signal_side}${ethSignal.stale ? ' STALE' : ''}`
    : '--';
  const ethPriceLabel = ethSignal
    ? `${fmtUsd(ethSignal.current_price)} / ${fmtUsd(ethSignal.price_to_beat)}`
    : '--';
  const ethPriceKey = ethSignal?.source?.includes('rtds') ? 'ETH TWAP PX / BEAT' : 'ETH PX / BEAT';
  const ethFilterLabel = state?.config.eth_delta_filter_enabled
    ? `${state.config.eth_price_symbol} UP>=${fmtMoneyCompact(state.config.eth_up_min_delta_usd)} DOWN<=${fmtMoneyCompact(state.config.eth_down_max_delta_usd)} ${state.config.confirm_checks}x`
    : 'off';
  const ethTradingLabel = state?.config.eth_trading_enabled ? 'LIVE ENABLED' : 'monitor only';
  const realizedCapUsd = state?.config.max_daily_realized_profit_usd ?? 0;
  const ethEarlyStrongLabel =
    state?.config.eth_market_enabled
      ? `${state.config.early_strong_delta_entry_window_sec}-${state.config.early_strong_delta_entry_min_t_remaining_sec}s >${fmtPx(state.config.early_strong_delta_entry_min_price)} <${fmtPx(state.config.early_strong_delta_entry_max_price)} ${state.config.early_strong_delta_entry_hedge_enabled ? 'price-only always-hedge' : `UP>=${fmtMoneyCompact(state.config.eth_early_strong_delta_up_min_delta_usd)} DOWN<=${fmtMoneyCompact(state.config.eth_early_strong_delta_down_max_delta_usd)}`} ${state.config.early_strong_delta_entry_confirm_checks}x${state.config.early_strong_delta_entry_hedge_enabled ? ' hedge' : ''}`
      : 'off';
  const ethStrongDeltaLabel =
    state?.config.eth_market_enabled
      ? `${state.config.strong_delta_entry_window_sec}-${state.config.strong_delta_entry_min_t_remaining_sec}s >${fmtPx(state.config.strong_delta_entry_min_price)} UP>=${fmtMoneyCompact(state.config.eth_strong_delta_up_min_delta_usd)} DOWN<=${fmtMoneyCompact(state.config.eth_strong_delta_down_max_delta_usd)} ${state.config.strong_delta_entry_confirm_checks}x`
      : 'off';
  const ethLateEdgeLabel =
    state?.config.eth_market_enabled
      ? state.config.eth_late_edge_delta_filter_enabled
        ? `${state.config.late_edge_entry_window_sec}-${state.config.late_edge_entry_min_t_remaining_sec}s ${fmtPx(state.config.late_edge_entry_min_price)}-${fmtPx(state.config.late_edge_entry_max_price)} UP>=${fmtMoneyCompact(state.config.eth_late_edge_up_min_delta_usd)} DOWN<=${fmtMoneyCompact(state.config.eth_late_edge_down_max_delta_usd)} ${lateEdgeConfirmLabel} ${fmtPct(state.config.eth_late_edge_risk_fraction * 100)}`
        : `${state.config.late_edge_entry_window_sec}-${state.config.late_edge_entry_min_t_remaining_sec}s ${fmtPx(state.config.late_edge_entry_min_price)}-${fmtPx(state.config.late_edge_entry_max_price)} price-only ${lateEdgeConfirmLabel} ${fmtPct(state.config.eth_late_edge_risk_fraction * 100)}`
      : 'off';
  const ethSizeLabel = `normal ${fmtPct((state?.config.eth_order_risk_fraction ?? 0) * 100)}; late ${fmtPct((state?.config.eth_late_edge_risk_fraction ?? 0) * 100)}`;
  const priceGuardLabel = state?.config.price_source_guard_enabled
    ? state.config.allow_binance_proxy_chainlink_entries
      ? 'WARN proxy allowed'
      : state.config.price_signal_source?.toLowerCase().includes('rtds')
        ? 'ON: RTDS TWAP required'
        : 'ON: block Binance proxy on Chainlink'
    : 'off';
  const sizeLabel =
    (state?.config.order_fixed_notional_usd ?? 0) > 0
      ? `${fmtUsd(state?.config.order_fixed_notional_usd)} fixed`
      : `${fmtPct((state?.config.order_risk_fraction ?? 0) * 100)} equity`;
  const oneSideLabel = state?.config.one_side_per_market
    ? `on; max ${state.config.max_buys_per_market}`
    : 'off';
  const partialExitTrigger =
    (state?.config.reversal_partial_held_bid_threshold ?? 0) > 0
      ? `held<${fmtPx(state?.config.reversal_partial_held_bid_threshold)}`
      : `dd>${fmtPx(state?.config.reversal_partial_held_bid_drawdown)}`;
  const reversalTrigger =
    (state?.config.reversal_held_bid_threshold ?? 0) > 0
      ? `held<${fmtPx(state?.config.reversal_held_bid_threshold)}`
      : `dd>=${fmtPct((state?.config.reversal_held_bid_drawdown ?? 0) * 100)}`;
  const earlyReversalLabel =
    state?.config.early_reversal_exit_enabled
      ? `${state.config.early_reversal_exit_window_sec}-${state.config.early_reversal_exit_min_t_remaining_sec}s held<${fmtPx(state.config.early_reversal_held_bid_threshold)} ${state.config.early_reversal_confirm_checks}x / ${fmtPct(state.config.early_reversal_exit_fraction * 100)}`
      : 'off';
  const reversalLabel =
    state?.config.reversal_exit_enabled
      ? `${state.config.reversal_partial_exit_enabled ? `${state.config.reversal_partial_exit_window_sec}-${state.config.reversal_partial_exit_min_t_remaining_sec}s ${partialExitTrigger} ${state.config.reversal_partial_confirm_checks}x / ${fmtPct(state.config.reversal_partial_exit_fraction * 100)}; ` : ''}${state.config.reversal_exit_window_sec}-${state.config.reversal_normal_min_t_remaining_sec}s ${reversalTrigger} ${state.config.reversal_confirm_checks}x / ${fmtPct(state.config.reversal_exit_order_fraction * 100)}; ${state.config.reversal_late_exit_enabled ? `${state.config.reversal_late_window_sec}-${state.config.reversal_exit_min_t_remaining_sec}s held<${fmtPx(state.config.reversal_late_held_bid_threshold)} ${state.config.reversal_late_confirm_checks}x` : 'late off'}`
      : 'off';

  return (
    <>
      {flash && <div className="flash-screen" />}
      <div style={shellStyle}>
        <TopBar
          time={now}
          botRunning={state?.bot_running ?? false}
          botMode={state?.bot_mode ?? 'stopped'}
          riskState={state?.risk_state ?? 'OK'}
          err={err}
          lastFlashAt={lastFlashAt}
        />

        <div style={compactLayout ? compactGridStyle : gridStyle}>
          <div style={compactLayout ? compactLeftColStack : colStack}>
            <Panel title="WALLET / EQUITY" contentStyle={summaryPanelContentStyle}>
              <Row k="pUSD CASH" v={fmtUsd(state?.wallet.balance_pusd)} hi relaxed />
              <Row k="OPEN VALUE" v={fmtUsd(state?.wallet.value_usd)} relaxed />
              <Sep />
              <Row k="TOTAL EQUITY" v={fmtUsd(totalEquity)} hi big relaxed />
            </Panel>

            <Panel title="P&L TODAY" contentStyle={summaryPanelContentStyle}>
              <Row k="REALIZED" v={fmtUsd(pnl?.realized_usd)} colored={pnl?.realized_usd} relaxed />
              <Row k="WINS / LOSSES" v={`${pnl?.wins ?? 0} / ${pnl?.losses ?? 0}`} relaxed />
              <Row k="WIN RATE" v={fmtPct(winRate ?? null)} relaxed />
              <Row k="PENDING" v={String(pnl?.pending ?? 0)} dim relaxed />
              <Row k="SINCE" v={pnl?.period_start_ts ? fmtTime(pnl.period_start_ts) : '--'} dim mono relaxed />
            </Panel>

            <Panel title="STRATEGY" flex>
              <div style={strategyStackStyle}>
                <div style={strategySectionStyle}>
                  <div style={subTitleStyle}>BTC</div>
                  <Row k="DOWN ENTRY" v={`${fmtPx(state?.config.min_entry_price)}-${fmtPx(state?.config.max_entry_price)}`} mono />
                  <Row k="UP ENTRY" v={`${fmtPx(state?.config.up_min_entry_price)}-${fmtPx(state?.config.up_max_entry_price)}`} mono />
                  <Row k="BTC FILTER" v={btcFilterLabel} mono />
                  <Row k="EARLY STRONG" v={earlyStrongDeltaEntryLabel} mono />
                  <Row k="STRONG DELTA" v={strongDeltaEntryLabel} mono />
                  <Row k="LATE EDGE" v={lateEdgeEntryLabel} mono />
                  <Row k="STABLE DELTA" v={stableDeltaEntryLabel} mono />
                  <Row k="ENTRY MOMENTUM" v={entryMomentumLabel} mono />
                  <Row k="TREND OVERHEAT" v={trendOverheatLabel} mono />
                  <Row k="SIZE" v={sizeLabel} mono />
                </div>
                <div style={strategySectionStyle}>
                  <div style={subTitleStyle}>ETH</div>
                  <Row k="DOWN ENTRY" v={`${fmtPx(state?.config.min_entry_price)}-${fmtPx(state?.config.max_entry_price)}`} mono />
                  <Row k="UP ENTRY" v={`${fmtPx(state?.config.up_min_entry_price)}-${fmtPx(state?.config.up_max_entry_price)}`} mono />
                  <Row k="ETH FILTER" v={ethFilterLabel} mono />
                  <Row k="ETH TRADE" v={ethTradingLabel} mono colored={state?.config.eth_trading_enabled ? 1 : null} />
                  <Row k="EARLY STRONG" v={ethEarlyStrongLabel} mono />
                  <Row k="STRONG DELTA" v={ethStrongDeltaLabel} mono />
                  <Row k="LATE EDGE" v={ethLateEdgeLabel} mono />
                  <Row k="ENTRY MOMENTUM" v={entryMomentumLabel} mono />
                  <Row k="SIZE" v={ethSizeLabel} mono />
                </div>
              </div>
              <Sep />
              <Row k="NET EDGE" v={highEdgeLabel} mono />
              <Row k="PRICE GUARD" v={priceGuardLabel} mono colored={state?.config.price_source_guard_enabled && !state?.config.allow_binance_proxy_chainlink_entries ? 1 : -1} />
              <Row k="WINDOW" v={`${state?.config.min_t_remaining_sec ?? '?'}-${state?.config.seconds_before_close ?? '?'}s`} mono />
              <Row k="EARLY ENTRY" v={earlyEntryLabel} mono />
              <Row k="MID ENTRY" v={midEntryLabel} mono />
              <Row k="TAIL ENTRY" v={tailEntryLabel} mono />
              <Row k="SCALE IN" v={scaleInLabel} mono />
              <Row k="ONE SIDE" v={oneSideLabel} mono />
              <Row k="STRONG REV" v={strongNormalReverseLabel} mono />
              <Row k="MIN ORDER" v={fmtUsd(state?.config.min_order_notional_usd)} mono />
              <Row k="BAL RESERVE" v={fmtUsd(state?.config.order_balance_reserve_usd)} mono />
              <Row k="ORDERS / HR" v={ordersPerHourLabel} mono />
              <Row k="EARLY REV EXIT" v={earlyReversalLabel} mono />
              <Row k="REV EXIT" v={reversalLabel} mono />
              <Row k="CONFIRM" v={`${state?.config.confirm_checks ?? '?'}x`} mono />
              <Row
                k="RETRY"
                v={`${state?.config.max_buy_retries_per_market === 0 ? 'unlimited' : `${state?.config.max_buy_retries_per_market ?? '?'}x`} / ${state?.config.order_retry_cooldown_sec ?? '?'}s / >=${state?.config.retry_min_t_remaining_sec ?? '?'}s / ${state?.config.max_retry_price_drift_ticks != null && state.config.max_retry_price_drift_ticks < 0 ? 'drift unlimited' : `+${state?.config.max_retry_price_drift_ticks ?? '?'}t`}`}
                mono
              />
              <Row k="FOK BUFFER" v={`${state?.config.fok_price_buffer_ticks ?? 0} tick`} mono />
              <Row k="SELL SLIP" v={`${state?.config.sell_fok_slippage_ticks ?? 0} tick`} mono />
              <Sep />
              <Row k="UNSETTLED CAP" v={String(state?.config.max_open_positions ?? '')} mono />
              <Row k="LOSS CAP / DAY" v={fmtPct((state?.config.max_daily_loss_fraction ?? 0) * 100)} mono />
              <Row k="REALIZED CAP / DAY" v={realizedCapUsd > 0 ? fmtUsd(realizedCapUsd) : 'off'} mono />
            </Panel>
          </div>

          <div style={compactLayout ? compactMiddleColStack : colStack}>
            <Panel title={m ? `${m.synthetic ? 'BTC TIMER' : 'LIVE MARKET'} 路 ${m.market_slug}${m.synthetic ? ' 路 DISPLAY ONLY' : ''}` : 'NO LIVE MARKET'}>
              {m ? (
                <>
                  <Row
                    k="BTC DELTA"
                    v={btcDeltaLabel}
                    hi
                    mono
                    colored={btcSignal ? btcSignal.delta_usd : null}
                  />
                  <Row k={btcPriceKey} v={btcPriceLabel} mono />
                  <Sep />
                  <Row
                    k="COUNTDOWN"
                    v={fmtDur(tRem)}
                    hi
                    big
                    colored={tRem != null && tRem < 60 ? 1 : -1}
                  />
                  <BookView
                    label="UP  "
                    book={state?.book_up}
                    cap={state?.config.up_max_entry_price ?? 0.87}
                    floor={state?.config.up_min_entry_price ?? 0.84}
                  />
                  <BookView
                    label="DOWN"
                    book={state?.book_down}
                    cap={state?.config.max_entry_price ?? 0.95}
                    floor={state?.config.min_entry_price ?? 0.80}
                  />
                </>
              ) : (
                <div style={{ color: 'var(--txt-dim)', padding: '6px 0' }}>
                  awaiting next 5-min BTC window<span className="caret">_</span>
                </div>
              )}
            </Panel>

            <Panel title={ethM ? `ETH MARKET 路 ${ethM.market_slug}${ethM.synthetic ? ' 路 DISPLAY ONLY' : ''}` : 'ETH MARKET 路 MONITOR'}>
              {state?.config.eth_market_enabled && ethM ? (
                <>
                  <Row
                    k="ETH DELTA"
                    v={ethDeltaLabel}
                    hi
                    mono
                    colored={ethSignal ? ethSignal.delta_usd : null}
                  />
                  <Row k={ethPriceKey} v={ethPriceLabel} mono />
                  <Sep />
                  <Row
                    k="COUNTDOWN"
                    v={fmtDur(ethTRem)}
                    hi
                    colored={ethTRem != null && ethTRem < 60 ? 1 : -1}
                  />
                  <BookView
                    label="UP  "
                    book={state?.eth_book_up}
                    cap={state?.config.up_max_entry_price ?? 0.93}
                    floor={state?.config.up_min_entry_price ?? 0.80}
                  />
                  <BookView
                    label="DOWN"
                    book={state?.eth_book_down}
                    cap={state?.config.max_entry_price ?? 0.93}
                    floor={state?.config.min_entry_price ?? 0.80}
                  />
                </>
              ) : (
                <div style={{ color: 'var(--txt-dim)', padding: '6px 0' }}>
                  ETH monitor disabled or awaiting next 5-min ETH window<span className="caret">_</span>
                </div>
              )}
            </Panel>

            <Panel title="DECISION LOG 路 live" flex>
              <DecisionsTable decisions={state?.decisions ?? []} />
            </Panel>
          </div>

          <div style={compactLayout ? compactRightColStack : colStack}>
            <Panel title="OPEN POSITIONS">
              <PositionsTable positions={state?.positions ?? []} />
            </Panel>

            <Panel title="ORDERS 路 recent" flex>
              <OrdersTable orders={state?.orders ?? []} />
            </Panel>
          </div>
        </div>

        <BottomBar state={state} />
      </div>
    </>
  );
}

function TopBar({
  time, botRunning, botMode, riskState, err, lastFlashAt,
}: { time: number; botRunning: boolean; botMode: string; riskState: string; err: string | null; lastFlashAt: number }) {
  const blink = Date.now() - lastFlashAt < 5000;
  const riskOk = riskState === 'OK';
  const botLabel = !botRunning
    ? 'STOPPED'
    : !riskOk
      ? `LOCKED (${riskState})`
      : 'RUNNING';
  const botColor = !botRunning
    ? 'var(--red)'
    : !riskOk
      ? 'var(--amber)'
      : 'var(--green)';

  // mode chip: green for paper (safe), red for live (real money)
  const modeChip = botMode === 'live'
    ? { label: 'LIVE', bg: '#330000', fg: 'var(--red)', border: 'var(--red)' }
    : botMode === 'paper'
      ? { label: 'PAPER', bg: '#001a0d', fg: 'var(--green)', border: 'var(--green)' }
      : { label: 'OFFLINE', bg: 'transparent', fg: 'var(--txt-dim)', border: 'var(--border-hi)' };

  return (
    <div style={topBarStyle}>
      <span style={{ color: 'var(--amber)', fontWeight: 700 }}>POLY_HFT</span>
      <span style={{ color: 'var(--txt-dim)' }}> 路 </span>
      <span style={{ color: 'var(--txt-hi)' }}>BTC / ETH 5MIN</span>
      <span style={{
        marginLeft: 12,
        padding: '1px 8px',
        border: `1px solid ${modeChip.border}`,
        background: modeChip.bg,
        color: modeChip.fg,
        fontWeight: 700,
        letterSpacing: '1.5px',
        fontSize: 11,
      }}>{modeChip.label}</span>
      <span style={spacer} />
      <span style={{ color: botColor, fontWeight: 600 }}>
        鈼?BOT {botLabel}
      </span>
      <span style={{ color: 'var(--txt-dim)', margin: '0 12px' }}>|</span>
      <span style={{ color: err ? 'var(--red)' : 'var(--green)' }}>
        鈼?{err ? 'API ERR' : 'API OK'}
      </span>
      {blink && (
        <>
          <span style={{ color: 'var(--txt-dim)', margin: '0 12px' }}>|</span>
          <span style={{ color: 'var(--amber-bright)', fontWeight: 700 }}>鈼?TRADE FIRED</span>
        </>
      )}
      <span style={spacer} />
      <span style={{ color: 'var(--txt)' }}>{fmtTime(time)}</span>
    </div>
  );
}

function BottomBar({ state }: { state: State | null }) {
  const errs = state?.errors || {};
  const errKeys = Object.keys(errs);
  return (
    <div style={bottomBarStyle}>
      <span style={{ color: 'var(--txt-dim)' }}>POLL 500ms</span>
      <span style={{ color: 'var(--txt-dim)', margin: '0 12px' }}>路</span>
      <span style={{ color: 'var(--txt-dim)' }}>
        DECISIONS {state?.decisions.length ?? 0} 路 ORDERS {state?.orders.length ?? 0}
      </span>
      <span style={spacer} />
      {errKeys.length > 0 && (
        <span style={{ color: 'var(--red)' }}>ERR: {errKeys.join(', ')}</span>
      )}
    </div>
  );
}

function useViewportWidth(): number {
  const [width, setWidth] = useState(() => (
    typeof window === 'undefined' ? 1200 : window.innerWidth
  ));

  useEffect(() => {
    const onResize = () => setWidth(window.innerWidth);
    onResize();
    window.addEventListener('resize', onResize);
    return () => window.removeEventListener('resize', onResize);
  }, []);

  return width;
}

function Panel({
  title, children, flex, contentStyle,
}: { title: string; children: ReactNode; flex?: boolean; contentStyle?: CSSProperties }) {
  return (
    <div style={{
      border: '1px solid var(--border)',
      background: 'var(--bg-panel)',
      display: 'flex',
      flexDirection: 'column',
      flex: flex ? 1 : '0 0 auto',
      minHeight: 0,
    }}>
      <div style={panelTitleStyle}>{title}</div>
      <div style={{ padding: '8px 12px', flex: flex ? 1 : 'unset', overflow: 'auto', ...contentStyle }}>
        {children}
      </div>
    </div>
  );
}

function Row({
  k, v, hi, big, dim, mono, colored, relaxed,
}: {
  k: string; v: ReactNode; hi?: boolean; big?: boolean;
  dim?: boolean; mono?: boolean; colored?: number | null; relaxed?: boolean;
}) {
  let color: string = hi ? 'var(--txt-hi)' : dim ? 'var(--txt-dim)' : 'var(--txt)';
  if (typeof colored === 'number') {
    color = colored > 0 ? 'var(--green)' : colored < 0 ? 'var(--red)' : color;
  }
  return (
    <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8, padding: relaxed ? '3px 0' : '2px 0' }}>
      <span style={{ color: 'var(--txt-dim)', letterSpacing: '0.5px', flex: '0 0 auto' }}>{k}</span>
      <span style={{
        color,
        fontFamily: mono ? 'inherit' : undefined,
        fontSize: big ? 16 : undefined,
        fontWeight: big ? 700 : 500,
        textAlign: 'right',
        overflowWrap: 'anywhere',
      }}>{v}</span>
    </div>
  );
}

function Sep() {
  return <div style={{ height: 1, background: 'var(--border)', margin: '4px 0' }} />;
}

function BookView({
  label, book, cap, floor,
}: { label: string; book: Book | null | undefined; cap: number; floor: number }) {
  const ask = book?.best_ask ?? null;
  let askColor = 'var(--txt)';
  if (ask != null) {
    if (ask > cap) askColor = 'var(--txt-dim)';
    else if (ask > floor) askColor = 'var(--amber-bright)';
    else askColor = 'var(--txt-dim)';
  }
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '3px 0', borderTop: '1px dashed var(--border)' }}>
      <span style={{ color: 'var(--txt-dim)', width: 36 }}>{label}</span>
      <span style={{ color: 'var(--txt-dim)' }}>bid</span>
      <span style={{ color: 'var(--green)' }}>{fmtPx(book?.best_bid)}</span>
      <span style={{ color: 'var(--txt-dim)' }}>脳{fmtNum(book?.bid_size, 0)}</span>
      <span style={spacer} />
      <span style={{ color: 'var(--txt-dim)' }}>ask</span>
      <span style={{ color: askColor, fontWeight: 700 }}>{fmtPx(ask)}</span>
      <span style={{ color: 'var(--txt-dim)' }}>脳{fmtNum(book?.ask_size, 0)}</span>
    </div>
  );
}

function actionColor(a: string): string {
  if (a === 'BUY') return 'var(--green)';
  if (a.startsWith('SKIP')) return 'var(--txt-dim)';
  return 'var(--txt)';
}

function resultColor(r: string): string {
  if (r === 'HIT') return 'var(--green)';
  if (r === 'MISS' || r === 'FAILED' || r === 'EXIT_FAILED') return 'var(--red)';
  if (r === 'PENDING' || r === 'UNCERTAIN' || r === 'EXITED' || r === 'PARTIAL_EXIT' || r === 'EXIT_UNCERTAIN') return 'var(--amber)';
  return 'var(--txt-dim)';
}

function orderStatusColor(status: string): string {
  if (status === 'matched' || status === 'filled' || status === 'exit_matched' || status === 'exit_filled') return 'var(--green)';
  if (status === 'error' || status === 'pre_submit_error' || status === 'exit_error' || status === 'exit_pre_submit_error') return 'var(--red)';
  return 'var(--amber)';
}

function DecisionsTable({ decisions }: { decisions: Decision[] }) {
  if (!decisions.length) return <Empty>no decisions yet<span className="caret">_</span></Empty>;
  return (
    <table style={tableStyle}>
      <thead>
        <tr>
          <Th>TIME</Th>
          <Th>ASSET</Th>
          <Th>MARKET</Th>
          <Th>SIDE</Th>
          <Th right>T_REM</Th>
          <Th right>ASK</Th>
          <Th>ACTION</Th>
          <Th>REASON</Th>
        </tr>
      </thead>
      <tbody>
        {decisions.slice(0, 40).map((d) => (
          <tr key={d.id} style={{ background: d.action === 'BUY' ? 'rgba(0,255,127,0.04)' : undefined }}>
            <Td dim>{fmtTime(d.ts)}</Td>
            <Td>{d.asset || '--'}</Td>
            <Td dim>{shortMarket(d.market_slug)}</Td>
            <Td>{d.side ?? '-'}</Td>
            <Td right>{fmtNum(d.t_remaining, 1)}s</Td>
            <Td right>{fmtPx(d.ask_price)}</Td>
            <Td color={actionColor(d.action)} bold>{d.action}</Td>
            <Td dim>{d.reason}</Td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function OrdersTable({ orders }: { orders: Order[] }) {
  if (!orders.length) return <Empty>no orders yet<span className="caret">_</span></Empty>;
  return (
    <table style={tableStyle}>
      <thead>
        <tr>
          <Th>TIME</Th>
          <Th>ASSET</Th>
          <Th>MARKET</Th>
          <Th>SIDE</Th>
          <Th right>SIZE</Th>
          <Th right>PX</Th>
          <Th>STATUS</Th>
          <Th>RESULT</Th>
          <Th right>FILLED $</Th>
        </tr>
      </thead>
      <tbody>
        {orders.slice(0, 20).map((o) => {
          return (
            <tr key={o.id}>
              <Td dim>{fmtTime(o.ts)}</Td>
              <Td>{o.asset || '--'}</Td>
              <Td dim>{shortMarket(o.market_slug)}</Td>
              <Td>{o.side}</Td>
              <Td right>{fmtNum(o.size, 2)}</Td>
              <Td right>{fmtPx(o.price)}</Td>
              <Td color={orderStatusColor(o.status)} bold>{o.status}</Td>
              <Td color={resultColor(o.result)} bold>{o.result}</Td>
              <Td right>{fmtUsd(o.filled_size)}</Td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}

function PositionsTable({ positions }: { positions: Position[] }) {
  if (!positions.length) return <Empty>no open positions<span className="caret">_</span></Empty>;
  return (
    <table style={tableStyle}>
      <thead>
        <tr>
          <Th>TITLE</Th>
          <Th>SIDE</Th>
          <Th right>SIZE</Th>
          <Th right>PX</Th>
          <Th right>VAL</Th>
        </tr>
      </thead>
      <tbody>
        {positions.map((p, i) => (
          <tr key={i}>
            <Td dim>{(p.title || '').replace(/^Bitcoin Up or Down - /, '')}</Td>
            <Td>{p.outcome}</Td>
            <Td right>{fmtNum(p.size, 2)}</Td>
            <Td right>{fmtPx(p.curPrice)}</Td>
            <Td right>{fmtUsd((p.size ?? 0) * (p.curPrice ?? 0))}</Td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function shortMarket(slug: string | null | undefined): string {
  return (slug || '').replace('btc-updown-5m-', '').replace('eth-updown-5m-', '');
}

function fmtMoneyCompact(v: number | null | undefined): string {
  if (v == null || Number.isNaN(v)) return '--';
  const abs = Math.abs(v);
  const digits = abs < 10 ? 2 : 0;
  const sign = v < 0 ? '-' : '';
  return `${sign}$${abs.toFixed(digits)}`;
}


function Th({ children, right }: { children: ReactNode; right?: boolean }) {
  return (
    <th style={{
      textAlign: right ? 'right' : 'left',
      padding: '4px 8px',
      color: 'var(--txt-dim)',
      fontWeight: 400,
      borderBottom: '1px solid var(--border)',
      fontSize: 10,
      letterSpacing: '0.8px',
      position: 'sticky',
      top: 0,
      background: 'var(--bg-panel)',
    }}>{children}</th>
  );
}

function Td({
  children, right, dim, color, bold,
}: { children: ReactNode; right?: boolean; dim?: boolean; color?: string; bold?: boolean }) {
  return (
    <td style={{
      textAlign: right ? 'right' : 'left',
      padding: '3px 8px',
      color: color || (dim ? 'var(--txt-dim)' : 'var(--txt)'),
      fontWeight: bold ? 700 : 400,
      borderBottom: '1px solid rgba(255,255,255,0.02)',
      whiteSpace: 'nowrap',
      overflow: 'hidden',
      textOverflow: 'ellipsis',
      maxWidth: 240,
    }}>{children}</td>
  );
}

function Empty({ children }: { children: ReactNode }) {
  return <div style={{ color: 'var(--txt-dim)', padding: '8px 4px' }}>{children}</div>;
}

const shellStyle: CSSProperties = { height: '100vh', display: 'grid', gridTemplateRows: '34px 1fr 24px' };
const topBarStyle: CSSProperties = {
  display: 'flex', alignItems: 'center', padding: '0 14px',
  borderBottom: '1px solid var(--border-hi)', background: 'var(--bg-panel)',
  fontSize: 12, letterSpacing: '0.5px',
};
const bottomBarStyle: CSSProperties = {
  display: 'flex', alignItems: 'center', padding: '0 12px',
  borderTop: '1px solid var(--border-hi)', background: 'var(--bg-panel)',
  fontSize: 10, letterSpacing: '0.5px',
};
const gridStyle: CSSProperties = {
  display: 'grid',
  gridTemplateColumns: '380px minmax(360px, 1fr) 430px',
  gap: 8, padding: 8, height: '100%', overflow: 'hidden',
};
const colStack: CSSProperties = { display: 'flex', flexDirection: 'column', gap: 6, minHeight: 0 };
const compactGridStyle: CSSProperties = {
  display: 'grid',
  gridTemplateColumns: '300px minmax(0, 1fr)',
  gridTemplateRows: 'minmax(0, 1fr) 210px',
  gap: 8,
  padding: 8,
  height: '100%',
  overflow: 'hidden',
};
const compactLeftColStack: CSSProperties = {
  ...colStack,
  gridColumn: '1',
  gridRow: '1',
};
const compactMiddleColStack: CSSProperties = {
  ...colStack,
  gridColumn: '2',
  gridRow: '1',
};
const compactRightColStack: CSSProperties = {
  ...colStack,
  gridColumn: '1 / span 2',
  gridRow: '2',
};
const strategyStackStyle: CSSProperties = {
  display: 'flex',
  flexDirection: 'column',
  gap: 6,
};
const strategySectionStyle: CSSProperties = {
  minWidth: 0,
  border: '1px solid rgba(255,255,255,0.05)',
  padding: '4px 6px',
};
const subTitleStyle: CSSProperties = {
  color: 'var(--amber-bright)',
  fontSize: 10,
  fontWeight: 700,
  letterSpacing: '1px',
  paddingBottom: 3,
};
const panelTitleStyle: CSSProperties = {
  background: 'var(--border)', color: 'var(--amber)',
  padding: '4px 12px', fontSize: 11, letterSpacing: '1.2px', fontWeight: 600,
};
const summaryPanelContentStyle: CSSProperties = { padding: '6px 16px' };
const spacer: CSSProperties = { flex: 1 };
const tableStyle: CSSProperties = { width: '100%', borderCollapse: 'collapse', fontSize: 11 };
