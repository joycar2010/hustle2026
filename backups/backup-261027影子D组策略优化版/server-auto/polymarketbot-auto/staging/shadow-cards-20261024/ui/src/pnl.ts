import type { ModeKpis } from './types';

/** Empty asset buckets mean no realized lots; absent summaries mean unavailable.
 * Never substitute today's or another asset's PnL for a lifetime value. */
export function assetPnl(lane: ModeKpis | undefined, asset: string, period: 'today' | 'cumulative') {
  const buckets = period === 'cumulative' ? lane?.cumulative_by_asset : lane?.by_asset;
  if (!buckets) return null;
  const value = buckets[asset];
  return { realized_usd: value?.realized_usd ?? 0, wins: value?.wins ?? 0, losses: value?.losses ?? 0 };
}

export function pnlReturn(pnl: number | null | undefined, capital: number | null | undefined) {
  return pnl != null && Number.isFinite(pnl) && capital != null && Number.isFinite(capital) && capital > 0
    ? pnl / capital * 100 : null;
}
