import { create } from 'zustand'

export interface SpreadData {
  symbol: string
  spot_bid: number
  spot_ask: number
  fut_bid: number
  fut_ask: number
  spread_long: number
  spread_short: number
  ts: number
  spot_recv_ts_ms?: number
  fut_recv_ts_ms?: number
  no_inventory?: boolean   // 无券(币安杠杆池-3045池空):dashboard 仍显示点差,SpreadsPage 点差榜可过滤
}

interface SpreadState {
  spreads: Map<string, SpreadData>
  lastUpdateTs: number
  setSpread: (symbol: string, data: SpreadData) => void
  setBulk: (items: SpreadData[]) => void
  mergeBulk: (items: SpreadData[]) => void
  getSorted: () => SpreadData[]
}

const SS_KEY = 'hc_spreads'

function validTs(value: unknown): number {
  const n = Number(value)
  return Number.isFinite(n) && n > 0 ? n : 0
}

// Global latest marker: the newest local receipt wins, while retaining the
// exchange event timestamp as a compatibility fallback for old snapshots.
export function spreadLiveTs(spread: Pick<SpreadData, 'ts' | 'spot_recv_ts_ms' | 'fut_recv_ts_ms'>): number {
  return Math.max(
    validTs(spread.spot_recv_ts_ms),
    validTs(spread.fut_recv_ts_ms),
    validTs(spread.ts),
  )
}

// A symbol is only as fresh as its oldest quote leg. This is display/filter
// metadata only; the execution safety gate remains enforced by the backend.
// Snapshots written before local receipt fields existed fall back to `ts`.
export function spreadFreshnessTs(spread: Pick<SpreadData, 'ts' | 'spot_recv_ts_ms' | 'fut_recv_ts_ms'>): number {
  const spot = validTs(spread.spot_recv_ts_ms)
  const futures = validTs(spread.fut_recv_ts_ms)
  if (spot > 0 && futures > 0) return Math.min(spot, futures)
  return validTs(spread.ts)
}

function normalizeSpread(item: SpreadData): SpreadData {
  return {
    symbol: item.symbol,
    spot_bid: Number(item.spot_bid),
    spot_ask: Number(item.spot_ask),
    fut_bid: Number(item.fut_bid),
    fut_ask: Number(item.fut_ask),
    spread_long: Number(item.spread_long),
    spread_short: Number(item.spread_short),
    ts: validTs(item.ts),
    spot_recv_ts_ms: validTs(item.spot_recv_ts_ms),
    fut_recv_ts_ms: validTs(item.fut_recv_ts_ms),
    no_inventory: item.no_inventory,
  }
}

function loadCached(): Map<string, SpreadData> {
  try {
    const raw = sessionStorage.getItem(SS_KEY)
    if (raw) {
      const arr: SpreadData[] = JSON.parse(raw)
      const m = new Map<string, SpreadData>()
      for (const s of arr) m.set(s.symbol, s)
      return m
    }
  } catch { /* ignore */ }
  return new Map()
}

function saveSpreads(spreads: Map<string, SpreadData>) {
  try {
    sessionStorage.setItem(SS_KEY, JSON.stringify(Array.from(spreads.values())))
  } catch { /* ignore */ }
}

export const useSpreadStore = create<SpreadState>((set, get) => ({
  spreads: loadCached(),
  lastUpdateTs: 0,

  setSpread: (symbol, data) => {
    set((state) => {
      const newMap = new Map(state.spreads)
      const parsed = normalizeSpread(data)
      newMap.set(symbol, parsed)
      saveSpreads(newMap)
      return { spreads: newMap, lastUpdateTs: Math.max(state.lastUpdateTs, spreadLiveTs(parsed)) }
    })
  },

  // 整表替换(非合并):仅用于全量快照(spread_snapshot)。Redis 已不再发布的死币/退市币不残留。
  // 注意:增量(spread_batch)绝不能用此函数,否则只含变化币的批次会把整表冲掉、其余币(如点差稳定的)
  // 瞬间消失开/平空白 → 增量用 mergeBulk。
  setBulk: (items) => {
    set(() => {
      const newMap = new Map<string, SpreadData>()
      let maxTs = 0
      for (const item of items) {
        const parsed = normalizeSpread(item)
        newMap.set(parsed.symbol, parsed)
        maxTs = Math.max(maxTs, spreadLiveTs(parsed))
      }
      saveSpreads(newMap)
      return { spreads: newMap, lastUpdateTs: maxTs }
    })
  },

  // 增量合并:WS spread_batch(只含本批变化的币)逐个 upsert,不动其余币。
  // 死币残留由全量 snapshot(连接时 + 定期)纠正,而非靠增量冲表。
  mergeBulk: (items) => {
    set((state) => {
      if (!items || items.length === 0) return state
      const newMap = new Map(state.spreads)
      let maxTs = state.lastUpdateTs
      for (const item of items) {
        const parsed = normalizeSpread(item)
        newMap.set(parsed.symbol, parsed)
        maxTs = Math.max(maxTs, spreadLiveTs(parsed))
      }
      saveSpreads(newMap)
      return { spreads: newMap, lastUpdateTs: maxTs }
    })
  },

  getSorted: () => {
    const items = Array.from(get().spreads.values())
    items.sort((a, b) =>
      Math.max(Math.abs(b.spread_long), Math.abs(b.spread_short)) -
      Math.max(Math.abs(a.spread_long), Math.abs(a.spread_short)),
    )
    return items
  },
}))
