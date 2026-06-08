import { create } from 'zustand'

interface SymbolStatusState {
  statuses: Map<string, string>
  setStatuses: (accountId: number, statusData: Record<string, string>) => void
}

export const useSymbolStatusStore = create<SymbolStatusState>((set) => ({
  statuses: new Map(),
  setStatuses: (accountId, statusData) => {
    set((state) => {
      const next = new Map(state.statuses)
      for (const [symbol, status] of Object.entries(statusData)) {
        next.set(`${accountId}:${symbol}`, status)
      }
      return { statuses: next }
    })
  },
}))
