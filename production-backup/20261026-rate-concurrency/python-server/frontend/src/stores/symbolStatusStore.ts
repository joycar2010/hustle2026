import { create } from 'zustand'

interface SymbolStatusState {
  statuses: Map<string, string>
  setStatuses: (accountId: number, statusData: Record<string, string>) => void
  removeSymbol: (symbol: string) => void
}

export const useSymbolStatusStore = create<SymbolStatusState>((set) => ({
  statuses: new Map(),
  setStatuses: (accountId, statusData) => {
    set((state) => {
      const next = new Map(state.statuses)
      // Worker payloads are full per-account snapshots.  Remove that
      // account's previous keys first; merging only the new entries left
      // completed/removed symbols stuck forever in their old borrow state.
      const prefix = `${accountId}:`
      for (const key of next.keys()) {
        if (key.startsWith(prefix)) next.delete(key)
      }
      for (const [symbol, status] of Object.entries(statusData)) {
        next.set(`${prefix}${symbol}`, status)
      }
      return { statuses: next }
    })
  },
  removeSymbol: (symbol) => {
    set((state) => {
      const next = new Map(state.statuses)
      const suffix = `:${symbol}`
      for (const key of next.keys()) {
        if (key.endsWith(suffix)) next.delete(key)
      }
      return { statuses: next }
    })
  },
}))
