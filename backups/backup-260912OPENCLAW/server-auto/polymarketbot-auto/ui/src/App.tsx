import { useEffect, useRef, useState } from 'react';
import type { CSSProperties, ReactNode } from 'react';
import { controlLive, fetchLlmSettings, fetchState, probeLlm, saveLlmSettings, testLlm, toggleLiveService } from './api';
import type {
  Book,
  Decision,
  AgentStatus,
  LlmSettings,
  LlmModelProfile,
  Order,
  Position,
  PriceHistoryPoint,
  SportsRealtime,
  State,
  WeatherRealtime,
} from './types';
import { fmtDur, fmtNum, fmtPct, fmtPx, fmtTime, fmtUsd } from './format';

const POLL_MS = 500;

export default function App() {
  const [state, setState] = useState<State | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [now, setNow] = useState<number>(Date.now() / 1000);
  const [flash, setFlash] = useState<boolean>(false);
  const [lastFlashAt, setLastFlashAt] = useState<number>(0);
  const [showSettings, setShowSettings] = useState<boolean>(false);
  const [activeModal, setActiveModal] = useState<'positions' | 'orders' | null>(null);
  const [operatorToken, setOperatorToken] = useState<string>('');
  const [liveBusy, setLiveBusy] = useState<boolean>(false);
  const [liveMessage, setLiveMessage] = useState<string>('');
  const [serviceBusy, setServiceBusy] = useState<string | null>(null);
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

  useEffect(() => {
    if (!activeModal) return undefined;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setActiveModal(null);
    };
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, [activeModal]);

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

  const toggleService = async (asset: string, enabled: boolean) => {
    if (!operatorToken.trim()) { setLiveMessage('请先填写实盘操作令牌。'); return; }
    if (enabled && !window.confirm(`确认仅为 ${asset} 开启实盘资格？开启资格不会自动启动订单。`)) return;
    setServiceBusy(asset);
    try { await toggleLiveService(asset, enabled, operatorToken.trim()); setState(await fetchState()); setLiveMessage(`${asset} 实盘资格已${enabled ? '开启' : '关闭'}。`); }
    catch (e) { setLiveMessage(`操作失败：${e}`); }
    finally { setServiceBusy(null); }
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
          serviceModes={state?.service_modes}
          serviceBusy={serviceBusy}
          onToggleService={toggleService}
        />

        <KpiStrip state={state} totalEquity={totalEquity} winRate={winRate} />

        <div style={compactLayout ? compactGridStyle : gridStyle}>
          <div style={compactLayout ? compactLeftColStack : colStack}>
            <Panel title="钱包 / 资产">
              <Row k="pUSD 现金" v={fmtUsd(state?.wallet.balance_pusd)} hi relaxed />
              <Row
                k="持仓市值"
                v={fmtUsd(state?.wallet.value_usd)}
                relaxed
                clickable
                onClick={() => setActiveModal('positions')}
                ariaLabel="打开当前持仓"
              />
              <Sep />
              <Row k="总资产" v={fmtUsd(totalEquity)} hi big relaxed />
            </Panel>

            <Panel title="今日盈亏" onClick={() => setActiveModal('orders')} ariaLabel="打开最近订单">
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
            <Panel
              title={m ? `${m.synthetic ? 'BTC 计时器' : '实时市场'} // ${m.market_slug}${m.synthetic ? ' // 仅展示' : ''}` : '暂无实时市场'}
              contentStyle={{ position: 'relative', overflow: 'hidden' }}
            >
              {m ? (
                <MarketPanelBody>
                  <VolatilityChart asset="BTC" history={state?.btc_price_history} currentPrice={btcSignal?.current_price} />
                  <div className="market-panel-foreground">
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
                  </div>
                </MarketPanelBody>
              ) : (
                <div style={{ color: 'var(--txt-dim)', padding: '6px 0' }}>
                  等待下一个 5 分钟 BTC 窗口<span className="caret">_</span>
                </div>
              )}
            </Panel>

            <Panel
              title={ethM ? `ETH 市场 // ${ethM.market_slug}${ethM.synthetic ? ' // 仅展示' : ''}` : 'ETH 市场 // 监控'}
              contentStyle={{ position: 'relative', overflow: 'hidden' }}
            >
              {state?.config.eth_market_enabled && ethM ? (
                <MarketPanelBody>
                  <VolatilityChart asset="ETH" history={state?.eth_price_history} currentPrice={ethSignal?.current_price} />
                  <div className="market-panel-foreground">
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
                  </div>
                </MarketPanelBody>
              ) : (
                <div style={{ color: 'var(--txt-dim)', padding: '6px 0' }}>
                  ETH 监控未启用或等待下一个 5 分钟窗口<span className="caret">_</span>
                </div>
              )}
            </Panel>

            <Panel title="天气 // 实时">
              <WeatherRealtimePanel weather={state?.weather} />
            </Panel>

            <Panel title="体育 // 实时（仅 paper）">
              <SportsRealtimePanel sports={state?.sports} />
            </Panel>
          </div>

          <div style={compactLayout ? compactRightColStack : colStack}>
            <Panel title="概率预测 // 实时">
              <ProbabilityPanel state={state} />
            </Panel>
            <Panel title="决策日志 // 实时" flex>
              <DecisionsTable decisions={state?.decisions ?? []} />
            </Panel>
          </div>
        </div>

        <BottomBar state={state} />
      </div>
      {showSettings && <SystemSettings onClose={() => setShowSettings(false)} />}
      {activeModal === 'positions' && (
        <DataModal title="当前持仓" onClose={() => setActiveModal(null)}>
          <PositionsTable positions={state?.positions ?? []} />
        </DataModal>
      )}
      {activeModal === 'orders' && (
        <DataModal title="订单 // 最近" onClose={() => setActiveModal(null)}>
          <OrdersTable orders={state?.orders ?? []} />
        </DataModal>
      )}
    </>
  );
}

