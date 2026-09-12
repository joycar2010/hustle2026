import { useEffect, useRef, useState } from 'react';
import type { CSSProperties, ReactNode } from 'react';
import { controlLive, fetchLlmSettings, fetchState, probeLlm, saveLlmSettings, testLlm } from './api';
import type { Book, Decision, LlmSettings, Order, Position, State } from './types';
import { fmtDur, fmtNum, fmtPct, fmtPx, fmtTime, fmtUsd } from './format';

const POLL_MS = 500;

export default function App() {
  const [state, setState] = useState<State | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [now, setNow] = useState<number>(Date.now() / 1000);
  const [flash, setFlash] = useState<boolean>(false);
  const [lastFlashAt, setLastFlashAt] = useState<number>(0);
  const [showSettings, setShowSettings] = useState<boolean>(false);
  const [operatorToken, setOperatorToken] = useState<string>('');
  const [liveBusy, setLiveBusy] = useState<boolean>(false);
  const [liveMessage, setLiveMessage] = useState<string>('');
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

  const toggleLive = async () => {
    const live = state?.bot_running && state.bot_mode === 'live';
    const action = live ? 'stop' : 'start';
    if (!operatorToken.trim()) {
      setLiveMessage('请先填写实盘操作令牌。');
      return;
    }
    if (action === 'start') {
      const balance = state?.wallet.balance_pusd;
      const balanceText = balance == null ? '余额未知' : `pUSD $${balance.toFixed(2)}`;
      if (!window.confirm(`即将启动真实订单（${balanceText}）。确认继续？`)) return;
    } else if (!window.confirm('确认关闭实盘？只会停止机器人循环，不会自动卖出已有持仓。')) {
      return;
    }
    setLiveBusy(true);
    setLiveMessage(action === 'start' ? '正在执行实盘预检并启动…' : '正在停止实盘…');
    try {
      const result = await controlLive(action, operatorToken.trim());
      setLiveMessage(result.note || (action === 'start' ? '实盘已开启。' : '实盘已关闭。'));
      const refreshed = await fetchState();
      setState(refreshed);
    } catch (e) {
      setLiveMessage(`操作失败：${e}`);
    } finally {
      setLiveBusy(false);
    }
  };

  const m = state?.market;
  const tRem = m ? Math.max(0, m.end_ts - now) : null;
  const ethM = state?.eth_market;
  const ethTRem = ethM ? Math.max(0, ethM.end_ts - now) : null;
  const cash = state?.wallet.balance_pusd;
  const openValue = state?.wallet.value_usd;
  const totalEquity = cash != null && Number.isFinite(cash) && openValue != null && Number.isFinite(openValue)
    ? cash + openValue
    : null;
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
          onSettings={() => setShowSettings(true)}
          operatorToken={operatorToken}
          onOperatorTokenChange={setOperatorToken}
          liveBusy={liveBusy}
          liveMessage={liveMessage}
          onToggleLive={toggleLive}
        />

        <div style={compactLayout ? compactGridStyle : gridStyle}>
          <div style={compactLayout ? compactLeftColStack : colStack}>
            <Panel title="钱包 / 资产">
              <Row k="pUSD 现金" v={fmtUsd(state?.wallet.balance_pusd)} hi relaxed />
              <Row k="持仓市值" v={fmtUsd(state?.wallet.value_usd)} relaxed />
              <Sep />
              <Row k="总资产" v={fmtUsd(totalEquity)} hi big relaxed />
            </Panel>

            <Panel title="今日盈亏">
              <Row k="已实现盈亏" v={fmtUsd(pnl?.realized_usd)} colored={pnl?.realized_usd} relaxed />
              <Row k="胜 / 负" v={`${pnl?.wins ?? 0} / ${pnl?.losses ?? 0}`} relaxed />
              <Row k="胜率" v={fmtPct(winRate ?? null)} relaxed />
              <Row k="待结算" v={String(pnl?.pending ?? 0)} dim relaxed />
              <Row k="统计起始" v={pnl?.period_start_ts ? fmtTime(pnl.period_start_ts) : '--'} dim mono relaxed />
            </Panel>

            <Panel title="交易策略" flex>
              <div style={strategyStackStyle}>
                <div style={strategySectionStyle}>
                  <div style={subTitleStyle}>BTC</div>
                  <Row k="下行入场" v={`${fmtPx(state?.config.min_entry_price)}-${fmtPx(state?.config.max_entry_price)}`} mono />
                  <Row k="上行入场" v={`${fmtPx(state?.config.up_min_entry_price)}-${fmtPx(state?.config.up_max_entry_price)}`} mono />
                  <Row k="BTC 过滤器" v={btcFilterLabel} mono />
                  <Row k="早期强信号" v={earlyStrongDeltaEntryLabel} mono />
                  <Row k="强 Delta" v={strongDeltaEntryLabel} mono />
                  <Row k="尾盘边际" v={lateEdgeEntryLabel} mono />
                  <Row k="稳定 Delta" v={stableDeltaEntryLabel} mono />
                  <Row k="入场动量" v={entryMomentumLabel} mono />
                  <Row k="趋势过热" v={trendOverheatLabel} mono />
                  <Row k="下单规模" v={sizeLabel} mono />
                </div>
                <div style={strategySectionStyle}>
                  <div style={subTitleStyle}>ETH</div>
                  <Row k="下行入场" v={`${fmtPx(state?.config.min_entry_price)}-${fmtPx(state?.config.max_entry_price)}`} mono />
                  <Row k="上行入场" v={`${fmtPx(state?.config.up_min_entry_price)}-${fmtPx(state?.config.up_max_entry_price)}`} mono />
                  <Row k="ETH 过滤器" v={ethFilterLabel} mono />
                  <Row k="ETH 交易" v={ethTradingLabel} mono colored={state?.config.eth_trading_enabled ? 1 : null} />
                  <Row k="早期强信号" v={ethEarlyStrongLabel} mono />
                  <Row k="强 Delta" v={ethStrongDeltaLabel} mono />
                  <Row k="尾盘边际" v={ethLateEdgeLabel} mono />
                  <Row k="入场动量" v={entryMomentumLabel} mono />
                  <Row k="下单规模" v={ethSizeLabel} mono />
                </div>
              </div>
              <Sep />
              <Row k="净边际" v={highEdgeLabel} mono />
              <Row k="价格保护" v={priceGuardLabel} mono colored={state?.config.price_source_guard_enabled && !state?.config.allow_binance_proxy_chainlink_entries ? 1 : -1} />
              <Row k="时间窗口" v={`${state?.config.min_t_remaining_sec ?? '?'}-${state?.config.seconds_before_close ?? '?'}s`} mono />
              <Row k="提前入场" v={earlyEntryLabel} mono />
              <Row k="中段入场" v={midEntryLabel} mono />
              <Row k="尾盘入场" v={tailEntryLabel} mono />
              <Row k="分批加仓" v={scaleInLabel} mono />
              <Row k="单边限制" v={oneSideLabel} mono />
              <Row k="强转普通" v={strongNormalReverseLabel} mono />
              <Row k="最小订单" v={fmtUsd(state?.config.min_order_notional_usd)} mono />
              <Row k="余额预留" v={fmtUsd(state?.config.order_balance_reserve_usd)} mono />
              <Row k="每小时订单" v={ordersPerHourLabel} mono />
              <Row k="早期反转退出" v={earlyReversalLabel} mono />
              <Row k="反转退出" v={reversalLabel} mono />
              <Row k="确认次数" v={`${state?.config.confirm_checks ?? '?'}x`} mono />
              <Row
                k="重试策略"
                v={`${state?.config.max_buy_retries_per_market === 0 ? 'unlimited' : `${state?.config.max_buy_retries_per_market ?? '?'}x`} / ${state?.config.order_retry_cooldown_sec ?? '?'}s / >=${state?.config.retry_min_t_remaining_sec ?? '?'}s / ${state?.config.max_retry_price_drift_ticks != null && state.config.max_retry_price_drift_ticks < 0 ? 'drift unlimited' : `+${state?.config.max_retry_price_drift_ticks ?? '?'}t`}`}
                mono
              />
              <Row k="FOK 缓冲" v={`${state?.config.fok_price_buffer_ticks ?? 0} tick`} mono />
              <Row k="卖出滑点" v={`${state?.config.sell_fok_slippage_ticks ?? 0} tick`} mono />
              <Sep />
              <Row k="未结算上限" v={String(state?.config.max_open_positions ?? '')} mono />
              <Row k="每日亏损上限" v={fmtPct((state?.config.max_daily_loss_fraction ?? 0) * 100)} mono />
              <Row k="每日已实现上限" v={realizedCapUsd > 0 ? fmtUsd(realizedCapUsd) : '关闭'} mono />
            </Panel>
          </div>

          <div style={compactLayout ? compactMiddleColStack : colStack}>
            <Panel title={m ? `${m.synthetic ? 'BTC 计时器' : '实时市场'} // ${m.market_slug}${m.synthetic ? ' // 仅展示' : ''}` : '暂无实时市场'}>
              {m ? (
                <>
                  <Row
                    k="BTC 价格差"
                    v={btcDeltaLabel}
                    hi
                    mono
                    colored={btcSignal ? btcSignal.delta_usd : null}
                  />
                  <Row k={btcPriceKey.replace('TWAP PX / BEAT', 'TWAP / 基准').replace('PX / BEAT', '价格 / 基准')} v={btcPriceLabel} mono />
                  <Sep />
                  <Row
                    k="倒计时"
                    v={fmtDur(tRem)}
                    hi
                    big
                    colored={tRem != null && tRem < 60 ? 1 : -1}
                  />
                  <BookView
                    label="上涨"
                    book={state?.book_up}
                    cap={state?.config.up_max_entry_price ?? 0.87}
                    floor={state?.config.up_min_entry_price ?? 0.84}
                  />
                  <BookView
                    label="下跌"
                    book={state?.book_down}
                    cap={state?.config.max_entry_price ?? 0.95}
                    floor={state?.config.min_entry_price ?? 0.80}
                  />
                </>
              ) : (
                <div style={{ color: 'var(--txt-dim)', padding: '6px 0' }}>
                  等待下一个 5 分钟 BTC 窗口<span className="caret">_</span>
                </div>
              )}
            </Panel>

            <Panel title={ethM ? `ETH 市场 // ${ethM.market_slug}${ethM.synthetic ? ' // 仅展示' : ''}` : 'ETH 市场 // 监控'}>
              {state?.config.eth_market_enabled && ethM ? (
                <>
                  <Row
                    k="ETH 价格差"
                    v={ethDeltaLabel}
                    hi
                    mono
                    colored={ethSignal ? ethSignal.delta_usd : null}
                  />
                  <Row k={ethPriceKey.replace('TWAP PX / BEAT', 'TWAP / 基准').replace('PX / BEAT', '价格 / 基准')} v={ethPriceLabel} mono />
                  <Sep />
                  <Row
                    k="倒计时"
                    v={fmtDur(ethTRem)}
                    hi
                    colored={ethTRem != null && ethTRem < 60 ? 1 : -1}
                  />
                  <BookView
                    label="上涨"
                    book={state?.eth_book_up}
                    cap={state?.config.up_max_entry_price ?? 0.93}
                    floor={state?.config.up_min_entry_price ?? 0.80}
                  />
                  <BookView
                    label="下跌"
                    book={state?.eth_book_down}
                    cap={state?.config.max_entry_price ?? 0.93}
                    floor={state?.config.min_entry_price ?? 0.80}
                  />
                </>
              ) : (
                <div style={{ color: 'var(--txt-dim)', padding: '6px 0' }}>
                  ETH 监控未启用或等待下一个 5 分钟窗口<span className="caret">_</span>
                </div>
              )}
            </Panel>

            <Panel title="决策日志 // 实时" flex>
              <DecisionsTable decisions={state?.decisions ?? []} />
            </Panel>
          </div>

          <div style={compactLayout ? compactRightColStack : colStack}>
            <Panel title="当前持仓">
              <PositionsTable positions={state?.positions ?? []} />
            </Panel>

            <Panel title="订单 // 最近">
              <OrdersTable orders={state?.orders ?? []} />
            </Panel>
          </div>
        </div>

        <BottomBar state={state} />
      </div>
      {showSettings && <SystemSettings onClose={() => setShowSettings(false)} />}
    </>
  );
}

