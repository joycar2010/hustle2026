import type { LlmSettings, LlmUsageSnapshot, State } from './types';

export async function fetchState(): Promise<State> {
  const r = await fetch('/api/state', { cache: 'no-store' });
  if (!r.ok) throw new Error(`/api/state ${r.status}`);
  return r.json();
}

/** Token telemetry is optional during rolling deployments; callers may fall
 * back to the nested `llm.usage` field in /api/state when this endpoint is
 * unavailable. */
export async function fetchLlmUsage(): Promise<{ models?: LlmUsageSnapshot['models']; ts?: number; configured?: Record<string, string> }> {
  const r = await fetch('/api/llm/usage', { cache: 'no-store' });
  if (!r.ok) throw new Error(`/api/llm/usage ${r.status}`);
  return r.json();
}

export async function controlLive(action: 'start' | 'stop', operatorToken: string): Promise<{ ok: boolean; running: boolean; mode: string; assets: Record<string, boolean>; diagnostic?: string; note?: string }> {
  const r = await fetch(`/api/live/${action}`, {
    method: 'POST',
    headers: { 'X-Operator-Token': operatorToken },
  });
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(data.detail || `/api/live/${action} ${r.status}`);
  return data;
}

export async function toggleLiveService(asset: string, enabled: boolean, operatorToken: string): Promise<unknown> {
  const r = await fetch(`/api/live/services/${encodeURIComponent(asset)}`, { method: 'PUT', headers: { 'content-type': 'application/json', 'X-Operator-Token': operatorToken }, body: JSON.stringify({ live_enabled: enabled }) });
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(data.detail || `/api/live/services/${asset} ${r.status}`);
  return data;
}

export async function fetchOrdersPage(offset: number, limit: number, lane: 'all' | 'paper' | 'live', asset = 'BTC'): Promise<{ rows: import('./types').Order[]; total: number; offset: number; limit: number; lane: string; asset?: string }> {
  const r = await fetch(`/api/orders?offset=${offset}&limit=${limit}&lane=${lane}${asset ? `&asset=${encodeURIComponent(asset)}` : ''}`, { cache: 'no-store' });
  if (!r.ok) throw new Error(`/api/orders ${r.status}`);
  return r.json();
}

export interface PolymarketActivityPage { rows: Array<Record<string, unknown>>; total: number; offset: number; limit: number; source?: string; }

/** Real Polymarket account activity (the user's wallet, not the local order ledger). */
export async function fetchPolymarketActivity(offset: number, limit: number): Promise<PolymarketActivityPage> {
  const r = await fetch(`/api/polymarket/activity?offset=${offset}&limit=${limit}`, { cache: 'no-store' });
  if (!r.ok) throw new Error(`/api/polymarket/activity ${r.status}`);
  const data = await r.json();
  const rows = Array.isArray(data?.rows) ? data.rows : Array.isArray(data?.data) ? data.data : [];
  return { ...data, rows, total: Number(data?.total ?? rows.length), offset: Number(data?.offset ?? offset), limit: Number(data?.limit ?? limit), source: data?.source || 'polymarket' };
}

export interface PolymarketFundingPage { rows: Array<Record<string, unknown>>; total: number; offset: number; limit: number; available?: boolean; message?: string; }

/** Deposits/withdrawals for the bound Polymarket account. */
export async function fetchPolymarketFunding(offset: number, limit: number): Promise<PolymarketFundingPage> {
  const r = await fetch(`/api/polymarket/ledger?offset=${offset}&limit=${limit}`, { cache: 'no-store' });
  if (!r.ok) throw new Error(`/api/polymarket/ledger ${r.status}`);
  const data = await r.json();
  const rows = Array.isArray(data?.rows) ? data.rows : Array.isArray(data?.records) ? data.records : Array.isArray(data?.data) ? data.data : [];
  return { ...data, rows, total: Number(data?.total ?? rows.length), offset: Number(data?.offset ?? offset), limit: Number(data?.limit ?? limit), available: data?.available !== false, message: data?.message };
}

export interface PnlDailyPage {
  lane: string; asset?: string; rows: Array<{ day: string; pnl_usd: number; wins: number; losses: number }>;
  total_days: number; offset: number; limit: number; capital_base_usd: number;
}
const pnlDailyPages = new Map<string, { ts: number; data: PnlDailyPage }>();
const pnlDailyRequests = new Map<string, Promise<PnlDailyPage>>();
const pnlDailyKey = (lane: string, offset: number, limit: number, asset: string) => `${lane}:${offset}:${Math.min(60, limit)}:${asset.toUpperCase()}`;
export function cachedPnlDaily(lane: 'paper' | 'live', offset: number, limit: number, asset = ''): PnlDailyPage | undefined {
  const cached = pnlDailyPages.get(pnlDailyKey(lane, offset, limit, asset));
  if (cached && Date.now() - cached.ts < 30000) return cached.data;
  // The probability panel already reads a larger daily page. Reuse that
  // snapshot for a smaller modal page while its network refresh runs.
  for (const entry of pnlDailyPages.values()) {
    const data = entry.data;
    if (Date.now() - entry.ts < 30000 && data.lane === lane
      && (data.asset || '').toUpperCase() === asset.toUpperCase()
      && data.offset <= offset
      && data.offset + data.rows.length >= Math.min(offset + limit, data.total_days)) {
      return { ...data, rows: data.rows.slice(offset - data.offset, offset - data.offset + limit), offset, limit };
    }
  }
  return undefined;
}
export async function fetchPnlDaily(lane: 'paper' | 'live', offset: number, limit: number, asset = ''): Promise<PnlDailyPage> {
  const key = pnlDailyKey(lane, offset, limit, asset);
  const pending = pnlDailyRequests.get(key);
  if (pending) return pending;
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 15000);
  const task = (async () => {
  try {
  const r = await fetch(`/api/pnl/daily?lane=${lane}&offset=${offset}&limit=${Math.min(60, limit)}${asset ? `&asset=${encodeURIComponent(asset)}` : ''}`, { cache: 'no-store', signal: controller.signal });
  if (!r.ok) throw new Error(`/api/pnl/daily ${r.status}`);
  const data = await r.json();
  // The isolated test adapter has a single current-day snapshot instead of a
  // historical rows endpoint.  Returning an empty row set is explicit and
  // prevents the UI from treating the aggregate as a fake daily series.
  const result = { ...data, rows: data.rows ?? [], total_days: data.total_days ?? (data.rows ?? []).length, offset: data.offset ?? offset, limit: data.limit ?? limit, lane: data.lane ?? lane, capital_base_usd: data.capital_base_usd ?? 0 };
  if (pnlDailyPages.size >= 32) pnlDailyPages.clear();
  pnlDailyPages.set(key, { ts: Date.now(), data: result });
  return result;
  } catch (error) {
    if (controller.signal.aborted) throw new Error('盈亏历史请求超时，请点击刷新重试');
    throw error;
  } finally {
    clearTimeout(timer);
    pnlDailyRequests.delete(key);
  }
  })();
  pnlDailyRequests.set(key, task);
  return task;
}

