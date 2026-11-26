const $ = id => document.getElementById(id);
const text = (id, value) => {
  const el = $(id);
  if (el) el.textContent = value;
  return el;
};
const color = (id, value) => {
  const el = $(id);
  if (el) el.style.color = value;
};
const fmt = (v, d = 2) => v == null || Number.isNaN(Number(v))
  ? '-'
  : Number(v).toLocaleString('en-US', {maximumFractionDigits: d});
const money = v => v == null ? '$0.00'
  : (Number(v) >= 0 ? '+$' : '-$') + Math.abs(Number(v)).toFixed(2);
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({
  '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
}[c]));

function book(prefix, b) {
  text(prefix + 'Bid', fmt(b && b.best_bid));
  text(prefix + 'Ask', fmt(b && b.best_ask));
  text(prefix + 'Size', fmt(b && b.ask_size, 0));
}

function renderConfig(c) {
  const el = $('config');
  if (!el) return;
  const labels = {
    min_entry_price: 'entry min', max_entry_price: 'entry max',
    entry_window_sec: 'entry window sec', min_t_remaining_sec: 'minimum remaining sec',
    min_net_edge: 'minimum net edge', taker_fee_rate: 'taker fee rate',
    confirm_checks: 'confirmations', order_shares: 'order shares',
    max_order_usd: 'max order USD', daily_loss_limit_usd: 'daily loss USD',
    max_open_positions: 'max positions', paper_bankroll_usd: 'paper bankroll',
    paper_slippage_ticks: 'paper slippage ticks', paper_slippage_pct: 'paper slippage pct',
    delta_filter_enabled: 'delta filter', maker_min_bid_price: 'maker min bid',
    maker_pair_complete_sec: 'maker pair SLA', maker_zero_fill_kill_sec: 'maker zero-fill kill',
    split_min_pair_ask: 'split min pair ask', split_clip_shares: 'split first-leg shares',
    split_max_lean_shares: 'split max lean shares', sports_min_edge: 'sports min edge',
    sports_daily_loss_limit_usd: 'sports daily loss USD', sports_quote_on_mock: 'sports mock quotes',
    sports_discover_limit: 'sports discover limit'
  };
  el.innerHTML = Object.entries(labels)
    .map(([key, label]) => '<div><span>' + label + '</span><strong>' + esc(c[key]) + '</strong></div>')
    .join('');
}

let latestGroups = {};

function heartbeatStatus(hb) {
  if (!hb) return 'unknown';
  if (!hb.ok) return hb.reason || 'stale';
  const detail = String(hb.detail || '');
  if (detail.startsWith('risk_block=')) return 'risk blocked';
  if (detail.startsWith('market_guard=')) return 'no eligible market';
  if (detail.includes('active_mainlines=0')) return 'no eligible market';
  if (detail.includes('no eligible') || detail.includes('no market')) return 'no eligible market';
  return 'running';
}

function renderAb(ab, heartbeat) {
  const groups = ab?.groups || {};
  const modes = {A: 'late_edge', B: 'maker', C: 'split_sell'};
  latestGroups = groups;
  for (const [key, group] of [['A', groups.A || {}], ['B', groups.B || {}], ['C', groups.C || {}]]) {
    text('ab' + key + 'Mode', (group.mode || '') + ' - ' + (group.version || ''));
    const daily = group.daily || {};
    const pnl = Number(daily.pnl_usd ?? group.daily_pnl_usd ?? 0);
    const returnPct = Number(daily.return_pct ?? group.daily_return_pct ?? 0);
    text('ab' + key + 'Pnl', money(pnl));
    color('ab' + key + 'Pnl', pnl >= 0 ? '#39d98a' : '#ff7183');
    text('ab' + key + 'Return', returnPct.toFixed(2) + '%');
    color('ab' + key + 'Return', returnPct >= 0 ? '#39d98a' : '#ff7183');
    const hb = heartbeat?.groups?.[modes[key]];
    const status = heartbeatStatus(hb);
    const costs = ' · model fees ' + money(-Math.abs(Number(daily.fees_usd || 0)))
      + ' · slippage ' + money(-Math.abs(Number(daily.slippage_usd || 0)))
      + ' · rebate est. ' + money(Number(daily.rebate_usd || 0)) + ' (excluded from net)';
    text('ab' + key + 'Stats', (daily.traded_sessions ?? daily.settled ?? 0) + ' traded sessions / ' + (daily.settled || 0) + ' settled / ' + (daily.pending_traded_sessions || 0) + ' pending / ' + (daily.wins || 0) + ' wins / ' + (daily.losses || 0) + ' losses / open ' + (group.open_positions || 0) + ' · empty ' + (daily.empty_closed_sessions || 0) + ' · ' + status + costs);    const cell = $('ab' + key + 'Stats');
    if (cell && hb?.detail) cell.title = hb.detail;
  }
}

