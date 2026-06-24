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
  symbol_margin?: Record<string, {
    free: number
    borrowed?: number
    interest?: number
    max_borrowable: number
    borrow_limit?: number  // VIP档借贷上限(与持U无关、同VIP各账户相同)
    daily_interest_rate: number
    no_inventory?: boolean
    effective_borrowable?: number
    borrow_cap_reason?: string
  }>
}

interface BalanceSummary {
  futuresTotal: number
  futuresMargin: number
  futuresAvailable: number
  positionCount: number
  totalContracts: number
  masterFuturesPositions?: Record<string, number>  // 主账户合约持仓 {symbol: positionAmt}
  masterFuturesLiqPct?: number | null  // 主账户合约户维持保证金率%(爆率列,币安标准 totalMaintMargin/totalMarginBalance×100)
}

interface BalanceState {
  balances: AccountBalance[]
  summary: BalanceSummary
  wsLatency: number
  lastUpdateTs: number
  setBalances: (balances: AccountBalance[]) => void
  setSummary: (partial: Partial<BalanceSummary>) => void
  setWsLatency: (ms: number) => void
  markRepaid: (accountId: number, symbol: string) => void
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

  // 还币成功后乐观清零该账户该币的持币(现币 free + 本金 borrowed + 利息 interest),
  // 让持币汇总/单一规则模态框即时更新;下次 WS 余额推送以服务端真值对账覆盖(setBalances 整体替换)。
  markRepaid: (accountId, symbol) => {
    set((state) => {
      const balances = state.balances.map((b) => {
        if (b.account_id !== accountId) return b
        const sm = b.symbol_margin?.[symbol]
        if (!sm) return b
        return {
          ...b,
          symbol_margin: {
            ...b.symbol_margin,
            [symbol]: { ...sm, free: 0, borrowed: 0, interest: 0 },
          },
        }
      })
      const next = { balances, summary: state.summary, lastUpdateTs: state.lastUpdateTs }
      try { sessionStorage.setItem(SS_KEY, JSON.stringify(next)) } catch { /* ignore */ }
      return { balances }
    })
  },
}))
