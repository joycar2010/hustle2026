const $ = id => document.getElementById(id);
const text = (id, value) => { const el = $(id); if (el) el.textContent = value; return el; };
const color = (id, value) => { const el = $(id); if (el) el.style.color = value; };
const fmt = (v, d = 2) => v == null || Number.isNaN(Number(v))
  ? '—'
  : Number(v).toLocaleString('en-US', { maximumFractionDigits: d });
const money = v => v == null ? '$0.00'
  : (Number(v) >= 0 ? '+$' : '-$') + Math.abs(Number(v)).toFixed(2);
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({
  '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
}[c]));

async function get(path) {
  const r = await fetch(path, { cache: 'no-store' });
  if (!r.ok) throw Error(`${r.status}`);
  return r.json();
}

function book(prefix, b) {
  text(prefix + 'Bid', fmt(b && b.best_bid));
  text(prefix + 'Ask', fmt(b && b.best_ask));
  text(prefix + 'Size', fmt(b && b.ask_size, 0));
}

function renderConfig(c) {
  const el = $('config');
  if (!el) return;
  const labels = {
    min_entry_price: '入场最低价', max_entry_price: '入场最高价',
    entry_window_sec: '入场窗口(秒)', min_t_remaining_sec: '最少剩余(秒)',
    min_net_edge: '最低净优势', taker_fee_rate: '费用率',
    order_shares: '订单份数', daily_loss_limit_usd: '日亏损上限',
    paper_bankroll_usd: 'Paper 本金',
    sports_daily_loss_limit_usd: '体育日亏损',
    sports_quote_on_mock: 'Mock赔率可报价',
    maker_min_bid_price: 'B最低bid',
    split_min_pair_ask: 'C最低pair ask',
    split_residual_sla_sec: 'C残仓SLA'
  };
  el.innerHTML = Object.entries(labels)
    .map(([key, label]) => `<div><span>${label}</span><strong>${esc(c[key])}</strong></div>`)
    .join('');
}

let latestGroups = {};

function heartbeatStatus(hb, fallbackLabel) {
  if (fallbackLabel) return fallbackLabel;
  if (!hb) return 'unknown';
  if (!hb.ok && hb.reason) {
    if (String(hb.reason).includes('scaffold')) return '未启用 / 暂无策略';
    return hb.reason;
  }
  const detail = String(hb.detail || '');
  if (detail.includes('status=risk_blocked') || detail.startsWith('risk_block=')) return 'risk blocked';
  if (detail.includes('status=mock_odds_quote_disabled')) return 'mock odds (no quote)';
  if (detail.includes('status=outside_window')) return 'outside pregame window';
  if (detail.includes('status=discover_empty') || detail.includes('status=discover_error')) return 'no eligible market';
  if (detail.includes('market_guard=')) return 'no eligible market';
  if (detail.includes('active_mainlines=0') && !detail.includes('status=running')) return 'no eligible market';
  if (detail.includes('status=running') || hb.ok) return 'running';
  return 'unknown';
}

function renderAb(ab, heartbeat) {
  const groups = ab?.groups || {};
  const modes = { A: 'late_edge', B: 'maker', C: 'split_sell' };
  latestGroups = groups;
  for (const [key, group] of [['A', groups.A || {}], ['B', groups.B || {}], ['C', groups.C || {}]]) {
    text('ab' + key + 'Mode', `${group.mode || ''} · ${group.version || ''}`);
    const daily = group.daily || {};
    const pnl = Number(daily.pnl_usd ?? group.daily_pnl_usd ?? 0);
    const returnPct = Number(daily.return_pct ?? group.daily_return_pct ?? 0);
    text('ab' + key + 'Pnl', money(pnl));
    color('ab' + key + 'Pnl', pnl >= 0 ? '#39d98a' : '#ff7183');
    text('ab' + key + 'Return', returnPct.toFixed(2) + '%');
    color('ab' + key + 'Return', returnPct >= 0 ? '#39d98a' : '#ff7183');
    const hb = heartbeat?.groups?.[modes[key]];
    const status = heartbeatStatus(hb);
    const filled = group.filled_sessions != null ? group.filled_sessions : '—';
    const empty = group.empty_closed_sessions != null ? group.empty_closed_sessions : '—';
    text(
      'ab' + key + 'Stats',
      `${daily.settled || 0} settled · W/L ${daily.wins || 0}/${daily.losses || 0}` +
      ` · filled ${filled} · empty ${empty} · open ${group.open_positions || 0} · ${status}`
    );
    const cell = $('ab' + key + 'Stats');
    if (cell && hb?.detail) cell.title = hb.detail;
  }
}

