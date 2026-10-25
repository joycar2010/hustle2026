export interface MarginDebtSnapshot {
  borrowed?: number
  interest?: number
  free?: number
  /** Server time when Binance returned the margin account snapshot. */
  snapshot_at_ms?: number
  /** BalancePusher's pushed-asset zero row is not an exchange debt snapshot. */
  snapshot_placeholder?: boolean
  max_borrowable?: number
  borrow_limit?: number
  effective_borrowable?: number
  daily_interest_rate?: number
  no_inventory?: boolean
  noinv_remaining_sec?: number
  repayhold_remaining_sec?: number
  residual_only?: boolean
  /** Maximum quantity for the next Binance borrow request (one bite). */
  next_borrowable?: number
  /** USDT notional corresponding to next_borrowable. */
  next_borrow_notional?: number
  /** Remaining cumulative cap in coin units; null means no configured cap. */
  remaining_borrow_capacity?: number | null
  /** Remaining cumulative cap in USDT; null means no configured cap. */
  remaining_borrow_capacity_usdt?: number | null
  /** Resolved single-request amount in USDT, before price/lot rounding. */
  single_order_amount_usdt?: number | null
  /** Configured cumulative amount cap in USDT, when present. */
  borrow_cap_usdt?: number | null
  borrow_cap_reason?: string
}

/**
 * Resolve one margin snapshot without relying on the exchange's symbol key
 * casing.  Binance normally returns uppercase symbols, but a cached/legacy
 * payload can contain lowercase keys; callers must still distinguish a
 * present (including explicit-zero) snapshot from a missing one.
 */
export function marginSnapshotForSymbol(
  symbolMargin: Record<string, MarginDebtSnapshot> | null | undefined,
  symbol: string,
): MarginDebtSnapshot | undefined {
  if (!symbolMargin) return undefined
  const exact = symbolMargin[symbol]
  if (exact !== undefined) return exact
  const wanted = String(symbol).toUpperCase()
  for (const [key, snapshot] of Object.entries(symbolMargin)) {
    if (key.toUpperCase() === wanted) return snapshot
  }
  return undefined
}

// `max_borrowable` is Binance's current account-level capacity.  The VIP
// `borrow_limit` is a theoretical tier ceiling and must not be used as an
// immediately executable amount in the dashboard.
export type BorrowableQuantitySource = 'max_borrowable' | 'effective_borrowable'

export interface BorrowableQuantity {
  quantity: number
  source: BorrowableQuantitySource
}

/** Return the USDT value of the next single borrow request. */
export function nextBorrowableUsdt(
  snapshot: MarginDebtSnapshot | undefined,
  spotPrice: number | undefined,
): number | null {
  if (!snapshot) return null
  const explicit = Number(snapshot.next_borrow_notional)
  if (Number.isFinite(explicit) && explicit >= 0) return explicit
  const price = Number(spotPrice)
  if (!Number.isFinite(price) || price <= 0) return null
  const quantity = Number(snapshot.next_borrowable ?? snapshot.effective_borrowable)
  if (Number.isFinite(quantity) && quantity >= 0) return quantity * price
  const rawMax = Number(snapshot.max_borrowable)
  return Number.isFinite(rawMax) && rawMax >= 0 ? rawMax * price : null
}

/** Return the remaining configured cumulative cap in USDT, if one exists. */
export function remainingBorrowCapacityUsdt(
  snapshot: MarginDebtSnapshot | undefined,
  spotPrice: number | undefined,
): number | null {
  if (!snapshot) return null
  const explicit = Number(snapshot.remaining_borrow_capacity_usdt)
  if (Number.isFinite(explicit) && explicit >= 0) return explicit
  const price = Number(spotPrice)
  const quantity = Number(snapshot.remaining_borrow_capacity)
  if (Number.isFinite(quantity) && quantity >= 0 && Number.isFinite(price) && price > 0) {
    return quantity * price
  }
  return null
}

/** Configured single-request amount, retained for labels/tooltips. */
export function singleBorrowOrderAmountUsdt(
  snapshot: MarginDebtSnapshot | undefined,
): number | null {
  if (!snapshot) return null
  const amount = Number(snapshot.single_order_amount_usdt)
  return Number.isFinite(amount) && amount >= 0 ? amount : null
}

export interface DebtBreakdown {
  principal: number
  interest: number
  total: number
}

/** Minimal shape of an active engine position used by balance/repay views. */
export interface BorrowPositionLike {
  id?: number | string | null
  sub_account_id: number
  symbol: string
  borrow_qty?: number | string | null
  status?: string | null
  account_note?: string | null
  created_at?: string | Date | null
  updated_at?: string | Date | null
}

/**
 * Position ids cross a JSON boundary (REST commonly emits numbers while a
 * Redis/WS producer may preserve them as strings).  Keep one comparison key
 * so an update cannot create a duplicate row or miss a terminal deletion.
 */
