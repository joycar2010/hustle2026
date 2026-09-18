import type { LlmSettings, State } from './types';

export async function fetchState(): Promise<State> {
  const r = await fetch('/api/state', { cache: 'no-store' });
  if (!r.ok) throw new Error(`/api/state ${r.status}`);
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

export async function probeLlm(base_url: string, api_key: string, timeout_sec = 15): Promise<{ ok: boolean; models: string[]; effective_base_url: string }> {
  const r = await fetch('/api/settings/llm/probe', {
    method: 'POST', headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ base_url, api_key, timeout_sec }),
  });
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(data.detail || `/api/settings/llm/probe ${r.status}`);
  return data;
}

export async function testLlm(payload: { base_url?: string; model?: string; api_key?: string; prompt?: string; timeout_sec?: number }): Promise<{ ok: boolean; model: string; latency_ms: number }> {
  const r = await fetch('/api/settings/llm/test', {
    method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify(payload),
  });
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(data.detail || `/api/settings/llm/test ${r.status}`);
  return data;
}
