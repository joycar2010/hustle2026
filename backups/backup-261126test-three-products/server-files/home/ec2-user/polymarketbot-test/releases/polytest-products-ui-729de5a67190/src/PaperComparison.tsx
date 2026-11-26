import { useEffect, useState } from 'react';
import PaperAiStatus, { paperAiReason } from './PaperAiStatus';
import type { PaperAiShadow } from './PaperAiStatus';
import './PaperComparison.css';

type Group = {
  virtual_capital_usd?: number | null; net_pnl_usd?: number | null; equity_complete?: boolean | null;
  realized_pnl_usd?: number | null; fees_usd?: number | null; fills?: number | null; open_positions_count?: number | null;
  pending_orders?: number | null; candidates?: number | null; accepted?: number | null; blocked?: Record<string, number> | null;
  max_drawdown_usd?: number | null; daily_allow_entries?: boolean | null; daily_block_reason?: string | null;
  trade_state?: string | null; pnl_status?: string | null; pnl_is_zero_due_to_no_fill?: boolean | null;
  status_label_zh?: string | null;
  ai_shadow?: PaperAiShadow | null;
};
type ClobHealth = { market?: { connected?: boolean }; books?: Record<string, { source_age_sec?: number; received_age_sec?: number }> };
type Stream = ClobHealth & { clob?: ClobHealth };
type Summary = {
  mode?: string; available?: boolean; stale?: boolean; updated_at?: number; started_at?: number; validation_after_ts?: number;
  ends_at?: number; elapsed_hours?: number; validation_complete?: boolean; validation_state?: string;
  experiment_state?: string; groups?: Record<string, Group>; warmup_note?: string; result_note?: string;
  primary_group?: string;
  health?: { status?: string; source_reason?: string | null; last_frame_at?: number; stream?: Stream; signal_source?: string; signal_window_sec?: number };
  calibration?: { observed_markets?: number; settled_markets?: number; min_markets_per_bin?: number;
    bins?: Record<string, { markets?: number; ready?: boolean }> };
};

const reasons: Record<string, string> = {
  FALSE_BREAKOUT: '疑似假突破', MOMENTUM_DECAY: '动量衰减', MODEL_WARMUP: '概率校准等待',
  PROBABILITY_WARMUP: '概率校准等待', PROBABILITY_FEATURE_UNAVAILABLE: '概率特征不可用',
  MODEL_NOT_CALIBRATED: '概率校准等待', FEATURE_WARMUP: '行情特征等待',
  INSUFFICIENT_NET_EDGE: '扣费后优势不足', NET_EDGE_TOO_SMALL: '扣费后优势不足',
  INVENTORY_LIMIT: '库存上限', INVENTORY_EXPOSURE_LIMIT: '库存敞口上限',
  STALE_BOOK: '盘口过期', STALE_SIGNAL: '价格源过期', SOURCE_BLOCKED: '价格源保护',
  STALE_OR_INVALID_BOOK: '盘口过期或无效', WIDE_SPREAD: '买卖价差过大', INSUFFICIENT_DEPTH: '可成交深度不足',
  EXECUTABLE_COST_UNAVAILABLE: '可成交成本未知', INVENTORY_UNKNOWN: '库存未知', AVAILABLE_CASH: '可用余额不足',
  MINIMUM_ORDER_SIZE: '小于最小下单量', MARKET_ALREADY_ENTERED: '同市场已入场',
  MAXIMUM_OPEN_POSITIONS: '最大持仓限制', MARKET_RISK_BUDGET: '单市场风险预算限制',
  ENTRY_TIME_WINDOW: '不在入场时间窗', ENTRY_PRICE_RANGE: '不在入场价格区间', BOOK_UNAVAILABLE: '盘口待恢复',
  MARKET_EVENT_GAP: '行情事件缺口', DAILY_LOSS: '日亏损熔断', DAILY_PROFIT: '日止盈',
  AI_SCOUT_FRESHNESS: 'Scout 价格源或盘口未通过', AI_TRADER_EXECUTION_COST: 'Trader 成本或执行未通过',
  AI_AUDITOR_DAILY_RISK: 'Auditor 日风险未通过', AI_MECHANIC_STREAM_HEALTH: 'Mechanic 行情健康未通过',
};
const amount = (value: number | null | undefined, signed = false, precision = 4) => value == null || !Number.isFinite(value)
  ? '—' : `${signed && value > 0 ? '+' : value < 0 ? '-' : ''}$${Math.abs(value).toFixed(precision)}`;