function openHistory(group) {
  const g = latestGroups[group] || {};
  const daily = g.daily || {};
  const rows = Array.isArray(daily.history) ? daily.history : [];
  text('historyTitle', group + ' · Beijing daily Paper history');
  text('historyMeta', 'Current day: ' + (daily.day_key || '-') + ' · net excludes estimated rebates; model slippage is already reflected in fill prices. Historical unknown slippage fills: ' + (g.historical_slippage_unknown_fills ?? 'unknown'));
  const body = $('historyRows');
  if (!body) return;
  body.innerHTML = rows.length
    ? rows.map(r => {
        const pnl = Number(r.pnl_usd || 0);
        const ret = Number(r.return_pct || 0);
        return '<tr><td>' + esc(r.day_key) + '</td><td class="' + (pnl >= 0 ? 'positive' : 'negative') + '">' + money(pnl) + '</td><td class="' + (ret >= 0 ? 'positive' : 'negative') + '">' + ret.toFixed(2) + '%</td><td>' + (r.wins || 0) + ' / ' + (r.losses || 0) + '</td><td>' + (r.settled || 0) + '</td><td>' + money(-Math.abs(Number(r.fees_usd || 0))) + '</td><td>' + money(-Math.abs(Number(r.slippage_usd || 0))) + '</td><td>' + money(Number(r.rebate_usd || 0)) + '</td></tr>';
      }).join('')
    : '<tr><td colspan="8" class="muted">No settled Paper data</td></tr>';
  $('historyModal')?.classList.remove('hidden');
}

function renderProducts(products) {
  const el = $('productCards');
  if (!el) return;
  const rows = (products || []).filter(p => p.key !== 'btc5m');
  el.innerHTML = rows.length ? rows.map(p => {
    const hb = p.heartbeat || {};
    // Product cards receive the normalized stats at the top level from the
    // read-only API. Accept a nested `paper` object too for forward
    // compatibility with clients that cache the product payload.
    const paper = p.paper || p;
    const daily = paper.daily || {};
    const totalPnl = Number(paper.pnl_usd ?? 0);
    const dayPnl = Number(daily.pnl_usd ?? 0);
    const dayReturn = Number(daily.return_pct ?? 0);
    const fees = Number(paper.fees_usd ?? 0);
    const rebate = Number(paper.rebate_usd ?? 0);
    const wins = Number(paper.wins ?? 0);
    const losses = Number(paper.losses ?? 0);
    const state = !p.enabled ? 'disabled / no strategy' : (p.status_label || heartbeatStatus(hb));
    const cls = !p.enabled ? 'muted' : (state === 'running' ? 'positive' : (state === 'risk blocked' ? 'negative' : 'muted'));
    const pnlClass = value => value >= 0 ? 'positive' : 'negative';
    const disabledNote = !p.enabled ? '<div class="muted">该产品尚未接入 Paper 交易与结算。</div>' : '';
    return '<article class="product-card"><div class="product-head"><strong>' + esc(p.key.toUpperCase()) + '</strong><span class="' + cls + '">' + esc(state) + '</span></div>'
      + '<p>' + esc(p.description || '') + '</p>'
      + disabledNote
      + (!p.enabled ? '' : '<div class="product-metrics"><div><span>Today PnL</span><b class="' + pnlClass(dayPnl) + '">' + money(dayPnl) + '</b></div>'
      + '<div><span>Today return</span><b class="' + pnlClass(dayReturn) + '">' + dayReturn.toFixed(2) + '%</b></div>'
      + '<div><span>Total PnL</span><b class="' + pnlClass(totalPnl) + '">' + money(totalPnl) + '</b></div>'
      + '<div><span>Wins / losses</span><b>' + wins + ' / ' + losses + '</b></div></div>'
      + '<small>phase ' + esc(p.phase) + ' · ' + esc(p.preferred_mode || 'paper') + ' · sessions ' + fmt(p.sessions, 0) + ' · filled ' + fmt(p.filled_sessions, 0) + ' · empty ' + fmt(p.empty_closed_sessions, 0) + ' · open ' + fmt(p.open_sessions, 0) + ' · settled ' + fmt(paper.settled ?? daily.settled, 0) + ' · fees ' + money(-Math.abs(fees)) + ' · rebate ' + money(rebate) + '</small>'
      + '<small class="muted" title="' + esc(hb.detail || hb.reason || '') + '">' + esc(hb.detail || hb.reason || '') + '</small></article>');
  }).join('') : '<div class="muted">No additional Paper products configured</div>';
}

