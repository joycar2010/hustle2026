import './ProductPanels.css';
import { PRODUCTS, ProductSettings, productName, type ProductAsset } from './ProductSettings';
import { ReviewPanel, EquityChart, formatReview, type ProductSnapshot } from './ProductPanels';
import { useEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import type { CSSProperties, ReactNode } from 'react';
import { cachedPnlDaily, controlLive, fetchConsensusHistory, fetchLlmSettings, fetchOrdersPage, fetchPnlDaily, fetchPolymarketFunding, fetchState, probeLlm, saveLlmSettings, testLlm, toggleLiveService } from './api';
import type { OrdersPage, OrdersPeriodFilter, PnlDailyPage } from './api';
import type {
  Book,
  Decision,
  AgentStatus,
  LlmSettings,
  LlmModelProfile,
  LlmUsageSnapshot,
  Order,
  PaperPosition,
  Position,
  PriceHistoryPoint,
  SlowLoopProposal,
  State,
} from './types';
import { fmtDur, fmtNum, fmtPct, fmtPx, fmtTime, fmtUsd } from './format';
import PaperComparison from './PaperComparison';
import './StrategyLayout.css';

// State snapshots include the paper comparison and accounting ledgers.  They
// can take several seconds while a large run is being compacted, so polling
// must remain available during the WebSocket handshake without piling up
// concurrent requests.
const POLL_MS = 3000;

export default function App() {
  const [state, setState] = useState<State | null>(null);
  const llmUsage: LlmUsageSnapshot | null = state?.llm?.usage ?? null;
  const [err, setErr] = useState<string | null>(null);
  const [now, setNow] = useState<number>(Date.now() / 1000);
  const [flash, setFlash] = useState<boolean>(false);
  const [lastFlashAt, setLastFlashAt] = useState<number>(0);
  const [showSettings, setShowSettings] = useState<boolean>(false);
  const [activeModal, setActiveModal] = useState<'positions' | 'orders' | 'orders-all' | 'pnl-history' | 'consensus-history' | 'decisions' | 'agent' | 'product' | 'wallet' | null>(null);
  const [activeProduct, setActiveProduct] = useState<ProductAsset>('BTC');
  const [decisionProduct, setDecisionProduct] = useState<ProductAsset>('BTC');
  const [reviewProduct, setReviewProduct] = useState<ProductAsset>('BTC');
  const [deskHistory, setDeskHistory] = useState(false);
  const [activeAgentRole, setActiveAgentRole] = useState<typeof OPENCLAW_ROLES[number] | null>(null);
  const [operatorToken, setOperatorToken] = useState<string>('');
  const [liveBusy, setLiveBusy] = useState<boolean>(false);
  const [liveMessage, setLiveMessage] = useState<string>('');
  const [serviceBusy, setServiceBusy] = useState<string | null>(null);
  const [transport, setTransport] = useState<'ws' | 'rest'>('rest');
  const [musicEnabled, setMusicEnabled] = useState(false);
  const musicRef = useRef<HTMLVideoElement | null>(null);
  const lastSeenOrderId = useRef<number>(-1);

  // State transport: WebSocket push first, REST polling as automatic
  // fallback (and during reconnect backoff).  Both carry the same payload.
  useEffect(() => {
    let cancelled = false;
    let ws: WebSocket | null = null;
    let pollId: number | null = null;
    let pollInFlight = false;
    let retry = 0;
    const applyState = (s: State) => {
      if (cancelled) return;
      setState(s);
      setErr(null);
      const orders = Array.isArray(s.orders) ? s.orders : [];
      const newest = orders.length ? orders[0].id : -1;
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
    };
    const startPolling = () => {
      if (pollId != null || cancelled) return;
      setTransport('rest');
      const tick = async () => {
        if (pollInFlight || cancelled) return;
        pollInFlight = true;
        try { applyState(await fetchState()); }
        catch (e) { if (!cancelled) setErr(String(e)); }
        finally { pollInFlight = false; }
      };
      tick();
      pollId = window.setInterval(tick, POLL_MS);
    };
    const stopPolling = () => {
      if (pollId != null) { window.clearInterval(pollId); pollId = null; }
    };
    let lastFrameAt = 0;
    // Start the fallback immediately.  A healthy WS will take ownership after
    // its first complete frame; this keeps a slow first snapshot from leaving
    // the dashboard on its empty initial state.
    startPolling();
    let receivedWsFrame = false;
    const connect = () => {
      if (cancelled) return;
      let socket: WebSocket;
      try {
        const proto = window.location.protocol === 'https:' ? 'wss' : 'ws';
        socket = new WebSocket(`${proto}://${window.location.host}/api/ws/state`);
      } catch { startPolling(); return; }
      ws = socket;
      socket.onopen = () => { retry = 0; lastFrameAt = Date.now(); setTransport('ws'); };
      socket.onmessage = (event) => {
        lastFrameAt = Date.now();
        try {
          applyState(JSON.parse(event.data));
          if (!receivedWsFrame || pollId != null) { receivedWsFrame = true; stopPolling(); setTransport('ws'); }
        } catch { /* skip bad frame */ }
      };
      socket.onerror = () => { try { socket.close(); } catch { /* already closed */ } };
      socket.onclose = () => {
        if (cancelled) return;
        startPolling(); // never leave the board blind while reconnecting
        const delay = Math.min(15000, 1000 * 2 ** Math.min(retry++, 4));
        window.setTimeout(connect, delay);
      };
    };
    // Watchdog: allow the expensive first snapshot to finish before declaring
    // a stalled socket.  Polling is already active until the first valid frame.
    const watchdog = window.setInterval(() => {
      if (ws && ws.readyState === WebSocket.OPEN && lastFrameAt && Date.now() - lastFrameAt > 10000) {
        try { ws.close(); } catch { /* noop */ }
      }
    }, 1000);
    connect();
    return () => { cancelled = true; window.clearInterval(watchdog); stopPolling(); try { ws?.close(); } catch { /* noop */ } };
  }, []);

  // Token telemetry now rides the WS state frame (state.llm.usage); the
  // dedicated REST poller was the last non-WS data path and is gone.

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
  // The design board reserves a narrow preview rail on wide screens, so use
  // the two-column terminal layout until there is enough room for all three
  // live data columns without squeezing the cards.
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

  const toggleMusic = async () => {
    const audio = musicRef.current;
    if (!audio) return;
    if (musicEnabled) {
      audio.pause();
      setMusicEnabled(false);
      return;
    }
    audio.volume = 0.18;
    audio.muted = false;
    try {
      // Reset the playhead before replaying. Calling load() here can cancel
      // Chromium's transient user activation and make the second click look
      // like an autoplay attempt.
      audio.pause();
      audio.currentTime = 0;
      const playPromise = audio.play();
      if (playPromise) await playPromise;
      setMusicEnabled(true);
    } catch {
      setLiveMessage('浏览器阻止自动播放，请再次点击音乐开关。');
    }
  };

  const m = state?.market;
  const tRem = m ? Math.max(0, m.end_ts - now) : null;
  const activeLive = serviceIsLive(state, 'BTC');
  const cash = activeLive ? state?.wallet.balance_pusd : state?.mode_split?.paper?.cash_usd;
  const openValue = activeLive ? state?.wallet.value_usd : state?.mode_split?.paper?.open_value_usd;
  const totalEquity = !activeLive && state?.mode_split?.paper?.equity_usd != null
    ? state.mode_split.paper.equity_usd : cash != null && Number.isFinite(cash) && openValue != null && Number.isFinite(openValue)
    ? cash + openValue
    : null;
  const pnl = state?.pnl;
  const winRate =
    pnl && pnl.wins != null && pnl.losses != null && pnl.wins + pnl.losses > 0
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
      ? `> ${fmtPx(state.config.min_net_edge)}; >=${fmtPx(state.config.high_price_edge_threshold)} BTC abs>=${fmtMoneyCompact(state.config.high_price_btc_delta_usd)}`
      : `> ${fmtPx(state?.config.min_net_edge)}`;
  const btcSignal = state?.btc_signal ?? null;
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
  const realizedCapFraction = state?.config.max_daily_realized_profit_fraction ?? state?.risk_snapshot?.max_daily_realized_profit_fraction ?? 0;
  const realizedCapUsd = state?.risk_snapshot?.daily_profit_target_usd ?? state?.config.max_daily_realized_profit_usd ?? 0;
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
      ? `${state.config.reversal_partial_exit_enabled ? `${state.config.reversal_partial_exit_window_sec}-${state.config.reversal_partial_exit_min_t_remaining_sec}s ${partialExitTrigger} ${state.config.reversal_partial_confirm_checks}x / ${fmtPct((state.config.reversal_partial_exit_fraction ?? 0) * 100)}; ` : ''}${state.config.reversal_exit_window_sec}-${state.config.reversal_normal_min_t_remaining_sec}s ${reversalTrigger} ${state.config.reversal_confirm_checks}x / ${fmtPct(state.config.reversal_exit_order_fraction * 100)}; ${state.config.reversal_late_exit_enabled ? `${state.config.reversal_late_window_sec}-${state.config.reversal_exit_min_t_remaining_sec}s held<${fmtPx(state.config.reversal_late_held_bid_threshold)} ${state.config.reversal_late_confirm_checks}x` : 'late off'}`
      : 'off';

  return (
    <>
      {/* Trade flash is a background notification; never let it cover or
          momentarily black out an open data modal. */}
      {flash && !activeModal && <div className="flash-screen" />}
      <div className="terminal-shell" style={shellStyle}>
        <TopBar
          time={now}
          botRunning={state?.bot_running ?? false}
          botMode={state?.active_lane ?? state?.bot_mode ?? 'stopped'}
          // `risk_state` can carry a diagnostic cursor/source reason while
          // the isolated Paper snapshot still explicitly permits entries.
          // Use the authoritative allow_entries bit for the Paper status pill;
          // live mode continues to use the strict risk state.
          riskState={state?.bot_mode === 'paper'
            ? state?.risk_snapshot?.allow_entries === false ? (state?.risk_state ?? 'BLOCKED') : 'OK'
            : (state?.risk_state ?? 'UNKNOWN')}
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
          musicEnabled={musicEnabled}
          onToggleMusic={toggleMusic}
          llmUsage={llmUsage || state?.llm?.usage || null}
          llmModels={state?.llm?.settings}
          accountLive={activeLive}
          profileName={state?.wallet?.polymarket_profile?.name || state?.wallet?.polymarket_profile?.pseudonym || state?.wallet?.user_name || state?.wallet?.profile?.name || state?.wallet?.profile?.pseudonym}
          portfolioValue={activeLive ? state?.wallet?.polymarket_profile?.portfolio_value_usd ?? state?.wallet?.polymarket_profile?.balance_usd ?? state?.wallet?.portfolio_value_usd ?? null : totalEquity}
        />

        <KpiStrip state={state} totalEquity={totalEquity} winRate={winRate} onWallet={() => setActiveModal('wallet')} onPositions={() => setActiveModal('positions')} onPnlHistory={() => setActiveModal('pnl-history')} />

        <PencilDashboard state={state} onPositions={() => setActiveModal('positions')} onDecisions={asset => { setDecisionProduct(asset); setActiveModal('decisions'); }} onOrdersAll={() => setActiveModal('orders-all')} onConsensusHistory={asset => {setReviewProduct(asset); setDeskHistory(false); setActiveModal('consensus-history');}} onAssetClick={(asset) => { setActiveProduct(asset); setActiveModal('product'); }} />

        <PaperComparison />

        <details className="legacy-details">
          <summary>详细监控与策略 / 实时数据</summary>
        <div className="terminal-grid" style={compactLayout ? compactGridStyle : gridStyle}>
          <div style={compactLayout ? compactLeftColStack : colStack}>
            <Panel title="钱包 / 资产">
              <Row k="钱包绑定" v={state?.wallet.binding?.status ?? (state?.wallet.deposit ? '已绑定' : '未绑定')} colored={state?.wallet.binding?.bound ? 1 : -1} relaxed />
              <Row k={activeLive ? 'pUSD 现金' : '模拟现金'} v={fmtUsd(cash)} hi relaxed />
              <Row
                k="持仓市值"
                v={fmtUsd(openValue)}
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

            <Panel title="风险 / 敞口">
              <RiskSnapshotPanel snapshot={state?.risk_snapshot} riskState={state?.risk_state} />
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
              <Row k="每日收益率上限" v={realizedCapFraction > 0 ? `${fmtPct(realizedCapFraction * 100)} · ${fmtUsd(realizedCapUsd)}` : (realizedCapUsd > 0 ? fmtUsd(realizedCapUsd) : '关闭')} mono />
            </Panel>
          </div>

          <div className="legacy-removed-column" style={compactLayout ? compactMiddleColStack : colStack}>
            <Panel title="组合曲线 // 成交量">
              <PortfolioChart state={state} />
            </Panel>
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

          </div>

          <div className="legacy-removed-column" style={compactLayout ? compactRightColStack : colStack}>
            <Panel title="概率预测 // 实时">
              <ProbabilityPanel state={state} />
            </Panel>
            <Panel title="决策日志 // 实时" flex>
              <DecisionsTable decisions={state?.decisions ?? []} />
            </Panel>
          </div>
        </div>
        </details>

        <BottomBar state={state} transport={transport} llmUsage={llmUsage || state?.llm?.usage || null} onAgentClick={(role) => { setActiveAgentRole(role); setActiveModal('agent'); }} />
        <ProposalToasts state={state} />
        <video ref={musicRef} src="/poluauto1.mp4" loop preload="auto" playsInline aria-hidden="true" tabIndex={-1} style={{ display: 'none' }} />
      </div>
      {showSettings && <SystemSettings onClose={() => setShowSettings(false)} />}
      {activeModal === 'wallet' && (
        activeLive ? <WalletActivityModal state={state} onClose={() => setActiveModal(null)} /> :
        <DataModal title="PAPER 模拟资金 / BTC 5M + BTC 15M + SOL 5M 合计账本" onClose={() => setActiveModal(null)}>
          <Row k="BTC 5M + BTC 15M + SOL 5M 模拟初始本金" v={fmtUsd(state?.mode_split?.paper?.capital_base_usd)} relaxed />
          {PRODUCTS.map(p => {
            const account = state?.products_by_key?.[p.key]?.account;
            return <Row key={p.key} k={p.label + ' 本金 / 现金 / 权益'} v={[account?.capital_base_usd, account?.cash_usd, account?.equity_usd].map(n => fmtUsd(n)).join(' / ')} relaxed />;
          })}
          <Row k="当前模拟现金" v={fmtUsd(state?.mode_split?.paper?.cash_usd)} relaxed />
          <Row k="模拟权益（持仓按成本估值）" v={fmtUsd(state?.mode_split?.paper?.equity_usd)} relaxed />
          <Row k="累计模拟费用" v={fmtUsd(state?.mode_split?.paper?.fees_usd)} relaxed />
          <div className="positions-sync-note">三个产品的独立模拟账本合计，不包含链上充值、提现或实盘资金；策略管理仍按各产品本金设置。</div>
        </DataModal>
      )}
      {activeModal === 'positions' && (
        <DataModal title={activeLive ? '实盘当前持仓 / 待结算' : 'PAPER 当前持仓与结算历史'} onClose={() => setActiveModal(null)}>
          {!activeLive && <>
            <div className="settled-position-note">模拟仓（未结算 paper 入场，合计 {fmtUsd((state?.paper_positions ?? []).reduce((sum, p) => sum + (p.notional_usd || 0), 0))}）：</div>
            <PaperPositionsTable rows={state?.paper_positions ?? []} />
            <div className="settled-position-note">已结算历史：{state?.paper_settled_count ?? state?.paper_settled_positions?.length ?? 0} 条。结算款已计入模拟现金，不属于待兑换，也不计入当前持仓。</div>
            <PaperSettledTable rows={state?.paper_settled_positions ?? []} />
          </>}
          {activeLive && <>
            <PositionsTable positions={state?.positions ?? []} />
          </>}
          {activeLive && !!state?.settled_positions?.length && <>
            <div className="settled-position-note">已结算 / 待赎回：{state.settled_positions.length} 条。它们不会计入当前风险敞口。</div>
            <PositionsTable positions={state.settled_positions} />
          </>}
        </DataModal>
      )}
      {activeModal === 'orders' && (
        <OrdersAllModal initialLane={serviceIsLive(state, 'BTC') ? 'live' : 'paper'} onClose={() => setActiveModal(null)} />
      )}
      {activeModal === 'decisions' && (
        <DataModal title="决策日志 // 详情" onClose={() => setActiveModal(null)}>
          <div className="product-tabs">{PRODUCTS.map(p => <button type="button" aria-pressed={decisionProduct === p.asset} key={p.key} onClick={() => setDecisionProduct(p.asset)}>{p.label}</button>)}</div>
          <DecisionsTable decisions={state?.products_by_key?.[PRODUCTS.find(p => p.asset === decisionProduct)!.key]?.decisions ?? []} />
        </DataModal>
      )}
      {activeModal === 'orders-all' && (
        <OrdersAllModal initialLane={serviceIsLive(state, 'BTC') ? 'live' : 'paper'} onClose={() => setActiveModal(null)} />
      )}
      {activeModal === 'pnl-history' && (
        <PnlHistoryModal initialLane={serviceIsLive(state, 'BTC') ? 'live' : 'paper'} onClose={() => setActiveModal(null)} />
      )}
      {activeModal === 'consensus-history' && (
        deskHistory ? <ConsensusHistoryModal onClose={() => setActiveModal(null)} /> :
        <DataModal title={productName(reviewProduct) + ' / 模型复核记录'} onClose={() => setActiveModal(null)}>
          <div className="product-tabs">{PRODUCTS.map(p => <button key={p.key} type="button" aria-pressed={reviewProduct === p.asset} onClick={() => setReviewProduct(p.asset)}>{p.label}</button>)}</div>
          {(() => {
            const data = state?.products_by_key?.[PRODUCTS.find(p => p.asset === reviewProduct)!.key];
            const rows = (data?.decisions || []).filter(record => record.model_review && (record.model_review.primary || record.model_review.secondary));
            if (!rows.length) return <Empty>此产品最近决策暂无模型复核记录</Empty>;
            return <table style={tableStyle}><thead><tr><Th>北京时间</Th><Th>市场</Th><Th>主模型</Th><Th>复核模型</Th></tr></thead><tbody>
              {rows.map(row => <tr key={row.id}><Td>{fmtDateTime(row.ts)}</Td><Td>{shortMarket(row.market_slug)}</Td><Td>{formatReview(row.model_review?.primary)}</Td><Td>{formatReview(row.model_review?.secondary)}</Td></tr>)}
            </tbody></table>;
          })()}
          <button type="button" className="settings-button" onClick={() => setDeskHistory(true)}>查看交易台历史</button>
        </DataModal>
      )}
      {activeModal === 'agent' && activeAgentRole && (
        <AgentDetailModal role={activeAgentRole} status={findAgentStatus(state?.agent_status, activeAgentRole.keys)} state={state} onClose={() => { setActiveModal(null); setActiveAgentRole(null); }} />
      )}
      {activeModal === 'product' && (
        <ProductDetailModal asset={activeProduct} state={state} onClose={() => setActiveModal(null)} />
      )}
    </>
  );
}

const PRICE_PERIODS = ['实时', '15分', '1时', '今日'] as const;

type SolSnapshot = {
  market?: { title?: string; market_slug?: string; start_ts?: number; end_ts?: number; remaining_sec?: number } | null;
  up?: Book | null;
  down?: Book | null;
  signal?: { current_price?: number; price_to_beat?: number; delta_usd?: number; signal_side?: string; decision_side?: string; hold_wr?: number; ts?: number } | null;
  decisions?: Array<{ id: number; ts: number; market_slug?: string; kind?: string; payload?: Record<string, unknown>; asset?: string; dry_run?: number }>;
};

function PencilDashboard({ state, onPositions, onDecisions, onOrdersAll, onConsensusHistory, onAssetClick }: { state: State | null; onPositions: () => void; onDecisions: (asset: ProductAsset) => void; onOrdersAll: () => void; onConsensusHistory: (asset: ProductAsset) => void; onAssetClick: (asset: ProductAsset) => void }) {
  const [pricePeriod, setPricePeriod] = useState<(typeof PRICE_PERIODS)[number]>('实时');
  const priceSince = pricePeriod === '实时' ? null
    : pricePeriod === '15分' ? Date.now() / 1000 - 900
    : pricePeriod === '1时' ? Date.now() / 1000 - 3600
    : (state?.pnl?.period_start_ts ?? null);
  const risk = state?.risk_snapshot;
  const riskIsLive = serviceIsLive(state, 'BTC');
  const [activeAsset, setActiveAsset] = useState<ProductAsset>('BTC');
  const [chartMode, setChartMode] = useState<'equity' | 'market'>('equity');
  const selected = PRODUCTS.find(p => p.asset === activeAsset)!;
  const product = state?.products_by_key?.[selected.key];
  const [solSnapshot, setSolSnapshot] = useState<SolSnapshot | null>(null);
  const [solHistory, setSolHistory] = useState<PriceHistoryPoint[]>([]);
  useEffect(() => {
    let cancelled = false;
    const load = () => fetch('/api/sol5m/snapshot', { cache: 'no-store' })
      .then((r) => r.ok ? r.json() : null)
      .then((value: SolSnapshot | null) => {
        if (cancelled || !value) return;
        setSolSnapshot(value);
        const signal = value.signal;
        if (signal?.current_price != null && Number.isFinite(Number(signal.current_price))) {
          const price = Number(signal.current_price);
          setSolHistory((prev) => {
            const point: PriceHistoryPoint = { ts: signal.ts || Date.now() / 1000, price, delta_usd: signal.delta_usd, market_slug: value.market?.market_slug };
            const next = [...prev.filter((item) => item.ts !== point.ts), point];
            return next.slice(-240);
          });
        }
      }).catch(() => { if (!cancelled) setSolSnapshot(null); });
    if (activeAsset !== 'SOL' || chartMode !== 'market') return;
    load();
    const timer = window.setInterval(load, 3000);
    return () => { cancelled = true; window.clearInterval(timer); };
  }, [activeAsset, chartMode]);
  void onPositions;
  return <div className="pencil-board-main">
    <div className="pencil-analysis-grid">
      <section className="pencil-panel pencil-chart-panel">
        <div className="pencil-panel-title"><span>{chartMode === 'equity' ? '组合净值 · 成本估值' : '行情'} / {selected.label} {activeAsset === 'BTC' && serviceIsLive(state, 'BTC') ? 'LIVE' : 'PAPER'}</span>
          <span className="pencil-period" role="tablist" aria-label="时间段">
            {PRODUCTS.map(p => <button key={p.key} type="button" className={activeAsset === p.asset ? 'active' : ''} onClick={() => { setActiveAsset(p.asset); if (p.key === 'btc15m') setChartMode('equity'); }}>{p.label}</button>)}
            {activeAsset !== 'BTC15M' && <button type="button" onClick={() => setChartMode(chartMode === 'equity' ? 'market' : 'equity')}>{chartMode === 'equity' ? '查看行情' : '查看净值'}</button>}
            {PRICE_PERIODS.map((p) => (
              <button key={p} type="button"
                className={pricePeriod === p ? 'active' : ''}
                onClick={() => setPricePeriod(p)}>
                {p}
              </button>
            ))}
          </span>
        </div>
        {chartMode === 'equity' || activeAsset === 'BTC15M' ? <EquityChart key={activeAsset} value={product?.account?.equity_usd} now={state?.now} since={priceSince} /> : <PortfolioChart state={state} asset={activeAsset} history={activeAsset === 'SOL' ? solHistory : state?.btc_price_history} solSnapshot={activeAsset === 'SOL' ? solSnapshot : null} sinceTs={priceSince} />}
      </section>
      <div className="pencil-side-stack">
        <section className="pencil-panel pencil-orders-panel pencil-decisions-clickable" onClick={() => onDecisions(activeAsset)} role="button" tabIndex={0} onKeyDown={(event) => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); onDecisions(activeAsset); } }}>
          <div className="pencil-panel-title">决策日志 // 实时 · {selected.label}</div>
          <DecisionLogPreview state={state} decisions={product?.decisions ?? []} />
        </section>
        <section className="pencil-panel pencil-prob-panel"><div className="pencil-panel-title">概率预测 / 双模型复核 · {selected.label}</div><ReviewPanel product={product} /></section>
      </div>
    </div>
    <div className="pencil-risk-row">
      <PencilMetric label={selected.label + ' 日亏损熔断'} value={product?.risk?.available
        ? fmtUsd(Math.max(0, -(product.risk.today_net_pnl_usd || 0))) + ' / ' + fmtUsd(product.risk.daily_loss_limit_usd) + ' · ' + zhText(product.risk.state) : '—'} tone="amber" mode="paper" />
      <PencilMetric label={riskIsLive ? '总敞口' : '总敞口 · 持仓成本'} value={fmtUsd(riskIsLive ? risk?.position_value_usd : state?.mode_split?.paper?.open_value_usd)} tone="amber" mode={riskIsLive ? 'live' : 'paper'} />
      <PencilMetric label={selected.label + ' 滑点容差 · 订单统计'} value={(product?.config?.paper_slippage_ticks ?? '—') + ' tick · 今 ' + (product?.today_order_count ?? '—') + ' / 累 ' + (product?.order_count ?? '—')} tone="green" />
      <PencilMetric label="全部订单" value={String(state?.orders_total ?? '--')} tone="blue" onClick={onOrdersAll} />
      <PencilMetric label={selected.label + ' 模型复核'} value={product?.model_review?.available ? '已记录' : '暂无复核记录'} tone="purple" onClick={() => onConsensusHistory(activeAsset)} />
    </div>
    {riskIsLive && <div className="live-risk-equity-note">
      <span>实盘日风控 · 日初权益 {fmtUsd(risk?.day_start_equity_usd ?? risk?.capital_base_usd)} · 当前权益 {fmtUsd(risk?.equity_usd)} · 估值时间 {fmtDateTime(risk?.data_as_of)}</span>
      <span>风控包含全部链上持仓及历史待兑换尾仓；OPEN 持仓列表可能过滤小额或已结算记录。</span>
    </div>}
    <div className="pencil-assets-row product-assets">{PRODUCTS.map(p => {
      const summary = state?.product_paper?.[p.asset];
      const snapshot = state?.products_by_key?.[p.key];
      const pnl = summary?.cumulative_net_pnl_usd;
      return <button type="button" key={p.key} className="pencil-asset-card pencil-asset-card-clickable" onClick={() => onAssetClick(p.asset)}>
        <span>{p.label} · PAPER</span>
        <b className={pnl == null ? '' : pnl >= 0 ? 'asset-profit-positive' : 'asset-profit-negative'}>{fmtSignedUsd(pnl)}</b>
        <small>{snapshot == null ? '状态待同步' : snapshot.paper_enabled ? 'Worker 运行' : 'Worker 停止'} · 待结算 {summary?.pending ?? '—'}</small>
        <small className="product-health-line" title={productHealthTitle(snapshot?.health)}>{productHealthLabel(snapshot?.health)}</small>
        <small>累计胜率 {fmtPct(summary?.cumulative_win_rate_pct)} · {summary?.cumulative_wins ?? '—'} 胜 / {summary?.cumulative_losses ?? '—'} 负</small>
      </button>;
    })}</div>
  </div>;
}