function ProbabilityPanel({ state }: { state: State | null }) {
  const rows = [
    ['BTC 上涨', state?.btc_signal ? Math.max(0, Math.min(1, 0.5 + state.btc_signal.delta_usd / 200)) : null, '#f4b942'],
    ['BTC 下跌', state?.btc_signal ? Math.max(0, Math.min(1, 0.5 - state.btc_signal.delta_usd / 200)) : null, '#f05b68'],
    ['ETH 上涨', state?.eth_signal ? Math.max(0, Math.min(1, 0.5 + state.eth_signal.delta_usd / 200)) : null, '#4ec0ff'],
    ['ETH 下跌', state?.eth_signal ? Math.max(0, Math.min(1, 0.5 - state.eth_signal.delta_usd / 200)) : null, '#8d7cff'],
  ] as const;
  return <div className="probability-panel">{rows.map(([label, probability, color]) => <div className="probability-row" key={label}><span>{label}</span><div className="probability-track"><i style={{ width: `${(probability ?? 0) * 100}%`, background: color }} /></div><b>{probability == null ? '--' : fmtPct(probability * 100)}</b></div>)}</div>;
}

function KpiStrip({ state, totalEquity, winRate }: { state: State | null; totalEquity: number | null; winRate: number | null }) {
  const pnl = state?.pnl?.realized_usd ?? null;
  const daily = pnl;
  const returnPct = totalEquity && totalEquity > 0 && pnl != null ? pnl / totalEquity * 100 : null;
  const items = [
    ['账户余额', fmtUsd(state?.wallet.balance_pusd)],
    ['累计盈亏', fmtUsd(pnl), pnl],
    ['收益率', fmtPct(returnPct), returnPct],
    ['胜率', fmtPct(winRate), winRate],
    ['今日损益', fmtUsd(daily), daily],
  ] as const;
  return <div className="kpi-strip" aria-label="账户关键指标">
    {items.map(([label, value, tone]) => <div className="kpi-card" key={label}>
      <span className="kpi-label">{label}</span><strong className={tone == null ? '' : tone >= 0 ? 'kpi-positive' : 'kpi-negative'}>{value}</strong>
    </div>)}
  </div>;
}

