import { create } from 'zustand'

export interface MarketInfo {
  funding_rate: number
  mark_price: number
  funding_interval: number
  funding_cap: number
  daily_interest: number
  ratio: number
  next_funding_time: number
}

interface MarketDataState {
  marketData: Map<string, MarketInfo>
  setMarketData: (data: Record<string, MarketInfo>) => void
}

export const useMarketDataStore = create<MarketDataState>((set) => ({
  marketData: new Map(),
  setMarketData: (data) => {
    set((state) => {
      const m = new Map(state.marketData)
      for (const [symbol, info] of Object.entries(data)) {
        m.set(symbol, info)
      }
      return { marketData: m }
    })
  },
}))