function serviceIsLive(state: State | null, asset: ProductAsset) {
  if (asset === 'BTC' && state?.active_lane) return state.active_lane === 'live';
  const info = state?.service_modes?.[asset];
  if (info?.live_enabled != null) return info.live_enabled === true;
  if (info?.mode) return info.mode.toLowerCase() === 'live';
  return state?.bot_mode === 'live' && asset === 'BTC';
}

function fmtSignedUsd(value: number | null | undefined) {
  if (value == null || !Number.isFinite(value)) return '—';
  if (!Number.isFinite(value) || Math.abs(value) < 0.005) return '$0.00';
  return `${value >= 0 ? '+' : '-'}$${Math.abs(value).toFixed(2)}`;
}

function fmtAge(seconds: number | null | undefined): string {
  if (seconds == null || !Number.isFinite(seconds)) return '--';
  const value = Math.max(0, Math.round(seconds));
  if (value < 60) return `${value}s`;
  if (value < 3600) return `${Math.floor(value / 60)}m ${value % 60}s`;
  return `${Math.floor(value / 3600)}h ${Math.floor((value % 3600) / 60)}m`;
}

function productHealthLabel(health: ProductSnapshot['health']): string {
  if (!health) return '健康状态待同步';
  const worker = health.worker_active === false ? 'Worker 停止' : health.worker_state === 'active' || health.worker_active ? 'Worker 运行' : 'Worker 状态未知';
  const freshness = health.freshness === 'fresh' ? '行情 fresh' : health.freshness === 'stale' ? '行情过期' : '行情待确认';
  const decision = health.last_decision_age_sec == null ? '决策 --' : `决策 ${fmtAge(health.last_decision_age_sec)}`;
  const entry = health.allow_entries === true ? '允许开仓' : health.allow_entries === false ? '开仓已阻断' : '开仓状态未知';
  const errors = health.tick_error_count ? ` · tick 错误 ${health.tick_error_count}` : '';
  return `${worker} · ${decision} · ${freshness} · ${entry}${errors}`;
}

function productHealthTitle(health: ProductSnapshot['health']): string {
  if (!health) return '等待产品健康数据';
  const reason = health.circuit_reason ? `风控原因：${health.circuit_reason}` : '暂无风控阻断原因';
  const tick = health.last_successful_tick_ts ? `最近成功行情 ${fmtDateTime(health.last_successful_tick_ts)}` : '最近成功行情未知';
  const pid = health.worker_pid ? `PID ${health.worker_pid}` : 'PID 未知';
  return `${pid} · ${tick} · ${reason}`;
}

function fmtDateTime(ts: number | null | undefined): string {
  if (ts == null || !Number.isFinite(ts)) return '--';
  return new Date(ts * 1000).toLocaleString('zh-CN', { hour12: false, timeZone: 'Asia/Shanghai' });
}

function finiteValue(value: unknown): number | null {
  if (value == null || value === '' || typeof value === 'boolean') return null;
  const number = typeof value === 'number' ? value : Number(value);
  return Number.isFinite(number) ? number : null;
}

function sumNullable(values: Array<number | null | undefined>): number | null {
  if (!values.length || values.some((value) => value == null || !Number.isFinite(value))) return null;
  return values.reduce<number>((sum, value) => sum + (value as number), 0);
}

function dailyEconomic(row: Record<string, any> | null | undefined): number | null {
  if (!row) return null;
  return finiteValue(row.net_pnl_usd ?? row.economic_pnl_usd ?? row.pnl_usd ?? row.realized_usd ?? row.realized_pnl_usd);
}

function dailyTrade(row: Record<string, any> | null | undefined): number | null {
  return row ? finiteValue(row.trade_pnl_usd ?? row.gross_pnl_usd ?? row.pnl_usd) : null;
}

function dailyFees(row: Record<string, any> | null | undefined): number | null {
  const fee = row ? finiteValue(row.fees_usd ?? row.fee_usd) : null;
  return fee == null ? null : -Math.abs(fee);
}

function dailyRebates(row: Record<string, any> | null | undefined): number | null {
  if (!row) return null;
  return finiteValue(row.rebates_usd ?? row.rebate_usd) ?? sumNullable([finiteValue(row.maker_rebate_usd), finiteValue(row.taker_rebate_usd), finiteValue(row.fees_refunded_usd)]);
}

function activityAmount(order: Order): number | null {
  const direct = finiteValue(order.usdc_size);
  if (direct != null) return Math.abs(direct);
  const size = finiteValue(order.size);
  const price = finiteValue(order.price);
  return size != null && price != null ? Math.abs(size * price) : null;
}

function activityCashflow(order: Order): number | null {
  const supplied = finiteValue(order.cashflow_usd);
  if (supplied != null) return supplied;
  const amount = activityAmount(order);
  if (amount == null) return null;
  const kind = String(order.activity_type || '').toUpperCase();
  if (kind === 'REDEEM' || kind === 'MERGE') return amount;
  if (kind === 'SPLIT') return -amount;
  if (kind !== 'TRADE') return null;
  const side = String(order.side || '').toUpperCase();
  if (side === 'SELL') return amount;
  if (side === 'BUY') return -amount;
  return null;
}

/** Derive per-market performance from settled order outcomes. Unresolved orders
 * intentionally remain neutral so the card never presents an invented PnL.
 * `paperOnly` selects the dry-run lane so paper and live results never mix. */
