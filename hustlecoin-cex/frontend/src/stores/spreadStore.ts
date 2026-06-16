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
}

interface SpreadState {
  spreads: Map<string, SpreadData>
  lastUpdateTs: number
  setSpread: (symbol: string, data: SpreadData) => void
  setBulk: (items: SpreadData[]) => void
  getSorted: () => SpreadData[]
}

const SS_KEY = 'hc_spreads'

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
      newMap.set(symbol, data)
      saveSpreads(newMap)
      return { spreads: newMap, lastUpdateTs: data.ts }
    })
  },

  // 整表替换(非合并):Redis 已不再发布的死币/退市币不会残留。
  // 之前用 new Map(state.spreads) 合并 → 死币(HIGH/ATA 退市后引擎停发)永远冻结在表里。
  setBulk: (items) => {
    set(() => {
      const newMap = new Map<string, SpreadData>()
      let maxTs = 0
      for (const item of items) {
        const parsed: SpreadData = {
          symbol: item.symbol,
          spot_bid: Number(item.spot_bid),
          spot_ask: Number(item.spot_ask),
          fut_bid: Number(item.fut_bid),
          fut_ask: Number(item.fut_ask),
          spread_long: Number(item.spread_long),
          spread_short: Number(item.spread_short),
          ts: item.ts,
        }
        newMap.set(parsed.symbol, parsed)
        if (parsed.ts > maxTs) maxTs = parsed.ts
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