function SystemSettings({ onClose }: { onClose: () => void }) {
  const [settings, setSettings] = useState<LlmSettings | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [probing, setProbing] = useState(false);
  const [testing, setTesting] = useState(false);
  const [message, setMessage] = useState('');
  useEffect(() => {
    fetchLlmSettings().then(setSettings).catch((e) => setMessage(`读取失败：${e}`)).finally(() => setLoading(false));
  }, []);
  const update = (patch: Partial<LlmSettings>) => setSettings((s) => s ? { ...s, ...patch } : s);
  const save = async () => {
    if (!settings) return;
    setSaving(true); setMessage('');
    try {
      const saved = await saveLlmSettings(settings);
      setSettings(saved);
      setMessage('已保存。重启服务后生效。');
    } catch (e) { setMessage(`保存失败：${e}`); }
    finally { setSaving(false); }
  };
  const probe = async () => {
    if (!settings) return;
    const key = settings.api_key && settings.api_key !== '••••••••' ? settings.api_key : (settings.api_key_configured ? '••••••••' : '');
    if (!settings.base_url || !key) { setMessage('请填写接口地址和 API 密钥后再拉取模型。'); return; }
    setProbing(true); setMessage('正在拉取模型列表…');
    try {
      const result = await probeLlm(settings.base_url, key, settings.timeout_sec);
      update({ base_url: result.effective_base_url, model: settings.model || result.models[0] || '' });
      setMessage(result.models.length ? `已发现 ${result.models.length} 个模型。` : '接口可用，但未返回模型列表。');
    } catch (e) { setMessage(`拉取失败：${e}`); }
    finally { setProbing(false); }
  };
  const test = async () => {
    if (!settings) return;
    setTesting(true); setMessage('正在测试模型连接…');
    try {
      const result = await testLlm({ base_url: settings.base_url, model: settings.model, api_key: settings.api_key, timeout_sec: settings.timeout_sec });
      setMessage(`连接成功（${result.model}，${result.latency_ms} ms）。`);
    } catch (e) { setMessage(`测试失败：${e}`); }
    finally { setTesting(false); }
  };
  return (
    <div className="settings-overlay" role="dialog" aria-modal="true" aria-label="系统设置">
      <div className="settings-dialog">
        <div className="settings-header"><span>系统设置 / 模型 API</span><button type="button" onClick={onClose} className="settings-close">×</button></div>
        {loading && <div className="settings-loading">正在读取配置…</div>}
        {!loading && settings && <>
          <p className="settings-note">配置参考 Mix「systemLLM」中继格式。API 密钥仅用于连接模型，页面不会显示原文。AI 只读顾问可分析行情，但不会直接下单；保存后请重启机器人服务。</p>
          <div className="settings-grid">
            <label>启用模型 API<input type="checkbox" checked={settings.enabled} onChange={(e) => update({ enabled: e.target.checked })} /></label>
            <label>启用 AI 只读顾问<input type="checkbox" checked={settings.advisor_enabled} onChange={(e) => update({ advisor_enabled: e.target.checked })} /></label>
            <label>服务商标识<input value={settings.provider} onChange={(e) => update({ provider: e.target.value })} placeholder="openai-compatible" /></label>
            <label className="settings-wide">接口地址<input value={settings.base_url} onChange={(e) => update({ base_url: e.target.value })} placeholder="https://api.openai.com/v1" /><small className="settings-hint">填写 OpenAI 兼容地址；裸域名会自动补上 /v1。</small></label>
            <label>模型名称<input value={settings.model} onChange={(e) => update({ model: e.target.value })} placeholder="gpt-4o-mini" /></label>
            <label>API 密钥<input type="password" value={settings.api_key === '••••••••' ? '' : settings.api_key} onChange={(e) => update({ api_key: e.target.value })} placeholder={settings.api_key_configured ? '已配置（留空保持不变）' : '请输入密钥'} autoComplete="new-password" /></label>
            <label>超时（秒）<input type="number" min="1" max="60" step="1" value={settings.timeout_sec} onChange={(e) => update({ timeout_sec: Number(e.target.value) })} /></label>
            <label>最大 Tokens<input type="number" min="1" max="32768" step="1" value={settings.max_tokens} onChange={(e) => update({ max_tokens: Number(e.target.value) })} /></label>
            <label>温度<input type="number" min="0" max="2" step="0.1" value={settings.temperature} onChange={(e) => update({ temperature: Number(e.target.value) })} /></label>
            <label className="settings-wide">系统提示词<textarea rows={4} value={settings.system_prompt} onChange={(e) => update({ system_prompt: e.target.value })} placeholder="可选：用于模型决策的系统提示词" /></label>
          </div>
          {message && <div className="settings-message">{message}</div>}
          <div className="settings-actions"><button type="button" onClick={probe} disabled={probing || testing} className="settings-secondary">{probing ? '拉取中…' : '拉取模型'}</button><button type="button" onClick={test} disabled={testing || probing} className="settings-secondary">{testing ? '测试中…' : '测试连接'}</button><button type="button" onClick={onClose} className="settings-secondary">取消</button><button type="button" onClick={save} disabled={saving || probing || testing} className="settings-primary">{saving ? '保存中…' : '保存设置'}</button></div>
        </>}
      </div>
    </div>
  );
}