function ProductDetailModal({ asset, state, onClose }: { asset: ProductAsset; state: State | null; onClose: () => void }) {
  const [paperOrders, setPaperOrders] = useState<Order[]>([]);
  const [liveOrders, setLiveOrders] = useState<Order[]>([]);
  const [days, setDays] = useState<Array<Record<string, any>>>([]);
  const [pnlSnapshot, setPnlSnapshot] = useState<PnlDailyPage | null>(null);
  const [loading, setLoading] = useState(true);
  const [refresh, setRefresh] = useState(0);
  const activeLive = serviceIsLive(state, asset);
  const label = productName(asset);
  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    Promise.all([
      fetchOrdersPage(0, 30, activeLive ? 'live' : 'paper', asset),
      fetchPnlDaily(activeLive ? 'live' : 'paper', 0, 365, asset),
    ]).then(([ordersPage, pnlPage]) => {
      if (!cancelled) { setPaperOrders(activeLive ? [] : ordersPage.rows || []); setLiveOrders(activeLive ? ordersPage.rows || [] : []); setDays(pnlPage.rows || []); setPnlSnapshot(pnlPage); }
    }).catch(() => {
      if (!cancelled) { setPaperOrders([]); setLiveOrders([]); setDays([]); setPnlSnapshot(null); }
    }).finally(() => { if (!cancelled) setLoading(false); });
    const timer = window.setInterval(() => setRefresh((value) => value + 1), activeLive ? 15000 : 3000);
    return () => { cancelled = true; window.clearInterval(timer); };
  }, [asset, activeLive, refresh]);
  const ownSummary = state?.product_paper?.[asset];
  const assetSnapshot = pnlSnapshot?.asset?.toUpperCase() === asset ? pnlSnapshot : null;
  const cumulative = assetSnapshot?.cumulative_summary;
  const ownCumulative = state?.mode_split?.paper?.cumulative_by_asset?.[asset];
  const paper = {
    realized_usd: ownSummary?.cumulative_net_pnl_usd ?? ownSummary?.cumulative_realized_usd ?? dailyEconomic(cumulative) ?? ownCumulative?.realized_usd,
    wins: ownSummary?.cumulative_wins ?? cumulative?.wins ?? ownCumulative?.wins,
    losses: ownSummary?.cumulative_losses ?? cumulative?.losses ?? ownCumulative?.losses,
  };
  const live = state?.mode_split?.live?.cumulative_by_asset?.[asset] || {};
  const ownToday = state?.mode_split?.paper?.by_asset?.[asset];
  const today = {
    realized_usd: ownSummary?.today_net_pnl_usd ?? ownSummary?.today_realized_usd ?? dailyEconomic(assetSnapshot?.today_summary) ?? ownToday?.realized_usd,
    pending: ownSummary?.pending ?? ownToday?.pending,
  };
  const paperTotal = (paper.wins ?? 0) + (paper.losses ?? 0);
  const liveTotal = (live.wins ?? 0) + (live.losses ?? 0);
  return <DataModal title={`${label} / ${activeLive ? '实盘' : 'PAPER 模拟'}数据`} onClose={onClose}>
    <div className="product-detail-grid">
      {!activeLive && <div className="product-detail-lane product-detail-paper"><h3>{label} · PAPER / 独立产品账本</h3><Row k="累计净盈亏" v={fmtSignedUsd(paper.realized_usd)} colored={paper.realized_usd} relaxed /><Row k="累计胜率" v={paperTotal ? fmtPct((paper.wins ?? 0) / paperTotal * 100) : '—'} relaxed /><Row k="胜 / 负" v={`${paper.wins ?? '—'} / ${paper.losses ?? '—'}`} relaxed /><Row k="今日净盈亏" v={fmtSignedUsd(today.realized_usd)} colored={today.realized_usd} relaxed /><Row k="当前待结算" v={String(today.pending ?? '—')} relaxed /></div>}
      {activeLive && <div className="product-detail-lane product-detail-live"><h3>{label} · LIVE</h3><Row k="累计经济盈亏" v={fmtSignedUsd(live.realized_usd)} colored={live.realized_usd} relaxed /><Row k="累计胜率" v={liveTotal ? fmtPct((live.wins ?? 0) / liveTotal * 100) : '--'} relaxed /><Row k="胜 / 负" v={`${live.wins ?? '—'} / ${live.losses ?? '—'}`} relaxed /><Row k="实盘资格" v={state?.service_modes?.[asset]?.live_enabled ? '已开启' : '未开启'} relaxed /><Row k="当前订单" v="链上真实成交 / 兑换" relaxed /></div>}
    </div>
    {!activeLive && <div className="product-detail-section"><h3>{label} · Paper 最近记录</h3>{loading ? <Empty>加载中…</Empty> : paperOrders.length ? <OrdersTable orders={paperOrders.slice(0, 12)} /> : <Empty>暂无 Paper 订单；历史汇总仍以独立账本为准。</Empty>}</div>}
    {activeLive && <div className="product-detail-section"><h3>{label} · Live 最近记录</h3>{loading ? <Empty>加载中…</Empty> : liveOrders.length ? <OrdersTable orders={liveOrders.slice(0, 12)} /> : <Empty>暂无 Live 订单或实盘尚未开启。</Empty>}</div>}
    <div className="product-detail-section"><h3>{label} · {activeLive ? '实盘' : 'Paper'} 每日净盈亏</h3>{days.length ? <div className="product-daily-list">{days.slice(0, 14).map((row) => <div key={row.day}><span>{row.day}</span><b className={(dailyEconomic(row) ?? 0) >= 0 ? 'asset-profit-positive' : 'asset-profit-negative'}>{fmtSignedUsd(dailyEconomic(row))}</b><small>{fmtPct(row.return_pct ?? (row.capital_base_usd > 0 && dailyEconomic(row) != null ? dailyEconomic(row)! / row.capital_base_usd * 100 : null))} · {row.wins} 胜 / {row.losses} 负</small></div>)}</div> : <Empty>暂无已结算记录</Empty>}</div>
  </DataModal>;
}

function DecisionLogPreview({ state, decisions: overrideDecisions }: { state: State | null; decisions?: Decision[] }) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const [visibleRows, setVisibleRows] = useState(3);
  const [windowStart, setWindowStart] = useState(0);
  const [isUpdating, setIsUpdating] = useState(false);
  const allDecisions = overrideDecisions || state?.decisions || [];
  const latestDecisionId = allDecisions.length ? allDecisions[0].id : null;
  useEffect(() => {
    const node = containerRef.current;
    if (!node) return;
    const update = () => setVisibleRows(Math.max(1, Math.floor((node.clientHeight - 8) / 26)));
    update();
    const observer = new ResizeObserver(update);
    observer.observe(node);
    return () => observer.disconnect();
  }, []);
  // A new decision always returns the feed to the newest row. The timed
  // window then advances one row at a time so older activity remains
  // inspectable without adding a second scrollbar to the dashboard panel.
  useEffect(() => {
    setWindowStart(0);
    if (latestDecisionId == null) return undefined;
    setIsUpdating(true);
    const timeout = window.setTimeout(() => setIsUpdating(false), 500);
    return () => window.clearTimeout(timeout);
  }, [latestDecisionId]);
  useEffect(() => {
    const maxStart = Math.max(0, allDecisions.length - visibleRows);
    if (maxStart <= 0) return undefined;
    const interval = window.setInterval(() => {
      setWindowStart((current) => current >= maxStart ? 0 : current + 1);
    }, 4200);
    return () => window.clearInterval(interval);
  }, [allDecisions.length, visibleRows]);
  const maxStart = Math.max(0, allDecisions.length - visibleRows);
  const start = Math.min(windowStart, maxStart);
  const decisions = allDecisions.slice(start, start + visibleRows);
  // The worker legitimately goes quiet for ~10-20s while five-minute windows
  // roll over (no market -> no decisions); label the pause honestly so a
  // static list reads as "between windows", not as a frozen feed.
  const latestTs = allDecisions[0]?.ts ?? null;
  const windowGap = latestTs != null && Date.now() / 1000 - latestTs > 8;
  return <div className={`decision-log-preview${isUpdating ? ' decision-log-updated' : ''}`} ref={containerRef} aria-live="polite">
    {windowGap && <div className="decision-log-row decision-log-gap"><span>⏳ 窗口切换中</span><small>等待下一个 5 分钟市场的新决策…</small><b>PAPER</b></div>}
    {decisions.map((d) => <div className="decision-log-row" key={`${d.id}-${start}`}><span>{d.asset || '--'} · {zhText(d.action)}</span><small>{zhText(d.reason).slice(0, 36)}</small><b>{d.dry_run ? 'PAPER' : 'LIVE'}</b></div>)}
    {!decisions.length && <Empty>暂无实时决策</Empty>}
  </div>;
}

function PencilMetric({ label, value, tone, mode, onClick }: { label: string; value: string; tone: 'green' | 'amber' | 'blue' | 'purple'; mode?: KpiMode; onClick?: () => void }) {
  const compact = label.startsWith('滑点容差');
  return <div className={`pencil-metric pencil-tone-${tone}${compact ? ' pencil-metric-slippage' : ''}${onClick ? ' pencil-metric-clickable' : ''}`} onClick={onClick} role={onClick ? 'button' : undefined} tabIndex={onClick ? 0 : undefined} onKeyDown={onClick ? (event) => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); onClick(); } } : undefined}>{mode && <ModeChip mode={mode} />}<span className="pencil-metric-label">{label}</span><b className="pencil-metric-value">{value}</b></div>;
}

const DISMISSED_PROPOSALS_KEY = 'polyauto-dismissed-proposals';

function proposalId(p: SlowLoopProposal): string {
  return `${p.key}:${String(p.proposed)}:${p.ts}`;
}

/** Binance-style bottom-right toast stack surfacing PENDING_HUMAN agent
 * proposals.  Display-only: approval still happens outside the UI, so the
 * card says where; dismissing just hides the card on this browser. */
function ProposalToasts({ state }: { state: State | null }) {
  const [dismissed, setDismissed] = useState<string[]>(() => {
    try { return JSON.parse(localStorage.getItem(DISMISSED_PROPOSALS_KEY) || '[]'); }
    catch { return []; }
  });
  const proposals = (state?.slow_loop?.proposals ?? [])
    .filter((p) => !dismissed.includes(proposalId(p)))
    .slice(0, 3);
  const dismiss = (id: string) => {
    setDismissed((current) => {
      const next = [...current.filter((x) => x !== id), id].slice(-60);
      try { localStorage.setItem(DISMISSED_PROPOSALS_KEY, JSON.stringify(next)); } catch { /* per-browser convenience only */ }
      return next;
    });
  };
  if (!proposals.length) return null;
  return (
    <div className="proposal-toasts" aria-live="polite" aria-label="待审批参数提案">
      {proposals.map((p) => {
        const id = proposalId(p);
        const conf = p.confidence === 'high' ? '高置信' : p.confidence === 'medium' ? '中置信' : '低置信';
        return (
          <div className={`proposal-toast proposal-conf-${p.confidence}`} key={id}>
            <div className="proposal-toast-head">
              <span className="proposal-toast-title">⚙ 参数提案 · {p.key}</span>
              <i className={`proposal-conf-chip chip-${p.confidence}`}>{conf}</i>
              <button type="button" className="proposal-toast-close" aria-label="关闭" onClick={() => dismiss(id)}>×</button>
            </div>
            <div className="proposal-toast-change">
              <code>{String(p.current)}</code>
              <span className="proposal-arrow">→</span>
              <code className="proposal-target">{String(p.proposed)}</code>
            </div>
            <div className="proposal-toast-reason" title={p.reason}>{p.reason}</div>
            <div className="proposal-toast-foot">
              <span>{p.source_agent} · {fmtTime(p.ts)} · 待人工审批</span>
              <button type="button" className="proposal-toast-later" onClick={() => dismiss(id)}>稍后处理</button>
            </div>
          </div>
        );
      })}
      <div className="proposal-toast-hint">审批入口：agents/out/proposals.jsonl（不会自动应用）</div>
    </div>
  );
}

function PortfolioChart({ state, asset = 'BTC', history, solSnapshot, sinceTs }: { state: State | null; asset?: 'BTC' | 'SOL' | 'ETH'; history?: PriceHistoryPoint[]; solSnapshot?: SolSnapshot | null; sinceTs?: number | null }) {
  const base = history || (asset === 'ETH' ? state?.eth_price_history : state?.btc_price_history) || [];
  // Period filter: keep the window when it still draws a line; otherwise
  // fall back to whatever history memory holds (honest about coverage).
  let pts = base;
  if (sinceTs) {
    const filtered = base.filter((p) => p.ts >= sinceTs);
    if (filtered.length >= 2) pts = filtered;
  }
  const points = pts.slice(sinceTs ? -240 : -48);
  if (points.length < 2) return <Empty>等待组合行情数据…</Empty>;
  const prices = points.map((p) => p.price); const lo = Math.min(...prices); const hi = Math.max(...prices); const span = Math.max(hi - lo, 1);
  const line = points.map((p, i) => `${(i / (points.length - 1)) * 100},${100 - ((p.price - lo) / span) * 82 - 9}`).join(' ');
  const signal = asset === 'SOL' ? solSnapshot?.signal : asset === 'ETH' ? state?.eth_signal : state?.btc_signal;
  const market = asset === 'SOL' ? solSnapshot?.market : asset === 'ETH' ? state?.eth_market : state?.market;
  const bookUp = asset === 'SOL' ? solSnapshot?.up : asset === 'ETH' ? state?.eth_book_up : state?.book_up;
  const bookDown = asset === 'SOL' ? solSnapshot?.down : asset === 'ETH' ? state?.eth_book_down : state?.book_down;
  const delta = signal?.delta_usd;
  // Direction word mirrors the worker's own signal side; fall back to the
  // delta sign so the label never contradicts the number next to it.
  const sideWord = signal ? (signal.signal_side === 'UP' ? '上涨' : signal.signal_side === 'DOWN' ? '下跌' : delta != null && delta !== 0 ? (delta > 0 ? '上涨' : '下跌') : '持平') : null;
  const tRem = market?.end_ts != null ? Math.max(0, market.end_ts - Date.now() / 1000) : null;
  const quote = (side: '上涨' | '下跌', book: Book | null | undefined) => (
    <span className="chart-book-row">
      <i className={side === '上涨' ? 'chart-side-up' : 'chart-side-down'}>{side}</i>
      买一 <b className="chart-book-bid">{book?.best_bid == null ? '--' : fmtPx(book.best_bid)}</b>×{book?.bid_size == null ? '--' : fmtNum(book.bid_size, 0)}
      <em>·</em>
      卖一 <b className="chart-book-ask">{book?.best_ask == null ? '--' : fmtPx(book.best_ask)}</b>×{book?.ask_size == null ? '--' : fmtNum(book.ask_size, 0)}
    </span>
  );
  return <div className="portfolio-chart" aria-label={`${asset}组合曲线和成交量`}>
    <svg viewBox="0 0 100 100" preserveAspectRatio="none"><polyline points={line} fill="none" stroke="var(--green)" strokeWidth="1.2" vectorEffect="non-scaling-stroke" /></svg>
    <div className="volume-bars" aria-label="实时价格变动"><span className="sr-only">绿色为上涨，红色为下跌</span>{points.slice(-24).map((p, i) => { const pnl = Number(p.delta_usd || 0); return <i key={`${p.ts}-${i}`} className={pnl >= 0 ? 'pnl-positive' : 'pnl-negative'} title={`${pnl >= 0 ? '上涨' : '下跌'} ${fmtUsd(Math.abs(pnl))}`} style={{ height: `${Math.max(8, Math.min(100, Math.abs(pnl) * 4 + 8))}%` }} />; })}</div>
    <div className="portfolio-chart-overlay" aria-label={`${asset}实时行情摘要`}>
      <span>{asset} 价格差 <b className={delta != null && delta >= 0 ? 'kpi-positive' : 'kpi-negative'}>{delta == null ? '--' : `${delta >= 0 ? '+' : ''}${fmtUsd(delta)}`}</b>{sideWord && <i className={`chart-side-word ${sideWord === '上涨' ? 'chart-side-up' : sideWord === '下跌' ? 'chart-side-down' : ''}`}>{sideWord}</i>}</span>
      <span>TWAP / 基准 <b>{signal ? `${fmtUsd(signal.current_price)} / ${fmtUsd(signal.price_to_beat)}` : '--'}</b></span>
      <span>倒计时 <b className={tRem != null && tRem < 60 ? 'chart-countdown-hot' : ''}>{tRem == null ? '--' : fmtDur(tRem)}</b></span>
      {quote('上涨', bookUp)}
      {quote('下跌', bookDown)}
    </div>
    <div className="chart-caption"><span>低 {fmtUsd(lo)}</span><span>{asset} 组合走势</span><span>高 {fmtUsd(hi)}</span></div>
  </div>;
}

function ProbabilityPanel({ state, asset = 'BTC', solSnapshot }: { state: State | null; asset?: 'BTC' | 'SOL'; solSnapshot?: SolSnapshot | null }) {
  const signal = asset === 'SOL' ? solSnapshot?.signal : state?.btc_signal;
  const solSignal = asset === 'SOL' ? solSnapshot?.signal : null;
  const delta = Number(signal?.delta_usd ?? 0);
  const hold = Number(solSignal?.hold_wr ?? 0.5);
  const decisionSide = solSignal?.decision_side || (state?.btc_signal?.signal_side ?? 'FLAT');
  const directional = decisionSide === 'UP' ? hold : decisionSide === 'DOWN' ? 1 - hold : Math.max(0, Math.min(1, 0.5 + delta / 200));
  const rows = [
    [`${asset} 上涨`, signal ? directional : null, '#f4b942'],
    [`${asset} 下跌`, signal ? 1 - directional : null, '#f05b68'],
  ] as const;
  return <div className="probability-panel">{rows.map(([label, probability, color]) => <div className="probability-row" key={label}><span>{label}</span><div className="probability-track"><i style={{ width: `${(probability ?? 0) * 100}%`, background: color }} /></div><b>{probability == null ? '--' : fmtPct(probability * 100)}</b></div>)}</div>;
}

type KpiMode = 'paper' | 'live' | 'chain';