function openHistory(group) {
  const g = latestGroups[group] || {};
  const daily = g.daily || {};
  const rows = Array.isArray(daily.history) ? daily.history : [];
  text('historyTitle', group + ' · 北京日 Paper 历史');
  text('historyMeta', '当前日: ' + (daily.day_key || '—'));
  const body = $('historyRows');
  if (!body) return;
  body.innerHTML = rows.length
    ? rows.map(r => {
        const pnl = Number(r.pnl_usd || 0);
        const ret = Number(r.return_pct || 0);
        return `<tr>
          <td>${esc(r.day_key)}</td>
          <td class="${pnl >= 0 ? 'positive' : 'negative'}">${money(pnl)}</td>
          <td class="${ret >= 0 ? 'positive' : 'negative'}">${ret.toFixed(2)}%</td>
          <td>${r.wins || 0} / ${r.losses || 0}</td>
          <td>${r.settled || 0}</td>
        </tr>`;
      }).join('')
    : '<tr><td colspan="5" class="muted">暂无已结算 Paper 数据</td></tr>';
  $('historyModal')?.classList.remove('hidden');
}

function renderProducts(products) {
  const el = $('productCards');
  if (!el) return;
  const rows = (products || []).filter(p => p.key !== 'btc5m');
  el.innerHTML = rows.length ? rows.map(p => {
    const hb = p.heartbeat || {};
    const paper = p.paper || p;
    const daily = paper.daily || {};
    const totalPnl = Number(paper.pnl_usd ?? 0);
    const dayPnl = Number(daily.pnl_usd ?? 0);
    const dayReturn = Number(daily.return_pct ?? 0);
    const fees = Number(paper.fees_usd ?? 0);
    const rebate = Number(paper.rebate_usd ?? 0);
    const wins = Number(paper.wins ?? 0);
    const losses = Number(paper.losses ?? 0);
    const state = p.status_label || (!p.enabled ? '未启用 / 暂无策略' : heartbeatStatus(hb));
    const cls = !p.enabled ? 'muted' : (state === 'running' ? 'positive' : (state === 'risk blocked' ? 'negative' : 'muted'));
    const pnlClass = value => value >= 0 ? 'positive' : 'negative';
    const disabledNote = !p.enabled ? '<div class="muted">该产品尚未接入 Paper 交易与结算。</div>' : '';
    return `<article class="product-card">
      <div class="product-head"><strong>${esc(p.key.toUpperCase())}</strong><span class="${cls}">${esc(state)}</span></div>
      <p>${esc(p.description || '')}</p>
      ${disabledNote}
      ${!p.enabled ? '' : `<div class="product-metrics">
        <div><span>Today PnL</span><b class="${pnlClass(dayPnl)}">${money(dayPnl)}</b></div>
        <div><span>Today return</span><b class="${pnlClass(dayReturn)}">${dayReturn.toFixed(2)}%</b></div>
        <div><span>Total PnL</span><b class="${pnlClass(totalPnl)}">${money(totalPnl)}</b></div>
        <div><span>Wins / losses</span><b>${wins} / ${losses}</b></div>
      </div>
      <small>phase ${esc(p.phase)} · ${esc(p.preferred_mode || 'paper')} · sessions ${fmt(p.sessions, 0)} · filled ${fmt(p.filled_sessions, 0)} · empty ${fmt(p.empty_closed_sessions, 0)} · open ${fmt(p.open_sessions, 0)} · fees ${money(-Math.abs(fees))} · rebate ${money(rebate)}</small>
      <small class="muted" title="${esc(hb.detail || hb.reason || '')}">${esc(hb.detail || hb.reason || '')}</small>`}
    </article>`;
  }).join('') : '<div class="muted">No additional Paper products configured</div>';
}

