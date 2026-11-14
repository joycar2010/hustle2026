const $ = id => document.getElementById(id);
const fmt = (v, d = 2) => v == null || Number.isNaN(Number(v)) ? '—' : Number(v).toLocaleString('en-US', { maximumFractionDigits: d });
const money = v => v == null ? '$0.00' : (Number(v) >= 0 ? '+$' : '-$') + Math.abs(Number(v)).toFixed(2);
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&':'&amp;', '<':'&lt;', '>':'&gt;', '"':'&quot;', "'":'&#39;' }[c]));

async function get(path) {
  const r = await fetch(path, { cache: 'no-store' });
  if (!r.ok) throw Error(`${r.status}`);
  return r.json();
}

function book(prefix, b) {
  $(prefix + 'Bid').textContent = fmt(b?.best_bid);
  $(prefix + 'Ask').textContent = fmt(b?.best_ask);
  $(prefix + 'Size').textContent = fmt(b?.ask_size, 0);
}

function renderConfig(c) {
  const names = {
    min_entry_price:'入场最低价', max_entry_price:'入场最高价',
    entry_window_sec:'入场窗口(秒)', min_t_remaining_sec:'最少剩余(秒)',
    min_net_edge:'最低净优势', taker_fee_rate:'费用率', confirm_checks:'确认次数',
    order_shares:'订单份数', max_order_usd:'最大订单金额',
    daily_loss_limit_usd:'日亏损上限', max_open_positions:'最大持仓',
    paper_bankroll_usd:'Paper 本金', delta_filter_enabled:'Delta 过滤'
  };
  $('config').innerHTML = Object.entries(names).map(([k, n]) =>
    `<div><span>${n}</span><strong>${esc(c[k])}</strong></div>`).join('');
}

function renderAb(ab) {
  const a = ab?.groups?.A || {};
  const b = ab?.groups?.B || {};
  $('abAMode').textContent = `${a.mode || 'late_edge'} · ${a.version || ''}`;
  $('abBMode').textContent = `${b.mode || 'maker'} · ${b.version || ''}`;
  $('abAPnl').textContent = money(a.pnl_usd);
  $('abBPnl').textContent = money(b.pnl_usd);
  $('abAPnl').style.color = Number(a.pnl_usd) >= 0 ? '#39d98a' : '#ff7183';
  $('abBPnl').style.color = Number(b.pnl_usd) >= 0 ? '#39d98a' : '#ff7183';
  $('abAStats').textContent = `${a.positions || 0} 笔 · 胜负 ${a.wins || 0} / ${a.losses || 0} · 未平 ${a.open_positions || 0}`;
  $('abBStats').textContent = b.db_exists ? `${b.positions || 0} 笔 · 胜负 ${b.wins || 0} / ${b.losses || 0} · 未平 ${b.open_positions || 0}` : '等待 B 组独立账本';
}

async function renderEvents() {
  try {
    const x = await get('/api/events?limit=20');
    $('events').innerHTML = x.items.length ? x.items.map(e =>
      `<tr><td>${new Date(Number(e.ts) * 1000).toLocaleTimeString()}</td><td>${esc(e.kind)}</td><td>${esc(e.market_slug || '—')}</td><td>${esc(JSON.stringify(e.payload))}</td></tr>`
    ).join('') : '<tr><td colspan="4" class="muted">暂无 Paper 决策记录</td></tr>';
  } catch (_) {}
}

async function refresh() {
  try {
    const s = await get('/api/state');
    $('dot').style.background = '#39d98a';
    $('mode').textContent = 'PAPER · 在线';
    $('updated').textContent = '更新 ' + new Date().toLocaleTimeString();
    $('market').textContent = s.market?.slug || '暂无开放市场';
    $('title').textContent = s.market?.title || s.errors?.[0] || '等待下一窗口';
    $('remaining').textContent = s.market ? `${fmt(s.market.remaining_sec, 0)} 秒` : '—';
    book('up', s.up); book('down', s.down);
    $('spot').textContent = s.signal ? fmt(s.signal.current_price) : '—';
    $('beat').textContent = s.signal ? fmt(s.signal.price_to_beat) : '—';
    $('delta').textContent = s.signal ? (s.signal.delta_usd >= 0 ? '+' : '') + fmt(s.signal.delta_usd) : '—';
    $('signal').textContent = s.signal?.side || '—';
    $('source').textContent = s.signal?.source || '公开行情';
    const j = s.journal || {};
    $('pnl').textContent = money(j.pnl_usd);
    $('pnl').style.color = Number(j.pnl_usd) >= 0 ? '#39d98a' : '#ff7183';
    $('wl').textContent = `${j.wins || 0} / ${j.losses || 0}`;
    $('count').textContent = fmt(j.positions, 0);
    $('open').textContent = fmt(j.open_positions, 0);
    renderConfig(s.config || {});
    renderAb(s.ab);
    const error = (s.errors || []).join(' · ');
    $('errors').textContent = error;
    $('errors').classList.toggle('hidden', !error);
    await renderEvents();
  } catch (err) {
    $('dot').style.background = '#ff7183';
    $('mode').textContent = 'PAPER · 离线';
    $('updated').textContent = '连接失败';
    $('errors').textContent = 'Dashboard API 暂时不可用：' + err.message;
    $('errors').classList.remove('hidden');
  }
}

document.addEventListener('DOMContentLoaded', () => {
  refresh();
  setInterval(refresh, 5000);
  $('refresh').onclick = refresh;
});