function ModeChip({ mode }: { mode: KpiMode }) {
  const label = mode === 'live' ? '实盘' : mode === 'chain' ? '链上' : '模拟';
  return <i className={`kpi-mode kpi-mode-${mode}`}>{label}</i>;
}

function KpiStrip({ state, totalEquity, winRate, onWallet, onPositions, onPnlHistory }: { state: State | null; totalEquity: number | null; winRate: number | null; onWallet: () => void; onPositions: () => void; onPnlHistory: () => void }) {
  void winRate; // cumulative win rate is read from the lane ledger below
  const activeMode: 'paper' | 'live' = serviceIsLive(state, 'BTC') ? 'live' : 'paper';
  const paperLane = state?.mode_split?.paper;
  const liveLane = state?.mode_split?.live;
  const pnl = activeMode === 'paper' ? paperLane?.realized_usd ?? null : state?.pnl?.realized_usd ?? null;
  const cumulative = state?.mode_split?.[activeMode]?.cumulative_realized_usd ?? pnl;
  const cumulativeWins = state?.mode_split?.[activeMode]?.cumulative_wins ?? (activeMode === 'live' ? state?.pnl?.wins : undefined);
  const cumulativeLosses = state?.mode_split?.[activeMode]?.cumulative_losses ?? (activeMode === 'live' ? state?.pnl?.losses : undefined);
  const chain = state?.chain_holdings;
  const chainSummary = state?.chain_snapshot?.live_summary ?? state?.wallet?.polymarket_profile?.live_summary;
  const chainSnapshot = state?.chain_snapshot;
  const chainAccountEnabled = activeMode === 'live';
  const chainAvailable = chainAccountEnabled && chainSummary?.available === true;
  // Keep the source indicator in secondary copy while the KPI badge follows the active execution lane.
  const kpiMode: KpiMode = activeMode;
  const chainPendingCount = chainAccountEnabled ? chainAvailable ? chain?.pending_count : state?.pnl?.pending : paperLane?.pending;
  const chainRedeemableCount = chainAvailable ? (chain?.redeemable_count ?? 0) : 0;
  const chainPendingValue = chainAvailable ? (chain?.pending_value_usd ?? 0) : null;
  const chainRedeemableValue = chainAvailable ? (chain?.redeemable_value_usd ?? 0) : null;
  const displayCumulative = chainAccountEnabled ? (chainSummary?.economic_usd ?? null) : cumulative;
  const displayToday = chainAccountEnabled ? (chainSummary?.today_economic_pnl_usd ?? null) : paperLane?.daily_economic_pnl_usd ?? pnl;
  const todayWins = chainAccountEnabled ? chainSummary?.today_wins : paperLane?.wins;
  const todayLosses = chainAccountEnabled ? chainSummary?.today_losses : paperLane?.losses;
  const displayCumulativeWins = chainAccountEnabled ? chainSummary?.wins : cumulativeWins;
  const displayCumulativeLosses = chainAccountEnabled ? chainSummary?.losses : cumulativeLosses;
  const todayTotal = todayWins != null && todayLosses != null ? todayWins + todayLosses : null;
  // Return%% divides by the ACTIVE lane's capital base (paper equity for the
  // paper lane -- the same number the worker's risk gate uses), never by the
  // chain balance while simulating.
  const capitalBase = state?.mode_split?.[activeMode]?.capital_base_usd ?? (chainAccountEnabled ? totalEquity : null);
  // The headline cards are explicitly "today" metrics.  The backend applies
  // the Asia/Shanghai day boundary; use that active lane value here instead
  // of the lifetime cumulative ledger used by the detail views.
  const returnBase = chainAccountEnabled ? (liveLane?.capital_base_usd ?? totalEquity) : capitalBase;
  // The headline is a Beijing-time trading-day return.  Lifetime economic PnL
  // remains available in the first card and in the history modal; it must not
  // leak into the daily percentage card.
  const returnPct = returnBase && returnBase > 0 && displayToday != null ? displayToday / returnBase * 100 : null;
  const chainFreshness = chainAccountEnabled
    ? chainAvailable ? `链上采样 ${fmtDateTime(chainSnapshot?.data_as_of)} · 延迟 ${fmtAge(chainSnapshot?.data_age_sec)}${chainSnapshot?.stale ? ' · 数据可能滞后' : ''}` : '链上统计暂不可用'
    : `${paperLane?.group ?? 'PAPER'} 独立模拟账本${paperLane?.stale ? ' · 数据可能滞后' : ''}`;
  const openValue = activeMode === 'paper'
    ? state?.mode_split?.paper?.open_value_usd
    : state?.wallet.value_usd;
  const items: Array<{ label: string; value: string; tone?: number | null; sub?: string; mode?: KpiMode; onClick?: () => void }> = [
    { label: activeMode === 'paper' ? '模拟账户余额' : '账户余额', value: fmtUsd(activeMode === 'paper' ? paperLane?.cash_usd : state?.wallet.balance_pusd), mode: activeMode === 'paper' ? 'paper' : 'chain', onClick: onWallet, sub: activeMode === 'paper' ? 'BTC 5M + BTC 15M + SOL 5M 虚拟资金合计 · 点击查看' : '点击查看充值 / 提现' },
    { label: activeMode === 'paper' ? '模拟持仓成本' : '持仓市值', value: fmtUsd(openValue), mode: activeMode, onClick: onPositions, sub: chainAvailable ? `待结算 ${fmtUsd(chainPendingValue)} + 待兑换 ${fmtUsd(chainRedeemableValue)}` : '点击查看当前模式持仓' },
    { label: activeMode === 'paper' ? '模拟待结算' : '待结算 / 待兑换', value: chainAvailable ? `${chainPendingCount} / ${chainRedeemableCount}` : chainPendingCount == null ? '—' : String(chainPendingCount), mode: activeMode, onClick: onPositions, sub: chainAvailable ? `待结算 ${chainPendingCount} · ${fmtUsd(chainPendingValue)} ｜ 待兑换 ${chainRedeemableCount} · ${fmtUsd(chainRedeemableValue)}` : activeMode === 'paper' ? '当前策略独立模拟持仓 · 点击查看结算历史' : '链上待结算状态' },
    { label: chainAccountEnabled ? '累计经济盈亏 · 链上' : '累计盈亏 · 模拟', value: fmtUsd(displayCumulative), tone: displayCumulative, mode: kpiMode, onClick: onPnlHistory, sub: chainFreshness },
    { label: '今日收益率', value: fmtPct(returnPct), tone: returnPct, mode: kpiMode, onClick: onPnlHistory, sub: `北京时间今日${chainAccountEnabled ? '经济' : '经济'}盈亏 / ${chainAccountEnabled ? '链上日初权益' : '模拟本金'} ${fmtUsd(returnBase)} · 点击查看每日历史` },
    { label: '今日胜率', value: fmtPct(todayTotal && todayWins != null ? todayWins / todayTotal * 100 : null), mode: kpiMode, onClick: onPnlHistory, sub: `已结束市场 ${todayWins ?? '—'} 胜 / ${todayLosses ?? '—'} 负 · 累计 ${displayCumulativeWins ?? '—'} / ${displayCumulativeLosses ?? '—'}` },
    {
      label: chainAccountEnabled ? '今日损益 · 链上' : '今日损益 · 模拟',
      value: fmtUsd(displayToday),
      tone: displayToday,
      mode: kpiMode,
      onClick: onPnlHistory,
      sub: chainAccountEnabled ? `北京时间 · 含手续费 / 返佣 · ${todayWins ?? '—'} 胜 / ${todayLosses ?? '—'} 负` : `北京时间 · 权益变化含费用 · ${todayWins ?? '—'} 胜 / ${todayLosses ?? '—'} 负`,
    },
  ] as const;
  return <div className="kpi-strip" aria-label="账户关键指标">
    {items.map((item) => <div className={`kpi-card${item.onClick ? ' kpi-card-clickable' : ''}${item.label.startsWith('今日损益') ? ' kpi-card-pnl' : ''}`} key={item.label} onClick={item.onClick} role={item.onClick ? 'button' : undefined} tabIndex={item.onClick ? 0 : undefined} onKeyDown={item.onClick ? (event) => { if (event.key === 'Enter' || event.key === ' ') item.onClick?.(); } : undefined}>
      {item.mode && <ModeChip mode={item.mode} />}
      <span className="kpi-label">{item.label}</span><strong className={item.tone == null ? '' : item.tone >= 0 ? 'kpi-positive' : 'kpi-negative'}>{item.value}</strong>{item.sub && <small className="kpi-sub" title={item.sub}>{item.sub}</small>}
    </div>)}
  </div>;
}