function renderEvents(items) {
  const el = $('events');
  if (!el) return;
  el.innerHTML = items?.length
    ? items.map(e => '<tr><td>' + new Date(Number(e.ts) * 1000).toLocaleTimeString() + '</td><td>' + esc(e.group || '') + ' ' + esc(e.kind) + '</td><td>' + esc(e.market_slug || '-') + '</td><td>' + esc(JSON.stringify(e.payload)) + '</td></tr>').join('')
    : '<tr><td colspan="4" class="muted">No Paper decisions</td></tr>';
}

function renderSnapshot(s) {
  const dot = $('dot');
  if (dot) dot.style.background = '#39d98a';
  text('mode', 'PAPER - WS online');
  text('updated', 'updated ' + new Date().toLocaleTimeString());
  text('market', s.market?.slug || 'no open market');
  text('title', s.market?.title || s.errors?.[0] || 'waiting');
  text('remaining', s.market ? fmt(s.market.remaining_sec, 0) + ' sec' : '-');
  book('up', s.up);
  book('down', s.down);
  text('spot', s.signal ? fmt(s.signal.current_price) : '-');
  text('beat', s.signal ? fmt(s.signal.price_to_beat) : '-');
  text('delta', s.signal ? (s.signal.delta_usd >= 0 ? '+' : '') + fmt(s.signal.delta_usd) : '-');
  text('signal', s.signal?.side || '-');
  text('source', s.signal?.source || 'public feed');
  const j = s.journal || {};
  const daily = j.daily || {};
  const dailyPnl = Number(daily.pnl_usd ?? j.daily_pnl_usd ?? 0);
  const dailyReturn = Number(daily.return_pct ?? j.daily_return_pct ?? 0);
  text('pnl', money(dailyPnl));
  color('pnl', dailyPnl >= 0 ? '#39d98a' : '#ff7183');
  text('dailyReturn', dailyReturn.toFixed(2) + '%');
  color('dailyReturn', dailyReturn >= 0 ? '#39d98a' : '#ff7183');
  text('wl', (daily.wins || 0) + ' / ' + (daily.losses || 0));
  text('count', fmt(daily.settled, 0));
  text('open', fmt(j.open_positions, 0) + ' open');
  renderConfig(s.config || {});
  renderAb(s.ab, s.heartbeat);
  renderProducts(s.products || []);
  const errors = (s.errors || []).join(' | ');
  const errorEl = $('errors');
  if (errorEl) {
    errorEl.textContent = errors;
    errorEl.classList.toggle('hidden', !errors);
  }
  renderEvents(s.events || []);
}

let socket = null;
let reconnectTimer = null;
let reconnectDelay = 1000;

function markOffline(message = 'WS reconnecting...') {
  const dot = $('dot');
  if (dot) dot.style.background = '#ffb84d';
  text('mode', 'PAPER - ' + message);
}

function connectWS(force = false) {
  if (!force && socket && (socket.readyState === WebSocket.OPEN || socket.readyState === WebSocket.CONNECTING)) return;
  if (socket) {
    socket.onclose = null;
    socket.close();
  }
  if (reconnectTimer) clearTimeout(reconnectTimer);
  const scheme = location.protocol === 'https:' ? 'wss' : 'ws';
  socket = new WebSocket(scheme + '://' + location.host + '/ws');
  markOffline();
  socket.onopen = () => {
    reconnectDelay = 1000;
    text('mode', 'PAPER - WS online');
  };
  socket.onmessage = event => {
    try {
      renderSnapshot(JSON.parse(event.data));
    } catch (err) {
      const errorEl = $('errors');
      if (errorEl) {
        errorEl.textContent = 'WS snapshot error: ' + err.message;
        errorEl.classList.remove('hidden');
      }
    }
  };
  socket.onerror = () => markOffline('WS error');
  socket.onclose = () => {
    socket = null;
    markOffline();
    reconnectTimer = setTimeout(() => connectWS(), reconnectDelay);
    reconnectDelay = Math.min(reconnectDelay * 2, 10000);
  };
}

function start() {
  const refreshButton = $('refresh');
  if (refreshButton) {
    refreshButton.textContent = 'Reconnect WS';
    refreshButton.onclick = () => connectWS(true);
  }
  document.querySelectorAll('.ab-card').forEach(card => {
    card.addEventListener('click', () => openHistory(card.dataset.group));
  });
  $('closeHistory')?.addEventListener('click', () => $('historyModal')?.classList.add('hidden'));
  $('historyModal')?.addEventListener('click', event => {
    if (event.target.id === 'historyModal') event.target.classList.add('hidden');
  });
  connectWS();
}

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', start, {once: true});
} else {
  start();
}
