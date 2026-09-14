import client from './client'

export interface Coin {
  id: number
  symbol: string
  base_asset: string
  quote_asset: string
  margin_tradable: boolean
  futures_tradable: boolean
  is_active: boolean
  is_new_coin: boolean
  is_delisting: boolean
  allow_open: boolean
  is_risky: boolean
  volume_24h: string | null
}

export async function getCoins(params?: Record<string, string>): Promise<Coin[]> {
  const { data } = await client.get('/api/coins/', { params })
  return data
}

export async function markNewCoin(symbol: string) {
  const { data } = await client.post(`/api/coins/${symbol}/mark-new`)
  return data
}

export async function markDelisting(symbol: string) {
  const { data } = await client.post(`/api/coins/${symbol}/mark-delisting`)
  return data
}

export async function patchCoin(symbol: string, body: Record<string, unknown>) {
  const { data } = await client.patch(`/api/coins/${symbol}`, body)
  return data
}

export async function syncVolume() {
  const { data } = await client.post('/api/coins/sync-volume')
  return data
}
