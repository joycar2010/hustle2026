import { useEffect, useState } from 'react';

export const PRODUCTS = [
  { key: 'btc5m', asset: 'BTC', label: 'BTC 5M' },
  { key: 'btc15m', asset: 'BTC15M', label: 'BTC 15M' },
  { key: 'sol5m', asset: 'SOL', label: 'SOL 5M' },
] as const;
export type ProductKey = typeof PRODUCTS[number]['key'];
export type ProductAsset = typeof PRODUCTS[number]['asset'];

export function productName(asset: string) {
  return PRODUCTS.find(p => p.asset === asset || p.key === asset.toLowerCase())?.label ?? asset;
}

type Lane = 'paper' | 'live';
type Values = Record<string, number | boolean | string>;
type Field = { key: string; label: string; type: string; min?: number; max?: number; step?: number; description?: string; group?: string; options?: string[] };
interface Config {
  product_key: ProductKey; fields: Field[]; effective: Values; paper: Values; live: Values; revision: string;
  paper_enabled: boolean; live_enabled: boolean;
}

async function request(path: string, body?: object, token?: string, signal?: AbortSignal) {
  const response = await fetch(path, {
    method: body ? 'PUT' : 'GET', cache: 'no-store', signal,
    headers: body ? { 'Content-Type': 'application/json', 'X-Operator-Token': token || '' } : undefined,
    body: body && JSON.stringify(body),
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    const detail = data.detail ?? data.error;
    throw new Error(typeof detail === 'string' ? detail : detail?.message ?? data.message ?? ('HTTP ' + response.status));
  }
  return data;
}

function category(key: string) {
  if (/fee|slip|rebate/.test(key)) return '手续费与滑点';
  if (/loss|profit|capital|bankroll|max_open|notional|risk|order_size|shares/.test(key)) return '资金与风控';
  if (/delta|lead|confirm|gap|twap|signal|bucket/.test(key)) return '信号与确认';
  return '入场与执行';
}

function ProductForm({ product, token }: { product: typeof PRODUCTS[number]; token: string }) {
  const [config, setConfig] = useState<Config | null>(null);
  const [lane, setLane] = useState<Lane>('paper');
  const [inputs, setInputs] = useState<Values>({});
  const [busy, setBusy] = useState(false);
  const [loadAttempt, retry] = useState(0);
  const [message, setMessage] = useState('');
  const path = '/api/products/' + product.key;

  useEffect(() => {
    const controller = new AbortController();
    request(path + '/config', undefined, undefined, controller.signal).then(data => {
      if (data.product_key !== product.key || !Array.isArray(data.fields)) throw new Error('产品配置响应不完整');
      setConfig(data);
    }).catch(e => { if (!controller.signal.aborted) setMessage(String(e.message)); });
    return () => controller.abort();
  }, [path, product.key, loadAttempt]);

  const apply = async (operation: 'save' | 'toggle') => {
    if (!config || busy) return;
    if (!token.trim()) { setMessage('请在顶栏填写操作令牌。'); return; }
    setBusy(true); setMessage('');
    try {
      if (operation === 'toggle') {
        if (!window.confirm('确认' + (config.paper_enabled ? '停止 ' : '启动 ') + product.label + ' Paper Worker？')) return;
        await request(path + '/paper', { enabled: !config.paper_enabled }, token.trim());
      } else {
        const values: Values = {};
        for (const field of config.fields) {
          if (!(field.key in inputs)) continue;
          const value = inputs[field.key];
          if (value === '') throw new Error(field.label + '不能为空');
          values[field.key] = field.type === 'boolean' ? value : field.options ? value : Number(value);
        }
        await request(path + '/config', { lane, values, revision: config.revision }, token.trim());
      }
      const latest: Config = await request(path + '/config');
      setConfig(latest);
      if (operation === 'save') setInputs({});
      setMessage(operation === 'toggle' ? (latest.paper_enabled ? 'Paper Worker 已启动' : 'Paper Worker 已停止') : lane === 'live' ? '实盘参数已保存' : latest.paper_enabled ? 'Paper 参数已保存，已回读运行配置' : 'Paper 参数已保存，下次启动加载');
    } catch (e) {
      setMessage(e instanceof Error ? e.message : String(e));
    } finally { setBusy(false); }
  };

  if (!config) return <div role="status">{message || '正在读取配置…'} {message && <button onClick={() => { setMessage(''); retry(x => x + 1); }}>重新读取</button>}</div>;
  const fields = config.fields.filter(field => Object.hasOwn(config[lane] || {}, field.key) && (lane === 'paper' || !field.key.startsWith('paper_')));
  const groups = [...new Set(fields.map(f => f.group || category(f.key)))];
  return <form className="product-config-form" onSubmit={event => { event.preventDefault(); void apply('save'); }}>
    <div className="product-action-row">
      <button type="button" className={'paper-switch ' + (config.paper_enabled ? 'paper-on' : 'paper-off')} onClick={() => apply('toggle')} disabled={busy} role="switch" aria-checked={config.paper_enabled} aria-label={product.label + ' Paper 开关'}><span className="paper-knob" />{config.paper_enabled ? 'Paper 运行' : 'Paper 停止'}</button>
      <div className="product-tabs">{(['paper', 'live'] as const).map(l => <button type="button" key={l} aria-pressed={lane === l} disabled={busy} onClick={() => { setLane(l); setInputs({}); setMessage(''); }}>{l === 'paper' ? 'Paper 参数' : '实盘参数'}</button>)}</div>
    </div>
    {lane === 'live' && <small>实盘交易已关闭。此处保存的参数供实盘启用时使用。</small>}
    {groups.map(group => <fieldset key={group}><legend>{group}</legend><div className="product-fields">{fields.filter(f => (f.group || category(f.key)) === group).map(field => {
      const value = inputs[field.key] ?? config[lane][field.key];
      const set = (v: boolean | string) => setInputs(prior => ({...prior, [field.key]: v}));
      const tip = field.description || field.key;
      return <label key={field.key} title={tip}><span>{field.label}</span>
        {field.type === 'boolean' ? <input type="checkbox" checked={value === true} onChange={e => set(e.target.checked)} />
          : field.options ? <select value={String(value)} onChange={e => set(e.target.value)}>{field.options.map(option => <option key={option}>{option}</option>)}</select>
          : <input type="number" required step={field.step ?? 'any'} min={field.min} max={field.max} value={value == null ? '' : String(value)} onChange={e => set(e.target.value)}/>}
      </label>;
    })}</div></fieldset>)}
    <div className="product-form-footer"><button className="settings-button" disabled={busy || !Object.keys(inputs).length} type="submit">{busy ? '处理中…' : lane === 'live' ? '保存实盘参数' : config.paper_enabled ? '保存并重启此 Paper Worker' : '保存 Paper 参数'}</button><span role="status">{message}</span>{message && <button type="button" onClick={() => { setInputs({}); setMessage(''); retry(x => x + 1); }} disabled={busy}>重新读取</button>}</div>
  </form>;
}

export function ProductSettings({ token, close }: { token: string; close: () => void }) {
  const [key, select] = useState<ProductKey>('btc5m');
  const product = PRODUCTS.find(p => p.key === key)!;
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') close(); };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [close]);
  return <div className="strategy-menu-popover product-manager" role="dialog" aria-label="策略管理" aria-modal="true">
    <div className="strategy-dialog-heading"><strong>策略管理</strong><button type="button" aria-label="关闭策略管理" className="strategy-dialog-close" onClick={close}>×</button></div>
    <div className="product-tabs" role="tablist" aria-label="产品">{PRODUCTS.map(p => <button key={p.key} type="button" role="tab" aria-selected={p.key === key} onClick={() => select(p.key)}>{p.label}</button>)}</div>
    <ProductForm key={key} product={product} token={token}/>
  </div>;
}