const count = (value: number | null | undefined) => value == null || !Number.isFinite(value) ? '—' : value.toLocaleString('zh-CN');
const dateTime = (value: number | undefined) => value == null || !Number.isFinite(value) ? '待启动'
  : new Date(value * 1000).toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai', hour12: false });

export default function PaperComparison() {
  const [summary, setSummary] = useState<Summary | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [now, setNow] = useState(Date.now() / 1000);
  useEffect(() => {
    let stopped = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let request: AbortController | null = null;
    const load = async () => {
      request = new AbortController();
      const timeout = window.setTimeout(() => request?.abort(), 6000);
      try {
        const response = await fetch('/api/paper/comparison', { cache: 'no-store', signal: request.signal });
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        const payload = await response.json();
        const value: Summary | null = payload?.summary ?? payload;
        if (value?.mode && value.mode.toLowerCase() !== 'paper') throw new Error('模式不匹配');
        if (!stopped) { setSummary(value); setError(null); }
      } catch {
        if (!stopped) setError('对照数据暂不可用，等待恢复');
      } finally {
        window.clearTimeout(timeout);
        if (!stopped) { setNow(Date.now() / 1000); timer = setTimeout(load, 3000); }
      }
    };
    void load();
    return () => { stopped = true; request?.abort(); if (timer) clearTimeout(timer); };
  }, []);
  const data = summary?.available === false ? null : summary;
  // A retired comparison run must not resurrect empty A/B cards on a native
  // Paper deployment. Keep genuine loading/error states for enabled runs.
  if (summary?.available === false && !summary.groups) return null;
  const calibration = data?.calibration;
  const bins = Object.entries(calibration?.bins ?? {});
  const readyBins = bins.filter(([, bin]) => bin.ready).length;
  const age = data?.updated_at == null ? null : Math.max(0, now - data.updated_at);
  const stale = !!error || data?.stale === true || (age != null && age > 15);
  const clob = data?.health?.stream?.clob ?? data?.health?.stream;
  const connected = clob?.market?.connected === true;
  const waiting = !data?.groups;
  const stateText = waiting ? '等待启动' : stale ? '采集状态待恢复 · 验证未完成' : data?.experiment_state === 'DRAINING' ? '停止新开仓 · 剩余库存处理中'
    : data?.validation_state === 'READY_FOR_REVIEW' ? '样本待复核 · 验证未完成' : '采集中 · 验证未完成';
  return <section className="paper-comparison" aria-label="PAPER 同条件对照">
    <div className="paper-comparison-heading">
      <strong><span className="paper-comparison-badge">PAPER</span> BTC 同条件对照 / P3</strong>
      <span className={stale ? 'paper-comparison-warning' : ''}>{stale ? '数据过期 · ' : ''}{stateText}</span>
    </div>
    <div className="paper-comparison-groups">
      {(['BASELINE', 'FILTERED'] as const).map((lane) => {
        const group = data?.groups?.[lane];
        const noFills = group?.fills === 0 || group?.trade_state === 'NO_FILLED_ORDERS'
          || group?.pnl_status === 'NOT_APPLICABLE' || group?.pnl_is_zero_due_to_no_fill === true;
        const pnl = noFills || group?.equity_complete === false ? null : group?.net_pnl_usd;
        const blocked = Object.entries(group?.blocked ?? {}).sort((a, b) => b[1] - a[1]);
        return <article className="paper-comparison-group" key={lane} data-paper-group={lane}>
          <div className="paper-comparison-group-title"><b>{lane === 'BASELINE' ? 'A · BASELINE' : 'B · FILTERED'}</b><span>{data?.primary_group === lane ? 'PAPER · primary' : 'PAPER · comparison'}</span></div>
          <dl>
            <div><dt>模拟本金</dt><dd>{amount(group?.virtual_capital_usd, false, 6)}</dd></div>
            <div><dt>扣费后净盈亏</dt><dd className={pnl == null ? '' : pnl >= 0 ? 'paper-comparison-positive' : 'paper-comparison-negative'}>{noFills ? '暂无成交' : amount(pnl, true)}</dd></div>
            <div><dt>累计交易费</dt><dd>{amount(group?.fees_usd)}</dd></div>
            <div><dt>成交 / 持仓 / 挂单</dt><dd>{count(group?.fills)} / {count(group?.open_positions_count)} / {count(group?.pending_orders)}</dd></div>
          </dl>
          {group?.equity_complete === false && <p className="paper-comparison-warning">部分持仓缺少可成交估值，净盈亏暂不展示。</p>}
          {noFills && <p className="paper-comparison-warning">{group?.status_label_zh ?? '尚无成交，收益暂不计算。'}</p>}
          {group?.daily_allow_entries === false && <p className="paper-comparison-warning">新开仓受阻：{reasons[group.daily_block_reason ?? ''] ?? group.daily_block_reason ?? '等待风控数据'}</p>}
          {lane === 'FILTERED' && <PaperAiStatus shadow={group?.ai_shadow} stale={stale} now={now} />}
          <div className="paper-comparison-filter">过滤原因：{blocked.length ? blocked.slice(0, 3).map(([reason, n]) => <span key={reason} title={reason}>{reasons[reason] ?? paperAiReason(reason)} × {n}</span>) : '暂无过滤记录'}</div>
          <details><summary>查看全部过滤及风险统计</summary><div className="paper-comparison-detail">
            <span>候选 {count(group?.candidates)} · 接受 {count(group?.accepted)} · 最大回撤 {amount(group?.max_drawdown_usd)}</span>
            {blocked.map(([reason, n]) => <span key={reason}>{reasons[reason] ?? paperAiReason(reason)} ({reason})：{n}</span>)}
          </div></details>
        </article>;
      })}
    </div>
    <div className="paper-comparison-status">
      <span className={connected && !stale ? 'paper-comparison-positive' : 'paper-comparison-warning'}>公共行情 WS：{waiting ? '等待数据' : stale ? '状态过期' : connected ? '已连接' : '未连接'} · {data?.health?.status ?? 'WAITING'}</span>
      <span>校准：已结算 {count(calibration?.settled_markets)} / 已观察 {count(calibration?.observed_markets)} 个独立市场 · 就绪桶 {readyBins}/{bins.length} · 每桶门槛 {count(calibration?.min_markets_per_bin)}</span>
      <span>已运行 {data?.elapsed_hours == null ? '—' : `${data.elapsed_hours.toFixed(2)}h`} · 更新 {dateTime(data?.updated_at)}</span>
    </div>
    {data?.health?.source_reason && <p className="paper-comparison-warning">价格源保护：{data.health.source_reason}</p>}
    <details className="paper-comparison-method"><summary>校准进度、时间范围与对照口径（北京时间）</summary>
      <div className="paper-comparison-detail">
        <span>开始 {dateTime(data?.started_at)} · 48h 可复核 {dateTime(data?.validation_after_ts)} · 72h 计划结束 {dateTime(data?.ends_at)}</span>
        <span>同一公共行情、相同费用与成交模型、相同初始本金，两个账本分别计量。</span>
        <span>信号源 {data?.health?.signal_source ?? '待连接'} · TWAP {data?.health?.signal_window_sec ?? '—'}s</span>
        {bins.map(([name, bin]) => <span key={name}>校准桶 {name}：{count(bin.markets)} / {count(calibration?.min_markets_per_bin)} · {bin.ready ? '就绪' : '预热中'}</span>)}
        <span>{data?.warmup_note ?? '优化组在对应概率桶完成独立样本校准前不新开仓；零成交可能是正常等待。'}</span>
        <span>{data?.result_note ?? '48–72 小时仅形成待复核样本，未完成验证，不自动切换实盘参数。'}</span>
      </div>
    </details>
    {error && <p className="paper-comparison-warning" role="status">{error}</p>}
  </section>;
}
