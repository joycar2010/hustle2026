import { create } from 'zustand'

export interface BanInfo {
  type: 'borrow' | 'repay'
  remaining: number
  total: number
  updatedAt: number
}

interface BanState {
  bans: Map<string, BanInfo>
  setBans: (accountId: number, banData: Record<string, { type: string; remaining: number; total: number }>) => void
}

export const useBanStore = create<BanState>((set) => ({
  bans: new Map(),
  setBans: (accountId, banData) => {
    set((state) => {
      const next = new Map(state.bans)
      const now = Date.now()
      for (const [symbol, info] of Object.entries(banData)) {
        const key = `${accountId}:${symbol}`
        next.set(key, {
          type: info.type as 'borrow' | 'repay',
          remaining: info.remaining,
          total: info.total,
          updatedAt: now,
        })
      }
      return { bans: next }
    })
  },
}))
