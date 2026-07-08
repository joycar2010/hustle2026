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
    noinv_remaining_sec?: number  // 无券冷却剩余秒数(引擎engine:noinv TTL与pusher标志取大),0=不在冷却
    repayhold_remaining_sec?: number  // 还币暂停剩余秒数(用户勾选/在途静默),0=未暂停;点状态可解除
    residual_only?: boolean  // 非推送/持仓币的零债务现币残留(仅供「持币汇总」卖回,不是可交易行)
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
  markRepaid: (accountId: number, symbol: string, amount?: number) => void
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

  // 还币成功后乐观更新该账户该币的持币(现币 free + 本金 borrowed + 利息 interest)。
  // 服务端真值随后由「写后即时刷新」(后端 balance:refresh → BalancePusher 立刻重推,不再干等 10s 轮询)
  // 经 setBalances 整体替换对账覆盖。
  //   amount 省略  → 全额还(清零;「一键全还」/移除币/持币汇总全清等场景保持旧行为);
  //   amount 提供  → 部分还,按量递减(币安先抵利息再抵本金,现币同步递减),全部 clamp ≥ 0。
  //                  修复「部分还币却乐观清零成全额还清」(问题1根因:此函数原为全额还而写,加部分还币后未同步)。
  markRepaid: (accountId, symbol, amount) => {
    set((state) => {
      const balances = state.balances.map((b) => {
        if (b.account_id !== accountId) return b
        const sm = b.symbol_margin?.[symbol]
        if (!sm) return b
        let patch: { free: number; borrowed: number; interest: number }
        if (amount == null) {
          patch = { free: 0, borrowed: 0, interest: 0 }
        } else {
          const interest0 = sm.interest ?? 0
          const interestPaid = Math.min(amount, interest0)         // 先抵利息
          const principalPaid = Math.max(0, amount - interestPaid) // 余下抵本金
          patch = {
            interest: Math.max(0, interest0 - interestPaid),
            borrowed: Math.max(0, (sm.borrowed ?? 0) - principalPaid),
            free: Math.max(0, (sm.free ?? 0) - amount),
          }
        }
        return {
          ...b,
          symbol_margin: { ...b.symbol_margin, [symbol]: { ...sm, ...patch } },
        }
      })
      const next = { balances, summary: state.summary, lastUpdateTs: state.lastUpdateTs }
      try { sessionStorage.setItem(SS_KEY, JSON.stringify(next)) } catch { /* ignore */ }
      return { balances }
    })
  },
}))
