import { useEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import type { CSSProperties, ReactNode } from 'react';
import { controlLive, fetchConsensusHistory, fetchLlmSettings, fetchOrdersPage, fetchPnlDaily, fetchState, probeLlm, putPaperService, putRiskSettings, saveLlmSettings, testLlm, toggleLiveService } from './api';
import type {
  Book,
  Decision,
  AgentStatus,
  AssetRegistryEntry,
  LlmSettings,
  LlmModelProfile,
  LlmUsageSnapshot,
  Order,
  PaperPosition,
  Position,
  PriceHistoryPoint,
  SlowLoopProposal,
  SportsRealtime,
  State,
  WeatherRealtime,
} from './types';
import { fmtDur, fmtNum, fmtPct, fmtPx, fmtTime, fmtUsd } from './format';

const POLL_MS = 1000; // REST fallback cadence, matched to the 1s WS tick
// This build is deployed to polyauto. The production dashboard owns the live
// gate; the UI must reflect that gate instead of hard-locking live controls as
// the isolated polytest build did.
const POLYTEST_PAPER_ONLY = false;

export default function App() {
  const [state, setState] = useState<State | null>(null);
  const llmUsage: LlmUsageSnapshot | null = state?.llm?.usage ?? null;
  const [err, setErr] = useState<string | null>(null);
  const [now, setNow] = useState<number>(Date.now() / 1000);
  const [flash, setFlash] = useState<boolean>(false);
  const [lastFlashAt, setLastFlashAt] = useState<number>(0);
  const [showSettings, setShowSettings] = useState<boolean>(false);
  const [activeModal, setActiveModal] = useState<'positions' | 'orders' | 'orders-all' | 'pnl-history' | 'consensus-history' | 'decisions' | 'agent' | 'product' | null>(null);
  const [activeProduct, setActiveProduct] = useState<string>('BTC');
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
    let retry = 0;
    const applyState = (s: State) => {
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
    };
    const startPolling = () => {
      if (pollId != null || cancelled) return;
      setTransport('rest');
      const tick = async () => {
        try { applyState(await fetchState()); }
        catch (e) { if (!cancelled) setErr(String(e)); }
      };
      tick();
      pollId = window.setInterval(tick, POLL_MS);
    };
    const stopPolling = () => {
      if (pollId != null) { window.clearInterval(pollId); pollId = null; }
    };
    let lastFrameAt = 0;
    const connect = () => {
      if (cancelled) return;
      let socket: WebSocket;
      try {
        const proto = window.location.protocol === 'https:' ? 'wss' : 'ws';
        socket = new WebSocket(`${proto}://${window.location.host}/api/ws/state`);
      } catch { startPolling(); return; }
      ws = socket;
      socket.onopen = () => { retry = 0; lastFrameAt = Date.now(); stopPolling(); setTransport('ws'); };
      socket.onmessage = (event) => {
        lastFrameAt = Date.now();
        try { applyState(JSON.parse(event.data)); } catch { /* skip bad frame */ }
      };
      socket.onerror = () => { try { socket.close(); } catch { /* already closed */ } };
      socket.onclose = () => {
        if (cancelled) return;
        startPolling(); // never leave the board blind while reconnecting
        const delay = Math.min(15000, 1000 * 2 ** Math.min(retry++, 4));
        window.setTimeout(connect, delay);
      };
    };
    // Watchdog: a socket that stalls without closing (proxy hiccup, frozen
    // producer) is force-closed after 3.5s of silence so the reconnect +
    // polling fallback path takes over immediately.
    const watchdog = window.setInterval(() => {
      if (ws && ws.readyState === WebSocket.OPEN && lastFrameAt && Date.now() - lastFrameAt > 2000) {
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
    if (POLYTEST_PAPER_ONLY || state?.paper_only) {
      setLiveMessage('PolyDex 测试实例仅允许 Paper，实盘路径已锁定。');
      return;
    }
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
    if (POLYTEST_PAPER_ONLY || state?.paper_only) {
      setLiveMessage('PolyDex 测试实例仅允许 Paper，实盘资格已锁定。');
      return;
    }
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
  const realizedCapFraction = state?.config.max_daily_realized_profit_fraction ?? 0;
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
      {/* Trade flash is a background notification; never let it cover or
          momentarily black out an open data modal. */}
      {flash && !activeModal && <div className="flash-screen" />}
      <div className="terminal-shell" style={shellStyle}>
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
          paperServices={state?.paper_services}
          serviceBusy={serviceBusy}
          onToggleService={toggleService}
          riskConfig={{ maxDailyLossFraction: state?.config.max_daily_loss_fraction, maxDailyRealizedProfitFraction: state?.config.max_daily_realized_profit_fraction, paperEquityUsd: state?.mode_split?.paper?.capital_base_usd, kellySizingEnabled: state?.kelly_sizing_enabled }}
          musicEnabled={musicEnabled}
          onToggleMusic={toggleMusic}
          llmUsage={llmUsage || state?.llm?.usage || null}
          llmModels={state?.llm?.settings}
        />

        <KpiStrip state={state} totalEquity={totalEquity} winRate={winRate} onPositions={() => setActiveModal('positions')} onPnlHistory={() => setActiveModal('pnl-history')} />

        <PencilDashboard state={state} onPositions={() => setActiveModal('positions')} onDecisions={() => setActiveModal('decisions')} onOrdersAll={() => setActiveModal('orders-all')} onConsensusHistory={() => setActiveModal('consensus-history')} onAssetClick={(asset) => { setActiveProduct(asset); setActiveModal('product'); }} />

        <details className="legacy-details">
          <summary>详细监控与策略 / 实时数据</summary>
        <div className="terminal-grid" style={compactLayout ? compactGridStyle : gridStyle}>
          <div style={compactLayout ? compactLeftColStack : colStack}>
            <Panel title="钱包 / 资产">
              <Row k="钱包绑定" v={state?.wallet.binding?.status ?? (state?.wallet.deposit ? '已绑定' : '未绑定')} colored={state?.wallet.binding?.bound ? 1 : -1} relaxed />
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
              <Row k="每日止盈上限" v={realizedCapFraction > 0 ? fmtPct(realizedCapFraction * 100) : '关闭'} mono />
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
      {activeModal === 'positions' && (
        <DataModal title="当前持仓 / 待结算" onClose={() => setActiveModal(null)}>
          {!!state?.paper_positions?.length && <>
            <div className="settled-position-note">模拟仓（未结算 paper 入场，合计 {fmtUsd(state.paper_positions.reduce((sum, p) => sum + (p.notional_usd || 0), 0))}）：</div>
            <PaperPositionsTable rows={state.paper_positions} />
          </>}
          {(state?.positions?.length || !state?.paper_positions?.length) && <>
            {!!state?.paper_positions?.length && <div className="settled-position-note">链上持仓（实盘）：</div>}
            <PositionsTable positions={state?.positions ?? []} />
          </>}
          {!!state?.settled_positions?.length && <>
            <div className="settled-position-note">已结算 / 待赎回：{state.settled_positions.length} 条。它们不会计入当前风险敞口。</div>
            <PositionsTable positions={state.settled_positions} />
          </>}
        </DataModal>
      )}
      {activeModal === 'orders' && (
        <DataModal title="订单 // 最近" onClose={() => setActiveModal(null)}>
          <OrdersTable orders={state?.orders ?? []} />
        </DataModal>
      )}
      {activeModal === 'decisions' && (
        <DataModal title="决策日志 // 详情" onClose={() => setActiveModal(null)}>
          <DecisionsTable decisions={state?.decisions ?? []} />
        </DataModal>
      )}
      {activeModal === 'orders-all' && (
        <OrdersAllModal onClose={() => setActiveModal(null)} />
      )}
      {activeModal === 'pnl-history' && (
        <PnlHistoryModal lane={state?.bot_mode === 'live' ? 'live' : 'paper'} onClose={() => setActiveModal(null)} />
      )}
      {activeModal === 'consensus-history' && (
        <ConsensusHistoryModal onClose={() => setActiveModal(null)} />
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
const CAT_PERIODS = ['今日', '7日', '30日', '累计'] as const;

type DashboardAsset = {
  id: string;
  label: string;
  category: string;
  color: string;
  value: number | null;
  live: boolean;
  entry?: AssetRegistryEntry;
};

const BUILTIN_ASSET_COLORS: Record<string, string> = {
  BTC: '#f5c451',
};

function registryEntries(state: State | null): AssetRegistryEntry[] {
  const raw = state?.asset_registry;
  if (!raw) return [];
  if (Array.isArray(raw)) return raw.flatMap((entry) => {
    const id = entry.id || entry.asset;
    return id ? [{ ...entry, id }] : [];
  });
  return Object.entries(raw).map(([id, entry]) => ({ id, ...(entry || {}) }));
}

function dashboardAssets(state: State | null): DashboardAsset[] {
  const builtins: DashboardAsset[] = [
    { id: 'BTC', label: 'BTC', category: '加密资产', color: BUILTIN_ASSET_COLORS.BTC, value: state?.btc_signal?.current_price ?? null, live: false },
  ];
  return builtins.map((asset) => ({ ...asset, live: POLYTEST_PAPER_ONLY ? false : serviceIsLive(state, asset.id) }));
}

function PencilDashboard({ state, onPositions, onDecisions, onOrdersAll, onConsensusHistory, onAssetClick }: { state: State | null; onPositions: () => void; onDecisions: () => void; onOrdersAll: () => void; onConsensusHistory: () => void; onAssetClick: (asset: string) => void }) {
  const assets = dashboardAssets(state);
  const [activeAsset, setActiveAsset] = useState<string>('BTC');
  // Period selectors are asset-group aware: price assets window the chart,
  // daily-cadence assets (weather/sports) aggregate lot-accounted day rows.
  const [pricePeriod, setPricePeriod] = useState<(typeof PRICE_PERIODS)[number]>('实时');
  const [catPeriod, setCatPeriod] = useState<(typeof CAT_PERIODS)[number]>('今日');
  const isPriceAsset = true;
  const priceSince = pricePeriod === '实时' ? null
    : pricePeriod === '15分' ? Date.now() / 1000 - 900
    : pricePeriod === '1时' ? Date.now() / 1000 - 3600
    : (state?.pnl?.period_start_ts ?? null);
  const risk = state?.risk_snapshot;
  const activeDescriptor = assets.find((asset) => asset.id === activeAsset) || assets[0];
  const selectedLabel = activeDescriptor?.label || activeAsset;
  const selectedMode = activeDescriptor?.live ? 'LIVE' : 'PAPER';
  void onPositions;
  return <div className="pencil-board-main">
    <div className="pencil-analysis-grid">
      <section className="pencil-panel pencil-chart-panel">
        <div className="pencil-panel-title"><span>组合净值 / {selectedLabel} {selectedMode}</span>
          <span className="pencil-period" role="tablist" aria-label="时间段">
            {(isPriceAsset ? PRICE_PERIODS : CAT_PERIODS).map((p) => (
              <button key={p} type="button"
                className={(isPriceAsset ? pricePeriod : catPeriod) === p ? 'active' : ''}
                onClick={() => { if (isPriceAsset) setPricePeriod(p as (typeof PRICE_PERIODS)[number]); else setCatPeriod(p as (typeof CAT_PERIODS)[number]); }}>
                {p}
              </button>
            ))}
          </span>
        </div>
        <div className="pencil-asset-tabs" role="tablist" aria-label="组合资产分类">
          {assets.map((asset) => <button key={asset.id} type="button" role="tab" aria-selected={activeAsset === asset.id} className={activeAsset === asset.id ? 'active' : ''} onClick={() => setActiveAsset(asset.id)}>{asset.label} <small>{asset.live ? 'LIVE' : 'PAPER'}</small></button>)}
        </div>
        {activeAsset === 'BTC' && <PortfolioChart state={state} asset="BTC" history={state?.btc_price_history} sinceTs={priceSince} />}
      </section>
      <div className="pencil-side-stack">
        <section className="pencil-panel pencil-orders-panel pencil-decisions-clickable" onClick={onDecisions} role="button" tabIndex={0} onKeyDown={(event) => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); onDecisions(); } }}>
          <div className="pencil-panel-title">决策日志 // 实时</div>
          <DecisionLogPreview state={state} />
        </section>
        <section className="pencil-panel pencil-prob-panel"><div className="pencil-panel-title">概率预测 / 双模型复核</div><ProbabilityPanel state={state} /></section>
      </div>
    </div>
    <div className="pencil-risk-row">
      {(() => {
        const lane: 'paper' | 'live' = state?.bot_mode === 'live' ? 'live' : 'paper';
        const base = state?.mode_split?.[lane]?.capital_base_usd ?? Math.max(1, state?.wallet.balance_pusd ?? 1);
        // 熔断只计亏损：与 worker risk.allowed_to_trade 同口径（pnl <= -limit 才停）。
        // 盈利日 pnl>0 消耗 0 亏损额度，不能用 abs 把当日盈利错当亏损显示。
        const dailyPnl = risk?.daily_realized_usd ?? 0;
        const lossFrac = Math.max(0, -dailyPnl) / Math.max(1, base);
        const limitFrac = risk?.max_daily_loss_fraction ?? 0.05;
        const lossTone: 'green' | 'amber' = limitFrac > 0 && lossFrac >= limitFrac * 0.6 ? 'amber' : 'green';
        return <PencilMetric label="日亏损熔断" value={`${fmtPct(lossFrac * 100)} / ${fmtPct(limitFrac * 100)}`} tone={lossTone} mode={lane} />;
      })()}
      <PencilMetric label="总敞口" value={fmtUsd(risk?.position_value_usd)} tone="amber" mode={state?.bot_mode === 'live' ? 'live' : 'paper'} />
      {(() => {
        const lane = state?.mode_split?.[state?.bot_mode === 'live' ? 'live' : 'paper'];
        // `today_counts.orders` is the authoritative count from the ledger.
        // The lane summary has no guaranteed `open_count` field and using it
        // made this card show 0 even when today's order stream had activity.
        const todayN = state?.today_counts?.orders ?? ((lane?.wins ?? 0) + (lane?.losses ?? 0));
        const lifetimeN = state?.orders_total ?? 0;
        return <PencilMetric label="滑点容差 · 订单统计" value={`买 ${state?.config.fok_price_buffer_ticks ?? '--'}t / 卖 ${state?.config.sell_fok_slippage_ticks ?? '--'}t · 今 ${todayN} / 累 ${lifetimeN}`} tone="green" />;
      })()}
      <PencilMetric label="全部订单" value={String(state?.orders_total ?? '--')} tone="blue" onClick={onOrdersAll} />
      <PencilMetric
        label="模型一致性"
        value={(() => {
          const consensus = state?.slow_loop?.digest?.consensus;
          if (!consensus) return state?.llm?.usage?.models?.length ? '在线' : '--';
          const agreed = (consensus.reason || '').includes('一致');
          if (!agreed) return '分歧·持有';
          return consensus.decision === 'HOLD' ? '一致·观望' : '双模一致';
        })()}
        tone={(() => {
          const consensus = state?.slow_loop?.digest?.consensus;
          if (!consensus) return 'purple';
          return (consensus.reason || '').includes('一致') ? 'green' : 'amber';
        })()}
        onClick={onConsensusHistory}
      />
    </div>
    <div className="pencil-assets-row">{assets.map(({ id: name, label, value, color, live, entry }) => {
      // The card's numbers follow its own lane; prefer the backend's full-day
      // per-asset summary (the 30-order response window drops older fills),
      // falling back to the local derivation for older servers.
      const assetKey = name;
      const fromLane = (lane: 'paper' | 'live') => {
        const ba = state?.mode_split?.[lane]?.cumulative_by_asset?.[assetKey]
          ?? state?.mode_split?.[lane]?.by_asset?.[assetKey];
        if (!ba) return null;
        const wins = ba.wins ?? 0; const losses = ba.losses ?? 0;
        return { profit: ba.realized_usd ?? 0, wins, losses, rate: wins + losses ? wins / (wins + losses) * 100 : null };
      };
      const perf = fromLane(live ? 'live' : 'paper') ?? assetPerformance(state?.orders || [], name, !live);
      const alt = fromLane(live ? 'paper' : 'live') ?? assetPerformance(state?.orders || [], name, !!live);
      const altLabel = live ? '模拟' : '实盘';
      const labelValue = entry?.pnl_usd != null ? fmtSignedUsd(entry.pnl_usd) : typeof value === 'number' ? fmtUsd(value) : '--';
      return <button type="button" className="pencil-asset-card pencil-asset-card-clickable" key={name} style={{ '--pencil-accent': color } as CSSProperties} onClick={() => onAssetClick(assetKey)} aria-label={`查看${label}模拟和实盘数据`}>
        <span>{label} · {live ? 'LIVE' : 'PAPER'}</span>
        <b>{labelValue}</b>
        <small>{(() => {
          return entry?.status || entry?.category || 'Paper 监控';
        })()}</small>
        {assetKey === 'BTC' && <small className="asset-stop-loss">止损 {state?.stop_loss?.[assetKey]?.status ?? '--'}</small>}
        <em className={perf.profit >= 0 ? 'asset-profit-positive' : 'asset-profit-negative'}>{live ? '实盘' : '模拟'}累计盈亏 {entry?.pnl_usd != null ? fmtSignedUsd(entry.pnl_usd) : fmtSignedUsd(perf.profit)} · 胜率 {entry?.win_rate != null ? `${Number(entry.win_rate).toFixed(1)}%` : perf.rate == null ? '--' : `${perf.rate.toFixed(1)}%`}</em>
        {(alt.wins + alt.losses) > 0 && <small className="asset-alt">{altLabel} {fmtSignedUsd(alt.profit)} · {alt.rate == null ? '--' : `${alt.rate.toFixed(1)}%`}</small>}
      </button>;
    })}</div>
  </div>;
}

function serviceIsLive(state: State | null, asset: string) {
  if (POLYTEST_PAPER_ONLY || state?.paper_only) return false;
  const info = state?.service_modes?.[asset];
  if (info?.live_enabled != null) return info.live_enabled === true;
  if (info?.mode) return info.mode.toLowerCase() === 'live';
  return state?.bot_mode === 'live' && asset === 'BTC';
}

function fmtSignedUsd(value: number) {
  if (!Number.isFinite(value) || Math.abs(value) < 0.005) return '$0.00';
  return `${value >= 0 ? '+' : '-'}$${Math.abs(value).toFixed(2)}`;
}

/** Derive per-market performance from settled order outcomes. Unresolved orders
 * intentionally remain neutral so the card never presents an invented PnL.
 * `paperOnly` selects the dry-run lane so paper and live results never mix. */
function assetPerformance(orders: Order[], asset: string, paperOnly = true) {
  const key = asset.toUpperCase() === '天气' ? 'WEATHER' : asset.toUpperCase() === '体育' ? 'SPORTS' : asset.toUpperCase();
  let profit = 0; let wins = 0; let losses = 0;
  for (const order of orders) {
    if ((order.dry_run !== 0) !== paperOnly) continue;
    const orderAsset = String(order.asset || '').toUpperCase();
    if (orderAsset !== key) continue;
    const result = String(order.result || '').toUpperCase();
    const size = Number(order.filled_size || order.size || 0);
    const price = Number(order.price || 0);
    if (!Number.isFinite(size) || !Number.isFinite(price)) continue;
    if (result === 'HIT' || result === 'WON' || result === 'EXITED' || result === 'PARTIAL_EXIT') {
      profit += Number.isFinite(Number(order.pnl)) ? Number(order.pnl) : size * Math.max(0, 1 - price); wins += 1;
    } else if (result === 'MISS' || result === 'LOST' || result === 'FAILED' || result === 'EXIT_FAILED') {
      profit += Number.isFinite(Number(order.pnl)) ? Number(order.pnl) : -size * Math.max(0, price); losses += 1;
    }
  }
  const total = wins + losses;
  return { profit, wins, losses, rate: total ? wins / total * 100 : null };
}

/** Per-asset daily rows cache (lot-accounted, from /api/pnl/daily?asset=). */
const catDailyCache: Record<string, { ts: number; rows: Array<{ day: string; pnl_usd: number; wins: number; losses: number }> }> = {};

export function CategoryOverview({ state, asset, period }: { state: State | null; asset: 'WEATHER' | 'SPORTS'; period: (typeof CAT_PERIODS)[number] }) {
  const count = asset === 'WEATHER' ? (state?.weather?.length ?? 0) : (state?.sports?.length ?? 0);
  const mode = serviceIsLive(state, asset) ? 'live' : 'paper';
  const kw = state?.feeds?.kalshi_weather;
  const od = state?.feeds?.odds;
  const [dailyRows, setDailyRows] = useState<Array<{ day: string; pnl_usd: number; wins: number; losses: number }>>(
    () => catDailyCache[asset]?.rows ?? [],
  );
  useEffect(() => {
    const hit = catDailyCache[asset];
    if (hit && Date.now() - hit.ts < 60000) { setDailyRows(hit.rows); return; }
    let cancelled = false;
    fetchPnlDaily('paper', 0, 60, asset)
      .then((r) => { if (!cancelled) { catDailyCache[asset] = { ts: Date.now(), rows: r.rows }; setDailyRows(r.rows); } })
      .catch(() => { /* keep whatever we had; feed rows still render */ });
    return () => { cancelled = true; };
  }, [asset]);
  const span = period === '今日' ? 1 : period === '7日' ? 7 : period === '30日' ? 30 : dailyRows.length;
  const sel = dailyRows.slice(0, Math.max(span, 0));
  const pnl = sel.reduce((s, r) => s + r.pnl_usd, 0);
  const wins = sel.reduce((s, r) => s + r.wins, 0);
  const losses = sel.reduce((s, r) => s + r.losses, 0);
  const rate = wins + losses ? wins / (wins + losses) * 100 : null;
  const cityCount = Math.max(count, 1);
  const events = od?.events_cached ?? count;
  const stadiums = Math.min(12, Math.max(1, Math.ceil(events / 10)));
  return <div className="category-overview">
    {asset === 'WEATHER' ? (
      <div className="cat-scene weather-scene" aria-label={`天气监控 ${count} 座城市`}>
        <i className="ws-sun" />
        <i className="ws-cloud ws-c1" />
        <i className="ws-cloud ws-c2" />
        <i className="ws-cloud ws-c3" />
        <span className="scene-badge">{count} 城监控</span>
        <div className="city-skyline" aria-hidden="true">
          {Array.from({ length: Math.min(cityCount, 8) }).map((_, i) => (
            <i key={i} className={`city-icon city-h${(i % 3) + 1}`} />
          ))}
        </div>
        <small className="scene-caption">每座剪影 = 一座监控城市 · Open-Meteo 集合模型 × Kalshi 温度盘</small>
      </div>
    ) : (
      <div className="cat-scene sports-scene" aria-label={`体育共识 ${events} 场`}>
        <i className="sp-ball" />
        <i className="sp-shadow" />
        <span className="scene-badge">{events} 场共识</span>
        <div className="stadium-grid" aria-hidden="true">
          {Array.from({ length: stadiums }).map((_, i) => (
            <i key={i} className="stadium-icon" style={{ animationDelay: `${i * 0.18}s` }} />
          ))}
        </div>
        <small className="scene-caption">每座场馆 ≈ 10 场博彩共识赛事 · 已匹配 {od?.matches ?? 0} · PM 监控 {count}</small>
      </div>
    )}
    <div className="category-overview-stats">
      <span>模式 <b>{mode.toUpperCase()}</b></span>
      <span>{period}盈亏 <b className={pnl >= 0 ? 'asset-profit-positive' : 'asset-profit-negative'}>{fmtSignedUsd(pnl)}</b></span>
      <span>{period}胜率 <b>{rate == null ? '--' : `${rate.toFixed(1)}%`}</b><small className="cat-wl"> {wins}/{losses}</small></span>
    </div>
    {asset === 'WEATHER' && kw?.scanned != null && (
      <div className="category-overview-stats category-feed-stats">
        <span>Kalshi 扫描 <b>{kw.scanned}</b></span>
        <span>有价 <b className={(kw.quoted ?? 0) > 0 ? 'asset-profit-positive' : ''}>{kw.quoted ?? 0}</b></span>
        <span>新结算 <b>{kw.settled_new ?? 0}</b></span>
      </div>
    )}
    {asset === 'SPORTS' && od?.events_cached != null && (
      <div className="category-overview-stats category-feed-stats">
        <span>已匹配 <b className={(od.matches ?? 0) > 0 ? 'asset-profit-positive' : ''}>{od.matches ?? 0}</b></span>
        <span>PM 监控 <b>{count}</b></span>
        <span>额度 <b>{od.remaining ?? '--'}</b></span>
      </div>
    )}
  </div>;
}

/** Compact read-only view for P3 instruments that do not have a specialised
 * price chart or weather/sports scene yet.  It deliberately renders the
 * registry snapshot instead of inventing a quote or a settled result. */
export function GenericCategoryOverview({ state, asset, period }: { state: State | null; asset?: DashboardAsset; period: (typeof CAT_PERIODS)[number] }) {
  if (!asset) return <Empty>暂无 P3 市场注册信息</Empty>;
  const id = asset.id;
  const paper = state?.mode_split?.paper?.cumulative_by_asset?.[id] ?? state?.mode_split?.paper?.by_asset?.[id];
  const orders = (state?.orders || []).filter((order) => String(order.asset || '').toUpperCase() === id.toUpperCase() && order.dry_run !== 0);
  const marketCount = Number(asset.entry?.market_count ?? asset.entry?.markets ?? 0);
  const pnl = asset.entry?.pnl_usd ?? paper?.realized_usd ?? assetPerformance(orders, id, true).profit;
  const wins = paper?.wins ?? (asset.entry?.win_rate != null ? Math.round((asset.entry.win_rate / 100) * orders.length) : 0);
  const losses = paper?.losses ?? Math.max(0, orders.length - wins);
  const rate = asset.entry?.win_rate ?? (wins + losses ? wins / (wins + losses) * 100 : null);
  const category = asset.entry?.category || asset.category || 'P3 市场';
  return <div className="category-overview generic-category-overview">
    <div className="p3-market-hero" style={{ '--p3-accent': asset.color } as CSSProperties}>
      <span className="scene-badge">{category}</span>
      <strong>{asset.label}</strong>
      <small>{asset.entry?.status || 'Paper 监控中'} · {marketCount} 个市场</small>
      <i className="p3-market-grid" aria-hidden="true" />
    </div>
    <div className="category-overview-stats">
      <span>模式 <b>PAPER</b></span>
      <span>{period}盈亏 <b className={Number(pnl) >= 0 ? 'asset-profit-positive' : 'asset-profit-negative'}>{fmtSignedUsd(Number(pnl) || 0)}</b></span>
      <span>{period}胜率 <b>{rate == null ? '--' : `${Number(rate).toFixed(1)}%`}</b><small className="cat-wl"> {wins}/{losses}</small></span>
    </div>
    <div className="category-overview-stats category-feed-stats">
      <span>市场发现 <b>{marketCount}</b></span>
      <span>Paper 订单 <b>{orders.length}</b></span>
      <span>实盘 <b>已锁定</b></span>
    </div>
  </div>;
}

function ProductDetailModal({ asset, state, onClose }: { asset: string; state: State | null; onClose: () => void }) {
  const [paperOrders, setPaperOrders] = useState<Order[]>([]);
  const [liveOrders, setLiveOrders] = useState<Order[]>([]);
  const [days, setDays] = useState<Array<{ day: string; pnl_usd: number; wins: number; losses: number }>>([]);
  const [loading, setLoading] = useState(true);
  const label = asset === 'WEATHER' ? '天气' : asset === 'SPORTS' ? '体育' : (registryEntries(state).find((entry) => entry.id === asset)?.label || asset);
  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    Promise.all([
      fetchOrdersPage(0, 30, 'paper', asset),
      fetchOrdersPage(0, 30, 'live', asset),
      fetchPnlDaily('paper', 0, 365, asset),
    ]).then(([paperPage, livePage, pnlPage]) => {
      if (!cancelled) { setPaperOrders(paperPage.rows || []); setLiveOrders(livePage.rows || []); setDays(pnlPage.rows || []); }
    }).catch(() => {
      if (!cancelled) { setPaperOrders([]); setLiveOrders([]); setDays([]); }
    }).finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [asset]);
  const paper = state?.mode_split?.paper?.cumulative_by_asset?.[asset] || {};
  const live = state?.mode_split?.live?.cumulative_by_asset?.[asset] || {};
  const today = state?.mode_split?.paper?.by_asset?.[asset] || {};
  const paperTotal = (paper.wins ?? 0) + (paper.losses ?? 0);
  const liveTotal = (live.wins ?? 0) + (live.losses ?? 0);
  return <DataModal title={`${label} / 模拟与实盘数据`} onClose={onClose}>
    <div className="product-detail-grid">
      <div className="product-detail-lane product-detail-paper"><h3>{label} · PAPER</h3><Row k="累计盈亏" v={fmtSignedUsd(paper.realized_usd ?? 0)} colored={paper.realized_usd} relaxed /><Row k="累计胜率" v={paperTotal ? fmtPct((paper.wins ?? 0) / paperTotal * 100) : '--'} relaxed /><Row k="胜 / 负" v={`${paper.wins ?? 0} / ${paper.losses ?? 0}`} relaxed /><Row k="今日盈亏" v={fmtSignedUsd(today.realized_usd ?? 0)} colored={today.realized_usd} relaxed /><Row k="当前待结算" v={String(today.pending ?? 0)} relaxed /></div>
      <div className="product-detail-lane product-detail-live"><h3>{label} · LIVE</h3><Row k="累计盈亏" v={fmtSignedUsd(live.realized_usd ?? 0)} colored={live.realized_usd} relaxed /><Row k="累计胜率" v={liveTotal ? fmtPct((live.wins ?? 0) / liveTotal * 100) : '--'} relaxed /><Row k="胜 / 负" v={`${live.wins ?? 0} / ${live.losses ?? 0}`} relaxed /><Row k="实盘资格" v="测试实例已锁定" relaxed /><Row k="当前订单" v="测试实例不产生实盘订单" relaxed /></div>
    </div>
    <div className="product-detail-section"><h3>{label} · Paper 最近记录</h3>{loading ? <Empty>加载中…</Empty> : paperOrders.length ? <OrdersTable orders={paperOrders.slice(0, 12)} /> : <Empty>暂无 Paper 订单；历史汇总仍以账本为准。</Empty>}</div>
    <div className="product-detail-section"><h3>{label} · Live 最近记录</h3>{loading ? <Empty>加载中…</Empty> : liveOrders.length ? <OrdersTable orders={liveOrders.slice(0, 12)} /> : <Empty>暂无 Live 订单或实盘尚未开启。</Empty>}</div>
    <div className="product-detail-section"><h3>{label} · Paper 日结算</h3>{days.length ? <div className="product-daily-list">{days.slice(0, 14).map((row) => <div key={row.day}><span>{row.day}</span><b className={row.pnl_usd >= 0 ? 'asset-profit-positive' : 'asset-profit-negative'}>{fmtSignedUsd(row.pnl_usd)}</b><small>{row.wins} 胜 / {row.losses} 负</small></div>)}</div> : <Empty>暂无已结算记录</Empty>}</div>
  </DataModal>;
}

function DecisionLogPreview({ state }: { state: State | null }) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const [visibleRows, setVisibleRows] = useState(3);
  const [windowStart, setWindowStart] = useState(0);
  const [isUpdating, setIsUpdating] = useState(false);
  const allDecisions = state?.decisions || [];
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

function PortfolioChart({ state, asset = 'BTC', history, sinceTs }: { state: State | null; asset?: 'BTC' | 'ETH'; history?: PriceHistoryPoint[]; sinceTs?: number | null }) {
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
  const signal = asset === 'ETH' ? state?.eth_signal : state?.btc_signal;
  const market = asset === 'ETH' ? state?.eth_market : state?.market;
  const bookUp = asset === 'ETH' ? state?.eth_book_up : state?.book_up;
  const bookDown = asset === 'ETH' ? state?.eth_book_down : state?.book_down;
  const delta = signal?.delta_usd;
  // Direction word mirrors the worker's own signal side; fall back to the
  // delta sign so the label never contradicts the number next to it.
  const sideWord = signal ? (signal.signal_side === 'UP' ? '上涨' : signal.signal_side === 'DOWN' ? '下跌' : delta != null && delta !== 0 ? (delta > 0 ? '上涨' : '下跌') : '持平') : null;
  const tRem = market ? Math.max(0, market.end_ts - Date.now() / 1000) : null;
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
    <div className="volume-bars" aria-label="实时盈亏柱形"><span className="sr-only">绿色为盈利，红色为亏损</span>{points.slice(-24).map((p, i) => { const pnl = Number(p.delta_usd || 0); return <i key={`${p.ts}-${i}`} className={pnl >= 0 ? 'pnl-positive' : 'pnl-negative'} title={`${pnl >= 0 ? '盈利' : '亏损'} ${fmtUsd(Math.abs(pnl))}`} style={{ height: `${Math.max(8, Math.min(100, Math.abs(pnl) * 4 + 8))}%` }} />; })}</div>
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

function ProbabilityPanel({ state }: { state: State | null }) {
  const rows = [
    ['BTC 上涨', state?.btc_signal ? Math.max(0, Math.min(1, 0.5 + state.btc_signal.delta_usd / 200)) : null, '#f4b942'],
    ['BTC 下跌', state?.btc_signal ? Math.max(0, Math.min(1, 0.5 - state.btc_signal.delta_usd / 200)) : null, '#f05b68'],
  ] as const;
  return <div className="probability-panel">{rows.map(([label, probability, color]) => <div className="probability-row" key={label}><span>{label}</span><div className="probability-track"><i style={{ width: `${(probability ?? 0) * 100}%`, background: color }} /></div><b>{probability == null ? '--' : fmtPct(probability * 100)}</b></div>)}</div>;
}

type KpiMode = 'paper' | 'live' | 'chain';

function ModeChip({ mode }: { mode: KpiMode }) {
  const label = mode === 'live' ? '实盘' : mode === 'chain' ? '链上' : '模拟';
  return <i className={`kpi-mode kpi-mode-${mode}`}>{label}</i>;
}

function KpiStrip({ state, totalEquity, winRate, onPositions, onPnlHistory }: { state: State | null; totalEquity: number | null; winRate: number | null; onPositions: () => void; onPnlHistory: () => void }) {
  void winRate; // cumulative win rate is read from the lane ledger below
  const activeMode: KpiMode = state?.bot_mode === 'live' ? 'live' : 'paper';
  const otherLabel = activeMode === 'live' ? '模拟' : '实盘';
  const paperLane = state?.mode_split?.paper;
  const liveLane = state?.mode_split?.live;
  const paperToday = paperLane?.realized_usd ?? 0;
  const liveToday = liveLane?.realized_usd ?? 0;
  const laneTodaySummary = `PAPER ${fmtSignedUsd(paperToday)} · LIVE ${fmtSignedUsd(liveToday)} · 待结算 ${paperLane?.pending ?? 0}/${liveLane?.pending ?? 0}`;
  const other = state?.mode_split?.[activeMode === 'live' ? 'paper' : 'live'];
  // Only surface the other lane when it actually has activity today.
  const otherBusy = !!other && (
    Math.abs(other.realized_usd ?? 0) > 0.005
    || (other.wins ?? 0) + (other.losses ?? 0) > 0
    || (other.pending ?? 0) > 0
    || (other.open_value_usd ?? 0) > 0.005
  );
  const altPnl = otherBusy ? `${otherLabel} ${fmtSignedUsd(other?.realized_usd ?? 0)}` : undefined;
  const pnl = state?.pnl?.realized_usd ?? null;
  const cumulative = state?.mode_split?.[activeMode]?.cumulative_realized_usd ?? pnl;
  const cumulativeWins = state?.mode_split?.[activeMode]?.cumulative_wins ?? state?.pnl?.wins ?? 0;
  const cumulativeLosses = state?.mode_split?.[activeMode]?.cumulative_losses ?? state?.pnl?.losses ?? 0;
  const todayWins = state?.pnl?.wins ?? 0;
  const todayLosses = state?.pnl?.losses ?? 0;
  const todayTotal = todayWins + todayLosses;
  // Return%% divides by the ACTIVE lane's capital base (paper equity for the
  // paper lane -- the same number the worker's risk gate uses), never by the
  // chain balance while simulating.
  const capitalBase = state?.mode_split?.[activeMode]?.capital_base_usd ?? totalEquity;
  // The headline cards are explicitly "today" metrics.  The backend applies
  // the Asia/Shanghai day boundary; use that active lane value here instead
  // of the lifetime cumulative ledger used by the detail views.
  const returnPct = capitalBase && capitalBase > 0 && pnl != null ? pnl / capitalBase * 100 : null;
  const openValue = activeMode === 'paper'
    ? state?.mode_split?.paper?.open_value_usd
    : state?.wallet.value_usd;
  const items: Array<{ label: string; value: string; tone?: number | null; sub?: string; mode?: KpiMode; onClick?: () => void }> = [
    { label: '账户余额', value: fmtUsd(state?.wallet.balance_pusd), mode: 'chain' },
    { label: activeMode === 'paper' ? '模拟持仓成本' : '持仓市值', value: fmtUsd(openValue), mode: activeMode, onClick: onPositions, sub: otherBusy && (other?.open_value_usd ?? 0) > 0.005 ? `${otherLabel} ${fmtUsd(other?.open_value_usd)}` : '点击查看持仓' },
    { label: '待结算', value: String(state?.pnl?.pending ?? 0), mode: activeMode, onClick: onPositions, sub: `PAPER ${paperLane?.pending ?? 0} · LIVE ${liveLane?.pending ?? 0}` },
    { label: '累计盈亏', value: fmtUsd(cumulative), tone: cumulative, mode: activeMode, onClick: onPnlHistory, sub: `今日 ${fmtSignedUsd(pnl ?? 0)}${altPnl ? ` ｜ ${altPnl}` : ''}` },
    { label: '收益率', value: fmtPct(returnPct), tone: returnPct, mode: activeMode, onClick: onPnlHistory, sub: `${capitalBase ? `今日 / ${activeMode === 'live' ? '权益' : '本金'} ${fmtUsd(capitalBase)}` : '今日'} · 累计 ${fmtPct(capitalBase && capitalBase > 0 && cumulative != null ? cumulative / capitalBase * 100 : null)}` },
    { label: '胜率', value: fmtPct(todayTotal ? todayWins / todayTotal * 100 : null), tone: todayTotal ? todayWins / todayTotal * 100 : null, mode: activeMode, onClick: onPnlHistory, sub: `今日胜 / 负 ${todayWins} / ${todayLosses} · 累计 ${cumulativeWins} / ${cumulativeLosses}` },
    {
      label: '今日损益 · PAPER / LIVE',
      value: `P ${fmtUsd(paperToday)} / L ${fmtUsd(liveToday)}`,
      tone: paperToday < 0 || liveToday < 0 ? -1 : paperToday > 0 || liveToday > 0 ? 1 : 0,
      mode: activeMode,
      onClick: onPnlHistory,
      sub: `已结算 ${paperLane?.wins ?? 0}/${liveLane?.wins ?? 0} 胜 · ${laneTodaySummary}`,
    },
  ] as const;
  return <div className="kpi-strip" aria-label="账户关键指标">
    {items.map((item) => <div className={`kpi-card${item.onClick ? ' kpi-card-clickable' : ''}${item.label.startsWith('今日损益') ? ' kpi-card-pnl' : ''}`} key={item.label} onClick={item.onClick} role={item.onClick ? 'button' : undefined} tabIndex={item.onClick ? 0 : undefined} onKeyDown={item.onClick ? (event) => { if (event.key === 'Enter' || event.key === ' ') item.onClick?.(); } : undefined}>
      {item.mode && <ModeChip mode={item.mode} />}
      <span className="kpi-label">{item.label}</span><strong className={item.tone == null ? '' : item.tone >= 0 ? 'kpi-positive' : 'kpi-negative'}>{item.value}</strong>{item.sub && <small className="kpi-sub">{item.sub}</small>}
    </div>)}
  </div>;
}

function RiskSnapshotPanel({ snapshot, riskState }: { snapshot?: State['risk_snapshot']; riskState?: string }) {
  const state = snapshot?.state || riskState || 'UNKNOWN';
  const tone = state === 'OK' ? 1 : state === 'UNKNOWN' ? null : -1;
  return <div className="risk-snapshot-panel">
    <Row k="风险闸门" v={zhText(state)} colored={tone} relaxed />
    <Row k="当前持仓" v={String(snapshot?.position_count ?? 0)} relaxed />
    <Row k={snapshot?.valuation === 'entry_cost' ? '持仓成本' : '持仓市值'} v={fmtUsd(snapshot?.position_value_usd)} relaxed />
    <Row k="未成交订单" v={String(snapshot?.open_orders ?? 0)} relaxed />
    <Row k="挂单名义" v={fmtUsd(snapshot?.open_order_notional_usd)} relaxed />
    <Row k="敞口占比" v={snapshot?.exposure_ratio == null ? '--' : fmtPct(snapshot.exposure_ratio * 100)} relaxed />
    <Row k="今日已实现" v={fmtUsd(snapshot?.daily_realized_usd)} colored={snapshot?.daily_realized_usd} relaxed />
    <Row k="亏损上限" v={snapshot?.max_daily_loss_fraction == null ? '--' : fmtPct(snapshot.max_daily_loss_fraction * 100)} dim mono relaxed />
    <Row k="持仓上限" v={String(snapshot?.max_open_positions ?? '--')} dim mono relaxed />
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

export function WeatherRealtimePanel({ weather }: { weather?: WeatherRealtime[] }) {
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

export function SportsRealtimePanel({ sports }: { sports?: SportsRealtime[] }) {
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
  operatorToken, onOperatorTokenChange, liveBusy, liveMessage, onToggleLive, serviceModes, paperServices, serviceBusy, onToggleService,
  riskConfig, llmUsage, llmModels, musicEnabled, onToggleMusic,
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
  serviceModes?: State['service_modes']; paperServices?: State['paper_services']; serviceBusy: string | null; onToggleService: (asset: string, enabled: boolean) => void;
  riskConfig?: { maxDailyLossFraction?: number; maxDailyRealizedProfitFraction?: number; paperEquityUsd?: number; kellySizingEnabled?: boolean };
  llmUsage?: LlmUsageSnapshot | null;
  llmModels?: { primary_model?: string; secondary_model?: string };
  musicEnabled: boolean;
  onToggleMusic: () => void;
}) {
  const blink = Date.now() - lastFlashAt < 5000;
  const riskOk = riskState === 'OK';
  // Paper worker 启停：乐观覆盖层吸收后端 3s 快照缓存；服务器一致后自动清除。
  const [paperBusy, setPaperBusy] = useState<string | null>(null);
  const [paperMsg, setPaperMsg] = useState('');
  const [paperOverride, setPaperOverride] = useState<Record<string, boolean>>({});
  const paperControlAvailable = paperServices != null;
  useEffect(() => {
    setPaperOverride((m) => {
      let changed = false;
      const next = { ...m };
      for (const k of Object.keys(next)) {
        if (paperServices?.[k]?.active === next[k]) { delete next[k]; changed = true; }
      }
      return changed ? next : m;
    });
  }, [paperServices]);
  const onTogglePaper = async (asset: string, enabled: boolean) => {
    if (!paperControlAvailable) {
      setPaperMsg('当前实例未提供 Paper worker 控制接口，显示为只读状态。');
      return;
    }
    if (!operatorToken) { setPaperMsg('需要操作令牌（顶栏输入）'); return; }
    if (!window.confirm(`确认${enabled ? '启动' : '停止'} ${asset} PAPER worker？${enabled ? '' : '\n停止后该产品不再产生新模拟入场，历史账目保留。'}`)) return;
    setPaperBusy(asset); setPaperMsg('');
    try {
      const res = await putPaperService(asset, enabled, operatorToken);
      setPaperOverride((m) => ({ ...m, [asset]: res.paper_active ?? enabled }));
      setPaperMsg(res.note || '');
    } catch (e) {
      setPaperMsg(e instanceof Error ? e.message : String(e));
    } finally {
      setPaperBusy(null);
    }
  };
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
  const effectiveBotMode = POLYTEST_PAPER_ONLY ? 'paper' : botMode;
  const modeChip = POLYTEST_PAPER_ONLY
    ? { label: 'PAPER ONLY', bg: '#001a0d', fg: 'var(--green)', border: 'var(--green)' }
    : effectiveBotMode === 'live'
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
        <span className="topbar-market-label">BTC 五分钟</span>
      </div>
      <LlmUsagePanel usage={llmUsage} models={llmModels} />
      <span className="topbar-mode" title={POLYTEST_PAPER_ONLY ? 'PolyDex 测试实例：所有服务仅 Paper' : undefined} style={{
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
          disabled={POLYTEST_PAPER_ONLY}
          title={POLYTEST_PAPER_ONLY ? '测试实例不接受实盘令牌' : undefined}
        />
        <button
          type="button"
          onClick={onToggleLive}
          disabled={liveBusy || POLYTEST_PAPER_ONLY}
          className={botRunning && botMode === 'live' ? 'live-stop-button' : 'live-start-button'}
          title={liveMessage || '需要实盘操作令牌'}
        >
          {POLYTEST_PAPER_ONLY ? '实盘已锁定' : liveBusy ? '处理中…' : botRunning && botMode === 'live' ? '关闭实盘' : '开启实盘'}
        </button>
        <button type="button" onPointerDown={() => onToggleMusic()} onClick={(event) => { if (event.detail === 0) onToggleMusic(); }} className={`music-toggle ${musicEnabled ? 'music-on' : ''}`} aria-pressed={musicEnabled} title="播放/暂停视频背景音乐">
          {musicEnabled ? '♫ 音乐开' : '♫ 音乐关'}
        </button>
        <details className="strategy-menu">
          <summary>策略管理</summary>
          <div className="strategy-menu-popover">
            {(['BTC'] as const).map((asset) => {
              const info = serviceModes?.[asset];
              const paperActive = paperOverride[asset] ?? paperServices?.[asset]?.active ?? info?.running;
              const bootOn = paperServices?.[asset]?.enabled;
              const label = paperActive === false ? 'Worker 已停止' : 'BTC 调度 · Worker 执行';
              return <div className="strategy-menu-row" key={asset}><b>{asset}</b>{info?.live_enabled && !POLYTEST_PAPER_ONLY
                ? <span className="strategy-live">实盘</span>
                : <button type="button" className={`paper-switch ${paperActive === false ? 'paper-off' : 'paper-on'}`} disabled={!paperControlAvailable || paperBusy === asset}
                    title={!paperControlAvailable ? '当前实例仅提供 Paper 状态读取' : operatorToken ? `点击${paperActive === false ? '启动' : '停止'} ${asset} Paper worker（开机自启：${bootOn ? '开' : '关'}）` : '需要顶栏操作令牌'}
                    onClick={() => onTogglePaper(asset, paperActive === false)}>
                    <span className="paper-knob" />{!paperControlAvailable ? 'Paper·只读' : paperBusy === asset ? '处理中…' : paperActive === false ? 'Paper·已停' : 'Paper·运行'}
                  </button>}<small>{label}</small></div>;
            })}
            {paperMsg && <div className="paper-switch-msg" title={paperMsg}>{paperMsg}</div>}
            <RiskSettingsForm riskConfig={riskConfig} operatorToken={operatorToken} />
          </div>
        </details>
        <div className="service-switches" aria-label="BTC 实盘开关">
          {(['BTC'] as const).map((asset) => {
            const info = serviceModes?.[asset]; const allowed = !POLYTEST_PAPER_ONLY && info?.can_enable_live === true; const enabled = !POLYTEST_PAPER_ONLY && info?.live_enabled === true;
            return <button key={asset} type="button" className={`service-switch ${enabled ? 'service-on' : ''}`} disabled={!allowed || serviceBusy === asset} title={allowed ? `${asset} 实盘资格开关` : `${asset} 已锁定为 Paper`} onClick={() => onToggleService(asset, !enabled)}>{asset} {enabled ? 'LIVE' : 'PAPER'}</button>;
          })}
        </div>
        {liveMessage && <span className="live-control-message" title={liveMessage}>{liveMessage}</span>}
      </div>
        <span className="topbar-clock">{fmtTime(time)}</span>
      </div>
    </div>
  );
}

/** Operator-gated editor for the worker trigger lines (daily loss circuit +
 * daily realized-profit stop).  Saving rewrites .env and restarts the paper
 * workers so the RUNNING gate matches what the panel shows. */
function RiskSettingsForm({ riskConfig, operatorToken }: { riskConfig?: { maxDailyLossFraction?: number; maxDailyRealizedProfitFraction?: number; paperEquityUsd?: number; kellySizingEnabled?: boolean }; operatorToken: string }) {
  const [lossPct, setLossPct] = useState<string>('');
  const [capPct, setCapPct] = useState<string>('');
  const [equityUsd, setEquityUsd] = useState<string>('');
  const [kelly, setKelly] = useState<boolean | null>(null); // null = untouched; only sent when toggled
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState('');
  const currentLoss = riskConfig?.maxDailyLossFraction != null ? (riskConfig.maxDailyLossFraction * 100).toFixed(0) : '--';
  const currentCap = riskConfig?.maxDailyRealizedProfitFraction != null ? riskConfig.maxDailyRealizedProfitFraction * 100 : null;
  const currentEquity = riskConfig?.paperEquityUsd != null ? riskConfig.paperEquityUsd : null;
  const currentKelly = riskConfig?.kellySizingEnabled;
  const kellyEffective = kelly != null ? kelly : (currentKelly ?? false);
  const save = async () => {
    if (!operatorToken.trim()) { setMsg('请先在顶栏填写实盘操作令牌'); return; }
    const payload: { max_daily_loss_fraction?: number; max_daily_realized_profit_fraction?: number; paper_equity_usd?: number; kelly_sizing_enabled?: boolean; restart_workers: boolean } = { restart_workers: true };
    if (lossPct.trim() !== '') payload.max_daily_loss_fraction = Number(lossPct) / 100;
    if (capPct.trim() !== '') payload.max_daily_realized_profit_fraction = Number(capPct) / 100;
    if (equityUsd.trim() !== '') payload.paper_equity_usd = Number(equityUsd);
    if (kelly != null) payload.kelly_sizing_enabled = kelly;
    if (payload.max_daily_loss_fraction == null && payload.max_daily_realized_profit_fraction == null && payload.paper_equity_usd == null && payload.kelly_sizing_enabled == null) { setMsg('请至少填写一项'); return; }
    setBusy(true); setMsg('保存并重启 worker 中…');
    try {
      const r = await putRiskSettings(payload, operatorToken.trim());
      setMsg(r.note || '已保存');
      setLossPct(''); setCapPct(''); setEquityUsd(''); setKelly(null);
    } catch (e) { setMsg(`失败：${e}`); }
    finally { setBusy(false); }
  };
  return (
    <div className="strategy-risk-form" onClick={(event) => event.stopPropagation()}>
      <div className="strategy-risk-title">风控触发线（worker 实际执行值）</div>
      <label>日亏损熔断 %<input type="number" min="1" max="50" step="1" placeholder={`当前 ${currentLoss}%`} value={lossPct} onChange={(e) => setLossPct(e.target.value)} /></label>
      <label>每日止盈上限 %<input type="number" min="0" max="100" step="0.1" placeholder={currentCap != null ? (currentCap > 0 ? `当前 ${currentCap.toFixed(1)}%` : '当前 关闭(0)') : '--'} value={capPct} onChange={(e) => setCapPct(e.target.value)} /></label>
      <label>模拟本金 $<input type="number" min="10" max="100000" step="10" placeholder={currentEquity != null ? `当前 $${currentEquity}` : '--'} value={equityUsd} onChange={(e) => setEquityUsd(e.target.value)} /></label>
      <div className="risk-kelly-row">
        <span className="risk-kelly-label">凯利拉闸<em>（口袋级仓位）</em></span>
        <button type="button" role="switch" aria-checked={kellyEffective} className={`kelly-switch ${kellyEffective ? 'on' : 'off'}`} onClick={() => setKelly(!kellyEffective)}>
          <span className="kelly-knob" /><span className="kelly-state">{kellyEffective ? '开' : '关'}</span>
        </button>
        <small className="risk-kelly-hint">{currentKelly == null ? '当前 --' : `当前 ${currentKelly ? '开·凯利仓位' : '关·固定仓位'}`}{kelly != null && kelly !== currentKelly ? ' →待保存' : ''}</small>
      </div>
      <button type="button" disabled={busy} onClick={save}>{busy ? '应用中…' : '保存并重启 Worker'}</button>
      {msg && <small className="strategy-risk-msg">{msg}</small>}
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
  if (typeof scope === 'string') return scope.includes('BTC') ? 'BTC 实时' : 'BTC Paper';
  const btc = scope.BTC;
  return btc ? `BTC ${btc === 'live' ? '实时' : 'Paper'}` : 'BTC Paper';
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
            <Td>{fmtTime(d.ts)}</Td>
            <Td>{d.asset || '--'}</Td>
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
function PnlHistoryModal({ lane, onClose }: { lane: 'paper' | 'live'; onClose: () => void }) {
  const PAGE = 14;
  const [page, setPage] = useState(0);
  const [rows, setRows] = useState<Array<{ day: string; pnl_usd: number; wins: number; losses: number }>>([]);
  const [totalDays, setTotalDays] = useState(0);
  const [capital, setCapital] = useState<number | null>(null);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState('');
  useEffect(() => {
    let cancelled = false;
    setLoading(true); setErr('');
    fetchPnlDaily(lane, page * PAGE, PAGE)
      .then((r) => { if (!cancelled) { setRows(r.rows); setTotalDays(r.total_days); setCapital(r.capital_base_usd || null); } })
      .catch((e) => { if (!cancelled) setErr(String(e)); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [lane, page]);
  const pages = Math.max(1, Math.ceil(totalDays / PAGE));
  return <DataModal title={`每日盈亏历史 / ${lane === 'live' ? '实盘' : '模拟'}（逐手账口径 · 与KPI同源）`} onClose={onClose}>
    <div className="orders-all-toolbar">
      <span className="orders-all-count">共 {totalDays} 个交易日{capital ? ` · 收益率基数 ${fmtUsd(capital)}` : ''}</span>
      <span style={spacer} />
      <button type="button" className="orders-page-btn" disabled={page <= 0 || loading} onClick={() => setPage((p) => Math.max(0, p - 1))}>‹ 上一页</button>
      <span className="orders-all-count">{page + 1} / {pages}</span>
      <button type="button" className="orders-page-btn" disabled={page + 1 >= pages || loading} onClick={() => setPage((p) => p + 1)}>下一页 ›</button>
    </div>
    {err && <div className="settings-message">{err}</div>}
    {loading ? <Empty>加载中…</Empty> : !rows.length ? <Empty>暂无历史结算数据</Empty> : (
      <table style={tableStyle}>
        <thead><tr><Th>日期</Th><Th right>盈亏</Th><Th right>胜</Th><Th right>负</Th><Th right>胜率</Th><Th right>收益率</Th></tr></thead>
        <tbody>
          {rows.map((r) => {
            const total = r.wins + r.losses;
            const wr = total ? r.wins / total * 100 : null;
            const ret = capital && capital > 0 ? r.pnl_usd / capital * 100 : null;
            return (
              <tr key={r.day}>
                <Td>{r.day}</Td>
                <Td right color={r.pnl_usd >= 0 ? 'var(--green)' : 'var(--red)'} bold>{fmtSignedUsd(r.pnl_usd)}</Td>
                <Td right>{r.wins}</Td>
                <Td right>{r.losses}</Td>
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

/** Full order history (paper + live) with server-side pagination. */
function OrdersAllModal({ onClose }: { onClose: () => void }) {
  const PAGE = 20;
  const [lane, setLane] = useState<'all' | 'paper' | 'live'>('all');
  const [page, setPage] = useState(0);
  const [rows, setRows] = useState<Order[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState('');
  useEffect(() => {
    let cancelled = false;
    setLoading(true); setErr('');
    fetchOrdersPage(page * PAGE, PAGE, lane)
      .then((r) => { if (!cancelled) { setRows(r.rows); setTotal(r.total); } })
      .catch((e) => { if (!cancelled) setErr(String(e)); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [lane, page]);
  const pages = Math.max(1, Math.ceil(total / PAGE));
  return <DataModal title="订单总览 / 模拟 + 实盘" onClose={onClose}>
    <div className="orders-all-toolbar">
      {(['all', 'paper', 'live'] as const).map((l) => (
        <button key={l} type="button" className={`orders-lane-tab${lane === l ? ' active' : ''}`}
          onClick={() => { setLane(l); setPage(0); }}>
          {l === 'all' ? '全部' : l === 'paper' ? '模拟' : '实盘'}
        </button>
      ))}
      <span className="orders-all-count">共 {total.toLocaleString('en-US')} 笔</span>
      <span style={spacer} />
      <button type="button" className="orders-page-btn" disabled={page <= 0 || loading} onClick={() => setPage((p) => Math.max(0, p - 1))}>‹ 上一页</button>
      <span className="orders-all-count">{page + 1} / {pages}</span>
      <button type="button" className="orders-page-btn" disabled={page + 1 >= pages || loading} onClick={() => setPage((p) => p + 1)}>下一页 ›</button>
    </div>
    {err && <div className="settings-message">{err}</div>}
    {loading ? <Empty>加载中…</Empty> : <OrdersTable orders={rows} />}
  </DataModal>;
}

/** Window end from the market slug (…-5m-<start>); stale = long past end
 * with no resolution recorded, which we label instead of hiding. */
function paperWindowEnd(slug: string): number | null {
  const m = /-(\d{9,})$/.exec(slug || '');
  return m ? Number(m[1]) + 300 : null;
}

function PaperPositionsTable({ rows }: { rows: PaperPosition[] }) {
  if (!rows.length) return <Empty>暂无模拟持仓<span className="caret">_</span></Empty>;
  const now = Date.now() / 1000;
  return (
    <table style={tableStyle}>
      <thead>
        <tr><Th>时间</Th><Th>市场</Th><Th>资产</Th><Th>方向</Th><Th right>数量</Th><Th right>价格</Th><Th right>名义</Th><Th>状态</Th></tr>
      </thead>
      <tbody>
        {rows.map((p, i) => {
          const end = paperWindowEnd(p.market_slug);
          const stale = end != null && now - end > 900;
          const d = new Date(p.ts * 1000);
          const sameDay = new Date().toDateString() === d.toDateString();
          const dateLabel = `${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
          return (
            <tr key={`${p.market_slug}-${i}`}>
              <Td dim>{sameDay ? fmtTime(p.ts) : `${dateLabel} ${fmtTime(p.ts)}`}</Td>
              <Td dim>{shortMarket(p.market_slug)}</Td>
              <Td>{p.asset}</Td>
              <Td>{zhText(p.side)}</Td>
              <Td right>{fmtNum(p.size, 2)}</Td>
              <Td right>{fmtPx(p.price)}</Td>
              <Td right>{fmtUsd(p.notional_usd)}</Td>
              <Td color={stale ? 'var(--red)' : 'var(--amber)'} bold>{stale ? '超期待结算' : '待结算'}</Td>
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