function TopBar({
  time, botRunning, botMode, riskState, err, lastFlashAt, onSettings,
  operatorToken, onOperatorTokenChange, liveBusy, liveMessage, onToggleLive,
}: {
  time: number;
  botRunning: boolean;
  botMode: string;
  riskState: string;
  err: string | null;
  lastFlashAt: number;
  onSettings: () => void;
  operatorToken: string;
  onOperatorTokenChange: (value: string) => void;
  liveBusy: boolean;
  liveMessage: string;
  onToggleLive: () => void;
}) {
  const blink = Date.now() - lastFlashAt < 5000;
  const riskOk = riskState === 'OK';
  const botLabel = !botRunning
    ? '已停止'
    : !riskOk
      ? `已锁定 (${zhText(riskState)})`
      : '运行中';
  const botColor = !botRunning
    ? 'var(--red)'
    : !riskOk
      ? 'var(--amber)'
      : 'var(--green)';

  // mode chip: green for paper (safe), red for live (real money)
  const modeChip = botMode === 'live'
    ? { label: '实盘', bg: '#330000', fg: 'var(--red)', border: 'var(--red)' }
    : botMode === 'paper'
      ? { label: '模拟盘', bg: '#001a0d', fg: 'var(--green)', border: 'var(--green)' }
      : { label: '离线', bg: 'transparent', fg: 'var(--txt-dim)', border: 'var(--border-hi)' };

  return (
    <div style={topBarStyle}>
      <span style={{ color: 'var(--amber)', fontWeight: 700 }}>POLY_HFT</span>
      <span style={{ color: 'var(--txt-dim)' }}> // </span>
      <span style={{ color: 'var(--txt-hi)' }}>BTC / ETH 五分钟</span>
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
        * 机器人 {botLabel}
      </span>
      <span style={{ color: 'var(--txt-dim)', margin: '0 12px' }}>|</span>
      <span style={{ color: err ? 'var(--red)' : 'var(--green)' }}>
        * {err ? '接口错误' : '接口正常'}
      </span>
      {blink && (
        <>
          <span style={{ color: 'var(--txt-dim)', margin: '0 12px' }}>|</span>
          <span style={{ color: 'var(--amber-bright)', fontWeight: 700 }}>* 已触发交易</span>
        </>
      )}
      <button type="button" onClick={onSettings} className="settings-button">系统设置</button>
      <input
        type="password"
        value={operatorToken}
        onChange={(e) => onOperatorTokenChange(e.target.value)}
        className="live-token-input"
        placeholder="实盘令牌"
        aria-label="实盘操作令牌"
        autoComplete="off"
      />
      <button
        type="button"
        onClick={onToggleLive}
        disabled={liveBusy}
        className={botRunning && botMode === 'live' ? 'live-stop-button' : 'live-start-button'}
        title={liveMessage || '需要实盘操作令牌'}
      >
        {liveBusy ? '处理中…' : botRunning && botMode === 'live' ? '关闭实盘' : '开启实盘'}
      </button>
      {liveMessage && <span className="live-control-message" title={liveMessage}>{liveMessage}</span>}
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
      <span style={{ color: 'var(--txt-dim)' }}>轮询 500ms</span>
      <span style={{ color: 'var(--txt-dim)', margin: '0 12px' }}>/</span>
      <span style={{ color: 'var(--txt-dim)' }}>
        决策 {state?.decisions.length ?? 0} / 订单 {state?.orders.length ?? 0}
      </span>
      <span style={spacer} />
      {errKeys.length > 0 && (
        <span style={{ color: 'var(--red)' }}>错误：{errKeys.join(', ')}</span>
      )}
    </div>
  );
}