function emptyProfile(): LlmModelProfile {
  return { enabled: false, provider: 'openai-compatible', base_url: '', model: '', api_key: '', api_key_configured: false, timeout_sec: 30, max_tokens: 512, temperature: 0.2, system_prompt: '' };
}

function profileFromLegacy(settings: LlmSettings): LlmModelProfile {
  return {
    enabled: settings.enabled,
    provider: settings.provider,
    base_url: settings.base_url,
    model: settings.model,
    api_key: settings.api_key,
    api_key_configured: settings.api_key_configured,
    timeout_sec: settings.timeout_sec,
    max_tokens: settings.max_tokens,
    temperature: settings.temperature,
    system_prompt: settings.system_prompt,
  };
}

function SystemSettings({ onClose }: { onClose: () => void }) {
  const [settings, setSettings] = useState<LlmSettings | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [probing, setProbing] = useState(false);
  const [testing, setTesting] = useState(false);
  const [message, setMessage] = useState('');
  const [activeSlot, setActiveSlot] = useState<'primary' | 'secondary'>('primary');
  useEffect(() => {
    fetchLlmSettings().then((raw) => {
      const primary = raw.primary || profileFromLegacy(raw);
      const secondary = raw.secondary || emptyProfile();
      setSettings({ ...raw, primary, secondary });
    }).catch((e) => setMessage(`读取失败：${e}`)).finally(() => setLoading(false));
  }, []);
  const update = (patch: Partial<LlmSettings>) => setSettings((s) => s ? { ...s, ...patch } : s);
  const updateProfile = (slot: 'primary' | 'secondary', patch: Partial<LlmModelProfile>) => setSettings((s) => {
    if (!s) return s;
    const current = s[slot] || (slot === 'primary' ? profileFromLegacy(s) : emptyProfile());
    const next = { ...current, ...patch };
    // Keep the legacy flat fields synchronized with the primary profile so
    // older dashboard servers continue to work unchanged.
    return slot === 'primary'
      ? { ...s, ...next, primary: next }
      : { ...s, secondary: next };
  });
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
    const profile = settings[activeSlot] || (activeSlot === 'primary' ? profileFromLegacy(settings) : emptyProfile());
    const key = profile.api_key && profile.api_key !== '••••••••' ? profile.api_key : (profile.api_key_configured ? '••••••••' : '');
    if (!profile.base_url || !key) { setMessage('请填写当前模型接口地址和 API 密钥后再拉取模型。'); return; }
    setProbing(true); setMessage('正在拉取模型列表…');
    try {
      const result = await probeLlm(profile.base_url, key, profile.timeout_sec);
      updateProfile(activeSlot, { base_url: result.effective_base_url, model: profile.model || result.models[0] || '' });
      setMessage(`${activeSlot === 'primary' ? '主模型' : '复核模型'}已发现 ${result.models.length} 个模型。`);
    } catch (e) { setMessage(`拉取失败：${e}`); }
    finally { setProbing(false); }
  };
  const test = async () => {
    if (!settings) return;
    const profile = settings[activeSlot] || (activeSlot === 'primary' ? profileFromLegacy(settings) : emptyProfile());
    setTesting(true); setMessage('正在测试模型连接…');
    try {
      const result = await testLlm({ base_url: profile.base_url, model: profile.model, api_key: profile.api_key, timeout_sec: profile.timeout_sec });
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
          <p className="settings-note">配置参考 Mix「systemLLM」中继格式。主模型负责分析，复核模型独立校验；意见不一致时进入等待。API 密钥仅用于连接模型，页面不会显示原文。AI 不能绕过确定性风控或直接持有私钥；保存后请重启机器人服务。</p>
          <div className="settings-grid">
            <label>启用模型 API<input type="checkbox" checked={settings.enabled} onChange={(e) => update({ enabled: e.target.checked })} /></label>
            <label>启用 AI 只读顾问<input type="checkbox" checked={settings.advisor_enabled} onChange={(e) => update({ advisor_enabled: e.target.checked })} /></label>
            <div className="model-tabs settings-wide" role="tablist" aria-label="模型角色">
              <button type="button" className={activeSlot === 'primary' ? 'model-tab active' : 'model-tab'} onClick={() => setActiveSlot('primary')}>主模型 · GPT-6-Astra</button>
              <button type="button" className={activeSlot === 'secondary' ? 'model-tab active' : 'model-tab'} onClick={() => setActiveSlot('secondary')}>复核模型 · Grok</button>
            </div>
            {(() => {
              const profile = settings[activeSlot] || (activeSlot === 'primary' ? profileFromLegacy(settings) : emptyProfile());
              return <>
                <label>启用当前模型<input type="checkbox" checked={profile.enabled} onChange={(e) => updateProfile(activeSlot, { enabled: e.target.checked })} /></label>
                <label>服务商标识<input value={profile.provider} onChange={(e) => updateProfile(activeSlot, { provider: e.target.value })} placeholder="openai-compatible" /></label>
                <label className="settings-wide">接口地址<input value={profile.base_url} onChange={(e) => updateProfile(activeSlot, { base_url: e.target.value })} placeholder="https://api.openai.com/v1" /><small className="settings-hint">填写 OpenAI 兼容地址；裸域名会自动补上 /v1。</small></label>
                <label>模型名称<input value={profile.model} onChange={(e) => updateProfile(activeSlot, { model: e.target.value })} placeholder={activeSlot === 'primary' ? 'gpt-6-astra' : 'grok-4'}/></label>
                <label>API 密钥<input type="password" value={profile.api_key === '••••••••' ? '' : profile.api_key} onChange={(e) => updateProfile(activeSlot, { api_key: e.target.value })} placeholder={profile.api_key_configured ? '已配置（留空保持不变）' : '请输入密钥'} autoComplete="new-password" /></label>
                <label>超时（秒）<input type="number" min="1" max="120" step="1" value={profile.timeout_sec} onChange={(e) => updateProfile(activeSlot, { timeout_sec: Number(e.target.value) })} /></label>
                <label>最大 Tokens<input type="number" min="1" max="32768" step="1" value={profile.max_tokens} onChange={(e) => updateProfile(activeSlot, { max_tokens: Number(e.target.value) })} /></label>
                <label>温度<input type="number" min="0" max="2" step="0.1" value={profile.temperature} onChange={(e) => updateProfile(activeSlot, { temperature: Number(e.target.value) })} /></label>
                <label className="settings-wide">系统提示词<textarea rows={3} value={profile.system_prompt} onChange={(e) => updateProfile(activeSlot, { system_prompt: e.target.value })} placeholder="可选：用于模型决策的系统提示词" /></label>
              </>;
            })()}
          </div>
          {message && <div className="settings-message">{message}</div>}
          <div className="settings-actions"><button type="button" onClick={probe} disabled={probing || testing} className="settings-secondary">{probing ? '拉取中…' : '拉取模型'}</button><button type="button" onClick={test} disabled={testing || probing} className="settings-secondary">{testing ? '测试中…' : '测试连接'}</button><button type="button" onClick={onClose} className="settings-secondary">取消</button><button type="button" onClick={save} disabled={saving || probing || testing} className="settings-primary">{saving ? '保存中…' : '保存设置'}</button></div>
        </>}
      </div>
    </div>
  );
}

