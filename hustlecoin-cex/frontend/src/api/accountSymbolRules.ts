import client from './client'

export interface AccountSymbolRule {
  id: number
  sub_account_id: number
  symbol: string
  open_spread: string | null
  close_spread: string | null
  order_amount: string | null
  remove_spread: string | null
  close_funding_ratio: string | null
  repay_funding_ratio: string | null
  max_daily_interest_rate: string | null
  repay_spread: string | null
  max_borrow_amount: string | null
  is_enabled: boolean
  created_at: string
  updated_at: string
}

export async function getAccountSymbolRules(subAccountId: number): Promise<AccountSymbolRule[]> {
  const { data } = await client.get(`/api/account-symbol-rules/${subAccountId}`)
  return data
}

export async function getAccountSymbolRule(subAccountId: number, symbol: string): Promise<AccountSymbolRule> {
  const { data } = await client.get(`/api/account-symbol-rules/${subAccountId}/${symbol}`)
  return data
}

export async function upsertAccountSymbolRule(
  subAccountId: number,
  symbol: string,
  body: Record<string, unknown>,
): Promise<AccountSymbolRule> {
  const { data } = await client.put(`/api/account-symbol-rules/${subAccountId}/${symbol}`, body)
  return data
}

export async function deleteAccountSymbolRule(subAccountId: number, symbol: string) {
  const { data } = await client.delete(`/api/account-symbol-rules/${subAccountId}/${symbol}`)
  return data
}

export async function resetAccountSymbolRule(subAccountId: number, symbol: string) {
  const { data } = await client.post(`/api/account-symbol-rules/${subAccountId}/${symbol}/reset`)
  return data
}

export async function batchUpdateAccountSymbolRules(
  items: Array<{ sub_account_id: number; symbol: string; data: Record<string, unknown> }>,
) {
  const { data } = await client.post('/api/account-symbol-rules/batch', { items })
  return data
}
