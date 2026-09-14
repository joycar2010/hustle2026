import client from './client'

export interface RulePreset {
  id: number
  name: string
  open_spread: string | null
  close_spread: string | null
  order_amount: string | null
  remove_spread: string | null
  close_funding_ratio: string | null
  repay_funding_ratio: string | null
  repay_spread: string | null
  max_daily_interest_rate: string | null
  max_borrow_amount: string | null
  created_at: string
}

export async function listPresets(): Promise<RulePreset[]> {
  const { data } = await client.get('/api/rule-presets/')
  return data
}

export async function createPreset(payload: Record<string, unknown>): Promise<RulePreset> {
  const { data } = await client.post('/api/rule-presets/', payload)
  return data
}

export async function updatePreset(id: number, payload: Record<string, unknown>): Promise<RulePreset> {
  const { data } = await client.put(`/api/rule-presets/${id}`, payload)
  return data
}

export async function deletePreset(id: number): Promise<void> {
  await client.delete(`/api/rule-presets/${id}`)
}

export async function applyPreset(presetId: number, symbol: string): Promise<void> {
  await client.post(`/api/rule-presets/${presetId}/apply/${symbol}`)
}