/** Translate common strategy/status tokens while preserving numeric details. */
function zhText(value: string): string {
  return value
    .replace(/\bSELL_DOWN\b/gi, '卖出：下跌')
    .replace(/\bSELL_UP\b/gi, '卖出：上涨')
    .replace(/\bUP\b/gi, '上涨')
    .replace(/\bDOWN\b/gi, '下跌')
    .replace(/\bbuy window\b/gi, '买入窗口')
    .replace(/\bexec_ask\b/gi, '执行卖价')
    .replace(/\bt_remaining\b/gi, '剩余时间')
    .replace(/\bedge\b/gi, '优势')
    .replace(/\bexit_dry_run\b/gi, '模拟退出')
    .replace(/\bdry_run\b/gi, '模拟执行')
    .replace(/\bSKIP_PRICE\b/gi, '跳过：价格')
    .replace(/\bSKIP_TIME\b/gi, '跳过：时间')
    .replace(/\bSKIP_MARKET\b/gi, '跳过：市场')
    .replace(/\bSKIP_BALANCE\b/gi, '跳过：余额')
    .replace(/\bSELL_DOWN\b/gi, '卖出：下跌')
    .replace(/\bSELL_UP\b/gi, '卖出：上涨')
    .replace(/\bBUY\b/g, '买入')
    .replace(/\bSELL\b/g, '卖出')
    .replace(/\bHIT\b/g, '命中')
    .replace(/\bMISS\b/g, '未命中')
    .replace(/\bFAILED\b/g, '失败')
    .replace(/\bPENDING\b/g, '待结算')
    .replace(/\bUNCERTAIN\b/g, '待确认')
    .replace(/\bEXITED\b/g, '已退出')
    .replace(/\bPARTIAL_EXIT\b/g, '部分退出')
    .replace(/\bEXIT_FAILED\b/g, '退出失败')
    .replace(/\bEXIT_UNCERTAIN\b/g, '退出待确认')
    .replace(/\bEXIT_UNMATCHED\b/g, '未成交（盘口无匹配，等待重试）')
    .replace(/\bexit_unmatched\b/gi, '未成交（盘口无匹配）')
    .replace(/\bNONE\b/g, '无')
    .replace(/\boff\b/gi, '关闭')
    .replace(/\bprice-only\b/gi, '仅价格')
    .replace(/\bmonitor only\b/gi, '仅监控')
    .replace(/\bLIVE ENABLED\b/gi, '实盘已启用')
    .replace(/\bunlimited\b/gi, '不限')
    .replace(/\bdrift unlimited\b/gi, '滑点不限')
    .replace(/\bhedge\b/gi, '对冲')
    .replace(/\bskip\b/gi, '跳过')
    .replace(/\bnormal\b/gi, '常规')
    .replace(/\bearly\b/gi, '早期')
    .replace(/\bstrong\b/gi, '强信号')
    .replace(/\btail\b/gi, '尾盘')
    .replace(/\blate\b/gi, '尾段')
    .replace(/\bfinal\b/gi, '最终')
    .replace(/\bprev\b/gi, '前一档')
    .replace(/\bmove\b/gi, '变动')
    .replace(/\bsame-dir\b/gi, '同方向')
    .replace(/\bper-slot side\b/gi, '每时段单边')
    .replace(/\bheld\b/gi, '持有')
    .replace(/\breverse\b/gi, '反转')
    .replace(/\bdrift\b/gi, '价格漂移')
    .replace(/\bequity\b/gi, '资产')
    .replace(/\bfixed\b/gi, '固定')
    .replace(/\bno qualifying side\b/gi, '没有符合条件的方向')
    .replace(/\bno qualifying market\b/gi, '没有符合条件的市场')
    .replace(/\bUP edge\b/gi, '上涨优势')
    .replace(/\bDOWN edge\b/gi, '下跌优势')
    .replace(/\bnet_edge\b/gi, '净优势')
    .replace(/\bask\b/gi, '卖价')
    .replace(/\blimit\b/gi, '上限')
    .replace(/\bfee\b/gi, '手续费')
    .replace(/\bWARN proxy allowed\b/gi, '警告：允许代理')
    .replace(/\bON: RTDS TWAP required\b/gi, '开启：需要 RTDS TWAP')
    .replace(/\bON: block Binance proxy on Chainlink\b/gi, '开启：阻止 Binance 代理')
    .replace(/\ball non-tail\b/gi, '所有非尾盘')
    .replace(/\bSTABLE\b/gi, '稳定')
    .replace(/\bSTALE\b/gi, '过期')
    .replace(/\bPROFIT_TAKE\b/g, '止盈保护')
    .replace(/\bLOSS_CAP\b/g, '亏损上限')
    .replace(/\bLOSS_STREAK\b/g, '连续亏损')
    .replace(/\bOK\b/g, '正常');
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
      }}>{typeof v === 'string' ? zhText(v) : v}</span>
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
      <span style={{ color: 'var(--txt-dim)' }}>买一</span>
      <span style={{ color: 'var(--green)' }}>{fmtPx(book?.best_bid)}</span>
      <span style={{ color: 'var(--txt-dim)' }}>x{fmtNum(book?.bid_size, 0)}</span>
      <span style={spacer} />
      <span style={{ color: 'var(--txt-dim)' }}>卖一</span>
      <span style={{ color: askColor, fontWeight: 700 }}>{fmtPx(ask)}</span>
      <span style={{ color: 'var(--txt-dim)' }}>x{fmtNum(book?.ask_size, 0)}</span>
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
  if (r === 'PENDING' || r === 'UNCERTAIN' || r === 'EXITED' || r === 'PARTIAL_EXIT' || r === 'EXIT_UNCERTAIN' || r === 'EXIT_UNMATCHED') return 'var(--amber)';
  return 'var(--txt-dim)';
}

