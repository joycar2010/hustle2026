export interface PushOrderedItem {
  symbol: string
  isPushed: boolean
}

const TERMINAL_POSITION_STATUSES = new Set(['CLOSED', 'FAILED'])

export function isLivePositionStatus(status?: string | null): boolean {
  const normalized = String(status || '').toUpperCase().trim()
  return normalized.length > 0 && !TERMINAL_POSITION_STATUSES.has(normalized)
}

export function sortByPushRecency<T extends PushOrderedItem>(
  items: readonly T[],
  pushedAt: Readonly<Record<string, number>>,
  pushedSymbols: readonly string[],
): T[] {
  const originalRank = new Map(pushedSymbols.map((symbol, index) => [symbol, index]))
  return [...items].sort((a, b) => {
    if (a.isPushed !== b.isPushed) return a.isPushed ? -1 : 1
    if (a.isPushed && b.isPushed) {
      const timeDiff = (pushedAt[b.symbol] ?? 0) - (pushedAt[a.symbol] ?? 0)
      if (timeDiff !== 0) return timeDiff
      const rankDiff = (originalRank.get(b.symbol) ?? -1) - (originalRank.get(a.symbol) ?? -1)
      if (rankDiff !== 0) return rankDiff
    }
    return a.symbol.localeCompare(b.symbol)
  })
}

export function splitActualBorrowRate(actualRate: number | null | undefined, slotCount: number) {
  const totalPerSecond = Math.max(0, Number(actualRate) || 0)
  const activeSlots = Math.max(0, Math.floor(slotCount))
  return {
    totalPerSecond,
    perSymbolPerSecond: activeSlots > 0 ? totalPerSecond / activeSlots : 0,
    activeSlots,
  }
}

export function accountBorrowRateLimitPerSlot(
  accountRateLimit: number | null | undefined,
  pushedSlotCount: number,
): number | null {
  if (accountRateLimit == null || !Number.isFinite(Number(accountRateLimit))) return null
  const slots = Math.max(0, Math.floor(pushedSlotCount))
  if (slots === 0) return 0
  return Math.max(0, Number(accountRateLimit)) / slots
}

/** Show configured/weight-limited capacity only while the row is borrowing. */
export function displayedBorrowRateLimit(
  rawStatus: string | null | undefined,
  accountRateLimit: number | null | undefined,
  pushedSlotCount: number,
): number | null {
  if (rawStatus !== '借币中') return null
  return accountBorrowRateLimitPerSlot(accountRateLimit, pushedSlotCount)
}