function DataModal({ title, onClose, children }: { title: string; onClose: () => void; children: ReactNode }) {
  return (
    <div
      className="data-modal-overlay"
      role="dialog"
      aria-modal="true"
      aria-label={title}
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <div className="data-modal-dialog" onMouseDown={(event) => event.stopPropagation()}>
        <div className="data-modal-header">
          <span>{title}</span>
          <button type="button" onClick={onClose} className="data-modal-close" aria-label="关闭">×</button>
        </div>
        <div className="data-modal-content">{children}</div>
      </div>
    </div>
  );
}

function WeatherRealtimePanel({ weather }: { weather?: WeatherRealtime[] }) {
  const rows = Array.isArray(weather) ? weather.slice(0, 4) : [];
  return (
    <div className="realtime-feed">
      {rows.length ? rows.map((item, index) => (
        <div className="realtime-feed-row" key={`${item.city || 'weather'}-${index}`}>
          <span className="realtime-feed-label">{item.city || item.market_slug || '天气市场'}</span>
          <span className="realtime-feed-value">{item.condition || '—'}</span>
          <span className="realtime-feed-value">{Number.isFinite(item.temperature_c) ? `${item.temperature_c!.toFixed(1)}°C` : '—'}</span>
          <span className="realtime-feed-value">{Number.isFinite(item.probability) ? fmtPct(item.probability! * 100) : '—'}</span>
        </div>
      )) : (
        <div className="realtime-feed-empty">等待天气数据源…</div>
      )}
      <div className="realtime-feed-meta">数据源：Open-Meteo / WeatherNext（预留） · 当前仅监控</div>
    </div>
  );
}