function orderStatusColor(status: string): string {
  if (status === 'matched' || status === 'filled' || status === 'exit_matched' || status === 'exit_filled') return 'var(--green)';
  if (status === 'error' || status === 'pre_submit_error' || status === 'exit_error' || status === 'exit_pre_submit_error') return 'var(--red)';
  return 'var(--amber)';
}

function DecisionsTable({ decisions }: { decisions: Decision[] }) {
  if (!decisions.length) return <Empty>暂无决策<span className="caret">_</span></Empty>;
  return (
    <table style={tableStyle}>
      <thead>
        <tr>
          <Th>时间</Th><Th>资产</Th><Th>市场</Th><Th>方向</Th><Th right>剩余</Th><Th right>卖价</Th><Th>动作</Th><Th>原因</Th>
        </tr>
      </thead>
      <tbody>
        {decisions.slice(0, 40).map((d) => (
          <tr key={d.id} style={{ background: d.action === 'BUY' ? 'rgba(0,255,127,0.04)' : undefined }}>
            <Td dim>{fmtTime(d.ts)}</Td>
            <Td>{d.asset || '--'}</Td>
            <Td dim>{shortMarket(d.market_slug)}</Td>
            <Td>{d.side ? zhText(d.side) : '-'}</Td>
            <Td right>{fmtNum(d.t_remaining, 1)}s</Td>
            <Td right>{fmtPx(d.ask_price)}</Td>
            <Td color={actionColor(d.action)} bold>{zhText(d.action)}</Td>
            <Td dim>{zhText(d.reason)}</Td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function OrdersTable({ orders }: { orders: Order[] }) {
  if (!orders.length) return <Empty>暂无订单<span className="caret">_</span></Empty>;
  return (
    <table style={tableStyle}>
      <thead>
        <tr>
          <Th>时间</Th><Th>资产</Th><Th>市场</Th><Th>方向</Th><Th right>数量</Th><Th right>价格</Th><Th>状态</Th><Th>结果</Th><Th right>成交额</Th>
        </tr>
      </thead>
      <tbody>
        {orders.slice(0, 20).map((o) => {
          return (
            <tr key={o.id}>
              <Td dim>{fmtTime(o.ts)}</Td>
              <Td>{o.asset || '--'}</Td>
              <Td dim>{shortMarket(o.market_slug)}</Td>
              <Td>{zhText(o.side)}</Td>
              <Td right>{fmtNum(o.size, 2)}</Td>
              <Td right>{fmtPx(o.price)}</Td>
            <Td color={orderStatusColor(o.status)} bold>{zhText(o.status)}</Td>
            <Td color={resultColor(o.result)} bold>{zhText(o.result)}</Td>
              <Td right>{fmtUsd(o.filled_size)}</Td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}

function PositionsTable({ positions }: { positions: Position[] }) {
  if (!positions.length) return <Empty>暂无持仓<span className="caret">_</span></Empty>;
  return (
    <table style={tableStyle}>
      <thead>
        <tr>
          <Th>名称</Th><Th>方向</Th><Th right>数量</Th><Th right>价格</Th><Th right>价值</Th>
        </tr>
      </thead>
      <tbody>
        {positions.map((p, i) => (
          <tr key={i}>
            <Td dim>{(p.title || '').replace(/^Bitcoin Up or Down - /, '')}</Td>
            <Td>{p.outcome ? zhText(p.outcome) : '-'}</Td>
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
const spacer: CSSProperties = { flex: 1 };
const tableStyle: CSSProperties = { width: '100%', borderCollapse: 'collapse', fontSize: 11 };