export function positionIdKey(value: unknown): string | null {
  if (value == null) return null
  const key = String(value).trim()
  return key.length > 0 ? key : null
}

export function samePositionId(left: unknown, right: unknown): boolean {
  const leftKey = positionIdKey(left)
  const rightKey = positionIdKey(right)
  return leftKey != null && rightKey != null && leftKey === rightKey
}

export type DebtDisplaySource = 'balance' | 'position' | 'none'

export interface DebtDisplay extends DebtBreakdown {
  /** True only when the row is an authoritative (non-placeholder) snapshot. */
  hasSnapshot: boolean
  /** `position` means the numbers are a temporary UI estimate, not authority. */
  source: DebtDisplaySource
}

const TERMINAL_POSITION_STATUSES = new Set(['CLOSED', 'FAILED'])

function observedAtMs(value: string | Date | number | null | undefined): number | null {
  if (value == null || value === '') return null
  const parsed = value instanceof Date
    ? value.getTime()
    : typeof value === 'number'
      ? value
      : Date.parse(String(value))
  return Number.isFinite(parsed) ? parsed : null
}

function latestPositionUpdateMs(
  positions: readonly BorrowPositionLike[],
  accountId: number,
  symbol: string,
): number | null {
  const wanted = String(symbol).toUpperCase()
  let latest: number | null = null
  for (const position of positions) {
    if (Number(position.sub_account_id) !== Number(accountId)) continue
    if (String(position.symbol || '').toUpperCase() !== wanted) continue
    const status = String(position.status || '').toUpperCase()
    if (status && TERMINAL_POSITION_STATUSES.has(status)) continue
    const observed = observedAtMs(position.updated_at) ?? observedAtMs(position.created_at)
    if (observed != null && (latest == null || observed > latest)) latest = observed
  }
  return latest
}

/**
 * Sum confirmed borrow quantities for one account/symbol while a balance
 * snapshot is catching up.  Duplicate websocket updates with the same id are
 * ignored; terminal positions never become a debt estimate.
 */
export function positionBorrowQuantity(
  positions: readonly BorrowPositionLike[],
  accountId: number,
  symbol: string,
): number {
  const wanted = String(symbol).toUpperCase()
  const seen = new Set<string>()
  return positions.reduce((sum, position) => {
    if (Number(position.sub_account_id) !== Number(accountId)) return sum
    if (String(position.symbol || '').toUpperCase() !== wanted) return sum
    const status = String(position.status || '').toUpperCase()
    // A row is created before Binance confirms the borrow.  Only lifecycle
    // states with a confirmed exchange borrow may be used as a debt fallback;
    // unknown/new states fail closed instead of manufacturing a holding.
    if (!CONFIRMED_BORROW_STATUSES.has(status)) return sum
    if (position.id != null && String(position.id) !== '') {
      const key = String(position.id)
      if (seen.has(key)) return sum
      seen.add(key)
    }
    return sum + nonNegative(position.borrow_qty)
  }, 0)
}

/**
 * Return the debt shown by a dashboard row.  A present, non-placeholder
 * balance snapshot is authoritative, including an explicit zero, unless that
 * zero was observed before a newer confirmed position update.  Balance and
 * position updates use separate websocket channels, so delivery order alone
 * cannot establish which value is newer.  The BalancePusher placeholder is
 * also all-zero and always permits the position fallback.
 */
export function debtWithPositionFallback(
  snapshot: MarginDebtSnapshot | null | undefined,
  positions: readonly BorrowPositionLike[],
  accountId: number,
  symbol: string,
): DebtDisplay {
  const snapshotDebt = snapshot != null ? debtBreakdown(snapshot) : null
  const principal = positionBorrowQuantity(positions, accountId, symbol)
  const isPlaceholder = snapshot?.snapshot_placeholder === true
  const snapshotAt = observedAtMs(snapshot?.snapshot_at_ms)
  const positionAt = latestPositionUpdateMs(positions, accountId, symbol)
  const staleZeroSnapshot = snapshotDebt != null
    && snapshotDebt.total <= 1e-8
    && principal > 1e-8
    && positionAt != null
    && (snapshotAt == null || snapshotAt <= positionAt)
  if (snapshotDebt != null && !isPlaceholder && !staleZeroSnapshot) {
    return { ...snapshotDebt, hasSnapshot: true, source: 'balance' }
  }
  if (principal > 1e-8) {
    return { principal, interest: 0, total: principal, hasSnapshot: false, source: 'position' }
  }
  return { principal: 0, interest: 0, total: 0, hasSnapshot: false, source: 'none' }
}