function SportsRealtimePanel({ sports }: { sports?: SportsRealtime[] }) {
  const rows = Array.isArray(sports) ? sports.slice(0, 4) : [];
  return (
    <div className="realtime-feed">
      {rows.length ? rows.map((item, index) => (
        <div className="realtime-feed-row" key={`${item.event || item.market_slug || 'sports'}-${index}`}>
          <span className="realtime-feed-label">{item.league || '体育市场'}</span>
          <span className="realtime-feed-value realtime-feed-event">{item.event || `${item.home_team || '主队'} vs ${item.away_team || '客队'}`}</span>
          <span className="realtime-feed-value">{item.status || (Number.isFinite(item.start_ts) ? fmtTime(item.start_ts) : '—')}</span>
          <span className="realtime-feed-value">{Number.isFinite(item.probability_home) ? fmtPct(item.probability_home! * 100) : '—'}</span>
        </div>
      )) : (
        <div className="realtime-feed-empty">等待体育市场数据源…</div>
      )}
      <div className="realtime-feed-meta">发现 / 规则 / 概率模型 / CLOB negRisk · 仅 paper，实盘关闭</div>
    </div>
  );
}

function TopBar({
  time, botRunning, botMode, riskState, err, lastFlashAt, onSettings,
  operatorToken, onOperatorTokenChange, liveBusy, liveMessage, onToggleLive, serviceModes, serviceBusy, onToggleService,
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
  serviceModes?: State['service_modes']; serviceBusy: string | null; onToggleService: (asset: string, enabled: boolean) => void;
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
      <div className="service-switches" aria-label="各服务实盘开关">
        {(['BTC', 'ETH', 'WEATHER', 'SPORTS'] as const).map((asset) => {
          const info = serviceModes?.[asset]; const allowed = info?.can_enable_live === true; const enabled = info?.live_enabled === true;
          return <button key={asset} type="button" className={`service-switch ${enabled ? 'service-on' : ''}`} disabled={!allowed || serviceBusy === asset} title={allowed ? `${asset} 实盘资格开关` : `${asset} 已锁定为 Paper`} onClick={() => onToggleService(asset, !enabled)}>{asset} {enabled ? 'LIVE' : 'PAPER'}</button>;
        })}
      </div>
      {liveMessage && <span className="live-control-message" title={liveMessage}>{liveMessage}</span>}
      <span style={spacer} />
      <span style={{ color: 'var(--txt)' }}>{fmtTime(time)}</span>
    </div>
  );
}

function BottomBar({ state }: { state: State | null }) {
  const errs = state?.errors || {};
  const errKeys = Object.keys(errs);
  const roleCards = OPENCLAW_ROLES.map((role) => ({ role, status: findAgentStatus(state?.agent_status, role.keys) }));
  return (
    <>
      <AssetDock state={state} />
      <div className="openclaw-agent-dock" aria-label="OpenClaw 中文权限状态">
        {roleCards.map(({ role, status }) => <AgentCard key={role.id} role={role} status={status} />)}
      </div>
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
    </>
  );
}

