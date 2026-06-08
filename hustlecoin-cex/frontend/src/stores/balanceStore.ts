import { create } from 'zustand'

export interface AccountBalance {
  account_id: number
  note: string
  spot_usdt_free: number
  margin_usdt_free: number
  margin_usdt_borrowed: number
  margin_net_usdt?: number
  margin_level: number
  futures_total: number
  futures_available: number
  futures_unrealized_pnl: number
  bnb_free: number
  bnb_interest: number
  symbol_margin?: Record<string, { free: number; max_borrowable: number; daily_interest_rate: number }>
}

interface BalanceSummary {
  futuresTotal: number
  futuresMargin: number
  futuresAvailable: number
  positionCount: number
  totalContracts: number
}

interface BalanceState {
  balances: AccountBalance[]
  summary: BalanceSummary
  wsLatency: number
  lastUpdateTs: number
  setBalances: (balances: AccountBalance[]) => void
  setSummary: (partial: Partial<BalanceSummary>) => void
  setWsLatency: (ms: number) => void
}

const SS_KEY = 'hc_balances'

function loadCached(): { balances: AccountBalance[]; summary: Partial<BalanceSummary>; lastUpdateTs: number } | null {
  try {
    const raw = sessionStorage.getItem(SS_KEY)
    if (raw) return JSON.parse(raw)
  } catch { /* ignore */ }
  return null
}

const cached = loadCached()

export const useBalanceStore = create<BalanceState>((set) => ({
  balances: cached?.balances ?? [],
  summary: {
    futuresTotal: cached?.summary?.futuresTotal ?? 0,
    futuresMargin: cached?.summary?.futuresMargin ?? 0,
    futuresAvailable: cached?.summary?.futuresAvailable ?? 0,
    positionCount: cached?.summary?.positionCount ?? 0,
    totalContracts: cached?.summary?.totalContracts ?? 0,
  },
  wsLatency: 0,
  lastUpdateTs: cached?.lastUpdateTs ?? 0,

  setBalances: (balances) => {
    const futuresTotal = balances.reduce((s, b) => s + b.futures_total, 0)
    const futuresAvailable = balances.reduce((s, b) => s + b.futures_available, 0)
    const futuresMargin = futuresTotal - futuresAvailable
    const ts = Date.now()
    set((state) => {
      const next = {
        balances,
        summary: { ...state.summary, futuresTotal, futuresMargin, futuresAvailable },
        lastUpdateTs: ts,
      }
      try { sessionStorage.setItem(SS_KEY, JSON.stringify(next)) } catch { /* ignore */ }
      return next
    })
  },

  setSummary: (partial) => {
    set((state) => ({
      summary: { ...state.summary, ...partial },
    }))
  },

  setWsLatency: (ms) => set({ wsLatency: ms }),
}))
