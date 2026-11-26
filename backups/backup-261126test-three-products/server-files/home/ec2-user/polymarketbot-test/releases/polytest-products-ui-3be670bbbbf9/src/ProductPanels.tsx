import { useEffect, useState } from 'react';
import { fmtUsd, fmtPct } from './format';
import type { Decision, Order } from './types';
import type { ProductKey } from './ProductSettings';

export interface ProductSnapshot {
  product_key: ProductKey;
  paper_enabled: boolean;
  order_count: number; today_order_count: number;
  orders: Order[];
  decisions: Decision[];
  config: Record<string, unknown>;
  risk: { state?: string; daily_loss_limit_usd?: number; daily_profit_limit_usd?: number; today_net_pnl_usd?: number; open_value_usd?: number; max_open_positions?: number; pending?: number; available?: boolean };
  account: { equity_usd?: number; cash_usd?: number; open_value_usd?: number; capital_base_usd?: number; today_orders?: number; orders_total?: number; pending?: number; cumulative_net_pnl_usd?: number };
  probability: { available: boolean; value?: number; side?: string; ts?: number; source?: string };
  model_review: { available: boolean; primary?: string; secondary?: string; ts?: number; source?: string };
}

export function formatReview(value: unknown): string {
  if (typeof value === 'string') return value || '暂无记录';
  if (value && typeof value === 'object') {
    const result = value as Record<string, unknown>;
    return [result.model, result.decision, result.reason].filter(v => typeof v === 'string').join(' · ') || '已记录';
  }
  return '暂无记录';
}

export function ReviewPanel({ product }: { product?: ProductSnapshot }) {
  const prob = product?.probability;
  const review = product?.model_review;
  return <div className="product-readings">
    <div><span>策略概率{prob?.side ? ' · ' + prob.side : ''}</span><b>{prob?.available && prob.value != null ? fmtPct(prob.value * 100) : '暂无记录'}</b></div>
    <div><span>主模型</span><b>{review?.available ? formatReview(review.primary) : '暂无复核记录'}</b></div>
    <div><span>复核模型</span><b>{review?.available ? formatReview(review.secondary) : '暂无复核记录'}</b></div>
  </div>;
}

type Point = { ts: number; value: number };
export function EquityChart({ value, now, since }: { value?: number | null; now?: number; since?: number | null }) {
  const [history, setHistory] = useState<Point[]>([]);
  useEffect(() => {
    if (value == null || !Number.isFinite(value) || !now) return;
    setHistory(old => {
      if (old.length && old[old.length - 1].ts >= now) return old;
      return [...old, {ts: now, value}].slice(-3600);
    });
  }, [value, now]);
  const points = since ? history.filter(p => p.ts >= since) : history.slice(-120);
  const values = points.map(p => p.value);
  const low = Math.min(...values), high = Math.max(...values);
  const span = (high - low) || 1;
  const duration = points.length > 1 ? points[points.length - 1].ts - points[0].ts : 1;
  const line = points.map(p => ((p.ts - points[0].ts) / duration) * 100 + ',' + (90 - (p.value - low) / span * 80)).join(' ');
  return <div className="product-equity-chart"><b>{fmtUsd(value)}</b>{points.length > 1 ?
    <svg viewBox="0 0 100 100" preserveAspectRatio="none" role="img" aria-label="模拟权益时间曲线"><polyline points={line} fill="none" stroke="var(--green)" strokeWidth="1.5" vectorEffect="non-scaling-stroke" /></svg> :
    <small>等待权益采样</small>}</div>;
}