function AssetDock({ state }: { state: State | null }) {
  const assets = [
    ['BTC', state?.btc_signal?.current_price, '#f4b942', state?.bot_assets?.BTC],
    ['ETH', state?.eth_signal?.current_price, '#4ec0ff', state?.bot_assets?.ETH],
    ['天气', state?.weather?.length ?? 0, '#60a5fa', false],
    ['体育', state?.sports?.length ?? 0, '#c084fc', false],
  ] as const;
  return <div className="asset-dock" aria-label="资产服务">
    {assets.map(([name, value, color, live]) => <div className="asset-card" key={name} style={{ '--asset-accent': color } as CSSProperties}>
      <span className="asset-icon">{name.slice(0, 1)}</span><span className="asset-name">{name}</span><strong>{typeof value === 'number' ? (name === 'BTC' || name === 'ETH' ? fmtUsd(value) : `${value}`) : '--'}</strong><span className="asset-mode">{live ? '实盘' : '模拟'}</span>
    </div>)}
  </div>;
}

const OPENCLAW_ROLES = [
  { id: 'desk', label: '台长调度', keys: ['desk', 'head_of_desk', '台长调度'], color: '#ffc857', tool: '指挥' },
  { id: 'search', label: '机会猎手', keys: ['search', '机会猎手'], color: '#22d3ee', tool: '扫描' },
  { id: 'whale', label: '聪明钱跟踪', keys: ['whale', '聪明钱跟踪'], color: '#c084fc', tool: '追踪' },
  { id: 'shill', label: '舆情验证', keys: ['shill', '舆情验证'], color: '#60a5fa', tool: '验证' },
  { id: 'risk', label: '风控合规', keys: ['risk', '风控合规'], color: '#facc15', tool: '防护' },
  { id: 'sniper', label: '订单执行', keys: ['sniper', '订单执行'], color: '#fb923c', tool: '执行' },
  { id: 'exit', label: '仓位管理', keys: ['exit', '仓位管理'], color: '#4ade80', tool: '管理' },
  { id: 'rug', label: '熔断兜底', keys: ['rug', '熔断兜底'], color: '#f87171', tool: '熔断' },
] as const;

function findAgentStatus(all: Record<string, AgentStatus> | undefined, keys: readonly string[]): AgentStatus {
  if (!all) return { status: 'offline' };
  const entry = Object.entries(all).find(([key]) => keys.some((candidate) => key.toLowerCase() === candidate.toLowerCase()));
  return entry?.[1] || { status: 'offline' };
}

function AgentCard({ role, status }: { role: typeof OPENCLAW_ROLES[number]; status: AgentStatus }) {
  const raw = String(status.status || 'offline').toLowerCase();
  const statusKey = raw === 'running' || raw === 'ok' ? 'running' : raw === 'idle' || raw === 'waiting' ? 'idle' : raw === 'blocked' ? 'blocked' : raw === 'error' || raw === 'failed' ? 'error' : 'offline';
  const statusLabel = statusKey === 'running' ? '运行中' : statusKey === 'idle' ? '等待中' : statusKey === 'blocked' ? '已阻断' : statusKey === 'error' ? '异常' : '离线';
  const heartbeat = status.heartbeat_ts ?? status.last_heartbeat_ts;
  const age = heartbeat ? Math.max(0, Date.now() / 1000 - heartbeat) : null;
  const mode = status.mode || 'paper';
  return (
    <div className={`agent-card agent-${statusKey}`} style={{ '--agent-accent': role.color } as CSSProperties} title={status.detail || role.label}>
      <div className="agent-avatar"><LobsterAvatar accent={role.color} tool={role.tool} /></div>
      <div className="agent-card-body">
        <div className="agent-card-name">{role.label}</div>
        <div className="agent-card-meta"><i className="agent-status-dot" />{statusLabel}<span className="agent-mode">{mode === 'live' ? '实盘' : '模拟'}</span></div>
        <div className="agent-card-foot">{age == null ? '无心跳' : age < 2 ? '刚刚' : `${Math.floor(age)}s 前`} · 队列 {status.queue_depth ?? 0}</div>
      </div>
    </div>
  );
}