function RiskSnapshotPanel({ snapshot, riskState }: { snapshot?: State['risk_snapshot']; riskState?: string }) {
  const state = snapshot?.state || riskState || 'UNKNOWN';
  const tone = state === 'OK' ? 1 : state === 'UNKNOWN' ? null : -1;
  const live = snapshot?.mode === 'live' || snapshot?.valuation === 'marked_account_equity';
  return <div className="risk-snapshot-panel">
    <Row k="风险闸门" v={zhText(state)} colored={tone} relaxed />
    {live && <>
      <Row k="日初权益" v={fmtUsd(snapshot?.day_start_equity_usd ?? snapshot?.capital_base_usd)} relaxed />
      <Row k="当前权益" v={fmtUsd(snapshot?.equity_usd)} relaxed />
    </>}
    <Row k="当前持仓" v={String(snapshot?.position_count ?? 0)} relaxed />
    <Row k={snapshot?.valuation === 'entry_cost' ? '持仓成本' : '持仓市值'} v={fmtUsd(snapshot?.position_value_usd)} relaxed />
    <Row k="未成交订单" v={String(snapshot?.open_orders ?? 0)} relaxed />
    <Row k="挂单名义" v={fmtUsd(snapshot?.open_order_notional_usd)} relaxed />
    <Row k="敞口占比" v={snapshot?.exposure_ratio == null ? '--' : fmtPct(snapshot.exposure_ratio * 100)} relaxed />
    <Row k={live ? '当日净权益变化（含费）' : '风控账本 · 今日已实现'} v={fmtUsd(live ? snapshot?.daily_net_pnl_usd : snapshot?.daily_realized_usd)} colored={live ? snapshot?.daily_net_pnl_usd : snapshot?.daily_realized_usd} relaxed />
    <Row k="亏损上限" v={snapshot?.max_daily_loss_fraction == null ? '--' : fmtPct(snapshot.max_daily_loss_fraction * 100)} dim mono relaxed />
    <Row k="持仓上限" v={String(snapshot?.max_open_positions ?? '--')} dim mono relaxed />
    {live && <div className="live-risk-equity-note">日风控含全部链上持仓及历史待兑换尾仓，OPEN 列表条数可能不同。</div>}
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
  const [modelOptions, setModelOptions] = useState<Record<'primary' | 'secondary', string[]>>({ primary: [], secondary: [] });
  const [manualModel, setManualModel] = useState<Record<'primary' | 'secondary', boolean>>({ primary: false, secondary: false });
  useEffect(() => {
    fetchLlmSettings().then((raw) => {
      const primary = raw.primary || profileFromLegacy(raw);
      const secondary = raw.secondary || emptyProfile();
      setSettings({ ...raw, primary, secondary });
      setModelOptions({ primary: primary.model ? [primary.model] : [], secondary: secondary.model ? [secondary.model] : [] });
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
      const result = await probeLlm(profile.base_url, key, profile.timeout_sec, activeSlot);
      const options = Array.from(new Set((result.models || []).map((model) => String(model).trim()).filter(Boolean)));
      setModelOptions((current) => ({ ...current, [activeSlot]: options }));
      const selected = profile.model && options.includes(profile.model) ? profile.model : options[0] || profile.model || '';
      setManualModel((current) => ({ ...current, [activeSlot]: Boolean(selected && !options.includes(selected)) }));
      updateProfile(activeSlot, { base_url: result.effective_base_url, model: selected });
      setMessage(`${activeSlot === 'primary' ? '主模型' : '复核模型'}已发现 ${result.models.length} 个模型。`);
    } catch (e) { setMessage(`拉取失败：${e}`); }
    finally { setProbing(false); }
  };
  const test = async () => {
    if (!settings) return;
    const profile = settings[activeSlot] || (activeSlot === 'primary' ? profileFromLegacy(settings) : emptyProfile());
    setTesting(true); setMessage('正在测试模型连接…');
    try {
      const result = await testLlm({ base_url: profile.base_url, model: profile.model, api_key: profile.api_key, timeout_sec: profile.timeout_sec, slot: activeSlot });
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
                <label>模型名称<select className="model-select" value={manualModel[activeSlot] ? '__manual__' : profile.model} onChange={(e) => {
                  if (e.target.value === '__manual__') {
                    setManualModel((current) => ({ ...current, [activeSlot]: true }));
                  } else {
                    setManualModel((current) => ({ ...current, [activeSlot]: false }));
                    updateProfile(activeSlot, { model: e.target.value });
                  }
                }}>
                  {!(modelOptions[activeSlot] || []).length && !profile.model && <option value="">请先拉取模型</option>}
                  {profile.model && !(modelOptions[activeSlot] || []).includes(profile.model) && <option value={profile.model}>{profile.model}（当前）</option>}
                  {(modelOptions[activeSlot] || []).map((model) => <option value={model} key={model}>{model}</option>)}
                  <option value="__manual__">手动输入模型 ID…</option>
                </select>
                {manualModel[activeSlot] && <input className="model-manual-input" value={profile.model} onChange={(e) => updateProfile(activeSlot, { model: e.target.value })} placeholder="例如 grok-3-latest" autoComplete="off" />}
                <small className="settings-hint">点击“拉取模型”后从列表选择；若上游未列出目标模型，可切换“手动输入模型 ID”。</small></label>
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
  const modal = (
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
  // Render outside the terminal shell so fixed/overflow and CRT layers can
  // never cover the dialog with an opaque black stacking context.
  return typeof document === 'undefined' ? null : createPortal(modal, document.body);
}

function TopBar({
  time, botRunning, botMode, riskState, err, lastFlashAt, onSettings,
  operatorToken, onOperatorTokenChange, liveBusy, liveMessage, onToggleLive, serviceModes, serviceBusy, onToggleService,
  llmUsage, llmModels, musicEnabled, onToggleMusic, profileName, portfolioValue, accountLive,
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
  llmUsage?: LlmUsageSnapshot | null;
  llmModels?: { primary_model?: string; secondary_model?: string };
  musicEnabled: boolean;
  onToggleMusic: () => void;
  profileName?: string | null;
  portfolioValue?: number | null;
  accountLive: boolean;
}) {
  const blink = Date.now() - lastFlashAt < 5000;
  const riskOk = riskState === 'OK';
  const [manage, setManage] = useState(false);
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
    <div className="terminal-topbar" style={topBarStyle}>
      <div className="topbar-brand">
        <img src="/xustlepoly-favicon.png" alt="XustlePoly" />
        <span className="topbar-brand-name">XustlePoly_HFT</span>
        <span className="topbar-divider">//</span>
        <span className="topbar-market-label">BTC / SOL</span>
      </div>
      <LlmUsagePanel usage={llmUsage} models={llmModels} />
      <span className="topbar-mode" style={{
        marginLeft: 12,
        padding: '1px 8px',
        border: `1px solid ${modeChip.border}`,
        background: modeChip.bg,
        color: modeChip.fg,
        fontWeight: 700,
        letterSpacing: '1.5px',
        fontSize: 11,
      }}>{modeChip.label}</span>
      <div className="topbar-status">
        <span style={{ color: botColor, fontWeight: 600 }}>* 机器人 {botLabel}</span>
        <span className="topbar-status-separator">|</span>
        <span style={{ color: err ? 'var(--red)' : 'var(--green)' }}>* {err ? '接口错误' : '接口正常'}</span>
        {blink && <><span className="topbar-status-separator">|</span><span className="topbar-trade-flash">* 已触发交易</span></>}
      </div>
      <div className="topbar-controls">
      <div className="topbar-action-row">
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
          disabled={liveBusy || (botMode !== 'live' && !Object.values(serviceModes || {}).some(item => item.can_enable_live))}
          className={botRunning && botMode === 'live' ? 'live-stop-button' : 'live-start-button'}
          title={liveMessage || (Object.values(serviceModes || {}).some(item => item.can_enable_live) ? '需要实盘操作令牌' : '产品实盘下单权限已关闭')}
        >
          {liveBusy ? '处理中…' : botRunning && botMode === 'live' ? '关闭实盘' : Object.values(serviceModes || {}).some(item => item.can_enable_live) ? '开启实盘' : '实盘已锁定'}
        </button>
        <button type="button" onPointerDown={() => onToggleMusic()} onClick={(event) => { if (event.detail === 0) onToggleMusic(); }} className={`music-toggle ${musicEnabled ? 'music-on' : ''}`} aria-pressed={musicEnabled} title="播放/暂停视频背景音乐">
          {musicEnabled ? '♫ 音乐开' : '♫ 音乐关'}
        </button>
        <div className="strategy-menu">
          <button className="settings-button" type="button" aria-expanded={manage} onClick={() => setManage(!manage)}>策略管理</button>
          {manage && <div className="product-backdrop" onClick={event => { if (event.target === event.currentTarget) setManage(false); }}><ProductSettings token={operatorToken} close={() => setManage(false)} /></div>}
        </div>
        <div className="service-switches" aria-label="各服务实盘开关">
          {(['BTC'] as const).map((asset) => {
            const info = serviceModes?.[asset]; const allowed = info?.can_enable_live === true; const enabled = info?.live_enabled === true;
            return <button key={asset} type="button" className={`service-switch ${enabled ? 'service-on' : ''}`} disabled={!allowed || serviceBusy === asset} title={allowed ? `${asset} 实盘资格开关` : `${asset} 已锁定为 Paper`} onClick={() => onToggleService(asset, !enabled)}>{asset} {enabled ? 'LIVE' : 'PAPER'}</button>;
          })}
        </div>
        {liveMessage && <span className="live-control-message" title={liveMessage}>{liveMessage}</span>}
      </div>
        <div className="topbar-account-summary" title={accountLive ? 'Polymarket 账户 / 资产组合' : 'BTC 5M + BTC 15M + SOL 5M 模拟账户 / 模拟权益合计'}>
          <span>{accountLive ? profileName || '链上用户未同步' : 'BTC 5M + BTC 15M + SOL 5M 模拟账户'}</span>
          <b>{portfolioValue == null ? accountLive ? '链上金额不可用' : '模拟金额暂不可用' : `${accountLive ? '' : '组合金额 '}${fmtUsd(portfolioValue)}`}</b>
        </div>
        <span className="topbar-clock">{fmtTime(time)}</span>
      </div>
    </div>
  );
}

function LlmUsagePanel({ usage, models }: { usage?: LlmUsageSnapshot | null; models?: { primary_model?: string; secondary_model?: string } }) {
  const rows = usage?.models || [];
  const find = (name: string | undefined, fallback: string) => {
    if (!name) return rows.find((r) => r.model.toLowerCase().includes(fallback.toLowerCase()));
    return rows.find((r) => r.model === name)
      || rows.find((r) => r.model.toLowerCase().includes(name.toLowerCase()))
      || (fallback === 'grok' ? rows.find((r) => r.model.toLowerCase().includes('grok')) : undefined);
  };
  const primary = find(models?.primary_model, 'astra');
  const secondary = find(models?.secondary_model, 'grok');
  const modelName = (entry: typeof primary, configured: string | undefined, fallback: string) => entry?.model || configured || fallback;
  const short = (n: number | undefined) => n == null ? '0' : n.toLocaleString('en-US');
  return <div className="llm-usage-panel" aria-label="双模型 TOKEN 实时消耗">
    <div className="llm-usage-item"><span className="llm-usage-model" title={modelName(primary, models?.primary_model, 'GPT-6-Astra')}>{modelName(primary, models?.primary_model, 'GPT-6-Astra')}</span><span className="llm-usage-value">{short(primary?.total_tokens)} TOK</span><small>{primary ? `累计 · ${short(primary.last_tokens)} 本次` : '尚未调用'}</small></div>
    <div className="llm-usage-divider" />
    <div className="llm-usage-item"><span className="llm-usage-model" title={modelName(secondary, models?.secondary_model, 'Grok')}>{modelName(secondary, models?.secondary_model, 'Grok')}</span><span className="llm-usage-value">{short(secondary?.total_tokens)} TOK</span><small>{secondary ? `累计 · ${short(secondary.last_tokens)} 本次` : '尚未调用'}</small></div>
  </div>;
}

function BottomBar({ state, transport, llmUsage, onAgentClick }: { state: State | null; transport: 'ws' | 'rest'; llmUsage: LlmUsageSnapshot | null; onAgentClick: (role: typeof OPENCLAW_ROLES[number]) => void }) {
  const errs = state?.errors || {};
  const errKeys = Object.keys(errs);
  const roleCards = OPENCLAW_ROLES.map((role) => ({ role, status: findAgentStatus(state?.agent_status, role.keys) }));
  return (
    <>
      <div className="openclaw-agent-dock" aria-label="OpenClaw 中文权限状态">
        <div className="openclaw-dock-caption">OpenClaw 装饰 Agent · Paper 无签名权限</div>
        {roleCards.map(({ role, status }, index) => <AgentCard key={role.id} role={role} status={status} llmUsage={llmUsage} roleIndex={index} todayCounts={state?.today_counts} onClick={() => onAgentClick(role)} />)}
      </div>
      <div className="bottom-bar" style={bottomBarStyle}>
        <span style={{ color: transport === 'ws' ? 'var(--green)' : 'var(--txt-dim)' }}>{transport === 'ws' ? 'WS 实时推送 · 0.25s' : '轮询 1s · 回退'}</span>
        <span style={{ color: 'var(--txt-dim)', margin: '0 12px' }}>/</span>
        <span style={{ color: 'var(--txt-dim)' }}>
          决策 <b style={{ color: 'var(--txt-hi)' }}>{(state?.decisions_total ?? state?.decisions.length ?? 0).toLocaleString('en-US')}</b>
          {' / 订单 '}<b style={{ color: 'var(--txt-hi)' }}>{(state?.orders_total ?? state?.orders.length ?? 0).toLocaleString('en-US')}</b>
        </span>
        <span style={spacer} />
        {errKeys.length > 0 && (
          <span style={{ color: 'var(--red)' }}>错误：{errKeys.join(', ')}</span>
        )}
      </div>
    </>
  );
}

export function AssetDock({ state }: { state: State | null }) {
  const assets = [
    ['BTC', state?.btc_signal?.current_price, '#f4b942', state?.bot_assets?.BTC],
  ] as const;
  return <div className="asset-dock" aria-label="资产服务">
    {assets.map(([name, value, color, live]) => <div className="asset-card" key={name} style={{ '--asset-accent': color } as CSSProperties}>
      <span className="asset-icon">{name.slice(0, 1)}</span><span className="asset-name">{name}</span><strong>{typeof value === 'number' ? fmtUsd(value) : '--'}</strong><span className="asset-mode">{live ? '实盘' : '模拟'}</span>
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

function formatAgentDataScope(scope: AgentStatus['data_scope']): string {
  if (!scope) return 'BTC Paper';
  if (typeof scope === 'string') return scope;
  return Object.entries(scope).filter(([key]) => key.toUpperCase() === 'BTC').map(([, value]) => `BTC ${value === 'live' ? '实时' : 'Paper'}`).join(' · ') || 'BTC Paper';
}

function formatAgentExecutionScope(scope: string | undefined): string {
  const labels: Record<string, string> = {
    btc_l2_live: 'BTC 实盘 · L2',
    btc_close_only_live: 'BTC 实盘 · 仅平仓',
    btc_emergency_live: 'BTC 实盘 · 紧急处置',
    risk_gate: '风控闸门 · 可拒绝',
    read_only: '只读分析 · 无下单权限',
  };
  return labels[scope || ''] || scope || '只读分析 · 无下单权限';
}

function AgentCard({ role, status, llmUsage, roleIndex, todayCounts, onClick }: { role: typeof OPENCLAW_ROLES[number]; status: AgentStatus; llmUsage: LlmUsageSnapshot | null; roleIndex: number; todayCounts?: State['today_counts']; onClick: () => void }) {
  const raw = String(status.status || 'offline').toLowerCase();
  const statusKey = raw === 'running' || raw === 'ok' ? 'running' : raw === 'idle' || raw === 'waiting' ? 'idle' : raw === 'blocked' ? 'blocked' : raw === 'error' || raw === 'failed' ? 'error' : 'offline';
  const statusLabel = statusKey === 'running' ? '运行中' : statusKey === 'idle' ? '等待中' : statusKey === 'blocked' ? '已阻断' : statusKey === 'error' ? '异常' : '离线';
  const queue = Number(status.queue_depth ?? 0);
  // Event figure = Beijing-trading-day count (resets at 00:00 Beijing);
  // falls back to the lifetime last-id when the server predates today_counts.
  const isExecRole = role.id === 'sniper' || role.id === 'exit' || role.id === 'rug';
  const eventId = todayCounts
    ? (isExecRole ? todayCounts.orders : todayCounts.decisions)
    : (isExecRole ? status.last_order_id : status.last_decision_id);
  const durationSeconds = Math.max(0.8, Math.min(3.8, 2.4 - queue * 0.12));
  const activityDuration = `${durationSeconds.toFixed(2)}s`;
  // Stable per-role phase offsets keep cards from rising as one synchronized
  // block while still reflecting the same workflow heartbeat.
  const phaseSeed = [...role.id].reduce((sum, char) => sum + char.charCodeAt(0), 0) % 100;
  const activityDelay = `${(-(phaseSeed / 100) * durationSeconds).toFixed(2)}s`;
  const recentTokens = (llmUsage?.models || []).reduce((sum, model) => sum + Number(model.last_tokens || 0), 0);
  const tokenLevel = Math.max(.2, Math.min(1, recentTokens / 1200));
  return (
    <div className={`agent-card agent-${statusKey}`} style={{ '--agent-accent': role.color, '--agent-activity-duration': activityDuration, '--agent-activity-delay': activityDelay } as CSSProperties} title={status.execution_detail || status.detail || role.label} onClick={onClick} onKeyDown={(event) => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); onClick(); } }} role="button" tabIndex={0}>
      <div className="agent-avatar"><img src={`/openclaw-${role.id === 'desk' ? 'taizhang' : role.id === 'search' ? 'hunter' : role.id}-cutout.png`} alt={`${role.label} OpenClaw`} /></div>
      <div className="agent-card-name">{role.label}</div>
      <div className="agent-card-body">
        <div className="agent-card-metrics" aria-label={`${role.label}实时指标`}>
          <div><span>状态</span><b><i className="agent-status-dot" />{statusLabel}</b></div>
          <div><span>队列</span><b>{queue}</b></div>
          <div><span>事件</span><b>{eventId ?? '--'}</b></div>
        </div>
        <div className="agent-token-wave" aria-label={`${role.label} TOKEN 使用波动`} title={`TOKEN 使用：${recentTokens.toLocaleString('en-US')}（最近一次模型调用）`} style={{ '--token-level': tokenLevel, '--wave-seed': roleIndex } as CSSProperties}>
          {Array.from({ length: 8 }, (_, bar) => <i key={bar} style={{ '--wave-bar': bar, '--wave-height': [0.5, 0.78, 1, 0.62, 0.9, 0.56, 0.74, 0.46][bar], '--wave-scale': [0.5, 0.78, 1, 0.62, 0.9, 0.56, 0.74, 0.46][bar] * tokenLevel } as CSSProperties} />)}
        </div>
      </div>
    </div>
  );
}

const AGENT_CAPABILITIES: Record<string, string[]> = {
  desk: ['任务调度', '审批队列', '日报汇总', '无交易权限'],
  search: ['市场发现', '价差扫描', '事件筛选', '只读行情'],
  whale: ['大额成交跟踪', '盘口异动', '地址行为分析', '只读行情'],
  shill: ['新闻与公告', '民调与舆情', '事件真实性校验', '只读数据'],
  risk: ['敞口校验', '滑点检查', '亏损熔断', '拒绝订单'],
  sniper: ['执行风控通过订单', '撤单与状态同步', '部分成交处理', '无私钥/提现权限'],
  exit: ['止盈止损建议', '平仓指令', '持仓生命周期', '禁止加仓'],
  rug: ['紧急撤单', '紧急平仓', '异常熔断', '无开仓权限'],
};

function AgentDetailModal({ role, status, state, onClose }: { role: typeof OPENCLAW_ROLES[number]; status: AgentStatus; state: State | null; onClose: () => void }) {
  const heartbeat = status.heartbeat_ts ?? status.last_heartbeat_ts;
  const age = heartbeat ? Math.max(0, Date.now() / 1000 - heartbeat) : null;
  const related = (role.id === 'sniper' || role.id === 'exit' || role.id === 'rug') ? (state?.orders || []).slice(0, 8) : [];
  const liveBridge = state?.bot_mode === 'live' && Boolean(state?.service_modes?.BTC?.live_enabled);
  const executionRole = role.id === 'sniper' || role.id === 'exit' || role.id === 'rug';
  const effectiveLive = status.mode === 'live' || (liveBridge && executionRole);
  const liveOrders = (state?.orders || []).filter((order) => order.dry_run === 0).length;
  const paperOrders = (state?.orders || []).filter((order) => order.dry_run !== 0).length;
  const statusText = String(status.status || 'offline').toLowerCase();
  const statusLabel = statusText === 'running' ? '运行中' : statusText === 'idle' || statusText === 'waiting' ? '等待中' : statusText === 'blocked' ? '已阻断' : statusText === 'error' ? '异常' : '离线';
  const executionDetail = effectiveLive
    ? 'BTC L2 实盘链路；订单仍需 RISK 通过'
    : (status.execution_detail || status.detail || '暂无状态说明');
  return <DataModal title={`${role.label} / OpenClaw 详细数据`} onClose={onClose}>
    <div className="agent-detail-head" style={{ '--agent-accent': role.color } as CSSProperties}>
      <img src={`/openclaw-${role.id === 'desk' ? 'taizhang' : role.id === 'search' ? 'hunter' : role.id}-cutout.png`} alt={`${role.label} OpenClaw`} />
      <div><strong>{role.label}</strong><span>{statusLabel} · {formatAgentExecutionScope(status.execution_scope)}</span><small>{executionDetail}</small></div>
    </div>
    <div className="agent-detail-metrics">
      <div><span>最近心跳</span><b>{age == null ? '无记录' : age < 2 ? '刚刚' : `${Math.floor(age)} 秒前`}</b></div>
      <div><span>处理队列</span><b>{status.queue_depth ?? 0}</b></div>
      <div><span>当前市场</span><b>{status.market || '未指定'}</b></div>
      <div><span>运行模式</span><b>{effectiveLive ? 'BTC Live' : 'Paper'}</b></div>
      <div><span>数据范围</span><b>{formatAgentDataScope(status.data_scope)}</b></div>
      <div><span>执行权限</span><b>{formatAgentExecutionScope(status.execution_scope)}</b></div>
      <div><span>主模型调用</span><b>{status.model_calls?.primary === 'ok' ? '正常' : status.model_calls?.primary === 'error' ? '异常' : '等待'}</b></div>
      <div><span>复核模型调用</span><b>{status.model_calls?.secondary === 'ok' ? '正常' : status.model_calls?.secondary === 'error' ? '异常' : '等待'}</b></div>
      <div><span>BTC 实盘订单</span><b>{liveOrders}</b></div>
      <div><span>Paper 订单</span><b>{paperOrders}</b></div>
    </div>
    <div className="agent-detail-section"><h4>权限范围</h4><div className="agent-capability-list">{(AGENT_CAPABILITIES[role.id] || []).map((capability) => <span key={capability}>{capability}</span>)}</div></div>
    {status.slow_loop && Object.keys(status.slow_loop).length > 0 && (
      <div className="agent-detail-section"><h4>慢环任务（最近一轮）</h4>
        <div className="agent-detail-orders">
          {Object.entries(status.slow_loop).map(([task, info]) => (
            <div key={task}>
              <span>{task}</span>
              <span>{info?.workflow_stage || info?.status || '--'}</span>
              <span>
                {info?.duration_ms != null ? `${info.duration_ms}ms` : ''}
                {info?.n_reviews != null ? ` · 复盘${info.n_reviews}` : ''}
                {info?.n_degraded != null ? ` · 退化${info.n_degraded}` : ''}
                {info?.whale_trades != null ? ` · 样本${info.whale_trades.toLocaleString('en-US')}` : ''}
              </span>
            </div>
          ))}
        </div>
      </div>
    )}
    {(role.id === 'sniper' || role.id === 'exit' || role.id === 'rug') && <div className="agent-detail-section"><h4>最近执行回报（事件明细）</h4>{related.length ? <div className="agent-detail-orders">{related.map((order) => <div key={order.id}><span>#{order.id} {order.asset || '--'} · {zhText(order.side)}</span><span>{zhText(order.status)}</span><span>{fmtTime(order.ts)}</span></div>)}</div> : <Empty>暂无执行记录</Empty>}</div>}
    {role.id === 'desk' && (state?.slow_loop?.proposals?.length ?? 0) > 0 && (
      <div className="agent-detail-section"><h4>待审批提案（台长汇总）</h4>
        <div className="agent-detail-orders">
          {(state?.slow_loop?.proposals ?? []).slice(0, 5).map((p) => (
            <div key={`${p.key}-${p.ts}`}>
              <span style={{ color: 'var(--amber-bright)' }}>{p.key}</span>
              <span><code style={{ color: 'var(--txt-dim)' }}>{String(p.current)}</code> <b style={{ color: 'var(--green)' }}>→ {String(p.proposed)}</b></span>
              <span style={{ color: p.confidence === 'high' ? 'var(--green)' : 'var(--txt-dim)' }}>{p.confidence} · {p.source_agent}</span>
            </div>
          ))}
        </div>
      </div>
    )}
    {!(role.id === 'sniper' || role.id === 'exit' || role.id === 'rug') && (() => {
      // Each analysis role sees ITS OWN slice of the decision stream, not a
      // shared dump: filters mirror what the role is responsible for.
      const filters: Record<string, (d: Decision) => boolean> = {
        desk: () => true,
        search: (d) => d.action === 'BUY' || ['SKIP_PRICE', 'SKIP_EDGE', 'SKIP_CONFIRM', 'SKIP_TIME', 'SKIP_SIZE'].includes(d.action),
        whale: (d) => d.action.includes('SIGNAL') || /delta/i.test(d.reason || ''),
        shill: (d) => ['SKIP_VOLATILE', 'SKIP_MARKET', 'SKIP_AMBIGUOUS', 'SKIP_TREND_OVERHEAT', 'SKIP_PRICE_MOMENTUM'].includes(d.action),
        risk: (d) => ['SKIP_RISK', 'SKIP_BALANCE', 'SKIP_EXEC_RISK', 'SKIP_RETRY_CAP', 'SKIP_ONE_SIDE'].includes(d.action),
      };
      const filter = filters[role.id] ?? (() => true);
      const rows = (state?.decisions ?? []).filter(filter).slice(0, 8);
      return (
        <div className="agent-detail-section"><h4>最近事件（{role.label}相关决策流）</h4>
          {rows.length ? (
            <div className="agent-detail-orders">
              {rows.map((d) => (
                <div key={d.id}>
                  <span><b style={{ color: 'var(--amber)' }}>#{d.id}</b> {d.asset || '--'} · <b style={{ color: actionColor(d.action) }}>{zhText(d.action)}</b></span>
                  <span title={zhText(d.reason)}>{zhText(d.reason).slice(0, 30)}</span>
                  <span style={{ color: 'var(--txt-dim)' }}>{fmtTime(d.ts)}</span>
                </div>
              ))}
            </div>
          ) : <Empty>窗口内暂无{role.label}相关事件（近 {state?.decisions?.length ?? 0} 条决策中）</Empty>}
        </div>
      );
    })()}
  </DataModal>;
}

export function LobsterAvatar({ accent, tool, roleId }: { accent: string; tool: string; roleId: string }) {
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
      <g className={`lobster-tool lobster-tool-${roleId}`} transform={roleId === 'desk' ? undefined : 'translate(0 20)'} stroke={accent} fill="none" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
        {roleId === 'desk' && <><path d="M31 8h18l-3-5H34z" fill={accent}/><path d="M34 11h12"/></>}
        {roleId === 'search' && <><circle cx="56" cy="13" r="5"/><path d="M60 17l7 6M51 13h-8"/></>}
        {roleId === 'whale' && <><circle cx="57" cy="13" r="5"/><path d="M61 17l5 5M53 9l-3-3"/></>}
        {roleId === 'shill' && <><path d="M50 15a8 8 0 0 1 14 0v5H50z"/><path d="M50 19h-3v5h4M64 19h3"/></>}
        {roleId === 'risk' && <path d="M57 7l7 3v5c0 5-3 8-7 10-4-2-7-5-7-10v-5z" fill="rgba(250,204,21,.25)" />}
        {roleId === 'sniper' && <><rect x="49" y="7" width="15" height="10" rx="1" fill="rgba(251,146,60,.25)"/><path d="M53 20h8M56 17v3"/><path d="M52 11h7M52 14h4"/></>}
        {roleId === 'exit' && <><circle cx="57" cy="14" r="7" fill="rgba(74,222,128,.2)"/><path d="M57 14l4-4M53 22h8"/></>}
        {roleId === 'rug' && <><circle cx="57" cy="9" r="3" fill={accent}/><path d="M57 12v8M51 20h12M52 20l-3 5M62 20l3 5"/></>}
      </g>
      <rect x="34" y="3" width="12" height="7" rx="2" fill={accent} opacity=".9"/><text x="40" y="8.4" textAnchor="middle" fontSize="4.3" fill="#101010" fontWeight="700">{tool}</text>
    </svg>
  );
}

/** Translate common strategy/status tokens while preserving numeric details. */
function zhText(value: string | null | undefined): string {
  return (value ?? '--')
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

function actionColor(a: string | null | undefined): string {
  const value = a ?? '';
  if (value === 'BUY') return 'var(--green)';
  if (value === 'SELL_EXIT' || value.startsWith('SELL')) return 'var(--amber-bright)';
  if (value.startsWith('SKIP')) return 'var(--txt)';
  return 'var(--txt-hi)';
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
          <tr key={`${d.asset}:${d.id}`} style={{ background: d.action === 'BUY' ? 'rgba(0,255,127,0.04)' : undefined }}>
            <Td>{fmtTime(d.ts)}</Td>
            <Td>{positionProduct(d.asset, d.market_slug)}</Td>
            <Td dim>{shortMarket(d.market_slug)}</Td>
            {/* side-less rows are market-level gates (e.g. time window),
                evaluated before either side -- label them honestly. */}
            <Td dim={!d.side}>{d.side ? zhText(d.side) : '全市场'}</Td>
            <Td right>{fmtNum(d.t_remaining, 1)}s</Td>
            <Td right>{fmtPx(d.ask_price)}</Td>
            <Td color={actionColor(d.action)} bold>{zhText(d.action)}</Td>
            <Td>{zhText(d.reason)}</Td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function feeAmountLabel(value: number): string {
  const sign = value < 0 ? '-' : value > 0 ? '+' : '';
  return `${sign}$${Math.abs(value).toFixed(6)}`;
}

function OrderFee({ order }: { order: Order }) {
  const kind = (order.activity_type || 'TRADE').toUpperCase();
  const chain = order.source === 'polymarket';
  const rawFee = finiteValue(order.fee_usd);
  const value = !chain && rawFee != null ? -Math.abs(rawFee) : rawFee;
  if (!chain) return <span style={{ color: value == null ? 'var(--txt-dim)' : value < 0 ? 'var(--red)' : value > 0 ? 'var(--green)' : 'var(--txt-hi)' }}>{value == null ? '—' : feeAmountLabel(value)}</span>;
  if (order.fee_status === 'not_applicable' || (chain && kind !== 'TRADE')) {
    return <span title="此记录不是买卖成交，不适用交易手续费；链上 Gas 单独计费。" style={{ color: 'var(--txt-dim)' }}>不适用</span>;
  }
  if (order.fee_status === 'ambiguous') {
    return <span title="同一交易包含多笔成交，暂不能唯一对应该笔手续费；待核对成交明细后显示，避免重复计费。" style={{ color: 'var(--amber)' }}>待核对</span>;
  }
  if (value == null || order.fee_status === 'pending') {
    return <span title="该笔成交的实际手续费尚未取得，正在同步；不按总手续费分摊或以费率推算。" style={{ color: 'var(--amber)' }}>待同步</span>;
  }
  const role = (order.liquidity_role || '').toUpperCase();
  const roleLabel = role === 'MAKER' || role === 'TAKER' ? role : '';
  const source = ({ polygon_order_filled: 'Polygon 成交事件', clob_authenticated_trades: 'CLOB 已认证成交记录' } as Record<string, string>)[order.fee_source || ''] || order.fee_source || '成交费用记录';
  const title = `实际交易手续费 ${feeAmountLabel(value)} · ${roleLabel || '流动性角色待确认'} · 来源：${source}；返佣单独统计。`;
  return <span title={title} style={{ display: 'inline-flex', alignItems: 'center', justifyContent: 'flex-end', gap: 5, fontVariantNumeric: 'tabular-nums', color: value < 0 ? 'var(--red)' : value > 0 ? 'var(--green)' : 'var(--txt-hi)' }}>
    {roleLabel && <small style={{ fontSize: 8, color: 'var(--txt-dim)' }}>{roleLabel}</small>}
    <span>{feeAmountLabel(value)}</span>
  </span>;
}

function OrdersTable({ orders }: { orders: Order[] }) {
  if (!orders.length) return <Empty>暂无订单<span className="caret">_</span></Empty>;
  return (
    <table style={tableStyle}>
      <thead>
        <tr>
          <Th>北京时间</Th><Th>产品</Th><Th>来源 / 类型</Th><Th>市场</Th><Th>方向</Th><Th right>份额</Th><Th right>价格</Th><Th>状态</Th><Th right>单笔盈亏</Th><Th right>现金流（买入支出/卖出或兑换收入）</Th><Th right>手续费支出</Th>
        </tr>
      </thead>
      <tbody>
        {orders.slice(0, 20).map((o) => {
          const chain = o.source === 'polymarket';
          const kind = o.activity_type || (o.side.toUpperCase().startsWith('REDEEM') ? 'REDEEM' : 'TRADE');
          const typeLabel = ({ TRADE: '成交', REDEEM: '兑换', MERGE: '合并', SPLIT: '拆分' } as Record<string, string>)[kind] || kind;
          const amount = chain ? activityCashflow(o) : finiteValue(o.cashflow_usd)
            ?? (o.side.toUpperCase().startsWith('SELL') ? 1 : -1) * (o.filled_size || o.size) * o.price;
          const product = positionProduct(o.asset, o.market_slug, o.title);
          const market = o.title
            ? `${product} · ${o.title.replace(/^Bitcoin Up or Down - /, '')}`
            : shortMarket(o.market_slug);
          const singlePnl = finiteValue(o.net_pnl_usd ?? o.pnl_net_usd ?? o.pnl_usd);
          const singlePnlColor = singlePnl == null ? 'var(--txt-dim)' : singlePnl >= 0 ? 'var(--green)' : 'var(--red)';
          const singlePnlLabel = singlePnl == null ? (o.settled ? '—' : '待结算') : fmtSignedUsd(singlePnl);
          return (
            <tr key={o.record_key || `${o.dry_run}:${o.id}`}>
              <Td dim>{fmtDateTime(o.ts)}</Td>
              <Td bold color={product === 'SOL 5M' ? 'var(--cyan)' : 'var(--amber-bright)'}>{product}</Td>
              <Td>{chain ? '链上' : '模拟'} · {typeLabel}</Td>
              <Td dim>{market}</Td>
              <Td>{chain && kind !== 'TRADE' ? '—' : zhText(o.side)}{o.outcome ? ` · ${zhText(o.outcome)}` : ''}</Td>
              <Td right>{fmtNum(o.size, 2)}</Td>
              <Td right>{kind === 'TRADE' ? fmtPx(o.price) : '—'}</Td>
              <Td color={chain ? 'var(--green)' : orderStatusColor(o.status)} bold>{chain ? '已确认' : zhText(o.status)}</Td>
              <Td right color={singlePnlColor} bold>{singlePnlLabel}</Td>
              <Td right color={amount == null ? undefined : amount >= 0 ? 'var(--green)' : 'var(--red)'}>{fmtSignedUsd(amount)}</Td>
              <Td right><OrderFee order={o} /></Td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}

/** Primary vs secondary model opinion history (desk cycles), paginated. */
function ConsensusHistoryModal({ onClose }: { onClose: () => void }) {
  const PAGE = 10;
  const [page, setPage] = useState(0);
  const [rows, setRows] = useState<Array<{ ts: number; decision?: string; reason?: string; agreed?: boolean; primary_text?: string; secondary_text?: string; reviews?: number; pnl_usd?: number }>>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState('');
  useEffect(() => {
    let cancelled = false;
    setLoading(true); setErr('');
    fetchConsensusHistory(page * PAGE, PAGE)
      .then((r) => { if (!cancelled) { setRows(r.rows); setTotal(r.total); } })
      .catch((e) => { if (!cancelled) setErr(String(e)); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [page]);
  const pages = Math.max(1, Math.ceil(total / PAGE));
  const opinionColor = (text?: string) => {
    const t = (text || '').toUpperCase();
    if (t.includes('BUY')) return 'var(--green)';
    if (t.includes('SELL')) return 'var(--red)';
    if (t.includes('HOLD')) return 'var(--amber-bright)';
    return 'var(--txt-dim)';
  };
  return <DataModal title="双模型意见历史 / 主模型 × 复核模型" onClose={onClose}>
    <div className="orders-all-toolbar">
      <span className="orders-all-count">共 {total} 轮台长共识</span>
      <span style={spacer} />
      <button type="button" className="orders-page-btn" disabled={page <= 0 || loading} onClick={() => setPage((p) => Math.max(0, p - 1))}>‹ 上一页</button>
      <span className="orders-all-count">{page + 1} / {pages}</span>
      <button type="button" className="orders-page-btn" disabled={page + 1 >= pages || loading} onClick={() => setPage((p) => p + 1)}>下一页 ›</button>
    </div>
    {err && <div className="settings-message">{err}</div>}
    {loading ? <Empty>加载中…</Empty> : !rows.length ? <Empty>暂无共识记录（慢环每 10 分钟一轮）</Empty> : (
      <table style={tableStyle}>
        <thead><tr><Th>时间</Th><Th>主模型意见</Th><Th>复核模型意见</Th><Th>仲裁结论</Th><Th right>复盘窗</Th><Th right>期间盈亏</Th></tr></thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={`${r.ts}-${i}`}>
              <Td dim>{fmtTime(r.ts)}</Td>
              <Td color={opinionColor(r.primary_text)} bold>{r.primary_text || '—'}</Td>
              <Td color={opinionColor(r.secondary_text)} bold>{r.secondary_text || '—'}</Td>
              <Td color={r.agreed ? 'var(--green)' : 'var(--amber-bright)'} bold>
                {r.agreed ? `一致 · ${r.decision}` : '分歧 · 持有'}
              </Td>
              <Td right dim>{r.reviews ?? '--'}</Td>
              <Td right color={(r.pnl_usd ?? 0) >= 0 ? 'var(--green)' : 'var(--red)'}>{r.pnl_usd == null ? '--' : fmtSignedUsd(r.pnl_usd)}</Td>
            </tr>
          ))}
        </tbody>
      </table>
    )}
  </DataModal>;
}

/** Daily settled PnL history for one lane, paginated. */
function PnlHistoryModal({ initialLane, onClose }: { initialLane: 'paper' | 'live'; onClose: () => void }) {
  const PAGE = 14;
  const [lane, setLane] = useState<'paper' | 'live'>(initialLane);
  const [paperAsset, setPaperAsset] = useState<'ALL' | ProductAsset>('ALL');
  const requestedAsset = lane === 'paper' ? paperAsset : 'BTC';
  const source = lane === 'live' ? 'chain' : 'ledger';
  const [page, setPage] = useState(0);
  const cached = cachedPnlDaily(lane, page * PAGE, PAGE, requestedAsset, source);
  const [rows, setRows] = useState<Array<Record<string, any>>>(() => cached?.rows ?? []);
  const [totalDays, setTotalDays] = useState<number | null>(cached?.total_days ?? null);
  const [capital, setCapital] = useState<number | null>(cached?.capital_base_usd ?? null);
  const [snapshot, setSnapshot] = useState<PnlDailyPage | null>(cached ?? null);
  const [loading, setLoading] = useState(!cached);
  const [refresh, setRefresh] = useState(0);
  const [err, setErr] = useState('');
  useEffect(() => {
    let cancelled = false;
    const prior = cachedPnlDaily(lane, page * PAGE, PAGE, requestedAsset, source);
    if (prior) { setRows(prior.rows); setTotalDays(prior.total_days); setCapital(prior.capital_base_usd); setSnapshot(prior); }
    setLoading(true); setErr('');
    fetchPnlDaily(lane, page * PAGE, PAGE, requestedAsset, source)
      .then((r) => { if (!cancelled) { setRows(r.rows); setTotalDays(r.total_days); setCapital(r.capital_base_usd || null); setSnapshot(r); } })
      .catch((e) => { if (!cancelled) setErr(String(e)); })
      .finally(() => { if (!cancelled) setLoading(false); });
    const timer = window.setInterval(() => setRefresh((value) => value + 1), lane === 'paper' ? 3000 : 15000);
    return () => { cancelled = true; if (timer != null) window.clearInterval(timer); };
  }, [lane, requestedAsset, page, refresh]);
  const pages = Math.max(1, Math.ceil((totalDays ?? 0) / PAGE));
  const pageEconomic = sumNullable(rows.map((row) => dailyEconomic(row)));
  const pageTrade = sumNullable(rows.map((row) => dailyTrade(row)));
  const pageFees = sumNullable(rows.map((row) => dailyFees(row)));
  const pageRebates = sumNullable(rows.map((row) => dailyRebates(row)));
  const pageSlippage = sumNullable(rows.map((row) => finiteValue(row.slippage_usd)));
  const productTotals = (['BTC', 'BTC15M', 'SOL'] as const).map((asset) => ({
    asset,
    net: sumNullable(rows.map((row) => dailyEconomic(row.by_asset?.[asset]))),
    capital: finiteValue(snapshot?.cumulative_by_asset?.[asset]?.capital_base_usd ?? snapshot?.by_asset?.[asset]?.capital_base_usd),
  }));
  const today = snapshot?.today_summary ?? null;
  const todayEconomic = finiteValue(snapshot?.today_economic_pnl_usd ?? dailyEconomic(today));
  const todayTrade = finiteValue(snapshot?.today_trade_pnl_usd ?? dailyTrade(today));
  const todayFees = finiteValue(snapshot?.today_fees_usd ?? dailyFees(today));
  const todayRebates = finiteValue(snapshot?.today_rebates_usd ?? dailyRebates(today));
  const todayWins = finiteValue(today?.wins);
  const todayLosses = finiteValue(today?.losses);
  const feeBreakdown = snapshot?.fee_breakdown;
  const paperPnlLabel = rows.some((row) => finiteValue(row.net_pnl_usd ?? row.economic_pnl_usd) != null) ? '模拟经济净盈亏' : '模拟已实现盈亏';
  const sampleNote = lane === 'live'
    ? `北京时间 · 财务采样 ${fmtDateTime(snapshot?.data_as_of)} · 延迟 ${fmtAge(snapshot?.data_age_sec)}${snapshot?.stale ? ' · 官方采样可能滞后' : ''}`
    : `${paperAsset === 'ALL' ? 'BTC 5M + BTC 15M + SOL 5M 独立模拟账本合计' : `${productName(paperAsset)} 独立模拟账本`} · 按北京时间自然日${snapshot?.stale ? ' · 数据可能滞后' : ''}`;
  const paperLedgerUnavailable = lane === 'paper' && snapshot?.available === false;
  return <DataModal title={`${lane === 'paper' ? paperAsset === 'ALL' ? 'BTC 5M + BTC 15M + SOL 5M' : productName(paperAsset) : 'BTC'} 每日收益率历史 / ${lane === 'live' ? '实盘经济盈亏' : paperPnlLabel}（北京时间）`} onClose={onClose}>
    <div className="orders-all-toolbar">
      {(['live', 'paper'] as const).map((item) => <button key={item} type="button" className={`orders-lane-tab${lane === item ? ' active' : ''}`} onClick={() => { setLane(item); setPage(0); setRows([]); setTotalDays(null); setSnapshot(null); }}>{item === 'live' ? '实盘' : '模拟'}</button>)}
      {lane === 'paper' && (['ALL', 'BTC', 'BTC15M', 'SOL'] as const).map((asset) => <button key={asset} type="button" className={`orders-lane-tab${paperAsset === asset ? ' active' : ''}`} onClick={() => { setPaperAsset(asset); setPage(0); setRows([]); setTotalDays(null); setSnapshot(null); }}>{asset === 'ALL' ? 'BTC 5M + BTC 15M + SOL 5M 合计' : productName(asset)}</button>)}
      <span className="orders-all-count">共 {totalDays ?? '--'} 个自然日{lane === 'paper' && capital ? ` · 模拟本金 ${fmtUsd(capital)}` : lane === 'live' ? ' · 收益率使用各日已确认日初权益' : ''}</span>
      <span style={spacer} />
      <button type="button" className="orders-page-btn" disabled={loading} onClick={() => setRefresh((value) => value + 1)}>{loading ? '更新中…' : '刷新'}</button>
      <button type="button" className="orders-page-btn" disabled={page <= 0 || loading} onClick={() => setPage((p) => Math.max(0, p - 1))}>‹ 上一页</button>
      <span className="orders-all-count">{page + 1} / {pages}</span>
      <button type="button" className="orders-page-btn" disabled={page + 1 >= pages || loading} onClick={() => setPage((p) => p + 1)}>下一页 ›</button>
    </div>
    <div className="positions-sync-note">{sampleNote}</div>
    {lane === 'paper' && (paperLedgerUnavailable || snapshot?.error) && <div className="settings-message" role="status">{paperLedgerUnavailable ? '模拟账本暂不可用，当前金额与收益率不能作为真实零值。' : '模拟账本读取异常。'}{snapshot?.error ? ` ${snapshot.error}` : ''}</div>}
    {lane === 'paper' && snapshot?.stale && <div className="positions-sync-note" role="status">正在使用最近账本采样，等待最新数据同步。</div>}
    {lane === 'live' && <div className="positions-sync-note">Activity 截至 {fmtDateTime(snapshot?.activity_as_of)} · 读取于 {fmtDateTime(snapshot?.activity_updated_at)}{snapshot?.activity_ahead_of_pnl ? ' · 新成交尚未进入财务采样' : ''} · 历史{snapshot?.source_fidelity === '1d' ? '按官方日采样' : `采样精度 ${snapshot?.source_fidelity || '—'}`}</div>}
    {lane === 'live' && <div className="positions-sync-note">胜负按官方已结束持仓的经济盈亏，每个市场计一次 · 读取于 {fmtDateTime(snapshot?.outcomes_updated_at)}</div>}
    <div className="pnl-summary-grid">
      <div className="pnl-summary-card"><h3>{lane === 'live' ? '当前页已知采样合计' : '当前页模拟合计'}</h3><Row k={lane === 'live' ? '经济净盈亏' : '扣费后净盈亏'} v={fmtSignedUsd(pageEconomic)} colored={pageEconomic} relaxed /><Row k="交易盈亏" v={fmtSignedUsd(pageTrade)} colored={pageTrade} relaxed /><Row k="手续费" v={fmtSignedUsd(pageFees)} colored={pageFees} relaxed /><Row k="返佣" v={fmtSignedUsd(pageRebates)} colored={pageRebates} relaxed /><small className="pnl-summary-note">{lane === 'live' ? '缺少可靠期初基准的日期显示 —；缺少已确认日初权益时不计算收益率。' : `净盈亏已计入模拟交易费用；模拟滑点${pageSlippage == null ? '' : ` ${fmtSignedUsd(pageSlippage)}`}已含成交价，不重复扣减。返佣仅记录已入账金额。`}</small></div>
      {lane === 'paper' && paperAsset === 'ALL' && <div className="pnl-summary-card"><h3>当前页产品拆分</h3>{productTotals.map((item) => <Row key={item.asset} k={`${productName(item.asset)} 净盈亏 / 收益率`} v={`${fmtSignedUsd(item.net)} / ${item.capital && item.capital > 0 && item.net != null ? fmtPct(item.net / item.capital * 100) : '—'}`} colored={item.net} relaxed />)}<small className="pnl-summary-note">合计收益率以各产品模拟本金之和计算；各产品独立计算日亏损熔断。</small></div>}
      {lane === 'live' && <div className="pnl-summary-card pnl-summary-chain"><h3>北京时间当日 · 链上</h3><Row k="经济净盈亏" v={fmtSignedUsd(todayEconomic)} colored={todayEconomic} relaxed /><Row k="交易盈亏" v={fmtSignedUsd(todayTrade)} colored={todayTrade} relaxed /><Row k="手续费" v={fmtSignedUsd(todayFees)} colored={todayFees} relaxed /><Row k="返佣" v={fmtSignedUsd(todayRebates)} colored={todayRebates} relaxed /><Row k="胜 / 负" v={`${todayWins ?? '—'} / ${todayLosses ?? '—'}`} relaxed /></div>}
      {lane === 'live' && <div className="pnl-summary-card"><h3>手续费 / 返佣明细</h3><Row k="累计手续费" v={fmtSignedUsd(feeBreakdown?.total_usd)} colored={feeBreakdown?.total_usd} relaxed /><Row k="Maker 手续费" v={fmtSignedUsd(feeBreakdown?.maker_fee_usd)} colored={feeBreakdown?.maker_fee_usd} relaxed /><Row k="Taker 手续费" v={fmtSignedUsd(feeBreakdown?.taker_fee_usd)} colored={feeBreakdown?.taker_fee_usd} relaxed /><Row k="累计返佣" v={fmtSignedUsd(feeBreakdown?.rebates_usd)} colored={feeBreakdown?.rebates_usd} relaxed /><Row k="手续费退还" v={fmtSignedUsd(feeBreakdown?.fees_refunded_usd)} colored={feeBreakdown?.fees_refunded_usd} relaxed /><small className="pnl-summary-note">返佣合计含手续费退还 · 官方未提供 Maker/Taker 手续费拆分</small></div>}
    </div>
    {err && <div className="settings-message">{err}</div>}
    {lane === 'live' && (snapshot?.error || snapshot?.activity_stale || snapshot?.outcomes_stale) && <div className="settings-message">部分链上接口更新延迟，已保留最近可用数据；缺失数据以 — 显示。</div>}
    {loading && !rows.length ? <div role="status" style={{ minHeight: 180, padding: 20 }}>正在读取北京时间每日账本…</div> : !rows.length ? <Empty>{paperLedgerUnavailable ? '模拟账本不可用，请稍后刷新；不展示虚构的零收益记录。' : '暂无历史结算数据'}</Empty> : (
      <table style={tableStyle}>
        <thead><tr><Th>北京日期</Th><Th right>{lane === 'live' ? '经济净盈亏' : paperAsset === 'ALL' ? '合计净盈亏' : '扣费后净盈亏'}</Th>{lane === 'paper' && paperAsset === 'ALL' && <><Th right>BTC 5M 净盈亏 / 收益率</Th><Th right>BTC 15M 净盈亏 / 收益率</Th><Th right>SOL 净盈亏 / 收益率</Th></>}<Th right>交易盈亏</Th><Th right>手续费</Th><Th right>返佣</Th><Th right>胜</Th><Th right>负</Th><Th right>胜率</Th><Th right>收益率</Th></tr></thead>
        <tbody>
          {rows.map((r) => {
            const pnl = dailyEconomic(r);
            const wins = finiteValue(r.wins);
            const losses = finiteValue(r.losses);
            const total = wins != null && losses != null ? wins + losses : null;
            const wr = total && wins != null ? wins / total * 100 : null;
            const dayCapital = lane === 'live' ? finiteValue(r.capital_base_usd) : finiteValue(r.capital_base_usd) ?? capital;
            const ret = finiteValue(r.return_pct) ?? (dayCapital && dayCapital > 0 && pnl != null ? pnl / dayCapital * 100 : null);
            return (
              <tr key={String(r.day)}>
                <Td><span title={lane === 'live' ? `基准 ${fmtDateTime(r.baseline_ts)} · 采样 ${fmtDateTime(r.data_as_of)} · ${r.coverage === 'complete' ? '完整边界' : r.coverage === 'unavailable' ? '缺少基准' : '部分采样'}` : undefined}>{String(r.day ?? '--')}</span>{lane === 'live' && r.coverage && r.coverage !== 'complete' && <small className="pnl-day-coverage">{r.coverage === 'unavailable' ? '基准待核' : '部分采样'}</small>}</Td>
                <Td right color={pnl == null ? undefined : pnl >= 0 ? 'var(--green)' : 'var(--red)'} bold>{fmtSignedUsd(pnl)}</Td>
                {lane === 'paper' && paperAsset === 'ALL' && (['BTC', 'BTC15M', 'SOL'] as const).map((asset) => {
                  const assetRow = r.by_asset?.[asset];
                  const assetPnl = dailyEconomic(assetRow);
                  const assetCapital = finiteValue(assetRow?.capital_base_usd);
                  const assetReturn = finiteValue(assetRow?.return_pct) ?? (assetCapital && assetCapital > 0 && assetPnl != null ? assetPnl / assetCapital * 100 : null);
                  return <Td key={asset} right color={assetPnl == null ? undefined : assetPnl >= 0 ? 'var(--green)' : 'var(--red)'}>{fmtSignedUsd(assetPnl)}<small style={{ display: 'block', color: 'var(--txt-dim)' }}>{assetReturn == null ? '—' : fmtPct(assetReturn)}</small></Td>;
                })}
                <Td right>{fmtSignedUsd(dailyTrade(r))}</Td><Td right color={(dailyFees(r) ?? 0) < 0 ? 'var(--red)' : undefined}>{fmtSignedUsd(dailyFees(r))}</Td><Td right color={(dailyRebates(r) ?? 0) > 0 ? 'var(--green)' : undefined}>{fmtSignedUsd(dailyRebates(r))}</Td>
                <Td right>{wins ?? '—'}</Td>
                <Td right>{losses ?? '—'}</Td>
                <Td right>{wr == null ? '--' : `${wr.toFixed(1)}%`}</Td>
                <Td right color={ret == null ? undefined : ret >= 0 ? 'var(--green)' : 'var(--red)'}>{ret == null ? '--' : `${ret >= 0 ? '+' : ''}${ret.toFixed(2)}%`}</Td>
              </tr>
            );
          })}
        </tbody>
      </table>
    )}
  </DataModal>;
}

function WalletActivityModal({ state, onClose }: { state: State | null; onClose: () => void }) {
  const [rows, setRows] = useState<Array<Record<string, unknown>>>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState('');
  useEffect(() => {
    let cancelled = false;
    fetchPolymarketFunding(0, 30).then((r) => { if (!cancelled) { setRows(r.rows || []); setTotal(r.total || 0); if (r.available === false && r.message) setErr(r.message); } })
      .catch((e) => { if (!cancelled) setErr(String(e)); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, []);
  const profile = state?.wallet?.user_name || state?.wallet?.pseudonym || state?.wallet?.polymarket_profile?.name || state?.wallet?.polymarket_profile?.pseudonym || state?.wallet?.profile?.name || state?.wallet?.profile?.pseudonym || 'Polymarket 用户';
  return <DataModal title={`${profile} / 充值与提现记录`} onClose={onClose}>
    <div className="orders-all-toolbar"><span className="orders-all-count">账户余额 {fmtUsd(state?.wallet?.balance_pusd)} · 组合 {fmtUsd(state?.wallet?.portfolio_value_usd ?? state?.wallet?.polymarket_profile?.portfolio_value_usd ?? state?.wallet?.value_usd)}</span><span style={spacer} /><span className="orders-all-count">共 {total} 笔</span></div>
    {err && <div className="settings-message">{err}</div>}
    {loading ? <Empty>加载中…</Empty> : !rows.length ? <Empty>暂无充值 / 提现记录<span className="caret">_</span></Empty> : (
      <table style={tableStyle}><thead><tr><Th>时间</Th><Th>类型</Th><Th right>金额</Th><Th>状态</Th><Th>交易哈希</Th></tr></thead><tbody>
        {rows.map((row, i) => {
          const ts = Number(row.timestamp ?? row.ts ?? 0);
          const type = String(row.type || row.kind || row.direction || '—');
          const amount = Number(row.amount_usd ?? row.amount ?? row.usdc_size ?? 0);
          const status = String(row.status || '已确认');
          const tx = String(row.transaction_hash || row.tx_hash || row.hash || '—');
          return <tr key={`${tx}-${i}`}><Td dim>{ts ? fmtTime(ts) : '—'}</Td><Td>{zhText(type)}</Td><Td right color={amount >= 0 ? 'var(--green)' : 'var(--red)'}>{fmtUsd(amount)}</Td><Td>{zhText(status)}</Td><Td dim>{tx.length > 18 ? `${tx.slice(0, 10)}…${tx.slice(-8)}` : tx}</Td></tr>;
        })}
      </tbody></table>
    )}
  </DataModal>;
}

/** Full order history (paper + live) with server-side pagination. */
function beijingDate(ts = Date.now() / 1000): string {
  return new Date((ts + 8 * 3600) * 1000).toISOString().slice(0, 10);
}

function beijingDateStart(date: string): number {
  return Date.parse(`${date}T00:00:00+08:00`) / 1000;
}

function OrdersAllModal({ initialLane = 'all', onClose }: { initialLane?: 'all' | 'paper' | 'live'; onClose: () => void }) {
  const PAGE = 20;
  const [lane, setLane] = useState<'all' | 'paper' | 'live'>(initialLane);
  const [assetFilter, setAssetFilter] = useState<'ALL' | ProductAsset>('ALL');
  const [page, setPage] = useState(0);
  const [rows, setRows] = useState<Order[]>([]);
  const [total, setTotal] = useState<number | null>(null);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState('');
  const [activity, setActivity] = useState<OrdersPage | null>(null);
  const [liveDaily, setLiveDaily] = useState<PnlDailyPage | null>(null);
  const [refresh, setRefresh] = useState(0);
  const [startDate, setStartDate] = useState(() => beijingDate());
  const [endDate, setEndDate] = useState('');
  const [period, setPeriod] = useState<OrdersPeriodFilter>(() => ({ start_ts: beijingDateStart(beijingDate()) }));
  const feeRetryKey = useRef('');
  useEffect(() => {
    let cancelled = false;
    let feeRetryTimer: number | null = null;
    setLoading(true); setErr('');
    
    Promise.allSettled([
      fetchOrdersPage(page * PAGE, PAGE, lane, assetFilter, lane === 'live' ? period : undefined),
      lane === 'paper' ? Promise.resolve(null) : fetchPnlDaily('live', 0, 14, 'BTC', 'chain'),
    ]).then(([ordersResult, dailyResult]) => {
      if (cancelled) return;
      const errors: string[] = [];
      if (ordersResult.status === 'fulfilled') {
        const result = ordersResult.value;
        setRows(result.rows); setTotal(result.total); setActivity(result);
        const retryKey = `${lane}:${assetFilter}:${page}:${period.start_ts}:${period.end_ts}`;
        const hasPendingFees = result.rows.some((row) => row.source === 'polymarket' && row.activity_type === 'TRADE'
          && row.fee_status !== 'ambiguous' && row.fee_status !== 'not_applicable'
          && (finiteValue(row.fee_usd) == null || row.fee_status === 'pending'));
        if (lane !== 'paper' && hasPendingFees && feeRetryKey.current !== retryKey) {
          feeRetryKey.current = retryKey;
          feeRetryTimer = window.setTimeout(() => { if (!cancelled) setRefresh((value) => value + 1); }, 5000);
        }
      } else errors.push(`交易记录更新失败：${String(ordersResult.reason)}`);
      if (dailyResult.status === 'fulfilled') setLiveDaily(dailyResult.value);
      else errors.push('当日链上统计更新失败，已保留最近可用采样。');
      setErr(errors.join(' '));
    }).finally(() => { if (!cancelled) setLoading(false); });
    const timer = window.setInterval(() => setRefresh((value) => value + 1), lane === 'paper' ? 3000 : 15000);
    return () => { cancelled = true; if (timer != null) window.clearInterval(timer); if (feeRetryTimer != null) window.clearTimeout(feeRetryTimer); };
  }, [lane, assetFilter, page, refresh, period.start_ts, period.end_ts]);
  const pages = Math.max(1, Math.ceil((total ?? 0) / PAGE));
  const pageChainRows = rows.filter((row) => row.source === 'polymarket');
  const pageCashflow = sumNullable(pageChainRows.map((row) => activityCashflow(row)));
  const pageTradeRows = pageChainRows.filter((row) => row.activity_type === 'TRADE');
  const confirmedFeeRows = pageTradeRows.filter((row) => finiteValue(row.fee_usd) != null && row.fee_status !== 'pending' && row.fee_status !== 'ambiguous');
  const pageFees = sumNullable(confirmedFeeRows.map((row) => finiteValue(row.fee_usd)));
  const summary = activity?.period_summary;
  const periodCashflow = finiteValue(summary?.net_cashflow_usd);
  const periodFees = finiteValue(summary?.fees_usd);
  const periodEconomic = finiteValue(summary?.official_economic_pnl_usd);
  const quickClosed = finiteValue(summary?.quick_closed_pnl_usd);
  const periodLabel = summary
    ? `${fmtDateTime(summary.start_ts)} — ${fmtDateTime(summary.end_ts)}`
    : '期间范围待同步';
  const resetForPeriod = (next: OrdersPeriodFilter) => {
    setPage(0); setRows([]); setTotal(null); setActivity(null); setErr('');
    feeRetryKey.current = ''; setPeriod(next); setRefresh((value) => value + 1);
  };
  const applyDates = () => {
    const from = startDate ? beijingDateStart(startDate) : undefined;
    const until = endDate ? beijingDateStart(endDate) + 86400 : undefined;
    if ((from != null && (!Number.isFinite(from) || from > Date.now() / 1000))
      || (until != null && !Number.isFinite(until))
      || (from != null && until != null && from >= until)) {
      setErr('请选择有效的北京日期，开始日期不能晚于结束日期或当前时刻。'); return;
    }
    resetForPeriod({ start_ts: from, end_ts: until });
  };
  const selectPeriod = (kind: 'today' | 'yesterday' | 'all') => {
    const day = kind === 'yesterday' ? beijingDate(Date.now() / 1000 - 86400) : beijingDate();
    setStartDate(kind === 'all' ? '' : day); setEndDate(kind === 'yesterday' ? day : '');
    resetForPeriod(kind === 'all' ? {} : { start_ts: beijingDateStart(day), end_ts: kind === 'yesterday' ? beijingDateStart(day) + 86400 : undefined });
  };
  const changePage = (next: number) => { setRows([]); setPage(next); };
  return <DataModal title={lane === 'live' ? 'Polymarket 实盘交易记录 / 当前用户' : lane === 'paper' ? 'BTC PAPER / 模拟成交记录' : '订单总览 / 模拟 + 实盘'} onClose={onClose}>
    <div className="orders-all-toolbar">
      {(['all', 'paper', 'live'] as const).map((l) => (
        <button key={l} type="button" className={`orders-lane-tab${lane === l ? ' active' : ''}`}
          onClick={() => { setLane(l); setPage(0); setRows([]); setTotal(null); setActivity(null); setLiveDaily(null); }}>
          {l === 'all' ? '全部' : l === 'paper' ? '模拟' : '实盘'}
        </button>
      ))}
      <span className="orders-all-count">共 {total?.toLocaleString('en-US') ?? '—'} 笔 · {lane === 'live' ? '链上真实记录' : lane === 'paper' ? 'Paper 成交' : '链上 + Paper 成交'}</span>
      {(['ALL', 'BTC', 'BTC15M', 'SOL'] as const).map((asset) => <button key={asset} type="button" className={`orders-lane-tab${assetFilter === asset ? ' active' : ''}`} onClick={() => { setAssetFilter(asset); setPage(0); setRows([]); setTotal(null); }}>{asset === 'ALL' ? '全部资产' : productName(asset)}</button>)}
      <span style={spacer} />
      <button type="button" className="orders-page-btn" disabled={loading} onClick={() => setRefresh((value) => value + 1)}>{loading ? '更新中…' : '刷新'}</button>
      <button type="button" className="orders-page-btn" disabled={page <= 0 || loading} onClick={() => changePage(Math.max(0, page - 1))}>‹ 上一页</button>
      <span className="orders-all-count">{page + 1} / {pages}</span>
      <button type="button" className="orders-page-btn" disabled={page + 1 >= pages || loading} onClick={() => changePage(page + 1)}>下一页 ›</button>
    </div>
    {lane === 'live' && <div className="orders-period-toolbar" aria-label="北京时间实盘记录筛选">
      <label>北京开始日期<input type="date" value={startDate} onChange={(event) => setStartDate(event.target.value)} /></label>
      <label>北京结束日期<input type="date" value={endDate} onChange={(event) => setEndDate(event.target.value)} /><small>留空统计至现在，所选结束日期包含全天</small></label>
      <button type="button" className="orders-page-btn" onClick={applyDates}>查询区间</button>
      <button type="button" className="orders-page-btn" onClick={() => selectPeriod('today')}>今日</button>
      <button type="button" className="orders-page-btn" onClick={() => selectPeriod('yesterday')}>昨日</button>
      <button type="button" className="orders-page-btn" onClick={() => selectPeriod('all')}>全部日期</button>
    </div>}
    {lane !== 'paper' && <>
      <div className="positions-sync-note">北京时间 · 统计区间 {periodLabel} · 各项期间汇总覆盖全部筛选记录，不随翻页变化。</div>
      <div className="positions-sync-note">Activity 截至 {fmtDateTime(activity?.activity_as_of)} · 读取于 {fmtDateTime(activity?.updated_at)}{liveDaily?.activity_ahead_of_pnl ? ' · 新成交尚未进入财务采样' : ''}</div>
      <div className="pnl-summary-grid orders-summary-grid">
        <div className="pnl-summary-card"><h3>筛选期间 · 现金流（买入支出/卖出或兑换收入）</h3><Row k="净现金流（含本金）" v={fmtSignedUsd(periodCashflow)} colored={periodCashflow} relaxed /><Row k="手续费支出" v={periodFees == null ? '待同步' : feeAmountLabel(-Math.abs(periodFees))} colored={periodFees == null ? undefined : -Math.abs(periodFees)} relaxed /><Row k="费用已确认" v={`${summary?.fee_confirmed ?? '—'} / ${summary?.fee_total_trades ?? '—'} 笔成交`} relaxed /><Row k="成交 / 兑换" v={`${summary?.trades ?? '—'} / ${summary?.redemptions ?? '—'}`} relaxed /><small className="pnl-summary-note">现金流按买入支出、卖出或兑换收入展示；手续费支出单列，净盈亏已经过一次费用处理。</small></div>
        <div className="pnl-summary-card pnl-summary-chain"><h3>同区间 · 官方经济采样</h3><Row k="经济净盈亏" v={fmtSignedUsd(periodEconomic)} colored={periodEconomic} relaxed /><Row k="交易盈亏" v={fmtSignedUsd(summary?.official_trade_pnl_usd)} colored={summary?.official_trade_pnl_usd} relaxed /><Row k="手续费" v={fmtSignedUsd(summary?.official_fees_usd)} colored={summary?.official_fees_usd} relaxed /><Row k="返佣" v={fmtSignedUsd(summary?.official_rebates_usd)} colored={summary?.official_rebates_usd} relaxed /><small className="pnl-summary-note">基准 {fmtDateTime(summary?.official_baseline_ts)}<br />采样 {fmtDateTime(summary?.official_data_as_of)}{summary?.official_data_source_ts != null && summary.official_data_source_ts !== summary.official_data_as_of && <>（源数据 {fmtDateTime(summary.official_data_source_ts)}）</>}<br />{summary?.official_coverage === 'complete' ? '区间边界完整' : summary?.official_coverage === 'unavailable' ? '缺少可靠基准，金额暂不计算' : '部分采样：边界或最新成交尚未完整覆盖'}</small></div>
        <div className="pnl-summary-card"><h3>快速闭仓结果 · 官方持仓</h3><Row k="已闭合市场净盈亏" v={fmtSignedUsd(quickClosed)} colored={quickClosed} relaxed /><Row k="已闭合市场" v={summary?.quick_closed_markets ?? '—'} relaxed /><small className="pnl-summary-note">最后结果 {fmtDateTime(summary?.quick_closed_as_of)}<br />按闭合日期归属的完整市场生命周期盈亏，可能包含期前成本；不含仍在交易持仓的浮盈亏，不能代替区间经济估值。</small></div>
      </div>
      <div className="positions-sync-note">本页 {pageChainRows.length} 条现金收付 {fmtSignedUsd(pageCashflow)} · 本页已确认手续费 {pageFees == null ? '待同步' : feeAmountLabel(pageFees)}（{confirmedFeeRows.length}/{pageTradeRows.length}） · 全账户累计手续费 {fmtSignedUsd(liveDaily?.fee_breakdown?.total_usd)} · 全账户累计返佣 {fmtSignedUsd(liveDaily?.fee_breakdown?.rebates_usd)}</div>
    </>}
    {err && <div className="settings-message">{err}</div>}
    {(activity?.stale || liveDaily?.activity_stale || liveDaily?.outcomes_stale || liveDaily?.error) && <div className="settings-message">链上接口更新延迟，当前显示最近可用数据。</div>}
    {loading && !rows.length ? <Empty>加载中…</Empty> : <OrdersTable orders={rows} />}
  </DataModal>;
}

/** Window end from the market slug (…-5m-<start>); stale = long past end
 * with no resolution recorded, which we label instead of hiding. */
function paperWindowEnd(slug: string): number | null {
  const m = /-(\d{9,})$/.exec(slug || '');
  return m ? Number(m[1]) + (slug.includes('-15m-') ? 900 : 300) : null;
}

function positionProduct(asset: unknown, slug: unknown, title?: unknown): string {
  const declared = String(asset || '').trim().toUpperCase();
  if (declared === 'BTC15M' || String(slug).includes('btc-updown-15m-')) return 'BTC 15M';
  if (['BTC','BTC5M','SOL','SOL5M'].includes(declared)) return productName(declared);
  const market = `${String(slug || '')} ${String(title || '')}`.toLowerCase();
  if (market.includes('sol-updown-') || market.includes('solana')) return 'SOL 5M';
  if (market.includes('btc-updown-') || market.includes('bitcoin')) return 'BTC 5M';
  return declared || '—';
}

function PaperPositionsTable({ rows }: { rows: PaperPosition[] }) {
  if (!rows.length) return <Empty>暂无模拟持仓<span className="caret">_</span></Empty>;
  const now = Date.now() / 1000;
  return (
    <table style={tableStyle}>
      <thead>
        <tr><Th>时间</Th><Th>产品</Th><Th>市场</Th><Th>方向</Th><Th right>数量</Th><Th right>价格</Th><Th right>名义</Th><Th>状态</Th></tr>
      </thead>
      <tbody>
        {rows.map((p, i) => {
          const end = paperWindowEnd(p.market_slug);
          const stale = end != null && now - end > 900;
          return (
            <tr key={`${p.market_slug}-${i}`}>
              <Td dim>{fmtDateTime(p.ts)}</Td>
              <Td bold color={positionProduct(p.asset, p.market_slug) === 'SOL 5M' ? 'var(--cyan)' : 'var(--amber-bright)'}>{positionProduct(p.asset, p.market_slug)}</Td>
              <Td dim>{shortMarket(p.market_slug)}</Td>
              <Td>{zhText(p.side)}</Td>
              <Td right>{fmtNum(p.remaining_size ?? p.size, 2)}</Td>
              <Td right>{fmtPx(p.entry_price ?? p.price)}</Td>
              <Td right>{fmtUsd(p.notional_usd)}</Td>
              <Td color={stale ? 'var(--red)' : 'var(--amber)'} bold>{stale ? '超期待结算' : '待结算'}</Td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}

function PaperSettledTable({ rows }: { rows: PaperPosition[] }) {
  if (!rows.length) return <Empty>暂无模拟结算历史<span className="caret">_</span></Empty>;
  return <table style={tableStyle}>
    <thead><tr><Th>北京结算时间</Th><Th>产品</Th><Th>市场</Th><Th>方向</Th><Th right>数量</Th><Th right>交易盈亏</Th><Th right>手续费</Th><Th right>净盈亏</Th><Th>状态</Th></tr></thead>
    <tbody>{rows.map((p, i) => {
      const gross = finiteValue(p.gross_pnl_usd ?? p.pnl_usd);
      const rawFees = finiteValue(p.fees_usd ?? p.fee_usd);
      const fees = rawFees == null ? null : -Math.abs(rawFees);
      const net = finiteValue(p.net_pnl_usd ?? p.pnl_net_usd);
      return <tr key={`${p.market_slug}-${p.closed_ts ?? i}`}>
        <Td dim>{fmtDateTime(p.closed_ts)}</Td><Td bold color={positionProduct(p.asset, p.market_slug) === 'SOL 5M' ? 'var(--cyan)' : 'var(--amber-bright)'}>{positionProduct(p.asset, p.market_slug)}</Td><Td dim>{shortMarket(p.market_slug)}</Td><Td>{zhText(p.side)}</Td>
        <Td right>{fmtNum(p.size, 2)}</Td><Td right>{fmtSignedUsd(gross)}</Td>
        <Td right color={fees != null && fees < 0 ? 'var(--red)' : undefined}>{fmtSignedUsd(fees)}</Td>
        <Td right color={net == null ? undefined : net >= 0 ? 'var(--green)' : 'var(--red)'} bold>{fmtSignedUsd(net)}</Td>
        <Td color="var(--green)">已结算入账</Td>
      </tr>;
    })}</tbody>
  </table>;
}

function PositionsTable({ positions }: { positions: Position[] }) {
  if (!positions.length) return <Empty>暂无持仓<span className="caret">_</span></Empty>;
  return (
    <table style={tableStyle}>
      <thead>
        <tr>
          <Th>产品</Th><Th>名称</Th><Th>方向</Th><Th right>数量</Th><Th right>价格</Th><Th right>价值</Th>
        </tr>
      </thead>
      <tbody>
        {positions.map((p, i) => {
          const raw = p as Position & { slug?: string; position_side?: string; outcome_index?: number; current_size?: number; total_size?: number; current_price?: number; current_value?: number };
          const name = (p.title || p.market_slug || raw.slug || p.conditionId || '--').replace(/^Bitcoin Up or Down - /, '');
          const direction = p.outcome || p.side || raw.position_side || (raw.outcome_index === 0 ? 'Up' : raw.outcome_index === 1 ? 'Down' : '--');
          const quantity = Number(p.size ?? raw.current_size ?? raw.total_size ?? 0);
          const price = Number(p.curPrice ?? raw.current_price ?? 0);
          const value = Number(p.currentValue ?? raw.current_value ?? quantity * price);
          return <tr key={i}>
            <Td bold>{positionProduct(p.asset, p.market_slug || raw.slug, p.title)}</Td>
            <Td dim>{name}</Td>
            <Td>{zhText(String(direction || '--'))}</Td>
            <Td right>{fmtNum(quantity, 2)}</Td>
            <Td right>{fmtPx(price)}</Td>
            <Td right>{fmtUsd(value)}</Td>
          </tr>;
        })}
      </tbody>
    </table>
  );
}

function shortMarket(slug: string | null | undefined): string {
  const value = slug || '';
  const compact = value.replace('btc-updown-15m-', '').replace('btc-updown-5m-', '').replace('sol-updown-5m-', '').replace('eth-updown-5m-', '');
  if (value.includes('btc-updown-15m-')) return `BTC 15m · ${compact}`;
  if (value.includes('sol-updown-5m-')) return `SOL 5m · ${compact}`;
  if (value.includes('btc-updown-5m-')) return `BTC 5m · ${compact}`;
  if (value.includes('eth-updown-5m-')) return `ETH 5m · ${compact}`;
  return compact || '未知市场';
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

