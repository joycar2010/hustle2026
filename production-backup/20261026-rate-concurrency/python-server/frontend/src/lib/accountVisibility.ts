export interface AccountEnabledRecord {
  is_enabled?: boolean
}

/** Legacy balance payloads omitted the flag and represented enabled accounts. */
export function isAccountTradingEnabled(account: AccountEnabledRecord): boolean {
  return account.is_enabled !== false
}