function LobsterAvatar({ accent, tool }: { accent: string; tool: string }) {
  return (
    <svg className="lobster-svg" viewBox="0 0 80 64" role="img" aria-label={`Q版龙虾：${tool}`}>
      <defs><linearGradient id={`lobster-${accent.replace('#', '')}`} x1="0" y1="0" x2="1" y2="1"><stop offset="0" stopColor="#ff786b"/><stop offset=".58" stopColor="#d73542"/><stop offset="1" stopColor="#761d37"/></linearGradient></defs>
      <ellipse cx="40" cy="55" rx="24" ry="5" fill="#000" opacity=".45" />
      <path d="M25 46c-7 4-13 4-18 1l5-5-7-5 12-2c2-8 8-13 16-15h14c8 2 14 7 16 15l12 2-7 5 5 5c-6 3-12 3-18-1-3 4-7 6-10 6s-7-2-10-6Z" fill={`url(#lobster-${accent.replace('#', '')})`} stroke="#ff9b82" strokeWidth="1.2" />
      <ellipse cx="40" cy="31" rx="15" ry="12" fill="#f05a55" stroke="#ff9b82" strokeWidth="1.2" />
      <circle cx="35" cy="29" r="3.4" fill="#fff"/><circle cx="45" cy="29" r="3.4" fill="#fff"/><circle cx="35" cy="29" r="1.5" fill="#111"/><circle cx="45" cy="29" r="1.5" fill="#111" />
      <path d="M36 36q4 3 8 0" fill="none" stroke="#57152d" strokeWidth="1.4" strokeLinecap="round" />
      <path d="M28 20 23 10M52 20l5-10" stroke="#ff9b82" strokeWidth="1.2" strokeLinecap="round"/><circle cx="23" cy="9" r="2" fill={accent}/><circle cx="57" cy="9" r="2" fill={accent}/>
      <path d="M14 28 5 20M66 28l9-8" stroke="#ff786b" strokeWidth="4" strokeLinecap="round"/><circle cx="5" cy="20" r="4" fill={accent}/><circle cx="75" cy="20" r="4" fill={accent}/>
      <rect x="34" y="3" width="12" height="7" rx="2" fill={accent} opacity=".9"/><text x="40" y="8.4" textAnchor="middle" fontSize="4.3" fill="#101010" fontWeight="700">{tool}</text>
    </svg>
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

function MarketPanelBody({ children }: { children: ReactNode }) {
  return <div className="market-panel-body">{children}</div>;
}

/**
 * Compact rolling spot-price chart used as a low-contrast panel background.
 * The API keeps a short trace per five-minute market; this component only
 * normalises the values and draws them, so it has no charting dependency.
 */
function VolatilityChart({
  asset,
  history,
  currentPrice,
}: {
  asset: 'BTC' | 'ETH';
  history?: PriceHistoryPoint[];
  currentPrice?: number;
}) {
  const points = (history || [])
    .filter((p) => Number.isFinite(p.price))
    .slice(-180);
  if (points.length === 0 && !Number.isFinite(currentPrice)) return null;

  if (points.length === 0 && Number.isFinite(currentPrice)) {
    points.push({ ts: Date.now() / 1000, price: Number(currentPrice) });
  }
  const values = points.map((p) => p.price);
  const min = Math.min(...values);
  const max = Math.max(...values);
  // Keep very small moves visible without making a flat feed fill the chart.
  const range = Math.max(max - min, Math.abs(max) * 0.00003, 0.000001);
  const pad = range * 0.16;
  const low = min - pad;
  const high = max + pad;
  const usable = Math.max(high - low, 0.000001);
  const coords = points.map((point, index) => {
    const x = points.length <= 1 ? 50 : (index / (points.length - 1)) * 100;
    const y = 28 - ((point.price - low) / usable) * 23;
    return [x, Math.max(2, Math.min(29, y))] as const;
  });
  const linePath = coords.map(([x, y], index) => `${index === 0 ? 'M' : 'L'}${x.toFixed(2)},${y.toFixed(2)}`).join(' ');
  const areaPath = `${linePath} L100,31 L0,31 Z`;
  const color = asset === 'BTC' ? '#f4b942' : '#4ec0ff';
  const gradientId = asset === 'BTC' ? 'btc-volatility-fill' : 'eth-volatility-fill';
  return (
    <div className="volatility-chart" aria-label={`${asset} 价格波动图`}>
      <svg viewBox="0 0 100 32" preserveAspectRatio="none" role="img" aria-hidden="true">
        <defs>
          <linearGradient id={gradientId} x1="0" x2="0" y1="0" y2="1">
            <stop offset="0%" stopColor={color} stopOpacity=".30" />
            <stop offset="100%" stopColor={color} stopOpacity=".02" />
          </linearGradient>
        </defs>
        <path d={areaPath} fill={`url(#${gradientId})`} />
        <path d={linePath} fill="none" stroke={color} strokeOpacity=".58" strokeWidth=".65" vectorEffect="non-scaling-stroke" />
        {coords.length > 0 && <circle cx={coords[coords.length - 1][0]} cy={coords[coords.length - 1][1]} r="1.05" fill={color} fillOpacity=".9" />}
      </svg>
    </div>
  );
}

function Panel({
  title, children, flex, contentStyle, onClick, ariaLabel,
}: {
  title: string;
  children: ReactNode;
  flex?: boolean;
  contentStyle?: CSSProperties;
  onClick?: () => void;
  ariaLabel?: string;
}) {
  return (
    <div
      style={{
      border: '1px solid var(--border)',
      background: 'var(--bg-panel)',
      display: 'flex',
      flexDirection: 'column',
      flex: flex ? 1 : '0 0 auto',
      minHeight: 0,
      cursor: onClick ? 'pointer' : undefined,
      ...((onClick ? { transition: 'border-color .12s ease' } : {})),
    }}
      onClick={onClick}
      role={onClick ? 'button' : undefined}
      tabIndex={onClick ? 0 : undefined}
      aria-label={ariaLabel}
      onKeyDown={onClick ? (event) => {
        if (event.key === 'Enter' || event.key === ' ') {
          event.preventDefault();
          onClick();
        }
      } : undefined}
    >
      <div style={panelTitleStyle}>{title}</div>
      <div style={{ padding: '8px 12px', flex: flex ? 1 : 'unset', overflow: 'auto', ...contentStyle }}>
        {children}
      </div>
    </div>
  );
}

function Row({
  k, v, hi, big, dim, mono, colored, relaxed, onClick, clickable, ariaLabel,
}: {
  k: string; v: ReactNode; hi?: boolean; big?: boolean;
  dim?: boolean; mono?: boolean; colored?: number | null; relaxed?: boolean;
  onClick?: () => void; clickable?: boolean; ariaLabel?: string;
}) {
  let color: string = hi ? 'var(--txt-hi)' : dim ? 'var(--txt-dim)' : 'var(--txt)';
  if (typeof colored === 'number') {
    color = colored > 0 ? 'var(--green)' : colored < 0 ? 'var(--red)' : color;
  }
  const isClickable = clickable || Boolean(onClick);
  return (
    <div
      style={{
        display: 'flex',
        justifyContent: 'space-between',
        gap: 8,
        padding: relaxed ? '3px 0' : '2px 0',
        cursor: isClickable ? 'pointer' : undefined,
        borderRadius: isClickable ? 2 : undefined,
      }}
      onClick={onClick}
      role={isClickable ? 'button' : undefined}
      tabIndex={isClickable ? 0 : undefined}
      aria-label={ariaLabel}
      onKeyDown={isClickable ? (event) => {
        if (event.key === 'Enter' || event.key === ' ') {
          event.preventDefault();
          onClick?.();
        }
      } : undefined}
    >
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

const shellStyle: CSSProperties = { height: '100vh', display: 'grid', gridTemplateRows: '34px auto minmax(0, 1fr) auto' };
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