/**
 * Return sub-account ids in creation/addition order.
 *
 * The API already returns accounts in this order, but keeping the comparison
 * here makes every dashboard entry point resilient to an out-of-order response
 * (for example after a reconnect).  ``id`` is only a deterministic tie-breaker
 * for rows created in the same database timestamp.
 */
export interface AccountCreationRecord {
  id: number
  created_at?: string | Date | null
}

function creationTimestamp(value: string | Date | null | undefined): number | null {
  if (value == null || value === '') return null
  const parsed = value instanceof Date ? value.getTime() : Date.parse(String(value))
  return Number.isFinite(parsed) ? parsed : null
}

export function accountIdsInCreationOrder(
  accounts: readonly AccountCreationRecord[],
): number[] {
  return accounts
    .map((account, index) => ({
      id: account.id,
      index,
      created: creationTimestamp(account.created_at),
    }))
    .sort((left, right) => {
      // Missing/invalid timestamps retain their API order after known rows.
      if (left.created == null && right.created != null) return 1
      if (left.created != null && right.created == null) return -1
      if (left.created != null && right.created != null && left.created !== right.created) {
        return left.created - right.created
      }
      // Creation timestamps are the source of truth.  When two rows share
      // the same timestamp, use the account id as a deterministic tie-break
      // so a reconnect/API response order cannot reshuffle their slots.
      if (left.created != null && right.created != null) {
        return left.id - right.id || left.index - right.index
      }
      // For rows without a usable timestamp there is no reliable chronology;
      // retain the server/input order instead of treating ids as creation
      // order.
      return left.index - right.index
    })
    .map((account) => account.id)
}

export function accountIdsFromBalanceOrder(
  balances: readonly {
    account_id: number
    account_created_at?: string | Date | null
  }[],
): number[] {
  return accountIdsInCreationOrder(balances.map((balance) => ({
    id: balance.account_id,
    created_at: balance.account_created_at,
  })))
}

function nonNegative(value: unknown): number {
  const parsed = Number(value)
  return Number.isFinite(parsed) && parsed > 0 ? parsed : 0
}

export function debtBreakdown(snapshot?: MarginDebtSnapshot): DebtBreakdown {
  const principal = nonNegative(snapshot?.borrowed)
  const interest = nonNegative(snapshot?.interest)
  return { principal, interest, total: principal + interest }
}

export function displayedBorrowableQuantity(
  snapshot?: MarginDebtSnapshot,
): BorrowableQuantity | null {
  if (!snapshot) return null

  // New payloads provide an explicit next-bite value.  Prefer it even when
  // zero: a zero next bite can mean the cumulative cap is exhausted while
  // Binance's raw inventory is still positive.
  if (snapshot.next_borrowable != null) {
    const parsed = Number(snapshot.next_borrowable)
    if (Number.isFinite(parsed) && parsed >= 0) {
      return { quantity: nonNegative(parsed), source: 'effective_borrowable' }
    }
  }

  const candidates: Array<[BorrowableQuantitySource, unknown]> = [
    ['max_borrowable', snapshot.max_borrowable],
    ['effective_borrowable', snapshot.effective_borrowable],
  ]
  // Preserve an explicit zero.  It means the account currently has no
  // executable capacity (often Binance -3045/no inventory), not "unknown".
  for (const [source, rawValue] of candidates) {
    if (rawValue == null) continue
    const parsed = Number(rawValue)
    if (Number.isFinite(parsed) && parsed >= 0) {
      return { quantity: nonNegative(parsed), source }
    }
  }
  return null
}

export function maxBorrowableUsdt(
  snapshot: MarginDebtSnapshot | undefined,
  spotPrice: number | undefined,
): number | null {
  // Kept for existing callers.  ``displayedBorrowableQuantity`` now prefers
  // the explicit next-bite field, so this legacy name returns the next
  // executable request value rather than a cumulative account cap.
  const borrowable = displayedBorrowableQuantity(snapshot)
  if (!borrowable) return null
  const price = Number(spotPrice)
  if (!Number.isFinite(price) || price <= 0) return null
  return borrowable.quantity * price
}

export function sortByAccountOrder<T>(
  rows: readonly T[],
  accountOrder: readonly number[],
  accountIdOf: (row: T) => number,
): T[] {
  const rank = new Map(accountOrder.map((accountId, index) => [accountId, index]))
  return rows.map((row, index) => ({ row, index })).sort((left, right) => {
    const leftId = accountIdOf(left.row)
    const rightId = accountIdOf(right.row)
    const leftRank = rank.get(leftId) ?? Number.MAX_SAFE_INTEGER
    const rightRank = rank.get(rightId) ?? Number.MAX_SAFE_INTEGER
    // Unknown accounts retain their source order.  Numeric id is not a proxy
    // for creation order (accounts can be deleted/recreated), so do not use it
    // as the primary fallback here.
    return leftRank - rightRank || left.index - right.index
  }).map(({ row }) => row)
}