function renderEvents(items) {
  const el = $('events');
  if (!el) return;
  el.innerHTML = items?.length
    ? items.map(e => `<tr>
        <td>${new Date(Number(e.ts) * 1000).toLocaleTimeString()}</td>
        <td>${esc(e.group || '')} ${esc(e.kind)}</td>
        <td>${esc(e.market_slug || '—')}</td>
        <td>${esc(JSON.stringify(e.payload))}</td>
      </tr>`).join('')
    : '<tr><td colspan="4" class="muted">暂无 Paper 决策</td></tr>';
}

function renderSnapshot(s) {
  const dot = $('dot');
  if (dot) dot.style.background = '#39d98a';
  text('mode', 'PAPER · 在线');
  text('updated', '更新 ' + new Date().toLocaleTimeString());
  text('market', s.market?.slug || '暂无开放市场');
  text('title', s.market?.title || s.errors?.[0] || '等待下一窗口');
  text('remaining', s.market ? `${fmt(s.market.remaining_sec, 0)} 秒` : '—');
  book('up', s.up);
  book('down', s.down);
  text('spot', s.signal ? fmt(s.signal.current_price) : '—');
  text('beat', s.signal ? fmt(s.signal.price_to_beat) : '—');
  text('delta', s.signal ? (s.signal.delta_usd >= 0 ? '+' : '') + fmt(s.signal.delta_usd) : '—');
  text('signal', s.signal?.side || '—');
  text('source', s.signal?.source || '公开行情');

  const j = s.journal || {};
  const daily = j.daily || {};
  const dailyPnl = Number(daily.pnl_usd ?? j.daily_pnl_usd ?? 0);
  const dailyReturn = Number(daily.return_pct ?? j.daily_return_pct ?? 0);
  text('pnl', money(dailyPnl));
  color('pnl', dailyPnl >= 0 ? '#39d98a' : '#ff7183');
  text('dailyReturn', dailyReturn.toFixed(2) + '%');
  color('dailyReturn', dailyReturn >= 0 ? '#39d98a' : '#ff7183');
  text('wl', `${daily.wins || 0} / ${daily.losses || 0}`);
  text('count', fmt(daily.settled, 0));
  text('open', `${fmt(j.open_positions, 0)} open`);

  renderConfig(s.config || {});
  renderAb(s.ab, s.heartbeat);
  renderProducts(s.products || []);
  renderEvents(s.events || []);

  const errors = (s.errors || []).join(' · ');
  const errorEl = $('errors');
  if (errorEl) {
    errorEl.textContent = errors;
    errorEl.classList.toggle('hidden', !errors);
  }
}

async function refresh() {
  try {
    const s = await get('/api/state');
    renderSnapshot(s);
  } catch (err) {
    const dot = $('dot');
    if (dot) dot.style.background = '#ff7183';
    text('mode', 'PAPER · 离线');
    text('updated', '连接失败');
    const errorEl = $('errors');
    if (errorEl) {
      errorEl.textContent = 'Dashboard API 暂时不可用：' + err.message;
      errorEl.classList.remove('hidden');
    }
  }
}

function start() {
  const refreshButton = $('refresh');
  if (refreshButton) refreshButton.onclick = refresh;
  document.querySelectorAll('.ab-card').forEach(card => {
    card.addEventListener('click', () => openHistory(card.dataset.group));
  });
  $('closeHistory')?.addEventListener('click', () => $('historyModal')?.classList.add('hidden'));
  $('historyModal')?.addEventListener('click', event => {
    if (event.target.id === 'historyModal') event.target.classList.add('hidden');
  });
  refresh();
  setInterval(refresh, 5000);
}

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', start, { once: true });
} else {
  start();
}
