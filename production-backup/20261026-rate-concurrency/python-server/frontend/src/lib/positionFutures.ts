const CLOSED_FUTURES_STATUSES = new Set([
  'FUTURES_CLOSED', 'PENDING_REPAY', 'REPAYING', 'CLOSED',
])

// The executor confirms the futures leg is flat before these states. Historical
// futures_long_qty remains in the ledger for PNL/audit; it is not current exposure.
export function hasClosedFutures(status: string): boolean {
  return CLOSED_FUTURES_STATUSES.has(status)
}

export function currentFuturesQty(
  position: { status: string; futures_long_qty?: string },
  masterQty = 0,
): number {
  // A shared master position may belong to a different subaccount. Never use it
  // to refill a closed row. Keep the existing fallback for open/in-flight rows.
  if (hasClosedFutures(position.status)) return 0
  return masterQty !== 0 ? Math.abs(masterQty) : parseFloat(position.futures_long_qty || '0')
}