// A position row is created before Binance confirms a borrow.  Those
// pre-submit/ambiguous rows must not inflate the dashboard's held-symbol
// count; the balance snapshot remains the authoritative source when it is
// available.  Keep this list explicit so a new lifecycle state fails closed
// for the display rather than being mistaken for exchange debt.
const CONFIRMED_BORROW_STATUSES = new Set([
  'BORROWED',
  'BORROWED_IDLE',
  'HEDGING',
  'SPOT_SOLD',
  'OPEN',
  'CLOSING',
  'CLOSING_FUTURES',
  'FUTURES_CLOSED',
  'CLOSING_SPOT',
  'SPOT_BOUGHT',
  'PENDING_REPAY',
  'REPAYING',
])

/** Return symbols with a confirmed, positive borrow principal. */
export function confirmedBorrowedSymbols(
  positions: readonly Pick<BorrowPositionLike, 'symbol' | 'borrow_qty' | 'status'>[],
): string[] {
  const symbols = new Set<string>()
  for (const position of positions) {
    const status = String(position.status || '').toUpperCase().trim()
    const quantity = nonNegative(position.borrow_qty)
    if (!CONFIRMED_BORROW_STATUSES.has(status) || quantity <= 1e-8) continue
    const symbol = String(position.symbol || '').toUpperCase().trim()
    if (symbol) symbols.add(symbol)
  }
  return [...symbols]
}

export function heldSymbolCount(
  balances: readonly { symbol_margin?: Record<string, MarginDebtSnapshot> }[],
  activeSymbols: readonly string[] = [],
  activePositions: readonly BorrowPositionLike[] = [],
): number {
  const symbols = new Set<string>()
  const balanceByAccount = new Map<number, { symbol_margin?: Record<string, MarginDebtSnapshot> }>()
  const authoritativeSymbols = new Set<string>()
  for (const balance of balances) {
    // ``account_id`` is optional in the small/legacy test shape, so only use
    // this map when a numeric account id is available.  The symbol-level set
    // below still protects the backwards-compatible string fallback.
    const accountId = Number((balance as { account_id?: unknown }).account_id)
    if (Number.isFinite(accountId)) balanceByAccount.set(accountId, balance)
    for (const [symbol, snapshot] of Object.entries(balance.symbol_margin || {})) {
      const normalized = String(symbol).toUpperCase()
      if (snapshot?.snapshot_placeholder !== true) authoritativeSymbols.add(normalized)
      // "持仓" is a trading/debt count. Free-only leftovers are shown in the
      // holdings modal's residual section, but must not turn an exchange-flat
      // dashboard into "持仓 N 币种". Debt remains authoritative even if a
      // stale producer accidentally leaves the residual-only hint set.
      if (debtBreakdown(snapshot).total > 1e-8) {
        symbols.add(normalized)
      }
    }
  }

  // A position event can beat the next balance snapshot.  Use the position as
  // a temporary fallback only when its account has no authoritative row yet
  // (or only has BalancePusher's explicit placeholder).  An authoritative
  // zero snapshot therefore removes a stale position from the count instead
  // of reviving the old ``posCount`` behaviour.
  for (const position of activePositions) {
    const status = String(position.status || '').toUpperCase().trim()
    const quantity = nonNegative(position.borrow_qty)
    if (!CONFIRMED_BORROW_STATUSES.has(status) || quantity <= 1e-8) continue
    const symbol = String(position.symbol || '').toUpperCase().trim()
    if (!symbol) continue
    const balance = balanceByAccount.get(Number(position.sub_account_id))
    const snapshot = marginSnapshotForSymbol(balance?.symbol_margin, symbol)
    const debt = debtWithPositionFallback(
      snapshot,
      activePositions,
      Number(position.sub_account_id),
      symbol,
    )
    if (debt.total > 1e-8) symbols.add(symbol)
  }

  // Preserve the original string-only API for callers that do not have
  // account ids.  Once a real (non-placeholder) row exists for a symbol, its
  // zero is authoritative and the legacy fallback must not re-add it.
  for (const symbol of activeSymbols) {
    const normalized = String(symbol || '').toUpperCase().trim()
    if (normalized && !authoritativeSymbols.has(normalized)) symbols.add(normalized)
  }
  return symbols.size
}

/** VIP tier ceiling converted to USDT; informational, not executable stock. */
export function borrowLimitUsdt(
  snapshot: MarginDebtSnapshot | undefined,
  spotPrice: number | undefined,
): number | null {
  if (snapshot?.borrow_limit == null) return null
  const limit = Number(snapshot.borrow_limit)
  const price = Number(spotPrice)
  if (!Number.isFinite(limit) || limit < 0 || !Number.isFinite(price) || price <= 0) return null
  return limit * price
}