export async function fetchConsensusHistory(offset: number, limit: number): Promise<{ rows: Array<{ ts: number; decision?: string; reason?: string; agreed?: boolean; primary_text?: string; secondary_text?: string; reviews?: number; pnl_usd?: number }>; total: number; offset: number; limit: number }> {
  const r = await fetch(`/api/consensus/history?offset=${offset}&limit=${limit}`, { cache: 'no-store' });
  if (!r.ok) throw new Error(`/api/consensus/history ${r.status}`);
  return r.json();
}

/** Start/stop one paper worker systemd unit (operator-token gated). */
export async function putPaperService(asset: string, enabled: boolean, operatorToken: string): Promise<{ ok: boolean; service: string; paper_active?: boolean; paper_services?: Record<string, { active?: boolean; enabled?: boolean }>; note?: string }> {
  const r = await fetch(`/api/paper/services/${encodeURIComponent(asset)}`, {
    method: 'PUT',
    headers: { 'content-type': 'application/json', 'X-Operator-Token': operatorToken },
    body: JSON.stringify({ enabled }),
  });
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(data.detail || `/api/paper/services/${asset} ${r.status}`);
  return data;
}

export async function putRiskSettings(payload: { max_daily_loss_fraction?: number; max_daily_realized_profit_fraction?: number; max_daily_realized_profit_usd?: number; paper_equity_usd?: number; kelly_sizing_enabled?: boolean; restart_workers?: boolean }, operatorToken: string): Promise<{ ok: boolean; note?: string; workers_restarted?: string[] }> {
  const r = await fetch('/api/settings/risk', {
    method: 'PUT',
    headers: { 'content-type': 'application/json', 'X-Operator-Token': operatorToken },
    body: JSON.stringify(payload),
  });
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(data.detail || `/api/settings/risk ${r.status}`);
  return data;
}

export async function fetchLlmSettings(): Promise<LlmSettings> {
  const r = await fetch('/api/settings/llm', { cache: 'no-store' });
  if (!r.ok) throw new Error(`/api/settings/llm ${r.status}`);
  return r.json();
}

export async function saveLlmSettings(settings: LlmSettings): Promise<LlmSettings> {
  const send = (payload: unknown) => fetch('/api/settings/llm', {
    method: 'PUT', headers: { 'content-type': 'application/json' }, body: JSON.stringify(payload),
  });
  let r = await send(settings);
  // Older poly servers validate a strict flat schema. Retry with the legacy
  // shape when they reject the optional dual-model fields, preserving the
  // existing single-model workflow during a rolling deployment.
  if (!r.ok && (r.status === 400 || r.status === 422) && (settings.primary || settings.secondary)) {
    const { primary: _primary, secondary: _secondary, ...legacy } = settings;
    r = await send(legacy);
  }
  if (!r.ok) {
    let message = `/api/settings/llm ${r.status}`;
    try { const data = await r.json(); message = data.detail || message; } catch { /* ignore */ }
    throw new Error(message);
  }
  return r.json();
}

export async function testLlmSettings(): Promise<{ ok: boolean; latency_ms?: number; models?: string[] }> {
  const r = await fetch('/api/settings/llm/test', { method: 'POST' });
  if (!r.ok) {
    let message = `接口测试失败（${r.status}）`;
    try { const data = await r.json(); message = data.detail || message; } catch { /* ignore */ }
    throw new Error(message);
  }
  return r.json();
}

export async function probeLlm(base_url: string, api_key: string, timeout_sec = 15, slot: 'primary' | 'secondary' = 'primary'): Promise<{ ok: boolean; models: string[]; effective_base_url: string }> {
  const r = await fetch('/api/settings/llm/probe', {
    method: 'POST', headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ base_url, api_key, timeout_sec, slot }),
  });
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(data.detail || `/api/settings/llm/probe ${r.status}`);
  return data;
}

export async function testLlm(payload: { base_url?: string; model?: string; api_key?: string; prompt?: string; timeout_sec?: number; slot?: 'primary' | 'secondary' }): Promise<{ ok: boolean; model: string; latency_ms: number }> {
  const r = await fetch('/api/settings/llm/test', {
    method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify(payload),
  });
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(data.detail || `/api/settings/llm/test ${r.status}`);
  return data;
}
